"""Shared utilities for Phase 4 benchmarks.

Provides:
  * ``in_process_cluster``: spawn N WorkerServer instances on free localhost
    ports inside the test process; tear down on exit.
  * ``deploy``: helper that pushes primary stages (and backups if recovery
    is given) to those workers.
  * placement strategies: ``greedy_placement`` and ``round_robin`` for
    baselines; ``dp_placement_no_recovery`` for Jupiter-style; the
    Recovery-Aware DP is reached via ``Scheduler.solve`` with R.
  * ``RESULTS_DIR``: where benchmark JSON lands.
"""

from __future__ import annotations

import contextlib
import socket
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from radp.common.protocol import WorkerClient
from radp.common.types import (
    SLO,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    LayerIdx,
    NoFeasibleSolutionError,
    Placement,
    RecoveryTable,
    Stage,
)
from radp.coordinator.recovery_plan import inverse_recovery
from radp.coordinator.scheduler import Scheduler, uniform_placement
from radp.worker.server import WorkerServer

RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------------------------
# Process + cluster lifecycle
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def in_process_cluster(
    device_ids: list[str],
) -> Generator[tuple[dict[DeviceId, str], dict[DeviceId, WorkerServer]], None, None]:
    """Start one WorkerServer per id on free localhost ports."""
    servers: dict[DeviceId, WorkerServer] = {}
    for did in device_ids:
        port = _free_port()
        wid = DeviceId(did)
        servers[wid] = WorkerServer(wid, f"127.0.0.1:{port}")
    addrs = {wid: s.bind_address for wid, s in servers.items()}
    for s in servers.values():
        s.start()
    try:
        yield addrs, servers
    finally:
        for s in servers.values():
            with contextlib.suppress(Exception):
                s.stop()


def deploy(
    addrs: dict[DeviceId, str],
    placement: Placement,
    *,
    model_id: str,
    recovery: RecoveryTable | None = None,
) -> None:
    """Push primaries (and backups, if recovery given) to the workers."""
    for stage in placement:
        with WorkerClient(addrs[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=model_id,
            )
    if recovery:
        stage_by_device = {s.device: s for s in placement}
        for k, backed_up_js in inverse_recovery(recovery).items():
            if k not in addrs:
                continue
            with WorkerClient(addrs[k]) as client:
                for j in backed_up_js:
                    js = stage_by_device.get(j)
                    if js is None:
                        continue
                    client.load_backup(
                        for_device_id=j,
                        start_layer=int(js.start_layer),
                        end_layer=int(js.end_layer),
                        model_id=model_id,
                    )


# ---------------------------------------------------------------------------
# Placement strategies (baselines)
# ---------------------------------------------------------------------------
def greedy_placement(devices: list[DeviceProfile], num_layers: int) -> Placement:
    """Throughput-weighted contiguous split (PETALS-style heuristic)."""
    weights = [max(d.compute_throughput, 1e-9) for d in devices]
    total = sum(weights)
    plan: list[Stage] = []
    cursor = 1
    for i, dev in enumerate(devices):
        if i == len(devices) - 1:
            count = num_layers - (cursor - 1)
        else:
            count = max(1, round(num_layers * weights[i] / total))
            count = min(count, num_layers - (cursor - 1) - (len(devices) - i - 1))
        plan.append(
            Stage(
                start_layer=LayerIdx(cursor),
                end_layer=LayerIdx(cursor + count - 1),
                device=dev.id,
            )
        )
        cursor += count
    return plan


def dp_placement(spec: ClusterSpec, recovery: RecoveryTable) -> Placement | None:
    """Recovery-Aware DP (ours). Returns None if infeasible."""
    try:
        return Scheduler(spec).solve(recovery).placement
    except NoFeasibleSolutionError:
        return None


def dp_placement_no_recovery(spec: ClusterSpec) -> Placement | None:
    """Jupiter-style: same DP but R={}, no backup memory reserved."""
    return dp_placement(spec, recovery={})


def round_robin_placement(devices: list[DeviceProfile], num_layers: int) -> Placement:
    return uniform_placement(devices, num_layers)


def max_stage_time(spec: ClusterSpec, placement: Placement) -> float:
    """Compute the max-stage-time (objective) for a given placement, for
    cross-strategy comparison on the same synthetic spec."""
    devices_by_id = {d.id: d for d in spec.devices}
    prev_device: DeviceId | None = None
    worst = 0.0
    for stage in placement:
        dev = devices_by_id[stage.device]
        t_comp = sum(
            spec.layers[i - 1].compute_time[dev.id]
            for i in range(int(stage.start_layer), int(stage.end_layer) + 1)
        )
        t_comm = 0.0
        if prev_device is not None:
            bw = spec.network.bandwidth.get((prev_device, dev.id), float("inf"))
            lat = spec.network.latency.get((prev_device, dev.id), 0.0)
            t_comm = spec.activation_bytes / bw + lat if bw > 0 else float("inf")
        worst = max(worst, t_comp + t_comm)
        prev_device = dev.id
    return worst


# ---------------------------------------------------------------------------
# Synthetic cluster builders (for algorithmic sweeps)
# ---------------------------------------------------------------------------
def make_synthetic_spec(
    *,
    num_devices: int,
    num_layers: int,
    mem_per_device_bytes: int = 4_000_000_000,
    mem_per_layer_bytes: int = 200_000_000,
    base_layer_seconds: float = 0.05,
    throughput_per_device: list[float] | None = None,
    activation_bytes: int = 1_000_000,
    bandwidth_bps: float = 1e9,
    latency_seconds: float = 0.001,
    slo: SLO | None = None,
) -> ClusterSpec:
    """Build a clean synthetic ClusterSpec for algorithmic experiments."""
    if throughput_per_device is None:
        throughput_per_device = [1.0] * num_devices
    if len(throughput_per_device) != num_devices:
        raise ValueError("throughput_per_device length mismatch")
    devices = [
        DeviceProfile(
            id=DeviceId(f"d{i}"),
            total_memory_bytes=mem_per_device_bytes,
            compute_throughput=throughput_per_device[i],
        )
        for i in range(num_devices)
    ]
    from radp.common.types import LayerProfile, NetworkProfile
    layers = [
        LayerProfile(
            layer_idx=LayerIdx(i),
            memory_bytes=mem_per_layer_bytes,
            compute_time={d.id: base_layer_seconds / d.compute_throughput for d in devices},
        )
        for i in range(1, num_layers + 1)
    ]
    network = NetworkProfile(
        bandwidth={(a.id, b.id): bandwidth_bps for a in devices for b in devices if a is not b},
        latency={(a.id, b.id): latency_seconds for a in devices for b in devices if a is not b},
    )
    return ClusterSpec(
        devices=devices,
        layers=layers,
        network=network,
        slo=slo if slo is not None else SLO(ttft_seconds=10.0, tbt_seconds=10.0),
        activation_bytes=activation_bytes,
    )


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------
def write_json(name: str, data: Any) -> Path:
    """Write benchmark output under experiments/results/<name>.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{name}.json"
    import json
    out.write_text(json.dumps(data, indent=2, default=str))
    return out


def read_json(name: str) -> Any:
    import json
    return json.loads((RESULTS_DIR / f"{name}.json").read_text())
