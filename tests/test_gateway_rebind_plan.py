"""rebind_plan: reactive reconfigure must swap the gateway's routing to the
re-solved plan and drop the old dead set (stale-flap survivors included) —
otherwise the replay routes per the old plan whose stages the workers evicted
("no stage loaded")."""

from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.gateway import RequestGateway


def _gw() -> RequestGateway:
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("w-head")),
        Stage(LayerIdx(7), LayerIdx(10), DeviceId("w-victim")),
        Stage(LayerIdx(11), LayerIdx(12), DeviceId("w-tail")),
    ]
    recovery: RecoveryTable = {
        DeviceId("w-head"): DeviceId("w-tail"),
        DeviceId("w-victim"): DeviceId("w-tail"),
        DeviceId("w-tail"): DeviceId("w-head"),
    }
    addrs = {DeviceId(d): f"{d}:1" for d in ("w-head", "w-victim", "w-tail", "w-new")}
    # opt-125m: gateway init loads config/tokenizer/head from the HF cache
    return RequestGateway(
        placement=placement, recovery=recovery,
        worker_addresses=addrs, model_id="facebook/opt-125m",
    )


def test_rebind_plan_swaps_routing_and_clears_dead() -> None:
    gw = _gw()
    gw.mark_dead(DeviceId("w-victim"))
    # stale-heartbeat flap: a healthy survivor also landed in _dead
    gw.mark_dead(DeviceId("w-head"))
    assert gw._dead == {DeviceId("w-victim"), DeviceId("w-head")}

    new_placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(7), DeviceId("w-head")),
        Stage(LayerIdx(8), LayerIdx(12), DeviceId("w-new")),
    ]
    gw.rebind_plan(new_placement, {})

    assert gw.placement == new_placement
    assert gw.recovery == {}
    assert gw._dead == set()
    plan = gw.current_plan()
    assert [(int(s.start_layer), int(s.end_layer), str(s.device)) for s in plan] == [
        (1, 7, "w-head"), (8, 12, "w-new"),
    ]


if __name__ == "__main__":
    test_rebind_plan_swaps_routing_and_clears_dead()
    print("ok")
