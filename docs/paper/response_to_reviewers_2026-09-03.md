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
**C** Abstract rewritten: "flat over the measured failure positions", "recovers about one decode step later than replication while retaining 3.7× less coordinator state", "two simultaneous failures at the cost of one when their backups sit on distinct nodes", "with backups confined to pipeline devices … across the memory range in which the model fits", "a protected-stage failure". Conclusion: **not changed in Round 1** (the panel caught this); rewritten in Round 2 with the same qualifiers, plus the 2.7× tail-stage figure beside 3.7×. §Latency now states the O(N) loop, the 2-SE bound on the per-position cost (<12 ms) and that we do not extrapolate beyond P=32; Limitations repeat this.

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
- R3-M1/M2 (coordinator sizing, 24/7 memory): the 12.4 GiB backup-weight reservation is now stated in §Setup (new); the Limitations sentence on coordinator memory scaling with concurrency and context was already in the submitted version and is unchanged **[limitation]**.
- R3-M3/R1-M6 (Petals crossover): §Latency reports the P≈10 crossover and that Petals is faster below it.
- R2-MAJOR-11/R3-M5 (Reconfigure composition): §Latency decomposes the logged trial (≈250 s re-profiling, ≈130 s cold-load/rewire).
- R3-M10/R2-MAJOR-8 (re-protection): Limitations state that the promoted backup serves unprotected until the mapping is re-solved **[limitation]**.
- DA-C8 (an AGX could host the model): §Setup states it and attributes the six-stage pipeline to the scheduler's throughput objective.
- DA alternatives (quantized replica): Discussion notes the trade against bit-exactness.
- R1-M15 (baseline naming): §Setup states that Petals/DejaVu name re-implemented mechanisms.
- R0 (Index Terms): "Internet of Things" added.

## Not addressed (require the testbed) — stated as limitations
Reconfigure n≥3 at 7B; longer prompts and concurrency; kill/OOM and random-timing injection; detection-inclusive latency; lossy-link runs; CUDA-vs-CUDA fidelity probe; sequential second failure / re-protection; energy.  Round 1 stated only the re-protection, lossy-link and fidelity-scope limitations; concurrency, prompt length, energy and heartbeat detection were added to Limitations in Round 2 (see below).

---

# Round 2 — verification re-review (2026-09-03)

The same five reviewers verified Round 1 against the pre-revision file. Panel: R0/R1/R2 Minor (two conditional), R3/DA Major; editorial decision **Major Revision** on three grounds: the Conclusion had not been revised although this letter said it had, the Fig. 2 reading sentence contradicted Table I, and one quantity (350M decode step) carried two values. Fourteen of the fifteen MUST-FIX items are applied below (item 7's disclosure of the earlier five-worker pool is deliberately omitted from the manuscript, since the submitted version never carried the 6.5 GB band); the letter's four unsupported statements (conclusion alignment; energy; concurrency/prompt length; the coordinator item citing a pre-existing sentence) are corrected above.

| # | Item | Change |
|---|---|---|
| 1 | Conclusion (all five) | Rewritten with the abstract's qualifiers: measured positions, coordinator state, ±11% spread, distinct-node backups, pipeline-device backups, protected-stage failure; 3.7× with 2.7× over recovered stages. |
| 2 | Fig. 2 reading sentence (R1, R2, R3, DA) | "retain nothing / matches / alone" replaced by the three-point frontier: Petals retains its inputs and wins below P≈10; DejaVu about one step sooner at the sum of columns; KV-CARE least state among sub-2 s families. Generator docstring updated. |
| 3 | 163 vs 183 ms (all five) | Two named quantities: 163 ms is the recovery sweep's median token interval (the "decode step"); 183 ms is the protection-cost runs' interval. Both stated where used. |
| 4 | Eq. (mem) reserves weights only (DA-C6, R2-C3) | Abstract: "the failed stage's weights have a device to load on"; §Design states that Eq. (mem) charges weights only and recovered KV is request working memory; §I "in one system" softened. |
| 5 | Contract qualifier (DA-C3, R3, R1) | Abstract closing sentence: "a protected-stage failure whose recovery contract holds". |
| 6 | 3.7× / 2.7× (R0, R2, R3, DA) | Abstract and Conclusion carry both. |
| 7 | Six-worker sweep (R1, R2, R3, DA) | §Feasibility: "the six CUDA workers", cap rule M(d)←min(M(d),c), 40 caps from 0.2 to 23 GB. |
| 8 | Figures (R0, R1, R3) | Fig. 1 regenerated: Reconfigure "mean", k=1 labelled, k=2 dashed/hollow; Fig. 2 caption notes Reconfigure at its two-position mean; Fig. 4 y-axis extended so the −11% whisker is visible, tick labels fixed. |
| 9 | "four times the bytes" (R1, DA) | Replaced by "four RPC round trips"; DejaVu replica location (coordinator vs peer in the published design) stated. |
| 10 | Limitations (all five) | Energy; single-request measurements with concurrency and prompt length unvaried; heartbeat detection adds up to 5 s. |
| 11 | Limitations (R1-M12/M13) | Post-recovery degradation of a promoted backup excluded from recovery latency; k=1/k=2 trials differ in victim and backup tier. |
| 12 | Reconfigure n and pairing (R1) | Table I note: one trial at each of P=4 and P=8; the pairing was inverted (P=4→465.8 s, P=8→413.1 s) and is corrected in the table and text; Limitations list the 7B Reconfigure trials as one per position. |
| 13 | 12.4 GiB vs R over protected stages (R1, DA) | R defined over every stage, the head included (its weights are preloaded although its KV is not parity-protected); §Setup says "the head included". |
| 14 | DejaVu slope / k=2 intercept (R1, R2, R3, DA) | "about two standard errors from zero and not modelled" (2.04 SE; Round 2 had written "within two", which was false); k=2 intercept 0.11 s below k=1 "within the fit uncertainty". |
| 15 | This letter | Corrected as above. |

SHOULD-FIX applied: 16 fencing sentence (returning partitioned worker not fenced; R does not model failure domains); 18 iteration bound (ten), enumeration size, growth formula (≈9.8 M ordered subsets at ten devices) and the 122 s solve time stated (Round 3); 19 fidelity column footnote "by construction", CPU tier absent from the 7B fleet; 22 Parity Models and regenerating-code wording corrected, PagedAttention cited, DOIs added to three of the four new entries (EC-Cache is a USENIX paper without a DOI; pages added); 23 heartbeat sentence; 24 parity and replication ship identical bytes; 26 cap rule and grid; 27 "throughput choice; capacity binds on the Nanos"; 28 "kB denotes 1 024 bytes"; 29 §Across Scales restored in compressed form with per-step normalisation (1.01 vs 0.89 steps per position); 32/33 α defined as a configured weight, device set 𝒟, DP cost t(i,j,d); 35 roadmap sentence; 37 "offline placement analysis" in the abstract; 40 ±11% referent.

Not applied — deferred desk work (facts or logs we hold but did not write up this round): 20 environment versions and power mode; 21 per-cell exclusion accounting; 30 rank inheritance after promotion; 41 naming the decomposed Reconfigure trial; 19's relative-error column (the probe recorded absolute differences only). Not applied — page budget (the paper is held at 10 pages): 17 coordinator sizing/availability paragraph; 25 forward-path blocking; 31 GQA/INT4 recomputation; 34 ℓ_max placement term; 38 orphan background file; §II paragraphs on the journal's own edge-reliability literature (R0). Not applied — by choice: 7's note on the earlier five-worker pool (the submitted version never carried the 6.5 GB band); 42's deleted hedge; K22's RAID lineage naming (the paper avoids the RAID name and describes the codes directly). Abstract 258 words; 10 pages.

---

# Round 3 — second verification re-review (2026-09-03)

Panel: R0 Minor (unconditional), R1 Accept subject to minor corrections, R2 Minor (unconditional), R3 Minor, DA Minor conditional on one word. No false statement was found in the Round-2 letter; three completeness overstatements are corrected above. All Round-3 residuals are sentence-scale and applied:

| Item | Reviewers | Change |
|---|---|---|
| R's domain vs 𝒮 (non-head) | R0-N10, R1, R2-N3-1, R3, DA-NEW-2 | §Design overview: R maps every stage, the head included, to a device in 𝒟; "parity protects only the non-head stages 𝒮; the head's backup serves replay". The 12.4 GiB figure stands (DA withdrew its ~10 GiB objection after reading the implementation). |
| Conclusion "recovered state has a device to run on" | R0-N9, R1, R2-N3-2, R3, DA-NEW-4 | "the failed stage's weights have a device to load on". |
| "496 rejected **solely** because no peer could reserve backup weights" | DA (new CRITICAL) | The scheduler pools backup-infeasible and placement-infeasible subsets in one handler, so a sole cause cannot be asserted; now "rejected as infeasible under Eq. (mem), which charges backup reservations beside each device's own stage". |
| "within two standard errors of zero" (DejaVu slope, 2.04 SE) | R1, DA-NEW-1 | "about two standard errors from zero". |
| "spread" is a sample SD | R1 | "round-to-round standard deviation" in §Cost; the abstract and conclusion were then rewritten under S7 to quote "+0.6% (±11% across three rounds)" directly. |
| 350M decode-step range | R1 | 1.6–1.9 → 1.7–1.9. |
| "within two seconds" excludes Petals by 0.31 s | R0-N13, R2 | "within three decode steps". |
| Table I footnote b | R0-N11, R2, R3 | "By construction (unit tests assert byte identity); these trials check sequence match; §Fidelity probes replay". |
| 7B decode step 500 vs 493 ms | R0-N12 | "500 ms (493 ms pooled over the repeated trials)". |
| "same KV columns … not traffic" vs the recovery fetch | R2-N3-3 | Qualified "during failure-free decoding". |
| EC-Cache bibliography | R0, R2 | Pages added (USENIX, no DOI). |

Still not applied: the items listed above under "page budget" and "no data".

Round-3 roadmap items applied after the panel's synthesis (same day): J5 enumeration formula and 122 s solve time; J7 "within three decode steps"; J11 "two to four decode steps" in the abstract and conclusion; J13 non-uniform cap ladder stated; J14 §I premise reconciled ("or one device cannot meet the throughput target"); S3 the prototype's per-position input mirror is retained for every family and charged to Petals alone, with the all-family ratios (3.0×, 42%) stated; S4 Table I note "no valid trial at P=16, 24, 32"; S5 "standard deviation" for the per-position figure; S7 abstract and conclusion now quote "+0.6% (±11% across three rounds)" instead of comparing against the spread; S8 the ±26% 95% interval at three rounds; S9 tolerated-failure sentence; S11 the §IV-F out-of-scope sentence deleted; S12 §IV-E receives the 12.4 GiB reservation. J6 (relative error), J8 (units beyond the table note), J9 (environment), J10 (RAID naming), S10 (journal literature), S13 (rank inheritance) remain on the not-applied lists above.

---

# Round 4 — third verification re-review (2026-09-04)

Panel: R0 Accept subject to editor-verified corrections, R1 Accept subject to two corrections, R2 Accept subject to one clause, R3 Accept subject to one erratum, DA Accept after four clauses. No false change description was found in the Round-3 letter. All items below are applied.

| Item | Reviewers | Change |
|---|---|---|
| "for want of backup room" (§V-A) kept the sole-cause attribution deleted from §IV-E | R1-NEW-13, R2, R3-NEW-1, DA | "as infeasible under Eq. (mem)". |
| "(493 ms pooled over the repeated trials)" was computed over all 75 rows including 15 unfired k=2 rows; the 60 valid trials give 498–500 ms | R0 (withdrawing its own Round-3 N12), R1-NEW-14, DA | Parenthetical deleted; "500 ms" stands. |
| Pareto sentence: "within three decode steps" drew the class 0.08 s above KV-CARE's own point and excluded Petals | R0, DA | Rewritten as endpoints: Petals low-state (40 kB/tok, 2.3 s), DejaVu low-latency at the sum of columns, KV-CARE between (3.7× below DejaVu, about one decode step later). No "least state" claim. |
| §III-A "current position" vs the prototype's per-position mirror history | DA, R3 | §III-A now notes that the prototype keeps the per-position history the replay ladder needs, pointing to §IV-C's accounting. |
| Fig. 1 (new this round; omitted from the Round-3 letter) | R0, R1, R2, R3, DA | Added in §III-A as Fig. 1 (later figures renumbered). Reviewers found it accurate against §III and the code. Applied their suggestions: R drawn asymmetric (one device hosts two backups, one none, as in the live 7B mapping); caption says the shaded head ships no KV column and "retains stage inputs" instead of "the interrupted position's input". |
| Letter scope residuals | R0, R1, R2, R3, DA | This section lists Fig. 1; the stale "spread" row above is corrected; J8 (units beyond the table note) and J10 (RAID naming) are recorded as not applied; J10's exactness novelty clause was applied (§II-E) and is now listed. |

Not applied, unchanged from Round 3: page-budget items (17, 25, 31, 34, 38, journal-literature paragraphs), deferred desk work (20, 21, 30, 41, relative-error column), by choice (5-worker note, deleted hedge, RAID naming, thin-space digit grouping in Table I).
