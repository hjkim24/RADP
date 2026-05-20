"""End-to-end Phase 2.8: N parallel ``generate`` calls through the SAME
RequestGateway must each return identical token sequences to the single-
threaded baseline. Proves:

  - request_id allocation is race-free
  - per-request KV cache on workers stays isolated
  - shared PyTorch modules (embed, lm_head) are concurrent-safe for inference
  - persistent gRPC channels handle concurrent RPCs correctly

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

import pytest

from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer

MODEL_ID = "facebook/opt-125m"


@pytest.fixture
def two_workers() -> Generator[dict[DeviceId, str], None, None]:
    servers = {
        DeviceId("worker-a"): WorkerServer(DeviceId("worker-a"), "127.0.0.1:50111"),
        DeviceId("worker-b"): WorkerServer(DeviceId("worker-b"), "127.0.0.1:50112"),
    }
    for s in servers.values():
        s.start()
    try:
        yield {dev: s.bind_address for dev, s in servers.items()}
    finally:
        for s in servers.values():
            s.stop()


@pytest.mark.slow
def test_concurrent_generates_match_baseline(two_workers: dict[DeviceId, str]) -> None:
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("worker-a")),
        Stage(LayerIdx(7), LayerIdx(12), DeviceId("worker-b")),
    ]
    for stage in placement:
        with WorkerClient(two_workers[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=MODEL_ID,
            )

    gw = RequestGateway(
        placement=placement, recovery={},
        worker_addresses=two_workers, model_id=MODEL_ID,
    )
    try:
        prompt = "The quick brown fox"
        max_tokens = 6
        baseline = gw.generate(prompt, max_tokens=max_tokens)

        n_concurrent = 8
        with ThreadPoolExecutor(max_workers=n_concurrent) as pool:
            futures = [
                pool.submit(gw.generate, prompt, max_tokens)
                for _ in range(n_concurrent)
            ]
            results = [f.result(timeout=120) for f in futures]
        for i, r in enumerate(results):
            assert r == baseline, (
                f"concurrent run {i} diverged from baseline:\n"
                f"  got:      {r}\n  baseline: {baseline}"
            )
    finally:
        gw.close()
