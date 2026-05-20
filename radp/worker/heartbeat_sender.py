"""Periodic heartbeat publisher (plan.md §4.1 worker/heartbeat_sender.py)."""

from __future__ import annotations

from radp.common.types import DeviceId


class HeartbeatSender:
    def __init__(
        self,
        device_id: DeviceId,
        coordinator_address: str,
        interval_seconds: float,
    ) -> None:
        self.device_id = device_id
        self.coordinator_address = coordinator_address
        self.interval_seconds = interval_seconds

    def start(self) -> None:
        """Kick off the background loop that pushes heartbeats."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _measure_free_memory(self) -> float:
        """Best-effort free memory query (bytes). Phase 3 fills in per-Jetson logic."""
        raise NotImplementedError
