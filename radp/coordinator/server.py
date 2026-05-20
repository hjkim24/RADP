"""gRPC server wiring for the coordinator.

Assembles: Scheduler -> Placement+RecoveryTable, FailureDetector, ActivationCache,
RequestGateway, and exposes them as `CoordinatorService` over gRPC.
"""

from __future__ import annotations

from radp.common.types import ClusterSpec


class CoordinatorServer:
    def __init__(self, spec: ClusterSpec, bind_address: str) -> None:
        self.spec = spec
        self.bind_address = bind_address

    def start(self) -> None:
        """Plan, deploy stages to workers, then serve gRPC."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
