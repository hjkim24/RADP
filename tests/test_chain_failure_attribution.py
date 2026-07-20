"""EXP-D3 Phase 3 smoke test for chain-aware failure attribution.

Verifies the gRPC trailer protocol between chain workers and the coord:
  - A middle worker whose downstream RunStage raises catches the error,
    stamps ``(radp-failed-start, radp-failed-end)`` onto its trailer, and
    aborts with UNAVAILABLE.
  - The coord's gateway can pull the trailer out of the resulting
    grpc.RpcError and reconstruct the dead stage's (start, end).

Avoids the HF model stack — the worker's StageRunner is a fake that
returns a fixed blob; the "dead downstream" is a worker that's never
started, so the gRPC channel is open but RunStage gets UNAVAILABLE.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from concurrent import futures
from typing import Any

import grpc
import pytest

from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway  # noqa: E402
from radp.worker.server import _WorkerServicer


class _FakeStageRunner:
    has_head = False

    def __init__(self) -> None:
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
        return b"OUT:" + activation_blob

    def evict_request(self, _request_id: Any) -> None:
        pass


def _spawn_worker_with_next_hop(
    runner: _FakeStageRunner,
    next_addr: str,
    *,
    my_start: int,
    my_end: int,
    next_start: int,
    next_end: int,
) -> tuple[str, grpc.Server]:
    servicer = _WorkerServicer(runner, mirror=None)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    radp_pb2_grpc.add_WorkerServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    addr = f"127.0.0.1:{port}"
    server.start()
    # Register the next_hop directly.
    servicer.SetNextHop(
        radp_pb2.SetNextHopRequest(
            next_address=next_addr,
            start_layer=my_start, end_layer=my_end,
            next_start_layer=next_start, next_end_layer=next_end,
        ),
        context=None,  # type: ignore[arg-type]
    )
    return addr, server


@pytest.fixture
def chain_with_dead_middle() -> Generator[
    tuple[str, int, int], None, None,
]:
    """Spawn ONE live head worker pointing at a dead (never-started)
    middle worker. Returns (head_addr, dead_start, dead_end).
    """
    # Reserve a port for the "dead" middle by binding briefly, closing.
    sock_srv = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    dead_port = sock_srv.add_insecure_port("127.0.0.1:0")
    sock_srv.start()
    sock_srv.stop(0).wait()  # immediately kill — port is "claimed" but nothing listens
    dead_addr = f"127.0.0.1:{dead_port}"
    dead_start, dead_end = 7, 12

    head_runner = _FakeStageRunner()
    head_addr, head_server = _spawn_worker_with_next_hop(
        head_runner, dead_addr,
        my_start=1, my_end=6,
        next_start=dead_start, next_end=dead_end,
    )
    try:
        yield head_addr, dead_start, dead_end
    finally:
        head_server.stop(0).wait()


def test_chain_failure_stamps_trailer(
    chain_with_dead_middle: tuple[str, int, int],
) -> None:
    head_addr, dead_start, dead_end = chain_with_dead_middle
    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.RunStage(
                radp_pb2.RunStageRequest(
                    activation=b"PROMPT-EMBED",
                    request_id=42,
                    is_prefill=True,
                    start_layer=1, end_layer=6,
                    position=0,
                ),
                timeout=15.0,
            )
    err = excinfo.value
    assert err.code() == grpc.StatusCode.UNAVAILABLE
    md = {k: v for k, v in (err.trailing_metadata() or ())}
    assert md.get("radp-failed-start") == str(dead_start)
    assert md.get("radp-failed-end") == str(dead_end)


def test_trailer_survives_an_extra_hop(
    chain_with_dead_middle: tuple[str, int, int],
) -> None:
    """On a chain longer than 3 stages the failure can be further downstream
    than a given worker's own next hop. Each intermediate hop must RELAY the
    trailer its successor already stamped, not overwrite it with its own next
    hop — otherwise the blame walks one stage toward the head per hop and the
    coord kills an alive worker (observed: a 4-stage chain whose stage 3 died
    got attributed to stage 2).

    Here: entry[1..0] -> head[1..6] -> dead[7..12]. The trailer that comes back
    out of `entry` must still name 7..12, not 1..6.
    """
    head_addr, dead_start, dead_end = chain_with_dead_middle
    entry_addr, entry_server = _spawn_worker_with_next_hop(
        _FakeStageRunner(), head_addr,
        my_start=1, my_end=1, next_start=1, next_end=6,
    )
    try:
        with grpc.insecure_channel(entry_addr) as ch:
            stub = radp_pb2_grpc.WorkerServiceStub(ch)
            with pytest.raises(grpc.RpcError) as excinfo:
                stub.RunStage(
                    radp_pb2.RunStageRequest(
                        activation=b"x", request_id=7, is_prefill=True,
                        start_layer=1, end_layer=1, position=0,
                    ),
                    timeout=15.0,
                )
        md = {k: v for k, v in (excinfo.value.trailing_metadata() or ())}
        assert md.get("radp-failed-start") == str(dead_start)
        assert md.get("radp-failed-end") == str(dead_end)
    finally:
        entry_server.stop(0).wait()


def test_gateway_attribution_picks_correct_dead_stage(
    chain_with_dead_middle: tuple[str, int, int],
) -> None:
    """The gateway's _attribute_chain_failure helper turns the trailer
    metadata back into a Stage from the current plan."""
    head_addr, dead_start, dead_end = chain_with_dead_middle

    # Hand-build a placement + recovery so we don't have to spin up the
    # full RequestGateway with HF weights. We only test the attribution
    # helper, which depends on current_plan().
    _placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("head")),
        Stage(LayerIdx(dead_start), LayerIdx(dead_end), DeviceId("middle")),
        Stage(LayerIdx(13), LayerIdx(18), DeviceId("tail")),
    ]

    class _GatewayShim:
        # Just enough surface for _attribute_chain_failure to work.
        # Phase 3 reads `placement` (the original) so the heartbeat-first
        # ordering still maps the trailer back to the truly-dead device.
        _execution_plan = _placement
        placement = _placement
        _plan_lock = threading.Lock()

        def current_plan(self) -> Placement:
            return list(self._execution_plan)

    # Trigger the real RpcError from the chain so we exercise the
    # trailer round-trip.
    with grpc.insecure_channel(head_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        try:
            stub.RunStage(
                radp_pb2.RunStageRequest(
                    activation=b"x", request_id=1,
                    is_prefill=True,
                    start_layer=1, end_layer=6,
                    position=0,
                ),
                timeout=15.0,
            )
            pytest.fail("expected RpcError")
        except grpc.RpcError as err:
            shim = _GatewayShim()
            dead_stage = RequestGateway._attribute_chain_failure(
                shim,  # type: ignore[arg-type]
                _placement[0],
                err,
            )
            assert dead_stage.device == DeviceId("middle")
            assert int(dead_stage.start_layer) == dead_start
            assert int(dead_stage.end_layer) == dead_end


def test_attribution_falls_back_to_head_when_trailer_missing() -> None:
    """If the gRPC error has no radp-failed-* trailer (head itself died,
    old worker binary, etc.), attribution must default to the head we
    called directly so the recovery loop still makes progress."""
    _placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("head")),
        Stage(LayerIdx(7), LayerIdx(12), DeviceId("middle")),
    ]

    class _GatewayShim:
        _execution_plan = _placement
        placement = _placement
        _plan_lock = threading.Lock()

        def current_plan(self) -> Placement:
            return list(self._execution_plan)

    # Synthesize an RpcError with no trailer.
    class _FakeErr(grpc.RpcError):
        def code(self) -> grpc.StatusCode:
            return grpc.StatusCode.UNAVAILABLE

        def trailing_metadata(self) -> tuple[Any, ...]:
            return ()

    shim = _GatewayShim()
    dead_stage = RequestGateway._attribute_chain_failure(
        shim,  # type: ignore[arg-type]
        _placement[0],
        _FakeErr(),
    )
    assert dead_stage.device == DeviceId("head")
