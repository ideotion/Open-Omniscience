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
from typing import NamedTuple
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


def test_the_wiki_clients_list_is_exactly_its_three_hosts_and_no_other_wikimedia_host(transparent):
    """R143: the Action API's ``*.wikipedia.org``, the pageviews ``wikimedia.org`` and ``stream.wikimedia.org``, as the consent popup's
    Wikipedia lane names them for this session. Every other host under ``wikimedia.org`` is refused, including as the target of a
    redirect. A list restored to the family (``.wikimedia.org``) fails here and in the popup pin; a list that gains a host the popup DOES name
    (``dumps.wikimedia.org``) fails only here, which is why this test exists beside the pin."""
    from src.wiki.client import WIKI_SESSION_HOSTS

    assert set(WIKI_SESSION_HOSTS) == {".wikipedia.org", "wikimedia.org", "stream.wikimedia.org"}
    s, wire = _session({"https://wikimedia.org/api/rest_v1/x": (302, "https://api.wikimedia.org/core/v1/x")}, hosts=WIKI_SESSION_HOSTS)
    with pytest.raises(RedirectRefused):
        s.get("https://wikimedia.org/api/rest_v1/x")
    assert wire.sent == ["https://wikimedia.org/api/rest_v1/x"], "the hop to api.wikimedia.org was refused before it was sent"
    for elsewhere in (
        "https://api.wikimedia.org/core/v1/x",
        "https://upload.wikimedia.org/x",
        "https://meta.wikimedia.org/w/api.php",
        "https://commons.wikimedia.org/w/api.php",
        "https://ores.wikimedia.org/v3/scores",  # the scores have their own client and their own list
        "https://dumps.wikimedia.org/x",  # the dumps have their own session
        "https://stream.wikimedia.org.evil.test/v2/stream",
        "https://www.wikidata.org/w/api.php",
    ):
        _refused(lambda url=elsewhere: refuse_unlisted_host(url, WIKI_SESSION_HOSTS))


def test_the_ores_list_is_exactly_the_host_of_its_endpoint(transparent):
    """R143: ``ores.wikimedia.org`` and nothing else. A replacement endpoint (say LiftWing on ``api.wikimedia.org``) is refused until the
    popup lane and this list both name it. A list restored to the family fails here and in the popup pin; a list that gains another
    ``wikimedia.org`` host the popup names for a different client (say the bare domain) fails only here."""
    from urllib.parse import urlsplit

    from src.wiki.ores import ORES_ENDPOINT, ORES_HOSTS

    assert set(ORES_HOSTS) == {urlsplit(ORES_ENDPOINT).hostname}
    s, wire = _session({f"{ORES_ENDPOINT}/enwiki/": (302, "https://api.wikimedia.org/service/lw/inference/v1/models/x:predict")}, hosts=ORES_HOSTS)
    with pytest.raises(RedirectRefused):
        s.get(f"{ORES_ENDPOINT}/enwiki/")
    assert wire.sent == [f"{ORES_ENDPOINT}/enwiki/"]
    for elsewhere in (
        "https://api.wikimedia.org/service/lw/inference/v1/models/x:predict",
        "https://stream.wikimedia.org/v2/stream/recentchange",
        "https://wikimedia.org/api/rest_v1/x",
        "https://ores.wikimedia.org.evil.test/v3/scores",
    ):
        _refused(lambda url=elsewhere: refuse_unlisted_host(url, ORES_HOSTS))


def test_the_ores_clients_session_carries_its_list(transparent):
    from src.wiki.ores import ORES_ENDPOINT, ORES_HOSTS, OresClient

    assert OresClient().session.allowed_hosts == ORES_HOSTS
    refuse_unlisted_host(f"{ORES_ENDPOINT}/enwiki/", ORES_HOSTS)


def test_an_ores_redirect_off_its_host_is_named_as_our_refusal_and_not_as_a_network_fault(transparent):
    """R143 makes a redirect to another Wikimedia host (Lift Wing, say) a refusal by the list. The scoring client names it ``refused_redirect``,
    with the refusal's fixed sentence as the detail, instead of the ``transport_error`` a dropped packet gets: Q717's probe reads that token."""
    from src.wiki.ores import ORES_ENDPOINT, ORES_HOSTS, OUTCOMES, OresClient

    asked = f"{ORES_ENDPOINT}/enwiki/?models=damaging%7Cgoodfaith&revids=123"
    s, wire = _session({asked: (302, "https://api.wikimedia.org/service/lw/inference/v1/models/x:predict")}, hosts=ORES_HOSTS)
    client = OresClient(session=s)
    assert client.score("en", [123]) == {}
    assert client.last_outcome == "refused_redirect" and client.last_outcome in OUTCOMES
    assert client.last_detail == "the host is not one this client talks to", "the refusal's own fixed sentence: not the exception's text, not its class name, no host"
    assert wire.sent == [asked], "the hop was refused before it was sent"


def test_a_dropped_ores_connection_is_still_a_transport_error(transparent):
    from src.wiki.ores import ORES_HOSTS, OresClient

    s, wire = _session(hosts=ORES_HOSTS)
    real = wire.send

    def _send(request, **kwargs):
        raise requests.ConnectionError("dropped")

    wire.send = _send
    client = OresClient(session=s)
    assert client.score("en", [123]) == {}
    assert client.last_outcome == "transport_error" and client.last_detail == "ConnectionError"
    wire.send = real


def test_the_duckduckgo_list_is_exactly_its_endpoint_host(transparent):
    """R143: ``html.duckduckgo.com`` and nothing else, as the consent popup's topic-discovery lane says. The bare domain and every other host
    under it are refused, including as the target of a redirect. A list restored to the family fails here and in the popup pin."""
    from urllib.parse import urlsplit

    from src.services.duckduckgo import DuckDuckGoSearch

    assert set(DuckDuckGoSearch.ALLOWED_HOSTS) == {urlsplit(DuckDuckGoSearch.BASE_URL).hostname}
    s, wire = _session({DuckDuckGoSearch.BASE_URL: (302, "https://duckduckgo.com/html/")}, hosts=DuckDuckGoSearch.ALLOWED_HOSTS)
    with pytest.raises(RedirectRefused):
        s.post(DuckDuckGoSearch.BASE_URL, data={"q": "x"})
    assert wire.sent == [DuckDuckGoSearch.BASE_URL], "the hop to the bare domain was refused before it was sent"
    for elsewhere in (
        "https://duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
        "https://links.duckduckgo.com/d.js",
        "https://duckduckgo.com.evil.test/",
        "https://evilduckduckgo.com/",
        "https://html.duckduckgo.com.evil.test/",
    ):
        _refused(lambda url=elsewhere: refuse_unlisted_host(url, DuckDuckGoSearch.ALLOWED_HOSTS))


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


_GOOD_ASSET = {"name": "install.sh", "browser_download_url": "https://github.com/x", "digest": "sha256:" + "0" * 64}


@pytest.mark.parametrize(
    "release",
    [
        {"assets": [1]},
        {"assets": ["install.sh"]},
        {"assets": [None]},
        {"assets": {"name": "install.sh"}},
        {"assets": "install.sh"},
        {"tag_name": 5, "assets": []},
        {"tag_name": ["v1"], "assets": [_GOOD_ASSET]},
        {"tag_name": "v1", "assets": [{**_GOOD_ASSET, "digest": 5}]},
        {"tag_name": "v1", "assets": [{**_GOOD_ASSET, "digest": ["sha256:" + "0" * 64]}]},
        {"tag_name": "v1", "assets": [{"name": "other"}, 7]},
    ],
    ids=["number", "string", "null", "mapping", "text", "tag number", "tag list", "digest number", "digest list", "a later asset"],
)
def test_a_release_whose_members_are_not_the_types_the_lookup_reads_is_a_named_fetch_failure(release):
    """JSON, an object, but ``assets`` that is not a list, an asset that is not an object, a ``tag_name`` or ``digest`` that is not text: the
    reader used to end in an unhandled ``AttributeError`` (a 500 naming a type). It is ``InstallerFetchFailed`` with the class ``TypeError``,
    like a body that is not an object, and has neither cause nor context."""
    from src.llm import installer

    with pytest.raises(installer.InstallerFetchFailed) as caught:
        installer.resolve_and_verify(lambda url: release, lambda url: b"")
    assert caught.value.why == "TypeError" and caught.value.__cause__ is None and caught.value.__context__ is None
    assert str(caught.value) == installer.InstallerFetchFailed.LOOKUP.format(why="TypeError")


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
        ("loop", "TooManyRedirects"),
    ],
)
def test_a_failed_installer_fetch_after_a_followed_redirect_says_only_the_status_or_the_class(installer_scripted, caplog, stage, kind, why):
    """R142: the signed address a failure quotes reaches neither the 502 detail, nor the log, nor a traceback chain, at either stage.

    The planted signature rides the SECOND address (the redirect target), because that is where a storage URL lives. The HTTP statuses, the
    connection error, the timeout and the truncated body quote it (the last two are planted: the real library's texts for them name only a
    host or nothing), so a stage that put ``str(exc)`` anywhere would show it. The bad ``Location`` and the loop pin the class named and the
    absence of any chain; their real texts do not quote the address, and a mutant that read ``.response.status_code`` off every exception that
    carries a response would name a loop ``HTTP 301``."""
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
    elif kind == "bad location":  # a Location that requests cannot read; its real error ("Invalid IPv6 URL") does not quote it
        first = RELEASE_DOWNLOAD_URL if download else installer.GITHUB_LATEST_RELEASE
        installer_scripted.routes[first] = (302, f"https://[::1/x?sig={SIG}")
    else:  # a redirect to itself, on a listed host: requests gives up after its limit
        first = RELEASE_DOWNLOAD_URL if download else installer.GITHUB_LATEST_RELEASE
        installer_scripted.routes[first] = (301, first)
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


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"[]", "TypeError"),
        (b'"a string"', "TypeError"),
        (b"3", "TypeError"),
        (b"null", "TypeError"),
        (b"[" * 200000 + b"]" * 200000, "RecursionError"),
    ],
    ids=["list", "string", "number", "null", "nested"],
)
def test_a_lookup_answer_that_is_json_but_not_an_object_is_a_fetch_failure_and_not_an_unhandled_error(installer_scripted, caplog, body, why):
    """The lookup reads an object; any other JSON used to reach ``.get`` and end as an unhandled 500 quoting the Python error."""
    import logging

    from src.llm import installer

    installer_scripted.bodies[installer.GITHUB_LATEST_RELEASE] = body
    caplog.set_level(logging.DEBUG)
    with pytest.raises(installer.InstallerFetchFailed) as caught:
        installer._default_get_json(installer.GITHUB_LATEST_RELEASE)
    assert caught.value.why == why
    assert caught.value.__cause__ is None and caught.value.__context__ is None


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


#: Each fixed-endpoint host list and the consent popup lane(s) that disclose its reach: ``(module, constant, lane ids)``. A list may be
#: narrower than its lane (the lane also covers other code), never wider: the popup is what the person consented to. Complete by
#: construction: ``test_every_host_list_a_session_is_built_with_is_pinned_to_a_popup_lane`` walks every session built under ``src/`` and fails
#: on a list that is not a row here, so a new list joins this table or the suite fails.
POPUP_LANE_LISTS = [
    ("src.wiki.client", "WIKI_SESSION_HOSTS", ("wikipedia",)),
    ("src.wiki.ores", "ORES_HOSTS", ("wikipedia",)),
    ("src.catalog.wikidata", "WDQS_HOSTS", ("discovery",)),
    ("src.catalog.wikidata_apply", "API_HOSTS", ("discovery",)),
    ("src.catalog.wikidata_enrich", "API_HOSTS", ("discovery",)),
    ("src.analytics.wikidata_rings", "API_HOSTS", ("keyword-rings",)),
    ("src.analytics.ring_loader", "API_HOSTS", ("keyword-rings",)),
    ("src.entities.items", "API_HOSTS", ("entity-items",)),
    ("src.entities.gazetteer_build", "API_HOSTS", ("entity-items",)),
    ("src.monitoring.release_run", "HF_API_HOSTS", ("ai",)),
    ("src.services.duckduckgo", "DuckDuckGoSearch.ALLOWED_HOSTS", ("topic-discovery",)),
    ("src.llm.installer", "GITHUB_API_HOSTS", ("ai",)),
    ("src.llm.installer", "GITHUB_ASSET_HOSTS", ("ai",)),
]

#: A session built with a list that arrives as a PARAMETER cannot be resolved to a name; each such place says why it is still pinned. Keyed by
#: ``(path, enclosing function, name)``, not by the name alone: a name-based allowance would accept any session built with a variable of that
#: name anywhere in the file, so the function is part of the key and the test below checks the function really takes that parameter.
PASSED_ON_HOST_LISTS = {
    ("src/llm/installer.py", "_get_within", "hosts"): "_get_within takes its list from its two callers, which pass GITHUB_API_HOSTS and GITHUB_ASSET_HOSTS (the rows above)",
}


def _popup_lane_hosts(lane_ids) -> set[str]:
    import json

    from tests.js_source_helper import array_literal, read_static

    lanes = {x["id"]: x for x in json.loads(array_literal(read_static("net-hosts.js"), "OO_NET_LANES"))}
    return {host for lane_id in lane_ids for host in lanes[lane_id]["hosts"]}


@pytest.mark.parametrize(("module", "name", "lane_ids"), POPUP_LANE_LISTS, ids=[f"{m}.{n}" for m, n, _ in POPUP_LANE_LISTS])
def test_no_host_list_reaches_further_than_the_consent_popup_tells_the_person(module, name, lane_ids):
    """The popup names the hosts a lane may reach (``src/static/net-hosts.js``); the code's list for that lane must be inside it. An exact
    entry is a host the popup names; a leading-dot entry (``.wikipedia.org``) is a family the popup names with a star (``*.wikipedia.org``).
    A list wider than its lane is the gap invariant #14e closes for the action itself: the person agreed to less than the request may do."""
    import importlib

    owner = importlib.import_module(module)
    hosts = owner
    for part in name.split("."):
        hosts = getattr(hosts, part)
    assert hosts, "an empty list pins nothing (and a session cannot be built with one)"
    popup = _popup_lane_hosts(lane_ids)
    wider = sorted(entry for entry in hosts if (f"*{entry}" if entry.startswith(".") else entry) not in popup)
    assert not wider, f"{module}.{name} may reach {wider}, which the popup lane(s) {list(lane_ids)} do not name"


class _Site(NamedTuple):
    """One session-factory call that passes ``allowed_hosts=`` something other than a literal ``None``."""

    #: The name the list is written as, resolvable to a row of ``POPUP_LANE_LISTS``: a plain name, or ``Class.NAME`` for ``cls.NAME`` or
    #: ``self.NAME`` inside that class. ``''`` for everything else (an inline tuple, a call, a subscript, ``module.NAME``, ``other.NAME``).
    ident: str
    #: ``(module, name)`` when that name was imported with ``from module import name``.
    imported: tuple[str, str] | None
    #: The function the call is in (``''`` at module level).
    function: str
    #: True when the name is NOT bound exactly once in the place the pin reads it: a plain name must have ONE binding in the whole module,
    #: made at module level (an assignment or an import); ``Class.NAME`` must be bound once in the body of a class bound once at module
    #: level. A parameter, a second assignment anywhere (a function with ``global``, a loop variable, a comprehension, a class body), a star
    #: import, or no binding at all makes it something other than the constant the pin reads.
    rebound: bool
    #: The source of the value, for the failure message.
    text: str


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _bindings(tree: ast.AST) -> tuple[dict[str, list[bool]], bool]:
    """Every place a name is bound anywhere in the module, as ``name -> [made at module level, ...]``, and whether a star import is there
    (it binds names nobody can list). Counts what rebinding costs: an assignment target (also augmented, loop, ``with``, walrus,
    comprehension), a parameter, ``def``/``class``/``import``, ``except ... as``, a ``match`` capture, ``del``; a ``global`` rebind in
    another function is an assignment inside it, so it is counted by being a second binding."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def at_module_level(node: ast.AST) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, _SCOPES):
                return False
        return True

    found: dict[str, list[bool]] = {}
    star = False

    def bind(name: str | None, node: ast.AST) -> None:
        if name:
            found.setdefault(name, []).append(at_module_level(node))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bind(node.id, node)
        elif isinstance(node, ast.arg):
            bind(node.arg, node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, node)
        elif isinstance(node, ast.alias):
            if node.name == "*":
                star = True
            else:
                bind(node.asname or node.name.split(".")[0], node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            bind(node.name, node)
        elif isinstance(node, ast.MatchMapping):
            bind(node.rest, node)
    return found, star


def _class_binds_once(owner: ast.ClassDef, name: str) -> bool:
    """``name`` is bound exactly once in the BODY of ``owner`` (not in its methods): the class constant the pin reads."""
    count = 0
    stack: list[ast.AST] = list(owner.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load) and node.id == name:
            count += 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            count += 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue  # a method's own names are its own
        stack.extend(ast.iter_child_nodes(node))
    return count == 1


def _host_list_sites(source: str, filename: str) -> list[_Site]:
    """Every session-factory call in ``source`` that passes ``allowed_hosts=`` something other than a literal ``None``."""
    tree = ast.parse(source, filename=filename)
    aliases: dict[str, str] = {}
    imported: dict[str, tuple[str, str]] = {}
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = (node.module, alias.name)
                if alias.name in _SESSION_FACTORIES and alias.asname:
                    aliases[alias.asname] = alias.name
    bound, star = _bindings(tree)

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        return node.attr if isinstance(node, ast.Attribute) else ""

    def ancestors(node: ast.AST):
        while node in parents:
            node = parents[node]
            yield node

    sites: list[_Site] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and name_of(node.func) in _SESSION_FACTORIES):
            continue
        scopes = [a for a in ancestors(node) if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
        owner = next((a for a in ancestors(node) if isinstance(a, ast.ClassDef)), None)
        function = scopes[0].name if scopes and not isinstance(scopes[0], ast.Lambda) else ""
        for k in node.keywords:
            if k.arg != "allowed_hosts" or (isinstance(k.value, ast.Constant) and k.value.value is None):
                continue
            value = k.value
            ident, rebound = "", True
            if isinstance(value, ast.Name):
                ident, rebound = value.id, star or bound.get(value.id) != [True]
            elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name) and value.value.id in ("cls", "self") and owner is not None:
                ident = f"{owner.name}.{value.attr}"
                rebound = star or bound.get(owner.name) != [True] or not _class_binds_once(owner, value.attr)
            sites.append(_Site(ident, imported.get(value.id) if isinstance(value, ast.Name) else None, function, rebound, ast.unparse(value)))
    return sites


#: The attribute a finished session's list is read from (``GuardedSession.allowed_hosts``): assigning it after the build replaces the list
#: whatever the factory was given.
_LIST_ATTRIBUTE = "allowed_hosts"


def _pinned_attribute_names() -> set[str]:
    return {name.split(".")[-1] for _m, name, _lanes in POPUP_LANE_LISTS} | {_LIST_ATTRIBUTE}


def _rebinds_in(source: str, rel: str) -> list[tuple[str, str]]:
    """Writes to a pinned list that no name-based walk sees: an ATTRIBUTE assigned anywhere (``self.ALLOWED_HOSTS = ...`` shadows the class
    constant for that instance, ``module.API_HOSTS = ...`` rebinds another module's, ``session.allowed_hosts = ...`` replaces a built
    session's list), and ``setattr``/``__setattr__`` with the name written as a string. A name built at run time (``setattr(o, name, v)``)
    is out of reach of a source walk, which is why the walk also refuses a star import and the pin test reads the live values."""
    names = _pinned_attribute_names()
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Load) and node.attr in names:
            found.append((rel, f"assigns .{node.attr}"))
        elif isinstance(node, ast.Call):
            callee = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if callee in ("setattr", "__setattr__", "delattr", "__delattr__") and any(
                isinstance(a, ast.Constant) and a.value in names for a in node.args[:2]
            ):
                found.append((rel, f"{callee} of a pinned list"))
    return found


def _unpinned_in(source: str, rel: str, module: str) -> list[tuple[str, str]]:
    """The sessions of ``source`` whose list is not one of the rows of ``POPUP_LANE_LISTS``, as ``(path, what the list is written as)``, and
    the writes to a pinned list that the name-based walk cannot see."""
    pinned = {(m, n) for m, n, _lanes in POPUP_LANE_LISTS}
    found: list[tuple[str, str]] = _rebinds_in(source, rel)
    for site in _host_list_sites(source, rel):
        if (rel, site.function, site.ident) in PASSED_ON_HOST_LISTS:
            continue
        if site.ident and not site.rebound and ((module, site.ident) in pinned or site.imported in pinned):
            continue
        found.append((rel, site.text))
    return found


def _unpinned_host_lists() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "src/safety/fetcher.py":
            continue
        module = rel[: -len(".py")].replace("/", ".")
        found += _unpinned_in(path.read_text(encoding="utf-8"), rel, module)
    return found


def test_every_host_list_a_session_is_built_with_is_pinned_to_a_popup_lane():
    """The pin above is a table, and a table that nothing checks for completeness is passed by the next list: walk every session built
    under ``src/`` and require its list to be one of the rows, written as a name (an inline tuple is unpinned by construction)."""
    assert _unpinned_host_lists() == []
    installer_src = (ROOT / "src/llm/installer.py").read_text(encoding="utf-8")
    passed = [
        call.args[1].id if len(call.args) > 1 and isinstance(call.args[1], ast.Name) else "<not a name>"
        for call in ast.walk(ast.parse(installer_src))
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_get_within"
    ]
    assert sorted(passed) == ["GITHUB_API_HOSTS", "GITHUB_ASSET_HOSTS"], "the installer's two fetches pass the two pinned lists and nothing else"
    # ... and the allowance is for a PARAMETER of that function, not for whatever else is called ``hosts``
    (get_within,) = [n for n in ast.walk(ast.parse(installer_src)) if isinstance(n, ast.FunctionDef) and n.name == "_get_within"]
    assert "hosts" in [a.arg for a in get_within.args.args]
    assert all(key[1] == "_get_within" for key in PASSED_ON_HOST_LISTS)


def _subclasses_of(source: str, rel: str, owners: set[str]) -> list[tuple[str, str]]:
    """Classes of ``source`` that name one of ``owners`` among their bases (by the last word of the base, so ``mod.Owner`` counts)."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                word = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
                if word in owners:
                    found.append((rel, f"class {node.name}({word})"))
    return found


def test_no_class_that_owns_a_pinned_host_list_is_subclassed():
    """``cls.ALLOWED_HOSTS`` is the pinned constant only when ``cls`` is the owner: a subclass that overrides the constant (anywhere under
    ``src/``, so the walk of one module cannot see it) makes the same classmethod build its session with the subclass's list."""
    owners = {name.split(".")[0] for _m, name, _lanes in POPUP_LANE_LISTS if "." in name}
    assert "DuckDuckGoSearch" in owners, "the table's class-owned row (the DuckDuckGo search) is among the classes that must not be subclassed"
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        found += _subclasses_of(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix(), owners)
    assert found == [], f"subclasses of a class that owns a pinned host list: {found}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("class Wide(DuckDuckGoSearch):\n    ALLOWED_HOSTS = ('evil.example',)", 1),
        ("import m\nclass Wide(m.DuckDuckGoSearch):\n    pass", 1),
        ("class Other(Base):\n    pass", 0),
    ],
)
def test_the_subclass_walk_sees_a_base_written_as_a_name_or_an_attribute(source, expected):
    assert len(_subclasses_of(source, "x.py", {"DuckDuckGoSearch"})) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=('a.org',))", [("", None)]),
        ("from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=HOSTS)", [("HOSTS", None)]),
        ("from x import HOSTS\nfrom src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=HOSTS)", [("HOSTS", ("x", "HOSTS"))]),
        ("from src.safety.fetcher import following_session\nclass C:\n    def f(self):\n        following_session('o', 'ua', allowed_hosts=self.HOSTS)", [("C.HOSTS", None)]),
        ("from src.safety.fetcher import guarded_session as gs\ngs(allowed_hosts=NEW_HOSTS)", [("NEW_HOSTS", None)]),
        ("from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=None)", []),
        ("from src.safety.fetcher import guarded_session\nguarded_session()", []),
        # an attribute of anything but the class's own cls/self is not a name the pin reads
        ("from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=wide.API_HOSTS)", [("", None)]),
        ("from src.safety.fetcher import guarded_session\ndef f(cls):\n    guarded_session(allowed_hosts=cls.HOSTS)", [("", None)]),
    ],
)
def test_the_completeness_walk_reads_the_list_every_session_is_built_with(source, expected):
    assert [(s.ident, s.imported) for s in _host_list_sites(source, "x.py")] == expected


_WIDE_ATTRIBUTE = "from src.safety.fetcher import guarded_session\nimport wide\nguarded_session(allowed_hosts=wide.API_HOSTS)"
_LOCAL_REBIND = "from src.safety.fetcher import guarded_session\nAPI_HOSTS = ('a.org',)\ndef f():\n    API_HOSTS = ('evil.example',)\n    guarded_session(allowed_hosts=API_HOSTS)"
_PARAMETER = "from src.safety.fetcher import guarded_session\ndef f(API_HOSTS):\n    guarded_session(allowed_hosts=API_HOSTS)"
_LOOP_TARGET = "from src.safety.fetcher import guarded_session\nAPI_HOSTS = ('a.org',)\ndef f(xs):\n    for API_HOSTS in xs:\n        guarded_session(allowed_hosts=API_HOSTS)"
_G = "from src.safety.fetcher import guarded_session\n"
_COMPREHENSION = _G + "[guarded_session(allowed_hosts=API_HOSTS) for API_HOSTS in [('evil.example',)]]"
_COMPREHENSION_AND_CONSTANT = _G + "API_HOSTS = ('a.org',)\n[guarded_session(allowed_hosts=API_HOSTS) for API_HOSTS in [('evil.example',)]]"
_CLASS_BODY = _G + "class C:\n    API_HOSTS = ('evil.example',)\n    s = guarded_session(allowed_hosts=API_HOSTS)"
_GLOBAL_REBIND = _G + "API_HOSTS = ('a.org',)\ndef later():\n    global API_HOSTS\n    API_HOSTS = ('evil.example',)\ndef f():\n    guarded_session(allowed_hosts=API_HOSTS)"
_BRANCHED = _G + "if X:\n    API_HOSTS = ('a.org',)\nelse:\n    API_HOSTS = ('evil.example',)\nguarded_session(allowed_hosts=API_HOSTS)"
_AUGMENTED = _G + "API_HOSTS = ('a.org',)\nAPI_HOSTS += ('evil.example',)\nguarded_session(allowed_hosts=API_HOSTS)"
_STAR_IMPORT = _G + "from elsewhere import *\nAPI_HOSTS = ('a.org',)\nguarded_session(allowed_hosts=API_HOSTS)"
_NEVER_BOUND = _G + "guarded_session(allowed_hosts=API_HOSTS)"
_IMPORTED_AND_REBOUND = "from src.catalog.wikidata import WDQS_HOSTS\n" + _G + "WDQS_HOSTS = ('evil.example',)\nguarded_session(allowed_hosts=WDQS_HOSTS)"
_DDG = _G + "class DuckDuckGoSearch:\n"
_INSTANCE_SHADOW = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    def __init__(self, hosts):\n        self.ALLOWED_HOSTS = hosts\n    def f(self):\n        guarded_session(allowed_hosts=self.ALLOWED_HOSTS)"
_CLASS_BOUND_TWICE = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    ALLOWED_HOSTS = ('evil.example',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_CLASS_REDEFINED = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)\nclass DuckDuckGoSearch:\n    ALLOWED_HOSTS = ('evil.example',)"
_CLASS_WITHOUT_CONSTANT = _DDG + "    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_CLASS_CONSTANT_ONCE = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_PARAMETER_BESIDE_CONSTANT = _G + "API_HOSTS = ('a.org',)\ndef f(API_HOSTS):\n    guarded_session(allowed_hosts=API_HOSTS)"
_EXCEPT_AS = _G + "API_HOSTS = ('a.org',)\ntry:\n    pass\nexcept ValueError as API_HOSTS:\n    guarded_session(allowed_hosts=API_HOSTS)"
_MATCH_CAPTURE = _G + "API_HOSTS = ('a.org',)\nmatch x:\n    case [API_HOSTS]:\n        guarded_session(allowed_hosts=API_HOSTS)"
_MATCH_STAR = _G + "API_HOSTS = ('a.org',)\nmatch x:\n    case [*API_HOSTS]:\n        guarded_session(allowed_hosts=API_HOSTS)"
_MATCH_MAPPING = _G + "API_HOSTS = ('a.org',)\nmatch x:\n    case {'k': 1, **API_HOSTS}:\n        guarded_session(allowed_hosts=API_HOSTS)"
_CLASS_STAR_IMPORT = "from elsewhere import *\n" + _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_CLASS_METHOD_LOCAL = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    def other(self):\n        ALLOWED_HOSTS = 1\n        return ALLOWED_HOSTS\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_CLASS_METHOD_SAME_NAME = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    def ALLOWED_HOSTS(self):\n        return ('evil.example',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)"
_CLASS_OTHER_RECEIVER = _DDG + "    ALLOWED_HOSTS = ('a.org',)\n    def f(self, wide):\n        guarded_session(allowed_hosts=wide.ALLOWED_HOSTS)"
_METHOD_SETATTR = _G + "API_HOSTS = ('a.org',)\ns = guarded_session(allowed_hosts=API_HOSTS)\ns.__setattr__('allowed_hosts', ('evil.example',))"
_SESSION_ATTRIBUTE = _G + "API_HOSTS = ('a.org',)\ns = guarded_session(allowed_hosts=API_HOSTS)\ns.allowed_hosts = ('evil.example',)"
_OTHER_MODULE_ATTRIBUTE = "import src.catalog.wikidata_apply as w\nw.API_HOSTS = ('evil.example',)"
_SETATTR = _G + "API_HOSTS = ('a.org',)\ns = guarded_session(allowed_hosts=API_HOSTS)\nsetattr(s, 'allowed_hosts', ('evil.example',))"
_DUNDER_SETATTR = _G + "API_HOSTS = ('a.org',)\ns = guarded_session(allowed_hosts=API_HOSTS)\nobject.__setattr__(s, 'allowed_hosts', ('evil.example',))"
_NESTED_REBIND = "from src.safety.fetcher import guarded_session\nAPI_HOSTS = ('a.org',)\ndef outer():\n    API_HOSTS = ('evil.example',)\n    def inner():\n        guarded_session(allowed_hosts=API_HOSTS)"


@pytest.mark.parametrize(
    ("source", "rel", "module", "unpinned"),
    [
        # what the pin reads is the module's own constant, so these are accepted ...
        ("from src.safety.fetcher import guarded_session\nAPI_HOSTS = ('a.org',)\nguarded_session(allowed_hosts=API_HOSTS)", "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", False),
        ("from src.catalog.wikidata import WDQS_HOSTS\nfrom src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=WDQS_HOSTS)", "src/catalog/discover.py", "src.catalog.discover", False),
        ("from src.safety.fetcher import guarded_session\nclass DuckDuckGoSearch:\n    ALLOWED_HOSTS = ('a.org',)\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)", "src/services/duckduckgo.py", "src.services.duckduckgo", False),
        ("from src.safety.fetcher import guarded_session\ndef _get_within(url, hosts):\n    guarded_session(allowed_hosts=hosts)", "src/llm/installer.py", "src.llm.installer", False),
        # ... and these are not: a name the pin does not read the value of
        (_WIDE_ATTRIBUTE, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_LOCAL_REBIND, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_PARAMETER, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_LOOP_TARGET, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_NESTED_REBIND, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        ("from src.safety.fetcher import guarded_session\nclass Other:\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)", "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        ("from src.safety.fetcher import guarded_session\nclass DuckDuckGoSearch:\n    @classmethod\n    def f(cls):\n        guarded_session(allowed_hosts=cls.ALLOWED_HOSTS)", "src/services/other.py", "src.services.other", True),
        # the installer's parameter allowance is for that function only, in that file only
        ("from src.safety.fetcher import guarded_session\ndef other(url, hosts):\n    guarded_session(allowed_hosts=hosts)", "src/llm/installer.py", "src.llm.installer", True),
        ("from src.safety.fetcher import guarded_session\ndef _get_within(url, hosts):\n    guarded_session(allowed_hosts=hosts)", "src/llm/other.py", "src.llm.other", True),
        ("from src.safety.fetcher import guarded_session\nguarded_session(allowed_hosts=('a.org',))", "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        # a second binding of the name ANYWHERE in the module is a different value than the constant the pin reads: a comprehension and a
        # class body at module level, a function that rebinds through ``global``, a branch, an augmented assignment, a star import
        (_COMPREHENSION, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_COMPREHENSION_AND_CONSTANT, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_CLASS_BODY, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_GLOBAL_REBIND, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_BRANCHED, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_AUGMENTED, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_STAR_IMPORT, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_NEVER_BOUND, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_IMPORTED_AND_REBOUND, "src/catalog/discover.py", "src.catalog.discover", True),
        # a class constant is the pinned one only when it is bound once in the class body, in a class bound once; an instance attribute
        # of the same name, a second class of the name, or a constant that is a method are not
        (_INSTANCE_SHADOW, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_BOUND_TWICE, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_REDEFINED, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_WITHOUT_CONSTANT, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_CONSTANT_ONCE, "src/services/duckduckgo.py", "src.services.duckduckgo", False),
        # writes to a pinned list that are not a name: the attribute of a built session, a pinned name on another module, setattr
        (_SESSION_ATTRIBUTE, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_OTHER_MODULE_ATTRIBUTE, "src/catalog/other.py", "src.catalog.other", True),
        (_SETATTR, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_DUNDER_SETATTR, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_METHOD_SETATTR, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        # every other way a name is bound: a parameter beside the constant, an exception name, the three kinds of match capture, a star import
        (_PARAMETER_BESIDE_CONSTANT, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_EXCEPT_AS, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_MATCH_CAPTURE, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_MATCH_STAR, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_MATCH_MAPPING, "src/catalog/wikidata_apply.py", "src.catalog.wikidata_apply", True),
        (_CLASS_STAR_IMPORT, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_METHOD_SAME_NAME, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        (_CLASS_OTHER_RECEIVER, "src/services/duckduckgo.py", "src.services.duckduckgo", True),
        # a method's own local of the same name is not the class constant, so it does not count against it
        (_CLASS_METHOD_LOCAL, "src/services/duckduckgo.py", "src.services.duckduckgo", False),
    ],
)
def test_the_completeness_walk_accepts_only_a_list_the_pin_reads(source, rel, module, unpinned):
    """The walk used to keep the last word of whatever the list was written as, so ``wide.API_HOSTS`` in a module whose own ``API_HOSTS``
    is pinned was accepted while the pin read the OTHER list; and a name bound inside the function (a rebind, a parameter, a loop variable)
    is not the module's constant either."""
    assert bool(_unpinned_in(source, rel, module)) is unpinned


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
        # a list handed in a form the pin cannot read is unlisted too, so the file has to be in UNLISTED_SESSIONS with its reason
        "import functools\nfrom src.safety.fetcher import guarded_session\nfunctools.partial(guarded_session, allowed_hosts=('evil.example',))",
        "from src.safety.fetcher import guarded_session\nguarded_session(**{'allowed_hosts': ('evil.example',)})",
        "from src.safety.fetcher import guarded_session\nopts = {}\nguarded_session(**opts)",
        "from src.safety.fetcher import guarded_session\nbuild = guarded_session\nbuild(allowed_hosts=('evil.example',))",
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
