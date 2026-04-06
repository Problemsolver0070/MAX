"""Observability: structured JSON logging, correlation ID context, metrics setup.

Usage:
    from max.observability import configure_logging, set_correlation_id

    configure_logging(level="DEBUG", json_format=True)
    token = set_correlation_id("req-abc-123")
    # ... all log messages now include correlation_id ...
"""

from __future__ import annotations

import contextvars
import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

# ── Correlation ID Context ──────────────────────────────────────────────

CorrelationContext: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(correlation_id: str) -> contextvars.Token:
    """Set the correlation ID for the current async context. Returns a reset token."""
    return CorrelationContext.set(correlation_id)


def get_correlation_id() -> str | None:
    """Get the correlation ID for the current async context."""
    return CorrelationContext.get()


# ── JSON Formatter ──────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(log_entry, default=str)


# ── Logging Configuration ───────────────────────────────────────────────


def configure_logging(
    level: str = "DEBUG",
    json_format: bool = False,
) -> None:
    """Configure the root logger with optional JSON formatting.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, use JsonFormatter for structured output.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    if json_format:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    elif not root.handlers:
        logging.basicConfig(level=root.level)
