"""End-to-end Phase 2.7: kill a worker mid-generation and verify the
remaining tokens MATCH the no-failure baseline token-for-token, proven
by cache-replay (no full re-prefill needed for that to be true).

Strategy:
  1. Spawn 3 in-process workers; deploy primaries + backups.
  2. Run a baseline generate of N tokens (no failure).
  3. New request: do prefill + a couple of decode steps successfully.
  4. Kill worker-b. Continue decoding.
  5. The remaining tokens (from step 3 + retried step 4 + further decodes)
     should match the SAME indices of the baseline's tokens.

Marked `slow`: downloads OPT-125M.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, RecoveryTable, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer

MODEL_ID = "facebook/opt-125m"


@pytest.fixture
def three_workers() -> Generator[tuple[dict[DeviceId, str], dict[DeviceId, WorkerServer]], None, None]:
    servers = {
        DeviceId("worker-a"): WorkerServer(DeviceId("worker-a"), "127.0.0.1:50101"),
        DeviceId("worker-b"): WorkerServer(DeviceId("worker-b"), "127.0.0.1:50102"),
        DeviceId("worker-c"): WorkerServer(DeviceId("worker-c"), "127.0.0.1:50103"),
    }
    for s in servers.values():
        s.start()
    addrs = {dev: s.bind_address for dev, s in servers.items()}
    try:
        yield addrs, servers
    finally:
        for s in servers.values():
            s.stop()


def _placement_and_recovery() -> tuple[Placement, RecoveryTable]:
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
    return placement, recovery


def _deploy(addrs: dict[DeviceId, str], placement: Placement, recovery: RecoveryTable) -> None:
    for stage in placement:
        with WorkerClient(addrs[stage.device]) as client:
            client.load_stage(
                device_id=stage.device,
                start_layer=int(stage.start_layer),
                end_layer=int(stage.end_layer),
                model_id=MODEL_ID,
            )
    for j, k in recovery.items():
        j_stage = next(s for s in placement if s.device == j)
        with WorkerClient(addrs[k]) as client:
            client.load_backup(
                for_device_id=j,
                start_layer=int(j_stage.start_layer),
                end_layer=int(j_stage.end_layer),
                model_id=MODEL_ID,
            )


@pytest.mark.slow
def test_mid_generation_kill_recovers_via_cache_replay(
    three_workers: tuple[dict[DeviceId, str], dict[DeviceId, WorkerServer]],
) -> None:
    addrs, servers = three_workers
    placement, recovery = _placement_and_recovery()
    _deploy(addrs, placement, recovery)

    prompt = "The quick brown fox"
    n_tokens = 6

    # 1) Baseline: generate end-to-end without failure.
    baseline_gw = RequestGateway(
        placement=placement,
        recovery=recovery,
        worker_addresses=addrs,
        model_id=MODEL_ID,
    )
    baseline = baseline_gw.generate(prompt, max_tokens=n_tokens)

    # 2) New gateway. Run prefill + 2 decode steps successfully.
    gw = RequestGateway(
        placement=placement,
        recovery=recovery,
        worker_addresses=addrs,
        model_id=MODEL_ID,
    )
    request_id = gw.new_request_id()
    try:
        gw._prefill(request_id, prompt)            # 1 token generated
        gw._decode_step(request_id)                # 2
        gw._decode_step(request_id)                # 3
        # 3) Kill worker-b. Subsequent decode steps must route through worker-c
        # via cache replay (worker-c's KV is empty; replay rebuilds it).
        servers[DeviceId("worker-b")].stop()
        gw._decode_step(request_id)                # 4 — triggers replay+retry
        gw._decode_step(request_id)                # 5
        gw._decode_step(request_id)                # 6
        recovered = list(gw._requests[request_id].generated_token_ids)
    finally:
        gw._evict_everywhere(request_id)

    assert len(recovered) == n_tokens
    assert recovered == baseline, (
        f"recovered={recovered}\nbaseline={baseline}\n"
        f"recovered_text={baseline_gw.handle.tokenizer.decode(recovered)!r}\n"
        f"baseline_text ={baseline_gw.handle.tokenizer.decode(baseline)!r}"
    )
    # Sanity: gateway should report worker-b dead.
    assert DeviceId("worker-b") in gw._dead
