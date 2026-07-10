"""Opt-in in-memory rollup serve for windowed top_terms (scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the opt-in serve is SAFE and FAITHFUL: off by default the windowed query is the
untouched live path; opted-in-but-not-built falls back to live; opted-in-and-built serves
the SAME values the live query would (order aside — ties may differ between engines) and
discloses the served source via a ``basis`` block. The fallback-to-live guarantee is what
makes it safe to ship off-by-default.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, rollup_serve
from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

_WIDE = 100_000  # a window covering the whole fixture (days)


@pytest.fixture()
def session():
    e = create_engine("sqlite:///:memory:", future=True,
                      connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The federal budget dominated the Senate; sanctions on Russia loomed.",
        "Russia and sanctions returned as the federal budget debate widened.",
        "Climate policy and drought reached the Senate committee on the budget.",
        "A pandemic vaccine plan and the federal budget met resistance.",
    ]
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=t, hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2024, 3, 1 + i, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


@pytest.fixture(autouse=True)
def _reset_serve_state():
    # The rollup serve is a PROCESS-GLOBAL singleton and its build runs on a daemon thread;
    # because the serve is auto-on whenever duckdb is available, ANY test across the suite that
    # runs a windowed top_terms/trending can leave a background _build_and_swap in flight that
    # later swaps _STATE (con/bind/built_at) out from under a test HERE — a stale-serve test
    # then observes a FRESH build and flakes (order-dependent, exposed by a base move). So drain
    # any in-flight build (wait out _BUILD_LOCK) and clear the singleton BOTH before and after
    # each test, not just after.
    def _drain_and_clear():
        if rollup_serve._BUILD_LOCK.acquire(timeout=30):
            rollup_serve._BUILD_LOCK.release()
        con = rollup_serve._STATE.get("con")
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        rollup_serve._STATE.update(
            {"con": None, "built_at": 0.0, "rows": 0, "bind": None,
             "token": None, "pending": False, "checked_at": 0.0}
        )

    _drain_and_clear()
    yield
    _drain_and_clear()


def _canon(res):
    """Order-insensitive value comparison (ties may order differently across engines)."""
    return sorted((t["normalized"], t["mentions"], t["articles"]) for t in res["terms"])


def test_forced_off_uses_the_live_path_unchanged(session, monkeypatch):
    # OO_COLUMNAR_SERVE=0 is the explicit deployment override to disable the serve.
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    assert rollup_serve.serve_mode() == "forced-off"
    assert rollup_serve.serve_enabled() is False
    out = q.top_terms(session, days=_WIDE, group=False, limit=20)
    assert "basis" not in out, "no rollup involvement when forced off"
    assert out["terms"], "the live windowed path still returns results"


def test_auto_mode_is_on_by_default_when_duckdb_available(session, monkeypatch):
    # Field ask 2026-07-02: automatic, not a manual env var. With duckdb present (this
    # module is skipped otherwise) and no env override, the serve enables itself.
    monkeypatch.delenv("OO_COLUMNAR_SERVE", raising=False)
    assert rollup_serve.serve_mode() == "auto"
    assert rollup_serve.serve_enabled() is True
    assert rollup_serve.status()["mode"] == "auto"


def test_opted_in_but_not_built_falls_back_to_live(session, monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    # nothing built yet -> serve returns None -> live path (no basis)
    out = q.top_terms(session, days=_WIDE, group=False, limit=20)
    assert "basis" not in out
    assert out["terms"]


def test_opted_in_and_built_serves_the_same_values_with_a_basis(session, monkeypatch):
    # A limit large enough to include EVERY fixture term, so there is no arbitrary tie at
    # the top-N cutoff (where the two engines may order ties differently) — this isolates
    # the value parity that actually matters.
    live = q.top_terms(session, days=_WIDE, group=False, limit=100)  # default off

    # Build the process singleton from THIS session (bypass the background thread) + opt in.
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time()
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")

    served = q.top_terms(session, days=_WIDE, group=False, limit=100)
    assert served.get("basis", {}).get("source") == "columnar-rollup"
    assert served["basis"]["as_of"], "the served response discloses its as-of build time"
    # SAME values the live query returns (order aside).
    assert _canon(served) == _canon(live)


def test_trending_served_matches_live_and_discloses_basis(session, monkeypatch):
    # trending() sums recent/prior windows from the mention table (the freeze). Wiring it
    # also accelerates trending_windows (Home), which calls trending per window. A wide
    # window covers the whole fixture; mentions are exact so the scored output matches.
    kw = dict(window_days=_WIDE, baseline_days=_WIDE, min_recent=1, limit=100)
    live = q.trending(session, **kw)  # default off

    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time()
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")

    served = q.trending(session, **kw)
    assert served.get("basis", {}).get("source") == "columnar-rollup"

    def canon(res):
        return sorted((t["normalized"], t["recent"], t["prior"]) for t in res["terms"])

    assert canon(served) == canon(live)


def test_per_country_never_uses_the_rollup(session, monkeypatch):
    # The rollup has no country dimension; a per-country query must stay on the live path.
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time()
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")

    out = q.top_terms(session, days=_WIDE, country="fr", group=False, limit=20)
    assert "basis" not in out, "per-country falls back to the live (country-aware) query"


def test_corpus_wide_is_never_touched(session, monkeypatch):
    # No days + no country = the counter path; the rollup serve must not interfere.
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time()
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")

    out = q.top_terms(session, group=True, limit=20)  # corpus-wide
    assert "basis" not in out
    assert out["terms"]


# ------------------------- D3: serve-previous-during-rebuild ------------------------- #


def test_serves_previous_rollup_stale_but_disclosed_during_rebuild(session, monkeypatch):
    """While a rebuild runs, the PREVIOUS in-memory rollup is served — the real previous-build
    numbers with as_of visible — NOT a live 21M-mention scan; basis discloses it stale. The
    D3 regression guard: this must never quietly regress into a live scan during a rebuild."""
    kw = dict(window_days=_WIDE, baseline_days=_WIDE, min_recent=1, limit=100)
    live = q.trending(session, **kw)  # default off -> the live numbers

    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time() - (rollup_serve._BACKSTOP_S + 1000)  # STALE
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    # A rebuild would run over the PRODUCTION store; in a test just record that it was asked.
    triggered: list[int] = []
    monkeypatch.setattr(rollup_serve, "_trigger_build_async", lambda: triggered.append(1))

    served = q.trending(session, **kw)
    assert served["basis"]["source"] == "columnar-rollup"
    assert served["basis"]["stale"] is True, "the served rollup is disclosed stale"
    assert served["basis"]["as_of"], "the previous build's as_of is visible"
    assert served["basis"]["age_seconds"] >= rollup_serve._BACKSTOP_S
    assert "PREVIOUS build" in served["basis"]["note"]

    def canon(res):
        return sorted((t["normalized"], t["recent"], t["prior"]) for t in res["terms"])

    assert canon(served) == canon(live), "the previous build's REAL numbers, never a blend"
    assert triggered, "a rebuild was triggered while the stale rollup kept serving"


def test_trending_windows_surfaces_the_rollup_basis(session, monkeypatch):
    """trending_windows (the Home poll the field measured at 467 s cold) must SURFACE the
    stale-but-disclosed rollup basis, not drop it — otherwise the staleness never reaches the
    endpoint that is actually polled."""
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time() - (rollup_serve._BACKSTOP_S + 500)  # stale
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    monkeypatch.setattr(rollup_serve, "_trigger_build_async", lambda: None)

    tw = q.trending_windows(session, limit=10)
    assert len(tw["windows"]) == 3
    assert tw["basis"]["source"] == "columnar-rollup"
    assert tw["basis"]["stale"] is True, "the Home poll discloses the stale rollup"


def test_no_previous_build_falls_back_to_live_never_the_rollup(session, monkeypatch):
    """D3 keeps fallback-to-live when there is NO previous build: the serve primitives return
    None (never a partial/empty rollup answer) and the caller runs the live query."""
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    rollup_serve._STATE.update({"con": None, "built_at": 0.0, "bind": None})
    # Don't spawn a background build in the test; just confirm the None fallback.
    monkeypatch.setattr(rollup_serve, "_trigger_build_async", lambda: None)
    assert rollup_serve.windowed_counts(session, lo=date(2000, 1, 1), hi=date(2100, 1, 1)) is None
    assert rollup_serve.windowed_rows(session, days=_WIDE) is None
    out = q.trending(session, window_days=_WIDE, baseline_days=_WIDE, min_recent=1, limit=20)
    assert "basis" not in out, "no previous build -> the live path, no rollup basis"
    assert out["terms"]


def test_rollup_never_served_to_a_different_database(session, monkeypatch):
    """Bind-awareness stays sacred: a rollup built over ONE engine is never served to a
    request on ANOTHER (a second corpus). Two engines/sessions — the shape production's test
    fixtures take, and the exact wrong-corpus hazard the _same_bind guard exists for."""
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, session)  # built over `session`'s engine
    rollup_serve._STATE["con"] = con
    rollup_serve._STATE["bind"] = session.get_bind()
    rollup_serve._STATE["built_at"] = time.time()
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    monkeypatch.setattr(rollup_serve, "_trigger_build_async", lambda: None)

    e2 = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(e2)
    s2 = sessionmaker(bind=e2, future=True)()
    s2.add(Source(name="S2", domain="y.test", country="fr"))
    s2.commit()
    try:
        assert rollup_serve.windowed_counts(s2, lo=date(2000, 1, 1), hi=date(2100, 1, 1)) is None
        assert rollup_serve.windowed_rows(s2, days=_WIDE) is None
        out = q.trending(s2, window_days=_WIDE, baseline_days=_WIDE, min_recent=1, limit=20)
        assert "basis" not in out, "the wrong-engine request must never see the rollup basis"
    finally:
        s2.close()


def test_basis_discloses_stale_and_rebuilding():
    """The basis disclosure itself (D3): stale + age when the build is old, rebuilding when a
    build is in flight."""
    fresh = rollup_serve.basis(7)
    assert fresh["stale"] is False and fresh["rebuilding"] is False  # nothing built

    rollup_serve._STATE["built_at"] = time.time() - (rollup_serve._BACKSTOP_S + 100)
    b = rollup_serve.basis(7)
    assert b["stale"] is True and b["age_seconds"] >= rollup_serve._BACKSTOP_S
    assert "PREVIOUS build" in b["note"]

    acquired = rollup_serve._BUILD_LOCK.acquire(blocking=False)
    try:
        assert rollup_serve.basis(7)["rebuilding"] is True
    finally:
        if acquired:
            rollup_serve._BUILD_LOCK.release()
