"""SearXNG search client with result shaping and search limits."""
from __future__ import annotations

from dataclasses import dataclass
import json
from urllib import parse, request, error


class SearchError(RuntimeError):
    """Raised when search fails or the task search budget is exhausted."""


@dataclass
class SearchResult:
    title: str
    url: str
    summary: str


class SearxngClient:
    def __init__(self, base_url: str, *, max_searches: int = 5) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_searches = max_searches
        self.search_count = 0

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        if self.max_searches != -1 and self.search_count >= self.max_searches:
            raise SearchError("search limit reached")
        self.search_count += 1
        params = parse.urlencode({"q": query, "format": "json"})
        url = f"{self.base_url}/search?{params}"
        req = request.Request(url, headers={"Accept": "application/json"})
        try:
            with request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise SearchError(f"SearXNG request failed for {url}: {exc}") from exc
        results = []
        for item in payload.get("results", [])[:limit]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    summary=str(item.get("content", item.get("summary", ""))),
                )
            )
        return results
