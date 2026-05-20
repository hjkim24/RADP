"""User-facing inference pipeline driver (Phase 2.6 — KV cache + autoregressive).

Per-request lifecycle:
  1. ``prefill(request_id, prompt)`` runs ONCE through the workers with
     ``is_prefill=True``. Workers populate their DynamicCache for this
     (request, stage) and the coordinator records the past-tokens length.
  2. ``decode_step(request_id, prev_token)`` runs ONCE per generated token
     through the workers with ``is_prefill=False``. Workers append a single
     time-step to their cache; coordinator advances past-tokens length.
  3. ``generate(prompt, max_tokens)`` = prefill + (max_tokens-1) decodes,
     yielding decoded tokens. On any worker failure mid-generation the
     plan is rebuilt; since the new (backup) worker has no KV cache, the
     current request is restarted (prompt + tokens-so-far re-prefilled).
  4. ``evict(request_id)`` tells every worker to drop the request's cache.

OPT-only (block invocation + embed_positions are OPT-specific).
"""

from __future__ import annotations

import contextlib
import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import grpc
import torch
from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask

from radp.common.logging_utils import get_logger
from radp.common.model_utils import ModelHandle, load_model, measure_resident_bytes
from radp.common.proto import radp_pb2, radp_pb2_grpc
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
from radp.coordinator.sampling import sample_next_token

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]

log = get_logger(__name__)


@dataclass
class _RequestState:
    past_length: int        # tokens accumulated in worker KV cache for this request
    generated_token_ids: list[int]


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
        self.handle: ModelHandle = load_model(model_id, dtype=dtype, torch_device=torch_device)
        self._decoder = self._get_opt_decoder(self.handle.model)
        rss_before = measure_resident_bytes()
        self._decoder.layers = torch.nn.ModuleList()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log.info(
            "coordinator freed decoder.layers (rss %.1f -> %.1f MB)",
            rss_before / (1024 * 1024),
            measure_resident_bytes() / (1024 * 1024),
        )

        self.cache = ActivationCache(max_bytes=activation_cache_bytes)
        self._request_counter = itertools.count(start=1)
        self._requests: dict[RequestId, _RequestState] = {}

        self._plan_lock = threading.Lock()
        self._dead: set[DeviceId] = set()
        self._execution_plan: Placement = list(placement)

        # Persistent gRPC channels to each worker — opened lazily and reused
        # across all RunStage / EvictRequest calls so concurrent requests
        # don't pay a channel-setup tax per RPC.
        self._channel_lock = threading.Lock()
        self._channels: dict[DeviceId, grpc.Channel] = {}
        self._stubs: dict[DeviceId, Any] = {}

    # ------------------------------------------------------------------
    # External signals
    # ------------------------------------------------------------------
    def mark_dead(self, device_id: DeviceId) -> bool:
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
    # Public inference API
    # ------------------------------------------------------------------
    def new_request_id(self) -> RequestId:
        return RequestId(next(self._request_counter))

    def generate(
        self,
        prompt: str,
        max_tokens: int,
        *,
        temperature: float = 0.0,
        top_k: int = 0,
        top_p: float = 1.0,
        eos_token_id: int | None = None,
        seed: int | None = None,
    ) -> list[int]:
        """Prefill + autoregressive decode.

        Sampling: ``temperature == 0`` (default) selects greedy argmax;
        positive temperature enables softmax sampling, optionally narrowed
        by ``top_k`` and ``top_p``.

        EOS: if ``eos_token_id`` is given and that token is produced, the
        loop exits early (the returned list ends with that token).

        Reproducibility: pass ``seed`` to get the same tokens across runs
        with the same sampling params.

        Returns the list of generated token ids (length ≤ ``max_tokens``).
        """
        request_id = self.new_request_id()
        device = torch.device(self.torch_device)
        generator: torch.Generator | None = None
        if seed is not None:
            generator = torch.Generator(device=device)
            generator.manual_seed(int(seed))

        def sampler(logits: torch.Tensor) -> int:
            return sample_next_token(
                logits,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                generator=generator,
            )

        try:
            return self._generate_inner(
                request_id, prompt, max_tokens, sampler=sampler, eos_id=eos_token_id
            )
        finally:
            self._evict_everywhere(request_id)
            self._requests.pop(request_id, None)

    def _generate_inner(
        self,
        request_id: RequestId,
        prompt: str,
        max_tokens: int,
        *,
        sampler: Callable[[torch.Tensor], int],
        eos_id: int | None,
    ) -> list[int]:
        last_failure_attempts = 0
        while True:
            try:
                # Prefill emits the first token; decode emits the rest.
                self._prefill(request_id, prompt, sampler=sampler)
                state = self._requests[request_id]
                if eos_id is not None and state.generated_token_ids[-1] == eos_id:
                    return state.generated_token_ids
                for _ in range(max_tokens - 1):
                    self._decode_step(request_id, sampler=sampler)
                    if eos_id is not None and state.generated_token_ids[-1] == eos_id:
                        break
                return state.generated_token_ids
            except grpc.RpcError as e:
                # Re-prefill path: cache is lost on backup, restart this request.
                last_failure_attempts += 1
                if last_failure_attempts > len(self.placement):
                    raise
                log.warning(
                    "request=%d mid-generation RPC failure (%s) — re-prefilling",
                    request_id, e,
                )
                self._evict_everywhere(request_id)
                self._requests.pop(request_id, None)
                # mark_dead was already called inside _run_pipeline

    # ------------------------------------------------------------------
    # Prefill / decode primitives
    # ------------------------------------------------------------------
    def _prefill(
        self,
        request_id: RequestId,
        prompt: str,
        *,
        sampler: Callable[[torch.Tensor], int] = lambda x: int(torch.argmax(x).item()),
    ) -> None:
        log.info("request=%d PREFILL prompt_len=%d", request_id, len(prompt))
        inputs = self.handle.tokenizer(prompt, return_tensors="pt")
        input_ids: torch.Tensor = inputs["input_ids"].to(self.torch_device)
        attention_mask_2d = inputs.get("attention_mask", torch.ones_like(input_ids))
        attention_mask_2d = attention_mask_2d.to(self.torch_device)
        seq_len = int(input_ids.shape[1])

        with torch.no_grad():
            hidden = self._embed(input_ids, attention_mask_2d, past_kv_length=0)
            attention_mask_4d = _prepare_4d_causal_attention_mask(
                attention_mask_2d, input_ids.shape, hidden, past_key_values_length=0
            )
            hidden, _ = self._run_pipeline(
                request_id, hidden, attention_mask_4d, is_prefill=True
            )
            logits = self._head(hidden)
            next_id = sampler(logits[0, -1, :])

        self._requests[request_id] = _RequestState(
            past_length=seq_len, generated_token_ids=[next_id]
        )

    def _decode_step(
        self,
        request_id: RequestId,
        *,
        sampler: Callable[[torch.Tensor], int] = lambda x: int(torch.argmax(x).item()),
    ) -> None:
        state = self._requests[request_id]
        prev_id = state.generated_token_ids[-1]
        past_len = state.past_length + len(state.generated_token_ids) - 1
        new_input = torch.tensor([[prev_id]], device=self.torch_device)
        attn_2d = torch.ones(1, past_len + 1, device=self.torch_device, dtype=torch.long)

        with torch.no_grad():
            hidden = self._embed(new_input, attn_2d, past_kv_length=past_len)
            attention_mask_4d = _prepare_4d_causal_attention_mask(
                attn_2d, (1, 1), hidden, past_key_values_length=past_len
            )
            hidden, _ = self._run_pipeline(
                request_id, hidden, attention_mask_4d, is_prefill=False
            )
            logits = self._head(hidden)
            next_id = sampler(logits[0, -1, :])

        state.generated_token_ids.append(next_id)

    # ------------------------------------------------------------------
    # Pipeline dispatch
    # ------------------------------------------------------------------
    def _run_pipeline(
        self,
        request_id: RequestId,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        *,
        is_prefill: bool,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        plan = self.current_plan()
        idx = 0
        while idx < len(plan):
            stage = plan[idx]
            stage_key = (int(stage.start_layer), int(stage.end_layer))
            blob = encode({"hidden_states": hidden.cpu(), "attention_mask": attention_mask.cpu()})
            try:
                result_blob = self._invoke(stage, request_id, blob, is_prefill=is_prefill)
            except grpc.RpcError as e:
                log.warning(
                    "request=%d stage layers[%d..%d] on %s failed: %s",
                    request_id, stage.start_layer, stage.end_layer, stage.device, e,
                )
                self.mark_dead(stage.device)
                # Try cache-replay recovery: rebuild the backup worker's KV cache
                # from history so we don't have to re-prefill the whole request.
                try:
                    self._replay_stage_history(request_id, stage_key)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "request=%d cache-replay failed; propagating to outer retry",
                        request_id,
                    )
                    raise e from None
                # Refresh plan (now points to the backup device) and retry this stage.
                plan = self.current_plan()
                continue
            # Append AFTER success — failed attempts never enter history, so replay
            # exactly reproduces the surviving workers' cache state.
            self.cache.append(request_id, stage_key, blob)
            decoded = decode(result_blob)
            hidden = decoded["hidden_states"].to(self.torch_device)
            attention_mask = decoded["attention_mask"].to(self.torch_device)
            idx += 1
        return hidden, attention_mask

    def _replay_stage_history(
        self, request_id: RequestId, stage_key: tuple[int, int]
    ) -> None:
        """Replay cached activations into whichever device now owns ``stage_key``.

        The first cached entry is always the prefill activation (we cache in
        ``_run_pipeline`` after success, and a request's first successful step
        is always its prefill). Subsequent entries are decode steps.
        """
        history = self.cache.get_history(request_id, stage_key)
        if not history:
            log.info(
                "request=%d no cache history for stage[%d..%d]; nothing to replay",
                request_id, *stage_key,
            )
            return
        plan = self.current_plan()
        owner = next(
            (s for s in plan if (int(s.start_layer), int(s.end_layer)) == stage_key),
            None,
        )
        if owner is None:
            raise RuntimeError(f"layer range {stage_key} not present in current plan")
        log.info(
            "request=%d replay %d activations to %s for stage[%d..%d]",
            request_id, len(history), owner.device, *stage_key,
        )
        for i, blob in enumerate(history):
            self._invoke(owner, request_id, blob, is_prefill=(i == 0))

    def _get_stub(self, device_id: DeviceId) -> Any:
        """Return a cached WorkerServiceStub backed by a persistent channel."""
        with self._channel_lock:
            stub = self._stubs.get(device_id)
            if stub is not None:
                return stub
            channel = grpc.insecure_channel(
                self.worker_addresses[device_id], options=_GRPC_OPTIONS
            )
            stub = radp_pb2_grpc.WorkerServiceStub(channel)
            self._channels[device_id] = channel
            self._stubs[device_id] = stub
            return stub

    def _invoke(
        self,
        stage: Stage,
        request_id: RequestId,
        activation_blob: bytes,
        *,
        is_prefill: bool,
    ) -> bytes:
        stub = self._get_stub(stage.device)
        req = radp_pb2.RunStageRequest(
            activation=activation_blob,
            request_id=int(request_id),
            is_prefill=is_prefill,
            start_layer=int(stage.start_layer),
            end_layer=int(stage.end_layer),
        )
        resp = stub.RunStage(req)
        return bytes(resp.activation)

    def _evict_everywhere(self, request_id: RequestId) -> None:
        """Best-effort: ask every (currently-alive) worker to drop this request's cache."""
        self.cache.evict_request(request_id)
        for device_id in self.worker_addresses:
            if device_id in self._dead:
                continue
            try:
                stub = self._get_stub(device_id)
                stub.EvictRequest(radp_pb2.EvictRequestRequest(request_id=int(request_id)))
            except Exception:  # noqa: BLE001
                log.debug("evict_request on %s failed (ignored)", device_id)

    def close(self) -> None:
        """Close all persistent worker channels. Call when shutting down."""
        with self._channel_lock:
            for ch in self._channels.values():
                with contextlib.suppress(Exception):
                    ch.close()
            self._channels.clear()
            self._stubs.clear()

    # ------------------------------------------------------------------
    # OPT-specific embed + head
    # ------------------------------------------------------------------
    @staticmethod
    def _get_opt_decoder(model: Any) -> Any:
        if not (hasattr(model, "model") and hasattr(model.model, "decoder")):
            raise ValueError("RequestGateway currently supports OPT-family models only.")
        return model.model.decoder

    def _embed(
        self,
        input_ids: torch.Tensor,
        attention_mask_2d: torch.Tensor,
        *,
        past_kv_length: int,
    ) -> torch.Tensor:
        dec = self._decoder
        inputs_embeds = dec.embed_tokens(input_ids)
        pos_embeds = dec.embed_positions(attention_mask_2d, past_key_values_length=past_kv_length)
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

    # ------------------------------------------------------------------
    # Convenience used by tests and existing callers
    # ------------------------------------------------------------------
    def prefill(self, prompt: str) -> torch.Tensor:
        """Single prefill returning logits (Phase 2 compatibility for tests).

        Retries on RPC failure by rebuilding the execution plan, just like
        ``generate()`` does — preserves Phase 3 failure-recovery behavior.
        """
        request_id = self.new_request_id()
        attempts = 0
        try:
            inputs = self.handle.tokenizer(prompt, return_tensors="pt")
            input_ids = inputs["input_ids"].to(self.torch_device)
            attention_mask_2d = inputs.get(
                "attention_mask", torch.ones_like(input_ids)
            ).to(self.torch_device)
            while True:
                try:
                    with torch.no_grad():
                        hidden = self._embed(
                            input_ids, attention_mask_2d, past_kv_length=0
                        )
                        attention_mask_4d = _prepare_4d_causal_attention_mask(
                            attention_mask_2d, input_ids.shape, hidden,
                            past_key_values_length=0,
                        )
                        hidden, _ = self._run_pipeline(
                            request_id, hidden, attention_mask_4d, is_prefill=True
                        )
                        return self._head(hidden)
                except grpc.RpcError:
                    attempts += 1
                    if attempts > len(self.placement):
                        raise
                    log.warning("request=%d prefill RPC failure — retrying", request_id)
        finally:
            self._evict_everywhere(request_id)
