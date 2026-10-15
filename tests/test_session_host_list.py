"""A guarded session given a host list refuses a request, and each redirect hop, to any other host.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Wikipedia, ORES and DuckDuckGo clients go through ``guarded_session`` / ``following_session``, whose ``requests`` sessions used to follow
a redirect to whatever host the answer named, with no host check on the hop. ``GuardedSession.send`` is the method ``requests`` calls for the
first request AND for every hop, so the list is checked there, on the URL the HTTP client will connect to.

No network: a scripted adapter stands where the socket would be, so the real ``requests`` redirect machinery runs.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import BaseAdapter

from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import RedirectRefused, guarded_session, refuse_unlisted_host
from src.safety.settings import SafetySettings
from src.wiki.walk import WAIT_REFUSED, refusal_token

ROOT = Path(__file__).resolve().parents[1]

#: The suffix family under wikipedia.org and the bare wikimedia.org (the pageviews host): host names, not URLs.
HOSTS = (".wikipedia.org", "wikimedia.org")


class _Script(BaseAdapter):
    """Stands where the socket would be: answers each URL from a table and records what was sent."""

    def __init__(self, routes: dict[str, tuple[int, str | None]] | None = None) -> None:
        super().__init__()
        self.routes = routes or {}
        self.sent: list[str] = []

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.sent.append(request.url)
        status, location = self.routes.get(request.url, (200, None))
        resp = requests.models.Response()
        resp.status_code = status
        if location:
            resp.headers["Location"] = location
        resp._content = b"{}"
        resp._content_consumed = True  # no raw: iter_content replays _content
        resp.url = request.url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


@pytest.fixture()
def transparent(monkeypatch):
    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="transparent"))
    monkeypatch.setattr(fetcher_mod, "_FOLLOWING", {})
    return monkeypatch


def _session(routes=None, hosts=HOSTS):
    s = guarded_session(allowed_hosts=hosts)
    wire = _Script(routes)
    s.mount("https://", wire)
    s.mount("http://", wire)
    return s, wire


def _refused(call) -> RedirectRefused:
    with pytest.raises(RedirectRefused) as caught:
        call()
    return caught.value


# --------------------------------------------------------------------------- #
# The redirect hop: the case the finding is about
# --------------------------------------------------------------------------- #
def test_a_redirect_to_an_unlisted_host_is_refused_before_it_is_sent(transparent):
    s, wire = _session({"https://en.wikipedia.org/w/api.php": (302, "https://evil.test/steal")})
    err = _refused(lambda: s.get("https://en.wikipedia.org/w/api.php"))
    assert err.reason == "the host is not one this client talks to"
    assert wire.sent == ["https://en.wikipedia.org/w/api.php"], "the hop was never sent"


def test_a_redirect_between_listed_hosts_is_followed(transparent):
    s, wire = _session({"https://en.wikipedia.org/w/api.php": (301, "https://de.wikipedia.org/w/api.php")})
    resp = s.get("https://en.wikipedia.org/w/api.php")
    assert resp.status_code == 200 and wire.sent == ["https://en.wikipedia.org/w/api.php", "https://de.wikipedia.org/w/api.php"]


def test_the_first_request_to_an_unlisted_host_is_refused_and_nothing_is_sent(transparent):
    s, wire = _session()
    assert _refused(lambda: s.get("https://evil.test/")).reason == "the host is not one this client talks to"
    assert wire.sent == []


def test_a_post_is_held_to_the_list_too(transparent):
    s, wire = _session({"https://en.wikipedia.org/x": (302, "https://evil.test/y")})
    _refused(lambda: s.post("https://en.wikipedia.org/x", data={"q": "1"}))
    assert wire.sent == ["https://en.wikipedia.org/x"]


def test_a_chain_is_refused_at_the_hop_that_leaves_the_list_not_before(transparent):
    s, wire = _session(
        {
            "https://en.wikipedia.org/a": (302, "https://de.wikipedia.org/b"),
            "https://de.wikipedia.org/b": (302, "https://evil.test/c"),
        }
    )
    _refused(lambda: s.get("https://en.wikipedia.org/a"))
    assert wire.sent == ["https://en.wikipedia.org/a", "https://de.wikipedia.org/b"]


# --------------------------------------------------------------------------- #
# One test per refusal clause, each of which only that clause can fail
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "https://notwikipedia.org/",  # the suffix is a label boundary, not a substring
        "https://wikipedia.org.evil.test/",  # a listed name as the START of another host
        "https://wikimedia.org.evil.test/",  # the same for an exact entry (a prefix match would let it through)
        "https://.wikipedia.org/",  # a suffix entry is a host UNDER the domain: an empty first label is not one
        "https://wikipedia.org/",  # ``.wikipedia.org`` is any host UNDER it, never the bare domain
        "https://en.wikipedia.org./",  # a trailing dot is another name, refused rather than normalised
        "https://127.0.0.1/",
        "https://[::1]/",
    ],
)
def test_the_host_clause_matches_on_label_boundaries_and_refuses_the_rest(url):
    assert _refused(lambda: refuse_unlisted_host(url, HOSTS)).reason == "the host is not one this client talks to"


def test_a_host_is_compared_as_the_name_the_connection_is_made_to_so_its_case_does_not_matter(transparent):
    """``urllib3`` lower-cases the host it parses; the comparison relies on that, and this fails if it ever stops."""
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://DE.Wikipedia.ORG/b")})
    assert s.get("https://en.wikipedia.org/a").status_code == 200 and len(wire.sent) == 2


def test_a_bare_domain_is_allowed_only_when_the_list_names_it():
    refuse_unlisted_host("https://wikimedia.org/api/rest_v1/x", HOSTS)  # listed as itself
    refuse_unlisted_host("https://stream.wikimedia.org/v2/x", ("wikimedia.org", ".wikimedia.org"))
    with pytest.raises(RedirectRefused):
        refuse_unlisted_host("https://wikimedia.org/x", (".wikimedia.org",))


def test_the_scheme_clause_refuses_a_downgrade_to_http(transparent):
    s, wire = _session({"https://en.wikipedia.org/a": (302, "http://de.wikipedia.org/b")})  # the host IS listed
    assert _refused(lambda: s.get("https://en.wikipedia.org/a")).reason == "the scheme is not https"
    assert wire.sent == ["https://en.wikipedia.org/a"]
    assert _refused(lambda: s.get("http://en.wikipedia.org/a")).reason == "the scheme is not https"


def test_the_userinfo_clause_refuses_credentials_on_a_listed_host(transparent):
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://evil.test@de.wikipedia.org/b")})  # the host IS listed
    assert _refused(lambda: s.get("https://en.wikipedia.org/a")).reason == "the URL carries a user name or a password"
    assert wire.sent == ["https://en.wikipedia.org/a"]


def test_a_backslash_before_an_at_sign_cannot_hide_the_host_in_a_redirect(transparent):
    """requests quotes the backslash on a hop, which turns ``evil.test\\`` into credentials of the listed host: still a refusal."""
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://evil.test\\@de.wikipedia.org/b")})
    _refused(lambda: s.get("https://en.wikipedia.org/a"))
    assert wire.sent == ["https://en.wikipedia.org/a"]


def test_the_port_clause_refuses_another_port_on_a_listed_host(transparent):
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://de.wikipedia.org:8443/b")})
    assert _refused(lambda: s.get("https://en.wikipedia.org/a")).reason == "the URL names a port other than 443"
    assert wire.sent == ["https://en.wikipedia.org/a"]


def test_the_default_port_written_out_is_not_a_refusal(transparent):
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://de.wikipedia.org:443/b")})
    assert s.get("https://en.wikipedia.org/a").status_code == 200 and len(wire.sent) == 2


def test_the_backslash_clause_refuses_an_authority_the_two_readings_split():
    """``urllib3`` reads ``evil.test`` here and ``urlparse`` ``de.wikipedia.org``; the list names evil.test so only the disagreement can refuse.

    The other clauses of ``_refuse_parser_mismatch`` (unparsable, cannot be IDNA-encoded, two hosts) cannot be reached through a session:
    ``prepare_url`` IDNA-encodes a first request and ``requote_uri`` percent-encodes a hop. They have their own tests in
    ``test_ssrf_parser_mismatch.py``."""
    err = _refused(lambda: refuse_unlisted_host("https://evil.test\\@de.wikipedia.org/b", ("evil.test", ".wikipedia.org")))
    assert "backslash" in err.reason


def test_the_percent_clause_refuses_a_host_urllib3_would_decode_and_connect_to():
    """``x%41.wikipedia.org`` is the listed host ``xa.wikipedia.org`` once decoded; only the percent clause refuses it."""
    err = _refused(lambda: refuse_unlisted_host("https://x%41.wikipedia.org/b", HOSTS))
    assert err.reason == "URL host is percent-encoded"


def test_the_percent_clause_holds_on_a_hop_that_survives_requoting(transparent):
    s, wire = _session({"https://en.wikipedia.org/a": (302, "https://x%2B.wikipedia.org/b")})  # %2B is not unreserved, so it stays
    _refused(lambda: s.get("https://en.wikipedia.org/a"))
    assert wire.sent == ["https://en.wikipedia.org/a"]


# --------------------------------------------------------------------------- #
# The URL is read both ways, and the list does not lean on the mismatch refusal
# --------------------------------------------------------------------------- #
def _readings(monkeypatch, **kw):
    """Take ``_refuse_parser_mismatch`` out and answer for both parsers, so only the comparison itself can refuse. With no overrides both
    readings are the clean ``https://de.wikipedia.org/`` (the baseline test proves that passes)."""
    monkeypatch.setattr(fetcher_mod.EthicalFetcher, "_refuse_parser_mismatch", staticmethod(lambda url: None))
    one = {"scheme": "https", "auth": None, "port": None, "host": "de.wikipedia.org"}
    two = {"scheme": "https", "netloc": "de.wikipedia.org", "hostname": "de.wikipedia.org", "port": None}
    for key, value in kw.items():
        (one if key.startswith("u3_") else two)[key[3:]] = value
    monkeypatch.setattr(fetcher_mod, "parse_url", lambda url: SimpleNamespace(**one))

    def urlparse_(url):
        if two.get("raises"):
            raise ValueError("unreadable")
        return SimpleNamespace(**{k: v for k, v in two.items() if k != "raises"})

    monkeypatch.setattr(fetcher_mod, "urlparse", urlparse_)


def test_the_two_readings_baseline_passes(monkeypatch):
    _readings(monkeypatch)
    refuse_unlisted_host("https://de.wikipedia.org/", HOSTS)


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"u3_host": "evil.test"}, "host is not one"),
        ({"up_hostname": "evil.test"}, "host is not one"),
        ({"u3_host": None}, "host is not one"),  # urllib3 reads no host at all
        ({"up_hostname": None}, "host is not one"),  # urlparse reads no host at all
        ({"up_hostname": ""}, "host is not one"),
        ({"u3_host": "de%2ewikipedia.org"}, "host is not one"),  # a percent in ONE reading only: the comparison refuses it by itself
        ({"up_hostname": "de%2ewikipedia.org"}, "host is not one"),
        ({"u3_port": 8443}, "port other than 443"),
        ({"up_port": 8443}, "port other than 443"),
        ({"u3_scheme": "http"}, "scheme is not https"),
        ({"up_scheme": "http"}, "scheme is not https"),
        ({"u3_auth": "user:pw"}, "user name or a password"),
        ({"up_netloc": "user@de.wikipedia.org"}, "user name or a password"),
        ({"up_raises": True}, "cannot be read"),
    ],
    ids=lambda v: "-".join(v) if isinstance(v, dict) else v,
)
def test_each_reading_has_to_pass_on_its_own(monkeypatch, override, reason):
    """``requests`` >= 2.32.2 connects to what ``urlparse`` reads and older releases to what ``urllib3`` reads, so a clause that looked at
    one reading only would protect whichever client version it was written against. The other reading is clean in every case."""
    _readings(monkeypatch, **override)
    err = _refused(lambda: refuse_unlisted_host("https://de.wikipedia.org/", HOSTS))
    assert reason in err.reason


@pytest.mark.parametrize("which", ["urllib3", "urlparse"])
def test_a_percent_in_only_one_reading_is_refused_by_the_percent_clause_when_it_runs(monkeypatch, which):
    """``_refuse_parser_mismatch`` is the refusal that NAMES the cause, and it looks at both parsers' hosts: with a percent in only one of
    them, that clause refuses before any comparison. (Only the two parsers it calls are faked, so the real clause runs.)"""
    import urllib3.util

    from src import ingest

    encoded, plain = "de%2ewikipedia.org", "de.wikipedia.org"
    monkeypatch.setattr(urllib3.util, "parse_url", lambda url: SimpleNamespace(host=encoded if which == "urllib3" else plain))
    monkeypatch.setattr(ingest, "urlparse", lambda url: SimpleNamespace(hostname=encoded if which == "urlparse" else plain))
    err = _refused(lambda: refuse_unlisted_host("https://de.wikipedia.org/", HOSTS))
    assert err.reason == "URL host is percent-encoded"


def test_the_real_parsers_split_a_backslash_authority_and_the_clauses_after_the_mismatch_refusal_still_refuse_it(monkeypatch):
    """With the mismatch refusal taken out, ``urllib3`` reads the listed ``de.wikipedia.org`` and ``urlparse`` (the reading the adapter
    connects to on the installed ``requests``) reads ``evil.test`` after an ``@``: the second reading refuses it as user information."""
    url = "https://de.wikipedia.org\\@evil.test/"
    # The premise, asserted so the test cannot pass vacuously if either library changes how it reads this string:
    assert fetcher_mod.parse_url(url).host == "de.wikipedia.org" and fetcher_mod.urlparse(url).hostname == "evil.test"
    monkeypatch.setattr(fetcher_mod.EthicalFetcher, "_refuse_parser_mismatch", staticmethod(lambda url: None))
    err = _refused(lambda: refuse_unlisted_host(url, HOSTS))
    assert err.reason == "the URL carries a user name or a password"


@pytest.mark.parametrize("location", ["https://evil.test/steal?token=SECRET", "https://evil.test\\@de.wikipedia.org/b", "https://x%2B.wikipedia.org/b"])
def test_a_refusal_never_carries_the_address_it_refused(transparent, location):
    s, _wire = _session({"https://en.wikipedia.org/a": (302, location)})
    text = str(_refused(lambda: s.get("https://en.wikipedia.org/a")))
    assert "evil" not in text and "SECRET" not in text and "x%2B" not in text, text


def test_a_refusal_is_a_request_failure_that_is_not_a_connection_error(transparent):
    """Callers that handle ``RequestException`` handle it; one that retries a ConnectionError does not retry a request that was never sent."""
    s, _wire = _session()
    err = _refused(lambda: s.get("https://evil.test/"))
    assert isinstance(err, requests.exceptions.RequestException)
    assert not isinstance(err, requests.exceptions.ConnectionError) and not isinstance(err, ValueError)


# --------------------------------------------------------------------------- #
# The list is opt-in, holds in both transports, and is validated
# --------------------------------------------------------------------------- #
def test_the_walk_names_a_redirect_refusal_a_refusal_not_a_dropped_connection():
    """Any ``OSError`` the walk meets is a connection that did not answer, and ``RedirectRefused`` is a ``RequestException`` (an
    ``OSError``); nothing was sent, so the edition's wait is named for what it is (``request_refused``)."""
    assert refusal_token(RedirectRefused("the host is not one this client talks to")) == WAIT_REFUSED


def test_a_session_built_without_a_list_follows_redirects_as_before(transparent):
    s = guarded_session()
    wire = _Script({"https://en.wikipedia.org/a": (302, "https://anywhere.test/b")})
    s.mount("https://", wire)
    assert s.allowed_hosts is None and s.get("https://en.wikipedia.org/a").status_code == 200
    assert wire.sent == ["https://en.wikipedia.org/a", "https://anywhere.test/b"]


def test_the_list_holds_in_protected_mode_too(monkeypatch):
    """``_session_for`` returns early for a transparent session; the list is set before that, and holds on the proxy path as well."""
    monkeypatch.setattr(
        fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")
    )
    s = guarded_session(allowed_hosts=HOSTS)
    wire = _Script()
    s.mount("https://", wire)
    assert s.transport_proxy is not None and s.allowed_hosts == HOSTS
    _refused(lambda: s.get("https://evil.test/"))
    assert wire.sent == []


@pytest.mark.parametrize(
    "bad",
    [
        (), ("",), (".",), ("Wikipedia.org",), ("https://wikipedia.org",), ("wikipedia.org/",), ("wikipedia.org:443",),
        ("..wikipedia.org",), ("a..b",), ("-a.org",), ("wíki.org",), ("a b.org",),
        (".org",), ("org",), (".com",),  # a single label: a whole TLD, or no domain at all
        ("wikipedia.org.",), (".wikipedia.org.",),  # a trailing dot is an empty last label
        ("a-.org",), ("a.-b.org",),  # a hyphen at the edge of a label
        ("127.0.0.1",), (".0.0.1",), ("a.1",),  # an address, or a numeric last label, is not a name
        ("x_y.org",), ("*.wikipedia.org",), ("ok.org", "bad host.org"),  # one bad entry among good ones
    ],
)
def test_a_malformed_list_is_refused_when_the_session_is_built(bad, transparent):
    with pytest.raises(ValueError):
        guarded_session(allowed_hosts=bad)


def test_a_bare_string_is_not_a_list_of_its_characters(transparent):
    """``tuple("localhost")`` is nine one-letter entries, each of which a lax check would have called a host."""
    for bare in ("localhost", "wikipedia.org", ".wikipedia.org"):
        with pytest.raises(TypeError):
            guarded_session(allowed_hosts=bare)


def test_ordinary_hosts_and_punycode_labels_are_listable(transparent):
    ok = ("a-b.org", ".a-b.org", "xn--bcher-kva.example", ".co.uk", "ores.wikimedia.org", "a1.b2.org")
    assert guarded_session(allowed_hosts=ok).allowed_hosts == ok


def test_a_well_formed_list_is_stored_as_a_tuple(transparent):
    assert guarded_session(allowed_hosts=["a.org", ".b.org"]).allowed_hosts == ("a.org", ".b.org")


def test_following_session_keys_the_cache_on_the_list(transparent):
    a = fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",))
    assert fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",)) is a, "kept while nothing changes"
    b = fetcher_mod.following_session("o", "ua", allowed_hosts=("b.org",))
    assert b is not a and b.allowed_hosts == ("b.org",), "another list is another session"
    assert fetcher_mod.following_session("o", "ua").allowed_hosts is None


def test_a_session_kept_while_the_settings_cannot_be_read_is_kept_only_for_the_list_it_was_built_with(transparent):
    plain = fetcher_mod.following_session("o", "ua")
    unreadable = SafetySettings(fetch_mode="transparent")
    unreadable.read_failed = True
    transparent.setattr(fetcher_mod, "load_settings", lambda: unreadable)
    assert fetcher_mod.following_session("o", "ua") is plain, "same list and agent: the held session is kept"
    listed = fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",))
    assert listed is not plain and listed.allowed_hosts == ("a.org",), "another list is another session, readable settings or not"
    assert fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",)) is listed


# --------------------------------------------------------------------------- #
# The clients: each hands its session the list that covers every URL it builds
# --------------------------------------------------------------------------- #
def test_the_wiki_clients_session_carries_the_list_that_covers_everything_it_serves(transparent):
    from src.wiki import mediawiki as mw
    from src.wiki import pageviews, stream
    from src.wiki.client import WIKI_SESSION_HOSTS, WikiClient

    assert WikiClient().session.allowed_hosts == WIKI_SESSION_HOSTS
    for url in (
        mw.api_endpoint("en"),
        mw.api_endpoint("zh-yue"),
        pageviews.top_url("en", date(2026, 10, 1)),  # the BARE domain, wikimedia.org
        stream.EVENTSTREAMS_URL,
    ):
        refuse_unlisted_host(url, WIKI_SESSION_HOSTS)


def test_an_edition_code_cannot_choose_the_host_the_wiki_client_calls(transparent):
    from src.wiki import mediawiki as mw
    from src.wiki.client import WIKI_SESSION_HOSTS

    for code in ("evil.test/#", "x@evil.test/", "evil.test\\", "127.0.0.1:9/"):
        with pytest.raises(RedirectRefused):
            refuse_unlisted_host(mw.api_endpoint(code), WIKI_SESSION_HOSTS)


def test_the_ores_clients_session_carries_its_list(transparent):
    from src.wiki.ores import ORES_ENDPOINT, ORES_HOSTS, OresClient

    assert OresClient().session.allowed_hosts == ORES_HOSTS
    refuse_unlisted_host(f"{ORES_ENDPOINT}/enwiki/", ORES_HOSTS)


def test_the_duckduckgo_list_covers_its_endpoint_and_its_own_bare_domain_and_nothing_else(transparent):
    from src.services.duckduckgo import DuckDuckGoSearch

    s, wire = _session(
        {DuckDuckGoSearch.BASE_URL: (302, "https://duckduckgo.com/html/")}, hosts=DuckDuckGoSearch.ALLOWED_HOSTS
    )
    assert s.post(DuckDuckGoSearch.BASE_URL, data={"q": "x"}).status_code == 200 and len(wire.sent) == 2
    for elsewhere in ("https://duckduckgo.com.evil.test/", "https://evilduckduckgo.com/"):
        with pytest.raises(RedirectRefused):
            refuse_unlisted_host(elsewhere, DuckDuckGoSearch.ALLOWED_HOSTS)


def test_the_duckduckgo_search_asks_for_its_list():
    from src.services.duckduckgo import DuckDuckGoSearch

    refuse_unlisted_host(DuckDuckGoSearch.BASE_URL, DuckDuckGoSearch.ALLOWED_HOSTS)
    with patch("src.safety.fetcher.guarded_session") as factory:
        factory.return_value.post.return_value = MagicMock(text="", raise_for_status=lambda: None)
        DuckDuckGoSearch.search("q", max_results=1)
    assert factory.call_args.kwargs["allowed_hosts"] == DuckDuckGoSearch.ALLOWED_HOSTS


def test_an_injected_session_is_not_given_a_list(transparent):
    """The tests' own seam is untouched: a caller that hands a session in keeps it, list and all."""
    from src.wiki.client import WikiClient

    mine = requests.Session()
    assert WikiClient(session=mine).session is mine


# --------------------------------------------------------------------------- #
# The six fixed-endpoint sessions that were the open remainder: each goes through its own default getter
# --------------------------------------------------------------------------- #
@pytest.fixture()
def scripted(monkeypatch):
    """Every ``guarded_session`` a module imports at call time is a real one with a scripted adapter mounted, so the module's OWN default
    getter runs against the real redirect machinery. Drop the ``allowed_hosts`` from a call site and its test below fails."""
    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="transparent"))
    wire = _Script()
    real = fetcher_mod.guarded_session

    def build(**kw):
        s = real(**kw)
        s.mount("https://", wire)
        s.mount("http://", wire)
        return s

    monkeypatch.setattr(fetcher_mod, "guarded_session", build)
    return wire


def _wikidata_get():
    from src.analytics import ring_loader
    from src.catalog import wikidata_apply
    from src.entities import gazetteer_build, items

    return {
        "catalog.wikidata_apply": wikidata_apply._default_getter,
        "entities.items": items._default_getter,
        "entities.gazetteer_build": gazetteer_build.guarded_getter,
        "analytics.ring_loader": ring_loader._default_getter,
    }


WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q42&format=json"


@pytest.mark.parametrize("name", ["catalog.wikidata_apply", "entities.items", "entities.gazetteer_build", "analytics.ring_loader"])
def test_a_wikidata_api_getter_refuses_a_redirect_off_its_host_and_follows_one_on_it(scripted, name):
    get = _wikidata_get()[name]
    scripted.routes[WIKIDATA_API_URL] = (302, "https://evil.test/steal")
    with pytest.raises(RedirectRefused):
        get(WIKIDATA_API_URL)
    assert scripted.sent == [WIKIDATA_API_URL], "the hop was refused before it was sent"
    scripted.sent.clear()
    scripted.routes[WIKIDATA_API_URL] = (302, "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q42&format=json&redirected=1")
    get(WIKIDATA_API_URL)
    assert len(scripted.sent) == 2, "a hop to its own host is followed"


def test_the_sparql_transport_refuses_a_redirect_off_its_host_and_follows_one_on_it(scripted):
    import urllib.parse

    from src.catalog import discover
    from src.catalog.wikidata import WDQS_ENDPOINT, build_query

    cfg = {"label_lang": "en", "limit": 5}
    run_query = discover._guarded_run_query(cfg)
    url = f"{WDQS_ENDPOINT}?" + urllib.parse.urlencode({"query": build_query("FR", ["Q11032"], label_lang="en", limit=5), "format": "json"})
    scripted.routes[url] = (302, "https://evil.test/steal")
    with pytest.raises(RedirectRefused):
        run_query("FR", ["Q11032"])
    assert scripted.sent == [url]


def test_the_weights_digest_fetch_refuses_a_redirect_off_huggingface_and_says_so(scripted, monkeypatch):
    from src.llm import ollama
    from src.llm.ollama import MINISTRAL_VLLM_MODEL
    from src.monitoring import release_run

    class _NoOllama:
        def __init__(self, *a, **k):
            raise RuntimeError("no local Ollama in this test")

    monkeypatch.setattr(ollama, "OllamaClient", _NoOllama)
    url = f"https://huggingface.co/api/models/{MINISTRAL_VLLM_MODEL}"
    scripted.routes[url] = (302, "https://evil.test/steal")
    out = release_run._weights_digest_proposal()
    assert out["hf"]["measured"] is False and "request refused" in out["hf"]["error"]
    assert "evil" not in out["hf"]["error"]
    assert scripted.sent == [url]


def test_every_endpoint_constant_passes_the_list_its_session_carries():
    """The lists are the hosts of the URLs the code builds, and a constant that moves host without its list is caught here."""
    from src.analytics import wikidata_rings
    from src.catalog import wikidata, wikidata_enrich
    from src.monitoring import release_run

    refuse_unlisted_host(wikidata_rings.API_ENDPOINT, wikidata_rings.API_HOSTS)
    refuse_unlisted_host(wikidata_enrich._API, wikidata_enrich.API_HOSTS)
    refuse_unlisted_host(wikidata.WDQS_ENDPOINT, wikidata.WDQS_HOSTS)
    refuse_unlisted_host("https://huggingface.co/api/models/x/y", release_run.HF_API_HOSTS)
    for hosts in (wikidata_rings.API_HOSTS, wikidata_enrich.API_HOSTS, wikidata.WDQS_HOSTS, release_run.HF_API_HOSTS):
        assert fetcher_mod._checked_hosts(hosts) == hosts
    assert wikidata_rings.API_HOSTS == wikidata_enrich.API_HOSTS, "two modules state the one Wikidata API host"
    # ... and a neighbour of each is refused, so a list that grew into a family would show up here:
    for url, hosts in (
        ("https://query.wikidata.org/sparql", wikidata_rings.API_HOSTS),
        ("https://www.wikidata.org/w/api.php", wikidata.WDQS_HOSTS),
        ("https://cdn-lfs.huggingface.co/x", release_run.HF_API_HOSTS),
    ):
        _refused(lambda url=url, hosts=hosts: refuse_unlisted_host(url, hosts))


# --------------------------------------------------------------------------- #
# What still has no list, so that a new session without one is a decision and not an accident
# --------------------------------------------------------------------------- #
_BULK = "bulk downloads from request-chosen mirrors that redirect between CDNs by design"
#: Every module that builds a guarded session WITHOUT a host list: ``{path: (calls, why it has none)}``. Zero slack: a call that gains a
#: list leaves this table, and a new call joins it with its reason. What is left here are URLs chosen by the request or the catalogue, or
#: hosts that move; a session for a fixed endpoint names its list instead.
UNLISTED_SESSIONS = {
    "src/geo/osm_downloads.py": (2, _BULK),
    "src/ingest/segmented_download.py": (2, _BULK),
    "src/wiki/dumps.py": (2, _BULK),
    "src/llm/installer.py": (2, "release assets whose storage host moves (docs/SECURITY.md, local AI install); needs its own look"),
    "src/stats/fetch.py": (1, "the statistics agencies' catalogue URLs: many hosts, none fixed"),
}

#: The factories that make a session. A call to one is unlisted unless it passes ``allowed_hosts`` something other than a literal
#: ``None``; a bare reference to a FUNCTION (``functools.partial(guarded_session, ...)``) cannot be checked, so it counts as unlisted too.
_SESSION_FACTORIES = ("guarded_session", "following_session", "GuardedSession", "_session_for")
_SESSION_FUNCTIONS = ("guarded_session", "following_session")


def _unlisted_in(source: str, filename: str) -> int:
    tree = ast.parse(source, filename=filename)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _SESSION_FACTORIES and alias.asname:
                    aliases[alias.asname] = alias.name
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        return node.attr if isinstance(node, ast.Attribute) else ""

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and name_of(node.func) in _SESSION_FACTORIES:
            listed = any(k.arg == "allowed_hosts" and not (isinstance(k.value, ast.Constant) and k.value.value is None) for k in node.keywords)
            count += 0 if listed else 1
        elif isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in called and name_of(node) in _SESSION_FUNCTIONS:
            count += 1  # a reference that is not a call: handed to partial(), stored, passed on
    return count


def _unlisted_session_calls() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "src/safety/fetcher.py":
            continue
        n = _unlisted_in(path.read_text(encoding="utf-8"), rel)
        if n:
            found[rel] = n
    return found


def test_a_guarded_session_without_a_host_list_is_a_decision_not_an_accident():
    assert all(why.strip() for _calls, why in UNLISTED_SESSIONS.values()), "every unlisted session says why it has no list"
    found = _unlisted_session_calls()
    table = {path: calls for path, (calls, _why) in UNLISTED_SESSIONS.items()}
    assert found == table, (
        "a session built without allowed_hosts follows any redirect; give it a list, or add it to UNLISTED_SESSIONS with the reason "
        f"(new or changed: {sorted(set(found.items()) ^ set(table.items()))})"
    )


@pytest.mark.parametrize(
    "source",
    [
        "from src.safety import fetcher\nfetcher.guarded_session()",
        "from src.safety.fetcher import guarded_session\nguarded_session(isolation_token='x')",
        "from src.safety.fetcher import following_session\nfollowing_session('o', 'ua')",
        "from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=None)",
        "from src.safety.fetcher import guarded_session as gs\ngs()",
        "import functools\nfrom src.safety.fetcher import guarded_session\nfunctools.partial(guarded_session, isolation_token='x')",
        "from src.safety.fetcher import GuardedSession\nGuardedSession()",
        "from src.safety.fetcher import _session_for\n_session_for(s, user_agent='ua')",
    ],
)
def test_the_scanner_counts_every_way_of_building_a_session_without_a_list(source):
    assert _unlisted_in(source, "x.py") == 1


@pytest.mark.parametrize(
    "source",
    [
        "from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=('a.org',))",
        "from src.safety.fetcher import guarded_session as gs\ngs(allowed_hosts=HOSTS)",
        "from src.safety.fetcher import following_session\nfollowing_session('o', 'ua', allowed_hosts=HOSTS)",
        "x = 1",
    ],
)
def test_the_scanner_passes_a_session_that_names_its_list(source):
    assert _unlisted_in(source, "x.py") == 0
