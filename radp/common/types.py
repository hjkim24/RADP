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
    free_memory_bytes: int = 0
    """Actual free memory at the time the heartbeat was captured. Used by
    memory_check / recovery_table to gate primary + backup layer
    assignments on what the device CAN load right now, not the
    hardware-spec ceiling. When 0 (legacy / uninitialised), callers fall
    back to total_memory_bytes for backwards compatibility."""


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
class StageTiming:
    """Per-stage wall clock observed at the coordinator for one pipeline step.

    Captured by RequestGateway._run_pipeline. `invoke_seconds` is the full
    gRPC round-trip (encode + RunStage RPC + decode), so it covers both
    activation transfer and worker-side compute. The split between the two
    isn't measurable from the coordinator alone — that would need worker-
    side timestamps in the RunStage response (future work).
    """

    device: DeviceId
    start_layer: int
    end_layer: int
    invoke_seconds: float


@dataclass(frozen=True)
class DPResult:
    """Output of the Recovery-Aware DP."""

    placement: Placement
    recovery: RecoveryTable
    max_stage_time: float
    """Slowest single stage's wall-clock — the throughput-bound metric."""
    sum_stage_time: float = 0.0
    """Σ stage_time across all stages — the single-stream latency metric.
    Default 0.0 keeps backwards compat with throughput-only call sites
    that don't populate it; new callers should fill both."""


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
    sum_stage_time: float = 0.0


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
    sum_stage_time: float = 0.0


@dataclass(frozen=True)
class ClusterSpec:
    """A whole cluster's static configuration, passed to the scheduler."""

    devices: list[DeviceProfile]
    layers: list[LayerProfile]
    network: NetworkProfile
    slo: SLO
    activation_bytes: int = 1_000_000
    """Size of one inter-stage activation payload (bytes). Used for T_comm."""
    eager_backup: bool = True
    """If True (default), each device must reserve memory for its assigned
    backup-source layers at deploy time — gives ~600 ms graceful recovery
    but constrains primary placement (a fast device can't take more layers
    than its backup peer can also hold). If False, the DP ignores backup
    memory burden and trusts that lazy weight-loading on failure will fit
    in whatever the backup peer has free at the time. Lazy mode trades a
    slower recovery (weights load from disk, ~5-30 s) and potential
    in-flight KV cache loss for better steady-state throughput on the
    primary node. See backlog item A5."""
    optimization_mode: str = "throughput"
    """Cost-function family for the DP. The scheduler tracks both Σ stage
    cost and max stage cost in every cell and ranks candidate placements
    by a mode-specific function of (sum, max):

      throughput → max               (EdgeShard throughput / Jupiter Eq. 1)
      latency    → sum               (EdgeShard latency Eq. 6, batch=1)
      blended    → sum + α·max       (Jupiter Eq. 4 with α=|D|-1 at k=1)

    SLO interaction:
      throughput — per-stage cost ≤ TBT_SLO is enforced inline as a hard
                   constraint (keeps individual stages within QoS under
                   concurrent load).
      latency    — per-stage SLO is NOT enforced inline (every layer added
                   to a fast device monotonically improves the sum, and
                   capping any single stage would just spread layers thin
                   and inflate Σ). SLO becomes a post-hoc feasibility
                   check on the final placement.

    See PHASES.md EXP-D2.3 for the cost-function discussion."""
    blend_alpha: float = 0.0
    """For optimization_mode='blended': the α weight on max in
    `sum + α·max`. At α=0 collapses to latency; at α=|D|-1 reproduces
    Jupiter's Eq. 4 single-sub-sequence case; large α approaches
    throughput-mode behavior. Ignored for other modes."""
    hop_overhead_seconds: float = 0.0
    """Per-hop fixed overhead added to T_comm beyond the wire-level
    transfer time (activation_bytes / bandwidth + latency). Models the
    gRPC framing + Python/GIL contention + scheduler delay that the
    wire-only T_comm misses — measured at ~8–10 ms per hop on live
    Jetson fleets (EXP-D2.5 + project_dp_comm_cost_underestimate).
    Default 0.0 preserves the legacy wire-only model; non-zero values
    make placements with many small stages cost more inside the DP
    so the optimiser stops loving 4-stage solutions in throughput
    mode when 2-stage with bulk-on-fast-device is the real max-min
    answer. EXP-D2.7 tests this directly. See PHASES.md."""
    target_concurrency: int = 1
    """Concurrency level the DP optimises for. With the default 1, the
    multi-stream interference term is a no-op (multiplier = 1) and the
    scheduler returns single-stream behaviour identical to pre-D2.8.
    Set to the expected steady-state concurrency (e.g. 16) to surface
    multi-stream queueing pressure in the DP cost — see
    thread_pool_size for the saturation point."""
    thread_pool_size: int = 30
    """Number of gRPC handler threads available per worker (matches the
    runtime ThreadPoolExecutor in WorkerServer). The DP uses
    target_concurrency * num_stages / thread_pool_size as a pool-
    saturation multiplier on T_stage: under saturation each in-flight
    stream waits its turn, so stage time inflates linearly. EXP-D2.8
    cost-model v2: a *necessary* but *insufficient* term on a
    homogeneous fleet, where the per-subset multiplier cancels against
    the per-subset max_T scaling and leaves the argmax untouched —
    pair it with stage_count_penalty_seconds for an effective swing."""
    stage_count_penalty_seconds: float = 0.0
    """EXP-D2.8 cost-model v2: an additive penalty applied to the
    outer-search rank as γ · |ψ|. Models the per-stage system overhead
    that doesn't show up in T_comm — task scheduling, coordinator
    bookkeeping, per-stage GIL+lock contention amortised across the
    whole pipeline — and unlike a multiplier, it does break the
    homogeneous-fleet indifference because *additive* penalties are
    sensitive to absolute stage count, not just ratios. Default 0.0
    preserves the legacy max-min argmax. Live calibration on the
    8-worker Jetson fleet (EXP-D2.8) targets the value where 2-stage
    L mode matches measured throughput dominance over 4-stage T mode."""
    extras: dict[str, str] = field(default_factory=dict)


# --- Exceptions -------------------------------------------------------------


class RADPError(Exception):
    """Base class for all RADP errors."""


class NoFeasibleSolutionError(RADPError):
    """Raised by the DP when every (y, n) cell is infeasible."""


class NoRecoveryError(RADPError):
    """Raised when a device has no viable backup candidate."""
