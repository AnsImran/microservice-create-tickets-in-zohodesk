"""Structured JSON logging configuration.

Production uses JSON lines (one object per line) for log aggregation.
Development can use ``LOG_FORMAT=text`` for human-readable output.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import UTC, datetime
from pathlib import Path


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

    formatter: logging.Formatter = JSONFormatter() if fmt == "json" else logging.Formatter(TEXT_FORMAT)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Phase-2 observability: when WLS_LOG_FILE is set, also write to a
    # rotating file so Promtail can tail it and ship to Loki.
    file_path = os.environ.get("WLS_LOG_FILE")
    if file_path:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=50 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
