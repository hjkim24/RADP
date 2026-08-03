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
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import grpc
import numpy as np
import torch
from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask

from radp.common.architectures import ModelArchitecture, get_architecture
from radp.common.logging_utils import get_logger
from radp.common.model_utils import ModelHandle, load_model, measure_resident_bytes
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.protocol import WorkerClient
from radp.common.tensor_io import decode, encode
from radp.common.types import (
    DeviceId,
    NoRecoveryError,
    Placement,
    RecoveryTable,
    RequestId,
    Stage,
    StageTiming,
)
from radp.coordinator.activation_cache import ActivationCache
from radp.coordinator.parity_cache import ParityCache
from radp.coordinator.recovery_plan import build_execution_plan
from radp.coordinator.replica_cache import ReplicaCache
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
    # EXP-D3 Phase 2: monotonically incremented per request — written into
    # the mirror cache as `position` so out-of-order arrivals from workers'
    # in-flight MirrorActivation RPCs sort into prefill→decode order.
    step_index: int = 0


@dataclass(frozen=True)
class StreamingToken:
    """One emitted token plus the wall clock of the step that produced it.

    `is_first=True` for the prefill output (first token of the response);
    `is_first=False` for every subsequent decode-loop iteration. `step_seconds`
    is end-to-end (embed + pipeline + lm_head + sample) — i.e., the latency
    a client would see between successive tokens in a streaming response.
    """

    token_id: int
    text: str
    is_first: bool
    stages: list[StageTiming]
    step_seconds: float


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
        chain_mode: str = "sync",
        async_chain_timeout_seconds: float = 30.0,
        recovery_mode: str = "full_replay",
        parity_k: int = 1,
    ) -> None:
        if recovery_mode not in {"full_replay", "surgical", "parity", "replicate"}:
            raise ValueError(
                f"recovery_mode must be 'full_replay', 'surgical', 'parity' or "
                f"'replicate', got {recovery_mode!r}"
            )
        self.recovery_mode = recovery_mode
        if parity_k not in {1, 2}:
            raise ValueError(f"parity_k must be 1 or 2, got {parity_k!r}")
        self.parity_k = parity_k
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
        self._arch: ModelArchitecture = get_architecture(self.handle.model.config.model_type)
        self._decoder = self._arch.get_decoder(self.handle.model)
        rss_before = measure_resident_bytes()
        self._decoder.layers = torch.nn.ModuleList()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log.info(
            "coordinator freed decoder.layers (arch=%s, rss %.1f -> %.1f MB)",
            self._arch.name,
            rss_before / (1024 * 1024),
            measure_resident_bytes() / (1024 * 1024),
        )

        self.cache = ActivationCache(max_bytes=activation_cache_bytes)
        # Parity (RAID-5-style) KV recovery: the head stage (placement[0],
        # start_layer==1) is coord-sourced and never ships KV (see
        # radp/worker/server.py RunStage's head-skip), so only the
        # non-head stages ever contribute a column. num_stages must be
        # len(placement) - 1 — using len(placement) would make
        # is_complete() unreachable (one stage would never contribute),
        # silently disabling parity recovery.
        self.parity_cache = ParityCache(
            num_stages=max(len(placement) - 1, 0), k=parity_k
        )
        self.replica_cache = ReplicaCache(num_stages=max(len(placement) - 1, 0))
        # gⁱ coefficient per non-head stage, i = 0-based rank by start_layer.
        # Device-independent, so it survives placement rewiring during recovery.
        non_head = sorted(
            (s for s in placement if int(s.start_layer) > 1),
            key=lambda s: int(s.start_layer),
        )
        self._parity_coeff = {
            (int(s.start_layer), int(s.end_layer)): i
            for i, s in enumerate(non_head)
        }
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

        # EXP-D3 Phase 2: lifetime counter of MirrorActivation pushes
        # we've ingested from workers — purely diagnostic, exposed via
        # /api/mirror_stats so deploys can confirm the mirror path is hot
        # without grepping logs.
        self._mirror_count = 0
        self._mirror_bytes = 0
        self._mirror_lock = threading.Lock()

        # EXP-D3 Phase F async chain.
        # `chain_mode == "async"` flips RunStage calls to fire-and-forget;
        # the chain tail wakes us via CoordinatorService.ResultReady, and
        # we wait on a per-(request_id, position) Event that the servicer
        # fills in. `chain_mode == "sync"` (default) preserves Phase 1a/1b
        # semantics for backward-compat + apples-to-apples baselines.
        if chain_mode not in {"sync", "async"}:
            raise ValueError(f"chain_mode must be 'sync' or 'async', got {chain_mode!r}")
        self.chain_mode = chain_mode
        self.async_chain_timeout_seconds = float(async_chain_timeout_seconds)
        self._pending_lock = threading.Lock()
        self._pending: dict[
            tuple[RequestId, int], tuple[threading.Event, dict[str, Any]]
        ] = {}

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

    def mark_alive(self, device_id: DeviceId) -> bool:
        """Reverse of mark_dead — remove the device from `_dead` and rebuild
        the execution plan with the new (smaller) dead set.

        Used by the web "revive" control to undo a simulated failure. Returns
        True if the device was actually in the dead set (state changed),
        False if it was already alive.

        Caveat for mid-stream revives: the device's KV cache won't reflect
        any decode steps the gateway routed onto the backup while it was
        dead, so subsequent tokens generated via the revived device may
        diverge from what the same prompt would produce on a fresh prefill.
        Use between requests for a clean reset.
        """
        with self._plan_lock:
            if device_id not in self._dead:
                return False
            self._dead.discard(device_id)
            # Rebuilding with a strictly smaller dead set can never raise
            # NoRecoveryError (if the previous plan was viable, this one is
            # at least as viable), so we don't try/except.
            self._execution_plan = build_execution_plan(
                self.placement, self.recovery, self._dead
            )
        log.info("device revived; dead=%s", sorted(self._dead))
        return True

    def current_plan(self) -> Placement:
        with self._plan_lock:
            return list(self._execution_plan)

    # ------------------------------------------------------------------
    # Mirror cache ingestion (EXP-D3 Phase 2)
    # ------------------------------------------------------------------
    def record_mirror(
        self,
        *,
        request_id: int,
        stage_key: tuple[int, int],
        position: int,
        activation: bytes,
    ) -> None:
        """Append a worker-shipped activation into the mirror cache.

        Idempotent — re-arriving (request, stage, position) is dropped.
        Coord skips its own first-stage local cache entry once mirrors are
        coming in, so this is the single source of truth for replay.
        """
        added = self.cache.put(
            RequestId(request_id), stage_key, position, activation
        )
        if added:
            with self._mirror_lock:
                self._mirror_count += 1
                self._mirror_bytes += len(activation)

    def record_kv(
        self,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        kv_bytes: bytes,
    ) -> None:
        """Feed a worker-shipped KV column into the parity or replica cache
        (MirrorKV), dispatching on ``recovery_mode`` — replicate keeps every
        stage's column verbatim; every other mode XORs it into parity."""
        key = (int(start_layer), int(end_layer))
        if self.recovery_mode == "replicate":
            self.replica_cache.store(
                RequestId(request_id), key, int(position), kv_bytes
            )
        else:
            self.parity_cache.xor_in(
                RequestId(request_id), key, int(position), kv_bytes,
                coeff_index=self._parity_coeff.get(key, 0),
            )

    def mirror_stats(self) -> dict[str, int]:
        """Lifetime ingress counters + current cache state. Diagnostic only."""
        with self._mirror_lock:
            count, bytes_ = self._mirror_count, self._mirror_bytes
        return {
            "lifetime_pushes": count,
            "lifetime_bytes": bytes_,
            "cache_bytes_used": self.cache.bytes_used(),
        }

    # ------------------------------------------------------------------
    # Async chain wake-up (EXP-D3 Phase F)
    # ------------------------------------------------------------------
    def record_result(
        self,
        *,
        request_id: int,
        position: int,
        activation: bytes,
        has_next_token: bool,
        next_token_id: int,
    ) -> None:
        """Fill the pending future for (request_id, position) so the
        gateway's _run_pipeline can return. The chain tail (worker)
        calls this via the CoordinatorService.ResultReady RPC.

        Stale results (position we've already recovered past, or a step
        we never registered a future for) are dropped — they're a normal
        consequence of the Phase 3 chain-failure recovery path racing
        with an in-flight async tail.
        """
        key = (RequestId(request_id), int(position))
        with self._pending_lock:
            entry = self._pending.get(key)
        if entry is None:
            log.debug(
                "ResultReady for req=%d pos=%d arrived with no pending future "
                "(likely a stale async result post-recovery); dropping",
                request_id, position,
            )
            return
        ev, payload = entry
        payload["activation"] = activation
        payload["has_next_token"] = bool(has_next_token)
        payload["next_token_id"] = int(next_token_id)
        ev.set()

    def _register_pending(
        self, request_id: RequestId, position: int
    ) -> tuple[threading.Event, dict[str, Any]]:
        key = (request_id, int(position))
        ev = threading.Event()
        payload: dict[str, Any] = {}
        with self._pending_lock:
            self._pending[key] = (ev, payload)
        return ev, payload

    def _unregister_pending(self, request_id: RequestId, position: int) -> None:
        key = (request_id, int(position))
        with self._pending_lock:
            self._pending.pop(key, None)

    # ------------------------------------------------------------------
    # Public inference API
    # ------------------------------------------------------------------
    def new_request_id(self) -> RequestId:
        return RequestId(next(self._request_counter))

    def generate_streaming(
        self,
        prompt: str,
        max_tokens: int,
        *,
        temperature: float = 0.0,
        top_k: int = 0,
        top_p: float = 1.0,
        eos_token_id: int | None = None,
        seed: int | None = None,
    ) -> Iterator[StreamingToken]:
        """Yield tokens as they are produced (real streaming).

        Unlike :meth:`generate`, this surfaces each decode step's wall clock
        and per-stage timings to the consumer immediately — which is what
        makes TTFT (first yield = prefill done) and TBT (between yields =
        single decode step) actually measure what they claim to measure.

        Recovery: stage-level recovery inside :meth:`_run_pipeline` still
        works (mark_dead + cache-replay onto backup). The outer "full
        re-prefill" retry from :meth:`generate` is intentionally absent
        here — once tokens have been streamed to the client, replaying
        them would emit duplicates.
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

        tokenizer = self.handle.tokenizer
        try:
            t0 = time.perf_counter()
            stage_timings = self._prefill(request_id, prompt, sampler=sampler)
            state = self._requests[request_id]
            first_token_id = state.generated_token_ids[-1]
            yield StreamingToken(
                token_id=first_token_id,
                text=tokenizer.decode([first_token_id]),
                is_first=True,
                stages=stage_timings,
                step_seconds=time.perf_counter() - t0,
            )
            if eos_token_id is not None and first_token_id == eos_token_id:
                return
            for _ in range(max_tokens - 1):
                t_step = time.perf_counter()
                stage_timings = self._decode_step(request_id, sampler=sampler)
                token_id = state.generated_token_ids[-1]
                yield StreamingToken(
                    token_id=token_id,
                    text=tokenizer.decode([token_id]),
                    is_first=False,
                    stages=stage_timings,
                    step_seconds=time.perf_counter() - t_step,
                )
                if eos_token_id is not None and token_id == eos_token_id:
                    return
        finally:
            self._evict_everywhere(request_id)
            self._requests.pop(request_id, None)

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
    ) -> list[StageTiming]:
        log.info("request=%d PREFILL prompt_len=%d", request_id, len(prompt))
        inputs = self.handle.tokenizer(prompt, return_tensors="pt")
        input_ids: torch.Tensor = inputs["input_ids"].to(self.torch_device)
        attention_mask_2d = inputs.get("attention_mask", torch.ones_like(input_ids))
        attention_mask_2d = attention_mask_2d.to(self.torch_device)
        seq_len = int(input_ids.shape[1])

        # Prefill is always position 0; subsequent decode steps increment.
        self._requests[request_id] = _RequestState(
            past_length=seq_len, generated_token_ids=[], step_index=0
        )
        with torch.no_grad():
            hidden = self._embed(input_ids, attention_mask_2d, past_kv_length=0)
            attention_mask_4d = _prepare_4d_causal_attention_mask(
                attention_mask_2d, input_ids.shape, hidden, past_key_values_length=0
            )
            hidden, _, timings, tail_token = self._run_pipeline(
                request_id, hidden, attention_mask_4d, is_prefill=True, position=0
            )
            if tail_token is not None:
                next_id = int(tail_token)
            else:
                assert hidden is not None
                logits = self._head(hidden)
                next_id = sampler(logits[0, -1, :])

        self._requests[request_id].generated_token_ids.append(next_id)
        return timings

    def _decode_step(
        self,
        request_id: RequestId,
        *,
        sampler: Callable[[torch.Tensor], int] = lambda x: int(torch.argmax(x).item()),
    ) -> list[StageTiming]:
        state = self._requests[request_id]
        prev_id = state.generated_token_ids[-1]
        past_len = state.past_length + len(state.generated_token_ids) - 1
        new_input = torch.tensor([[prev_id]], device=self.torch_device)
        attn_2d = torch.ones(1, past_len + 1, device=self.torch_device, dtype=torch.long)

        state.step_index += 1
        with torch.no_grad():
            hidden = self._embed(new_input, attn_2d, past_kv_length=past_len)
            attention_mask_4d = _prepare_4d_causal_attention_mask(
                attn_2d, (1, 1), hidden, past_key_values_length=past_len
            )
            hidden, _, timings, tail_token = self._run_pipeline(
                request_id,
                hidden,
                attention_mask_4d,
                is_prefill=False,
                position=state.step_index,
            )
            if tail_token is not None:
                next_id = int(tail_token)
            else:
                assert hidden is not None
                logits = self._head(hidden)
                next_id = sampler(logits[0, -1, :])

        state.generated_token_ids.append(next_id)
        return timings

    # ------------------------------------------------------------------
    # Chain-aware failure recovery (EXP-D3 Phase 3)
    # ------------------------------------------------------------------
    def _attribute_chain_failure(
        self, head_stage: Stage, error: grpc.RpcError
    ) -> Stage:
        """Identify the actually-dead stage from gRPC trailer metadata.

        Workers in chain mode catch their downstream RunStage RpcError and
        stamp ``(radp-failed-start, radp-failed-end)`` onto the trailer
        before aborting. We map that back to the stage from the
        *original* placement (not the current execution plan), so that
        when the heartbeat path has already advanced the plan onto the
        backup we still surface the truly-dead device (not the substitute
        that's about to receive the rewired traffic). If the trailer is
        missing (head itself died, old worker binary), fall back to
        blaming the head we called directly.
        """
        try:
            trailer = error.trailing_metadata()
        except AttributeError:
            trailer = ()
        md = {k: v for k, v in trailer or ()}
        s = md.get("radp-failed-start")
        e_ = md.get("radp-failed-end")
        if s is None or e_ is None:
            return head_stage
        try:
            failed_start, failed_end = int(s), int(e_)
        except ValueError:
            return head_stage
        # The original placement carries the "true" owner of a layer
        # range; the execution plan can substitute a backup in. The chain
        # only points at a dead worker's address until rewire fires, so
        # the trailer is always reporting against the original wiring.
        for stage in self.placement:
            if (
                int(stage.start_layer) == failed_start
                and int(stage.end_layer) == failed_end
            ):
                return stage
        # No match in the original placement either — fallback so we
        # still make progress rather than infinite-loop.
        return head_stage

    def _rewire_chain(self) -> None:
        """Re-issue SetNextHop calls so every worker's next-hop matches the
        current execution plan. Idempotent — workers update their
        ``_next_hops`` dict in place; redundant calls are cheap.

        Called after a recovery substitution so the chain skips the dead
        worker entirely. The replacement worker (the backup) is wired into
        the predecessor's next-hop; its own next-hop points at whatever
        follows in the plan, or is cleared if it becomes the new tail.
        """
        plan = self.current_plan()
        for i, stage in enumerate(plan):
            addr = self.worker_addresses[stage.device]
            try:
                with WorkerClient(addr) as client:
                    if i + 1 < len(plan):
                        nxt = plan[i + 1]
                        client.set_next_hop(
                            my_start=int(stage.start_layer),
                            my_end=int(stage.end_layer),
                            next_address=self.worker_addresses[nxt.device],
                            next_start=int(nxt.start_layer),
                            next_end=int(nxt.end_layer),
                        )
                    else:
                        client.set_next_hop(
                            my_start=int(stage.start_layer),
                            my_end=int(stage.end_layer),
                            next_address="",
                        )
            except Exception:  # noqa: BLE001
                log.exception(
                    "rewire next_hop on %s[%d..%d] failed (continuing)",
                    stage.device, stage.start_layer, stage.end_layer,
                )

    def _recover_from_chain_failure(
        self,
        request_id: RequestId,
        head_stage: Stage,
        error: grpc.RpcError,
        current_position: int,
    ) -> tuple[Stage, Any]:
        """Identify the dead worker, promote its backup, rewire the chain,
        rebuild KV caches via full replay, and return ``(new_head_stage,
        last_response)``. The last_response IS the result of the original
        failed call — the caller can use it directly.

        Why a full chain replay and not just a stage replay:
          On the original failed attempt the chain ran *partially* — the
          surviving upstream workers (the head, anyone between it and the
          dead stage) already advanced their KV cache by one step. If we
          only replay onto the backup and retry, the head will advance
          again on the retry, double-counting that position. So we evict
          all surviving caches and rebuild the entire request from scratch
          through the new chain.

        Side effects (in order):
          1. ``mark_dead`` + plan rebuild (backup substituted)
          2. ``PromoteBackup`` on the backup peer
          3. ``_rewire_chain`` updates every worker's next-hop
          4. ``_evict_kv_everywhere`` drops stale KV caches on survivors
          5. Replay history through the new chain end-to-end; the last
             invocation's response is the recovered token / activation.

        Recovery overhead is therefore O(positions × stages) RPC calls
        plus the backup promotion latency — acceptable for the paper
        claim ("R guarantees correctness on single-fault scenarios"),
        not optimised for high-frequency failures.

        ``recovery_mode == "surgical"`` swaps the O(positions × stages)
        full replay for the O(positions × 1 stage) mirror-fed rebuild of
        ONLY the promoted backup — see :meth:`_recover_surgical`. The
        default ("full_replay") keeps the behaviour documented above.
        """
        if self.recovery_mode == "replicate":
            return self._recover_replicate(
                request_id, head_stage, error, current_position
            )
        if self.recovery_mode == "parity":
            return self._recover_parity(
                request_id, head_stage, error, current_position
            )
        if self.recovery_mode == "surgical":
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        dead_stage = self._attribute_chain_failure(head_stage, error)
        already_dead = dead_stage.device in self._dead

        if already_dead:
            # The heartbeat path beat the chain trailer to the punch and
            # already marked this device dead — `_execution_plan` reflects
            # the substitution but the chain wiring (next-hop addresses)
            # still points at the dead worker, which is why the in-flight
            # call surfaced this trailer. We only need to (a) ensure the
            # backup is promoted, (b) rewire, (c) replay.
            log.info(
                "request=%d chain failure for already-dead %s[%d..%d]; "
                "finalising recovery (rewire + replay)",
                request_id,
                dead_stage.device,
                dead_stage.start_layer,
                dead_stage.end_layer,
            )
        else:
            log.warning(
                "request=%d chain failure attributed to %s[%d..%d] (head was %s)",
                request_id,
                dead_stage.device,
                dead_stage.start_layer,
                dead_stage.end_layer,
                head_stage.device,
            )
            self.mark_dead(dead_stage.device)

        backup_dev = self.recovery.get(dead_stage.device)
        if backup_dev is None:
            raise RuntimeError(
                f"no recovery entry for dead device {dead_stage.device}"
            )
        backup_addr = self.worker_addresses.get(backup_dev)
        if backup_addr is None:
            raise RuntimeError(
                f"recovery device {backup_dev} has no address"
            )

        # PromoteBackup is idempotent on the worker side (StageRunner
        # logs but no-ops if already promoted), so it's safe to call even
        # in the heartbeat-first path.
        try:
            with WorkerClient(backup_addr) as client:
                client.promote_backup(for_device_id=dead_stage.device)
        except Exception:
            log.exception(
                "request=%d promote_backup on %s failed",
                request_id, backup_dev,
            )
            raise

        self._rewire_chain()
        # Drop surviving workers' stale KV caches for this request; the
        # full-chain replay below rebuilds them deterministically.
        self._evict_kv_for_request(request_id)

        new_plan = self.current_plan()
        new_head = new_plan[0]
        last_resp = self._replay_through_chain(
            request_id, new_head, current_position
        )
        return new_head, last_resp

    def _recover_surgical(
        self,
        request_id: RequestId,
        head_stage: Stage,
        error: grpc.RpcError,
        current_position: int,
    ) -> tuple[Stage, Any]:
        """Surgical recovery — rebuild ONLY the promoted backup's KV.

        Same ``(new_head_stage, last_response)`` contract as
        :meth:`_recover_from_chain_failure`, but instead of evicting every
        survivor's KV and replaying the whole request from position 0
        through the entire chain (O(positions × all stages)), we:

          1. promote the backup + rewire the chain (identical prefix), then
          2. replay the *dead stage's* mirrored inputs for positions
             0..P-1 into the promoted backup with ``replay_only=True`` —
             rebuilding only that one stage's KV, leaving the survivors'
             KV intact (they already hold 0..P-1), and
          3. run the failed position P LIVE: feed the mirrored dead-stage
             input at P into the backup and forward downstream, which
             yields the recovered token. The chain head already advanced
             to P on the failed attempt, so we do NOT re-run it — the
             mirrored dead-stage input at P *is* the head's output at P.

        Cost: O(positions × 1 stage). See design spec §10.

        Async-mirror safety: the worker mirror is fire-and-forget, so the
        input for position P may not have arrived yet. If the mirrored
        history is shorter than P+1 we cannot reconstruct P without
        re-running the head, so we fall back to the correct-but-costly
        full-chain replay rather than emit a silently-wrong token.
        """
        dead_stage = self._attribute_chain_failure(head_stage, error)
        if dead_stage.device not in self._dead:
            log.warning(
                "request=%d surgical recovery: chain failure attributed to "
                "%s[%d..%d] (head was %s)",
                request_id, dead_stage.device,
                dead_stage.start_layer, dead_stage.end_layer, head_stage.device,
            )
            self.mark_dead(dead_stage.device)

        backup_dev = self.recovery.get(dead_stage.device)
        if backup_dev is None:
            raise RuntimeError(
                f"no recovery entry for dead device {dead_stage.device}"
            )
        backup_addr = self.worker_addresses.get(backup_dev)
        if backup_addr is None:
            raise RuntimeError(f"recovery device {backup_dev} has no address")

        # PromoteBackup is idempotent on the worker side.
        try:
            with WorkerClient(backup_addr) as client:
                client.promote_backup(for_device_id=dead_stage.device)
        except Exception:
            log.exception(
                "request=%d promote_backup on %s failed", request_id, backup_dev
            )
            raise
        self._rewire_chain()

        dead_key = (int(dead_stage.start_layer), int(dead_stage.end_layer))
        history = self.cache.get_history(request_id, dead_key)

        # Async-mirror lag safety fallback: no mirrored input for position P
        # → we can't reconstruct P surgically. Fall back to full replay.
        if len(history) <= current_position:
            log.warning(
                "request=%d surgical recovery: mirror history for stage[%d..%d] "
                "has %d positions (<= failed position %d); falling back to "
                "full-chain replay",
                request_id, *dead_key, len(history), current_position,
            )
            self._evict_kv_for_request(request_id)
            new_plan = self.current_plan()
            new_head = new_plan[0]
            last_resp = self._replay_through_chain(
                request_id, new_head, current_position
            )
            return new_head, last_resp

        # Locate the promoted backup stage now owning the dead layer range.
        plan = self.current_plan()
        backup_stage = next(
            (s for s in plan
             if (int(s.start_layer), int(s.end_layer)) == dead_key),
            None,
        )
        if backup_stage is None:
            raise RuntimeError(
                f"layer range {dead_key} not present in post-recovery plan"
            )

        log.warning(
            "request=%d SURGICAL rebuild: backup %s stage[%d..%d] KV "
            "positions 0..%d, then run %d live (history_len=%d)",
            request_id, backup_stage.device, *dead_key,
            current_position - 1, current_position, len(history),
        )
        # Rebuild ONLY the backup's KV for 0..P-1 — no forward, survivors
        # keep their intact caches.
        for i in range(current_position):
            self._invoke(
                backup_stage, request_id, history[i],
                is_prefill=(i == 0), position=i, replay_only=True,
            )
        # Run position P live: forwards backup → downstream and yields the
        # recovered response. The head already advanced to P; we skip it.
        last_resp = self._invoke(
            backup_stage, request_id, history[current_position],
            is_prefill=(current_position == 0),
            position=current_position, replay_only=False,
        )
        return backup_stage, last_resp

    def _recover_replicate(
        self,
        request_id: RequestId,
        head_stage: Stage,
        error: grpc.RpcError,
        current_position: int,
    ) -> tuple[Stage, Any]:
        """Full-KV-replication recovery — install the dead stage's own stored
        KV columns onto the promoted backup, then run the failed position live.
        No survivor fetch, no XOR, no slot-spread guard (cf. _recover_parity):
        replicate holds the dead stage's OWN columns, not survivors', so there
        is no alignment skew to guard against.

        Falls back to :meth:`_recover_surgical` (which itself ladders to full
        replay) whenever the stored columns can't be trusted — never emits a
        wrong token:
          * the dead stage is the head (coord-sourced, never stored);
          * the stored columns are incomplete for the slots the victim held;
          * the mirrored dead-stage input for the failed position is missing.

        Cost: one LoadKV + one live position — no per-position replay, no
        survivor RPCs. See docs/superpowers/specs/2026-07-22-replication-
        baseline-design.md.
        """
        dead_stage = self._attribute_chain_failure(head_stage, error)
        if int(dead_stage.start_layer) == 1:  # head: coord-sourced, never stored
            log.info(
                "request=%d replicate: dead stage is the head; deferring to "
                "surgical", request_id,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        if dead_stage.device not in self._dead:
            log.warning(
                "request=%d replicate recovery: chain failure attributed to "
                "%s[%d..%d] (head was %s)",
                request_id, dead_stage.device,
                dead_stage.start_layer, dead_stage.end_layer, head_stage.device,
            )
            self.mark_dead(dead_stage.device)
        dead_key = (int(dead_stage.start_layer), int(dead_stage.end_layer))

        # `current_position` is the GENERATION-STEP index (0=prefill,
        # 1,2,3,...=decode), not the absolute KV-slot count -- prefill
        # (position 0) durably stores `past_length` slots (the whole
        # prompt) in ONE step, then each decode step adds exactly one more.
        # So by the time a decode at `current_position` fails, the dead
        # stage has durably stored slots 0..(past_length+current_position-2)
        # -- n_slots = past_length + current_position - 1. (A crash during
        # prefill itself has nothing durable yet -- n_slots = 0.) Mirrors
        # how _recover_parity derives n_slots from actual survivor byte
        # lengths rather than assuming it equals current_position.
        req_state = self._requests.get(request_id)
        past_length = int(req_state.past_length) if req_state is not None else 0
        n_slots = (
            past_length + current_position - 1 if current_position >= 1 else 0
        )
        if n_slots < 1 or not self.replica_cache.is_complete(
            request_id, dead_key, up_to_position=n_slots - 1
        ):
            log.info(
                "request=%d replicate: stored KV incomplete for %s; "
                "deferring to surgical", request_id, dead_key,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        stored = self.replica_cache.get_stage_kv(request_id, dead_key)
        if stored is None:
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        history = self.cache.get_history(request_id, dead_key)
        if len(history) <= current_position:
            log.warning(
                "request=%d replicate: mirror history len=%d <= failed pos %d; "
                "fallback to surgical", request_id, len(history), current_position,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        # Size-mismatch guard hoisted above promote/rewire (mirrors
        # _recover_parity's discipline of finishing all geometry checks
        # before touching the backup): a fallback here must leave the
        # backup un-promoted and the chain un-rewired, not half-done.
        n_heads, head_dim, np_dtype, itemsize = self._kv_dims()
        n_dead_layers = dead_key[1] - dead_key[0] + 1
        dead_slot_bytes = n_dead_layers * 2 * n_heads * head_dim * itemsize
        if len(stored) != n_slots * dead_slot_bytes:
            log.info(
                "request=%d replicate: stored KV size %d != expected %d (%d slots x %d); "
                "deferring to surgical",
                request_id, len(stored), n_slots * dead_slot_bytes, n_slots, dead_slot_bytes,
            )
            return self._recover_surgical(request_id, head_stage, error, current_position)

        backup_dev = self.recovery.get(dead_stage.device)
        if backup_dev is None:
            raise NoRecoveryError(f"no backup for {dead_stage.device}")
        backup_addr = self.worker_addresses.get(backup_dev)
        if backup_addr is None:
            raise RuntimeError(f"recovery device {backup_dev} has no address")
        try:
            with WorkerClient(backup_addr) as client:
                client.promote_backup(for_device_id=dead_stage.device)
        except Exception:
            log.exception(
                "request=%d promote_backup on %s failed", request_id, backup_dev
            )
            raise
        self._rewire_chain()

        dead_slots = np.frombuffer(stored, dtype=np.uint8).reshape(
            n_slots, dead_slot_bytes
        )
        dead_kv_bytes = self._slot_major_to_layer_major(
            dead_slots, n_dead_layers, n_heads, head_dim, np_dtype
        )

        backup_stage = next(
            (s for s in self.current_plan()
             if (int(s.start_layer), int(s.end_layer)) == dead_key),
            None,
        )
        if backup_stage is None:
            raise RuntimeError(
                f"layer range {dead_key} not present in post-recovery plan"
            )

        log.warning(
            "request=%d REPLICATE reconstruct: backup %s stage[%d..%d] "
            "slots=%d (stored KV, zero-forward), then run pos %d live",
            request_id, backup_stage.device, *dead_key, n_slots, current_position,
        )
        with WorkerClient(self.worker_addresses[backup_stage.device]) as client:
            client.load_kv(
                request_id=request_id,
                start_layer=dead_key[0], end_layer=dead_key[1],
                kv_bytes=dead_kv_bytes, num_positions=n_slots,
            )

        last_resp = self._invoke(
            backup_stage, request_id, history[current_position],
            is_prefill=(current_position == 0),
            position=current_position, replay_only=False,
        )
        return backup_stage, last_resp

    def _recover_parity(
        self,
        request_id: RequestId,
        head_stage: Stage,
        error: grpc.RpcError,
        current_position: int,
    ) -> tuple[Stage, Any]:
        """Zero-forward parity recovery — reconstruct the dead stage's KV by
        byte-XOR of the surviving non-head stages' intact KV with the
        maintained parity blob, install it onto the promoted backup, and run
        only the failed position live. No model forward pass rebuilds the KV.

        Falls back to :meth:`_recover_surgical` (which itself ladders to full
        replay) whenever parity can't be trusted — never emits a wrong token:
          * the dead stage is the head (coord-sourced, not in the parity
            group);
          * a FetchKV RPC fails, or a survivor's KV byte-count doesn't match
            the expected slot geometry;
          * parity is incomplete for any needed slot (an in-flight KV push
            hasn't landed yet);
          * the mirrored dead-stage input for the failed position is missing.

        Scope (topology): any non-head victim that has at least one non-head
        survivor DOWNSTREAM of it is reconstructed here. Survivors need not
        agree on their slot count: the ones UPSTREAM of the victim already
        completed the failed position P (one extra KV slot) while the
        downstream ones never received it, so we reconstruct the shared
        prefix N = min(survivor slot counts) — exactly what the victim holds,
        since it crashed at the TOP of its RunStage before appending P — and
        slice the upstream survivors back to N before XOR-ing.

        Honest limits that remain:
          * single fault only — two dead stages leave the XOR underdetermined
            (the parity completeness gate catches it → surgical);
          * a victim with NO downstream non-head survivor (i.e. the LAST
            stage) leaves every survivor one slot LONGER than the victim, so
            that extra shared slot's parity is missing the victim's own
            contribution — the completeness gate trips and recovery SAFELY
            falls back to surgical;
          * a crash at position 0 (prefill) has no prior KV to zero-forward
            reconstruct from, so it degenerates to running prefill live (an
            actual forward pass), not a zero-forward one;
          * "any non-head victim" above assumes :meth:`_attribute_chain_failure`
            names the true victim, which needs the intermediate hop that
            first sees the RpcError to reach its ``except`` handler and
            relay the trailer. That holds for a fail-fast downstream
            failure (the successor errors immediately). It does NOT hold
            for a victim that HANGS 2+ hops down: every hop shares nearly
            the same ``timeout=10.0``, so the entry hop's own deadline can
            trip first and it blames its own (alive) next hop instead —
            fixing that needs inner hops to carry shorter deadlines than
            outer ones (future work).

        LAYOUT: the parity blob and the workers' MirrorKV columns are
        SLOT-major (per absolute KV-slot, layers within a slot);
        ``export_kv``/``install_kv`` are LAYER-major (per layer, all
        positions). :meth:`_xor_reconstruct_kv` reconciles the two.

        Cost: O(survivors) FetchKV + one LoadKV + one live position — no
        per-position replay. See design spec §10 (parity).
        """
        dead_stage = self._attribute_chain_failure(head_stage, error)
        # Head is coord-sourced and never ships KV — not in the parity group.
        if int(dead_stage.start_layer) == 1:
            log.info(
                "request=%d parity: dead stage is the head; deferring to surgical",
                request_id,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        # RAID-6 (k=2): if two non-head stages are dead, reconstruct both via P+Q.
        dead_nonhead = [
            s for s in self.placement
            if int(s.start_layer) > 1 and s.device in self._dead
        ]
        if self.parity_k == 2 and len(dead_nonhead) == 2:
            return self._recover_parity_double(
                request_id, head_stage, error, current_position, dead_nonhead
            )
        if self.parity_k == 2 and len(dead_nonhead) > 2:
            log.warning("request=%d RAID-6: >2 dead non-head stages; surgical",
                        request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        if dead_stage.device not in self._dead:
            log.warning(
                "request=%d parity recovery: chain failure attributed to "
                "%s[%d..%d] (head was %s)",
                request_id, dead_stage.device,
                dead_stage.start_layer, dead_stage.end_layer, head_stage.device,
            )
            self.mark_dead(dead_stage.device)
        dead_key = (int(dead_stage.start_layer), int(dead_stage.end_layer))

        # Survivors = current-plan NON-HEAD stages that are neither the dead
        # stage's range nor the promoted backup's — the ORIGINAL alive
        # non-head stages, whose KV for this request is still intact. (After
        # mark_dead the plan already substitutes the backup into dead_key, so
        # excluding dead_key leaves exactly those survivors.)
        survivors = [
            s for s in self.current_plan()
            if int(s.start_layer) > 1
            and (int(s.start_layer), int(s.end_layer)) != dead_key
        ]
        if not survivors:
            log.warning(
                "request=%d parity: no non-head survivors; fallback to surgical",
                request_id,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        n_heads, head_dim, np_dtype, itemsize = self._kv_dims()

        # Fetch every survivor's LAYER-major KV up front (before promote/rewire
        # — survivors don't move, so a fallback here stays pristine). Any RPC
        # failure or geometry mismatch → surgical.
        try:
            surv_kv: list[tuple[Stage, bytes]] = []
            for s in survivors:
                buf, _ = self._fetch_stage_kv(request_id, s, current_position)
                surv_kv.append((s, buf))
        except Exception:  # noqa: BLE001
            log.exception(
                "request=%d parity survivor FetchKV failed; fallback to surgical",
                request_id,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        # Each survivor's own absolute KV-slot count comes from its byte length —
        # FetchKV's num_positions only echoes the request. Survivors need NOT
        # agree: in the sync chain the stages UPSTREAM of the victim already
        # appended the failed position P's KV before the chain reached it, so
        # they carry one slot MORE than the downstream ones. The dead stage
        # crashed at the top of its RunStage, before appending P, so it holds
        # exactly the slots every non-head stage shares — N = the minimum. The
        # extra trailing slot(s) on the upstream survivors are sliced off during
        # the XOR (see :meth:`_xor_reconstruct_kv`).
        slot_counts: list[int] = []
        for s, buf in surv_kv:
            n_l = int(s.end_layer) - int(s.start_layer) + 1
            bytes_per_slot = n_l * 2 * n_heads * head_dim * itemsize
            if bytes_per_slot == 0 or len(buf) % bytes_per_slot != 0:
                log.warning(
                    "request=%d parity: survivor %s KV size %d not a multiple of "
                    "slot size %d; fallback to surgical",
                    request_id, s.device, len(buf), bytes_per_slot,
                )
                return self._recover_surgical(
                    request_id, head_stage, error, current_position
                )
            slot_counts.append(len(buf) // bytes_per_slot)
        if max(slot_counts) - min(slot_counts) > 1:
            # Only the upstream +1 skew is legal (upstream stages completed
            # position P, downstream ones never received it). A wider spread
            # means a survivor returned a short/stale buffer — reconstructing
            # from it would install a truncated KV and silently emit wrong
            # tokens. Fall back.
            log.warning(
                "request=%d parity: survivor slot-count spread %d exceeds the "
                "legal upstream +1 skew (counts=%s); fallback to surgical",
                request_id, max(slot_counts) - min(slot_counts), slot_counts,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        n_slots = min(slot_counts)
        if n_slots == 0:
            log.warning(
                "request=%d parity: survivors share no KV slots; "
                "fallback to surgical", request_id,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        # Completeness gate: every slot must have all non-head contributors.
        for slot in range(n_slots):
            if not self.parity_cache.is_complete(request_id, slot):
                log.warning(
                    "request=%d parity incomplete at slot %d/%d; "
                    "fallback to surgical", request_id, slot, n_slots,
                )
                return self._recover_surgical(
                    request_id, head_stage, error, current_position
                )

        # Need the mirrored dead-stage input for the failed position to run it
        # live (the chain head already advanced to P; we do NOT re-run it).
        history = self.cache.get_history(request_id, dead_key)
        if len(history) <= current_position:
            log.warning(
                "request=%d parity: mirror history len=%d <= failed pos %d; "
                "fallback to surgical", request_id, len(history), current_position,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )

        # Promote backup + rewire (identical prefix to surgical).
        backup_dev = self.recovery.get(dead_stage.device)
        if backup_dev is None:
            raise RuntimeError(
                f"no recovery entry for dead device {dead_stage.device}"
            )
        backup_addr = self.worker_addresses.get(backup_dev)
        if backup_addr is None:
            raise RuntimeError(f"recovery device {backup_dev} has no address")
        try:
            with WorkerClient(backup_addr) as client:
                client.promote_backup(for_device_id=dead_stage.device)
        except Exception:
            log.exception(
                "request=%d promote_backup on %s failed", request_id, backup_dev
            )
            raise
        self._rewire_chain()

        # Reconstruct the dead stage's LAYER-major KV via slot-wise XOR.
        dead_kv_bytes = self._xor_reconstruct_kv(
            request_id, dead_key, surv_kv, n_slots,
            n_heads=n_heads, head_dim=head_dim,
            np_dtype=np_dtype, itemsize=itemsize,
        )

        backup_stage = next(
            (s for s in self.current_plan()
             if (int(s.start_layer), int(s.end_layer)) == dead_key),
            None,
        )
        if backup_stage is None:
            raise RuntimeError(
                f"layer range {dead_key} not present in post-recovery plan"
            )

        log.warning(
            "request=%d PARITY reconstruct: backup %s stage[%d..%d] KV "
            "slots=%d (zero-forward XOR), then run pos %d live",
            request_id, backup_stage.device, *dead_key, n_slots, current_position,
        )
        with WorkerClient(self.worker_addresses[backup_stage.device]) as client:
            client.load_kv(
                request_id=request_id,
                start_layer=dead_key[0], end_layer=dead_key[1],
                kv_bytes=dead_kv_bytes, num_positions=n_slots,
            )

        # Run the failed position live: feed the mirrored dead-stage input at P
        # into the backup and forward downstream — yields the recovered token.
        last_resp = self._invoke(
            backup_stage, request_id, history[current_position],
            is_prefill=(current_position == 0),
            position=current_position, replay_only=False,
        )
        return backup_stage, last_resp

    def _kv_dims(self) -> tuple[int, int, Any, int]:
        """(n_heads, head_dim, numpy dtype, itemsize) for this model's KV
        tensors — mirrors StageRunner._kv_shape so reconstructed bytes match
        the workers' export/install layout exactly."""
        config = self.handle.model.config
        n_heads = (
            getattr(config, "num_key_value_heads", None)
            or config.num_attention_heads
        )
        head_dim = getattr(config, "head_dim", None) or (
            config.hidden_size // config.num_attention_heads
        )
        np_dtype = {"float32": np.float32, "float16": np.float16}[self.dtype]
        return int(n_heads), int(head_dim), np_dtype, int(np.dtype(np_dtype).itemsize)

    def _fetch_stage_kv(
        self, request_id: RequestId, stage: Stage, up_to_position: int
    ) -> tuple[bytes, int]:
        """Pull one stage's LAYER-major ``export_kv`` bytes off its worker."""
        with WorkerClient(self.worker_addresses[stage.device]) as client:
            return client.fetch_kv(
                request_id=request_id,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                up_to_position=int(up_to_position),
            )

    @staticmethod
    def _slot_major_to_layer_major(
        dead_slots,  # np.ndarray[uint8], shape (n_slots, dead_slot_bytes)
        n_dead_layers: int,
        n_heads: int,
        head_dim: int,
        np_dtype,
    ) -> bytes:
        """Turn per-slot dead-stage columns into LAYER-major install_kv bytes.

        Inverse of extract_kv_column's layout: reshape each slot to
        (n_dead_layers, 2, n_heads, head_dim), stack over slots, then move the
        slot axis back between heads and head_dim (transpose (1,2,3,0,4)).
        Axis order pinned by the parity bit-exact end-to-end test.
        """
        import numpy as np
        n_slots = dead_slots.shape[0]
        dead_slot_major = dead_slots.view(np_dtype).reshape(
            n_slots, n_dead_layers, 2, n_heads, head_dim
        )
        dead_layer_major = np.ascontiguousarray(
            np.transpose(dead_slot_major, (1, 2, 3, 0, 4))
        )
        return dead_layer_major.tobytes()

    def _xor_reconstruct_kv(
        self,
        request_id: RequestId,
        dead_key: tuple[int, int],
        surv_kv: list[tuple[Stage, bytes]],
        n_slots: int,
        *,
        n_heads: int,
        head_dim: int,
        np_dtype: Any,
        itemsize: int,
    ) -> bytes:
        """Reconstruct the dead stage's LAYER-major KV bytes.

        Each survivor's LAYER-major ``export_kv`` buffer reshapes to
        ``(n_layers, 2, n_heads, N, head_dim)``; moving the slot axis to the
        front (transpose ``(3, 0, 1, 2, 4)``) gives per-slot columns whose
        byte layout is exactly what ``extract_kv_column`` pushed into the
        parity blob. Per slot we XOR the survivors' columns into a copy of the
        parity blob (uint8, zero-padded to the widest column) and slice out the
        dead stage's own column. Reassembling slots and inverting the transpose
        (``(1, 2, 3, 0, 4)``) yields LAYER-major bytes for ``install_kv``.

        The transpose axis order is pinned by the bit-exact end-to-end test.
        """
        n_dead_layers = dead_key[1] - dead_key[0] + 1
        dead_slot_bytes = n_dead_layers * 2 * n_heads * head_dim * itemsize

        # Survivor LAYER-major -> per-slot uint8 rows [slot][column bytes].
        surv_rows: list[np.ndarray] = []
        for stage, buf in surv_kv:
            n_l = int(stage.end_layer) - int(stage.start_layer) + 1
            # -1 on the slot axis: a survivor UPSTREAM of the victim holds one
            # slot MORE than the shared count (it processed the failed position
            # before the chain reached the victim). Slice back to `n_slots`
            # after the transpose so every survivor lines up on slots 0..N-1 —
            # KV is append-only, so slot i's bytes are identical either way.
            arr = np.frombuffer(buf, dtype=np_dtype).reshape(
                n_l, 2, n_heads, -1, head_dim
            )
            slot_major = np.ascontiguousarray(
                np.transpose(arr, (3, 0, 1, 2, 4))[:n_slots]
            )
            surv_rows.append(slot_major.reshape(n_slots, -1).view(np.uint8))

        dead_slots = np.empty((n_slots, dead_slot_bytes), dtype=np.uint8)
        for slot in range(n_slots):
            parity = self.parity_cache.get_parity(request_id, slot)
            if parity is None:  # guarded by the completeness gate; defensive
                raise RuntimeError(
                    f"request={request_id} parity missing for slot {slot}"
                )
            acc = np.frombuffer(parity, dtype=np.uint8).copy()
            for rows in surv_rows:
                col = rows[slot]
                acc[: col.size] ^= col
            dead_slots[slot] = acc[:dead_slot_bytes]

        return self._slot_major_to_layer_major(
            dead_slots, n_dead_layers, n_heads, head_dim, np_dtype
        )

    def _gf_reconstruct_kv(
        self,
        request_id: RequestId,
        dead_keys: list[tuple[int, int]],   # exactly 2, ordered by rank x<y
        surv: list[tuple[Stage, bytes, int]],  # (stage, layer-major bytes, rank)
        n_slots: int,
        *,
        n_heads: int,
        head_dim: int,
        np_dtype: Any,
        itemsize: int,
    ) -> dict[tuple[int, int], bytes]:
        """Reconstruct TWO dead non-head stages' LAYER-major KV via GF(2^8) P+Q.

        Per slot: Pxy = P ⊕ (XOR of survivor columns); Qxy = Q ⊕ (Σ g^rank·col);
        solve_two_erasures(Pxy, Qxy, x, y) → the two dead columns concatenated in
        rank order. Both dead stages share the same slot layout, but may differ in
        bytes-per-slot (different layer counts), so slice each victim's own bytes
        out of the solved column by its own geometry.
        """
        from radp.coordinator.gf256 import gf_mul_scalar, gf_pow, solve_two_erasures

        (x_key, y_key) = dead_keys
        x = self._parity_coeff[x_key]
        y = self._parity_coeff[y_key]
        x_bytes = (x_key[1] - x_key[0] + 1) * 2 * n_heads * head_dim * itemsize
        y_bytes = (y_key[1] - y_key[0] + 1) * 2 * n_heads * head_dim * itemsize

        # Survivor LAYER-major -> per-slot uint8 rows (same reshape/transpose as
        # _xor_reconstruct_kv), plus each survivor's rank for the Q accumulation.
        surv_rows: list[tuple[np.ndarray, int]] = []
        for stage, buf, rank in surv:
            n_l = int(stage.end_layer) - int(stage.start_layer) + 1
            arr = np.frombuffer(buf, dtype=np_dtype).reshape(n_l, 2, n_heads, -1, head_dim)
            slot_major = np.ascontiguousarray(
                np.transpose(arr, (3, 0, 1, 2, 4))[:n_slots])
            surv_rows.append((slot_major.reshape(n_slots, -1).view(np.uint8), rank))

        x_slots = np.empty((n_slots, x_bytes), dtype=np.uint8)
        y_slots = np.empty((n_slots, y_bytes), dtype=np.uint8)
        for slot in range(n_slots):
            p = self.parity_cache.get_parity(request_id, slot)
            q = self.parity_cache.get_qparity(request_id, slot)
            if p is None or q is None:
                raise RuntimeError(f"request={request_id} P/Q missing at slot {slot}")
            pxy = np.frombuffer(p, dtype=np.uint8).copy()
            qxy = np.frombuffer(q, dtype=np.uint8).copy()
            for rows, rank in surv_rows:
                col = rows[slot]
                pxy[: col.size] ^= col
                qxy[: col.size] ^= gf_mul_scalar(gf_pow(2, rank), col)
            dx, dy = solve_two_erasures(pxy, qxy, x, y)
            x_slots[slot] = dx[:x_bytes]
            y_slots[slot] = dy[:y_bytes]

        return {
            x_key: self._slot_major_to_layer_major(
                x_slots, x_key[1] - x_key[0] + 1, n_heads, head_dim, np_dtype),
            y_key: self._slot_major_to_layer_major(
                y_slots, y_key[1] - y_key[0] + 1, n_heads, head_dim, np_dtype),
        }

    def _recover_parity_double(
        self, request_id, head_stage, error, current_position, dead_nonhead,
    ):
        # order the two victims by rank (start_layer); mark both dead defensively
        dead_nonhead = sorted(dead_nonhead, key=lambda s: int(s.start_layer))
        dead_keys = [(int(s.start_layer), int(s.end_layer)) for s in dead_nonhead]
        for s in dead_nonhead:
            if s.device not in self._dead:
                self.mark_dead(s.device)

        survivors = [
            s for s in self.current_plan()
            if int(s.start_layer) > 1
            and (int(s.start_layer), int(s.end_layer)) not in dead_keys
        ]
        if not survivors:
            log.warning("request=%d RAID-6: no non-head survivors; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        n_heads, head_dim, np_dtype, itemsize = self._kv_dims()
        try:
            surv_kv = []
            for s in survivors:
                buf, _ = self._fetch_stage_kv(request_id, s, current_position)
                surv_kv.append((s, buf))
        except Exception:  # noqa: BLE001
            log.exception("request=%d RAID-6 survivor FetchKV failed; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        # slot geometry — identical rule to the single path (min shared prefix)
        slot_counts = []
        for s, buf in surv_kv:
            n_l = int(s.end_layer) - int(s.start_layer) + 1
            bps = n_l * 2 * n_heads * head_dim * itemsize
            if bps == 0 or len(buf) % bps != 0:
                log.warning("request=%d RAID-6 survivor geometry bad; surgical", request_id)
                return self._recover_surgical(request_id, head_stage, error, current_position)
            slot_counts.append(len(buf) // bps)
        if max(slot_counts) - min(slot_counts) > 1:
            log.warning("request=%d RAID-6 survivor slot spread >1; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)
        n_slots = min(slot_counts)
        if n_slots == 0:
            return self._recover_surgical(request_id, head_stage, error, current_position)
        for slot in range(n_slots):
            if not self.parity_cache.is_complete(request_id, slot):
                log.warning("request=%d RAID-6 parity incomplete slot %d; surgical",
                            request_id, slot)
                return self._recover_surgical(request_id, head_stage, error, current_position)

        # both victims need a mirrored input at the failed position to run live;
        # we enter the chain at the upstream-most victim.
        up_key = dead_keys[0]
        history = self.cache.get_history(request_id, up_key)
        if len(history) <= current_position:
            log.warning("request=%d RAID-6 mirror history short; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        # promote + rewire BOTH backups
        for s in dead_nonhead:
            backup_dev = self.recovery.get(s.device)
            if backup_dev is None or self.worker_addresses.get(backup_dev) is None:
                raise RuntimeError(f"no recovery/address for dead device {s.device}")
            with WorkerClient(self.worker_addresses[backup_dev]) as client:
                client.promote_backup(for_device_id=s.device)
        self._rewire_chain()

        surv_ranked = [
            (s, buf, self._parity_coeff[(int(s.start_layer), int(s.end_layer))])
            for s, buf in surv_kv
        ]
        recon = self._gf_reconstruct_kv(
            request_id, dead_keys, surv_ranked, n_slots,
            n_heads=n_heads, head_dim=head_dim, np_dtype=np_dtype, itemsize=itemsize,
        )
        for dkey in dead_keys:
            backup_stage = next(
                (s for s in self.current_plan()
                 if (int(s.start_layer), int(s.end_layer)) == dkey), None)
            if backup_stage is None:
                raise RuntimeError(f"layer range {dkey} absent from post-recovery plan")
            with WorkerClient(self.worker_addresses[backup_stage.device]) as client:
                client.load_kv(request_id=request_id, start_layer=dkey[0],
                               end_layer=dkey[1], kv_bytes=recon[dkey],
                               num_positions=n_slots)

        log.warning("request=%d RAID-6 reconstruct: victims=%s slots=%d, run pos %d live",
                    request_id, dead_keys, n_slots, current_position)
        entry_stage = next(
            s for s in self.current_plan()
            if (int(s.start_layer), int(s.end_layer)) == up_key)
        last_resp = self._invoke(
            entry_stage, request_id, history[current_position],
            is_prefill=(current_position == 0), position=current_position,
            replay_only=False,
        )
        return entry_stage, last_resp

    def _replay_through_chain(
        self,
        request_id: RequestId,
        new_head: Stage,
        current_position: int,
    ) -> Any:
        """Replay the head's cached input history end-to-end through the
        (rewired) chain. Returns the last RunStageResponse — which is the
        recovered response for the failed step.
        """
        head_key = (int(new_head.start_layer), int(new_head.end_layer))
        history = self.cache.get_history(request_id, head_key)
        if not history:
            raise RuntimeError(
                f"request={request_id} no head history to replay through chain"
            )
        log.info(
            "request=%d replay %d positions through chain head %s[%d..%d]",
            request_id, len(history), new_head.device, *head_key,
        )
        last_resp: Any = None
        for i, blob in enumerate(history):
            last_resp = self._invoke(
                new_head, request_id, blob,
                is_prefill=(i == 0), position=i, replay_only=False,
            )
        return last_resp

    def _evict_kv_for_request(self, request_id: RequestId) -> None:
        """Tell every alive worker to drop this request's KV cache, so
        the upcoming replay rebuilds it from scratch. Best-effort —
        failures are logged but ignored (the worker may already be dead).
        """
        for device_id in self.worker_addresses:
            if device_id in self._dead:
                continue
            try:
                stub = self._get_stub(device_id)
                stub.EvictRequest(
                    radp_pb2.EvictRequestRequest(request_id=int(request_id))
                )
            except Exception:  # noqa: BLE001
                log.debug(
                    "EvictRequest on %s during recovery failed (ignored)",
                    device_id,
                )

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
        position: int,
    ) -> tuple[
        torch.Tensor | None,
        torch.Tensor | None,
        list[StageTiming],
        int | None,
    ]:
        """Run the deployed pipeline.

        Returns ``(hidden, attention_mask, timings, next_token_id)``:
          - Phase 1a (coord-mediated head): the chain tail returns the
            final activation. hidden/attention_mask are populated,
            next_token_id is None — coord applies its own head + sampler.
          - Phase 1b (head on chain tail): tail samples on-device and
            returns next_token_id; hidden/attention_mask are None and
            coord skips its head/sampler entirely.
        """
        plan = self.current_plan()
        if not plan:
            raise RuntimeError("empty plan — no workers to dispatch to")

        # EXP-D3 chain topology (Phase 1a): coord only invokes the FIRST
        # worker. SetNextHop wiring (configured during deploy) makes each
        # worker forward its activation directly to its successor; the
        # chain tail returns the final activation back through nested
        # gRPC responses. Coord still applies lm_head + sampling here.
        first_stage = plan[0]
        first_key = (int(first_stage.start_layer), int(first_stage.end_layer))
        blob = encode({
            "hidden_states": hidden.cpu(),
            "attention_mask": attention_mask.cpu(),
        })
        # Phase 2: prime the mirror cache locally for the chain-head stage —
        # the head worker won't mirror its own input back to us (coord *is*
        # the source), but the failure-recovery path still needs to find
        # this entry in cache.get_history((req, first_key)).
        self.cache.put(request_id, first_key, position, blob)
        invoke_start = time.perf_counter()
        try:
            resp = self._invoke(
                first_stage, request_id, blob, is_prefill=is_prefill,
                position=position,
            )
        except (grpc.RpcError, TimeoutError) as e:
            # Phase F: in async chain mode the ResultReady wake-up never
            # arrived within async_chain_timeout_seconds, so _invoke
            # raises TimeoutError instead of an RpcError. There's no
            # trailer in this case (the fire-and-forget chain unwound
            # long ago) — _attribute_chain_failure handles the missing
            # trailing_metadata attribute gracefully and falls back to
            # the head stage. The recovery driver's "already-dead" branch
            # then picks up wherever the heartbeat path left things and
            # finishes the rewire + replay.
            log.warning(
                "request=%d chain RunStage to %s[%d..%d] raised: %s",
                request_id, first_stage.device,
                first_stage.start_layer, first_stage.end_layer, e,
            )
            first_stage, resp = self._recover_from_chain_failure(
                request_id, first_stage, e, position
            )
            plan = self.current_plan()
        chain_wall = time.perf_counter() - invoke_start
        timings = [
            StageTiming(
                device=first_stage.device,
                start_layer=int(first_stage.start_layer),
                end_layer=int(plan[-1].end_layer),
                invoke_seconds=chain_wall,
            )
        ]
        # Phase 1b path: chain tail sampled the token on-device.
        if getattr(resp, "has_next_token", False):
            return None, None, timings, int(resp.next_token_id)
        # Phase 1a path: tail returned the final activation; coord head + sample.
        decoded = decode(bytes(resp.activation))
        hidden = decoded["hidden_states"].to(self.torch_device)
        attention_mask = decoded["attention_mask"].to(self.torch_device)
        return hidden, attention_mask, timings, None

    def _replay_stage_history(
        self, request_id: RequestId, stage_key: tuple[int, int]
    ) -> None:
        """Replay cached activations into whichever device now owns ``stage_key``.

        Phase 2: history is the contiguous prefix [position 0 = prefill,
        position 1 = decode 1, …]. We re-issue them with the original
        positions so the backup's mirror entries match coord's view.
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
        # Phase 3: replay_only so the backup just rebuilds its KV cache
        # without chain-forwarding into the surviving downstream stages
        # (which already have the correct cache from the original run).
        for i, blob in enumerate(history):
            self._invoke(
                owner, request_id, blob,
                is_prefill=(i == 0), position=i, replay_only=True,
            )

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
        position: int,
        replay_only: bool = False,
    ) -> Any:
        """Returns a RunStageResponse-shaped object. In sync chain mode
        this is the raw RPC response; in async chain mode we register a
        pending future, fire the head call (which returns ACK immediately
        because the worker fans the call out async), then block until
        the chain tail's ResultReady RPC populates the future. Replay
        always runs in sync mode regardless of chain_mode — replay onto a
        freshly-promoted backup must NOT chain-forward, so async makes no
        sense there.

        ``replay_only=True`` instructs the worker to run only its local
        stage forward (rebuilding KV cache) without chain-forwarding or
        head-sampling. See ``_replay_stage_history``.
        """
        stub = self._get_stub(stage.device)
        use_async = self.chain_mode == "async" and not replay_only
        req = radp_pb2.RunStageRequest(
            activation=activation_blob,
            request_id=int(request_id),
            is_prefill=is_prefill,
            start_layer=int(stage.start_layer),
            end_layer=int(stage.end_layer),
            position=int(position),
            replay_only=bool(replay_only),
            async_chain=use_async,
        )
        if not use_async:
            return stub.RunStage(req)
        # Async path: register future, fire head call (returns ACK fast),
        # wait for the chain tail to wake us via ResultReady.
        ev, payload = self._register_pending(request_id, position)
        try:
            stub.RunStage(req)  # propagates RpcError so callers' recovery still fires
            if not ev.wait(self.async_chain_timeout_seconds):
                raise TimeoutError(
                    f"async chain timed out after "
                    f"{self.async_chain_timeout_seconds}s "
                    f"waiting for ResultReady (req={request_id}, pos={position})"
                )
            return radp_pb2.RunStageResponse(
                request_id=int(request_id),
                activation=payload.get("activation", b""),
                has_next_token=bool(payload.get("has_next_token", False)),
                next_token_id=int(payload.get("next_token_id", 0)),
            )
        finally:
            self._unregister_pending(request_id, position)

    def _evict_everywhere(self, request_id: RequestId) -> None:
        """Best-effort: ask every (currently-alive) worker to drop this request's cache."""
        self.cache.evict_request(request_id)
        self.parity_cache.evict_request(request_id)
        self.replica_cache.evict_request(request_id)
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
    # Architecture-dispatched embed + head
    # ------------------------------------------------------------------
    def _embed(
        self,
        input_ids: torch.Tensor,
        attention_mask_2d: torch.Tensor,
        *,
        past_kv_length: int,
    ) -> torch.Tensor:
        return self._arch.embed(self._decoder, input_ids, attention_mask_2d, past_kv_length)

    def _head(self, hidden: torch.Tensor) -> torch.Tensor:
        return self._arch.head(self._decoder, self.handle.model.lm_head, hidden)

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
                        hidden, _, _, _ = self._run_pipeline(
                            request_id, hidden, attention_mask_4d,
                            is_prefill=True, position=0,
                        )
                        assert hidden is not None
                        return self._head(hidden)
                except grpc.RpcError:
                    attempts += 1
                    if attempts > len(self.placement):
                        raise
                    log.warning("request=%d prefill RPC failure — retrying", request_id)
        finally:
            self._evict_everywhere(request_id)
