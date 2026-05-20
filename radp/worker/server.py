"""gRPC worker server: WorkerService implementation."""

from __future__ import annotations

import threading
from concurrent import futures
from typing import Any

import grpc

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId, LayerIdx, RequestId
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

    def RunStage(self, request: Any, context: grpc.ServicerContext) -> Any:
        result = self._runner.run(
            request_id=RequestId(request.request_id),
            activation_blob=bytes(request.activation),
            is_prefill=request.is_prefill,
        )
        return radp_pb2.RunStageResponse(activation=result, request_id=request.request_id)

    def LoadBackup(self, request: Any, context: grpc.ServicerContext) -> Any:
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Phase 3")
        return radp_pb2.LoadBackupResponse(ok=False)

    def PromoteBackup(self, request: Any, context: grpc.ServicerContext) -> Any:
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Phase 3")
        return radp_pb2.PromoteBackupResponse(ok=False)


class WorkerServer:
    """gRPC server hosting a StageRunner."""

    def __init__(
        self,
        device_id: DeviceId,
        bind_address: str,
        *,
        torch_device: str = "cpu",
        dtype: str = "float32",
        max_workers: int = 4,
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

    def start(self) -> None:
        self._server.add_insecure_port(self.bind_address)
        self._server.start()
        log.info("worker %s listening on %s", self.device_id, self.bind_address)

    def wait_for_termination(self) -> None:
        self._server.wait_for_termination()

    def stop(self, grace: float = 1.0) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._server.stop(grace).wait()
        log.info("worker %s stopped", self.device_id)
