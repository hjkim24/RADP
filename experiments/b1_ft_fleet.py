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
import contextlib
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import grpc

from experiments._harness import RESULTS_DIR
from experiments.run_e2e_remote import _GRPC_OPTIONS, _bench_one_request
from radp.common.logging_utils import configure_logging, get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc

log = get_logger(__name__)

_DEFAULT_COORD = "115.145.158.253:50050"
_DEFAULT_COORD_HOST = "ax-1"
_DEFAULT_COORD_SSH = "isp@115.145.158.253"
_DEFAULT_SSH_KEY = "~/.ssh/hjkim24-isp"
_INVENTORY = str(Path(__file__).resolve().parent.parent / "deploy" / "inventory.ini")
_ANSIBLE_RETRY_WINDOW = 900.0  # seconds to keep retrying unreachable-host failures


def _fleet_model_id() -> str:
    """Model the fleet is serving, read from deploy/group_vars/all.yml so the
    result JSON records true provenance instead of a hardcoded string."""
    gv = Path(_INVENTORY).parent / "group_vars" / "all.yml"
    for line in gv.read_text().splitlines():
        if line.strip().startswith("model_id:"):
            return line.split(":", 1)[1].split("#")[0].strip().strip('"')
    return "unknown"
_DROPIN = "/etc/systemd/system/radp-coordinator.service.d/recovery.conf"
_PARITY_K_DROPIN = "/etc/systemd/system/radp-coordinator.service.d/parity_k.conf"
_WORKER_DROPIN_DIR = "/etc/systemd/system/radp-worker.service.d"
_WORKER_DROPIN = f"{_WORKER_DROPIN_DIR}/parity.conf"
_PARITY_LOG_MARKER = "PARITY reconstruct:"
_REPLICATE_LOG_MARKER = "REPLICATE reconstruct:"
_RAID6_LOG_MARKER = "RAID-6 reconstruct:"


# ---------------------------------------------------------------------------
# Fleet orchestration helpers (ansible + ssh)
# ---------------------------------------------------------------------------
def _ansible(host: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    # The driver runs across a VPN that flaps for minutes at a time; a
    # connection-level failure is retried (up to _ANSIBLE_RETRY_WINDOW) rather
    # than killing a multi-hour sweep. Genuine module failures raise at once.
    deadline = time.time() + _ANSIBLE_RETRY_WINDOW
    while True:
        try:
            # stdin=DEVNULL: ansible aborts if it inherits a non-blocking fd
            # ("Ansible requires blocking IO"), and a shared terminal fd can be
            # flipped to non-blocking by unrelated processes mid-sweep.
            cp = subprocess.run(
                ["ansible", host, "-i", _INVENTORY, *args],
                capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            cp = None
        if cp is not None and cp.returncode == 0 and "FAILED" not in cp.stdout \
                and "UNREACHABLE" not in cp.stdout:
            return cp
        blob = "" if cp is None else cp.stdout + cp.stderr
        transient = cp is None or "UNREACHABLE" in blob or any(
            s in blob for s in ("Operation timed out", "Connection timed out",
                                "Connection refused", "No route to host",
                                "Failed to connect to the host"))
        if transient and time.time() < deadline:
            log.warning("ansible %s unreachable; retrying in 20 s (%.0fs left in window)",
                        host, deadline - time.time())
            time.sleep(20)
            continue
        detail = "timed out" if cp is None else f"failed:\n{cp.stdout}\n{cp.stderr}"
        raise RuntimeError(f"ansible {host} {args} {detail}")


def set_recovery_mode(coord_host: str, mode: str) -> None:
    """Write the coordinator RADP_RECOVERY_MODE drop-in (applied on next restart)."""
    _ansible(
        coord_host, "-b", "-m", "copy", "-a",
        f"content='[Service]\nEnvironment=RADP_RECOVERY_MODE={mode}\n' dest={_DROPIN}",
    )
    log.info("recovery_mode drop-in set to %s", mode)


def set_parity_k(coord_host: str, k: int) -> None:
    """Write the coordinator RADP_PARITY_K drop-in (applied on next restart).

    A SEPARATE drop-in file from ``_DROPIN`` (recovery.conf), not folded into
    it: ``set_recovery_mode``'s ansible copy fully REPLACES that file's
    content on every call, so writing RADP_PARITY_K there too would stomp
    whichever RADP_RECOVERY_MODE line was written first (or vice versa).
    systemd merges every ``*.conf`` under a ``.service.d`` directory, so a
    second file coexists cleanly — same pattern as the worker's dedicated
    ``_WORKER_DROPIN``."""
    _ansible(
        coord_host, "-b", "-m", "copy", "-a",
        f"content='[Service]\nEnvironment=RADP_PARITY_K={k}\n' dest={_PARITY_K_DROPIN}",
    )
    log.info("parity_k drop-in set to %s", k)


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
    coord_host: str, coord_ssh: str, ssh_key: str, timeout: int = 1200
) -> float:
    # 1200 s: a 7B-class boot re-profiles block-wise (~260 s) and cold-loads
    # 6 primary + 6 backup stages (~6 min). The old 320 s default was sized
    # for OPT-350M and timed out on every OPT-6.7B restart (2026-08-31).
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
    # `timeout` is a budget of REACHABLE waiting: an operator-side network
    # flap makes ssh fail fast (exit 255, empty stdout) with no exception, and
    # on 2026-08-31 twelve such minutes silently ate the whole wall-clock
    # budget while the coordinator had long been ready. Probe attempts that
    # produce neither READY nor WAIT are treated as unreachable and are not
    # charged; a 3x wall-clock cap still bounds the loop.
    budget = float(timeout)
    wall_deadline = time.time() + 3 * timeout
    last_unreach_log = 0.0
    while time.time() < wall_deadline and budget > 0:
        tick = time.time()
        out = ""
        try:
            out = subprocess.run(
                ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-o", "StrictHostKeyChecking=no", coord_ssh, probe],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except (subprocess.TimeoutExpired, OSError):
            pass
        if "READY" in out:
            return time.perf_counter() - t0
        if "WAIT" in out:
            budget -= (time.time() - tick) + 4
        elif time.time() - last_unreach_log > 60:
            log.warning(
                "coordinator host unreachable from the controller; "
                "not charging the readiness budget (%.0fs left)", budget,
            )
            last_unreach_log = time.time()
        time.sleep(4)
    raise TimeoutError(
        f"coordinator not ready (reachable-wait budget {timeout}s / "
        f"wall cap {3 * timeout}s exhausted)"
    )


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
# Reactive-replacement: coordinator web_api reconfigure (no gateway recovery
# mode — R={} means there is no backup to promote, so a crash aborts and the
# ONLY path back is the coordinator re-solving the DP over survivors).
# ---------------------------------------------------------------------------
_COORD_WEB_PORT = 8080


def _coord_web(coord_host: str) -> str:
    host = coord_host.split(":")[0]
    return f"http://{host}:{_COORD_WEB_PORT}"


def reconfigure_over_survivors(coord_host: str, timeout: float = 900.0) -> dict:
    """POST /api/reconfigure — coordinator re-solves over survivors + redeploys.
    Returns the response dict (survivors/excluded/placement)."""
    req = urllib.request.Request(
        _coord_web(coord_host) + "/api/reconfigure", method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_cluster(coord_host: str, timeout: float = 30.0) -> dict:
    """GET /api/cluster → the auto_schedule sidecar (placement, recovery, ...)."""
    req = urllib.request.Request(_coord_web(coord_host) + "/api/cluster")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_placement(coord_host: str, timeout: float = 30.0) -> list[dict]:
    """GET /api/cluster → the currently-deployed placement stages
    ([{device,start,end}, ...])."""
    return fetch_cluster(coord_host, timeout).get("placement", [])


def pick_interior_victim(placement: list[dict]) -> tuple[str, int, int]:
    """Pick a chain-INTERIOR stage (never head, never tail) to crash — returns
    (device, start, end). Head failure has special gateway handling and the
    tail owns sampling; an interior stage is the clean reactive victim. Chosen
    from the LIVE placement because the fleet solve is only quasi-deterministic
    — CPU-worker registration timing shifts stage boundaries between coordinator
    restarts, so a statically-passed victim stage can miss the deployed chain
    (fault never fires)."""
    interior = placement[1:-1] if len(placement) > 2 else placement
    mid = interior[len(interior) // 2]
    return str(mid["device"]), int(mid["start"]), int(mid["end"])


def pick_two_interior_victims(
    placement: list[dict], recovery: dict[str, str] | None = None,
) -> list[tuple[str, int, int]]:
    """Two interior non-head victims for a RAID-6 double-failure trial: exclude
    the head (start_layer == 1) and the LAST stage (no downstream non-head
    survivor → parity gate would fall back).

    When the recovery table R is given, the pair must be RECOVERABLE — neither
    victim's backup may itself be a victim (a dead backup makes the promote
    impossible). Among recoverable pairs, prefer one whose backups land on
    DISTINCT nodes (a shared backup node concentrates 2 promoted stages and
    inflates the intercept — the 350M degenerate-R artifact); if only
    shared-backup pairs exist, take the first and let the run proceed (that
    degeneracy is a property of R, not of this driver). Pairs are scanned in
    start-layer order for determinism. Raises ValueError if fewer than two
    interior stages exist or no recoverable pair exists under R."""
    ordered = sorted(placement, key=lambda s: int(s["start"]))
    interior = [s for s in ordered[:-1] if int(s["start"]) > 1]
    if len(interior) < 2:
        raise ValueError(
            f"need >=2 interior non-head stages for RAID-6, got {len(interior)}"
        )
    as_tuple = [(s["device"], int(s["start"]), int(s["end"])) for s in interior]
    if not recovery:
        return as_tuple[:2]
    recoverable: list[list[tuple[str, int, int]]] = []
    for i in range(len(as_tuple)):
        for j in range(i + 1, len(as_tuple)):
            v1, v2 = as_tuple[i], as_tuple[j]
            b1, b2 = recovery.get(v1[0]), recovery.get(v2[0])
            if b1 in (None, v1[0], v2[0]) or b2 in (None, v1[0], v2[0]):
                continue  # a victim's backup is dead (or missing) → unrecoverable
            recoverable.append([v1, v2])
            if b1 != b2:
                return [v1, v2]  # first distinct-backup pair wins
    if recoverable:
        log.warning("RAID-6 victims %s share a backup node — degenerate R, "
                    "intercept will carry the concentration cost",
                    [v[0] for v in recoverable[0]])
        return recoverable[0]
    raise ValueError(f"no recoverable 2-victim pair under R={recovery}")


def clear_all_failures(coord_host: str, timeout: float = 30.0) -> None:
    """POST /api/clear_all_failures — empty the gateway's ``_dead`` set.

    Called right before marking the victim so the reactive re-solve excludes
    EXACTLY the victim, not also whatever stable worker happened to miss a
    heartbeat in the crash/abort window (the compute-time crash briefly stalls
    the chain, which can flap an unrelated worker's heartbeat). Makes survivors
    deterministically ``all − {victim}`` across every position."""
    req = urllib.request.Request(
        _coord_web(coord_host) + "/api/clear_all_failures", method="POST"
    )
    with contextlib.suppress(urllib.error.HTTPError):
        with urllib.request.urlopen(req, timeout=timeout):
            pass


def mark_device_dead(coord_host: str, device: str, timeout: float = 30.0) -> None:
    """POST /api/inject_failure — put ``device`` into the gateway's ``_dead``
    set so the subsequent /api/reconfigure re-solves over the TRUE survivors.

    The fleet fault is a *compute-time crash*, not a process kill: the victim's
    worker process stays alive and keeps heart-beating, so it never enters
    ``_dead`` on its own (a real failure detector would mark it dead on the
    heartbeat timeout). We do that explicitly here — immediately, so the
    reactive re-placement deterministically excludes the node that crashed
    rather than whichever worker happened to miss a heartbeat. Idempotent:
    a 409 ("already dead") is treated as success."""
    body = json.dumps({"device_id": device}).encode()
    req = urllib.request.Request(
        _coord_web(coord_host) + "/api/inject_failure", method="POST",
        data=body, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except urllib.error.HTTPError as e:
        if e.code != 409:  # 409 == already dead: fine
            raise


def _reconfigured_over_survivors(placement: list, victim_device: str) -> bool:
    """Measurement gate: the post-reconfigure placement must NOT contain the
    victim — proof the reactive re-solve genuinely happened over survivors."""
    return all(stage["device"] != victim_device for stage in placement)


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


def _stream_text_chunks(
    stub: Any, prompt: str, max_tokens: int, *, allow_error: bool = False,
) -> dict[str, Any]:
    """Capture text-token arrival times, retaining partial output on failure."""
    req = radp_pb2.GenerateRequest(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.0,
        top_k=0,
        top_p=1.0,
        eos_token_id=0,
        seed=0,
    )
    sent_at = time.perf_counter()
    texts: list[str] = []
    times: list[float] = []
    error: str | None = None
    try:
        for chunk in stub.Generate(req):
            if chunk.text:
                texts.append(chunk.text)
                times.append(time.perf_counter())
            if chunk.done:
                break
    except Exception as exc:  # noqa: BLE001 - expected for the faulted request
        if not allow_error:
            raise
        error = str(exc)
    return {
        "sent_at": sent_at,
        "completed_at": time.perf_counter(),
        "texts": texts,
        "times": times,
        "error": error,
    }


def _client_recovery_interval(
    failed_texts: list[str], failed_times: list[float],
    replay_texts: list[str], replay_times: list[float],
) -> tuple[float, int]:
    """Return last pre-failure token -> first new post-replay token wall time."""
    if not failed_texts or len(failed_texts) != len(failed_times):
        raise ValueError("faulted request produced no timestamped prefix")
    prefix_tokens = len(failed_texts)
    if replay_texts[:prefix_tokens] != failed_texts:
        raise ValueError("replayed prefix differs from the client-visible prefix")
    if prefix_tokens >= len(replay_texts) or prefix_tokens >= len(replay_times):
        raise ValueError("replay did not produce a new post-recovery token")
    return replay_times[prefix_tokens] - failed_times[-1], prefix_tokens


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


def run_reactive_replacement_trial(
    stub_factory: Any, *, position: int, prompt: str, max_tokens: int,
    victim_host: str, victim_stage: tuple[int, int], victim_device: str,
    coord: str, coord_host: str, coord_ssh: str, ssh_key: str,
) -> dict[str, Any]:
    """One reactive-replacement measurement at failure position P.

    The coordinator MUST be deployed in the R={} regime (backup_placement=
    False) for this line, so the crash aborts (no backup to promote) and
    /api/reconfigure is the only way back. TTR is the client-observed interval
    from the last token emitted before the crash to the first new valid token
    after replay catches up with that emitted prefix.

    This is the fleet analog of the in-process ``run_reactive_replacement``
    baseline (see ``experiments/b1_ft_baselines.py``): reset -> timed healthy
    reference -> arm+crash (aborts) -> re-solve over survivors -> replay from
    0 -> ttr = replay_wall - reference_wall. It reuses ``run_trial``'s own
    plumbing (``restart_coordinator_and_wait``, ``arm_fault``, ``fault_fired``,
    ``_bench_one_request``) rather than gRPC/gateway recovery — the whole
    point of this path is that there IS no gateway recovery to dispatch.

    Unlike ``run_trial``, this trial takes its OWN fresh healthy reference
    (not the sweep-level one) because after this trial's reconfigure the
    chain topology permanently drops the victim; only the restart at the top
    of the NEXT trial restores the full healthy chain (same "victim never
    really died" reset semantics ``run_trial`` already relies on).
    """
    # 1. Restart the coordinator (fresh, all-workers plan) + a timed healthy
    # reference request.
    reset_wall = restart_coordinator_and_wait(coord_host, coord_ssh, ssh_key)
    ref = _bench_one_request(stub_factory(), prompt, max_tokens=max_tokens)
    reference_wall = ref["total_seconds"]
    reference_text = ref["decoded_text"]

    # Pick the victim from the LIVE placement this trial's restart just solved,
    # so the armed crash matches the actually-deployed chain (see
    # ``pick_interior_victim`` — the fleet solve is only quasi-deterministic).
    # On this fleet device_id == ansible host alias, so victim_device doubles as
    # the arm/mark target. The statically-passed victim_* args are ignored here.
    placement0 = fetch_placement(coord)
    victim_device, vstart, vend = pick_interior_victim(placement0)
    victim_host = victim_device

    # 2. Arm the crash at `position`, then fire the request. With R={} there
    # is no backup to promote, so the gateway's chain-failure path raises
    # straight out of the stream — the request aborts. That IS the expected
    # outcome, not an error in the harness.
    arm_fault(victim_host, vstart, vend, position)
    failed = _stream_text_chunks(
        stub_factory(), prompt, max_tokens, allow_error=True,
    )
    fired = fault_fired(victim_host)

    # 3. Coordinator re-solves the DP over survivors and redeploys.
    # 4. Replay the SAME request from 0 on the reconfigured chain.
    # Both steps are guarded: transient failures (HTTP 409, network timeout)
    # mark the trial INVALID rather than aborting the whole sweep.
    try:
        # The compute-time crash left the victim heart-beating, so mark it dead
        # explicitly (what a heartbeat-timeout detector would do) BEFORE the
        # re-solve, so /api/reconfigure excludes the node that actually crashed.
        # Clear first so ONLY the victim is excluded (the crash can flap an
        # unrelated worker's heartbeat) → survivors = all − {victim}.
        clear_all_failures(coord)
        mark_device_dead(coord, victim_device)
        resp = reconfigure_over_survivors(coord)
        replay = _stream_text_chunks(stub_factory(), prompt, max_tokens)

        ttr, prefix_tokens = _client_recovery_interval(
            failed["texts"], failed["times"], replay["texts"], replay["times"],
        )
        replay_text = "".join(replay["texts"])
        seq_match = replay_text == reference_text
        reconfigured = _reconfigured_over_survivors(resp["placement"], victim_device)

        row = {
            "mode": "reactive_replacement",
            "position": position,
            "ttr_seconds": ttr,
            "metric": "client_observed_recovery_interval",
            "pre_failure_tokens": prefix_tokens,
            "first_new_token_index": prefix_tokens,
            "failed_request_aborted": failed["error"] is not None,
            "fault_to_abort_seconds": failed["completed_at"] - failed["times"][-1],
            "replay_catchup_seconds": replay["times"][prefix_tokens] - replay["sent_at"],
            "sequence_match": seq_match,
            "reconfigured": reconfigured,
            "fired": fired,
            "reset_wall_seconds": reset_wall,
            "reference_wall_seconds": reference_wall,
            "text_tokens": len(replay["texts"]),
            "decoded_text": replay_text,
            "survivors": resp.get("survivors"),
            "excluded": resp.get("excluded"),
            "placement": resp.get("placement"),
        }
        valid = fired and failed["error"] is not None and seq_match and reconfigured
        log.info(
            "%-11s P=%-2d  TTR=%.3fs  fired=%s seq_match=%s reconfigured=%s  %s",
            "reactive", position, ttr, fired, seq_match, reconfigured,
            "OK" if valid else "!! INVALID",
        )
    except Exception as e:
        # Transient failure on reconfigure or replay: mark trial invalid, don't
        # abort the sweep. Downstream fit-gate (which checks `reconfigured`)
        # will exclude this row.
        row = {
            "mode": "reactive_replacement",
            "position": position,
            "ttr_seconds": None,
            "metric": "client_observed_recovery_interval",
            "sequence_match": False,
            "reconfigured": False,
            "fired": fired,
            "reset_wall_seconds": reset_wall,
            "reference_wall_seconds": reference_wall,
            "text_tokens": None,
            "decoded_text": None,
            "survivors": None,
            "excluded": None,
            "placement": None,
            "error": str(e),
        }
        log.warning(
            "%-11s P=%-2d  FAILED (reconfigure/replay): %s",
            "reactive", position, e,
        )
    return row


def run_raid6_trial(
    stub_factory: Any, *, position: int, prompt: str, max_tokens: int,
    reference: str | None, coord: str, coord_host: str, coord_ssh: str,
    ssh_key: str,
) -> dict[str, Any]:
    """RAID-6 (k=2) double-victim measurement at failure position P.

    Structural model is ``run_reactive_replacement_trial``: fetch the LIVE
    placement after this trial's OWN restart (the fleet solve is only
    quasi-deterministic, so a statically-passed victim can miss the deployed
    chain — see that function's docstring) and pick the victims from it via
    ``pick_two_interior_victims``. Recovery itself, though, is gateway-side
    zero-forward reconstruction exactly like ``run_trial``'s "parity" mode
    (not a coordinator DP re-solve), so TTR is read from the per-step tbt
    array the same way ``run_trial`` does — NOT a whole-request wall delta
    like reactive_replacement's.

    Both victims are armed to compute-crash at the SAME position, but the
    chain relay is synchronous (``chain_mode: sync``), so only the first one
    hit on the wire ever raises a live exception — the other's RunStage is
    never invoked and its fault file never fires. That's fine: both are ALSO
    explicitly marked dead via ``mark_device_dead`` (/api/inject_failure)
    before the request. That call only updates the gateway's ``self._dead``
    bookkeeping and rebuilds its cached execution plan — it does NOT rewire
    the physical chain (workers keep forwarding to whatever ``_rewire_chain``
    last told them, and that's only invoked from inside a recovery function
    itself), so the real crash still fires on the wire exactly as armed. When
    the gateway attributes that crash, it finds BOTH victims already in
    ``self._dead`` and its RAID-6 branch dispatches to
    ``_recover_parity_double`` (see gateway.py's ``_recover_parity``, the
    "RAID-6 (k=2)" check) instead of the single-victim ladder. ``clear_all_
    failures`` runs first so a heartbeat flap elsewhere can't inflate the
    dead-set past 2 and trip the ">2 dead non-head stages" surgical fallback.
    """
    reset_wall = restart_coordinator_and_wait(coord_host, coord_ssh, ssh_key)
    cluster = fetch_cluster(coord)
    (v1_dev, v1s, v1e), (v2_dev, v2s, v2e) = pick_two_interior_victims(
        cluster.get("placement", []), cluster.get("recovery"))

    clear_all_failures(coord)
    mark_device_dead(coord, v1_dev)
    mark_device_dead(coord, v2_dev)
    arm_fault(v1_dev, v1s, v1e, position)
    arm_fault(v2_dev, v2s, v2e, position)

    stub = stub_factory()
    rec = _bench_one_request(stub, prompt, max_tokens=max_tokens)

    v1_fired = fault_fired(v1_dev)
    v2_fired = fault_fired(v2_dev)
    fired = v1_fired or v2_fired  # only the upstream-hit victim ever fires
    tbt = rec["tbt_seconds_each"]
    expected_idx = position - 1
    ttr = tbt[expected_idx] if 0 <= expected_idx < len(tbt) else float("nan")
    peak = max(tbt) if tbt else float("nan")
    peak_idx = tbt.index(peak) if tbt else -1
    median_tbt = statistics.median(tbt) if tbt else float("nan")
    recovery_visible = bool(tbt) and ttr > 1.3 * median_tbt
    seq_match = (reference is None) or (rec["decoded_text"] == reference)

    # Same log-marker gate as parity/replicate in `run_trial`: proof the
    # gateway actually took the RAID-6 double-reconstruct path rather than
    # silently laddering to surgical.
    coord_log = fetch_coordinator_log(coord_ssh, ssh_key)
    raid6_branch_log = next(
        (line for line in coord_log.splitlines() if _RAID6_LOG_MARKER in line),
        None,
    )
    raid6_branch_ran = raid6_branch_log is not None

    row = {
        "mode": "raid6",
        "position": position,
        "ttr_seconds": ttr,
        "ttr_step_index": expected_idx,
        "expected_step_index": expected_idx,
        "median_tbt_seconds": median_tbt,
        "ttr_over_median": (ttr / median_tbt) if median_tbt else float("nan"),
        "peak_seconds": peak,
        "peak_step_index": peak_idx,
        "peak_is_recovery": peak_idx == expected_idx,
        "victim1_device": v1_dev,
        "victim2_device": v2_dev,
        "victim1_fired": v1_fired,
        "victim2_fired": v2_fired,
        "fired": fired,
        "recovery_visible": recovery_visible,
        "sequence_match": seq_match,
        "raid6_branch_ran": raid6_branch_ran,
        "raid6_branch_log": raid6_branch_log,
        "text_tokens": rec["text_tokens"],
        "reset_wall_seconds": reset_wall,
        "tbt_seconds_each": [round(x, 4) for x in tbt],
        "decoded_text": rec["decoded_text"],
    }
    valid = fired and recovery_visible and seq_match and raid6_branch_ran
    log.info(
        "%-11s P=%-2d  TTR=%.3fs (%.1fx median, step %d)  v1_fired=%s v2_fired=%s "
        "seq_match=%s raid6_branch=%s%s  %s",
        "raid6", position, ttr, (ttr / median_tbt) if median_tbt else float("nan"),
        expected_idx, v1_fired, v2_fired, seq_match, raid6_branch_ran,
        "" if raid6_branch_ran else " (FELL BACK TO SURGICAL)",
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

    # Parity, replicate AND raid6 need the workers shipping KV columns for
    # the ENTIRE sweep, not just their own trials — all three gate on the
    # SAME RADP_PARITY drop-in (see `set_worker_replication`; raid6 is just
    # parity recovery with k=2), so arm it once up front, before any
    # coordinator reschedule (including the healthy-reference one below), so
    # it's never racing a trial. Not auto-disabled at the end: cleanup is a
    # separate, explicit restore step.
    if "parity" in modes or "replicate" in modes or "raid6" in modes:
        set_worker_parity(True)

    # Healthy reference (no fault armed): the plan is fresh after the restart
    # inside the first mode's first trial anyway, but we want the reference in
    # full_replay-neutral state, so schedule once and capture it.
    set_recovery_mode(coord_host, "full_replay")
    restart_coordinator_and_wait(coord_host, coord_ssh, ssh_key)
    ref = _bench_one_request(stub_factory(), prompt, max_tokens=max_tokens)
    reference = ref["decoded_text"]
    log.info("reference (%d tok): %r", ref["text_tokens"], reference)

    # reactive_replacement drives the coordinator over its web_api instead of
    # the gateway's recovery_mode dispatch (there IS no recovery — R={} means
    # no backup to promote), so it must NEVER get a `set_recovery_mode` write:
    # that env var selects among surgical/parity/replicate branches that this
    # path does not use. device_id == ansible host alias in this fleet's
    # inventory.ini (see deploy/inventory.ini), so the victim's placement
    # "device" string is `victim_host` itself.
    # ponytail: assumes device_id == ansible alias; add a --victim-device
    # flag if a fleet ever diverges the two.
    victim_device = victim_host

    trials: list[dict[str, Any]] = []
    for mode in modes:
        if mode != "reactive_replacement":
            # raid6 is gateway "parity" recovery with k=2 — "raid6" itself is
            # a driver-level mode name, not a valid RADP_RECOVERY_MODE value
            # (the gateway only knows full_replay/surgical/parity/replicate).
            # parity_k is reset EVERY mode (not just raid6) so a previous
            # raid6 run's k=2 drop-in can never silently leak into a later
            # single-victim parity/replicate measurement in the same or a
            # subsequent sweep.
            set_recovery_mode(coord_host, "parity" if mode == "raid6" else mode)
            set_parity_k(coord_host, 2 if mode == "raid6" else 1)
        for p in positions:
            def _dispatch() -> dict[str, Any]:
                if mode == "reactive_replacement":
                    return run_reactive_replacement_trial(
                        stub_factory, position=p, prompt=prompt,
                        max_tokens=max_tokens, victim_host=victim_host,
                        victim_stage=victim_stage, victim_device=victim_device,
                        coord=coord, coord_host=coord_host,
                        coord_ssh=coord_ssh, ssh_key=ssh_key,
                    )
                if mode == "raid6":
                    return run_raid6_trial(
                        stub_factory, position=p, prompt=prompt,
                        max_tokens=max_tokens, reference=reference,
                        coord=coord, coord_host=coord_host,
                        coord_ssh=coord_ssh, ssh_key=ssh_key,
                    )
                return run_trial(
                    stub_factory, mode=mode, position=p, prompt=prompt,
                    max_tokens=max_tokens, victim_host=victim_host,
                    victim_stage=victim_stage, reference=reference,
                    coord_host=coord_host, coord_ssh=coord_ssh, ssh_key=ssh_key,
                )

            # A trial lost to a VPN flap gets one retry, then is recorded as
            # an error row (fired=False keeps it out of the fits) so the sweep
            # finishes and writes its JSON instead of dying mid-run.
            for attempt in (1, 2):
                try:
                    trials.append(_dispatch())
                    break
                except (RuntimeError, TimeoutError, OSError, grpc.RpcError) as exc:
                    log.warning("trial mode=%s P=%d attempt %d/2 failed: %s",
                                mode, p, attempt, exc)
                    if attempt == 2:
                        trials.append({"mode": mode, "position": p,
                                       "fired": False, "error": str(exc)})
                    else:
                        time.sleep(120)

    # Linear fits over VALID trials only. For "parity" / "replicate" / "raid6",
    # validity additionally requires the real (non-surgical-fallback) branch
    # to have actually fired — a trial that silently fell back to surgical
    # must NOT contaminate that mode's fit. "reactive_replacement" rows carry
    # no tbt-derived "recovery_visible", so they get their own
    # mutually-exclusive branch, gated on `reconfigured` the exact way
    # parity/replicate/raid6 gate on their own branch-ran flags. Its TTR is now
    # the same client-visible token interval as the recovery-step rows.
    fits: dict[str, Any] = {}
    for mode in modes:
        if mode == "reactive_replacement":
            pts = [(t["position"], t["ttr_seconds"]) for t in trials
                   if t["mode"] == mode and t["fired"] and t["sequence_match"]
                   and t["reconfigured"] and t.get("failed_request_aborted")]
        else:
            pts = [(t["position"], t["ttr_seconds"]) for t in trials
                   if t["mode"] == mode and t["fired"] and t["recovery_visible"] and t["sequence_match"]
                   and (mode != "parity" or t["parity_branch_ran"])
                   and (mode != "replicate" or t["replicate_branch_ran"])
                   and (mode != "raid6" or t["raid6_branch_ran"])]
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
            "coord": coord, "model": _fleet_model_id(), "chain_mode": "sync",
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
    p.add_argument(
        "--modes", default="full_replay,surgical",
        help="comma-separated: full_replay,surgical,parity,replicate,raid6,"
             "reactive_replacement. reactive_replacement drives the "
             "coordinator's /api/reconfigure over HTTP (no gateway recovery "
             "mode) and REQUIRES the coordinator already deployed R={} "
             "(backup_placement=False) — a separate controller-gated step. "
             "raid6 is gateway parity recovery with RADP_PARITY_K=2 and a "
             "double-victim crash (see `run_raid6_trial`) — the --victim-* "
             "flags are ignored for it (victims are picked live, two per "
             "trial, via `pick_two_interior_victims`), same as "
             "reactive_replacement ignores them for its own live pick.",
    )
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--max-tokens", type=int, default=0,
                   help="0 = max(positions)+4")
    p.add_argument("--out", default=None,
                   help="output file stem (default: b1_ft_fleet_reactive if "
                        "reactive_replacement is in --modes, else b1_ft_fleet)")
    args = p.parse_args()

    positions = [int(x) for x in args.positions.split(",") if x.strip()]
    max_tokens = args.max_tokens or (max(positions) + 4)
    modes = [m for m in args.modes.split(",") if m]
    out_name = args.out or (
        "b1_ft_fleet_reactive" if "reactive_replacement" in modes else "b1_ft_fleet"
    )
    run(
        coord=args.coord, coord_host=args.coord_host, coord_ssh=args.coord_ssh,
        ssh_key=str(Path(args.ssh_key).expanduser()),
        victim_host=args.victim_host,
        victim_stage=(args.victim_start, args.victim_end),
        positions=positions, modes=modes,
        prompt=args.prompt, max_tokens=max_tokens, out_name=out_name,
    )


if __name__ == "__main__":
    main()
