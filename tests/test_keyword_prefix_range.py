"""The omnibar keyword group seeks the index instead of scanning the table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.search_omni import _keywords_group, _like_escape, _prefix_predicate
from src.database.models import Base, Keyword

_TERMS = ["climate", "climate change", "climat", "clima_te", "50%", "50 percent", "été", "ete", "zebra", "z", "ñandú"]


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, future=True)() as s:
        for i, t in enumerate(_TERMS):
            s.add(Keyword(term=t, normalized_term=t.casefold(), language="en", frequency=100 - i))
        s.commit()
    with sessionmaker(bind=eng, future=True)() as s:
        yield s


@pytest.mark.parametrize("q", ["c", "cl", "clim", "climate", "Climate", "clima_", "50%", "50", "é", "e", "z", "ñ", "nomatch", "%", "_"])
def test_the_range_finds_exactly_what_the_like_prefix_found(db, q):
    folded = q.casefold()
    like = {k.normalized_term for k in db.query(Keyword).filter(Keyword.normalized_term.like(_like_escape(folded) + "%", escape="\\"))}
    rng = {k.normalized_term for k in db.query(Keyword).filter(_prefix_predicate(Keyword.normalized_term, folded))}
    assert rng == like


def test_the_group_still_answers_and_counts(db):
    g = _keywords_group(db, "clim")
    assert g["total"] == 4 and [i["normalized_term"] for i in g["items"]][0] == "climate"


def test_the_query_plan_seeks_the_term_index(db):
    from sqlalchemy.dialects import sqlite

    stmt = db.query(Keyword.id).filter(_prefix_predicate(Keyword.normalized_term, "clim")).statement
    sql = str(stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    plan = " ".join(str(r[-1]) for r in db.execute(text("EXPLAIN QUERY PLAN " + sql)).all())
    assert "SEARCH" in plan and "idx_keyword_normalized_term" in plan and "normalized_term>" in plan, plan


def test_an_empty_prefix_keeps_the_like_form(db):
    assert _keywords_group(db, "")["total"] == len(_TERMS)
