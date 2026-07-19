# Cross-stage parity KV-cache recovery — design

**Date:** 2026-07-20
**Status:** design approved, pending implementation-plan
**Related:** [`2026-07-16-b1-ft-baselines-design.md`](2026-07-16-b1-ft-baselines-design.md) (surgical/full-replay), `paper/refs/recovery-comparison.md`, REPORT §B1-FLEET

---

## 1. Motivation & goal

RADP's confirmed recovery mechanisms (full-replay, surgical) both reconstruct a
dead pipeline stage's KV cache by **re-running the model** over replayed inputs.
Surgical (rebuild only the dead stage from the mirrored inputs) is fast and
correct, but it is **the same family as Petals** (client-side input cache →
replay onto a replacement server). That overlap is the paper's differentiation
gap.

**Goal (primary = novelty).** Build a *third recovery family* that reconstructs
the dead stage's KV with **zero model forward pass** — cross-stage XOR parity,
the RAID-5 analog for a pipeline's KV caches. It trades a continuous network
tax (ship KV to the coordinator) for near-elimination of failure-time recompute.
This is the genuinely-new mechanism vs both input-replay (surgical/Petals) and
full KV replication (DejaVu / streamed-KV). GhostServe (MLSys'26) explicitly
leaves cross-node pipeline parity as future work — this is that opening.

**Fidelity/scope (decided).** Full fleet: a real gRPC KV-streaming +
coordinator-maintained parity + fleet fault → XOR reconstruct → measured TTR,
added as a **third line** to `experiments/b1_ft_fleet.py` alongside surgical and
full-replay. Strongest evidence, accepted higher cost (new proto + redeploy).

## 2. Approach (chosen = A; B, C rejected)

**A — pad-to-max XOR parity (RAID-5 analog). CHOSEN.**
Each pipeline stage is one "block" in a RAID stripe. Pad each stage's KV to the
max stage size, XOR into a single parity blob `P`. The coordinator stores **only
P** (≈ one largest-stage's worth), not every stage. Losing one stage = losing
one block → recover by XOR-ing survivors with P. True parity, space-efficient,
zero recompute.

- Rejected **B — coordinator-side full KV replication**: simpler (no pad/XOR,
  no failure-time fetch) but stores the *whole model's* KV at the coordinator
  (against RADP's edge-memory thesis) and is *replication, not parity* — loses
  the novelty the goal demands.
- Rejected **C — balanced per-layer re-grouping parity**: removes padding waste
  but breaks the "one block per stage" RAID invariant (a stage owns multiple
  layers → multiple blocks in one stripe → single-parity can't recover a whole
  stage). Marginal benefit, more complexity.

**Padding-skew note (feature, not bug):** parity efficiency = `P_size /
Σ stage_size` is best when stages are balanced. This *couples parity efficiency
to placement balance* — a direct tie-in to RADP's ψ+R coupling thesis, not just
an inefficiency to apologize for.

**Bit-XOR, not arithmetic.** Reconstruction only needs the RAID invariant
`⊕_i pad(KV_i) ⊕ P = 0`, which holds for raw **byte** XOR regardless of tensor
dtype/interpretation. So P is maintained as bytes; reconstruction XORs raw bytes
and the result is bit-identical to the dead stage's original KV. dtype-agnostic,
`numpy frombuffer(u8) ^ frombuffer(u8)` fast.

## 3. Architecture & data flow

### Steady state (keep P alive)
```
each worker, after RunStage appends this position's KV:
  extract_kv_column(req, stage_key, position)  # this stage's layers' k,v, last slice → bytes
  → MirrorKV push to coord  (fire-and-forget, beside the existing MirrorActivation)

coordinator ParityCache.xor_in(req, stage_key, position, column_bytes):
  pad column to pad_to(position) = max over stages of that position's column bytes
  P[req][position] ^= padded_column          # store ONLY P (RAID-5), + contributor bitmask
```
- `pad_to` is **per-position** (prefill's position-0 blob covers prompt_len and
  is ≫ a decode column; all stages align at the same position index).
- Input mirror (activations, ~2 KB/tok) stays ON in parity mode → fallback fuel.

### On failure of stage B (zero forward)
```
1. attribute dead stage      (shared with surgical — gRPC trailer)
2. promote backup + rewire   (shared with surgical — fixed overhead ~250 ms)
3. reconstruct KV_B, no model forward:
     surv = { stage: FetchKV(stage, req, up_to=P-1) for each surviving stage }  # once per survivor
     for pos in 0..P-1 where P[pos] is complete:
       KV_B_padded[pos] = ⊕(pad(surv[s][pos]) for s in survivors) ⊕ P[pos]
       KV_B[pos] = truncate(KV_B_padded[pos], B's byte length) → decode
     (any incomplete pos → fall back, see §5)
4. LoadKV(backup, req, stage_key, KV_B)   # install into DynamicCache, no forward
5. continue generation from position P on the rewired chain
```

### Three families compared (same fixed overhead; reconstruct differs)
| family | per-position reconstruct | nature |
|---|---|---|
| full-replay | whole-chain forward (~150 ms) | recompute |
| surgical | 1-stage forward (~15 ms) | recompute |
| **parity** | survivor KV fetch + byte XOR (~network, est. ~1 ms) | **transfer + XOR, zero recompute** |

## 4. Components & interfaces

### New proto (`radp/common/proto/radp.proto`) — 3 RPCs
| RPC | dir | request → response | purpose |
|---|---|---|---|
| `MirrorKV` | worker → coord | `{req, start, end, position, kv_bytes, is_prefill}` → `Ack` | steady-state KV column push |
| `FetchKV` | coord → worker | `{req, start, end, up_to_position}` → `{kv_bytes}` | pull a survivor's KV at failure |
| `LoadKV` | coord → backup | `{req, start, end, kv_bytes}` → `Ack` | install reconstructed KV, no forward |

→ proto change = recompile stubs + redeploy all nodes.

### New code
- **`radp/coordinator/parity_cache.py`** — `ParityCache` (sibling of
  `ActivationCache`): `xor_in(req, stage_key, position, column_bytes)`,
  `get(req, pos)`, `is_complete(req, pos)`, per-request eviction. Holds the
  per-`(req,pos)` contributor bitmask and `pad_to`. **Stores only P.**
- **`radp/worker/stage_runner.py`** — 3 helpers, DynamicCache ↔ bytes only:
  `extract_kv_column(req, stage_key, pos) → bytes`,
  `export_kv(req, stage_key) → bytes` (FetchKV),
  `install_kv(req, stage_key, bytes)` (LoadKV; builds DynamicCache, no forward).
- **`radp/coordinator/gateway.py`** — `recovery_mode == "parity"` branch +
  `_recover_parity(...)`: attribute → promote → rewire (shared with surgical) →
  reconstruct via ParityCache + FetchKV + LoadKV → continue.

### Minimal edits to existing code
- **`radp/worker/server.py`** — in `RunStage`, after the stage runs, if
  `RADP_PARITY` env is set: `extract_kv_column` → `MirrorKV` push (one line
  beside the existing mirror push). Add `FetchKV` / `LoadKV` servicer handlers.
- **`radp/coordinator/server.py`** — receive `MirrorKV` → `parity_cache.xor_in`;
  allow `"parity"` in `RADP_RECOVERY_MODE` (env wiring already exists).
- **Activation:** worker `RADP_PARITY=1` systemd drop-in (same pattern as
  `RADP_FAULT_INJECTION`) → KV-shipping tax only paid when parity is in play.

### Isolation boundaries
- `ParityCache`: owns P maintenance/lookup; XOR+pad encapsulated; gateway sees
  only `get`/`is_complete`.
- worker KV helpers: DynamicCache ↔ bytes only; proto/gateway see bytes.
- `_recover_parity`: shares promote/rewire with surgical, replaces only the
  reconstruct step → minimal duplication.

## 5. Correctness & fallback

**RAID invariant.** `P[pos]` must be the XOR of **exactly all N stages' columns,
once each**, for that position. A duplicate `(stage,pos)` self-cancels →
corruption. `ParityCache` dedups by `(stage,pos)` and marks a position
`complete` only when all N contributed. Reconstruction uses only complete
positions.

**bit-identical ⇒ sequence-match.** A bit-identical backup KV makes continued
generation identical to the no-failure run. In-process test asserts the bit
match directly; the fleet line verifies end-to-end sequence-match vs reference.

**Fallback ladder (never a wrong token):**
```
parity  →(P[pos] incomplete or FetchKV fails)→  surgical  →(gappy mirror history)→  full_replay
```
Parity mode keeps the cheap input mirror ON, so surgical is always available as
fallback. Parity is strictly the *fast path*; correctness never depends on it.

## 6. Testing
- **`tests/test_parity_cache.py`** (fast, no model): XOR / pad / completeness /
  duplicate-ignore / reconstruct unit tests.
- **`tests/test_parity_recovery.py`** (slow, `pytestmark = slow`): mirror+parity
  harness — run chain, xor_in columns, kill interior stage, reconstruct via
  parity, **assert reconstructed KV bit-identical to the original** + output
  sequence matches reference.
- **Fleet:** add `parity` to `experiments/b1_ft_fleet.py` modes → third line,
  same P sweep, fired + sequence-match gates. Extend `fig_recovery_ttr` to 3
  lines.

## 7. Scope / explicit limits (YAGNI)
- **Single fault only** (RAID-5 = one block loss). Concurrent multi-stage
  failure → parity infeasible = documented limit (matches R's single-backup
  assumption). Reed-Solomon multi-fault = future work.
- Padding-skew inefficiency accepted (reframed as ψ+R coupling angle).
- Continuous KV-shipping network tax is **measured/reported, not optimized**.
- `FetchKV` pulls survivors' full KV at failure — O(P × (N−1)) network, the
  honest cost; not cached at the coordinator (that would be replication = B).
- fp16 CUDA tensors — bit-XOR is dtype-agnostic, no issue.

## 8. Success criteria
1. **Correctness:** every fleet parity trial sequence-matches the reference; the
   in-process test asserts bit-identical KV reconstruction.
2. **Novelty (measurable):** parity TTR(P) slope ≪ surgical's ~15 ms/pos
   (near-flat, network-bound not compute-bound).
3. **Claim established:** parity is a third recovery family — zero forward
   recompute, space-efficient (store only P) — distinct from both input-replay
   (surgical/Petals) and full replication.

## 9. Open risks / notes
- **Fixed overhead dominates at small P.** promote+rewire (~250 ms) is shared by
  all three families, so parity's win over surgical is modest at small P and
  grows with P. Report honestly; the slope is the novelty, not the intercept.
- **FetchKV cost.** Survivor-KV fetch is real network on weak Nanos; must verify
  it stays ≪ surgical's recompute. If it doesn't at the fleet's link speed, that
  itself is the paper's compute-vs-network crossover finding — still a result.
- **DynamicCache internals.** Exact per-layer indexing (global vs stage-local
  slots) is an implementation detail to nail during coding; the interface
  (bytes ↔ DynamicCache) is stable.
- **Measured in sync chain** (same as B1-FLEET) — async detection is a separate
  axis.
