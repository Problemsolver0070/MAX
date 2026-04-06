"""Tests for rate limiting setup."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import Request

from max.api.rate_limit import create_limiter, rate_limit_key_func


class TestCreateLimiter:
    def test_creates_limiter_instance(self):
        limiter = create_limiter()
        assert limiter is not None

    def test_limiter_has_key_func(self):
        limiter = create_limiter()
        assert limiter._key_func is not None


class TestRateLimitKeyFunc:
    def test_extracts_client_host(self):
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        key = rate_limit_key_func(request)
        assert key == "1.2.3.4"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock(spec=Request)
        request.client = None
        key = rate_limit_key_func(request)
        assert key == "unknown"
