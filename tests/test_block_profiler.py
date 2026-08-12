"""The profiler must not need the whole model in memory."""

from __future__ import annotations

import pytest

from radp.common.types import DeviceId


@pytest.mark.slow
def test_block_wise_profile_covers_every_layer() -> None:
    from radp.profiler.layer_profiler import profile_layers

    profiles = profile_layers(
        "facebook/opt-125m",
        device_id=DeviceId("test"),
        warmup=1,
        repeat=2,
        dtype="float32",
        torch_device="cpu",
        seq_length=8,
    )
    assert len(profiles) == 12  # opt-125m has 12 layers
    assert [int(p.layer_idx) for p in profiles] == list(range(1, 13))
    for p in profiles:
        assert p.memory_bytes > 0
        assert p.compute_time[DeviceId("test")] > 0


@pytest.mark.slow
def test_block_wise_peak_stays_below_full_model() -> None:
    """The point of the change: peak tracks one block, not the checkpoint."""
    from radp.common.model_utils import measure_resident_bytes
    from radp.profiler.layer_profiler import profile_layers

    before = measure_resident_bytes()
    profile_layers(
        "facebook/opt-125m",
        device_id=DeviceId("test"),
        warmup=1,
        repeat=1,
        dtype="float32",
        torch_device="cpu",
        seq_length=8,
    )
    growth_mb = (measure_resident_bytes() - before) / (1024 * 1024)
    # opt-125m is ~500 MB in float32; one block is ~14 MB. Allow generous slack
    # for the interpreter and HF config caching, but fail if we kept the model.
    assert growth_mb < 200, f"profiler retained {growth_mb:.0f} MB"
