"""Home "Latest in your corpus" — the recency endpoint (slice S1).

A recency LENS (newest-by-``created_at``, un-spoofable) with two TRANSPARENT
substance gates the caller sets — ≥ min words AND ≥ min cited-sources — never a
quality/click-bait score. The length gate is script-aware (skipped for unsegmented
zh/ja/th and where word_count is unknown); cited sources = outbound external links
(internal ignored). The scanned window is disclosed; every row shows its real values.

The pure gate + the core (over an in-memory corpus) run in the sandbox; the endpoint
+ route are pinned by string assertions (no fastapi) and exercised for real in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.analytics.recency import passes_substance_gates

_ROOT = Path(__file__).resolve().parents[1]


def _score_like_keys(obj) -> list[str]:
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


# ------------------------------- the pure gates -------------------------------- #

def test_substance_gates():
    assert passes_substance_gates(500, "en", 3, 300, 2) is True
    assert passes_substance_gates(50, "en", 3, 300, 2) is False      # too short
    assert passes_substance_gates(500, "en", 1, 300, 2) is False     # too few sources
    assert passes_substance_gates(500, "en", 0, 0, 0) is True        # no gates -> nothing hidden


def test_length_gate_is_script_aware_and_unknown_safe():
    # word_count is meaningless for unsegmented langs -> the length gate is skipped.
    assert passes_substance_gates(5, "zh", 0, 300, 0) is True
    assert passes_substance_gates(5, "ja-JP", 0, 300, 0) is True     # base language folded
    assert passes_substance_gates(5, "th", 0, 300, 0) is True
    # unknown length is never a reason to hide.
    assert passes_substance_gates(None, "en", 0, 300, 0) is True
    # ...but a real short segmented article is gated out.
    assert passes_substance_gates(5, "en", 0, 300, 0) is False


# -------------------------- the core over a corpus ----------------------------- #

@pytest.fixture()
def corpus():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, ArticleLink, Base, Source

    eng = sa.create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(id=1, name="Web", domain="w.test", source_type="news", tags="finance,world"))
    s.add(Source(id=2, name="NL", domain="newsletters.import.local", source_type="newsletter", tags="digest"))
    s.add(Source(id=3, name="Wiki (en)", domain="en.wikipedia.org", source_type="reference", tags=""))
    s.commit()
    base = datetime(2026, 6, 20, tzinfo=UTC)

    def art(i, wc, lang, sid, days):
        return Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=sid, title=f"t{i}",
                       hash=f"h{i}", language=lang, word_count=wc, content="c",
                       published_at=base, created_at=base + timedelta(days=days))

    s.add_all([art(1, 120, "en", 1, 1), art(2, 900, "en", 1, 5), art(3, 50, "en", 1, 4),
               art(4, 400, "fr", 1, 3), art(5, 20, "zh", 1, 2),
               art(6, 600, "en", 2, 6), art(7, 800, "en", 3, 7)])
    s.commit()

    def lk(aid, u):
        return ArticleLink(article_id=aid, url=u, normalized_url=u, link_type="external")

    s.add_all([lk(2, f"a{i}") for i in range(4)] + [lk(6, "b0")] + [lk(7, f"c{i}") for i in range(3)]
              + [ArticleLink(article_id=2, url="int", normalized_url="int", link_type="internal")])
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_orders_by_created_at_newest_first(corpus):
    from src.analytics.recency import recent_collected

    r = recent_collected(corpus)
    assert [a["id"] for a in r["articles"]] == [7, 6, 2, 3, 4, 5, 1]   # collected-days 7..1
    assert r["candidate_window"] == 7 and r["matched"] == 7
    # the local reader link (invariant #6), the content-provenance label, real values
    top = r["articles"][0]
    assert top["url"] == "/api/articles/7/view" and top["content_type"] == "wikipedia"
    assert next(a for a in r["articles"] if a["id"] == 2)["cited_sources"] == 4  # internal ignored


def test_min_words_gate_keeps_unsegmented(corpus):
    from src.analytics.recency import recent_collected

    r = recent_collected(corpus, min_words=300)
    # en 120/50 dropped; zh 20 KEPT (unsegmented — never word-gated blindly)
    assert set(a["id"] for a in r["articles"]) == {7, 6, 2, 4, 5}
    assert r["matched"] == 5


def test_min_sources_and_facets(corpus):
    from src.analytics.recency import recent_collected

    assert set(a["id"] for a in recent_collected(corpus, min_sources=2)["articles"]) == {2, 7}
    assert [a["id"] for a in recent_collected(corpus, content_type="newsletter")["articles"]] == [6]
    assert set(a["id"] for a in recent_collected(corpus, tags="finance")["articles"]) == {1, 2, 3, 4, 5}


def test_limit_returns_capped_but_discloses_window(corpus):
    from src.analytics.recency import recent_collected

    r = recent_collected(corpus, limit=2)
    assert r["returned"] == 2 and len(r["articles"]) == 2
    assert r["matched"] == 7 and r["candidate_window"] == 7   # window still fully scanned + disclosed


def test_no_score_fields(corpus):
    from src.analytics.recency import recent_collected

    r = recent_collected(corpus, min_words=100)
    assert _score_like_keys(r) == []
    assert "never a" in r["caveat"] and "recency lens" in r["caveat"].lower()


# ------------------------------ near-dup collapse (S1b) ------------------------ #

_WIRE = ("The central bank raised interest rates by fifty basis points on Tuesday citing "
         "persistent inflation across the services sector and warned of further tightening "
         "should price pressures continue into the next quarter according to officials familiar.")


def _dup_corpus(sources_single=False):
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = sa.create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    base = datetime(2026, 6, 20, tzinfo=UTC)
    if sources_single:
        s.add(Source(id=1, name="Solo", domain="solo.test", source_type="news"))
    else:
        for i in range(1, 5):
            s.add(Source(id=i, name=f"Outlet{i}", domain=f"o{i}.test", source_type="news", tags="world"))
    s.commit()

    def art(i, sid, days, content):
        return Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=sid, title=f"t{i}",
                       hash=f"h{i}", language="en", word_count=len(content.split()), content=content,
                       published_at=base, created_at=base + timedelta(days=days))

    if sources_single:
        s.add_all([art(10, 1, 1, _WIRE), art(11, 1, 2, _WIRE), art(12, 1, 3, _WIRE)])
    else:
        # byte-identical wire reprint across outlets 1/2/3 + a fresher republish by
        # outlet 1 (art5) + a distinct story (art4).
        s.add_all([art(1, 1, 1, _WIRE), art(2, 2, 3, _WIRE), art(3, 3, 5, _WIRE),
                   art(4, 4, 4, "A totally different story about a football match last night."),
                   art(5, 1, 6, _WIRE)])
    s.commit()
    return s


def test_collapse_is_off_by_default_and_byte_identical():
    from src.analytics.recency import recent_collected

    s = _dup_corpus()
    r = recent_collected(s)
    assert "collapse" not in r
    assert all("duplicates" not in a for a in r["articles"])  # S1a shape untouched


def test_collapse_folds_reprints_to_the_freshest_story():
    from src.analytics.recency import recent_collected

    s = _dup_corpus()
    r = recent_collected(s, collapse=True)
    ids = {a["id"] for a in r["articles"]}
    assert ids == {5, 4}  # the wire cluster {1,2,3,5} folds to its freshest member (art5)
    rep = next(a for a in r["articles"] if a["id"] == 5)
    assert rep["duplicates"] == 3 and set(rep["duplicate_ids"]) == {1, 2, 3}
    assert rep["outlets"] == 3 and rep["single_source"] is False  # 3 distinct outlets
    assert next(a for a in r["articles"] if a["id"] == 4)["duplicates"] == 0  # standalone
    assert r["collapse"]["clusters"] == 1 and r["collapse"]["copies_folded"] == 3
    assert r["matched"] == 5  # the pre-collapse match count is still disclosed


def test_collapse_flags_a_single_source_reprinting_itself():
    from src.analytics.recency import recent_collected

    s = _dup_corpus(sources_single=True)
    r = recent_collected(s, collapse=True)
    rep = r["articles"][0]
    # one outlet reprinting itself is NOT corroboration — it is flagged, not counted.
    assert rep["single_source"] is True and rep["outlets"] == 1 and rep["duplicates"] == 2
    assert len(r["articles"]) == 1 and r["collapse"]["copies_folded"] == 2


def test_collapse_carries_the_near_dup_caveat_and_no_score():
    from src.analytics.recency import recent_collected

    s = _dup_corpus()
    r = recent_collected(s, collapse=True)
    assert r["collapse"]["applied"] is True and "text overlap" in r["collapse"]["caveat"].lower()
    assert _score_like_keys(r) == []


# ------------------------------ wiring (no fastapi) ---------------------------- #

def test_endpoint_is_wired():
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/api/articles/recent"' in src
    assert "from src.analytics.recency import recent_collected" in src
    # registered BEFORE the {article_id}/view route so the static path wins
    i_recent = src.index('"/api/articles/recent"')
    i_view = src.index('"/api/articles/{article_id}/view"')
    assert i_recent < i_view
    # a bad content_type is rejected, not silently ignored
    assert "content_type must be one of" in src
    # the near-dup collapse (S1b) is threaded through the endpoint
    assert "collapse: bool = False" in src
    assert "collapse=collapse" in src


# --------------------------------- the endpoint (CI) --------------------------- #

def test_recent_endpoint(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    with Sess() as s:
        s.add(Source(name="Web", domain="w.test", source_type="news"))
        s.commit()
        s.add(Article(url="https://w.test/1", canonical_url="https://w.test/1", source_id=1,
                      title="t", hash="h1", language="en", word_count=350, content="c",
                      published_at=datetime(2024, 6, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
        s.commit()

    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/recent")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["returned"] == 1 and data["articles"][0]["word_count"] == 350
            assert data["articles"][0]["url"] == "/api/articles/1/view"
            # a real gate excludes it, and the window/matched disclose that
            r2 = client.get("/api/articles/recent?min_words=1000")
            assert r2.json()["returned"] == 0 and r2.json()["candidate_window"] == 1
            # a bad content_type is a 400
            assert client.get("/api/articles/recent?content_type=bogus").status_code == 400
            # collapse=true attaches the collapse block (one standalone article here)
            rc = client.get("/api/articles/recent?collapse=true").json()
            assert rc["collapse"]["applied"] is True
            assert rc["articles"][0]["duplicates"] == 0
    finally:
        app.dependency_overrides.clear()
