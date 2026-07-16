"""Task 3a: in-process cluster + mirror wiring smoke test.

Proves `in_process_cluster_with_mirror` actually routes worker->coord
MirrorActivation pushes into the driving RequestGateway's cache, so
surgical recovery (which reads gw.cache.get_history for the interior
stage) has real mirrored data to rebuild from -- unlike the plain
in_process_cluster, where the driving gateway runs no CoordinatorService
and interior-stage mirrors vanish into the void.
"""
from __future__ import annotations

import time

import pytest

from experiments._harness import deploy, in_process_cluster_with_mirror, wire_chain
from radp.common.types import DeviceId, LayerIdx, Stage
from radp.coordinator.gateway import RequestGateway

pytestmark = pytest.mark.slow

MODEL_ID = "facebook/opt-125m"


def test_interior_stage_mirror_populated() -> None:
    # 3-worker chain; after prefill + a few decodes the coord's cache holds
    # the interior stage (5,8) history, proving the worker->coord mirror is
    # wired all the way to the gateway that's actually driving the request.
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
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        wire_chain(addrs, placement)  # chain-forward past the head stage
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        attach(gw)
        rid = gw.new_request_id()
        gw._prefill(rid, "The quick brown fox")
        for _ in range(4):
            gw._decode_step(rid)
        # mirror is async/fire-and-forget over gRPC -- poll briefly rather
        # than asserting immediately.
        hist: list[bytes] = []
        for _ in range(50):
            hist = gw.cache.get_history(rid, (5, 8))
            if hist:
                break
            time.sleep(0.05)
        gw._evict_everywhere(rid)
        gw.close()
    assert len(hist) > 0, "interior-stage (5,8) mirror never reached the coord cache"
