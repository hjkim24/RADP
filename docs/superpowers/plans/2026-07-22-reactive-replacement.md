# Reactive Re-placement Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reactive re-placement FT baseline — the no-proactive-backup (R={}) operating point where, on failure, the coordinator re-solves layer placement over survivors with the real Recovery-Aware DP, cold-reloads them, and the request replays from position 0 — as the 4th line on the TTR(P) / 2-D Pareto comparison.

**Architecture:** Least-invasive: an additive scheduler toggle (`backup_placement=False` → R={}), an additive coordinator `reconfigure_over_survivors()` + `POST /api/reconfigure` endpoint on the existing web_api, and a driver-orchestrated fleet measurement over HTTP. The gateway `_recover_*` recovery paths and `recovery_mode` are UNCHANGED. Fairness with the autonomous recovery lines is at the measurement definition (`TTR = wall(crash→recovered) − reference`), not the implementation.

**Tech Stack:** Python 3, FastAPI (existing web_api), the existing Recovery-Aware DP scheduler, pytest, matplotlib. No new proto, no gateway recovery change.

## Global Constraints

- Gateway `_recover_*` / recovery dispatch / `recovery_mode` are UNCHANGED — the feature is an additive scheduler toggle + coordinator reconfigure capability + endpoint + driver orchestration.
- Generated `*_pb2.py` / `*_pb2_grpc.py` are gitignored — never commit them.
- Correctness bar: the recovered (replayed) sequence must equal the healthy reference on every trial.
- Measurement integrity: publish a reactive TTR only when the post-reconfigure placement provably excludes the victim (`_reconfigured_over_survivors`), mirroring parity's `parity_branch_ran` / replicate's `replicate_branch_ran`.
- `backup_placement` defaults to True everywhere — every existing run's behavior is unchanged; only the reactive line deploys with it False.
- Figures follow `ppt/DESIGN_SYSTEM.md` §7 (slide scale, deck palette, English in-figure text); the TTR(P) plot's log y-axis is required (reactive is ~100× the recovery methods).
- Fleet operations are controller-run with user awareness.

---

### Task 1: In-process rename — run_reactive_replacement

**Files:**
- Modify: `experiments/b1_ft_baselines.py` (`run_b1_cold_restart`, `run_all`)

**Interfaces:**
- Produces: `run_reactive_replacement(*, prompt, max_tokens, kill_after_tokens, reference, reference_wall) -> BaselineResult` with `BaselineResult.name == "reactive-replacement"`.

- [ ] **Step 1: Rename the function and result label**

In `experiments/b1_ft_baselines.py`, rename `def run_b1_cold_restart(` → `def run_reactive_replacement(` (signature unchanged). Change its `BaselineResult(name="B1-cold-restart", ...)` to `name="reactive-replacement"`.

- [ ] **Step 2: Update the docstring to the new term + honest fidelity note**

Replace the function's docstring with:

```python
    """Reactive re-placement baseline: no proactive backup (R={}). On the SAME
    mid-stage crash, the first attempt aborts (no backup to promote). Recovery
    then RE-SOLVES a placement over the survivors, redeploys the model on them,
    wires a fresh chain, and re-runs generation from scratch (full model reload
    IS the cost). ``ttr_seconds`` is the whole re-placement's wall-clock minus
    the healthy ``reference_wall``, per the TTR taxonomy.

    Fidelity note: in-process there are no per-device profiles (all workers are
    identical stubs), so ``resolve_excluding`` uses a uniform greedy re-split as
    a STAND-IN for the Recovery-Aware DP. The fleet variant runs the real DP
    over profiled survivors (see the reactive-replacement fleet path). This
    in-process test verifies the mechanism's CORRECTNESS (re-solve + replay →
    reference tokens), which is placement-algorithm-independent; the real cost
    is measured on the fleet.
    """
```

- [ ] **Step 3: Update run_all and any callers**

In `run_all`, change the `run_b1_cold_restart(...)` entry in the `lines = [...]` list to `run_reactive_replacement(...)` (same kwargs). Grep the file for any other `run_b1_cold_restart` reference and update it: `grep -n run_b1_cold_restart experiments/b1_ft_baselines.py` must return nothing after this step.

- [ ] **Step 4: Run the in-process baseline driver to confirm the rename works**

Run: `.venv-py39/bin/python experiments/b1_ft_baselines.py --max-tokens 12 --kill-after-tokens 4 --out /tmp/b1_reactive_check`
Expected: prints `wrote ...`; the JSON has a line with `name: "reactive-replacement"`, `sequence_matches_reference: true`, `aborted: false`. (Uses `.venv-py39` — this driver deploys opt-125m.)

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py
git commit -m "refactor(baselines): rename cold-restart -> reactive_replacement (in-process)"
```

---

### Task 2: Scheduler backup_placement toggle (R={} regime)

**Files:**
- Modify: `radp/common/types.py` (`ClusterSpec`)
- Modify: `radp/coordinator/scheduler.py` (`solve_alternating`)
- Test: `tests/test_reactive_replacement.py` (new)

**Interfaces:**
- Consumes: `ClusterSpec` (existing dataclass), `Scheduler(spec)`, `RecoveryTable` (a dict `{DeviceId: DeviceId}`).
- Produces: `ClusterSpec.backup_placement: bool = True`; when False, `Scheduler(spec).solve_alternating_best_order(...)` / `solve_alternating(...)` return an `AlternatingResult` whose `.recovery` is an empty dict.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reactive_replacement.py`:

```python
from radp.coordinator.scheduler import Scheduler
from radp.common.types import (
    ClusterSpec, DeviceProfile, LayerProfile, NetworkProfile, SLO, DeviceId,
)


def _spec(backup_placement: bool) -> ClusterSpec:
    devs = [
        DeviceProfile(id=DeviceId(d), total_memory_bytes=8_000_000_000,
                      compute_throughput=1.0)
        for d in ("a", "b", "c")
    ]
    layers = [LayerProfile(layer_index=i, compute_time={DeviceId("a"): 1.0,
              DeviceId("b"): 1.0, DeviceId("c"): 1.0}, kv_bytes=1000,
              param_bytes=1000) for i in range(6)]
    net = NetworkProfile(pairwise_bandwidth_bytes_per_s={}, default_bandwidth_bytes_per_s=1e9)
    return ClusterSpec(devices=devs, layers=layers, network=net,
                       slo=SLO(ttft_seconds=1.0, tbt_seconds=1.0),
                       backup_placement=backup_placement)


def test_backup_placement_false_gives_empty_recovery():
    result = Scheduler(_spec(backup_placement=False)).solve_alternating_best_order()
    assert result.recovery == {}
    # Ψ still covers all layers over all devices.
    covered = sorted(l for s in result.placement
                     for l in range(int(s.start_layer), int(s.end_layer) + 1))
    assert covered == list(range(1, 7))


def test_backup_placement_true_is_default_and_populates_recovery():
    assert _spec(backup_placement=True).backup_placement is True
    result = Scheduler(_spec(backup_placement=True)).solve_alternating_best_order()
    assert result.recovery != {}   # default path unchanged: backups assigned
```

Note: match the ACTUAL constructor fields of `DeviceProfile`, `LayerProfile`, `NetworkProfile`, `SLO` when you open `radp/common/types.py` — the above shows the shape; use the real field names verbatim (they may differ, e.g. `kv_bytes`/`param_bytes` naming).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reactive_replacement.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'backup_placement'` (the field doesn't exist yet).

- [ ] **Step 3: Add the field to ClusterSpec**

In `radp/common/types.py`, in the `ClusterSpec` dataclass, directly after the `eager_backup: bool = True` field and its docstring, add:

```python
    backup_placement: bool = True
    """If True (default), the scheduler assigns a backup peer per stage (R) via
    ``determine_recovery_table`` — proactive recovery. If False, R is empty
    ({}), the DP solves Ψ with no backup burden, and a stage failure has no
    backup to promote (reactive re-placement baseline). Default True keeps every
    existing run unchanged."""
```

- [ ] **Step 4: Guard the recovery-table derivation in solve_alternating**

In `radp/coordinator/scheduler.py`, in `solve_alternating`, find the loop line:

```python
                r = determine_recovery_table(self.spec, prev_psi)
```

Replace it with:

```python
                r = (determine_recovery_table(self.spec, prev_psi)
                     if self.spec.backup_placement else {})
```

With `r == {}`, the DP runs with no backup burden and Ψ converges without an R to alternate against — the result's recovery is `{}`. No other change to the alternating logic.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reactive_replacement.py -v`
Expected: PASS (2 passed). Then run the existing scheduler suite to confirm the default path is unchanged: `.venv/bin/python -m pytest tests/ -k "schedul or placement or recovery_table" -m "not slow" -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add radp/common/types.py radp/coordinator/scheduler.py tests/test_reactive_replacement.py
git commit -m "feat(scheduler): backup_placement toggle — R={} for reactive re-placement"
```

---

### Task 3: Coordinator reconfigure_over_survivors

**Files:**
- Modify: `radp/coordinator/server.py` (`auto_schedule`, new `reconfigure_over_survivors`)

**Interfaces:**
- Consumes: `self._addr_lookup: dict[DeviceId, str]`, `self.detector`, `self.gateway`, the existing `auto_schedule()` body (ProfileOrchestrator → profiles → `ClusterSpec` → `Scheduler.solve_alternating_best_order` → store `self.placement`/`self.recovery`), `self.deploy()`.
- Produces: `CoordinatorServer.reconfigure_over_survivors(survivors: set[DeviceId]) -> Placement` — re-runs the profiling+DP+deploy over ONLY the survivor workers and returns the new `self.placement`.

The obstacle (spec): `wait_for_workers` waits for every key in the addr set it is given, and a compute-crash victim still heartbeats. So the reconfigure must profile+solve over an addr set restricted to survivors.

- [ ] **Step 1: Extract the profiling+DP core to accept a worker subset**

In `radp/coordinator/server.py`, refactor `auto_schedule()` so its body — from building the `ProfileOrchestrator` through storing `self.placement`/`self.recovery` — becomes a private helper parameterized by the worker addr set:

```python
    def _profile_and_solve(self, addr_lookup: dict[DeviceId, str]) -> "AlternatingResult":
        """Profile the given workers, run the Recovery-Aware DP over them, store
        the result on self.placement/self.recovery, and return it. Shared by
        auto_schedule (full fleet) and reconfigure_over_survivors (survivors)."""
        orch = ProfileOrchestrator(addr_lookup, self.detector)
        records = orch.wait_for_workers(
            timeout_seconds=self.config.profiling_wait_timeout_seconds
        )
        layer_profiles = orch.collect_layer_profiles(
            self.config.model_id,
            warmup=self.config.profiling_layer_warmup,
            repeats=self.config.profiling_layer_repeats,
            seq_length=self.config.profiling_layer_seq_length,
        )
        network = orch.collect_network_profile(
            payload_bytes=self.config.profiling_network_payload_bytes,
            rounds=self.config.profiling_network_rounds,
        )
        devices = ProfileOrchestrator.build_device_profiles(records, layer_profiles)
        # ... (the existing activation_bytes / spec-build / Scheduler call /
        #      placement-cache / self.placement=,self.recovery= block, verbatim
        #      from the current auto_schedule body, using `addr_lookup` in place
        #      of self._addr_lookup where the worker set is referenced) ...
        return result
```

Then `auto_schedule()` becomes: keep its pre-amble (the `if self.detector is None: raise ...` guard and logging), then `return self._profile_and_solve(self._addr_lookup)`. Move the existing body into `_profile_and_solve` unchanged except that every reference to the worker set uses the `addr_lookup` parameter. **Behavior for the full-fleet call must be identical** — the existing fleet auto_schedule is the regression check.

- [ ] **Step 2: Add reconfigure_over_survivors**

Directly after `auto_schedule`, add:

```python
    def reconfigure_over_survivors(self, survivors: set[DeviceId]) -> "Placement":
        """Reactive re-placement: re-run the profiling + Recovery-Aware DP +
        deploy over ONLY the survivor workers, excluding the failed one(s).
        Returns the new placement (which must not contain any excluded device).
        Driver-triggered via POST /api/reconfigure — NOT an autonomous recovery
        path.
        """
        if self.detector is None:
            raise RuntimeError("reconfigure_over_survivors requires start() first")
        surv_lookup = {d: a for d, a in self._addr_lookup.items() if d in survivors}
        if not surv_lookup:
            raise RuntimeError("no survivor workers to reconfigure over")
        log.warning(
            "reactive re-placement: re-solving over %d survivors %s",
            len(surv_lookup), sorted(str(d) for d in surv_lookup),
        )
        self._profile_and_solve(surv_lookup)
        self.deploy()
        return list(self.placement)
```

- [ ] **Step 3: Sanity import + syntax check (no fleet)**

Run: `.venv/bin/python -c "import ast; ast.parse(open('radp/coordinator/server.py').read()); print('ok')"`
Then confirm the module imports without a running fleet: `.venv/bin/python -c "import radp.coordinator.server; print('import ok')"`
Expected: `ok` / `import ok`.

- [ ] **Step 4: Commit**

```bash
git add radp/coordinator/server.py
git commit -m "feat(coord): reconfigure_over_survivors — DP re-solve over survivors"
```

Note: there is no in-process unit test for `reconfigure_over_survivors` — it needs a live `CoordinatorServer` + heartbeating workers (the in-process harness uses `RequestGateway`, not `CoordinatorServer`). It is exercised by the fleet smoke in Task 5. `_profile_and_solve`'s full-fleet path is regression-covered by the existing fleet auto_schedule (Task 5 deploy).

---

### Task 4: web_api POST /api/reconfigure

**Files:**
- Modify: `radp/coordinator/web_api.py` (add the endpoint)
- Test: `tests/test_reactive_replacement.py` (append an endpoint test)

**Interfaces:**
- Consumes: `server.gateway._dead` (set of dead `DeviceId`), `server._addr_lookup` (all worker device ids), `server.reconfigure_over_survivors(survivors)` (Task 3).
- Produces: `POST /api/reconfigure` → `{"survivors": [...], "excluded": [...], "placement": [...]}`.

- [ ] **Step 1: Write the failing endpoint test**

Append to `tests/test_reactive_replacement.py`:

```python
def test_reconfigure_endpoint_excludes_dead(monkeypatch):
    import types as _t
    from fastapi.testclient import TestClient
    from radp.coordinator.web_api import make_app
    from radp.common.types import DeviceId, Stage, LayerIdx

    calls = {}

    class _Gw:
        _dead = {DeviceId("on-1")}

    def _reconfigure(survivors):
        calls["survivors"] = survivors
        return [Stage(LayerIdx(1), LayerIdx(24), DeviceId("on-6"))]

    server = _t.SimpleNamespace(
        gateway=_Gw(),
        _addr_lookup={DeviceId("on-1"): "a", DeviceId("on-6"): "b"},
        reconfigure_over_survivors=_reconfigure,
    )
    client = TestClient(make_app(server))
    resp = client.post("/api/reconfigure")
    assert resp.status_code == 200
    body = resp.json()
    assert body["excluded"] == ["on-1"]
    assert body["survivors"] == ["on-6"]
    assert calls["survivors"] == {DeviceId("on-6")}
```

Match the real `make_app` / request-model conventions when you open `web_api.py` (the existing POST endpoints take a pydantic model or no body; `/api/reconfigure` takes NO body — it derives survivors from `_dead`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reactive_replacement.py::test_reconfigure_endpoint_excludes_dead -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the endpoint**

In `radp/coordinator/web_api.py`, alongside the other `@app.post(...)` routes, add:

```python
    @app.post("/api/reconfigure")
    def post_reconfigure() -> Any:
        """Reactive re-placement: re-solve the layer placement over the CURRENT
        survivors (all workers minus the gateway's dead set) and redeploy. This
        is the driver-triggered baseline path — it does NOT promote a backup
        (that is the surgical/parity/replicate recovery path). Returns the new
        placement so the caller can confirm the failed device is absent.
        """
        gw = server.gateway
        if gw is None:
            return JSONResponse({"detail": "gateway not ready"}, status_code=503)
        dead = set(getattr(gw, "_dead", set()))
        survivors = set(server._addr_lookup.keys()) - dead
        if not survivors:
            return JSONResponse(
                {"detail": "no survivors to reconfigure over"}, status_code=409
            )
        placement = server.reconfigure_over_survivors(survivors)
        return {
            "survivors": sorted(str(d) for d in survivors),
            "excluded": sorted(str(d) for d in dead),
            "placement": [
                {"device": str(s.device), "start": int(s.start_layer),
                 "end": int(s.end_layer)} for s in placement
            ],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reactive_replacement.py -v`
Expected: PASS (all reactive tests: scheduler + endpoint).

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/web_api.py tests/test_reactive_replacement.py
git commit -m "feat(web_api): POST /api/reconfigure — reactive re-placement over survivors"
```

---

### Task 5: Fleet driver — reactive-replacement measurement path (code-only)

**Files:**
- Modify: `experiments/b1_ft_fleet.py`

**Interfaces:**
- Consumes: existing `restart_coordinator_and_wait`, `arm_fault`, `fault_fired`, `fetch_coordinator_log`, `_linfit`; the new `POST /api/reconfigure`.
- Produces: `run_reactive_replacement_trial(...)`, a `reconfigure_over_survivors(coord_http)` helper, `_reconfigured_over_survivors(placement, victim)` gate; a `reactive_replacement` mode in the sweep.

This runs against live hardware; no unit test. Deliverable = the driver code + a documented dry-run. **Do NOT run a live sweep** (controller-run later).

- [ ] **Step 1: Add the reconfigure HTTP helper and the gate**

Add to `experiments/b1_ft_fleet.py` (near the other helpers). The coordinator's web_api is on `<coord_host>:8080`:

```python
import urllib.request, json as _json

_COORD_WEB_PORT = 8080

def _coord_web(coord_host: str) -> str:
    host = coord_host.split(":")[0]
    return f"http://{host}:{_COORD_WEB_PORT}"

def reconfigure_over_survivors(coord_host: str, timeout: float = 320.0) -> dict:
    """POST /api/reconfigure — coordinator re-solves over survivors + redeploys.
    Returns the response dict (survivors/excluded/placement)."""
    req = urllib.request.Request(
        _coord_web(coord_host) + "/api/reconfigure", method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode())

def _reconfigured_over_survivors(placement: list, victim_device: str) -> bool:
    """Measurement gate: the post-reconfigure placement must NOT contain the
    victim — proof the reactive re-solve genuinely happened over survivors."""
    return all(stage["device"] != victim_device for stage in placement)
```

- [ ] **Step 2: Add run_reactive_replacement_trial**

Add a measurement path that mirrors the taxonomy of the in-process `run_reactive_replacement` (wall − reference) but drives the fleet over HTTP. Reuse the existing generate/crash mechanics of `run_trial` for the healthy-reference and the crash, then call `reconfigure_over_survivors`, then replay. Emit a row:

```python
def run_reactive_replacement_trial(
    coord_host, coord_ssh, ssh_key, victim_host, victim_stage, victim_device,
    *, position, prompt, max_tokens,
) -> dict:
    """One reactive-replacement measurement at failure position P. The
    coordinator MUST be deployed in the R={} regime (backup_placement=False) for
    this line, so the crash aborts (no backup) and /api/reconfigure re-solves.
    TTR = wall(crash -> replayed recovered token) - healthy reference wall.
    """
    # 1. restart coordinator (all workers) + healthy reference request, timed.
    # 2. arm crash at `position`; run the request -> aborts at P (R={}). t_start.
    # 3. resp = reconfigure_over_survivors(coord_host)
    # 4. replay the request from 0 on the reconfigured chain -> t_end, tokens.
    # 5. ttr = (t_end - t_start) - reference_wall
    # 6. return {"mode": "reactive_replacement", "position": position,
    #            "ttr_seconds": ttr, "sequence_match": tokens == reference,
    #            "reconfigured": _reconfigured_over_survivors(resp["placement"],
    #                                                          victim_device),
    #            "fired": ...}
    ...
```

Write the concrete body reusing `run_trial`'s existing reference/crash/replay plumbing (open the file and follow that function's structure); the placeholder `...` above is the shape, not the deliverable — the committed code must be complete.

- [ ] **Step 3: Wire "reactive_replacement" into the sweep and the fit gate**

Allow `"reactive_replacement"` in the CLI `--modes`. When that mode is swept, call `run_reactive_replacement_trial` instead of `run_trial`, and gate a trial's validity/fit inclusion on `reconfigured` the exact way parity is gated on `parity_branch_ran` and replicate on `replicate_branch_ran` (mutually-exclusive per-mode branch, no leak into other modes). Output `experiments/results/b1_ft_fleet_reactive.json`.

- [ ] **Step 4: Static verification (NO live sweep)**

Run: `.venv/bin/python -c "import ast; ast.parse(open('experiments/b1_ft_fleet.py').read()); print('ok')"`
Run: `.venv/bin/python experiments/b1_ft_fleet.py --help` → `--modes` accepts `reactive_replacement`.
Do NOT run a live `--modes reactive_replacement` sweep (controller-run later, and it needs the R={} deploy).

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_fleet.py
git commit -m "feat(replicate): fleet reactive-replacement path + reconfigure gate (code-only)"
```

---

### Task 6: Figures — reactive line + Pareto point

**Files:**
- Modify: `paper/figures/_slide.py` (`SUBJECT`), `paper/figures/make_recovery_ttr_slide.py`, `paper/figures/make_recovery_2d.py`

**Interfaces:**
- Consumes: `SUBJECT`, the results JSONs; `reconfigured` gate field.
- Produces: `reactive_replacement` color; a reactive line on the TTR(P) log plot; a reactive point on the 2-D Pareto. **Written-only** (measured JSON `b1_ft_fleet_reactive.json` is produced by the deferred controller-run sweep).

- [ ] **Step 1: Add the color**

In `paper/figures/_slide.py`, in the `SUBJECT` dict add:

```python
    "reactive_replacement": "#595959",  # baseline anchor — muted grey, distinct
```

- [ ] **Step 2: Add the reactive line to the TTR(P) plot (guarded, gated)**

In `paper/figures/make_recovery_ttr_slide.py`: add a `"reactive_replacement"` entry to `STYLE` (`(SUBJECT["reactive_replacement"], "v", "reactive")`), load `b1_ft_fleet_reactive.json` alongside the others **guarded by `if path.exists()`** so the plot still renders when it's absent, and in `valid(t)` add the clause `and (t["mode"] != "reactive_replacement" or t.get("reconfigured"))`. Keep the log y-axis and the normal-decode-step reference line.

- [ ] **Step 3: Add the reactive point to the 2-D Pareto**

In `paper/figures/make_recovery_2d.py`: add a reactive point `("reactive", ttr_at(rea, "reactive_replacement"), 0, SUBJECT["reactive_replacement"], "v")` where `rea = json.load(...b1_ft_fleet_reactive.json)`; its storage y is 0 (stores no KV). Guard the load; extend `ttr_at`'s gate so reactive requires `reconfigured` (mirror the parity/replicate `*_branch_ran` gate already added). Top-of-file comment: `# reactive point generated after the controller-run reactive sweep produces b1_ft_fleet_reactive.json`.

- [ ] **Step 4: Verify the existing figures still render with the reactive JSON absent**

Run: `.venv/bin/python paper/figures/make_recovery_ttr_slide.py` → still produces the existing lines, no crash.
Run: `.venv/bin/python -c "import ast; ast.parse(open('paper/figures/make_recovery_2d.py').read()); print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add paper/figures/_slide.py paper/figures/make_recovery_ttr_slide.py paper/figures/make_recovery_2d.py
git commit -m "feat(figures): reactive-replacement line + Pareto point (deferred generation)"
```

---

## Notes for the implementer

- **Never touch `gateway._recover_*`, the recovery dispatch, or `recovery_mode`.** Reactive re-placement is a scheduler toggle + a coordinator reconfigure capability + an endpoint + driver orchestration. If you find yourself editing `_recover_parity`/`_recover_surgical`/`_recover_replicate` or adding a `recovery_mode` value, stop — that is out of scope and contradicts the spec.
- **`backup_placement` defaults True.** Every existing run must be byte-for-byte unaffected. Only the reactive fleet line deploys with it False.
- **`_profile_and_solve` extraction (Task 3) must be behavior-preserving for the full-fleet call.** The existing fleet auto_schedule is the regression net; the extraction only parameterizes the worker set.
- The fleet reactive sweep (running Task 5's path live + generating Task 6's measured figures) is controller-run after this branch merges, with the R={} deploy — like the parity/replicate sweeps.
