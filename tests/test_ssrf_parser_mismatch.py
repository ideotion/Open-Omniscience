"""A URL the two parsers read as two hosts is refused before any request (first hop and redirects)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ingest import BlockedTarget, EthicalFetcher


class _Resp:
    def __init__(self, status: int, location: str | None = None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.url = "http://x/"
        self.content = b""

    def close(self) -> None:
        pass


class _Session:
    def __init__(self, first: _Resp):
        self.first = first
        self.urls: list[str] = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.first if len(self.urls) == 1 else _Resp(200)


def _fetcher(session):
    f = EthicalFetcher.__new__(EthicalFetcher)
    f.session = session
    f.timeout = 5
    f._max_redirects = 3
    f._guard_target = lambda host: None  # type: ignore[method-assign]
    f._isolated_proxies = lambda netloc: None  # type: ignore[method-assign]
    f._request_proxy_endpoints = lambda url, proxies: {}  # type: ignore[method-assign]
    return f


EVIL = "https://evil.test\\@www.example.org/x"


def test_redirect_with_backslash_authority_is_refused_before_the_second_request():
    s = _Session(_Resp(302, EVIL))
    with pytest.raises(BlockedTarget):
        _fetcher(s)._guarded_redirect_get("http://www.example.org/")
    assert s.urls == ["http://www.example.org/"]


def test_first_request_with_backslash_is_refused():
    s = _Session(_Resp(200))
    with pytest.raises(BlockedTarget):
        _fetcher(s)._guarded_redirect_get(EVIL)
    assert s.urls == []


def test_ordinary_urls_pass():
    for u in ("https://www.example.org/a?b=1", "http://[::1]:8080/", "https://bücher.example/x"):
        EthicalFetcher._refuse_parser_mismatch(u)


def _agree(monkeypatch, theirs: str | None, ours: str | None) -> None:
    """Make the two parsers answer what the test says, so only the clause under test can refuse."""
    import urllib3.util

    from src import ingest

    monkeypatch.setattr(urllib3.util, "parse_url", lambda url: SimpleNamespace(host=theirs))
    monkeypatch.setattr(ingest, "urlparse", lambda url: SimpleNamespace(hostname=ours))


@pytest.mark.parametrize("url", ["http://a.org\x00.evil/", "http://a.org\t/", "http://a .org/", "https://x\\@a.org/"])
def test_clause_authority_characters_alone(monkeypatch, url):
    _agree(monkeypatch, "a.org", "a.org")
    with pytest.raises(BlockedTarget, match="authority contains"):
        EthicalFetcher._refuse_parser_mismatch(url)


@pytest.mark.parametrize("host", ["%31%32%37.0.0.1", "a%2eorg"])
def test_clause_percent_encoded_host_alone(monkeypatch, host):
    _agree(monkeypatch, host, host)
    with pytest.raises(BlockedTarget, match="percent-encoded"):
        EthicalFetcher._refuse_parser_mismatch(f"http://{host}/")


def test_clause_percent_encoded_host_for_real():
    for u in ("http://%31%32%37.0.0.1/", "http://%65vil.test/"):
        with pytest.raises(BlockedTarget, match="percent-encoded|read differently"):
            EthicalFetcher._refuse_parser_mismatch(u)


def test_clause_client_cannot_parse_alone(monkeypatch):
    import urllib3.util

    def boom(url):
        raise ValueError("no")

    monkeypatch.setattr(urllib3.util, "parse_url", boom)
    with pytest.raises(BlockedTarget, match="not parsable by the HTTP client"):
        EthicalFetcher._refuse_parser_mismatch("http://a.org/")


def test_clause_urlparse_cannot_read_alone(monkeypatch):
    import urllib3.util

    monkeypatch.setattr(urllib3.util, "parse_url", lambda url: SimpleNamespace(host="a"))
    with pytest.raises(BlockedTarget, match="cannot be read"):
        EthicalFetcher._refuse_parser_mismatch("http://[a/")


def test_clause_idna_encoding_alone(monkeypatch):
    _agree(monkeypatch, "\u00fc..x", "\u00fc..x")
    with pytest.raises(BlockedTarget, match="cannot be encoded"):
        EthicalFetcher._refuse_parser_mismatch("http://x/")


def test_clause_two_hosts_alone(monkeypatch):
    _agree(monkeypatch, "evil.test", "good.org")
    with pytest.raises(BlockedTarget, match="read differently"):
        EthicalFetcher._refuse_parser_mismatch("http://x/")


def test_the_real_parsers_disagree_on_the_backslash_form_and_on_two_idnas():
    for u in (EVIL, "http://faß.de/"):
        with pytest.raises(BlockedTarget, match="authority contains|read differently"):
            EthicalFetcher._refuse_parser_mismatch(u)


@pytest.mark.parametrize(
    "url",
    [
        "https://a.org/p?q=a b",
        "https://example.org/news/some article.html",
        "https://a.org/x#frag ment",
        "https://a.org/p?q=a\\b",
        "https://bücher.example/x",
    ],
)
def test_a_space_or_backslash_outside_the_authority_is_fetched_not_refused(url):
    EthicalFetcher._refuse_parser_mismatch(url)
