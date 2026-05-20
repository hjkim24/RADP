"""Recovery table R determination (plan.md §3.4, §5.1).

R(j) = argmin over k ≠ j of [T_download(j → k) + T_recompute(k)]
       s.t.  Σ mem(stage(j)) ≤ free_mem(k)

Phase 1 uses a simple greedy heuristic; future work (plan.md §7.2, §8) may
upgrade to R–Ψ alternating optimization.
"""

from __future__ import annotations

from radp.common.types import (
    ClusterSpec,
    DeviceId,
    NoRecoveryError,
    Placement,
    RecoveryTable,
    Stage,
)


def estimate_download_time(
    spec: ClusterSpec,
    src_stage_bytes: int,
    dst_device_id: DeviceId,
    src_device_id: DeviceId,
) -> float:
    """Seconds to ship src's stage weights into dst's reserve slot.

    Plan.md models this as bandwidth-bound; we add one-way latency for completeness.
    """
    key = (src_device_id, dst_device_id)
    bw = spec.network.bandwidth.get(key)
    lat = spec.network.latency.get(key, 0.0)
    if bw is None or bw <= 0:
        return float("inf")
    return src_stage_bytes / bw + lat


def estimate_recompute_time(
    spec: ClusterSpec,
    src_stage_layers: list[int],
    dst_device_id: DeviceId,
) -> float:
    """Seconds for dst to execute src's stage once after takeover."""
    total = 0.0
    for layer_idx in src_stage_layers:
        layer = spec.layers[layer_idx - 1]
        t = layer.compute_time.get(dst_device_id)
        if t is None:
            return float("inf")
        total += t
    return total


def _stage_bytes(spec: ClusterSpec, stage: Stage) -> int:
    return sum(
        spec.layers[i - 1].memory_bytes
        for i in range(stage.start_layer, stage.end_layer + 1)
    )


def determine_recovery_table(
    spec: ClusterSpec,
    current_placement: Placement,
) -> RecoveryTable:
    """For each device j, choose the backup k minimizing (download + recompute),
    subject to k having enough free memory for j's stage.

    Free memory for k is approximated as `Mem(k) - mem(stage(k))`. This is a
    Phase 1 simplification — fully joint feasibility is left to the DP itself.
    """
    placement_by_device: dict[DeviceId, Stage] = {s.device: s for s in current_placement}

    # Precompute each device's own stage byte usage (the "in use" portion).
    self_usage: dict[DeviceId, int] = {
        d.id: _stage_bytes(spec, placement_by_device[d.id]) if d.id in placement_by_device else 0
        for d in spec.devices
    }

    recovery: RecoveryTable = {}
    for j in spec.devices:
        j_stage = placement_by_device.get(j.id)
        if j_stage is None:
            # j has no primary stage; nothing to back up.
            continue
        j_stage_bytes = self_usage[j.id]
        j_stage_layers = list(range(j_stage.start_layer, j_stage.end_layer + 1))

        best_k: DeviceId | None = None
        best_cost = float("inf")
        for k in spec.devices:
            if k.id == j.id:
                continue
            free = k.total_memory_bytes - self_usage[k.id]
            if free < j_stage_bytes:
                continue
            cost = estimate_download_time(
                spec, j_stage_bytes, k.id, j.id
            ) + estimate_recompute_time(spec, j_stage_layers, k.id)
            if cost < best_cost:
                best_cost = cost
                best_k = k.id

        if best_k is None:
            raise NoRecoveryError(
                f"Device {j.id} has no viable backup: every peer lacks free memory "
                f"for {j_stage_bytes} bytes."
            )
        recovery[j.id] = best_k

    return recovery
