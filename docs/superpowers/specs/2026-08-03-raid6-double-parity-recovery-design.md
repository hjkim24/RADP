# RAID-6 double-parity cross-stage KV recovery — design spec

**Date:** 2026-08-03
**Status:** approved (design), pending spec review
**Depends on:** 2026-07-20 parity recovery (RAID-5), 2026-07-22 replication baseline,
2026-07-30 FT overhead + fidelity metrics.

## Goal

Extend cross-stage parity KV recovery from single-failure (RAID-5, one XOR blob P)
to double-failure (RAID-6, blobs P + Q over GF(2⁸)), runtime-toggleable back to
RAID-5, then measure RAID-5 vs replicate vs RAID-6 on the live fleet against the
existing B1 data.

## Motivation

Current parity recovery reconstructs exactly one dead non-head stage; two
simultaneous deaths leave the XOR underdetermined and fall back to surgical
(`radp/coordinator/gateway.py:1076` docstring). `replicate` survives arbitrary
simultaneous failures but pays O(N) steady-state storage. RAID-6 buys
two-failure tolerance at O(1) storage (2 blobs) — the fair middle point that
turns the 2-D recovery-time × storage story into a 3-way comparison: under a
2-failure event RAID-5 falls back to expensive recompute, replicate survives at
O(N), RAID-6 survives at O(1).

## Non-goals (YAGNI)

- General Reed-Solomon (k > 2). k = 2 exactly.
- Worker changes. The worker already ships KV columns when `RADP_PARITY` is set;
  Q is computed coordinator-side from the same columns.
- Head-stage recovery (head is coord-sourced, never in the parity group — unchanged).
- >2 simultaneous failures: safe fallback to surgical.
- New cache class: extend `ParityCache`, do not add a parallel type.

## Architecture

Three orthogonal env knobs (all runtime-selectable):

| Env | Meaning | Values |
|---|---|---|
| `RADP_PARITY` | worker ships KV columns to coord | set / unset |
| `RADP_RECOVERY_MODE` | what coord does with them | full_replay / surgical / parity / replicate |
| `RADP_PARITY_K` | parity blobs when mode=parity | `1` (default, RAID-5) / `2` (RAID-6) |

`RADP_PARITY_K` is coordinator-only and meaningful only when
`RADP_RECOVERY_MODE=parity`. k=1 keeps today's path byte-for-byte; k=2 adds the Q
blob and the 2-failure decode. The worker is untouched.

### Field arithmetic

GF(2⁸), primitive polynomial `0x11d` (x⁸+x⁴+x³+x²+1), generator g = `0x02` —
the standard RAID-6 field (Anvin, "The mathematics of RAID-6").

Non-head stages D₀…D_{m-1} are ordered by `start_layer` (device-independent, so
the rank is stable across placement rewiring). Two syndromes:

```
P = Σ Dᵢ                (XOR — exactly today's ParityCache)
Q = Σ gⁱ · Dᵢ           (GF scalar-multiply by gⁱ, then XOR-accumulate)
```

### Single failure (1 dead stage), k=2 mode

Use P alone: `D_x = P ⊕ (XOR of surviving Dᵢ)`. Identical to the existing
`_xor_reconstruct_kv` path. RAID-6 mode therefore reuses RAID-5's single-failure
recovery unchanged and strictly *contains* RAID-5.

### Double failure (dead ranks x < y), k=2 mode

```
Pxy = P ⊕ (XOR of surviving Dᵢ)          = Dx ⊕ Dy
Qxy = Q ⊕ (Σ gⁱ · surviving Dᵢ)          = gˣ·Dx ⊕ gʸ·Dy
```
Solve (Anvin §4), byte-wise over GF(2⁸):
```
denom = g^(y-x) ⊕ 1                        (nonzero for 0 ≤ x < y < 255)
A = g^(y-x) · denom⁻¹
B = g^(-x)  · denom⁻¹
Dx = A·Pxy ⊕ B·Qxy
Dy = Pxy ⊕ Dx
```

## Components

### ① `radp/coordinator/gf256.py` (new)

Pure-numpy GF(2⁸) tables and ops. No dependencies beyond numpy.

**Produces:**
- `GF_EXP: np.ndarray` (uint8, len 512 for wrap-free indexing), `GF_LOG: np.ndarray` (uint8, len 256).
- `gf_mul_scalar(c: int, arr: np.ndarray[uint8]) -> np.ndarray[uint8]` — multiply
  every byte of `arr` by scalar `c` in GF(2⁸) (log/exp lookup; `c==0 → zeros`).
- `gf_inv(c: int) -> int` — multiplicative inverse (`c != 0`).
- `gf_pow(base: int, exp: int) -> int` — for gⁱ and g^(-x) (negative exp via inverse).

### ② `radp/coordinator/parity_cache.py` (modify)

`ParityCache.__init__(num_stages, max_bytes=…, k: int = 1)`.

- `_Entry` gains `q_parity: np.ndarray` allocated only when `k == 2`.
- `xor_in(request_id, stage_key, position, column_bytes, coeff_index: int = 0)`:
  when `k == 2`, after the P update, do `q[:col.size] ^= gf_mul_scalar(gf_pow(2, coeff_index), col)`.
  Q grows/zero-pads in lockstep with P. The existing contributor-set dedup guards
  both blobs (one `if stage_key in contributors: return`).
- `get_qparity(request_id, position) -> bytes | None` — sibling to `get_parity`.
- `is_complete` unchanged (contributor-count based; P and Q share contributors).
- Byte accounting includes the Q blob when k==2.

**Interface note:** `coeff_index` defaults to 0 so k=1 callers and existing tests
are unaffected. When k==1 the Q branch never runs and `coeff_index` is ignored.

### ③ `radp/coordinator/gateway.py` (modify)

- Constructor: read/accept `parity_k` (from `RADP_PARITY_K`), pass to
  `ParityCache(..., k=parity_k)`. Validate `parity_k ∈ {1, 2}`.
- Build a stable `stage_key → coeff_index` map once from `self.placement`
  (non-head stages sorted by `start_layer`, 0-based rank).
- `record_kv`: when mode==parity and k==2, pass `coeff_index` into `xor_in`.
  (replicate/k=1 paths unchanged.)
- `_recover_parity`: branch on the number of dead non-head stages (original
  placement stages whose device ∈ `self._dead`):
  - `1` → existing single-fault path (P only). Unchanged.
  - `2` and k==2 → new `_gf_reconstruct_kv` for both victims, promote+rewire both
    backups, run failed position live.
  - otherwise → `_recover_surgical` fallback.
- `_gf_reconstruct_kv(...)`: sibling to `_xor_reconstruct_kv`. Per slot: read P and
  Q blobs, compute Pxy (XOR survivors) and Qxy (GF-accumulate survivors by their
  ranks), solve for the two dead columns, slice each victim's own bytes. Same
  slot-major ↔ layer-major reconciliation and upstream +1-slot skew handling as
  the single-fault path, applied to both victims (both crash at the top of
  RunStage before appending P, so both hold the shared prefix
  N = min(survivor slot counts)).

### ④ `radp/coordinator/server.py` (modify)

Read `RADP_PARITY_K` (default `1`), pass to the Gateway constructor alongside the
existing `RADP_RECOVERY_MODE` read (server.py:520).

### ⑤ `experiments/_harness.py` + `experiments/gen_overhead.py` (modify)

Storage accounting gains a `raid6` family = **2 × parity storage** (P blob + Q
blob, both sized to the widest = max-stage KV). Steady-state shipping is unchanged
(the worker ships the same columns; Q is a coord-local fold, no extra wire bytes).

### ⑥ `experiments/storage_scaling_models.py` + `paper/figures/make_storage_scaling_models.py` (modify)

Add the raid6 line: at balanced N, raid6 = 2/N of full KV vs parity 1/N vs
replicate (N-1)/N. Report the crossover where raid6 ≥ replicate (non-head < 3).

### ⑦ `experiments/b1_ft_fleet.py` (modify)

- `raid6` family: run with `RADP_PARITY_K=2` + `RADP_RECOVERY_MODE=parity`.
- Two-victim injection: pick two interior non-head victims (neither the last
  stage) from the live placement, `mark_device_dead` both, then trigger a step and
  time the 2-failure recovery. TTR curve across failure positions, mirroring the
  existing RAID-5 curve.
- Contrast run: RAID-5 (k=1) + 2 victims → confirm fallback to surgical/full-replay.

### ⑧ Deliverables

- `experiments/results/b1_ft_raid6.json` (gitignored) — 2-failure TTR + storage.
- `experiments/REPORT.md` §B1-RAID6: the 3-way comparison (single TTR / double TTR
  / steady-state storage / failure tolerance), plus findings entry.
- `PHASES.md`: Phase B1-RAID6.
- `paper/figures/`: RAID-6 point on the 2-D Pareto (storage 2×parity, tolerates 2).
- brain-wiki `topics/radp-fault-tolerance.md`: RAID-6 metrics update.

## Failure model / correctness

- GF reconstruction is integer/deterministic → recovered KV is **bit-exact** to
  the original, same guarantee as XOR (asserted in unit tests).
- Never emit a wrong token: any doubt (P or Q incomplete, survivor geometry
  mismatch, >2 deaths, victim with no downstream survivor, missing mirror input)
  → `_recover_surgical` fallback, exactly like the single-fault path.
- `denom = g^(y-x) ⊕ 1` is nonzero for all distinct ranks in a fleet of < 255
  non-head stages — always satisfied here.

## Testing

- `tests/test_gf256.py`: `gf_mul_scalar` against a reference; `a · gf_inv(a) == 1`
  for all `a ∈ [1,255]`; `gf_pow(2, i)` matches iterated multiply; distributivity
  on a few vectors.
- `tests/test_raid6_recovery.py`: synthetic stage columns → build P and Q →
  drop every distinct (x, y) pair → `_gf_reconstruct_kv` (or the extracted pure
  solver) returns the two dropped columns **bit-exact**; single-drop in k=2 still
  works via the P path.
- `tests/test_parity_recovery.py`, `tests/test_replicate_recovery.py`: unchanged,
  must still pass (k=1 regression gate).
- Live 2-victim fleet run is an experiment step, not a unit test.

## Backward compatibility

- Default `RADP_PARITY_K=1` reproduces today's RAID-5 path exactly (Q never
  allocated, `coeff_index` ignored, single-fault decode unchanged).
- `recovery_mode` enum and worker gates unchanged.
- Existing results/figures remain valid; RAID-6 is additive.

## Open defaults (resolved, no TBD)

- Toggle interface: `RADP_PARITY_K` env (not a new recovery_mode value).
- Coefficient assignment: gⁱ where i = 0-based rank of the stage among non-head
  stages sorted by start_layer.
- Two-victim selection for measurement: two interior non-head stages, excluding
  the last stage (avoids the no-downstream-survivor geometry that trips the gate).
