"""`radp-worker` CLI entry point (Phase 2)."""

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
    p.add_argument("--device-id", required=True, help="Unique device id, e.g. jetson-1.")
    p.add_argument("--bind", default="0.0.0.0:50051", help="gRPC bind address.")
    p.add_argument("--torch-device", default="cpu", help="torch device string.")
    p.add_argument("--dtype", default="float32", choices=["float32", "float16", "bfloat16"])
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    server = WorkerServer(
        device_id=DeviceId(args.device_id),
        bind_address=args.bind,
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
