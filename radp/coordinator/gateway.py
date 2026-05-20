"""User-facing inference pipeline driver (Phase 3).

Owns the live `execution_plan` (the original placement, dynamically
substituted via the recovery table when devices are flagged as dead by the
FailureDetector). For each request:

  1. Embed prompt -> initial hidden state
  2. For each Stage(start, end, device) in execution_plan:
       a. cache activation INTO this stage (keyed by request_id + stage_key)
       b. RPC RunStage(start, end) on the assigned worker
       c. if RPC fails: mark device dead, recompute plan, replay from cache
  3. final_layer_norm + lm_head -> logits -> next token

OPT-only (carried from Phase 2 MVP).
"""

from __future__ import annotations

import itertools
import threading
from typing import Any

import grpc
import torch
from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask

from radp.common.logging_utils import get_logger
from radp.common.model_utils import ModelHandle, load_model
from radp.common.protocol import WorkerClient
from radp.common.tensor_io import decode, encode
from radp.common.types import (
    DeviceId,
    NoRecoveryError,
    Placement,
    RecoveryTable,
    RequestId,
    Stage,
)
from radp.coordinator.activation_cache import ActivationCache
from radp.coordinator.recovery_plan import build_execution_plan

log = get_logger(__name__)


class RequestGateway:
    def __init__(
        self,
        *,
        placement: Placement,
        recovery: RecoveryTable,
        worker_addresses: dict[DeviceId, str],
        model_id: str,
        torch_device: str = "cpu",
        dtype: str = "float32",
        activation_cache_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.placement = placement
        self.recovery = recovery
        self.worker_addresses = worker_addresses
        self.model_id = model_id
        self.torch_device = torch_device
        self.dtype = dtype

        missing = [
            s.device for s in placement if s.device not in worker_addresses
        ] + [k for k in recovery.values() if k not in worker_addresses]
        if missing:
            raise ValueError(f"No address for devices: {sorted(set(missing))}")

        log.info("coordinator loading model %s on %s", model_id, torch_device)
        self.handle: ModelHandle = load_model(
            model_id, dtype=dtype, torch_device=torch_device
        )
        self._decoder = self._get_opt_decoder(self.handle.model)

        self.cache = ActivationCache(max_bytes=activation_cache_bytes)
        self._request_counter = itertools.count(start=1)

        # Live state: which devices are dead + the current execution plan.
        self._plan_lock = threading.Lock()
        self._dead: set[DeviceId] = set()
        self._execution_plan: Placement = list(placement)

    # ------------------------------------------------------------------
    # External signals (called by CoordinatorServer / FailureDetector)
    # ------------------------------------------------------------------
    def mark_dead(self, device_id: DeviceId) -> bool:
        """Returns True if this caused an execution-plan change."""
        with self._plan_lock:
            if device_id in self._dead:
                return False
            self._dead.add(device_id)
            try:
                self._execution_plan = build_execution_plan(
                    self.placement, self.recovery, self._dead
                )
            except NoRecoveryError:
                log.exception("recovery infeasible after %s failure", device_id)
                raise
        log.warning("execution plan updated; dead=%s", sorted(self._dead))
        return True

    def current_plan(self) -> Placement:
        with self._plan_lock:
            return list(self._execution_plan)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def prefill(self, prompt: str) -> torch.Tensor:
        request_id = RequestId(next(self._request_counter))
        log.info("request=%d prompt_len=%d", request_id, len(prompt))
        try:
            inputs = self.handle.tokenizer(prompt, return_tensors="pt")
            input_ids = inputs["input_ids"].to(self.torch_device)
            attention_mask_2d = inputs.get(
                "attention_mask", torch.ones_like(input_ids)
            ).to(self.torch_device)

            with torch.no_grad():
                hidden = self._embed(input_ids, attention_mask_2d)
                attention_mask_4d = _prepare_4d_causal_attention_mask(
                    attention_mask_2d, input_ids.shape, hidden, past_key_values_length=0
                )
                hidden, attention_mask_4d = self._run_through_workers(
                    request_id, hidden, attention_mask_4d
                )
                logits = self._head(hidden)
            return logits
        finally:
            self.cache.evict_request(request_id)

    def next_token(self, prompt: str) -> tuple[int, str]:
        logits = self.prefill(prompt)
        token_id = int(torch.argmax(logits[0, -1, :]).item())
        return token_id, self.handle.tokenizer.decode([token_id])

    # ------------------------------------------------------------------
    # Pipeline (with recovery)
    # ------------------------------------------------------------------
    def _run_through_workers(
        self,
        request_id: RequestId,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        plan = self.current_plan()
        idx = 0
        while idx < len(plan):
            stage = plan[idx]
            stage_key = (int(stage.start_layer), int(stage.end_layer))
            payload = {
                "hidden_states": hidden.cpu(),
                "attention_mask": attention_mask.cpu(),
            }
            blob = encode(payload)
            self.cache.put(request_id, stage_key, blob)

            try:
                result_blob = self._invoke(stage, request_id, blob)
            except grpc.RpcError as e:
                log.warning(
                    "request=%d stage layers[%d..%d] on %s failed: %s — recovering",
                    request_id, stage.start_layer, stage.end_layer, stage.device, e,
                )
                self.mark_dead(stage.device)
                # Rebuild plan and replay this stage on the (now-substituted) device.
                plan = self.current_plan()
                continue

            decoded = decode(result_blob)
            hidden = decoded["hidden_states"].to(self.torch_device)
            attention_mask = decoded["attention_mask"].to(self.torch_device)
            idx += 1
        return hidden, attention_mask

    def _invoke(
        self,
        stage: Stage,
        request_id: RequestId,
        activation_blob: bytes,
    ) -> bytes:
        address = self.worker_addresses[stage.device]
        with WorkerClient(address) as client:
            return client.run_stage(
                activation=activation_blob,
                request_id=request_id,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                is_prefill=True,
            )

    # ------------------------------------------------------------------
    # OPT-specific embed + head (unchanged from Phase 2)
    # ------------------------------------------------------------------
    @staticmethod
    def _get_opt_decoder(model: Any) -> Any:
        if not (hasattr(model, "model") and hasattr(model.model, "decoder")):
            raise ValueError("RequestGateway currently supports OPT-family models only.")
        return model.model.decoder

    def _embed(self, input_ids: torch.Tensor, attention_mask_2d: torch.Tensor) -> torch.Tensor:
        dec = self._decoder
        inputs_embeds = dec.embed_tokens(input_ids)
        pos_embeds = dec.embed_positions(attention_mask_2d, past_key_values_length=0)
        hidden = inputs_embeds + pos_embeds
        if getattr(dec, "project_in", None) is not None:
            hidden = dec.project_in(hidden)
        return hidden  # type: ignore[no-any-return]

    def _head(self, hidden: torch.Tensor) -> torch.Tensor:
        dec = self._decoder
        if getattr(dec, "final_layer_norm", None) is not None:
            hidden = dec.final_layer_norm(hidden)
        if getattr(dec, "project_out", None) is not None:
            hidden = dec.project_out(hidden)
        logits = self.handle.model.lm_head(hidden)
        return logits  # type: ignore[no-any-return]
