"""Distinct isolation tokens ride distinct Tor circuits (queue item 50(a)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Over a SOCKS proxy, ``_with_stream_isolation`` puts a per-token username and password on the proxy URL, and Tor's
``IsolateSOCKSAuth`` builds one circuit per credential. Until item 50(a) the credential was the token stripped to
``[A-Za-z0-9_.-]`` and cut at 32 characters, so every token sharing those first 32 characters shared a circuit: every
Wikidata lookup, every segment of one download, the three dump kinds of one wiki. Each
test below drives the callers' own URL builders and segment path, not hand-written tokens.
"""

from __future__ import annotations

import hashlib
import itertools

import pytest
from urllib3.util import parse_url

from src.analytics.wikidata_rings import wbentities_url, wbsearch_url
from src.geo.osm_downloads import osm_download_url
from src.geo.osm_regions import list_regions
from src.ingest import EthicalFetcher
from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import _with_stream_isolation
from src.wiki.dumps import dump_url

_SOCKS = "socks5h://127.0.0.1:9050"
_NEEDLE = "qneedle"  # a query value a URL token carries; it must not reach the proxy URL


def _credential(token: str) -> str:
    """The username the proxy URL carries for ``token`` (and that the password repeats)."""
    url = parse_url(_with_stream_isolation(_SOCKS, token))
    user, _, password = (url.auth or "").partition(":")
    assert user and user == password, url
    assert (url.host, url.port) == ("127.0.0.1", 9050), url  # the credential never moves the proxy
    return user


def _all_distinct(tokens: list[str]) -> None:
    creds = [_credential(t) for t in tokens]
    assert len(set(tokens)) == len(tokens), "the fixture must hand in distinct tokens"
    assert len(set(creds)) == len(creds), dict(zip(tokens, creds, strict=True))


def test_every_wikidata_lookup_rides_its_own_circuit():
    """The ring loader and the item fetch promise that two lookups are unlinkable over Tor (one circuit each)."""
    _all_distinct([wbsearch_url("inflation"), wbsearch_url("inflación", "es"), wbentities_url("Q42"), wbentities_url("Q1")])


def test_every_dump_of_one_wiki_rides_its_own_circuit():
    _all_distinct([dump_url("en", kind) for kind in ("pages-articles", "pages-articles-multistream", "pages-articles-multistream-index")])


def test_every_osm_region_rides_its_own_circuit():
    """Already true before item 50(a) (the region codes differ early); kept so it stays true."""
    _all_distinct([osm_download_url(r.code) for r in list_regions()])


def test_every_segment_of_one_download_rides_its_own_circuit(monkeypatch):
    """The segmented download's own fetch, with its own per-segment token, handed to the guarded factory."""
    from src.ingest import segmented_download

    tokens: list[str] = []

    class _Resp:
        content = b""

        def raise_for_status(self) -> None:
            return None

    class _Session:
        def get(self, url, **kw):
            return _Resp()

    def factory(*, isolation_token=None, **kw):
        tokens.append(isolation_token)
        return _Session()

    monkeypatch.setattr(fetcher_mod, "guarded_session", factory)
    url = dump_url("en", "pages-articles-multistream")
    for start in range(0, 4 * 1_048_576, 1_048_576):
        segmented_download.default_fetch_segment(url, start, start + 1_048_576)
    assert len(tokens) == 4
    _all_distinct(tokens)


def test_two_hosts_that_share_their_first_32_characters_ride_two_circuits():
    """The fetcher's own per-host credential, from the host key it hands over."""
    f = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, proxy=_SOCKS)
    a = "regional-news-network-of-the-world-north.example"
    b = "regional-news-network-of-the-world-south.example"
    assert a[:32] == b[:32]
    got = {f._isolated_proxies(h)["https"] for h in (a, b)}
    assert len(got) == 2


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("日本", "中国"),  # no kept character: both read "oo" before
        ("host.example:8443", "host.example8443"),  # the port's colon was stripped
        ("[2001:db8::1]", "2001db81"),
    ],
)
def test_tokens_the_old_stripping_folded_together_stay_apart(a, b):
    assert _credential(a) != _credential(b)


def test_a_short_clean_token_is_its_own_credential_as_before():
    for token in ("news.example", "dl-1", "enwiki-dump", "a" * 32):
        assert _credential(token) == token


def test_any_other_token_is_named_by_a_digest_of_the_whole_token():
    for token in ("a" * 33, "host.example:8443", wbentities_url("Q42"), "日本"):
        want = "oo." + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
        assert _credential(token) == want
        assert len(want) > 32  # so it can never equal a credential used as written


def test_the_same_token_keeps_its_circuit():
    for token in ("news.example", wbentities_url("Q42"), "日本"):
        assert _with_stream_isolation(_SOCKS, token) == _with_stream_isolation(_SOCKS, token)


def test_a_url_tokens_path_and_query_never_reach_the_proxy_url():
    out = _with_stream_isolation(_SOCKS, wbsearch_url(_NEEDLE))
    assert _NEEDLE not in out and "wbsearchentities" not in out and "wikidata" not in out


def test_no_two_of_a_large_set_of_real_tokens_share_a_credential():
    """Every dump kind of every UI edition, every OSM region, and four segments of twelve dumps, together."""
    from src.wiki.dumps import DUMP_KINDS

    editions = ("en", "fr", "de", "es", "pt", "ru", "zh", "ja", "ar", "hi", "bn", "id")
    tokens = [dump_url(w, k) for w, k in itertools.product(editions, DUMP_KINDS)]
    tokens += [f"{t}#seg-{s}-{s + 10}" for t in tokens[:12] for s in range(0, 40, 10)]
    tokens += [osm_download_url(r.code) for r in list_regions()]
    _all_distinct(tokens)


def test_credentials_the_caller_chose_and_non_socks_proxies_are_left_alone():
    assert _with_stream_isolation("socks5://u:p@127.0.0.1:9050", "x" * 40) == "socks5://u:p@127.0.0.1:9050"
    assert _with_stream_isolation("http://127.0.0.1:8118", "x" * 40) == "http://127.0.0.1:8118"
    assert _with_stream_isolation(_SOCKS, "") == _SOCKS
    assert _with_stream_isolation(_SOCKS, None) == _SOCKS
