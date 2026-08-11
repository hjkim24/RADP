"""EXP-D2.9 — does the decoupled procedure actually produce an infeasible placement?

D2.8 established (measured) that a cost-only DP picks a 2-stage placement while
the recovery-enabled coordinator deploys 4 stages. It then *asserted* — in a
print statement, never executed — that the 2-stage answer is infeasible because
no peer could hold the big stage's backup. That assertion is what the paper's
"ψ and R have coupled feasibility" claim rests on, so it needs to be run rather
than argued.

This script runs it: take the cost-only placement, hand it to the production
recovery-table solver under production memory accounting, and see whether
`determine_recovery_table` raises NoRecoveryError.

Two accountings are reported, because D2.8's own spec quietly used the
optimistic one:
  - realistic: free_memory_bytes as reported by heartbeats, eager_backup=True
    (what the live coordinator uses)
  - optimistic: free := total, eager_backup=False (what d28_cost_model_sweep.py
    passed to build_spec)

Whatever it says is the answer. A feasible result falsifies the coupling claim
at this model size and must be reported as such.
"""

from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import replace
from itertools import combinations, permutations
from pathlib import Path

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
from radp.coordinator.scheduler import Scheduler, _rank

COORD_URL = "http://115.145.158.253:8080/api/cluster"
SNAPSHOT_PATH = Path("/tmp/radp_cluster_snapshot_d29.json")
MB = 1024 * 1024


def fetch_snapshot() -> dict:
    if SNAPSHOT_PATH.exists():
        return json.loads(SNAPSHOT_PATH.read_text())
    with urllib.request.urlopen(COORD_URL, timeout=10) as r:
        data = r.read()
    SNAPSHOT_PATH.write_bytes(data)
    return json.loads(data)


def build_spec(snapshot: dict, *, realistic: bool, mode: str, C: int, gamma: float) -> ClusterSpec:
    devices = [
        DeviceProfile(
            id=DeviceId(p["id"]),
            total_memory_bytes=p["total_memory_bytes"],
            compute_throughput=p["compute_throughput"],
            free_memory_bytes=(
                p.get("free_memory_bytes") or p["total_memory_bytes"]
                if realistic
                else p["total_memory_bytes"]
            ),
        )
        for p in snapshot["device_profiles"]
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(lp["layer_idx"]),
            memory_bytes=lp["memory_bytes"],
            compute_time={DeviceId(k): v for k, v in lp["compute_time"].items()},
        )
        for lp in snapshot["layer_profiles"]
    ]
    net = snapshot["network_profile"]
    bandwidth: dict[tuple[DeviceId, DeviceId], float] = {}
    latency: dict[tuple[DeviceId, DeviceId], float] = {}
    for k, v in net["bandwidth_bps"].items():
        s, d = k.split("->")
        bandwidth[(DeviceId(s), DeviceId(d))] = v
    for k, v in net["latency_seconds"].items():
        s, d = k.split("->")
        latency[(DeviceId(s), DeviceId(d))] = v
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=NetworkProfile(bandwidth=bandwidth, latency=latency),
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode=mode,
        eager_backup=realistic,
        hop_overhead_seconds=0.008,
        target_concurrency=C,
        thread_pool_size=30,
        stage_count_penalty_seconds=gamma,
    )


def cost_only_placement(base_spec: ClusterSpec):
    """d28's search: best ordered subset under the inner DP with recovery={}."""
    best_rank, best_placement = math.inf, None
    for k in range(2, len(base_spec.devices) + 1):
        for subset in combinations(base_spec.devices, k):
            for perm in permutations(subset):
                spec = replace(base_spec, devices=list(perm))
                try:
                    res = Scheduler(spec).solve(recovery={})
                except Exception:  # noqa: BLE001
                    continue
                rank = _rank(
                    (res.sum_stage_time, res.max_stage_time),
                    base_spec.optimization_mode,
                    base_spec.blend_alpha,
                ) + base_spec.stage_count_penalty_seconds * len(perm)
                if rank < best_rank - 1e-9:
                    best_rank, best_placement = rank, res.placement
    if best_placement is None:
        raise RuntimeError("no feasible cost-only placement")
    return best_placement


def fmt(placement) -> str:
    return " → ".join(f"{s.device}[{int(s.start_layer)}..{int(s.end_layer)}]" for s in placement)


def try_recovery(spec: ClusterSpec, placement, label: str) -> bool:
    """Run the production recovery solver on `placement`. Return True if feasible."""
    try:
        table = determine_recovery_table(spec, placement)
    except NoRecoveryError as e:
        print(f"    {label}: INFEASIBLE — NoRecoveryError: {e}")
        return False
    print(f"    {label}: feasible — R = {dict(table)}")
    return True


def main() -> None:
    snap = fetch_snapshot()
    layer_mb = snap["layer_profiles"][0]["memory_bytes"] / MB
    print(f"model {snap['model_id']}  L={len(snap['layer_profiles'])}  "
          f"per-layer {layer_mb:.1f} MB")
    print("devices (total / free as reported):")
    for d in snap["device_profiles"]:
        print(f"  {d['id']:<6} total={d['total_memory_bytes']/2**30:5.1f}G "
              f"free={(d.get('free_memory_bytes') or 0)/2**30:5.1f}G "
              f"t={d['compute_throughput']:.3f}")

    prod = [
        Stage(device=DeviceId(s["device"]),
              start_layer=LayerIdx(s["start"]),
              end_layer=LayerIdx(s["end"]))
        for s in snap["placement"]
    ]
    print(f"\nproduction placement (recovery-enabled): {fmt(prod)}")
    print(f"production recovery table (deployed):    {snap['recovery']}")

    grid = [("throughput", 16, 0.0), ("throughput", 1, 0.0), ("latency", 1, 0.0)]
    for realistic in (True, False):
        acct = ("realistic (heartbeat free, eager_backup=True)" if realistic
                else "optimistic (free:=total, eager_backup=False) — d28's setting")
        print(f"\n=== memory accounting: {acct} ===")
        for mode, C, gamma in grid:
            spec = build_spec(snap, realistic=realistic, mode=mode, C=C, gamma=gamma)
            try:
                psi_cost = cost_only_placement(spec)
            except Exception as e:  # noqa: BLE001
                print(f"  {mode}/C={C}: cost-only search failed: {e}")
                continue
            print(f"  {mode}/C={C}  cost-only ψ ({len(psi_cost)} stages): {fmt(psi_cost)}")
            try_recovery(spec, psi_cost, "recovery on cost-only ψ")
            try_recovery(spec, prod, "recovery on production ψ ")

    # Headroom arithmetic — the quantity the D2.8 print statement asserted about.
    print("\n=== headroom check (the claim D2.8 asserted but never ran) ===")
    biggest = max(prod, key=lambda s: s.end_layer - s.start_layer + 1)
    n = int(biggest.end_layer - biggest.start_layer + 1)
    print(f"  largest production stage: {biggest.device} holds {n} layers "
          f"= {n * layer_mb:.0f} MB of weights")
    print("  smallest reported free memory across peers: "
          f"{min((d.get('free_memory_bytes') or 0) for d in snap['device_profiles'])/2**30:.1f} GB")
    print("  a 23-layer stage's backup is "
          f"{23 * layer_mb:.0f} MB — compare against the free column above.")


if __name__ == "__main__":
    main()
