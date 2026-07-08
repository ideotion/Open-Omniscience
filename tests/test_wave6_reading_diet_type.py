"""Content-provenance S3 — reading diet BY CONTENT CHANNEL (source_type axis).

The SAME diet/concentration lens as the source-axis ``diet_self_audit`` producer,
applied to the CHANNEL axis (``Source.source_type``): over a window, what SHARE of the
articles you collected each content channel (news/newsletter/wiki/statistics/law/
market/discovery/...) accounts for, with a concentration measure (dominant-channel
share + Gini) and an honest Wilson 95% interval. "How much of my reading is
newsletters vs web vs wiki." A descriptive count, NEVER a quality/credibility score.

Every test uses an ISOLATED in-memory engine (never SessionLocal); the endpoint test
routes the handler through ``app.dependency_overrides[get_db]`` and pops it in a
``finally`` (the ledger's endpoint-test rule). The pure helper runs anywhere; the
endpoint test is gated on the crypto extra (``src.api.main``), so it runs in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.concentration import reading_diet_by_type
from src.analytics.queries import SOURCE_TYPE_UNTYPED, source_type_facets
from src.database.models import Article, Base, Source

try:
    from src.api.main import app  # noqa: F401

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001 - crypto extra/native ext absent in the bare sandbox
    _HAVE_MAIN = False


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _score_like_keys(obj) -> list[str]:
    """Walk the dict KEYS recursively for a forbidden score/ranking field (the ledger's
    no-score check: a caveat legitimately SAYS 'no score', so a naive repr() substring
    check would false-positive — inspect keys, not values)."""
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank":
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


def _session():
    # StaticPool shares ONE in-memory connection across threads, so the endpoint (run
    # off the event loop in the threadpool) sees the seeded tables.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(session, spec, *, aid_start=0):
    """Seed sources + articles. ``spec`` = list of (source_type|None, n_articles, age_days).

    A distinct Source per spec row (so two rows can share a channel to test cross-source
    aggregation). ``age_days`` sets ``created_at`` relative to now for window tests.
    """
    now = datetime.now(UTC)
    aid = aid_start
    for i, (st, n, age) in enumerate(spec):
        src = Source(name=f"S{i}", domain=f"s{i}-{aid_start}.test", source_type=st)
        session.add(src)
        session.flush()
        if st is None:
            # The ORM default 'news' fires on INSERT even for an explicit None; force a
            # genuine NULL the way a restore-merge / wikidata-untyped source has it.
            session.query(Source).filter_by(id=src.id).update({Source.source_type: None})
        for _ in range(n):
            aid += 1
            session.add(
                Article(
                    url=f"https://x.test/{aid}",
                    canonical_url=f"https://x.test/{aid}",
                    source_id=src.id,
                    title=f"t{aid}",
                    content="body",
                    hash=f"{aid:064d}",  # 64-digit, unique per article (ljust '0' collides 1/10)
                    language="en",
                    created_at=now - timedelta(days=age),
                )
            )
    session.commit()
    return session


def _by_channel(payload):
    return {c["source_type"]: c["articles"] for c in payload["channels"]}


# --------------------------------------------------------------------------- #
#  The pure helper (runs anywhere)
# --------------------------------------------------------------------------- #
def test_shares_sum_to_one_across_channels():
    s = _session()
    _seed(s, [("news", 6, 1), ("newsletter", 3, 1), ("wiki", 1, 1)])

    out = reading_diet_by_type(s, days=30)

    assert out["total"] == 10
    assert out["n_channels"] == 3
    assert _by_channel(out) == {"news": 6, "newsletter": 3, "wiki": 1}
    # Every channel's share is its count / the windowed total ...
    shares = {c["source_type"]: c["share"] for c in out["channels"]}
    assert shares["news"] == pytest.approx(0.6)
    assert shares["newsletter"] == pytest.approx(0.3)
    assert shares["wiki"] == pytest.approx(0.1)
    # ... and they sum to exactly 1.0 (a full partition of the window, nothing dropped).
    assert sum(c["share"] for c in out["channels"]) == pytest.approx(1.0)
    # descending order
    assert [c["source_type"] for c in out["channels"]] == ["news", "newsletter", "wiki"]
    s.close()


def test_concentration_gini_and_ci_present_and_no_score():
    s = _session()
    _seed(s, [("news", 30, 1), ("newsletter", 10, 1), ("wiki", 10, 1)])  # total 50, not small-n

    out = reading_diet_by_type(s, days=30)

    # Concentration: dominant-channel share (top_n=1) + a defined Gini (n >= 2).
    assert out["top_n"] == 1
    assert out["top_channels"] == ["news"]
    assert out["top_share"] == pytest.approx(30 / 50)
    assert isinstance(out["gini"], float)
    assert 0.0 <= out["gini"] <= 1.0
    # Honest 95% interval on the dominant-channel share, containing the point estimate.
    ci = out["interval"]
    assert ci is not None
    assert ci["low"] <= out["top_share"] <= ci["high"]
    assert "Wilson" in ci["method"]
    assert out["small_n"] is False
    # Method + caveat present; NO score field anywhere (walk the keys).
    assert "no score" in out["method"].lower()
    assert "never a quality or credibility score" in out["caveat"]
    # The CI honesty non-negotiable is PINNED: the interval is scoped to the corpus, not the
    # world (a future reword can't silently drop this guarantee).
    cav = out["caveat"].lower()
    assert "within your corpus" in cav
    assert "never the world" in cav
    assert _score_like_keys(out) == []
    s.close()


def test_single_channel_reports_100_pct_and_small_n_caveat():
    s = _session()
    _seed(s, [("newsletter", 4, 1)])  # a single channel, and small

    out = reading_diet_by_type(s, days=30)

    assert out["n_channels"] == 1
    assert out["total"] == 4
    assert _by_channel(out) == {"newsletter": 4}
    assert out["channels"][0]["share"] == pytest.approx(1.0)
    assert sum(c["share"] for c in out["channels"]) == pytest.approx(1.0)
    assert out["top_share"] == pytest.approx(1.0)
    # A single channel has no concentration to compare -> the Gini is honestly undefined.
    assert out["gini"] is None
    # The honest small-n / single-channel caveat is present (not hidden).
    assert out["small_n"] is True
    cav = out["caveat"].lower()
    assert "one channel" in cav or "single channel" in cav
    assert "small sample" in cav
    assert _score_like_keys(out) == []
    s.close()


def test_two_sources_same_channel_aggregate_into_one_bucket():
    s = _session()
    # Two distinct SOURCES, both the 'news' channel -> one 'news' bucket of 4.
    _seed(s, [("news", 3, 1), ("news", 1, 1), ("wiki", 2, 1)])

    out = reading_diet_by_type(s, days=30)

    assert _by_channel(out) == {"news": 4, "wiki": 2}
    assert out["total"] == 6
    s.close()


def test_window_excludes_old_articles():
    s = _session()
    _seed(s, [("news", 5, 1), ("wiki", 4, 400)])  # wiki is 400 days old

    recent = reading_diet_by_type(s, days=30)
    assert _by_channel(recent) == {"news": 5}  # wiki excluded from the 30-day window
    assert recent["total"] == 5

    wide = reading_diet_by_type(s, days=3650)  # a window that reaches the old wiki article
    assert _by_channel(wide) == {"news": 5, "wiki": 4}
    assert wide["total"] == 9
    s.close()


def test_untyped_channel_is_its_own_bucket_not_folded_into_news():
    s = _session()
    _seed(s, [("news", 2, 1), (None, 3, 1)])  # None -> a genuine NULL source_type

    out = reading_diet_by_type(s, days=30)

    assert _by_channel(out) == {"news": 2, SOURCE_TYPE_UNTYPED: 3}
    assert out["total"] == 5
    s.close()


def test_empty_window_is_honest_not_a_fabricated_split():
    s = _session()
    _seed(s, [("news", 4, 400)])  # only old articles

    out = reading_diet_by_type(s, days=30)

    assert out["total"] == 0
    assert out["n_channels"] == 0
    assert out["channels"] == []
    assert out["top_share"] is None
    assert out["gini"] is None
    assert out["interval"] is None
    assert out.get("note")  # an honest empty-state note, never a crash or a guessed split
    # 'small_n' means a thin but NON-empty sample; an empty window is not "small", it is empty
    # (the note/caveat say so) -- the field must not conflate the two.
    assert out["small_n"] is False
    assert _score_like_keys(out) == []
    s.close()


def test_window_uses_created_at_not_the_spoofable_published_at():
    """The window is ACQUISITION time (created_at), never the source-controlled published_at:
    a fresh published_at on an OLD created_at is EXCLUDED, and an ancient published_at on a
    RECENT created_at is INCLUDED. Pins the un-spoofable claim by design (not by NULL accident)."""
    s = _session()
    now = datetime.now(UTC)
    src = Source(name="Sp", domain="spoof.test", source_type="news")
    s.add(src)
    s.flush()
    # (created_at age days, published_at age days):
    #   A collected long ago but claims a fresh publish date (the spoof) -> must be EXCLUDED
    #   B collected recently but publish date is ancient                 -> must be INCLUDED
    for i, (c_age, p_age) in enumerate([(400, 1), (1, 400)]):
        s.add(
            Article(
                url=f"https://spoof.test/{i}",
                canonical_url=f"https://spoof.test/{i}",
                source_id=src.id,
                title=f"t{i}",
                content="body",
                hash=f"{i:064d}",
                language="en",
                created_at=now - timedelta(days=c_age),
                published_at=now - timedelta(days=p_age),
            )
        )
    s.commit()

    out = reading_diet_by_type(s, days=30)
    # Only B (recent created_at) is in the 30-day acquisition window; A's fresh published_at
    # does NOT pull it in -> the window is created_at, not published_at.
    assert out["total"] == 1
    assert _by_channel(out) == {"news": 1}
    s.close()


def test_gini_hand_computed_for_equal_channels_is_zero():
    """Two channels with EQUAL counts -> a perfectly even split -> Gini 0.0 (a hand-checkable
    value, so the wiring to the primitive is non-vacuous). CI bounds stay within [0, 1]."""
    s = _session()
    _seed(s, [("news", 5, 1), ("wiki", 5, 1)])

    out = reading_diet_by_type(s, days=30)

    assert out["gini"] == pytest.approx(0.0)
    assert out["top_share"] == pytest.approx(0.5)
    ci = out["interval"]
    assert 0.0 <= ci["low"] <= ci["high"] <= 1.0
    s.close()


def test_channel_counts_match_source_type_facets_over_a_full_window():
    """Consistency with the S2 facet: over a window covering the whole corpus, the diet's
    per-channel counts EQUAL source_type_facets (both normalise identically)."""
    s = _session()
    _seed(s, [("news", 4, 1), ("newsletter", 2, 1), ("statistics", 1, 1), (None, 2, 1)])

    diet = reading_diet_by_type(s, days=3650)
    facet = source_type_facets(s)

    assert _by_channel(diet) == {f["source_type"]: f["articles"] for f in facet["facets"]}
    assert diet["total"] == facet["total"]
    s.close()


# --------------------------------------------------------------------------- #
#  The endpoint (CI — src.api.main needs the crypto extra)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_endpoint_returns_method_caveat_and_no_score():
    from fastapi.testclient import TestClient

    from src.api.main import app as _app
    from src.database.session import get_db

    s = _session()
    _seed(s, [("news", 6, 1), ("newsletter", 3, 1), ("wiki", 1, 1)])

    _app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(_app) as client:
            r = client.get("/api/insights/reading-diet-by-type", params={"days": 30})
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["total"] == 10
            assert {c["source_type"]: c["articles"] for c in data["channels"]} == {
                "news": 6,
                "newsletter": 3,
                "wiki": 1,
            }
            assert sum(c["share"] for c in data["channels"]) == pytest.approx(1.0)
            assert data["method"] and data["caveat"]
            assert _score_like_keys(data) == []

            # A too-short window is an honest empty state, never a 500 or a guess.
            r2 = client.get("/api/insights/reading-diet-by-type", params={"days": 3650})
            assert r2.status_code == 200, r2.text

            # Out-of-range days -> 422 (validated at BOTH bounds), never silently clamped.
            assert client.get(
                "/api/insights/reading-diet-by-type", params={"days": 0}
            ).status_code == 422
            assert client.get(
                "/api/insights/reading-diet-by-type", params={"days": 3651}
            ).status_code == 422
    finally:
        _app.dependency_overrides.pop(get_db, None)
    s.close()
