"""Memory feasibility check for the Recovery-Aware DP (plan.md §3.3 (1), §5.4).

A device k is feasible for a candidate self-stage [start, end] iff
    Σ mem(i) for i in [start, end]                          (self)
  + Σ Σ mem(i) for j in R⁻¹(k), i in stage_of(j, placement) (backup)
  ≤ Mem(k)

Layer indices are 1-based and inclusive on both ends (matches plan.md).
"""

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
    """Σ mem(i) for i ∈ [start, end]. Both ends inclusive, 1-based."""
    if start < 1 or end > len(layers) or start > end:
        raise ValueError(f"Invalid layer range [{start}, {end}] for {len(layers)} layers")
    return sum(layers[i - 1].memory_bytes for i in range(start, end + 1))


def backup_memory_for(
    node: DeviceId,
    recovery: RecoveryTable,
    current_placement: Placement,
    layers: list[LayerProfile],
) -> int:
    """Total memory `node` must reserve for every j with R(j) == node."""
    backup_sources = [j for j, k in recovery.items() if k == node]
    if not backup_sources:
        return 0

    stages_by_device: dict[DeviceId, list[tuple[LayerIdx, LayerIdx]]] = {}
    for stage in current_placement:
        stages_by_device.setdefault(stage.device, []).append((stage.start_layer, stage.end_layer))

    total = 0
    for j in backup_sources:
        for start, end in stages_by_device.get(j, []):
            total += stage_self_memory(layers, start, end)
    return total


def memory_check(
    node: DeviceProfile,
    start: LayerIdx,
    end: LayerIdx,
    recovery: RecoveryTable,
    current_placement: Placement,
    layers: list[LayerProfile],
    *,
    eager_backup: bool = True,
) -> bool:
    """True iff `node` can host the proposed self-stage AND its backup obligations.

    `current_placement` is used only to look up stage sizes of devices j ∈ R⁻¹(node);
    it does NOT need to reflect the candidate self-stage [start, end] being tested.

    `eager_backup` controls whether backup memory is reserved at deploy time
    (default; the Recovery-Aware DP design) or lazy-loaded on failure (A5).
    When False, only the self-stage memory is checked; backup peers trust
    that they'll have enough free memory at fault time to load weights from
    disk.
    """
    self_mem = stage_self_memory(layers, start, end)
    # Prefer heartbeat-reported free over hardware-spec total — see
    # recovery_table for the same reasoning (EXP-D2.4 OOM cycle root cause).
    budget = node.free_memory_bytes or node.total_memory_bytes
    if not eager_backup:
        return self_mem <= budget
    backup_mem = backup_memory_for(node.id, recovery, current_placement, layers)
    return self_mem + backup_mem <= budget
