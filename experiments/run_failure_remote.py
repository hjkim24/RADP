"""Live-fleet failure-injection + recovery benchmark (plan.md §6 scenario 2).

Drives ONE long Generate request through the coordinator's SSE endpoint, kills
a target worker mid-stream via Ansible, and records:

  * Pre-kill steady-state TBT (the K decode steps before the kill is fired)
  * The recovery step itself (the first decode step that runs after kill —
    pays for gRPC error detection + execution-plan rebuild + cache replay
    + retry on backup)
  * Post-kill steady-state TBT (the remaining decode steps once recovery is
    done; should be close to pre-kill but with the backup doing 2x work)
  * Per-step stages list (device + start/end + invoke_seconds) — proves
    the backup absorbed the dead stage rather than the request hanging
  * Tokens emitted vs requested (correctness: must equal max_tokens)

Single trial per invocation. The coordinator's gateway has no `mark_alive`,
so once a worker is marked dead, it stays dead until coordinator restart.
Run multiple times by restarting the radp-coordinator unit between trials
(or just take the one-trial number as the headline result — the within-run
spike vs steady-state contrast is the actual paper data).

Default victim = ao-1 (an AGX Orin that the DP scheduler typically puts in
the middle of the pipeline, so its loss exercises a meaningful backup).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from experiments._harness import RESULTS_DIR
from radp.common.logging_utils import configure_logging, get_logger

log = get_logger(__name__)

_DEFAULT_COORD_HOST = "ax-1"             # ansible inventory name
_DEFAULT_COORD_WEB = "115.145.158.253:8080"  # FastAPI / SSE
_SIDECAR_REMOTE = "/tmp/radp_scheduler_stats.json"
_DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


# ---------------------------------------------------------------------------
# Ansible helpers — kill / restart victim worker, fetch sidecar
# ---------------------------------------------------------------------------
def _ansible(host: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run `ansible <host> -b <args>` from deploy/ with reasonable defaults."""
    return subprocess.run(
        ["ansible", host, "-b", *args],
        cwd=_DEPLOY_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def stop_worker(host: str) -> tuple[float, bool, str]:
    """SIGKILL the radp-worker unit on `host`. Returns (wall_seconds, ok, stderr)."""
    t0 = time.perf_counter()
    cp = _ansible(host, "-m", "shell", "-a", "systemctl kill -s KILL radp-worker")
    dt = time.perf_counter() - t0
    ok = cp.returncode == 0
    if not ok:
        log.warning("stop_worker(%s) failed rc=%d: %s", host, cp.returncode, cp.stderr.strip())
    else:
        log.warning("stop_worker(%s) issued in %.3fs", host, dt)
    return dt, ok, cp.stderr


def start_worker(host: str) -> tuple[float, bool, str]:
    """Re-start the radp-worker unit (post-experiment cleanup)."""
    t0 = time.perf_counter()
    cp = _ansible(host, "-m", "systemd", "-a", "name=radp-worker state=started")
    dt = time.perf_counter() - t0
    ok = cp.returncode == 0
    if not ok:
        log.warning("start_worker(%s) failed rc=%d: %s", host, cp.returncode, cp.stderr.strip())
    return dt, ok, cp.stderr


def restart_coordinator(host: str) -> tuple[float, bool, str]:
    """Restart the radp-coordinator unit. Clears the gateway's _dead set
    (no mark_alive API exists) and forces a fresh auto_schedule run."""
    t0 = time.perf_counter()
    cp = _ansible(host, "-m", "systemd", "-a", "name=radp-coordinator state=restarted", timeout=60)
    dt = time.perf_counter() - t0
    ok = cp.returncode == 0
    if not ok:
        log.warning("restart_coordinator(%s) failed rc=%d: %s", host, cp.returncode, cp.stderr.strip())
    return dt, ok, cp.stderr


def wait_for_coordinator_ready(
    coord_web: str, *, timeout_seconds: float = 180.0, poll_interval: float = 2.0
) -> tuple[float, bool, dict[str, Any] | None]:
    """Poll /api/gateway until ready=True && dead_devices=[].

    Returns (wall_seconds_waited, success, final_gateway_payload).
    auto_schedule runs ProfileLayers + MeasurePeer on every worker so the
    bring-up can easily take 60-90s on the live fleet — be generous.
    """
    t0 = time.perf_counter()
    last: dict[str, Any] | None = None
    while time.perf_counter() - t0 < timeout_seconds:
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"http://{coord_web}/api/gateway", timeout=5
            ) as r:
                last = json.loads(r.read().decode("utf-8"))
            if last.get("ready") and not last.get("dead_devices"):
                return time.perf_counter() - t0, True, last
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass  # coordinator still booting / FastAPI not up yet
        time.sleep(poll_interval)
    return time.perf_counter() - t0, False, last


def fetch_sidecar(host: str) -> dict[str, Any] | None:
    """Slurp /tmp/radp_scheduler_stats.json off the coordinator host."""
    try:
        cp = subprocess.run(
            ["ansible", host, "-b", "-m", "slurp", "-a", f"src={_SIDECAR_REMOTE}"],
            cwd=_DEPLOY_DIR, capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("sidecar fetch failed: %s", e)
        return None
    try:
        raw = cp.stdout.split(" =>", 1)[1].strip()
        payload = json.loads(raw)
        import base64
        return dict(json.loads(base64.b64decode(payload["content"]).decode("utf-8")))
    except Exception as e:  # noqa: BLE001
        log.warning("sidecar parse failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# SSE stream client
# ---------------------------------------------------------------------------
def stream_generate(
    coord_web: str,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float = 0.0,
    seed: int = 0,
    timeout: int = 600,
) -> Iterator[dict[str, Any]]:
    """POST /api/generate and yield each SSE `data: {...}` frame as a dict."""
    body = json.dumps(
        {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_k": 0,
            "top_p": 1.0,
            "seed": seed,
            "eos_token_id": 0,  # OPT BOS — never actually emitted under greedy
        }
    ).encode()
    req = urllib.request.Request(
        f"http://{coord_web}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
            if line.startswith("data: "):
                yield json.loads(line[6:])


def _victim_address(coord_web: str, victim: str) -> str | None:
    """Look up the victim's grpc address via /api/gateway (best-effort, logged only)."""
    try:
        with urllib.request.urlopen(f"http://{coord_web}/api/gateway", timeout=10) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        for w in data.get("workers", []):
            if w.get("id") == victim:
                return str(w.get("address"))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log.warning("gateway lookup failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# Single trial
# ---------------------------------------------------------------------------
def run_trial(
    *,
    coord_web: str,
    victim: str,
    prompt: str,
    max_tokens: int,
    kill_after_tokens: int,
) -> dict[str, Any]:
    """Open one Generate stream, fire `stop_worker(victim)` after K tokens, finish."""
    addr = _victim_address(coord_web, victim) or "<unknown>"
    log.info("victim=%s (address=%s), kill_after=%d/%d tokens",
             victim, addr, kill_after_tokens, max_tokens)

    per_token: list[dict[str, Any]] = []
    kill_t_local = None  # wall-clock seconds since t0 when kill was *issued*
    killed_at_token = None
    err: str | None = None
    kill_thread_holder: dict[str, Any] = {}

    def _run_kill(target_host: str, holder: dict[str, Any]) -> None:
        dt, ok, stderr = stop_worker(target_host)
        holder["dt"] = dt
        holder["ok"] = ok
        holder["stderr"] = stderr

    t0 = time.perf_counter()
    try:
        for frame in stream_generate(
            coord_web,
            prompt=prompt,
            max_tokens=max_tokens,
            seed=0,
        ):
            kind = frame.get("kind")
            if kind == "token":
                idx = len(per_token)  # 0-based index of this token
                per_token.append(
                    {
                        "idx": idx,
                        "t_recv": time.perf_counter() - t0,
                        "step_seconds": frame.get("step_seconds"),
                        "is_first": frame.get("is_first"),
                        "stages": frame.get("stages", []),
                        "text": frame.get("text", ""),
                    }
                )
                if idx + 1 == kill_after_tokens:
                    # Token kill_after_tokens has just arrived; fire the kill
                    # asynchronously so we don't block reading the stream.
                    kill_t_local = time.perf_counter() - t0
                    killed_at_token = idx
                    log.warning("firing stop_worker(%s) after token #%d at t=%.3fs",
                                victim, idx, kill_t_local)
                    # CRITICAL: fire-and-forget. Do NOT join the kill thread
                    # before continuing to read the SSE stream — joining
                    # blocks the main thread for the ~1.2s the ansible
                    # subprocess takes to complete, during which the
                    # coordinator keeps emitting tokens that pile up in
                    # the socket buffer. When the main thread resumes,
                    # all buffered frames are read with the same t_recv,
                    # destroying per-token timing fidelity.
                    kill_thread_holder["thread"] = threading.Thread(
                        target=_run_kill,
                        args=(victim, kill_thread_holder),
                        daemon=True,
                    )
                    kill_thread_holder["thread"].start()
            elif kind == "done":
                log.info("stream done: n_tokens=%d wall=%.3fs",
                         frame.get("n_tokens"), frame.get("wall_seconds"))
                break
            elif kind == "error":
                err = str(frame.get("message"))
                log.error("stream error frame: %s", err)
                break
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        err = repr(e)
        log.exception("stream connection failed")

    wall = time.perf_counter() - t0

    # Reap the kill thread (fire-and-forget so it may still be running).
    th = kill_thread_holder.get("thread")
    if th is not None:
        th.join(timeout=15)
    kill_dt = kill_thread_holder.get("dt")
    kill_ok = kill_thread_holder.get("ok")

    return {
        "victim": victim,
        "victim_address": addr,
        "prompt": prompt,
        "max_tokens_requested": max_tokens,
        "kill_after_tokens": kill_after_tokens,
        "tokens_emitted": len(per_token),
        "wall_seconds": wall,
        "killed_at_token": killed_at_token,
        "kill_issued_at_seconds": kill_t_local,
        "kill_command_seconds": kill_dt,
        "kill_command_ok": kill_ok,
        "error": err,
        "per_token": per_token,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def _stages_signature(tok: dict[str, Any]) -> tuple[tuple[str, int, int], ...]:
    """Hashable signature of a token's stage routing — used to detect the
    moment the execution plan flips to a backup."""
    return tuple(
        (s["device"], s["start"], s["end"]) for s in tok.get("stages", [])
    )


def _find_recovery_step(toks: list[dict[str, Any]], victim: str) -> int | None:
    """Locate the first token whose stages signature drops the victim entirely
    — that's the first decode step the gateway routed onto the backup."""
    for tok in toks:
        if tok.get("is_first"):
            continue
        if all(s["device"] != victim for s in tok.get("stages", [])):
            return int(tok["idx"])
    return None


def summarize(trial: dict[str, Any]) -> dict[str, Any]:
    """Decompose the trial into pre-kill / recovery / post-recovery stats.

    The recovery step is found by looking for the FIRST decode step where the
    stage list no longer contains the victim — that's when the gateway saw
    the failure and rebuilt the execution plan onto the backup. This is more
    reliable than assuming recovery happens at killed_at_token+1, because:

      (a) the kill is fired asynchronously (ansible takes ~1s to propagate);
      (b) several tokens may already be in flight before SIGKILL lands;
      (c) the actual recovery is when the routing flips, not when we sent
          the kill signal.
    """
    toks = trial["per_token"]
    if not toks:
        return {"_empty": True}

    decode_steps = [(t["idx"], t["step_seconds"]) for t in toks if not t.get("is_first")]
    victim = trial["victim"]
    recovery_idx = _find_recovery_step(toks, victim)
    if recovery_idx is None:
        return {
            "_no_recovery_observed": True,
            "decode_tbt_p50": _percentile([s for _, s in decode_steps], 0.5),
            "note": (
                f"victim {victim} never disappeared from the stage list — either "
                "the kill never took effect, or this token ran the whole time."
            ),
        }

    pre = [s for i, s in decode_steps if i < recovery_idx]
    recovery_step = next((s for i, s in decode_steps if i == recovery_idx), None)
    post = [s for i, s in decode_steps if i > recovery_idx]

    summary: dict[str, Any] = {
        "ttft_seconds": toks[0]["step_seconds"],
        "recovery_token_idx": recovery_idx,
        "kill_fired_at_token_idx": trial.get("killed_at_token"),
        "tokens_in_flight_during_kill": (
            recovery_idx - (trial.get("killed_at_token") or 0) - 1
            if trial.get("killed_at_token") is not None else None
        ),
        "pre_kill_tbt": {
            "n": len(pre),
            "mean": statistics.fmean(pre) if pre else float("nan"),
            "p50": _percentile(pre, 0.5),
            "p95": _percentile(pre, 0.95),
        },
        "recovery_step_seconds": recovery_step,
        "post_recovery_tbt": {
            "n": len(post),
            "mean": statistics.fmean(post) if post else float("nan"),
            "p50": _percentile(post, 0.5),
            "p95": _percentile(post, 0.95),
        },
    }
    if recovery_step is not None and pre:
        summary["spike_over_pre_p50_seconds"] = recovery_step - _percentile(pre, 0.5)
        summary["spike_factor"] = recovery_step / _percentile(pre, 0.5)

    def _stage_summary(tok: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"device": s["device"], "range": [s["start"], s["end"]],
             "invoke_ms": round(s["invoke_seconds"] * 1000, 2)}
            for s in tok.get("stages", [])
        ]
    if recovery_idx - 1 < len(toks):
        summary["stages_last_pre_recovery"] = _stage_summary(toks[recovery_idx - 1])
    if recovery_idx < len(toks):
        summary["stages_recovery_step"] = _stage_summary(toks[recovery_idx])
    if recovery_idx + 1 < len(toks):
        summary["stages_first_post_recovery"] = _stage_summary(toks[recovery_idx + 1])
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--coord-web", default=_DEFAULT_COORD_WEB,
                   help="coordinator web API host:port (FastAPI SSE)")
    p.add_argument("--coord-host", default=_DEFAULT_COORD_HOST,
                   help="ansible inventory name of coordinator (sidecar fetch)")
    p.add_argument("--victim", required=True,
                   help="ansible inventory name of the worker to kill (e.g. ao-1, on-3)")
    p.add_argument("--prompt", default="The quick brown fox jumps over the lazy dog")
    p.add_argument("--max-tokens", type=int, default=60,
                   help="total tokens to generate (more = better post-recovery sample)")
    p.add_argument("--kill-after-tokens", type=int, default=15,
                   help="kill the worker AFTER this many tokens have been received")
    p.add_argument("--restart-victim", action="store_true",
                   help="restart the worker via systemd after the trial (post-cleanup)")
    p.add_argument("--restart-coord", action="store_true",
                   help="restart the coordinator (clears gateway _dead state + reruns "
                        "auto_schedule) and wait for ready=True. Use this between trials.")
    p.add_argument("--ready-timeout", type=float, default=180.0,
                   help="seconds to wait for coordinator ready after restart")
    p.add_argument("--reset-cluster", action="store_true",
                   help="shorthand: --restart-victim AND --restart-coord (full reset)")
    p.add_argument("--out", default="failure_remote")
    args = p.parse_args()

    if args.kill_after_tokens < 2 or args.kill_after_tokens >= args.max_tokens:
        raise SystemExit("kill_after_tokens must be in [2, max_tokens)")

    log.info("fetching pre-trial scheduler sidecar from %s", args.coord_host)
    sidecar_before = fetch_sidecar(args.coord_host)
    if sidecar_before:
        # Top-level `placement` is a list of {device,start,end}; group by device.
        victim_layers = [
            (s["start"], s["end"]) for s in sidecar_before.get("placement", [])
            if s.get("device") == args.victim
        ]
        if victim_layers:
            log.info("victim %s currently owns layer ranges %s", args.victim, victim_layers)
        else:
            log.warning("victim %s NOT in current placement — kill will have no routing effect", args.victim)
        recovery = sidecar_before.get("recovery", {})
        if args.victim in recovery:
            log.info("victim's backup per R: %s", recovery[args.victim])

    trial = run_trial(
        coord_web=args.coord_web,
        victim=args.victim,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        kill_after_tokens=args.kill_after_tokens,
    )
    summary = summarize(trial)

    log.info("=" * 60)
    if "_empty" in summary or "_no_recovery_observed" in summary:
        log.warning("trial produced no useful breakdown: %s", summary)
    else:
        log.info("TTFT             : %.3fs", summary["ttft_seconds"])
        log.info("kill fired at    : token idx %s",
                 summary.get("kill_fired_at_token_idx"))
        log.info("recovery seen at : token idx %d (%d tokens were in flight)",
                 summary["recovery_token_idx"],
                 summary.get("tokens_in_flight_during_kill") or 0)
        log.info("pre-kill   TBT   : p50=%.3fs p95=%.3fs (n=%d)",
                 summary["pre_kill_tbt"]["p50"],
                 summary["pre_kill_tbt"]["p95"],
                 summary["pre_kill_tbt"]["n"])
        log.info("recovery step    : %.3fs  (spike +%.3fs over pre-p50, %.1fx)",
                 summary["recovery_step_seconds"],
                 summary.get("spike_over_pre_p50_seconds", float("nan")),
                 summary.get("spike_factor", float("nan")))
        log.info("post-rec   TBT   : p50=%.3fs p95=%.3fs (n=%d)",
                 summary["post_recovery_tbt"]["p50"],
                 summary["post_recovery_tbt"]["p95"],
                 summary["post_recovery_tbt"]["n"])
        log.info("tokens emitted   : %d / requested %d",
                 trial["tokens_emitted"], trial["max_tokens_requested"])
    log.info("=" * 60)

    out: dict[str, Any] = {
        "coord_web": args.coord_web,
        "coord_host": args.coord_host,
        "trial": trial,
        "summary": summary,
        "scheduler_before": sidecar_before,
    }
    out_path = RESULTS_DIR / f"{args.out}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    log.info("wrote %s", out_path)

    if args.reset_cluster:
        args.restart_victim = True
        args.restart_coord = True

    cleanup: dict[str, Any] = {}
    if args.restart_victim:
        log.info("restarting victim worker %s via systemd", args.victim)
        dt, ok, _ = start_worker(args.victim)
        log.info("start_worker(%s): ok=%s dt=%.3fs", args.victim, ok, dt)
        cleanup["restart_victim"] = {"ok": ok, "seconds": dt}

    if args.restart_coord:
        log.info("restarting coordinator %s via systemd (clears _dead state)", args.coord_host)
        dt, ok, _ = restart_coordinator(args.coord_host)
        cleanup["restart_coord"] = {"ok": ok, "seconds": dt}
        log.info("restart_coordinator(%s): ok=%s dt=%.3fs", args.coord_host, ok, dt)
        if ok:
            log.info("waiting up to %.0fs for coordinator to come ready...", args.ready_timeout)
            wait_s, ready, final = wait_for_coordinator_ready(
                args.coord_web, timeout_seconds=args.ready_timeout,
            )
            cleanup["wait_for_ready"] = {
                "ok": ready, "seconds": wait_s,
                "final_dead_devices": final.get("dead_devices") if final else None,
            }
            if ready:
                log.info("coordinator ready in %.1fs (no dead devices)", wait_s)
            else:
                log.warning("coordinator NOT ready after %.1fs (last state: %s)",
                            wait_s, final)
    if cleanup:
        # Re-write the output JSON with cleanup info appended (the trial JSON
        # was already saved above, but cleanup status is useful for the log).
        out["cleanup"] = cleanup
        out_path.write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
