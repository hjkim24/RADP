"""Phase 2.10: distributed pipeline must work for LLaMA-family models too.

Uses HuggingFaceTB/SmolLM-135M (30-layer LLaMA architecture, ~135M params,
no auth required). Verifies:

  * load_stage_blocks supports the 'llama' model_type (correct weight prefix)
  * The worker computes position_ids from cache length, calls the block with
    position_embeddings derived from a worker-local rotary_emb
  * Distributed greedy generate matches single-process `model.generate(...)`
    token-for-token, just like the OPT integration test does

Marked `slow`: downloads SmolLM-135M (~270MB).
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

MODEL_ID = "HuggingFaceTB/SmolLM-135M"


@pytest.fixture
def two_workers() -> Generator[dict[DeviceId, str], None, None]:
    a = WorkerServer(DeviceId("worker-a"), "127.0.0.1:50131")
    b = WorkerServer(DeviceId("worker-b"), "127.0.0.1:50132")
    a.start()
    b.start()
    try:
        yield {DeviceId("worker-a"): "127.0.0.1:50131", DeviceId("worker-b"): "127.0.0.1:50132"}
    finally:
        a.stop()
        b.stop()


@pytest.mark.slow
def test_llama_distributed_generate_matches_local(
    two_workers: dict[DeviceId, str],
) -> None:
    # SmolLM-135M has 30 transformer layers; split 15-15.
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(15), DeviceId("worker-a")),
        Stage(LayerIdx(16), LayerIdx(30), DeviceId("worker-b")),
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
        max_new_tokens = 6
        distributed = gw.generate(prompt, max_tokens=max_new_tokens)
        assert len(distributed) == max_new_tokens

        ref = load_model(MODEL_ID, torch_device="cpu", dtype="float32")
        inputs = ref.tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            out = ref.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
            )
        ref_new = out[0, inputs["input_ids"].shape[1]:].tolist()

        assert distributed == ref_new, (
            f"distributed={distributed}\nref={ref_new}\n"
            f"distributed_text={ref.tokenizer.decode(distributed)!r}\n"
            f"ref_text       ={ref.tokenizer.decode(ref_new)!r}"
        )
    finally:
        gw.close()
