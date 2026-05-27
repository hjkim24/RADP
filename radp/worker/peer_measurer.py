"""Worker→peer network measurement (Phase D1).

Used by the `MeasurePeer` RPC: the coordinator tells a worker "measure your
link to <peer_address>", and this module opens a temporary gRPC channel to
that peer, runs N rounds of Ping with two payload sizes, and derives:

  - latency   = median small-payload RTT / 2  (one-way constant overhead)
  - bandwidth = payload_bytes / max((big_rtt − small_rtt) / 2, ε)
                where (big_rtt − small_rtt)/2 is the one-way transit time
                attributable to the extra payload bytes.

Both directions go through the worker→peer link, so this measures the link
itself (not the coordinator's view).
"""

from __future__ import annotations

import os
import statistics
import time
from typing import Any

import grpc

from radp.common.proto import radp_pb2, radp_pb2_grpc

_SMALL_PAYLOAD_BYTES = 64
_DEFAULT_TIMEOUT_S = 10.0

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


def measure_peer(
    peer_address: str,
    payload_bytes: int,
    rounds: int,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_S,
) -> tuple[float, float]:
    """Return (bandwidth_bps, latency_seconds) for the local→peer link.

    Raises grpc.RpcError if the peer is unreachable or the Ping RPC fails.
    """
    if rounds <= 0:
        raise ValueError(f"rounds must be > 0, got {rounds}")
    if payload_bytes <= _SMALL_PAYLOAD_BYTES:
        raise ValueError(
            f"payload_bytes ({payload_bytes}) must exceed the baseline "
            f"small-payload size ({_SMALL_PAYLOAD_BYTES}) to separate "
            f"latency from bandwidth."
        )

    big_payload = os.urandom(payload_bytes)
    small_payload = os.urandom(_SMALL_PAYLOAD_BYTES)

    channel = grpc.insecure_channel(peer_address, options=_GRPC_OPTIONS)
    try:
        stub = radp_pb2_grpc.WorkerServiceStub(channel)
        small_rtts = _ping_rtts(stub, small_payload, rounds, timeout_seconds)
        big_rtts = _ping_rtts(stub, big_payload, rounds, timeout_seconds)
    finally:
        channel.close()

    small_median = statistics.median(small_rtts)
    big_median = statistics.median(big_rtts)
    latency = small_median / 2.0

    transit = (big_median - small_median) / 2.0
    bandwidth = float("inf") if transit <= 0 else payload_bytes / transit

    return bandwidth, latency


def _ping_rtts(
    stub: Any, payload: bytes, rounds: int, timeout_seconds: float
) -> list[float]:
    rtts: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        stub.Ping(
            radp_pb2.PingRequest(payload=payload, sent_ns=time.monotonic_ns()),
            timeout=timeout_seconds,
        )
        rtts.append(time.perf_counter() - t0)
    return rtts
