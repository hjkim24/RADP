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

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import torch
from torch import nn
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

from radp.common.architectures import get_architecture
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


def estimate_activation_bytes(
    model_id: str,
    dtype: str,
    *,
    batch_size: int = 1,
) -> int:
    """Inter-stage activation transfer size: batch * hidden_size * dtype_bytes.

    Each pipeline stage hands its successor a single hidden-state vector per
    token (shape: [batch, 1, hidden] during decode). The Scheduler's comm
    cost is `activation_bytes / bandwidth + latency`; getting this number
    right is what lets DP weigh compute vs comm correctly.

    Uses AutoConfig (no model weights loaded) so it's cheap to call at
    coordinator startup.
    """
    if dtype not in DTYPE_BYTES:
        raise ValueError(f"Unsupported dtype {dtype!r}; choose from {sorted(DTYPE_BYTES)}")
    config = AutoConfig.from_pretrained(model_id)
    hidden = int(config.hidden_size)
    return batch_size * hidden * DTYPE_BYTES[dtype]


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


@dataclass
class WeightsLocation:
    """Where a model's weights live and in what format.

    Four formats are supported (cf. HF conventions):
      * ``"safetensors"`` — single ``model.safetensors``
      * ``"bin"`` — single ``pytorch_model.bin``
      * ``"safetensors_sharded"`` — ``model.safetensors.index.json`` + shards
      * ``"bin_sharded"``         — ``pytorch_model.bin.index.json`` + shards

    For sharded formats, ``index_path`` points at the index JSON and
    ``weight_map`` is the parsed ``weight_map`` field (tensor_name → shard
    filename). ``model_id`` is retained so we can download specific shard
    files on demand via ``huggingface_hub.hf_hub_download``.
    """

    fmt: str
    path: Path  # single-file: the file. Sharded: the index file.
    model_id: str | None = None
    weight_map: dict[str, str] | None = None


def _find_weights_location(model_id: str) -> WeightsLocation:
    """Locate weights for ``model_id`` and download the entry-point file
    (single weights or the shard index). Sharded shards themselves are
    downloaded lazily by ``_WeightReader``.

    Lookup order, first match wins:
      1. single ``model.safetensors``
      2. single ``pytorch_model.bin``
      3. sharded ``model.safetensors.index.json``
      4. sharded ``pytorch_model.bin.index.json``
    """
    import json as _json

    from huggingface_hub import hf_hub_download

    errors: list[str] = []
    for filename, fmt in [
        ("model.safetensors", "safetensors"),
        ("pytorch_model.bin", "bin"),
    ]:
        try:
            return WeightsLocation(fmt=fmt, path=Path(hf_hub_download(model_id, filename)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{filename}: {e}")

    for index_filename, fmt in [
        ("model.safetensors.index.json", "safetensors_sharded"),
        ("pytorch_model.bin.index.json", "bin_sharded"),
    ]:
        try:
            idx_path = Path(hf_hub_download(model_id, index_filename))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{index_filename}: {e}")
            continue
        try:
            idx_data = _json.loads(idx_path.read_text())
            weight_map = idx_data["weight_map"]
            log.info(
                "%s is sharded (%s): %d tensors across %d shards",
                model_id, fmt, len(weight_map), len(set(weight_map.values())),
            )
            return WeightsLocation(
                fmt=fmt, path=idx_path, model_id=model_id, weight_map=weight_map,
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{index_filename} parse: {e}")

    raise FileNotFoundError(
        f"No supported weights file for {model_id}. Tried single + sharded "
        f"safetensors/bin. Errors:\n  " + "\n  ".join(errors)
    )


class _WeightReader:
    """Uniform (keys / get_tensor / close) API over single or sharded weights.

    Single safetensors: opens once with ``safe_open`` (mmap, lazy per-tensor).
    Single bin: ``torch.load`` once (whole file in memory).
    Sharded safetensors: per-shard ``safe_open`` handles, opened lazily as
      tensors from that shard are first requested.
    Sharded bin: per-shard ``torch.load``, also lazy.
    """

    def __init__(self, loc: WeightsLocation, torch_device: str) -> None:
        self.fmt = loc.fmt
        self._torch_device = torch_device
        # Single-file caches:
        self._st: Any = None
        self._state: dict[str, torch.Tensor] | None = None
        # Sharded caches:
        self._weight_map: dict[str, str] | None = loc.weight_map
        self._model_id: str | None = loc.model_id
        self._shard_st: dict[str, Any] = {}              # shard filename → safe_open handle
        self._shard_state: dict[str, dict[str, torch.Tensor]] = {}  # shard filename → state dict

        if loc.fmt == "safetensors":
            from safetensors import safe_open
            handle: Any = safe_open(  # type: ignore[no-untyped-call]
                str(loc.path), framework="pt", device=torch_device
            )
            handle.__enter__()
            self._st = handle
        elif loc.fmt == "bin":
            self._state = torch.load(
                str(loc.path), map_location=torch_device, weights_only=True
            )
        elif loc.fmt in ("safetensors_sharded", "bin_sharded"):
            if self._weight_map is None or self._model_id is None:
                raise ValueError(f"{loc.fmt} requires weight_map + model_id")
        else:
            raise ValueError(f"Unsupported weights format: {loc.fmt}")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def keys(self) -> set[str]:
        if self._st is not None:
            return set(self._st.keys())
        if self._state is not None:
            return set(self._state.keys())
        if self._weight_map is not None:
            return set(self._weight_map.keys())
        return set()

    def get_tensor(self, key: str) -> torch.Tensor:
        if self._st is not None:
            tensor: torch.Tensor = self._st.get_tensor(key)
            return tensor
        if self._state is not None:
            return self._state[key]
        # Sharded path: find the shard, lazy-open, read.
        assert self._weight_map is not None and self._model_id is not None
        shard_filename = self._weight_map[key]
        if self.fmt == "safetensors_sharded":
            handle = self._get_shard_safetensors(shard_filename)
            return handle.get_tensor(key)  # type: ignore[no-any-return]
        # bin_sharded
        state = self._get_shard_bin(shard_filename)
        return state[key]

    def close(self) -> None:
        if self._st is not None:
            self._st.__exit__(None, None, None)
            self._st = None
        for handle in self._shard_st.values():
            with contextlib.suppress(Exception):
                handle.__exit__(None, None, None)
        self._shard_st.clear()
        self._shard_state.clear()
        self._state = None

    # ------------------------------------------------------------------
    # Sharded internals — download + cache per shard on first access
    # ------------------------------------------------------------------
    def _get_shard_safetensors(self, shard_filename: str) -> Any:
        if shard_filename in self._shard_st:
            return self._shard_st[shard_filename]
        from huggingface_hub import hf_hub_download
        from safetensors import safe_open
        assert self._model_id is not None
        log.info("downloading shard %s of %s", shard_filename, self._model_id)
        path = hf_hub_download(self._model_id, shard_filename)
        handle: Any = safe_open(  # type: ignore[no-untyped-call]
            path, framework="pt", device=self._torch_device
        )
        handle.__enter__()
        self._shard_st[shard_filename] = handle
        return handle

    def _get_shard_bin(self, shard_filename: str) -> dict[str, torch.Tensor]:
        if shard_filename in self._shard_state:
            return self._shard_state[shard_filename]
        from huggingface_hub import hf_hub_download
        assert self._model_id is not None
        log.info("downloading shard %s of %s", shard_filename, self._model_id)
        path = hf_hub_download(self._model_id, shard_filename)
        state: dict[str, torch.Tensor] = torch.load(
            path, map_location=self._torch_device, weights_only=True
        )
        self._shard_state[shard_filename] = state
        return state


def _open_weight_reader(loc: WeightsLocation, torch_device: str) -> _WeightReader:
    return _WeightReader(loc, torch_device)


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
    config = AutoConfig.from_pretrained(model_id)
    arch = get_architecture(config.model_type)
    if start < 1 or end > config.num_hidden_layers or start > end:
        raise ValueError(
            f"Stage [{start}, {end}] out of range for "
            f"{config.num_hidden_layers}-layer model {model_id}"
        )

    torch_dtype = DTYPE_MAP[dtype]
    weights_loc = _find_weights_location(model_id)

    blocks = nn.ModuleList()
    rss_before = measure_resident_bytes()
    reader = _open_weight_reader(weights_loc, torch_device)
    try:
        all_keys = reader.keys()
        # HF checkpoints for the same model family don't always agree on
        # whether the state dict keys start with "model." — opt-125m's
        # pytorch_model.bin does, opt-350m's model.safetensors does NOT
        # (key is "decoder.layers.0.self_attn.k_proj.weight" with no leading
        # "model."). Both layouts exist on HF Hub for the same model id at
        # different snapshots. The arch returns the canonical "model."-
        # prefixed form; if that prefix never appears in the file, strip
        # "model." and try the bare form. Detect once, apply to every layer.
        canonical_prefix = arch.weight_prefix(int(start) - 1)
        if not any(k.startswith(canonical_prefix) for k in all_keys):
            stripped = (
                canonical_prefix[len("model."):]
                if canonical_prefix.startswith("model.") else canonical_prefix
            )
            if any(k.startswith(stripped) for k in all_keys):
                log.info(
                    "checkpoint uses bare key layout (no 'model.' prefix); "
                    "stripping it from weight_prefix for this load"
                )
                _strip_model = True
            else:
                _strip_model = False
        else:
            _strip_model = False

        for global_idx in range(int(start), int(end) + 1):
            layer = arch.make_block(config, layer_idx=global_idx - 1)
            layer.to(dtype=torch_dtype, device=torch_device)
            layer.eval()

            prefix = arch.weight_prefix(global_idx - 1)
            if _strip_model and prefix.startswith("model."):
                prefix = prefix[len("model."):]
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
