"""Multi-stage inference executor (Phase 2.10).

Adds KV-cache support: each worker maintains a ``DynamicCache`` per
``(request_id, stage_key)``. ``is_prefill=True`` clears the cache for that
key; subsequent decode-step ``run`` calls append to it. Cache lifetime ends
when the coordinator calls ``evict_request`` (typically right after the user
request finishes).

Model-family agnostic: block invocation is delegated to a
``ModelArchitecture`` adapter (OPT / LLaMA / Mistral) chosen by
``config.model_type``. The worker creates the per-architecture auxiliary
modules (e.g., LLaMA's ``rotary_emb``) once per model load.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import torch
from torch import nn
from transformers import AutoConfig, DynamicCache

from radp.common.architectures import ModelArchitecture, get_architecture
from radp.common.logging_utils import get_logger
from radp.common.model_utils import (
    DTYPE_MAP,
    load_stage_blocks,
    measure_resident_bytes,
)
from radp.common.tensor_io import decode, encode
from radp.common.types import DeviceId, LayerIdx, RequestId

log = get_logger(__name__)

StageKey = tuple[int, int]
CacheKey = tuple[RequestId, StageKey]

# Parity KV helpers (2026-07-20-parity-recovery): raw-bytes <-> DynamicCache
# layout is dtype-driven off the runner's configured `self.dtype`, never
# hardcoded fp16 — the round-trip test runs float32, the fleet runs float16.
_NP_DTYPE_MAP: dict[str, type] = {
    "float32": np.float32,
    "float16": np.float16,
}


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
        self._kv_shape_cache: tuple[int, int, type] | None = None
        self._config: Any | None = None
        self._arch: ModelArchitecture | None = None
        self._aux: dict[str, nn.Module] = {}
        # EXP-D3 Phase 1b: chain-tail head deployment. When a worker is the
        # chain tail and a head has been loaded, RunStage applies the
        # arch-specific `head` (final_layer_norm + project_out + lm_head)
        # plus greedy argmax sampling, returning the next token id
        # directly to the coord. Coord stays out of the per-token critical
        # path entirely. _head_decoder is a stub that just carries the
        # final_layer_norm / project_out submodules (matches the
        # ModelArchitecture.head() signature).
        self._head_lm_head: nn.Linear | None = None
        self._head_decoder: nn.Module | None = None

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

    def load_head(self, model_id: str) -> None:
        """Load the arch-specific head modules (final_layer_norm + project_out
        + lm_head) so this worker can serve as the chain tail with sampling.
        """
        from radp.common.model_utils import load_model
        with self._lock:
            self._ensure_model(model_id)
            handle = load_model(
                model_id, dtype=self.dtype, torch_device=self.torch_device,
            )
            # The arch.head() signature wants a `decoder` from which it pulls
            # `final_layer_norm` and `project_out`. For OPT that's
            # model.model.decoder; we keep a reference so the modules live
            # on the right device and stay attached for inference.
            decoder = (
                handle.model.model.decoder
                if hasattr(handle.model, "model") and hasattr(handle.model.model, "decoder")
                else getattr(handle.model, "model", handle.model)
            )
            self._head_decoder = decoder
            self._head_lm_head = handle.model.lm_head
            log.info(
                "worker=%s head loaded (rss=%.1f MB) — chain-tail sampling enabled",
                self.device_id,
                measure_resident_bytes() / (1024 * 1024),
            )

    @property
    def has_head(self) -> bool:
        return self._head_lm_head is not None and self._head_decoder is not None

    def sample_next_token(self, hidden: torch.Tensor) -> int:
        """Apply the loaded head + greedy argmax to the final hidden state."""
        if self._arch is None or not self.has_head:
            raise RuntimeError(
                f"worker={self.device_id} sample_next_token called but no head loaded"
            )
        with torch.no_grad():
            logits = self._arch.head(
                self._head_decoder, self._head_lm_head, hidden,
            )
            return int(torch.argmax(logits[0, -1, :]).item())

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
    # Parity KV helpers (raw bytes <-> DynamicCache; no forward pass)
    # ------------------------------------------------------------------
    def extract_kv_column(
        self, request_id: RequestId, *, start: LayerIdx, end: LayerIdx, position: int,
    ) -> bytes:
        """This stage's K,V at one position: per layer, K bytes then V bytes,
        CPU-contiguous, in the runner's configured dtype."""
        with self._lock:
            cache = self._require_kv_cache(request_id, start, end)
            parts: list[bytes] = []
            for layer_idx in self._stage_layer_indices(start, end):
                k = cache.key_cache[layer_idx][:, :, position : position + 1, :]
                v = cache.value_cache[layer_idx][:, :, position : position + 1, :]
                parts.append(k.cpu().contiguous().numpy().tobytes())
                parts.append(v.cpu().contiguous().numpy().tobytes())
            return b"".join(parts)

    def export_kv(self, request_id: RequestId, *, start: LayerIdx, end: LayerIdx) -> bytes:
        """This stage's full K,V (all positions), same per-layer K-then-V layout
        as `extract_kv_column`."""
        with self._lock:
            cache = self._require_kv_cache(request_id, start, end)
            parts: list[bytes] = []
            for layer_idx in self._stage_layer_indices(start, end):
                parts.append(cache.key_cache[layer_idx].cpu().contiguous().numpy().tobytes())
                parts.append(cache.value_cache[layer_idx].cpu().contiguous().numpy().tobytes())
            return b"".join(parts)

    def install_kv(
        self,
        request_id: RequestId,
        *,
        start: LayerIdx,
        end: LayerIdx,
        kv_bytes: bytes,
        num_positions: int,
    ) -> None:
        """Rebuild a DynamicCache for (request_id, (start,end)) from raw bytes
        produced by `export_kv`/reconstructed via parity XOR. No forward pass.
        Overwrites any existing cache for this key."""
        n_heads, head_dim, np_dtype = self._kv_shape()
        per_tensor = n_heads * int(num_positions) * head_dim
        buf = np.frombuffer(kv_bytes, dtype=np_dtype)
        cache = DynamicCache()
        offset = 0
        with self._lock:
            for layer_idx in self._stage_layer_indices(start, end):
                k_arr = buf[offset : offset + per_tensor].reshape(1, n_heads, num_positions, head_dim)
                offset += per_tensor
                v_arr = buf[offset : offset + per_tensor].reshape(1, n_heads, num_positions, head_dim)
                offset += per_tensor
                # .copy() detaches from the read-only `buf` view so the cache
                # owns writable storage (DynamicCache.update may later `cat`
                # onto these tensors during decode).
                k = torch.from_numpy(k_arr.copy()).to(self.torch_device)
                v = torch.from_numpy(v_arr.copy()).to(self.torch_device)
                cache.update(k, v, layer_idx)
            self._kv_cache[(request_id, (int(start), int(end)))] = cache

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
        # IMPORTANT: get_seq_length(layer_idx) — our cache only has slots filled
        # for THIS stage's layer indices (start-1 .. end-1, 0-based). Querying
        # the default layer 0 would return 0 for any non-first stage and
        # silently misalign RoPE positions. Use this stage's first layer index.
        first_layer_idx = int(start) - 1
        past_length = (
            int(cache.get_seq_length(layer_idx=first_layer_idx))
            if not is_prefill
            else 0
        )
        with torch.no_grad():
            hidden = self._run_blocks(blocks, hidden, attention_mask, cache, past_length)

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

    def run_tail_and_sample(
        self,
        request_id: RequestId,
        activation_blob: bytes,
        *,
        start: LayerIdx,
        end: LayerIdx,
        is_prefill: bool,
    ) -> int:
        """Chain-tail path: run the loaded stage, apply the head + greedy
        argmax in a single forward pass, return the next token id.

        Avoids the round-trip through an encoded bytes activation that
        ``run()`` produces — the head wants the tensor directly. Saves
        ~1-2 ms of CPU encode per token at the chain tail.
        """
        if not self.has_head:
            raise RuntimeError(
                f"worker={self.device_id} run_tail_and_sample called but no head loaded"
            )
        with self._lock:
            key = (int(start), int(end))
            blocks = self._stages.get(key)
            if blocks is None:
                raise RuntimeError(
                    f"worker={self.device_id} no stage loaded for layers[{start}..{end}]"
                )
            cache_key = (request_id, key)
            if is_prefill:
                self._kv_cache[cache_key] = DynamicCache()
            cache = self._kv_cache.setdefault(cache_key, DynamicCache())

        payload = decode(activation_blob)
        hidden = payload["hidden_states"].to(self.torch_device)
        attention_mask = payload["attention_mask"].to(self.torch_device)
        first_layer_idx = int(start) - 1
        past_length = (
            int(cache.get_seq_length(layer_idx=first_layer_idx))
            if not is_prefill
            else 0
        )
        with torch.no_grad():
            hidden = self._run_blocks(blocks, hidden, attention_mask, cache, past_length)
            assert self._arch is not None  # ensured by load_head/run path
            logits = self._arch.head(
                self._head_decoder, self._head_lm_head, hidden,
            )
            next_token = int(torch.argmax(logits[0, -1, :]).item())
        log.debug(
            "worker=%s request=%d TAIL+sample → token=%d cache_len=%d",
            self.device_id, request_id, next_token, cache.get_seq_length(),
        )
        return next_token

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _stage_layer_indices(self, start: LayerIdx, end: LayerIdx) -> list[int]:
        """0-based GLOBAL layer indices owned by this stage: start-1 .. end-1
        (matches the `first_layer_idx = int(start) - 1` convention in `run()`
        and the `global_idx - 1` block layer_idx in `load_stage_blocks`)."""
        return list(range(int(start) - 1, int(end)))

    def _require_kv_cache(self, request_id: RequestId, start: LayerIdx, end: LayerIdx) -> DynamicCache:
        cache = self._kv_cache.get((request_id, (int(start), int(end))))
        if cache is None:
            raise RuntimeError(
                f"worker={self.device_id} no KV cache for request={request_id} "
                f"layers[{start}..{end}]"
            )
        return cache

    def _kv_shape(self) -> tuple[int, int, type]:
        """(n_heads, head_dim, numpy dtype) for this stage's KV tensors,
        cached. dtype-driven off `self.dtype` (never hardcoded fp16); shapes
        read from the pinned model's config."""
        if self._kv_shape_cache is None:
            if self.dtype not in _NP_DTYPE_MAP:
                raise ValueError(
                    f"worker={self.device_id} dtype {self.dtype!r} has no raw-bytes "
                    f"KV mapping; choose from {sorted(_NP_DTYPE_MAP)}"
                )
            assert self._config is not None, "load_primary/load_backup must be called first"
            config = self._config
            n_heads = getattr(config, "num_key_value_heads", None) or config.num_attention_heads
            head_dim = getattr(config, "head_dim", None) or (
                config.hidden_size // config.num_attention_heads
            )
            self._kv_shape_cache = (int(n_heads), int(head_dim), _NP_DTYPE_MAP[self.dtype])
        return self._kv_shape_cache

    def _ensure_model(self, model_id: str) -> None:
        if self._model_id is None:
            config = AutoConfig.from_pretrained(model_id)
            self._config = config
            self._arch = get_architecture(config.model_type)
            self._aux = self._arch.make_aux(
                config, dtype=DTYPE_MAP[self.dtype], device=self.torch_device
            )
            self._model_id = model_id
            log.info(
                "worker=%s pinned to model %s (arch=%s)",
                self.device_id, model_id, self._arch.name,
            )
        elif self._model_id != model_id:
            raise ValueError(
                f"worker={self.device_id} already pinned to {self._model_id}; "
                f"refusing to switch to {model_id}"
            )

    def _run_blocks(
        self,
        blocks: nn.ModuleList,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache: DynamicCache,
        past_length: int,
    ) -> torch.Tensor:
        """Architecture-dispatched block invocation. Cache is mutated in place."""
        assert self._arch is not None, "load_primary/load_backup must be called first"
        arch = self._arch
        aux = self._aux
        for block in blocks:
            hidden = arch.run_block(block, hidden, attention_mask, cache, past_length, aux)
        return hidden
