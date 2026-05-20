"""Aggregate benchmark JSONs into a human-readable Markdown report.

Reads all known result files from experiments/results/ and prints (or writes
to a file) a single report with one section per scenario. Missing files are
quietly skipped, so you can run any subset of benchmarks first.
"""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

from experiments._harness import RESULTS_DIR


def _read(name: str) -> dict | None:
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _fmt_float(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, float) and (x != x):  # NaN
        return "nan"
    return f"{x:.{digits}f}"


def _section_normal(buf: StringIO) -> None:
    data = _read("normal")
    if data is None:
        return
    buf.write("## Scenario 1 — Normal operation (live)\n\n")
    buf.write(f"- Model: `{data['model_id']}`\n")
    buf.write(
        f"- Placement: {data['placement_devices']} on stages {data['stages_layers']}\n"
    )
    buf.write(f"- Requests: {data['n_requests']} × {data['max_tokens']} tokens\n\n")
    buf.write("| metric | value |\n|---|---|\n")
    buf.write(f"| TTFT mean | {_fmt_float(data['ttft_seconds_mean'])}s |\n")
    buf.write(f"| TTFT p50  | {_fmt_float(data['ttft_seconds_p50'])}s |\n")
    buf.write(f"| TBT p50   | {_fmt_float(data['tbt_seconds_p50'])}s |\n")
    buf.write(
        f"| Throughput | {_fmt_float(data['throughput_tokens_per_sec_mean'], 1)} tokens/s |\n\n"
    )


def _section_failure(buf: StringIO) -> None:
    data = _read("failure")
    if data is None:
        return
    buf.write("## Scenario 2 — Single-node failure recovery (live)\n\n")
    buf.write(
        f"- Prompt: `{data['prompt']}` | max_tokens={data['max_tokens']} | "
        f"kill_after_tokens={data['kill_after_tokens']}\n\n"
    )

    a = data["mid_decode_replay"]
    buf.write("### A) Mid-decode cache replay (per-step)\n\n")
    buf.write("| metric | value |\n|---|---|\n")
    buf.write(f"| tokens completed | {a['tokens_completed']} / {a['max_tokens_requested']} |\n")
    buf.write(f"| steady-state TBT p50 | {_fmt_float(a['steady_tbt_p50_seconds'])}s |\n")
    buf.write(f"| recovery decode step  | {_fmt_float(a['recovery_step_seconds'])}s |\n")
    buf.write(
        f"| extra cost attributable to failure | "
        f"{_fmt_float(a['extra_seconds_attributable_to_failure'])}s |\n\n"
    )

    b = data["e2e_wall_clock"]
    buf.write("### B) End-to-end wall clock comparison\n\n")
    buf.write(f"- All three runs produced identical tokens: **{b['sequences_all_match']}**\n\n")
    buf.write("| run | seconds |\n|---|---:|\n")
    buf.write(f"| baseline (no failure)   | {_fmt_float(b['baseline_seconds'])} |\n")
    buf.write(f"| cache-replay recovery   | {_fmt_float(b['cache_replay_seconds'])} |\n")
    buf.write(f"| re-prefill recovery     | {_fmt_float(b['re_prefill_seconds'])} |\n\n")


def _section_algo_memory(buf: StringIO) -> None:
    data = _read("algo_memory")
    if data is None:
        return
    buf.write("## Scenario 3 — Memory sensitivity (algorithmic)\n\n")
    buf.write(
        f"- L={data['num_layers']}, |D|={data['num_devices']}, "
        f"mem/layer={data['mem_per_layer_bytes']:_}\n\n"
    )
    buf.write("| mem×(primary) | ours feasible | jupiter feasible "
              "| greedy_max(s) | ours_max(s) | jupiter_max(s) |\n")
    buf.write("|---:|:---:|:---:|---:|---:|---:|\n")
    for r in data["rows"]:
        buf.write(
            f"| {r['mem_multiplier_of_primary']} "
            f"| {'✓' if r['ours_feasible'] else '✗'} "
            f"| {'✓' if r['jupiter_feasible'] else '✗'} "
            f"| {_fmt_float(r['greedy_max_stage_seconds'])} "
            f"| {_fmt_float(r['ours_max_stage_seconds'])} "
            f"| {_fmt_float(r['jupiter_max_stage_seconds'])} |\n"
        )
    buf.write(f"\n> {data['note']}\n\n")


def _section_algo_hetero(buf: StringIO) -> None:
    data = _read("algo_hetero")
    if data is None:
        return
    buf.write("## Scenario 4 — Heterogeneity (algorithmic)\n\n")
    buf.write(
        f"- L={data['num_layers']}, |D|={data['num_devices']}, "
        "fast-device throughput multiplier varied; others=1.0\n\n"
    )
    buf.write("| fast×T | greedy_max(s) | ours_max(s) | ours/greedy speedup "
              "| greedy layers | ours layers |\n")
    buf.write("|---:|---:|---:|---:|:---:|:---:|\n")
    for r in data["rows"]:
        buf.write(
            f"| {r['throughput_multiplier_fast_device']} "
            f"| {_fmt_float(r['greedy_max_stage_seconds'])} "
            f"| {_fmt_float(r['ours_max_stage_seconds'])} "
            f"| {_fmt_float(r['ours_vs_greedy_speedup'], 2)}× "
            f"| {r['greedy_layer_counts']} | {r['ours_layer_counts']} |\n"
        )
    buf.write(f"\n> {data['note']}\n\n")


def _section_concurrent(buf: StringIO) -> None:
    data = _read("concurrent")
    if data is None:
        return
    buf.write("## Concurrent requests — throughput vs concurrency (live)\n\n")
    buf.write(f"- `{data['model_id']}`, max_tokens/request = {data['max_tokens_per_request']}\n\n")
    buf.write("| concurrency | n_requests | total_s | aggregate tok/s | p50 latency | max latency |\n")
    buf.write("|---:|---:|---:|---:|---:|---:|\n")
    for r in data["rows"]:
        buf.write(
            f"| {r['concurrency']} | {r['n_requests']} "
            f"| {_fmt_float(r['total_seconds'])} "
            f"| {_fmt_float(r['aggregate_throughput_tokens_per_sec'], 1)} "
            f"| {_fmt_float(r['per_request_latency_p50_seconds'])}s "
            f"| {_fmt_float(r['per_request_latency_max_seconds'])}s |\n"
        )
    buf.write("\n")


def _section_algo_runtime(buf: StringIO) -> None:
    data = _read("algo_runtime")
    if data is None:
        return
    buf.write("## DP runtime sweep (algorithmic)\n\n")
    buf.write(f"- repeat per cell: {data['repeat_per_cell']}\n\n")
    buf.write("| L | |D| | L²×|D| | runtime median (s) |\n")
    buf.write("|---:|---:|---:|---:|\n")
    for r in data["rows"]:
        buf.write(
            f"| {r['num_layers']} | {r['num_devices']} | {r['L_squared_times_M']} "
            f"| {_fmt_float(r['runtime_seconds_median'], 5)} |\n"
        )
    buf.write(f"\n> {data['note']}\n\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write report to this path (default: stdout).",
    )
    args = p.parse_args()
    buf = StringIO()
    buf.write("# RADP Phase 4 — Benchmark report\n\n")
    _section_normal(buf)
    _section_failure(buf)
    _section_concurrent(buf)
    _section_algo_memory(buf)
    _section_algo_hetero(buf)
    _section_algo_runtime(buf)
    text = buf.getvalue()
    if args.out is None:
        print(text)
    else:
        args.out.write_text(text)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
