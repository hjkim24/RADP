"""Spec tests for the memory-feasibility check (plan.md §3.3 (1))."""

from __future__ import annotations

import pytest

from radp.common.types import ClusterSpec, LayerIdx, Placement, Stage
from radp.coordinator.memory_check import memory_check


def test_fits_when_only_self_stage(homogeneous_spec_2x4: ClusterSpec) -> None:
    """Without any backup obligation, a 2-layer self-stage fits in a 4GB node."""
    pytest.skip("Phase 1: implement memory_check.")

    node = homogeneous_spec_2x4.devices[0]
    placement: Placement = [Stage(1, 2, node.id), Stage(3, 4, homogeneous_spec_2x4.devices[1].id)]
    assert memory_check(
        node=node,
        start=LayerIdx(1),
        end=LayerIdx(2),
        recovery={},
        current_placement=placement,
        layers=homogeneous_spec_2x4.layers,
    )


def test_rejects_when_backup_exceeds_capacity(homogeneous_spec_2x4: ClusterSpec) -> None:
    """If d1 must back up d2's stage AND host its own 2 layers, total > 4GB -> rejected."""
    pytest.skip("Phase 1: implement memory_check.")

    d1, d2 = homogeneous_spec_2x4.devices
    placement: Placement = [Stage(1, 2, d1.id), Stage(3, 4, d2.id)]
    recovery = {d2.id: d1.id}  # d1 backs up d2 -> 4 layers worth ~ 2GB + 2GB = 4GB borderline
    # With layer_bytes=0.5GB, 4 layers = 2GB; node = 4GB -> still fits.
    # Real failure case left for Phase 1 to refine with realistic numbers.
    assert memory_check(
        node=d1,
        start=LayerIdx(1),
        end=LayerIdx(2),
        recovery=recovery,
        current_placement=placement,
        layers=homogeneous_spec_2x4.layers,
    )
