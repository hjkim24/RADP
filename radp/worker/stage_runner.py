"""Multi-stage inference executor (Phase 2.6).

Adds KV-cache support: each worker maintains a ``DynamicCache`` per
``(request_id, stage_key)``. ``is_prefill=True`` clears the cache for that
key; subsequent decode-step ``run`` calls append to it. Cache lifetime ends
when the coordinator calls ``evict_request`` (typically right after the user
request finishes).

OPT family only (block forward signature is OPT-specific). Per-stage
weights still loaded via ``load_stage_blocks``.
"""

from __future__ import annotations

import threading
from typing import Any

import torch
from torch import nn
from transformers import DynamicCache

from radp.common.logging_utils import get_logger
from radp.common.model_utils import (
    load_stage_blocks,
    measure_resident_bytes,
)
from radp.common.tensor_io import decode, encode
from radp.common.types import DeviceId, LayerIdx, RequestId

log = get_logger(__name__)

StageKey = tuple[int, int]
CacheKey = tuple[RequestId, StageKey]


class StageRunner:
    """Owns one or more loaded stages on a single device, plus per-request KV cache."""

    def __init__(
        self,
        device_id: DeviceId,
        *,
        torch_device: str = "cpu",
        dtype: str = "float32",
    ) -> None:
        self.device_id = device_id
        self.torch_device = torch_device
        self.dtype = dtype
        self._lock = threading.Lock()
        self._model_id: str | None = None
        self._primary: StageKey | None = None
        self._stages: dict[StageKey, nn.ModuleList] = {}
        self._backup_for: dict[StageKey, DeviceId] = {}
        self._promoted: set[StageKey] = set()
        self._kv_cache: dict[CacheKey, DynamicCache] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_primary(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        with self._lock:
            self._ensure_model(model_id)
            key = (int(start), int(end))
            blocks = load_stage_blocks(
                model_id, start, end, dtype=self.dtype, torch_device=self.torch_device
            )
            self._stages[key] = blocks
            self._primary = key
            log.info(
                "worker=%s primary loaded layers[%d..%d] (rss=%.1f MB)",
                self.device_id, start, end,
                measure_resident_bytes() / (1024 * 1024),
            )

    def load_backup(
        self,
        model_id: str,
        start: LayerIdx,
        end: LayerIdx,
        *,
        for_device_id: DeviceId,
    ) -> None:
        with self._lock:
            self._ensure_model(model_id)
            key = (int(start), int(end))
            if key in self._stages:
                self._backup_for[key] = for_device_id
                log.info(
                    "worker=%s reusing existing stage layers[%d..%d] as backup for %s",
                    self.device_id, start, end, for_device_id,
                )
                return
            blocks = load_stage_blocks(
                model_id, start, end, dtype=self.dtype, torch_device=self.torch_device
            )
            self._stages[key] = blocks
            self._backup_for[key] = for_device_id
            log.info(
                "worker=%s backup loaded for %s layers[%d..%d] (rss=%.1f MB)",
                self.device_id, for_device_id, start, end,
                measure_resident_bytes() / (1024 * 1024),
            )

    def promote_backup(self, for_device_id: DeviceId) -> None:
        with self._lock:
            keys = [k for k, owner in self._backup_for.items() if owner == for_device_id]
            if not keys:
                raise RuntimeError(
                    f"worker={self.device_id} no backup loaded for {for_device_id}"
                )
            for k in keys:
                self._promoted.add(k)
            log.info(
                "worker=%s promoted backup for %s: stages=%s",
                self.device_id, for_device_id, keys,
            )

    def evict_request(self, request_id: RequestId) -> None:
        """Drop the KV cache for `request_id` across all stages."""
        with self._lock:
            keys = [k for k in self._kv_cache if k[0] == request_id]
            for k in keys:
                del self._kv_cache[k]
        if keys:
            log.debug("worker=%s evicted KV cache for request %d (%d stages)",
                      self.device_id, request_id, len(keys))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(
        self,
        request_id: RequestId,
        activation_blob: bytes,
        *,
        start: LayerIdx,
        end: LayerIdx,
        is_prefill: bool,
    ) -> bytes:
        with self._lock:
            key = (int(start), int(end))
            blocks = self._stages.get(key)
            if blocks is None:
                raise RuntimeError(
                    f"worker={self.device_id} no stage loaded for layers[{start}..{end}]"
                )
            cache_key = (request_id, key)
            if is_prefill:
                # Reset cache for this request+stage on a fresh prefill.
                self._kv_cache[cache_key] = DynamicCache()
            cache = self._kv_cache.setdefault(cache_key, DynamicCache())

        payload = decode(activation_blob)
        hidden = payload["hidden_states"].to(self.torch_device)
        attention_mask = payload["attention_mask"].to(self.torch_device)
        with torch.no_grad():
            hidden = self._run_blocks(blocks, hidden, attention_mask, cache)

        out_payload: dict[str, torch.Tensor] = {
            "hidden_states": hidden.detach().cpu(),
            "attention_mask": attention_mask.detach().cpu(),
        }
        log.debug(
            "worker=%s request=%d layers[%d..%d] prefill=%s shape=%s cache_len=%d",
            self.device_id, request_id, start, end, is_prefill, tuple(hidden.shape),
            cache.get_seq_length() if cache is not None else 0,
        )
        return encode(out_payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _ensure_model(self, model_id: str) -> None:
        if self._model_id is None:
            self._model_id = model_id
            log.info("worker=%s pinned to model %s", self.device_id, model_id)
        elif self._model_id != model_id:
            raise ValueError(
                f"worker={self.device_id} already pinned to {self._model_id}; "
                f"refusing to switch to {model_id}"
            )

    @staticmethod
    def _run_blocks(
        blocks: nn.ModuleList,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache: DynamicCache,
    ) -> torch.Tensor:
        """OPT-only block invocation with shared KV cache mutated in place."""
        for block in blocks:
            out: Any = block(
                hidden,
                attention_mask=attention_mask,
                past_key_values=cache,
                use_cache=True,
            )
            # OPT 5.x returns just the hidden tensor; older versions returned a tuple.
            hidden = out[0] if isinstance(out, tuple) else out
        return hidden
