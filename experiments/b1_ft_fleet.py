"""Live-fleet TTR(P) sweep for surgical vs full-replay recovery.

The fleet analog of the in-process ``experiments.b1_ft_baselines`` sweep. It
drives the REAL coordinator (default ax-1) over the deployed OPT-350M chain and,
for each failure depth P and each recovery mode, injects a *compute-time* crash
on one chain-interior worker at decode position P, then measures the recovery
step's wall clock (TTR) and checks the recovered sequence against a healthy
reference.

Injection = the worker-side fault hook committed alongside this file
(``RADP_FAULT_INJECTION`` + ``/tmp/radp_fault.json``): the victim raises AFTER
its position-P input-mirror push has landed at the coord, steering recovery
into the surgical branch deterministically. This is NOT a SIGKILL — see the
spec §10 fault-model note.

IMPORTANT setup the operator must have already applied (see the session log /
REPORT):
  * every worker started with RADP_FAULT_INJECTION=1 (systemd drop-in), so the
    hook is live;
  * coordinator running with ``chain_mode: sync`` — in async mode an interior
    compute-time crash is only caught by the 30 s per-request timeout and then
    mis-attributed to the head, which swamps the recovery signal.
The driver sets ``RADP_RECOVERY_MODE`` per mode itself (coordinator drop-in +
restart).

Between trials the coordinator is restarted to reset the plan to healthy (the
victim is only logically dead — its process never died — so a fresh schedule
un-marks it and restores it as primary).

Writes experiments/results/<out>.json.
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
from experiments.run_e2e_remote import _GRPC_OPTIONS, _bench_one_request
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.proto import radp_pb2_grpc

log = get_logger(__name__)

_DEFAULT_COORD = "115.145.158.253:50050"
_DEFAULT_COORD_HOST = "ax-1"
_DEFAULT_COORD_SSH = "isp@115.145.158.253"
_DEFAULT_SSH_KEY = "~/.ssh/hjkim24-isp"
_INVENTORY = str(Path(__file__).resolve().parent.parent / "deploy" / "inventory.ini")
_DROPIN = "/etc/systemd/system/radp-coordinator.service.d/recovery.conf"
_WORKER_DROPIN_DIR = "/etc/systemd/system/radp-worker.service.d"
_WORKER_DROPIN = f"{_WORKER_DROPIN_DIR}/parity.conf"
_PARITY_LOG_MARKER = "PARITY reconstruct:"
_REPLICATE_LOG_MARKER = "REPLICATE reconstruct:"


# ---------------------------------------------------------------------------
# Fleet orchestration helpers (ansible + ssh)
# ---------------------------------------------------------------------------
def _ansible(host: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        ["ansible", host, "-i", _INVENTORY, *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if cp.returncode != 0 or "FAILED" in cp.stdout or "UNREACHABLE" in cp.stdout:
        raise RuntimeError(f"ansible {host} {args} failed:\n{cp.stdout}\n{cp.stderr}")
    return cp


def set_recovery_mode(coord_host: str, mode: str) -> None:
    """Write the coordinator RADP_RECOVERY_MODE drop-in (applied on next restart)."""
    _ansible(
        coord_host, "-b", "-m", "copy", "-a",
        f"content='[Service]\nEnvironment=RADP_RECOVERY_MODE={mode}\n' dest={_DROPIN}",
    )
    log.info("recovery_mode drop-in set to %s", mode)


def set_worker_parity(on: bool) -> None:
    """Write/remove the worker RADP_PARITY=1 systemd drop-in on ALL workers
    and restart them. Unlike the per-trial coordinator recovery-mode
    drop-in, this must be armed ONCE up front (before any trial) since
    parity needs the workers shipping KV columns for the whole sweep."""
    if on:
        _ansible("workers", "-b", "-m", "file", "-a",
                 f"path={_WORKER_DROPIN_DIR} state=directory")
        _ansible(
            "workers", "-b", "-m", "copy", "-a",
            f"content='[Service]\nEnvironment=RADP_PARITY=1\n' dest={_WORKER_DROPIN}",
        )
    else:
        _ansible("workers", "-b", "-m", "file", "-a",
                 f"path={_WORKER_DROPIN} state=absent")
    _ansible(
        "workers", "-b", "-m", "systemd", "-a",
        "name=radp-worker state=restarted daemon_reload=yes",
    )
    log.info("worker RADP_PARITY drop-in %s", "armed" if on else "removed")


def set_worker_replication(on: bool) -> None:
    """Replicate reuses the same worker KV-ship gate as parity — the worker
    does not know the coordinator's storage mode (it ships KV columns
    whenever RADP_PARITY=1 regardless of whether the coordinator then keeps
    them as a parity XOR or a full replica). Alias for clarity at call sites."""
    set_worker_parity(on)


def restart_coordinator_and_wait(
    coord_host: str, coord_ssh: str, ssh_key: str, timeout: int = 320
) -> float:
    """Restart the coordinator (daemon-reload picks up the drop-in) and block
    until it has re-scheduled and is serving. Returns wall seconds waited."""
    _ansible(
        coord_host, "-b", "-m", "systemd", "-a",
        "name=radp-coordinator state=restarted daemon_reload=yes",
    )
    t0 = time.perf_counter()
    # Poll the coordinator's own log for the end-of-schedule marker, keyed on
    # the just-set ActiveEnterTimestamp so we never match a previous cycle.
    probe = (
        'START=$(systemctl show radp-coordinator -p ActiveEnterTimestamp --value); '
        'journalctl -u radp-coordinator --no-pager --since "$START" 2>/dev/null '
        '| grep -q "freed decoder.layers" && echo READY || echo WAIT'
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = subprocess.run(
            ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=no", coord_ssh, probe],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if "READY" in out:
            return time.perf_counter() - t0
        time.sleep(4)
    raise TimeoutError(f"coordinator not ready within {timeout}s after restart")


def arm_fault(victim_host: str, start: int, end: int, position: int) -> None:
    _ansible(
        victim_host, "-m", "copy", "-a",
        f'content={{"start":{start},"end":{end},"position":{position}}}\n '
        f"dest=/tmp/radp_fault.json",
    )


def fault_fired(victim_host: str) -> bool:
    """The hook removes the file when it fires — absence == fired."""
    cp = _ansible(victim_host, "-m", "stat", "-a", "path=/tmp/radp_fault.json")
    return '"exists": false' in cp.stdout


def fetch_coordinator_log(coord_ssh: str, ssh_key: str) -> str:
    """Fetch the coordinator's journal since its last restart. Every trial
    (see ``run_trial``) restarts the coordinator before its one request, so
    "since last restart" == "since this trial started". Reuses the exact
    ssh invocation style from ``restart_coordinator_and_wait``."""
    probe = (
        'START=$(systemctl show radp-coordinator -p ActiveEnterTimestamp --value); '
        'journalctl -u radp-coordinator --no-pager --since "$START" 2>/dev/null'
    )
    cp = subprocess.run(
        ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         "-o", "StrictHostKeyChecking=no", coord_ssh, probe],
        capture_output=True, text=True, timeout=30,
    )
    return cp.stdout


def _parity_branch_ran(log_text: str) -> bool:
    """True iff the gateway's real zero-forward parity path fired.

    ``gateway._recover_parity`` ladders to ``_recover_surgical`` on every
    "can't trust parity" gate (dead stage is head, no survivors, FetchKV
    failure, geometry mismatch, incomplete parity cache, missing mirrored
    input) and only reaches the XOR-reconstruct itself past all of them —
    at which point it logs exactly one ``log.warning`` containing this
    marker (see gateway.py's ``_recover_parity``, the "PARITY reconstruct:"
    line). Its absence means the trial silently fell back to surgical.
    Pure string predicate — no SSH — so it's unit-testable directly.
    """
    return _PARITY_LOG_MARKER in log_text


def _replicate_branch_ran(log_text: str) -> bool:
    """True iff the gateway's real replicate (full-KV-copy) path fired,
    exact mirror of ``_parity_branch_ran``: ``gateway._recover_replicate``
    ladders to ``_recover_surgical`` on the same "can't trust" gates and
    only reaches the replica-copy itself past all of them, at which point
    it logs exactly one ``log.warning`` containing this marker (see
    gateway.py's ``_recover_replicate``, the "REPLICATE reconstruct:"
    line). Its absence means the trial silently fell back to surgical.
    Pure string predicate — no SSH — so it's unit-testable directly.
    """
    return _REPLICATE_LOG_MARKER in log_text


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------
def _linfit(xs: list[float], ys: list[float]) -> dict[str, float]:
    """Ordinary least squares y = intercept + slope * x."""
    n = len(xs)
    if n < 2:
        return {"intercept": float("nan"), "slope": float("nan")}
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return {"intercept": float("nan"), "slope": float("nan")}
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return {"intercept": intercept, "slope": slope}


def run_trial(
    stub_factory: Any, *, mode: str, position: int, prompt: str, max_tokens: int,
    victim_host: str, victim_stage: tuple[int, int], reference: str | None,
    coord_host: str, coord_ssh: str, ssh_key: str,
) -> dict[str, Any]:
    """Reset → arm at `position` → one request → extract recovery-step TTR."""
    reset_wall = restart_coordinator_and_wait(coord_host, coord_ssh, ssh_key)
    arm_fault(victim_host, victim_stage[0], victim_stage[1], position)

    stub = stub_factory()
    rec = _bench_one_request(stub, prompt, max_tokens=max_tokens)

    fired = fault_fired(victim_host)
    tbt = rec["tbt_seconds_each"]
    # The crash lands when the victim processes decode `position`, so the
    # recovery cost IS the step at per-step index position-1 (prefill = 0).
    # Read it there rather than taking max(tbt): we control where the fault
    # fires, and once recovery gets cheap (parity ~2x a normal step) an
    # unrelated jitter spike elsewhere in the stream can exceed the real
    # recovery step and silently mis-measure it. `peak_*` is kept as a
    # diagnostic so such cases stay visible.
    expected_idx = position - 1
    ttr = tbt[expected_idx] if 0 <= expected_idx < len(tbt) else float("nan")
    peak = max(tbt) if tbt else float("nan")
    peak_idx = tbt.index(peak) if tbt else -1
    median_tbt = statistics.median(tbt) if tbt else float("nan")
    # Sanity: the recovery step must stand out from a normal decode step.
    # (Replaces the old "peak lands at expected index" gate, which fails for
    # a fast recovery even when that recovery was perfectly correct.)
    recovery_visible = bool(tbt) and ttr > 1.3 * median_tbt
    seq_match = (reference is None) or (rec["decoded_text"] == reference)

    # Parity-only: verify the gateway actually took the zero-forward XOR
    # path rather than silently falling back to surgical (see
    # `_parity_branch_ran`). Never checked for full_replay/surgical trials.
    parity_branch_ran: bool | None = None
    parity_branch_log: str | None = None
    if mode == "parity":
        coord_log = fetch_coordinator_log(coord_ssh, ssh_key)
        parity_branch_log = next(
            (line for line in coord_log.splitlines() if _PARITY_LOG_MARKER in line),
            None,
        )
        parity_branch_ran = parity_branch_log is not None

    # Replicate-only: exact mirror of the parity gate above — verify the
    # gateway actually took the full-replica-copy path rather than silently
    # falling back to surgical (see `_replicate_branch_ran`). Never checked
    # for full_replay/surgical/parity trials.
    replicate_branch_ran: bool | None = None
    replicate_branch_log: str | None = None
    if mode == "replicate":
        coord_log = fetch_coordinator_log(coord_ssh, ssh_key)
        replicate_branch_log = next(
            (line for line in coord_log.splitlines() if _REPLICATE_LOG_MARKER in line),
            None,
        )
        replicate_branch_ran = replicate_branch_log is not None

    row = {
        "mode": mode,
        "position": position,
        "ttr_seconds": ttr,
        "ttr_step_index": expected_idx,
        "expected_step_index": expected_idx,
        "median_tbt_seconds": median_tbt,
        "ttr_over_median": (ttr / median_tbt) if median_tbt else float("nan"),
        # Diagnostics: where the largest step actually landed. peak_is_recovery
        # False just means an unrelated jitter spike beat a cheap recovery —
        # informational, not a validity gate.
        "peak_seconds": peak,
        "peak_step_index": peak_idx,
        "peak_is_recovery": peak_idx == expected_idx,
        "fired": fired,
        "recovery_visible": recovery_visible,
        "sequence_match": seq_match,
        "parity_branch_ran": parity_branch_ran,
        "parity_branch_log": parity_branch_log,
        "replicate_branch_ran": replicate_branch_ran,
        "replicate_branch_log": replicate_branch_log,
        "text_tokens": rec["text_tokens"],
        "reset_wall_seconds": reset_wall,
        "tbt_seconds_each": [round(x, 4) for x in tbt],
        "decoded_text": rec["decoded_text"],
    }
    valid = fired and recovery_visible and seq_match
    note = ""
    if mode == "parity":
        valid = valid and bool(parity_branch_ran)
        note = "  parity_branch=%s%s" % (
            parity_branch_ran,
            "" if parity_branch_ran else " (FELL BACK TO SURGICAL)",
        )
    elif mode == "replicate":
        valid = valid and bool(replicate_branch_ran)
        note = "  replicate_branch=%s%s" % (
            replicate_branch_ran,
            "" if replicate_branch_ran else " (FELL BACK TO SURGICAL)",
        )
    log.info(
        "%-11s P=%-2d  TTR=%.3fs (%.1fx median, step %d)  fired=%s seq_match=%s%s  %s",
        mode, position, ttr, (ttr / median_tbt) if median_tbt else float("nan"),
        expected_idx, fired, seq_match, note,
        "OK" if valid else "!! INVALID",
    )
    return row


def run(
    *, coord: str, coord_host: str, coord_ssh: str, ssh_key: str,
    victim_host: str, victim_stage: tuple[int, int], positions: list[int],
    modes: list[str], prompt: str, max_tokens: int, out_name: str,
) -> dict[str, Any]:
    def stub_factory() -> Any:
        ch = grpc.insecure_channel(coord, options=_GRPC_OPTIONS)
        return radp_pb2_grpc.CoordinatorServiceStub(ch)

    # Parity AND replicate need the workers shipping KV columns for the
    # ENTIRE sweep, not just their own trials — both gate on the SAME
    # RADP_PARITY drop-in (see `set_worker_replication`), so arm it once up
    # front, before any coordinator reschedule (including the
    # healthy-reference one below), so it's never racing a trial. Not
    # auto-disabled at the end: cleanup is a separate, explicit restore step.
    if "parity" in modes or "replicate" in modes:
        set_worker_parity(True)

    # Healthy reference (no fault armed): the plan is fresh after the restart
    # inside the first mode's first trial anyway, but we want the reference in
    # full_replay-neutral state, so schedule once and capture it.
    set_recovery_mode(coord_host, "full_replay")
    restart_coordinator_and_wait(coord_host, coord_ssh, ssh_key)
    ref = _bench_one_request(stub_factory(), prompt, max_tokens=max_tokens)
    reference = ref["decoded_text"]
    log.info("reference (%d tok): %r", ref["text_tokens"], reference)

    trials: list[dict[str, Any]] = []
    for mode in modes:
        set_recovery_mode(coord_host, mode)
        for p in positions:
            trials.append(run_trial(
                stub_factory, mode=mode, position=p, prompt=prompt,
                max_tokens=max_tokens, victim_host=victim_host,
                victim_stage=victim_stage, reference=reference,
                coord_host=coord_host, coord_ssh=coord_ssh, ssh_key=ssh_key,
            ))

    # Linear fits over VALID trials only. For "parity" / "replicate",
    # validity additionally requires the real (non-surgical-fallback) branch
    # to have actually fired — a trial that silently fell back to surgical
    # must NOT contaminate that mode's fit.
    fits: dict[str, Any] = {}
    for mode in modes:
        pts = [(t["position"], t["ttr_seconds"]) for t in trials
               if t["mode"] == mode and t["fired"] and t["recovery_visible"] and t["sequence_match"]
               and (mode != "parity" or t["parity_branch_ran"])
               and (mode != "replicate" or t["replicate_branch_ran"])]
        if len(pts) >= 2:
            f = _linfit([p for p, _ in pts], [y for _, y in pts])
            fits[mode] = {**f, "n_points": len(pts)}
            log.info("[fit] %-11s TTR(P) = %.1fms + %.2fms * P  (n=%d)",
                     mode, f["intercept"] * 1e3, f["slope"] * 1e3, len(pts))
        else:
            fits[mode] = {"intercept": float("nan"), "slope": float("nan"),
                          "n_points": len(pts)}

    summary = {
        "config": {
            "coord": coord, "model": "facebook/opt-350m", "chain_mode": "sync",
            "victim_host": victim_host, "victim_stage": list(victim_stage),
            "positions": positions, "modes": modes, "max_tokens": max_tokens,
            "prompt": prompt,
        },
        "reference": {"text": reference, "tokens": ref["text_tokens"]},
        "trials": trials,
        "fits": fits,
    }
    out_path = RESULTS_DIR / f"{out_name}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    log.info("wrote %s", out_path)
    return summary


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coord", default=_DEFAULT_COORD)
    p.add_argument("--coord-host", default=_DEFAULT_COORD_HOST)
    p.add_argument("--coord-ssh", default=_DEFAULT_COORD_SSH)
    p.add_argument("--ssh-key", default=_DEFAULT_SSH_KEY)
    p.add_argument("--victim-host", default="on-1")
    p.add_argument("--victim-start", type=int, default=16)
    p.add_argument("--victim-end", type=int, default=17)
    p.add_argument("--positions", default="4,8,16,24,32",
                   help="comma-separated failure depths P")
    p.add_argument("--modes", default="full_replay,surgical")
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--max-tokens", type=int, default=0,
                   help="0 = max(positions)+4")
    p.add_argument("--out", default="b1_ft_fleet")
    args = p.parse_args()

    positions = [int(x) for x in args.positions.split(",") if x.strip()]
    max_tokens = args.max_tokens or (max(positions) + 4)
    run(
        coord=args.coord, coord_host=args.coord_host, coord_ssh=args.coord_ssh,
        ssh_key=str(Path(args.ssh_key).expanduser()),
        victim_host=args.victim_host,
        victim_stage=(args.victim_start, args.victim_end),
        positions=positions, modes=[m for m in args.modes.split(",") if m],
        prompt=args.prompt, max_tokens=max_tokens, out_name=args.out,
    )


if __name__ == "__main__":
    main()
