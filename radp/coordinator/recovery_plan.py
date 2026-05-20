"""Failure-aware execution-plan computation.

Given the original placement Ψ, the recovery table R, and a set of dead
devices, produce an execution plan that:
  - replaces every dead stage with a call on its backup (R(j) = k)
  - keeps the surviving stages where they were
  - preserves the layer order (1..L), since OPT blocks are not commutative

A plan is just ``list[Stage]`` (same type as Placement); the same device
may appear multiple times when it covers both its own primary and a
backed-up peer's stage. Each Stage carries the explicit (start, end)
layer range, so the worker knows which loaded ModuleList to invoke.
"""

from __future__ import annotations

from radp.common.logging_utils import get_logger
from radp.common.types import (
    DeviceId,
    NoRecoveryError,
    Placement,
    RecoveryTable,
    Stage,
)

log = get_logger(__name__)


def build_execution_plan(
    placement: Placement,
    recovery: RecoveryTable,
    dead: set[DeviceId],
) -> Placement:
    """Translate the original placement into a runnable plan given dead nodes."""
    plan: Placement = []
    for stage in placement:
        if stage.device not in dead:
            plan.append(stage)
            continue
        backup = recovery.get(stage.device)
        if backup is None or backup in dead:
            raise NoRecoveryError(
                f"Device {stage.device} is dead and its backup "
                f"{backup!r} is unavailable"
            )
        log.info(
            "execution plan: layers[%d..%d] %s -> %s (backup)",
            stage.start_layer, stage.end_layer, stage.device, backup,
        )
        plan.append(
            Stage(
                start_layer=stage.start_layer,
                end_layer=stage.end_layer,
                device=backup,
            )
        )
    return plan


def inverse_recovery(recovery: RecoveryTable) -> dict[DeviceId, list[DeviceId]]:
    """R⁻¹: for each backup-target k, list the devices j with R(j)=k."""
    inverse: dict[DeviceId, list[DeviceId]] = {}
    for j, k in recovery.items():
        inverse.setdefault(k, []).append(j)
    return inverse
