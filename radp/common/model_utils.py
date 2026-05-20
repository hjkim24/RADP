"""Model loading + layer-range slicing helpers.

Implementations live in Phase 2; this module pins down the interfaces so
callers can wire dependencies now.
"""

from __future__ import annotations

from typing import Protocol

from radp.common.types import LayerIdx


class ModelHandle(Protocol):
    """Opaque handle to a fully-loaded transformer (interface only)."""

    model_id: str
    num_layers: int


def load_model(model_id: str, dtype: str = "int4") -> ModelHandle:
    """Load a HuggingFace model (or quantized variant) into local memory.

    Phase 2 will implement this using `transformers` + `bitsandbytes` /
    Jetson-specific kernels.
    """
    raise NotImplementedError


def slice_stage(
    model: ModelHandle,
    start_layer: LayerIdx,
    end_layer: LayerIdx,
) -> object:
    """Return a runnable module containing only [start_layer, end_layer] (inclusive).

    Phase 2: extract a ModuleList slice and wrap with the right pre/post hooks.
    """
    raise NotImplementedError


def estimate_layer_memory(model_id: str, layer_idx: LayerIdx, dtype: str) -> int:
    """Static memory estimate (bytes) for a single transformer block.

    Used by the profiler when actual measurement is not yet available.
    """
    raise NotImplementedError
