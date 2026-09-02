"""EXP-D2.9b — at what memory headroom do ψ and R actually couple?

D2.9a showed that on this fleet at OPT-350M the decoupled procedure
(cost-only placement, then assign backups) produces a placement whose
recovery table solves fine: a 23-layer stage is 576 MB against ~5 GB of peer
headroom. So the coupling the paper claims is real only in a regime this
hardware/model pair does not reach.

This script locates that regime by sweeping a cap on per-device free memory
and, at each cap, running both procedures end to end:

  decoupled : psi = argmin cost with recovery={}  ->  determine_recovery_table(psi)
  joint     : solve_alternating() (production path, backup burden in the DP)

Three outcomes are possible at a given cap, and the middle one is the claim:
  both feasible          -> no coupling; either procedure works
  decoupled INFEASIBLE,
      joint feasible     -> COUPLING: solving them separately loses a solution
  both infeasible        -> below this cap the model does not fit at all

The pipeline search enumerates ordered subsets of the CUDA-capable devices
(the ones the solver ever picks). The backup-host SCOPE is swept explicitly and
applied to BOTH procedures — the 2026-08-30 run showed that giving only one of
them the wider scope manufactures a bogus "joint failed but decoupled worked":
  pipeline : R may use only pipeline devices (ClusterSpec.backup_hosts=None —
             the production coordinator's behaviour, see commit ade8356)
  fleet    : every device in the fleet is a candidate backup host

Offline and deterministic — reads the cluster snapshot, touches no worker.
Writes experiments/results/d29_coupling_threshold_<date>.json.
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
    NoFeasibleSolutionError,
    NoRecoveryError,
)
from radp.coordinator.recovery_table import determine_recovery_table
from radp.coordinator.scheduler import Scheduler, _rank

COORD_URL = "http://115.145.158.253:8080/api/cluster"
SNAPSHOT_PATH = Path("/tmp/radp_cluster_snapshot_d29.json")
GB = 1024 ** 3
MB = 1024 ** 2

# Devices the solver ever picks (the CPU-forced Nanos have t=0.011 and are
# never chosen for the pipeline, but they remain valid backup hosts).
PIPELINE_POOL = {"on-1", "on-2", "on-6", "ao-1", "ao-2"}


def fetch_snapshot() -> dict:
    if SNAPSHOT_PATH.exists():
        return json.loads(SNAPSHOT_PATH.read_text())
    with urllib.request.urlopen(COORD_URL, timeout=10) as r:
        data = r.read()
    SNAPSHOT_PATH.write_bytes(data)
    return json.loads(data)


def build_spec(snapshot: dict, cap_bytes: int | None) -> ClusterSpec:
    """Full-fleet spec. `cap_bytes` caps every device's reported free memory."""
    devices = []
    for p in snapshot["device_profiles"]:
        free = p.get("free_memory_bytes") or p["total_memory_bytes"]
        if cap_bytes is not None:
            free = min(free, cap_bytes)
        devices.append(
            DeviceProfile(
                id=DeviceId(p["id"]),
                total_memory_bytes=p["total_memory_bytes"],
                compute_throughput=p["compute_throughput"],
                free_memory_bytes=free,
            )
        )
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(lp["layer_idx"]),
            memory_bytes=lp["memory_bytes"],
            compute_time={DeviceId(k): v for k, v in lp["compute_time"].items()},
        )
        for lp in snapshot["layer_profiles"]
    ]
    net = snapshot["network_profile"]
    bw: dict[tuple[DeviceId, DeviceId], float] = {}
    lat: dict[tuple[DeviceId, DeviceId], float] = {}
    for k, v in net["bandwidth_bps"].items():
        s, d = k.split("->")
        bw[(DeviceId(s), DeviceId(d))] = v
    for k, v in net["latency_seconds"].items():
        s, d = k.split("->")
        lat[(DeviceId(s), DeviceId(d))] = v
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=NetworkProfile(bandwidth=bw, latency=lat),
        slo=SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        optimization_mode="throughput",
        eager_backup=True,
        hop_overhead_seconds=0.008,
        target_concurrency=16,
        thread_pool_size=30,
        stage_count_penalty_seconds=0.0,
    )


def _pipeline_devices(spec: ClusterSpec) -> list[DeviceProfile]:
    return [d for d in spec.devices if str(d.id) in PIPELINE_POOL]


def _scoped(spec: ClusterSpec, perm, scope: str) -> ClusterSpec:
    """Pipeline = `perm`; backup hosts = `perm` (pipeline) or the whole fleet."""
    hosts = list(spec.devices) if scope == "fleet" else list(perm)
    return replace(spec, devices=list(perm), backup_hosts=hosts)


def decoupled(spec: ClusterSpec, scope: str):
    """Cost-only placement search (recovery={}), then assign backups to it."""
    pool = _pipeline_devices(spec)
    best_rank, best_psi, best_perm = math.inf, None, None
    for k in range(2, len(pool) + 1):
        for subset in combinations(pool, k):
            for perm in permutations(subset):
                try:
                    res = Scheduler(replace(spec, devices=list(perm))).solve(recovery={})
                except Exception:  # noqa: BLE001
                    continue
                rank = _rank(
                    (res.sum_stage_time, res.max_stage_time),
                    spec.optimization_mode,
                    spec.blend_alpha,
                )
                if rank < best_rank - 1e-9:
                    best_rank, best_psi, best_perm = rank, res.placement, perm
    if best_psi is None:
        return None, None, "no placement"
    try:
        r = determine_recovery_table(_scoped(spec, best_perm, scope), best_psi)
    except NoRecoveryError as e:
        return best_psi, None, f"NoRecoveryError: {e}"
    return best_psi, r, None


def joint(spec: ClusterSpec, scope: str):
    """Production path: alternating DP with the backup burden inside feasibility."""
    pool = _pipeline_devices(spec)
    best_rank, best = math.inf, None
    for k in range(2, len(pool) + 1):
        for subset in combinations(pool, k):
            for perm in permutations(subset):
                try:
                    res = Scheduler(_scoped(spec, perm, scope)).solve_alternating()
                except (NoFeasibleSolutionError, NoRecoveryError):
                    continue
                except Exception:  # noqa: BLE001
                    continue
                rank = _rank(
                    (res.sum_stage_time, res.max_stage_time),
                    spec.optimization_mode,
                    spec.blend_alpha,
                )
                if rank < best_rank - 1e-9:
                    best_rank, best = rank, res
    if best is None:
        return None, None, "no feasible joint solution"
    return best.placement, best.recovery, None


def fmt(psi) -> str:
    if psi is None:
        return "-"
    return " → ".join(f"{s.device}[{int(s.start_layer)}..{int(s.end_layer)}]" for s in psi)


def main() -> None:
    import datetime as _dt
    snap = fetch_snapshot()
    layer_b = snap["layer_profiles"][0]["memory_bytes"]
    L = len(snap["layer_profiles"])
    print(f"model {snap['model_id']}  L={L}  per-layer {layer_b/MB:.1f} MB  "
          f"whole model {L*layer_b/MB:.0f} MB")
    print("uncapped free: " + "  ".join(
        f"{d['id']}={(d.get('free_memory_bytes') or 0)/GB:.2f}G"
        for d in snap["device_profiles"]))

    # 6000..2200 band added for the 7B-class model (whole model ~12.7 GB —
    # per-device caps below ~2 GB cannot fit it even backup-free); the
    # 2000..200 tail is the 350M-era grid, kept so the same script still
    # reproduces the original sweep.
    caps_mb = [6000, 5500, 5000, 4500, 4000, 3500, 3000, 2800, 2600, 2400,
               2200, 2000, 1500, 1200, 1000, 900, 800, 700, 650, 600,
               550, 500, 450, 400, 350, 300, 250, 200]
    rows = []
    for scope in ("pipeline", "fleet"):
        print(f"\n=== backup-host scope: {scope} ===")
        print(f"{'cap':>7}  {'decoupled':>10}  {'joint':>10}   verdict")
        print("-" * 100)
        coupling_band = []
        for cap_mb in caps_mb:
            spec = build_spec(snap, cap_mb * MB)
            psi_d, r_d, err_d = decoupled(spec, scope)
            psi_j, r_j, err_j = joint(spec, scope)
            d_ok, j_ok = err_d is None, err_j is None
            if d_ok and j_ok:
                verdict = "both feasible"
            elif not d_ok and j_ok:
                verdict = "COUPLING: decoupled loses a solution the joint solver finds"
                coupling_band.append(cap_mb)
            elif not d_ok and not j_ok:
                verdict = "model does not fit"
            else:
                verdict = "joint failed but decoupled worked (unexpected)"
            print(f"{cap_mb:>6}M  {'ok' if d_ok else 'FAIL':>10}  {'ok' if j_ok else 'FAIL':>10}   {verdict}")
            if not d_ok:
                print(f"          decoupled ψ: {fmt(psi_d)}")
                print(f"          reason     : {err_d}")
            if j_ok:
                print(f"          joint ψ    : {fmt(psi_j)}   R={dict(r_j) if r_j else '-'}")
            rows.append({
                "scope": scope, "cap_mb": cap_mb,
                "decoupled_ok": d_ok, "joint_ok": j_ok, "verdict": verdict,
                "decoupled_psi": fmt(psi_d), "decoupled_R": dict(r_d) if r_d else None,
                "decoupled_error": err_d,
                "joint_psi": fmt(psi_j), "joint_R": dict(r_j) if r_j else None,
                "joint_error": err_j,
            })
        if coupling_band:
            print(f"COUPLING BAND ({scope}): free-memory cap {min(coupling_band)}–{max(coupling_band)} MB "
                  f"per device (whole model {L*layer_b/MB:.0f} MB).")
        else:
            print(f"NO COUPLING BAND ({scope}) across the swept caps.")

    out = Path(__file__).parent / "results" / (
        f"d29_coupling_threshold_{_dt.date.today():%Y%m%d}.json")
    out.write_text(json.dumps({
        "experiment": "d29_coupling_threshold",
        "model_id": snap["model_id"], "num_layers": L, "per_layer_bytes": layer_b,
        "uncapped_free_bytes": {d["id"]: d.get("free_memory_bytes") for d in snap["device_profiles"]},
        "pipeline_pool": sorted(PIPELINE_POOL),
        "caps_mb": caps_mb, "rows": rows,
    }, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
