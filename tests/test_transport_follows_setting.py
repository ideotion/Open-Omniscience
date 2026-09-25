"""Protected fetch mode reaches every request, or the request is refused by name.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two transport leaks, found together on 2026-09-25 while mapping S04-08's S5 (Q1014: "a
lane never downgrades Tor -> clearnet without the explicit consent the non-negotiable
requires"):

  1. ``guarded_session`` read ``http_proxy`` alone. Protected mode with only a SOCKS POOL
     (C10) -- a configuration ``save_settings`` accepts and
     ``tests/test_socks_proxy_pool.py`` pins as valid -- gave every session it builds no
     proxy at all: the MediaWiki API and its stream, dumps, ORES, OSM downloads, official
     statistics, DuckDuckGo discovery and the AI installer went out directly while the
     articles went through the pool.
  2. ``src.api.markets``, ``src.api.hazards`` and ``src.api.ingestion`` built their
     fetcher at IMPORT time. Import runs before the operator unlocks an encrypted store,
     when the safety settings load from the pre-migration file if one survives, or as
     their defaults. So on an encrypted install whose protected mode was saved in
     Settings, those three fetched directly with the bot User-Agent unless an older
     settings file happened to carry the same choice, and on any install a later
     switch in Settings did not reach them before a restart.

And a third, found by the first test here the moment it ran in a sandbox whose
environment sets ``HTTPS_PROXY``: requests folds the ``HTTP(S)_PROXY`` / ``ALL_PROXY``
environment into a REQUEST's proxy mapping and lets it win over the SESSION's
(``Session.merge_environment_settings``). Every path that left the operator's proxy on
``session.proxies`` alone -- the whole single-proxy shared session, and the article
fetcher whenever it did not isolate (an HTTP proxy, or isolation switched off) and on
both preflight side doors -- sent its requests through the system proxy instead of Tor.

WHAT IS MEASURED HERE IS WHAT REQUESTS ACTUALLY HANDS ITS TRANSPORT. A recording adapter
is mounted where the socket would be, so each assertion reads the ``proxies`` requests
passed on after merging the request, the session and the environment -- the value that
decides where the bytes go -- rather than an attribute that only describes an intention.
Nothing here opens a socket.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

import src.ingest.airplane as ap
from src.ingest import EthicalFetcher, activate_kill_switch, clear_kill_switch
from src.safety import fetcher as fetcher_mod
from src.safety.fetcher import (
    NO_PROXY_REFUSAL,
    NetworkBlocked,
    TransportUnavailable,
    _with_stream_isolation,
    following_fetcher,
    guarded_session,
    make_fetcher,
    shard_host_to_proxy,
)

POOL = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051", "socks5h://127.0.0.1:9052"]
SINGLE = "socks5h://127.0.0.1:9150"

#: One URL per family the shared session serves.
URLS = (
    "https://en.wikipedia.org/w/api.php?action=query",
    "https://stream.wikimedia.org/v2/stream/recentchange",
    "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2",
    "https://download.geofabrik.de/europe/monaco-latest.osm.pbf",
    "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL",
    "https://html.duckduckgo.com/html/",
    "https://ollama.com/install.sh",
)

ROOT = Path(__file__).resolve().parents[1]


class _Recorder(BaseAdapter):
    """Stands where the socket would be and records what requests hands it."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, dict]] = []

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.sent.append((request.url, dict(proxies or {})))
        resp = requests.models.Response()
        resp.status_code = 200
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp._content = b"<html><body>ok</body></html>"
        resp._content_consumed = True  # iter_content replays _content; there is no raw
        resp.encoding = "utf-8"
        resp.url = request.url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


def _recorded(session: requests.Session) -> _Recorder:
    rec = _Recorder()
    session.mount("https://", rec)
    session.mount("http://", rec)
    return rec


@pytest.fixture()
def settings_env(monkeypatch, tmp_path):
    """A clean settings store and no transport variables; each test sets its own."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    for name in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    # A test-local cache, so one test's fetchers never answer another's call.
    monkeypatch.setattr(fetcher_mod, "_FOLLOWING", {})
    return monkeypatch


# --------------------------------------------------------------------------- #
# 1. The shared session honours the pool
# --------------------------------------------------------------------------- #
def test_a_pool_alone_sends_every_request_through_its_hosts_pool_member(settings_env):
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXIES", ",".join(POOL))
    s = guarded_session(isolation_token="dl-1")
    rec = _recorded(s)
    for url in URLS:
        s.get(url, timeout=5)
    assert len(rec.sent) == len(URLS)
    for url, proxies in rec.sent:
        host = urlparse(url).hostname
        want = _with_stream_isolation(shard_host_to_proxy(host, POOL), "dl-1")
        assert proxies.get("https") == want and proxies.get("http") == want, (
            f"{url} left through {proxies!r}, not its pool member {want!r}"
        )


def test_a_host_reaches_the_same_pool_member_whichever_path_fetches_it(settings_env):
    """The shared session shards exactly as the EthicalFetcher does, so a host's
    endpoint does not depend on which of the two code paths asked for it."""
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXIES", ",".join(POOL))
    s = guarded_session()
    rec = _recorded(s)
    article_path = EthicalFetcher(min_interval_s=0.0, proxy_pool=POOL)
    for url in URLS:
        s.get(url, timeout=5)
    for url, proxies in rec.sent:
        host = urlparse(url).hostname
        assert proxies["https"] == article_path._effective_base_proxy(host)


def test_the_pool_takes_precedence_over_the_single_proxy_as_it_does_for_articles(settings_env):
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXY", SINGLE)
    settings_env.setenv("OO_HTTP_PROXIES", ",".join(POOL))
    s = guarded_session()
    rec = _recorded(s)
    s.get(URLS[0], timeout=5)
    assert rec.sent[0][1]["https"] in POOL
    assert make_fetcher()._proxy_pool == POOL


def test_a_caller_that_passes_empty_proxies_still_leaves_through_the_pool(settings_env):
    """The session-level fallback is a pool member too, so ``proxies={}`` -- which the
    per-request sharding leaves alone -- cannot reach a direct connection."""
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXIES", ",".join(POOL))
    s = guarded_session()
    rec = _recorded(s)
    s.get(URLS[0], timeout=5, proxies={})
    assert rec.sent[0][1]["https"] in POOL


def test_the_single_proxy_path_is_unchanged(settings_env):
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXY", SINGLE)
    s = guarded_session(isolation_token="t")
    rec = _recorded(s)
    s.get(URLS[0], timeout=5)
    assert rec.sent[0][1]["https"] == _with_stream_isolation(SINGLE, "t")


def test_transparent_mode_is_unchanged(settings_env):
    settings_env.setenv("OO_HTTP_PROXY", SINGLE)  # stored, but the mode is transparent
    s = guarded_session()
    assert not s.proxies and s.proxy_pool == () and s.transport_refusal is None


# --------------------------------------------------------------------------- #
# 2. No usable transport is a named refusal, never a direct connection
# --------------------------------------------------------------------------- #
def test_protected_mode_with_no_proxy_refuses_by_name_and_sends_nothing(settings_env):
    settings_env.setenv("OO_FETCH_MODE", "protected")
    s = guarded_session()
    rec = _recorded(s)
    for verb in (s.get, s.head):
        with pytest.raises(TransportUnavailable, match="no proxy is configured"):
            verb(URLS[0], timeout=5)
    assert rec.sent == [], "a refused request must never reach the transport"
    with pytest.raises(TransportUnavailable) as exc:
        make_fetcher()
    assert str(exc.value) == NO_PROXY_REFUSAL


def test_the_refusal_is_a_connection_error_and_never_reads_as_airplane_mode():
    """Callers already treat "the proxy did not answer" as wait-and-retry, never as a
    reason to go direct; the refusal takes that road. It must not be a NetworkBlocked,
    which callers report as the operator's airplane switch."""
    assert issubclass(TransportUnavailable, requests.exceptions.ConnectionError)
    assert not issubclass(TransportUnavailable, NetworkBlocked)


def test_a_pool_with_a_non_socks_member_is_refused_whole(settings_env):
    """``save_settings`` refuses to store such a pool; the environment and a hand-edited
    file do not pass through it, so both factories refuse it again, by name."""
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXIES", "socks5h://127.0.0.1:9050,http://127.0.0.1:8118")
    s = guarded_session()
    rec = _recorded(s)
    with pytest.raises(TransportUnavailable, match="not a SOCKS proxy"):
        s.get(URLS[0], timeout=5)
    assert rec.sent == []
    with pytest.raises(TransportUnavailable, match="not a SOCKS proxy"):
        make_fetcher()


def test_the_kill_switch_is_named_before_the_transport(settings_env):
    settings_env.setenv("OO_FETCH_MODE", "protected")  # and no proxy
    activate_kill_switch()  # the autouse fixture clears it after the test
    s = guarded_session()
    with pytest.raises(NetworkBlocked):
        s.get(URLS[0], timeout=5)


def test_the_hazard_relay_reports_the_refusal_per_feed_and_never_raises(settings_env):
    """``fetch_hazards`` promises that one bad feed lands in ``failures`` and nothing raises,
    and the route over it promises no 500. A refusal at construction is a failed feed."""
    from src.api.hazards import _FEEDS, fetch_hazards

    settings_env.setenv("OO_FETCH_MODE", "protected")  # and no proxy
    items, failures = fetch_hazards()
    assert items == []
    assert [f.split(":")[0] for f in failures] == list(_FEEDS)
    assert all(f"TransportUnavailable: {NO_PROXY_REFUSAL}" in f for f in failures)


# --------------------------------------------------------------------------- #
# 3. The long-lived fetchers follow the setting
# --------------------------------------------------------------------------- #
def test_the_following_fetcher_follows_a_switch_to_protected_mode_and_back(settings_env):
    from src.safety.settings import GENERIC_USER_AGENT, save_settings

    before = following_fetcher("t")
    assert before.proxy is None
    assert following_fetcher("t") is before, "kept while the transport is unchanged"

    save_settings({"fetch_mode": "protected", "http_proxy": SINGLE})
    during = following_fetcher("t")
    assert during is not before
    assert during.proxy == SINGLE and during.user_agent == GENERIC_USER_AGENT

    save_settings({"fetch_mode": "transparent"})
    after = following_fetcher("t")
    assert after is not during and after.proxy is None


def test_the_three_api_fetchers_carry_protected_mode_set_after_import(settings_env):
    """The defect itself: import first (as the app does, before unlock), then switch."""
    import src.api.hazards  # noqa: F401 - imported before the switch, as the app does
    import src.api.ingestion as ingestion
    import src.api.markets  # noqa: F401
    from src.safety.settings import save_settings

    save_settings({"fetch_mode": "protected", "http_proxy": SINGLE})
    assert ingestion.get_fetcher().proxy == SINGLE
    assert following_fetcher("markets").proxy == SINGLE
    assert following_fetcher("hazards").proxy == SINGLE


def _import_time_calls(path: Path) -> list[int]:
    """Lines where ``path`` calls a fetcher factory outside any function body: at module
    level or directly in a class body, i.e. at import time."""
    factories = {"make_fetcher", "guarded_session", "following_fetcher", "EthicalFetcher"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []

    def visit(node: ast.AST, in_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            inside = in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if not inside and isinstance(child, ast.Call):
                fn = child.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if name in factories:
                    hits.append(child.lineno)
            visit(child, inside)

    visit(tree, False)
    return hits


def test_no_module_builds_a_fetcher_at_import_time():
    """A fetcher built at import reads the settings before an encrypted store is
    unlocked, and keeps what it read. The guard walks every module in ``src``."""
    offenders = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in sorted((ROOT / "src").rglob("*.py"))
        for line in _import_time_calls(path)
    ]
    assert offenders == [], (
        "these build a fetcher at import time, so they never see protected mode; "
        "call src.safety.fetcher.following_fetcher(<owner>) inside the function instead: "
        + ", ".join(offenders)
    )


def test_the_import_time_guard_sees_the_shapes_it_exists_for(tmp_path):
    """The guard is only as good as its parser: prove it on the defect's own shape, a
    class attribute, and a call nested in an expression, and prove a function body and
    a lambda stay clean."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from src.safety.fetcher import make_fetcher, guarded_session\n"
        "_fetcher = make_fetcher()\n"
        "class Holder:\n"
        "    session = guarded_session()\n"
        "TABLE = {'f': fetcher_mod.make_fetcher()}\n"
        "def later():\n"
        "    return make_fetcher()\n"
        "LAZY = lambda: make_fetcher()\n",
        encoding="utf-8",
    )
    assert _import_time_calls(sample) == [2, 4, 5]


# --------------------------------------------------------------------------- #
# 4. An environment proxy variable never replaces the operator's proxy
# --------------------------------------------------------------------------- #
#: What a system-wide proxy variable points at on the machines this protects.
ENV_PROXY = "http://10.9.8.7:3128"


@pytest.fixture()
def env_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, ENV_PROXY)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    return ENV_PROXY


@pytest.fixture()
def public_dns():
    """``news.test`` answers a public address, through the production hook (as
    ``tests/test_ssrf_connect_guard.py`` does), so the article fetcher's own target
    guard passes and the request reaches the recording adapter."""
    was_installed = ap.is_installed()
    saved = ap._orig_getaddrinfo

    def _resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == "news.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return saved(host, port, *args, **kwargs)

    ap._orig_getaddrinfo = _resolver  # type: ignore[assignment]
    ap.ensure_connect_guard_installed()
    clear_kill_switch()
    try:
        yield
    finally:
        ap._orig_getaddrinfo = saved  # type: ignore[assignment]
        if not was_installed:
            ap.uninstall_airplane_socket_guard()


def test_the_shared_session_keeps_the_operators_proxy_over_an_environment_one(settings_env, env_proxy):
    settings_env.setenv("OO_FETCH_MODE", "protected")
    settings_env.setenv("OO_HTTP_PROXY", SINGLE)
    s = guarded_session()
    rec = _recorded(s)
    s.get(URLS[0], timeout=5)
    assert rec.sent[0][1]["https"] == SINGLE, rec.sent


def test_requests_itself_lets_the_environment_beat_a_session_proxy(env_proxy):
    """The premise, measured on the installed requests rather than recalled, so a
    change in requests' precedence shows up here first."""
    s = requests.Session()
    s.proxies = {"http": SINGLE, "https": SINGLE}
    rec = _recorded(s)
    s.get(URLS[0], timeout=5)
    assert rec.sent[0][1]["https"] == ENV_PROXY
    s.get(URLS[0], timeout=5, proxies={"http": SINGLE, "https": SINGLE})
    assert rec.sent[1][1]["https"] == SINGLE


@pytest.mark.parametrize(
    ("proxy", "isolation"),
    [("http://127.0.0.1:8118", "1"), (SINGLE, "0")],
    ids=["http-proxy-cannot-isolate", "socks-with-isolation-off"],
)
def test_the_article_fetcher_keeps_the_operators_proxy_over_an_environment_one(
    monkeypatch, env_proxy, public_dns, proxy, isolation
):
    """The two cases where the fetcher used to leave the choice to ``session.proxies``."""
    monkeypatch.setenv("OO_TOR_STREAM_ISOLATION", isolation)
    f = EthicalFetcher(respect_robots=False, min_interval_s=0.0, timeout=5, proxy=proxy)
    rec = _recorded(f.session)
    f.fetch("https://news.test/story")
    assert rec.sent, "the fetch never reached the transport"
    assert all(p["https"] == proxy for _, p in rec.sent), rec.sent


def test_the_preflight_side_door_carries_the_hosts_proxy(monkeypatch, env_proxy, public_dns):
    """``src.monitoring.preflight`` calls ``_guarded_redirect_get`` with no mapping."""
    monkeypatch.setenv("OO_TOR_STREAM_ISOLATION", "1")
    f = EthicalFetcher(respect_robots=False, min_interval_s=0.0, timeout=5, proxy=SINGLE)
    rec = _recorded(f.session)
    f._guarded_redirect_get("https://news.test/robots.txt")
    assert rec.sent[0][1]["https"] == _with_stream_isolation(SINGLE, "news.test")


def test_the_connect_guard_allowlists_the_proxy_requests_actually_uses(env_proxy):
    """``_request_proxy_endpoints`` must agree with requests about which proxy a request
    goes through; it read session over environment, the reverse of requests."""
    f = EthicalFetcher(respect_robots=False, min_interval_s=0.0, timeout=5)
    f.session.proxies = {"https": SINGLE}
    rec = _recorded(f.session)
    f.session.get(URLS[0], timeout=5)
    used = rec.sent[0][1]["https"]
    assert f._request_proxy_endpoints(URLS[0], None)["https"] == used == ENV_PROXY
    explicit = {"http": SINGLE, "https": SINGLE}
    f.session.get(URLS[0], timeout=5, proxies=dict(explicit))
    assert f._request_proxy_endpoints(URLS[0], explicit)["https"] == rec.sent[1][1]["https"] == SINGLE
