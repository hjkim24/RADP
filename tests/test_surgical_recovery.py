"""Surgical recovery mode (Task 3b): a mid-chain SIGKILL is recovered by
rebuilding ONLY the promoted backup's KV from the mirrored dead-stage
inputs (leaving survivors' KV intact) and reconciling the single failed
position — the exact-correctness gate is that the recovered full sequence
equals the healthy wired reference token-for-token.

Uses the mirror+wire_chain harness (`in_process_cluster_with_mirror` +
`wire_chain`) so the interior-stage worker mirror is actually populated in
the driving gateway's cache — the plain head-only cluster would not mirror.

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

import logging
import time

import pytest

pytestmark = pytest.mark.slow

from experiments._harness import (
    deploy,
    in_process_cluster_with_mirror,
    wire_chain,
)
from radp.common.types import DeviceId, LayerIdx, Stage
from radp.coordinator.gateway import RequestGateway

MODEL = "facebook/opt-125m"


def _cfg():
    ids = ["worker-a", "worker-b", "worker-c"]
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
    return ids, placement, recovery


def _healthy_reference(prompt, n):
    ids, placement, recovery = _cfg()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
        )
        attach(gw)
        ref = list(gw.generate(prompt, max_tokens=n))
        gw.close()
    return ref


def test_surgical_recovery_matches_reference():
    prompt, n, kill_after = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n)
    ids, placement, recovery = _cfg()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="surgical",
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup
        rid = gw.new_request_id()
        gw._prefill(rid, prompt)
        for step in range(1, n):
            if step == kill_after:
                servers[DeviceId("worker-b")].stop()
                time.sleep(0.3)  # let the async mirror for the kill position settle
            gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        gw.close()
    assert len(recovered) == n
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"


def test_surgical_recovery_exercises_live_position_rebuild(caplog):
    """Drive the surgical live-P path for real.

    The brief's ``server.stop()`` injection kills worker-b *before* it
    receives (and mirrors) the failed position, so the mirror lacks P and
    recovery takes the correct-but-costly full-replay fallback. Here we
    instead simulate the intended fault mode the mirror-before-run design
    targets: worker-b mirrors position P (fire-and-forget, before running),
    then "crashes" mid-stage before forwarding to c. The mirror therefore
    HOLDS position P, so recovery rebuilds ONLY the promoted backup's KV
    (positions 0..P-1) and reconciles P live — no full-chain replay.

    Asserts (via the gateway's own recovery logs) that the surgical branch,
    not the fallback, ran — and the exact-correctness gate still holds.
    """
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n)
    dead_key = (5, 8)
    ids, placement, recovery = _cfg()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="surgical",
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        rid = gw.new_request_id()
        b_runner = servers[DeviceId("worker-b")].runner
        orig_run = b_runner.run
        state = {"calls": 0, "tripped": False}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            # Only fault worker-b's own stage forward, for the target request.
            if int(request_id) == int(rid) and (int(start), int(end)) == dead_key:
                state["calls"] += 1  # call k == position k-1 (prefill = pos 0)
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    # The servicer already fire-and-forget-mirrored THIS input
                    # (position kill_at) before invoking us. Wait until it lands
                    # in the coord cache so recovery sees history[kill_at] and
                    # takes the SURGICAL (not fallback) path — then "crash".
                    deadline = time.time() + 5.0
                    while (
                        len(gw.cache.get_history(rid, dead_key)) <= kill_at
                        and time.time() < deadline
                    ):
                        time.sleep(0.01)
                    raise RuntimeError("simulated worker-b mid-stage crash after mirror")
            return orig_run(
                request_id, activation_blob, start=start, end=end, is_prefill=is_prefill
            )

        b_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        gw.close()

    assert state["tripped"], "fault never injected — recovery path not exercised"
    logs = caplog.text
    assert "SURGICAL rebuild" in logs, (
        "surgical live-P rebuild did not run — recovery took another path:\n" + logs
    )
    assert "falling back to full-chain replay" not in logs, (
        "recovery fell back to full replay instead of surgical:\n" + logs
    )
    assert len(recovered) == n
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"
