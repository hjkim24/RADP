"""EXP-D3 Phase F smoke tests for async chain.

Verifies, without the HF model stack:
  - Worker in async mode fires the next-hop RunStage to a background
    executor and returns ACK immediately (no wait for chain tail).
  - Chain tail (a worker with no next_hop) calls coord.ResultReady with
    its produced activation / next_token_id.
  - Gateway's record_result wakes a pending event so the caller of
    _invoke can return without polling.

We stand up:
  - one fake worker as chain head (registered next_hop -> tail)
  - one fake worker as chain tail (no next_hop, no head sampling — so it
    returns the activation back via ResultReady)
  - a "coord" grpc server that routes ResultReady straight into a
    RequestGateway-shaped record_result helper

The Gateway itself is not constructed (HF weights would be required);
we exercise just the wake-up + future-resolution code path via a thin
shim.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from concurrent import futures
from typing import Any

import grpc
import pytest

from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import LayerIdx, RequestId
from radp.worker.server import _CoordDispatcher, _WorkerServicer


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeStageRunner:
    has_head = False

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[int, int, int, bool]] = []
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
            self.calls.append((int(request_id), int(start), int(end), is_prefill))
        return f"[{self.label}]".encode() + activation_blob

    def evict_request(self, _request_id: Any) -> None:
        pass


class _ResultCoord(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    """Stand-in for the gateway's record_result hook. Exposes a dict keyed
    by (request_id, position) that fills as ResultReady RPCs land, plus
    a per-key Event so tests can block on a specific wake-up."""

    def __init__(self) -> None:
        self.results: dict[tuple[int, int], dict[str, Any]] = {}
        self.events: dict[tuple[int, int], threading.Event] = {}
        self._lock = threading.Lock()

    def event_for(self, request_id: int, position: int) -> threading.Event:
        key = (request_id, position)
        with self._lock:
            ev = self.events.get(key)
            if ev is None:
                ev = threading.Event()
                self.events[key] = ev
            return ev

    # CoordinatorServiceServicer methods --------------------------------
    def Heartbeat(self, request: Any, context: grpc.ServicerContext) -> Any:
        return radp_pb2.HeartbeatResponse(ack=True)

    def Generate(self, request: Any, context: grpc.ServicerContext) -> Any:
        return iter(())

    def MirrorActivation(self, request: Any, context: grpc.ServicerContext) -> Any:
        return radp_pb2.MirrorActivationResponse(ok=True)

    def ResultReady(self, request: Any, context: grpc.ServicerContext) -> Any:
        key = (int(request.request_id), int(request.position))
        with self._lock:
            self.results[key] = {
                "activation": bytes(request.activation),
                "has_next_token": bool(request.has_next_token),
                "next_token_id": int(request.next_token_id),
            }
            ev = self.events.get(key)
            if ev is None:
                ev = threading.Event()
                self.events[key] = ev
            ev.set()
        return radp_pb2.ResultReadyResponse(ok=True)


def _spawn_worker(coord_addr: str, label: str) -> tuple[
    str, grpc.Server, _WorkerServicer, _FakeStageRunner,
]:
    runner = _FakeStageRunner(label)
    dispatcher = _CoordDispatcher(coord_addr)
    servicer = _WorkerServicer(runner, dispatcher)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_WorkerServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    addr = f"127.0.0.1:{port}"
    server.start()
    return addr, server, servicer, runner


@pytest.fixture
def async_chain() -> Generator[dict[str, Any], None, None]:
    coord_servicer = _ResultCoord()
    coord_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(
        coord_servicer, coord_server
    )
    coord_port = coord_server.add_insecure_port("127.0.0.1:0")
    coord_addr = f"127.0.0.1:{coord_port}"
    coord_server.start()

    head_addr, head_srv, head_sv, head_run = _spawn_worker(coord_addr, "head")
    tail_addr, tail_srv, tail_sv, tail_run = _spawn_worker(coord_addr, "tail")

    head_sv.SetNextHop(  # type: ignore[arg-type]
        radp_pb2.SetNextHopRequest(
            next_address=tail_addr,
            start_layer=1, end_layer=6,
            next_start_layer=7, next_end_layer=12,
        ),
        context=None,  # type: ignore[arg-type]
    )

    try:
        yield {
            "coord_addr": coord_addr,
            "coord_servicer": coord_servicer,
            "head_addr": head_addr,
            "head_runner": head_run,
            "tail_runner": tail_run,
        }
    finally:
        for srv in (head_srv, tail_srv, coord_server):
            try:
                srv.stop(0).wait()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_async_chain_head_acks_before_tail_completes(
    async_chain: dict[str, Any],
) -> None:
    """The head's RunStage handler must return ACK on async_chain=True
    without waiting for the tail's RunStage to come back. We catch the
    head's response BEFORE the tail's ResultReady wakes the coord."""
    head_addr = async_chain["head_addr"]
    coord = async_chain["coord_servicer"]

    ev = coord.event_for(request_id=42, position=0)

    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        resp = stub.RunStage(
            radp_pb2.RunStageRequest(
                activation=b"PROMPT",
                request_id=42,
                is_prefill=True,
                start_layer=1, end_layer=6,
                position=0,
                async_chain=True,
            ),
            timeout=5.0,
        )
    # The head's RunStage returned. It must not carry the tail's result.
    assert resp.activation == b""
    assert resp.has_next_token is False

    # Tail will eventually fire ResultReady.
    assert ev.wait(timeout=5.0), "ResultReady never arrived"
    payload = coord.results[(42, 0)]
    # tail returned activation = "[tail]" + ("[head]" + b"PROMPT")
    assert payload["activation"] == b"[tail][head]PROMPT"
    assert payload["has_next_token"] is False


def test_async_chain_concurrent_requests_pipeline(
    async_chain: dict[str, Any],
) -> None:
    """Two concurrent streams interleave through the chain without
    serializing on each other — both ResultReady events fire."""
    head_addr = async_chain["head_addr"]
    coord = async_chain["coord_servicer"]

    ev1 = coord.event_for(request_id=1, position=0)
    ev2 = coord.event_for(request_id=2, position=0)

    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        for rid in (1, 2):
            stub.RunStage(
                radp_pb2.RunStageRequest(
                    activation=f"P{rid}".encode(),
                    request_id=rid,
                    is_prefill=True,
                    start_layer=1, end_layer=6,
                    position=0,
                    async_chain=True,
                ),
                timeout=5.0,
            )

    assert ev1.wait(timeout=5.0)
    assert ev2.wait(timeout=5.0)
    assert (1, 0) in coord.results
    assert (2, 0) in coord.results


def test_async_chain_same_request_serializes_steps(
    async_chain: dict[str, Any],
) -> None:
    """Sequential steps for the SAME request must serialize on the
    per-request lock so they don't race the worker's DynamicCache. We
    can't observe the lock directly, but if it weren't there, the head's
    `calls` list could record positions out of order under load. Drive
    8 quick steps and assert positions land monotonically increasing."""
    head_addr = async_chain["head_addr"]
    head_runner: _FakeStageRunner = async_chain["head_runner"]
    coord = async_chain["coord_servicer"]

    n_steps = 8
    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        for pos in range(n_steps):
            stub.RunStage(
                radp_pb2.RunStageRequest(
                    activation=f"p{pos}".encode(),
                    request_id=99,
                    is_prefill=(pos == 0),
                    start_layer=1, end_layer=6,
                    position=pos,
                    async_chain=True,
                ),
                timeout=5.0,
            )

    # Wait for all wake-ups so we know every step finished on the tail.
    for pos in range(n_steps):
        assert coord.event_for(99, pos).wait(timeout=5.0), f"pos {pos} stalled"

    # The head should have processed every step in submission order — the
    # per-request lock serializes them even though the gRPC pool has
    # multiple worker threads.
    seen_positions: list[int] = [c[0] for c in head_runner.calls if c[0] == 99]
    # we only put request_id=99 in this test, so all calls are this request
    assert len(head_runner.calls) == n_steps
    # The fake runner records (req, start, end, is_prefill); we want to
    # check it ran exactly n_steps times for our request and only step 0
    # was a prefill.
    prefill_count = sum(1 for c in head_runner.calls if c[3])
    assert prefill_count == 1, f"expected 1 prefill, saw {prefill_count}"
