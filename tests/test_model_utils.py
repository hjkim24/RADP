"""Unit tests for the architecture-detection helpers in model_utils.

Avoids downloading real HF weights — uses minimal nn.Module fakes that
mimic the attribute paths of OPT / LLaMA / GPT-2.
"""

from __future__ import annotations

import pytest
from torch import nn

from radp.common.model_utils import (
    DTYPE_BYTES,
    estimate_kv_cache_bytes,
    get_transformer_layers,
    layer_param_bytes,
)


def _three_layers() -> nn.ModuleList:
    return nn.ModuleList([nn.Linear(8, 8) for _ in range(3)])


class _OPTLike(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.model = nn.Module()
        self.model.decoder = nn.Module()  # type: ignore[attr-defined]
        self.model.decoder.layers = _three_layers()  # type: ignore[attr-defined]


class _LlamaLike(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.model = nn.Module()
        self.model.layers = _three_layers()  # type: ignore[attr-defined]


class _GPT2Like(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.transformer = nn.Module()
        self.transformer.h = _three_layers()  # type: ignore[attr-defined]


class _Unknown(nn.Module):
    pass


def test_get_transformer_layers_opt_style() -> None:
    layers = get_transformer_layers(_OPTLike())
    assert len(layers) == 3


def test_get_transformer_layers_llama_style() -> None:
    layers = get_transformer_layers(_LlamaLike())
    assert len(layers) == 3


def test_get_transformer_layers_gpt2_style() -> None:
    layers = get_transformer_layers(_GPT2Like())
    assert len(layers) == 3


def test_get_transformer_layers_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Cannot locate transformer-block"):
        get_transformer_layers(_Unknown())


def test_estimate_kv_cache_bytes_formula() -> None:
    # 2 * hidden * seq * dtype = 2 * 512 * 128 * 2 = 262_144
    assert estimate_kv_cache_bytes(512, 128, DTYPE_BYTES["float16"]) == 2 * 512 * 128 * 2


def test_layer_param_bytes_matches_manual_sum() -> None:
    layer = nn.Linear(16, 32)  # 16*32 weights + 32 biases, default float32
    expected = (16 * 32 + 32) * 4
    assert layer_param_bytes(layer) == expected
