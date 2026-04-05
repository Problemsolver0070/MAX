"""Tests for HTTP tools."""

from unittest.mock import AsyncMock, patch

import pytest

from max.tools.native.web_tools import handle_http_fetch, handle_http_request


class TestHttpFetch:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "Hello World"
        mock_response.headers = {"content-type": "text/plain"}

        with patch("max.tools.native.web_tools.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handle_http_fetch({"url": "https://example.com"})
            assert result["status_code"] == 200
            assert result["body"] == "Hello World"


class TestHttpRequest:
    @pytest.mark.asyncio
    async def test_put_request(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"content-type": "application/json"}

        with patch("max.tools.native.web_tools.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handle_http_request({
                "url": "https://api.example.com/data",
                "method": "PUT",
                "body": '{"key": "value"}',
                "headers": {"Content-Type": "application/json"},
            })
            assert result["status_code"] == 200
