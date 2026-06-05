"""A3b — live deployment of baseline placements + comparison.

For each of the four baselines (greedy / uniform / jupiter_dp / ours):

  1. Render a complete manual-mode cluster.yaml carrying that baseline's
     placement + R-table, push it to /etc/radp/cluster.yaml on the
     coordinator, restart radp-coordinator, and wait for
     /api/gateway to come ready (ready=True && dead_devices==[]).

  2. Run a normal-operation benchmark (gRPC Generate × N requests) and
     record TTFT / TBT / throughput.

  3. Run a failure-injection benchmark (--trials K) against the same
     victim. Baselines with R={} (greedy / uniform / jupiter_dp) will
     hit NoRecoveryError mid-stream: the run_trial logic surfaces this
     as an SSE error frame, and the per-trial summary captures it as
     `_no_recovery_observed` plus the count of tokens emitted before
     the stream died — that's the catastrophic-failure data point.

  4. Save all per-cell raw timings + aggregate to a single JSON.

Why this is meaningful even though A3a found Ours.Psi == Jupiter_DP.Psi:
the normal-operation cells should overlap (placement is identical for
ours vs jupiter), confirming the empirical equivalence, while the
failure cells will diverge dramatically (ours survives with ~680ms
spike; jupiter / greedy / uniform crash). That divergence IS the
paper's headline experimental claim about recovery-awareness.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import grpc

from experiments._harness import RESULTS_DIR
from experiments.a3_baselines import (
    cluster_spec_from_sidecar,
    compute_all_baselines,
)
from experiments.run_e2e_remote import _bench_one_request, _percentile
from experiments.run_failure_remote import (
    aggregate_trials,
    fetch_sidecar,
    wait_for_coordinator_ready,
)
from experiments.run_failure_remote import (
    run_trial as run_failure_trial,
)
from experiments.run_failure_remote import (
    summarize as summarize_failure,
)
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.proto import radp_pb2_grpc

log = get_logger(__name__)


_DEFAULT_COORD_HOST = "ax-1"
_DEFAULT_COORD_GRPC = "115.145.158.253:50050"
_DEFAULT_COORD_WEB = "115.145.158.253:8080"
_DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"
_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


# ---------------------------------------------------------------------------
# 1) Cluster yaml synthesis + push
# ---------------------------------------------------------------------------
def fetch_current_gateway(coord_web: str) -> dict[str, Any]:
    """GET /api/gateway → model + worker info (used to reconstruct the yaml)."""
    with urllib.request.urlopen(f"http://{coord_web}/api/gateway", timeout=10) as r:  # noqa: S310
        return dict(json.loads(r.read().decode("utf-8")))


def build_manual_cluster_yaml(
    *,
    model_id: str,
    model_dtype: str,
    model_torch_device: str,
    workers: list[dict[str, str]],  # [{id, address}, ...]
    placement: list[dict[str, Any]],
    recovery: dict[str, str],
    coord_bind: str = "0.0.0.0:50050",
    activation_bytes: int = 1_048_576,
    slo_ttft_seconds: float = 3.0,
    slo_tbt_seconds: float = 1.0,
    heartbeat_timeout_seconds: float = 5.0,
    heartbeat_tick_seconds: float = 1.0,
) -> str:
    """Build a complete manual-mode cluster.yaml as a string.

    Matches the format produced by deploy/.../cluster.yaml.j2 in manual mode
    (the coord's `CoordinatorConfig.from_yaml` parses this back).
    """
    lines: list[str] = []
    lines.append("## Rendered by experiments/run_a3_remote.py")
    lines.append("model:")
    lines.append(f"  id: {model_id}")
    lines.append(f"  dtype: {model_dtype}")
    lines.append(f"  torch_device: {model_torch_device}")
    lines.append("")
    lines.append("coordinator:")
    lines.append(f'  bind: "{coord_bind}"')
    lines.append(f"  heartbeat_timeout_seconds: {heartbeat_timeout_seconds}")
    lines.append(f"  heartbeat_tick_seconds: {heartbeat_tick_seconds}")
    lines.append("  schedule_mode: manual")
    lines.append(f"  activation_bytes: {activation_bytes}")
    lines.append("  slo:")
    lines.append(f"    ttft_seconds: {slo_ttft_seconds}")
    lines.append(f"    tbt_seconds: {slo_tbt_seconds}")
    lines.append("")
    lines.append("workers:")
    for w in workers:
        lines.append(f"  - id: {w['id']}")
        lines.append(f'    address: "{w["address"]}"')
    lines.append("")
    lines.append("placement:")
    for s in placement:
        lines.append(f"  - device: {s['device']}")
        lines.append(f"    start: {int(s['start'])}")
        lines.append(f"    end: {int(s['end'])}")
    lines.append("")
    lines.append("recovery:")
    if recovery:
        for j, k in recovery.items():
            lines.append(f"  {j}: {k}")
    else:
        lines.append("  {}")
    return "\n".join(lines) + "\n"


def push_cluster_yaml(coord_host: str, yaml_str: str) -> tuple[float, bool, str]:
    """SCP the yaml to coord:/etc/radp/cluster.yaml via Ansible copy."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
        tf.write(yaml_str)
        local_path = tf.name
    t0 = time.perf_counter()
    cp = subprocess.run(
        ["ansible", coord_host, "-b", "-m", "copy",
         "-a", f"src={local_path} dest=/etc/radp/cluster.yaml owner=root group=root mode=0644"],
        cwd=_DEPLOY_DIR, capture_output=True, text=True, timeout=60, check=False,
    )
    dt = time.perf_counter() - t0
    ok = cp.returncode == 0
    if not ok:
        log.warning("push_cluster_yaml failed rc=%d: %s", cp.returncode, cp.stderr.strip())
    Path(local_path).unlink(missing_ok=True)
    return dt, ok, cp.stderr


def restart_coord(coord_host: str) -> tuple[float, bool, str]:
    t0 = time.perf_counter()
    cp = subprocess.run(
        ["ansible", coord_host, "-b", "-m", "systemd",
         "-a", "name=radp-coordinator state=restarted"],
        cwd=_DEPLOY_DIR, capture_output=True, text=True, timeout=60, check=False,
    )
    return time.perf_counter() - t0, cp.returncode == 0, cp.stderr


def deploy_baseline(
    *,
    coord_host: str,
    coord_web: str,
    yaml_str: str,
    ready_timeout: float = 180.0,
) -> dict[str, Any]:
    """Push yaml + restart + wait ready. Returns timing + status info."""
    info: dict[str, Any] = {}

    push_dt, push_ok, _ = push_cluster_yaml(coord_host, yaml_str)
    info["push_seconds"] = push_dt
    info["push_ok"] = push_ok
    if not push_ok:
        info["aborted"] = "push_failed"
        return info

    restart_dt, restart_ok, _ = restart_coord(coord_host)
    info["restart_seconds"] = restart_dt
    info["restart_ok"] = restart_ok
    if not restart_ok:
        info["aborted"] = "restart_failed"
        return info

    wait_s, ready, final = wait_for_coordinator_ready(
        coord_web, timeout_seconds=ready_timeout
    )
    info["wait_seconds"] = wait_s
    info["ready"] = ready
    info["final_state"] = (
        {"dead_devices": final.get("dead_devices"),
         "placement": final.get("placement")}
        if final else None
    )
    if not ready:
        info["aborted"] = "not_ready_after_timeout"
    return info


# ---------------------------------------------------------------------------
# 2) Per-cell benchmarks
# ---------------------------------------------------------------------------
def run_normal_benchmark(
    coord_grpc: str,
    *,
    n_requests: int,
    warmup: int,
    max_tokens: int,
    prompt: str,
) -> dict[str, Any]:
    """gRPC Generate × N. Same per-request timing as run_e2e_remote."""
    channel = grpc.insecure_channel(coord_grpc, options=_GRPC_OPTIONS)
    stub = radp_pb2_grpc.CoordinatorServiceStub(channel)
    try:
        for _ in range(warmup):
            _bench_one_request(stub, prompt, max_tokens=2)
        per_request = []
        for i in range(n_requests):
            row = _bench_one_request(stub, prompt, max_tokens=max_tokens)
            row["request_idx"] = i
            per_request.append(row)
    finally:
        channel.close()

    ttfts = [r["ttft_seconds"] for r in per_request]
    tbts = [t for r in per_request for t in r["tbt_seconds_each"]]
    thrus = [r["throughput_tokens_per_sec"] for r in per_request]
    return {
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
            "count": len(tbts),
            "mean": statistics.fmean(tbts) if tbts else float("nan"),
            "p50": _percentile(tbts, 0.5),
            "p95": _percentile(tbts, 0.95),
            "p99": _percentile(tbts, 0.99),
        },
        "throughput_tokens_per_sec": {
            "mean": statistics.fmean(thrus) if thrus else float("nan"),
        },
        "per_request": per_request,
    }


def run_failure_benchmark(
    *,
    coord_web: str,
    coord_host: str,
    victim: str,
    prompt: str,
    max_tokens: int,
    kill_after_tokens: int,
    trials: int,
    yaml_for_reset: str,
    ready_timeout: float = 180.0,
) -> dict[str, Any]:
    """Run K failure-injection trials. Between trials, push the same yaml
    again (so coord comes back up in the *same* manual-mode placement
    after the previous trial dirtied the gateway state)."""
    all_trials: list[dict[str, Any]] = []
    all_summaries: list[dict[str, Any]] = []

    for trial_idx in range(trials):
        log.info("  [failure] trial %d/%d", trial_idx + 1, trials)
        sidecar_before = fetch_sidecar(coord_host)
        trial = run_failure_trial(
            coord_web=coord_web,
            victim=victim,
            prompt=prompt,
            max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens,
        )
        summary = summarize_failure(trial)

        if "_no_recovery_observed" in summary:
            # R={} case: the gateway raised NoRecoveryError mid-stream,
            # surfacing as an SSE error frame. Add catastrophic-failure
            # fields the aggregator can later pivot on.
            summary["kind"] = "catastrophic_failure"
            summary["tokens_emitted_before_failure"] = trial["tokens_emitted"]
        elif "recovery_step_seconds" in summary:
            summary["kind"] = "graceful_recovery"
        else:
            summary["kind"] = "indeterminate"

        log.info("    -> kind=%s, tokens=%d/%d, error=%s",
                 summary["kind"], trial["tokens_emitted"],
                 trial["max_tokens_requested"], trial.get("error"))

        all_trials.append({
            "trial_idx": trial_idx, "trial": trial, "summary": summary,
            "scheduler_before": sidecar_before,
        })
        all_summaries.append(summary)

        if trial_idx + 1 < trials:
            log.info("  [failure] resetting cluster (re-push same yaml)")
            reset_info = _reset_to_same_yaml(
                coord_host=coord_host, coord_web=coord_web,
                victim=victim, yaml_str=yaml_for_reset,
                ready_timeout=ready_timeout,
            )
            all_trials[-1]["reset"] = reset_info

    catastrophic = [s for s in all_summaries if s.get("kind") == "catastrophic_failure"]
    graceful = [s for s in all_summaries if s.get("kind") == "graceful_recovery"]

    return {
        "n_trials": trials,
        "n_catastrophic": len(catastrophic),
        "n_graceful": len(graceful),
        "trials": all_trials,
        "aggregate": aggregate_trials(all_summaries),
        "catastrophic_tokens_before_failure": {
            "values": [s.get("tokens_emitted_before_failure", 0) for s in catastrophic],
            "mean": (
                statistics.fmean(
                    s.get("tokens_emitted_before_failure", 0) for s in catastrophic
                )
                if catastrophic else float("nan")
            ),
        },
    }


def _reset_to_same_yaml(
    *, coord_host: str, coord_web: str, victim: str,
    yaml_str: str, ready_timeout: float,
) -> dict[str, Any]:
    """Restart victim worker + restart coord with the SAME yaml + wait ready.
    Used between failure trials within a single baseline cell to get back
    to the trial's starting state without changing the placement."""
    cp = subprocess.run(
        ["ansible", victim, "-b", "-m", "systemd",
         "-a", "name=radp-worker state=started"],
        cwd=_DEPLOY_DIR, capture_output=True, text=True, timeout=30, check=False,
    )
    victim_ok = cp.returncode == 0

    # Re-push yaml in case anything got perturbed, then restart.
    push_dt, push_ok, _ = push_cluster_yaml(coord_host, yaml_str)
    restart_dt, restart_ok, _ = restart_coord(coord_host)
    wait_s, ready, _ = wait_for_coordinator_ready(
        coord_web, timeout_seconds=ready_timeout
    )
    return {
        "victim_restart_ok": victim_ok,
        "push_seconds": push_dt, "push_ok": push_ok,
        "restart_seconds": restart_dt, "restart_ok": restart_ok,
        "wait_seconds": wait_s, "ready": ready,
    }


# ---------------------------------------------------------------------------
# 3) Per-baseline orchestration
# ---------------------------------------------------------------------------
def run_baseline_cell(
    *,
    name: str,
    placement: list[dict[str, Any]],
    recovery: dict[str, str],
    coord_host: str,
    coord_web: str,
    coord_grpc: str,
    gateway_info: dict[str, Any],
    victim: str,
    normal_requests: int,
    normal_warmup: int,
    normal_max_tokens: int,
    failure_trials: int,
    failure_max_tokens: int,
    failure_kill_after: int,
    prompt: str,
    ready_timeout: float,
) -> dict[str, Any]:
    """Full pipeline for one baseline cell."""
    log.info("========== BASELINE: %s ==========", name)
    log.info("placement: %s", ", ".join(
        f"{s['device']}[{s['start']}-{s['end']}]" for s in placement
    ))
    log.info("recovery : %s", recovery if recovery else "{}")

    yaml_str = build_manual_cluster_yaml(
        model_id=gateway_info["model_id"],
        model_dtype=gateway_info["dtype"],
        model_torch_device=gateway_info["torch_device"],
        workers=[{"id": w["id"], "address": w["address"]}
                 for w in gateway_info["workers"]],
        placement=placement,
        recovery=recovery,
    )

    deploy_info = deploy_baseline(
        coord_host=coord_host, coord_web=coord_web,
        yaml_str=yaml_str, ready_timeout=ready_timeout,
    )
    if deploy_info.get("aborted"):
        log.error("deploy aborted for %s: %s", name, deploy_info["aborted"])
        return {"name": name, "deploy": deploy_info, "skipped": True}

    log.info("[%s] normal benchmark (n=%d × %d tok)", name, normal_requests, normal_max_tokens)
    normal = run_normal_benchmark(
        coord_grpc=coord_grpc, n_requests=normal_requests, warmup=normal_warmup,
        max_tokens=normal_max_tokens, prompt=prompt,
    )
    log.info("  TTFT p50=%.3fs p95=%.3fs | TBT p50=%.3fs p95=%.3fs",
             normal["ttft_seconds"]["p50"], normal["ttft_seconds"]["p95"],
             normal["tbt_seconds"]["p50"], normal["tbt_seconds"]["p95"])

    # Between normal and failure cells, push the SAME yaml + restart so we
    # start the failure trials from a clean state (no dead from previous
    # work, gateway _dead set cleared).
    log.info("[%s] resetting before failure trials", name)
    reset_info = _reset_to_same_yaml(
        coord_host=coord_host, coord_web=coord_web,
        victim=victim, yaml_str=yaml_str, ready_timeout=ready_timeout,
    )

    log.info("[%s] failure benchmark (victim=%s, %d trials × %d tok, kill after %d)",
             name, victim, failure_trials, failure_max_tokens, failure_kill_after)
    failure = run_failure_benchmark(
        coord_web=coord_web, coord_host=coord_host, victim=victim,
        prompt=prompt, max_tokens=failure_max_tokens,
        kill_after_tokens=failure_kill_after, trials=failure_trials,
        yaml_for_reset=yaml_str, ready_timeout=ready_timeout,
    )
    log.info("  catastrophic=%d/%d graceful=%d/%d",
             failure["n_catastrophic"], failure_trials,
             failure["n_graceful"], failure_trials)

    return {
        "name": name,
        "placement": placement,
        "recovery": recovery,
        "deploy": deploy_info,
        "pre_failure_reset": reset_info,
        "normal": normal,
        "failure": failure,
    }


# ---------------------------------------------------------------------------
# 4) CLI
# ---------------------------------------------------------------------------
def _load_baselines_from_sidecar(sidecar_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load A1's sidecar JSON and return (sidecar, computed baselines)."""
    payload = json.loads(sidecar_path.read_text())
    sidecar = payload.get("scheduler") or payload
    spec = cluster_spec_from_sidecar(sidecar)
    return sidecar, compute_all_baselines(spec)


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--coord-web", default=_DEFAULT_COORD_WEB)
    p.add_argument("--coord-host", default=_DEFAULT_COORD_HOST)
    p.add_argument("--coord-grpc", default=_DEFAULT_COORD_GRPC)
    p.add_argument("--sidecar", default="experiments/results/auto_baseline_first.json",
                   help="sidecar with embedded scheduler block (for baseline computation)")
    p.add_argument("--baselines", nargs="+",
                   default=["greedy", "uniform", "jupiter_dp", "ours"],
                   help="which baselines to run (subset of all four)")
    p.add_argument("--victim", default="ao-1")
    p.add_argument("--prompt", default="The quick brown fox jumps over the lazy dog")
    p.add_argument("--normal-requests", type=int, default=10)
    p.add_argument("--normal-warmup", type=int, default=2)
    p.add_argument("--normal-max-tokens", type=int, default=30)
    p.add_argument("--failure-trials", type=int, default=3)
    p.add_argument("--failure-max-tokens", type=int, default=60)
    p.add_argument("--failure-kill-after", type=int, default=15)
    p.add_argument("--ready-timeout", type=float, default=180.0)
    p.add_argument("--out", default="a3_remote")
    args = p.parse_args()

    sidecar_path = Path(args.sidecar)
    log.info("loading baselines from %s", sidecar_path)
    sidecar, baselines = _load_baselines_from_sidecar(sidecar_path)
    log.info("baselines computed: %s", list(baselines.keys()))

    log.info("fetching current gateway info from %s", args.coord_web)
    gateway_info = fetch_current_gateway(args.coord_web)
    log.info("model=%s dtype=%s torch_device=%s workers=%d",
             gateway_info["model_id"], gateway_info["dtype"],
             gateway_info["torch_device"], len(gateway_info["workers"]))

    out_path = RESULTS_DIR / f"{args.out}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "coord_web": args.coord_web,
        "coord_host": args.coord_host,
        "coord_grpc": args.coord_grpc,
        "victim": args.victim,
        "prompt": args.prompt,
        "source_sidecar": str(sidecar_path),
        "gateway_info_before": gateway_info,
        "computed_baselines": baselines,
        "cells": [],
    }

    for name in args.baselines:
        if name not in baselines:
            log.warning("baseline %r not in computed set — skipping", name)
            continue
        b = baselines[name]
        if b.get("infeasible"):
            log.warning("baseline %s infeasible: %s — skipping", name, b.get("reason"))
            continue
        cell = run_baseline_cell(
            name=name,
            placement=b["placement"],
            recovery=b["recovery"],
            coord_host=args.coord_host,
            coord_web=args.coord_web,
            coord_grpc=args.coord_grpc,
            gateway_info=gateway_info,
            victim=args.victim,
            normal_requests=args.normal_requests,
            normal_warmup=args.normal_warmup,
            normal_max_tokens=args.normal_max_tokens,
            failure_trials=args.failure_trials,
            failure_max_tokens=args.failure_max_tokens,
            failure_kill_after=args.failure_kill_after,
            prompt=args.prompt,
            ready_timeout=args.ready_timeout,
        )
        out["cells"].append(cell)
        # Save incrementally so a long run can be inspected / resumed.
        out_path.write_text(json.dumps(out, indent=2))
        log.info("wrote partial %s (%d/%d cells)",
                 out_path, len(out["cells"]), len(args.baselines))

    # Final comparison summary
    log.info("=" * 72)
    log.info("FINAL COMPARISON")
    log.info("%-12s | %s | %s | %s",
             "baseline", "normal_tbt_p50", "failure_kind", "tokens_completed")
    log.info("-" * 72)
    for cell in out["cells"]:
        if cell.get("skipped"):
            log.info("%-12s | SKIPPED (%s)", cell["name"], cell["deploy"].get("aborted"))
            continue
        n_tbt = cell["normal"]["tbt_seconds"]["p50"]
        f_agg = cell["failure"]
        f_kind = (
            f"graceful({f_agg['n_graceful']}/{f_agg['n_trials']})"
            if f_agg["n_graceful"]
            else f"catastrophic({f_agg['n_catastrophic']}/{f_agg['n_trials']})"
        )
        n_tok = (
            f_agg["catastrophic_tokens_before_failure"]["mean"]
            if f_agg["n_catastrophic"]
            else "all"
        )
        log.info("%-12s | %14.3fs | %20s | %s",
                 cell["name"], n_tbt, f_kind, n_tok)
    log.info("=" * 72)
    log.info("wrote %s", out_path)


if __name__ == "__main__":
    main()
