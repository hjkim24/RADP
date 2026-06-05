"""A3 baseline placement computation.

Reconstructs a ClusterSpec from a saved auto_schedule sidecar (the JSON
written to /tmp/radp_scheduler_stats.json by the coordinator) and computes
all four baseline placements on the SAME profile data:

  1. greedy     — throughput-weighted contiguous split (PETALS-style).
                  R = {}: this heuristic has no notion of recovery.
  2. uniform    — round-robin / equal layers per device. Ignores
                  heterogeneity. R = {}.
  3. jupiter_dp — same DP as ours but with R = {}, no backup memory
                  reservation. This is the closest competitor — measures
                  the marginal contribution of recovery-aware scheduling.
  4. ours       — full Recovery-Aware DP via solve_alternating(), which
                  jointly optimizes (Ψ, R) over the same profile.

Per user decision (2026-06-05): each baseline carries the R-table it
would have under its own design intent. greedy / uniform / jupiter_dp
all have R = {}, so on the live fleet a worker SIGKILL surfaces as a
NoRecoveryError mid-stream (stream dies — that IS the experimental data
point). Only `ours` recovers gracefully.

Used by experiments/run_a3_remote.py as the source of the live placement
to push to the coordinator in manual mode.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments._harness import (
    greedy_placement,
    max_stage_time,
    round_robin_placement,
)
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import (
    SLO,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
    NoFeasibleSolutionError,
    Placement,
    RecoveryTable,
)
from radp.coordinator.scheduler import Scheduler

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Sidecar → ClusterSpec
# ---------------------------------------------------------------------------
def _parse_pair_key(key: str) -> tuple[DeviceId, DeviceId]:
    """Parse the 'a->b' string key the sidecar uses for network edges."""
    src, dst = key.split("->", 1)
    return DeviceId(src), DeviceId(dst)


def cluster_spec_from_sidecar(
    sidecar: dict[str, Any],
    *,
    slo_ttft_seconds: float = 3.0,
    slo_tbt_seconds: float = 1.0,
    activation_bytes: int = 1_048_576,
) -> ClusterSpec:
    """Rebuild the in-memory ClusterSpec the scheduler operates on.

    The sidecar carries device_profiles, layer_profiles, network_profile —
    everything except the SLO/activation knobs (those live in the coord
    yaml). Defaults here match deploy/group_vars/all.yml on the live fleet.
    """
    devices = [
        DeviceProfile(
            id=DeviceId(d["id"]),
            total_memory_bytes=int(d["total_memory_bytes"]),
            compute_throughput=float(d["compute_throughput"]),
        )
        for d in sidecar["device_profiles"]
    ]

    layers = [
        LayerProfile(
            layer_idx=LayerIdx(int(lp["layer_idx"])),
            memory_bytes=int(lp["memory_bytes"]),
            compute_time={DeviceId(k): float(v) for k, v in lp["compute_time"].items()},
        )
        for lp in sidecar["layer_profiles"]
    ]

    np_in = sidecar["network_profile"]
    bandwidth = {
        _parse_pair_key(k): float(v) for k, v in np_in["bandwidth_bps"].items()
    }
    latency = {
        _parse_pair_key(k): float(v) for k, v in np_in["latency_seconds"].items()
    }
    network = NetworkProfile(bandwidth=bandwidth, latency=latency)

    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=network,
        slo=SLO(ttft_seconds=slo_ttft_seconds, tbt_seconds=slo_tbt_seconds),
        activation_bytes=activation_bytes,
    )


# ---------------------------------------------------------------------------
# Baseline computation
# ---------------------------------------------------------------------------
def _placement_to_dicts(placement: Placement) -> list[dict[str, Any]]:
    return [
        {"device": str(s.device), "start": int(s.start_layer), "end": int(s.end_layer)}
        for s in placement
    ]


def _recovery_to_dicts(recovery: RecoveryTable) -> dict[str, str]:
    return {str(j): str(k) for j, k in recovery.items()}


def _placement_layer_counts(placement: Placement) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in placement:
        counts[str(s.device)] = counts.get(str(s.device), 0) + (
            int(s.end_layer) - int(s.start_layer) + 1
        )
    return counts


def _feasibility(
    spec: ClusterSpec, placement: Placement, recovery: RecoveryTable
) -> dict[str, Any]:
    """Does the (placement, R) combo satisfy per-device memory limits?

    Splits into two checks:
      * primary_ok — every device fits its own assigned stage
      * with_backup_ok — every device fits its own stage PLUS any backup
                         burden it would carry under R
    A baseline with R={} has identical primary_ok and with_backup_ok.
    """
    devices_by_id = {d.id: d for d in spec.devices}
    placement_by_device = {s.device: s for s in placement}

    primary_violations: list[str] = []
    for stage in placement:
        used = sum(
            spec.layers[i - 1].memory_bytes
            for i in range(int(stage.start_layer), int(stage.end_layer) + 1)
        )
        cap = devices_by_id[stage.device].total_memory_bytes
        if used > cap:
            primary_violations.append(
                f"{stage.device}: stage uses {used} > cap {cap}"
            )

    # Backup burden per device (from R⁻¹).
    backup_burden: dict[DeviceId, int] = {d.id: 0 for d in spec.devices}
    for j, k in recovery.items():
        j_stage = placement_by_device.get(j)
        if j_stage is None:
            continue
        backup_burden[k] += sum(
            spec.layers[i - 1].memory_bytes
            for i in range(int(j_stage.start_layer), int(j_stage.end_layer) + 1)
        )

    backup_violations: list[str] = []
    for d in spec.devices:
        own = (
            sum(
                spec.layers[i - 1].memory_bytes
                for i in range(
                    int(placement_by_device[d.id].start_layer),
                    int(placement_by_device[d.id].end_layer) + 1,
                )
            )
            if d.id in placement_by_device
            else 0
        )
        total = own + backup_burden[d.id]
        if total > d.total_memory_bytes:
            backup_violations.append(
                f"{d.id}: own {own} + backup {backup_burden[d.id]} = "
                f"{total} > cap {d.total_memory_bytes}"
            )

    return {
        "primary_ok": not primary_violations,
        "with_backup_ok": not backup_violations,
        "primary_violations": primary_violations,
        "backup_violations": backup_violations,
    }


def _compute_predicted_metrics(
    spec: ClusterSpec, placement: Placement, recovery: RecoveryTable
) -> dict[str, Any]:
    """Predicted max_stage_time + diagnostics for a placement."""
    mst = max_stage_time(spec, placement)
    counts = _placement_layer_counts(placement)
    return {
        "max_stage_time_seconds": mst,
        "n_stages": len(placement),
        "layers_per_device": counts,
        "max_layers_on_one_device": max(counts.values()) if counts else 0,
        "feasibility": _feasibility(spec, placement, recovery),
    }


def compute_all_baselines(spec: ClusterSpec) -> dict[str, dict[str, Any]]:
    """Compute placement + R for all four baselines. None on infeasibility."""
    results: dict[str, dict[str, Any]] = {}
    num_layers = len(spec.layers)

    # --- 1. greedy ---
    pl = greedy_placement(spec.devices, num_layers)
    results["greedy"] = {
        "placement": _placement_to_dicts(pl),
        "recovery": {},
        **_compute_predicted_metrics(spec, pl, {}),
    }

    # --- 2. uniform ---
    pl = round_robin_placement(spec.devices, num_layers)
    results["uniform"] = {
        "placement": _placement_to_dicts(pl),
        "recovery": {},
        **_compute_predicted_metrics(spec, pl, {}),
    }

    # --- 3. jupiter_dp (same DP as ours but R={}) ---
    try:
        jupiter_result = Scheduler(spec).solve(recovery={})
        pl = jupiter_result.placement
        results["jupiter_dp"] = {
            "placement": _placement_to_dicts(pl),
            "recovery": {},
            "scheduler_max_stage": jupiter_result.max_stage_time,
            **_compute_predicted_metrics(spec, pl, {}),
        }
    except NoFeasibleSolutionError as e:
        results["jupiter_dp"] = {"infeasible": True, "reason": str(e)}

    # --- 4. ours (R-Ψ alternating, jointly optimizing R + Ψ) ---
    try:
        alt = Scheduler(spec).solve_alternating(max_iterations=10)
        pl = alt.placement
        rec = alt.recovery
        results["ours"] = {
            "placement": _placement_to_dicts(pl),
            "recovery": _recovery_to_dicts(rec),
            "scheduler_max_stage": alt.max_stage_time,
            "alternating_iterations": alt.iterations,
            "alternating_converged": alt.converged,
            **_compute_predicted_metrics(spec, pl, rec),
        }
    except NoFeasibleSolutionError as e:
        results["ours"] = {"infeasible": True, "reason": str(e)}

    return results


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------
def print_comparison(baselines: dict[str, dict[str, Any]]) -> None:
    log.info("=" * 78)
    log.info("%-12s | %10s | %4s | %s | %s",
             "baseline", "max_stage", "stg", "primary", "w/ backup")
    log.info("-" * 78)
    for name, b in baselines.items():
        if b.get("infeasible"):
            log.info("%-12s | INFEASIBLE: %s", name, b["reason"])
            continue
        feas = b["feasibility"]
        log.info(
            "%-12s | %8.1f ms | %4d | %-7s | %s",
            name,
            b["max_stage_time_seconds"] * 1000,
            b["n_stages"],
            "ok" if feas["primary_ok"] else "FAIL",
            "ok" if feas["with_backup_ok"] else "FAIL",
        )
    log.info("=" * 78)
    # Relative comparison vs ours.
    if "ours" in baselines and "max_stage_time_seconds" in baselines["ours"]:
        ours_mst = baselines["ours"]["max_stage_time_seconds"]
        log.info("Relative max_stage_time (vs ours):")
        for name, b in baselines.items():
            if name == "ours" or "max_stage_time_seconds" not in b:
                continue
            ratio = b["max_stage_time_seconds"] / ours_mst
            sign = "+" if ratio > 1 else ""
            log.info("  %-12s : %s%.1f%% (%.2fx)",
                     name, sign, (ratio - 1) * 100, ratio)
    log.info("=" * 78)


def print_placement_detail(baselines: dict[str, dict[str, Any]]) -> None:
    for name, b in baselines.items():
        if b.get("infeasible"):
            continue
        log.info("--- %s ---", name)
        for s in b["placement"]:
            log.info("  %s [%d..%d]", s["device"], s["start"], s["end"])
        if b["recovery"]:
            log.info("  R: %s", b["recovery"])
        else:
            log.info("  R: {} (no recovery defined)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--sidecar", default="experiments/results/auto_baseline_first.json",
                   help="path to a previous run's JSON with embedded sidecar "
                        "(top-level 'scheduler' field)")
    p.add_argument("--slo-ttft", type=float, default=3.0)
    p.add_argument("--slo-tbt", type=float, default=1.0)
    p.add_argument("--activation-bytes", type=int, default=1_048_576)
    p.add_argument("--out", default="a3_baselines",
                   help="output JSON name under experiments/results/")
    p.add_argument("--detail", action="store_true",
                   help="also print per-baseline placement layer-by-layer")
    args = p.parse_args()

    sidecar_path = Path(args.sidecar)
    payload = json.loads(sidecar_path.read_text())
    sidecar = payload.get("scheduler") or payload  # accept either shape
    if "device_profiles" not in sidecar:
        raise SystemExit(
            f"file {sidecar_path} does not look like a coord sidecar "
            "(missing device_profiles)"
        )

    log.info("loaded sidecar: model=%s, %d devices, %d layers",
             sidecar.get("model_id"),
             len(sidecar["device_profiles"]),
             len(sidecar["layer_profiles"]))

    spec = cluster_spec_from_sidecar(
        sidecar,
        slo_ttft_seconds=args.slo_ttft,
        slo_tbt_seconds=args.slo_tbt,
        activation_bytes=args.activation_bytes,
    )
    baselines = compute_all_baselines(spec)
    print_comparison(baselines)
    if args.detail:
        print_placement_detail(baselines)

    out_path = Path("experiments/results") / f"{args.out}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "source_sidecar": str(sidecar_path),
        "slo": {"ttft_seconds": args.slo_ttft, "tbt_seconds": args.slo_tbt},
        "activation_bytes": args.activation_bytes,
        "baselines": baselines,
    }, indent=2))
    log.info("wrote %s", out_path)


if __name__ == "__main__":
    main()
