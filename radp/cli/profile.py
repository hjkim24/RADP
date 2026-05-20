"""`radp-profile` CLI: run layer + network profilers and dump JSON."""

from __future__ import annotations

import argparse

from radp.common.logging_utils import configure_logging, get_logger

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-profile")
    p.add_argument("--model-id", required=True)
    p.add_argument("--output", required=True, help="Where to write profile JSON.")
    p.add_argument("--peers", nargs="*", default=[], help="Other workers for network probe.")
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    log.info("profile run: model=%s output=%s", args.model_id, args.output)
    raise NotImplementedError("Phase 1: invoke layer_profiler + network_profiler here.")


if __name__ == "__main__":
    main()
