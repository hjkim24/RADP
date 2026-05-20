"""Phase B2 end-to-end: load a real sharded HF model via load_stage_blocks
and verify byte-for-byte weight equivalence vs. full-model load.

Uses HuggingFaceTB/SmolLM-1.7B (2-shard safetensors, ~3.4GB total, LLaMA
architecture). Downloads only the shards needed for the requested layer
range — for a small slice this is meaningfully less than the full model.

Marked `slow`. First run downloads multiple GB.
"""

from __future__ import annotations

import pytest
import torch

from radp.common.model_utils import (
    _find_weights_location,
    get_transformer_layers,
    load_model,
    load_stage_blocks,
)
from radp.common.types import LayerIdx

MODEL_ID = "HuggingFaceTB/SmolLM-1.7B"


@pytest.mark.slow
def test_sharded_index_detected() -> None:
    loc = _find_weights_location(MODEL_ID)
    assert loc.fmt == "safetensors_sharded"
    assert loc.weight_map is not None
    # SmolLM-1.7B publishes 2 shards.
    shard_files = set(loc.weight_map.values())
    assert len(shard_files) >= 2
    # All weight_map values should be valid filenames.
    for f in shard_files:
        assert f.endswith(".safetensors")


@pytest.mark.slow
def test_sharded_load_stage_blocks_matches_full_model() -> None:
    """Loading a layer range from sharded weights must produce identical
    parameters to slicing the same range out of a fully-loaded model."""
    start, end = LayerIdx(5), LayerIdx(8)

    sliced = load_stage_blocks(MODEL_ID, start, end, dtype="float32", torch_device="cpu")

    full = load_model(MODEL_ID, dtype="float32", torch_device="cpu")
    full_layers = list(get_transformer_layers(full.model))[int(start) - 1 : int(end)]

    assert len(sliced) == len(full_layers)
    for ref, got in zip(full_layers, sliced, strict=True):
        ref_state = ref.state_dict()
        got_state = got.state_dict()
        assert set(ref_state.keys()) == set(got_state.keys())
        for k in ref_state:
            assert torch.equal(ref_state[k], got_state[k]), f"mismatch on {k}"
