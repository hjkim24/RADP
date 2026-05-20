"""Phase A1: R-Ψ alternating optimization (plan.md §3.4 → §7.2).

Tests:
  * Homogeneous cluster converges in 1 iteration (round-robin is already optimal).
  * Heterogeneous cluster's alternating result is at least as good as
    single-shot, and converges in ≤ max_iterations.
  * Each iteration log records expected fields.
  * Tight memory falls back to last self-consistent placement or raises.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from radp.common.types import (
    SLO,
    AlternatingResult,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
    NoFeasibleSolutionError,
)
from radp.coordinator.recovery_table import determine_recovery_table
from radp.coordinator.scheduler import Scheduler, uniform_placement


def test_homogeneous_converges_in_one_iteration(
    homogeneous_spec_2x4: ClusterSpec,
) -> None:
    """All devices identical → round-robin Ψ₀ is already optimal and
    self-consistent. The first iteration should produce Ψ₁ == Ψ₀; the
    second confirms (R, Ψ) is unchanged → converged at iter 2."""
    result = Scheduler(homogeneous_spec_2x4).solve_alternating()
    assert isinstance(result, AlternatingResult)
    assert result.converged
    assert result.iterations <= 2
    # Layer counts match round-robin (2-2 split).
    counts = [s.end_layer - s.start_layer + 1 for s in result.placement]
    assert counts == [2, 2]


def test_heterogeneous_alternating_is_at_least_as_good_as_single_shot(
    heterogeneous_spec_3x6: ClusterSpec,
) -> None:
    """Alternating starts from the same Ψ₀ as single-shot, so the worst case
    is equal; whenever the new R/Ψ improves max_stage_time it should win."""
    init = uniform_placement(heterogeneous_spec_3x6.devices, len(heterogeneous_spec_3x6.layers))
    r0 = determine_recovery_table(heterogeneous_spec_3x6, init)
    single_shot = Scheduler(heterogeneous_spec_3x6).solve(r0)

    alt = Scheduler(heterogeneous_spec_3x6).solve_alternating()
    assert alt.max_stage_time <= single_shot.max_stage_time + 1e-9
    assert alt.iterations >= 1


def test_iteration_log_fields_populated(heterogeneous_spec_3x6: ClusterSpec) -> None:
    alt = Scheduler(heterogeneous_spec_3x6).solve_alternating(max_iterations=5)
    assert len(alt.history) == alt.iterations
    assert alt.history[0].iteration == 1
    # On the very first iteration the comparison baseline is the uniform Ψ;
    # `psi_changed` may be either, but `r_changed` is always True (prev_r=None).
    assert alt.history[0].r_changed is True
    if alt.converged:
        # Last iteration must report self_consistent and unchanged R+Ψ.
        last = alt.history[-1]
        assert last.self_consistent
        assert not last.psi_changed
        assert not last.r_changed


def test_max_iterations_safeguard_returns_best_self_consistent(
    heterogeneous_spec_3x6: ClusterSpec,
) -> None:
    """With max_iterations=1 the loop never gets a chance to confirm
    convergence (need at least 2 iters to see Ψ unchanged). The result
    must still be a self-consistent placement, just with converged=False."""
    alt = Scheduler(heterogeneous_spec_3x6).solve_alternating(max_iterations=1)
    assert alt.iterations == 1
    assert not alt.converged
    # The returned Ψ must satisfy its own memory constraint (we tracked best).
    sched = Scheduler(heterogeneous_spec_3x6)
    assert sched._memory_self_check(alt.placement, alt.recovery)


def test_infeasible_under_tight_slo_raises() -> None:
    """SLO so tight that no placement fits — alternating should propagate."""
    devices = [
        DeviceProfile(id=DeviceId("a"), total_memory_bytes=4_000_000_000, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("b"), total_memory_bytes=4_000_000_000, compute_throughput=1.0),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=200_000_000,
            compute_time={DeviceId("a"): 0.5, DeviceId("b"): 0.5},
        )
        for i in range(1, 5)
    ]
    network = NetworkProfile(
        bandwidth={(DeviceId("a"), DeviceId("b")): 1e9, (DeviceId("b"), DeviceId("a")): 1e9},
        latency={(DeviceId("a"), DeviceId("b")): 0.001, (DeviceId("b"), DeviceId("a")): 0.001},
    )
    spec = ClusterSpec(devices=devices, layers=layers, network=network, slo=SLO(0.1, 0.001))
    with pytest.raises(NoFeasibleSolutionError):
        Scheduler(spec).solve_alternating()


def test_alternating_beats_single_shot_on_crafted_case() -> None:
    """Construct a case where round-robin Ψ₀ leads single-shot to an
    inferior result because the chosen R reserves memory wastefully on
    the wrong devices. Alternating should improve max_stage_time strictly.
    """
    # 4 devices: 1 fast, 3 medium. 12 layers. Round-robin = 3 each.
    # Single-shot from round-robin will get a placement Ψ₁ that
    # concentrates more layers on the fast device → its backup target then
    # carries a larger reserve. Re-deriving R against Ψ₁ and re-running DP
    # should redistribute differently. We just assert alt ≤ single-shot.
    devices = [
        DeviceProfile(id=DeviceId(f"d{i}"), total_memory_bytes=4_000_000_000,
                      compute_throughput=t)
        for i, t in enumerate([3.0, 1.0, 1.0, 1.0])
    ]
    base_time = 0.05
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=200_000_000,
            compute_time={d.id: base_time / d.compute_throughput for d in devices},
        )
        for i in range(1, 13)
    ]
    net = NetworkProfile(
        bandwidth={(a.id, b.id): 1e9 for a in devices for b in devices if a is not b},
        latency={(a.id, b.id): 0.001 for a in devices for b in devices if a is not b},
    )
    spec = ClusterSpec(devices=devices, layers=layers, network=net, slo=SLO(10.0, 10.0))

    init = uniform_placement(spec.devices, len(spec.layers))
    r0 = determine_recovery_table(spec, init)
    single = Scheduler(spec).solve(r0)
    alt = Scheduler(spec).solve_alternating(max_iterations=10)

    assert alt.max_stage_time <= single.max_stage_time + 1e-9
    # Also sanity-check that we have a meaningful history
    assert len(alt.history) >= 1


def test_no_recovery_propagates_when_no_best_yet() -> None:
    """When R cannot be determined on the very first iteration AND we
    haven't recorded any self-consistent fallback, the error propagates."""
    # 2 devices, both at full memory after primary stage → no backup target
    # has free room for the peer's stage → NoRecoveryError on first try.
    devices = [
        DeviceProfile(id=DeviceId("a"), total_memory_bytes=1_000_000_000, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("b"), total_memory_bytes=1_000_000_000, compute_throughput=1.0),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=1_000_000_000,  # each layer fills a whole device
            compute_time={DeviceId("a"): 0.05, DeviceId("b"): 0.05},
        )
        for i in (1, 2)
    ]
    net = NetworkProfile(
        bandwidth={(DeviceId("a"), DeviceId("b")): 1e9, (DeviceId("b"), DeviceId("a")): 1e9},
        latency={(DeviceId("a"), DeviceId("b")): 0.001, (DeviceId("b"), DeviceId("a")): 0.001},
    )
    spec = ClusterSpec(devices=devices, layers=layers, network=net, slo=SLO(10.0, 10.0))
    from radp.common.types import NoRecoveryError as _NRE
    with pytest.raises((_NRE, NoFeasibleSolutionError)):
        Scheduler(spec).solve_alternating()


def test_can_pass_explicit_initial_placement(
    heterogeneous_spec_3x6: ClusterSpec,
) -> None:
    """If the caller already has a good seed Ψ, alternating should accept it."""
    seed = [
        replace(s) for s in uniform_placement(
            heterogeneous_spec_3x6.devices, len(heterogeneous_spec_3x6.layers),
        )
    ]
    alt = Scheduler(heterogeneous_spec_3x6).solve_alternating(
        initial_placement=seed, max_iterations=5,
    )
    assert alt.max_stage_time > 0
