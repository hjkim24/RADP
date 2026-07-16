"""B1 — fault-tolerance baseline comparison (spec 2026-07-16).

Drives RADP + four recovery-strategy baselines through one identical
mid-stream worker SIGKILL and reports TTR / correctness / goodput.
See docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass

from experiments._harness import deploy, in_process_cluster
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
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


def _drive_inplace(
    *, name: str, prompt: str, max_tokens: int, kill_after_tokens: int,
    reference: list[int], disable_mirror: bool,
) -> BaselineResult:
    """Manual prefill+decode; kill the interior victim mid-decode; the
    gateway's in-place recovery (mirror replay) fixes the failed step."""
    device_ids, placement, recovery, victim = chain_config()
    with in_process_cluster(device_ids) as (addrs, servers):
        deploy(addrs, placement, model_id=MODEL_ID, recovery=recovery)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL_ID,
        )
        if disable_mirror:
            gw.cache.get_history = lambda *a, **kw: []  # type: ignore[method-assign]
        gw.generate(prompt, max_tokens=2)  # warmup
        rid = gw.new_request_id()
        ttr: float | None = None
        aborted = False
        toks: list[int] = []
        t_start = time.perf_counter()
        try:
            gw._prefill(rid, prompt)
            for step in range(1, max_tokens):
                if step == kill_after_tokens:
                    servers[victim].stop()
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


def run_radp(
    *, prompt: str, max_tokens: int, kill_after_tokens: int, reference: list[int]
) -> BaselineResult:
    return _drive_inplace(
        name="RADP", prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
        disable_mirror=False,
    )
