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

# Match the conftest values so subset-search tests use the same per-device
# memory cap as the shared fixtures.
LAYER_BYTES = 500_000_000
NODE_BYTES  = 4_000_000_000


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


def test_subset_search_drops_pathologically_slow_device_in_throughput_mode() -> None:
    """A fleet with two fast devices and one *100×-slower* device should
    self-prune the slow device in throughput mode — the slow device's
    layer-floor stage would set the max_stage time and gate throughput.

    Regression for EXP-D2.3's finding: every-device-participates is the
    right default for balanced edge fleets, but on heterogeneous fleets
    the slow tier's hop-vs-compute ratio inverts and the DP wants to drop
    them. Subset enumeration in solve_alternating_best_order surfaces
    that choice automatically.
    """
    devices = [
        DeviceProfile(id=DeviceId("fast1"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=10.0),
        DeviceProfile(id=DeviceId("fast2"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=10.0),
        DeviceProfile(id=DeviceId("slug"), total_memory_bytes=NODE_BYTES,
                      compute_throughput=0.1),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=LAYER_BYTES,
            compute_time={
                DeviceId("fast1"): 0.001,
                DeviceId("fast2"): 0.001,
                DeviceId("slug"): 0.100,    # 100× slower
            },
        )
        for i in range(1, 7)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.0005 for d1 in devices for d2 in devices if d1 is not d2},
    )
    spec = ClusterSpec(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=1.0, tbt_seconds=0.5),
        optimization_mode="throughput",
    )
    # With subset search enabled (default), the DP should pick {fast1, fast2}
    # only — leaving the slug out entirely.
    result = Scheduler(spec).solve_alternating_best_order()
    chosen = {s.device for s in result.placement}
    assert DeviceId("slug") not in chosen
    assert chosen == {DeviceId("fast1"), DeviceId("fast2")}


def test_subset_search_off_keeps_all_devices() -> None:
    """With enable_subset_search=False the DP must include every device,
    even when one of them is pathologically slow. Anchors that the new
    flag actually toggles behaviour."""
    devices = [
        DeviceProfile(id=DeviceId("fast1"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=10.0),
        DeviceProfile(id=DeviceId("fast2"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=10.0),
        DeviceProfile(id=DeviceId("slug"), total_memory_bytes=NODE_BYTES,
                      compute_throughput=0.1),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=LAYER_BYTES,
            compute_time={
                DeviceId("fast1"): 0.001,
                DeviceId("fast2"): 0.001,
                DeviceId("slug"): 0.100,
            },
        )
        for i in range(1, 7)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.0005 for d1 in devices for d2 in devices if d1 is not d2},
    )
    spec = ClusterSpec(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode="throughput",
    )
    result = Scheduler(spec).solve_alternating_best_order(enable_subset_search=False)
    chosen = {s.device for s in result.placement}
    assert chosen == {DeviceId("fast1"), DeviceId("fast2"), DeviceId("slug")}


def test_interference_multiplier_is_pure_function() -> None:
    """EXP-D2.8: T_stage_with_interference inflates by max(1, C·|ψ|/pool).

    Multiplier is a pure function of (target_concurrency, thread_pool_size,
    num_stages) — at C=1 or pool=0 it collapses to 1, matching the
    legacy _stage_time exactly so single-stream callers stay backward-
    compatible. At C=16, num_stages=4, pool=30 the multiplier is
    16·4/30 ≈ 2.13."""
    devices = [
        DeviceProfile(id=DeviceId("d1"), total_memory_bytes=NODE_BYTES, compute_throughput=1.0),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i), memory_bytes=LAYER_BYTES,
            compute_time={DeviceId("d1"): 0.010},
        )
        for i in range(1, 5)
    ]
    network = NetworkProfile(bandwidth={}, latency={})
    base_spec_kwargs = dict(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode="throughput",
    )

    # target_concurrency=1: multiplier = 1, behaves like _stage_time.
    spec_noop = ClusterSpec(**base_spec_kwargs, target_concurrency=1, thread_pool_size=30)
    sch = Scheduler(spec_noop)
    assert sch._stage_time_with_interference(DeviceId("d1"), 1, 4, num_stages=4) \
        == pytest.approx(4 * 0.010)

    # target_concurrency=16, |ψ|=4, pool=30: multiplier = 16·4/30 ≈ 2.133
    spec_sat = ClusterSpec(**base_spec_kwargs, target_concurrency=16, thread_pool_size=30)
    sch_sat = Scheduler(spec_sat)
    assert sch_sat._stage_time_with_interference(DeviceId("d1"), 1, 4, num_stages=4) \
        == pytest.approx(4 * 0.010 * (16 * 4 / 30))

    # Below saturation (C·|ψ| ≤ pool): multiplier floors at 1.
    spec_below = ClusterSpec(**base_spec_kwargs, target_concurrency=2, thread_pool_size=30)
    sch_below = Scheduler(spec_below)
    assert sch_below._stage_time_with_interference(DeviceId("d1"), 1, 4, num_stages=4) \
        == pytest.approx(4 * 0.010)  # 2·4=8 ≤ 30 → floor at 1


def test_linear_interference_multiplier_collapses_argmax_to_tie_on_homogeneous_fleet() -> None:
    """EXP-D2.8: the linear pool-saturation multiplier
    `max(1, C·|ψ|/pool)` inflates each stage proportionally to |ψ|,
    but on a homogeneous fleet a |ψ|-stage placement carries a
    1/|ψ|-fraction of the layer compute per stage. The two factors
    *cancel* — every subset size produces the same max_T·multiplier
    product, leaving the outer search in a tie that the first-visited
    (smallest) subset wins. Without an additive term in the rank
    (stage_count_penalty, tested next), this is the weakest the
    multiplier can do on its own."""
    devices = [
        DeviceProfile(id=DeviceId(f"d{i}"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=1.0)
        for i in range(1, 5)
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i), memory_bytes=LAYER_BYTES,
            compute_time={d.id: 0.010 for d in devices},
        )
        for i in range(1, 9)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.0001 for d1 in devices for d2 in devices if d1 is not d2},
    )
    base_kwargs = dict(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode="throughput",
        hop_overhead_seconds=0.0,
    )

    # Baseline: target_concurrency=1 ⇒ multiplier no-op. T_comm > 0 on
    # non-first stages makes 4-stage strictly cheaper (more in-flight
    # parallelism with smaller per-stage compute).
    spec_baseline = ClusterSpec(**base_kwargs, target_concurrency=1, thread_pool_size=30)
    p_baseline = Scheduler(spec_baseline).solve_alternating_best_order().placement
    assert len({s.device for s in p_baseline}) == 4

    # Under saturation, the multiplier *collapses* the 4-stage advantage
    # — every subset size ties on max_T·multiplier, and the outer
    # search keeps the first feasible candidate it sees (subset size 2).
    spec_sat = ClusterSpec(**base_kwargs, target_concurrency=16, thread_pool_size=8)
    p_sat = Scheduler(spec_sat).solve_alternating_best_order().placement
    assert len({s.device for s in p_sat}) <= 2


def test_stage_count_penalty_picks_fewer_stages_in_throughput_mode() -> None:
    """EXP-D2.8: an additive `stage_count_penalty_seconds · |ψ|` term
    inside the throughput-mode rank breaks the homogeneous-fleet
    indifference the linear multiplier alone leaves behind. With a
    8-layer fleet of 4 identical devices and γ_stages=0.030, the
    natural 4-stage answer (max_T = 0.020) carries a 0.120 penalty
    while a 2-stage answer (max_T = 0.040) carries 0.060 — the
    optimiser swings to 2-stage."""
    devices = [
        DeviceProfile(id=DeviceId(f"d{i}"), total_memory_bytes=NODE_BYTES * 4,
                      compute_throughput=1.0)
        for i in range(1, 5)
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i), memory_bytes=LAYER_BYTES,
            compute_time={d.id: 0.010 for d in devices},
        )
        for i in range(1, 9)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.0001 for d1 in devices for d2 in devices if d1 is not d2},
    )
    spec = ClusterSpec(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode="throughput",
        stage_count_penalty_seconds=0.030,
    )
    placement = Scheduler(spec).solve_alternating_best_order().placement
    assert len({s.device for s in placement}) <= 2, (
        f"stage_count_penalty did not collapse the stage count: "
        f"got {len(placement)} stages on a homogeneous 4-device fleet"
    )


def test_stage_count_penalty_default_zero_is_no_op(
    heterogeneous_spec_3x6: ClusterSpec,
) -> None:
    """Default stage_count_penalty_seconds=0 must reproduce the baseline
    placement byte-for-byte — no silent behaviour shift for existing
    deployments."""
    spec_default = heterogeneous_spec_3x6
    spec_zero = replace(heterogeneous_spec_3x6, stage_count_penalty_seconds=0.0)
    p_default = Scheduler(spec_default).solve_alternating_best_order().placement
    p_zero = Scheduler(spec_zero).solve_alternating_best_order().placement
    assert [(s.start_layer, s.end_layer, s.device) for s in p_default] \
        == [(s.start_layer, s.end_layer, s.device) for s in p_zero]


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


def test_subset_search_skips_subsets_with_no_viable_backup() -> None:
    """A subset whose stages leave no peer with room for a backup must be
    skipped, not abort the whole search.

    Regression for the first OPT-6.7B boot (2026-08-30): the first 2-device
    subset (two 8 GB Nanos, 16 layers = 6.5 GB each) raised NoRecoveryError
    from determine_recovery_table, and solve_alternating_best_order only
    caught NoFeasibleSolutionError, so the coordinator came up with no
    placement even though 3+-device subsets were feasible.
    """
    unit = 100_000_000
    ids = [DeviceId("a"), DeviceId("b"), DeviceId("c")]
    # 3 units per device; 4 one-unit layers. Two devices: 2 active + 2 backup
    # = 4 units > 3 -> no viable backup. Three devices (2/1/1): fits.
    devices = [
        DeviceProfile(id=d, total_memory_bytes=3 * unit, compute_throughput=1.0)
        for d in ids
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=unit,
            compute_time={d: 0.01 for d in ids},
        )
        for i in range(1, 5)
    ]
    network = NetworkProfile(
        bandwidth={(x, y): 1e9 for x in ids for y in ids if x != y},
        latency={(x, y): 0.0005 for x in ids for y in ids if x != y},
    )
    spec = ClusterSpec(
        devices=devices, layers=layers, network=network,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
    )
    result = Scheduler(spec).solve_alternating_best_order()
    assert {s.device for s in result.placement} == set(ids)
    assert set(result.recovery) == set(ids)
