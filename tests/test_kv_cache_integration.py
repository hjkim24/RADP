"""End-to-end Phase 2.6: distributed autoregressive generate must match the
single-model greedy `model.generate()` token-for-token.

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
import torch

from radp.common.model_utils import load_model
from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer


@pytest.fixture
def two_workers() -> Generator[dict[DeviceId, str], None, None]:
    a = WorkerServer(DeviceId("worker-a"), "127.0.0.1:50081")
    b = WorkerServer(DeviceId("worker-b"), "127.0.0.1:50082")
    a.start()
    b.start()
    try:
        yield {DeviceId("worker-a"): "127.0.0.1:50081", DeviceId("worker-b"): "127.0.0.1:50082"}
    finally:
        a.stop()
        b.stop()


@pytest.mark.slow
def test_distributed_generate_matches_local(two_workers: dict[DeviceId, str]) -> None:
    model_id = "facebook/opt-125m"
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
    max_new_tokens = 8

    # Distributed autoregressive generate.
    distributed = gateway.generate(prompt, max_tokens=max_new_tokens)
    assert len(distributed) == max_new_tokens

    # Reference: greedy decoding on the full local model.
    ref = load_model(model_id, torch_device="cpu", dtype="float32")
    inputs = ref.tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        out = ref.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            num_beams=1,
        )
    ref_new = out[0, inputs["input_ids"].shape[1]:].tolist()

    assert distributed == ref_new, (
        f"distributed={distributed}\nref={ref_new}\n"
        f"distributed_text={ref.tokenizer.decode(distributed)!r}\n"
        f"ref_text       ={ref.tokenizer.decode(ref_new)!r}"
    )
