"""EXP-D3 Phase 2 smoke test for the worker → coord mirror cache pipeline.

Verifies, without touching the HF model stack, that:
  - A worker that receives a RunStage for a non-first stage pushes the
    activation back to the coord via MirrorActivation.
  - The coord's ActivationCache materialises the entry at the right
    (request, stage, position).
  - First-stage worker does NOT mirror (coord already owns that input).

Drives only the gRPC plane: the worker's StageRunner is monkey-patched to
return a fixed blob so we don't need real weights, and the gateway's
``record_mirror`` is the only coord-side surface we exercise.
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
from radp.coordinator.activation_cache import ActivationCache
from radp.worker.server import _MirrorDispatcher, _WorkerServicer


class _FakeStageRunner:
    """Drop-in replacement that skips the heavy model path entirely."""

    has_head = False

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int, bool]] = []

    def run(
        self,
        *,
        request_id: RequestId,
        activation_blob: bytes,
        start: LayerIdx,
        end: LayerIdx,
        is_prefill: bool,
    ) -> bytes:
        self.calls.append((int(request_id), int(start), int(end), is_prefill))
        return b"OUT:" + activation_blob


class _CaptureCoordServicer(radp_pb2_grpc.CoordinatorServiceServicer):  # type: ignore[misc]
    """Routes MirrorActivation straight into a local ActivationCache so the
    test can assert on (request, stage, position) -> bytes without a gateway."""

    def __init__(self, cache: ActivationCache) -> None:
        self.cache = cache
        self.received = threading.Event()
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
        self.received.set()
        return radp_pb2.MirrorActivationResponse(ok=True)


@pytest.fixture
def fake_coord() -> Generator[tuple[str, _CaptureCoordServicer], None, None]:
    cache = ActivationCache(max_bytes=10 * 1024 * 1024)
    servicer = _CaptureCoordServicer(cache)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_CoordinatorServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    addr = f"127.0.0.1:{port}"
    server.start()
    try:
        yield addr, servicer
    finally:
        server.stop(grace=0.5).wait()


@pytest.fixture
def fake_worker(
    fake_coord: tuple[str, _CaptureCoordServicer],
) -> Generator[
    tuple[str, _FakeStageRunner, _CaptureCoordServicer, _MirrorDispatcher],
    None,
    None,
]:
    coord_addr, coord_servicer = fake_coord
    runner = _FakeStageRunner()
    mirror = _MirrorDispatcher(coord_addr)
    servicer = _WorkerServicer(runner, mirror)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    radp_pb2_grpc.add_WorkerServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    addr = f"127.0.0.1:{port}"
    server.start()
    try:
        yield addr, runner, coord_servicer, mirror
    finally:
        mirror.close()
        server.stop(grace=0.5).wait()


def _run_stage(
    worker_addr: str,
    *,
    request_id: int,
    start: int,
    end: int,
    position: int,
    activation: bytes,
    is_prefill: bool,
) -> bytes:
    with grpc.insecure_channel(worker_addr) as ch:
        stub = radp_pb2_grpc.WorkerServiceStub(ch)
        resp = stub.RunStage(
            radp_pb2.RunStageRequest(
                activation=activation,
                request_id=request_id,
                is_prefill=is_prefill,
                start_layer=start,
                end_layer=end,
                position=position,
            )
        )
    return bytes(resp.activation)


def _wait_for_mirror_count(
    servicer: _CaptureCoordServicer, target: int, *, timeout: float = 2.0
) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        with servicer._lock:
            if servicer.count >= target:
                return
        time.sleep(0.01)
    raise AssertionError(f"mirror count never reached {target} (got {servicer.count})")


def test_non_first_stage_mirrors_input_to_coord(
    fake_worker: tuple[str, _FakeStageRunner, _CaptureCoordServicer, _MirrorDispatcher],
) -> None:
    worker_addr, runner, coord, _ = fake_worker
    # Stage [5..8] is a non-first stage → must mirror its input.
    _run_stage(
        worker_addr,
        request_id=42,
        start=5, end=8,
        position=0,
        activation=b"prefill-input",
        is_prefill=True,
    )
    _wait_for_mirror_count(coord, 1)
    assert coord.cache.get_history(RequestId(42), (5, 8)) == [b"prefill-input"]


def test_first_stage_does_not_mirror(
    fake_worker: tuple[str, _FakeStageRunner, _CaptureCoordServicer, _MirrorDispatcher],
) -> None:
    worker_addr, runner, coord, _ = fake_worker
    # Stage [1..4] is the head — gateway owns the cache entry locally.
    _run_stage(
        worker_addr,
        request_id=7,
        start=1, end=4,
        position=0,
        activation=b"prompt-embed",
        is_prefill=True,
    )
    time.sleep(0.2)  # give the mirror dispatcher a chance to (wrongly) fire
    with coord._lock:
        assert coord.count == 0
    assert coord.cache.get_history(RequestId(7), (1, 4)) == []


def test_multiple_steps_mirror_with_monotonic_positions(
    fake_worker: tuple[str, _FakeStageRunner, _CaptureCoordServicer, _MirrorDispatcher],
) -> None:
    worker_addr, runner, coord, _ = fake_worker
    for pos, blob in enumerate([b"prefill", b"decode-1", b"decode-2", b"decode-3"]):
        _run_stage(
            worker_addr,
            request_id=99,
            start=9, end=12,
            position=pos,
            activation=blob,
            is_prefill=(pos == 0),
        )
    _wait_for_mirror_count(coord, 4)
    assert coord.cache.get_history(RequestId(99), (9, 12)) == [
        b"prefill", b"decode-1", b"decode-2", b"decode-3",
    ]
