"""Activation mirror cache (plan.md §2.1 ActivationCache, §2.2 step 4).

The coordinator caches the activation BLOB flowing INTO each stage. On
worker failure the cached activation is replayed into the backup worker
instead of re-running the prefix of the pipeline.

Phase 3 implementation is a simple LRU bounded by total bytes, keyed by
(request_id, stage_key) where stage_key = (start_layer, end_layer).
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
        self._store: OrderedDict[CacheKey, bytes] = OrderedDict()
        self._bytes_used = 0

    # ------------------------------------------------------------------
    def put(self, request_id: RequestId, stage_key: StageKey, activation: bytes) -> None:
        key = (request_id, stage_key)
        with self._lock:
            existing = self._store.pop(key, None)
            if existing is not None:
                self._bytes_used -= len(existing)
            self._store[key] = activation
            self._bytes_used += len(activation)
            self._evict_if_needed()

    def get(self, request_id: RequestId, stage_key: StageKey) -> bytes | None:
        key = (request_id, stage_key)
        with self._lock:
            blob = self._store.get(key)
            if blob is not None:
                self._store.move_to_end(key)  # LRU bump
            return blob

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            keys = [k for k in self._store if k[0] == request_id]
            for k in keys:
                self._bytes_used -= len(self._store.pop(k))

    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes_used

    # ------------------------------------------------------------------
    def _evict_if_needed(self) -> None:
        # Caller holds the lock.
        while self._bytes_used > self.max_bytes and self._store:
            _, blob = self._store.popitem(last=False)
            self._bytes_used -= len(blob)
