"""gRPC worker server (Phase 3).

WorkerService:
  - LoadStage / LoadBackup / PromoteBackup: stage lifecycle
  - RunStage: per-stage forward (now selects loaded stage by layer range)

Spawns a HeartbeatSender thread if a coordinator address is provided.
"""

from __future__ import annotations

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


class _WorkerServicer(radp_pb2_grpc.WorkerServiceServicer):  # type: ignore[misc]
    def __init__(self, runner: StageRunner) -> None:
        self._runner = runner

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
        result = self._runner.run(
            request_id=RequestId(request.request_id),
            activation_blob=bytes(request.activation),
            start=LayerIdx(request.start_layer),
            end=LayerIdx(request.end_layer),
            is_prefill=request.is_prefill,
        )
        return radp_pb2.RunStageResponse(activation=result, request_id=request.request_id)

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
        radp_pb2_grpc.add_WorkerServiceServicer_to_server(
            _WorkerServicer(self.runner), self._server
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
        self._server.stop(grace).wait()
        log.info("worker %s stopped", self.device_id)
