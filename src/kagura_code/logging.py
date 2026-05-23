"""Logging setup with secret-redaction formatter."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .redact import redact_secrets


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return redact_secrets(text)


_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def setup_logging(
    *,
    level: str = "warn",
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure the 'kagura_code' logger with stderr + optional file sink."""
    logger = logging.getLogger("kagura_code")
    logger.setLevel(_LEVELS[level])
    # Avoid duplicate handlers on repeated setup_logging calls.
    logger.handlers.clear()
    logger.propagate = False

    fmt = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(fmt)
    logger.addHandler(stderr_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger
