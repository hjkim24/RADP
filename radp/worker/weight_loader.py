"""Dynamic weight loader: pulls layer weights on demand, manages reserve slot."""

from __future__ import annotations

from radp.common.types import LayerIdx


class WeightLoader:
    """Fetches layer weights from an origin (HF hub or coordinator-hosted mirror)."""

    def __init__(self, model_id: str, cache_dir: str) -> None:
        self.model_id = model_id
        self.cache_dir = cache_dir

    def fetch(self, start: LayerIdx, end: LayerIdx) -> str:
        """Download (or read from cache) layers [start, end] and return a local path."""
        raise NotImplementedError

    def evict(self, start: LayerIdx, end: LayerIdx) -> None:
        """Free memory occupied by the given layer range."""
        raise NotImplementedError
