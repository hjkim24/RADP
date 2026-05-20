"""Algorithmic-only sweeps (no live servers needed).

  1. Memory sensitivity (plan.md §6.5 scenario 3): for synthetic clusters,
     vary per-device memory; report feasibility of greedy / Jupiter-DP /
     ours, and the resulting max-stage-time.
  2. Heterogeneity effect (§6.5 scenario 4): vary CV of compute_throughput;
     report max-stage-time ratio greedy/ours.
  3. DP runtime: sweep L × |D|; confirm polynomial growth (O(L² × |D|)).

Writes one JSON per sweep into experiments/results/.
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

from experiments._harness import (
    dp_placement,
    dp_placement_no_recovery,
    greedy_placement,
    make_synthetic_spec,
    max_stage_time,
    round_robin_placement,
    write_json,
)
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import Placement, RecoveryTable
from radp.coordinator.recovery_table import determine_recovery_table

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 1) Memory sensitivity
# ---------------------------------------------------------------------------
def run_memory_sensitivity() -> dict[str, Any]:
    num_devices = 3
    num_layers = 12
    mem_per_layer = 200_000_000
    # Sweep total device memory from comfortable (×4 per stage) down to
    # barely fitting the primary stage.
    layers_per_stage = num_layers // num_devices  # 4
    primary_bytes = layers_per_stage * mem_per_layer  # 800 MB
    multipliers = [4.0, 3.0, 2.5, 2.0, 1.75, 1.5, 1.25, 1.1, 1.05, 1.0]
    rows = []
    for mult in multipliers:
        device_mem = int(primary_bytes * mult)
        spec = make_synthetic_spec(
            num_devices=num_devices,
            num_layers=num_layers,
            mem_per_device_bytes=device_mem,
            mem_per_layer_bytes=mem_per_layer,
        )
        greedy_plan: Placement = greedy_placement(spec.devices, num_layers)
        rr_plan = round_robin_placement(spec.devices, num_layers)
        try:
            R: RecoveryTable = determine_recovery_table(spec, rr_plan)
        except Exception:  # noqa: BLE001
            R = {}
        ours_plan = dp_placement(spec, R)
        jupiter_plan = dp_placement_no_recovery(spec)
        rows.append(
            {
                "mem_multiplier_of_primary": mult,
                "mem_per_device_bytes": device_mem,
                "ours_feasible": ours_plan is not None,
                "jupiter_feasible": jupiter_plan is not None,
                "greedy_max_stage_seconds": max_stage_time(spec, greedy_plan),
                "ours_max_stage_seconds": (
                    max_stage_time(spec, ours_plan) if ours_plan else None
                ),
                "jupiter_max_stage_seconds": (
                    max_stage_time(spec, jupiter_plan) if jupiter_plan else None
                ),
            }
        )
    return {
        "scenario": "memory_sensitivity",
        "num_devices": num_devices,
        "num_layers": num_layers,
        "mem_per_layer_bytes": mem_per_layer,
        "rows": rows,
        "note": "ours reserves backup memory; jupiter doesn't. Tight memory "
                "(mult ≤ 2.0) makes ours infeasible first, demonstrating the "
                "co-optimization constraint.",
    }


# ---------------------------------------------------------------------------
# 2) Heterogeneity
# ---------------------------------------------------------------------------
def run_heterogeneity() -> dict[str, Any]:
    num_devices = 3
    num_layers = 12
    # Throughput multiplier for the "fast" device; others stay at 1.0.
    multipliers = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
    rows = []
    for mult in multipliers:
        spec = make_synthetic_spec(
            num_devices=num_devices,
            num_layers=num_layers,
            throughput_per_device=[mult, 1.0, 1.0],
        )
        # R: every device backs up its neighbor.
        rr_plan = round_robin_placement(spec.devices, num_layers)
        R = determine_recovery_table(spec, rr_plan)
        greedy_plan = greedy_placement(spec.devices, num_layers)
        ours_plan = dp_placement(spec, R)
        if ours_plan is None:
            continue
        greedy_t = max_stage_time(spec, greedy_plan)
        ours_t = max_stage_time(spec, ours_plan)
        rows.append(
            {
                "throughput_multiplier_fast_device": mult,
                "greedy_max_stage_seconds": greedy_t,
                "ours_max_stage_seconds": ours_t,
                "ours_vs_greedy_speedup": greedy_t / ours_t if ours_t > 0 else None,
                "greedy_layer_counts": [
                    int(s.end_layer) - int(s.start_layer) + 1 for s in greedy_plan
                ],
                "ours_layer_counts": [
                    int(s.end_layer) - int(s.start_layer) + 1 for s in ours_plan
                ],
            }
        )
    return {
        "scenario": "heterogeneity",
        "num_devices": num_devices,
        "num_layers": num_layers,
        "rows": rows,
        "note": "As the fast device gets faster, ours assigns it more layers "
                "(load balanced by compute time), while greedy/round-robin do "
                "the simple proportional split.",
    }


# ---------------------------------------------------------------------------
# 3) DP runtime sweep
# ---------------------------------------------------------------------------
def run_dp_runtime(repeat: int = 5) -> dict[str, Any]:
    rows = []
    for num_layers in (12, 24, 32, 48, 64):
        for num_devices in (2, 3, 4, 5, 6):
            if num_layers < num_devices:
                continue
            # Generous memory so the DP never short-circuits on infeasibility —
            # we want to measure forward-DP runtime, not feasibility pruning.
            spec = make_synthetic_spec(
                num_devices=num_devices,
                num_layers=num_layers,
                mem_per_device_bytes=1_000_000_000_000,
            )
            timings = []
            for _ in range(repeat):
                t0 = time.perf_counter()
                _ = dp_placement(spec, recovery={})  # empty R = pure forward DP
                timings.append(time.perf_counter() - t0)
            rows.append(
                {
                    "num_layers": num_layers,
                    "num_devices": num_devices,
                    "L_squared_times_M": num_layers * num_layers * num_devices,
                    "runtime_seconds_median": statistics.median(timings),
                    "runtime_seconds_min": min(timings),
                }
            )
    return {
        "scenario": "dp_runtime",
        "repeat_per_cell": repeat,
        "rows": rows,
        "note": "Plan.md §3.5: DP forward is O(L² × |D|). Runtime should grow ~linearly with L²×M.",
    }


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument(
        "--scenarios",
        nargs="+",
        default=["memory", "hetero", "runtime"],
        choices=["memory", "hetero", "runtime"],
    )
    args = p.parse_args()
    if "memory" in args.scenarios:
        write_json("algo_memory", run_memory_sensitivity())
        log.info("wrote algo_memory")
    if "hetero" in args.scenarios:
        write_json("algo_hetero", run_heterogeneity())
        log.info("wrote algo_hetero")
    if "runtime" in args.scenarios:
        write_json("algo_runtime", run_dp_runtime())
        log.info("wrote algo_runtime")


if __name__ == "__main__":
    main()
