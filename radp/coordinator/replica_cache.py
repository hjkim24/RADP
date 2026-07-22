"""Full-KV replication cache (design spec 2026-07-22-replication-baseline).

The zero-recompute baseline against which parity is compared. Where
``ParityCache`` folds every stage's KV column into ONE XOR blob per position,
``ReplicaCache`` keeps each stage's columns verbatim, keyed by stage. Recovery
reads the dead stage's own stored columns directly — no survivor fetch, no XOR.

Storage is Σ(stage KV) vs parity's max(stage KV): that gap is the whole point
of the comparison. TTR is similar (both reload, no recompute).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from radp.common.types import RequestId

StageKey = tuple[int, int]


class ReplicaCache:
    def __init__(self, num_stages: int, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.num_stages = num_stages
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        # request -> stage_key -> {position: column_bytes}
        self._by_request: OrderedDict[
            RequestId, dict[StageKey, dict[int, bytes]]
        ] = OrderedDict()
        self._bytes_used = 0

    def store(
        self, request_id: RequestId, stage_key: StageKey,
        position: int, column_bytes: bytes,
    ) -> None:
        with self._lock:
            stages = self._by_request.setdefault(request_id, {})
            self._by_request.move_to_end(request_id)
            positions = stages.setdefault(stage_key, {})
            if position in positions:
                return  # dedup — re-arriving (stage, position) ignored
            positions[position] = column_bytes
            self._bytes_used += len(column_bytes)
            self._evict_if_needed_locked()

    def get_stage_kv(
        self, request_id: RequestId, stage_key: StageKey
    ) -> bytes | None:
        with self._lock:
            stages = self._by_request.get(request_id)
            if not stages or stage_key not in stages:
                return None
            positions = stages[stage_key]
            return b"".join(positions[p] for p in sorted(positions))

    def is_complete(
        self, request_id: RequestId, stage_key: StageKey, up_to_position: int
    ) -> bool:
        with self._lock:
            stages = self._by_request.get(request_id)
            if not stages or stage_key not in stages:
                return False
            positions = stages[stage_key]
            return all(p in positions for p in range(up_to_position + 1))

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            stages = self._by_request.pop(request_id, None)
            if stages:
                self._bytes_used -= sum(
                    len(b) for positions in stages.values() for b in positions.values()
                )

    def _evict_if_needed_locked(self) -> None:
        # Never evict the sole in-flight request: store() calls move_to_end(),
        # making it both oldest and newest if alone. Evicting it would destroy
        # the KV just added (actively maintained for recovery) with no savings.
        while self._bytes_used > self.max_bytes and len(self._by_request) > 1:
            _, stages = self._by_request.popitem(last=False)  # oldest request
            self._bytes_used -= sum(
                len(b) for positions in stages.values() for b in positions.values()
            )
