"""Spec tests for the Recovery-Aware DP scheduler.

Each test is currently skipped — they encode *expected* behavior so that
Phase 1 implementation has a concrete target.
"""

from __future__ import annotations

import pytest

from radp.common.types import ClusterSpec, DeviceId, RecoveryTable
from radp.coordinator.scheduler import Scheduler


def test_two_devices_balanced(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Homogeneous: 4 layers across 2 identical devices -> 2-2 split."""
    pytest.skip("Phase 1: implement Scheduler.solve.")

    recovery: RecoveryTable = {DeviceId("d1"): DeviceId("d2"), DeviceId("d2"): DeviceId("d1")}
    result = Scheduler(homogeneous_spec_2x4).solve(recovery)

    assert [s.device for s in result.placement] == [DeviceId("d1"), DeviceId("d2")]
    assert [(s.start_layer, s.end_layer) for s in result.placement] == [(1, 2), (3, 4)]


def test_heterogeneous_favors_fast(heterogeneous_spec_3x6: ClusterSpec) -> None:
    """Fast device should be assigned more layers than mid/slow."""
    pytest.skip("Phase 1: implement Scheduler.solve.")

    recovery: RecoveryTable = {
        DeviceId("fast"): DeviceId("mid"),
        DeviceId("mid"): DeviceId("slow"),
        DeviceId("slow"): DeviceId("fast"),
    }
    result = Scheduler(heterogeneous_spec_3x6).solve(recovery)

    layer_counts = {s.device: s.end_layer - s.start_layer + 1 for s in result.placement}
    assert layer_counts[DeviceId("fast")] >= layer_counts[DeviceId("mid")]
    assert layer_counts[DeviceId("mid")] >= layer_counts[DeviceId("slow")]


def test_infeasible_raises(homogeneous_spec_2x4: ClusterSpec) -> None:
    """When SLO/memory makes every cell infeasible, NoFeasibleSolutionError is raised."""
    pytest.skip("Phase 1: implement Scheduler.solve + feasibility paths.")
