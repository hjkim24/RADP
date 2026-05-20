"""Pairwise bandwidth + latency probe across the cluster."""

from __future__ import annotations

from radp.common.types import DeviceProfile, NetworkProfile


def profile_network(devices: list[DeviceProfile]) -> NetworkProfile:
    """Round-robin pairs of devices and measure bandwidth + RTT.

    Implementation (Phase 1):
      - Use iperf3 (or a built-in gRPC blob-echo) per pair.
      - Repeat each pair `repeat` times, take median.
    """
    raise NotImplementedError
