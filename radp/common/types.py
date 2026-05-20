"""Core type definitions shared across all RADP modules.

Mirrors the notation used in plan.md §3:
  - Psi (placement)  -> Placement      = list[Stage]
  - R   (recovery)   -> RecoveryTable  = dict[DeviceId, DeviceId]
  - mem(i), T_comp, T_comm             -> LayerProfile, NetworkProfile
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NewType

DeviceId = NewType("DeviceId", str)
LayerIdx = NewType("LayerIdx", int)
RequestId = NewType("RequestId", int)


@dataclass(frozen=True)
class DeviceProfile:
    """A single edge device (e.g., one Jetson Nano)."""

    id: DeviceId
    total_memory_bytes: int
    compute_throughput: float
    """Normalized scalar; baseline Jetson Nano = 1.0."""


@dataclass(frozen=True)
class LayerProfile:
    """Per-layer resource footprint.

    `memory_bytes` is the layer weight + estimated KV-cache headroom.
    `compute_time` is a per-device measurement (T_comp(i, d)).
    """

    layer_idx: LayerIdx
    memory_bytes: int
    compute_time: dict[DeviceId, float]


@dataclass(frozen=True)
class NetworkProfile:
    """Pairwise network characteristics between devices."""

    bandwidth: dict[tuple[DeviceId, DeviceId], float]
    """bytes / second"""
    latency: dict[tuple[DeviceId, DeviceId], float]
    """one-way seconds (typically RTT/2)"""


@dataclass(frozen=True)
class Stage:
    """A contiguous layer range assigned to a single device.

    Layer indices are 1-based and **inclusive** on both ends to match plan.md.
    """

    start_layer: LayerIdx
    end_layer: LayerIdx
    device: DeviceId


Placement = list[Stage]
"""Ordered pipeline: stages[0] runs first, stages[-1] last."""

RecoveryTable = dict[DeviceId, DeviceId]
"""R(j) = k means k is j's backup. Plan.md §3.4."""


@dataclass(frozen=True)
class SLO:
    """Service-level objectives (plan.md §3.3 (2))."""

    ttft_seconds: float
    tbt_seconds: float


@dataclass(frozen=True)
class DPResult:
    """Output of the Recovery-Aware DP."""

    placement: Placement
    recovery: RecoveryTable
    max_stage_time: float
    """Objective value A(L, |D|) — the slowest stage time."""


@dataclass(frozen=True)
class AlternatingIterationLog:
    """One iteration of the R-Ψ alternating loop."""

    iteration: int
    max_stage_time: float
    self_consistent: bool
    """True iff Ψ_i's own backup burden fits within memory (the DP used
    Ψ_{i-1} as its reference, so this may differ)."""
    psi_changed: bool
    """True iff Ψ_i ≠ Ψ_{i-1} (also true on the first iteration)."""
    r_changed: bool


@dataclass(frozen=True)
class AlternatingResult:
    """Output of Scheduler.solve_alternating (plan.md §3.4 / §7.2)."""

    placement: Placement
    recovery: RecoveryTable
    max_stage_time: float
    iterations: int
    converged: bool
    """True iff (R_i, Ψ_i) == (R_{i-1}, Ψ_{i-1}) and Ψ_i is self-consistent.
    False means we returned the best self-consistent intermediate found
    within ``max_iterations``."""
    history: list[AlternatingIterationLog]


@dataclass(frozen=True)
class ClusterSpec:
    """A whole cluster's static configuration, passed to the scheduler."""

    devices: list[DeviceProfile]
    layers: list[LayerProfile]
    network: NetworkProfile
    slo: SLO
    activation_bytes: int = 1_000_000
    """Size of one inter-stage activation payload (bytes). Used for T_comm."""
    extras: dict[str, str] = field(default_factory=dict)


# --- Exceptions -------------------------------------------------------------


class RADPError(Exception):
    """Base class for all RADP errors."""


class NoFeasibleSolutionError(RADPError):
    """Raised by the DP when every (y, n) cell is infeasible."""


class NoRecoveryError(RADPError):
    """Raised when a device has no viable backup candidate."""
