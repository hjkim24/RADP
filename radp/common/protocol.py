"""Typed gRPC client wrappers (Phase 3)."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import grpc

from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import DeviceId, RequestId

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


class WorkerClient:
    """High-level synchronous client to a single worker."""

    def __init__(self, address: str) -> None:
        self.address = address
        self._channel: grpc.Channel | None = None
        self._stub: Any | None = None

    def __enter__(self) -> WorkerClient:
        self._channel = grpc.insecure_channel(self.address, options=_GRPC_OPTIONS)
        self._stub = radp_pb2_grpc.WorkerServiceStub(self._channel)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._channel is not None:
            self._channel.close()
        self._channel = None
        self._stub = None

    def _require_stub(self) -> Any:
        if self._stub is None:
            raise RuntimeError("WorkerClient used outside of `with` block")
        return self._stub

    def load_stage(
        self,
        *,
        device_id: DeviceId,
        start_layer: int,
        end_layer: int,
        model_id: str,
    ) -> None:
        req = radp_pb2.LoadStageRequest(
            device_id=str(device_id),
            start_layer=start_layer,
            end_layer=end_layer,
            model_id=model_id,
        )
        resp = self._require_stub().LoadStage(req)
        if not resp.ok:
            raise RuntimeError(f"LoadStage failed on {self.address}: {resp.error}")

    def load_backup(
        self,
        *,
        for_device_id: DeviceId,
        start_layer: int,
        end_layer: int,
        model_id: str,
    ) -> None:
        req = radp_pb2.LoadBackupRequest(
            for_device_id=str(for_device_id),
            start_layer=start_layer,
            end_layer=end_layer,
            model_id=model_id,
        )
        resp = self._require_stub().LoadBackup(req)
        if not resp.ok:
            raise RuntimeError(f"LoadBackup failed on {self.address}")

    def promote_backup(self, *, for_device_id: DeviceId) -> None:
        req = radp_pb2.PromoteBackupRequest(for_device_id=str(for_device_id))
        resp = self._require_stub().PromoteBackup(req)
        if not resp.ok:
            raise RuntimeError(f"PromoteBackup failed on {self.address}")

    def run_stage(
        self,
        *,
        activation: bytes,
        request_id: RequestId,
        start_layer: int,
        end_layer: int,
        is_prefill: bool = True,
    ) -> bytes:
        req = radp_pb2.RunStageRequest(
            activation=activation,
            request_id=int(request_id),
            is_prefill=is_prefill,
            start_layer=start_layer,
            end_layer=end_layer,
        )
        resp = self._require_stub().RunStage(req)
        return bytes(resp.activation)

    def evict_request(self, *, request_id: RequestId) -> None:
        req = radp_pb2.EvictRequestRequest(request_id=int(request_id))
        self._require_stub().EvictRequest(req)

    def load_head(self, *, model_id: str) -> None:
        """Deploy lm_head + final_layer_norm + project_out to this worker so
        it can serve as the chain tail with on-worker sampling."""
        req = radp_pb2.LoadHeadRequest(model_id=model_id)
        resp = self._require_stub().LoadHead(req)
        if not resp.ok:
            raise RuntimeError(f"LoadHead failed on {self.address}: {resp.error}")

    def fetch_kv(
        self,
        *,
        request_id: RequestId,
        start_layer: int,
        end_layer: int,
        up_to_position: int,
    ) -> tuple[bytes, int]:
        """Pull a stage's raw KV bytes (positions 0..up_to_position) off a
        worker — used at failure time to rebuild a promoted backup's cache
        without a full re-prefill (parity recovery)."""
        req = radp_pb2.FetchKVRequest(
            request_id=int(request_id),
            start_layer=start_layer,
            end_layer=end_layer,
            up_to_position=up_to_position,
        )
        resp = self._require_stub().FetchKV(req)
        return bytes(resp.kv_bytes), int(resp.num_positions)

    def load_kv(
        self,
        *,
        request_id: RequestId,
        start_layer: int,
        end_layer: int,
        kv_bytes: bytes,
        num_positions: int,
    ) -> None:
        """Install raw KV bytes (as returned by fetch_kv) into a worker's
        DynamicCache for this (request, stage) — the write side of parity
        recovery's failure-time rebuild."""
        req = radp_pb2.LoadKVRequest(
            request_id=int(request_id),
            start_layer=start_layer,
            end_layer=end_layer,
            kv_bytes=kv_bytes,
            num_positions=num_positions,
        )
        self._require_stub().LoadKV(req)

    def set_next_hop(
        self,
        *,
        my_start: int,
        my_end: int,
        next_address: str,
        next_start: int = 0,
        next_end: int = 0,
    ) -> None:
        """Register the chain successor for THIS worker's (my_start, my_end)
        stage. Pass ``next_address=""`` to clear (chain tail)."""
        req = radp_pb2.SetNextHopRequest(
            next_address=next_address,
            start_layer=my_start,
            end_layer=my_end,
            next_start_layer=next_start,
            next_end_layer=next_end,
        )
        resp = self._require_stub().SetNextHop(req)
        if not resp.ok:
            raise RuntimeError(
                f"SetNextHop failed on {self.address}: {resp.error}"
            )


class CoordinatorClient:
    """High-level client to the coordinator (Generate + Heartbeat)."""

    def __init__(self, address: str) -> None:
        self.address = address
        self._channel: grpc.Channel | None = None
        self._stub: Any | None = None

    def __enter__(self) -> CoordinatorClient:
        self._channel = grpc.insecure_channel(self.address, options=_GRPC_OPTIONS)
        self._stub = radp_pb2_grpc.CoordinatorServiceStub(self._channel)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._channel is not None:
            self._channel.close()
        self._channel = None
        self._stub = None

    def _require_stub(self) -> Any:
        if self._stub is None:
            raise RuntimeError("CoordinatorClient used outside of `with` block")
        return self._stub

    def generate(
        self,
        prompt: str,
        max_tokens: int,
        *,
        temperature: float = 0.0,
        top_k: int = 0,
        top_p: float = 1.0,
        eos_token_id: int = 0,
        seed: int = 0,
    ) -> list[str]:
        req = radp_pb2.GenerateRequest(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            eos_token_id=eos_token_id,
            seed=seed,
        )
        chunks = []
        for chunk in self._require_stub().Generate(req):
            chunks.append(chunk.text)
            if chunk.done:
                break
        return chunks

    def heartbeat(
        self,
        device_id: DeviceId,
        free_memory_bytes: float,
        *,
        total_memory_bytes: float = 0.0,
        device_class: str = "",
    ) -> None:
        req = radp_pb2.HeartbeatRequest(
            device_id=str(device_id),
            free_memory_bytes=float(free_memory_bytes),
            ts_ns=int(time.time_ns()),
            total_memory_bytes=float(total_memory_bytes),
            device_class=device_class,
        )
        self._require_stub().Heartbeat(req)
