"""Article-length diagnostic — Home "Latest in your corpus" slice S0.

The evidence needed to pick honest thresholds for the Home substance filter (min
words AND min cited-sources): the DISTRIBUTION of article length + cited-source
count over the corpus, per content type and language. Counts only, NO score.

The pure summarizer + the report (over an in-memory corpus) run in the sandbox;
the endpoint + the Settings button are pinned by string assertions (no fastapi
needed) so the wiring cannot silently regress; the fastapi endpoint test runs in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.analytics.article_length import (
    _LINK_BUCKETS,
    _WORD_BUCKETS,
    summarize,
)

_ROOT = Path(__file__).resolve().parents[1]


def _score_like_keys(obj) -> list[str]:
    """Walk KEYS recursively (a caveat legitimately SAYS 'never a score', so a
    substring check on repr() would false-trip — the shipped-log lesson)."""
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


# ----------------------------- pure summarizer --------------------------------- #

def test_summarize_basic_distribution():
    s = summarize([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], _WORD_BUCKETS)
    assert s["n"] == 10 and s["min"] == 10 and s["max"] == 100
    assert s["mean"] == 55.0
    assert s["median"] == 50 and s["p90"] == 90 and s["p25"] == 30  # nearest-rank


def test_summarize_empty_is_honest_not_zero():
    s = summarize([], _LINK_BUCKETS)
    assert s["n"] == 0
    assert s["min"] is None and s["max"] is None and s["median"] is None
    assert sum(s["histogram"].values()) == 0


def test_summarize_histograms_bucket_correctly():
    wh = summarize([0, 50, 150, 350, 700, 1500, 5000], _WORD_BUCKETS)["histogram"]
    assert wh == {"0-99": 2, "100-299": 1, "300-599": 1, "600-999": 1,
                  "1000-1999": 1, "2000+": 1}
    lh = summarize([0, 0, 1, 2, 3, 4, 5, 8, 12], _LINK_BUCKETS)["histogram"]
    assert lh == {"0": 2, "1": 1, "2": 1, "3": 1, "4-5": 2, "6-9": 1, "10+": 1}


# ----------------------------- report over a corpus ---------------------------- #

@pytest.fixture()
def corpus():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, ArticleLink, Base, Source

    eng = sa.create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(id=1, name="Web", domain="w.test", source_type="news"))
    s.add(Source(id=2, name="NL", domain="nl.test", source_type="newsletter"))
    s.commit()

    def art(i, wc, lang, sid):
        return Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=sid,
                       title=f"t{i}", hash=f"h{i}", language=lang, word_count=wc, content="c",
                       published_at=datetime(2024, 6, 1, tzinfo=UTC), created_at=datetime.now(UTC))

    s.add_all([art(1, 120, "en", 1), art(2, 900, "en", 1), art(3, 50, "en-US", 1),
               art(4, None, "en", 1),  # NULL word_count -> excluded from length dists
               art(5, 400, "fr", 1), art(6, 600, "fr", 2),
               art(7, 8, "zh", 1), art(8, 12, "zh", 1)])  # unsegmented: tiny wc is an artifact
    s.commit()

    def lk(aid, u, t):
        return ArticleLink(article_id=aid, url=u, normalized_url=u, link_type=t)

    s.add_all([lk(2, f"u{i}", "external") for i in range(5)]
              + [lk(6, f"v{i}", "external") for i in range(2)]
              + [lk(1, "u1x", "external"), lk(1, "int", "internal")])  # internal must NOT count
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_report_scans_and_splits_by_type_and_language(corpus):
    from src.analytics.article_length import article_length_report

    r = article_length_report(corpus)
    assert r["scanned"] == 8 and r["with_word_count"] == 7  # the NULL one is counted, not measured
    assert r["word_count"]["n"] == 7 and r["word_count"]["min"] == 8 and r["word_count"]["max"] == 900
    # per content type (source_type on Source, resolved via the id map)
    assert r["word_count_by_content_type"]["news"]["n"] == 6
    assert r["word_count_by_content_type"]["newsletter"]["n"] == 1
    # per language, en-US folded to en
    assert r["word_count_by_language"]["en"]["n"] == 3
    assert r["word_count_by_language"]["fr"]["n"] == 2


def test_report_flags_unsegmented_languages(corpus):
    from src.analytics.article_length import article_length_report

    r = article_length_report(corpus)
    # zh word_count is a segmentation artifact — flagged so it is never word-gated.
    assert r["word_count_by_language"]["zh"]["unsegmented"] is True
    assert r["word_count_by_language"]["en"]["unsegmented"] is False
    assert "zh" in r["unsegmented_languages"]


def test_report_counts_cited_sources_with_zeros_and_ignores_internal(corpus):
    from src.analytics.article_length import article_length_report

    r = article_length_report(corpus)
    cs = r["cited_sources"]
    # external: art2=5, art6=2, art1=1; the other 5 articles have 0 (internal ignored)
    assert cs["n"] == 8 and cs["max"] == 5
    assert cs["histogram"]["0"] == 5 and cs["histogram"]["1"] == 1
    assert cs["histogram"]["2"] == 1 and cs["histogram"]["4-5"] == 1


def test_report_carries_no_score_fields(corpus):
    from src.analytics.article_length import article_length_report

    r = article_length_report(corpus)
    assert _score_like_keys(r) == []          # no score/ranking KEY anywhere
    assert "never a score" in r["caveat"]     # ...while the honesty caveat is present


# ----------------------------- wiring (no fastapi) ----------------------------- #

def test_endpoint_and_button_are_wired():
    diag = (_ROOT / "src" / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert '@router.get("/article-length")' in diag
    assert "from src.analytics.article_length import article_length_report" in diag
    # DIAGNOSE-THE-DIAGNOSTICS ruling #7 (2026-07-20): the standalone download button was
    # removed -- the all-diagnostics bundle already carries article-length.json (the
    # completeness ratchet guarantees it), so the endpoint itself is what stays wired.
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/diagnostics/article-length?download=1" not in html


# ----------------------------- the endpoint (CI) ------------------------------- #

def test_article_length_endpoint(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = create_engine(f"sqlite:///{tmp_path / 'al.db'}", future=True,
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
            r = client.get("/api/diagnostics/article-length")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["scanned"] == 1 and data["word_count"]["n"] == 1
            assert data["word_count_by_content_type"]["news"]["n"] == 1
            assert _score_like_keys(data) == []
    finally:
        app.dependency_overrides.clear()
