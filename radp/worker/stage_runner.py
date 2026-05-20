"""Single-stage inference executor (Phase 2 MVP).

Loads the full model (Phase 2 simplification — every worker holds the whole
model) and, on each ``run`` call, walks ONLY the assigned transformer blocks.
Coordinator handles embedding + final norm + LM head.

Currently supports OPT-family models only. The decoder-layer call signature
in transformers is architecture-specific; add a new branch in `_run_blocks`
to support LLaMA / GPT-2 / etc.
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


class StageRunner:
    """Owns a primary stage [start, end] of transformer blocks on one device."""

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
        self._start: LayerIdx | None = None
        self._end: LayerIdx | None = None
        self._blocks: nn.ModuleList | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_primary(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        with self._lock:
            log.info(
                "worker=%s loading %s[%d..%d] on %s",
                self.device_id, model_id, start, end, self.torch_device,
            )
            handle = load_model(model_id, dtype=self.dtype, torch_device=self.torch_device)
            if start < 1 or end > handle.num_layers or start > end:
                raise ValueError(
                    f"Stage [{start}, {end}] out of range for {handle.num_layers}-layer model"
                )
            layers = get_transformer_layers(handle.model)
            self._handle = handle
            self._start = start
            self._end = end
            self._blocks = nn.ModuleList(list(layers)[int(start) - 1 : int(end)])

    def load_backup(self, model_id: str, start: LayerIdx, end: LayerIdx) -> None:
        raise NotImplementedError("Phase 3")

    def promote_backup(self) -> None:
        raise NotImplementedError("Phase 3")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(self, request_id: RequestId, activation_blob: bytes, *, is_prefill: bool) -> bytes:
        if self._handle is None or self._blocks is None:
            raise RuntimeError("StageRunner.run called before load_primary")

        payload = decode(activation_blob)
        hidden = payload["hidden_states"].to(self.torch_device)
        attention_mask = payload["attention_mask"].to(self.torch_device)

        with torch.no_grad():
            hidden = self._run_blocks(self._blocks, hidden, attention_mask)

        out_payload: dict[str, torch.Tensor] = {
            "hidden_states": hidden.detach().cpu(),
            "attention_mask": attention_mask.detach().cpu(),
        }
        log.debug(
            "worker=%s request=%d stage[%d..%d] prefill=%s shape=%s",
            self.device_id, request_id, self._start, self._end, is_prefill, tuple(hidden.shape),
        )
        return encode(out_payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    @staticmethod
    def _run_blocks(
        blocks: nn.ModuleList,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Architecture-specific block invocation. OPT-only in Phase 2."""
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
