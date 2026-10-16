"""A guarded session given a host list refuses a request, and each redirect hop, to any other host.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Wikipedia, ORES and DuckDuckGo clients go through ``guarded_session`` / ``following_session``, whose ``requests`` sessions used to follow
a redirect to whatever host the answer named, with no host check on the hop. ``GuardedSession.send`` is the method ``requests`` calls for the
first request AND for every hop, so the list is checked there, on the URL the HTTP client will connect to. The five Wikidata loaders, the
Hugging Face release check and the Ollama installer's release lookup each build one fixed endpoint and carry a list of exactly its host
(tested below, module by module); the installer's download carries the exact hosts the repository records GitHub serving a release asset from.

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
        self.bodies: dict[str, bytes] = {}  # a URL's body when it answers 200; ``{}`` otherwise
        self.sent: list[str] = []
        self.timeouts: list[float | None] = []  # the timeout each request was sent with, in step with ``sent``

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.sent.append(request.url)
        self.timeouts.append(timeout)
        status, location = self.routes.get(request.url, (200, None))
        resp = requests.models.Response()
        resp.status_code = status
        if location:
            resp.headers["Location"] = location
        resp._content = self.bodies.get(request.url, b"{}")
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
        # A percent in ONE reading only. Here the ``%2e`` eats the dot the ``.wikipedia.org`` suffix needs, so the comparison refuses; a percent
        # elsewhere in a listed label (``x%41.wikipedia.org``) passes the comparison and only the percent clause below refuses it.
        ({"u3_host": "de%2ewikipedia.org"}, "host is not one"),
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

    wire.sessions = []  # every session the module under test built, so a test can read the list it was given

    def build(**kw):
        s = real(**kw)
        s.mount("https://", wire)
        s.mount("http://", wire)
        wire.sessions.append(s)
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
    assert {s.allowed_hosts for s in scripted.sessions} == {("www.wikidata.org",)}, "the getter's own session carries exactly the API host"


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
    assert scripted.sent == [url], "the hop was refused before it was sent"
    scripted.sent.clear()
    scripted.routes[url] = (302, f"{WDQS_ENDPOINT}?redirected=1")
    run_query("FR", ["Q11032"])
    assert len(scripted.sent) == 2, "a hop to its own host is followed"
    assert {s.allowed_hosts for s in scripted.sessions} == {("query.wikidata.org",)}, "the transport's own session carries exactly the WDQS host"


def test_the_weights_digest_fetch_refuses_a_redirect_off_huggingface_and_says_so(scripted, monkeypatch):
    from src.llm import ollama
    from src.llm.ollama import MINISTRAL_VLLM_MODEL
    from src.monitoring import release_run

    class _NoOllama:
        def __init__(self, *a, **k):
            raise RuntimeError("no local Ollama in this test")

    monkeypatch.setattr(ollama, "OllamaClient", _NoOllama)
    url = release_run.HF_MODEL_API_URL.format(model=MINISTRAL_VLLM_MODEL)
    scripted.routes[url] = (302, "https://evil.test/steal")
    out = release_run._weights_digest_proposal()
    assert out["hf"]["measured"] is False and "request refused" in out["hf"]["error"]
    assert "evil" not in out["hf"]["error"]
    assert scripted.sent == [url]
    assert {s.allowed_hosts for s in scripted.sessions} == {("huggingface.co",)}, "the check's own session carries exactly the Hugging Face host"


@pytest.fixture()
def installer_scripted(scripted, monkeypatch):
    """The Ollama installer's own default getter, run through ``prepare_installer`` against the scripted wire: a scripted platform, the kill switch clear."""
    from src.ingest import clear_kill_switch
    from src.llm import installer

    clear_kill_switch()
    monkeypatch.setattr(installer, "platform_support", lambda: {"scripted": True, "download_url": "https://ollama.com/download"})
    yield scripted
    clear_kill_switch()


def test_the_installer_release_lookup_refuses_a_redirect_off_its_host_and_follows_one_on_it(installer_scripted):
    from src.llm import installer

    url = installer.GITHUB_LATEST_RELEASE
    installer_scripted.routes[url] = (302, "https://exfil.example.invalid/steal?k=secret")
    with pytest.raises(installer.InstallerRedirectRefused) as caught:
        installer._default_get_json(url)
    assert installer_scripted.sent == [url], "the hop was refused before it was sent"
    assert isinstance(caught.value, installer.InstallerVerificationError), "the route that maps a verification failure maps this one too"
    installer_scripted.sent.clear()
    # GitHub answers a renamed repository with a 301 to the repository's id, on the SAME host: that stays followed.
    installer_scripted.routes[url] = (301, "https://api.github.com/repositories/1/releases/latest")
    assert installer._default_get_json(url) == {}
    assert installer_scripted.sent == [url, "https://api.github.com/repositories/1/releases/latest"]
    assert {s.allowed_hosts for s in installer_scripted.sessions} == {("api.github.com",)}, "the lookup's own session carries exactly the API host"
    # ... and the same host over plain http is refused by the scheme clause, so the sentence says "somewhere", not "another host":
    installer_scripted.sent.clear()
    installer_scripted.routes[url] = (302, "http://api.github.com/repos/ollama/ollama/releases/latest")
    with pytest.raises(installer.InstallerRedirectRefused):
        installer._default_get_json(url)
    assert installer_scripted.sent == [url]


def test_any_other_failure_of_the_release_lookup_is_a_fetch_failure_and_not_called_a_refusal(installer_scripted):
    """Only a refusal by the host list is named as one; a server error, a dropped connection and a timeout are a fetch failure (R142): their own
    fixed sentence and the status code or the class name, never the text of the failure."""
    from src.llm import installer

    installer_scripted.routes[installer.GITHUB_LATEST_RELEASE] = (500, None)
    with pytest.raises(installer.InstallerFetchFailed) as caught:
        installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    assert not isinstance(caught.value, installer.InstallerRedirectRefused)
    assert isinstance(caught.value, installer.InstallerVerificationError), "the route that maps a verification failure maps this one too"
    assert caught.value.why == "HTTP 500" and str(caught.value) == installer.InstallerFetchFailed.LOOKUP.format(why="HTTP 500")

    def _dropped(request, **kwargs):
        raise requests.ConnectionError("the connection dropped")

    installer_scripted.send = _dropped
    with pytest.raises(installer.InstallerFetchFailed) as dropped:
        installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    assert not isinstance(dropped.value, installer.InstallerRedirectRefused | RedirectRefused) and dropped.value.why == "ConnectionError"

    def _slow(request, **kwargs):
        raise requests.Timeout("the answer was slow")

    installer_scripted.send = _slow
    with pytest.raises(installer.InstallerFetchFailed) as slow:
        installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    assert not isinstance(slow.value, installer.InstallerRedirectRefused | RedirectRefused) and slow.value.why == "Timeout"


RELEASE_DOWNLOAD_URL = "https://github.com/ollama/ollama/releases/download/v0.1.0/install.sh"
STORAGE_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/1/install.sh?sig=1"
SCRIPT = b"#!/bin/sh\necho installing\n"


def _release_json(download_url: str, script: bytes = SCRIPT) -> bytes:
    """The release answer the lookup returns: the one asset the installer looks for, with the digest GitHub attests for it."""
    import hashlib
    import json

    asset = {"name": "install.sh", "browser_download_url": download_url, "digest": "sha256:" + hashlib.sha256(script).hexdigest()}
    return json.dumps({"tag_name": "v0.1.0", "assets": [asset]}).encode()


def test_the_installer_download_refuses_a_redirect_off_its_hosts_and_follows_one_between_them(installer_scripted):
    from src.llm import installer

    wire = installer_scripted
    wire.routes[RELEASE_DOWNLOAD_URL] = (302, "https://exfil.example.invalid/steal?k=secret")
    with pytest.raises(installer.InstallerRedirectRefused) as caught:
        installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    assert wire.sent == [RELEASE_DOWNLOAD_URL], "the hop was refused before it was sent"
    assert str(caught.value) == installer.InstallerRedirectRefused.DOWNLOAD_MESSAGE
    assert isinstance(caught.value, installer.InstallerVerificationError), "the route that maps a verification failure maps this one too"
    # Every host GitHub has served a release asset from, and the release's own host again (a renamed repository), is followed:
    for storage in (STORAGE_URL, "https://objects.githubusercontent.com/x/install.sh?sig=1", RELEASE_DOWNLOAD_URL + "?renamed=1"):
        wire.sent.clear()
        wire.routes[RELEASE_DOWNLOAD_URL] = (302, storage)
        wire.bodies[storage] = SCRIPT
        assert installer._default_get_bytes(RELEASE_DOWNLOAD_URL) == SCRIPT
        assert wire.sent == [RELEASE_DOWNLOAD_URL, storage]
    assert {s.allowed_hosts for s in wire.sessions} == {installer.GITHUB_ASSET_HOSTS}, "the download's own sessions carry exactly the asset hosts"


@pytest.mark.parametrize(
    "hop",
    [
        "https://exfil.example.invalid/x",
        "https://raw.githubusercontent.com/ollama/ollama/main/install.sh",
        "https://githubusercontent.com/x",
        "https://api.github.com/repos/ollama/ollama/releases/latest",
        "https://release-assets.githubusercontent.com.exfil.example.invalid/x",
        "http://release-assets.githubusercontent.com/x",
        "https://exfil@release-assets.githubusercontent.com/x",
        "https://release-assets.githubusercontent.com:8443/x",
        "https://release-assets%2B.githubusercontent.com/x",
    ],
    ids=[
        "another host",
        "a sibling under the same family",
        "the bare domain of the family",
        "the lookup's own host",
        "a listed name as a prefix",
        "plain http on a listed host",
        "credentials on a listed host",
        "another port on a listed host",
        "a percent sign in the host (the host clause refuses it too)",
    ],
)
def test_each_kind_of_hop_off_the_download_list_is_refused_before_it_is_sent(installer_scripted, hop):
    """Through the installer's own getter, so that dropping or widening the list at the call site fails every case."""
    from src.llm import installer

    installer_scripted.routes[RELEASE_DOWNLOAD_URL] = (302, hop)
    with pytest.raises(installer.InstallerRedirectRefused):
        installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    assert installer_scripted.sent == [RELEASE_DOWNLOAD_URL]


@pytest.mark.parametrize(
    "named",
    [
        "https://exfil.example.invalid/install.sh?k=secret",
        "exfil.example.invalid/install.sh?k=secret",
        "//exfil.example.invalid/install.sh?k=secret",
        "https:///install.sh?k=secret",
        "https://exfil.example.invalid:99999/install.sh?k=secret",
    ],
    ids=["a foreign host", "no scheme", "scheme-relative", "no host", "a port out of range"],
)
def test_a_release_that_names_a_download_address_off_the_hosts_is_refused_before_it_is_sent(installer_scripted, caplog, named):
    """The download URL is a value the release response chooses, so the list also decides which host the response may send it to, and an
    address ``requests`` cannot even read (which it rejects with an error quoting the address) is a refusal too, not a 500 that echoes it."""
    import logging

    from fastapi import HTTPException

    from src.api.llm import llm_install_prepare
    from src.llm import installer

    installer_scripted.bodies[installer.GITHUB_LATEST_RELEASE] = _release_json(named)
    with pytest.raises(installer.InstallerRedirectRefused) as caught:
        installer.resolve_and_verify(installer._default_get_json, installer._default_get_bytes)
    assert installer_scripted.sent == [installer.GITHUB_LATEST_RELEASE], "the lookup was sent and the download was not"
    assert str(caught.value) == installer.InstallerRedirectRefused.DOWNLOAD_MESSAGE
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HTTPException) as routed:
        llm_install_prepare()
    assert routed.value.status_code == 502 and routed.value.detail == installer.InstallerRedirectRefused.DOWNLOAD_MESSAGE
    assert "exfil" not in caplog.text and "secret" not in caplog.text, "the address the release named is in no log line"


@pytest.mark.parametrize("named", [123, ["https://github.com/x"], {"url": "https://github.com/x"}], ids=["a number", "a list", "a mapping"])
def test_a_release_whose_download_address_is_not_text_is_a_missing_address(named):
    """``requests`` would call ``str()`` on it and quote it in an error; the release reader says, in fixed words, that it lists none."""
    from src.llm import installer

    release = {"tag_name": "v1", "assets": [{"name": "install.sh", "browser_download_url": named, "digest": "sha256:" + "0" * 64}]}
    with pytest.raises(installer.InstallerVerificationError, match="lists no download URL") as caught:
        installer._attested_installer(release)
    assert not isinstance(caught.value, installer.InstallerRedirectRefused) and "github.com" not in str(caught.value)


def test_the_whole_install_check_runs_through_the_real_redirect_machinery(installer_scripted):
    """Lookup, redirect from the release host to the storage host, and the digest check, with nothing replaced but the wire."""
    from src.llm import installer

    wire = installer_scripted
    wire.bodies[installer.GITHUB_LATEST_RELEASE] = _release_json(RELEASE_DOWNLOAD_URL)
    wire.routes[RELEASE_DOWNLOAD_URL] = (302, STORAGE_URL)
    wire.bodies[STORAGE_URL] = SCRIPT
    data, version, _sha, url = installer.resolve_and_verify(installer._default_get_json, installer._default_get_bytes)
    assert (data, version, url) == (SCRIPT, "v0.1.0", RELEASE_DOWNLOAD_URL)
    assert wire.sent == [installer.GITHUB_LATEST_RELEASE, RELEASE_DOWNLOAD_URL, STORAGE_URL]
    # Bytes that are not the attested ones are still a checksum failure, not a refusal:
    wire.bodies[STORAGE_URL] = SCRIPT + b"# changed\n"
    with pytest.raises(installer.InstallerVerificationError) as caught:
        installer.resolve_and_verify(installer._default_get_json, installer._default_get_bytes)
    assert not isinstance(caught.value, installer.InstallerRedirectRefused) and "checksum mismatch" in str(caught.value)


def test_any_other_failure_of_the_download_is_a_fetch_failure_and_not_called_a_refusal(installer_scripted):
    """A missing file, a dropped connection and a timeout are a fetch failure with the download's own sentence, and not a refusal."""
    from src.llm import installer

    installer_scripted.routes[RELEASE_DOWNLOAD_URL] = (404, None)
    with pytest.raises(installer.InstallerFetchFailed) as caught:
        installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    assert not isinstance(caught.value, installer.InstallerRedirectRefused)
    assert caught.value.why == "HTTP 404" and str(caught.value) == installer.InstallerFetchFailed.DOWNLOAD.format(why="HTTP 404")

    def _dropped(request, **kwargs):
        raise requests.ConnectionError("the connection dropped")

    installer_scripted.send = _dropped
    with pytest.raises(installer.InstallerFetchFailed) as dropped:
        installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    assert not isinstance(dropped.value, installer.InstallerRedirectRefused | RedirectRefused) and dropped.value.why == "ConnectionError"

    def _slow(request, **kwargs):
        raise requests.Timeout("the answer was slow")

    installer_scripted.send = _slow
    with pytest.raises(installer.InstallerFetchFailed) as slow:
        installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    assert not isinstance(slow.value, installer.InstallerRedirectRefused | RedirectRefused) and slow.value.why == "Timeout"


@pytest.mark.parametrize("stage", ["lookup", "download"])
@pytest.mark.parametrize(
    "refusal_text",
    [None, "refused https://exfil.example.invalid/steal?k=secret"],
    ids=["the real refusal", "a refusal whose own text names the target"],
)
def test_a_refused_installer_redirect_reaches_the_user_and_the_log_without_the_host_it_pointed_at(installer_scripted, monkeypatch, caplog, refusal_text, stage):
    """The 502 detail, the log and the exception chain say what did not happen, never where the request was aimed, at either stage.

    The second case is what makes this a test of THIS code and not of ``refuse_unlisted_host``'s wording: a refusal that does carry the
    target must still not reach a response, a log record or a traceback."""
    import logging
    import traceback

    from fastapi import HTTPException

    from src.api.llm import llm_install_prepare
    from src.llm import installer

    download = stage == "download"
    if download:
        installer_scripted.bodies[installer.GITHUB_LATEST_RELEASE] = _release_json(RELEASE_DOWNLOAD_URL)
    if refusal_text is not None:
        real = fetcher_mod.refuse_unlisted_host

        def _names_the_target(url, allowed):
            if download and url == installer.GITHUB_LATEST_RELEASE:
                return real(url, allowed)  # the lookup passes; the download is what is refused
            raise RedirectRefused(refusal_text)

        monkeypatch.setattr(fetcher_mod, "refuse_unlisted_host", _names_the_target)
    else:
        refused_url = RELEASE_DOWNLOAD_URL if download else installer.GITHUB_LATEST_RELEASE
        installer_scripted.routes[refused_url] = (302, "https://exfil.example.invalid/steal?k=secret")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HTTPException) as caught:
        llm_install_prepare()
    assert caught.value.status_code == 502
    assert caught.value.detail == (installer.InstallerRedirectRefused.DOWNLOAD_MESSAGE if download else installer.InstallerRedirectRefused.MESSAGE)
    cause = caught.value.__cause__
    assert isinstance(cause, installer.InstallerRedirectRefused)
    assert cause.__cause__ is None and cause.__context__ is None, "no chain behind it: a traceback chain is a sink"
    seen = [caught.value.detail, caplog.text, "".join(traceback.format_exception(caught.value))]
    seen += [str(r.exc_info) + str(r.exc_text) + str(getattr(r, "scrubbed_traceback", "")) for r in caplog.records]  # the attribute errorlog writes out
    for text in seen:
        assert "exfil" not in text and "secret" not in text and "invalid" not in text
    ours = [r for r in caplog.records if r.name == "src.llm.installer"]
    assert [r.levelno for r in ours] == [logging.WARNING] and ours[0].getMessage().endswith("(RedirectRefused)"), "the class name is logged, once"
    assert ("download" in ours[0].getMessage()) is download, "the line names the stage that was refused"
    assert ours[0].exc_info is None


SIG = "PLANTEDSIG0123456789"
#: The storage address the release redirects to, as GitHub signs it: the signature is in the query.
SIGNED_STORAGE_URL = f"https://release-assets.githubusercontent.com/github-production-release-asset/1/install.sh?sig={SIG}&se=2026-10-16T12%3A00%3A00Z&sp=r"
SIGNED_LOOKUP_URL = f"https://api.github.com/repositories/1/releases/latest?sig={SIG}"


def _failing_hop(wire, installer, stage):
    """Aim the stage's request at a second address (a followed redirect) carrying a planted signature, and return that address."""
    if stage == "download":
        wire.bodies[installer.GITHUB_LATEST_RELEASE] = _release_json(RELEASE_DOWNLOAD_URL)
        wire.routes[RELEASE_DOWNLOAD_URL] = (302, SIGNED_STORAGE_URL)
        return SIGNED_STORAGE_URL
    wire.routes[installer.GITHUB_LATEST_RELEASE] = (301, SIGNED_LOOKUP_URL)
    return SIGNED_LOOKUP_URL


def _fail_at(wire, failing_url, make):
    """Make the wire raise ``make(url)`` for the failing hop only, so the redirect before it is followed first."""
    real = wire.send

    def _send(request, **kwargs):
        if request.url == failing_url:
            raise make(request.url)
        return real(request, **kwargs)

    wire.send = _send


@pytest.mark.parametrize("stage", ["lookup", "download"])
@pytest.mark.parametrize(
    ("kind", "why"),
    [
        ("404", "HTTP 404"),
        ("503", "HTTP 503"),
        ("connection", "ConnectionError"),
        ("timeout", "Timeout"),
        ("truncated", "ChunkedEncodingError"),
        ("bad location", "ValueError"),
    ],
)
def test_a_failed_installer_fetch_after_a_followed_redirect_says_only_the_status_or_the_class(installer_scripted, caplog, stage, kind, why):
    """R142: the signed address a failure quotes reaches neither the 502 detail, nor the log, nor a traceback chain, at either stage.

    The planted signature rides the SECOND address (the redirect target), because that is where a storage URL lives; every failure text
    below quotes it, so a stage that put ``str(exc)`` anywhere would show it."""
    import logging
    import traceback

    from fastapi import HTTPException

    from src.api.llm import llm_install_prepare
    from src.llm import installer

    download = stage == "download"
    hop = _failing_hop(installer_scripted, installer, stage)
    if kind in ("404", "503"):
        installer_scripted.routes[hop] = (int(kind), None)
    elif kind == "connection":
        _fail_at(installer_scripted, hop, lambda url: requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}"))
    elif kind == "timeout":
        _fail_at(installer_scripted, hop, lambda url: requests.Timeout(f"Read timed out fetching {url}"))
    elif kind == "truncated":
        _fail_at(installer_scripted, hop, lambda url: requests.exceptions.ChunkedEncodingError(f"Connection broken fetching {url}"))
    else:  # a Location that requests cannot read: its failure quotes the address it could not parse
        first = RELEASE_DOWNLOAD_URL if download else installer.GITHUB_LATEST_RELEASE
        installer_scripted.routes[first] = (302, f"https://[::1/x?sig={SIG}")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HTTPException) as caught:
        llm_install_prepare()
    assert caught.value.status_code == 502
    sentence = installer.InstallerFetchFailed.DOWNLOAD if download else installer.InstallerFetchFailed.LOOKUP
    assert caught.value.detail == sentence.format(why=why)
    cause = caught.value.__cause__
    assert isinstance(cause, installer.InstallerFetchFailed) and not isinstance(cause, installer.InstallerRedirectRefused)
    assert cause.__cause__ is None and cause.__context__ is None, "no chain behind it: a traceback chain is a sink"
    seen = [caught.value.detail, caplog.text, "".join(traceback.format_exception(caught.value)), repr(cause)]
    seen += [str(r.exc_info) + str(r.exc_text) + str(getattr(r, "scrubbed_traceback", "")) for r in caplog.records]  # the attribute errorlog writes out
    for text in seen:
        assert SIG not in text and "release-assets" not in text and "sig=" not in text and "api.github.com/repositories" not in text
    ours = [r for r in caplog.records if r.name == "src.llm.installer"]
    assert [r.levelno for r in ours] == [logging.WARNING] and ours[0].getMessage().endswith(f"({why})"), "the status or class is logged, once"
    assert ("download" in ours[0].getMessage()) is download, "the line names the stage that failed"
    assert ours[0].exc_info is None


def test_a_lookup_answer_that_is_not_json_is_a_fetch_failure_by_class_name(installer_scripted, caplog):
    import logging

    from src.llm import installer

    installer_scripted.bodies[installer.GITHUB_LATEST_RELEASE] = b"<html>sign in to continue</html>"
    caplog.set_level(logging.DEBUG)
    with pytest.raises(installer.InstallerFetchFailed) as caught:
        installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    assert caught.value.why == "JSONDecodeError" and "sign in" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "sign in" not in caplog.text


def test_failure_words_are_a_status_or_a_class_name_and_nothing_else():
    from src.safety.fetcher import failure_words

    def _http(status):
        err = requests.HTTPError("404 Client Error: Not Found for url: https://x.example/?sig=SECRET")
        err.response = SimpleNamespace(status_code=status)
        return err

    assert failure_words(_http(404)) == "HTTP 404"
    for odd in (None, True, "404", 99, 600, 12.5):  # not a status: the class name, never the text
        assert failure_words(_http(odd)) == "HTTPError"
    assert failure_words(requests.HTTPError("no response attached: https://x.example/?sig=SECRET")) == "HTTPError"
    assert failure_words(requests.ConnectionError("https://x.example/?sig=SECRET")) == "ConnectionError"
    assert failure_words(ValueError("https://x.example/?sig=SECRET")) == "ValueError"


def test_each_fetcher_keeps_its_own_timeout_and_asks_for_the_install_window(installer_scripted):
    """The shared helper's other arguments: the lookup waits 30 s and the download 120 s, and both ride the AI-install egress window.

    With the kill switch engaged (airplane mode) and the window open, both succeed: a session built without the purpose would be refused
    by the switch. With the switch engaged and no window, both are refused BY THE SWITCH, which is not a redirect refusal."""
    from src.ingest import activate_kill_switch
    from src.ingest.egress_window import PURPOSE_AI_INSTALL, close_window, open_window
    from src.llm import installer
    from src.safety.fetcher import NetworkBlocked

    wire = installer_scripted
    assert installer._default_get_json(installer.GITHUB_LATEST_RELEASE) == {}
    assert installer._default_get_bytes(RELEASE_DOWNLOAD_URL) == b"{}"
    assert wire.timeouts == [30, 120]
    activate_kill_switch()
    try:
        for get, url in ((installer._default_get_json, installer.GITHUB_LATEST_RELEASE), (installer._default_get_bytes, RELEASE_DOWNLOAD_URL)):
            with pytest.raises(NetworkBlocked) as blocked:
                get(url)
            assert not isinstance(blocked.value, installer.InstallerRedirectRefused | RedirectRefused)
        open_window(PURPOSE_AI_INSTALL)
        wire.sent.clear()
        assert installer._default_get_json(installer.GITHUB_LATEST_RELEASE) == {}
        assert installer._default_get_bytes(RELEASE_DOWNLOAD_URL) == b"{}"
        assert wire.sent == [installer.GITHUB_LATEST_RELEASE, RELEASE_DOWNLOAD_URL]
    finally:
        close_window()


def test_each_fetch_of_the_install_asks_for_its_own_stream_isolation(installer_scripted, monkeypatch):
    """Protected mode: the lookup and the download each ride their own proxy stream (the isolation token is the address fetched), so one
    install is not one linkable circuit."""
    from src.llm import installer

    plain = "socks5h://127.0.0.1:9150"
    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="protected", http_proxy=plain))
    installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    installer._default_get_bytes(RELEASE_DOWNLOAD_URL)
    proxies = [s.transport_proxy for s in installer_scripted.sessions]
    assert len(proxies) == 2 and None not in proxies and plain not in proxies, "each session carries a proxy with its isolation credential layered on"
    assert proxies[0] != proxies[1], "the two fetches do not share a stream"


def test_a_missing_transport_is_not_called_a_redirect_refusal(installer_scripted, monkeypatch):
    """Protected mode with no usable proxy refuses every request; that is a connection failure of its own, not a refused redirect."""
    from src.llm import installer
    from src.safety.fetcher import TransportUnavailable

    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="protected"))
    for get, url in ((installer._default_get_json, installer.GITHUB_LATEST_RELEASE), (installer._default_get_bytes, RELEASE_DOWNLOAD_URL)):
        with pytest.raises(TransportUnavailable) as caught:
            get(url)
        assert not isinstance(caught.value, installer.InstallerRedirectRefused | RedirectRefused)
    assert installer_scripted.sent == []


def test_the_download_list_is_exactly_the_github_hosts_the_consent_popup_discloses():
    """The hosts a person is told about at the consent step are the hosts the install's own requests may reach: the GitHub hosts of the
    popup's Local AI lane are the lookup's host plus the download's, no more and no fewer (``ollama.com``, ``huggingface.co`` and
    ``pypi.org`` on that lane are reached by a spawned process, not by these sessions)."""
    import json
    from urllib.parse import urlsplit

    from src.llm import installer
    from tests.js_source_helper import array_literal, read_static

    lane = next(x for x in json.loads(array_literal(read_static("net-hosts.js"), "OO_NET_LANES")) if x.get("id") == "ai")
    github = {h for h in lane["hosts"] if h == "github.com" or h.endswith((".github.com", ".githubusercontent.com"))}
    assert github == set(installer.GITHUB_API_HOSTS) | set(installer.GITHUB_ASSET_HOSTS)
    assert urlsplit(RELEASE_DOWNLOAD_URL).hostname in installer.GITHUB_ASSET_HOSTS, "the host of the address the release names is listed"
    assert fetcher_mod._checked_hosts(installer.GITHUB_ASSET_HOSTS) == installer.GITHUB_ASSET_HOSTS
    assert not any(h.startswith(".") for h in installer.GITHUB_ASSET_HOSTS), "exact hosts, never a family"
    for host in installer.GITHUB_ASSET_HOSTS:
        refuse_unlisted_host(f"https://{host}/x", installer.GITHUB_ASSET_HOSTS)
    # ... and the neighbours are refused, so a list that grew by a sibling or a family shows up here:
    for url in (
        "https://api.github.com/repos/ollama/ollama/releases/latest",
        "https://codeload.github.com/ollama/ollama/zip/refs/heads/main",
        "https://raw.githubusercontent.com/ollama/ollama/main/install.sh",
        "https://avatars.githubusercontent.com/u/1",
        "https://githubusercontent.com/x",
        "https://ollama.com/install.sh",
        "https://release-assets.githubusercontent.co%6D/x",  # a listed name once decoded: refused for the percent sign as well as for the host
    ):
        _refused(lambda url=url: refuse_unlisted_host(url, installer.GITHUB_ASSET_HOSTS))
    # The other direction: the lookup's list must not accept the download's hosts.
    for host in installer.GITHUB_ASSET_HOSTS:
        _refused(lambda host=host: refuse_unlisted_host(f"https://{host}/x", installer.GITHUB_API_HOSTS))


def test_every_endpoint_list_is_exactly_the_host_of_the_endpoint_it_serves():
    """The lists are the hosts of the URLs the code builds: equal to them, not merely accepting them, so a list widened by one host
    (a sibling, a CDN, a family) fails here, and so does an endpoint that moves host without its list."""
    from urllib.parse import urlsplit

    from src.analytics import wikidata_rings
    from src.catalog import wikidata, wikidata_enrich
    from src.llm import installer
    from src.monitoring import release_run

    pairs = (
        (installer.GITHUB_API_HOSTS, installer.GITHUB_LATEST_RELEASE),
        (wikidata_rings.API_HOSTS, wikidata_rings.API_ENDPOINT),
        (wikidata_enrich.API_HOSTS, wikidata_enrich._API),
        (wikidata.WDQS_HOSTS, wikidata.WDQS_ENDPOINT),
        (release_run.HF_API_HOSTS, release_run.HF_MODEL_API_URL.format(model="x/y")),
    )
    for hosts, endpoint in pairs:
        assert hosts == (urlsplit(endpoint).hostname,)
        refuse_unlisted_host(endpoint, hosts)
        assert fetcher_mod._checked_hosts(hosts) == hosts
    # The QID label resolver (``src/api/source_management.py``) fetches ``wikidata_rings``'s URLs through the source-typing getter, which
    # carries ``wikidata_enrich``'s list; the two modules state the one host, and this is what keeps them in step.
    assert wikidata_rings.API_HOSTS == wikidata_enrich.API_HOSTS, "the source-typing getter also serves the QID label resolver's URLs"
    # ... and a neighbour of each is refused, so a list that grew into a family would show up here too:
    for url, hosts in (
        ("https://query.wikidata.org/sparql", wikidata_rings.API_HOSTS),
        ("https://www.wikidata.org/w/api.php", wikidata.WDQS_HOSTS),
        ("https://cdn-lfs.huggingface.co/x", release_run.HF_API_HOSTS),
        ("https://github.com/ollama/ollama/releases/download/v1/install.sh", installer.GITHUB_API_HOSTS),
        ("https://release-assets.githubusercontent.com/x", installer.GITHUB_API_HOSTS),
    ):
        _refused(lambda url=url, hosts=hosts: refuse_unlisted_host(url, hosts))


# --------------------------------------------------------------------------- #
# What still has no list, so that a new session without one is a decision and not an accident
# --------------------------------------------------------------------------- #
_BULK = "bulk downloads from request-chosen mirrors that redirect between CDNs by design"
#: Every module that builds a guarded session WITHOUT a host list: ``{path: (calls, why it has none)}``. Zero slack: a call that gains a
#: list leaves this table, and a new call joins it with its reason. What is left here are URLs chosen by the request or the catalogue; a
#: session for a fixed endpoint, or for the few hosts a fixed service serves from, names its list instead (the Ollama installer's two do).
UNLISTED_SESSIONS = {
    "src/geo/osm_downloads.py": (2, _BULK),
    "src/ingest/segmented_download.py": (2, _BULK),
    "src/wiki/dumps.py": (2, _BULK),
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
