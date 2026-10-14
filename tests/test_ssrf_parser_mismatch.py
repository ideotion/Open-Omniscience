"""A URL the two parsers read as two hosts is refused before any request (first hop and redirects)."""
from __future__ import annotations

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


@pytest.mark.parametrize("url", ["http://a.org\x00.evil/", "http://a.org\t/", "http://a .org/"])
def test_whitespace_and_control_characters_are_refused(url):
    with pytest.raises(BlockedTarget):
        EthicalFetcher._refuse_parser_mismatch(url)


def test_ordinary_urls_pass():
    for u in ("https://www.example.org/a?b=1", "http://[::1]:8080/", "https://bücher.example/x"):
        EthicalFetcher._refuse_parser_mismatch(u)


@pytest.mark.parametrize(
    "url",
    [
        "http://%31%32%37.0.0.1/",  # the host comparison alone refuses this
        "http://%65vil.test/",
        "http://faß.de/",  # two IDNA standards, two names
        "https://evil.test\\@www.example.org/x",  # the backslash clause alone
    ],
)
def test_each_clause_refuses_what_only_it_refuses(url):
    with pytest.raises(BlockedTarget):
        EthicalFetcher._refuse_parser_mismatch(url)


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
