"""Tests for OpenAPIToolProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.providers.openapi import OpenAPIToolProvider

_PATCH_HTTPX = "max.tools.providers.openapi.httpx.AsyncClient"

PETSTORE_SPEC: dict = {
    "openapi": "3.0.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                    },
                ],
                "responses": {"200": {"description": "A list of pets"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                },
                                "required": ["name"],
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Pet created"}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "A pet"}},
            },
        },
    },
}


@pytest.fixture
async def provider() -> OpenAPIToolProvider:
    """Create a provider loaded with the petstore spec."""
    p = OpenAPIToolProvider(spec_prefix="petstore")
    await p.load_spec(PETSTORE_SPEC)
    return p


def _mock_httpx_client(
    *,
    response: MagicMock | None = None,
    request_side_effect: Exception | None = None,
    head_response: MagicMock | None = None,
    head_side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a mock httpx.AsyncClient suitable for use as a context manager."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    if request_side_effect:
        client.request = AsyncMock(side_effect=request_side_effect)
    elif response is not None:
        client.request = AsyncMock(return_value=response)

    if head_side_effect:
        client.head = AsyncMock(side_effect=head_side_effect)
    elif head_response is not None:
        client.head = AsyncMock(return_value=head_response)

    return client


class TestOpenAPIToolProvider:
    """Unit tests for the OpenAPI auto-import provider."""

    # ── Spec loading ──────────────────────────────────────────────

    async def test_load_spec_from_dict(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        assert len(tools) == 3

    async def test_load_spec_from_json_string(self) -> None:
        p = OpenAPIToolProvider(spec_prefix="json")
        await p.load_spec(json.dumps(PETSTORE_SPEC))
        tools = await p.list_tools()
        assert len(tools) == 3

    async def test_load_spec_from_yaml_string(self) -> None:
        import yaml

        p = OpenAPIToolProvider(spec_prefix="yml")
        await p.load_spec(yaml.dump(PETSTORE_SPEC))
        tools = await p.list_tools()
        assert len(tools) == 3

    async def test_load_spec_from_file(self, tmp_path) -> None:
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(PETSTORE_SPEC))

        p = OpenAPIToolProvider(spec_prefix="file")
        await p.load_spec(str(spec_file))
        tools = await p.list_tools()
        assert len(tools) == 3

    async def test_load_spec_invalid_raises(self) -> None:
        p = OpenAPIToolProvider(spec_prefix="bad")
        with pytest.raises(ValueError, match="Unable to parse"):
            await p.load_spec("<<<not json or yaml>>>")

    # ── Tool IDs and metadata ─────────────────────────────────────

    async def test_tool_ids(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        ids = {t.tool_id for t in tools}
        assert ids == {
            "petstore.listPets",
            "petstore.createPet",
            "petstore.getPet",
        }

    async def test_provider_id(
        self, provider: OpenAPIToolProvider
    ) -> None:
        assert provider.provider_id == "openapi:petstore"

    async def test_tool_category_is_api(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        assert all(t.category == "api" for t in tools)

    async def test_tool_provider_id_matches(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        assert all(
            t.provider_id == "openapi:petstore" for t in tools
        )

    async def test_tool_descriptions(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        by_id = {t.tool_id: t for t in tools}
        assert by_id["petstore.listPets"].description == "List all pets"
        assert by_id["petstore.createPet"].description == "Create a pet"
        assert by_id["petstore.getPet"].description == "Get a pet"

    # ── Input schemas ─────────────────────────────────────────────

    async def test_input_schema_list_pets(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        by_id = {t.tool_id: t for t in tools}
        schema = by_id["petstore.listPets"].input_schema
        assert "limit" in schema["properties"]
        assert schema["properties"]["limit"] == {"type": "integer"}
        # limit is a query param, not required
        assert (
            "required" not in schema
            or "limit" not in schema.get("required", [])
        )

    async def test_input_schema_create_pet(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        by_id = {t.tool_id: t for t in tools}
        schema = by_id["petstore.createPet"].input_schema
        assert "name" in schema["properties"]
        assert schema["properties"]["name"] == {"type": "string"}
        assert "name" in schema.get("required", [])

    async def test_input_schema_get_pet(
        self, provider: OpenAPIToolProvider
    ) -> None:
        tools = await provider.list_tools()
        by_id = {t.tool_id: t for t in tools}
        schema = by_id["petstore.getPet"].input_schema
        assert "petId" in schema["properties"]
        assert "petId" in schema.get("required", [])

    # ── Fallback operation ID generation ──────────────────────────

    async def test_fallback_tool_id_without_operation_id(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Minimal", "version": "0.1"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/items/{itemId}": {
                    "delete": {
                        "summary": "Delete an item",
                        "parameters": [
                            {
                                "name": "itemId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {
                            "204": {"description": "Deleted"},
                        },
                    }
                }
            },
        }
        p = OpenAPIToolProvider(spec_prefix="min")
        await p.load_spec(spec)
        tools = await p.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_id == "min.delete_items_itemId"

    # ── Execute — GET ─────────────────────────────────────────────

    async def test_execute_get(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 1, "name": "Rex"}]

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.listPets", {"limit": 10}
            )

        assert result.success is True
        assert result.output == [{"id": 1, "name": "Rex"}]

        # Verify the HTTP call
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == (
            "https://petstore.example.com/v1/pets"
        )
        assert call_args[1]["params"] == {"limit": 10}

    # ── Execute — POST ────────────────────────────────────────────

    async def test_execute_post(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 42, "name": "Fido"}

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.createPet", {"name": "Fido"}
            )

        assert result.success is True
        assert result.output == {"id": 42, "name": "Fido"}

        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == (
            "https://petstore.example.com/v1/pets"
        )
        assert call_args[1]["json"] == {"name": "Fido"}

    # ── Execute — path parameters ─────────────────────────────────

    async def test_execute_path_params(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "123",
            "name": "Buddy",
        }

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.getPet", {"petId": "123"}
            )

        assert result.success is True
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == (
            "https://petstore.example.com/v1/pets/123"
        )

    # ── Execute — error cases ─────────────────────────────────────

    async def test_unknown_tool(
        self, provider: OpenAPIToolProvider
    ) -> None:
        result = await provider.execute("petstore.nonexistent", {})
        assert result.success is False
        assert "Unknown tool" in result.error

    async def test_execute_http_error_status(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.getPet", {"petId": "999"}
            )

        assert result.success is False
        assert "404" in result.error

    async def test_execute_network_error(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_client = _mock_httpx_client(
            request_side_effect=ConnectionError("refused"),
        )

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.listPets", {}
            )

        assert result.success is False
        assert "refused" in result.error

    # ── Health check ──────────────────────────────────────────────

    async def test_health_check_healthy(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = _mock_httpx_client(head_response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            assert await provider.health_check() is True

    async def test_health_check_server_error(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = _mock_httpx_client(head_response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            assert await provider.health_check() is False

    async def test_health_check_no_base_url(self) -> None:
        p = OpenAPIToolProvider(spec_prefix="empty")
        assert await p.health_check() is False

    async def test_health_check_connection_error(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_client = _mock_httpx_client(
            head_side_effect=ConnectionError("refused"),
        )

        with patch(_PATCH_HTTPX, return_value=mock_client):
            assert await provider.health_check() is False

    # ── Auth headers ──────────────────────────────────────────────

    async def test_auth_headers_sent(self) -> None:
        p = OpenAPIToolProvider(
            spec_prefix="auth",
            auth_headers={"Authorization": "Bearer tok123"},
        )
        await p.load_spec(PETSTORE_SPEC)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await p.execute("auth.listPets", {"limit": 5})

        assert result.success is True
        call_args = mock_client.request.call_args
        assert call_args[1]["headers"] == {
            "Authorization": "Bearer tok123",
        }

    # ── Base URL extraction ───────────────────────────────────────

    async def test_base_url_extracted(
        self, provider: OpenAPIToolProvider
    ) -> None:
        assert provider._base_url == (
            "https://petstore.example.com/v1"
        )

    async def test_base_url_empty_when_no_servers(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "No servers", "version": "0.1"},
            "paths": {},
        }
        p = OpenAPIToolProvider(spec_prefix="ns")
        await p.load_spec(spec)
        assert p._base_url == ""

    # ── Duration tracking ─────────────────────────────────────────

    async def test_execute_records_duration(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.listPets", {}
            )

        assert result.duration_ms >= 0

    # ── Spec with path-level parameters ───────────────────────────

    async def test_path_level_parameters_merged(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "PathParam", "version": "0.1"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/orgs/{orgId}/members": {
                    "parameters": [
                        {
                            "name": "orgId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "get": {
                        "operationId": "listMembers",
                        "summary": "List org members",
                        "parameters": [
                            {
                                "name": "role",
                                "in": "query",
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {
                            "200": {"description": "Members"},
                        },
                    },
                }
            },
        }
        p = OpenAPIToolProvider(spec_prefix="org")
        await p.load_spec(spec)
        tools = await p.list_tools()
        assert len(tools) == 1
        schema = tools[0].input_schema
        assert "orgId" in schema["properties"]
        assert "role" in schema["properties"]
        assert "orgId" in schema.get("required", [])

    # ── Text response fallback ────────────────────────────────────

    async def test_execute_text_response(
        self, provider: OpenAPIToolProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "plain text response"

        mock_client = _mock_httpx_client(response=mock_response)

        with patch(_PATCH_HTTPX, return_value=mock_client):
            result = await provider.execute(
                "petstore.listPets", {}
            )

        assert result.success is True
        assert result.output == "plain text response"
