"""Live failure-recovery benchmark (plan.md §6.5 scenario 2).

Two measurements:

  A) Mid-decode cache-replay (PRIMARY measurement):
     Drive prefill + step-by-step decode manually, kill worker-b mid-way,
     observe that the next decode step takes ``recovery_latency_seconds``
     (which includes synchronous detection + cache replay to backup + retry)
     and the remaining steps continue at steady state. Tokens completed
     should equal max_tokens (no drops).

  B) Wall-clock comparison cache-replay vs re-prefill:
     Run ``gateway.generate(prompt, max_tokens)`` once normally as baseline,
     once with worker-b stopped BEFORE the call (forces every prefill to
     re-route via backup), once with the cache forcibly disabled (forces the
     outer-retry / re-prefill fallback). Compare total wall-clock.
"""

from __future__ import annotations

import argparse
import contextlib
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


# ---------------------------------------------------------------------------
# A) Mid-decode cache replay — per-step latencies
# ---------------------------------------------------------------------------
def measure_mid_decode_replay(
    *, prompt: str, max_tokens: int, kill_after_tokens: int
) -> dict[str, object]:
    placement, recovery = _placement_and_recovery()
    victim = DeviceId("worker-b")
    with in_process_cluster(["worker-a", "worker-b", "worker-c"]) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        gw.generate(prompt, max_tokens=2)  # warmup

        request_id = gw.new_request_id()
        steady: list[float] = []
        recovery_latency = float("nan")
        try:
            gw._prefill(request_id, prompt)
            for step in range(1, max_tokens):
                if step == kill_after_tokens:
                    servers[victim].stop()
                    log.info("victim %s stopped before step %d", victim, step)
                t0 = time.perf_counter()
                gw._decode_step(request_id)
                dt = time.perf_counter() - t0
                if step == kill_after_tokens:
                    recovery_latency = dt
                else:
                    steady.append(dt)
            tokens_done = len(gw._requests[request_id].generated_token_ids)
        finally:
            with contextlib.suppress(Exception):
                gw._evict_everywhere(request_id)

    steady_p50 = statistics.median(steady) if steady else float("nan")
    return {
        "tokens_completed": tokens_done,
        "max_tokens_requested": max_tokens,
        "kill_after_tokens": kill_after_tokens,
        "steady_tbt_p50_seconds": steady_p50,
        "recovery_step_seconds": recovery_latency,
        "extra_seconds_attributable_to_failure": recovery_latency - steady_p50,
    }


# ---------------------------------------------------------------------------
# B) End-to-end wall clock comparison
# ---------------------------------------------------------------------------
def measure_e2e_wall_clock(*, prompt: str, max_tokens: int) -> dict[str, object]:
    placement, recovery = _placement_and_recovery()
    results = {}

    # baseline: no failure
    with in_process_cluster(["worker-a", "worker-b", "worker-c"]) as (addrs, _):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL_ID)
        gw.generate(prompt, max_tokens=2)  # warmup
        t0 = time.perf_counter()
        baseline_tokens = gw.generate(prompt, max_tokens=max_tokens)
        results["baseline_seconds"] = time.perf_counter() - t0

    # cache_replay: kill worker-b before generate (every request re-routes)
    with in_process_cluster(["worker-a", "worker-b", "worker-c"]) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL_ID)
        gw.generate(prompt, max_tokens=2)
        servers[DeviceId("worker-b")].stop()
        t0 = time.perf_counter()
        replay_tokens = gw.generate(prompt, max_tokens=max_tokens)
        results["cache_replay_seconds"] = time.perf_counter() - t0

    # re_prefill: same as above but with cache history disabled, forcing
    # the outer-retry/re-prefill fallback inside `generate`.
    with in_process_cluster(["worker-a", "worker-b", "worker-c"]) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL_ID)
        gw.cache.get_history = lambda *a, **kw: []  # type: ignore[method-assign]
        gw.generate(prompt, max_tokens=2)
        servers[DeviceId("worker-b")].stop()
        t0 = time.perf_counter()
        reprefill_tokens = gw.generate(prompt, max_tokens=max_tokens)
        results["re_prefill_seconds"] = time.perf_counter() - t0

    results["baseline_tokens"] = baseline_tokens
    results["cache_replay_tokens"] = replay_tokens
    results["re_prefill_tokens"] = reprefill_tokens
    results["sequences_all_match"] = (
        baseline_tokens == replay_tokens == reprefill_tokens
    )
    return results


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--max-tokens", type=int, default=10)
    p.add_argument("--kill-after-tokens", type=int, default=4)
    p.add_argument("--out", default="failure")
    args = p.parse_args()

    log.info("A) mid-decode cache replay measurement")
    a = measure_mid_decode_replay(
        prompt=args.prompt, max_tokens=args.max_tokens,
        kill_after_tokens=args.kill_after_tokens,
    )
    log.info(
        "  steady_tbt=%.3fs recovery_step=%.3fs extra=%.3fs",
        a["steady_tbt_p50_seconds"], a["recovery_step_seconds"],
        a["extra_seconds_attributable_to_failure"],
    )

    log.info("B) end-to-end wall-clock comparison")
    b = measure_e2e_wall_clock(prompt=args.prompt, max_tokens=args.max_tokens)
    log.info(
        "  baseline=%.3fs cache_replay=%.3fs re_prefill=%.3fs match=%s",
        b["baseline_seconds"], b["cache_replay_seconds"],
        b["re_prefill_seconds"], b["sequences_all_match"],
    )

    out = {
        "model_id": MODEL_ID,
        "prompt": args.prompt,
        "max_tokens": args.max_tokens,
        "kill_after_tokens": args.kill_after_tokens,
        "mid_decode_replay": a,
        "e2e_wall_clock": b,
    }
    write_json(args.out, out)


if __name__ == "__main__":
    main()
