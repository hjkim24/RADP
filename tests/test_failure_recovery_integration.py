"""End-to-end failure recovery: kill a worker, verify the next request succeeds.

Spawns 3 in-process gRPC worker servers, stops worker-b mid-experiment,
then runs another prefill — gateway should route through worker-c (R(b)=c)
and produce the same logits as before.

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
import torch

from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer


@pytest.fixture
def three_workers() -> Generator[tuple[dict[DeviceId, str], dict[DeviceId, WorkerServer]], None, None]:
    servers = {
        DeviceId("worker-a"): WorkerServer(DeviceId("worker-a"), "127.0.0.1:50071"),
        DeviceId("worker-b"): WorkerServer(DeviceId("worker-b"), "127.0.0.1:50072"),
        DeviceId("worker-c"): WorkerServer(DeviceId("worker-c"), "127.0.0.1:50073"),
    }
    for s in servers.values():
        s.start()
    addrs = {dev: s.bind_address for dev, s in servers.items()}
    try:
        yield addrs, servers
    finally:
        for s in servers.values():
            s.stop()


@pytest.mark.slow
def test_failure_then_recovery(
    three_workers: tuple[dict[DeviceId, str], dict[DeviceId, WorkerServer]],
) -> None:
    addrs, servers = three_workers
    model_id = "facebook/opt-125m"

    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery: RecoveryTable = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }

    # Deploy primaries.
    for stage in placement:
        with WorkerClient(addrs[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=model_id,
            )

    # Deploy backups: R(b)=c so c gets b's layers preloaded.
    for j, k in recovery.items():
        j_stage = next(s for s in placement if s.device == j)
        with WorkerClient(addrs[k]) as client:
            client.load_backup(
                for_device_id=j,
                start_layer=int(j_stage.start_layer),
                end_layer=int(j_stage.end_layer),
                model_id=model_id,
            )

    gateway = RequestGateway(
        placement=placement,
        recovery=recovery,
        worker_addresses=addrs,
        model_id=model_id,
        torch_device="cpu",
        dtype="float32",
    )

    prompt = "The quick brown fox"

    # Sanity baseline.
    healthy_logits = gateway.prefill(prompt)

    # Kill worker-b.
    servers[DeviceId("worker-b")].stop()

    # Next prefill should: hit gRPC error on b, mark b dead, retry on c.
    recovered_logits = gateway.prefill(prompt)

    assert healthy_logits.shape == recovered_logits.shape
    # Same model + same prompt + backup loaded with the SAME weight slice ->
    # results should be numerically identical (within float32 noise).
    assert torch.allclose(healthy_logits, recovered_logits, atol=5e-4, rtol=1e-4), (
        f"max abs diff = {(healthy_logits - recovered_logits).abs().max().item():.3e}"
    )

    # And the gateway should now report b as dead.
    assert DeviceId("worker-b") in gateway._dead
