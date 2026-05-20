"""Tests for FailureDetector heartbeat tracking + tick logic."""

from __future__ import annotations

from radp.common.types import DeviceId
from radp.coordinator.failure_detector import FailureDetector, HeartbeatRecord


def test_tick_fires_after_timeout() -> None:
    fired: list[DeviceId] = []
    fd = FailureDetector(on_failure=fired.append, timeout_seconds=1.0)
    base = 1_000_000_000_000
    fd.record(HeartbeatRecord(DeviceId("d1"), base, 0.0))
    fd.record(HeartbeatRecord(DeviceId("d2"), base, 0.0))

    # Just before timeout: nothing fires.
    assert fd.tick(now_ns=base + int(0.9e9)) == []
    assert fired == []

    # Past timeout for both.
    out = fd.tick(now_ns=base + int(1.5e9))
    assert set(out) == {DeviceId("d1"), DeviceId("d2")}
    assert set(fired) == {DeviceId("d1"), DeviceId("d2")}


def test_tick_does_not_refire_for_same_device() -> None:
    fired: list[DeviceId] = []
    fd = FailureDetector(on_failure=fired.append, timeout_seconds=1.0)
    base = 1_000_000_000_000
    fd.record(HeartbeatRecord(DeviceId("d1"), base, 0.0))
    fd.tick(now_ns=base + int(2e9))
    fd.tick(now_ns=base + int(3e9))
    assert fired == [DeviceId("d1")]


def test_new_heartbeat_re_arms_detection() -> None:
    fired: list[DeviceId] = []
    fd = FailureDetector(on_failure=fired.append, timeout_seconds=1.0)
    base = 1_000_000_000_000
    fd.record(HeartbeatRecord(DeviceId("d1"), base, 0.0))
    fd.tick(now_ns=base + int(2e9))
    assert fired == [DeviceId("d1")]
    # device recovers and starts sending heartbeats again
    fd.record(HeartbeatRecord(DeviceId("d1"), base + int(3e9), 0.0))
    fd.tick(now_ns=base + int(5e9))  # 2s after new heartbeat -> timeout again
    assert fired == [DeviceId("d1"), DeviceId("d1")]


def test_mark_failed_fires_immediately() -> None:
    fired: list[DeviceId] = []
    fd = FailureDetector(on_failure=fired.append, timeout_seconds=10.0)
    assert fd.mark_failed(DeviceId("d1")) is True
    assert fired == [DeviceId("d1")]
    # Idempotent.
    assert fd.mark_failed(DeviceId("d1")) is False
    assert fired == [DeviceId("d1")]
