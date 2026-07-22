"""B1 — fault-tolerance baseline comparison (spec 2026-07-16).

Drives RADP + four recovery-strategy baselines through one identical
mid-stream worker SIGKILL and reports TTR / correctness / goodput.
See docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import time
import types
from dataclasses import asdict, dataclass

from experiments._harness import (
    deploy,
    greedy_placement,
    in_process_cluster,
    in_process_cluster_with_mirror,
    wire_chain,
    write_json,
)
from radp.common.types import (
    DeviceId,
    DeviceProfile,
    LayerIdx,
    Placement,
    RecoveryTable,
    Stage,
)
from radp.coordinator.gateway import RequestGateway

MODEL_ID = "facebook/opt-125m"


@dataclass
class BaselineResult:
    name: str
    ttr_seconds: float | None          # None => never recovered (abort)
    tokens_completed: int
    tokens_requested: int
    sequence_matches_reference: bool
    goodput_tok_per_s: float
    aborted: bool


def chain_config() -> tuple[list[str], Placement, RecoveryTable, DeviceId]:
    """3-worker chain with an interior victim (worker-b)."""
    device_ids = ["worker-a", "worker-b", "worker-c"]
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
    return device_ids, placement, recovery, DeviceId("worker-b")


def generate_reference(*, prompt: str, max_tokens: int) -> tuple[list[int], float]:
    """Healthy-cluster run: the correct token sequence + wall-clock baseline."""
    device_ids, placement, recovery, _ = chain_config()
    with in_process_cluster(device_ids) as (addrs, _servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        gw.generate(prompt, max_tokens=2)  # warmup
        t0 = time.perf_counter()
        toks = gw.generate(prompt, max_tokens=max_tokens)
        wall = time.perf_counter() - t0
        gw.close()
    return list(toks), wall


def generate_wired_reference(*, prompt: str, max_tokens: int) -> list[int]:
    """Healthy-cluster run on the SAME topology the crash-injection lines
    use (mirror-wired coordinator + ``wire_chain``-ed workers), so the
    reference is directly comparable token-for-token. ``generate_reference``
    above uses the plain head-only ``in_process_cluster`` (no
    ``wire_chain``), which silently runs only the first stage — see
    ``experiments._harness.wire_chain``'s docstring — so it is not a valid
    reference for the in-place recovery lines.
    """
    toks, _wall = _generate_wired_reference_impl(prompt=prompt, max_tokens=max_tokens)
    return toks


def generate_wired_reference_wall(
    *, prompt: str, max_tokens: int
) -> tuple[list[int], float]:
    """Like :func:`generate_wired_reference`, but also returns the
    healthy-cluster wall-clock — the ``reference_wall`` the cold-restart
    line's TTR is measured against (see ``run_b1_cold_restart``)."""
    return _generate_wired_reference_impl(prompt=prompt, max_tokens=max_tokens)


def _generate_wired_reference_impl(
    *, prompt: str, max_tokens: int
) -> tuple[list[int], float]:
    device_ids, placement, recovery, _ = chain_config()
    with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup
        t0 = time.perf_counter()
        toks = list(gw.generate(prompt, max_tokens=max_tokens))
        wall = time.perf_counter() - t0
        gw.close()
    return toks, wall


def _inject_mid_stage_crash(gw, victim_server, victim_runner, *, dead_key, at_position):
    """Monkeypatch ``victim_runner.run`` for a deterministic mid-forward
    crash at decode position ``at_position``.

    Generalizes the prototype fault in
    ``tests/test_surgical_recovery.py::test_surgical_recovery_exercises_live_position_rebuild``:
    the worker servicer already fire-and-forgets a mirror push of its
    incoming activation to the coordinator BEFORE calling
    ``StageRunner.run`` (see ``radp/worker/server.py``'s ``RunStage``), so
    intercepting ``run`` itself is always strictly after that mirror send.
    We count calls for ``dead_key`` (this stage's own ``(start, end)`` —
    call 1 is prefill / position 0, call k is decode position k-1), and on
    the call matching ``at_position`` we poll
    ``gw.cache.get_history(request_id, dead_key)`` until the mirror for
    that position has actually landed, THEN raise — guaranteeing the
    coordinator has history[at_position] so recovery can take its real
    surgical/full-replay path instead of the async-mirror-lag fallback.

    Returns a ``tripped`` object; ``tripped.fired`` is True once the fault
    has actually raised (assert this — a fault that never fires means the
    "recovery" that follows measured nothing).
    """
    orig_run = victim_runner.run
    tripped = types.SimpleNamespace(fired=False)
    calls = {"n": 0}

    def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
        if (int(start), int(end)) == dead_key:
            calls["n"] += 1
            if calls["n"] - 1 == at_position and not tripped.fired:
                tripped.fired = True
                deadline = time.time() + 5.0
                while (
                    len(gw.cache.get_history(request_id, dead_key)) <= at_position
                    and time.time() < deadline
                ):
                    time.sleep(0.01)
                raise RuntimeError(
                    f"simulated {victim_server.device_id} mid-stage crash "
                    f"after mirror (position={at_position})"
                )
        return orig_run(
            request_id, activation_blob, start=start, end=end, is_prefill=is_prefill
        )

    victim_runner.run = flaky_run
    return tripped


def _drive_inplace_crash(
    *, name: str, recovery_mode: str, prompt: str, max_tokens: int,
    kill_after_tokens: int, reference: list[int],
) -> BaselineResult:
    """Mirror+wire_chain cluster; drive one request through prefill+decode;
    inject a mid-stage crash on the interior victim at ``kill_after_tokens``
    (after its mirror for that position has landed); the gateway's in-place
    recovery (``recovery_mode``) fixes the failed decode step in place.
    ``ttr_seconds`` is that single failed step's wall-clock.

    ``recovery_mode in {"parity", "replicate"}`` needs the worker to ship KV
    columns to the coordinator (see ``radp/worker/server.py``'s
    ``_maybe_push_parity_kv``), gated on the ``RADP_PARITY`` env var — the
    same gate both modes share (no separate env var). It's set only for the
    duration of this call and restored after, so it doesn't change the
    other lines' (surgical / full-replay) timing.
    """
    device_ids, placement, recovery, victim = chain_config()
    dead_key = next(
        (int(s.start_layer), int(s.end_layer)) for s in placement if s.device == victim
    )
    needs_parity_gate = recovery_mode in ("parity", "replicate")
    old_parity = os.environ.get("RADP_PARITY")
    if needs_parity_gate:
        os.environ["RADP_PARITY"] = "1"
    try:
        with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
            deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
            wire_chain(addrs, placement)
            gw = RequestGateway(
                placement=placement, recovery=recovery,
                worker_addresses=addrs, model_id=MODEL_ID,
                recovery_mode=recovery_mode,
            )
            attach(gw)
            gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

            rid = gw.new_request_id()
            tripped = _inject_mid_stage_crash(
                gw, servers[victim], servers[victim].runner,
                dead_key=dead_key, at_position=kill_after_tokens,
            )

            ttr: float | None = None
            aborted = False
            toks: list[int] = []
            t_start = time.perf_counter()
            try:
                gw._prefill(rid, prompt)
                for step in range(1, max_tokens):
                    t0 = time.perf_counter()
                    gw._decode_step(rid)
                    dt = time.perf_counter() - t0
                    if step == kill_after_tokens:
                        ttr = dt
                toks = list(gw._requests[rid].generated_token_ids)
            except Exception:
                aborted = True
                with contextlib.suppress(Exception):
                    toks = list(gw._requests[rid].generated_token_ids)
            finally:
                with contextlib.suppress(Exception):
                    gw._evict_everywhere(rid)
            total = time.perf_counter() - t_start
            gw.close()
    finally:
        if needs_parity_gate:
            if old_parity is None:
                os.environ.pop("RADP_PARITY", None)
            else:
                os.environ["RADP_PARITY"] = old_parity

    assert tripped.fired, (
        f"{name}: injected mid-stage crash on {victim} never fired "
        f"(dead_key={dead_key}, at_position={kill_after_tokens}) — "
        "recovery measured nothing"
    )

    completed = len(toks)
    goodput = completed / total if total > 0 else 0.0
    return BaselineResult(
        name=name,
        ttr_seconds=None if aborted else ttr,
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=goodput,
        aborted=aborted,
    )


def run_radp_surgical(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace_crash(
        name="RADP-surgical", recovery_mode="surgical",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )


def run_radp_full_replay(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace_crash(
        name="RADP-full-replay", recovery_mode="full_replay",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )


def run_radp_replicate(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace_crash(
        name="RADP-replicate", recovery_mode="replicate",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )


def run_b0_abort(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    """No backup deployed (``recovery={}``). The SAME mid-stage crash on
    worker-b makes ``mark_dead`` raise ``NoRecoveryError`` (no backup entry
    to substitute) inside the gateway's chain-failure recovery, which
    propagates straight out of ``generate_streaming`` — the stream aborts
    with whatever tokens were already produced.
    """
    device_ids, placement, _recovery, victim = chain_config()
    dead_key = next(
        (int(s.start_layer), int(s.end_layer)) for s in placement if s.device == victim
    )
    with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery={})
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery={},
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        tripped = _inject_mid_stage_crash(
            gw, servers[victim], servers[victim].runner,
            dead_key=dead_key, at_position=kill_after_tokens,
        )

        toks: list[int] = []
        t_start = time.perf_counter()
        try:
            for tok in gw.generate_streaming(prompt, max_tokens=max_tokens):
                toks.append(tok.token_id)
        except Exception:
            pass  # no recovery table -> abort is the expected outcome
        total = time.perf_counter() - t_start
        gw.close()

    assert tripped.fired, (
        f"B0-abort: injected mid-stage crash on {victim} never fired "
        f"(dead_key={dead_key}, at_position={kill_after_tokens}) — "
        "abort measured nothing"
    )

    completed = len(toks)
    goodput = completed / total if total > 0 else 0.0
    return BaselineResult(
        name="B0-abort",
        ttr_seconds=None,
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=goodput,
        aborted=True,
    )


def resolve_excluding(dead: DeviceId, survivors: list[DeviceId]) -> Placement:
    """Cold-restart's re-solve step: contiguous, equal-weight re-split of
    all layers over ``survivors`` only (``dead`` dropped entirely) via the
    same ``greedy_placement`` PETALS-style heuristic used elsewhere in this
    harness. No per-device throughput profile is available in this
    in-process test harness, so every survivor gets weight 1.0.
    """
    assert dead not in survivors, f"dead device {dead!r} must not be a survivor"
    _device_ids, original_placement, _recovery, _victim = chain_config()
    num_layers = max(int(s.end_layer) for s in original_placement)
    devices = [
        DeviceProfile(
            id=DeviceId(d), total_memory_bytes=4_000_000_000, compute_throughput=1.0
        )
        for d in survivors
    ]
    return greedy_placement(devices, num_layers)


def run_b1_cold_restart(
    *, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], reference_wall: float,
) -> BaselineResult:
    """Cold-restart baseline: no in-place recovery. On the SAME mid-stage
    crash, the first attempt aborts exactly like ``run_b0_abort``. Recovery
    then re-solves a placement over the survivors, redeploys the model on
    them, wires a fresh chain, and re-runs generation from scratch on a
    brand-new ``RequestGateway`` (full model reload included — that IS the
    cold-restart cost). ``ttr_seconds`` is the whole restart's wall-clock
    minus the healthy-cluster ``reference_wall``, per the TTR taxonomy.
    """
    device_ids, placement, _recovery, victim = chain_config()
    dead_key = next(
        (int(s.start_layer), int(s.end_layer)) for s in placement if s.device == victim
    )
    with in_process_cluster_with_mirror(device_ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL_ID, recovery={})
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery={},
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        tripped = _inject_mid_stage_crash(
            gw, servers[victim], servers[victim].runner,
            dead_key=dead_key, at_position=kill_after_tokens,
        )

        t_start = time.perf_counter()
        with contextlib.suppress(Exception):
            for _tok in gw.generate_streaming(prompt, max_tokens=max_tokens):
                pass
        gw.close()

        survivors = [d for d in device_ids if d != victim]
        new_plan = resolve_excluding(victim, survivors)
        surv_addrs = {d: addrs[d] for d in survivors}
        deploy(surv_addrs, new_plan, model_id=MODEL_ID, recovery={})
        wire_chain(surv_addrs, new_plan)
        gw2 = RequestGateway(
            placement=new_plan, recovery={},
            worker_addresses=surv_addrs, model_id=MODEL_ID,
        )
        attach(gw2)
        toks = list(gw2.generate(prompt, max_tokens=max_tokens))
        total = time.perf_counter() - t_start
        gw2.close()

    assert tripped.fired, (
        f"B1-cold-restart: injected mid-stage crash on {victim} never fired "
        f"(dead_key={dead_key}, at_position={kill_after_tokens}) — "
        "restart measured nothing"
    )

    completed = len(toks)
    goodput = completed / total if total > 0 else 0.0
    return BaselineResult(
        name="B1-cold-restart",
        ttr_seconds=total - reference_wall,
        tokens_completed=completed,
        tokens_requested=max_tokens,
        sequence_matches_reference=(toks == reference),
        goodput_tok_per_s=goodput,
        aborted=False,
    )


def run_all(*, prompt: str, max_tokens: int, kill_after_tokens: int) -> dict:
    """Generate the wired reference ONCE (tokens + wall), then run all four
    lines under that SAME reference and the same mid-stage-crash injection.
    Returns a JSON-serializable comparison record.
    """
    reference, reference_wall = generate_wired_reference_wall(
        prompt=prompt, max_tokens=max_tokens
    )
    lines = [
        run_radp_surgical(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens, reference=reference,
        ),
        run_radp_full_replay(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens, reference=reference,
        ),
        run_radp_replicate(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens, reference=reference,
        ),
        run_b1_cold_restart(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens, reference=reference,
            reference_wall=reference_wall,
        ),
        run_b0_abort(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after_tokens, reference=reference,
        ),
    ]
    return {
        "model_id": MODEL_ID,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "kill_after_tokens": kill_after_tokens,
        "reference_wall_seconds": reference_wall,
        "lines": [asdict(line) for line in lines],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default="The quick brown fox")
    p.add_argument("--max-tokens", type=int, default=12)
    p.add_argument("--kill-after-tokens", type=int, default=4)
    p.add_argument("--out", default="b1_ft_baselines")
    args = p.parse_args()

    rec = run_all(
        prompt=args.prompt, max_tokens=args.max_tokens,
        kill_after_tokens=args.kill_after_tokens,
    )
    path = write_json(args.out, rec)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
