"""Tests for ActivationCache (plan.md §2.1, Phase 2.7 append-history API)."""

from __future__ import annotations

from radp.common.types import RequestId
from radp.coordinator.activation_cache import ActivationCache


def test_append_and_get_history_in_order() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.append(RequestId(1), (1, 6), b"prefill")
    c.append(RequestId(1), (1, 6), b"decode1")
    c.append(RequestId(1), (1, 6), b"decode2")
    assert c.get_history(RequestId(1), (1, 6)) == [b"prefill", b"decode1", b"decode2"]


def test_history_isolated_per_request_and_stage() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.append(RequestId(1), (1, 6), b"r1_s1_a")
    c.append(RequestId(1), (7, 12), b"r1_s2_a")
    c.append(RequestId(2), (1, 6), b"r2_s1_a")
    assert c.get_history(RequestId(1), (1, 6)) == [b"r1_s1_a"]
    assert c.get_history(RequestId(1), (7, 12)) == [b"r1_s2_a"]
    assert c.get_history(RequestId(2), (1, 6)) == [b"r2_s1_a"]
    assert c.get_history(RequestId(2), (7, 12)) == []


def test_evict_request_drops_all_stage_histories() -> None:
    c = ActivationCache(max_bytes=1_000_000)
    c.append(RequestId(7), (1, 6), b"a")
    c.append(RequestId(7), (7, 12), b"b")
    c.append(RequestId(8), (1, 6), b"c")
    c.evict_request(RequestId(7))
    assert c.get_history(RequestId(7), (1, 6)) == []
    assert c.get_history(RequestId(7), (7, 12)) == []
    assert c.get_history(RequestId(8), (1, 6)) == [b"c"]
    assert c.bytes_used() == 1


def test_lru_evicts_oldest_request_when_over_cap() -> None:
    c = ActivationCache(max_bytes=10)
    c.append(RequestId(1), (1, 1), b"a" * 5)
    c.append(RequestId(2), (1, 1), b"b" * 5)
    c.append(RequestId(3), (1, 1), b"c" * 4)  # 5+5+4=14 > 10; request 1 evicted
    assert c.get_history(RequestId(1), (1, 1)) == []
    assert c.get_history(RequestId(2), (1, 1)) == [b"bbbbb"]
    assert c.get_history(RequestId(3), (1, 1)) == [b"cccc"]


def test_lru_recency_via_get_history() -> None:
    """Reading a request's history should make it most-recent (so it survives)."""
    c = ActivationCache(max_bytes=10)
    c.append(RequestId(1), (1, 1), b"a" * 5)
    c.append(RequestId(2), (1, 1), b"b" * 5)
    # Touch request 1 to mark it MRU.
    _ = c.get_history(RequestId(1), (1, 1))
    c.append(RequestId(3), (1, 1), b"c" * 4)  # request 2 should be evicted now
    assert c.has_history(RequestId(1), (1, 1))
    assert not c.has_history(RequestId(2), (1, 1))
    assert c.has_history(RequestId(3), (1, 1))
