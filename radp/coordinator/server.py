"""Coordinator orchestrator (Phase 2 MVP).

On start:
  1. Read YAML config: model_id, workers (id + address), placement.
  2. For each Stage in placement, call WorkerService.LoadStage on the target.
  3. Build a RequestGateway over the placement.
  4. Start a gRPC CoordinatorService server exposing Generate(prompt, max_tokens).

Phase 2 supports both:
  - manual placement (placement section in YAML)
  - auto placement via the Phase 1 DP (placement: auto + profile path)
"""

from __future__ import annotations

from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc
import yaml

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway

log = get_logger(__name__)

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


@dataclass
class WorkerSpec:
    device_id: DeviceId
    address: str


@dataclass
class CoordinatorConfig:
    model_id: str
    bind_address: str
    workers: list[WorkerSpec]
    placement: Placement
    torch_device: str = "cpu"
    dtype: str = "float32"

    @classmethod
    def from_yaml(cls, path: str | Path) -> CoordinatorConfig:
        data = yaml.safe_load(Path(path).read_text())
        model_id = data["model"]["id"]
        torch_device = data["model"].get("torch_device", "cpu")
        dtype = data["model"].get("dtype", "float32")
        bind_address = data["coordinator"]["bind"]
        workers = [
            WorkerSpec(device_id=DeviceId(w["id"]), address=w["address"])
            for w in data["workers"]
        ]
        placement = [
            Stage(
                start_layer=LayerIdx(int(s["start"])),
                end_layer=LayerIdx(int(s["end"])),
                device=DeviceId(s["device"]),
            )
            for s in data["placement"]
        ]
        return cls(
            model_id=model_id,
            bind_address=bind_address,
            workers=workers,
            placement=placement,
            torch_device=torch_device,
            dtype=dtype,
        )


class _CoordinatorServicer(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    def __init__(self, gateway: RequestGateway) -> None:
        self._gateway = gateway

    def Heartbeat(self, request: Any, context: grpc.ServicerContext) -> Any:
        return radp_pb2.HeartbeatResponse(ack=True)

    def Generate(self, request: Any, context: grpc.ServicerContext) -> Any:
        prompt = request.prompt
        max_tokens = max(1, int(request.max_tokens))
        log.info("Generate prompt_len=%d max_tokens=%d", len(prompt), max_tokens)
        text_acc = prompt
        for step in range(max_tokens):
            _, token_text = self._gateway.next_token(text_acc)
            yield radp_pb2.GenerateChunk(text=token_text, done=False)
            text_acc = text_acc + token_text
            if step == max_tokens - 1:
                yield radp_pb2.GenerateChunk(text="", done=True)


class CoordinatorServer:
    def __init__(self, config: CoordinatorConfig) -> None:
        self.config = config
        self._addr_lookup: dict[DeviceId, str] = {w.device_id: w.address for w in config.workers}
        self.gateway: RequestGateway | None = None
        self._server: grpc.Server | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def deploy(self) -> None:
        """Push each stage to its target worker via LoadStage."""
        for stage in self.config.placement:
            address = self._addr_lookup[stage.device]
            log.info(
                "deploy %s layers[%d..%d] -> %s",
                stage.device, stage.start_layer, stage.end_layer, address,
            )
            with WorkerClient(address) as client:
                client.load_stage(
                    device_id=stage.device,
                    start_layer=int(stage.start_layer),
                    end_layer=int(stage.end_layer),
                    model_id=self.config.model_id,
                )

    def start(self) -> None:
        self.gateway = RequestGateway(
            placement=self.config.placement,
            worker_addresses=self._addr_lookup,
            model_id=self.config.model_id,
            torch_device=self.config.torch_device,
            dtype=self.config.dtype,
        )
        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=4),
            options=_GRPC_OPTIONS,
        )
        radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(
            _CoordinatorServicer(self.gateway), self._server
        )
        self._server.add_insecure_port(self.config.bind_address)
        self._server.start()
        log.info("coordinator listening on %s", self.config.bind_address)

    def wait_for_termination(self) -> None:
        if self._server is None:
            raise RuntimeError("CoordinatorServer.start has not been called")
        self._server.wait_for_termination()

    def stop(self, grace: float = 1.0) -> None:
        if self._server is not None:
            self._server.stop(grace).wait()
            log.info("coordinator stopped")
