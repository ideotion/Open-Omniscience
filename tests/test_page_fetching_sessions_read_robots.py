"""A guarded session that fetches a PAGE or a DOCUMENT reads robots.txt first, and fails closed (rows 126-128).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

SECURITY.md (Transport) exempts from robots.txt only the guarded sessions that call a PUBLISHED API or download a DATA or DUMP
file. Two did not fit and did not read it: the DuckDuckGo topic search (its HTML page for people) and the IPCC reports (PDF
documents on a website). Both now ask ``src.safety.fetcher.require_robots_allow`` first, and a disallowed or unreadable
robots.txt refuses the request, by name, never worked around. The last test is the ratchet: every module that builds a guarded
session is either listed here with the SECURITY.md row that states its API/data-file exemption, or reads robots.txt itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.ingest import EthicalFetcher, RobotsDisallowed, RobotsUnavailable
from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import RedirectRefused, require_robots_allow

ROOT = Path(__file__).resolve().parents[1]
DDG_URL = "https://html.duckduckgo.com/html/"
DDG_HOSTS = ("html.duckduckgo.com",)


class _Resp:
    def __init__(self, url: str, status: int, body: bytes) -> None:
        self.url, self.status_code, self.content, self.text = url, status, body, body.decode()
        self.headers = {"Content-Type": "text/plain"}

    def close(self) -> None:
        pass


class _Session:
    """An injected session: serves robots.txt from memory and records every address it was asked for."""

    def __init__(self, robots: bytes = b"User-agent: *\n", status: int = 200) -> None:
        self.robots, self.status = robots, status
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, **_kw):
        self.calls.append(url)
        return _Resp(url, self.status, self.robots)


def _fetcher(tmp_path: Path, session: _Session) -> EthicalFetcher:
    return EthicalFetcher(session=session, min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "r.json")


# --------------------------------------------------------------------------- #
# The gate itself
# --------------------------------------------------------------------------- #


def test_an_allowing_robots_txt_lets_the_address_through(tmp_path):
    s = _Session(b"User-agent: *\nDisallow: /private/\n")
    require_robots_allow(DDG_URL, DDG_HOSTS, user_agents=("Mozilla/5.0 (compatible; X/1.0)",), fetcher=_fetcher(tmp_path, s))
    assert s.calls == ["https://html.duckduckgo.com/robots.txt"]


def test_a_disallow_refuses(tmp_path):
    s = _Session(b"User-agent: *\nDisallow: /html/\n")
    with pytest.raises(RobotsDisallowed):
        require_robots_allow(DDG_URL, DDG_HOSTS, fetcher=_fetcher(tmp_path, s))


def test_a_disallow_aimed_at_the_agent_the_request_sends_refuses_too(tmp_path):
    # Allowed for the app's crawler agent, disallowed for the agent the search session actually sends: refused, without the query.
    s = _Session(b"User-agent: Mozilla\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
    f = _fetcher(tmp_path, s)
    require_robots_allow(DDG_URL, DDG_HOSTS, fetcher=f)  # the crawler agent alone is allowed
    with pytest.raises(RobotsDisallowed) as exc:
        require_robots_allow(DDG_URL + "?q=secret", DDG_HOSTS, user_agents=("Mozilla/5.0 (compatible; X/1.0)",), fetcher=f)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_a_robots_txt_that_cannot_be_read_refuses_fail_closed(tmp_path, status):
    s = _Session(b"", status=status)
    with pytest.raises(RobotsUnavailable):
        require_robots_allow(DDG_URL, DDG_HOSTS, fetcher=_fetcher(tmp_path, s))


def test_a_missing_robots_txt_allows_as_the_standard_says(tmp_path):
    require_robots_allow(DDG_URL, DDG_HOSTS, fetcher=_fetcher(tmp_path, _Session(b"", status=404)))


def test_an_address_off_the_list_is_refused_before_any_request(tmp_path):
    s = _Session()
    with pytest.raises(RedirectRefused):
        require_robots_allow("https://duckduckgo.com/html/", DDG_HOSTS, fetcher=_fetcher(tmp_path, s))
    with pytest.raises(RedirectRefused):
        require_robots_allow("http://html.duckduckgo.com/html/", DDG_HOSTS, fetcher=_fetcher(tmp_path, s))
    assert s.calls == []


def test_the_default_fetcher_is_held_to_the_hosts_for_every_request(monkeypatch):
    seen: list[str] = []

    class _Real:
        session = type("S", (), {"get": staticmethod(lambda u, *a, **k: seen.append(u))})()

        @staticmethod
        def _guard_target(host):
            seen.append(f"guard:{host}")

    monkeypatch.setattr(fetcher_mod, "make_fetcher", lambda: _Real())
    f = fetcher_mod._host_held_fetcher(DDG_HOSTS)
    with pytest.raises(Exception, match="refused"):
        f.session.get("https://evil.example/robots.txt")
    with pytest.raises(Exception, match="refused"):
        f._guard_target("evil.example")
    f.session.get("https://html.duckduckgo.com/robots.txt")
    f._guard_target("html.duckduckgo.com")
    assert seen == ["https://html.duckduckgo.com/robots.txt", "guard:html.duckduckgo.com"]


# --------------------------------------------------------------------------- #
# DuckDuckGo: the search page is a page, so robots.txt applies and a refusal is said as one
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("exc", "reason"), [(RobotsDisallowed("no"), "disallowed"), (RobotsUnavailable("down"), "unavailable")])
def test_the_search_is_never_sent_when_robots_refuses(monkeypatch, exc, reason):
    from src.services import duckduckgo

    def _refuse(*_a, **_k):
        raise exc

    built: list[object] = []
    monkeypatch.setattr(fetcher_mod, "require_robots_allow", _refuse)
    monkeypatch.setattr(fetcher_mod, "guarded_session", lambda *a, **k: built.append(k))
    with pytest.raises(duckduckgo.SearchRefusedByRobots) as got:
        duckduckgo.DuckDuckGoSearch.search("press freedom")
    assert got.value.reason == reason
    assert built == [], "a refused search builds no session and sends nothing"
    # ... and topic discovery passes the refusal on instead of answering "0 sources".
    with pytest.raises(duckduckgo.SearchRefusedByRobots):
        duckduckgo.DuckDuckGoSearch.discover_sources_by_topic("press freedom")


def test_the_search_checks_its_own_page_and_its_own_agent(monkeypatch):
    from src.services import duckduckgo

    asked: list[tuple] = []
    monkeypatch.setattr(fetcher_mod, "require_robots_allow", lambda url, hosts, **k: asked.append((url, hosts, k)))
    duckduckgo.DuckDuckGoSearch._robots_allow()
    url, hosts, kw = asked[0]
    assert url == duckduckgo.DuckDuckGoSearch.BASE_URL and hosts == duckduckgo.DuckDuckGoSearch.ALLOWED_HOSTS
    assert kw["user_agents"] == (duckduckgo.DuckDuckGoSearch.USER_AGENT,)


@pytest.mark.parametrize("reason", ["disallowed", "unavailable"])
def test_the_route_says_robots_refused_it_never_that_nothing_was_found(monkeypatch, reason):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.safety.settings import SafetySettings
    from src.services.duckduckgo import SearchRefusedByRobots

    monkeypatch.setattr("src.safety.settings.load_settings", lambda: SafetySettings(discovery_external_enabled=True))
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    def _refused(self, topic, max_sources, region="wt-wt"):
        raise SearchRefusedByRobots(reason)

    monkeypatch.setattr("src.database.source_manager.SourceManager.discover_sources_by_topic", _refused)
    body = TestClient(app).post("/api/sources/discover/topic?topic=press+freedom").json()
    assert body["count"] == 0 and body["refused_by_robots"] == reason
    assert "robots.txt" in body["message"] and "nothing was searched" in body["message"]
    assert "Discovered" not in body["message"]


# --------------------------------------------------------------------------- #
# IPCC: the reports are documents on a website, so robots.txt applies
# --------------------------------------------------------------------------- #


def test_an_ipcc_report_is_not_fetched_when_robots_refuses(monkeypatch):
    from src.ingest import ipcc_spm

    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    got: list[str] = []

    def _no(url):
        raise ValueError("refused by robots")

    with pytest.raises(ValueError, match="robots"):
        ipcc_spm.fetch_spm("wg1", get=lambda u: got.append(u), robots=_no)
    assert got == [], "robots refused, so the report was never asked for"


@pytest.mark.parametrize(("exc", "words"), [(RobotsDisallowed("no"), "does not allow"), (RobotsUnavailable("down"), "could not be read")])
def test_the_default_ipcc_check_reads_robots_on_the_ipcc_host_and_names_the_refusal(monkeypatch, exc, words):
    from src.ingest import ipcc_spm

    asked: list[tuple] = []

    def _gate(url, hosts, **_k):
        asked.append((url, hosts))
        raise exc

    monkeypatch.setattr(fetcher_mod, "require_robots_allow", _gate)
    entry = ipcc_spm.spm_entry("wg1")
    with pytest.raises(ValueError, match=words):
        ipcc_spm._default_robots(entry.url)
    assert asked == [(entry.url, ipcc_spm.API_HOSTS)]


def test_the_live_ipcc_path_asks_robots_first(monkeypatch):
    from src.ingest import ipcc_spm

    order: list[str] = []
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    monkeypatch.setattr(ipcc_spm, "_default_robots", lambda url: order.append("robots") or (_ for _ in ()).throw(ValueError("robots")))
    monkeypatch.setattr(ipcc_spm, "_default_getter", lambda url: order.append("get"))
    with pytest.raises(ValueError, match="robots"):
        ipcc_spm.fetch_spm("wg1")
    assert order == ["robots"]


# --------------------------------------------------------------------------- #
# The ratchet: a guarded session is an API/data-file exemption with its SECURITY.md row, or it reads robots.txt
# --------------------------------------------------------------------------- #

#: Modules whose guarded sessions call a published API or download a data or dump file, so they do not read robots.txt
#: (SECURITY.md, Transport): ``{path: text of the SECURITY.md row or paragraph that names it}``. Zero slack, both ways.
API_OR_DATA_FILE = {
    "src/analytics/ring_loader.py": "**Keyword translations**",
    "src/catalog/discover.py": "**Source discovery**",
    "src/catalog/wikidata_apply.py": "**Source discovery**",
    "src/entities/gazetteer_build.py": "`scripts/build_place_gazetteer.py` reaches `www.wikidata.org`",
    "src/entities/items.py": "**Places and people**",
    "src/geo/osm_downloads.py": "**Maps / OpenStreetMap**",
    "src/ingest/segmented_download.py": "**Maps / OpenStreetMap**",
    "src/llm/installer.py": "**Local AI install & weights**",
    "src/maintenance/self_update.py": "**App updates**",
    "src/monitoring/release_run.py": "the 0.4 release run reads one Hugging Face URL",
    "src/osm/replication.py": "**Maps / OpenStreetMap**",
    "src/stats/fetch.py": "**Official statistics**",
    "src/wiki/client.py": "**Wikipedia / Wikimedia**",
    "src/wiki/dumps.py": "**Wikipedia / Wikimedia**",
    "src/wiki/ores.py": "**Wikipedia / Wikimedia**",
}
#: Modules whose guarded session fetches a page or a document, so they call ``require_robots_allow`` first.
READS_ROBOTS = {"src/ingest/ipcc_spm.py", "src/services/duckduckgo.py"}

_FACTORIES = ("guarded_session", "following_session", "GuardedSession", "_session_for")


def _names_in(tree: ast.AST, wanted: tuple[str, ...]) -> int:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in wanted and alias.asname:
                    aliases[alias.asname] = alias.name

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        return node.attr if isinstance(node, ast.Attribute) else ""

    return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute)) and name_of(n) in wanted)


def _session_builders() -> set[str]:
    found = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "src/safety/fetcher.py":
            continue
        if _names_in(ast.parse(path.read_text(encoding="utf-8"), filename=rel), _FACTORIES):
            found.add(rel)
    return found


def test_every_guarded_session_is_an_api_or_data_file_exemption_or_reads_robots():
    found = _session_builders()
    assert not (set(API_OR_DATA_FILE) & READS_ROBOTS), "a module is one or the other"
    assert found == set(API_OR_DATA_FILE) | READS_ROBOTS, (
        "a module builds a guarded session, which never reads robots.txt. If it calls a published API or downloads a data or dump "
        "file, add it to API_OR_DATA_FILE with the SECURITY.md row that says so; if it fetches a page or a document, call "
        "src.safety.fetcher.require_robots_allow first and add it to READS_ROBOTS "
        f"(new or gone: {sorted(found ^ (set(API_OR_DATA_FILE) | READS_ROBOTS))})"
    )


def test_each_exemption_is_stated_in_security_md():
    security = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    missing = {path: row for path, row in API_OR_DATA_FILE.items() if row not in security}
    assert not missing, f"the SECURITY.md row each exemption names is gone: {missing}"


def test_each_robots_reader_calls_the_gate():
    for rel in sorted(READS_ROBOTS):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "require_robots_allow"]
        assert calls, f"{rel} builds a guarded session for a page or a document and never calls require_robots_allow"
