"""Thin wrapper around generated gRPC stubs.

The generated `radp_pb2` / `radp_pb2_grpc` modules are produced by
`scripts/gen_proto.sh` and live next to this file. Phase 2 will add
typed client classes (`WorkerClient`, `CoordinatorClient`) that hide
the raw stubs from the rest of the codebase; the skeletons below pin
their signatures.
"""

from __future__ import annotations


class WorkerClient:
    """High-level client to a single worker. Phase 2 implementation."""

    def __init__(self, address: str) -> None:
        self.address = address

    def __enter__(self) -> WorkerClient:
        raise NotImplementedError

    def __exit__(self, *exc: object) -> None:
        raise NotImplementedError


class CoordinatorClient:
    """High-level client to the coordinator (used by workers + user CLI)."""

    def __init__(self, address: str) -> None:
        self.address = address
