"""load_primary starts a new plan: stale stages from the previous plan must go.

Regression for the OPT-6.7B B1 sweep (2026-08-31): on a per-trial redeploy the
worker kept the previous plan's primary + backup stages while loading the new
primary. At 350M that wastes a few hundred MB; at 6.7B on a Jetson (unified
memory) it OOM-killed on-6 mid-LoadStage and the deploy failed.
"""
from radp.common.types import DeviceId, LayerIdx
from radp.worker.stage_runner import StageRunner

MODEL = "facebook/opt-125m"


def _runner() -> StageRunner:
    return StageRunner(DeviceId("worker-a"), torch_device="cpu", dtype="float32")


def test_load_primary_drops_previous_plan() -> None:
    r = _runner()
    r.load_primary(MODEL, LayerIdx(1), LayerIdx(2))
    r.load_backup(MODEL, LayerIdx(3), LayerIdx(4), for_device_id=DeviceId("worker-b"))
    r._kv_cache[("req-1", (1, 2))] = object()  # type: ignore[assignment]
    assert set(r._stages) == {(1, 2), (3, 4)}

    r.load_primary(MODEL, LayerIdx(5), LayerIdx(6))
    assert set(r._stages) == {(5, 6)}, "previous plan's stages must be dropped"
    assert r._primary == (5, 6)
    assert r._backup_for == {}, "backup registry belongs to the old plan"
    assert r._promoted == set()
    assert r._kv_cache == {}, "old requests' KV belongs to the old plan"


def test_load_primary_reuses_matching_resident_stage() -> None:
    r = _runner()
    r.load_backup(MODEL, LayerIdx(1), LayerIdx(2), for_device_id=DeviceId("worker-b"))
    resident = r._stages[(1, 2)]
    r.load_primary(MODEL, LayerIdx(1), LayerIdx(2))
    assert r._stages[(1, 2)] is resident, "same-key stage should be reused, not reloaded"
    assert r._primary == (1, 2)
