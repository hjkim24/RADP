"""Tests for the Recovery-Aware DP scheduler (plan.md §3, §5)."""

from __future__ import annotations

import pytest

from radp.common.types import ClusterSpec, DeviceId, NoFeasibleSolutionError, RecoveryTable
from radp.coordinator.scheduler import Scheduler, uniform_placement


def test_uniform_placement_remainder_to_early_devices(homogeneous_spec_2x4: ClusterSpec) -> None:
    placement = uniform_placement(homogeneous_spec_2x4.devices, num_layers=5)
    assert [(s.start_layer, s.end_layer, s.device) for s in placement] == [
        (1, 3, homogeneous_spec_2x4.devices[0].id),
        (4, 5, homogeneous_spec_2x4.devices[1].id),
    ]


def test_two_devices_balanced(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Homogeneous: 4 layers across 2 identical devices -> exact 2-2 split."""
    recovery: RecoveryTable = {DeviceId("d1"): DeviceId("d2"), DeviceId("d2"): DeviceId("d1")}
    result = Scheduler(homogeneous_spec_2x4).solve(recovery)

    assert [s.device for s in result.placement] == [DeviceId("d1"), DeviceId("d2")]
    assert [(s.start_layer, s.end_layer) for s in result.placement] == [(1, 2), (3, 4)]
    # max stage time = 2 * 0.05 (compute) + 1e6/1e9 + 1e-3 (comm) = 0.102
    assert result.max_stage_time == pytest.approx(0.102, abs=1e-6)


def test_heterogeneous_favors_fast(heterogeneous_spec_3x6: ClusterSpec) -> None:
    """Fast device should get >= as many layers as mid >= slow."""
    recovery: RecoveryTable = {
        DeviceId("fast"): DeviceId("mid"),
        DeviceId("mid"): DeviceId("slow"),
        DeviceId("slow"): DeviceId("fast"),
    }
    result = Scheduler(heterogeneous_spec_3x6).solve(recovery)
    counts = {s.device: s.end_layer - s.start_layer + 1 for s in result.placement}
    assert counts[DeviceId("fast")] >= counts[DeviceId("mid")]
    assert counts[DeviceId("mid")] >= counts[DeviceId("slow")]
    # Coverage: stages must partition all 6 layers contiguously.
    starts_ends = [(s.start_layer, s.end_layer) for s in result.placement]
    assert starts_ends[0][0] == 1
    assert starts_ends[-1][1] == 6
    for (_, e), (s2, _) in zip(starts_ends, starts_ends[1:]):
        assert s2 == e + 1


def test_infeasible_when_slo_too_tight(homogeneous_spec_2x4: ClusterSpec) -> None:
    """If TBT_SLO is below the minimum achievable stage cost, DP must raise."""
    from dataclasses import replace

    tight_slo = replace(homogeneous_spec_2x4, slo=replace(homogeneous_spec_2x4.slo, tbt_seconds=0.001))
    recovery: RecoveryTable = {DeviceId("d1"): DeviceId("d2"), DeviceId("d2"): DeviceId("d1")}
    with pytest.raises(NoFeasibleSolutionError):
        Scheduler(tight_slo).solve(recovery)


def test_infeasible_when_fewer_layers_than_devices(homogeneous_spec_2x4: ClusterSpec) -> None:
    """All-participate assumption: L < M is infeasible by construction."""
    from dataclasses import replace

    spec = replace(homogeneous_spec_2x4, layers=homogeneous_spec_2x4.layers[:1])
    with pytest.raises(NoFeasibleSolutionError):
        Scheduler(spec).solve({DeviceId("d1"): DeviceId("d2"), DeviceId("d2"): DeviceId("d1")})


def test_end_to_end_with_auto_recovery(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Full flow: round-robin initial -> determine_recovery_table -> solve."""
    from radp.coordinator.recovery_table import determine_recovery_table

    init = uniform_placement(homogeneous_spec_2x4.devices, len(homogeneous_spec_2x4.layers))
    recovery = determine_recovery_table(homogeneous_spec_2x4, init)
    result = Scheduler(homogeneous_spec_2x4).solve(recovery)
    assert len(result.placement) == len(homogeneous_spec_2x4.devices)
    assert result.recovery == recovery
