"""Activation mirror cache (plan.md §2.1 ActivationCache, §2.2 step 4).

The coordinator caches the input activation to every stage. On worker failure,
the cached activation for stage j is replayed into the backup k, avoiding a
full re-prefill from the prompt.
"""

from __future__ import annotations

from radp.common.types import DeviceId, RequestId


class ActivationCache:
    """Per-(request, stage) activation store with bounded retention."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes

    def put(self, request_id: RequestId, device: DeviceId, activation: bytes) -> None:
        """Store the activation that flowed INTO this stage for this request."""
        raise NotImplementedError

    def get(self, request_id: RequestId, device: DeviceId) -> bytes | None:
        """Retrieve the activation for replay. None if evicted."""
        raise NotImplementedError

    def evict_request(self, request_id: RequestId) -> None:
        """Drop all activations for a completed request."""
        raise NotImplementedError
