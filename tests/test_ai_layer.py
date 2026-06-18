"""
The AI layer: AI-derived analytics in their OWN tables in the MAIN database.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-18 (REVERSES the earlier separate-database design): AI
analytics live in their own tables in the main corpus DB — for seamless UI integration
and fast corpus-wide selection (a real indexed JOIN). The integrity guarantee is
preserved BY CONSTRUCTION — own table, no score, model provenance, and (the
load-bearing test here) the trusted rule-based keyword index NEVER reads ``ai_keyword``,
so AI output can never be confused with, or joined into, rule-based fact.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import store as ai_store
from src.database.models import AiKeyword, Base

_REPO = Path(__file__).resolve().parents[1]
# The trusted, rule-based analytics must never read the AI table.
_TRUSTED_DIR = _REPO / "src" / "analytics"


def _sess():
    """An in-memory MAIN schema (FK enforcement is off in a bare sqlite engine, so the
    store round-trip doesn't need real articles — that path is covered by the HTTP
    test in test_ai_keyword_extract.py)."""
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --- round trip ------------------------------------------------------------- #


def test_record_and_read_keywords_round_trip():
    s = _sess()
    added = ai_store.record_keywords(
        s, 42, ["sanctions", "central bank", "sanctions", "  "], model="llama3.2:3b",
        language="en",
    )
    assert added == 2  # duplicate "sanctions" and the blank are dropped
    rows = ai_store.keywords_for_article(s, 42)
    assert [r.term for r in rows] == ["central bank", "sanctions"]
    assert all(r.model == "llama3.2:3b" and r.language == "en" for r in rows)
    assert all(r.confirmed is False for r in rows)  # unconfirmed by default
    # a re-run tops up, never duplicates
    assert ai_store.record_keywords(s, 42, ["sanctions", "embargo"], model="m") == 1
    assert [r.term for r in ai_store.keywords_for_article(s, 42)] == [
        "central bank", "embargo", "sanctions",
    ]
    assert ai_store.keywords_for_article(s, 7) == []  # a different article is unaffected


def test_confirm_within_the_lens():
    s = _sess()
    ai_store.record_keywords(s, 1, ["drought"], model="m")
    row = ai_store.keywords_for_article(s, 1)[0]
    assert ai_store.set_confirmed(s, row.id, True) is True
    assert ai_store.keywords_for_article(s, 1, confirmed_only=True)[0].term == "drought"
    assert ai_store.set_confirmed(s, 999, True) is False  # unknown row


# --- the table lives in the main DB now ------------------------------------- #


def test_ai_keyword_is_a_main_db_table():
    assert "ai_keyword" in Base.metadata.tables


def test_ai_keyword_has_fk_to_articles_and_no_score():
    """A REAL FK now (same database) — the indexed JOIN that makes corpus-wide AI-signal
    selection fast; and NO composite score column (honesty by construction)."""
    cols = {c.name: c for c in AiKeyword.__table__.columns}
    fks = cols["article_id"].foreign_keys
    assert fks and any(fk.column.table.name == "articles" for fk in fks)
    forbidden = {
        "score", "credibility_score", "reliability_score", "political_bias",
        "trust_score", "quality_score", "confidence_score",
    }
    assert forbidden & set(cols) == set()


# --- the integrity guarantee that SURVIVES the move ------------------------- #


def test_trusted_keyword_index_never_reads_the_ai_table():
    """The trusted, rule-based analytics must NEVER read ``ai_keyword`` / ``AiKeyword``
    nor import the AI layer — that is what keeps AI output from masquerading as, or being
    joined into, rule-based fact now that the two live in the same database. (The
    rule-based keyword index reads only ``articles.content``.)"""
    for f in sorted(_TRUSTED_DIR.rglob("*.py")):
        src = f.read_text("utf-8")
        assert "ai_keyword" not in src, f
        assert "AiKeyword" not in src, f
        assert "src.ai_layer" not in src, f
