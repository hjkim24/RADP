"""Spec tests for the recovery-table heuristic."""

from __future__ import annotations

import pytest

from radp.common.types import ClusterSpec, DeviceId, Placement, Stage
from radp.coordinator.recovery_table import determine_recovery_table


def test_each_device_has_distinct_backup(homogeneous_spec_2x4: ClusterSpec) -> None:
    pytest.skip("Phase 1: implement determine_recovery_table.")

    placement: Placement = [
        Stage(1, 2, DeviceId("d1")),  # type: ignore[arg-type]
        Stage(3, 4, DeviceId("d2")),  # type: ignore[arg-type]
    ]
    R = determine_recovery_table(homogeneous_spec_2x4, placement)
    for j, k in R.items():
        assert j != k
