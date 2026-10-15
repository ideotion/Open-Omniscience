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
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import BaseAdapter

from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import RedirectRefused, guarded_session, refuse_unlisted_host
from src.safety.settings import SafetySettings

ROOT = Path(__file__).resolve().parents[1]

#: The three words of the reasons a refusal may carry, none of them a URL or a host.
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


def test_the_parser_clause_refuses_a_host_the_two_readings_disagree_on():
    """``urllib3`` reads ``evil.test`` here and ``urlparse`` ``de.wikipedia.org``; the list names evil.test so only the disagreement can refuse."""
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
    [(), ("",), (".",), ("Wikipedia.org",), ("https://wikipedia.org",), ("wikipedia.org/",), ("wikipedia.org:443",), ("..wikipedia.org",), ("a..b",), ("-a.org",), ("wíki.org",), ("a b.org",)],
)
def test_a_malformed_list_is_refused_when_the_session_is_built(bad, transparent):
    with pytest.raises(ValueError):
        guarded_session(allowed_hosts=bad)


def test_a_well_formed_list_is_stored_as_a_tuple(transparent):
    assert guarded_session(allowed_hosts=["a.org", ".b.org"]).allowed_hosts == ("a.org", ".b.org")


def test_following_session_keys_the_cache_on_the_list(transparent):
    a = fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",))
    assert fetcher_mod.following_session("o", "ua", allowed_hosts=("a.org",)) is a, "kept while nothing changes"
    b = fetcher_mod.following_session("o", "ua", allowed_hosts=("b.org",))
    assert b is not a and b.allowed_hosts == ("b.org",), "another list is another session"
    assert fetcher_mod.following_session("o", "ua").allowed_hosts is None


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
# What still has no list, so that a new session without one is a decision and not an accident
# --------------------------------------------------------------------------- #
#: Every module that builds a guarded session WITHOUT a host list, with the number of such calls. Each is a fixed upstream whose list is
#: not yet decided (the dumps and OSM mirrors, the model hosts and the statistics sources redirect between CDNs by design), so a list
#: needs a look at where each really redirects. Zero slack: a call that gains a list leaves this table, and a new call joins it.
UNLISTED_SESSIONS = {
    "src/analytics/ring_loader.py": 1,
    "src/catalog/discover.py": 1,
    "src/catalog/wikidata_apply.py": 1,
    "src/entities/gazetteer_build.py": 1,
    "src/entities/items.py": 1,
    "src/geo/osm_downloads.py": 2,
    "src/ingest/segmented_download.py": 2,
    "src/llm/installer.py": 2,
    "src/monitoring/release_run.py": 1,
    "src/stats/fetch.py": 1,
    "src/wiki/dumps.py": 2,
}


def _unlisted_session_calls() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "src/safety/fetcher.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in ("guarded_session", "following_session") and not any(k.arg == "allowed_hosts" for k in node.keywords):
                found[rel] = found.get(rel, 0) + 1
    return found


def test_a_guarded_session_without_a_host_list_is_a_decision_not_an_accident():
    found = _unlisted_session_calls()
    assert found == UNLISTED_SESSIONS, (
        "a session built without allowed_hosts follows any redirect; give it a list, or add it to UNLISTED_SESSIONS with the reason "
        f"(new or changed: {sorted(set(found.items()) ^ set(UNLISTED_SESSIONS.items()))})"
    )
