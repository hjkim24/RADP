"""HuggingFace model loading + layer-range slicing helpers.

Two loading paths:
  * ``load_model``        — coordinator-side: full HF causal LM (needs
                            embedding + lm_head + optional pre/post norms).
  * ``load_stage_blocks`` — worker-side (Phase 2.5): allocates ONLY the
                            requested transformer blocks and streams their
                            weights from safetensors. Memory cost scales
                            with stage size, not full model size.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import torch
from torch import nn
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

from radp.common.logging_utils import get_logger
from radp.common.types import LayerIdx

log = get_logger(__name__)

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


# ---------------------------------------------------------------------------
# Phase 2.5: per-stage weight loading (no full-model resident in RAM)
# ---------------------------------------------------------------------------
def measure_resident_bytes() -> int:
    """Resident set size of the current process (bytes)."""
    return int(psutil.Process().memory_info().rss)


def _find_weights_file(model_id: str) -> tuple[Path, str]:
    """Locate the single-file model weights in the local HF cache (download if
    needed). Returns ``(path, format)`` where format is 'safetensors' or 'bin'.

    Sharded weights are not yet supported.
    """
    from huggingface_hub import hf_hub_download
    errors: list[str] = []
    for filename, fmt in [
        ("model.safetensors", "safetensors"),
        ("pytorch_model.bin", "bin"),
    ]:
        try:
            return Path(hf_hub_download(model_id, filename)), fmt
        except Exception as e:  # noqa: BLE001
            errors.append(f"{filename}: {e}")
    raise NotImplementedError(
        f"Phase 2.5 requires a single 'model.safetensors' or 'pytorch_model.bin' "
        f"for {model_id}. Sharded weights are not yet supported. "
        f"Errors:\n  " + "\n  ".join(errors)
    )


class _WeightReader:
    """Tiny wrapper that exposes a uniform (keys / get_tensor / close) API
    over either safetensors mmap or a fully-loaded ``torch.load`` state dict.
    The safetensors path is the memory-efficient one; bin is a fallback."""

    def __init__(self, path: Path, fmt: str, torch_device: str) -> None:
        self.fmt = fmt
        self._st: Any = None
        self._state: dict[str, torch.Tensor] | None = None
        if fmt == "safetensors":
            from safetensors import safe_open  # local import keeps surface small
            handle: Any = safe_open(  # type: ignore[no-untyped-call]
                str(path), framework="pt", device=torch_device
            )
            handle.__enter__()
            self._st = handle
        elif fmt == "bin":
            self._state = torch.load(str(path), map_location=torch_device, weights_only=True)
        else:
            raise ValueError(f"Unsupported weights format: {fmt}")

    def keys(self) -> set[str]:
        if self._st is not None:
            return set(self._st.keys())
        assert self._state is not None
        return set(self._state.keys())

    def get_tensor(self, key: str) -> torch.Tensor:
        if self._st is not None:
            tensor: torch.Tensor = self._st.get_tensor(key)
            return tensor
        assert self._state is not None
        return self._state[key]

    def close(self) -> None:
        if self._st is not None:
            self._st.__exit__(None, None, None)
            self._st = None
        self._state = None


def _open_weight_reader(path: Path, fmt: str, torch_device: str) -> _WeightReader:
    return _WeightReader(path, fmt, torch_device)


def load_stage_blocks(
    model_id: str,
    start: LayerIdx,
    end: LayerIdx,
    *,
    dtype: str = "float32",
    torch_device: str = "cpu",
) -> nn.ModuleList:
    """Construct ONLY the transformer blocks for layers [start, end] and
    populate them with pretrained weights from safetensors.

    OPT-only for Phase 2.5 (other architectures need their own decoder-block
    class + a different weight-key prefix).
    """
    from transformers.models.opt.modeling_opt import OPTDecoderLayer

    config = AutoConfig.from_pretrained(model_id)
    if config.model_type != "opt":
        raise NotImplementedError(
            f"Phase 2.5 supports OPT only, got '{config.model_type}'"
        )
    if start < 1 or end > config.num_hidden_layers or start > end:
        raise ValueError(
            f"Stage [{start}, {end}] out of range for "
            f"{config.num_hidden_layers}-layer model {model_id}"
        )

    torch_dtype = DTYPE_MAP[dtype]
    weights_path, fmt = _find_weights_file(model_id)

    blocks = nn.ModuleList()
    rss_before = measure_resident_bytes()
    reader = _open_weight_reader(weights_path, fmt, torch_device)
    try:
        all_keys = reader.keys()
        for global_idx in range(int(start), int(end) + 1):
            layer = OPTDecoderLayer(config, layer_idx=global_idx - 1)
            layer.to(dtype=torch_dtype, device=torch_device)
            layer.eval()

            prefix = f"model.decoder.layers.{global_idx - 1}."
            local_state: dict[str, torch.Tensor] = {}
            for k in all_keys:
                if k.startswith(prefix):
                    tensor = reader.get_tensor(k)
                    local_state[k[len(prefix):]] = tensor.to(dtype=torch_dtype)
            missing, unexpected = layer.load_state_dict(local_state, strict=False)
            if missing:
                log.warning("layer %d missing keys: %s", global_idx, missing)
            if unexpected:
                log.warning("layer %d unexpected keys: %s", global_idx, unexpected)
            blocks.append(layer)
    finally:
        reader.close()
    rss_after = measure_resident_bytes()
    delta_mb = (rss_after - rss_before) / (1024 * 1024)
    log.info(
        "load_stage_blocks %s[%d..%d]: %d blocks, rss +%.1f MB (now %.1f MB)",
        model_id, start, end, int(end) - int(start) + 1, delta_mb,
        rss_after / (1024 * 1024),
    )
    return blocks
