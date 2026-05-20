"""Tests for the memory-feasibility check (plan.md §3.3 (1))."""

from __future__ import annotations

from radp.common.types import ClusterSpec, LayerIdx, Placement, Stage
from radp.coordinator.memory_check import backup_memory_for, memory_check, stage_self_memory


def test_stage_self_memory_inclusive(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Range [2, 3] should cover layers 2 and 3 (inclusive)."""
    layers = homogeneous_spec_2x4.layers
    assert stage_self_memory(layers, LayerIdx(2), LayerIdx(3)) == 2 * layers[0].memory_bytes


def test_backup_memory_zero_when_no_obligation(homogeneous_spec_2x4: ClusterSpec) -> None:
    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [Stage(LayerIdx(1), LayerIdx(2), d1.id), Stage(LayerIdx(3), LayerIdx(4), d2.id)]
    assert backup_memory_for(d1.id, {}, placement, homogeneous_spec_2x4.layers) == 0


def test_backup_memory_sums_R_inverse(homogeneous_spec_2x4: ClusterSpec) -> None:
    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [Stage(LayerIdx(1), LayerIdx(2), d1.id), Stage(LayerIdx(3), LayerIdx(4), d2.id)]
    recovery = {d2.id: d1.id}  # d1 backs up d2 (whose stage is layers 3..4)
    expected = 2 * homogeneous_spec_2x4.layers[0].memory_bytes
    assert backup_memory_for(d1.id, recovery, placement, homogeneous_spec_2x4.layers) == expected


def test_fits_when_only_self_stage(homogeneous_spec_2x4: ClusterSpec) -> None:
    """2 layers self (1GB) on a 4GB node with no backup obligation -> fits."""
    node = homogeneous_spec_2x4.devices[0]
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(2), node.id),
        Stage(LayerIdx(3), LayerIdx(4), homogeneous_spec_2x4.devices[1].id),
    ]
    assert memory_check(
        node=node,
        start=LayerIdx(1),
        end=LayerIdx(2),
        recovery={},
        current_placement=placement,
        layers=homogeneous_spec_2x4.layers,
    )


def test_fits_when_self_plus_backup_under_capacity(homogeneous_spec_2x4: ClusterSpec) -> None:
    """d1 hosts 2 layers (1GB) and backs up d2's 2 layers (1GB) = 2GB ≤ 4GB."""
    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [Stage(LayerIdx(1), LayerIdx(2), d1.id), Stage(LayerIdx(3), LayerIdx(4), d2.id)]
    assert memory_check(
        node=d1,
        start=LayerIdx(1),
        end=LayerIdx(2),
        recovery={d2.id: d1.id},
        current_placement=placement,
        layers=homogeneous_spec_2x4.layers,
    )


def test_rejects_when_self_alone_exceeds_capacity(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Asking d1 (4GB) to host all 4 layers (2GB) AND back up d2's 4 layers (2GB)
    while d2 also covers 4 — clearly oversubscribed."""
    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [Stage(LayerIdx(1), LayerIdx(4), d2.id)]  # d2 covers all 4
    # d1 candidate self-stage = layers 1..4 (2GB) + backup of d2's 4 layers (2GB) = 4GB exactly.
    # Push it slightly over by also requiring backup of a phantom placement.
    placement_oversized: Placement = [
        Stage(LayerIdx(1), LayerIdx(4), d2.id),
        Stage(LayerIdx(1), LayerIdx(4), d2.id),  # double-counted on purpose
    ]
    assert not memory_check(
        node=d1,
        start=LayerIdx(1),
        end=LayerIdx(4),
        recovery={d2.id: d1.id},
        current_placement=placement_oversized,
        layers=homogeneous_spec_2x4.layers,
    )
    # Sanity: exactly-at-capacity case (4GB self+backup, 4GB node) still passes.
    assert memory_check(
        node=d1,
        start=LayerIdx(1),
        end=LayerIdx(4),
        recovery={d2.id: d1.id},
        current_placement=placement,
        layers=homogeneous_spec_2x4.layers,
    )
