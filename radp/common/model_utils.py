"""HuggingFace model loading + layer-range slicing helpers.

Centralizes the architecture-specific knowledge of where transformer blocks
live in different model families (OPT, LLaMA, GPT-2, etc.) so the rest of
the codebase can treat any HF causal LM uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn
from transformers import AutoModelForCausalLM, AutoTokenizer

from radp.common.types import LayerIdx

DTYPE_MAP: dict[str, torch.dtype] = {
    "float32": torch.float32,
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
}

DTYPE_BYTES: dict[str, int] = {
    "float32": 4,
    "float16": 2,
    "bfloat16": 2,
}


@dataclass
class ModelHandle:
    """A loaded HF causal LM ready for inference or per-layer profiling."""

    model: Any
    tokenizer: Any
    model_id: str
    num_layers: int
    hidden_size: int
    torch_device: str
    dtype: str


def load_model(
    model_id: str,
    *,
    dtype: str = "float32",
    torch_device: str = "cpu",
) -> ModelHandle:
    """Load a HF causal LM in eval mode on the requested device."""
    if dtype not in DTYPE_MAP:
        raise ValueError(f"Unsupported dtype {dtype!r}; choose from {sorted(DTYPE_MAP)}")

    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=DTYPE_MAP[dtype])
    model.to(torch_device)  # type: ignore[arg-type]
    model.eval()  # type: ignore[no-untyped-call]
    tokenizer = AutoTokenizer.from_pretrained(model_id)

    config = model.config
    return ModelHandle(
        model=model,
        tokenizer=tokenizer,
        model_id=model_id,
        num_layers=int(config.num_hidden_layers),
        hidden_size=int(config.hidden_size),
        torch_device=torch_device,
        dtype=dtype,
    )


def get_transformer_layers(model: Any) -> nn.ModuleList:
    """Return the ModuleList containing the transformer blocks.

    Supports the common HF causal-LM architectures:
      - OPT:           model.model.decoder.layers
      - LLaMA / Mistral: model.model.layers
      - GPT-2:         model.transformer.h
    """
    if hasattr(model, "model"):
        inner = model.model
        if hasattr(inner, "decoder") and hasattr(inner.decoder, "layers"):
            return inner.decoder.layers  # type: ignore[no-any-return]
        if hasattr(inner, "layers"):
            return inner.layers  # type: ignore[no-any-return]
    if hasattr(model, "transformer") and hasattr(model.transformer, "h"):
        return model.transformer.h  # type: ignore[no-any-return]
    raise ValueError(
        f"Cannot locate transformer-block ModuleList in model of type {type(model).__name__}. "
        "Add a new branch to get_transformer_layers() for this architecture."
    )


def slice_stage(handle: ModelHandle, start: LayerIdx, end: LayerIdx) -> nn.ModuleList:
    """Return the transformer blocks for layers [start, end] (1-based inclusive)."""
    if start < 1 or end > handle.num_layers or start > end:
        raise ValueError(
            f"Invalid stage [{start}, {end}] for model with {handle.num_layers} layers"
        )
    layers = get_transformer_layers(handle.model)
    return nn.ModuleList(list(layers)[int(start) - 1 : int(end)])


def estimate_kv_cache_bytes(hidden_size: int, max_seq_length: int, dtype_bytes: int) -> int:
    """KV cache footprint per layer for ``max_seq_length`` tokens.

    Per layer:  K and V each are [seq, hidden]  ->  2 * hidden * seq * dtype_bytes.
    """
    return 2 * hidden_size * max_seq_length * dtype_bytes


def layer_param_bytes(layer: nn.Module) -> int:
    """Sum of parameter storage bytes for one transformer block."""
    total = 0
    for param in layer.parameters():
        total += int(param.numel()) * int(param.element_size())
    return total
