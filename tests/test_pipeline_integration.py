"""End-to-end correctness: distributed pipeline output must match
a single full-model forward of OPT-125M.

Spawns two in-process gRPC worker servers on localhost, deploys layers 1-6
to worker A and 7-12 to worker B, then compares logits to the reference
(model.forward) output.

Marked `slow` — downloads OPT-125M (~250MB) on first run.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
import torch

from radp.common.model_utils import load_model
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer


@pytest.fixture
def two_workers() -> Generator[dict[DeviceId, str], None, None]:
    a = WorkerServer(DeviceId("worker-a"), "127.0.0.1:50061")
    b = WorkerServer(DeviceId("worker-b"), "127.0.0.1:50062")
    a.start()
    b.start()
    try:
        yield {DeviceId("worker-a"): "127.0.0.1:50061", DeviceId("worker-b"): "127.0.0.1:50062"}
    finally:
        a.stop()
        b.stop()


@pytest.mark.slow
def test_pipeline_matches_full_model(two_workers: dict[DeviceId, str]) -> None:
    model_id = "facebook/opt-125m"
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("worker-a")),
        Stage(LayerIdx(7), LayerIdx(12), DeviceId("worker-b")),
    ]

    # Deploy stages by directly invoking the runner via gRPC clients (mirrors
    # what CoordinatorServer.deploy does).
    from radp.common.protocol import WorkerClient
    for stage in placement:
        with WorkerClient(two_workers[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=model_id,
            )

    gateway = RequestGateway(
        placement=placement,
        recovery={},
        worker_addresses=two_workers,
        model_id=model_id,
        torch_device="cpu",
        dtype="float32",
    )

    prompt = "The quick brown fox"
    pipeline_logits = gateway.prefill(prompt)

    # Reference: same model, single-process full forward.
    ref = load_model(model_id, torch_device="cpu", dtype="float32")
    inputs = ref.tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        ref_logits = ref.model(**inputs).logits

    assert pipeline_logits.shape == ref_logits.shape
    # Numerical tolerance: float32 + many ops, allow modest drift.
    assert torch.allclose(pipeline_logits, ref_logits, atol=5e-4, rtol=1e-4), (
        f"max abs diff = {(pipeline_logits - ref_logits).abs().max().item():.3e}"
    )
