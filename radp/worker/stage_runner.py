"""Multi-stage inference executor (Phase 3).

A worker can host MULTIPLE loaded stages: one primary (the layers it was
originally assigned by the DP), zero or more backups (stages of peers j
for which R(j) == self, preloaded so failure handoff is instant).

Each ``run(start, end, ...)`` call selects which loaded stage to execute,
identified by its (start_layer, end_layer) range. This lets the coordinator
re-route requests through the surviving worker without changing the API.

Phase 3 simplification (carried over from Phase 2 MVP):
  - Every worker holds the FULL model in memory. ``load_primary`` /
    ``load_backup`` just record which slice that stage refers to.
    Phase 2.5 will swap in real per-stage weight loading.
"""

from __future__ import annotations

import threading
from typing import Any

import torch
from torch import nn

from radp.common.logging_utils import get_logger
from radp.common.model_utils import ModelHandle, get_transformer_layers, load_model
from radp.common.tensor_io import decode, encode
from radp.common.types import DeviceId, LayerIdx, RequestId

log = get_logger(__name__)

StageKey = tuple[int, int]  # (start_layer, end_layer)


class StageRunner:
    """Owns one or more loaded stages on a single device."""

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
        self._handle: ModelHandle | None = None
        self._primary: StageKey | None = None
        # All loaded stages (primary + backups) keyed by (start, end).
        self._stages: dict[StageKey, nn.ModuleList] = {}
        # backup_for[stage_key] = original owner device id (for diagnostics)
        self._backup_for: dict[StageKey, DeviceId] = {}
        # Stages whose backup has been promoted (ready to serve).
        self._promoted: set[StageKey] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_primary(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        with self._lock:
            self._ensure_model(model_id)
            self._validate_range(start, end)
            key = (int(start), int(end))
            self._stages[key] = self._slice_blocks(start, end)
            self._primary = key
            log.info(
                "worker=%s primary loaded layers[%d..%d]",
                self.device_id, start, end,
            )

    def load_backup(
        self,
        model_id: str,
        start: LayerIdx,
        end: LayerIdx,
        *,
        for_device_id: DeviceId,
    ) -> None:
        """Preload another node's stage into our reserve slot."""
        with self._lock:
            self._ensure_model(model_id)
            self._validate_range(start, end)
            key = (int(start), int(end))
            self._stages[key] = self._slice_blocks(start, end)
            self._backup_for[key] = for_device_id
            log.info(
                "worker=%s backup loaded for %s layers[%d..%d]",
                self.device_id, for_device_id, start, end,
            )

    def promote_backup(self, for_device_id: DeviceId) -> None:
        """Mark every backup stage owned-for `for_device_id` as ready to serve.

        Currently a bookkeeping flip — the stage is already in memory from
        load_backup; we just record that the coordinator can route real
        traffic to it.
        """
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

        payload = decode(activation_blob)
        hidden = payload["hidden_states"].to(self.torch_device)
        attention_mask = payload["attention_mask"].to(self.torch_device)
        with torch.no_grad():
            hidden = self._run_blocks(blocks, hidden, attention_mask)

        out_payload: dict[str, torch.Tensor] = {
            "hidden_states": hidden.detach().cpu(),
            "attention_mask": attention_mask.detach().cpu(),
        }
        log.debug(
            "worker=%s request=%d layers[%d..%d] prefill=%s shape=%s",
            self.device_id, request_id, start, end, is_prefill, tuple(hidden.shape),
        )
        return encode(out_payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _ensure_model(self, model_id: str) -> None:
        if self._handle is None:
            log.info(
                "worker=%s loading %s on %s",
                self.device_id, model_id, self.torch_device,
            )
            self._handle = load_model(
                model_id, dtype=self.dtype, torch_device=self.torch_device
            )
        elif self._handle.model_id != model_id:
            raise ValueError(
                f"worker={self.device_id} already holds {self._handle.model_id}; "
                f"refusing to switch to {model_id}"
            )

    def _validate_range(self, start: LayerIdx, end: LayerIdx) -> None:
        assert self._handle is not None
        if start < 1 or end > self._handle.num_layers or start > end:
            raise ValueError(
                f"Stage [{start}, {end}] out of range for "
                f"{self._handle.num_layers}-layer model"
            )

    def _slice_blocks(self, start: LayerIdx, end: LayerIdx) -> nn.ModuleList:
        assert self._handle is not None
        layers = get_transformer_layers(self._handle.model)
        return nn.ModuleList(list(layers)[int(start) - 1 : int(end)])

    @staticmethod
    def _run_blocks(
        blocks: nn.ModuleList,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        """OPT-only block invocation (Phase 2 MVP carryover)."""
        for block in blocks:
            out: Any = block(
                hidden,
                attention_mask=attention_mask,
                layer_head_mask=None,
                past_key_value=None,
                output_attentions=False,
                use_cache=False,
            )
            hidden = out[0] if isinstance(out, tuple) else out
        return hidden
