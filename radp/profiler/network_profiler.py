"""Pairwise bandwidth + latency probe across the cluster.

Live probing requires the gRPC worker fleet to be up (Phase 2 dependency).
Phase 1.5 ships only the offline path: load a hand-authored NetworkProfile
from JSON, or construct one programmatically from your LAN spec.
"""

from __future__ import annotations

import json
from pathlib import Path

from radp.common.types import DeviceId, DeviceProfile, NetworkProfile


def profile_network(devices: list[DeviceProfile]) -> NetworkProfile:
    """Live measurement. Requires Phase 2 (workers running with gRPC echo)."""
    raise NotImplementedError(
        "Live network profiling requires the worker fleet (Phase 2). "
        "For now, use load_network_profile() with a JSON spec or build "
        "NetworkProfile manually from known LAN characteristics."
    )


def save_network_profile(profile: NetworkProfile, path: str | Path) -> None:
    """Serialize a NetworkProfile to JSON.

    Format:
      { "pairs": [ {"src": "...", "dst": "...", "bandwidth_bps": ..., "latency_seconds": ...}, ... ] }
    """
    pairs = []
    seen: set[tuple[str, str]] = set()
    for (src, dst), bw in profile.bandwidth.items():
        seen.add((str(src), str(dst)))
        pairs.append(
            {
                "src": str(src),
                "dst": str(dst),
                "bandwidth_bps": float(bw),
                "latency_seconds": float(profile.latency.get((src, dst), 0.0)),
            }
        )
    # Include latency-only entries if any pair has no bandwidth recorded.
    for (src, dst), lat in profile.latency.items():
        if (str(src), str(dst)) in seen:
            continue
        pairs.append(
            {
                "src": str(src),
                "dst": str(dst),
                "bandwidth_bps": 0.0,
                "latency_seconds": float(lat),
            }
        )
    Path(path).write_text(json.dumps({"pairs": pairs}, indent=2))


def load_network_profile(path: str | Path) -> NetworkProfile:
    """Load a NetworkProfile previously saved by save_network_profile or hand-written."""
    raw = json.loads(Path(path).read_text())
    bandwidth: dict[tuple[DeviceId, DeviceId], float] = {}
    latency: dict[tuple[DeviceId, DeviceId], float] = {}
    for pair in raw["pairs"]:
        key = (DeviceId(str(pair["src"])), DeviceId(str(pair["dst"])))
        bandwidth[key] = float(pair["bandwidth_bps"])
        latency[key] = float(pair["latency_seconds"])
    return NetworkProfile(bandwidth=bandwidth, latency=latency)


def uniform_network(
    devices: list[DeviceProfile],
    *,
    bandwidth_bps: float,
    latency_seconds: float,
) -> NetworkProfile:
    """Construct a NetworkProfile assuming every pair has identical characteristics.

    Convenient default for tests / homogeneous LANs.
    """
    bandwidth: dict[tuple[DeviceId, DeviceId], float] = {}
    latency: dict[tuple[DeviceId, DeviceId], float] = {}
    for src in devices:
        for dst in devices:
            if src.id == dst.id:
                continue
            bandwidth[(src.id, dst.id)] = bandwidth_bps
            latency[(src.id, dst.id)] = latency_seconds
    return NetworkProfile(bandwidth=bandwidth, latency=latency)
