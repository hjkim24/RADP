"""`radp-worker` CLI entry point (Phase 3).

Every flag falls back to an environment variable so that systemd units (or
container orchestrators) can configure the worker via ``Environment=`` lines
without long ExecStart arguments.

  --device-id      / RADP_DEVICE_ID         (required)
  --bind           / RADP_BIND              (default: 0.0.0.0:50051)
  --coord          / RADP_COORD             (default: unset → no heartbeat)
  --heartbeat-interval / RADP_HEARTBEAT_INTERVAL_S  (default: 1.0)
  --torch-device   / RADP_TORCH_DEVICE      (default: cpu)
  --dtype          / RADP_DTYPE             (default: float32)
"""

from __future__ import annotations

import argparse
import os
import signal
from types import FrameType

from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import DeviceId
from radp.worker.server import WorkerServer

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-worker")
    p.add_argument("--device-id", default=os.environ.get("RADP_DEVICE_ID"))
    p.add_argument("--bind", default=os.environ.get("RADP_BIND", "0.0.0.0:50051"))
    p.add_argument("--coord", default=os.environ.get("RADP_COORD"))
    p.add_argument(
        "--heartbeat-interval",
        type=float,
        default=float(os.environ.get("RADP_HEARTBEAT_INTERVAL_S", "1.0")),
    )
    p.add_argument(
        "--torch-device", default=os.environ.get("RADP_TORCH_DEVICE", "cpu")
    )
    p.add_argument(
        "--dtype",
        default=os.environ.get("RADP_DTYPE", "float32"),
        choices=["float32", "float16", "bfloat16"],
    )
    args = p.parse_args()
    if not args.device_id:
        p.error("--device-id or RADP_DEVICE_ID is required")
    return args


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
