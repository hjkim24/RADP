# Response to Reviewers — KV-CARE (simulated IoT-J panel, 2026-09-03)

We thank the five reviewers. All comments were addressed by rewriting, by
re-deriving quantities from the reported measurements, or by offline
reanalysis of the saved cluster profiles; the testbed is no longer available,
so comments that require new fleet measurements are answered by stating the
limitation explicitly (marked **[limitation]**). Format: **R** reviewer
comment → **A** our response → **C** change and location.

## 1. Over-claims in abstract / conclusion (R0, R1-C1, R2-C1/C4, R3-M6, DA-C2/C4)
**R** "matches replication's latency" contradicts Table I (1.42 vs 0.77 s at P=32); "independent of the failure position" is asserted for an O(N) loop measured to P=32; "a stage failure" generalizes beyond the protected stages; the feasibility claim omits its backup-host scope.
**A** Agreed on all four.
**C** Abstract rewritten: "flat over the measured failure positions", "recovers about one decode step later than replication while retaining 3.7× less coordinator state", "two simultaneous failures at the cost of one when their backups sit on distinct nodes", "with backups confined to pipeline devices … across the memory range in which the model fits", "a protected-stage failure". Conclusion aligned. §Latency now states the O(N) loop, the 2-SE bound on the per-position cost (<12 ms) and that we do not extrapolate beyond P=32; Limitations repeat this.

## 2. Recovery-State Footprint scope and Petals' retained state (R1-C2, R3-M2, DA-C1/C5, R2-C3)
**R** The metric excludes preloaded backup weights (~12.4 GiB fleet-wide) and credits Petals with 0 kB/tok although it retains per-position stage inputs.
**A** Agreed. The footprint metric measures request-proportional state; backup weights are a placement-time reservation common to every backup-based family and belong to the feasibility axis.
**C** §Setup (Metrics) redefines the metric and states the 12.4 GiB reservation; Table I lists Petals at 40 kB/tok (five fp16 hidden vectors per token) with a table note; Fig. 2 (Pareto) moves the Petals point accordingly; §Footprint adds the Petals figure and the tail-stage caveat (2.7× over the four recoverable stages).

## 3. Contract-conditioned latency, best-case injection, detection delay (R1-M7, R3-C3, DA-C3)
**A** Agreed; the injection deliberately exercises the contract's design case. **[limitation]** kill/OOM, random-timing, and detection-inclusive measurements need the fleet.
**C** Limitations state the injection model, that reported latencies characterize the parity path rather than the average over failure timings, the unmeasured fallback cost, and the heartbeat parameters (1 s tick, 5 s timeout, §Design runtime).

## 4. Table and notation errors (R0, R1-C3, DA-M4)
**C** Table I: Reconfigure row now lists its two measured positions, no P=32 entry, no "median"; state column note; P (position) disambiguated from P[r,q] at first use; Table III cap bound written as the uncapped free memory; "decode step" defined as the median token interval of the same sweep.

## 5. Feasibility baseline strength and scope (R1-M9, R2-MAJOR-7, DA-C7)
**R** Cost-first with R=∅ is the weakest sequential procedure; would a headroom rule suffice?
**A** We added a headroom-margin sequential baseline (place with each device's free memory scaled by 1−m, then reserve on true capacities) by offline reanalysis of the saved 7B profile, and re-ran the sweep with all six CUDA workers in the pipeline pool (the previous run's pool omitted one Nano).
**C** §Feasibility and Table III now report the six-worker sweep: with backups confined to pipeline devices the joint-only band spans every cap at which the model fits (4.8 GB up to the uncapped 23 GB; the earlier draft's 6.5 GB came from a five-worker pool), and the headroom baseline (0.75× and 0.5× capacities for placement, true capacities for reservation) finds no backup at any cap in that scope; in the whole-fleet scope both procedures succeed down to 4.8 GB, with the headroom variants failing earlier (0.75 below 6.5 GB, 0.5 below 5 GB). The abstract's feasibility claim now carries the scope qualifier.

## 6. Coded-computation literature (R2-C2, R3-M7)
**C** §Related Work (Parity) opens with the lineage: coded computation (Lee et al., IEEE T-IT 2018), Parity Models (SOSP 2019), EC-Cache (OSDI 2016), regenerating codes (Dimakis et al., IEEE T-IT 2010), and positions KV-CARE's coded unit and repair read against them. Bibliography entries added (please verify volume/page fields before submission).

## 7. IoT motivation vs. wired-LAN evaluation (R0-M, R3-C1)
**A** The constrained links motivate keeping inference on site; the pipeline itself runs on the site's local network. Lossy intra-site links were not measured **[limitation]**.
**C** §Introduction clarifies the on-site/local-network distinction; Limitations add lossy or intermittent links and the failure mode they induce (contract failure → replay).

## 8. Other MAJOR items
- R2-MAJOR-3 (R undefined): R:S→D defined in §Design overview. — R2-MAJOR-4 (DP exactness): exact for throughput/latency modes, heuristic for blended; ψ/R alternation labeled a heuristic.
- R3-M1/M2 (coordinator sizing, 24/7 memory): 12.4 GiB reservation stated; coordinator memory scaling with concurrency and context named in Limitations **[limitation]**.
- R3-M3/R1-M6 (Petals crossover): §Latency reports the P≈10 crossover and that Petals is faster below it.
- R2-MAJOR-11/R3-M5 (Reconfigure composition): §Latency decomposes the logged trial (≈250 s re-profiling, ≈130 s cold-load/rewire).
- R3-M10/R2-MAJOR-8 (re-protection): Limitations state that the promoted backup serves unprotected until the mapping is re-solved **[limitation]**.
- DA-C8 (an AGX could host the model): §Setup states it and attributes the six-stage pipeline to the scheduler's throughput objective.
- DA alternatives (quantized replica): Discussion notes the trade against bit-exactness.
- R1-M15 (baseline naming): §Setup states that Petals/DejaVu name re-implemented mechanisms.
- R0 (Index Terms): "Internet of Things" added.

## Not addressed (require the testbed) — stated as limitations
Reconfigure n≥3 at 7B; longer prompts and concurrency; kill/OOM and random-timing injection; detection-inclusive latency; lossy-link runs; CUDA-vs-CUDA fidelity probe; sequential second failure / re-protection; energy.
