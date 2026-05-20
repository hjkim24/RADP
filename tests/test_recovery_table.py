"""Tests for the recovery-table heuristic (plan.md §3.4, §5.1)."""

from __future__ import annotations

import pytest

from radp.common.types import ClusterSpec, DeviceId, LayerIdx, NoRecoveryError, Placement, Stage
from radp.coordinator.recovery_table import determine_recovery_table


def test_each_device_has_distinct_backup(homogeneous_spec_2x4: ClusterSpec) -> None:
    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(2), d1.id),
        Stage(LayerIdx(3), LayerIdx(4), d2.id),
    ]
    R = determine_recovery_table(homogeneous_spec_2x4, placement)
    assert set(R.keys()) == {d1.id, d2.id}
    for j, k in R.items():
        assert j != k


def test_heterogeneous_picks_fastest_capable_backup(
    heterogeneous_spec_3x6: ClusterSpec,
) -> None:
    """With uniform 2-2-2 split, every node has 1GB headroom plenty. For each j,
    the backup with the smallest (download + recompute) wins. Recompute is
    minimized on the fastest peer."""
    fast, mid, slow = heterogeneous_spec_3x6.devices
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(2), fast.id),
        Stage(LayerIdx(3), LayerIdx(4), mid.id),
        Stage(LayerIdx(5), LayerIdx(6), slow.id),
    ]
    R = determine_recovery_table(heterogeneous_spec_3x6, placement)
    # mid and slow should both prefer `fast` (lowest recompute time).
    assert R[mid.id] == fast.id
    assert R[slow.id] == fast.id
    # `fast` itself must pick between mid and slow; mid has lower recompute.
    assert R[fast.id] == mid.id


def test_raises_when_no_peer_has_capacity() -> None:
    """A 2-device cluster where each device is already maxed out on memory
    leaves no room for any backup — must raise NoRecoveryError."""
    from radp.common.types import (
        SLO,
        ClusterSpec,
        DeviceProfile,
        LayerProfile,
        NetworkProfile,
    )

    devices = [
        DeviceProfile(id=DeviceId("a"), total_memory_bytes=1_000_000_000, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("b"), total_memory_bytes=1_000_000_000, compute_throughput=1.0),
    ]
    # Each layer is 500MB; each device hosts one — uses full capacity.
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=1_000_000_000,
            compute_time={DeviceId("a"): 0.05, DeviceId("b"): 0.05},
        )
        for i in (1, 2)
    ]
    network = NetworkProfile(
        bandwidth={(DeviceId("a"), DeviceId("b")): 1e9, (DeviceId("b"), DeviceId("a")): 1e9},
        latency={(DeviceId("a"), DeviceId("b")): 0.001, (DeviceId("b"), DeviceId("a")): 0.001},
    )
    spec = ClusterSpec(devices=devices, layers=layers, network=network, slo=SLO(1.0, 0.5))
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(1), DeviceId("a")),
        Stage(LayerIdx(2), LayerIdx(2), DeviceId("b")),
    ]
    with pytest.raises(NoRecoveryError):
        determine_recovery_table(spec, placement)
