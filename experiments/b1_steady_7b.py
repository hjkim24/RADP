"""B1 protection-cost N=3 at 7B — steady-state throughput of off / single /
double parity / replication, order-rotated across 3 rounds (the 0830 350M
protocol, scripted so the 7B run survives unattended).

Per cell: worker KV-ship drop-in + coordinator mode/k drop-ins, coordinator
restart (~10 min at 7B), one discarded primer request, then N requests whose
per-step latencies land in the cell JSON. Aggregate mean/sample-std per mode
across rounds goes to ``b1_steady_7b_n3.json`` alongside per-round deltas vs
the same round's protection-off cell.

Run from the repo root:
    nohup .venv/bin/python experiments/b1_steady_7b.py < /dev/null >> LOG 2>&1 &
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import statistics
import time
from typing import Any

import grpc

from experiments._harness import RESULTS_DIR
from experiments.b1_ft_fleet import (
    _DEFAULT_COORD,
    _DEFAULT_COORD_HOST,
    _DEFAULT_COORD_SSH,
    _DEFAULT_SSH_KEY,
    fetch_placement,
    restart_coordinator_and_wait,
    set_parity_k,
    set_recovery_mode,
    set_worker_parity,
)
from experiments.run_e2e_remote import _GRPC_OPTIONS, _bench_one_request, _percentile
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.proto import radp_pb2_grpc

log = get_logger("b1_steady_7b")

# mode -> (worker KV-ship on, coordinator recovery mode, parity k)
CELLS: dict[str, tuple[bool, str, int]] = {
    "protection_off": (False, "surgical", 1),
    "single_parity": (True, "parity", 1),
    "double_parity": (True, "parity", 2),
    "replication": (True, "replicate", 1),
}
# Rotated per round so warm-up / drift cannot systematically favor one mode.
ROUND_ORDERS = [
    ["replication", "double_parity", "single_parity", "protection_off"],
    ["protection_off", "single_parity", "double_parity", "replication"],
    ["double_parity", "protection_off", "replication", "single_parity"],
]


def run_cell(coord: str, prompt: str, requests: int, max_tokens: int) -> dict[str, Any]:
    ch = grpc.insecure_channel(coord, options=_GRPC_OPTIONS)
    stub = radp_pb2_grpc.CoordinatorServiceStub(ch)
    _bench_one_request(stub, prompt, max_tokens)  # primer, discarded
    per_request = [_bench_one_request(stub, prompt, max_tokens)
                   for _ in range(requests)]
    ch.close()
    tbt = [x for r in per_request for x in r["tbt_seconds_each"]]
    return {
        "per_request": per_request,
        "tbt_seconds": {"p50": _percentile(tbt, 0.5), "p95": _percentile(tbt, 0.95),
                        "n": len(tbt)},
        "ttft_seconds": {"p50": _percentile([r["ttft_seconds"] for r in per_request], 0.5)},
        "throughput_tokens_per_sec": statistics.mean(
            r["throughput_tokens_per_sec"] for r in per_request),
        "decoded_texts_identical": len({r["decoded_text"] for r in per_request}) == 1,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coord", default=_DEFAULT_COORD)
    p.add_argument("--coord-host", default=_DEFAULT_COORD_HOST)
    p.add_argument("--coord-ssh", default=_DEFAULT_COORD_SSH)
    p.add_argument("--ssh-key", default=_DEFAULT_SSH_KEY)
    p.add_argument("--requests", type=int, default=10)
    p.add_argument("--max-tokens", type=int, default=20)
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--rounds", type=int, default=3)
    args = p.parse_args()
    configure_logging()
    date = f"{_dt.date.today():%Y%m%d}"

    rounds: list[dict[str, Any]] = []
    current_ship: bool | None = None
    for rnd in range(1, args.rounds + 1):
        order = ROUND_ORDERS[(rnd - 1) % len(ROUND_ORDERS)]
        row: dict[str, Any] = {"round": rnd, "order": order, "cells": {}}
        for mode in order:
            ship, rec_mode, k = CELLS[mode]
            if ship != current_ship:
                set_worker_parity(ship)
                current_ship = ship
            set_recovery_mode(args.coord_host, rec_mode)
            set_parity_k(args.coord_host, k)
            restart_coordinator_and_wait(args.coord_host, args.coord_ssh, args.ssh_key)
            # _coord_web wants the coordinator's address, not the ansible alias
            placement = fetch_placement(args.coord)
            t0 = time.time()
            cell = run_cell(args.coord, args.prompt, args.requests, args.max_tokens)
            cell["placement"] = placement
            cell["wall_seconds"] = time.time() - t0
            row["cells"][mode] = cell
            out = RESULTS_DIR / f"b1_steady_7b_r{rnd}_{mode}_{date}.json"
            out.write_text(json.dumps(cell, indent=2))
            log.info("[r%d %-14s] tput=%.3f tok/s  tbt p50=%.1f ms  identical=%s",
                     rnd, mode, cell["throughput_tokens_per_sec"],
                     cell["tbt_seconds"]["p50"] * 1e3, cell["decoded_texts_identical"])
        rounds.append(row)

    aggregate: dict[str, Any] = {}
    for mode in CELLS:
        tputs = [r["cells"][mode]["throughput_tokens_per_sec"] for r in rounds]
        p50s = [r["cells"][mode]["tbt_seconds"]["p50"] * 1e3 for r in rounds]
        d_tput = [(r["cells"][mode]["throughput_tokens_per_sec"]
                   / r["cells"]["protection_off"]["throughput_tokens_per_sec"] - 1) * 100
                  for r in rounds]
        aggregate[mode] = {
            "throughput_mean": statistics.mean(tputs),
            "throughput_std": statistics.stdev(tputs) if len(tputs) > 1 else 0.0,
            "tbt_p50_ms_mean": statistics.mean(p50s),
            "tbt_p50_ms_std": statistics.stdev(p50s) if len(p50s) > 1 else 0.0,
            "delta_tput_vs_off_pct_mean": statistics.mean(d_tput),
            "delta_tput_vs_off_pct_std": statistics.stdev(d_tput) if len(d_tput) > 1 else 0.0,
        }
        log.info("[agg] %-14s tput=%.3f±%.3f tok/s  Δ=%+.2f±%.2f%%  tbt p50=%.1f±%.1f ms",
                 mode, aggregate[mode]["throughput_mean"], aggregate[mode]["throughput_std"],
                 aggregate[mode]["delta_tput_vs_off_pct_mean"],
                 aggregate[mode]["delta_tput_vs_off_pct_std"],
                 aggregate[mode]["tbt_p50_ms_mean"], aggregate[mode]["tbt_p50_ms_std"])

    out = RESULTS_DIR / "b1_steady_7b_n3.json"
    out.write_text(json.dumps({
        "experiment": "b1_steady_7b_n3", "date": date,
        "config": {"coord": args.coord, "requests": args.requests,
                   "max_tokens": args.max_tokens, "prompt": args.prompt},
        "rounds": rounds, "aggregate": aggregate,
    }, indent=2))
    log.info("wrote %s", out)

    # Restore the fleet's standing config (the 0830 protocol's restore step).
    set_worker_parity(False)
    current_ship = False
    set_recovery_mode(args.coord_host, "surgical")
    set_parity_k(args.coord_host, 1)
    restart_coordinator_and_wait(args.coord_host, args.coord_ssh, args.ssh_key)
    log.info("fleet restored: worker KV-ship off, surgical, k=1")


if __name__ == "__main__":
    main()
