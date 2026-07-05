"""SearXNG 検索と Web ページ本文取得のクライアント。"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib import parse, request, error


class SearchError(RuntimeError):
    """検索失敗、取得失敗、または検索回数上限到達時に送出する例外。"""


@dataclass
class SearchResult:
    """検索結果 1 件分。

    page_content には実際に URL へアクセスして抽出した本文抜粋を入れる。
    これにより、LLM が検索結果タイトルだけで判断してしまう問題を避ける。
    """

    title: str
    url: str
    summary: str
    page_content: str = ""
    fetch_error: str = ""


class SearxngClient:
    def __init__(self, base_url: str, *, max_searches: int = 5) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_searches = max_searches
        self.search_count = 0

    def search(self, query: str, *, limit: int = 5, fetch_pages: bool = True) -> list[SearchResult]:
        """SearXNG で検索し、可能なら各結果ページの本文も取得する。

        fetch_pages=True の場合、検索結果の上位 URL を実際に開いて本文抜粋を返す。
        本文取得に失敗しても検索自体は失敗扱いにせず、fetch_error に理由を残す。
        """

        if self.max_searches != -1 and self.search_count >= self.max_searches:
            raise SearchError("search limit reached")
        self.search_count += 1
        params = parse.urlencode({"q": query, "format": "json"})
        url = f"{self.base_url}/search?{params}"
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "local-coding-agent/0.1"})
        try:
            with request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise SearchError(f"SearXNG request failed for {url}: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("results", [])[:limit]:
            result = SearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                summary=str(item.get("content", item.get("summary", ""))),
            )
            if fetch_pages and result.url:
                try:
                    result.page_content = self.fetch_url(result.url, max_chars=6000)
                except SearchError as exc:
                    result.fetch_error = str(exc)
            results.append(result)
        return results

    def fetch_url(self, url: str, *, max_chars: int = 12000) -> str:
        """指定 URL の本文を取得して、LLM に渡しやすいテキストへ整形する。"""

        _validate_fetch_url(url)
        req = request.Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "local-coding-agent/0.1",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as resp:
                raw = resp.read(512_000)
                content_type = resp.headers.get("Content-Type", "")
        except error.URLError as exc:
            raise SearchError(f"URL fetch failed for {url}: {exc}") from exc

        charset = _charset_from_content_type(content_type) or "utf-8"
        text = raw.decode(charset, errors="replace")
        if "html" in content_type.lower() or "<html" in text[:1000].lower():
            text = _html_to_text(text)
        return _normalize_text(text)[:max_chars]


def _validate_fetch_url(url: str) -> None:
    """外部サイト本文取得用の最低限の安全確認。

    ローカルホストやプライベート IP へのアクセスを避け、SSRF 的な使われ方を
    しにくくする。DNS 名の最終的な解決先までは検証しないため、実運用では
    ネットワーク境界側の制限も併用する。
    """

    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SearchError(f"only http/https URLs can be fetched: {url}")
    host = parsed.hostname
    if not host:
        raise SearchError(f"URL host is missing: {url}")
    lowered = host.lower()
    if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
        raise SearchError(f"local hosts cannot be fetched: {host}")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise SearchError(f"private or local IPs cannot be fetched: {host}")


def _charset_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^;]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()
