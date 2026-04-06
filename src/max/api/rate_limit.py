"""Rate limiting configuration using slowapi."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter


def rate_limit_key_func(request: Request) -> str:
    """Extract rate limit key from request (client IP)."""
    if request.client is not None:
        return request.client.host
    return "unknown"


def create_limiter() -> Limiter:
    """Create a slowapi Limiter instance."""
    return Limiter(key_func=rate_limit_key_func)
