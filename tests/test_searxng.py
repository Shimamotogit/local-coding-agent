import json
from urllib import request
import pytest

from agent.searxng import SearxngClient, SearchError


class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps({"results": [{"title": "Docs", "url": "https://example.com", "content": "Summary"}]}).encode()


def test_search_api_can_be_mocked(monkeypatch):
    monkeypatch.setattr(request, "urlopen", lambda req, timeout=20: FakeResponse())
    client = SearxngClient("http://localhost:8888", max_searches=5)
    results = client.search("pytest")
    assert results[0].title == "Docs"
    assert results[0].url == "https://example.com"
    assert results[0].summary == "Summary"


def test_search_limit_works(monkeypatch):
    monkeypatch.setattr(request, "urlopen", lambda req, timeout=20: FakeResponse())
    client = SearxngClient("http://localhost:8888", max_searches=1)
    client.search("first")
    with pytest.raises(SearchError):
        client.search("second")


def test_search_limit_can_be_disabled(monkeypatch):
    monkeypatch.setattr(request, "urlopen", lambda req, timeout=20: FakeResponse())
    client = SearxngClient("http://localhost:8888", max_searches=-1)
    for _ in range(3):
        assert client.search("many")
