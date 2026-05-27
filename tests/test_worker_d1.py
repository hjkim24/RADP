"""Phase D1 — worker-side RPCs for auto-scheduling.

Covers:
  - Ping echo correctness
  - measure_peer(): two in-process workers measure each other's link
  - ProfileLayers RPC returns a valid JSON-encoded list[LayerProfile]
    (slow — requires loading a small HF model)
  - HeartbeatSender includes total_memory_bytes + device_class
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from typing import Any

import grpc
import pytest

from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId
from radp.worker.peer_measurer import measure_peer
from radp.worker.server import WorkerServer

_ADDR_A = "127.0.0.1:50071"
_ADDR_B = "127.0.0.1:50072"


@pytest.fixture
def two_workers() -> Generator[tuple[str, str], None, None]:
    a = WorkerServer(DeviceId("worker-a"), _ADDR_A)
    b = WorkerServer(DeviceId("worker-b"), _ADDR_B)
    a.start()
    b.start()
    try:
        yield _ADDR_A, _ADDR_B
    finally:
        a.stop()
        b.stop()


def _stub(addr: str) -> tuple[Any, grpc.Channel]:
    channel = grpc.insecure_channel(addr)
    stub = radp_pb2_grpc.WorkerServiceStub(channel)
    return stub, channel


def test_ping_echoes_payload_and_sent_ns(two_workers: tuple[str, str]) -> None:
    addr_a, _ = two_workers
    stub, channel = _stub(addr_a)
    try:
        payload = b"hello-radp-D1"
        sent = time.monotonic_ns()
        resp = stub.Ping(radp_pb2.PingRequest(payload=payload, sent_ns=sent))
        assert resp.payload == payload
        assert resp.sent_ns == sent
        assert resp.echo_ns > 0
    finally:
        channel.close()


def test_measure_peer_between_workers(two_workers: tuple[str, str]) -> None:
    addr_a, addr_b = two_workers
    bandwidth, latency = measure_peer(
        peer_address=addr_b, payload_bytes=65_536, rounds=5
    )
    assert latency >= 0.0
    # 64KiB over localhost should be at least 10 MB/s; infinity is also fine
    # (very small transit time). Just guard against absurd zero/negative values.
    assert bandwidth > 10_000_000 or bandwidth == float("inf")
    # And we get something back from A too (symmetry):
    bandwidth2, latency2 = measure_peer(
        peer_address=addr_a, payload_bytes=65_536, rounds=5
    )
    assert latency2 >= 0.0
    assert bandwidth2 > 10_000_000 or bandwidth2 == float("inf")


def test_measure_peer_invalid_payload_raises() -> None:
    with pytest.raises(ValueError, match="payload_bytes"):
        measure_peer(peer_address="127.0.0.1:1", payload_bytes=8, rounds=1)


def test_measure_peer_rpc_failure_surfaces(two_workers: tuple[str, str]) -> None:
    # MeasurePeer RPC targeting a port nobody listens on → should return ok=False
    addr_a, _ = two_workers
    stub, channel = _stub(addr_a)
    try:
        resp = stub.MeasurePeer(
            radp_pb2.MeasurePeerRequest(
                peer_address="127.0.0.1:1",  # nothing here
                payload_bytes=1024,
                rounds=2,
            )
        )
        assert resp.ok is False
        assert resp.error  # non-empty diagnostic
    finally:
        channel.close()


@pytest.mark.slow
def test_profile_layers_returns_valid_json(two_workers: tuple[str, str]) -> None:
    addr_a, _ = two_workers
    stub, channel = _stub(addr_a)
    try:
        resp = stub.ProfileLayers(
            radp_pb2.ProfileLayersRequest(
                model_id="facebook/opt-125m",
                warmup=1,
                repeats=2,
                seq_length=16,
            ),
            timeout=600.0,
        )
        assert resp.ok, f"ProfileLayers failed: {resp.error}"
        decoded = json.loads(resp.serialized_profiles.decode("utf-8"))
        assert isinstance(decoded, list)
        # OPT-125M has 12 decoder layers
        assert len(decoded) == 12
        first = decoded[0]
        assert first["layer_idx"] == 1
        assert first["memory_bytes"] > 0
        assert "worker-a" in first["compute_time"]
        assert first["compute_time"]["worker-a"] > 0.0
    finally:
        channel.close()


def test_heartbeat_request_supports_new_fields() -> None:
    # No coordinator running; just verify the message accepts the new fields.
    req = radp_pb2.HeartbeatRequest(
        device_id="worker-a",
        free_memory_bytes=3.5e9,
        ts_ns=time.time_ns(),
        total_memory_bytes=4.2e9,
        device_class="jetson-orin-nano-4gb",
    )
    serialized = req.SerializeToString()
    parsed = radp_pb2.HeartbeatRequest.FromString(serialized)
    assert parsed.total_memory_bytes == pytest.approx(4.2e9)
    assert parsed.device_class == "jetson-orin-nano-4gb"
