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
import types
from collections.abc import Callable, Generator
from concurrent import futures
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import grpc

from radp.common.proto import radp_pb2_grpc
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
from radp.coordinator.gateway import RequestGateway
from radp.coordinator.recovery_plan import inverse_recovery
from radp.coordinator.scheduler import Scheduler, uniform_placement
from radp.coordinator.server import _CoordinatorServicer
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


@contextmanager
def in_process_cluster_with_mirror(
    device_ids: list[str],
) -> Generator[
    tuple[
        dict[DeviceId, str],
        dict[DeviceId, WorkerServer],
        Callable[[RequestGateway], None],
    ],
    None,
    None,
]:
    """Like ``in_process_cluster``, but stands up a real CoordinatorService
    and points every WorkerServer at it, so non-first-stage workers actually
    mirror their interior activations. The servicer is reused as-is
    (`radp.coordinator.server._CoordinatorServicer`) by handing it a
    duck-typed holder instead of a full CoordinatorServer -- it only ever
    reads `.gateway` and `.detector` off what it's given.

    Yields (addrs, servers, attach) where attach(gw) wires `holder.gateway`
    so MirrorActivation pushes land in `gw.cache` (query interior stages via
    `gw.cache.get_history(rid, (start, end))` -- the head stage never
    mirrors, only non-first stages do).
    """
    holder = types.SimpleNamespace(gateway=None, detector=None)
    coord_port = _free_port()
    coord_addr = f"127.0.0.1:{coord_port}"
    coord_server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(
        _CoordinatorServicer(holder), coord_server
    )
    coord_server.add_insecure_port(coord_addr)
    coord_server.start()

    servers: dict[DeviceId, WorkerServer] = {}
    for did in device_ids:
        port = _free_port()
        wid = DeviceId(did)
        servers[wid] = WorkerServer(
            wid, f"127.0.0.1:{port}", coordinator_address=coord_addr
        )
    addrs = {wid: s.bind_address for wid, s in servers.items()}
    for s in servers.values():
        s.start()

    def attach(gw: RequestGateway) -> None:
        holder.gateway = gw

    try:
        yield addrs, servers, attach
    finally:
        for s in servers.values():
            with contextlib.suppress(Exception):
                s.stop()
        coord_server.stop(0)


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


def wire_chain(addrs: dict[DeviceId, str], placement: Placement) -> None:
    """Chain-wire consecutive stages via SetNextHop so RunStage actually
    forwards past the head worker.

    ``deploy()`` only loads primaries/backups. Without this, every worker's
    ``_next_hops`` stays empty, ``_get_next_hop`` returns None, and the head
    worker treats itself as the chain tail -- it runs ONLY its own stage and
    hands the (incomplete) activation straight back to the gateway. Verified
    by instrumenting ``_WorkerServicer.RunStage``: with a 3-stage placement
    and no wiring, only the head stage's RunStage ever fires; with this
    helper called after ``deploy()``, all 3 stages fire in order. Mirrors
    ``RequestGateway._rewire_chain`` (used there only for post-recovery
    re-wiring); this is the same wiring needed once, up front, for the
    initial deploy.
    """
    for i, stage in enumerate(placement):
        with WorkerClient(addrs[stage.device]) as client:
            if i + 1 < len(placement):
                nxt = placement[i + 1]
                client.set_next_hop(
                    my_start=int(stage.start_layer),
                    my_end=int(stage.end_layer),
                    next_address=addrs[nxt.device],
                    next_start=int(nxt.start_layer),
                    next_end=int(nxt.end_layer),
                )
            else:
                client.set_next_hop(
                    my_start=int(stage.start_layer),
                    my_end=int(stage.end_layer),
                    next_address="",
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
# Storage analysis
# ---------------------------------------------------------------------------
def replication_overhead(placement: Placement, n_heads: int, head_dim: int, itemsize: int) -> dict:
    """Steady-state coordinator storage: replicate = Σ non-head stage KV,
    parity = max non-head stage KV. Deterministic — no measurement. Feeds the
    2-D Pareto y-axis and the O(N) storage-scaling curve.
    """
    per_stage = []
    for stage in placement:
        if int(stage.start_layer) == 1:  # head is coord-sourced, not stored
            continue
        n_layers = int(stage.end_layer) - int(stage.start_layer) + 1
        stage_bytes = n_layers * 2 * n_heads * head_dim * itemsize
        per_stage.append(((int(stage.start_layer), int(stage.end_layer)), stage_bytes))
    sizes = [b for _, b in per_stage]
    total = sum(sizes)
    biggest = max(sizes) if sizes else 0
    return {
        "replicate_bytes": total,
        "parity_bytes": biggest,
        "ratio": (total / biggest) if biggest else 0.0,
        "per_stage": per_stage,
    }


def shipping_overhead(placement: Placement, n_heads: int, head_dim: int, itemsize: int) -> dict:
    """Steady-state worker->coord shipping bytes per decode step, per family.

    Two shipments, verified against radp/worker/server.py:
      - input mirror (activation, submit_mirror): ALWAYS-ON for every non-head
        stage in ANY mode (server.py:438-451, gated only on _mirror not None +
        start_layer>1 + not replay_only). hidden_dim*itemsize per stage.
      - KV column (MirrorKV, _maybe_push_parity_kv): RADP_PARITY-gated
        (server.py:473-484) -> parity/replicate only. Same per-stage KV column
        replication_overhead computes.

    So the mirror is the shared baseline; the KV column is the delta parity/
    replicate pay on top. surgical/full_replay/reactive ship the mirror only.
    """
    hidden_dim = n_heads * head_dim
    mirror = 0
    kv = 0
    per_stage_kv = []
    per_stage_mirror = []
    for stage in placement:
        if int(stage.start_layer) == 1:  # head is coord-sourced, ships nothing
            continue
        n_layers = int(stage.end_layer) - int(stage.start_layer) + 1
        stage_kv = n_layers * 2 * n_heads * head_dim * itemsize
        stage_mirror = hidden_dim * itemsize
        kv += stage_kv
        mirror += stage_mirror
        per_stage_kv.append(((int(stage.start_layer), int(stage.end_layer)), stage_kv))
        per_stage_mirror.append(((int(stage.start_layer), int(stage.end_layer)), stage_mirror))
    return {
        "input_mirror_bytes_per_step": mirror,
        "kv_column_bytes_per_step": kv,
        "shipping_bytes_per_step": {
            "full_replay": mirror,
            "reactive": mirror,
            "surgical": mirror,
            "parity": mirror + kv,
            "replicate": mirror + kv,
        },
        "per_stage_kv": per_stage_kv,
        "per_stage_mirror": per_stage_mirror,
    }


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
