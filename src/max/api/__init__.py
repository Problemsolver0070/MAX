"""Max REST API package — app factory and router assembly."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from max.api.admin import router as admin_router
from max.api.health import router as health_router
from max.api.introspection import router as introspection_router
from max.api.messaging import router as messaging_router
from max.api.rate_limit import create_limiter
from max.api.telegram import router as telegram_router


def create_api_app(lifespan: Any = None) -> FastAPI:
    """Create the FastAPI application with all routers and middleware.

    Args:
        lifespan: Optional async context manager for startup/shutdown.
    """
    app = FastAPI(
        title="Max API",
        version="0.1.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    # Rate limiting
    limiter = create_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Routers
    app.include_router(health_router)
    app.include_router(messaging_router)
    app.include_router(telegram_router)
    app.include_router(introspection_router)
    app.include_router(admin_router)

    return app
