"""Tests for the `backup_placement` toggle (R={} reactive re-placement baseline).

Reactive re-placement needs the R={} regime: no backup peer assigned per
stage, so a stage failure aborts and the coordinator reconfigures instead of
promoting a pre-armed backup. `ClusterSpec.backup_placement=False` makes
`solve_alternating` skip `determine_recovery_table` and use an empty
RecoveryTable, while the DP still solves Ψ over all layers/devices.
"""

from __future__ import annotations

from radp.common.types import (
    SLO,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
)
from radp.coordinator.scheduler import Scheduler

LAYER_BYTES = 500_000_000
NODE_BYTES = 8_000_000_000


def _spec(backup_placement: bool) -> ClusterSpec:
    devices = [
        DeviceProfile(id=DeviceId(d), total_memory_bytes=NODE_BYTES, compute_throughput=1.0)
        for d in ("a", "b", "c")
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=LAYER_BYTES,
            compute_time={d.id: 0.05 for d in devices},
        )
        for i in range(1, 7)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.001 for d1 in devices for d2 in devices if d1 is not d2},
    )
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=network,
        # 6 layers * 0.05s = 0.3s worst case on one device; well under the
        # 1.0s per-stage SLO cap regardless of how the search splits/subsets.
        slo=SLO(ttft_seconds=1.0, tbt_seconds=1.0),
        backup_placement=backup_placement,
    )


def test_backup_placement_false_gives_empty_recovery() -> None:
    result = Scheduler(_spec(backup_placement=False)).solve_alternating_best_order()
    assert result.recovery == {}
    # Psi still covers all layers over all devices.
    covered = sorted(
        layer
        for stage in result.placement
        for layer in range(int(stage.start_layer), int(stage.end_layer) + 1)
    )
    assert covered == list(range(1, 7))


def test_backup_placement_true_is_default_and_populates_recovery() -> None:
    assert _spec(backup_placement=True).backup_placement is True
    result = Scheduler(_spec(backup_placement=True)).solve_alternating_best_order()
    assert result.recovery != {}  # default path unchanged: backups assigned


def test_reconfigure_endpoint_excludes_dead() -> None:
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
