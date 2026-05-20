"""User-facing inference pipeline driver (Phase 2 MVP).

Flow (prefill-only; OPT family):
  1. Tokenize prompt -> input_ids
  2. Run OPT's embedding + position-embedding to obtain initial hidden states
  3. Construct the 4D causal attention mask once
  4. For each Stage in placement: gRPC -> worker -> updated hidden state
  5. Apply final_layer_norm + lm_head to compute logits
  6. Greedy-argmax the next token, decode, return

Limitations (Phase 2):
  - Prefill only, no KV cache, no autoregressive loop (caller may run prefill
    multiple times with growing input_ids for naive generation).
  - OPT-family models only.
  - Coordinator loads the full model (uses only embed + norm + lm_head); workers
    also hold the full model but run only their assigned blocks.
"""

from __future__ import annotations

import itertools
from typing import Any

import torch
from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask

from radp.common.logging_utils import get_logger
from radp.common.model_utils import ModelHandle, load_model
from radp.common.protocol import WorkerClient
from radp.common.tensor_io import decode, encode
from radp.common.types import DeviceId, Placement, RequestId

log = get_logger(__name__)


class RequestGateway:
    """Drives one or more user prompts through the deployed pipeline."""

    def __init__(
        self,
        *,
        placement: Placement,
        worker_addresses: dict[DeviceId, str],
        model_id: str,
        torch_device: str = "cpu",
        dtype: str = "float32",
    ) -> None:
        self.placement = placement
        self.worker_addresses = worker_addresses
        self.model_id = model_id
        self.torch_device = torch_device
        self.dtype = dtype

        missing = [s.device for s in placement if s.device not in worker_addresses]
        if missing:
            raise ValueError(f"No address for devices: {missing}")

        log.info("coordinator loading model %s on %s", model_id, torch_device)
        self.handle: ModelHandle = load_model(model_id, dtype=dtype, torch_device=torch_device)
        self._decoder = self._get_opt_decoder(self.handle.model)
        self._request_counter = itertools.count(start=1)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def prefill(self, prompt: str) -> torch.Tensor:
        """Run prefill for `prompt` end-to-end. Returns full logits [1, seq, vocab]."""
        request_id = RequestId(next(self._request_counter))
        log.info("request=%d prompt_len=%d", request_id, len(prompt))

        inputs = self.handle.tokenizer(prompt, return_tensors="pt")
        input_ids = inputs["input_ids"].to(self.torch_device)
        attention_mask_2d = inputs.get("attention_mask")
        if attention_mask_2d is None:
            attention_mask_2d = torch.ones_like(input_ids)
        attention_mask_2d = attention_mask_2d.to(self.torch_device)

        with torch.no_grad():
            hidden = self._embed(input_ids, attention_mask_2d)
            attention_mask_4d = _prepare_4d_causal_attention_mask(
                attention_mask_2d, input_ids.shape, hidden, past_key_values_length=0
            )

            for stage in self.placement:
                blob = encode({"hidden_states": hidden.cpu(), "attention_mask": attention_mask_4d.cpu()})
                address = self.worker_addresses[stage.device]
                with WorkerClient(address) as client:
                    result_blob = client.run_stage(
                        activation=blob,
                        request_id=request_id,
                        is_prefill=True,
                    )
                result = decode(result_blob)
                hidden = result["hidden_states"].to(self.torch_device)
                attention_mask_4d = result["attention_mask"].to(self.torch_device)

            logits = self._head(hidden)
        return logits

    def next_token(self, prompt: str) -> tuple[int, str]:
        """Convenience: greedy-argmax the next token after `prompt`."""
        logits = self.prefill(prompt)
        token_id = int(torch.argmax(logits[0, -1, :]).item())
        text = self.handle.tokenizer.decode([token_id])
        return token_id, text

    # ------------------------------------------------------------------
    # OPT-specific embed + head
    # ------------------------------------------------------------------
    @staticmethod
    def _get_opt_decoder(model: Any) -> Any:
        if not (hasattr(model, "model") and hasattr(model.model, "decoder")):
            raise ValueError("RequestGateway currently supports OPT-family models only.")
        return model.model.decoder

    def _embed(self, input_ids: torch.Tensor, attention_mask_2d: torch.Tensor) -> torch.Tensor:
        """OPT: embed_tokens + embed_positions, then optional project_in."""
        dec = self._decoder
        inputs_embeds = dec.embed_tokens(input_ids)
        pos_embeds = dec.embed_positions(attention_mask_2d, past_key_values_length=0)
        hidden = inputs_embeds + pos_embeds
        if getattr(dec, "project_in", None) is not None:
            hidden = dec.project_in(hidden)
        return hidden  # type: ignore[no-any-return]

    def _head(self, hidden: torch.Tensor) -> torch.Tensor:
        """OPT: optional final_layer_norm + project_out + lm_head."""
        dec = self._decoder
        if getattr(dec, "final_layer_norm", None) is not None:
            hidden = dec.final_layer_norm(hidden)
        if getattr(dec, "project_out", None) is not None:
            hidden = dec.project_out(hidden)
        logits = self.handle.model.lm_head(hidden)
        return logits  # type: ignore[no-any-return]
