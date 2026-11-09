"""Protected mode names the app to Wikimedia only (R657).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Settings note, the user manual and docs/SECURITY.md said protected mode sends a generic User-Agent. The collector did; a guarded
session did not: ``_session_for`` set the caller's own agent before it read the mode, so every API client built on it (the Wikidata
ring loader, statistics, OSM, self-update) named the app through Tor. R657: in protected mode a guarded session sends
``GENERIC_USER_AGENT`` to every host except Wikimedia's (Wikipedia, Wikidata, the dumps), whose User-Agent policy asks API clients to
name themselves. The decision is taken in ``GuardedSession.send``, so it holds for the first request and for every redirect hop, whatever
User-Agent a request carried. Each test drives a real session through a recording adapter; nothing leaves the machine.
"""

from __future__ import annotations

import pytest
import requests
from requests.adapters import BaseAdapter

from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import DESCRIPTIVE_AGENT_DOMAINS, keeps_descriptive_agent
from src.safety.settings import GENERIC_USER_AGENT

_SOCKS = "socks5h://127.0.0.1:9050"
_AGENT = "OpenOmniscience-test-agent/1.0 (local-first research app)"

#: Hosts the app's guarded sessions talk to on Wikimedia's side: every one keeps the descriptive agent.
_WIKIMEDIA = (
    "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q42",
    "https://query.wikidata.org/sparql?query=x",
    "https://en.wikipedia.org/w/api.php?action=query",
    "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2",
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/",
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
)


def test_the_allowlist_is_wikimedias_three_domains_and_nothing_else():
    assert DESCRIPTIVE_AGENT_DOMAINS == ("wikipedia.org", "wikidata.org", "wikimedia.org")


@pytest.mark.parametrize("url", _WIKIMEDIA)
def test_a_wikimedia_host_keeps_the_descriptive_agent(url):
    assert keeps_descriptive_agent(url)


@pytest.mark.parametrize("url", _ELSEWHERE)
def test_any_other_host_gets_the_generic_agent(url):
    assert not keeps_descriptive_agent(url)


@pytest.mark.parametrize("url", ["", "not a url", "https://", "https://[::1/", "http://a.wikipedia.org\\@evil.example/"])
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
    "Transparent mode names this tool in the User-Agent (polite, but identifiable). Protected mode routes every fetch through a proxy you "
    "run and sends a generic User-Agent, except to Wikimedia's sites (Wikipedia, Wikidata, the dumps): their API policy asks each tool to "
    "name itself, so those requests still name this one."
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
        ("src/static/index.html", "except to Wikimedia's sites (Wikipedia, Wikidata, the dumps)"),
        ("src/api/safety.py", "except to Wikimedia's sites (Wikipedia, Wikidata, the dumps)"),
        ("docs/USER_MANUAL.md", "The one exception is Wikimedia's sites (Wikipedia, Wikidata, the dumps)"),
        ("docs/SECURITY.md", "The list is `DESCRIPTIVE_AGENT_DOMAINS` in `src/safety/fetcher.py`"),
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
