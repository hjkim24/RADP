"""`radp-coordinator` CLI entry point (Phase 2).

  --config / RADP_CONFIG    (required)  Path to coordinator YAML.
"""

from __future__ import annotations

import argparse
import os
import signal
from types import FrameType

from radp.common.logging_utils import configure_logging, get_logger
from radp.coordinator.server import CoordinatorConfig, CoordinatorServer

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-coordinator")
    p.add_argument(
        "--config",
        default=os.environ.get("RADP_CONFIG"),
        help="Path to coordinator YAML config (env: RADP_CONFIG).",
    )
    args = p.parse_args()
    if not args.config:
        p.error("--config or RADP_CONFIG is required")
    return args


def main() -> None:
    configure_logging()
    args = _parse_args()
    config = CoordinatorConfig.from_yaml(args.config)
    server = CoordinatorServer(config)
    log.info("deploying placement to %d workers", len(config.workers))
    server.deploy()
    server.start()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, shutting down", signum)
        server.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
