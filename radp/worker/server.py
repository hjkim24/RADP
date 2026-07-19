"""gRPC worker server (Phase 3).

WorkerService:
  - LoadStage / LoadBackup / PromoteBackup: stage lifecycle
  - RunStage: per-stage forward (now selects loaded stage by layer range)

Spawns a HeartbeatSender thread if a coordinator address is provided.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from concurrent import futures
from typing import Any

import grpc

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId, LayerIdx, RequestId
from radp.profiler.layer_profiler import profile_layers
from radp.worker.heartbeat_sender import HeartbeatSender
from radp.worker.peer_measurer import measure_peer
from radp.worker.stage_runner import StageRunner

log = get_logger(__name__)

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


class _CoordDispatcher:
    """Fire-and-forget pusher to the coord — handles both Phase 2
    ``MirrorActivation`` (background bookkeeping) and Phase F
    ``ResultReady`` (chain-tail wake-up that's actually latency-critical).

    Two separate executors so a backed-up mirror queue never blocks a
    tail-of-chain ResultReady call. ``submit_mirror`` is single-threaded
    (ordered sends), ``submit_result`` has a small pool because the chain
    tail may need to fire ResultReady for several concurrent requests
    without head-of-line blocking. The gRPC channel is shared.

    ``submit_*`` never raises — a transient coord blip drops the push;
    the gateway falls back to its sync-chain retry path via Phase 3
    recovery when the chain tail's wake-up never arrives.
    """

    def __init__(self, coordinator_address: str) -> None:
        self._addr = coordinator_address
        self._channel = grpc.insecure_channel(coordinator_address, options=_GRPC_OPTIONS)
        self._stub = radp_pb2_grpc.CoordinatorServiceStub(self._channel)
        self._mirror_exec = futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mirror"
        )
        self._result_exec = futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="result-ready"
        )

    # --- Phase 2 mirror ----------------------------------------------------
    def submit_mirror(
        self,
        *,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        activation: bytes,
        is_prefill: bool,
    ) -> Any:
        """Returns the submitted Future (or None if the executor is shut
        down) so callers that need the push to have *landed* — e.g. the
        fault injector forcing the surgical branch — can block on it.
        """
        with contextlib.suppress(RuntimeError):
            return self._mirror_exec.submit(
                self._send_mirror,
                request_id, start_layer, end_layer, position, activation, is_prefill,
            )
        return None

    def _send_mirror(
        self,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        activation: bytes,
        is_prefill: bool,
    ) -> None:
        try:
            req = radp_pb2.MirrorActivationRequest(
                request_id=request_id,
                start_layer=start_layer,
                end_layer=end_layer,
                position=position,
                activation=activation,
                is_prefill=is_prefill,
            )
            self._stub.MirrorActivation(req, timeout=5.0)
        except Exception as e:  # noqa: BLE001
            log.debug(
                "MirrorActivation push for req=%d stage[%d..%d] pos=%d failed (%s); ignored",
                request_id, start_layer, end_layer, position, e,
            )

    # --- Parity KV push (worker -> coord, RADP_PARITY-gated) ---------------
    def submit_kv(
        self,
        *,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        kv_bytes: bytes,
        is_prefill: bool,
        num_positions: int,
    ) -> Any:
        with contextlib.suppress(RuntimeError):
            return self._mirror_exec.submit(
                self._send_kv,
                request_id, start_layer, end_layer, position,
                kv_bytes, is_prefill, num_positions,
            )
        return None

    def _send_kv(
        self,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        kv_bytes: bytes,
        is_prefill: bool,
        num_positions: int,
    ) -> None:
        try:
            self._stub.MirrorKV(radp_pb2.MirrorKVRequest(
                request_id=request_id,
                start_layer=start_layer,
                end_layer=end_layer,
                position=position,
                kv_bytes=kv_bytes,
                is_prefill=is_prefill,
                num_positions=num_positions,
            ), timeout=5.0)
        except Exception as e:  # noqa: BLE001
            log.debug(
                "MirrorKV push req=%d stage[%d..%d] pos=%d failed (%s); ignored",
                request_id, start_layer, end_layer, position, e,
            )

    # --- Phase F ResultReady (async chain return channel) ------------------
    def submit_result(
        self,
        *,
        request_id: int,
        position: int,
        activation: bytes,
        has_next_token: bool,
        next_token_id: int,
    ) -> None:
        with contextlib.suppress(RuntimeError):
            self._result_exec.submit(
                self._send_result,
                request_id, position, activation, has_next_token, next_token_id,
            )

    def _send_result(
        self,
        request_id: int,
        position: int,
        activation: bytes,
        has_next_token: bool,
        next_token_id: int,
    ) -> None:
        try:
            req = radp_pb2.ResultReadyRequest(
                request_id=request_id,
                position=position,
                activation=activation,
                has_next_token=has_next_token,
                next_token_id=next_token_id,
            )
            self._stub.ResultReady(req, timeout=5.0)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "ResultReady push for req=%d pos=%d failed (%s); "
                "gateway will time out and route through Phase 3 recovery",
                request_id, position, e,
            )

    def close(self) -> None:
        self._mirror_exec.shutdown(wait=False, cancel_futures=True)
        self._result_exec.shutdown(wait=False, cancel_futures=True)
        with contextlib.suppress(Exception):
            self._channel.close()


# Backward-compat alias — keeps the public symbol name workers used to
# import as ``_MirrorDispatcher`` (e.g. via tests).
_MirrorDispatcher = _CoordDispatcher


# --- Fleet fault injection (test-only) -----------------------------------
# Reproduces on the real fleet the in-process B1 injector: a *compute-time*
# crash (mid-forward raise), deliberately timed to land AFTER this position's
# input-mirror push has reached the coord, so recovery takes the surgical
# branch deterministically (a raw SIGKILL races the fire-and-forget mirror).
#
# Completely inert unless the worker is started with RADP_FAULT_INJECTION set
# — normal deployments pay nothing and can't be crashed by a stray file. When
# enabled, the target is read per-RunStage from a small JSON file, so a sweep
# can retarget the position without restarting the worker:
#   {"start": 16, "end": 17, "position": 8}
# Fires once (removes the file), matching the single-fault recovery model.
_FAULT_SPEC_PATH = os.environ.get("RADP_FAULT_SPEC", "/tmp/radp_fault.json")


def _maybe_inject_fault(
    runner: Any, request: Any, replay_only: bool, mirror_future: Any
) -> None:
    if replay_only or not os.environ.get("RADP_FAULT_INJECTION"):
        return
    try:
        with open(_FAULT_SPEC_PATH) as f:
            spec = json.load(f)
    except (FileNotFoundError, ValueError):
        return
    if (
        int(request.start_layer) == int(spec["start"])
        and int(request.end_layer) == int(spec["end"])
        and int(request.position) == int(spec["position"])
    ):
        # Block until THIS position's mirror has actually landed at the coord,
        # so get_history is a contiguous prefix through `position` and the
        # gateway stays on the surgical branch (len(history) > position).
        if mirror_future is not None:
            with contextlib.suppress(Exception):
                mirror_future.result(timeout=5.0)
        with contextlib.suppress(OSError):
            os.remove(_FAULT_SPEC_PATH)  # fire once
        device_id = getattr(runner, "device_id", "?")
        raise RuntimeError(
            f"injected compute-time crash: worker={device_id} "
            f"stage[{request.start_layer}..{request.end_layer}] "
            f"pos={request.position}"
        )


class _AsyncChainDispatcher:
    """Fires next-hop RunStage calls to the downstream worker in the
    background so the current worker's gRPC handler can return ACK
    immediately. A bounded pool caps concurrent in-flight forwards but
    multiple streams can interleave without per-stream head-of-line
    blocking. Sends that fail are logged at WARNING — the chain tail's
    ResultReady will never fire for those streams, and the gateway's
    per-request future will time out and trigger Phase 3 recovery.
    """

    def __init__(self, max_workers: int = 8) -> None:
        self._exec = futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="chain-fwd"
        )

    def submit(
        self,
        next_stub: Any,
        request: Any,
        *,
        request_id: int,
    ) -> None:
        with contextlib.suppress(RuntimeError):
            self._exec.submit(self._send, next_stub, request, request_id)

    def _send(self, next_stub: Any, request: Any, request_id: int) -> None:
        try:
            next_stub.RunStage(request, timeout=30.0)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async chain forward req=%d failed (%s); "
                "downstream chain tail will not fire ResultReady, "
                "gateway will time out",
                request_id, e,
            )

    def close(self) -> None:
        self._exec.shutdown(wait=False, cancel_futures=True)


class _WorkerServicer(radp_pb2_grpc.WorkerServiceServicer):  # type: ignore[misc]
    def __init__(
        self,
        runner: StageRunner,
        mirror: _CoordDispatcher | None = None,
    ) -> None:
        self._runner = runner
        # The "mirror" attribute name is kept for backward compatibility
        # with smoke tests that wired a single-purpose mirror dispatcher
        # directly. Newer code treats it as a general coord dispatcher
        # that also handles ResultReady wake-ups in async chain mode.
        self._mirror = mirror
        self._coord = mirror  # alias for clarity at Phase F call sites
        self._next_lock = threading.Lock()
        # Chain forwarding: {(my_start, my_end): (next_addr, channel, stub,
        # next_start, next_end)}. SetNextHop() populates this for the
        # *primary* stage; on PromoteBackup the coord will re-issue
        # SetNextHop for the promoted stage.
        self._next_hops: dict[
            tuple[int, int], tuple[str, Any, Any, int, int]
        ] = {}
        # Phase F async chain forwarder — only spun up when at least one
        # async RunStage call comes in, so sync-chain deployments don't
        # pay the executor cost.
        self._chain_fwd: _AsyncChainDispatcher | None = None
        # Per-request serial lock so two overlapping async steps for the
        # same request can't race on the same DynamicCache. Cleaned up
        # by EvictRequest at the end of each request's lifecycle.
        self._req_locks: dict[int, threading.Lock] = {}
        self._req_locks_guard = threading.Lock()

    def _request_lock(self, request_id: int) -> threading.Lock:
        with self._req_locks_guard:
            lock = self._req_locks.get(request_id)
            if lock is None:
                lock = threading.Lock()
                self._req_locks[request_id] = lock
            return lock

    def _drop_request_lock(self, request_id: int) -> None:
        with self._req_locks_guard:
            self._req_locks.pop(request_id, None)

    def _get_chain_fwd(self) -> _AsyncChainDispatcher:
        # Lazy — most workers in sync-chain mode never hit this.
        if self._chain_fwd is None:
            self._chain_fwd = _AsyncChainDispatcher()
        return self._chain_fwd

    def _get_next_hop(
        self, start: int, end: int
    ) -> tuple[str, Any, int, int] | None:
        """(next_addr, stub, next_start, next_end) or None if chain tail."""
        with self._next_lock:
            entry = self._next_hops.get((start, end))
            if entry is None:
                return None
            return entry[0], entry[2], entry[3], entry[4]

    def SetNextHop(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            next_addr = str(request.next_address).strip()
            key = (int(request.start_layer), int(request.end_layer))
            with self._next_lock:
                prev = self._next_hops.pop(key, None)
                if prev is not None:
                    with contextlib.suppress(Exception):
                        prev[1].close()  # close prior channel
                if next_addr:
                    channel = grpc.insecure_channel(next_addr, options=_GRPC_OPTIONS)
                    stub = radp_pb2_grpc.WorkerServiceStub(channel)
                    self._next_hops[key] = (
                        next_addr, channel, stub,
                        int(request.next_start_layer),
                        int(request.next_end_layer),
                    )
                    log.info(
                        "SetNextHop: stage[%d..%d] → %s stage[%d..%d]",
                        key[0], key[1], next_addr,
                        int(request.next_start_layer),
                        int(request.next_end_layer),
                    )
                else:
                    log.info(
                        "SetNextHop: stage[%d..%d] cleared (chain tail)",
                        key[0], key[1],
                    )
            return radp_pb2.SetNextHopResponse(ok=True)
        except Exception as e:  # noqa: BLE001
            log.exception("SetNextHop failed")
            return radp_pb2.SetNextHopResponse(ok=False, error=str(e))

    def LoadHead(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            self._runner.load_head(model_id=str(request.model_id))
            return radp_pb2.LoadHeadResponse(ok=True)
        except Exception as e:  # noqa: BLE001
            log.exception("LoadHead failed")
            return radp_pb2.LoadHeadResponse(ok=False, error=str(e))

    def LoadStage(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            self._runner.load_primary(
                model_id=request.model_id,
                start=LayerIdx(request.start_layer),
                end=LayerIdx(request.end_layer),
            )
            return radp_pb2.LoadStageResponse(ok=True)
        except Exception as e:  # noqa: BLE001
            log.exception("LoadStage failed")
            return radp_pb2.LoadStageResponse(ok=False, error=str(e))

    def LoadBackup(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            self._runner.load_backup(
                model_id=request.model_id,
                start=LayerIdx(request.start_layer),
                end=LayerIdx(request.end_layer),
                for_device_id=DeviceId(request.for_device_id),
            )
            return radp_pb2.LoadBackupResponse(ok=True)
        except Exception:  # noqa: BLE001
            log.exception("LoadBackup failed")
            return radp_pb2.LoadBackupResponse(ok=False)

    def PromoteBackup(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            self._runner.promote_backup(for_device_id=DeviceId(request.for_device_id))
            return radp_pb2.PromoteBackupResponse(ok=True)
        except Exception:  # noqa: BLE001
            log.exception("PromoteBackup failed")
            return radp_pb2.PromoteBackupResponse(ok=False)

    def RunStage(self, request: Any, context: grpc.ServicerContext) -> Any:
        next_hop = self._get_next_hop(int(request.start_layer), int(request.end_layer))
        replay_only = bool(getattr(request, "replay_only", False))
        async_chain = bool(getattr(request, "async_chain", False))
        # EXP-D3 Phase 2 mirror: fire-and-forget the input activation back
        # to the coord BEFORE running the stage, so even a crash mid-stage
        # leaves the coord with enough history to replay onto the recovery
        # peer. Skip on (a) the first stage — coord *is* the source — and
        # (b) replay calls — those activations ALREADY came from the cache.
        mirror_future = None
        if (
            self._mirror is not None
            and int(request.start_layer) > 1
            and not replay_only
        ):
            mirror_future = self._mirror.submit_mirror(
                request_id=int(request.request_id),
                start_layer=int(request.start_layer),
                end_layer=int(request.end_layer),
                position=int(request.position),
                activation=bytes(request.activation),
                is_prefill=bool(request.is_prefill),
            )
        # Test-only: crash here (after the mirror push) if armed for this
        # (stage, position) — see _maybe_inject_fault. No-op otherwise.
        _maybe_inject_fault(self._runner, request, replay_only, mirror_future)
        # Phase F: serialize concurrent async-mode steps for the same
        # request so they can't race on the same DynamicCache. Sync chain
        # is naturally serial via nested responses, so we only pay this
        # cost when async_chain is set.
        request_lock = (
            self._request_lock(int(request.request_id))
            if async_chain and not replay_only else None
        )
        if request_lock is not None:
            request_lock.acquire()
        try:
            return self._dispatch_run_stage(
                request, next_hop, replay_only, async_chain, context,
            )
        finally:
            if request_lock is not None:
                request_lock.release()

    def _maybe_push_parity_kv(self, request: Any, replay_only: bool) -> None:
        """Parity KV push (Task 4): after a non-head stage runs, ship each
        newly-added absolute KV slot to the coord for XOR'ing into the
        parity blob. Gated on RADP_PARITY so the default path pays nothing.
        The head (start_layer == 1) is coord-sourced and never ships KV;
        replay_only calls only rebuild the local cache, they don't produce
        new generation output, so they're excluded too."""
        if (
            not os.environ.get("RADP_PARITY")
            or int(request.start_layer) <= 1
            or replay_only
            or self._mirror is None
        ):
            return
        request_id = RequestId(request.request_id)
        start = LayerIdx(request.start_layer)
        end = LayerIdx(request.end_layer)
        seq_len = self._runner.kv_seq_len(request_id, start=start, end=end)
        new_slots = range(seq_len) if request.is_prefill else [seq_len - 1]
        for s in new_slots:
            if s < 0:
                continue
            with contextlib.suppress(Exception):
                col = self._runner.extract_kv_column(
                    request_id, start=start, end=end, position=s,
                )
                self._mirror.submit_kv(
                    request_id=int(request.request_id),
                    start_layer=int(request.start_layer),
                    end_layer=int(request.end_layer),
                    position=s,
                    kv_bytes=col,
                    is_prefill=bool(request.is_prefill),
                    num_positions=1,
                )

    def _dispatch_run_stage(
        self,
        request: Any,
        next_hop: tuple[str, Any, int, int] | None,
        replay_only: bool,
        async_chain: bool,
        context: grpc.ServicerContext,
    ) -> Any:
        # EXP-D3 Phase 1b: chain tail with a head loaded runs the local
        # stage AND applies head + greedy argmax, returning the next token
        # id directly. Coord skips its own head + sampling step.
        # Skip in replay_only mode — we only want to rebuild the KV cache,
        # not generate a token.
        if next_hop is None and self._runner.has_head and not replay_only:
            next_token = self._runner.run_tail_and_sample(
                request_id=RequestId(request.request_id),
                activation_blob=bytes(request.activation),
                start=LayerIdx(request.start_layer),
                end=LayerIdx(request.end_layer),
                is_prefill=request.is_prefill,
            )
            self._maybe_push_parity_kv(request, replay_only)
            if async_chain and self._coord is not None:
                # Phase F: chain tail wakes the gateway's future directly
                # over a separate RPC instead of letting the nested
                # response unwind. ACK back to the *predecessor* worker
                # so its async forwarder thread can free up.
                self._coord.submit_result(
                    request_id=int(request.request_id),
                    position=int(request.position),
                    activation=b"",
                    has_next_token=True,
                    next_token_id=int(next_token),
                )
                return radp_pb2.RunStageResponse(
                    request_id=request.request_id,
                )
            return radp_pb2.RunStageResponse(
                request_id=request.request_id,
                has_next_token=True,
                next_token_id=int(next_token),
            )
        # Local stage forward.
        result = self._runner.run(
            request_id=RequestId(request.request_id),
            activation_blob=bytes(request.activation),
            start=LayerIdx(request.start_layer),
            end=LayerIdx(request.end_layer),
            is_prefill=request.is_prefill,
        )
        self._maybe_push_parity_kv(request, replay_only)
        # EXP-D3 Phase 1a chain forwarding — if a next hop is registered for
        # this stage, propagate the result downstream synchronously and
        # return whatever the chain tail produced. With no next hop
        # registered and no head loaded the worker behaves as the legacy
        # coord-mediated star-topology tail and returns the activation.
        # Phase 3 replay_only: skip forwarding even when next_hop is set —
        # we only need this worker's KV cache rebuilt.
        if next_hop is None or replay_only:
            if (
                async_chain
                and not replay_only
                and self._coord is not None
                and next_hop is None
            ):
                # Phase F chain tail without head (Phase 1a fallback) —
                # ship the final activation back to the gateway via
                # ResultReady instead of returning it through the chain.
                self._coord.submit_result(
                    request_id=int(request.request_id),
                    position=int(request.position),
                    activation=result,
                    has_next_token=False,
                    next_token_id=0,
                )
                return radp_pb2.RunStageResponse(
                    request_id=request.request_id,
                )
            return radp_pb2.RunStageResponse(
                activation=result, request_id=request.request_id,
            )
        _next_addr, next_stub, next_start, next_end = next_hop
        next_req = radp_pb2.RunStageRequest(
            activation=result,
            request_id=int(request.request_id),
            is_prefill=bool(request.is_prefill),
            start_layer=next_start,
            end_layer=next_end,
            position=int(request.position),
            async_chain=async_chain,
        )
        if async_chain:
            # Phase F: fire-and-forget. Our handler returns ACK now; the
            # downstream worker (or the eventual chain tail) wakes the
            # gateway's future via ResultReady. We do NOT see the
            # downstream's failure here — async chain failure attribution
            # is delegated to the gateway's per-request timeout + Phase 3
            # heartbeat path, which still triggers full recovery.
            self._get_chain_fwd().submit(
                next_stub, next_req, request_id=int(request.request_id),
            )
            return radp_pb2.RunStageResponse(request_id=request.request_id)
        try:
            forwarded = next_stub.RunStage(next_req, timeout=10.0)
        except grpc.RpcError as e:
            # EXP-D3 Phase 3 chain-aware failure attribution. The downstream
            # call failed; stamp the failed (start, end) onto our gRPC trailer
            # so the coord identifies the correct dead worker instead of
            # mis-attributing the RpcError to *us*. Then abort our own
            # response with UNAVAILABLE so the gateway notices.
            code = (
                e.code() if hasattr(e, "code") else grpc.StatusCode.UNAVAILABLE
            )
            log.warning(
                "downstream chain RunStage to %s[%d..%d] failed (%s); "
                "stamping trailer and aborting",
                _next_addr, next_start, next_end, code,
            )
            context.set_trailing_metadata((
                ("radp-failed-start", str(next_start)),
                ("radp-failed-end", str(next_end)),
            ))
            context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"chain downstream {next_start}..{next_end} unreachable",
            )
            raise  # unreachable, but keeps the type checker happy
        return forwarded

    # --- KV recovery (parity): thin pass-throughs to Task 2's StageRunner
    # helpers. Layer-major layout, no slot-major conversion here — the
    # gateway (Task 6) owns all reconstruction-layout logic.
    def FetchKV(self, request: Any, context: grpc.ServicerContext) -> Any:
        kv = self._runner.export_kv(
            RequestId(request.request_id),
            start=LayerIdx(request.start_layer),
            end=LayerIdx(request.end_layer),
        )
        return radp_pb2.FetchKVResponse(
            kv_bytes=kv, num_positions=int(request.up_to_position) + 1,
        )

    def LoadKV(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._runner.install_kv(
            RequestId(request.request_id),
            start=LayerIdx(request.start_layer),
            end=LayerIdx(request.end_layer),
            kv_bytes=bytes(request.kv_bytes),
            num_positions=int(request.num_positions),
        )
        return radp_pb2.LoadKVResponse()

    def EvictRequest(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._runner.evict_request(RequestId(request.request_id))
        # Phase F: drop the per-request lock now that the request is done.
        self._drop_request_lock(int(request.request_id))
        return radp_pb2.EvictRequestResponse(ok=True)

    # ------------------------------------------------------------------
    # Phase D — profiling-based auto-scheduling
    # ------------------------------------------------------------------

    def Ping(self, request: Any, context: grpc.ServicerContext) -> Any:
        return radp_pb2.PingResponse(
            payload=request.payload,
            sent_ns=request.sent_ns,
            echo_ns=time.monotonic_ns(),
        )

    def MeasurePeer(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            bandwidth, latency = measure_peer(
                peer_address=request.peer_address,
                payload_bytes=int(request.payload_bytes),
                rounds=int(request.rounds),
            )
            return radp_pb2.MeasurePeerResponse(
                bandwidth_bps=bandwidth,
                latency_seconds=latency,
                ok=True,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("MeasurePeer to %s failed", request.peer_address)
            return radp_pb2.MeasurePeerResponse(ok=False, error=str(e))

    def ProfileLayers(self, request: Any, context: grpc.ServicerContext) -> Any:
        try:
            kwargs: dict[str, Any] = {
                "dtype": self._runner.dtype,
                "torch_device": self._runner.torch_device,
            }
            if request.warmup > 0:
                kwargs["warmup"] = int(request.warmup)
            if request.repeats > 0:
                kwargs["repeat"] = int(request.repeats)
            if request.seq_length > 0:
                kwargs["seq_length"] = int(request.seq_length)
            profiles = profile_layers(
                model_id=request.model_id,
                device_id=self._runner.device_id,
                **kwargs,
            )
            payload = json.dumps(
                [
                    {
                        "layer_idx": int(p.layer_idx),
                        "memory_bytes": p.memory_bytes,
                        "compute_time": {
                            str(k): float(v) for k, v in p.compute_time.items()
                        },
                    }
                    for p in profiles
                ]
            ).encode("utf-8")
            return radp_pb2.ProfileLayersResponse(
                serialized_profiles=payload, ok=True
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ProfileLayers(%s) failed", request.model_id)
            return radp_pb2.ProfileLayersResponse(ok=False, error=str(e))


class WorkerServer:
    """gRPC server hosting a StageRunner + optional heartbeat publisher."""

    def __init__(
        self,
        device_id: DeviceId,
        bind_address: str,
        *,
        coordinator_address: str | None = None,
        heartbeat_interval: float = 1.0,
        torch_device: str = "cpu",
        dtype: str = "float32",
        max_workers: int = 16,
        device_class: str = "",
    ) -> None:
        self.device_id = device_id
        self.bind_address = bind_address
        self.runner = StageRunner(device_id, torch_device=torch_device, dtype=dtype)
        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=max_workers),
            options=_GRPC_OPTIONS,
        )
        # EXP-D3 Phase 2 mirror cache pusher — only when we have a coord to
        # talk to. The dispatcher opens its own gRPC channel so RunStage
        # never blocks waiting on the coord.
        self.mirror: _CoordDispatcher | None = None
        if coordinator_address:
            self.mirror = _CoordDispatcher(coordinator_address)
        self._servicer = _WorkerServicer(self.runner, self.mirror)
        radp_pb2_grpc.add_WorkerServiceServicer_to_server(
            self._servicer, self._server
        )
        self._stopped = threading.Event()
        self.heartbeat: HeartbeatSender | None = None
        if coordinator_address:
            self.heartbeat = HeartbeatSender(
                device_id=device_id,
                coordinator_address=coordinator_address,
                interval_seconds=heartbeat_interval,
                device_class=device_class,
            )

    def start(self) -> None:
        self._server.add_insecure_port(self.bind_address)
        self._server.start()
        log.info("worker %s listening on %s", self.device_id, self.bind_address)
        if self.heartbeat is not None:
            self.heartbeat.start()

    def wait_for_termination(self) -> None:
        self._server.wait_for_termination()

    def stop(self, grace: float = 1.0) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        if self.heartbeat is not None:
            self.heartbeat.stop()
        if self.mirror is not None:
            self.mirror.close()
        if self._servicer._chain_fwd is not None:
            self._servicer._chain_fwd.close()
        self._server.stop(grace).wait()
        log.info("worker %s stopped", self.device_id)
