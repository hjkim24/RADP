"""Activation mirror cache (plan.md §2.1 ActivationCache, §2.2 step 4).

Phase 2.7: stores the FULL HISTORY of activations into each stage during a
request — one entry per pipeline step (prefill, then one per decode token).
On failure of worker w mid-generation, the coordinator replays w's history
to the backup worker, which rebuilds its DynamicCache to exactly match
what w had — without touching the surviving workers' caches.

EXP-D3 Phase 2 extension: writes are now positioned (``put(position, blob)``
keyed by the worker's per-(request, stage) sequence number) so the
``MirrorActivation`` RPCs that workers fire-and-forget can arrive out of
order from in-flight gRPCs without scrambling replay order. ``append``
remains for the local first-stage path used inside the gateway.

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
        # OrderedDict by request_id (recency) ->
        #   dict[StageKey, dict[position, bytes]]
        # The inner dict is keyed by position so out-of-order arrivals from
        # in-flight MirrorActivation RPCs collate correctly. get_history()
        # returns the contiguous prefix of positions starting at 0.
        self._by_request: OrderedDict[
            RequestId, dict[StageKey, dict[int, bytes]]
        ] = OrderedDict()
        self._bytes_used = 0

    # ------------------------------------------------------------------
    def append(self, request_id: RequestId, stage_key: StageKey, activation: bytes) -> None:
        """Append at the next slot of (request, stage). Used by the gateway
        for the first-stage input (locally generated; always in order)."""
        with self._lock:
            slots = self._slots(request_id, stage_key)
            position = len(slots)
            self._store_unlocked(slots, position, activation)

    def put(
        self,
        request_id: RequestId,
        stage_key: StageKey,
        position: int,
        activation: bytes,
    ) -> bool:
        """Insert at an explicit position (used by MirrorActivation handler).

        Idempotent — duplicate (request, stage, position) is ignored.
        Returns True iff the entry was newly added.
        """
        with self._lock:
            slots = self._slots(request_id, stage_key)
            if position in slots:
                return False
            self._store_unlocked(slots, position, activation)
            return True

    def get_history(self, request_id: RequestId, stage_key: StageKey) -> list[bytes]:
        """Return the contiguous prefix of positions [0, 1, …]. Stops at the
        first gap, so a stalled mirror won't cause replay to skip a step."""
        with self._lock:
            req_map = self._by_request.get(request_id)
            if req_map is None:
                return []
            self._by_request.move_to_end(request_id)
            slots = req_map.get(stage_key)
            if not slots:
                return []
            out: list[bytes] = []
            i = 0
            while i in slots:
                out.append(slots[i])
                i += 1
            return out

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            req_map = self._by_request.pop(request_id, None)
            if req_map is None:
                return
            for slots in req_map.values():
                for blob in slots.values():
                    self._bytes_used -= len(blob)

    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes_used

    def has_history(self, request_id: RequestId, stage_key: StageKey) -> bool:
        with self._lock:
            req_map = self._by_request.get(request_id)
            return bool(req_map and req_map.get(stage_key))

    # ------------------------------------------------------------------
    def _slots(
        self, request_id: RequestId, stage_key: StageKey
    ) -> dict[int, bytes]:
        # Caller holds the lock. Returns the position-keyed dict for
        # (request_id, stage_key), creating entries lazily and LRU-bumping.
        req_map = self._by_request.get(request_id)
        if req_map is None:
            req_map = {}
            self._by_request[request_id] = req_map
        self._by_request.move_to_end(request_id)
        return req_map.setdefault(stage_key, {})

    def _store_unlocked(
        self, slots: dict[int, bytes], position: int, activation: bytes
    ) -> None:
        slots[position] = activation
        self._bytes_used += len(activation)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        # Caller holds the lock. Drop oldest whole requests until under cap.
        while self._bytes_used > self.max_bytes and self._by_request:
            _, req_map = self._by_request.popitem(last=False)
            for slots in req_map.values():
                for blob in slots.values():
                    self._bytes_used -= len(blob)
