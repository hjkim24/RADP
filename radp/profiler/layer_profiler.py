"""Per-layer compute time + memory profiler.

Uses PyTorch forward hooks so we can profile every transformer block from a
single full-model forward pass, without manually wrangling attention masks /
rotary embeddings / position ids per architecture.

Output feeds LayerProfile -> Scheduler. Runs on any device PyTorch supports
(CPU on Mac, CUDA on Jetson). Profiling results on different machines can
be merged via `merge_profiles` to build a cross-device LayerProfile.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

import torch
from torch import nn

from radp.common.logging_utils import get_logger
from radp.common.model_utils import (
    DTYPE_BYTES,
    estimate_kv_cache_bytes,
    get_transformer_layers,
    layer_param_bytes,
    load_model,
)
from radp.common.types import DeviceId, LayerIdx, LayerProfile

log = get_logger(__name__)


def profile_layers(
    model_id: str,
    device_id: DeviceId,
    *,
    warmup: int = 3,
    repeat: int = 10,
    dtype: str = "float32",
    torch_device: str = "cpu",
    seq_length: int = 64,
    kv_cache_max_seq: int = 256,
    prompt: str = "The quick brown fox jumps over the lazy dog. " * 16,
) -> list[LayerProfile]:
    """Profile every transformer block of `model_id` on `torch_device`.

    Returns one LayerProfile per layer (1-based ordering) where:
      - memory_bytes = parameter bytes + estimated KV-cache bytes
      - compute_time = {device_id: median wall-clock seconds over `repeat` runs}
    """
    log.info("loading %s on %s (dtype=%s)", model_id, torch_device, dtype)
    handle = load_model(model_id, dtype=dtype, torch_device=torch_device)
    layers = get_transformer_layers(handle.model)

    timings_ns: dict[int, list[float]] = {i: [] for i in range(len(layers))}
    starts_ns: dict[int, float] = {}

    def _pre(idx: int) -> Any:
        def hook(_module: nn.Module, _inputs: tuple[Any, ...]) -> None:
            starts_ns[idx] = time.perf_counter()
        return hook

    def _post(idx: int) -> Any:
        def hook(_module: nn.Module, _inputs: tuple[Any, ...], _outputs: Any) -> None:
            timings_ns[idx].append(time.perf_counter() - starts_ns[idx])
        return hook

    handles = []
    for i, layer in enumerate(layers):
        handles.append(layer.register_forward_pre_hook(_pre(i)))
        handles.append(layer.register_forward_hook(_post(i)))

    try:
        inputs = handle.tokenizer(
            prompt,
            return_tensors="pt",
            max_length=seq_length,
            truncation=True,
            padding="max_length",
        )
        input_ids = inputs["input_ids"].to(torch_device)
        attention_mask = inputs.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(torch_device)

        log.info("warmup %dx", warmup)
        with torch.no_grad():
            for _ in range(warmup):
                handle.model(input_ids=input_ids, attention_mask=attention_mask)

        # Reset after warmup
        for k in timings_ns:
            timings_ns[k] = []

        log.info("measure %dx", repeat)
        with torch.no_grad():
            for _ in range(repeat):
                handle.model(input_ids=input_ids, attention_mask=attention_mask)
    finally:
        for h in handles:
            h.remove()

    dtype_bytes = DTYPE_BYTES[dtype]
    kv_bytes = estimate_kv_cache_bytes(handle.hidden_size, kv_cache_max_seq, dtype_bytes)
    profiles: list[LayerProfile] = []
    for idx, layer in enumerate(layers):
        samples = timings_ns[idx]
        if not samples:
            raise RuntimeError(
                f"No timing samples for layer {idx + 1}; forward hook never fired."
            )
        median_seconds = statistics.median(samples)
        weight_bytes = layer_param_bytes(layer)
        profiles.append(
            LayerProfile(
                layer_idx=LayerIdx(idx + 1),
                memory_bytes=weight_bytes + kv_bytes,
                compute_time={device_id: median_seconds},
            )
        )
    log.info("profiled %d layers, slowest=%.4fs", len(profiles),
             max(next(iter(p.compute_time.values())) for p in profiles))
    return profiles


def save_profile(profiles: list[LayerProfile], path: str | Path) -> None:
    """Serialize profiles to JSON. Keys in compute_time become device-id strings."""
    data = [
        {
            "layer_idx": int(p.layer_idx),
            "memory_bytes": p.memory_bytes,
            "compute_time": {str(k): float(v) for k, v in p.compute_time.items()},
        }
        for p in profiles
    ]
    Path(path).write_text(json.dumps(data, indent=2))


def load_profile(path: str | Path) -> list[LayerProfile]:
    raw = json.loads(Path(path).read_text())
    return [
        LayerProfile(
            layer_idx=LayerIdx(int(entry["layer_idx"])),
            memory_bytes=int(entry["memory_bytes"]),
            compute_time={DeviceId(k): float(v) for k, v in entry["compute_time"].items()},
        )
        for entry in raw
    ]


def merge_profiles(*profile_sets: list[LayerProfile]) -> list[LayerProfile]:
    """Merge per-device profile runs into one list with combined compute_time maps.

    Each input must be the same model (same layer count + memory_bytes); only
    the compute_time dicts differ across runs.
    """
    if not profile_sets:
        return []
    first = profile_sets[0]
    expected_len = len(first)
    for s in profile_sets[1:]:
        if len(s) != expected_len:
            raise ValueError(
                f"Profile length mismatch: {len(s)} vs expected {expected_len}"
            )

    merged: list[LayerProfile] = []
    for i in range(expected_len):
        combined: dict[DeviceId, float] = {}
        for s in profile_sets:
            combined.update(s[i].compute_time)
        merged.append(
            LayerProfile(
                layer_idx=LayerIdx(i + 1),
                memory_bytes=first[i].memory_bytes,
                compute_time=combined,
            )
        )
    return merged
