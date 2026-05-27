"""Coordinator orchestrator (Phase 3).

On start:
  1. Read YAML config: model, workers, placement, recovery.
  2. Deploy each Stage to its assigned worker via LoadStage.
  3. For each backup (R(j) = k), call LoadBackup on k.
  4. Build a RequestGateway over (placement, recovery).
  5. Start the FailureDetector — heartbeat timeouts call gateway.mark_dead.
  6. Start gRPC CoordinatorService.
"""

from __future__ import annotations

from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import grpc
import yaml

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.failure_detector import FailureDetector, HeartbeatRecord
from radp.coordinator.gateway import RequestGateway
from radp.coordinator.recovery_plan import inverse_recovery

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
    recovery: RecoveryTable = field(default_factory=dict)
    torch_device: str = "cpu"
    dtype: str = "float32"
    heartbeat_timeout_seconds: float = 5.0
    heartbeat_tick_seconds: float = 1.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> CoordinatorConfig:
        data = yaml.safe_load(Path(path).read_text())
        model = data["model"]
        coord = data["coordinator"]
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
        recovery_raw = data.get("recovery", {})
        recovery: RecoveryTable = {
            DeviceId(k): DeviceId(v) for k, v in recovery_raw.items()
        }
        return cls(
            model_id=model["id"],
            bind_address=coord["bind"],
            workers=workers,
            placement=placement,
            recovery=recovery,
            torch_device=model.get("torch_device", "cpu"),
            dtype=model.get("dtype", "float32"),
            heartbeat_timeout_seconds=float(
                coord.get("heartbeat_timeout_seconds", 5.0)
            ),
            heartbeat_tick_seconds=float(coord.get("heartbeat_tick_seconds", 1.0)),
        )


class _CoordinatorServicer(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    def __init__(self, gateway: RequestGateway, detector: FailureDetector) -> None:
        self._gateway = gateway
        self._detector = detector

    def Heartbeat(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._detector.record(
            HeartbeatRecord(
                device_id=DeviceId(request.device_id),
                last_ts_ns=int(request.ts_ns),
                free_memory_bytes=float(request.free_memory_bytes),
                total_memory_bytes=float(request.total_memory_bytes),
                device_class=str(request.device_class),
            )
        )
        return radp_pb2.HeartbeatResponse(ack=True)

    def Generate(self, request: Any, context: grpc.ServicerContext) -> Any:
        prompt = request.prompt
        max_tokens = max(1, int(request.max_tokens))
        # Proto defaults: 0 means "use the natural off-state".
        eos = int(request.eos_token_id) if request.eos_token_id else None
        seed = int(request.seed) if request.seed else None
        top_p = float(request.top_p) if 0.0 < float(request.top_p) <= 1.0 else 1.0
        log.info(
            "Generate prompt_len=%d max_tokens=%d temp=%.2f top_k=%d top_p=%.2f eos=%s seed=%s",
            len(prompt), max_tokens, request.temperature, request.top_k, top_p, eos, seed,
        )
        token_ids = self._gateway.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=float(request.temperature),
            top_k=int(request.top_k),
            top_p=top_p,
            eos_token_id=eos,
            seed=seed,
        )
        # Stream each decoded token; final chunk signals done.
        tokenizer = self._gateway.handle.tokenizer
        for i, tid in enumerate(token_ids):
            yield radp_pb2.GenerateChunk(text=tokenizer.decode([tid]), done=False)
            if i == len(token_ids) - 1:
                yield radp_pb2.GenerateChunk(text="", done=True)


class CoordinatorServer:
    def __init__(self, config: CoordinatorConfig) -> None:
        self.config = config
        self._addr_lookup: dict[DeviceId, str] = {
            w.device_id: w.address for w in config.workers
        }
        self.gateway: RequestGateway | None = None
        self.detector: FailureDetector | None = None
        self._server: grpc.Server | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def deploy(self) -> None:
        """Push primary stages, then backup stages, to their target workers."""
        for stage in self.config.placement:
            address = self._addr_lookup[stage.device]
            log.info(
                "deploy primary %s layers[%d..%d] -> %s",
                stage.device, stage.start_layer, stage.end_layer, address,
            )
            with WorkerClient(address) as client:
                client.load_stage(
                    device_id=stage.device,
                    start_layer=int(stage.start_layer),
                    end_layer=int(stage.end_layer),
                    model_id=self.config.model_id,
                )

        # Backup deployment: for each k, load every j in R⁻¹(k)'s stage.
        stage_by_device = {s.device: s for s in self.config.placement}
        for k, backed_up_js in inverse_recovery(self.config.recovery).items():
            backup_addr = self._addr_lookup.get(k)
            if backup_addr is None:
                log.warning("recovery target %s has no address; skipping backup load", k)
                continue
            with WorkerClient(backup_addr) as client:
                for j in backed_up_js:
                    j_stage = stage_by_device.get(j)
                    if j_stage is None:
                        log.warning("backup source %s has no stage; skipping", j)
                        continue
                    log.info(
                        "deploy backup %s layers[%d..%d] (for %s) -> %s",
                        k, j_stage.start_layer, j_stage.end_layer, j, backup_addr,
                    )
                    client.load_backup(
                        for_device_id=j,
                        start_layer=int(j_stage.start_layer),
                        end_layer=int(j_stage.end_layer),
                        model_id=self.config.model_id,
                    )

    def start(self) -> None:
        self.gateway = RequestGateway(
            placement=self.config.placement,
            recovery=self.config.recovery,
            worker_addresses=self._addr_lookup,
            model_id=self.config.model_id,
            torch_device=self.config.torch_device,
            dtype=self.config.dtype,
        )

        def on_failure(device_id: DeviceId) -> None:
            assert self.gateway is not None
            try:
                self.gateway.mark_dead(device_id)
                # Trigger promotion on the backup target (if any).
                k = self.config.recovery.get(device_id)
                if k is None or k not in self._addr_lookup:
                    return
                try:
                    with WorkerClient(self._addr_lookup[k]) as client:
                        client.promote_backup(for_device_id=device_id)
                except Exception:  # noqa: BLE001
                    log.exception("promote_backup on %s failed", k)
            except Exception:  # noqa: BLE001
                log.exception("on_failure handling for %s failed", device_id)

        self.detector = FailureDetector(
            on_failure=on_failure,
            timeout_seconds=self.config.heartbeat_timeout_seconds,
            tick_interval_seconds=self.config.heartbeat_tick_seconds,
        )
        self.detector.start()

        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=16),
            options=_GRPC_OPTIONS,
        )
        radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(
            _CoordinatorServicer(self.gateway, self.detector), self._server
        )
        self._server.add_insecure_port(self.config.bind_address)
        self._server.start()
        log.info("coordinator listening on %s", self.config.bind_address)

    def wait_for_termination(self) -> None:
        if self._server is None:
            raise RuntimeError("CoordinatorServer.start has not been called")
        self._server.wait_for_termination()

    def stop(self, grace: float = 1.0) -> None:
        if self.detector is not None:
            self.detector.stop()
        if self._server is not None:
            self._server.stop(grace).wait()
            log.info("coordinator stopped")
