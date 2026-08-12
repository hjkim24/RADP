"""Per-layer compute time + memory profiler.

Loads and profiles one transformer block at a time via `load_stage_blocks`,
so peak memory tracks a single block instead of the whole checkpoint (a 7B
model cannot be fully materialized on an 8 GB Jetson). Each block is fed a
synthetic hidden state through `arch.run_block` — the same calling
convention `stage_runner` uses for a real decoder block — then freed before
the next block is loaded.

Output feeds LayerProfile -> Scheduler. Runs on any device PyTorch supports
(CPU on Mac, CUDA on Jetson). Profiling results on different machines can
be merged via `merge_profiles` to build a cross-device LayerProfile.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import median

import torch
from transformers import AutoConfig
from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask

from radp.common.architectures import get_architecture
from radp.common.logging_utils import get_logger
from radp.common.model_utils import (
    DTYPE_BYTES,
    DTYPE_MAP,
    estimate_kv_cache_bytes,
    layer_param_bytes,
    load_stage_blocks,
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
    prompt: str | None = None,
) -> list[LayerProfile]:
    """Profile every transformer block of `model_id` on `torch_device`.

    Returns one LayerProfile per layer (1-based ordering) where:
      - memory_bytes = parameter bytes + estimated KV-cache bytes
      - compute_time = {device_id: median wall-clock seconds over `repeat` runs}
    """
    del prompt  # legacy arg kept for CLI compat; we synthesise input_ids directly
    log.info("loading %s on %s (dtype=%s)", model_id, torch_device, dtype)

    config = AutoConfig.from_pretrained(model_id)
    arch = get_architecture(config.model_type)
    num_layers = config.num_hidden_layers
    hidden_size = config.hidden_size
    torch_dtype = DTYPE_MAP[dtype]
    aux = arch.make_aux(config, torch_dtype, torch_device)
    is_cuda = str(torch_device).startswith("cuda")

    profiles: list[LayerProfile] = []
    for global_idx in range(1, num_layers + 1):
        blocks = load_stage_blocks(
            model_id, LayerIdx(global_idx), LayerIdx(global_idx),
            dtype=dtype, torch_device=torch_device,
        )
        block = blocks[0]
        # A decoder block's real input is a hidden state — this is exactly how
        # stage_runner invokes it. Values do not affect timing; shape does.
        hidden = torch.zeros(
            (1, seq_length, hidden_size), dtype=torch_dtype, device=torch_device
        )
        # run_block expects the additive 4D causal mask stage_runner receives
        # from the gateway (built the same way there), not the raw 2D
        # tokenizer-level mask -- OPTAttention indexes it as
        # attention_mask[:, :, :, :key_len], which needs 4 dims.
        attention_mask_2d = torch.ones(
            (1, seq_length), dtype=torch.long, device=torch_device
        )
        attention_mask = _prepare_4d_causal_attention_mask(
            attention_mask_2d, (1, seq_length), hidden, past_key_values_length=0
        )

        samples: list[float] = []
        with torch.no_grad():
            for _ in range(warmup):
                arch.run_block(block, hidden, attention_mask, None, 0, aux)
            if is_cuda:
                torch.cuda.synchronize()
            for _ in range(repeat):
                if is_cuda:
                    start_ev = torch.cuda.Event(enable_timing=True)
                    end_ev = torch.cuda.Event(enable_timing=True)
                    start_ev.record()
                    arch.run_block(block, hidden, attention_mask, None, 0, aux)
                    end_ev.record()
                    torch.cuda.synchronize()
                    samples.append(start_ev.elapsed_time(end_ev) / 1000.0)
                else:
                    t0 = time.perf_counter()
                    arch.run_block(block, hidden, attention_mask, None, 0, aux)
                    samples.append(time.perf_counter() - t0)

        param_bytes = layer_param_bytes(block)
        kv_bytes = estimate_kv_cache_bytes(
            hidden_size, kv_cache_max_seq, DTYPE_BYTES[dtype]
        )
        profiles.append(
            LayerProfile(
                layer_idx=LayerIdx(global_idx),
                memory_bytes=param_bytes + kv_bytes,
                compute_time={device_id: median(samples)},
            )
        )
        log.info(
            "layer %d/%d: %.3f ms median (%d samples)",
            global_idx, num_layers, median(samples) * 1000, len(samples),
        )
        del blocks, block
        if is_cuda:
            torch.cuda.empty_cache()

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
