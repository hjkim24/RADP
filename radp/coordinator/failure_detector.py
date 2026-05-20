"""Heartbeat-based failure detection (plan.md §2.1, §2.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from radp.common.types import DeviceId


@dataclass
class HeartbeatRecord:
    device_id: DeviceId
    last_ts_ns: int
    free_memory_bytes: float


class FailureDetector:
    """Tracks the most recent heartbeat per device and fires a callback on timeout.

    Phase 3 will hook this into the gRPC `Heartbeat` RPC and into the
    recovery trigger flow (plan.md §2.2 step 1-2).
    """

    def __init__(
        self,
        timeout_seconds: float,
        on_failure: Callable[[DeviceId], None],
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.on_failure = on_failure
        self._records: dict[DeviceId, HeartbeatRecord] = {}

    def record(self, hb: HeartbeatRecord) -> None:
        """Store the latest heartbeat from a device."""
        raise NotImplementedError

    def tick(self, now_ns: int) -> list[DeviceId]:
        """Called periodically. Returns the device ids that just timed out
        (also invokes `on_failure` for each)."""
        raise NotImplementedError
