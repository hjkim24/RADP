"""B1 — fault-tolerance baseline comparison (spec 2026-07-16).

Drives RADP + four recovery-strategy baselines through one identical
mid-stream worker SIGKILL and reports TTR / correctness / goodput.
See docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md.
"""
from __future__ import annotations

import contextlib
import time
import types
from dataclasses import dataclass

from experiments._harness import (
    deploy,
    in_process_cluster,
    in_process_cluster_with_mirror,
    wire_chain,
)
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


def generate_wired_reference(*, prompt: str, max_tokens: int) -> list[int]:
    """Healthy-cluster run on the SAME topology the crash-injection lines
    use (mirror-wired coordinator + ``wire_chain``-ed workers), so the
    reference is directly comparable token-for-token. ``generate_reference``
    above uses the plain head-only ``in_process_cluster`` (no
    ``wire_chain``), which silently runs only the first stage — see
    ``experiments._harness.wire_chain``'s docstring — so it is not a valid
    reference for the in-place recovery lines.
    """
    device_ids, placement, recovery, _ = chain_config()
    with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        attach(gw)
        toks = list(gw.generate(prompt, max_tokens=max_tokens))
        gw.close()
    return toks


def _inject_mid_stage_crash(gw, victim_server, victim_runner, *, dead_key, at_position):
    """Monkeypatch ``victim_runner.run`` for a deterministic mid-forward
    crash at decode position ``at_position``.

    Generalizes the prototype fault in
    ``tests/test_surgical_recovery.py::test_surgical_recovery_exercises_live_position_rebuild``:
    the worker servicer already fire-and-forgets a mirror push of its
    incoming activation to the coordinator BEFORE calling
    ``StageRunner.run`` (see ``radp/worker/server.py``'s ``RunStage``), so
    intercepting ``run`` itself is always strictly after that mirror send.
    We count calls for ``dead_key`` (this stage's own ``(start, end)`` —
    call 1 is prefill / position 0, call k is decode position k-1), and on
    the call matching ``at_position`` we poll
    ``gw.cache.get_history(request_id, dead_key)`` until the mirror for
    that position has actually landed, THEN raise — guaranteeing the
    coordinator has history[at_position] so recovery can take its real
    surgical/full-replay path instead of the async-mirror-lag fallback.

    Returns a ``tripped`` object; ``tripped.fired`` is True once the fault
    has actually raised (assert this — a fault that never fires means the
    "recovery" that follows measured nothing).
    """
    orig_run = victim_runner.run
    tripped = types.SimpleNamespace(fired=False)
    calls = {"n": 0}

    def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
        if (int(start), int(end)) == dead_key:
            calls["n"] += 1
            if calls["n"] - 1 == at_position and not tripped.fired:
                tripped.fired = True
                deadline = time.time() + 5.0
                while (
                    len(gw.cache.get_history(request_id, dead_key)) <= at_position
                    and time.time() < deadline
                ):
                    time.sleep(0.01)
                raise RuntimeError(
                    f"simulated {victim_server.device_id} mid-stage crash "
                    f"after mirror (position={at_position})"
                )
        return orig_run(
            request_id, activation_blob, start=start, end=end, is_prefill=is_prefill
        )

    victim_runner.run = flaky_run
    return tripped


def _drive_inplace_crash(
    *, name: str, recovery_mode: str, prompt: str, max_tokens: int,
    kill_after_tokens: int, reference: list[int],
) -> BaselineResult:
    """Mirror+wire_chain cluster; drive one request through prefill+decode;
    inject a mid-stage crash on the interior victim at ``kill_after_tokens``
    (after its mirror for that position has landed); the gateway's in-place
    recovery (``recovery_mode``) fixes the failed decode step in place.
    ``ttr_seconds`` is that single failed step's wall-clock.
    """
    device_ids, placement, recovery, victim = chain_config()
    dead_key = next(
        (int(s.start_layer), int(s.end_layer)) for s in placement if s.device == victim
    )
    with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
            recovery_mode=recovery_mode,
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        rid = gw.new_request_id()
        tripped = _inject_mid_stage_crash(
            gw, servers[victim], servers[victim].runner,
            dead_key=dead_key, at_position=kill_after_tokens,
        )

        ttr: float | None = None
        aborted = False
        toks: list[int] = []
        t_start = time.perf_counter()
        try:
            gw._prefill(rid, prompt)
            for step in range(1, max_tokens):
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

    assert tripped.fired, (
        f"{name}: injected mid-stage crash on {victim} never fired "
        f"(dead_key={dead_key}, at_position={kill_after_tokens}) — "
        "recovery measured nothing"
    )

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


def run_radp_surgical(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace_crash(
        name="RADP-surgical", recovery_mode="surgical",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )


def run_radp_full_replay(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace_crash(
        name="RADP-full-replay", recovery_mode="full_replay",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )
