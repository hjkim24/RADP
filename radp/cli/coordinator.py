"""`radp-coordinator` CLI entry point (Phase 2)."""

from __future__ import annotations

import argparse
import signal
from types import FrameType

from radp.common.logging_utils import configure_logging, get_logger
from radp.coordinator.server import CoordinatorConfig, CoordinatorServer

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-coordinator")
    p.add_argument("--config", required=True, help="Path to coordinator YAML config.")
    return p.parse_args()


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
