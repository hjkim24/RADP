"""End-to-end Phase 2.9: sampling + EOS behavior over the live pipeline.

  * Greedy (temperature=0) produces deterministic output (regression check).
  * Sampling (temperature>0) with the same seed produces identical tokens
    across two runs (seed reproducibility).
  * Sampling with different seeds produces different tokens (probabilistic
    but very unlikely to coincide for 8 tokens).
  * EOS-aware stopping: forcing the very first generated token to be the
    EOS id stops generation immediately.

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer

MODEL_ID = "facebook/opt-125m"


@pytest.fixture
def two_workers() -> Generator[dict[DeviceId, str], None, None]:
    a = WorkerServer(DeviceId("worker-a"), "127.0.0.1:50121")
    b = WorkerServer(DeviceId("worker-b"), "127.0.0.1:50122")
    a.start()
    b.start()
    try:
        yield {DeviceId("worker-a"): "127.0.0.1:50121", DeviceId("worker-b"): "127.0.0.1:50122"}
    finally:
        a.stop()
        b.stop()


def _placement() -> Placement:
    return [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("worker-a")),
        Stage(LayerIdx(7), LayerIdx(12), DeviceId("worker-b")),
    ]


def _deploy(addrs: dict[DeviceId, str]) -> None:
    for stage in _placement():
        with WorkerClient(addrs[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=MODEL_ID,
            )


@pytest.mark.slow
def test_greedy_is_deterministic(two_workers: dict[DeviceId, str]) -> None:
    _deploy(two_workers)
    gw = RequestGateway(
        placement=_placement(), recovery={},
        worker_addresses=two_workers, model_id=MODEL_ID,
    )
    try:
        a = gw.generate("The quick brown fox", max_tokens=6)
        b = gw.generate("The quick brown fox", max_tokens=6)
        assert a == b
    finally:
        gw.close()


@pytest.mark.slow
def test_sampling_seed_reproducible(two_workers: dict[DeviceId, str]) -> None:
    _deploy(two_workers)
    gw = RequestGateway(
        placement=_placement(), recovery={},
        worker_addresses=two_workers, model_id=MODEL_ID,
    )
    try:
        a = gw.generate("The quick brown fox", max_tokens=8, temperature=1.0, top_p=0.9, seed=42)
        b = gw.generate("The quick brown fox", max_tokens=8, temperature=1.0, top_p=0.9, seed=42)
        assert a == b
        c = gw.generate("The quick brown fox", max_tokens=8, temperature=1.0, top_p=0.9, seed=99)
        # Astronomically unlikely to collide for 8 tokens with different seeds.
        assert c != a
    finally:
        gw.close()


@pytest.mark.slow
def test_sampling_differs_from_greedy(two_workers: dict[DeviceId, str]) -> None:
    _deploy(two_workers)
    gw = RequestGateway(
        placement=_placement(), recovery={},
        worker_addresses=two_workers, model_id=MODEL_ID,
    )
    try:
        greedy = gw.generate("The quick brown fox", max_tokens=10)
        sampled = gw.generate(
            "The quick brown fox", max_tokens=10, temperature=1.5, top_k=50, seed=7,
        )
        # Same prompt + high-temperature sampling should diverge from greedy at
        # least somewhere (otherwise the test isn't actually exercising sampling).
        assert sampled != greedy
    finally:
        gw.close()


@pytest.mark.slow
def test_eos_token_id_stops_generation_immediately(
    two_workers: dict[DeviceId, str],
) -> None:
    """With max_tokens=10 but the very first generated token forced to be the
    EOS id, the result should be exactly [eos_id]."""
    _deploy(two_workers)
    gw = RequestGateway(
        placement=_placement(), recovery={},
        worker_addresses=two_workers, model_id=MODEL_ID,
    )
    try:
        # Whatever greedy emits as the first token — pass it as `eos_token_id`.
        baseline = gw.generate("The quick brown fox", max_tokens=10)
        first_tok = baseline[0]
        early = gw.generate(
            "The quick brown fox", max_tokens=10, eos_token_id=first_tok,
        )
        assert early == [first_tok]
    finally:
        gw.close()
