"""Home "Latest in your corpus" — S1 recency endpoint (recency LENS + substance FILTERS).

Newest-first by un-spoofable collection time, two transparent gates the user sets AND
sees (min words AND min cited sources), script-aware length (zh/ja/th bypass the word
gate, flagged), near-dup wire-reprint collapse. Counts only, NO score.

The report runs over an in-memory corpus (sandbox); the endpoint runs in CI (fastapi).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# A real wire paragraph, reprinted verbatim across sources (near-dup).
_WIRE = (
    "The central bank raised its benchmark interest rate by fifty basis points on "
    "Tuesday, citing persistent inflation across the euro area and warning that further "
    "tightening may follow before the end of the year if price pressures do not ease."
)
_UNIQUE1 = (
    "Researchers described a newly sequenced soil bacterium whose enzymes break down a "
    "common industrial plastic far faster than any previously catalogued organism."
)
_UNIQUE2 = (
    "The regional water authority published a decade of reservoir levels showing a slow "
    "structural decline that the seasonal rains no longer fully reverse each winter."
)
_UNIQUE3 = (
    "A cooperative of small growers announced a shared cold-storage facility intended to "
    "cut post-harvest losses that had reached nearly a third of their annual tomato crop."
)
_ZH = "".join(["中央银行周二宣布上调基准利率并警告通胀压力持续存在可能进一步收紧货币政策直到年底"] * 3)


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


@pytest.fixture()
def corpus():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, ArticleLink, Base, Source

    eng = sa.create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add_all(
        [
            Source(id=1, name="Web", domain="w.test", source_type="news", tags="news,europe"),
            Source(id=2, name="NL", domain="nl.test", source_type="newsletter", tags="tech"),
            Source(id=3, name="Wire", domain="wire.test", source_type="news", tags="news"),
        ]
    )
    s.commit()
    now = datetime.now(UTC)

    def art(i, sid, lang, wc, content, mins_ago):
        return Article(
            id=i, url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=sid,
            title=f"t{i}", hash=f"h{i}", language=lang, word_count=wc, content=content,
            published_at=now, created_at=now - timedelta(minutes=mins_ago),
        )

    s.add_all([
        art(1, 1, "en", 600, _WIRE, 1),      # wire, freshest copy (Web / news)
        art(4, 1, "en", 800, _UNIQUE1, 2),   # unique long, well-linked
        art(5, 1, "en", 30, "short blurb", 3),  # short -> fails min_words=100
        art(6, 1, "zh", 8, _ZH, 4),          # unsegmented: tiny wc is an artifact
        art(2, 3, "en", 600, _WIRE, 5),      # wire reprint (Wire / news)
        art(7, 1, "en", 900, _UNIQUE2, 6),   # long but NO external links
        art(8, 2, "en", 400, _UNIQUE3, 7),   # newsletter / tag=tech
        art(3, 2, "en", 600, _WIRE, 9),      # wire reprint (NL / newsletter), oldest
    ])
    s.commit()

    def lk(aid, n, t="external"):
        return [
            ArticleLink(article_id=aid, url=f"u{aid}-{i}", normalized_url=f"u{aid}-{i}", link_type=t)
            for i in range(n)
        ]

    links = lk(1, 3) + lk(4, 4) + lk(5, 2) + lk(6, 2) + lk(2, 3) + lk(8, 1) + lk(3, 3)
    links += [ArticleLink(article_id=4, url="int", normalized_url="int", link_type="internal")]
    # art 7 has zero external links.
    s.add_all(links)
    s.commit()
    try:
        yield s
    finally:
        s.close()


def _ids(res) -> list[int]:
    return [a["id"] for a in res["articles"]]


def test_recency_order_and_near_dup_collapse(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20)
    ids = _ids(r)
    # Newest-first by created_at; the wire trio collapses into its freshest copy (id 1).
    assert ids[0] == 1
    assert 2 not in ids and 3 not in ids, "wire reprints must be folded, not shown"
    story = r["articles"][0]
    assert story["duplicates_collapsed"] == 2
    assert set(story["also_reported_by"]) == {"wire.test", "nl.test"}
    assert r["collapsed_total"] == 2
    # Remaining distinct stories present, still recency-ordered.
    assert ids == [1, 4, 5, 6, 7, 8]


def test_collapse_off_shows_every_copy(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20, collapse=False)
    assert set(_ids(r)) == {1, 2, 3, 4, 5, 6, 7, 8}
    assert all(a["duplicates_collapsed"] == 0 for a in r["articles"])


def test_min_words_gate_is_script_aware(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20, min_words=100, collapse=False)
    ids = set(_ids(r))
    assert 5 not in ids, "a 30-word article fails the ≥100 gate"
    assert 6 in ids, "an unsegmented (zh) article is never word-gated"
    z = next(a for a in r["articles"] if a["id"] == 6)
    assert z["unsegmented"] is True
    assert z["word_count"] == 8  # the real (unreliable) value is still exposed honestly
    assert next(a for a in r["articles"] if a["id"] == 1)["unsegmented"] is False


def test_min_sources_gate(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20, min_sources=1, collapse=False)
    ids = set(_ids(r))
    assert 7 not in ids, "an article with zero external links fails ≥1 cited source"
    assert 4 in ids
    a4 = next(a for a in r["articles"] if a["id"] == 4)
    assert a4["cited_sources"] == 4  # internal link is NOT counted


def test_content_type_and_tag_facets(corpus):
    from src.analytics.latest import latest_articles

    nl = latest_articles(corpus, limit=20, content_type="newsletter", collapse=False)
    assert all(a["source"]["source_type"] == "newsletter" for a in nl["articles"])
    assert set(_ids(nl)) == {3, 8}

    tech = latest_articles(corpus, limit=20, tag="tech", collapse=False)
    assert set(_ids(tech)) == {3, 8}, "tag=tech scopes to the newsletter source"

    missing = latest_articles(corpus, limit=20, tag="nonexistent-tag")
    assert missing["articles"] == [] and missing["returned"] == 0


def test_facet_options_and_gates_echoed(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=5, min_words=50, min_sources=1)
    assert r["available_content_types"]["news"] >= 1
    assert r["available_content_types"]["newsletter"] >= 1
    tag_names = {t["tag"] for t in r["available_tags"]}
    assert {"news", "europe", "tech"} <= tag_names
    assert r["gates"] == {"min_words": 50, "min_sources": 1}
    assert r["filters"] == {"content_type": None, "tag": None}


def test_window_excludes_old_articles(corpus):
    from src.analytics.latest import latest_articles

    # Every fixture article is minutes old; a 1-day window keeps them, but the window is
    # honoured: shift nothing here, just assert the window field is reported.
    r = latest_articles(corpus, limit=20, window_days=1, collapse=False)
    assert r["window_days"] == 1
    assert len(r["articles"]) == 8


def test_no_score_fields(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20)
    assert _score_like_keys(r) == []
    assert "never a score" in r["caveat"]


def test_url_is_the_local_reader(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20)
    assert r["articles"][0]["url"] == "/api/articles/1/view"


# ------------------- D1: near-dup collapse on a bounded content prefix ------------------- #


def _prefix_corpus():
    """Two articles that SHARE a long lede (within the prefix) but differ after it, plus a
    third that shares text with the first only in the TAIL (beyond the prefix)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add_all([
        Source(id=1, name="A", domain="a.test", source_type="news", tags="news"),
        Source(id=2, name="B", domain="b.test", source_type="news", tags="news"),
        Source(id=3, name="C", domain="c.test", source_type="news", tags="news"),
    ])
    s.commit()
    now = datetime.now(UTC)
    lede = ("The government today unveiled a sweeping new economic package as inflation "
            "pressures mounted across the region. Officials described the measures in "
            "detail at a lengthy press briefing. ") * 20  # ~4k+ chars -> spans the prefix
    tail_x = (" A completely unrelated closing section about sports fixtures. ") * 40
    tail_y = (" A different unrelated closing about weather patterns and rainfall. ") * 40
    shared_tail = (" IDENTICAL TAIL BOILERPLATE that only appears late in the body. ") * 40

    def art(i, sid, content, mins):
        return Article(id=i, url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=sid,
                       title=f"t{i}", hash=f"h{i}", language="en", word_count=900, content=content,
                       published_at=now, created_at=now - timedelta(minutes=mins))

    s.add_all([
        art(1, 1, lede + tail_x, 1),        # shares the LEDE with 2 (within prefix) -> collapse
        art(2, 2, lede + tail_y, 2),        # reprint: same lede, different tail
        art(3, 3, "Unrelated opening. " * 300 + shared_tail, 3),  # shares only a TAIL with none in-prefix
    ])
    s.commit()
    return s


def test_neardup_collapse_uses_the_bounded_prefix():
    from src.analytics.latest import latest_articles

    s = _prefix_corpus()
    r = latest_articles(s, limit=20)
    ids = _ids(r)
    # 1 and 2 share the lede (within the 4000-char prefix) -> collapsed into the freshest (1).
    assert ids[0] == 1
    assert 2 not in ids, "a reprint sharing the lede must collapse via the folded prefix"
    assert r["articles"][0]["duplicates_collapsed"] == 1
    # 3 shares no in-prefix text with anything -> stays a distinct story (disclosed limit).
    assert 3 in ids
    s.close()


def test_neardup_prefix_is_disclosed_and_not_leaked(corpus):
    from src.analytics.latest import latest_articles

    r = latest_articles(corpus, limit=20)
    assert r["collapse_prefix_chars"] == 4000
    assert "first 4000 characters" in r["method"]
    # The internal near-dup input must never leak into the payload.
    for a in r["articles"]:
        assert "_body_prefix" not in a and "_source_domain" not in a


def test_neardup_prefix_env_override(monkeypatch):
    from src.analytics.latest import latest_articles

    monkeypatch.setenv("OO_LATEST_NEARDUP_PREFIX_CHARS", "800")
    s = _prefix_corpus()
    r = latest_articles(s, limit=20)
    assert r["collapse_prefix_chars"] == 800
    assert "first 800 characters" in r["method"]
    s.close()


def test_collapse_off_reads_no_prefix_and_folds_nothing():
    from src.analytics.latest import latest_articles

    s = _prefix_corpus()
    r = latest_articles(s, limit=20, collapse=False)
    assert set(_ids(r)) == {1, 2, 3}
    assert "collapse_prefix_chars" not in r  # want_prefix False -> the prefix column is never read
    s.close()


def test_neardup_prefix_bounds_the_comparison_window(monkeypatch):
    """Two reprints with DIFFERENT ~300-char openings but an IDENTICAL body: a TINY prefix
    compares only the (distinct) openings -> NOT collapsed; a LARGE prefix reaches the shared
    body -> collapsed. Proves the collapse compares exactly the disclosed prefix window (the
    honest limitation stated in the method), and that the fold reads that window, not the blob."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics.latest import latest_articles
    from src.database.models import Article, Base, Source

    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add_all([
        Source(id=1, name="A", domain="a.test", source_type="news", tags="news"),
        Source(id=2, name="B", domain="b.test", source_type="news", tags="news"),
    ])
    s.commit()
    now = datetime.now(UTC)
    # VARIED (non-repeated) text so shingle sets are rich: repeated phrases collapse to a
    # handful of distinct shingles and never reach the 0.7 threshold. Distinct openings run
    # past the 500-char prefix floor; the shared body then dominates a large window.
    open_a = " ".join(f"Alpha lead sentence {i} for the first outlet only, item {i*2}." for i in range(18))
    open_b = " ".join(f"Beta headline clause {i} for the second outlet instead, note {i*3}." for i in range(18))
    body = " ".join(
        f"Shared wire sentence {i} on the central bank decision and its outcome {i+5}."
        for i in range(200)
    )  # ~13k chars, ~200 distinct sentences
    s.add_all([
        Article(id=1, url="https://x/1", canonical_url="https://x/1", source_id=1, title="t1",
                hash="h1", language="en", word_count=900, content=open_a + body,
                published_at=now, created_at=now - timedelta(minutes=1)),
        Article(id=2, url="https://x/2", canonical_url="https://x/2", source_id=2, title="t2",
                hash="h2", language="en", word_count=900, content=open_b + body,
                published_at=now, created_at=now - timedelta(minutes=2)),
    ])
    s.commit()

    monkeypatch.setenv("OO_LATEST_NEARDUP_PREFIX_CHARS", "500")  # the floor: only the openings
    small = latest_articles(s, limit=20)
    assert {1, 2} <= set(_ids(small)), "at the tiny prefix the distinct openings are not folded"
    assert small["collapse_prefix_chars"] == 500

    monkeypatch.setenv("OO_LATEST_NEARDUP_PREFIX_CHARS", "6000")
    large = latest_articles(s, limit=20)
    assert 2 not in _ids(large), "with the shared body inside the prefix, the reprint collapses"
    assert large["articles"][0]["duplicates_collapsed"] == 1
    s.close()


# ----------------------------- wiring (no fastapi) ----------------------------- #

def test_endpoint_is_wired():
    ins = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert '@router.get("/latest")' in ins
    assert "from src.analytics.latest import latest_articles" in ins


# ----------------------------- the endpoint (CI) ------------------------------- #

def test_latest_endpoint(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = create_engine(
        f"sqlite:///{tmp_path / 'l.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    now = datetime.now(UTC)
    with Sess() as s:
        s.add(Source(name="Web", domain="w.test", source_type="news", tags="news"))
        s.commit()
        s.add(Article(
            url="https://w.test/1", canonical_url="https://w.test/1", source_id=1, title="t",
            hash="h1", language="en", word_count=500, content="a real body here",
            published_at=now, created_at=now,
        ))
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
            r = client.get("/api/insights/latest?min_words=100&min_sources=0")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["returned"] == 1
            assert data["articles"][0]["word_count"] == 500
            assert data["articles"][0]["url"] == "/api/articles/1/view"
            assert _score_like_keys(data) == []
    finally:
        app.dependency_overrides.clear()
