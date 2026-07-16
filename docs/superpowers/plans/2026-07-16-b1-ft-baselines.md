# B1 Fault-Tolerance Baseline Comparison — Implementation Plan (Path 2: surgical recovery)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the mirror cache's surgical recovery (rebuild only the promoted backup's KV) into the gateway, then benchmark RADP-surgical vs RADP-full-replay vs cold-restart vs abort under one identical mid-chain worker kill.

**Architecture:** The centerpiece is a new *surgical* recovery mode in `radp/coordinator/gateway.py` — on a mid-chain fault it rebuilds only the promoted backup's KV from the mirrored stage inputs (leaving survivors' KV intact and reconciling the single failed position), instead of the current full-chain replay that evicts and recomputes every stage. The benchmark driver `experiments/b1_ft_baselines.py` drives all four recovery strategies through the same injection and reports TTR / correctness / goodput.

**Tech Stack:** Python 3.9+, pytest, PyTorch, gRPC, RADP coordinator/worker packages.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md` — **read §10 (Path 2 revision)**; it supersedes the original B0–B3 set.
- **Baseline set (4 lines):** **RADP-surgical** (new), **RADP-full-replay** (current default, already built in Task 2 as `run_radp`), **cold-restart**, **abort**. B2 (no-mirror ablation) is absorbed into full-replay; B3 (redundant hosting) is deferred to a separate experiment.
- Metrics only: **TTR**, **token correctness/completeness**, **goodput under failure**.
- Failure injection: **single mid-stream SIGKILL** of one chain-interior worker (`worker-b`).
- **TTR taxonomy:** *in-place* lines (RADP-surgical, RADP-full-replay) → TTR = latency of the single failed decode step. *Restart* lines (cold-restart) → TTR = `wall_with_failure − reference_wall`. *Abort* → `None`.
- In-process dev constants: `MODEL_ID = "facebook/opt-125m"`, 3-worker chain `worker-a/b/c` layers `1-4 / 5-8 / 9-12`, interior victim `worker-b`, `max_tokens=12`, `kill_after_tokens=4`.
- **Test env:** run pytest ONLY as `.venv-py39/bin/python -m pytest ...`. The venv MUST have `transformers>=4.40,<4.51` (currently 4.50.3). `KeyError: None` from an OPT forward ⇒ venv drifted (`uv pip install --python .venv-py39/bin/python 'transformers>=4.40,<4.51'`).
- **pytest marker:** `addopts = "-ra -q -m 'not slow'"` deselects model-loading tests. Every model-loading test MUST be `@pytest.mark.slow` (module-level `pytestmark = pytest.mark.slow`) and run with `-m slow`. A plain run yielding "no tests collected" (exit 5) is NOT a pass.
- **Do not break existing recovery:** `recovery_mode` defaults to the current full-replay behavior; existing callers and tests must be unaffected.
- **Known pre-existing test state:** `tests/test_cache_replay_recovery.py` and `tests/test_failure_recovery_integration.py` fail ONLY on a stale `assert <dead> in gw._dead` bookkeeping check; recovery produces the correct sequence. Not a regression; do not "fix" it as part of this work.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Do NOT commit `experiments/results/*.json`.

---

## File Structure

- **Modify** `radp/coordinator/gateway.py` — add `recovery_mode` to `RequestGateway`; add `_recover_surgical(...)`; branch `_recover_from_chain_failure` on the mode. Reuse the existing `_replay_stage_history` for the KV rebuild.
- **Create** `tests/test_surgical_recovery.py` — correctness tests for the surgical mode (in-process, opt-125m, slow).
- **Modify** `experiments/b1_ft_baselines.py` — add `run_radp_surgical`, `run_b0_abort`, `run_b1_cold_restart`, `resolve_excluding`, the unified `run_all`, and `main()`. (`run_radp` from Task 2 is the full-replay line.)
- **Modify** `tests/test_b1_ft_baselines.py` — tests for the new lines + driver.
- **Modify (final task)** `experiments/run_failure_remote.py`, `experiments/REPORT.md` — fleet run.

---

## Task 1 — DONE (commit 33bcd22)
Driver scaffold: `BaselineResult`, `chain_config()`, `generate_reference()`. Reviewed clean.

## Task 2 — DONE (commit 310e0c1)
`run_radp` = the **RADP-full-replay** line (drives the gateway's current default recovery; in-place TTR). Reviewed clean. Recovers 12/12, sequence matches reference. (In the driver, this line is labeled "RADP-full-replay".)

---

### Task 3: Surgical recovery mode in the gateway (CORE)

**Files:**
- Modify: `radp/coordinator/gateway.py`
- Test: `tests/test_surgical_recovery.py`

**Interfaces:**
- Consumes: existing `RequestGateway`, `_replay_stage_history`, `_attribute_chain_failure`, `_rewire_chain`, `_invoke`, `cache.get_history`.
- Produces: `RequestGateway(..., recovery_mode: str = "full_replay")` accepting `"full_replay"` | `"surgical"`; a `_recover_surgical(self, request_id, head_stage, error, current_position) -> tuple[Stage, Any]` with the SAME return contract as `_recover_from_chain_failure`.

**Mechanics (chain coord→a→b→c, b dies at position P; a advanced to P, c at P-1, backup cold):**
1. Attribute dead stage; `mark_dead`; promote backup; `_rewire_chain` — same as the full-replay path.
2. **Do NOT evict survivors' KV.**
3. Rebuild the backup's KV: replay the dead stage's mirrored inputs for positions **0..P-1** into the backup with `replay_only=True` (this is what `_replay_stage_history` does — but slice to exclude P; see Step 3b of the TDD below).
4. Run position **P live**: `_invoke` the backup with the mirrored dead-stage input at P (do NOT re-run `a`), let it forward backup→c, and capture the response as the recovered token/activation.
5. Return `(new_head_or_backup_stage, last_resp)`.

**Correctness gate:** recovered full sequence == the healthy reference, exactly (same bar as full-replay).

**⚠️ Dependency risk — verify FIRST (Step 0):** surgical replay reads `cache.get_history(request_id, dead_stage_key)` — the *worker mirror* for a non-head stage. Task 2's full-replay path used only the coord-native HEAD history, so its success does NOT prove the worker mirror is populated in the in-process cluster. Before building anything, confirm the mirror history for `worker-b`'s stage is non-empty after a few decode steps in `in_process_cluster`. If it is empty (mirror not wired in-process), STOP and report BLOCKED with what you found — the surgical path cannot be built or tested in-process without it.

- [ ] **Step 0: Verify the mirror is populated in-process (spike)**

Write a throwaway check (a scratch script or a temporary test) that stands up the 3-worker `in_process_cluster`, deploys with recovery, runs ~4 decode steps, and prints `gw.cache.get_history(request_id, (5, 8))` length. Run it with `.venv-py39/bin/python`. Expected: length > 0 (mirror populated for worker-b's stage 5–8). If it is 0, report BLOCKED (do not proceed) — include the finding and, if you can see why (e.g. the coordinator service that receives `MirrorActivation` is not running in `in_process_cluster`), say so.

- [ ] **Step 1: Write the failing correctness test**

```python
# tests/test_surgical_recovery.py
import pytest
pytestmark = pytest.mark.slow

from experiments._harness import deploy, in_process_cluster
from radp.common.types import DeviceId, LayerIdx, Stage
from radp.coordinator.gateway import RequestGateway

MODEL_ID = "facebook/opt-125m"


def _chain():
    placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }
    return ["worker-a", "worker-b", "worker-c"], placement, recovery, DeviceId("worker-b")


def test_surgical_recovery_matches_reference():
    ids, placement, recovery, victim = _chain()
    prompt, max_tokens, kill_after = "The quick brown fox", 12, 4

    # healthy reference
    with in_process_cluster(ids) as (addrs, _):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gwr = RequestGateway(placement=placement, recovery=recovery,
                             worker_addresses=addrs, model_id=MODEL_ID)
        reference = list(gwr.generate(prompt, max_tokens=max_tokens))
        gwr.close()

    # surgical recovery under a mid-chain kill
    with in_process_cluster(ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL_ID,
                            recovery_mode="surgical")
        gw.generate(prompt, max_tokens=2)  # warmup
        rid = gw.new_request_id()
        gw._prefill(rid, prompt)
        for step in range(1, max_tokens):
            if step == kill_after:
                servers[victim].stop()
            gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        gw.close()

    assert len(recovered) == max_tokens
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"


def test_full_replay_still_default():
    # Regression guard: default mode unchanged.
    gw = RequestGateway.__new__(RequestGateway)
    assert getattr(RequestGateway, "__init__")  # sanity
```

(Keep `test_full_replay_still_default` minimal or replace with a real default-mode assertion you can construct cheaply; the intent is "default mode is still full_replay".)

- [ ] **Step 2: Run the test to confirm RED**

Run: `.venv-py39/bin/python -m pytest tests/test_surgical_recovery.py::test_surgical_recovery_matches_reference -m slow -v`
Expected: FAIL — `RequestGateway.__init__` has no `recovery_mode` kwarg (TypeError) until you add it.

- [ ] **Step 3: Add `recovery_mode` + branch (no behavior change at default)**

In `RequestGateway.__init__`, add `recovery_mode: str = "full_replay"` and store `self.recovery_mode = recovery_mode`. In `_recover_from_chain_failure`, at the point where it currently does evict + `_replay_through_chain`, branch: if `self.recovery_mode == "surgical"`, delegate to `self._recover_surgical(request_id, head_stage, error, current_position)` and return its result; otherwise keep the existing full-replay behavior byte-for-byte.

- [ ] **Step 3b: Implement `_recover_surgical`**

Reuse the promote+rewire prefix from `_recover_from_chain_failure`, then rebuild only the backup's KV and run the failed position live. Concretely: identify `dead_stage` and its `stage_key=(start,end)`; promote backup; `_rewire_chain()`; get `history = self.cache.get_history(request_id, stage_key)`; replay `history[:current_position]` into the backup via `_invoke(..., replay_only=True)` (rebuild KV for 0..P-1, NO survivor evict); then `_invoke` the backup with `history[current_position]` (the mirrored input at P), `replay_only=False`, so it forwards through c and yields the recovered response; return `(backup_stage, last_resp)`. If `history` is shorter than expected (no entry at P), fall back to the full-replay path and log — do not silently produce a wrong token.

Show the complete method body in your implementation; do not leave `...` placeholders. Follow the surrounding code's logging and error style.

- [ ] **Step 4: Run the test to confirm GREEN**

Run: `.venv-py39/bin/python -m pytest tests/test_surgical_recovery.py -m slow -v`
Expected: PASS — recovered sequence equals the healthy reference (12/12 tokens). If tokens diverge at the recovery position, the position-P reconciliation (Step 3b) is off by one — check whether `history` includes P and whether you replayed `[:P]` vs `[:P+1]`.

- [ ] **Step 5: Guard the existing recovery tests still behave**

Run the existing recovery suite to confirm you did not change default behavior:
`.venv-py39/bin/python -m pytest tests/test_cache_replay_recovery.py tests/test_failure_recovery_integration.py -m slow -q`
Expected: SAME pre-existing state as before your change (they still fail ONLY on the `_dead` bookkeeping assert; the recovered sequences still match). If any NEW failure appears, your default-path branch changed behavior — fix it.

- [ ] **Step 6: Commit**

```bash
git add radp/coordinator/gateway.py tests/test_surgical_recovery.py
git commit -m "feat(recovery): surgical recovery mode — rebuild only the promoted backup's KV

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: RADP-surgical benchmark line

**Files:** Modify `experiments/b1_ft_baselines.py`; Test `tests/test_b1_ft_baselines.py`.

**Interfaces:** Consumes `_drive_inplace` (Task 2), `chain_config`, `generate_reference`. Produces `run_radp_surgical(*, prompt, max_tokens, kill_after_tokens, reference) -> BaselineResult` (name `"RADP-surgical"`).

**Approach:** identical to `run_radp` (Task 2's `_drive_inplace`) EXCEPT construct the gateway with `recovery_mode="surgical"`. Add a `recovery_mode` parameter to `_drive_inplace` (default `"full_replay"`), pass it into `RequestGateway(...)`. Update `run_radp` to set its `BaselineResult.name` to `"RADP-full-replay"` (it drives the default mode).

- [ ] Step 1: failing test `test_radp_surgical_recovers_full_sequence` — same shape as `test_radp_recovers_full_sequence` but calls `run_radp_surgical`, asserts `name == "RADP-surgical"`, `tokens_completed == max_tokens`, `sequence_matches_reference is True`, `ttr_seconds is not None`. (module already `pytestmark = slow`.)
- [ ] Step 2: run `-m slow` → RED (`run_radp_surgical` undefined).
- [ ] Step 3: add `recovery_mode` param to `_drive_inplace`; add `run_radp_surgical`; relabel `run_radp` name to `"RADP-full-replay"`.
- [ ] Step 4: run `-m slow` → GREEN (surgical recovers 12/12, matches reference). Compare its `ttr_seconds` to full-replay in the report if easy (surgical should be ≤ full-replay).
- [ ] Step 5: commit `feat(b1): RADP-surgical benchmark line`.

---

### Task 5: B0 abort line

**Files:** Modify `experiments/b1_ft_baselines.py`; Test `tests/test_b1_ft_baselines.py`.
**Interfaces:** Produces `run_b0_abort(*, prompt, max_tokens, kill_after_tokens, reference, reference_wall) -> BaselineResult` (name `"B0-abort"`). Deploy with `recovery={}` (no backup); stream via `gw.generate_streaming`; the victim death aborts. `ttr_seconds=None`, `aborted=True`, `tokens_completed < max_tokens`, `sequence_matches_reference=False`.

- [ ] Step 1: failing test `test_b0_aborts_with_partial_output` (asserts aborted True, ttr None, tokens_completed < max, sequence match False).
- [ ] Step 2: `-m slow` → RED.
- [ ] Step 3: implement `run_b0_abort` (deploy recovery={}, stream, kill after `kill_after_tokens` streamed, catch abort). If `generate_streaming` yields objects whose token attr differs, inspect `radp/coordinator/gateway.py:71` `class StreamingToken` and use the real attribute.
- [ ] Step 4: `-m slow` → GREEN. If B0 unexpectedly completes, confirm `recovery={}` truly loaded no backup and that `NoRecoveryError` aborts (`gateway.py:620`+).
- [ ] Step 5: commit `feat(b1): B0 no-recovery abort line`.

---

### Task 6: B1 cold-restart line

**Files:** Modify `experiments/b1_ft_baselines.py`; Test `tests/test_b1_ft_baselines.py`.
**Interfaces:** Produces `resolve_excluding(dead, survivors) -> Placement` (contiguous re-split of all 12 layers over survivors, via `_harness.greedy_placement`) and `run_b1_cold_restart(*, prompt, max_tokens, kill_after_tokens, reference, reference_wall) -> BaselineResult` (name `"B1-cold-restart"`). On failure: stream until the victim is killed; then re-solve over survivors, redeploy, re-run from scratch; `ttr_seconds = wall_with_failure − reference_wall` (INCLUDES the re-solve, per resolved decision), full correct sequence.

- [ ] Step 1: failing tests `test_resolve_excluding_covers_all_layers_over_survivors` + `test_b1_cold_restart_recovers_full_sequence`.
- [ ] Step 2: `-m slow` (and the non-slow `resolve_excluding` test) → RED.
- [ ] Step 3: implement `resolve_excluding` (survivors get all 12 layers, contiguous) + `run_b1_cold_restart` (first attempt streams to kill; then deploy new plan on survivors + fresh `RequestGateway(recovery={})` + `generate` from scratch; total wall includes both).
- [ ] Step 4: `-m slow` → GREEN (re-run sequence == reference; `resolve_excluding` covers layers 1–12 with no gaps/overlaps).
- [ ] Step 5: commit `feat(b1): B1 cold-restart line`.

---

### Task 7: Unified driver + metrics + CLI

**Files:** Modify `experiments/b1_ft_baselines.py`; Test `tests/test_b1_ft_baselines.py`.
**Interfaces:** Produces `run_all(*, prompt, max_tokens, kill_after_tokens) -> dict` (runs RADP-surgical, RADP-full-replay, B0-abort, B1-cold-restart through the same injection; returns `{"model_id","prompt","max_tokens","kill_after_tokens","reference_wall_seconds","lines":[asdict(...)]}`) and `main()` (argparse CLI writing `experiments/results/<out>.json` via `_harness.write_json`).

- [ ] Step 1: failing test `test_run_all_returns_all_four_lines` — `names == {"RADP-surgical","RADP-full-replay","B0-abort","B1-cold-restart"}`; each line dict has `ttr_seconds, tokens_completed, goodput_tok_per_s, sequence_matches_reference`.
- [ ] Step 2: `-m slow` → RED.
- [ ] Step 3: implement `run_all` (generate reference once, run the four lines, `asdict` each) + `main()`.
- [ ] Step 4: `-m slow` → GREEN; then smoke-run the CLI: `.venv-py39/bin/python -m experiments.b1_ft_baselines --max-tokens 8 --kill-after-tokens 3 --out b1_smoke` — prints `wrote .../results/b1_smoke.json` with four lines.
- [ ] Step 5: commit `feat(b1): unified driver + CLI`.

---

### Task 8: Fleet config-A run + REPORT (procedural, hardware — operator-run)

**Files:** Modify `experiments/run_failure_remote.py`, `experiments/REPORT.md`.
Not TDD — produces measured numbers on the physical fleet (config A: AGX Orin + Nano CUDA ×3, `MODEL_ID` = OPT-350M; Llama-3.2-1B if time permits).

- [ ] Step 1: parameterize the `run_*` line functions to accept externally-provided real worker addresses (keep the in-process default), so they run against the fleet without duplicating the drive logic.
- [ ] Step 2: wire config A in `run_failure_remote.py` (real deploy, interior victim, real SIGKILL via the existing remote mechanism); call `run_all`.
- [ ] Step 3: run on the cluster; capture `experiments/results/b1_ft_baselines_configA_opt350m.json`.
- [ ] Step 4: add a "B1 — FT baseline comparison" subsection to `experiments/REPORT.md` with the comparison table (per line: TTR, tokens, sequence_match, goodput) — headline **surgical ≪ full-replay ≈ cold-restart ≫ abort**.
- [ ] Step 5: commit `feat(b1): fleet config-A FT baseline run + REPORT section`.

---

## Self-Review

**Spec coverage (§10 Path 2):** RADP-surgical → Task 3 (gateway feature) + Task 4 (line). RADP-full-replay → Task 2 (done). cold-restart → Task 6. abort → Task 5. Metrics (TTR/correctness/goodput) → `BaselineResult`, populated by every line. Single mid-chain SIGKILL → shared injection. Fleet → Task 8. B2 absorbed (full-replay), B3 deferred — neither appears as a task. ✓

**Placeholder scan:** Task 3 Step 3b requires the full method body (no `...`). The flagged runtime confirmations (mirror populated in-process — Step 0; StreamingToken field — Task 5; B0 abort mechanism — Task 5) are verification steps with exact file:line, not placeholders.

**Type consistency:** `BaselineResult` fields unchanged across all lines. `recovery_mode: str = "full_replay"` added to `RequestGateway` and threaded through `_drive_inplace`. `_recover_surgical` returns the same `(Stage, Any)` tuple as `_recover_from_chain_failure`. `run_all` returns `{"lines":[...]}` matching the Task 7 test.

**Chief risk (called out):** Task 3 depends on the worker mirror being populated in-process (Step 0 gate). If it is not, Task 3 is BLOCKED and surgical recovery can only be validated on the fleet — escalate before building on an empty mirror.
