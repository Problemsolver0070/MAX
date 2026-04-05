"""Browser automation tools — navigate, click, type, screenshot, and more.

Uses Playwright for headless Chromium browser automation.
All tools gracefully degrade if Playwright is not installed.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from max.tools.registry import ToolDefinition

try:
    from playwright.async_api import async_playwright  # noqa: F401

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# ── Module-level state ────────────────────────────────────────────────

_browser: Any = None  # playwright Browser instance
_context: Any = None  # BrowserContext
_pages: dict[str, Any] = {}  # page_id → Page
MAX_PAGES = 5
MAX_CONTENT_BYTES = 50_000  # 50 KB cap for content returns

# ── Tool definitions ──────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="browser.navigate",
        category="browser",
        description="Navigate to a URL in a headless browser. Reuses or creates a page.",
        permissions=["network.http", "browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "page_id": {
                    "type": "string",
                    "description": "Page ID to reuse (optional, creates new if omitted)",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="browser.click",
        category="browser",
        description="Click an element on the page by CSS selector.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click",
                },
            },
            "required": ["page_id", "selector"],
        },
    ),
    ToolDefinition(
        tool_id="browser.type",
        category="browser",
        description="Type text into an input element on the page.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input element",
                },
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["page_id", "selector", "text"],
        },
    ),
    ToolDefinition(
        tool_id="browser.screenshot",
        category="browser",
        description="Take a screenshot of the current page. Returns base64-encoded PNG.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "full_page": {
                    "type": "boolean",
                    "description": "Capture full scrollable page",
                    "default": False,
                },
            },
            "required": ["page_id"],
        },
    ),
    ToolDefinition(
        tool_id="browser.get_content",
        category="browser",
        description="Get page content as HTML or text, optionally scoped to a selector.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "selector": {
                    "type": "string",
                    "description": "CSS selector to scope content (optional)",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: html or text",
                    "default": "text",
                    "enum": ["html", "text"],
                },
            },
            "required": ["page_id"],
        },
    ),
    ToolDefinition(
        tool_id="browser.fill_form",
        category="browser",
        description="Fill multiple form fields at once.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "fields": {
                    "type": "object",
                    "description": "Mapping of CSS selector to value to fill",
                },
            },
            "required": ["page_id", "fields"],
        },
    ),
    ToolDefinition(
        tool_id="browser.evaluate",
        category="browser",
        description="Execute JavaScript expression in the browser page context.",
        permissions=["browser.control"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID"},
                "expression": {
                    "type": "string",
                    "description": "JavaScript expression to evaluate",
                },
            },
            "required": ["page_id", "expression"],
        },
    ),
]

# ── Helpers ───────────────────────────────────────────────────────────


async def _ensure_browser() -> None:
    """Launch browser if not running."""
    global _browser, _context
    if _browser is None:
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)
        _context = await _browser.new_context()


async def _get_page(page_id: str | None = None) -> tuple[str, Any]:
    """Get existing page or create new one.

    If max pages reached, closes the oldest page to make room.
    """
    await _ensure_browser()
    if page_id and page_id in _pages:
        return page_id, _pages[page_id]
    if len(_pages) >= MAX_PAGES:
        # Close oldest page
        oldest = next(iter(_pages))
        await _pages[oldest].close()
        del _pages[oldest]
    pid = page_id or str(uuid.uuid4())[:8]
    _pages[pid] = await _context.new_page()
    return pid, _pages[pid]


def _require_page(page_id: str) -> Any | None:
    """Return a page by id, or None if not found."""
    return _pages.get(page_id)


async def close_browser() -> None:
    """Cleanup browser resources."""
    global _browser, _context, _pages
    for page in _pages.values():
        await page.close()
    _pages.clear()
    if _browser:
        await _browser.close()
        _browser = None
        _context = None


def _no_playwright_error() -> dict[str, Any]:
    return {
        "error": (
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )
    }


# ── Handlers ──────────────────────────────────────────────────────────


async def handle_browser_navigate(inputs: dict[str, Any]) -> dict[str, Any]:
    """Navigate to a URL."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    url = inputs["url"]
    page_id_input = inputs.get("page_id")
    pid, page = await _get_page(page_id_input)
    await page.goto(url)
    title = await page.title()
    content = await page.content()
    return {
        "page_id": pid,
        "title": title,
        "content": content[:MAX_CONTENT_BYTES],
    }


async def handle_browser_click(inputs: dict[str, Any]) -> dict[str, Any]:
    """Click an element on the page."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    await page.click(inputs["selector"])
    return {"clicked": True}


async def handle_browser_type(inputs: dict[str, Any]) -> dict[str, Any]:
    """Type text into an input element."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    await page.fill(inputs["selector"], inputs["text"])
    return {"typed": True}


async def handle_browser_screenshot(inputs: dict[str, Any]) -> dict[str, Any]:
    """Take a screenshot of the page."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    full_page = inputs.get("full_page", False)
    screenshot_bytes = await page.screenshot(full_page=full_page)
    image_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
    viewport = page.viewport_size or {"width": 0, "height": 0}
    return {
        "image_base64": image_b64,
        "width": viewport.get("width", 0),
        "height": viewport.get("height", 0),
    }


async def handle_browser_get_content(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get page content as HTML or text."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    selector = inputs.get("selector")
    fmt = inputs.get("format", "text")

    if selector:
        if fmt == "html":
            content = await page.eval_on_selector(selector, "el => el.outerHTML")
        else:
            content = await page.eval_on_selector(selector, "el => el.innerText")
    else:
        if fmt == "html":
            content = await page.content()
        else:
            content = await page.eval_on_selector("body", "el => el.innerText")

    return {"content": str(content)[:MAX_CONTENT_BYTES]}


async def handle_browser_fill_form(inputs: dict[str, Any]) -> dict[str, Any]:
    """Fill multiple form fields."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    fields = inputs["fields"]
    count = 0
    for selector, value in fields.items():
        await page.fill(selector, value)
        count += 1
    return {"filled": count}


async def handle_browser_evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute JavaScript in the page context."""
    if not HAS_PLAYWRIGHT:
        return _no_playwright_error()
    page = _require_page(inputs["page_id"])
    if page is None:
        return {"error": f"page '{inputs['page_id']}' not found"}
    result = await page.evaluate(inputs["expression"])
    return {"result": result}
