"""Web scraping tools -- scrape, extract links, and search.

Uses httpx for HTTP requests and BeautifulSoup for HTML parsing.
Gracefully degrades when beautifulsoup4 is not installed.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from max.tools.registry import ToolDefinition

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Constants ────────────────────────────────────────────────────────

MAX_TEXT_BYTES = 50_000  # 50 KB cap for scraped text

# ── Tool definitions ─────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="web.scrape",
        category="web",
        description="Scrape a URL and extract text, optionally scoped by CSS selector.",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "selector": {
                    "type": "string",
                    "description": "CSS selector to scope extraction (optional)",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="web.extract_links",
        category="web",
        description="Extract all hyperlinks from a URL, optionally resolving relative links.",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to extract links from"},
                "base_url": {
                    "type": "string",
                    "description": "Base URL for resolving relative links (optional)",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="web.search",
        category="web",
        description="Search the web via Brave Search API. Returns titles, URLs, and snippets.",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 5,
                },
                "api_key": {
                    "type": "string",
                    "description": "Brave Search API key (uses configured key if omitted)",
                },
            },
            "required": ["query"],
        },
    ),
]

# ── Helpers ──────────────────────────────────────────────────────────


def _no_bs4_error() -> dict[str, Any]:
    return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}


async def _fetch_html(url: str, timeout: int = 30) -> httpx.Response:
    """Fetch a URL and return the response."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        return await client.get(url)


# ── Handlers ─────────────────────────────────────────────────────────


async def handle_web_scrape(inputs: dict[str, Any]) -> dict[str, Any]:
    """Scrape a URL and extract text content."""
    if not HAS_BS4:
        return _no_bs4_error()

    url = inputs["url"]
    selector = inputs.get("selector")

    try:
        response = await _fetch_html(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"HTTP error fetching {url}: {exc}"}

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Extract text
    if selector:
        element = soup.select_one(selector)
        if element is None:
            return {"error": f"Selector '{selector}' not found on page", "url": url}
        text = element.get_text(separator="\n", strip=True)
    else:
        # Remove script and style elements for cleaner text
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    return {
        "text": text[:MAX_TEXT_BYTES],
        "title": title,
        "url": url,
    }


async def handle_web_extract_links(inputs: dict[str, Any]) -> dict[str, Any]:
    """Extract all hyperlinks from a URL."""
    if not HAS_BS4:
        return _no_bs4_error()

    url = inputs["url"]
    base_url = inputs.get("base_url")

    try:
        response = await _fetch_html(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"HTTP error fetching {url}: {exc}"}

    soup = BeautifulSoup(response.text, "html.parser")

    links: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if base_url:
            href = urllib.parse.urljoin(base_url, href)
        text = anchor.get_text(strip=True)
        links.append({"text": text, "href": href})

    return {
        "links": links,
        "count": len(links),
    }


async def handle_web_search(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search the web using Brave Search API."""
    query = inputs["query"]
    count = inputs.get("count", 5)
    api_key = inputs.get("api_key", "")

    if not api_key:
        return {
            "error": (
                "Brave Search API key required. "
                "Pass api_key or configure Settings.brave_search_api_key."
            )
        }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": count},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"Brave Search API error: {exc}"}

    data = response.json()
    web_results = data.get("web", {}).get("results", [])

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
        }
        for r in web_results
    ]

    return {
        "results": results,
        "count": len(results),
    }
