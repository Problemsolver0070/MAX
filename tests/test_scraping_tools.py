"""Tests for web scraping tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native.scraping_tools import (
    TOOL_DEFINITIONS,
    MAX_TEXT_BYTES,
    handle_web_extract_links,
    handle_web_scrape,
    handle_web_search,
)

# ── Sample HTML fixtures ─────────────────────────────────────────────

SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
<h1>Hello World</h1>
<p id="intro">This is a test paragraph.</p>
<script>var x = 1;</script>
<style>.hidden { display: none; }</style>
<div class="content">Main content here.</div>
<a href="/about">About Us</a>
<a href="https://example.com/contact">Contact</a>
<a href="/blog">Blog</a>
</body>
</html>
"""

BRAVE_API_RESPONSE = {
    "web": {
        "results": [
            {
                "title": "Python Docs",
                "url": "https://docs.python.org",
                "description": "Official Python documentation.",
            },
            {
                "title": "Real Python",
                "url": "https://realpython.com",
                "description": "Python tutorials and guides.",
            },
        ]
    }
}


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_httpx_client(response_text: str = "", status_code: int = 200, json_data: dict | None = None):
    """Create a mock httpx.AsyncClient context manager."""
    mock_response = AsyncMock()
    mock_response.status_code = status_code
    mock_response.text = response_text
    mock_response.raise_for_status = MagicMock()
    if json_data is not None:
        mock_response.json = MagicMock(return_value=json_data)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return mock_client, mock_response


# ── Tool definition tests ────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_three_definitions(self):
        assert len(TOOL_DEFINITIONS) == 3

    def test_all_category_web(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "web"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        assert ids == {"web.scrape", "web.extract_links", "web.search"}

    def test_all_require_network_http(self):
        for td in TOOL_DEFINITIONS:
            assert "network.http" in td.permissions

    def test_scrape_schema_requires_url(self):
        scrape = next(td for td in TOOL_DEFINITIONS if td.tool_id == "web.scrape")
        assert "url" in scrape.input_schema["required"]

    def test_extract_links_schema_requires_url(self):
        links = next(td for td in TOOL_DEFINITIONS if td.tool_id == "web.extract_links")
        assert "url" in links.input_schema["required"]

    def test_search_schema_requires_query(self):
        search = next(td for td in TOOL_DEFINITIONS if td.tool_id == "web.search")
        assert "query" in search.input_schema["required"]


# ── web.scrape tests ─────────────────────────────────────────────────


class TestWebScrape:
    @pytest.mark.asyncio
    async def test_scrape_basic(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com"})

        assert result["title"] == "Test Page"
        assert result["url"] == "https://example.com"
        assert "Hello World" in result["text"]
        assert "This is a test paragraph." in result["text"]
        # Script and style should be removed
        assert "var x = 1" not in result["text"]
        assert ".hidden" not in result["text"]

    @pytest.mark.asyncio
    async def test_scrape_with_selector(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com", "selector": "#intro"})

        assert result["title"] == "Test Page"
        assert result["text"] == "This is a test paragraph."

    @pytest.mark.asyncio
    async def test_scrape_selector_not_found(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com", "selector": "#nonexistent"})

        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_scrape_truncation(self):
        # Build HTML with text exceeding 50KB
        big_text = "A" * (MAX_TEXT_BYTES + 10_000)
        big_html = f"<html><head><title>Big</title></head><body><p>{big_text}</p></body></html>"
        mock_client, _ = _mock_httpx_client(big_html)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com"})

        assert len(result["text"]) <= MAX_TEXT_BYTES

    @pytest.mark.asyncio
    async def test_scrape_http_error(self):
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=real_httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com/missing"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_scrape_missing_bs4(self):
        with patch("max.tools.native.scraping_tools.HAS_BS4", False):
            result = await handle_web_scrape({"url": "https://example.com"})

        assert "error" in result
        assert "beautifulsoup4" in result["error"]

    @pytest.mark.asyncio
    async def test_scrape_no_title(self):
        html_no_title = "<html><body><p>No title here.</p></body></html>"
        mock_client, _ = _mock_httpx_client(html_no_title)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_scrape({"url": "https://example.com"})

        assert result["title"] == ""
        assert "No title here." in result["text"]


# ── web.extract_links tests ──────────────────────────────────────────


class TestWebExtractLinks:
    @pytest.mark.asyncio
    async def test_extract_links_basic(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_extract_links({"url": "https://example.com"})

        assert result["count"] == 3
        assert len(result["links"]) == 3
        hrefs = [link["href"] for link in result["links"]]
        assert "/about" in hrefs
        assert "https://example.com/contact" in hrefs
        assert "/blog" in hrefs

    @pytest.mark.asyncio
    async def test_extract_links_with_base_url(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_extract_links(
                {"url": "https://example.com", "base_url": "https://example.com"}
            )

        assert result["count"] == 3
        hrefs = [link["href"] for link in result["links"]]
        # Relative URLs should be resolved
        assert "https://example.com/about" in hrefs
        assert "https://example.com/contact" in hrefs
        assert "https://example.com/blog" in hrefs

    @pytest.mark.asyncio
    async def test_extract_links_text(self):
        mock_client, _ = _mock_httpx_client(SAMPLE_HTML)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_extract_links({"url": "https://example.com"})

        texts = [link["text"] for link in result["links"]]
        assert "About Us" in texts
        assert "Contact" in texts
        assert "Blog" in texts

    @pytest.mark.asyncio
    async def test_extract_links_no_links(self):
        html_no_links = "<html><body><p>No links here.</p></body></html>"
        mock_client, _ = _mock_httpx_client(html_no_links)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_extract_links({"url": "https://example.com"})

        assert result["count"] == 0
        assert result["links"] == []

    @pytest.mark.asyncio
    async def test_extract_links_http_error(self):
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=real_httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(status_code=500)
            )
        )
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_extract_links({"url": "https://example.com/broken"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_extract_links_missing_bs4(self):
        with patch("max.tools.native.scraping_tools.HAS_BS4", False):
            result = await handle_web_extract_links({"url": "https://example.com"})

        assert "error" in result
        assert "beautifulsoup4" in result["error"]


# ── web.search tests ─────────────────────────────────────────────────


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_search_basic(self):
        mock_client, _ = _mock_httpx_client(json_data=BRAVE_API_RESPONSE)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_search({"query": "python", "api_key": "test-key"})

        assert result["count"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Python Docs"
        assert result["results"][1]["url"] == "https://realpython.com"

    @pytest.mark.asyncio
    async def test_search_custom_count(self):
        mock_client, _ = _mock_httpx_client(json_data=BRAVE_API_RESPONSE)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_search({"query": "python", "count": 10, "api_key": "test-key"})

        # Verify the params passed to the API
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["params"]["count"] == 10

    @pytest.mark.asyncio
    async def test_search_missing_api_key(self):
        result = await handle_web_search({"query": "python"})

        assert "error" in result
        assert "API key" in result["error"]

    @pytest.mark.asyncio
    async def test_search_api_error(self):
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=real_httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock(status_code=403)
            )
        )
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_search({"query": "python", "api_key": "bad-key"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        empty_response = {"web": {"results": []}}
        mock_client, _ = _mock_httpx_client(json_data=empty_response)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_search({"query": "xyznonexistent", "api_key": "test-key"})

        assert result["count"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_result_fields(self):
        mock_client, _ = _mock_httpx_client(json_data=BRAVE_API_RESPONSE)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            result = await handle_web_search({"query": "python", "api_key": "test-key"})

        for r in result["results"]:
            assert "title" in r
            assert "url" in r
            assert "description" in r

    @pytest.mark.asyncio
    async def test_search_headers(self):
        mock_client, _ = _mock_httpx_client(json_data=BRAVE_API_RESPONSE)

        with patch("max.tools.native.scraping_tools.httpx.AsyncClient", return_value=mock_client):
            await handle_web_search({"query": "python", "api_key": "my-secret-key"})

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["X-Subscription-Token"] == "my-secret-key"
        assert headers["Accept"] == "application/json"
