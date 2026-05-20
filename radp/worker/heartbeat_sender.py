"""Periodic heartbeat publisher (plan.md §2.1, §4.1)."""

from __future__ import annotations

import threading

import psutil

from radp.common.logging_utils import get_logger
from radp.common.protocol import CoordinatorClient
from radp.common.types import DeviceId

log = get_logger(__name__)


class HeartbeatSender:
    """Background thread that posts heartbeats to the coordinator every interval."""

    def __init__(
        self,
        device_id: DeviceId,
        coordinator_address: str,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        self.device_id = device_id
        self.coordinator_address = coordinator_address
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name=f"heartbeat-{self.device_id}", daemon=True
        )
        self._thread.start()
        log.info(
            "heartbeat thread started: device=%s coord=%s interval=%.1fs",
            self.device_id, self.coordinator_address, self.interval_seconds,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds * 2)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._send_one()
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat send failed: %s", e)
            self._stop.wait(self.interval_seconds)

    def _send_one(self) -> None:
        free_bytes = self._measure_free_memory()
        with CoordinatorClient(self.coordinator_address) as c:
            c.heartbeat(self.device_id, free_bytes)

    @staticmethod
    def _measure_free_memory() -> float:
        return float(psutil.virtual_memory().available)
