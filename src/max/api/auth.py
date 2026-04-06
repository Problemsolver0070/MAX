"""API key authentication for FastAPI endpoints."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from max.api.dependencies import AppState, get_app_state

_bearer = HTTPBearer()


async def verify_api_key(
    app_state: AppState = Depends(get_app_state),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Validate the Bearer token against configured API keys.

    Returns the matched key string for downstream use (e.g., rate limiting key).
    """
    valid_keys = [k.strip() for k in app_state.settings.max_api_keys.split(",") if k.strip()]

    if not valid_keys:
        raise HTTPException(status_code=503, detail="No API keys configured")

    matched = any(
        hmac.compare_digest(credentials.credentials, k)
        for k in valid_keys
    )
    if not credentials.credentials or not matched:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return credentials.credentials
