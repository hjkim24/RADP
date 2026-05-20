"""Shared pytest fixtures: synthetic clusters for DP / recovery tests."""

from __future__ import annotations

import pytest

from radp.common.types import (
    SLO,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
)

LAYER_BYTES = 500_000_000  # ~0.5 GB per layer (toy figure)
NODE_BYTES = 4_000_000_000  # 4 GB Jetson Nano


def _device(i: int) -> DeviceProfile:
    return DeviceProfile(
        id=DeviceId(f"d{i}"),
        total_memory_bytes=NODE_BYTES,
        compute_throughput=1.0,
    )


def _uniform_layer(idx: int, devices: list[DeviceProfile], time_per_device: float) -> LayerProfile:
    return LayerProfile(
        layer_idx=LayerIdx(idx),
        memory_bytes=LAYER_BYTES,
        compute_time={d.id: time_per_device for d in devices},
    )


@pytest.fixture
def homogeneous_spec_2x4() -> ClusterSpec:
    """2 identical devices, 4 identical layers — expected split is 2/2."""
    devices = [_device(1), _device(2)]
    layers = [_uniform_layer(i, devices, time_per_device=0.05) for i in range(1, 5)]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.001 for d1 in devices for d2 in devices if d1 is not d2},
    )
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=network,
        slo=SLO(ttft_seconds=1.0, tbt_seconds=0.5),
    )


@pytest.fixture
def heterogeneous_spec_3x6() -> ClusterSpec:
    """3 devices with varied throughput, 6 layers — DP should give faster device more layers."""
    devices = [
        DeviceProfile(id=DeviceId("fast"), total_memory_bytes=NODE_BYTES * 2, compute_throughput=2.0),
        DeviceProfile(id=DeviceId("mid"), total_memory_bytes=NODE_BYTES, compute_throughput=1.0),
        DeviceProfile(id=DeviceId("slow"), total_memory_bytes=NODE_BYTES, compute_throughput=0.5),
    ]
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=LAYER_BYTES,
            compute_time={
                DeviceId("fast"): 0.025,
                DeviceId("mid"): 0.05,
                DeviceId("slow"): 0.1,
            },
        )
        for i in range(1, 7)
    ]
    network = NetworkProfile(
        bandwidth={(d1.id, d2.id): 1e9 for d1 in devices for d2 in devices if d1 is not d2},
        latency={(d1.id, d2.id): 0.001 for d1 in devices for d2 in devices if d1 is not d2},
    )
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=network,
        slo=SLO(ttft_seconds=1.0, tbt_seconds=0.5),
    )
