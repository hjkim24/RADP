# FT overhead + fidelity metrics — design

**Status:** approved design (brainstorm 2026-07-30)

## Goal

Add two FT evaluation axes beyond the current two (TTR × steady-state storage):

- **① Steady-state network overhead** — the always-on bandwidth of shipping KV
  to the coordinator during normal decode. The "premium" side of the tradeoff;
  completes the cost picture the 2-D Pareto only half-shows (it shows storage,
  not bandwidth).
- **② Recovery fidelity** — whether recovered KV is bit-identical to the
  original. `parity`/`replicate` restore stored bytes (exact by construction);
  `surgical`/`full-replay`/`reactive` recompute, which *may* diverge on
  heterogeneous tiers. Probe-first: measure the actual cross-tier divergence and
  report whatever is true — a strong differentiator if recompute drifts, an
  honest "all bit-exact" if it doesn't.

Both are new *evaluation metrics*, not new recovery mechanisms. The five
recovery families (full-replay, surgical, parity, replicate, reactive) are
unchanged.

## Background

- Current metrics live in `experiments/_harness.py:replication_overhead(placement, n_heads, head_dim, itemsize)`
  (storage only: `replicate_bytes`=Σ non-head stage KV, `parity_bytes`=max non-head
  stage KV) and the fleet TTR sweeps (`b1_ft_fleet_*.json`).
- Per-stage KV column (one position, one stage) = `n_layers × 2 × n_heads × head_dim × itemsize`.
  For OPT-350M (`n_heads=16, head_dim=64 → hidden_dim=1024`, fp16 `itemsize=2`):
  KV column = `n_layers × 4096 B`. Measured deployed placement:
  `parity_bytes=16384` (max, 4-layer stage), `replicate_bytes=36864` (Σ), ratio 2.25.
- Bit-fidelity of `parity`/`replicate` is already asserted in-process via
  `torch.equal` (`tests/test_parity_recovery.py:65-66`, `tests/test_replicate_recovery.py:265-268`).
- Fleet decode rate for bandwidth conversion: median TBT = 163.3 ms
  (`b1_ft_fleet_parity.json`), ≈ 6.12 decode steps/s.

The two components are independent; they share only the fleet and the model
geometry. They become separate tasks in the implementation plan.

---

## Component ① — steady-state network overhead

### What it measures

Per-family bytes shipped worker→coordinator per decode step during **normal
operation** (no failure), and the resulting bandwidth given the measured decode
rate. Two shipment kinds, verified against the worker code:

- **input mirror** (activation push, `submit_mirror`): gated ONLY on
  `self._mirror is not None` + non-head (`start_layer > 1`) + `not replay_only`
  (`radp/worker/server.py:438-451`). **NOT recovery-mode-gated → always-on for
  every family.** It is the shared chain-recovery substrate. Size per non-head
  stage per step = `hidden_dim × itemsize` (the current position's input
  hidden-state vector; fp16 → 2048 B).
- **KV column** (MirrorKV push, `_maybe_push_parity_kv`): gated on `RADP_PARITY`
  (`radp/worker/server.py:473-484`) + non-head + not-replay. **Only parity and
  replicate ship it.** Size per non-head stage per step = the KV column
  (`n_layers × 2 × n_heads × head_dim × itemsize`, i.e. 4096 B/layer fp16) — the
  same per-stage bytes `replication_overhead` already computes.

| family | per-step shipping | components |
|---|---|---|
| full-replay | Σ(hidden_dim × itemsize) | input mirror only (always-on; full-replay's own recovery doesn't use it) |
| reactive | Σ(hidden_dim × itemsize) | input mirror only (always-on; reactive re-solves, doesn't use it) |
| surgical | Σ(hidden_dim × itemsize) | input mirror (surgical's substrate) |
| parity | Σ(hidden_dim × itemsize) + Σ(KV column) | mirror + KV column (RADP_PARITY) |
| replicate | Σ(hidden_dim × itemsize) + Σ(KV column) | mirror + KV column (RADP_PARITY) |

Key facts this must encode:
- **parity and replicate ship the SAME bytes** (both mirror + Σ KV columns).
  They differ only in what the coordinator *keeps* (XOR-to-max vs store-Σ). So
  network is NOT a parity-vs-replicate differentiator — storage still is. Output
  must make this visible (equal shipping, unequal storage).
- **The input mirror is an always-on baseline** paid by all five families — the
  KV column is the *delta* parity/replicate pay on top. surgical/full-replay/
  reactive ship only the mirror; parity/replicate ship mirror + KV column.
- **full-replay and reactive pay the mirror without using it** (their recovery
  re-forwards from tokens / re-solves). That is a latent optimization — the
  mirror could be gated off for non-surgical modes — and a finding worth stating,
  not hiding.
- **KV column ≫ mirror per stage** once a stage holds >1 layer (16384 vs 2048
  for a 4-layer stage), so parity/replicate's total is several× the mirror-only
  modes'.

### Interface

New function in `experiments/_harness.py` (sibling to `replication_overhead`,
keeps storage vs network separate):

```
shipping_overhead(placement, n_heads, head_dim, itemsize) -> dict
  returns {
    "input_mirror_bytes_per_step": <Σ hidden_dim·itemsize over non-head stages>,  # all families
    "kv_column_bytes_per_step":    <Σ KV column over non-head stages>,            # parity/replicate only
    "shipping_bytes_per_step": {
        "full_replay": <mirror>, "reactive": <mirror>, "surgical": <mirror>,
        "parity":    <mirror + kv>,   # == replicate
        "replicate": <mirror + kv>,
    },
    "per_stage_kv": [...],       # reuse replication_overhead per_stage
    "per_stage_mirror": [...],   # hidden_dim·itemsize per non-head stage
  }
```

Bandwidth conversion is done by the overhead generator (not the pure function),
reading `median_tbt_seconds` from `b1_ft_fleet_parity.json`:
`bandwidth_bytes_per_s[family] = shipping_bytes_per_step[family] / median_tbt`.

`hidden_dim` for the mirror term = `n_heads × head_dim` (the model's residual
width). Both the mirror set and the KV-column set = the non-head stages
(`start_layer > 1`), matching the two worker gates above.

### Output

Extend `b1_ft_overhead.json` with `shipping_bytes_per_step` and
`bandwidth_bytes_per_s` (keep existing storage fields). Whatever step currently
writes that file (controller-run — `make_recovery_2d.py` only reads it) adds the
two fields; if no committed generator exists, add a small
`experiments/gen_overhead.py` that computes both storage and shipping for the
deployed placement and writes the JSON.

Illustrative (deployed placement = 4 non-head stages, 6.12 steps/s): mirror ≈
4 × 2048 = 8192 B/step (≈ 50 KB/s) paid by all; KV column ≈ 36864 B/step; so
parity = replicate ≈ 45056 B/step (≈ 276 KB/s), surgical = full-replay =
reactive ≈ 8192 B/step (≈ 50 KB/s). (Numbers land from the generator — do not
hard-code.)

### Testing

Pure arithmetic → unit tests on invariants:
- `shipping["parity"] == shipping["replicate"]` (mirror + same KV columns)
- `shipping["surgical"] == shipping["full_replay"] == shipping["reactive"] == input_mirror_bytes_per_step`
  (mirror-only; NOT zero — the mirror is always-on)
- `shipping["parity"] - shipping["surgical"] == kv_column_bytes_per_step` (KV is the delta)
- `kv_column_bytes_per_step == replication_overhead(...)["replicate_bytes"]` (same Σ)

---

## Component ② — recovery fidelity probe (probe-first)

### The question

Does recomputing a stage's KV on a **different tier** than the original produce
bit-identical KV? In-process tests can't answer this (single device). The answer
decides whether ② is a differentiator (recompute drifts) or a verification
(all exact).

### The probe

Standalone `experiments/probe_recompute_fidelity.py`, run per-tier via ansible,
deliberately NOT using the fault harness (isolate the phenomenon):

1. **Fixed input, generated once.** Seed a hidden-state tensor `[1, S, hidden_dim]`
   on CPU with a fixed seed, save its raw bytes to a file. Ship the SAME file to
   each board so every tier forwards byte-identical input (device RNG differs, so
   the input must be generated once and copied, never re-seeded per board).
2. **Fixed stage.** Load a fixed small layer range of OPT-350M (e.g. 2 layers)
   onto the board's own device at the board's RADP runtime dtype (fp16 CUDA on
   AGX/Nano, whatever CPU boards use) — so the divergence reflects real recovery,
   not an artificial config. Reuse the worker's stage-forward path
   (`radp.worker` StageRunner / layer forward) so the KV is computed exactly as
   recovery would compute it.
3. **Extract + hash.** Run the forward, take the resulting K and V tensors in a
   canonical layout, dump the raw bytes to a file, and print a sha256 hash + shape/dtype.
4. **Compare across tiers.** Controller collects the per-board dumps and compares:
   - hashes equal → bit-identical on those tiers;
   - hashes differ → divergence; then quantify from the dumped tensors
     (fraction of mismatched elements, max abs diff) and optionally whether the
     divergence flips a downstream token.

Tier pairs, in priority order: **CUDA(on-1) ↔ CPU(on-3)** (most likely to
diverge — different kernels), then AGX(ao-1) ↔ Nano(on-1), AGX ↔ CPU. Start with
the first pair; expand only if it diverges.

### From probe result → per-family fidelity

| family | fidelity |
|---|---|
| parity / replicate | **bit-exact by construction** (restore stored bytes; already `torch.equal`-asserted in-process). Tier-independent. |
| surgical / full-replay / reactive | recompute → inherit the probe result. Diverges → "cross-tier recovery differs from original bit-for-bit (token-flip: measured separately)". Bit-identical → "recompute also bit-exact (measured)". |

### Output

`experiments/results/b1_ft_fidelity.json`: per tier-pair hash-equality + (if
divergent) magnitude, plus the per-family fidelity verdict derived from it.

### Testing

- The comparison/quantify logic (hash equality, fraction-mismatched, max-abs-diff)
  is unit-testable on synthetic tensor pairs (identical → exact; perturbed → the
  expected magnitude).
- The board-side forward is a live-fleet step, not unit-tested; its correctness
  is the input-determinism guarantee (same input bytes) + reusing the worker's
  own forward path.

---

## Component ③ — deliverables (both)

- **① figure/table:** a steady-state overhead table (family × storage bytes ×
  shipping B/step × bandwidth). Whether to add network as a third axis/panel to
  the 2-D Pareto or a standalone bar is decided **after** the numbers land (don't
  pre-commit a figure form).
- **② result:** if the probe diverges, a fidelity column added to the recovery
  comparison + a short "correctness axis" write-up; if it's bit-identical, an
  honest "all five families bit-exact (recompute verified tier-invariant on this
  stack)" note. No figure unless the divergence has structure worth plotting.
- **Docs:** REPORT `§B1-OVERHEAD` (①) and `§B1-FIDELITY` (②) + `§11` findings;
  `PHASES.md` Phase entries; brain-wiki `topics/radp-fault-tolerance` update
  (metrics section).

## Out of scope / honest limits

- No new recovery mechanism, no gateway/coordinator change for ①. ② touches only
  a standalone probe script + `radp.worker` reuse (read-only forward).
- ① is a computed model validated by the measured decode rate — not a live
  packet capture (deferred; the KV-column bytes are exact by geometry, so the
  model is faithful).
- ② quantifies KV bit-divergence, not a full downstream-quality study. Token-flip
  under divergence is a spot-check, not a distribution.
- Network is a family-level axis (parity == replicate); it does not sharpen the
  parity-vs-replicate hero claim, which stays storage-only.

## File structure

- `experiments/_harness.py` — add `shipping_overhead()` (sibling to
  `replication_overhead`).
- `experiments/gen_overhead.py` — (if no committed generator) compute storage +
  shipping for the deployed placement → `b1_ft_overhead.json`.
- `experiments/probe_recompute_fidelity.py` — the per-tier probe + comparison.
- `experiments/results/b1_ft_overhead.json` — +shipping/bandwidth fields (gitignored).
- `experiments/results/b1_ft_fidelity.json` — new (gitignored).
- `tests/test_shipping_overhead.py`, `tests/test_fidelity_compare.py` — unit tests.
- `experiments/REPORT.md`, `PHASES.md` — write-ups.
