"""Single-stage inference executor (plan.md §4.1 worker/stage_runner.py).

A stage = contiguous slice [start_layer, end_layer] of the transformer.
The runner owns a primary slot and (optionally) a reserve backup slot.
"""

from __future__ import annotations

from radp.common.types import LayerIdx, RequestId


class StageRunner:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    def load_primary(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        """Materialize the primary stage into device memory."""
        raise NotImplementedError

    def load_backup(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        """Load a backup stage into the reserve slot (kept dormant)."""
        raise NotImplementedError

    def promote_backup(self) -> None:
        """Swap reserve -> primary after a failure handoff."""
        raise NotImplementedError

    def run(self, request_id: RequestId, activation: bytes, is_prefill: bool) -> bytes:
        """Forward pass through the currently active primary stage."""
        raise NotImplementedError
