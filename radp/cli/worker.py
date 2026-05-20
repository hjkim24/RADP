"""`radp-worker` CLI entry point."""

from __future__ import annotations

import argparse

from radp.common.logging_utils import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-worker")
    p.add_argument("--coord", required=True, help="Coordinator address host:port.")
    p.add_argument("--device-id", required=True, help="Unique device id, e.g. jetson-1.")
    p.add_argument("--bind", default="0.0.0.0:50051")
    p.add_argument("--cache-dir", default=".cache/radp")
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    log.info("worker starting: device=%s coord=%s", args.device_id, args.coord)
    raise NotImplementedError("Phase 2: wire up WorkerServer here.")


if __name__ == "__main__":
    main()
