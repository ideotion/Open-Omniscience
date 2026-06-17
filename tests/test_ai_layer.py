"""
The AI layer: a SEPARATE, parallel database for AI-derived analytics.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-17 (CLAUDE.md — "LLM SCOPE — STRICT PHYSICAL SEPARATION"):
the AI never writes the main store except summaries/translations; ALL other
AI-derived analytics live HERE, in their own encrypted database, NEVER joined to the
main store. These tests pin that separation BY CONSTRUCTION — the load-bearing
guarantee the maintainer chose physical separation for.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import store as ai_store
from src.ai_layer.models import AiBase, AiKeyword

_REPO = Path(__file__).resolve().parents[1]
_AI_DIR = _REPO / "src" / "ai_layer"
# The trusted, rule-based analytics + the core DB layer must never read the AI store.
_TRUSTED_DIRS = (_REPO / "src" / "analytics", _REPO / "src" / "database")


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    AiBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --- round trip: the "second keyword database" works ------------------------- #


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
    # a different article is unaffected
    assert ai_store.keywords_for_article(s, 7) == []


def test_confirm_within_the_lens():
    s = _sess()
    ai_store.record_keywords(s, 1, ["drought"], model="m")
    row = ai_store.keywords_for_article(s, 1)[0]
    assert ai_store.set_confirmed(s, row.id, True) is True
    assert ai_store.keywords_for_article(s, 1, confirmed_only=True)[0].term == "drought"
    assert ai_store.set_confirmed(s, 999, True) is False  # unknown row


# --- separation invariants: the keystone ------------------------------------- #


def test_ai_base_is_disjoint_from_the_main_corpus_base():
    """The AI metadata shares NO table with the trusted corpus schema, so the two
    databases can never be confused or merged."""
    from src.database.models import Base as MainBase

    ai_tables = set(AiBase.metadata.tables)
    main_tables = set(MainBase.metadata.tables)
    assert ai_tables & main_tables == set(), ai_tables & main_tables
    assert "ai_keyword" in ai_tables


def test_ai_keyword_has_no_fk_to_articles_and_no_score():
    """``article_id`` is a SOFT integer reference (no SQL join across the two DBs),
    and AI output carries NO composite score (honesty by construction)."""
    cols = {c.name: c for c in AiKeyword.__table__.columns}
    assert cols["article_id"].foreign_keys == set()
    forbidden = {
        "score", "credibility_score", "reliability_score", "political_bias",
        "trust_score", "quality_score", "confidence_score",
    }
    assert forbidden & set(cols) == set()


def test_ai_layer_never_attaches_or_imports_the_main_orm():
    """Physical separation by construction: the AI layer must not ATTACH another DB
    nor import the main ORM models (which would invite a cross-DB join). It may use
    the connect() factory and the WriterGate class — those are not a join surface."""
    for f in sorted(_AI_DIR.glob("*.py")):
        src = f.read_text("utf-8").upper()
        assert "ATTACH DATABASE" not in src, f
    for f in sorted(_AI_DIR.glob("*.py")):
        src = f.read_text("utf-8")
        assert not re.search(r"from\s+src\.database\.models\s+import", src), f
        assert "import src.database.models" not in src, f


def test_trusted_keyword_index_never_imports_the_ai_layer():
    """The trusted, rule-based analytics + the core DB layer must never read the AI
    store — the main analytics index is canonical and AI-free."""
    for d in _TRUSTED_DIRS:
        for f in sorted(d.rglob("*.py")):
            src = f.read_text("utf-8")
            assert "src.ai_layer" not in src, f


# --- the production store: a separate file, opened via the ONE factory -------- #


def test_global_ai_store_is_a_separate_file_and_round_trips(tmp_path, monkeypatch):
    """init_ai_db creates a SEPARATE file (not the main corpus), opened through the
    one connection factory; a write via the AI session works and the AI write gate
    (its OWN gate, not the main store's) serialises it."""
    from src.ai_layer import db as aidb
    from src.database.session import engine as main_engine

    ai_path = tmp_path / "ai_layer.db"
    monkeypatch.setenv("OO_AI_DB_PATH", str(ai_path))
    aidb._reset_for_tests()
    try:
        aidb.init_ai_db()
        assert ai_path.exists()
        # a different file from the main corpus
        assert str(ai_path) != (main_engine.url.database or "")

        grants_before = aidb.ai_write_gate.stats()["grants"]
        with aidb.ai_session_scope() as s:
            ai_store.record_keywords(s, 5, ["petrol"], model="m", kind="keyword")
        # the AI gate took the write window (proves its OWN gate engaged)
        assert aidb.ai_write_gate.stats()["grants"] > grants_before
        # the gate was released cleanly (no leak)
        assert aidb.ai_write_gate.held_by_current_thread() is False

        with aidb.ai_session_scope() as s:
            assert [r.term for r in ai_store.keywords_for_article(s, 5)] == ["petrol"]
    finally:
        aidb._reset_for_tests()
