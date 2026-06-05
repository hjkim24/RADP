"""Verify that load_stage_blocks produces transformer blocks whose weights
exactly match those of the same slice from a full HF model load.

Marked `slow` — downloads OPT-125M safetensors.
"""

from __future__ import annotations

import pytest
import torch

from radp.common.model_utils import (
    get_transformer_layers,
    load_model,
    load_stage_blocks,
)  # noqa: I001
from radp.common.types import LayerIdx


@pytest.mark.slow
def test_sliced_weights_match_full_model() -> None:
    model_id = "facebook/opt-125m"
    start, end = LayerIdx(3), LayerIdx(6)

    full = load_model(model_id, dtype="float32", torch_device="cpu")
    full_layers = list(get_transformer_layers(full.model))[int(start) - 1 : int(end)]

    sliced = load_stage_blocks(model_id, start, end, dtype="float32", torch_device="cpu")
    assert len(sliced) == int(end) - int(start) + 1

    for ref, got in zip(full_layers, sliced):
        ref_state = ref.state_dict()
        got_state = got.state_dict()
        assert set(ref_state.keys()) == set(got_state.keys())
        for k in ref_state:
            assert torch.equal(ref_state[k], got_state[k]), f"mismatch on {k}"


# NOTE: numerical equivalence at the block-call level is exercised end-to-end
# by tests/test_pipeline_integration.py (distributed pipeline output ==
# full-model forward output). The byte-for-byte weight match above is the
# focused unit-level check.
