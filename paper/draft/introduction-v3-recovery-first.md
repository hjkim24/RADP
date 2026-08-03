# RADP — Introduction (v3, recovery-first draft)

> IEEE TII target. IMRAD/CARS intro, flowing prose, IEEE numbered citations.
> Citation numbers are placeholders keyed at the bottom; finalize against the .bib.
> Suggested title: **"Recovery-Aware Distributed LLM Inference on Heterogeneous
> Edge: Cross-Stage Parity for Zero-Recompute, O(1)-Storage Fault Tolerance."**

## I. Introduction

Large language models are moving from the cloud into industrial field workloads. Recent deployments run billion-parameter models for battery-management state estimation [1], assembly-line fault diagnosis [2], quality and defect inspection [3], and industrial control-system security [4]. In many of these settings the inference cannot be offloaded to the cloud at all. Air-gapped operational-technology networks forbid offload by policy; off-grid installations such as offshore platforms, mines, and remote substations have no dependable cloud link; and mobile robots and automated guided vehicles run real-time closed loops that cannot absorb a per-token round trip. For this class of workload, local inference is a premise rather than a preference.

A billion-parameter model, however, must hold its weights together with a key–value (KV) cache whose size grows with the sequence length, and this footprint exceeds the capacity of any single edge device. The established response is to partition the model across several of the heterogeneous nodes already installed in the field and serve it as a distributed pipeline [5], [6], [7], a pattern also studied for industrial DNN inference across the cloud–edge–end continuum [8], [9].

Two properties of the industrial edge govern how such a pipeline behaves in practice. The first is heterogeneity: GPU-class accelerators (AGX Orin, Orin Nano) coexist with CPU-only boards, with per-node throughput ratios reaching roughly 76× within a single fleet. The second is unreliability. Edge nodes fail routinely from energy depletion and hardware malfunction [10], and one node failure cascades into data loss and degraded service [11]; on our own fleet we observe crashes, out-of-memory kills, and network partitions directly. A distributed edge serving system must therefore treat a mid-inference node failure as an expected event, not an exception.

Existing distributed-inference systems handle heterogeneity but not recovery under tight memory. Latency- and throughput-optimal placement schemes assign each layer to a single device and carry no recovery path, so the first worker failure aborts the entire stream [6], [7]; on a production line this is a stoppage or a safety event, not a dropped request. Swarm-redundancy serving instead assumes that a spare peer already holds each layer [5], which presupposes the 16 GB-class nodes that a 4 GB edge simply does not have. A more fundamental gap underlies both: prior work optimizes layer placement (ψ) and recovery routing (R) as separate problems, yet on memory-tight edge their feasibility is coupled, because reserving backup capacity changes which placements fit at all. Solving them in isolation forfeits either feasibility or performance.

The recovery mechanism itself is also unexamined for this regime. Recomputation-based recovery re-runs the whole pipeline (full replay) or replays the dead stage from mirrored inputs (surgical recovery, the family to which the swarm approach belongs [5]); its cost grows with how far into the generation the failure occurred. Storing the KV state removes the recomputation, as datacenter serving does through replication [12] or erasure coding [13], but full replication multiplies steady-state storage across every stage, and re-solving placement over the survivors with no backup at all forces a cold weight reload that is prohibitive for interactive latency, which is precisely why the one serving system to adopt survivor-reconfiguration engineers around the naive version [14]. Which recovery strategy is right for heterogeneous, memory-constrained edge inference has not been established.

We present RADP (Recovery-Aware DP), which makes recovery a first-class dimension of distributed edge inference. RADP solves placement and recovery jointly in a single alternating dynamic program that feeds the backup-memory reservation back into the placement feasibility check, and a single cost knob recovers the latency regime of [6] and the throughput regime of [7] within one formulation. On a shared recovery substrate — an activation mirror cache with chain-aware failure attribution over gRPC trailer metadata — RADP introduces cross-stage parity recovery: every surviving non-head stage streams its KV column to the coordinator, which XOR-accumulates them into a single parity blob, and on a failure the dead stage's KV is reconstructed byte-for-byte from the survivors and the blob with no model forward pass. Evaluated as one of five recovery strategies (full replay, surgical, full replication, reactive re-placement, and parity) on a recovery-time × steady-state-storage plane, parity is the only strategy that is cheap on both axes. On a live five-stage OPT-350M Jetson chain its recovery time is essentially flat in failure position (0.87 ms per token, about 19× gentler than surgical and 188× than full replay), while its storage is O(1) in pipeline depth (one max-stage blob) against replication's O(N) (the sum over stages); at per-token granularity the gap looks modest (16 KB vs 37 KB), but because KV backup accumulates over the sequence and grows with the model, at realistic context lengths and model sizes it widens to hundreds of megabytes or gigabytes.

This paper makes the following contributions:

1. **Recovery as a first-class axis, and a two-dimensional trade-off.** We frame edge-inference fault tolerance as a recovery-time × steady-state-storage trade-off and compare the full strategy space on a live heterogeneous fleet, showing that only cross-stage parity occupies the low-cost corner on both axes.
2. **Cross-stage parity recovery.** A RAID-5-style byte-XOR scheme that reconstructs a failed stage's KV with zero recomputation and O(1) storage, transplanting the datacenter store-KV idea [12], [13] into the heterogeneous, memory-tight edge regime; because it restores stored bytes rather than recomputing, the recovered KV is bit-identical to the original, a guarantee the recompute-based strategies cannot make across device tiers.
3. **Joint placement–recovery dynamic program.** An alternating DP that couples the backup reservation into placement feasibility and generalizes latency- and throughput-optimal placement through a single cost parameter.
4. **Live evaluation on a heterogeneous Jetson fleet.** A five-strategy recovery comparison on OPT-350M, establishing parity's flat recovery time, its O(1)-vs-O(N) storage scaling, and bit-identical recovered output, alongside the placement and asynchronous-forwarding results that make the joint formulation deployable.

---

## Reference key (finalize against .bib; IEEE numbering)
1. Zhang et al., 2026 (TII) — 3B LLM for BMS state estimation
2. Liu et al., 2024 (TII) — assembly-line fault diagnosis
3. Wang et al., 2024 (TII) — quality/defect inspection
4. Chamotra et al., 2026 (TII) — ICS security
5. Borzunov et al., 2023 — Petals (ACL demo / NeurIPS extended)
6. EdgeShard — DP latency-optimal edge-cloud layer placement
7. Jupiter — TBT-SLO throughput-optimal placement
8. Lin et al., 2020 (TII) — cloud–edge–end DNN partition
9. Wu et al., 2021 (TII) — IIoT collaborative DNN inference
10. Kaur et al., 2023 (TII) — edge failures: energy depletion, hardware malfunction
11. Xu et al., 2020 (TII) — node failure → data loss, degradation cascade
12. Strati et al., 2024 (ICML) — DéjàVu, KV-cache streaming/replication for FT serving
13. GhostServe, 2026 (MLSys) — erasure-coded checkpointing for FT LLM serving
14. Miao et al., 2024 (ASPLOS) — SpotServe, stateful survivor-reconfiguration for serving

## Notes for revision
- Recovery-first re-centering applied: placement DP / async forwarding / L≻T are folded into contribution 3–4 as enablers, not the headline (per 2026-07-30 advisor pivot).
- Fidelity stated only as a bit-exact *guarantee* (contribution 2), not an output-error claim — the deep-dive showed greedy output does not flip (§B1-FIDELITY).
- Network-overhead axis intentionally omitted (advisor #4).
- Em dashes kept to 2 (para 5, para 6-anchor); vary before submission if a page break lands oddly.
- Numbers verified against experiments/REPORT.md §B1-*: parity 284.1+0.87ms·P, 19×/188×; storage 16384/36864 B, O(1)/O(N); 76× heterogeneity from prior deck.
