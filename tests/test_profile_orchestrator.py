"""Phase D2 — ProfileOrchestrator.

Covers:
  - wait_for_workers timeout vs success path
  - collect_network_profile builds a full-mesh NetworkProfile from
    in-process workers (asserts symmetry shape, not exact bandwidth)
  - build_device_profiles normalizes compute_throughput correctly
  - collect_layer_profiles (slow — loads OPT-125M)
  - HeartbeatRecord carries new fields via the live RPC path

Uses real in-process WorkerServer + FailureDetector wired by a no-op
on_failure callback, mirroring the production startup sequence the way
Phase D3 will plumb it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator

import pytest

from radp.common.protocol import CoordinatorClient
from radp.common.types import (
    DeviceId,
    LayerIdx,
    LayerProfile,
)
from radp.coordinator.failure_detector import FailureDetector, HeartbeatRecord
from radp.coordinator.profile_orchestrator import ProfileOrchestrator
from radp.coordinator.server import CoordinatorServer
from radp.worker.server import WorkerServer

_COORD_ADDR = "127.0.0.1:50090"
_ADDR_A = "127.0.0.1:50091"
_ADDR_B = "127.0.0.1:50092"


@pytest.fixture
def two_workers_no_coord() -> Generator[dict[DeviceId, str], None, None]:
    """Two workers without a coordinator (no heartbeat thread)."""
    a = WorkerServer(DeviceId("worker-a"), _ADDR_A)
    b = WorkerServer(DeviceId("worker-b"), _ADDR_B)
    a.start()
    b.start()
    try:
        yield {DeviceId("worker-a"): _ADDR_A, DeviceId("worker-b"): _ADDR_B}
    finally:
        a.stop()
        b.stop()


def _make_detector() -> FailureDetector:
    return FailureDetector(
        on_failure=lambda _d: None,
        timeout_seconds=60.0,
        tick_interval_seconds=10.0,
    )


def test_wait_for_workers_times_out_when_none_register() -> None:
    detector = _make_detector()
    orch = ProfileOrchestrator(
        {DeviceId("nobody"): "127.0.0.1:1"}, detector
    )
    with pytest.raises(TimeoutError, match="missing"):
        orch.wait_for_workers(timeout_seconds=0.5, poll_interval_seconds=0.05)


def test_wait_for_workers_returns_when_all_present() -> None:
    detector = _make_detector()
    addrs = {DeviceId("a"): "127.0.0.1:1", DeviceId("b"): "127.0.0.1:2"}
    orch = ProfileOrchestrator(addrs, detector)

    def feed() -> None:
        time.sleep(0.1)
        detector.record(HeartbeatRecord(DeviceId("a"), time.time_ns(), 1.0))
        time.sleep(0.05)
        detector.record(
            HeartbeatRecord(
                DeviceId("b"), time.time_ns(), 2.0,
                total_memory_bytes=4.2e9, device_class="jetson-nano",
            )
        )

    threading.Thread(target=feed, daemon=True).start()
    records = orch.wait_for_workers(timeout_seconds=2.0, poll_interval_seconds=0.05)
    assert set(records.keys()) == {DeviceId("a"), DeviceId("b")}
    assert records[DeviceId("b")].total_memory_bytes == pytest.approx(4.2e9)
    assert records[DeviceId("b")].device_class == "jetson-nano"


def test_collect_network_profile_full_mesh(
    two_workers_no_coord: dict[DeviceId, str],
) -> None:
    detector = _make_detector()
    orch = ProfileOrchestrator(two_workers_no_coord, detector)
    network = orch.collect_network_profile(payload_bytes=4096, rounds=3)

    # Full mesh = N*(N-1) directed pairs = 2*(2-1) = 2 entries
    assert set(network.bandwidth.keys()) == {
        (DeviceId("worker-a"), DeviceId("worker-b")),
        (DeviceId("worker-b"), DeviceId("worker-a")),
    }
    assert set(network.latency.keys()) == set(network.bandwidth.keys())
    for v in network.bandwidth.values():
        assert v > 0
    for v in network.latency.values():
        assert v >= 0.0


def test_build_device_profiles_normalizes_throughput() -> None:
    # Synthetic: 2 layers, 2 devices. dev-fast: 1.0s total. dev-slow: 4.0s total.
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(1),
            memory_bytes=1_000_000,
            compute_time={
                DeviceId("dev-fast"): 0.5,
                DeviceId("dev-slow"): 2.0,
            },
        ),
        LayerProfile(
            layer_idx=LayerIdx(2),
            memory_bytes=1_000_000,
            compute_time={
                DeviceId("dev-fast"): 0.5,
                DeviceId("dev-slow"): 2.0,
            },
        ),
    ]
    records = {
        DeviceId("dev-fast"): HeartbeatRecord(
            DeviceId("dev-fast"), 0, 0.0, total_memory_bytes=8e9,
        ),
        DeviceId("dev-slow"): HeartbeatRecord(
            DeviceId("dev-slow"), 0, 0.0, total_memory_bytes=4e9,
        ),
    }
    profiles = ProfileOrchestrator.build_device_profiles(records, layers)
    by_id = {p.id: p for p in profiles}
    # fastest normalizes to 1.0; slow = 1.0 / 4.0 = 0.25
    assert by_id[DeviceId("dev-fast")].compute_throughput == pytest.approx(1.0)
    assert by_id[DeviceId("dev-slow")].compute_throughput == pytest.approx(0.25)
    assert by_id[DeviceId("dev-fast")].total_memory_bytes == 8_000_000_000
    assert by_id[DeviceId("dev-slow")].total_memory_bytes == 4_000_000_000


def test_heartbeat_propagates_new_fields_through_full_stack() -> None:
    """Live RPC: WorkerServer's HeartbeatSender → CoordinatorServer → detector."""
    from radp.coordinator.server import CoordinatorConfig, WorkerSpec

    config = CoordinatorConfig(
        bind_address=_COORD_ADDR,
        model_id="facebook/opt-125m",
        workers=[WorkerSpec(DeviceId("worker-c"), _ADDR_A)],
        placement=[],
        recovery={},
        heartbeat_timeout_seconds=60.0,
        heartbeat_tick_seconds=10.0,
        torch_device="cpu",
        dtype="float32",
    )
    coord = CoordinatorServer(config)
    coord.start()
    try:
        # Send a single heartbeat directly (no WorkerServer needed for this test)
        with CoordinatorClient(_COORD_ADDR) as c:
            c.heartbeat(
                DeviceId("worker-c"),
                free_memory_bytes=3.5e9,
                total_memory_bytes=4.2e9,
                device_class="jetson-orin-nano-4gb",
            )
        # Wait a beat for the detector to record
        time.sleep(0.1)
        assert coord.detector is not None
        records = coord.detector.snapshot_records()
        assert DeviceId("worker-c") in records
        rec = records[DeviceId("worker-c")]
        assert rec.total_memory_bytes == pytest.approx(4.2e9)
        assert rec.device_class == "jetson-orin-nano-4gb"
        assert rec.free_memory_bytes == pytest.approx(3.5e9)
    finally:
        coord.stop()


@pytest.mark.slow
def test_collect_layer_profiles_merges_per_device(
    two_workers_no_coord: dict[DeviceId, str],
) -> None:
    detector = _make_detector()
    orch = ProfileOrchestrator(two_workers_no_coord, detector)
    profiles = orch.collect_layer_profiles(
        "facebook/opt-125m", warmup=1, repeats=2, seq_length=16,
    )
    # OPT-125M has 12 decoder layers
    assert len(profiles) == 12
    # Each merged LayerProfile must have compute_time entries for BOTH workers
    for p in profiles:
        assert set(p.compute_time.keys()) == {
            DeviceId("worker-a"), DeviceId("worker-b"),
        }
        for t in p.compute_time.values():
            assert t > 0
