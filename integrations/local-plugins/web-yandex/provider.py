"""Profile-local Yandex search providers over direct HTTP."""
from __future__ import annotations

import logging
import ssl
from urllib.parse import urlsplit

import httpx

from agent.web_search_provider import WebSearchProvider

DIRECT = "https://ya.ru/search/xml/generative"
logger = logging.getLogger(__name__)

CONTEXT_CHARS = 4000


def _http_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def normalize(wire, limit, provider):
    """Keep generated prose separate from source text and preserve citation IDs."""
    if not isinstance(wire, dict):
        return {"success": False, "error": "Search response must be an object"}
    if "result" in wire:
        wire = wire["result"]
    elif isinstance(wire.get("data"), dict) and "search_result" in wire["data"]:
        wire = wire["data"]["search_result"]
    if not isinstance(wire, dict) or not isinstance(wire.get("message"), dict):
        return {"success": False, "error": "Search response has no message object"}
    summary = wire["message"].get("content")
    rejected = wire.get("is_answer_rejected")
    links, titles, sources = wire.get("links", []), wire.get("titles", []), wire.get("used_sources", {})
    if not isinstance(summary, str) or type(rejected) is not bool or not isinstance(links, list) or not isinstance(titles, list) or not isinstance(sources, dict):
        return {"success": False, "error": "Invalid SearchAPI response schema"}
    citations = {}
    by_url = {}
    for key, source in sources.items():
        if isinstance(source, dict) and _http_url(source.get("url")):
            citations[str(key)] = {"title": str(source.get("title", "")), "url": source["url"]}
            by_url[source["url"]] = source
    docs = []
    seen = set()
    for index, url in enumerate(links + list(by_url)):
        if not _http_url(url) or url in seen:
            continue
        seen.add(url)
        source = by_url.get(url, {})
        context = source.get("context", "")
        context = context if isinstance(context, str) else ""
        title = titles[index] if index < len(titles) and isinstance(titles[index], str) else ""
        docs.append({
            "url": url, "title": str(source.get("title") or title),
            "description": context[:CONTEXT_CHARS], "position": len(docs) + 1,
            "context_truncated": len(context) > CONTEXT_CHARS,
            "context_original_chars": len(context),
        })
    data = {
        "web": docs[:limit], "provider": provider,
        "generated_summary": summary, "summary_is_generated": True,
        "citations": citations, "request_id": wire.get("reqid"),
        "source_text_note": "Descriptions contain source text only; empty means not supplied. Verify important claims on original pages.",
    }
    result = {"success": not rejected, "data": data}
    if rejected:
        result.update(rejected=True, error="SearchAPI declined to produce an answer; source links may still be useful")
    return result


class YandexSearchProvider(WebSearchProvider):
    def __init__(self, context=False, endpoint=None):
        self.context = context
        if context and (not _http_url(endpoint) or urlsplit(endpoint).scheme != "https"):
            raise ValueError("context search requires an explicit HTTPS endpoint")
        self.endpoint = endpoint if context else DIRECT

    @property
    def name(self):
        return "yandex-context" if self.context else "yandex"

    @property
    def display_name(self):
        return "Yandex SearchAPI + configured source text" if self.context else "Yandex SearchAPI"

    def is_available(self):
        # Loading is explicit opt-in; availability does not promise network reachability.
        return True

    def search(self, query, limit=5):
        from tools.interrupt import is_interrupted
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            return {"success": False, "error": "Query must contain 1–12000 characters"}
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        try:
            limit = max(1, min(int(limit), 100))
            url = self.endpoint
            payload = {"unexported": True, "data": {"query": query}} if self.context else {"messages": [{"role": "user", "content": query}]}
            response = httpx.post(url, json=payload, timeout=45, follow_redirects=False, verify=ssl.create_default_context())
            if response.status_code != 200:
                return {"success": False, "provider": self.name, "error": f"Search HTTP {response.status_code}"}
            if is_interrupted():
                return {"success": False, "error": "Interrupted"}
            if len(response.content) > 2_000_000:
                return {"success": False, "error": "Search response exceeds 2 MB"}
            return normalize(response.json(), limit, self.name)
        except Exception as exc:
            logger.warning("Yandex search failed: %s", type(exc).__name__)
            return {"success": False, "provider": self.name, "error": f"{type(exc).__name__}: {exc}"}
