"""A5 (2026-07-24 throughput brief, C4): the robots.txt verdict cache must
survive a cold EthicalFetcher construction (make_fetcher() builds a BRAND NEW
instance once per collection pass -- see the module-level note next to
_ROBOTS_TTL in src/ingest/__init__.py -- so without persistence the cache was
already being thrown away every pass, not merely across a real app restart).

Reuses the fake-session/response pattern from tests/test_fetcher_limits.py
(a real requests.Session is never constructed, so the SSRF/DNS guard is
inert and only the robots/persistence logic under test runs).
"""

from __future__ import annotations

import json
import time

import pytest

from src.ingest import EthicalFetcher, FetchFailed, RobotsDisallowed, RobotsUnavailable
from src.ingest import _load_persisted_robots as load_persisted_robots


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _Session:
    """Routable fake session; counts robots.txt hits so tests can prove a
    persisted verdict was reused WITHOUT a live re-fetch."""

    def __init__(self):
        self.headers = {}
        self._routes: dict[str, _Resp] = {}
        self.robots_calls = 0

    def route(self, url, **kwargs):
        self._routes[url] = _Resp(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url.endswith("/robots.txt"):
            self.robots_calls += 1
        if url in self._routes:
            return self._routes[url]
        return _Resp(status_code=404, text="not found", url=url)


def _fetcher(session, cache_path, **kw):
    return EthicalFetcher(
        min_interval_s=0.0, session=session, robots_cache_path=cache_path, **kw
    )


PAGE = "https://example.com/article"


# --------------------------------------------------------------------------- #
# The core promise: an in-TTL persisted verdict is reused, no re-fetch.
# --------------------------------------------------------------------------- #


def test_persisted_allow_all_verdict_is_reused_after_a_simulated_restart(tmp_path):
    cache = tmp_path / "robots_cache.json"
    session_a = _Session()
    session_a.route(
        "https://example.com/robots.txt", text="User-agent: *\nAllow: /", content_type="text/plain"
    )
    session_a.route(PAGE, text="<html><body>hi</body></html>")
    fetcher_a = _fetcher(session_a, cache)
    fetcher_a.fetch(PAGE)  # populates + persists the robots decision
    assert session_a.robots_calls == 1
    assert cache.exists()

    # "restart": a BRAND NEW fetcher instance, same cache path, whose session's
    # robots.txt would now DISALLOW everything -- if the persisted verdict is
    # correctly reused, the fetch must still succeed (never re-checking).
    session_b = _Session()
    session_b.route(
        "https://example.com/robots.txt", status_code=403, text="", content_type="text/plain"
    )
    session_b.route(PAGE, text="<html><body>hi again</body></html>")
    fetcher_b = _fetcher(session_b, cache)
    fetcher_b.fetch(PAGE)  # must NOT raise RobotsUnavailable
    assert session_b.robots_calls == 0, "a fresh instance must reuse the in-TTL persisted verdict"


def test_persisted_disallow_all_verdict_is_also_reused_fail_closed(tmp_path):
    """The fail-closed 'disallow everything' decision (a 401/403 robots.txt)
    round-trips too -- reused as a REFUSAL, not silently 'fixed' by a later
    live check."""
    cache = tmp_path / "robots_cache.json"
    session_a = _Session()
    session_a.route("https://example.com/robots.txt", status_code=403, text="")
    fetcher_a = _fetcher(session_a, cache)
    with pytest.raises(RobotsUnavailable):
        fetcher_a.fetch(PAGE)
    assert session_a.robots_calls == 1

    session_b = _Session()
    session_b.route(
        "https://example.com/robots.txt", text="User-agent: *\nAllow: /", content_type="text/plain"
    )  # the site now looks permissive -- must NOT matter, the cache is reused
    fetcher_b = _fetcher(session_b, cache)
    with pytest.raises(RobotsUnavailable):
        fetcher_b.fetch(PAGE)
    assert session_b.robots_calls == 0


# --------------------------------------------------------------------------- #
# NEGATIVE-SPACE: an expired verdict must NEVER be trusted stale.
# --------------------------------------------------------------------------- #


def test_expired_verdict_is_refetched_not_trusted_stale(tmp_path):
    cache = tmp_path / "robots_cache.json"
    # Hand-write an already-EXPIRED allow-all entry (fetched_at far past TTL).
    cache.write_text(
        json.dumps(
            {
                "https://example.com": {
                    "kind": "allow_all",
                    "body": None,
                    "fetched_at": time.time() - 7200,  # 2h ago; TTL is 3600s
                }
            }
        ),
        "utf-8",
    )
    session = _Session()
    # The site is now RESTRICTIVE -- a stale trust would wrongly permit the fetch.
    session.route("https://example.com/robots.txt", status_code=403, text="")
    fetcher = _fetcher(session, cache)
    with pytest.raises(RobotsUnavailable):
        fetcher.fetch(PAGE)
    assert session.robots_calls == 1, "an expired persisted verdict must be re-fetched, not reused"


def test_a_stale_persisted_allow_never_survives_a_real_site_restriction_change(tmp_path):
    """The brief's own NEGATIVE-SPACE phrasing: a stale (past-TTL) persisted
    entry must never allow a fetch that should re-check -- pin the exact
    disallow-now-enforced outcome, not just 'a re-fetch happened'."""
    cache = tmp_path / "robots_cache.json"
    cache.write_text(
        json.dumps(
            {
                "https://example.com": {
                    "kind": "parsed",
                    "body": "User-agent: *\nAllow: /",
                    "fetched_at": time.time() - 9999,
                }
            }
        ),
        "utf-8",
    )
    session = _Session()
    session.route(
        "https://example.com/robots.txt",
        text="User-agent: *\nDisallow: /article",
        content_type="text/plain",
    )
    fetcher = _fetcher(session, cache)
    with pytest.raises(RobotsDisallowed):
        fetcher.fetch(PAGE)


# --------------------------------------------------------------------------- #
# Resilience + opt-out.
# --------------------------------------------------------------------------- #


def test_a_corrupt_cache_file_never_breaks_construction_or_the_fetch(tmp_path):
    cache = tmp_path / "robots_cache.json"
    cache.write_text("{not valid json", "utf-8")
    session = _Session()
    session.route(
        "https://example.com/robots.txt", text="User-agent: *\nAllow: /", content_type="text/plain"
    )
    session.route(PAGE, text="<html><body>ok</body></html>")
    fetcher = _fetcher(session, cache)  # must not raise on construction
    fetcher.fetch(PAGE)  # must fall back to a live fetch
    assert session.robots_calls == 1


def test_persistence_can_be_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_ROBOTS_CACHE_PERSIST", "0")
    cache = tmp_path / "robots_cache.json"
    session = _Session()
    session.route(
        "https://example.com/robots.txt", text="User-agent: *\nAllow: /", content_type="text/plain"
    )
    session.route(PAGE, text="<html><body>ok</body></html>")
    fetcher = _fetcher(session, cache)
    fetcher.fetch(PAGE)
    assert not cache.exists(), "persistence must be fully inert when disabled"


# --------------------------------------------------------------------------- #
# The wall-clock <-> monotonic translation itself (the correctness-critical
# part: a raw monotonic value would be meaningless across a real restart).
# --------------------------------------------------------------------------- #


def test_load_persisted_robots_translates_wall_clock_ttl_into_the_current_monotonic_frame(
    tmp_path,
):
    cache = tmp_path / "robots_cache.json"
    fetched_at = 1_000_000.0  # an arbitrary wall-clock instant
    cache.write_text(
        json.dumps(
            {"https://example.com": {"kind": "allow_all", "body": None, "fetched_at": fetched_at}}
        ),
        "utf-8",
    )
    # 600s later, in a FRESH process whose monotonic clock starts at some
    # unrelated arbitrary value (here simulated as 42.0 -- nothing like the
    # wall-clock numbers above, exactly the cross-process reality).
    out = load_persisted_robots(cache, now_monotonic=lambda: 42.0, now_wall=fetched_at + 600)
    assert "https://example.com" in out
    decision, expiry = out["https://example.com"]
    assert decision is not None
    # remaining = 3600 - 600 = 3000; expressed against the fake monotonic 42.0.
    assert expiry == pytest.approx(42.0 + 3000.0)


def test_load_persisted_robots_drops_unknown_shapes_without_raising(tmp_path):
    cache = tmp_path / "robots_cache.json"
    cache.write_text(json.dumps({"https://example.com": {"kind": "mystery"}}), "utf-8")
    assert load_persisted_robots(cache, now_monotonic=time.monotonic) == {}


def test_a_bad_fetch_error_still_persists_as_disallow_all(tmp_path):
    """A network/timeout-style failure during the robots.txt fetch itself must
    fail closed AND persist as disallow_all (never a guessed allow)."""
    cache = tmp_path / "robots_cache.json"

    class _RaisingSession(_Session):
        def get(self, url, timeout=None, allow_redirects=True, **kwargs):
            if url.endswith("/robots.txt"):
                self.robots_calls += 1
                raise FetchFailed("simulated transient network failure")
            return super().get(url, timeout=timeout, allow_redirects=allow_redirects, **kwargs)

    session = _RaisingSession()
    fetcher = _fetcher(session, cache)
    with pytest.raises(RobotsUnavailable):
        fetcher.fetch(PAGE)
    raw = json.loads(cache.read_text("utf-8"))
    assert raw["https://example.com"]["kind"] == "disallow_all"
