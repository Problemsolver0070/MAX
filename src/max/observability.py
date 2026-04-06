"""Observability: structured JSON logging, correlation ID context, metrics setup.

Usage:
    from max.observability import configure_logging, set_correlation_id, configure_metrics

    configure_logging(level="DEBUG", json_format=True)
    token = set_correlation_id("req-abc-123")
    # ... all log messages now include correlation_id ...

    registry = configure_metrics(service_name="max", enabled=True)
    counter = registry.counter("requests.total", "Total requests")
    counter.add(1)
"""

from __future__ import annotations

import contextvars
import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)

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
            log_entry["exception"] = "".join(traceback.format_exception(*record.exc_info))

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
        # Avoid duplicate JSON handlers on repeated calls
        for existing in root.handlers[:]:
            if isinstance(existing.formatter, JsonFormatter):
                root.removeHandler(existing)
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    elif not root.handlers:
        logging.basicConfig(level=root.level)


# ── Metrics Registry ──────────────────────────────────────────────────


class MetricsRegistry:
    """Centralized registry for OpenTelemetry metrics instruments.

    Provides typed factory methods for counters, histograms, and gauges.
    Deduplicates instruments by name.
    """

    def __init__(self, meter_name: str = "max") -> None:
        self._meter = metrics.get_meter(meter_name)
        self._instruments: dict[str, Any] = {}

    def counter(self, name: str, description: str = "") -> metrics.Counter:
        """Get or create a counter."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_counter(name, description=description)
        return self._instruments[name]

    def histogram(self, name: str, description: str = "") -> metrics.Histogram:
        """Get or create a histogram."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_histogram(name, description=description)
        return self._instruments[name]

    def gauge(self, name: str, description: str = "") -> metrics.Gauge:
        """Get or create a gauge."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_gauge(name, description=description)
        return self._instruments[name]


# ── Metrics Configuration ─────────────────────────────────────────────


_metrics_configured = False


def configure_metrics(
    service_name: str = "max",
    enabled: bool = False,
) -> MetricsRegistry:
    """Configure OpenTelemetry metrics.

    Args:
        service_name: Service name for metric labeling.
        enabled: If True, set up a real meter provider with console exporter.
            OTLP exporter support will be added when opentelemetry-exporter-otlp
            is introduced; use the otel_exporter_endpoint config field at that time.
    """
    global _metrics_configured  # noqa: PLW0603
    if enabled and not _metrics_configured:
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=60000,
        )
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)
        _metrics_configured = True

    return MetricsRegistry(meter_name=service_name)
