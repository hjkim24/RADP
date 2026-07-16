"""B1 — fault-tolerance baseline comparison (spec 2026-07-16).

Drives RADP + four recovery-strategy baselines through one identical
mid-stream worker SIGKILL and reports TTR / correctness / goodput.
See docs/superpowers/specs/2026-07-16-b1-ft-baselines-design.md.
"""
from __future__ import annotations

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
