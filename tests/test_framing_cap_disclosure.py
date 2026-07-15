"""S10 — the framing endpoint discloses its admission cap ({analyzed_n, total_n, capped}).

/api/framing compares at most ``limit`` articles (each bounded to 8000 chars). When the
match exceeds ``limit`` it used to analyse a silent subset; now it DISCLOSES how many of the
total it looked at — a disclosed bound, never a silent truncation. Under the cap the analysis
output is byte-identical (the disclosure fields are additive, capped is False).

Imports vaderSentiment (the [analysis] extra) via src.api.framing -> runs in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

pytest.importorskip("vaderSentiment")

from datetime import UTC, datetime  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.api.framing as fr  # noqa: E402
from src.awareness.framing import compare_framing  # noqa: E402
from src.database.fts import ensure_fts, search_ids  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402


def _session(n: int, *, fts: bool = False):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(eng)
    if fts:
        ensure_fts(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(id=1, name="Wire", domain="wire.test"))
    for i in range(1, n + 1):
        s.add(Article(
            id=i, url=f"https://wire.test/{i}", canonical_url=f"https://wire.test/{i}",
            source_id=1, title=f"t{i}", content="election policy debate news",
            hash=f"{i:064d}", published_at=datetime(2026, 6, 1, tzinfo=UTC),
        ))
    s.commit()
    return s


def test_the_8000_char_per_article_cap_is_still_present():
    assert fr._FRAMING_MAX_CHARS == 8000


def test_no_query_path_discloses_the_cap_when_corpus_exceeds_limit():
    s = _session(5)
    out = fr.framing(query=None, limit=2, db=s)
    assert out["capped"] is True
    assert out["analyzed_n"] == 2  # only the most-recent `limit` analysed
    assert out["total_n"] == 5  # the whole corpus disclosed
    # the analysis fields are still there (compared the 2, honestly bounded)
    assert out["sources_compared"] >= 1 and "framing" in out


def test_under_cap_is_byte_identical_plus_additive_disclosure():
    s = _session(3)
    out = fr.framing(query=None, limit=200, db=s)
    # honest disclosure: nothing was dropped
    assert out["capped"] is False
    assert out["analyzed_n"] == 3 and out["total_n"] == 3
    # byte-identical analysis: the framing output equals a direct compare_framing over the
    # same by_source (only analyzed_n/total_n/capped/query are additive on top).
    ref_articles = s.query(Article).order_by(Article.id.desc()).limit(200).all()
    by_source: dict[str, list[dict]] = {}
    for a in ref_articles:
        by_source.setdefault(a.source.name if a.source else "Unknown", []).append(
            {"title": a.title, "content": (a.content or "")[:fr._FRAMING_MAX_CHARS],
             "url": a.url,
             "published_at": a.published_at.isoformat() if a.published_at else None}
        )
    ref = compare_framing(by_source)
    for k in ("sources_compared", "total_articles", "framing", "shared_terms", "caveat"):
        assert out[k] == ref[k], k


def test_query_path_discloses_cap_from_the_full_match_total():
    s = _session(6, fts=True)
    # sanity: the FTS query matches all 6
    assert len(search_ids(s, "election")) == 6
    out = fr.framing(query="election", limit=2, db=s)
    assert out["total_n"] == 6  # the FULL match count, not the analysed subset
    assert out["analyzed_n"] == 2 and out["capped"] is True


def test_empty_match_is_honest_and_uncapped():
    s = _session(3, fts=True)
    out = fr.framing(query="zzzznomatch", limit=10, db=s)
    assert out["analyzed_n"] == 0 and out["total_n"] == 0 and out["capped"] is False
    assert out["sources_compared"] == 0 and out["framing"] == []
