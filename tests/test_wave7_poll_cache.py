"""Wave 7 Q — the background-refreshed memo cache for the POLLED alert strip (Item 8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-07-08, Item 8 (P0): ``GET /api/signals/alerts`` was recomputing the
45-day space-time convergence scan on EVERY poll (p50 23.7 s, p95 60 s, 156 calls) —
the single-worker death-spiral driver. ``src.analytics.poll_cache`` memoises the result
and refreshes it in the BACKGROUND, so a poll is served instantly and the scan never runs
on the request thread beyond the first cold call.

These tests prove the honesty + safety non-negotiables:
  * the cached value EQUALS a fresh live ``compute_alerts`` (same real value, just cached);
  * a stale cache is refreshed by the BACKGROUND path (``refresh_alerts``, invoked by
    ``warm_cache``);
  * a cold/empty cache falls back to a live compute;
  * the payload carries a visible ``as_of`` and NO score key (recursive key-walk);
  * BIND-AWARENESS: a memo built over one DB never serves another (the poll_cache analog
    of the Wave-1 rollup regression), for BOTH poll_cache and rollup_serve.

Imports fastapi/sqlalchemy only at module scope (core deps) -> runs in CI; the duckdb
rollup regression is gated per-test.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import poll_cache
from src.analytics.alerts import compute_alerts
from src.database.models import (
    Article,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
    Watch,
    WatchMatch,
)

# The cache-freshness disclosure keys poll_cache adds on top of the raw compute_alerts
# payload — stripped before an equality comparison against a direct live compute.
_DECOR = {"as_of", "cache_age_s", "cached", "cache_note"}


def _fresh_session():
    """A session on its OWN in-memory engine (a bind distinct from every other one)."""
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    """Point the hazard snapshot store at an empty tmp dir so alerts are deterministic
    (no leftover snapshot from another test bleeds into the info/urgent tiers)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Never leak the process-lifetime memo between tests, and keep the TTL generous so
    the cached-equality assertions never trip the stale self-heal path."""
    monkeypatch.setenv("OO_ALERTS_CACHE_TTL_S", "600")
    poll_cache.clear()
    yield
    poll_cache.clear()


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seed_convergence(s):
    """3 articles, 2 distinct sources, one place + one recent window -> one convergence."""
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    on = date.today() - timedelta(days=5)
    for aid, src in ((101, 1), (102, 2), (103, 1)):
        s.add(Article(
            id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
            source_id=src, title=f"Story {aid}", content="event body text", hash=f"h{aid}",
            language="en", published_at=datetime.now(UTC), created_at=datetime.now(UTC),
        ))
        s.add(ArticleMentionedPlace(
            article_id=aid, name="Gaza", country="ps", kind="city",
            mentions=1, lat=31.5, lon=34.45, extractor="lexical-v1",
        ))
        s.add(ArticleMentionedDate(
            article_id=aid, mentioned_on=on, precision="day", extractor="dateextract",
            status="candidate",
        ))
    s.commit()
    return [101, 102, 103]


def _seed_fired_watch(s, article_ids):
    now = _now_naive()
    w = Watch(name="Flood watch", query="flood", threshold=3, window_days=7,
              enabled=True, last_matched_at=now)
    s.add(w)
    s.flush()
    s.add(WatchMatch(watch_id=w.id, matched_at=now, n_articles=len(article_ids),
                     new_articles=2, article_ids=json.dumps(article_ids)))
    s.commit()
    return w.id


def _strip(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _DECOR}


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for it in obj:
            yield from _walk_keys(it)


# --------------------------------------------------------------------------- #
#  1) The cached value EQUALS a fresh live compute — just memoised.
# --------------------------------------------------------------------------- #
def test_cached_alerts_equals_a_fresh_live_compute(data_dir):
    s = _fresh_session()
    ids = _seed_convergence(s)
    _seed_fired_watch(s, [901, 902])

    r1 = poll_cache.get_alerts(s)  # cold -> live compute, populates
    r2 = poll_cache.get_alerts(s)  # served from the memo
    live = compute_alerts(
        s, within_hours=48, hazard_max_age_hours=48, convergence_lookback_days=45
    )

    assert r1["cached"] is False, "first call is a live compute"
    assert r2["cached"] is True, "second poll is served from the memo (no recompute)"
    # The cached payload is byte-identical to a fresh live compute (only the freshness
    # disclosure differs) — a REAL value, just memoised. Never fabricated/summarised.
    assert _strip(r1) == live
    assert _strip(r2) == live
    # Sanity: the real signals flowed through (watch + convergence tiers populated).
    assert set(r1["tiers"]["watch"]["article_ids"]) == {901, 902}
    assert set(r1["tiers"]["info"]["article_ids"]) == set(ids)


# --------------------------------------------------------------------------- #
#  2) A stale cache is refreshed by the BACKGROUND path (what warm_cache invokes).
# --------------------------------------------------------------------------- #
def test_stale_cache_is_refreshed_by_the_background_path(data_dir):
    s = _fresh_session()
    r0 = poll_cache.get_alerts(s)  # cold -> caches; no watch yet
    assert r0["cached"] is False
    assert len(r0["tiers"]["watch"]["watches"]) == 0

    # The corpus changes: a watch fires. Then age the memo so it is stale.
    _seed_fired_watch(s, [901, 902])
    key = poll_cache._key(48, 48, 45)
    with poll_cache._LOCK:
        poll_cache._CACHE[key]["built_at"] = 1.0  # ancient -> stale

    # THE BACKGROUND PATH refreshes it (warm_cache calls refresh_alerts; run it
    # synchronously over the same session to keep the test deterministic — no threads).
    poll_cache.refresh_alerts(s)

    r1 = poll_cache.get_alerts(s)
    assert r1["cached"] is True, "served from the refreshed memo"
    assert len(r1["tiers"]["watch"]["watches"]) == 1, "the background refresh picked up the new watch"
    assert r1["cache_age_s"] < 30, "the entry was rebuilt with a fresh built_at"


# --------------------------------------------------------------------------- #
#  3) A cold/empty cache falls back to a live compute.
# --------------------------------------------------------------------------- #
def test_cold_cache_falls_back_to_live(data_dir):
    s = _fresh_session()
    _seed_fired_watch(s, [7, 8])
    poll_cache.clear()  # explicitly cold

    out = poll_cache.get_alerts(s)
    assert out["cached"] is False, "a cold cache computes live"
    live = compute_alerts(
        s, within_hours=48, hazard_max_age_hours=48, convergence_lookback_days=45
    )
    assert _strip(out) == live
    assert len(out["tiers"]["watch"]["watches"]) == 1


# --------------------------------------------------------------------------- #
#  4) The payload carries a visible as_of and NO score key (recursive key-walk).
# --------------------------------------------------------------------------- #
def test_payload_carries_as_of_and_no_score_key(data_dir):
    s = _fresh_session()
    _seed_convergence(s)
    out = poll_cache.get_alerts(s)

    assert out.get("as_of"), "a visible as_of must disclose the memo's age"
    assert "cache_age_s" in out and out["cache_age_s"] >= 0
    assert out["cached"] in (True, False)
    # The method/caveat still describe a transparent LOCAL rule (memoisation adds an
    # as_of, it does not change WHAT is computed / claim a network fetch).
    assert out["method"] and "no network" in out["method"].lower()
    assert "network" in out["cache_note"].lower(), "the memo note must disclose it is not fetched"

    # No composite score ANYWHERE — walk the dict KEYS recursively (the ledger lesson:
    # a no-score test checks field NAMES, never repr(), so the caveat prose "no score"
    # does not trip it).
    bad = ("score", "ranking", "rating")
    for k in _walk_keys(out):
        kl = str(k).lower()
        assert not any(b in kl for b in bad), f"unexpected score-like key: {k!r}"


# --------------------------------------------------------------------------- #
#  5) BIND-AWARENESS (poll_cache): a memo built over one DB never serves another.
# --------------------------------------------------------------------------- #
def test_poll_cache_bind_mismatch_never_serves_another_corpus(data_dir):
    a = _fresh_session()
    _seed_fired_watch(a, [1, 2])  # corpus A has a fired watch
    b = _fresh_session()  # corpus B has none

    ra = poll_cache.get_alerts(a)  # populates the default key under A's bind
    assert len(ra["tiers"]["watch"]["watches"]) == 1

    rb = poll_cache.get_alerts(b)  # SAME param key, DIFFERENT engine -> must not serve A
    assert rb["cached"] is False, "a bind mismatch falls back to a live compute"
    assert len(rb["tiers"]["watch"]["watches"]) == 0, "served B's own (empty) corpus, never A's"


def test_same_bind_gate_is_identity_based():
    a = _fresh_session()
    b = _fresh_session()
    assert poll_cache._same_bind(a, a.get_bind()) is True
    assert poll_cache._same_bind(a, b.get_bind()) is False
    assert poll_cache._same_bind(None, a.get_bind()) is False
    assert poll_cache._same_bind(a, None) is False


# --------------------------------------------------------------------------- #
#  6) The endpoint is served through the memo (dependency_overrides[get_db]).
# --------------------------------------------------------------------------- #
def test_alerts_endpoint_served_through_memo_via_dependency_override(data_dir):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    s = _fresh_session()
    _seed_fired_watch(s, [11, 22])
    poll_cache.clear()

    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            r1 = c.get("/api/signals/alerts").json()
            r2 = c.get("/api/signals/alerts").json()
    finally:
        app.dependency_overrides.pop(get_db, None)

    # The endpoint contract is preserved (all three provider tiers are keys) + the memo
    # disclosure is present.
    assert set(r1["tiers"]) == {"info", "watch", "urgent"}
    assert "never invents urgency" in r1["caveat"]
    assert r1.get("as_of") and r1["cached"] is False
    assert r2["cached"] is True, "the second poll is served from the memo"
    assert _strip(r1) == _strip(r2), "the cached poll is the same real value"
    # The fired watch flowed through (the endpoint used the overridden session, not
    # SessionLocal).
    assert set(r1["tiers"]["watch"]["article_ids"]) == {11, 22}


# --------------------------------------------------------------------------- #
#  7) ITEM 2 REGRESSION — rollup_serve bind mismatch falls back to live (Wave-1).
#     A rollup built over one DB must NEVER serve another corpus's numbers.
# --------------------------------------------------------------------------- #
def test_rollup_serve_bind_mismatch_falls_back_to_live(monkeypatch):
    from src.analytics import columnar

    if not columnar.duckdb_available():
        pytest.skip("duckdb not installed (optional [columnar] extra)")

    from src.analytics import queries as q
    from src.analytics import rollup_serve
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article

    def _seed_corpus(texts):
        s = _fresh_session()
        s.add(Source(id=1, name="S", domain="x.test", country="fr"))
        s.commit()
        ex = BaselineExtractor()
        for i, t in enumerate(texts):
            art = Article(
                url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
                title="T", content=t, hash=f"h{i}", country="fr", language="en",
                published_at=datetime(2024, 3, 1 + i, tzinfo=UTC), created_at=datetime.now(UTC),
            )
            s.add(art)
            s.commit()
            index_article(s, art, extractor=ex)
        return s

    wide = 100_000
    a = _seed_corpus([
        "The federal budget dominated the Senate; sanctions on Russia loomed.",
        "Russia and sanctions returned as the federal budget debate widened.",
    ])
    b = _seed_corpus([
        "Climate policy and drought reached the committee on renewable energy.",
        "A pandemic vaccine plan met resistance from the health ministry.",
    ])

    # Build the process-lifetime rollup over corpus A and pin its bind to A's engine.
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(con, a)
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    try:
        rollup_serve._STATE["con"] = con
        rollup_serve._STATE["bind"] = a.get_bind()
        rollup_serve._STATE["built_at"] = time.time()

        # A same-bind serve DOES use the rollup (basis disclosed) — proves it is wired.
        served_a = q.top_terms(a, days=wide, group=False, limit=100)
        assert served_a.get("basis", {}).get("source") == "columnar-rollup"

        # A DIFFERENT-engine session must fall back to the LIVE query (no basis) and return
        # ITS OWN corpus — never A's rollup numbers (the Wave-1 regression).
        served_b = q.top_terms(b, days=wide, group=False, limit=100)
        assert "basis" not in served_b, "a bind mismatch must fall back to the live query"
        live_b = q.top_terms(b, days=wide, group=False, limit=100)  # bind still mismatched
        b_terms = sorted(t["normalized"] for t in served_b["terms"])
        assert b_terms == sorted(t["normalized"] for t in live_b["terms"])
        # And it is genuinely B's corpus, not A's (disjoint headline terms).
        assert "drought" in b_terms or "energy" in b_terms or "vaccine" in b_terms
        assert "sanctions" not in b_terms

        # The low-level gate agrees: windowed_counts returns None for the mismatched bind.
        assert rollup_serve.windowed_counts(b, lo=date(2000, 1, 1), hi=date.today()) is None
        assert rollup_serve.windowed_rows(b, days=wide) is None
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
        rollup_serve._STATE.update({"con": None, "built_at": 0.0, "rows": 0, "bind": None})
