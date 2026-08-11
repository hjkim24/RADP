"""Backup-host scope + alternating seed repair (EXP-D2.9b).

Two behaviours measured on the live snapshot and fixed here:

1. ``solve_alternating_best_order`` enumerates device *subsets*, and each
   candidate spec used to carry only its subset — so a node dropped from the
   pipeline for being slow was also dropped as a backup host, even with GBs
   free. ``ClusterSpec.backup_hosts`` decouples the two scopes.

2. ``solve_alternating`` seeds from a round-robin placement. Under tight
   memory that seed can have no feasible recovery table, and iteration 1
   raised with nothing recorded — reporting failure although feasible
   (Ψ, R) pairs existed. The seed is now repaired from the cost-only DP.
"""

from __future__ import annotations

import pytest

from radp.common.types import (
    SLO,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
    NoRecoveryError,
    Stage,
)
from radp.coordinator.recovery_table import determine_recovery_table
from radp.coordinator.scheduler import Scheduler

MB = 1024 * 1024


def _spec(devices, *, backup_hosts=None, n_layers=4, layer_mb=100):
    # Every candidate host needs a compute_time entry: the recovery greedy
    # scores peers by download + recompute, and a missing entry scores inf,
    # which silently removes the host from consideration.
    known = {d.id: 0.01 for d in list(devices) + list(backup_hosts or [])}
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i + 1),
            memory_bytes=layer_mb * MB,
            compute_time=dict(known),
        )
        for i in range(n_layers)
    ]
    ids = [d.id for d in devices] + [h.id for h in (backup_hosts or [])]
    net = NetworkProfile(
        bandwidth={(a, b): 1e9 for a in ids for b in ids if a != b},
        latency={(a, b): 0.001 for a in ids for b in ids if a != b},
    )
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=net,
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        backup_hosts=backup_hosts,
    )


def _dev(name, free_mb, throughput=1.0):
    return DeviceProfile(
        id=DeviceId(name),
        total_memory_bytes=8 * 1024 * MB,
        compute_throughput=throughput,
        free_memory_bytes=free_mb * MB,
    )


def test_backup_host_scope_defaults_to_pipeline_devices():
    """Without backup_hosts, only pipeline devices may hold a backup."""
    fast_a, fast_b = _dev("a", 250), _dev("b", 250)
    placement = [
        Stage(device=DeviceId("a"), start_layer=LayerIdx(1), end_layer=LayerIdx(2)),
        Stage(device=DeviceId("b"), start_layer=LayerIdx(3), end_layer=LayerIdx(4)),
    ]
    # Each stage is 200 MB; each peer has 250 MB free but 200 MB is its own
    # stage, leaving 50 MB — not enough to back the other up.
    with pytest.raises(NoRecoveryError):
        determine_recovery_table(_spec([fast_a, fast_b]), placement)


def test_backup_hosts_widens_the_pool_and_makes_recovery_feasible():
    """An idle node with free memory rescues the same placement."""
    fast_a, fast_b = _dev("a", 250), _dev("b", 250)
    idle = _dev("slow", 900, throughput=0.01)  # never picked for the pipeline
    placement = [
        Stage(device=DeviceId("a"), start_layer=LayerIdx(1), end_layer=LayerIdx(2)),
        Stage(device=DeviceId("b"), start_layer=LayerIdx(3), end_layer=LayerIdx(4)),
    ]
    spec = _spec([fast_a, fast_b], backup_hosts=[fast_a, fast_b, idle])
    table = determine_recovery_table(spec, placement)
    assert table[DeviceId("a")] == DeviceId("slow")
    assert table[DeviceId("b")] == DeviceId("slow")


def test_alternating_survives_a_seed_with_no_feasible_recovery_table():
    """An infeasible starting placement must not abort the whole solve.

    `solve_alternating` used to derive R from its seed on iteration 1 and
    raise NoRecoveryError with nothing recorded, reporting failure even when
    feasible (Ψ, R) pairs existed. It now repairs the seed from the cost-only
    DP first. Here the seed piles four layers on `a`, whose 400 MB no peer can
    hold, while a balanced split is comfortably feasible.
    """
    # Nine 100 MB layers. The seed piles seven of them (700 MB) on `a`; the
    # two peers hold 700 MB each but 100 MB of that is their own layer, so
    # neither can take the 700 MB backup. A balanced 3/3/3 split does fit.
    a, b, c = _dev("a", 1200), _dev("b", 700), _dev("c", 700)
    spec = _spec([a, b, c], n_layers=9)

    bad_seed = [
        Stage(device=DeviceId("a"), start_layer=LayerIdx(1), end_layer=LayerIdx(7)),
        Stage(device=DeviceId("b"), start_layer=LayerIdx(8), end_layer=LayerIdx(8)),
        Stage(device=DeviceId("c"), start_layer=LayerIdx(9), end_layer=LayerIdx(9)),
    ]
    with pytest.raises(NoRecoveryError):
        determine_recovery_table(spec, bad_seed)

    result = Scheduler(spec).solve_alternating(initial_placement=bad_seed)
    assert result.recovery, "solver returned an empty recovery table"
    assert len(result.placement) == 3
