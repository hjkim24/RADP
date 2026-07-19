"""Cross-stage XOR parity cache (design spec 2026-07-20-parity-recovery).

Maintains ONE parity blob P per (request, position) = XOR of every stage's
zero-padded raw KV-column bytes (RAID-5 across pipeline stages). Stores only P
plus a per-(request, position) set of contributing stages, so a position is
usable for reconstruction only once all `num_stages` stages have contributed
exactly once (duplicate (stage, position) pushes are ignored).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np

from radp.common.types import RequestId

StageKey = tuple[int, int]


class _Entry:
    __slots__ = ("parity", "contributors")

    def __init__(self, size: int) -> None:
        self.parity = np.zeros(size, dtype=np.uint8)
        self.contributors: set[StageKey] = set()


class ParityCache:
    def __init__(self, num_stages: int, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.num_stages = num_stages
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._by_request: OrderedDict[RequestId, dict[int, _Entry]] = OrderedDict()
        self._bytes_used = 0

    def xor_in(
        self, request_id: RequestId, stage_key: StageKey,
        position: int, column_bytes: bytes,
    ) -> None:
        col = np.frombuffer(column_bytes, dtype=np.uint8)
        with self._lock:
            positions = self._by_request.setdefault(request_id, {})
            self._by_request.move_to_end(request_id)
            entry = positions.get(position)
            if entry is None:
                entry = _Entry(col.size)
                positions[position] = entry
                self._bytes_used += col.size
            if stage_key in entry.contributors:
                return  # dedup — never double-XOR
            if col.size > entry.parity.size:  # grow to new max, zero-padded
                grown = np.zeros(col.size, dtype=np.uint8)
                grown[: entry.parity.size] = entry.parity
                self._bytes_used += col.size - entry.parity.size
                entry.parity = grown
            entry.parity[: col.size] ^= col
            entry.contributors.add(stage_key)
            self._evict_if_needed_locked()

    def is_complete(self, request_id: RequestId, position: int) -> bool:
        with self._lock:
            positions = self._by_request.get(request_id)
            if not positions or position not in positions:
                return False
            return len(positions[position].contributors) == self.num_stages

    def get_parity(self, request_id: RequestId, position: int) -> bytes | None:
        with self._lock:
            positions = self._by_request.get(request_id)
            if not positions or position not in positions:
                return None
            return positions[position].parity.tobytes()

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            positions = self._by_request.pop(request_id, None)
            if positions:
                self._bytes_used -= sum(e.parity.size for e in positions.values())

    def _evict_if_needed_locked(self) -> None:
        # Never evict the sole in-flight request: xor_in() calls move_to_end(),
        # making it both oldest and newest if alone. Evicting it would destroy
        # the parity just added (and actively maintained for recovery), with no
        # byte savings. Once a second request arrives, normal LRU eviction resumes.
        while self._bytes_used > self.max_bytes and len(self._by_request) > 1:
            _, positions = self._by_request.popitem(last=False)  # oldest request
            self._bytes_used -= sum(e.parity.size for e in positions.values())
