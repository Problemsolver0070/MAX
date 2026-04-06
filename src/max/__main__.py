"""Entry point for Max: python -m max."""

from __future__ import annotations

import logging

import uvicorn

from max.app import create_app
from max.config import Settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Start Max with uvicorn."""
    settings = Settings()
    app = create_app()

    uvicorn.run(
        app,
        host=settings.max_host,
        port=settings.max_port,
        log_level="info",
        access_log=False,  # We use structured JSON logging instead
    )


if __name__ == "__main__":
    main()
