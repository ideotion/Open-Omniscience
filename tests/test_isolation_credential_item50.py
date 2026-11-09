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

import contextlib
import hashlib
import hmac
import itertools
import subprocess
import sys
from pathlib import Path

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
ROOT = Path(__file__).resolve().parent.parent
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
    """The ring loader's and the catalogue apply's docstrings say each lookup rides its own circuit."""
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


def test_any_other_token_is_named_by_a_keyed_digest_of_the_whole_token(monkeypatch):
    """HMAC-SHA256 under the process's own key: ``oo.`` and 32 hex digits, never a credential used as written."""
    probe_key = bytes(range(32))
    monkeypatch.setattr(fetcher_mod, "_ISOLATION_KEY", probe_key)
    for token in ("a" * 33, "host.example:8443", wbentities_url("Q42"), "日本", "lone-\ud800-surrogate"):
        want = "oo." + hmac.new(probe_key, token.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:32]
        assert _credential(token) == want
        assert len(want) > 32  # so it can never equal a credential used as written


def test_a_guessed_url_cannot_be_checked_against_its_credential():
    """Whoever reads the SOCKS handshake cannot hash a guessed lookup and compare: the digest is keyed, and the key is the process's."""
    token = wbsearch_url(_NEEDLE)
    cred = _credential(token)
    assert cred != "oo." + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    assert len(fetcher_mod._ISOLATION_KEY) == 32 and any(fetcher_mod._ISOLATION_KEY)


def test_the_key_is_made_fresh_in_each_process():
    """Two interpreters name the same URL differently; within one, the same token keeps its circuit."""
    code = (
        "from src.safety.fetcher import _with_stream_isolation as w;"
        "import sys; print(w('socks5h://127.0.0.1:9050', sys.argv[1]))"
    )
    token = wbentities_url("Q42")
    runs = {
        subprocess.run([sys.executable, "-c", code, token], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        for _ in range(2)
    }
    assert len(runs) == 2, runs


def test_the_key_comes_from_the_os_random_source_and_nowhere_else():
    """A key from the PID or the clock would pass every test above, and lets the handshake reader enumerate it and confirm a guess."""
    import ast

    src = ROOT / "src"
    tree = ast.parse((src / "safety" / "fetcher.py").read_text(encoding="utf-8"))
    values = [
        ast.unparse(node.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id == "_ISOLATION_KEY"
    ]
    assert values == ["secrets.token_bytes(32)"]
    named_in = {p.relative_to(ROOT).as_posix() for p in src.rglob("*.py") if "_ISOLATION_KEY" in p.read_text(encoding="utf-8")}
    assert named_in == {"src/safety/fetcher.py"}


def test_the_same_token_keeps_its_circuit():
    for token in ("news.example", wbentities_url("Q42"), "日本"):
        assert _with_stream_isolation(_SOCKS, token) == _with_stream_isolation(_SOCKS, token)


def test_a_url_tokens_path_and_query_never_reach_the_proxy_url():
    """A short URL whose old 32-character prefix carried its query: the parsed credential no longer does."""
    token = f"https://a.example/?q={_NEEDLE}"
    url = parse_url(_with_stream_isolation(_SOCKS, token))
    assert _NEEDLE not in (url.auth or "") and "example" not in (url.auth or "")


@pytest.mark.parametrize(
    ("module", "getter"),
    [
        ("src.analytics.ring_loader", "_default_getter"),
        ("src.catalog.wikidata_apply", "_default_getter"),
        ("src.entities.items", "_default_getter"),
        ("src.entities.gazetteer_build", "guarded_getter"),
    ],
)
def test_each_wikidata_getter_hands_its_own_url_as_the_token(module, getter, monkeypatch):
    """The lookups are told apart only if each caller hands over the URL it asks for, not a constant."""
    import importlib

    tokens: list[str] = []

    class _Resp:
        status_code = 200
        text = "{}"
        content = b"{}"
        headers: dict = {}

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {}

    class _Session:
        def get(self, url, **kw):
            return _Resp()

    def factory(*, isolation_token=None, **kw):
        tokens.append(isolation_token)
        return _Session()

    monkeypatch.setattr(fetcher_mod, "guarded_session", factory)
    get = getattr(importlib.import_module(module), getter)
    urls = [wbentities_url("Q42"), wbentities_url("Q1")]
    for u in urls:
        # What the getter makes of the stand-in answer is not this test's question; the token it handed over is.
        with contextlib.suppress(Exception):
            get(u)
    assert tokens == urls
    _all_distinct(tokens)


def test_a_protected_session_carries_the_keyed_credential_to_its_proxy(monkeypatch, tmp_path):
    """Built the way every caller builds it, in protected mode over one SOCKS proxy, with a URL token."""
    import requests
    from requests.adapters import BaseAdapter

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_FETCH_MODE", "protected")
    monkeypatch.setenv("OO_HTTP_PROXY", _SOCKS)
    monkeypatch.delenv("OO_HTTP_PROXIES", raising=False)
    monkeypatch.setattr(fetcher_mod, "_FOLLOWING", {})
    sent: list[dict] = []

    class _Recorder(BaseAdapter):
        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            sent.append(dict(proxies or {}))
            resp = requests.models.Response()
            resp.status_code = 200
            resp._content = b"{}"
            resp.url = request.url
            resp.request = request
            return resp

        def close(self) -> None:
            pass

    token = wbentities_url("Q42")
    s = fetcher_mod.guarded_session(isolation_token=token)
    s.mount("https://", _Recorder())
    s.get(token, timeout=5)
    assert sent and sent[0]["https"] == _with_stream_isolation(_SOCKS, token)
    assert parse_url(sent[0]["https"]).auth == f"{_credential(token)}:{_credential(token)}"
    assert _credential(token).startswith("oo.")


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
