# B1 Fault-Tolerance Baseline Comparison — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a benchmark that drives RADP and four recovery-strategy baselines through one identical mid-stream worker failure and emits a single comparison record (TTR, correctness, goodput) per line.

**Architecture:** A new self-contained driver module `experiments/b1_ft_baselines.py` reuses the existing in-process cluster harness (`experiments/_harness.py`) and `RequestGateway`. Each baseline is one function returning a `BaselineResult`; a top-level `run_all()` runs them through the same injection and writes one JSON. Development and TDD happen in-process with `facebook/opt-125m`; the confirmed lines port to the real fleet (config A) as the final task.

**Tech Stack:** Python 3.9+, pytest, PyTorch, gRPC, the RADP coordinator/worker packages.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md`. Every task's requirements implicitly include it.
- Baselines: **B0 abort**, **B1 cold-restart**, **B2 no-mirror replay (ablation)**, **B3 redundant hosting**, plus **RADP**.
- Metrics only: **TTR**, **token correctness/completeness**, **goodput under failure**. NOT steady-state overhead, NOT failure diversity, NOT the heterogeneity sweep.
- Failure injection: **single mid-stream SIGKILL** of one chain-interior worker.
- Resolved decisions: B3 rebuilds KV via **replay**; cold-restart TTR **includes** the DP re-solve; fleet config **A** = AGX Orin + Nano CUDA ×3.
- **TTR taxonomy** (defined once, used by every line):
  - *In-place* lines (RADP, B3): TTR = latency of the failed decode step (`recovery_step_seconds`).
  - *Restart* lines (B1, B2): TTR = `total_wall_clock_with_failure − reference_wall_clock` (extra time to recover by restarting).
  - *Abort* line (B0): TTR = `None` (never recovers).
- In-process dev constants: `MODEL_ID = "facebook/opt-125m"`, 3-worker chain `worker-a/b/c` with layers `1-4 / 5-8 / 9-12`, interior victim `worker-b`, `max_tokens=12`, `kill_after_tokens=4`.
- Do NOT commit `experiments/results/*.json` unless already tracked; follow the repo's existing results-tracking convention.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- **Create** `experiments/b1_ft_baselines.py` — driver: `BaselineResult`, config helpers, reference generation, one function per line, `run_all()`, `main()` CLI.
- **Create** `tests/test_b1_ft_baselines.py` — in-process TDD tests (opt-125m, fake cluster).
- **Reuse (no edit)** `experiments/_harness.py` (`in_process_cluster`, `deploy`, `dp_placement_no_recovery`, `write_json`, `greedy_placement`), `radp/coordinator/gateway.py` (`RequestGateway`), `radp/coordinator/scheduler.py` (`Scheduler`).
- **Modify (final task only)** `experiments/run_failure_remote.py` + `experiments/REPORT.md` for the fleet run.

Reference for existing patterns: `experiments/run_failure.py` (`measure_mid_decode_replay`, `measure_e2e_wall_clock` — the `re_prefill` variant disables the mirror via `gw.cache.get_history = lambda *a, **kw: []`).

---

### Task 1: Driver scaffold — `BaselineResult`, config, reference generation

**Files:**
- Create: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Produces:
  - `MODEL_ID: str`
  - `@dataclass BaselineResult(name: str, ttr_seconds: float | None, tokens_completed: int, tokens_requested: int, sequence_matches_reference: bool, goodput_tok_per_s: float, aborted: bool)`
  - `chain_config() -> tuple[list[str], Placement, RecoveryTable, DeviceId]` returning `(device_ids, placement, recovery, victim)`
  - `generate_reference(*, prompt: str, max_tokens: int) -> tuple[list[int], float]` returning `(reference_token_ids, reference_wall_seconds)` on a healthy cluster

- [ ] **Step 1: Write the failing test**

```python
# tests/test_b1_ft_baselines.py
from experiments.b1_ft_baselines import BaselineResult, chain_config, generate_reference


def test_chain_config_has_interior_victim():
    device_ids, placement, recovery, victim = chain_config()
    assert victim == "worker-b"
    # victim is interior: not the first and not the last stage's device
    assert placement[0].device != victim
    assert placement[-1].device != victim
    assert recovery[victim] in device_ids


def test_generate_reference_returns_tokens_and_walltime():
    toks, wall = generate_reference(prompt="The quick brown fox", max_tokens=6)
    assert len(toks) == 6
    assert wall > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'BaselineResult'`.

- [ ] **Step 3: Write minimal implementation**

```python
# experiments/b1_ft_baselines.py
"""B1 — fault-tolerance baseline comparison (spec 2026-07-16).

Drives RADP + four recovery-strategy baselines through one identical
mid-stream worker SIGKILL and reports TTR / correctness / goodput.
See docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from experiments._harness import deploy, in_process_cluster
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.gateway import RequestGateway

MODEL_ID = "facebook/opt-125m"


@dataclass
class BaselineResult:
    name: str
    ttr_seconds: float | None          # None => never recovered (abort)
    tokens_completed: int
    tokens_requested: int
    sequence_matches_reference: bool
    goodput_tok_per_s: float
    aborted: bool


def chain_config() -> tuple[list[str], Placement, RecoveryTable, DeviceId]:
    """3-worker chain with an interior victim (worker-b)."""
    device_ids = ["worker-a", "worker-b", "worker-c"]
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery: RecoveryTable = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }
    return device_ids, placement, recovery, DeviceId("worker-b")


def generate_reference(*, prompt: str, max_tokens: int) -> tuple[list[int], float]:
    """Healthy-cluster run: the correct token sequence + wall-clock baseline."""
    device_ids, placement, recovery, _ = chain_config()
    with in_process_cluster(device_ids) as (addrs, _servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        gw.generate(prompt, max_tokens=2)  # warmup
        t0 = time.perf_counter()
        toks = gw.generate(prompt, max_tokens=max_tokens)
        wall = time.perf_counter() - t0
        gw.close()
    return list(toks), wall
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py -v`
Expected: PASS (both tests). If `generate_reference` is slow, that is acceptable — opt-125m loads once per `in_process_cluster`.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "test(b1): driver scaffold — BaselineResult, chain config, reference gen

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: RADP line (in-place replay)

**Files:**
- Modify: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Consumes: `chain_config`, `generate_reference`, `BaselineResult`, `MODEL_ID`.
- Produces: `run_radp(*, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]) -> BaselineResult`

- [ ] **Step 1: Write the failing test**

```python
from experiments.b1_ft_baselines import run_radp, generate_reference


def test_radp_recovers_full_sequence():
    prompt, max_tokens = "The quick brown fox", 12
    ref, _ = generate_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_radp(prompt=prompt, max_tokens=max_tokens, kill_after_tokens=4, reference=ref)
    assert r.name == "RADP"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True
    assert r.ttr_seconds is not None and r.ttr_seconds > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py::test_radp_recovers_full_sequence -v`
Expected: FAIL with `ImportError: cannot import name 'run_radp'`.

- [ ] **Step 3: Write minimal implementation**

```python
import contextlib


def _drive_inplace(
    *, name: str, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], disable_mirror: bool,
) -> BaselineResult:
    """Manual prefill+decode; kill the interior victim mid-decode; the
    gateway's in-place recovery (mirror replay) fixes the failed step."""
    device_ids, placement, recovery, victim = chain_config()
    with in_process_cluster(device_ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        if disable_mirror:
            gw.cache.get_history = lambda *a, **kw: []  # type: ignore[method-assign]
        gw.generate(prompt, max_tokens=2)  # warmup
        rid = gw.new_request_id()
        ttr: float | None = None
        aborted = False
        toks: list[int] = []
        t_start = time.perf_counter()
        try:
            gw._prefill(rid, prompt)
            for step in range(1, max_tokens):
                if step == kill_after_tokens:
                    servers[victim].stop()
                t0 = time.perf_counter()
                gw._decode_step(rid)
                dt = time.perf_counter() - t0
                if step == kill_after_tokens:
                    ttr = dt
            toks = list(gw._requests[rid].generated_token_ids)
        except Exception:
            aborted = True
            with contextlib.suppress(Exception):
                toks = list(gw._requests[rid].generated_token_ids)
        finally:
            with contextlib.suppress(Exception):
                gw._evict_everywhere(rid)
        total = time.perf_counter() - t_start
        gw.close()

    completed = len(toks)
    goodput = completed / total if total > 0 else 0.0
    return BaselineResult(
        name=name,
        ttr_seconds=None if aborted else ttr,
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=goodput,
        aborted=aborted,
    )


def run_radp(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace(
        name="RADP", prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
        disable_mirror=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py::test_radp_recovers_full_sequence -v`
Expected: PASS. (This mirrors the proven `measure_mid_decode_replay` path, so recovery should succeed and the sequence should match the healthy reference.)

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "feat(b1): RADP in-place replay line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: B2 no-mirror line (restart-based ablation)

**Files:**
- Modify: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Consumes: `generate_reference`, `chain_config`, `BaselineResult`.
- Produces: `run_b2_no_mirror(*, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int], reference_wall: float) -> BaselineResult`

**Rationale:** With the mirror disabled, a manual `_decode_step` cannot replay KV. B2 must use `gw.generate()` so the gateway's `_generate_inner` re-prefill loop restarts the whole request. TTR for this restart line = extra wall-clock over the reference (per the TTR taxonomy).

- [ ] **Step 1: Write the failing test**

```python
from experiments.b1_ft_baselines import run_b2_no_mirror


def test_b2_no_mirror_recovers_by_restart():
    prompt, max_tokens = "The quick brown fox", 12
    ref, ref_wall = generate_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_b2_no_mirror(
        prompt=prompt, max_tokens=max_tokens, kill_after_tokens=4,
        reference=ref, reference_wall=ref_wall,
    )
    assert r.name == "B2-no-mirror"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True
    assert r.ttr_seconds is not None  # extra-wall-clock, may be small in-process
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py::test_b2_no_mirror_recovers_by_restart -v`
Expected: FAIL with `ImportError: cannot import name 'run_b2_no_mirror'`.

- [ ] **Step 3: Write minimal implementation**

```python
def _drive_restart(
    *, name: str, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], reference_wall: float, disable_mirror: bool,
) -> BaselineResult:
    """Use gw.generate(); kill the victim mid-stream via a background timer
    on token count. Recovery happens by _generate_inner's re-prefill restart.
    TTR = wall_with_failure - reference_wall."""
    device_ids, placement, recovery, victim = chain_config()
    with in_process_cluster(device_ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        if disable_mirror:
            gw.cache.get_history = lambda *a, **kw: []  # type: ignore[method-assign]
        gw.generate(prompt, max_tokens=2)  # warmup

        # Kill the victim after `kill_after_tokens` streamed tokens.
        killed = {"done": False}

        def _kill_when_ready(tokens_so_far: int) -> None:
            if not killed["done"] and tokens_so_far >= kill_after_tokens:
                servers[victim].stop()
                killed["done"] = True

        aborted = False
        toks: list[int] = []
        t0 = time.perf_counter()
        try:
            for i, st in enumerate(gw.generate_streaming(prompt, max_tokens=max_tokens)):
                toks.append(st.token_id)
                _kill_when_ready(len(toks))
        except Exception:
            aborted = True
        total = time.perf_counter() - t0
        gw.close()

    completed = len(toks)
    goodput = completed / total if total > 0 else 0.0
    ttr = None if aborted else max(0.0, total - reference_wall)
    return BaselineResult(
        name=name, ttr_seconds=ttr, tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=goodput, aborted=aborted,
    )


def run_b2_no_mirror(
    *, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], reference_wall: float,
) -> BaselineResult:
    return _drive_restart(
        name="B2-no-mirror", prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
        reference_wall=reference_wall, disable_mirror=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py::test_b2_no_mirror_recovers_by_restart -v`
Expected: PASS. If `generate_streaming` yields objects whose token field is not `token_id`, inspect `radp/coordinator/gateway.py:71` (`class StreamingToken`) and use the correct attribute — adjust `st.token_id` accordingly, then re-run. This is the one field to verify against the real class.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "feat(b1): B2 no-mirror restart ablation line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: B0 abort line (no recovery)

**Files:**
- Modify: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Consumes: `_drive_restart` pattern, `chain_config`, `BaselineResult`.
- Produces: `run_b0_abort(*, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int], reference_wall: float) -> BaselineResult`

**Rationale:** B0 deploys with `recovery={}` (no backup). When the victim dies, `_generate_inner` retries re-prefill up to `len(placement)` times and then raises — but the victim stays dead, so it aborts. `tokens_completed` = tokens streamed before the abort; `ttr = None`; `aborted = True`.

- [ ] **Step 1: Write the failing test**

```python
from experiments.b1_ft_baselines import run_b0_abort


def test_b0_aborts_with_partial_output():
    prompt, max_tokens = "The quick brown fox", 12
    ref, ref_wall = generate_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_b0_abort(
        prompt=prompt, max_tokens=max_tokens, kill_after_tokens=4,
        reference=ref, reference_wall=ref_wall,
    )
    assert r.name == "B0-abort"
    assert r.aborted is True
    assert r.ttr_seconds is None
    assert r.tokens_completed < max_tokens          # never finished
    assert r.sequence_matches_reference is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py::test_b0_aborts_with_partial_output -v`
Expected: FAIL with `ImportError: cannot import name 'run_b0_abort'`.

- [ ] **Step 3: Write minimal implementation**

```python
def run_b0_abort(
    *, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], reference_wall: float,
) -> BaselineResult:
    """No recovery: deploy with recovery={}. Victim death aborts the stream."""
    device_ids, placement, _recovery, victim = chain_config()
    with in_process_cluster(device_ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery={})
        gw = RequestGateway(
            placement=placement, recovery={},
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        gw.generate(prompt, max_tokens=2)  # warmup
        killed = {"done": False}
        aborted = False
        toks: list[int] = []
        t0 = time.perf_counter()
        try:
            for st in gw.generate_streaming(prompt, max_tokens=max_tokens):
                toks.append(st.token_id)
                if not killed["done"] and len(toks) >= kill_after_tokens:
                    servers[victim].stop()
                    killed["done"] = True
        except Exception:
            aborted = True
        total = time.perf_counter() - t0
        gw.close()

    completed = len(toks)
    return BaselineResult(
        name="B0-abort",
        ttr_seconds=None,
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=(completed / total if total > 0 else 0.0),
        aborted=(aborted or completed < max_tokens),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py::test_b0_aborts_with_partial_output -v`
Expected: PASS. If B0 unexpectedly completes (recovery happened without a table), verify `deploy(..., recovery={})` truly loaded no backups and that `RequestGateway(recovery={})` has no fallback — check `radp/coordinator/gateway.py:620` `_recover_from_chain_failure`; with an empty table `NoRecoveryError` should propagate and abort. Adjust the injection only if the mechanism differs.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "feat(b1): B0 no-recovery abort line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: B1 cold-restart line (re-solve survivors + full re-run)

**Files:**
- Modify: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Consumes: `chain_config`, `greedy_placement` (from `_harness`), `BaselineResult`.
- Produces:
  - `resolve_excluding(dead: DeviceId, survivors: list[str]) -> Placement` — contiguous re-split of all 12 layers over the survivors (in-process stand-in for the fleet DP re-solve).
  - `run_b1_cold_restart(*, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int], reference_wall: float) -> BaselineResult`

**Rationale:** Cold-restart = on failure, drop the dead node, re-solve a placement over survivors, redeploy, re-run from scratch. TTR includes the re-solve (per resolved decision). In-process the re-solve is a cheap contiguous re-split; the real DP re-solve cost is measured on the fleet (Task 7).

- [ ] **Step 1: Write the failing test**

```python
from experiments.b1_ft_baselines import run_b1_cold_restart, resolve_excluding


def test_resolve_excluding_covers_all_layers_over_survivors():
    plan = resolve_excluding("worker-b", ["worker-a", "worker-c"])
    assert {s.device for s in plan} == {"worker-a", "worker-c"}
    assert int(plan[0].start_layer) == 1
    assert int(plan[-1].end_layer) == 12


def test_b1_cold_restart_recovers_full_sequence():
    prompt, max_tokens = "The quick brown fox", 12
    ref, ref_wall = generate_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_b1_cold_restart(
        prompt=prompt, max_tokens=max_tokens, kill_after_tokens=4,
        reference=ref, reference_wall=ref_wall,
    )
    assert r.name == "B1-cold-restart"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True
    assert r.ttr_seconds is not None and r.ttr_seconds >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py -k "resolve_excluding or cold_restart" -v`
Expected: FAIL with `ImportError: cannot import name 'run_b1_cold_restart'`.

- [ ] **Step 3: Write minimal implementation**

```python
from experiments._harness import greedy_placement
from radp.common.types import DeviceProfile


def resolve_excluding(dead: DeviceId, survivors: list[str]) -> Placement:
    """Contiguous re-split of all 12 layers over the survivors (equal-weight).
    In-process stand-in for the fleet DP re-solve."""
    devs = [DeviceProfile(id=DeviceId(s), total_memory_bytes=4_000_000_000,
                          compute_throughput=1.0) for s in survivors if s != dead]
    return greedy_placement(devs, num_layers=12)


def run_b1_cold_restart(
    *, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], reference_wall: float,
) -> BaselineResult:
    device_ids, placement, recovery, victim = chain_config()
    survivors = [d for d in device_ids if d != victim]
    with in_process_cluster(device_ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL_ID)
        gw.generate(prompt, max_tokens=2)  # warmup

        t0 = time.perf_counter()
        aborted = False
        toks: list[int] = []
        # First attempt: stream until the victim is killed mid-stream.
        killed = {"done": False}
        try:
            for st in gw.generate_streaming(prompt, max_tokens=max_tokens):
                toks.append(st.token_id)
                if not killed["done"] and len(toks) >= kill_after_tokens:
                    servers[victim].stop()
                    killed["done"] = True
        except Exception:
            pass  # expected: first attempt fails, cold-restart follows
        gw.close()

        # Cold restart: re-solve over survivors, redeploy, re-run from scratch.
        new_plan = resolve_excluding(victim, survivors)
        surv_addrs = {DeviceId(d): addrs[DeviceId(d)] for d in survivors}
        deploy(surv_addrs, new_plan, model_id=MODEL_ID, recovery={})
        gw2 = RequestGateway(placement=new_plan, recovery={},
                             worker_addresses=surv_addrs, model_id=MODEL_ID)
        try:
            toks = gw2.generate(prompt, max_tokens=max_tokens)
        except Exception:
            aborted = True
            toks = []
        gw2.close()
        total = time.perf_counter() - t0

    completed = len(toks)
    return BaselineResult(
        name="B1-cold-restart",
        ttr_seconds=None if aborted else max(0.0, total - reference_wall),
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(list(toks) == reference),
        goodput_tok_per_s=(completed / total if total > 0 else 0.0),
        aborted=aborted,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py -k "resolve_excluding or cold_restart" -v`
Expected: PASS. If the re-run sequence does not match the reference (2-device re-split changes layer boundaries but not the model, so greedy argmax output must be identical), confirm `resolve_excluding` covers exactly layers 1–12 with no gaps/overlaps; fix the split if `test_resolve_excluding_*` passed but the sequence differs.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "feat(b1): B1 cold-restart line (re-solve survivors + re-run)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Unified driver + B3 infeasibility calc + JSON/CLI

**Files:**
- Modify: `experiments/b1_ft_baselines.py`
- Test: `tests/test_b1_ft_baselines.py`

**Interfaces:**
- Consumes: all `run_*` line functions, `generate_reference`, `write_json` (from `_harness`).
- Produces:
  - `redundant_hosting_fits(*, device_mem_bytes: int, stage_weight_bytes: int, primary_stage_bytes: int) -> bool` — B3 feasibility: a device already holding its primary stage must also fit a full replica of the backed-up stage.
  - `run_all(*, prompt: str, max_tokens: int, kill_after_tokens: int) -> dict` — runs RADP/B0/B1/B2 in-process through the same injection, adds the B3 feasibility flag, returns a JSON-serializable comparison record.
  - `main() -> None` — argparse CLI writing `experiments/results/<out>.json`.

**Rationale:** B3's in-place TTR equals RADP's in-process (same replay path), so in-process B3 adds no signal beyond RADP; its real content is the **memory feasibility** finding (pure function here) and a fleet TTR on a 32 GB board (Task 7). The driver records the feasibility flag for the config-A 4 GB Nano.

- [ ] **Step 1: Write the failing test**

```python
from experiments.b1_ft_baselines import redundant_hosting_fits, run_all


def test_redundant_hosting_infeasible_on_4gb():
    # 4GB Nano already holds a ~2GB primary; a full ~2GB replica does not fit.
    assert redundant_hosting_fits(
        device_mem_bytes=4_000_000_000,
        stage_weight_bytes=2_000_000_000,
        primary_stage_bytes=2_000_000_000,
    ) is False
    # A 32GB board fits both.
    assert redundant_hosting_fits(
        device_mem_bytes=32_000_000_000,
        stage_weight_bytes=2_000_000_000,
        primary_stage_bytes=2_000_000_000,
    ) is True


def test_run_all_returns_all_lines():
    rec = run_all(prompt="The quick brown fox", max_tokens=8, kill_after_tokens=3)
    names = {line["name"] for line in rec["lines"]}
    assert {"RADP", "B0-abort", "B1-cold-restart", "B2-no-mirror"} <= names
    assert rec["b3_redundant_fits_4gb"] is False
    for line in rec["lines"]:
        assert "ttr_seconds" in line and "tokens_completed" in line
        assert "goodput_tok_per_s" in line and "sequence_matches_reference" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b1_ft_baselines.py -k "redundant or run_all" -v`
Expected: FAIL with `ImportError: cannot import name 'redundant_hosting_fits'`.

- [ ] **Step 3: Write minimal implementation**

```python
import argparse
from dataclasses import asdict

from experiments._harness import write_json


def redundant_hosting_fits(
    *, device_mem_bytes: int, stage_weight_bytes: int, primary_stage_bytes: int
) -> bool:
    """A redundant-hosting backup device holds its own primary stage AND a
    full live replica of the backed-up stage. Fits only if both reside."""
    return primary_stage_bytes + stage_weight_bytes <= device_mem_bytes


def run_all(*, prompt: str, max_tokens: int, kill_after_tokens: int) -> dict:
    reference, reference_wall = generate_reference(prompt=prompt, max_tokens=max_tokens)
    lines = [
        run_radp(prompt=prompt, max_tokens=max_tokens,
                 kill_after_tokens=kill_after_tokens, reference=reference),
        run_b0_abort(prompt=prompt, max_tokens=max_tokens,
                     kill_after_tokens=kill_after_tokens,
                     reference=reference, reference_wall=reference_wall),
        run_b1_cold_restart(prompt=prompt, max_tokens=max_tokens,
                            kill_after_tokens=kill_after_tokens,
                            reference=reference, reference_wall=reference_wall),
        run_b2_no_mirror(prompt=prompt, max_tokens=max_tokens,
                         kill_after_tokens=kill_after_tokens,
                         reference=reference, reference_wall=reference_wall),
    ]
    # B3 config-A feasibility: 4GB Nano holding a ~2GB stage cannot also host
    # a full replica. Weights are placeholders here; the fleet run (Task 7)
    # substitutes measured per-stage bytes.
    b3_fits = redundant_hosting_fits(
        device_mem_bytes=4_000_000_000,
        stage_weight_bytes=2_000_000_000,
        primary_stage_bytes=2_000_000_000,
    )
    return {
        "model_id": MODEL_ID,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "kill_after_tokens": kill_after_tokens,
        "reference_wall_seconds": reference_wall,
        "b3_redundant_fits_4gb": b3_fits,
        "lines": [asdict(line) for line in lines],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--max-tokens", type=int, default=12)
    p.add_argument("--kill-after-tokens", type=int, default=4)
    p.add_argument("--out", default="b1_ft_baselines")
    args = p.parse_args()
    rec = run_all(prompt=args.prompt, max_tokens=args.max_tokens,
                  kill_after_tokens=args.kill_after_tokens)
    path = write_json(args.out, rec)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_b1_ft_baselines.py -k "redundant or run_all" -v`
Then smoke-run the CLI: `python -m experiments.b1_ft_baselines --max-tokens 8 --kill-after-tokens 3 --out b1_smoke`
Expected: tests PASS; CLI prints `wrote .../results/b1_smoke.json` with four lines + the `b3_redundant_fits_4gb: false` flag.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_baselines.py tests/test_b1_ft_baselines.py
git commit -m "feat(b1): unified driver + B3 feasibility calc + CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Fleet port + config-A run + REPORT section (procedural, hardware)

**Files:**
- Modify: `experiments/run_failure_remote.py` (add a `--baselines` path invoking the `run_*` functions against real worker addresses)
- Modify: `experiments/REPORT.md` (add a B1 results subsection)

**Interfaces:**
- Consumes: the confirmed `run_*` line functions; the fleet's real worker addresses and ansible deploy from the existing remote harness.

**Note:** This task runs on the physical fleet (config A: AGX Orin + Nano CUDA ×3) with `MODEL_ID` set to the fleet model (OPT-350M; Llama-3.2-1B if time permits). It is not TDD — it produces measured numbers. The in-process line functions are reused; only the cluster wiring differs.

- [ ] **Step 1: Parameterize the line functions for real addresses**

Extract the cluster wiring so `run_*` can accept an externally-provided `(addrs, servers-or-None, placement, recovery, victim)` instead of always calling `in_process_cluster`/`chain_config`. Keep the in-process default. Show the refactor as a `cluster` parameter with the in-process context manager as default; do not duplicate the driving logic.

- [ ] **Step 2: Wire config A in `run_failure_remote.py`**

Use the existing remote deploy to stand up AGX Orin + Nano CUDA ×3, build the placement/recovery over those four devices, pick an interior victim, and call `run_all` with the real addresses. Kill the victim via the remote harness's existing SIGKILL mechanism (`experiments/run_failure_remote.py` `_find_recovery_step` already tracks the victim-drop step).

- [ ] **Step 3: Run and capture**

Run the fleet benchmark (operator-invoked on the cluster). Capture `experiments/results/b1_ft_baselines_configA_opt350m.json`.

- [ ] **Step 4: Measure B3 TTR on a 32 GB board**

On AGX Orin 32 GB (ao-2), deploy a redundant replica of the victim's stage on a live peer, kill the victim, measure the reroute+replay TTR. Record it alongside `redundant_hosting_fits(...)=False` for the 4 GB Nano (using measured per-stage bytes).

- [ ] **Step 5: Write the REPORT.md subsection + commit**

Add a "B1 — FT baseline comparison" subsection to `experiments/REPORT.md` with the comparison table (per line: TTR, tokens_completed, sequence_match, goodput) and the B3 infeasibility note.

```bash
git add experiments/run_failure_remote.py experiments/REPORT.md experiments/results/b1_ft_baselines_configA_opt350m.json
git commit -m "feat(b1): fleet config-A FT baseline run + REPORT section

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Baselines B0/B1/B2/B3 + RADP → Tasks 2–6 (B3 = feasibility calc T6 + fleet TTR T7). ✓
- Metrics TTR/correctness/goodput → `BaselineResult` (T1), populated by every line. ✓
- Single mid-stream SIGKILL → the shared injection in `_drive_inplace`/`_drive_restart`/B0/B1. ✓
- B2 dual-role labeling → name `B2-no-mirror`; ablation grouping is a reporting concern in T7's table. ✓
- B3 4 GB infeasibility + 32 GB TTR → `redundant_hosting_fits` (T6) + T7 Step 4. ✓
- Resolved decisions (replay / re-solve in TTR / config A) → Global Constraints + T5 + T7. ✓
- In-process dev → fleet headline → Tasks 1–6 in-process, Task 7 fleet. ✓
- Scope exclusions (overhead L8, diversity L7, sweep L4) → not present in any task. ✓

**Placeholder scan:** No "TBD/handle edge cases/similar to Task N". Two explicitly-flagged runtime confirmations (StreamingToken field name in T3S4; B0 abort mechanism in T4S4) are verification steps with the exact file:line to check, not placeholders.

**Type consistency:** `BaselineResult` fields identical across all `run_*`. `chain_config` returns `(device_ids, placement, recovery, victim)` consumed consistently. `run_all` returns `{"lines": [...], "b3_redundant_fits_4gb": bool}` matching the T6 test. `resolve_excluding(dead, survivors)` signature matches T5 test.

**Known simplification (fleet-deferred):** in-process B3 ≡ RADP (same replay path), so B3's in-process line is intentionally omitted; its signal is the feasibility calc + fleet TTR. In-process cold-restart uses a contiguous re-split, not the DP; the DP re-solve cost is a fleet measurement. Both are stated at their tasks.
