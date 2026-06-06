"""Concurrent multi-stream throughput measurement against a deployed coord.

The Phase D / EXP-D2.4 single-stream A3b' run optimises Σ stage_time
(latency mode) which gives one user the best TBT but parks 21 of 24
layers on the AGX. Under k concurrent streams the AGX becomes a queue
and the pipeline serialises behind it, while a throughput-mode
placement (balanced stages, lower max_stage_time) should win.

This script measures aggregate token throughput across a configurable
number of concurrent stream_generate calls. Pair it with two coord
deployments (throughput-mode vs latency-mode) to characterise the
crossover.

Result JSON: per-stream wall-clock + token count + TBT distribution +
the aggregate tok/s computed against wall-clock of the slowest stream.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Reuse the SSE client + result dir constant from the existing runner.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.run_failure_remote import stream_generate  # noqa: E402
from radp.common.logging_utils import configure_logging, get_logger

log = get_logger(__name__)

RESULTS_DIR = Path("experiments/results")


def _run_one_stream(
    coord_web: str,
    prompt: str,
    max_tokens: int,
    stream_idx: int,
    warmup_skip: int,
) -> dict[str, Any]:
    """One SSE generate call. Returns wall, tokens, TTFT, per-token TBTs."""
    t0 = time.perf_counter()
    last = t0
    ttft: float | None = None
    tbts: list[float] = []
    tokens = 0
    err: str | None = None
    try:
        for frame in stream_generate(coord_web, prompt=prompt, max_tokens=max_tokens):
            now = time.perf_counter()
            if ttft is None:
                ttft = now - t0
            else:
                tbts.append(now - last)
            last = now
            if frame.get("text") is not None:
                tokens += 1
            if frame.get("done"):
                break
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    wall = last - t0
    tbts_post_warmup = tbts[warmup_skip:] if warmup_skip > 0 else tbts
    return {
        "stream_idx": stream_idx,
        "tokens": tokens,
        "wall_seconds": wall,
        "ttft_seconds": ttft,
        "tbt_seconds": tbts,
        "tbt_p50_postwarmup": statistics.median(tbts_post_warmup) if tbts_post_warmup else None,
        "tbt_p95_postwarmup": (
            statistics.quantiles(tbts_post_warmup, n=20)[18]
            if len(tbts_post_warmup) >= 20 else None
        ),
        "error": err,
    }


def measure_concurrent(
    *,
    coord_web: str,
    concurrency: int,
    prompt: str,
    max_tokens: int,
    warmup_skip: int,
) -> dict[str, Any]:
    """Spawn `concurrency` concurrent streams, return per-stream + aggregate metrics."""
    log.info("concurrency=%d max_tokens=%d", concurrency, max_tokens)
    t_wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _run_one_stream, coord_web, prompt, max_tokens, i, warmup_skip,
            )
            for i in range(concurrency)
        ]
        results = [f.result() for f in as_completed(futures)]
    wall_total = time.perf_counter() - t_wall_start
    results.sort(key=lambda r: r["stream_idx"])

    total_tokens = sum(r["tokens"] for r in results)
    successful = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]
    aggregate_tok_per_sec = total_tokens / wall_total if wall_total > 0 else 0.0
    per_stream_tok_per_sec = [
        r["tokens"] / r["wall_seconds"] if r["wall_seconds"] > 0 else 0.0
        for r in successful
    ]
    tbts_all = [t for r in successful for t in r["tbt_seconds"][warmup_skip:]]

    summary = {
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "wall_seconds": wall_total,
        "total_tokens": total_tokens,
        "aggregate_tok_per_sec": aggregate_tok_per_sec,
        "successful_streams": len(successful),
        "failed_streams": len(failed),
        "per_stream_tok_per_sec_mean": (
            statistics.fmean(per_stream_tok_per_sec) if per_stream_tok_per_sec else 0.0
        ),
        "tbt_p50_all_streams": statistics.median(tbts_all) if tbts_all else None,
        "tbt_p95_all_streams": (
            statistics.quantiles(tbts_all, n=20)[18] if len(tbts_all) >= 20 else None
        ),
    }
    log.info(
        "C=%d: wall=%.2fs total=%d tokens, aggregate=%.1f tok/s, "
        "per-stream mean=%.1f tok/s, TBT p50=%s ms",
        concurrency, wall_total, total_tokens,
        aggregate_tok_per_sec, summary["per_stream_tok_per_sec_mean"],
        f"{summary['tbt_p50_all_streams']*1000:.1f}" if summary["tbt_p50_all_streams"] else "—",
    )
    return {"summary": summary, "per_stream": results}


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--coord-web", default="115.145.158.253:8080")
    p.add_argument("--prompt", default="The quick brown fox jumps over the lazy dog")
    p.add_argument("--max-tokens", type=int, default=30,
                   help="tokens per stream")
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8],
                   help="sweep these concurrency levels")
    p.add_argument("--warmup-skip", type=int, default=2,
                   help="drop first N TBT samples per stream as warmup")
    p.add_argument("--repeats", type=int, default=1,
                   help="run each concurrency level N times and aggregate")
    p.add_argument("--out", default="concurrent_throughput",
                   help="output JSON name under experiments/results/")
    args = p.parse_args()

    sweep: dict[int, list[dict[str, Any]]] = {c: [] for c in args.concurrency}
    for rep in range(args.repeats):
        log.info("===== repeat %d/%d =====", rep + 1, args.repeats)
        for c in args.concurrency:
            r = measure_concurrent(
                coord_web=args.coord_web,
                concurrency=c,
                prompt=args.prompt,
                max_tokens=args.max_tokens,
                warmup_skip=args.warmup_skip,
            )
            sweep[c].append(r)

    out_path = RESULTS_DIR / f"{args.out}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "coord_web": args.coord_web,
        "prompt": args.prompt,
        "max_tokens": args.max_tokens,
        "warmup_skip": args.warmup_skip,
        "repeats": args.repeats,
        "sweep": {str(c): runs for c, runs in sweep.items()},
    }, indent=2))
    log.info("wrote %s", out_path)

    # Compact summary table for quick visual review
    log.info("=" * 60)
    log.info("FINAL TABLE — aggregate tok/s by concurrency")
    log.info("%-12s | %-15s | %-15s | %s",
             "concurrency", "aggregate tok/s", "per-stream tok/s", "TBT p50 (ms)")
    log.info("-" * 60)
    for c in args.concurrency:
        runs = sweep[c]
        ag = statistics.fmean([r["summary"]["aggregate_tok_per_sec"] for r in runs])
        ps = statistics.fmean([r["summary"]["per_stream_tok_per_sec_mean"] for r in runs])
        tbt_p50s = [
            r["summary"]["tbt_p50_all_streams"] for r in runs
            if r["summary"]["tbt_p50_all_streams"] is not None
        ]
        tbt = statistics.fmean(tbt_p50s) * 1000 if tbt_p50s else float("nan")
        log.info("%-12d | %-15.1f | %-15.1f | %.1f", c, ag, ps, tbt)


if __name__ == "__main__":
    main()
