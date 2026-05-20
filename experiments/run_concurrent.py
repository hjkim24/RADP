"""Concurrent-request throughput benchmark (Phase 2.8).

Sweeps concurrency level C ∈ {1, 2, 4, 8, ...}: fires C ``generate(prompt,
max_tokens)`` calls in parallel from a ThreadPoolExecutor against a single
RequestGateway, measures total wall time, and reports aggregate throughput
(tokens / second across all concurrent requests).

A perfectly serial system shows constant throughput as C grows; a system
that exploits concurrency shows throughput climbing — up to the point where
the workers' inference compute (or coordinator's embed/head, or thread-pool
size) saturates.
"""

from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from experiments._harness import deploy, in_process_cluster, write_json
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.gateway import RequestGateway

log = get_logger(__name__)

MODEL_ID = "facebook/opt-125m"


def _placement_and_recovery() -> tuple[Placement, RecoveryTable]:
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery: RecoveryTable = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }
    return placement, recovery


def run(
    *,
    concurrencies: list[int],
    requests_per_level: int,
    max_tokens: int,
    prompt: str,
) -> dict[str, object]:
    placement, recovery = _placement_and_recovery()
    rows = []
    with in_process_cluster(["worker-a", "worker-b", "worker-c"]) as (addrs, _):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        try:
            # Warm caches + tokenizer.
            gw.generate(prompt, max_tokens=2)

            for c in concurrencies:
                n_requests = max(requests_per_level, c)
                # Round n_requests up to a multiple of c so each "wave" is full.
                if n_requests % c != 0:
                    n_requests += c - (n_requests % c)
                per_req_times: list[float] = []
                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=c) as pool:
                    futures = []
                    for _ in range(n_requests):
                        t_req = time.perf_counter()
                        futures.append(
                            (t_req, pool.submit(gw.generate, prompt, max_tokens))
                        )
                    for t_req, f in futures:
                        f.result(timeout=180)
                        per_req_times.append(time.perf_counter() - t_req)
                total = time.perf_counter() - t0
                total_tokens = n_requests * max_tokens
                rows.append(
                    {
                        "concurrency": c,
                        "n_requests": n_requests,
                        "total_seconds": total,
                        "aggregate_throughput_tokens_per_sec": total_tokens / total,
                        "per_request_latency_p50_seconds": statistics.median(
                            per_req_times
                        ),
                        "per_request_latency_max_seconds": max(per_req_times),
                    }
                )
                log.info(
                    "concurrency=%d  reqs=%d  agg=%.1f tok/s  p50_lat=%.3fs",
                    c, n_requests,
                    rows[-1]["aggregate_throughput_tokens_per_sec"],
                    rows[-1]["per_request_latency_p50_seconds"],
                )
        finally:
            gw.close()
    return {
        "model_id": MODEL_ID,
        "max_tokens_per_request": max_tokens,
        "rows": rows,
    }


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--concurrencies", type=int, nargs="+", default=[1, 2, 4, 8])
    p.add_argument("--requests-per-level", type=int, default=8)
    p.add_argument("--max-tokens", type=int, default=8)
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--out", default="concurrent")
    args = p.parse_args()
    result = run(
        concurrencies=args.concurrencies,
        requests_per_level=args.requests_per_level,
        max_tokens=args.max_tokens,
        prompt=args.prompt,
    )
    write_json(args.out, result)


if __name__ == "__main__":
    main()
