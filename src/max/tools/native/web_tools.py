"""HTTP tools — fetch and full request support."""

from __future__ import annotations

from typing import Any

import httpx

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="http.fetch",
        category="web",
        description="HTTP GET/POST request. Returns status, headers, and body.",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET or POST)",
                    "default": "GET",
                },
                "headers": {"type": "object", "description": "Request headers"},
                "body": {
                    "type": "string",
                    "description": "Request body (for POST)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 30,
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="http.request",
        category="web",
        description="Full HTTP request with any method (GET/POST/PUT/DELETE/PATCH/HEAD).",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL"},
                "method": {"type": "string", "description": "HTTP method"},
                "headers": {"type": "object", "description": "Request headers"},
                "body": {"type": "string", "description": "Request body"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 30,
                },
            },
            "required": ["url", "method"],
        },
    ),
]


async def _do_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Perform an HTTP request."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
        )
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text[:50000],  # Cap at 50KB
        }


async def handle_http_fetch(inputs: dict[str, Any]) -> dict[str, Any]:
    """HTTP GET/POST request."""
    return await _do_request(
        url=inputs["url"],
        method=inputs.get("method", "GET"),
        headers=inputs.get("headers"),
        body=inputs.get("body"),
        timeout=inputs.get("timeout", 30),
    )


async def handle_http_request(inputs: dict[str, Any]) -> dict[str, Any]:
    """Full HTTP request with any method."""
    return await _do_request(
        url=inputs["url"],
        method=inputs["method"],
        headers=inputs.get("headers"),
        body=inputs.get("body"),
        timeout=inputs.get("timeout", 30),
    )
