"""Activation mirror cache (plan.md §2.1 ActivationCache, §2.2 step 4).

Phase 2.7: stores the FULL HISTORY of activations into each stage during a
request — one entry per pipeline step (prefill, then one per decode token).
On failure of worker w mid-generation, the coordinator replays w's history
to the backup worker, which rebuilds its DynamicCache to exactly match
what w had — without touching the surviving workers' caches.

Bounded by total bytes across all (request, stage) keys; oldest WHOLE
requests are evicted first (per-request granularity, not per-entry, to
preserve replay correctness).
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from radp.common.types import RequestId

StageKey = tuple[int, int]
CacheKey = tuple[RequestId, StageKey]


class ActivationCache:
    def __init__(self, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        # OrderedDict by request_id (recency) -> dict[StageKey, list[bytes]]
        self._by_request: OrderedDict[RequestId, dict[StageKey, list[bytes]]] = OrderedDict()
        self._bytes_used = 0

    # ------------------------------------------------------------------
    def append(self, request_id: RequestId, stage_key: StageKey, activation: bytes) -> None:
        """Append a new activation to the (request, stage) history."""
        with self._lock:
            req_map = self._by_request.get(request_id)
            if req_map is None:
                req_map = {}
                self._by_request[request_id] = req_map
            self._by_request.move_to_end(request_id)  # LRU bump
            history = req_map.setdefault(stage_key, [])
            history.append(activation)
            self._bytes_used += len(activation)
            self._evict_if_needed()

    def get_history(self, request_id: RequestId, stage_key: StageKey) -> list[bytes]:
        """Return the cached activations in append order. Empty list if absent."""
        with self._lock:
            req_map = self._by_request.get(request_id)
            if req_map is None:
                return []
            self._by_request.move_to_end(request_id)
            return list(req_map.get(stage_key, ()))

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            req_map = self._by_request.pop(request_id, None)
            if req_map is None:
                return
            for history in req_map.values():
                for blob in history:
                    self._bytes_used -= len(blob)

    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes_used

    def has_history(self, request_id: RequestId, stage_key: StageKey) -> bool:
        with self._lock:
            req_map = self._by_request.get(request_id)
            return bool(req_map and stage_key in req_map and req_map[stage_key])

    # ------------------------------------------------------------------
    def _evict_if_needed(self) -> None:
        # Caller holds the lock. Drop oldest whole requests until under cap.
        while self._bytes_used > self.max_bytes and self._by_request:
            _, req_map = self._by_request.popitem(last=False)
            for history in req_map.values():
                for blob in history:
                    self._bytes_used -= len(blob)
