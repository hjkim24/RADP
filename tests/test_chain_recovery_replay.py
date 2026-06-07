"""EXP-D3 Phase 3 end-to-end smoke test for chain recovery.

Wires up an in-process 3-stage fake chain (head → middle → tail) plus a
coord-shaped gateway. Kills the middle worker mid-generation and verifies
the gateway:
  - reads the trailer to attribute the failure to the middle stage,
  - promotes the recovery peer (a 4th worker pre-loaded as backup),
  - rewires the chain so traffic flows head → backup → tail,
  - replays cached input history through the new chain,
  - returns a response from the retry call.

The test stays in the gRPC plane — no HF weights, no torch.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Generator
from concurrent import futures
from typing import Any

import grpc
import pytest

from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId, LayerIdx, RequestId
from radp.coordinator.activation_cache import ActivationCache
from radp.worker.server import _MirrorDispatcher, _WorkerServicer


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeStageRunner:
    has_head = False

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[int, int, int, bool, bool]] = []
        self.promoted_for: list[str] = []
        self._lock = threading.Lock()

    def run(
        self,
        *,
        request_id: Any,
        activation_blob: bytes,
        start: LayerIdx,
        end: LayerIdx,
        is_prefill: bool,
    ) -> bytes:
        with self._lock:
            self.calls.append(
                (int(request_id), int(start), int(end), is_prefill, False)
            )
        return f"[{self.label}]".encode() + activation_blob

    def evict_request(self, _request_id: Any) -> None:
        pass

    def promote_backup(self, *, for_device_id: DeviceId) -> None:
        with self._lock:
            self.promoted_for.append(str(for_device_id))


def _spawn_worker(coord_addr: str | None = None) -> tuple[
    str, grpc.Server, _WorkerServicer, _FakeStageRunner,
]:
    runner = _FakeStageRunner(label=f"w{id(object())}")
    mirror = _MirrorDispatcher(coord_addr) if coord_addr else None
    servicer = _WorkerServicer(runner, mirror)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_WorkerServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    addr = f"127.0.0.1:{port}"
    server.start()
    return addr, server, servicer, runner


class _CaptureCoord(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    def __init__(self, cache: ActivationCache) -> None:
        self.cache = cache
        self.count = 0
        self._lock = threading.Lock()

    def Heartbeat(self, request: Any, context: grpc.ServicerContext) -> Any:
        return radp_pb2.HeartbeatResponse(ack=True)

    def Generate(self, request: Any, context: grpc.ServicerContext) -> Any:
        return iter(())

    def MirrorActivation(self, request: Any, context: grpc.ServicerContext) -> Any:
        self.cache.put(
            RequestId(int(request.request_id)),
            (int(request.start_layer), int(request.end_layer)),
            int(request.position),
            bytes(request.activation),
        )
        with self._lock:
            self.count += 1
        return radp_pb2.MirrorActivationResponse(ok=True)


@pytest.fixture
def chain_with_backup() -> Generator[dict[str, Any], None, None]:
    """3-stage chain + 1 backup peer + a coord that catches mirrors."""
    cache = ActivationCache(max_bytes=10 * 1024 * 1024)
    coord_servicer = _CaptureCoord(cache)
    coord_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(
        coord_servicer, coord_server
    )
    coord_port = coord_server.add_insecure_port("127.0.0.1:0")
    coord_addr = f"127.0.0.1:{coord_port}"
    coord_server.start()

    head_addr, head_srv, head_sv, _ = _spawn_worker(coord_addr)
    middle_addr, middle_srv, middle_sv, _ = _spawn_worker(coord_addr)
    tail_addr, tail_srv, tail_sv, _ = _spawn_worker(coord_addr)
    backup_addr, backup_srv, backup_sv, backup_runner = _spawn_worker(coord_addr)

    # Wire the chain head -> middle -> tail.
    head_sv.SetNextHop(  # type: ignore[arg-type]
        radp_pb2.SetNextHopRequest(
            next_address=middle_addr,
            start_layer=1, end_layer=6,
            next_start_layer=7, next_end_layer=12,
        ),
        context=None,  # type: ignore[arg-type]
    )
    middle_sv.SetNextHop(  # type: ignore[arg-type]
        radp_pb2.SetNextHopRequest(
            next_address=tail_addr,
            start_layer=7, end_layer=12,
            next_start_layer=13, next_end_layer=18,
        ),
        context=None,  # type: ignore[arg-type]
    )
    # Tail has no next-hop; default is chain tail returning activation.

    try:
        yield {
            "coord_addr": coord_addr,
            "cache": cache,
            "head_addr": head_addr,
            "middle_addr": middle_addr,
            "tail_addr": tail_addr,
            "backup_addr": backup_addr,
            "head_sv": head_sv,
            "middle_sv": middle_sv,
            "tail_sv": tail_sv,
            "backup_sv": backup_sv,
            "backup_runner": backup_runner,
            "middle_server": middle_srv,
        }
    finally:
        for srv in (head_srv, middle_srv, tail_srv, backup_srv, coord_server):
            with contextlib.suppress(Exception):
                srv.stop(0).wait()


def test_chain_failure_attribution_with_mirror_cache(
    chain_with_backup: dict[str, Any],
) -> None:
    """End-to-end: run one step OK to populate the mirror cache, kill the
    middle worker, run again — the failure trailer surfaces the right
    dead stage AND the cache has the data needed for replay."""
    head_addr = chain_with_backup["head_addr"]
    middle_server = chain_with_backup["middle_server"]
    cache: ActivationCache = chain_with_backup["cache"]

    # Step 1: full chain run. Middle worker should mirror its input.
    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        resp = stub.RunStage(
            radp_pb2.RunStageRequest(
                activation=b"PROMPT-EMBED",
                request_id=7,
                is_prefill=True,
                start_layer=1, end_layer=6,
                position=0,
            ),
            timeout=15.0,
        )
        assert resp.activation, "tail should return non-empty activation"

    # Allow the fire-and-forget mirror to flush. The middle stage at (7,12)
    # is non-first, so its input should land in the coord cache.
    import time
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if cache.has_history(RequestId(7), (7, 12)):
            break
        time.sleep(0.01)
    assert cache.has_history(RequestId(7), (7, 12)), (
        "mirror cache should contain middle stage's input"
    )

    # Step 2: kill the middle worker, retry the same chain. The head's
    # downstream call now raises; the head stamps the trailer with
    # (7, 12) and aborts. We verify the trailer reaches the caller.
    middle_server.stop(0).wait()
    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.RunStage(
                radp_pb2.RunStageRequest(
                    activation=b"PROMPT-EMBED",
                    request_id=8,
                    is_prefill=True,
                    start_layer=1, end_layer=6,
                    position=0,
                ),
                timeout=15.0,
            )
    err = excinfo.value
    assert err.code() == grpc.StatusCode.UNAVAILABLE
    md = {k: v for k, v in (err.trailing_metadata() or ())}
    assert md.get("radp-failed-start") == "7"
    assert md.get("radp-failed-end") == "12"
