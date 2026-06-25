"""Internet access for Ai-Improve.

Gives the AI live access to the web: a resilient search (Wikipedia as the
reliable primary, DuckDuckGo as a best-effort secondary) plus a generic URL
fetcher that strips HTML down to readable text. Search results can be fed
straight back into the classifier as training data.
"""

from __future__ import annotations

import html
import re
import urllib.parse

import requests

_UA = {"User-Agent": "AiImprove/1.0 (+https://github.com/pennshallcreate/ai-improve)"}
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(raw: str, limit: int = 4000) -> str:
    raw = _TAG_RE.sub(" ", raw)
    text = html.unescape(_HTML_RE.sub(" ", raw))
    return _WS_RE.sub(" ", text).strip()[:limit]


def fetch_url(url: str, limit: int = 4000) -> dict:
    """Fetch any URL and return its readable text content."""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    resp = requests.get(url, headers=_UA, timeout=12)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    body = resp.text if "html" in ctype or "text" in ctype else ""
    return {
        "url": resp.url,
        "status": resp.status_code,
        "content_type": ctype,
        "text": _strip_html(body, limit) if body else "(non-text content)",
    }


def _search_wikipedia(query: str, limit: int) -> list[dict]:
    r = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": limit},
        headers=_UA, timeout=10,
    )
    r.raise_for_status()
    out = []
    for hit in r.json().get("query", {}).get("search", []):
        title = hit["title"]
        out.append({
            "title": title,
            "snippet": _strip_html(hit.get("snippet", ""), 300),
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "source": "wikipedia",
        })
    return out


def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    """Best-effort DuckDuckGo HTML scrape (often rate-limited by anti-bot)."""
    r = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
    )
    if r.status_code != 200:
        return []
    out = []
    pattern = re.compile(
        r'result__a"[^>]*href="(.*?)".*?>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>',
        re.S,
    )
    for href, title, snippet in pattern.findall(r.text)[:limit]:
        out.append({
            "title": _strip_html(title, 200),
            "snippet": _strip_html(snippet, 300),
            "url": html.unescape(href),
            "source": "duckduckgo",
        })
    return out


def search(query: str, limit: int = 5) -> dict:
    """Search the web. Tries DuckDuckGo, always backs up with Wikipedia."""
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required")

    results: list[dict] = []
    errors: list[str] = []
    for provider in (_search_duckduckgo, _search_wikipedia):
        try:
            results.extend(provider(query, limit))
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            errors.append(f"{provider.__name__}: {exc}")
        if len(results) >= limit:
            break

    return {"query": query, "results": results[:limit], "errors": errors}
