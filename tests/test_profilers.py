"""Tests for the layer + network profiler I/O helpers.

The end-to-end layer profiling test (downloading OPT-125M) is marked slow
and skipped by default. To run it: `uv run pytest -m slow`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radp.common.types import DeviceId, DeviceProfile, LayerIdx, LayerProfile
from radp.profiler.layer_profiler import load_profile, merge_profiles, save_profile
from radp.profiler.network_profiler import (
    load_network_profile,
    save_network_profile,
    uniform_network,
)


# ---------------------------------------------------------------------------
# Layer profile JSON roundtrip
# ---------------------------------------------------------------------------
def test_layer_profile_json_roundtrip(tmp_path: Path) -> None:
    profiles = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=1_000_000 * i,
            compute_time={DeviceId("d1"): 0.01 * i, DeviceId("d2"): 0.02 * i},
        )
        for i in range(1, 4)
    ]
    out = tmp_path / "profile.json"
    save_profile(profiles, out)
    loaded = load_profile(out)
    assert loaded == profiles


def test_merge_profiles_combines_compute_time() -> None:
    a = [
        LayerProfile(LayerIdx(1), 100, {DeviceId("d1"): 0.01}),
        LayerProfile(LayerIdx(2), 100, {DeviceId("d1"): 0.02}),
    ]
    b = [
        LayerProfile(LayerIdx(1), 100, {DeviceId("d2"): 0.03}),
        LayerProfile(LayerIdx(2), 100, {DeviceId("d2"): 0.04}),
    ]
    merged = merge_profiles(a, b)
    assert merged[0].compute_time == {DeviceId("d1"): 0.01, DeviceId("d2"): 0.03}
    assert merged[1].compute_time == {DeviceId("d1"): 0.02, DeviceId("d2"): 0.04}


def test_merge_profiles_rejects_length_mismatch() -> None:
    a = [LayerProfile(LayerIdx(1), 100, {DeviceId("d1"): 0.01})]
    b = [LayerProfile(LayerIdx(i), 100, {DeviceId("d2"): 0.01}) for i in (1, 2)]
    with pytest.raises(ValueError, match="length mismatch"):
        merge_profiles(a, b)


# ---------------------------------------------------------------------------
# Network profile JSON roundtrip
# ---------------------------------------------------------------------------
def test_network_profile_json_roundtrip(tmp_path: Path) -> None:
    devices = [
        DeviceProfile(id=DeviceId("a"), total_memory_bytes=4_000_000_000, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("b"), total_memory_bytes=4_000_000_000, compute_throughput=1.0),
    ]
    profile = uniform_network(devices, bandwidth_bps=1e9, latency_seconds=0.001)
    out = tmp_path / "network.json"
    save_network_profile(profile, out)
    loaded = load_network_profile(out)
    assert loaded.bandwidth == profile.bandwidth
    assert loaded.latency == profile.latency


def test_uniform_network_excludes_self_loops() -> None:
    devices = [
        DeviceProfile(id=DeviceId("a"), total_memory_bytes=1, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("b"), total_memory_bytes=1, compute_throughput=1.0),
    ]
    profile = uniform_network(devices, bandwidth_bps=1.0, latency_seconds=0.0)
    for (src, dst) in profile.bandwidth:
        assert src != dst


# ---------------------------------------------------------------------------
# End-to-end (slow; opt-in)
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_profile_layers_end_to_end_opt125m(tmp_path: Path) -> None:
    """Smoke test: download OPT-125M and profile every layer on CPU.

    Skipped by default; run with `uv run pytest -m slow`.
    OPT-125M has 12 layers and ~250MB of weights.
    """
    from radp.profiler.layer_profiler import profile_layers

    profiles = profile_layers(
        model_id="facebook/opt-125m",
        device_id=DeviceId("mac-cpu"),
        warmup=1,
        repeat=2,
        seq_length=32,
    )
    assert len(profiles) == 12
    for p in profiles:
        assert p.memory_bytes > 0
        assert p.compute_time[DeviceId("mac-cpu")] > 0
    # Roundtrip the result
    out = tmp_path / "opt125m.json"
    save_profile(profiles, out)
    loaded = load_profile(out)
    assert loaded == profiles
