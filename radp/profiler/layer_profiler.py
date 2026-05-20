"""Measure per-layer compute time + memory footprint on a target device.

Phase 1 deliverable. Output feeds LayerProfile -> Scheduler.
"""

from __future__ import annotations

from radp.common.types import DeviceProfile, LayerProfile


def profile_layers(
    model_id: str,
    device: DeviceProfile,
    num_layers: int,
    *,
    warmup: int = 3,
    repeat: int = 10,
) -> list[LayerProfile]:
    """Run forward passes layer-by-layer and record timing / memory.

    Implementation steps (Phase 1):
      1. Load model with `model_utils.load_model`.
      2. For each transformer block, run `repeat` micro-benchmarks after
         `warmup` calls; record median compute_time.
      3. Snapshot CUDA / Jetson memory delta -> memory_bytes.
    """
    raise NotImplementedError
