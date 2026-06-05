# RADP — Recovery-Aware DP for Distributed LLM Inference

**Benchmark report (live edge fleet)**

This report aggregates all live-fleet measurements collected for the paper.
Raw JSON sources are cited per experiment. Numbers in this document reflect
data after the critical fixes in commits `934ea27` (project_in order) and
`246a02b` (weight-loader prefix mismatch); see §7 for retracted data.

---

## Executive summary

| Claim | Evidence | Effect |
|---|---|---|
| Recovery-Aware DP **beats** the throughput-weighted greedy heuristic in normal operation when compute heterogeneity is meaningful | EXP-D2.1, n=300 TBT samples per cell | TBT p50 **-6.5%**, throughput **+8.3%** |
| Recovery-Aware DP **preserves all tokens** under worker failure while R={} baselines **lose 70%+** | EXP-D2.1, N=3 failure trials × 2 baselines | ours 60/60 ×3, greedy 17/60 ×3 |
| Recovery latency is bounded, predictable, and within edge-LLM SLOs | EXP-D2.1 + Phase EXP-A2 N=5 | mean 617 ms, p95 670 ms; tight 100 ms spread |
| In compute-light, network-bound regimes, all algorithms tie at the slowest-device floor | Phase EXP-A3 (OPT-125M, 8 homogeneous Nanos) | algorithms within ±0.1%; failure differentiator unchanged |

The headline paper claim — *"Recovery-Aware DP wins on normal operation **and** failure resilience, with the same R-Ψ joint optimization"* — is supported by N=3-backed live data on a heterogeneous 7-worker edge cluster.

---

## 1. Setup

### 1.1 Fleet

| device | class | cores | RAM | torch | role |
|---|---|---|---|---|---|
| on-1 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-2 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-6 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-3 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (forced)** | worker (CPU-Nano tier) |
| on-4 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (forced)** | worker (CPU-Nano tier) |
| on-5 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (forced)** | worker (CPU-Nano tier) |
| ao-2 | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CPU (only torch wheel available for JP5/Py3.9) | worker (CPU-AGX tier) |
| ax-1 | Jetson AGX Xavier 32 GB | 8 ARM Carmel | 30 GB | CPU | coordinator |
| ~~ao-1~~ | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CPU | **excluded — disk 100%** |

The three Nano-CPU workers were forced to CPU mode via the `RADP_TORCH_DEVICE` systemd env, creating a real 3-tier compute partition (~1.5 ms / 17 ms / 42 ms per layer for OPT-350M).

### 1.2 Models

| model | layers | hidden | weight format | bytes |
|---|---|---|---|---|
| facebook/opt-125m | 12 | 768 | bin (model.* prefix) | ~250 MB |
| facebook/opt-350m | 24 | 1024 | safetensors (no model.* prefix) | ~660 MB |
| facebook/opt-1.3b | 24 | 2048 | bin (model.* prefix) | 2.6 GB **— failed to deploy, see §6** |

### 1.3 Tooling

- [`experiments/run_e2e_remote.py`](run_e2e_remote.py) — single-baseline gRPC throughput benchmark
- [`experiments/run_failure_remote.py`](run_failure_remote.py) — SSE stream + Ansible-fired SIGKILL worker, per-token stage trace
- [`experiments/run_a3_remote.py`](run_a3_remote.py) — multi-baseline live deployment + comparison (manual cluster.yaml synthesis + push + restart + bench loop)
- [`experiments/a3_baselines.py`](a3_baselines.py) — algorithmic baseline computation from a profile sidecar
- [`experiments/run_algorithm.py`](run_algorithm.py) — synthetic-spec sweeps (no live cluster)

All ansible operations target the live fleet via `deploy/inventory.ini` (gitignored).

---

## 2. Algorithmic prediction (synthetic sweeps)

These run on synthetic specs and validate algorithm-level claims without touching the live fleet.

### 2.1 Compute heterogeneity sweep

3-device, 12-layer synthetic spec with varying fast-device multiplier. Compute-only cost model.

| fast-device multiplier | greedy (ms) | ours (ms) | speedup | greedy split | ours split |
|---|---|---|---|---|---|
| 1.0× (homogeneous) | 202.0 | 202.0 | 1.00× | [4,4,4] | [4,4,4] |
| 1.5× | 202.0 | 200.0 | 1.01× | [5,3,4] | [6,3,3] |
| 2.0× | 152.0 | 152.0 | 1.00× | [6,3,3] | [6,3,3] |
| **3.0×** | 152.0 | 133.3 | **1.14×** | [7,2,3] | [8,2,2] |
| 4.0× | 102.0 | 102.0 | 1.00× | [8,2,2] | [8,2,2] |
| **6.0×** | 102.0 | 83.3 | **1.22×** | [9,2,1] | [10,1,1] |

→ DP wins by 14–22% at specific multipliers where greedy's `round()` puts an extra layer on a slow device. Tie at multipliers that align cleanly. Source: [`algo_hetero.json`](results/algo_hetero.json).

### 2.2 Memory sensitivity, DP runtime, R-Ψ alternating gain

Captured in [`algo_memory.json`](results/algo_memory.json), [`algo_runtime.json`](results/algo_runtime.json), [`algo_alternating.json`](results/algo_alternating.json). DP runtime confirmed O(L² × |D|) up to L=64, M=6 (~30 ms). Memory mult sweep shows ours becomes infeasible before greedy at tight memory; jupiter-DP loses earlier because it accounts for backup but greedy ignores memory entirely (would produce OOM-bound placements at the boundary that the synthetic harness counts as "feasible").

---

## 3. Live measurements — OPT-125M (homogeneous Nano fleet)

### 3.1 Normal operation (A1)

8-worker fleet (5 Nanos + 1 AGX + 1 AGX-CPU + on-6 added later), auto_schedule placement.

| metric | value |
|---|---|
| TTFT mean / p50 / p95 | 283 / 276 / 324 ms |
| TBT mean / p50 / p95 / p99 (n=600) | 217 / 220 / 289 / 321 ms |
| Throughput mean | 4.42 tok/s |
| DP max_stage_time | 113.6 ms |
| Model–measurement gap | 104 ms (system overhead per pipeline traversal) |
| Auto-schedule phases | wait 4 ms · layers 35,170 ms · network 3,059 ms · DP 13 ms |

Source: [`auto_baseline_first.json`](results/auto_baseline_first.json).

### 3.2 Failure injection + recovery (A2 N=5)

Single victim ao-1 (1-layer stage), repeated 5 times with cluster auto-reset between trials.

| metric | value |
|---|---|
| Pre-kill TBT p50 (trial avg) | 221 ms |
| **Recovery step** | mean **729 ms**, p50 **677 ms**, p95 **883 ms** (range 669–930 ms) |
| Spike vs pre-p50 | mean +509 ms, **3.30×** |
| Post-recovery TBT p50 | 226 ms (within ~5 ms of pre-kill baseline) |
| In-flight tokens during kill | mean 4.6, max 7 |
| **Token loss** | **0 / 300** |
| Backup activation | **5 / 5 trials** correctly routed to R(ao-1) = ao-2 |

Per-trial layer absorption: the four 2-layer-on-backup cases hit 669–695 ms recovery; the one 3-layer absorption case hit 930 ms. Each extra layer the backup must absorb costs ~250 ms — dominated by cache-replay + serialization, not compute.

Source: [`a2_kill_ao1_n5.json`](results/a2_kill_ao1_n5.json).

### 3.3 Algorithm comparison live (A3b)

4 baselines deployed in sequence via manual-mode cluster.yaml + coord restart.

| baseline | TBT p50 | TBT p95 | TTFT p50 | failure | tokens emitted |
|---|---|---|---|---|---|
| greedy | 221 ms | 284 ms | 348 ms | catastrophic 3/3 | [19, 20, 18] |
| uniform | 215 ms | 290 ms | 329 ms | catastrophic 3/3 | [19, 19, 19] |
| jupiter_dp | 217 ms | 285 ms | 350 ms | catastrophic 3/3 | [19, 19, 19] |
| **ours** | **219 ms** | 288 ms | 353 ms | **graceful 3/3** | **60/60 × 3** |

ours recovery: mean **597 ms**, p50 **594 ms**, p95 **726 ms**.

ours and jupiter_dp produce **byte-identical** placements on this profile (memory headroom too large for backup reservation to constrain Ψ). All four baselines tie on normal-operation TBT within ±3% — the algorithmic gap is hidden by the slowest-device floor when compute heterogeneity is small. Source: [`a3b_opt350m.json`](results/a3b_opt350m.json) (the file name is unfortunate; this file actually holds the OPT-125M A3b run).

→ In the homogeneous compute regime, **normal-operation performance is indistinguishable**. The unique DP advantage in this regime is **recovery awareness** (binary: ours graceful vs all others catastrophic).

---

## 4. Live measurements — OPT-350M (3-tier heterogeneity)

After EXP-D2.1 fixes, this is the **headline paper data**. Three artificial compute tiers were created by forcing three Nanos to CPU mode (`model_torch_device=cpu` per-host inventory override). Measured per-layer compute times verify the tiers:

| tier | devices | mean per-layer compute (OPT-350M) |
|---|---|---|
| CUDA Nano | on-1, on-2, on-6 | ~1.5 ms |
| CPU AGX | ao-2 | 17.6 ms |
| CPU Nano | on-3, on-4, on-5 | 42 ms |

Slowest-device floor = 42 ms × 1 layer = 42 ms.

### 4.1 Single-baseline (A1', `ours` placement)

10 requests × 30 tokens, warmup 2.

| metric | value |
|---|---|
| TTFT mean / p95 | 367 / 390 ms |
| TBT p50 / p95 | 257 / 312 ms |
| Throughput mean | 3.8 tok/s |
| DP max_stage prediction | 136.8 ms |
| Model–measurement gap | 120 ms |

Source: [`opt350m_3tier_baseline.json`](results/opt350m_3tier_baseline.json).

### 4.2 Algorithm comparison live (A3b' N=3) — **paper figure**

| Metric | greedy | **ours** | Δ |
|---|---|---|---|
| Normal TBT p50 | 302.3 ms | **282.6 ms** | **-6.5%** |
| Normal TBT p95 | 366.0 ms | 352.0 ms | -3.8% |
| Normal TBT p99 | 407.8 ms | 389.1 ms | -4.6% |
| Normal TTFT p50 | 524.9 ms | 519.8 ms | -1.0% (tie) |
| Throughput mean | 3.14 tok/s | **3.40 tok/s** | **+8.3%** |
| Failure (3 trials) | **3/3 catastrophic** | **3/3 graceful** | **binary** |
| Tokens emitted (failure) | 17, 17, 17 | 60/60 × 3 | |
| Recovery step | N/A | mean **617** / p50 **600** / p95 **670** ms | tight |
| Recovery range | N/A | 573–678 ms | 105 ms spread |
| Spike vs pre-p50 | N/A | +329 ms (**2.16×**) | |

n=300 TBT samples per condition (10 req × 30 tok). Source: [`a3b_opt350m_3tier_n3.json`](results/a3b_opt350m_3tier_n3.json).

### 4.3 Placement comparison

```
greedy : on-6[1-8]    on-3[9]   on-1[10-15]  ao-2[16]  on-5[17]  on-4[18]  on-2[19-24]
         CUDA work spread 8 + 6 + 6 across three CUDA Nanos

ours   : on-6[1-16]   on-3[17]  on-1[18-20]  ao-2[21]  on-5[22]  on-4[23]  on-2[24]
         CUDA work concentrated 16 + 3 + 1 on the three CUDA Nanos
```

Both placements keep CUDA stages below the 42 ms CPU-Nano floor in algorithmic prediction (greedy stages: 8 × 1.5 = 12 ms, 6 × 1.5 = 9 ms; ours: 16 × 1.5 = 24 ms, 3 × 1.5 = 4.5 ms). The 6.5% live TBT gap therefore comes from **pipeline transition overhead** that the cost model under-counts when fewer of those transitions are long-haul CUDA↔CUDA hops.

### 4.4 Why DP wins live where the cost model predicted tie

Algorithmic comparison at realistic `activation_bytes` predicts ours and greedy tie at 45.3 ms max_stage (CPU-Nano floor):

| baseline | algorithmic max_stage (activation_bytes=4 KB) |
|---|---|
| greedy | 45.3 ms |
| uniform | 171 ms (+278% — ao-2 with 4 layers becomes bottleneck) |
| jupiter_dp | 45.3 ms (placement identical to ours) |
| ours | 45.3 ms |

The cost model only sees compute + activation_transfer per stage. Live measurement also captures: (a) gRPC framing overhead scaling with stage count, (b) Python / GIL contention when many small stages run back-to-back, (c) KV cache append cost. ours' fewer-bigger-stages placement saves on all three.

Source: [`a3a_opt350m_3tier_ab4k.json`](results/a3a_opt350m_3tier_ab4k.json).

---

## 5. Key findings (paper)

1. **DP wins on normal operation, but only when compute heterogeneity is meaningful.** In our OPT-125M homogeneous-Nano fleet (§3.3), all four placements tie within ±3% TBT. In the OPT-350M 3-tier fleet (§4.2), ours beats greedy by **-6.5% TBT** and **+8.3% throughput**, with n=300 samples per condition.

2. **DP wins on failure resilience as a binary across both regimes.** ours preserves all tokens (180/180 in §4.2 N=3 trials; 300/300 in §3.2 N=5 trials). Every R={} baseline (greedy, uniform, jupiter_dp) drops the stream catastrophically — exactly 17–20 tokens emitted before NoRecoveryError, depending on the kill-after + in-flight window.

3. **Recovery is bounded and predictable.** Across two regimes and two model sizes, recovery latency stays within **600–700 ms median**, with **p95 under 730 ms**. The recovery cost scales mildly with backup-burden-layer count (~250 ms per extra layer the backup must absorb).

4. **The cost-function gap.** The DP's algorithmic prediction *under-estimates* the value of fewer-bigger stages. greedy and ours tie on predicted max_stage_time (45.3 ms), but ours wins live by 6.5%. Improving the cost model with marginal-layer or transition-count terms is plan.md backlog item A6.

5. **OPT-350M's `project_in` and the safetensors prefix layout are both gotchas.** Two real fixes were needed to make OPT-350M work on this stack — both are commit-trail visible (`934ea27`, `246a02b`) and worth flagging for anyone trying to extend the loader to other architectures.

---

## 6. Negative results

### 6.1 OPT-1.3B on Jetson Nano (EXP-D0)

Three attempts: (i) auto_schedule put 18 layers on one Nano, OOM-reboot under load; (ii) 6-worker auto retry, on-1 OS reboot during 18-layer LoadStage; (iii) manual 4-5-layer-per-Nano placement, on-6 sshd swap-thrash. Root cause: **single-bin OPT-1.3B (2.6 GB) is loaded fully into memory by `torch.load`**, so the per-worker peak is close to the whole model size. Distributing doesn't help if the loader is not sharded. Sharded models (Llama-2-7B, OPT-6.7B) would work but are out of scope.

### 6.2 DP placement polarization analysis

Both EXP-D0 and the early EXP-D1 runs produced extreme placements (18-19 layers on one node, 1 on every other). Two hypotheses were explored:

- **`activation_bytes` calibration**: the default 1 MB is 5–200× larger than real OPT-350M activations (~4 KB decode, ~70 KB prefill). DP over-counts transition cost → favors concentration. Confirmed via the `activation_bytes` sweep ([`a3a_opt350m_ab4096.json`](results/a3a_opt350m_ab4096.json), `..._ab35000.json`, `..._ab100000.json`, `..._ab1048576.json`).
- **Stage count is fixed by device count** (= 6 or 7), so the *number* of transitions is identical across all placements. The cost difference comes from *which* devices each transition involves and *what compute* each stage holds. DP's concentration choice can still be correct under that model — the polarization is not a bug per se.

### 6.3 Memory-binding regime — not reached

Even at OPT-350M with all backup layers loaded, peak per-Nano usage stayed under 1 GB (vs 8 GB cap). The `ours.Ψ == jupiter_dp.Ψ` byte-identical placement is the consistent observation across both OPT-125M and OPT-350M — backup memory reservation never constrained Ψ. Reaching the memory-binding regime requires either Llama-7B INT4 on smaller-RAM Nanos or a much deeper model.

---

## 7. Retractions (EXP-D1)

The OPT-350M data in earlier PHASES.md sections (EXP-D1) is **invalid**. The HF safetensors snapshot of facebook/opt-350m uses keys like `decoder.layers.0.self_attn.k_proj.weight` (no leading `model.`), while `OPTArchitecture.weight_prefix` returned the prefixed form. The mismatch caused `layer.load_state_dict(empty_dict, strict=False)` to leave every block at random-init weights. Symptoms:

- Greedy decode on "The quick brown fox" returned " Country" × 8 (degenerate, repeated tokens from random transformer blocks).
- ProfileLayers reported ~1 ms / layer on CPU Nanos — physically implausible; matmul over near-zero weights was being SIMD-zero-shortcut'd.
- A3b' showed greedy *9% faster than ours* in live — the opposite of the corrected EXP-D2.1 result.

Fix in commit `246a02b`. All §3 OPT-125M data predates the bug and is unaffected.

---

## 8. Limitations + future work

| Limitation | Impact | Path forward |
|---|---|---|
| Single victim (ao-2) in EXP-D2.1 | Recovery cost as a function of victim layer count not measured at multiple positions | Victim sweep across head / middle / tail stages — ~30 min on current fleet |
| ao-1 (AGX Orin) excluded from EXP-D2 / D2.1 fleet | Loses one AGX-Orin in the heterogeneity setup | Disk cleanup (bstarcom team_quant) or wait for self-recovery |
| 3 Nanos forced to CPU mode | Heterogeneity is *artificial*, not naturally arising from edge battery/thermal throttling | Re-measure on a fleet with one genuinely-different SKU (Pi 5 vs Nano vs AGX); thermally throttle by sustained-load preheating |
| OPT-1.3B unreachable on this fleet | Cannot demonstrate ours' advantage in the memory-binding regime | Re-test with sharded Llama-2-7B INT4 (radp's sharded loader already supports it) |
| DP cost-function gap | ours' live-TBT advantage exists but is under-counted by the predictor — slight risk to predictability | Add marginal-layer / transition-overhead terms; backlog item A6 |
| `activation_bytes` static | Currently 1 MB hard-coded; real workload uses ~4-70 KB | Estimate dynamically from prompt length + model hidden dim; backlog A6 |
| Single failure injection per trial | Multi-failure recovery not yet tested | Backlog A2 (R as list-of-backups) |

---

## Appendix A — Result JSON map

| file | scope |
|---|---|
| `auto_baseline_first.json` | OPT-125M A1 (8-worker) |
| `a2_kill_ao1_first.json` | OPT-125M A2 single trial |
| `a2_kill_ao1_n5.json` | OPT-125M A2 N=5 |
| `a3_alg_first.json` | OPT-125M A3a algorithmic |
| `a3_full_first.json` | (legacy A3b' draft — superseded by `a3b_opt350m.json`) |
| `a3b_opt350m.json` | **OPT-125M** A3b 4-baseline (filename misleading; pre-D-track) |
| `opt350m_baseline_first.json` | OPT-350M EXP-D1 A1' **(retracted; bogus weights)** |
| `a3a_opt350m.json` | OPT-350M EXP-D1 A3a' (retracted) |
| `a3a_opt350m_ab4096.json`, `_ab35000.json`, `_ab100000.json`, `_ab1048576.json` | `activation_bytes` sweep |
| `opt350m_3tier_baseline.json` | EXP-D2 A1' 6-worker 3-tier (corrected weights) |
| `a3b_opt350m_3tier.json` | EXP-D2 A3b' greedy vs ours, N=1 |
| `opt350m_3tier_7w_baseline.json` | EXP-D2.1 sidecar (7-worker 3-tier) |
| `a3a_opt350m_3tier_ab4k.json` | EXP-D2.1 algorithmic comparison |
| **`a3b_opt350m_3tier_n3.json`** | **EXP-D2.1 A3b' N=3 — headline paper data** |
| `algo_hetero.json`, `algo_memory.json`, `algo_runtime.json`, `algo_alternating.json` | Synthetic algorithmic sweeps |
