"""Heartbeat-based failure detection (plan.md §2.1, §2.2).

Records the most recent heartbeat per device. A background ticker fires
``on_failure(device_id)`` exactly once per device whose latest heartbeat
is older than ``timeout_seconds``. A device that comes back (sends another
heartbeat) is removed from the "already-fired" set so it can be re-flagged
on a subsequent failure.

Coordinator may also call ``mark_failed(device_id)`` to trigger immediate
synchronous detection (e.g., after a gRPC error).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from radp.common.logging_utils import get_logger
from radp.common.types import DeviceId

log = get_logger(__name__)


@dataclass
class HeartbeatRecord:
    device_id: DeviceId
    last_ts_ns: int
    free_memory_bytes: float
    # Phase D additions — defaulted so existing call sites keep working
    total_memory_bytes: float = 0.0
    device_class: str = ""


class FailureDetector:
    def __init__(
        self,
        on_failure: Callable[[DeviceId], None],
        *,
        timeout_seconds: float = 5.0,
        tick_interval_seconds: float = 1.0,
    ) -> None:
        self.on_failure = on_failure
        self.timeout_seconds = timeout_seconds
        self.tick_interval_seconds = tick_interval_seconds
        self._lock = threading.Lock()
        self._records: dict[DeviceId, HeartbeatRecord] = {}
        self._fired: set[DeviceId] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def record(self, hb: HeartbeatRecord) -> None:
        with self._lock:
            self._records[hb.device_id] = hb
            self._fired.discard(hb.device_id)

    def snapshot_records(self) -> dict[DeviceId, HeartbeatRecord]:
        """Thread-safe shallow copy of the current heartbeat table.

        Consumers (e.g., ProfileOrchestrator) get a stable view without
        racing against incoming heartbeats.
        """
        with self._lock:
            return dict(self._records)

    def mark_failed(self, device_id: DeviceId) -> bool:
        """Immediately mark `device_id` as failed. Returns True if this is the
        first time we've flagged it (the caller should run recovery once)."""
        with self._lock:
            if device_id in self._fired:
                return False
            self._fired.add(device_id)
        log.warning("synchronous failure mark: %s", device_id)
        self._safe_callback(device_id)
        return True

    def tick(self, now_ns: int | None = None) -> list[DeviceId]:
        """Single sweep — exposed for tests. Returns devices flagged in this tick."""
        if now_ns is None:
            now_ns = time.time_ns()
        timeout_ns = int(self.timeout_seconds * 1e9)
        fired_now: list[DeviceId] = []
        with self._lock:
            for dev_id, rec in self._records.items():
                if dev_id in self._fired:
                    continue
                if now_ns - rec.last_ts_ns > timeout_ns:
                    self._fired.add(dev_id)
                    fired_now.append(dev_id)
        for dev_id in fired_now:
            log.warning("heartbeat timeout: %s", dev_id)
            self._safe_callback(dev_id)
        return fired_now

    # ------------------------------------------------------------------
    # Background ticker
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="failure-detector", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.tick_interval_seconds * 2)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("failure-detector tick crashed")
            self._stop.wait(self.tick_interval_seconds)

    def _safe_callback(self, device_id: DeviceId) -> None:
        try:
            self.on_failure(device_id)
        except Exception:  # noqa: BLE001
            log.exception("on_failure callback raised for %s", device_id)
