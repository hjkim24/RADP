"""Recovery table R determination (plan.md §3.4, §5.1).

Initial implementation is a greedy heuristic; later phases may upgrade to
R–Ψ alternating optimization (plan.md §7.2, §8).
"""

from __future__ import annotations

from radp.common.types import (
    ClusterSpec,
    NoRecoveryError,  # noqa: F401  (raised by determine_recovery_table)
    Placement,
    RecoveryTable,
)


def determine_recovery_table(
    spec: ClusterSpec,
    current_placement: Placement,
) -> RecoveryTable:
    """For each device j, pick the backup k minimizing T_download + T_recompute,
    subject to k having enough free memory for j's stage.

    Plan.md §3.4:
        R(j) = argmin_{k ∈ D \\ {j}} [T_download(j -> k) + T_recompute(k)]
        s.t. sum(mem(stage(j))) ≤ free_mem(k)
    """
    raise NotImplementedError


def estimate_download_time(
    spec: ClusterSpec,
    src_stage_bytes: int,
    dst_device_id: str,
    src_device_id: str,
) -> float:
    """Time to ship src's weights into dst's reserve slot (seconds)."""
    raise NotImplementedError


def estimate_recompute_time(
    spec: ClusterSpec,
    src_stage_layers: list[int],
    dst_device_id: str,
) -> float:
    """Time for dst to execute src's stage once after takeover (seconds)."""
    raise NotImplementedError
