"""Coordinator orchestrator (Phase 3 + Phase D3).

Two startup modes, selected by `CoordinatorConfig.schedule_mode`:

  manual (default): placement + recovery come from the YAML. Server creates
  the gateway during start(), then deploy() pushes stages.

  auto (Phase D3): YAML omits placement/recovery. After start() brings up
  gRPC + heartbeat detection, auto_schedule() blocks for every expected
  worker to register, runs ProfileOrchestrator to gather layer/network/
  device profiles, then calls Scheduler.solve_alternating() to choose Ψ + R.
  deploy() then runs against the computed placement.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import grpc
import yaml

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.protocol import WorkerClient
from radp.common.types import (
    SLO,
    AlternatingResult,
    ClusterSpec,
    DeviceId,
    LayerIdx,
    Placement,
    RecoveryTable,
    Stage,
)
from radp.coordinator.failure_detector import FailureDetector, HeartbeatRecord
from radp.coordinator.gateway import RequestGateway
from radp.coordinator.profile_orchestrator import ProfileOrchestrator
from radp.coordinator.recovery_plan import inverse_recovery
from radp.coordinator.scheduler import Scheduler

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
    # Empty for schedule_mode == "auto" — populated at runtime by auto_schedule.
    placement: Placement = field(default_factory=list)
    recovery: RecoveryTable = field(default_factory=dict)
    torch_device: str = "cpu"
    dtype: str = "float32"
    heartbeat_timeout_seconds: float = 5.0
    heartbeat_tick_seconds: float = 1.0
    # ---- Phase D3 auto-scheduling parameters ---------------------------
    schedule_mode: str = "manual"           # "manual" | "auto"
    slo_ttft_seconds: float = 0.3
    slo_tbt_seconds: float = 0.1
    activation_bytes: int = 1_000_000
    profiling_layer_warmup: int = 1
    profiling_layer_repeats: int = 3
    profiling_layer_seq_length: int = 32
    profiling_network_payload_bytes: int = 1_048_576
    profiling_network_rounds: int = 10
    profiling_wait_timeout_seconds: float = 60.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> CoordinatorConfig:
        data = yaml.safe_load(Path(path).read_text())
        model = data["model"]
        coord = data["coordinator"]
        workers = [
            WorkerSpec(device_id=DeviceId(w["id"]), address=w["address"])
            for w in data["workers"]
        ]
        # placement / recovery are optional (omitted in auto mode)
        placement = [
            Stage(
                start_layer=LayerIdx(int(s["start"])),
                end_layer=LayerIdx(int(s["end"])),
                device=DeviceId(s["device"]),
            )
            for s in data.get("placement", []) or []
        ]
        recovery_raw = data.get("recovery") or {}
        recovery: RecoveryTable = {
            DeviceId(k): DeviceId(v) for k, v in recovery_raw.items()
        }
        slo = coord.get("slo") or {}
        profiling = coord.get("profiling") or {}
        schedule_mode = str(coord.get("schedule_mode", "manual")).lower()
        if schedule_mode not in {"manual", "auto"}:
            raise ValueError(
                f"coordinator.schedule_mode must be 'manual' or 'auto', "
                f"got {schedule_mode!r}"
            )
        if schedule_mode == "manual" and not placement:
            raise ValueError(
                "coordinator.schedule_mode='manual' requires a non-empty "
                "'placement' section in the YAML."
            )
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
            schedule_mode=schedule_mode,
            slo_ttft_seconds=float(slo.get("ttft_seconds", 0.3)),
            slo_tbt_seconds=float(slo.get("tbt_seconds", 0.1)),
            activation_bytes=int(coord.get("activation_bytes", 1_000_000)),
            profiling_layer_warmup=int(profiling.get("layer_warmup", 1)),
            profiling_layer_repeats=int(profiling.get("layer_repeats", 3)),
            profiling_layer_seq_length=int(profiling.get("layer_seq_length", 32)),
            profiling_network_payload_bytes=int(
                profiling.get("network_payload_bytes", 1_048_576)
            ),
            profiling_network_rounds=int(profiling.get("network_rounds", 10)),
            profiling_wait_timeout_seconds=float(
                profiling.get("wait_timeout_seconds", 60.0)
            ),
        )


class _CoordinatorServicer(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    """Backs CoordinatorService RPCs with the current server state.

    Holds a reference to the CoordinatorServer rather than to a snapshot of
    its gateway/detector, so it picks up the gateway the instant
    `auto_schedule()` installs it. Heartbeats arrive *before* the gateway
    exists in auto mode — that's intentional, so workers can register and
    profiling can run.
    """

    def __init__(self, server: CoordinatorServer) -> None:
        self._server = server

    def Heartbeat(self, request: Any, context: grpc.ServicerContext) -> Any:
        detector = self._server.detector
        if detector is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("FailureDetector not started")
            return radp_pb2.HeartbeatResponse(ack=False)
        detector.record(
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
        gateway = self._server.gateway
        if gateway is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(
                "Coordinator is still bootstrapping; auto-scheduling has "
                "not produced a placement yet."
            )
            return
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
        token_ids = gateway.generate(
            prompt,
            max_tokens=max_tokens,
            temperature=float(request.temperature),
            top_k=int(request.top_k),
            top_p=top_p,
            eos_token_id=eos,
            seed=seed,
        )
        # Stream each decoded token; final chunk signals done.
        tokenizer = gateway.handle.tokenizer
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
        # Mutable cluster state — `auto_schedule()` overwrites these in
        # auto mode; manual mode keeps the YAML values throughout.
        self.placement: Placement = list(config.placement)
        self.recovery: RecoveryTable = dict(config.recovery)
        self.gateway: RequestGateway | None = None
        self.detector: FailureDetector | None = None
        self._server: grpc.Server | None = None
        self._gateway_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def serve(self) -> None:
        """Bring the coordinator to a serving state in the order this mode requires.

        manual: deploy stages first, then start gRPC + gateway. (gRPC must
                not be listening before workers hold their stages, otherwise
                Generate calls would dispatch to unloaded workers.)
        auto:   start gRPC + detector first so workers can heartbeat, run
                auto_schedule() to derive placement/recovery, then deploy.

        Either way, on return the coordinator is ready to accept Generate.
        """
        if self.config.schedule_mode == "auto":
            self.start()
            self.auto_schedule()
            self.deploy()
        else:
            self.deploy()
            self.start()
        # Gateway is only created at the end of deploy(); guarantee it here.
        self._ensure_gateway()

    def deploy(self) -> None:
        """Push primary stages, then backup stages, to their target workers."""
        if not self.placement:
            raise RuntimeError(
                "deploy() called before placement is known. In auto mode, "
                "call auto_schedule() between start() and deploy()."
            )
        for stage in self.placement:
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
        stage_by_device = {s.device: s for s in self.placement}
        for k, backed_up_js in inverse_recovery(self.recovery).items():
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

    def _ensure_gateway(self) -> RequestGateway:
        """Lazy-create the RequestGateway. Requires `self.placement` to be set."""
        with self._gateway_lock:
            if self.gateway is None:
                if not self.placement:
                    raise RuntimeError(
                        "Cannot build gateway: placement is empty. "
                        "Call auto_schedule() first in auto mode."
                    )
                self.gateway = RequestGateway(
                    placement=self.placement,
                    recovery=self.recovery,
                    worker_addresses=self._addr_lookup,
                    model_id=self.config.model_id,
                    torch_device=self.config.torch_device,
                    dtype=self.config.dtype,
                )
            return self.gateway

    def start(self) -> None:
        """Bring up FailureDetector + gRPC server.

        In manual mode, the gateway is also created here (placement is
        already known from YAML). In auto mode, the gateway stays None
        until auto_schedule() runs — Generate RPCs reply UNAVAILABLE in
        the meantime, while Heartbeat keeps working so workers can register.
        """

        def on_failure(device_id: DeviceId) -> None:
            if self.gateway is None:
                log.warning(
                    "on_failure(%s) fired before gateway is ready; skipping",
                    device_id,
                )
                return
            try:
                self.gateway.mark_dead(device_id)
                k = self.recovery.get(device_id)
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
            _CoordinatorServicer(self), self._server
        )
        self._server.add_insecure_port(self.config.bind_address)
        self._server.start()
        log.info(
            "coordinator listening on %s (schedule_mode=%s)",
            self.config.bind_address, self.config.schedule_mode,
        )

    def auto_schedule(self) -> AlternatingResult:
        """Run ProfileOrchestrator + Scheduler to populate placement + recovery.

        Call this between start() and deploy() in auto mode. Blocks until
        every expected worker has heartbeated, then profiles layers + the
        worker→worker mesh, runs the Recovery-Aware DP, and stores the
        result on `self`. After this returns, deploy() can run.
        """
        if self.detector is None:
            raise RuntimeError("auto_schedule() must be called after start()")
        orch = ProfileOrchestrator(self._addr_lookup, self.detector)

        log.info(
            "auto-scheduling: waiting for %d workers (timeout=%.0fs)",
            len(self._addr_lookup),
            self.config.profiling_wait_timeout_seconds,
        )
        t_wait_start = time.perf_counter()
        records = orch.wait_for_workers(
            timeout_seconds=self.config.profiling_wait_timeout_seconds
        )
        wait_ms = (time.perf_counter() - t_wait_start) * 1000

        log.info("auto-scheduling: profiling layers (%s)", self.config.model_id)
        t_layers_start = time.perf_counter()
        layer_profiles = orch.collect_layer_profiles(
            self.config.model_id,
            warmup=self.config.profiling_layer_warmup,
            repeats=self.config.profiling_layer_repeats,
            seq_length=self.config.profiling_layer_seq_length,
        )
        layers_ms = (time.perf_counter() - t_layers_start) * 1000

        log.info("auto-scheduling: profiling network")
        t_network_start = time.perf_counter()
        network = orch.collect_network_profile(
            payload_bytes=self.config.profiling_network_payload_bytes,
            rounds=self.config.profiling_network_rounds,
        )
        network_ms = (time.perf_counter() - t_network_start) * 1000

        t_devprofiles_start = time.perf_counter()
        devices = ProfileOrchestrator.build_device_profiles(records, layer_profiles)
        devprofiles_ms = (time.perf_counter() - t_devprofiles_start) * 1000
        spec = ClusterSpec(
            devices=devices,
            layers=layer_profiles,
            network=network,
            slo=SLO(
                ttft_seconds=self.config.slo_ttft_seconds,
                tbt_seconds=self.config.slo_tbt_seconds,
            ),
            activation_bytes=self.config.activation_bytes,
        )

        log.info("auto-scheduling: solving DP (devices=%d, layers=%d)",
                 len(devices), len(layer_profiles))
        t_dp_start = time.perf_counter()
        result = Scheduler(spec).solve_alternating()
        dp_ms = (time.perf_counter() - t_dp_start) * 1000
        log.info(
            "auto-scheduling: solution max_stage_time=%.4fs converged=%s iterations=%d",
            result.max_stage_time, result.converged, result.iterations,
        )
        for stage in result.placement:
            log.info("  placement: %s ← layers[%d..%d]",
                     stage.device, stage.start_layer, stage.end_layer)
        for j, k in result.recovery.items():
            log.info("  recovery:  %s → %s (backup)", j, k)

        self.placement = list(result.placement)
        self.recovery = dict(result.recovery)
        self._write_scheduler_stats_sidecar(
            wait_ms=wait_ms,
            layers_ms=layers_ms,
            network_ms=network_ms,
            devprofiles_ms=devprofiles_ms,
            dp_ms=dp_ms,
            result=result,
            spec=spec,
            records=records,
        )
        return result

    def _write_scheduler_stats_sidecar(
        self,
        *,
        wait_ms: float,
        layers_ms: float,
        network_ms: float,
        devprofiles_ms: float,
        dp_ms: float,
        result: AlternatingResult,
        spec: ClusterSpec,
        records: dict[DeviceId, Any],
    ) -> None:
        """Dump every measurement auto_schedule made to /tmp/radp_scheduler_stats.json.

        Benchmarks read this to get the placement, recovery, profile data,
        and per-phase wall clock without parsing the journal. Path is fixed
        so deploys don't need to thread it through env vars. Best-effort —
        any failure here is logged and swallowed; the coordinator must not
        die just because the stats file couldn't be written.
        """
        try:
            stats = {
                "timestamp_ns": time.time_ns(),
                "model_id": self.config.model_id,
                "phase_ms": {
                    "wait_for_workers": wait_ms,
                    "collect_layer_profiles": layers_ms,
                    "collect_network_profile": network_ms,
                    "build_device_profiles": devprofiles_ms,
                    "scheduler_solve": dp_ms,
                    "total": wait_ms + layers_ms + network_ms + devprofiles_ms + dp_ms,
                },
                "scheduler_result": {
                    "max_stage_time_seconds": result.max_stage_time,
                    "iterations": result.iterations,
                    "converged": result.converged,
                },
                "placement": [
                    {
                        "device": str(s.device),
                        "start": int(s.start_layer),
                        "end": int(s.end_layer),
                    }
                    for s in result.placement
                ],
                "recovery": {str(j): str(k) for j, k in result.recovery.items()},
                "device_profiles": [
                    {
                        "id": str(d.id),
                        "total_memory_bytes": d.total_memory_bytes,
                        "compute_throughput": d.compute_throughput,
                    }
                    for d in spec.devices
                ],
                "layer_profiles": [
                    {
                        "layer_idx": int(lp.layer_idx),
                        "memory_bytes": lp.memory_bytes,
                        "compute_time": {
                            str(d): float(t) for d, t in lp.compute_time.items()
                        },
                    }
                    for lp in spec.layers
                ],
                "network_profile": {
                    "bandwidth_bps": {
                        f"{src}->{dst}": v
                        for (src, dst), v in spec.network.bandwidth.items()
                    },
                    "latency_seconds": {
                        f"{src}->{dst}": v
                        for (src, dst), v in spec.network.latency.items()
                    },
                },
                "heartbeat_classifiers": {
                    str(d): {
                        "free_memory_bytes": r.free_memory_bytes,
                        "total_memory_bytes": r.total_memory_bytes,
                        "device_class": r.device_class,
                    }
                    for d, r in records.items()
                },
            }
            path = Path("/tmp/radp_scheduler_stats.json")
            path.write_text(json.dumps(stats, indent=2))
            log.info("scheduler stats written to %s", path)
        except Exception:  # noqa: BLE001
            log.exception("failed to write scheduler stats sidecar")

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
