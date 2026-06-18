"""Framing perf guard (field report 2026-06-18: /api/framing ≈141 s).

The fix bounds the text fed to the coarse VADER/term-frequency framing computation
(a signal, not a verdict) and eager-loads the source to kill an N+1. This pins the
content bound so a future change can't re-introduce full-text VADER over long pages.

Imports vaderSentiment (the [analysis] extra) via src.api.framing -> runs in CI.
"""

from __future__ import annotations

import pytest

pytest.importorskip("vaderSentiment")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import src.api.framing as fr  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402


def _session_with_long_article():
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(id=1, name="Long Source", domain="long.test"))
    s.add(Article(id=1, url="https://long.test/1", canonical_url="https://long.test/1",
                  source_id=1, title="t", content="x" * 20000, hash="h1"))
    s.commit()
    return s


def test_framing_bounds_content_fed_to_vader(monkeypatch):
    captured: dict = {}

    def _fake_compare(by_source, **kw):
        captured.update(by_source)
        return {"framing": [], "sources_compared": 0, "total_articles": 0,
                "shared_terms": [], "caveat": ""}

    monkeypatch.setattr(fr, "compare_framing", _fake_compare)
    s = _session_with_long_article()
    fr.framing(query=None, limit=200, db=s)

    contents = [a["content"] for arts in captured.values() for a in arts]
    assert contents, "the article should have been grouped by source"
    # The 20k-char article is bounded; nothing exceeds the cap.
    assert all(len(c) <= fr._FRAMING_MAX_CHARS for c in contents)
    assert max(len(c) for c in contents) == fr._FRAMING_MAX_CHARS
