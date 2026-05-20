"""Tests for ActivationCache (plan.md §2.1)."""

from __future__ import annotations

from radp.common.types import RequestId
from radp.coordinator.activation_cache import ActivationCache


def test_put_get_basic() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.put(RequestId(1), (1, 6), b"hello")
    assert c.get(RequestId(1), (1, 6)) == b"hello"
    assert c.get(RequestId(2), (1, 6)) is None


def test_overwrite_updates_bytes() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.put(RequestId(1), (1, 6), b"aaaa")
    c.put(RequestId(1), (1, 6), b"bb")
    assert c.bytes_used() == 2
    assert c.get(RequestId(1), (1, 6)) == b"bb"


def test_lru_evicts_oldest() -> None:
    c = ActivationCache(max_bytes=6)
    c.put(RequestId(1), (1, 1), b"aaa")  # 3 bytes
    c.put(RequestId(2), (1, 1), b"bbb")  # +3, exactly at cap
    c.put(RequestId(3), (1, 1), b"cc")   # forces eviction of oldest (R=1)
    assert c.get(RequestId(1), (1, 1)) is None
    assert c.get(RequestId(2), (1, 1)) == b"bbb"
    assert c.get(RequestId(3), (1, 1)) == b"cc"


def test_evict_request_drops_all_stage_keys() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.put(RequestId(7), (1, 6), b"first")
    c.put(RequestId(7), (7, 12), b"second")
    c.put(RequestId(8), (1, 6), b"keep")
    c.evict_request(RequestId(7))
    assert c.get(RequestId(7), (1, 6)) is None
    assert c.get(RequestId(7), (7, 12)) is None
    assert c.get(RequestId(8), (1, 6)) == b"keep"
