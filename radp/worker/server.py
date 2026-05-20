"""gRPC worker server: hosts StageRunner + HeartbeatSender."""

from __future__ import annotations

from radp.common.types import DeviceId


class WorkerServer:
    def __init__(
        self,
        device_id: DeviceId,
        coordinator_address: str,
        bind_address: str,
        cache_dir: str,
    ) -> None:
        self.device_id = device_id
        self.coordinator_address = coordinator_address
        self.bind_address = bind_address
        self.cache_dir = cache_dir

    def start(self) -> None:
        """Start gRPC server + heartbeat loop."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
