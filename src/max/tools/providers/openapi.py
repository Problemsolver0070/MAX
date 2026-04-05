"""OpenAPIToolProvider — auto-generates tools from an OpenAPI 3.x specification."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from max.tools.models import ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.registry import ToolDefinition

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)


def _slugify_path(method: str, path: str) -> str:
    """Convert a method + path into a snake_case operation name.

    Example: GET /pets/{petId}/toys  →  get_pets_petId_toys
    """
    # Remove braces from path params, split on '/'
    cleaned = re.sub(r"[{}]", "", path).strip("/")
    parts = cleaned.split("/")
    return f"{method.lower()}_{'_'.join(parts)}"


class OpenAPIToolProvider(ToolProvider):
    """Provider that reads an OpenAPI 3.x spec and exposes endpoints as tools.

    Each path + method combination becomes a distinct tool.  Tool IDs follow
    the pattern ``{prefix}.{operationId}`` when an operationId is declared,
    otherwise ``{prefix}.{method}_{path_snake}``.
    """

    def __init__(
        self,
        spec_prefix: str,
        auth_headers: dict[str, str] | None = None,
    ) -> None:
        self._prefix = spec_prefix
        self._auth_headers = auth_headers or {}
        self._base_url: str = ""
        self._tools: list[ToolDefinition] = []
        self._endpoints: dict[str, dict[str, Any]] = {}

    # ── ToolProvider interface ────────────────────────────────────────

    @property
    def provider_id(self) -> str:
        return f"openapi:{self._prefix}"

    async def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute an HTTP call corresponding to the given tool."""
        start = time.monotonic()
        endpoint = self._endpoints.get(tool_id)
        if not endpoint:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Unknown tool: {tool_id}",
            )

        method: str = endpoint["method"]
        path: str = endpoint["path"]
        param_defs: list[dict[str, Any]] = endpoint.get("parameters", [])
        has_request_body: bool = endpoint.get("has_request_body", False)

        # Separate inputs into path / query / body buckets
        path_params: dict[str, str] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}

        param_locations: dict[str, str] = {p["name"]: p["in"] for p in param_defs}

        for key, value in inputs.items():
            location = param_locations.get(key)
            if location == "path":
                path_params[key] = str(value)
            elif location == "query":
                query_params[key] = value
            elif location == "header":
                pass  # headers handled separately
            elif has_request_body:
                body_params[key] = value
            else:
                query_params[key] = value

        # Substitute path parameters
        url = self._base_url + path
        for name, value in path_params.items():
            url = url.replace(f"{{{name}}}", value)

        headers = dict(self._auth_headers)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if method.upper() in ("POST", "PUT", "PATCH") and body_params:
                    response = await client.request(
                        method.upper(),
                        url,
                        json=body_params,
                        params=query_params or None,
                        headers=headers or None,
                    )
                else:
                    response = await client.request(
                        method.upper(),
                        url,
                        params=query_params or None,
                        headers=headers or None,
                    )

            duration_ms = int((time.monotonic() - start) * 1000)

            if response.status_code >= 400:
                return ToolResult(
                    tool_id=tool_id,
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text}",
                    duration_ms=duration_ms,
                )

            # Try to parse JSON, fall back to text
            try:
                output = response.json()
            except Exception:
                output = response.text

            return ToolResult(
                tool_id=tool_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("OpenAPI tool %s execution failed", tool_id)
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Ping the base URL with a HEAD request."""
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.head(self._base_url)
                return resp.status_code < 500
        except Exception:
            return False

    # ── Spec loading ──────────────────────────────────────────────────

    async def load_spec(self, spec: dict[str, Any] | str) -> None:
        """Load an OpenAPI 3.x spec from a dict, JSON/YAML string, or file path.

        After loading, tool definitions and endpoint metadata are populated
        and available via :meth:`list_tools` and :meth:`execute`.
        """
        parsed = self._parse_spec(spec)
        self._extract_base_url(parsed)
        self._build_tools(parsed)

    def _parse_spec(self, spec: dict[str, Any] | str) -> dict[str, Any]:
        """Resolve *spec* to a Python dict."""
        if isinstance(spec, dict):
            return spec

        # Try JSON first
        try:
            return json.loads(spec)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try YAML
        if HAS_YAML:
            try:
                loaded = yaml.safe_load(spec)
                if isinstance(loaded, dict):
                    return loaded
            except yaml.YAMLError:
                pass

        # Try as file path
        path = Path(spec)
        if path.exists():
            text = path.read_text()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            if HAS_YAML:
                try:
                    loaded = yaml.safe_load(text)
                    if isinstance(loaded, dict):
                        return loaded
                except yaml.YAMLError:
                    pass

        msg = "Unable to parse OpenAPI spec: not valid JSON, YAML, or file path"
        raise ValueError(msg)

    def _extract_base_url(self, spec: dict[str, Any]) -> None:
        """Pull the base URL from ``servers[0].url``."""
        servers = spec.get("servers", [])
        if servers and isinstance(servers, list):
            self._base_url = servers[0].get("url", "").rstrip("/")

    def _build_tools(self, spec: dict[str, Any]) -> None:
        """Walk ``paths`` and create a ToolDefinition per operation."""
        self._tools.clear()
        self._endpoints.clear()

        paths = spec.get("paths", {})
        for path, path_item in paths.items():
            # path-level parameters apply to all methods
            path_level_params = path_item.get("parameters", [])

            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                operation = path_item.get(method)
                if operation is None:
                    continue

                operation_id = operation.get("operationId")
                if operation_id:
                    tool_id = f"{self._prefix}.{operation_id}"
                else:
                    tool_id = f"{self._prefix}.{_slugify_path(method, path)}"

                # Merge path-level + operation-level parameters
                op_params = list(path_level_params) + operation.get("parameters", [])

                # Build input_schema
                input_schema = self._build_input_schema(op_params, operation.get("requestBody"))

                has_body = operation.get("requestBody") is not None

                description = operation.get("summary") or operation.get("description") or ""

                tool_def = ToolDefinition(
                    tool_id=tool_id,
                    category="api",
                    description=description,
                    provider_id=self.provider_id,
                    input_schema=input_schema,
                )
                self._tools.append(tool_def)
                self._endpoints[tool_id] = {
                    "method": method,
                    "path": path,
                    "parameters": op_params,
                    "has_request_body": has_body,
                }

    @staticmethod
    def _build_input_schema(
        parameters: list[dict[str, Any]],
        request_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Combine parameters and requestBody into a single JSON-Schema object."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        # Parameters (path, query, header, cookie)
        for param in parameters:
            name = param["name"]
            schema = param.get("schema", {"type": "string"})
            properties[name] = schema
            if param.get("required", False) or param.get("in") == "path":
                if name not in required:
                    required.append(name)

        # Request body — application/json schema
        if request_body:
            content = request_body.get("content", {})
            json_schema = content.get("application/json", {}).get("schema", {})
            body_props = json_schema.get("properties", {})
            body_required = json_schema.get("required", [])

            properties.update(body_props)
            for r in body_required:
                if r not in required:
                    required.append(r)

        result: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["required"] = required

        return result
