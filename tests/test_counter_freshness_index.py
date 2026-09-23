"""`counter_envelope` must not read 1.1 M rows to answer "is this fresh?" (finding F7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE MEASUREMENT. `counter_envelope` runs on the Insights top path and asks
`min(keywords.last_reconciled_at) WHERE mention_count > 0`. `idx_keyword_mention_count`
covered only the predicate, so SQLite located the matching index entries and then read the
ROWS to fetch the timestamp -- **50,781 ms across three calls** on the 1.34 M-article field
instance (`docs/audit/15`, Appendix B).

THESE TESTS ASSERT THE PLAN, NOT THE SCHEMA. An index the planner does not choose is
decoration, and "the index exists" is exactly the assertion that would stay green while the
scan came back. `EXPLAIN QUERY PLAN` is the instrument, and COVERING is the word that
distinguishes a fix from a hope.
"""

from __future__ import annotations

import sqlite3

import pytest

_DDL = """
CREATE TABLE keywords (id INTEGER PRIMARY KEY, term TEXT, mention_count INTEGER,
                       article_count INTEGER, last_reconciled_at TIMESTAMP);
"""
_OLD = "CREATE INDEX idx_keyword_mention_count ON keywords (mention_count)"
_NEW = ("CREATE INDEX idx_keyword_counter_freshness "
        "ON keywords (mention_count, last_reconciled_at)")

#: The three statements `counter_envelope` runs, verbatim in shape.
_ENVELOPE = {
    "watermark": "SELECT min(last_reconciled_at) FROM keywords WHERE mention_count > 0",
    "staleness": ("SELECT id FROM keywords WHERE mention_count > 0 AND "
                  "(last_reconciled_at IS NULL OR last_reconciled_at < '2026-09-20') LIMIT 1"),
    "n": "SELECT count(id) FROM keywords WHERE mention_count > 0",
}
#: The hot query the OLD index existed for -- it must not regress.
_TOP_TERMS = "SELECT id FROM keywords ORDER BY mention_count DESC LIMIT 50"


def _store(*indexes):
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    for ddl in indexes:
        c.execute(ddl)
    c.executemany(
        "INSERT INTO keywords (term, mention_count, article_count, last_reconciled_at) "
        "VALUES (?,?,?,?)",
        [(f"t{i}", i % 6, 1, None if i % 3 == 0 else "2026-09-01") for i in range(5000)],
    )
    c.execute("ANALYZE")
    return c


def _plan(c, sql) -> str:
    return " | ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + sql))


@pytest.mark.parametrize("name", sorted(_ENVELOPE))
def test_every_envelope_query_is_COVERING_under_the_composite(name):
    """COVERING is the whole fix: the planner answers from the index and touches no rows."""
    plan = _plan(_store(_NEW), _ENVELOPE[name])
    assert "COVERING INDEX idx_keyword_counter_freshness" in plan, plan


def test_the_watermark_query_was_NOT_covering_under_the_old_index():
    """THE NEGATIVE TWIN, and the one that makes the test above mean something. Without it
    a green suite would not distinguish "the composite fixed this" from "this was always
    fine" -- and the recorded shape is that the second reading is the comfortable one."""
    plan = _plan(_store(_OLD), _ENVELOPE["watermark"])
    assert "idx_keyword_mention_count" in plan
    assert "COVERING" not in plan, (
        "the single-column index was already covering; then F7's 50,781 ms needs another "
        f"explanation and this whole change is aimed at the wrong thing -- plan: {plan}"
    )


def test_the_hot_top_terms_scan_does_not_regress():
    """The old index's own reason for existing. The composite leads with mention_count, so
    the ordered scan is still index-only -- measured, not assumed, because this is what a
    careless "replace the index" would break."""
    assert "COVERING INDEX idx_keyword_counter_freshness" in _plan(_store(_NEW), _TOP_TERMS)


def test_keeping_BOTH_indexes_would_buy_nothing():
    """WHY THE OLD ONE IS DROPPED RATHER THAN KEPT. With both present the planner picks the
    composite for the envelope queries anyway, so the single-column index earns nothing and
    charges write amplification on an 11 M-row table -- on the write-bound instance this
    audit is about. If this ever fails, the drop needs re-arguing rather than defending."""
    both = _store(_OLD, _NEW)
    assert "idx_keyword_counter_freshness" in _plan(both, _ENVELOPE["watermark"])


def test_the_model_and_the_boot_self_heal_agree_on_the_index():
    """The store reached by `create_all` and the store reached by the self-heal must not
    end up with different indexes -- the recorded create_all-vs-migration split means BOTH
    paths are real, and a store that ran only one of them is a store someone will debug."""
    from pathlib import Path

    from src.database.models import Keyword

    names = {ix.name for ix in Keyword.__table__.indexes}
    assert "idx_keyword_counter_freshness" in names
    assert "idx_keyword_mention_count" not in names

    heal = Path("src/database/maintenance.py").read_text(encoding="utf-8")
    assert "idx_keyword_counter_freshness" in heal
    assert "DROP INDEX IF EXISTS idx_keyword_mention_count" in heal
