"""Memory feasibility check for the Recovery-Aware DP (plan.md §3.3 (1), §5.4)."""

from __future__ import annotations

from radp.common.types import (
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    Placement,
    RecoveryTable,
)


def stage_self_memory(layers: list[LayerProfile], start: LayerIdx, end: LayerIdx) -> int:
    """Σ mem(i) for i ∈ [start, end]."""
    raise NotImplementedError


def backup_memory_for(
    node: DeviceId,
    recovery: RecoveryTable,
    current_placement: Placement,
    layers: list[LayerProfile],
) -> int:
    """Total memory `node` must reserve for every j with R(j) == node.

    Walks R⁻¹(node) and sums mem(stage(j)) for each such j.
    """
    raise NotImplementedError


def memory_check(
    node: DeviceProfile,
    start: LayerIdx,
    end: LayerIdx,
    recovery: RecoveryTable,
    current_placement: Placement,
    layers: list[LayerProfile],
) -> bool:
    """Can `node` host the proposed self-stage AND its backup obligations?

    Returns True iff:
        stage_self_memory + backup_memory_for(node) ≤ node.total_memory_bytes
    """
    raise NotImplementedError
