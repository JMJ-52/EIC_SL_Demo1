from __future__ import annotations

import json
import urllib.error
import urllib.request

TAVILY_URL = "https://api.tavily.com/search"


def search_web(api_key: str, query: str, max_results: int = 5) -> list[dict]:
    """Search Tavily. Raises LLMError-free: callers decide how to handle failure."""
    payload = {"api_key": api_key, "query": query, "max_results": max_results}
    request = urllib.request.Request(
        TAVILY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read())
    return [
        {"title": str(r.get("title") or ""), "url": str(r.get("url") or ""), "content": str(r.get("content") or "")}
        for r in (body.get("results") or [])
        if isinstance(r, dict)
    ]

