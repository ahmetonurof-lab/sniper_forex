#!/usr/bin/env python
"""Persistent runtime logging for SNIPER_FOREX live trading.

Provides:
- RotatingFileHandler to logs/sniper_forex.log (survives terminal closure)
- StreamHandler to stdout (visible in interactive sessions)
- Automatic rotation with bounded retention
- Secret/credential masking

No strategy or trading-logic changes.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Optional

LOGGER_NAME = "sniper_forex"
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "sniper_forex.log"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 5  # Keep 5 rotated files

# Patterns to mask in log output
_SENSITIVE_PATTERNS = [
    re.compile(
        r"(password|passwd|secret|token|api_key|apikey|credential)s?\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"(MT5_PASSWORD|MT5_LOGIN)s?\s*[:=]\s*\S+", re.IGNORECASE),
]


def _mask_sensitive(msg: str) -> str:
    """Mask sensitive values in log messages."""
    for pat in _SENSITIVE_PATTERNS:
        msg = pat.sub(r"\1=***", msg)
    return msg


class _SensitiveFilter(logging.Filter):
    """Filter that masks sensitive values in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _mask_sensitive(str(record.msg))
        if record.args:
            record.args = tuple(
                _mask_sensitive(str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True


def setup_logging(
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
) -> logging.Logger:
    """Initialize persistent logging.

    Creates:
    - logs/sniper_forex.log (rotating, survives terminal closure)
    - stdout stream (visible in interactive sessions)

    Returns the configured logger.
    """
    logger = logging.getLogger(LOGGER_NAME)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s.%(module)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Sensitive filter
    sensitive_filter = _SensitiveFilter()

    # File handler (rotating)
    log_dir_path = Path(log_dir or DEFAULT_LOG_DIR)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    file_path = log_dir_path / (log_file or DEFAULT_LOG_FILE)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(file_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(sensitive_filter)
    logger.addHandler(file_handler)

    # Stream handler (stdout)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(sensitive_filter)
    logger.addHandler(stream_handler)

    logger.info("Logging initialized -> %s", file_path.absolute())
    return logger


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Get the configured logger."""
    return logging.getLogger(name)
