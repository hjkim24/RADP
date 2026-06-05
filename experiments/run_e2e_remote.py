"""Live-fleet end-to-end benchmark.

Runs against a deployed RADP coordinator (default 115.145.158.253:50050)
rather than the in-process cluster used by run_normal.py. Captures:

  * Per-request: TTFT, every TBT, steady-state throughput
  * Across requests: TTFT mean + p50/p95, TBT p50/p95/p99, tok/s mean
  * Scheduler stats from the coordinator's sidecar file
    (/tmp/radp_scheduler_stats.json), pulled in via Ansible. Includes
    per-phase wall clock (wait_for_workers, ProfileLayers,
    MeasurePeer, DP solve), placement, recovery table, layer/network/
    device profiles, and the chosen max_stage_time.

Writes everything to experiments/results/<out>.json. The intent is
"one JSON per bench run, large enough to plot from."
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import grpc

from experiments._harness import RESULTS_DIR
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc

log = get_logger(__name__)

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]
_DEFAULT_COORD = "115.145.158.253:50050"
_DEFAULT_COORD_HOST = "ax-1"  # ansible inventory name
_SIDECAR_REMOTE = "/tmp/radp_scheduler_stats.json"


def _fetch_scheduler_sidecar(host: str) -> dict[str, Any] | None:
    """Pull the coordinator's auto_schedule stats sidecar via Ansible.

    Returns None if the file isn't present or readable — that's normal in
    manual schedule_mode, where auto_schedule never ran.
    """
    deploy_dir = Path(__file__).resolve().parents[1] / "deploy"
    try:
        result = subprocess.run(
            ["ansible", host, "-b", "-m", "slurp", "-a", f"src={_SIDECAR_REMOTE}"],
            cwd=deploy_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("scheduler sidecar fetch failed: %s", e)
        return None
    # Ansible slurp returns base64 in stdout JSON; parse + decode.
    try:
        # Strip the "ax-1 | SUCCESS => " prefix Ansible prints.
        raw = result.stdout.split(" =>", 1)[1].strip()
        payload = json.loads(raw)
        import base64
        decoded = base64.b64decode(payload["content"]).decode("utf-8")
        return dict(json.loads(decoded))
    except Exception as e:  # noqa: BLE001
        log.warning("scheduler sidecar parse failed: %s", e)
        return None


def _bench_one_request(
    stub: Any, prompt: str, max_tokens: int
) -> dict[str, Any]:
    """Issue one Generate stream, time prefill (= TTFT) and every decode step."""
    req = radp_pb2.GenerateRequest(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.0,
        top_k=0,
        top_p=1.0,
        eos_token_id=0,
        seed=0,
    )
    t_send = time.perf_counter()
    iterator = stub.Generate(req)
    chunk_times: list[float] = []
    chunk_texts: list[str] = []
    for chunk in iterator:
        chunk_times.append(time.perf_counter())
        if chunk.text:
            chunk_texts.append(chunk.text)
        if chunk.done:
            break
    if not chunk_times:
        raise RuntimeError("Generate stream returned no chunks")

    ttft_s = chunk_times[0] - t_send
    # Each subsequent chunk = one decode step worth of latency.
    decode_lat = [
        chunk_times[i] - chunk_times[i - 1] for i in range(1, len(chunk_times))
    ]
    # Throughput counts every emitted text token (final empty chunk excluded).
    text_tokens = len(chunk_texts)
    total_s = chunk_times[-1] - t_send
    return {
        "ttft_seconds": ttft_s,
        "tbt_seconds_each": decode_lat,
        "total_seconds": total_s,
        "text_tokens": text_tokens,
        "throughput_tokens_per_sec": text_tokens / total_s if total_s > 0 else 0.0,
        "decoded_text": "".join(chunk_texts),
    }


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run(
    *,
    coord: str,
    coord_host: str,
    n_requests: int,
    warmup: int,
    max_tokens: int,
    prompt: str,
    out_name: str,
) -> dict[str, Any]:
    log.info("connecting to coordinator at %s", coord)
    channel = grpc.insecure_channel(coord, options=_GRPC_OPTIONS)
    stub = radp_pb2_grpc.CoordinatorServiceStub(channel)

    try:
        log.info("warmup x%d", warmup)
        for _ in range(warmup):
            _bench_one_request(stub, prompt, max_tokens=2)

        per_request: list[dict[str, Any]] = []
        for i in range(n_requests):
            log.info("request %d/%d", i + 1, n_requests)
            row = _bench_one_request(stub, prompt, max_tokens=max_tokens)
            row["request_idx"] = i
            per_request.append(row)
    finally:
        channel.close()

    # Aggregate across requests.
    ttfts = [r["ttft_seconds"] for r in per_request]
    all_tbts = [t for r in per_request for t in r["tbt_seconds_each"]]
    thrus = [r["throughput_tokens_per_sec"] for r in per_request]

    summary: dict[str, Any] = {
        "coord": coord,
        "model_id": None,  # filled from sidecar below if present
        "n_requests": n_requests,
        "warmup": warmup,
        "max_tokens": max_tokens,
        "prompt": prompt,
        "ttft_seconds": {
            "mean": statistics.fmean(ttfts) if ttfts else float("nan"),
            "p50": _percentile(ttfts, 0.5),
            "p95": _percentile(ttfts, 0.95),
        },
        "tbt_seconds": {
            "count": len(all_tbts),
            "mean": statistics.fmean(all_tbts) if all_tbts else float("nan"),
            "p50": _percentile(all_tbts, 0.5),
            "p95": _percentile(all_tbts, 0.95),
            "p99": _percentile(all_tbts, 0.99),
        },
        "throughput_tokens_per_sec": {
            "mean": statistics.fmean(thrus) if thrus else float("nan"),
            "p50": _percentile(thrus, 0.5),
        },
        "per_request": per_request,
    }

    log.info("fetching scheduler sidecar from %s", coord_host)
    sidecar = _fetch_scheduler_sidecar(coord_host)
    if sidecar is not None:
        summary["scheduler"] = sidecar
        summary["model_id"] = sidecar.get("model_id")

    out_path = RESULTS_DIR / f"{out_name}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    log.info("wrote %s", out_path)

    log.info(
        "TTFT mean=%.3fs p95=%.3fs  TBT p50=%.3fs p95=%.3fs  tok/s mean=%.1f",
        summary["ttft_seconds"]["mean"], summary["ttft_seconds"]["p95"],
        summary["tbt_seconds"]["p50"], summary["tbt_seconds"]["p95"],
        summary["throughput_tokens_per_sec"]["mean"],
    )
    if sidecar is not None:
        sched = sidecar.get("scheduler_result", {})
        log.info(
            "scheduler: max_stage=%.1fms iter=%d converged=%s  "
            "phases: wait=%.0fms layers=%.0fms net=%.0fms dp=%.1fms",
            sched.get("max_stage_time_seconds", 0) * 1000,
            sched.get("iterations", -1),
            sched.get("converged", False),
            sidecar["phase_ms"]["wait_for_workers"],
            sidecar["phase_ms"]["collect_layer_profiles"],
            sidecar["phase_ms"]["collect_network_profile"],
            sidecar["phase_ms"]["scheduler_solve"],
        )
    return summary


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--coord", default=_DEFAULT_COORD)
    p.add_argument("--coord-host", default=_DEFAULT_COORD_HOST,
                   help="Ansible inventory hostname for scheduler-sidecar fetch")
    p.add_argument("--requests", type=int, default=5)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--max-tokens", type=int, default=20)
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--out", default="e2e_remote")
    args = p.parse_args()
    run(
        coord=args.coord,
        coord_host=args.coord_host,
        n_requests=args.requests,
        warmup=args.warmup,
        max_tokens=args.max_tokens,
        prompt=args.prompt,
        out_name=args.out,
    )


if __name__ == "__main__":
    main()
