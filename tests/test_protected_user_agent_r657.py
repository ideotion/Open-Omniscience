"""Protected mode names the app to the Wikimedia hosts its Wikipedia, Wikidata and dump features call, and nowhere else (R657).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Settings note, the user manual and docs/SECURITY.md said protected mode sends a generic User-Agent. The collector did; a guarded
session did not: ``_session_for`` set the caller's own agent before it read the mode, so every API client built on it (the Wikidata
ring loader, statistics, OSM, self-update) named the app through Tor, and the release run's law probe built its fetcher by hand, so it
went out with no proxy at all (a field-check probe did the same until #1921 removed it). R657: in protected mode a guarded session sends
``GENERIC_USER_AGENT`` to every host except the Wikimedia hosts the app's own clients name (``DESCRIPTIVE_AGENT_HOSTS``), whose
User-Agent policy asks API clients to name themselves, and only over https. The decision is taken in ``GuardedSession.send``, so it holds
for the first request and for every redirect hop, whatever User-Agent a request carried; the law probe builds its fetcher through
``make_fetcher``. Each test drives real code through a recording adapter or a recording fetch; nothing leaves the machine.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import DESCRIPTIVE_AGENT_HOSTS, keeps_descriptive_agent
from src.safety.settings import GENERIC_USER_AGENT

_SOCKS = "socks5h://127.0.0.1:9050"
_AGENT = "OpenOmniscience-test-agent/1.0 (local-first research app)"

#: Hosts the app's guarded sessions talk to on Wikimedia's side: every one keeps the descriptive agent.
_WIKIMEDIA = (
    "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q42",
    "https://query.wikidata.org/sparql?query=x",
    "https://en.wikipedia.org/w/api.php?action=query",
    "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2",
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/X/daily/20260101/20260131",
    "https://stream.wikimedia.org/v2/stream/recentchange",
    "https://ores.wikimedia.org/v3/scores/",
    "https://EN.WIKIPEDIA.ORG./wiki/X",
)
#: Hosts that are not Wikimedia's, lookalikes included: every one gets the generic agent.
_ELSEWHERE = (
    "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD?format=json&page=2",
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_gdp",
    "https://download.geofabrik.de/europe-updates/state.txt",
    "https://api.github.com/repos/ideotion/Open-Omniscience/tags",
    "https://html.duckduckgo.com/html/?q=x",
    "https://evilwikipedia.org/w/api.php",
    "https://wikipedia.org.evil.example/w/api.php",
    "https://wikidata.org.example/",
    "https://www.wikiquote.org/",
    "https://127.0.0.1:11434/api/tags",
    "https://shop.wikimedia.org/",  # under wikimedia.org, but no client of the app's calls it
    "https://meta.wikimedia.org/w/api.php",
    "https://wikidata.org/w/api.php",  # the bare domain: the app calls www. and query.
    "https://wikipedia.org/",  # the portal, not an edition
    "http://en.wikipedia.org/w/api.php",  # plain http: the agent would cross the exit in clear text
)


def test_the_allowlist_is_exactly_the_wikimedia_hosts_the_apps_clients_name():
    """One explicit list, and every entry on it is a host one of the app's own Wikimedia clients is confined to: nothing wider."""
    from src.analytics.wikidata_rings import API_HOSTS as rings_hosts
    from src.catalog.wikidata import WDQS_HOSTS
    from src.catalog.wikidata_enrich import API_HOSTS as enrich_hosts
    from src.wiki.client import WIKI_SESSION_HOSTS
    from src.wiki.dumps import dump_url
    from src.wiki.ores import ORES_HOSTS

    named = {*WIKI_SESSION_HOSTS, *ORES_HOSTS, *WDQS_HOSTS, *enrich_hosts, *rings_hosts, urlparse(dump_url("en", "pages-articles")).hostname}
    assert len(DESCRIPTIVE_AGENT_HOSTS) == len(set(DESCRIPTIVE_AGENT_HOSTS))
    assert set(DESCRIPTIVE_AGENT_HOSTS) == named


@pytest.mark.parametrize("url", _WIKIMEDIA)
def test_a_wikimedia_host_keeps_the_descriptive_agent(url):
    assert keeps_descriptive_agent(url)


@pytest.mark.parametrize("url", _ELSEWHERE)
def test_any_other_host_gets_the_generic_agent(url):
    assert not keeps_descriptive_agent(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://",
        "https://[::1/",
        "https://a.wikipedia.org\\@evil.example/",  # urllib3 reads a.wikipedia.org, urlparse evil.example
        "https://evil.example\\@en.wikipedia.org/",  # the other way round: urlparse reads en.wikipedia.org, urllib3 evil.example
        "https://en.wikipedia.org\t.evil.example/",
    ],
)
def test_an_unreadable_or_ambiguous_url_gets_the_generic_agent(url):
    assert not keeps_descriptive_agent(url)


class _Recorder(BaseAdapter):
    """Records each request's URL and User-Agent; answers 200, or 302 to ``redirects[url]`` when one is set."""

    def __init__(self, redirects: dict[str, str] | None = None) -> None:
        super().__init__()
        self.sent: list[tuple[str, str]] = []
        self.redirects = redirects or {}

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.sent.append((request.url, request.headers.get("User-Agent", "")))
        resp = requests.models.Response()
        target = self.redirects.get(request.url)
        resp.status_code = 302 if target else 200
        if target:
            resp.headers["Location"] = target
        resp._content = b"{}"
        resp.url = request.url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


@pytest.fixture
def mode(monkeypatch, tmp_path):
    """Sets the fetch mode the way an operator does (the settings file's environment), with one SOCKS proxy."""

    def _set(name: str) -> None:
        monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("OO_FETCH_MODE", name)
        monkeypatch.setenv("OO_HTTP_PROXY", _SOCKS)
        monkeypatch.delenv("OO_HTTP_PROXIES", raising=False)
        monkeypatch.setattr(fetcher_mod, "_FOLLOWING", {})

    return _set


def _session(recorder: _Recorder, **kw) -> requests.Session:
    s = fetcher_mod.guarded_session(user_agent=_AGENT, **kw)
    s.mount("https://", recorder)
    s.mount("http://", recorder)
    return s


def test_protected_mode_sends_the_generic_agent_except_to_wikimedia(mode):
    mode("protected")
    rec = _Recorder()
    s = _session(rec)
    for url in (*_WIKIMEDIA[:4], *_ELSEWHERE[:4]):
        s.get(url, timeout=5)
    agents = dict(rec.sent)
    for url in _WIKIMEDIA[:4]:
        assert agents[url] == _AGENT, url
    for url in _ELSEWHERE[:4]:
        assert agents[url] == GENERIC_USER_AGENT, url


def test_a_user_agent_the_request_carries_does_not_reach_another_host(mode):
    mode("protected")
    rec = _Recorder()
    _session(rec).get(_ELSEWHERE[0], headers={"User-Agent": "OpenOmniscienceBot/9"}, timeout=5)
    assert rec.sent == [(_ELSEWHERE[0], GENERIC_USER_AGENT)]


def test_every_redirect_hop_gets_the_agent_its_own_host_is_owed(mode):
    mode("protected")
    rec = _Recorder({_WIKIMEDIA[0]: _ELSEWHERE[0], _ELSEWHERE[1]: _WIKIMEDIA[2]})
    s = _session(rec)
    s.get(_WIKIMEDIA[0], timeout=5)
    s.get(_ELSEWHERE[1], timeout=5)
    assert rec.sent == [
        (_WIKIMEDIA[0], _AGENT),
        (_ELSEWHERE[0], GENERIC_USER_AGENT),
        (_ELSEWHERE[1], GENERIC_USER_AGENT),
        (_WIKIMEDIA[2], _AGENT),
    ]


def test_a_following_session_follows_the_same_rule(mode):
    mode("protected")
    rec = _Recorder()
    s = fetcher_mod.following_session("r657-test", _AGENT)
    s.mount("https://", rec)
    s.get(_WIKIMEDIA[0], timeout=5)
    s.get(_ELSEWHERE[0], timeout=5)
    assert rec.sent == [(_WIKIMEDIA[0], _AGENT), (_ELSEWHERE[0], GENERIC_USER_AGENT)]


def test_transparent_mode_names_the_app_everywhere_as_before(mode):
    mode("transparent")
    rec = _Recorder()
    s = _session(rec)
    s.get(_WIKIMEDIA[0], timeout=5)
    s.get(_ELSEWHERE[0], timeout=5)
    assert rec.sent == [(_WIKIMEDIA[0], _AGENT), (_ELSEWHERE[0], _AGENT)]


_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
_NOTE = (
    "Transparent mode names this tool in the User-Agent (polite, but identifiable). Protected mode routes the app's web fetches through a "
    "proxy you run and sends a generic User-Agent, except in its API and dump requests to Wikimedia's servers: Wikimedia's API policy asks "
    "each tool to name itself, so those still name this one. The newsletter mailbox pull, OpenTimestamps anchoring and the local-AI "
    "downloads connect directly."
)
_HINT = "Protected mode cannot guarantee anonymity — you must run and trust the proxy yourself. SOCKS proxies such as Tor need nothing extra installed."
_LOCALES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_settings_note_states_the_exception_and_every_locale_carries_it():
    """The note is the key the page translates by; a locale without it would show the old, wrong sentence's translation or English."""
    import json

    html = _flat((_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8"))
    assert _NOTE in html and _HINT in html
    for lang in _LOCALES:
        table = json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert table.get(_NOTE) and table.get(_HINT), lang
        assert not any("Protected mode sends a generic User-Agent and routes" in k for k in table), lang
        assert not any("optional [safety] extra" in k for k in table), lang


@pytest.mark.parametrize(
    ("path", "exception"),
    [
        ("src/static/index.html", "except in its API and dump requests to Wikimedia's servers"),
        ("src/api/safety.py", "except in its API and dump requests to Wikimedia's servers"),
        ("docs/USER_MANUAL.md", "The one User-Agent exception is the app's API and dump requests to Wikimedia's servers"),
        ("docs/SECURITY.md", "The list is `DESCRIPTIVE_AGENT_HOSTS` in `src/safety/fetcher.py`"),
    ],
)
def test_no_text_says_protected_mode_hides_the_app_from_everyone(path, exception):
    """Each text that describes protected mode names the Wikimedia exception, and none still sends SOCKS users to an extra that does not exist."""
    if path.endswith(".py"):  # the note the settings endpoint returns, not the source's split literals
        from src.api.safety import _PROXY_NOTE as text
    else:
        text = _flat((_ROOT / path).read_text(encoding="utf-8"))
    assert exception in text, path
    assert "[safety] extra" not in text, path
    assert "OpenTimestamps anchoring and the local-AI downloads connect directly" in text, path


def test_the_manuals_other_protected_mode_sentence_names_the_exception_too():
    """The manual describes protected mode twice; the second place (its anonymity note) said "a generic User-Agent" with no exception."""
    text = _flat((_ROOT / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8"))
    assert "the app's part is a generic User-Agent and routing every fetch through it." not in text
    assert "except in its API and dump requests to Wikimedia's servers, which still name the tool" in text


def _recording_fetch(monkeypatch) -> list[tuple[str, str | None, str]]:
    """Replaces ``EthicalFetcher.fetch`` with one that records the fetcher's proxy and agent and refuses, so nothing is sent."""
    from src.ingest import EthicalFetcher, FetchError

    seen: list[tuple[str, str | None, str]] = []

    def fetch(self, url, *a, **kw):
        seen.append((str(url), self.proxy, self.user_agent))
        raise FetchError("recorded, not sent")

    monkeypatch.setattr(EthicalFetcher, "fetch", fetch)
    return seen


def test_the_release_runs_law_probe_fetches_through_the_proxy_with_the_generic_agent(mode, monkeypatch):
    """It built ``EthicalFetcher(timeout=45.0)`` by hand: in protected mode it went out with no proxy and the bot's name."""
    from src.monitoring import release_run

    mode("protected")
    seen = _recording_fetch(monkeypatch)
    release_run._law_live_checks()
    assert seen, "the catalogue names no priority-host document to probe"
    assert {(proxy, agent) for _url, proxy, agent in seen} == {(_SOCKS, GENERIC_USER_AGENT)}


def test_protected_mode_with_no_proxy_refuses_the_law_probe_by_name(mode, monkeypatch):
    """No proxy in protected mode: ``make_fetcher`` refuses before any fetch, and the probe records the refusal as its result."""
    from src.monitoring import release_run

    mode("protected")
    monkeypatch.delenv("OO_HTTP_PROXY")
    seen = _recording_fetch(monkeypatch)
    assert "TransportUnavailable" in release_run._law_probe()["error"]
    assert seen == []


def test_only_the_safety_module_and_the_soak_harness_build_an_ethical_fetcher_by_hand():
    """Every other module gets its fetcher from ``make_fetcher``/``following_fetcher``, which read the fetch mode. A fetcher built by
    hand follows no mode: no proxy and the bot's name in protected mode. The soak harness hands its fetcher a stand-in session."""
    import ast

    built_in: set[str] = set()
    for path in (_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name == "EthicalFetcher":
                    built_in.add(path.relative_to(_ROOT).as_posix())
    assert built_in == {"src/safety/fetcher.py", "src/testing/collect_soak.py"}
