# Full-KV-Replication Baseline for RADP — Design Spec

**Date:** 2026-07-22
**Status:** approved (brainstorming) → ready for writing-plans

## Goal

Add a **full KV replication** recovery baseline (DejaVu / KevlarFlow lineage) so
parity recovery is compared not only against the recompute family
(full-replay, surgical) but against the *other* zero-recompute strategy —
storing every stage's KV verbatim instead of XOR-folding it into one blob. Also
place **cold-restart** on the same fleet TTR(P) graph as a single worst-case
anchor point.

## Key insight that shapes the whole design

Replication and parity share the **same recovery mechanism** (reload, zero
recompute), so their TTR is similar — replication may even be slightly faster
at recovery (it moves one stored copy; parity fetches N−1 survivor KVs and XORs
them). **Parity does not win on TTR against replication.** Parity wins on
**steady-state storage**: one XOR blob (max stage) vs N full copies (Σ stages).

Therefore the result is **not** a 1-D TTR line but a **2-D Pareto** (TTR ×
steady-state storage). Only parity sits in the low-TTR ∧ low-storage corner:
full-replay/surgical have zero storage but TTR grows with failure position P;
replication has low TTR but N× storage.

This reproduces, in our edge regime, the erasure-coding-vs-replication
comparison GhostServe already made (8:2 erasure coding cuts overhead 75% vs
full replication). Our contribution here is the transplant + measurement, not
the comparison itself.

### Where parity wins, tied, loses (state all three — honesty gate)

| Axis | Winner |
|---|---|
| TTR / recovery-time data movement | replication (slightly) |
| Steady-state upload network (worker→coord KV columns) | tie — both ship the same columns |
| **Steady-state storage bytes** | **parity** (max vs Σ; ~2.25× on our placement) |
| **Storage scaling in stage count N** | **parity** — O(1) vs O(N) |
| Recovery coverage under fixed memory budget | parity (deferred to backlog) |

The paper must state the replication-wins-TTR fact plainly, not hide it.

## Scope

**In scope:**
- `recovery_mode="replicate"` end to end (cache, gateway recovery path, config).
- Fleet TTR(P) sweep line for replicate (P=4,8,16,24,32), alongside parity.
- Cold-restart as a **single** fleet point at P=32 (not a swept line).
- Storage-overhead computation (Σ vs max) → 2-D Pareto axis + O(N) scaling curve.
- In-process tests (correctness + bit-identical + fallback + measurement gate).
- `run_radp_replicate` line in `b1_ft_baselines.py` (in-process comparison).

**Out of scope (backlog):**
- Recovery coverage under a fixed memory budget (needs concurrent-load test).
- KV-shipping steady-state throughput impact (existing backlog).
- Peer-to-peer (ring) replication à la KevlarFlow — we deliberately store at the
  coordinator, identical to parity, so storage location is not a confound.

## Architecture

`recovery_mode` gains a fourth value `"replicate"`, a sibling of `"parity"` with
the XOR removed.

```
Steady state:  worker ships KV column via MirrorKV  (IDENTICAL to parity;
               the worker does not know which mode it is in)
   coordinator:  parity   → parity_cache.xor_in(...)        (fold into one blob)
                 replicate → replica_cache.store(...)       (keep each verbatim)

Recovery:      parity    → fetch N−1 survivors + XOR-reconstruct + install
               replicate → get stored dead-stage KV + install   (no fetch, no XOR)
```

Recovery's 5 steps (see REPORT §B1-PARITY): ② backup promote and ⑤ live failed
position are shared by all modes. Replicate differs from parity only in ①③④:

| Step | parity | replicate |
|---|---|---|
| ① fetch survivor KV | N−1 × FetchKV | **skipped** |
| ③ obtain dead KV | XOR reconstruct | **read stored copy** (get_stage_kv) |
| ④ install to backup | LoadKV | LoadKV (identical) |

**Layout:** replicate reuses parity's final transpose. Workers ship SLOT-major
columns; `install_kv` expects LAYER-major. Rather than reshaping on ingest,
replicate stores columns as received and converts **just before install**,
reusing the transpose logic at the tail of `_xor_reconstruct_kv` (extracted to a
shared helper so both paths call it).

## Components

### `radp/coordinator/replica_cache.py` (new)

Sibling of `ParityCache`, same signatures where they overlap. The one structural
difference is the key layout: parity keys by position only (`{position: blob}`,
one blob); replicate keys by stage then position (`{stage_key: {position:
bytes}}`, one buffer per stage). Hence `get_stage_kv` exists here and not in
parity.

```python
class ReplicaCache:
    def __init__(self, num_stages: int, max_bytes: int = 256 * 1024 * 1024) -> None
    def store(self, request_id, stage_key, position, column_bytes) -> None
        # self._by_request[rid][stage_key][position] = bytes
        # dedup: re-arriving (stage_key, position) is ignored (idempotent)
        # bytes accounting mirrors ParityCache
    def get_stage_kv(self, request_id, stage_key) -> bytes | None
        # concatenate positions 0..N of stage_key in order → SLOT-major bytes,
        # or None if the stage was never stored (→ caller falls back)
    def is_complete(self, request_id, stage_key, up_to_position) -> bool
        # True iff positions 0..up_to_position are all present (no hole)
    def evict_request(self, request_id) -> None
    def _evict_if_needed_locked(self) -> None
        # LRU by request; `len(self._by_request) > 1` guard identical to parity
```

### `radp/coordinator/gateway.py` (modify)

- `recovery_mode` validation set gains `"replicate"`.
- `_recover_replicate(self, request_id, head_stage, error, current_position)`
  — clone of `_recover_parity` with steps ① and ③ replaced:
  - attribute dead stage; head → defer to surgical (unchanged);
  - `replica_cache.is_complete(...)` false → fall back to surgical (which ladders
    to full-replay). Never emit a wrong token.
  - `dead_kv_slot_major = replica_cache.get_stage_kv(request_id, dead_key)`;
    None → fallback.
  - convert SLOT-major → LAYER-major via the shared transpose helper.
  - promote backup, rewire, `LoadKV`, run failed position live (identical tail).
  - log `"REPLICATE reconstruct: backup %s stage[%d..%d] ..."` so the measurement
    driver can confirm the replicate branch ran (not a silent surgical fallback).
- `record_kv` dispatch: `if mode == "replicate": replica_cache.store(...)`.
- Extract the SLOT↔LAYER transpose tail of `_xor_reconstruct_kv` into a shared
  `_slot_major_to_layer_major(...)` used by both parity and replicate.

### `experiments/_harness.py` (or new util) — overhead computation

```python
def replication_overhead(placement, n_heads, head_dim, itemsize) -> dict:
    # per non-head stage: layers × 2 × n_heads × head_dim × itemsize
    # returns {"replicate_bytes": sum, "parity_bytes": max, "ratio": sum/max,
    #          "per_stage": [(stage_key, bytes), ...]}
```

Deterministic (no measurement). Feeds the 2-D Pareto y-axis and the O(N) scaling
curve.

## Measurement

### Fleet driver — `experiments/b1_ft_fleet.py` (extend)

- `modes` gains `"replicate"` → full P sweep (4,8,16,24,32) beside parity.
- `"cold_restart"` measured at **P=32 only** (single anchor). Rationale: its
  fleet TTR is dominated by ansible/systemd restart + model reload — a property
  of our deployment tooling, not the recovery algorithm — so it is a worst-case
  anchor, not a clean swept line.
- `set_worker_replication(on)` reuses the same worker env as parity (the worker
  ships columns regardless of coordinator storage mode).
- `set_recovery_mode` passes `"replicate"` through (already a string arg).
- Measurement-integrity gates reused: `recovery_visible`, `sequence_match`, plus
  a replicate-specific log check `"REPLICATE reconstruct:"` (mirror of parity's
  `parity_branch_ran`) to exclude surgical-fallback mislabeling.
- Output: `b1_ft_fleet_replicate.json`; overhead `b1_ft_overhead.json` (computed).

### In-process driver — `experiments/b1_ft_baselines.py` (extend)

Add `run_radp_replicate` (recovery_mode="replicate") beside the existing
surgical / full-replay / cold-restart / abort lines, so the in-process
comparison table is complete even without the fleet.

### Figures

1. **`fig_recovery_2d`** (new, headline) — 2-D Pareto. x = **TTR at P=32**
   (the worst measured position — the axis where recompute methods are most
   punished; state the choice in the caption), y = steady-state storage bytes.
   Four points: full-replay (0 storage, high TTR), surgical (0 storage, mid
   TTR), replicate (N× storage, low TTR), parity (1-blob storage, low TTR).
   Parity alone in the low-low corner. Deck palette; English labels (per
   DESIGN_SYSTEM §7.3).
2. **`fig_storage_scaling`** (new) — x = stage count, y = storage bytes.
   replicate O(N) rising line, parity O(1) flat. Computed, not measured. State
   in the caption that it is derived from placement, not benchmarked.
3. Add a `replicate` line to `fig_recovery_ttr_slide` — overlapping parity or
   slightly below it. Do not hide the tie/loss.

## Testing

### `tests/test_replicate_recovery.py` (new)

- `test_replica_cache_store_get` — store N columns → `get_stage_kv` returns them
  concatenated in position order; re-store is deduped.
- `test_replica_cache_incomplete_returns_none` — a hole → `is_complete` False,
  and the recovery path falls back.
- `test_replicate_recovery_matches_reference` — in-process crash inject →
  replicate recovery → output equals the wired healthy reference **and** the
  reconstructed backup KV is **bit-identical** to the victim's, per layer K & V
  (replicate loads the stored bytes, so bit-exactness is structural, same
  strength as parity).
- `test_replicate_falls_back_when_incomplete` — store incomplete → surgical
  fallback, output still matches reference.
- `test_replicate_branch_ran_logged` — `"REPLICATE reconstruct:"` present when
  the true replicate branch runs (measurement-gate reliability).
- `test_replica_cache_evict_keeps_sole_request` — `len>1` LRU guard identical to
  parity.
- `test_replication_overhead` — Σ vs max correct on a known placement
  (2+2+4+1 = 9 layers vs max 4 → ratio 2.25).

### Correctness note

The bit-identical assertion applies to replicate as it does to parity, and
**not** to surgical/full-replay: replicate reloads stored bytes rather than
recomputing, so like parity it is bit-exact by construction. This is the line
that separates the recompute family (surgical/full-replay) from the storage
family (parity/replicate) on the numerical-reproducibility axis (REPORT §B1).

## Files

- Create: `radp/coordinator/replica_cache.py`, `tests/test_replicate_recovery.py`,
  `paper/figures/make_recovery_2d.py`, `paper/figures/make_storage_scaling.py`
- Modify: `radp/coordinator/gateway.py` (recovery_mode set, `_recover_replicate`,
  `record_kv` dispatch, extract `_slot_major_to_layer_major`),
  `experiments/b1_ft_fleet.py` (replicate sweep + cold-restart anchor +
  `set_worker_replication` + log gate), `experiments/b1_ft_baselines.py`
  (`run_radp_replicate`), `experiments/_harness.py` (`replication_overhead`),
  `paper/figures/make_recovery_ttr_slide.py` (add replicate line)
- Generated pb2 stubs unchanged — replicate reuses MirrorKV/FetchKV/LoadKV, no
  new proto.

## Global constraints (from the repo)

- Generated `*_pb2.py` are gitignored — do not commit them.
- Recovery correctness must never depend on replicate: fallback ladder
  (replicate → surgical → full-replay) preserved; a wrong token is never emitted.
- Measurement integrity: a mode's TTR is published only when its own branch log
  confirms it ran (no surgical-fallback mislabeled as replicate).
- Figures follow DESIGN_SYSTEM §7: slide scale, deck palette, English in-figure
  text, anchor text to shapes.
- Only cite what a paper states (GhostServe facts from paper/refs/PAPERS.md).
