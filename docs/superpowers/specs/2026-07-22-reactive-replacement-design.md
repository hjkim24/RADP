# Reactive Re-placement Baseline for RADP — Design Spec

**Date:** 2026-07-22
**Status:** approved (brainstorming) → ready for writing-plans

## Goal

Add a **reactive re-placement** fault-tolerance baseline on the live Jetson
fleet: the "no proactive backup" operating point. On failure it tears down,
re-solves the layer placement over the survivors with the real Recovery-Aware
DP, cold-reloads them, and replays the request from position 0. It sits as the
fourth line on the TTR(P) comparison (and an anchor on the 2-D Pareto) beside
full-replay / surgical / parity / replicate, showing what a failure costs when
you have NOT pre-placed a warm backup (R = {}).

## Why this name, not "cold-restart"

The mechanism does **not** restart the crashed worker — the victim is removed
permanently and the *survivors* reconfigure. Calling it "cold-restart" is
inaccurate (nothing is restarted at the victim; it is a re-placement of layers
over the remaining workers). The name **reactive re-placement** states the point
directly and contrasts with the paper's thesis: the Recovery-Aware DP places the
backup (R) *proactively*; this baseline re-solves placement *reactively* at
failure time, cold. The comparison axis becomes **proactive recovery (ours) vs
reactive re-placement (baseline)**.

The existing in-process `run_b1_cold_restart` is renamed to match.

## What the comparison means (honesty gate)

All four methods are measured on the **same TTR(P) axis, same fault (interior
victim on-1 crashing at position P), same TTR taxonomy** (wall from crash to
recovered token, minus the healthy reference wall), and same correctness
requirement (recovered sequence == healthy reference). They are directly
comparable on that axis.

But they occupy **different points in the ψ+R design space**:

| Method | Backup R | Steady-state cost | Recovery cost |
|---|---|---|---|
| surgical / parity / replicate | pre-placed (warm) | backup memory / KV shipping | sub-second |
| reactive re-placement | none (R = {}) | zero | full reconfiguration (~30 s+) |

Reactive re-placement is the "no recovery-aware placement" baseline. Its TTR is
dominated by the survivors' model reload (~30 s on Jetson), ~100× the recovery
methods — so the shared TTR(P) plot MUST use the existing log y-axis. On the
KV-storage 2-D Pareto it stores 0 KV (like full-replay) but sits far higher on
TTR; its natural framing is the TTR(P) line as the "no-backup anchor," so it is
presented primarily there.

## The wait_for_workers constraint (why config manipulation is required)

`ProfileOrchestrator.wait_for_workers` builds `expected =
set(self.worker_addresses.keys())` and **raises TimeoutError unless every
expected worker heartbeats** (`radp/coordinator/profile_orchestrator.py:67`).
So merely stopping the victim and restarting the coordinator would hang
auto_schedule (the victim stays in `expected`, never heartbeats → timeout →
coordinator never comes up).

Therefore the victim must be removed from the coordinator's **expected worker
set** — i.e. from the rendered `cluster.yaml` `workers:` list — before the
coordinator restarts. This mirrors real ops: mark the dead node out of the
cluster inventory, then the scheduler reconfigures over the rest. It is a
config change, **not** a coordinator/gateway code change.

## Architecture

Reactive re-placement is a **driver-orchestrated experiment line, not a
coordinator recovery_mode.** surgical/parity/replicate are gateway recovery
branches; this is an external sequence that (1) makes the victim absent, (2)
excludes it from the coordinator's expected set, (3) restarts the coordinator so
its own auto_schedule re-solves over survivors and LoadStage-reloads them, (4)
replays from position 0. **The gateway and coordinator code are unchanged** —
the only additions are one Jinja conditional in the deploy template and driver
orchestration.

```
in-process (correctness): run_reactive_replacement   (renamed from run_b1_cold_restart)
                          uniform-greedy re-split as a STAND-IN for the DP
fleet (cost):             b1_ft_fleet.py reactive-replacement path
                          real DP re-solve over survivors via auto_schedule-on-restart
```

## Scope

**In scope:**
- Rename `run_b1_cold_restart` → `run_reactive_replacement` (in-process), result
  label `"reactive-replacement"`, honest docstring; update `run_all`, REPORT,
  PHASES references.
- `cluster.yaml.j2`: `workers:` loop gains `if h not in (excluded_workers |
  default([]))` so the coordinator's expected set can exclude the victim.
- Fleet driver (`b1_ft_fleet.py`): ansible helpers to down/up the victim worker
  and to re-render+restart the coordinator excluding/including the victim; a
  `run_reactive_replacement_trial` measurement path; a measurement-integrity
  gate confirming the reconfiguration ran over survivors.
- Figures: `reactive_replacement` color in `SUBJECT`; a reactive line on the
  TTR(P) log plot; a reactive point on the 2-D Pareto.

**Out of scope:**
- Any change to `_recover_*` / gateway / coordinator Python code.
- The A variant (same-worker restart) — rejected in brainstorming (optimistic;
  reactive re-placement is the honest no-spare edge cost).
- Making the in-process re-solve use the real DP — it has no per-device profiles
  (all in-process workers are identical stubs), so the DP would degenerate to
  the uniform split it already computes; the fidelity split (heuristic in-process
  / real DP on fleet) is documented, not closed.

## Components

### A. In-process rename — `experiments/b1_ft_baselines.py`

- `run_b1_cold_restart` → `run_reactive_replacement`; `BaselineResult(name=
  "B1-cold-restart")` → `name="reactive-replacement"`.
- Docstring: state the new term AND that the in-process re-solve
  (`resolve_excluding` → `greedy_placement`, uniform weight) is a **stand-in**
  for the Recovery-Aware DP, which the fleet variant runs for real over profiled
  survivors. Do not hide the fidelity difference.
- Update `run_all`'s lines list and any callers.
- `resolve_excluding` / `greedy_placement` logic unchanged.

### B. Deploy template — `deploy/roles/radp-coordinator/templates/cluster.yaml.j2`

Change the workers loop from `{% for h in groups['workers'] %}` to:

```jinja
{% for h in groups['workers'] if h not in (excluded_workers | default([])) %}
```

`excluded_workers` holds **ansible inventory host names** (e.g. `on-1`), not
device_ids — the loop iterates `groups['workers']`, whose members are inventory
hosts, so `h` is a host name. Rendering with `-e '{"excluded_workers":["on-1"]}'`
drops the victim from the coordinator's expected set; rendering with the default
empty list restores the full set. No other template change.

### C. Fleet driver — `experiments/b1_ft_fleet.py`

Ansible helpers (mirror the existing `set_worker_parity` / `restart_coordinator_
and_wait` style):
- `set_worker_down(host)` / `set_worker_up(host)` — `systemctl stop|start
  radp-worker` on the victim host.
- `exclude_worker_from_coordinator(victim_host)` / `restore_coordinator_workers()`
  — re-render `cluster.yaml` on the coordinator host via ansible with/without
  `excluded_workers`, then restart the coordinator and wait for readiness (reuse
  `restart_coordinator_and_wait`, whose 320 s timeout already covers auto_schedule
  profiling + LoadStage reload over survivors).

Measurement path `run_reactive_replacement_trial(victim_host, position, *,
coord_host, coord_ssh, ssh_key, prompt, max_tokens)`:

```
1. Full coordinator restart (all workers) → auto_schedule over all → run the
   request once cleanly, timed → reference_wall.
2. Arm the compute-time crash at `position` on the victim; run the request; it
   aborts at P.  t_start = crash observation.
3. set_worker_down(victim); exclude_worker_from_coordinator(victim);
   restart coordinator → auto_schedule over survivors → DP re-solve → LoadStage
   reload on survivors.
4. Re-run the request from position 0 on the reconfigured chain.  t_end.
5. ttr_seconds = (t_end - t_start) - reference_wall.
6. restore_coordinator_workers(); set_worker_up(victim).   # experiment hygiene
```

Measurement-integrity gate `_reconfigured_over_survivors(log_text, victim)` —
confirm from the coordinator log that auto_schedule ran over the survivor set
(the post-restart placement does NOT contain the victim, or the "all N workers
heartbeated" line shows N-1). A trial whose reconfiguration did not genuinely
occur is marked invalid and excluded from the fit — the mirror of parity's
`parity_branch_ran` / replicate's `replicate_branch_ran` gate.

Result row: `mode="reactive_replacement"`, `position`, `ttr_seconds`,
`sequence_match` (replayed tokens == reference), `reconfigured` (the gate).
Output `experiments/results/b1_ft_fleet_reactive.json`.

Positions: full sweep `4,8,16,24,32` for a complete line; **single P=32 anchor
is the acceptable fallback** if fleet fragility (per-trial coordinator restart +
profiling + reload + config re-render ×2) makes the full sweep impractical — the
reload dominates so the line is nearly flat regardless. Log which was run.

### D. Figures — `paper/figures/`

- `_slide.py` `SUBJECT`: add `reactive_replacement` in a muted/dark tone
  distinct from the other four (it is a baseline, not a highlight) — e.g.
  `#595959`; exact hex at implementation.
- `make_recovery_ttr_slide.py`: add a `reactive_replacement` line, gated on
  `reconfigured` the same way replicate is gated on `replicate_branch_ran`; keep
  the log y-axis and normal-decode-step reference line; guard the JSON load so
  the plot still renders with the reactive JSON absent.
- `make_recovery_2d.py`: add the reactive point (0 KV storage, its measured TTR).

## Measurement integrity (binding)

- A reactive-replacement trial's TTR is published only when
  `_reconfigured_over_survivors` confirms the coordinator genuinely re-solved
  over survivors — no silent no-op mislabeled as reactive re-placement.
- Recovered sequence must equal the healthy reference (`sequence_match`), same
  correctness bar as every other line.
- Only facts a run actually produced go in the figures; no fabricated numbers.

## Testing

- **In-process (correctness gate):** the renamed `run_reactive_replacement`
  still yields `sequence_matches_reference=true`, `aborted=false` in the
  in-process baseline driver. The rename must not break the mechanism. (Correct
  tokens after re-solve+replay is placement-algorithm-independent, so the uniform
  stand-in is a valid correctness check.)
- **Template render check:** `cluster.yaml.j2` renders the correct `workers:`
  list with `excluded_workers` set (victim absent) and unset (full set) — a
  focused render assertion, no fleet needed.
- **Fleet:** manual / controller-run, no unit test (like the replicate sweep).
  The `_reconfigured_over_survivors` gate is verified by a fleet smoke before the
  sweep.

## Files

- Modify: `experiments/b1_ft_baselines.py` (rename + docstring + run_all),
  `deploy/roles/radp-coordinator/templates/cluster.yaml.j2` (one conditional),
  `experiments/b1_ft_fleet.py` (helpers + reactive path + gate),
  `paper/figures/_slide.py` (SUBJECT color),
  `paper/figures/make_recovery_ttr_slide.py` (reactive line),
  `paper/figures/make_recovery_2d.py` (reactive point),
  `experiments/REPORT.md` + `RADP/PHASES.md` (rename references + new §).
- No new proto, no gateway/coordinator code change, no generated stubs.

## Global constraints (from the repo)

- Gateway/coordinator Python code is UNCHANGED — the feature is driver
  orchestration plus one Jinja conditional.
- Generated `*_pb2.py` are gitignored — never committed.
- Correctness bar: recovered sequence == healthy reference on every trial.
- Measurement integrity: publish a reactive TTR only when the reconfiguration
  provably ran over survivors.
- Figures follow `ppt/DESIGN_SYSTEM.md` §7 (slide scale, deck palette, English
  in-figure text) and the log y-axis is required (reactive is ~100× the recovery
  methods).
- Fleet operations are controller-run with user awareness (fault injection +
  worker stop/start + coordinator reconfiguration on live hardware).
