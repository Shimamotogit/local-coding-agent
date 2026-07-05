import json

import pytest

from agent.searxng import SearchError, SearxngClient


class FakeResponse:
    def __init__(self, body, content_type="text/html; charset=utf-8"):
        self._body = body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *_args):
        return self._body


def fake_search_response():
    return FakeResponse(
        json.dumps({"results": [{"title": "Docs", "url": "https://example.com/page", "content": "Summary"}]}),
        content_type="application/json; charset=utf-8",
    )


def fake_page_response():
    return FakeResponse("<html><body><h1>本文タイトル</h1><p>ページ本文です。</p><script>ignore</script></body></html>")


def test_search_api_can_be_mocked(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=20):
        calls.append(req.full_url)
        if "/search?" in req.full_url:
            return fake_search_response()
        return fake_page_response()

    monkeypatch.setattr("agent.searxng.request.urlopen", fake_urlopen)
    client = SearxngClient("http://searxng.example", max_searches=5)
    results = client.search("pytest")
    assert results[0].title == "Docs"
    assert results[0].url == "https://example.com/page"
    assert results[0].summary == "Summary"
    assert "ページ本文です" in results[0].page_content
    assert len(calls) == 2


def test_search_limit_works(monkeypatch):
    monkeypatch.setattr("agent.searxng.request.urlopen", lambda req, timeout=20: fake_search_response())
    client = SearxngClient("http://searxng.example", max_searches=1)
    client.search("first", fetch_pages=False)
    with pytest.raises(SearchError):
        client.search("second", fetch_pages=False)


def test_search_limit_can_be_disabled(monkeypatch):
    monkeypatch.setattr("agent.searxng.request.urlopen", lambda req, timeout=20: fake_search_response())
    client = SearxngClient("http://searxng.example", max_searches=-1)
    for _ in range(3):
        assert client.search("many", fetch_pages=False)


def test_fetch_url_rejects_localhost():
    client = SearxngClient("http://searxng.example")
    with pytest.raises(SearchError):
        client.fetch_url("http://localhost/private")
