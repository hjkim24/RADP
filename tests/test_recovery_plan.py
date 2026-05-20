"""Tests for failure-aware execution-plan computation."""

from __future__ import annotations

import pytest

from radp.common.types import DeviceId, LayerIdx, NoRecoveryError, Stage
from radp.coordinator.recovery_plan import build_execution_plan, inverse_recovery


def _stage(s: int, e: int, d: str) -> Stage:
    return Stage(LayerIdx(s), LayerIdx(e), DeviceId(d))


def test_plan_unchanged_with_no_failures() -> None:
    placement = [_stage(1, 4, "a"), _stage(5, 8, "b"), _stage(9, 12, "c")]
    recovery = {DeviceId("a"): DeviceId("b")}
    plan = build_execution_plan(placement, recovery, dead=set())
    assert plan == placement


def test_dead_stage_routed_to_backup() -> None:
    placement = [_stage(1, 4, "a"), _stage(5, 8, "b"), _stage(9, 12, "c")]
    recovery = {DeviceId("a"): DeviceId("b"), DeviceId("b"): DeviceId("c"), DeviceId("c"): DeviceId("a")}
    plan = build_execution_plan(placement, recovery, dead={DeviceId("b")})
    # b's slot goes to c; layer order preserved.
    assert [s.device for s in plan] == [DeviceId("a"), DeviceId("c"), DeviceId("c")]
    assert [(s.start_layer, s.end_layer) for s in plan] == [(1, 4), (5, 8), (9, 12)]


def test_raises_if_backup_also_dead() -> None:
    placement = [_stage(1, 4, "a"), _stage(5, 8, "b")]
    recovery = {DeviceId("a"): DeviceId("b"), DeviceId("b"): DeviceId("a")}
    with pytest.raises(NoRecoveryError):
        build_execution_plan(placement, recovery, dead={DeviceId("a"), DeviceId("b")})


def test_inverse_recovery_groups_correctly() -> None:
    recovery = {
        DeviceId("a"): DeviceId("b"),
        DeviceId("c"): DeviceId("b"),
        DeviceId("b"): DeviceId("c"),
    }
    inv = inverse_recovery(recovery)
    assert sorted(inv[DeviceId("b")]) == [DeviceId("a"), DeviceId("c")]
    assert inv[DeviceId("c")] == [DeviceId("b")]
