"""Shared logger setup so coordinator and workers produce consistent log lines."""

from __future__ import annotations

import logging
import sys

_FMT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Install a stderr handler with the standard format. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FMT))
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
