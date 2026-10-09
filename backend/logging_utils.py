"""Minimal local logging helpers for the public runtime."""

from __future__ import annotations

import logging
from typing import Any


def log_event(source: str, message: object, *, level: str = "INFO", **_: Any) -> None:
    """Emit one structured local log line."""

    logger = logging.getLogger(f"coilem.{str(source).lower()}")
    method = getattr(logger, str(level).lower(), logger.info)
    method(str(message))


def tagged_log(*args: object, level: str = "INFO", **_: object) -> None:
    """Accept the existing tag/message call shapes used by shared math code."""

    if not args:
        return
    if len(args) == 1:
        source, message = "APP", args[0]
    else:
        source, message = str(args[0]), args[1]
    log_event(source, message, level=level)
