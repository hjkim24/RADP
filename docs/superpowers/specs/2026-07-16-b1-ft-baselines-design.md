# B1 — Fault-Tolerance Baseline Comparison (Design Spec)

**Date:** 2026-07-16
**Status:** design approved, pending implementation plan
**Origin:** `paper/draft/0-advisor-feedback-analysis.md` Part 3-B, experiment B1
**Motivation:** Advisor feedback — the current recovery result compares RADP only against *no-recovery* baselines (placement-only aborts), which is a trivial comparison. To make fault tolerance the paper's main axis, RADP must be compared against **real recovery strategies** on the **same fleet, model, and failure injection**, on metrics meaningful even against non-FT systems.

---

## 1. Goal & Claim

**Goal:** Measure RADP's recovery against a literature-grounded set of alternative recovery strategies under an identical single mid-stream worker failure, and show RADP wins (or is competitive) on time-to-recovery, correctness, and goodput.

**Claim to support:** *Under a mid-stream worker SIGKILL, RADP recovers faster (TTR) and with full correctness at lower goodput loss than cold-restart and no-mirror replay, while true redundant-hosting — the only strategy that could beat RADP on TTR — is infeasible in the 4 GB Nano regime it targets.*

This is a **recovery-quality** comparison, distinct from the throughput/latency (L≻T) finding, which is repositioned separately as cost-of-FT.

---

## 2. Baseline Set

Five lines, all driven through the **same** injection (single mid-stream SIGKILL of one chain-interior worker), same model, same placement shape where applicable.

| Line | Placement / Recovery | On mid-stream SIGKILL | Literature grounding |
|---|---|---|---|
| **RADP** (ours) | DP placement + backup reserved (Eq.mem) + out-of-band mirror cache | attribute dead worker (trailer/heartbeat) → promote backup → replay KV from mirror → continue | — |
| **B0 — no-recovery (abort)** | `dp_placement_no_recovery` (R = {}, no backup memory) | no backup → stream aborts with partial output | EdgeShard, Jupiter (no recovery) |
| **B1 — cold-restart** | re-solve placement excluding the dead node | re-run the entire request from position 0 on the healthy re-solve | naive checkpoint-less job restart |
| **B2 — no-mirror replay** (ablation) | DP + backup reserved, **mirror cache disabled** | promote backup → rebuild KV by recomputing the prefix from the chain head (no out-of-band mirror to replay) | RADP ablation ≡ naive backup-promotion without out-of-band state |
| **B3 — redundant hosting** | backup **pre-hosts a live replica** of the stage (weights resident on two devices) | reroute to the live replica (KV-rebuild mechanics: see Open Questions) | Petals swarm, JARVIS duplication, Parallax replica |

### 2.1 B2's dual role (labeling)
B2 differs from RADP in **exactly one** dimension (the mirror cache), so it is simultaneously:
- an **ablation** that causally isolates the mirror cache's contribution, and
- a legitimate standalone **baseline** (naive backup-promotion without out-of-band state).

It is run **once** in this experiment. The comparison table labels it explicitly as `RADP − mirror (ablation)`, visually grouped apart from the external baselines (B0/B1/B3), so it is not mistaken for a competitor system. The paper's ablation discussion reuses the same number — no separate re-run.

### 2.2 B3 and the 4 GB infeasibility finding
Redundant hosting keeps a second copy of a stage's weights resident on a live peer, doubling that stage's memory footprint. On a 4 GB Nano this is **infeasible** — which is itself the finding tying back to the coupled-feasibility thesis (§ RADP reserves *memory* for a backup and rebuilds via mirror replay, rather than paying for a full live replica).

Handling:
- **Measure** B3's TTR on the memory-abundant boards (AGX Orin 32 GB / AGX Xavier), where a live replica fits, for an apples-to-apples TTR number vs RADP.
- **Compute/demonstrate** that the same B3 placement exceeds memory on the 4 GB Nano (infeasibility), reported alongside.

---

## 3. Metrics (per line)

| Metric | Definition | Reuses |
|---|---|---|
| **TTR** (time-to-recovery) | wall-time of the failed decode step: failure → first correct token after recovery | `measure_mid_decode_replay` `recovery_step_seconds` |
| **Correctness / token completeness** | tokens delivered vs requested; sequence matches the no-failure reference | `tokens_completed`, sequence equality check |
| **Goodput under failure** | effective tokens ÷ total wall-clock including recomputation | new aggregate over the driver run |

**Explicitly out of B1** (separate experiments): steady-state mirror/backup overhead (L8), failure-mode diversity crash/OOM/partition (L7), fair-setup heterogeneity sweep (L4).

---

## 4. Execution Strategy

1. **Develop & validate** the four baseline variants in-process (`experiments/run_failure.py` style: `in_process_cluster`, opt-125m, 3 workers) — fast iteration, deterministic.
2. **Port** the confirmed variants to the real fleet (`experiments/run_failure_remote.py`) for the **headline numbers** on the 6-worker Jetson fleet with OPT-350M (and, if time permits, Llama-3.2-1B). This satisfies the "real, fair measurement" requirement.

---

## 5. Reuse vs New (minimize new code)

| Need | Existing asset | Work |
|---|---|---|
| RADP recovery line | `measure_mid_decode_replay` | reuse |
| B2 no-mirror mechanism | `measure_e2e_wall_clock` `re_prefill` variant (`cache.get_history = []`) | adapt to mid-decode injection |
| B0 abort placement | `experiments/_harness.dp_placement_no_recovery` | swap placement, measure partial output |
| B1 cold-restart | — | **new** (re-solve + full re-run + goodput accounting) |
| B3 redundant hosting | — | **new** (replica-resident placement + reroute + 4 GB infeasibility calc) |
| Unified driver | — | **new** (one injection → 5 lines → one comparison JSON) |

**New code = B1 line + B3 line + unified driver.** Everything else adapts existing harness code.

---

## 6. Deliverables

- Unified driver emitting one comparison record per fleet run:
  `experiments/results/b1_ft_baselines_<config>.json` (per line: TTR, tokens_completed, sequence_match, goodput).
- A recovery comparison figure (bar/CDF), reusing `paper/figures/make_recovery_cdf.py` scaffolding.
- A results section in `experiments/REPORT.md` under the recovery experiments.

---

## 7. Scope Boundaries (what B1 does NOT do)

- No steady-state overhead measurement (L8 — separate).
- No crash/OOM/partition diversity; single mid-stream SIGKILL only (L7 — separate).
- No heterogeneity/model-size fair-setup sweep (L4 — separate, feeds the repositioned throughput story).
- No B4 skip/degraded line (correctness-lossy; out of scope for this correctness-preserving comparison).

---

## 8. Risks

1. Fair setup / real measurement may show the **L≻T throughput margin shrinks** — acceptable, since throughput is no longer the headline.
2. RADP's TTR advantage over cold-restart may be **less dramatic than hoped** (617 ms clean recovery is fast, but cold-restart's cost depends on how deep the failure lands). Run B1 first and let the measurement decide — do **not** rationalize if it contradicts the claim (`feedback_question_unexpected_results`).
3. B3 KV-rebuild mechanics are unsettled (below) — could make B3 TTR comparable to RADP rather than better; that is still a valid finding given B3's memory infeasibility on 4 GB.

---

## 9. Open Questions (resolve during planning)

- **B3 KV rebuild:** a live replica has the stage *weights* but not this request's *KV cache*. Does B3 (a) rebuild KV via replay like RADP, (b) actively mirror-compute in parallel (Petals dual-cache style), or (c) recompute prefix? This choice determines whether B3's TTR advantage over RADP is real or marginal. Pin it against what the Petals paper actually specifies before implementing.
- **Cold-restart re-solve cost:** does B1's TTR include the DP re-solve time, or only the re-run? Decide and document (recommend: include it — that is the real cost a cold-restart system pays).
- **Fleet config for B1:** use a neutral/representative config (not the 76× extreme) so recovery numbers are not entangled with the contested heterogeneity setup.
