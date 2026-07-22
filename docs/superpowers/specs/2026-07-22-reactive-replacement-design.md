# Reactive Re-placement Baseline for RADP — Design Spec

**Date:** 2026-07-22
**Status:** approved (brainstorming) → ready for writing-plans
**Supersedes:** the earlier ansible-orchestration draft of this same file
(rejected: heavier, reintroduced deployment-tooling overhead into the measured
TTR). This is the minimally-invasive web_api version.

## Goal

Add a **reactive re-placement** fault-tolerance baseline: the "no proactive
backup (R = {})" operating point. On failure the coordinator re-solves the layer
placement over the survivors with the real Recovery-Aware DP, cold-reloads them
(LoadStage), and the request is replayed from position 0. It sits as the fourth
line on the TTR(P) comparison (and a point on the 2-D Pareto) beside full-replay
/ surgical / parity / replicate, showing what a failure costs when you have NOT
pre-placed a warm backup.

## Why this name, not "cold-restart"

The victim worker is NOT restarted — the *survivors* reconfigure. "Cold-restart"
is inaccurate. **Reactive re-placement** states the thesis contrast: the
Recovery-Aware DP places the backup (R) *proactively*; this baseline re-solves
placement *reactively* at failure time, cold. The paper axis becomes **proactive
recovery (ours) vs reactive re-placement (baseline)**. The in-process
`run_b1_cold_restart` is renamed to match.

## What it is — a BASELINE, measured with minimal code

Reactive re-placement is a baseline we measure, NOT a self-healing feature we
ship. So it must be built with the **least invasive** code that still yields a
fair measurement:

- **No gateway `_recover_*` change**, no new `recovery_mode` value — the
  recovery-dispatch and the surgical/parity/replicate paths are untouched.
- The trigger is **driver-initiated** (an operator/script reconfiguring a dead
  cluster is exactly what a no-recovery baseline models), via one **additive**
  HTTP endpoint on the coordinator's existing web_api.
- Fairness with the autonomous recovery lines is achieved at the **measurement
  definition**, not the implementation: all four use `TTR = wall(crash →
  recovered token) − healthy reference wall`, the same taxonomy the in-process
  cold-restart already used. Whether the trigger is coordinator-autonomous
  (surgical/parity/replicate) or driver-issued (reactive) is orchestration, not
  a measured quantity.

## Enabling facts (verified in code)

- The fleet coordinator runs its FastAPI **web_api on :8080** (`RADP_WEB_PORT`,
  confirmed LISTENing on ax-1). It already exposes `POST /api/generate`,
  `POST /api/inject_failure` (→ `gw.mark_dead`; with R={} the next Generate
  raises `NoRecoveryError`), `POST /api/revive_device`, `POST /api/clear_all_
  failures`, `GET /api/cluster`.
- `auto_schedule()` stores its result on `self.placement`/`self.recovery` and is
  gated by a **device-set-keyed placement cache**, so re-running it over a
  different (survivor) worker set is a cache miss → real DP re-solve, no stale
  full-fleet plan. `deploy()` reads `self.placement` and pushes LoadStage.
- The obstacle: `ProfileOrchestrator.wait_for_workers` builds `expected =
  set(worker_addresses.keys())` and raises unless ALL heartbeat. A compute-crash
  victim stays alive (still heartbeats) but is in the gateway's `_dead` set.
  So the reconfigure must run auto_schedule over an **explicit survivor set =
  all workers − `gateway._dead`**, waiting only for those.

## Architecture

```
in-process (correctness):  run_reactive_replacement   (renamed from run_b1_cold_restart)
                           uniform-greedy re-split as a STAND-IN for the DP
fleet (cost):              driver drives the coordinator over web_api :8080
                           POST /api/reconfigure runs the real DP over survivors
```

Fleet driver flow (all HTTP, no ansible, no coordinator restart):

```
deploy coordinator in the R={} (no-backup) regime          # reactive's identity
POST /api/generate                 → healthy reference      → reference_wall
run Generate with the compute-crash armed at position P
   → crash at P → R={} → NoRecoveryError → request aborts   → t_start
POST /api/reconfigure              → survivors = workers − gw._dead
                                     → auto_schedule(survivors) + deploy
                                     → LoadStage reload on survivors (dominant cost)
POST /api/generate                 → replay from position 0 → t_end
ttr = (t_end − t_start) − reference_wall
restore for next trial (revive victim + redeploy full)
```

## Scope

**In scope:**
- Rename `run_b1_cold_restart` → `run_reactive_replacement` (in-process), result
  label `"reactive-replacement"`, honest docstring; update `run_all`, REPORT,
  PHASES references.
- Coordinator: a `reconfigure_over_survivors()` capability (re-run the
  profiling+DP+deploy over an explicit survivor set) + a `POST /api/reconfigure`
  endpoint that computes survivors from `gateway._dead` and calls it. **No
  gateway `_recover_*` change, no new recovery_mode.**
- Fleet driver (`experiments/b1_ft_fleet.py` or a sibling): a
  `run_reactive_replacement_trial` measurement path over web_api, a driver
  helper for the reconfigure call, and a measurement-integrity gate.
- Figures: `reactive_replacement` color in `SUBJECT`; a reactive line on the
  TTR(P) log plot; a reactive point on the 2-D Pareto.

**Out of scope (rejected in brainstorming, recorded so they aren't reopened):**
- A coordinator-autonomous `recovery_mode="reactive_replacement"` (catch
  NoRecoveryError in the Generate handler → reconfigure → retry). More faithful
  as a *feature*, but it touches the production recovery path for a baseline we
  do not ship — YAGNI + risk. The measurement-definition unification gives a
  fair comparison without it.
- Same-worker restart (A variant) — optimistic; rejected earlier.
- ansible / cluster.yaml template manipulation / coordinator process restart —
  the earlier draft's approach, superseded by the web_api path (which also keeps
  deployment-tooling overhead out of the measured TTR).
- Making the in-process re-solve use the real DP — no per-device profiles on
  identical in-process stubs; the DP would degenerate to the uniform split it
  already computes. The fidelity split (heuristic in-process / real DP on fleet)
  is documented, not closed.

## Components

### A. In-process rename — `experiments/b1_ft_baselines.py`
- `run_b1_cold_restart` → `run_reactive_replacement`; `BaselineResult(name=
  "B1-cold-restart")` → `name="reactive-replacement"`.
- Docstring: new term + explicit note that the in-process re-solve
  (`resolve_excluding` → `greedy_placement`, uniform weight) is a **stand-in**
  for the Recovery-Aware DP the fleet runs for real over profiled survivors.
- Update `run_all` and any callers. `resolve_excluding`/`greedy_placement`
  logic unchanged.

### B. Coordinator — `radp/coordinator/server.py` + `web_api.py`
- `server.py`: extract the profiling+DP+deploy core of `auto_schedule` so it can
  run over an **explicit worker subset**, and add
  `reconfigure_over_survivors(survivors: set[DeviceId])` that runs it for the
  given survivors and re-deploys. `auto_schedule()` keeps its current behavior
  (full set) by delegating to the same core. `wait_for_workers` is called with
  the survivor subset, so it waits only for them.
- `web_api.py`: add `POST /api/reconfigure` (mirrors the existing POST
  endpoints) — reads `server.gateway._dead`, computes `survivors =
  set(all workers) − _dead`, calls `server.reconfigure_over_survivors(survivors)`,
  returns the new placement (so the driver can confirm the victim is absent).
- **No change to `gateway._recover_*`, the recovery dispatch, or recovery_mode.**

### C. Fleet driver — `experiments/b1_ft_fleet.py`
- Helper `reconfigure_over_survivors(coord_web_addr)` → `POST /api/reconfigure`;
  the driver already restarts the coordinator per trial and can drive
  `/api/generate` + the compute-crash drop-in.
- `run_reactive_replacement_trial(victim, position, ...)` implementing the flow
  above; the coordinator is deployed in the **R={} regime** for this line.
  R={} is reactive re-placement's identity: with a backup present the coordinator
  would promote it (surgical/parity/replicate style) instead of reconfiguring, so
  no backup must exist. **Constraint: it must stay AUTO mode** — `/api/reconfigure`
  re-runs the auto scheduler's DP over survivors, which manual mode does not have.
  So the regime is *auto mode with backup placement disabled* (ψ solved, R = {}),
  NOT manual mode. **Verified: no such flag exists today** — `eager_backup=False`
  only makes backups *lazy* (R still assigned), and the scheduler always calls
  `determine_recovery_table`. So this line adds a small, additive scheduler
  option (e.g. `backup_placement: bool = True`; when False, skip
  `determine_recovery_table` and return an empty RecoveryTable). Default True
  keeps every existing run's behavior unchanged; the DP (ψ) is untouched. Only
  the reactive line deploys with it False. This is the one new bit of
  coordinator/scheduler code beyond the reconfigure endpoint, and it is additive
  (a guarded skip), not a change to existing recovery logic.
- Measurement-integrity gate `_reconfigured_over_survivors(reconfigure_response
  or /api/cluster, victim)` — the post-reconfigure placement must NOT contain the
  victim. A trial whose reconfigure did not genuinely re-place over survivors is
  marked invalid and excluded from the fit — the mirror of parity's
  `parity_branch_ran` / replicate's `replicate_branch_ran`.
- Result row: `mode="reactive_replacement"`, `position`, `ttr_seconds`,
  `sequence_match` (replayed tokens == reference), `reconfigured` (the gate).
  Output `experiments/results/b1_ft_fleet_reactive.json`.
- Positions: full sweep `4,8,16,24,32` for a complete line; **single P=32 anchor
  is the acceptable fallback** if fleet fragility makes the sweep impractical
  (the reload dominates, so the line is nearly flat). Log which was run.

### D. Figures — `paper/figures/`
- `_slide.py` `SUBJECT`: add `reactive_replacement` in a muted/dark tone distinct
  from the other four (a baseline, not a highlight) — e.g. `#595959`; exact hex
  at implementation.
- `make_recovery_ttr_slide.py`: add a `reactive_replacement` line, gated on
  `reconfigured` the way replicate is gated on `replicate_branch_ran`; keep the
  log y-axis (reactive is ~100× the recovery methods) and the normal-decode-step
  reference line; guard the JSON load so the plot still renders when the reactive
  JSON is absent.
- `make_recovery_2d.py`: add the reactive point (0 KV storage, its measured TTR).

## What the comparison means (honesty gate)

All four are measured on the **same TTR(P) axis, same fault (interior victim
crashing at position P), same TTR taxonomy** (`wall(crash → recovered token) −
reference wall`), same correctness bar (recovered sequence == reference). They
are directly comparable there.

They occupy **different ψ+R operating points**: surgical/parity/replicate exploit
a pre-placed warm backup (R present); reactive re-placement has none (R = {}) and
pays a full cold reconfiguration at failure time (~30 s, dominated by survivor
model reload — ~100× the recovery methods, hence the log y-axis). Reactive is the
"no recovery-aware placement" baseline; its natural home is the TTR(P) line as
the no-backup anchor. On the KV-storage 2-D Pareto it stores 0 KV (with
full-replay) but sits far higher on TTR.

## Measurement integrity (binding)
- A reactive-replacement trial's TTR is published only when the post-reconfigure
  placement provably excludes the victim (`_reconfigured_over_survivors`) — no
  silent no-op mislabeled as reactive re-placement.
- Recovered sequence must equal the healthy reference on every trial.
- Only facts a run actually produced go in the figures; no fabricated numbers.

## Testing
- **In-process (correctness gate):** the renamed `run_reactive_replacement`
  still yields `sequence_matches_reference=true`, `aborted=false`. The rename
  must not break the mechanism (correct tokens after re-solve+replay is
  placement-algorithm-independent, so the uniform stand-in is a valid check).
- **Coordinator unit:** `reconfigure_over_survivors(survivors)` produces a
  placement that (a) omits the excluded victim and (b) covers all layers over the
  survivors — testable against the scheduler with a small synthetic device set,
  no fleet needed. `POST /api/reconfigure` computes survivors from `_dead`
  correctly (a focused API test with a stub gateway).
- **Fleet:** manual / controller-run, no unit test (like the replicate sweep).
  The `_reconfigured_over_survivors` gate is verified by a fleet smoke before the
  sweep.

## Files
- Modify: `experiments/b1_ft_baselines.py` (rename + docstring + run_all),
  `radp/coordinator/server.py` (extract core + `reconfigure_over_survivors`),
  `radp/coordinator/scheduler.py` (additive `backup_placement` toggle → R={}),
  `radp/coordinator/web_api.py` (`POST /api/reconfigure`),
  `experiments/b1_ft_fleet.py` (reactive path + helper + gate),
  `paper/figures/_slide.py`, `paper/figures/make_recovery_ttr_slide.py`,
  `paper/figures/make_recovery_2d.py`,
  `experiments/REPORT.md` + `RADP/PHASES.md` (rename + new §).
- No new proto, no gateway `_recover_*` change, no generated stubs committed.

## Global constraints (from the repo)
- Gateway `_recover_*` / recovery dispatch / recovery_mode are UNCHANGED — the
  feature is an additive coordinator reconfigure capability + endpoint + driver
  orchestration.
- Generated `*_pb2.py` are gitignored — never committed.
- Correctness bar: recovered sequence == healthy reference on every trial.
- Measurement integrity: publish a reactive TTR only when the reconfigure
  provably re-placed over survivors.
- Figures follow `ppt/DESIGN_SYSTEM.md` §7; the log y-axis is required.
- Fleet operations are controller-run with user awareness (fault injection +
  live reconfiguration on real hardware).
