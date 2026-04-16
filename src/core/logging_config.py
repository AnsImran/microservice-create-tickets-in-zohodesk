"""Structured JSON logging configuration.

Production uses JSON lines (one object per line) for log aggregation.
Development can use ``LOG_FORMAT=text`` for human-readable output.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s  %(message)s"


def setup_logging(*, level: str = "INFO", fmt: str = "json") -> None:
    """Configure the root logger with *fmt* format at *level*."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove any pre-existing handlers (e.g. from basicConfig).
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))
    root.addHandler(handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
