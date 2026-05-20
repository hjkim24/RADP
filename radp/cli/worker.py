"""`radp-worker` CLI entry point (Phase 3)."""

from __future__ import annotations

import argparse
import signal
from types import FrameType

from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import DeviceId
from radp.worker.server import WorkerServer

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-worker")
    p.add_argument("--device-id", required=True)
    p.add_argument("--bind", default="0.0.0.0:50051")
    p.add_argument("--coord", default=None, help="Coordinator address for heartbeats. Optional.")
    p.add_argument("--heartbeat-interval", type=float, default=1.0)
    p.add_argument("--torch-device", default="cpu")
    p.add_argument("--dtype", default="float32", choices=["float32", "float16", "bfloat16"])
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    server = WorkerServer(
        device_id=DeviceId(args.device_id),
        bind_address=args.bind,
        coordinator_address=args.coord,
        heartbeat_interval=args.heartbeat_interval,
        torch_device=args.torch_device,
        dtype=args.dtype,
    )
    server.start()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, shutting down", signum)
        server.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
