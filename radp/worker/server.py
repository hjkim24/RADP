"""gRPC worker server (Phase 3).

WorkerService:
  - LoadStage / LoadBackup / PromoteBackup: stage lifecycle
  - RunStage: per-stage forward (now selects loaded stage by layer range)

Spawns a HeartbeatSender thread if a coordinator address is provided.
"""

from __future__ import annotations

import contextlib
import json
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


class _MirrorDispatcher:
    """Fire-and-forget MirrorActivation pusher to the coord (EXP-D3 Phase 2).

    Single-thread executor so per-(request, stage) sends preserve order on
    the wire; the coord still tolerates reorder via positioned writes, but
    a single sender thread is the cheapest way to keep the common case in
    order without per-RPC sequence accounting. ``submit()`` never raises —
    a transient coord blip drops the mirror for that step; replay still
    has whatever positions did make it through, and the gateway's
    contiguous-prefix replay (see ActivationCache.get_history) stops at
    the first gap instead of skipping a step.
    """

    def __init__(self, coordinator_address: str) -> None:
        self._addr = coordinator_address
        self._channel = grpc.insecure_channel(coordinator_address, options=_GRPC_OPTIONS)
        self._stub = radp_pb2_grpc.CoordinatorServiceStub(self._channel)
        self._exec = futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mirror"
        )

    def submit(
        self,
        *,
        request_id: int,
        start_layer: int,
        end_layer: int,
        position: int,
        activation: bytes,
        is_prefill: bool,
    ) -> None:
        # Executor may already be shut down (server stopping); swallow.
        with contextlib.suppress(RuntimeError):
            self._exec.submit(
                self._send_blocking,
                request_id, start_layer, end_layer, position, activation, is_prefill,
            )

    def _send_blocking(
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

    def close(self) -> None:
        self._exec.shutdown(wait=False, cancel_futures=True)
        with contextlib.suppress(Exception):
            self._channel.close()


class _WorkerServicer(radp_pb2_grpc.WorkerServiceServicer):  # type: ignore[misc]
    def __init__(
        self,
        runner: StageRunner,
        mirror: _MirrorDispatcher | None = None,
    ) -> None:
        self._runner = runner
        self._mirror = mirror
        self._next_lock = threading.Lock()
        # Chain forwarding: {(my_start, my_end): (next_addr, channel, stub,
        # next_start, next_end)}. SetNextHop() populates this for the
        # *primary* stage; on PromoteBackup the coord will re-issue
        # SetNextHop for the promoted stage.
        self._next_hops: dict[
            tuple[int, int], tuple[str, Any, Any, int, int]
        ] = {}

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
        # EXP-D3 Phase 2 mirror: fire-and-forget the input activation back
        # to the coord BEFORE running the stage, so even a crash mid-stage
        # leaves the coord with enough history to replay onto the recovery
        # peer. Skip mirroring on the first stage — coord generated that
        # input locally and primes its own cache (see RequestGateway).
        if self._mirror is not None and int(request.start_layer) > 1:
            self._mirror.submit(
                request_id=int(request.request_id),
                start_layer=int(request.start_layer),
                end_layer=int(request.end_layer),
                position=int(request.position),
                activation=bytes(request.activation),
                is_prefill=bool(request.is_prefill),
            )
        # EXP-D3 Phase 1b: chain tail with a head loaded runs the local
        # stage AND applies head + greedy argmax, returning the next token
        # id directly. Coord skips its own head + sampling step.
        if next_hop is None and self._runner.has_head:
            next_token = self._runner.run_tail_and_sample(
                request_id=RequestId(request.request_id),
                activation_blob=bytes(request.activation),
                start=LayerIdx(request.start_layer),
                end=LayerIdx(request.end_layer),
                is_prefill=request.is_prefill,
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
        # EXP-D3 Phase 1a chain forwarding — if a next hop is registered for
        # this stage, propagate the result downstream synchronously and
        # return whatever the chain tail produced. With no next hop
        # registered and no head loaded the worker behaves as the legacy
        # coord-mediated star-topology tail and returns the activation.
        if next_hop is None:
            return radp_pb2.RunStageResponse(
                activation=result, request_id=request.request_id,
            )
        _next_addr, next_stub, next_start, next_end = next_hop
        forwarded = next_stub.RunStage(
            radp_pb2.RunStageRequest(
                activation=result,
                request_id=int(request.request_id),
                is_prefill=bool(request.is_prefill),
                start_layer=next_start,
                end_layer=next_end,
                position=int(request.position),
            )
        )
        return forwarded

    def EvictRequest(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._runner.evict_request(RequestId(request.request_id))
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
        self.mirror: _MirrorDispatcher | None = None
        if coordinator_address:
            self.mirror = _MirrorDispatcher(coordinator_address)
        radp_pb2_grpc.add_WorkerServiceServicer_to_server(
            _WorkerServicer(self.runner, self.mirror), self._server
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
        self._server.stop(grace).wait()
        log.info("worker %s stopped", self.device_id)
