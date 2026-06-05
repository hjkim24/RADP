"""Phase D3 — coordinator startup with auto-scheduling.

Covers:
  - CoordinatorConfig.from_yaml parses auto-mode YAML (no placement, with
    schedule_mode, slo, profiling sections)
  - manual mode rejects empty placement
  - bad schedule_mode value is rejected
  - integration (slow): real workers + coordinator, auto path produces a
    consistent placement + functional gateway
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from radp.common.types import DeviceId
from radp.coordinator.server import CoordinatorConfig, CoordinatorServer, WorkerSpec
from radp.worker.server import WorkerServer

_COORD_ADDR = "127.0.0.1:50095"
_ADDR_A = "127.0.0.1:50096"
_ADDR_B = "127.0.0.1:50097"


def _write_auto_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "cluster.yaml"
    p.write_text("""
model:
  id: facebook/opt-125m
  dtype: float32
  torch_device: cpu

coordinator:
  bind: "0.0.0.0:50050"
  heartbeat_timeout_seconds: 5.0
  heartbeat_tick_seconds: 1.0
  schedule_mode: auto
  activation_bytes: 524288
  slo:
    ttft_seconds: 0.5
    tbt_seconds: 0.2
  profiling:
    layer_warmup: 2
    layer_repeats: 4
    layer_seq_length: 24
    network_payload_bytes: 2048
    network_rounds: 5
    wait_timeout_seconds: 30.0

workers:
  - id: w-1
    address: "127.0.0.1:50001"
  - id: w-2
    address: "127.0.0.1:50002"
""")
    return p


def _write_manual_yaml(tmp_path: Path, *, with_placement: bool) -> Path:
    p = tmp_path / "cluster.yaml"
    placement_block = (
        """
placement:
  - device: w-1
    start: 1
    end: 6
  - device: w-2
    start: 7
    end: 12

recovery:
  w-1: w-2
  w-2: w-1
"""
        if with_placement
        else ""
    )
    p.write_text(f"""
model:
  id: facebook/opt-125m
  dtype: float32
  torch_device: cpu

coordinator:
  bind: "0.0.0.0:50050"

workers:
  - id: w-1
    address: "127.0.0.1:50001"
  - id: w-2
    address: "127.0.0.1:50002"
{placement_block}
""")
    return p


def test_from_yaml_auto_mode(tmp_path: Path) -> None:
    cfg = CoordinatorConfig.from_yaml(_write_auto_yaml(tmp_path))
    assert cfg.schedule_mode == "auto"
    assert cfg.placement == []
    assert cfg.recovery == {}
    assert cfg.slo_ttft_seconds == pytest.approx(0.5)
    assert cfg.slo_tbt_seconds == pytest.approx(0.2)
    assert cfg.activation_bytes == 524288
    assert cfg.profiling_layer_warmup == 2
    assert cfg.profiling_layer_repeats == 4
    assert cfg.profiling_layer_seq_length == 24
    assert cfg.profiling_network_payload_bytes == 2048
    assert cfg.profiling_network_rounds == 5
    assert cfg.profiling_wait_timeout_seconds == pytest.approx(30.0)


def test_from_yaml_manual_mode_with_placement(tmp_path: Path) -> None:
    cfg = CoordinatorConfig.from_yaml(_write_manual_yaml(tmp_path, with_placement=True))
    assert cfg.schedule_mode == "manual"
    assert len(cfg.placement) == 2
    assert cfg.recovery == {DeviceId("w-1"): DeviceId("w-2"),
                            DeviceId("w-2"): DeviceId("w-1")}


def test_from_yaml_manual_requires_placement(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="manual.*placement"):
        CoordinatorConfig.from_yaml(
            _write_manual_yaml(tmp_path, with_placement=False)
        )


def test_from_yaml_rejects_unknown_schedule_mode(tmp_path: Path) -> None:
    p = tmp_path / "cluster.yaml"
    p.write_text("""
model: { id: x }
coordinator:
  bind: "0.0.0.0:50050"
  schedule_mode: hybrid
workers:
  - id: w-1
    address: "127.0.0.1:50001"
""")
    with pytest.raises(ValueError, match="schedule_mode"):
        CoordinatorConfig.from_yaml(p)


def test_deploy_before_placement_raises() -> None:
    cfg = CoordinatorConfig(
        model_id="facebook/opt-125m",
        bind_address=_COORD_ADDR,
        workers=[WorkerSpec(DeviceId("w-a"), _ADDR_A)],
        schedule_mode="auto",  # so empty placement is legitimate
    )
    server = CoordinatorServer(cfg)
    with pytest.raises(RuntimeError, match="placement"):
        server.deploy()


@pytest.fixture
def auto_fleet() -> Generator[tuple[CoordinatorServer, list[WorkerServer]], None, None]:
    cfg = CoordinatorConfig(
        model_id="facebook/opt-125m",
        bind_address=_COORD_ADDR,
        workers=[
            WorkerSpec(DeviceId("w-a"), _ADDR_A),
            WorkerSpec(DeviceId("w-b"), _ADDR_B),
        ],
        torch_device="cpu",
        dtype="float32",
        heartbeat_timeout_seconds=30.0,
        heartbeat_tick_seconds=0.2,
        schedule_mode="auto",
        slo_ttft_seconds=10.0,
        slo_tbt_seconds=10.0,
        activation_bytes=4096,
        profiling_layer_warmup=0,
        profiling_layer_repeats=1,
        profiling_layer_seq_length=8,
        profiling_network_payload_bytes=2048,
        profiling_network_rounds=3,
        profiling_wait_timeout_seconds=10.0,
    )
    coord = CoordinatorServer(cfg)
    coord.start()  # gRPC + detector up; gateway stays None
    workers = [
        WorkerServer(
            DeviceId("w-a"), _ADDR_A,
            coordinator_address=_COORD_ADDR, heartbeat_interval=0.2,
            torch_device="cpu", dtype="float32",
        ),
        WorkerServer(
            DeviceId("w-b"), _ADDR_B,
            coordinator_address=_COORD_ADDR, heartbeat_interval=0.2,
            torch_device="cpu", dtype="float32",
        ),
    ]
    for w in workers:
        w.start()
    try:
        yield coord, workers
    finally:
        for w in workers:
            w.stop()
        coord.stop()


@pytest.mark.slow
def test_auto_schedule_produces_valid_placement(
    auto_fleet: tuple[CoordinatorServer, list[WorkerServer]],
) -> None:
    coord, _ = auto_fleet
    result = coord.auto_schedule()
    # Both workers must appear in the placement
    devices_in_placement = {s.device for s in result.placement}
    assert devices_in_placement == {DeviceId("w-a"), DeviceId("w-b")}
    # All 12 OPT-125M layers covered, contiguous, no gaps
    sorted_stages = sorted(result.placement, key=lambda s: s.start_layer)
    assert int(sorted_stages[0].start_layer) == 1
    assert int(sorted_stages[-1].end_layer) == 12
    for prev, curr in zip(sorted_stages, sorted_stages[1:]):
        assert int(curr.start_layer) == int(prev.end_layer) + 1
    # Recovery covers every placed device
    assert set(result.recovery.keys()) == {DeviceId("w-a"), DeviceId("w-b")}
    # Server state was updated
    assert coord.placement == list(result.placement)
    assert coord.recovery == dict(result.recovery)
    # Gateway should NOT yet exist (auto_schedule deferred it to serve/deploy)
    assert coord.gateway is None
