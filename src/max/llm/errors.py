"""LLM client error hierarchy for Max."""

from __future__ import annotations


class LLMError(Exception):
    """Base exception for all LLM client errors."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class LLMRateLimitError(LLMError):
    """Raised when the API returns a 429 rate limit response."""


class LLMConnectionError(LLMError):
    """Raised when the API is unreachable."""


class LLMAuthError(LLMError):
    """Raised when authentication fails (invalid/expired API key)."""
