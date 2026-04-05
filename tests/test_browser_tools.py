"""Tests for browser automation tools.

All tests mock Playwright — no real browser is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native import browser_tools
from max.tools.native.browser_tools import (
    TOOL_DEFINITIONS,
    close_browser,
    handle_browser_click,
    handle_browser_evaluate,
    handle_browser_fill_form,
    handle_browser_get_content,
    handle_browser_navigate,
    handle_browser_screenshot,
    handle_browser_type,
)

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_browser_state():
    """Reset module-level browser state before and after every test."""
    browser_tools._browser = None
    browser_tools._context = None
    browser_tools._playwright_instance = None
    browser_tools._pages.clear()
    browser_tools.MAX_PAGES = 5
    yield
    browser_tools._browser = None
    browser_tools._context = None
    browser_tools._playwright_instance = None
    browser_tools._pages.clear()
    browser_tools.MAX_PAGES = 5


def _make_mock_page() -> AsyncMock:
    """Create a mock Playwright Page object with all required async methods."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.title = AsyncMock(return_value="Test Page")
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfakeimage")
    page.evaluate = AsyncMock(return_value=42)
    page.eval_on_selector = AsyncMock(return_value="Selected content")
    page.close = AsyncMock()
    page.viewport_size = {"width": 1280, "height": 720}
    return page


def _setup_browser_with_page(page_id: str = "test-page") -> AsyncMock:
    """Set up mock browser, context, and a pre-registered page."""
    mock_page = _make_mock_page()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    browser_tools._browser = mock_browser
    browser_tools._context = mock_context
    browser_tools._pages[page_id] = mock_page

    return mock_page


# ── Tool definitions ──────────────────────────────────────────────────


class TestToolDefinitions:
    def test_seven_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 7

    def test_all_category_browser(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "browser", f"{td.tool_id} has wrong category"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} has wrong provider"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        expected = {
            "browser.navigate",
            "browser.click",
            "browser.type",
            "browser.screenshot",
            "browser.get_content",
            "browser.fill_form",
            "browser.evaluate",
        }
        assert ids == expected

    def test_all_have_input_schema(self):
        for td in TOOL_DEFINITIONS:
            assert "type" in td.input_schema
            assert td.input_schema["type"] == "object"

    def test_all_have_description(self):
        for td in TOOL_DEFINITIONS:
            assert len(td.description) > 10, f"{td.tool_id} has too-short description"


# ── Missing dependency ────────────────────────────────────────────────


class TestMissingPlaywright:
    """When Playwright is not installed, all handlers return an error dict."""

    @pytest.mark.asyncio
    async def test_navigate_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_navigate({"url": "https://example.com"})
            assert "error" in result
            assert "playwright" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_click_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_click({"page_id": "x", "selector": "a"})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_type_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_type({"page_id": "x", "selector": "input", "text": "hi"})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_screenshot_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_screenshot({"page_id": "x"})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_content_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_get_content({"page_id": "x"})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_fill_form_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_fill_form({"page_id": "x", "fields": {"#a": "b"}})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_evaluate_no_playwright(self):
        with patch.object(browser_tools, "HAS_PLAYWRIGHT", False):
            result = await handle_browser_evaluate({"page_id": "x", "expression": "1+1"})
            assert "error" in result


# ── Page not found ────────────────────────────────────────────────────


class TestPageNotFound:
    """Handlers that require an existing page_id return an error when missing."""

    @pytest.mark.asyncio
    async def test_click_page_not_found(self):
        result = await handle_browser_click({"page_id": "missing", "selector": "a"})
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_type_page_not_found(self):
        result = await handle_browser_type(
            {"page_id": "missing", "selector": "input", "text": "hi"}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_screenshot_page_not_found(self):
        result = await handle_browser_screenshot({"page_id": "missing"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_content_page_not_found(self):
        result = await handle_browser_get_content({"page_id": "missing"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fill_form_page_not_found(self):
        result = await handle_browser_fill_form({"page_id": "missing", "fields": {"#a": "b"}})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_evaluate_page_not_found(self):
        result = await handle_browser_evaluate({"page_id": "missing", "expression": "1+1"})
        assert "error" in result


# ── Navigate ──────────────────────────────────────────────────────────


class TestBrowserNavigate:
    @pytest.mark.asyncio
    async def test_navigate_creates_new_page(self):
        mock_page = _make_mock_page()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium = AsyncMock()
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = AsyncMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        mock_settings = MagicMock()
        mock_settings.browser_headless = True
        mock_settings.browser_max_pages = 5

        with (
            patch(
                "max.tools.native.browser_tools.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("max.config.Settings", return_value=mock_settings),
        ):
            result = await handle_browser_navigate({"url": "https://example.com"})

        assert "page_id" in result
        assert result["title"] == "Test Page"
        assert result["content"] == "<html><body>Hello</body></html>"
        mock_page.goto.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_navigate_reuses_existing_page(self):
        mock_page = _setup_browser_with_page("pg1")
        result = await handle_browser_navigate({"url": "https://example.com", "page_id": "pg1"})
        assert result["page_id"] == "pg1"
        mock_page.goto.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_navigate_content_truncated(self):
        mock_page = _setup_browser_with_page("pg1")
        big_content = "A" * 100_000
        mock_page.content = AsyncMock(return_value=big_content)
        result = await handle_browser_navigate({"url": "https://example.com", "page_id": "pg1"})
        assert len(result["content"]) == 50_000


# ── Click ─────────────────────────────────────────────────────────────


class TestBrowserClick:
    @pytest.mark.asyncio
    async def test_click_success(self):
        mock_page = _setup_browser_with_page("pg1")
        result = await handle_browser_click({"page_id": "pg1", "selector": "#btn"})
        assert result == {"clicked": True}
        mock_page.click.assert_called_once_with("#btn")


# ── Type ──────────────────────────────────────────────────────────────


class TestBrowserType:
    @pytest.mark.asyncio
    async def test_type_success(self):
        mock_page = _setup_browser_with_page("pg1")
        result = await handle_browser_type(
            {"page_id": "pg1", "selector": "#email", "text": "user@test.com"}
        )
        assert result == {"typed": True}
        mock_page.fill.assert_called_once_with("#email", "user@test.com")


# ── Screenshot ────────────────────────────────────────────────────────


class TestBrowserScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_success(self):
        mock_page = _setup_browser_with_page("pg1")
        result = await handle_browser_screenshot({"page_id": "pg1"})
        assert "image_base64" in result
        assert result["width"] == 1280
        assert result["height"] == 720
        mock_page.screenshot.assert_called_once_with(full_page=False)

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self):
        mock_page = _setup_browser_with_page("pg1")
        result = await handle_browser_screenshot({"page_id": "pg1", "full_page": True})
        assert "image_base64" in result
        mock_page.screenshot.assert_called_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_screenshot_no_viewport(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.viewport_size = None
        result = await handle_browser_screenshot({"page_id": "pg1"})
        assert result["width"] == 0
        assert result["height"] == 0


# ── Get content ───────────────────────────────────────────────────────


class TestBrowserGetContent:
    @pytest.mark.asyncio
    async def test_get_content_text_default(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.eval_on_selector = AsyncMock(return_value="Hello World")
        result = await handle_browser_get_content({"page_id": "pg1"})
        assert result["content"] == "Hello World"
        mock_page.eval_on_selector.assert_called_once_with("body", "el => el.innerText")

    @pytest.mark.asyncio
    async def test_get_content_html(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.content = AsyncMock(return_value="<html>full</html>")
        result = await handle_browser_get_content({"page_id": "pg1", "format": "html"})
        assert result["content"] == "<html>full</html>"
        mock_page.content.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_content_selector_text(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.eval_on_selector = AsyncMock(return_value="Section text")
        result = await handle_browser_get_content(
            {"page_id": "pg1", "selector": "#main", "format": "text"}
        )
        assert result["content"] == "Section text"
        mock_page.eval_on_selector.assert_called_once_with("#main", "el => el.innerText")

    @pytest.mark.asyncio
    async def test_get_content_selector_html(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.eval_on_selector = AsyncMock(return_value="<div id='main'>Hi</div>")
        result = await handle_browser_get_content(
            {"page_id": "pg1", "selector": "#main", "format": "html"}
        )
        assert result["content"] == "<div id='main'>Hi</div>"
        mock_page.eval_on_selector.assert_called_once_with("#main", "el => el.outerHTML")

    @pytest.mark.asyncio
    async def test_get_content_truncated(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.eval_on_selector = AsyncMock(return_value="X" * 100_000)
        result = await handle_browser_get_content({"page_id": "pg1"})
        assert len(result["content"]) == 50_000


# ── Fill form ─────────────────────────────────────────────────────────


class TestBrowserFillForm:
    @pytest.mark.asyncio
    async def test_fill_form_success(self):
        mock_page = _setup_browser_with_page("pg1")
        fields = {"#name": "Alice", "#email": "alice@test.com", "#age": "30"}
        result = await handle_browser_fill_form({"page_id": "pg1", "fields": fields})
        assert result == {"filled": 3}
        assert mock_page.fill.call_count == 3

    @pytest.mark.asyncio
    async def test_fill_form_empty_fields(self):
        _setup_browser_with_page("pg1")
        result = await handle_browser_fill_form({"page_id": "pg1", "fields": {}})
        assert result == {"filled": 0}


# ── Evaluate ──────────────────────────────────────────────────────────


class TestBrowserEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_success(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.evaluate = AsyncMock(return_value=42)
        result = await handle_browser_evaluate({"page_id": "pg1", "expression": "2 + 40"})
        assert result == {"result": 42}
        mock_page.evaluate.assert_called_once_with("2 + 40")

    @pytest.mark.asyncio
    async def test_evaluate_string_result(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.evaluate = AsyncMock(return_value="hello")
        result = await handle_browser_evaluate({"page_id": "pg1", "expression": "document.title"})
        assert result == {"result": "hello"}

    @pytest.mark.asyncio
    async def test_evaluate_null_result(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_page.evaluate = AsyncMock(return_value=None)
        result = await handle_browser_evaluate({"page_id": "pg1", "expression": "void 0"})
        assert result == {"result": None}


# ── MAX_PAGES limit ──────────────────────────────────────────────────


class TestMaxPagesLimit:
    @pytest.mark.asyncio
    async def test_oldest_page_closed_when_limit_reached(self):
        """When MAX_PAGES pages exist, creating a new one closes the oldest."""
        mock_context = AsyncMock()
        mock_browser = AsyncMock()
        browser_tools._browser = mock_browser
        browser_tools._context = mock_context

        # Pre-populate MAX_PAGES pages
        oldest_page = _make_mock_page()
        browser_tools._pages["page-0"] = oldest_page
        for i in range(1, browser_tools.MAX_PAGES):
            browser_tools._pages[f"page-{i}"] = _make_mock_page()

        assert len(browser_tools._pages) == browser_tools.MAX_PAGES

        # Creating a new page via navigate should evict the oldest
        new_mock_page = _make_mock_page()
        mock_context.new_page = AsyncMock(return_value=new_mock_page)

        result = await handle_browser_navigate(
            {"url": "https://new.example.com", "page_id": "new-page"}
        )

        # The oldest page should have been closed
        oldest_page.close.assert_called_once()
        # page-0 should no longer be in the map
        assert "page-0" not in browser_tools._pages
        # New page should be present
        assert "new-page" in browser_tools._pages
        assert result["page_id"] == "new-page"
        # Total pages should still be MAX_PAGES
        assert len(browser_tools._pages) == browser_tools.MAX_PAGES


# ── Close browser ────────────────────────────────────────────────────


class TestCloseBrowser:
    @pytest.mark.asyncio
    async def test_close_browser_cleans_up(self):
        mock_page = _setup_browser_with_page("pg1")
        mock_browser = browser_tools._browser
        mock_pw_instance = AsyncMock()
        mock_pw_instance.stop = AsyncMock()
        browser_tools._playwright_instance = mock_pw_instance

        await close_browser()

        mock_page.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw_instance.stop.assert_called_once()
        assert browser_tools._browser is None
        assert browser_tools._context is None
        assert browser_tools._playwright_instance is None
        assert len(browser_tools._pages) == 0

    @pytest.mark.asyncio
    async def test_close_browser_when_no_browser(self):
        """close_browser should not raise if no browser is running."""
        await close_browser()
        assert browser_tools._browser is None
        assert browser_tools._playwright_instance is None


# ── Ensure browser ───────────────────────────────────────────────────


class TestEnsureBrowser:
    @pytest.mark.asyncio
    async def test_ensure_browser_launches_once(self):
        """_ensure_browser creates browser and context only once."""
        mock_page = _make_mock_page()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium = AsyncMock()
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = AsyncMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        mock_settings = MagicMock()
        mock_settings.browser_headless = True
        mock_settings.browser_max_pages = 5

        with (
            patch(
                "max.tools.native.browser_tools.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("max.config.Settings", return_value=mock_settings),
        ):
            # First navigate creates the browser
            await handle_browser_navigate({"url": "https://a.com", "page_id": "pg1"})
            # Second navigate reuses existing browser (no new launch)
            await handle_browser_navigate({"url": "https://b.com", "page_id": "pg1"})

        # launch was called only once
        mock_pw_instance.chromium.launch.assert_called_once_with(headless=True)
