"""Live normal-operation benchmark (plan.md §6.5 scenario 1).

Runs N requests of OPT-125M with a fixed prompt and max_tokens, measuring:
  - TTFT  (prefill latency)
  - TBT   (median decode-step latency)
  - tokens/sec (end-to-end throughput)

In-process gRPC cluster on free localhost ports. Currently records only our
system; baseline comparison lives in run_algorithm.py (cross-strategy
algorithmic comparison) since on a homogeneous Mac CPU greedy and DP both
land on the same 4-4-4 split.
"""

from __future__ import annotations

import argparse
import statistics
import time

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
    n_requests: int,
    max_tokens: int,
    prompt: str,
    out_name: str,
) -> dict[str, object]:
    placement, recovery = _placement_and_recovery()
    device_ids = ["worker-a", "worker-b", "worker-c"]

    with in_process_cluster(device_ids) as (addrs, _):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement,
            recovery=recovery,
            worker_addresses=addrs,
            model_id=MODEL_ID,
        )

        # Warm up to load tokenizer / caches.
        gw.generate(prompt, max_tokens=2)

        per_request: list[dict[str, float]] = []
        for i in range(n_requests):
            request_id = gw.new_request_id()
            try:
                t_pre0 = time.perf_counter()
                gw._prefill(request_id, prompt)
                ttft = time.perf_counter() - t_pre0

                decode_lat: list[float] = []
                for _ in range(max_tokens - 1):
                    t_dec0 = time.perf_counter()
                    gw._decode_step(request_id)
                    decode_lat.append(time.perf_counter() - t_dec0)

                total = ttft + sum(decode_lat)
                tbt_median = statistics.median(decode_lat) if decode_lat else float("nan")
                per_request.append(
                    {
                        "request_idx": i,
                        "ttft_seconds": ttft,
                        "tbt_median_seconds": tbt_median,
                        "decode_steps": len(decode_lat),
                        "total_seconds": total,
                        "throughput_tokens_per_sec": max_tokens / total,
                    }
                )
            finally:
                gw._evict_everywhere(request_id)

    ttfts = [r["ttft_seconds"] for r in per_request]
    tbts = [r["tbt_median_seconds"] for r in per_request]
    thrus = [r["throughput_tokens_per_sec"] for r in per_request]
    summary = {
        "model_id": MODEL_ID,
        "placement_devices": [s.device for s in placement],
        "stages_layers": [(int(s.start_layer), int(s.end_layer)) for s in placement],
        "n_requests": n_requests,
        "max_tokens": max_tokens,
        "prompt_chars": len(prompt),
        "ttft_seconds_mean": statistics.fmean(ttfts),
        "ttft_seconds_p50": statistics.median(ttfts),
        "tbt_seconds_p50": statistics.median(tbts),
        "throughput_tokens_per_sec_mean": statistics.fmean(thrus),
        "per_request": per_request,
    }
    write_json(out_name, summary)
    log.info(
        "normal: TTFT=%.3fs  TBT=%.3fs  throughput=%.1f tok/s  (over %d requests)",
        summary["ttft_seconds_mean"],
        summary["tbt_seconds_p50"],
        summary["throughput_tokens_per_sec_mean"],
        n_requests,
    )
    return summary


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--requests", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=12)
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--out", default="normal")
    args = p.parse_args()
    run(
        n_requests=args.requests,
        max_tokens=args.max_tokens,
        prompt=args.prompt,
        out_name=args.out,
    )


if __name__ == "__main__":
    main()
