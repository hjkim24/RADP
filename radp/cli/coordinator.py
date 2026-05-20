"""`radp-coordinator` CLI entry point."""

from __future__ import annotations

import argparse

from radp.common.logging_utils import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-coordinator")
    p.add_argument("--config", required=True, help="Path to experiment YAML config.")
    p.add_argument("--bind", default="0.0.0.0:50050", help="gRPC bind address.")
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    log.info("coordinator starting: config=%s bind=%s", args.config, args.bind)
    raise NotImplementedError("Phase 2: wire up CoordinatorServer here.")


if __name__ == "__main__":
    main()
