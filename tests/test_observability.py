"""Tests for observability: structured logging, correlation ID, metrics."""

from __future__ import annotations

import json
import logging

from max.observability import (
    CorrelationContext,
    JsonFormatter,
    MetricsRegistry,
    configure_logging,
    configure_metrics,
    get_correlation_id,
    set_correlation_id,
)


class TestJsonFormatter:
    def test_formats_as_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="max.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "test message"
        assert parsed["level"] == "INFO"
        assert parsed["module"] == "max.test"

    def test_includes_timestamp(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hi",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed

    def test_includes_correlation_id_when_set(self):
        formatter = JsonFormatter()
        token = set_correlation_id("test-corr-123")
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hi",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["correlation_id"] == "test-corr-123"
        finally:
            CorrelationContext.reset(token)

    def test_correlation_id_null_when_not_set(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hi",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] is None

    def test_includes_exception_info(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="error",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError: boom" in parsed["exception"]


class TestCorrelationContext:
    def test_set_and_get(self):
        token = set_correlation_id("abc-123")
        try:
            assert get_correlation_id() == "abc-123"
        finally:
            CorrelationContext.reset(token)

    def test_get_returns_none_by_default(self):
        assert get_correlation_id() is None

    def test_context_isolation(self):
        token = set_correlation_id("outer")
        try:
            assert get_correlation_id() == "outer"
            inner_token = set_correlation_id("inner")
            assert get_correlation_id() == "inner"
            CorrelationContext.reset(inner_token)
            assert get_correlation_id() == "outer"
        finally:
            CorrelationContext.reset(token)


class TestConfigureLogging:
    def test_sets_log_level(self):
        configure_logging(level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING
        # Reset
        configure_logging(level="DEBUG")

    def test_adds_json_handler(self):
        configure_logging(level="DEBUG", json_format=True)
        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) >= 1
        # Cleanup
        for h in json_handlers:
            root.removeHandler(h)

    def test_repeated_calls_do_not_duplicate_handlers(self):
        configure_logging(level="DEBUG", json_format=True)
        configure_logging(level="DEBUG", json_format=True)
        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) == 1
        # Cleanup
        for h in json_handlers:
            root.removeHandler(h)


class TestMetricsRegistry:
    def test_creates_counter(self):
        registry = MetricsRegistry()
        counter = registry.counter("test.counter", "A test counter")
        assert counter is not None

    def test_creates_histogram(self):
        registry = MetricsRegistry()
        histogram = registry.histogram("test.histogram", "A test histogram")
        assert histogram is not None

    def test_creates_gauge(self):
        registry = MetricsRegistry()
        gauge = registry.gauge("test.gauge", "A test gauge")
        assert gauge is not None

    def test_same_name_returns_same_instrument(self):
        registry = MetricsRegistry()
        c1 = registry.counter("test.dup", "counter")
        c2 = registry.counter("test.dup", "counter")
        assert c1 is c2

    def test_counter_add(self):
        registry = MetricsRegistry()
        counter = registry.counter("test.add", "counter")
        counter.add(1)  # should not raise

    def test_histogram_record(self):
        registry = MetricsRegistry()
        histogram = registry.histogram("test.record", "histogram")
        histogram.record(1.5)  # should not raise


class TestConfigureMetrics:
    def test_returns_registry(self):
        registry = configure_metrics(service_name="test-max", enabled=True)
        assert isinstance(registry, MetricsRegistry)

    def test_disabled_returns_noop_registry(self):
        registry = configure_metrics(service_name="test-max", enabled=False)
        assert isinstance(registry, MetricsRegistry)
        counter = registry.counter("noop.counter", "noop")
        counter.add(1)  # should not raise even when disabled
