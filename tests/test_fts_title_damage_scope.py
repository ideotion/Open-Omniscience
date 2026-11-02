"""A failing read of the titles-only index is the SEARCH INDEX's damage, not the articles' (damage.scope_of).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Without this, ``article_fts_title`` was not matched by the shadow-table pattern, so a read that failed
inside it was scoped ``data`` and routed to verify-then-salvage, the heavy route, for damage to an index
that is rebuilt from the articles (``POST /api/search/instant/build?rebuild=true``).
"""

from __future__ import annotations

import pytest

from src.database import damage


@pytest.mark.parametrize("table", ["article_fts_title", "article_fts_title_data", "article_fts_title_idx",
                                   "article_fts_title_docsize", "article_fts_title_vocab", "article_fts", "article_fts_data"])
def test_a_statement_over_the_index_alone_is_search_index_scope(table):
    scope, basis = damage.scope_of(11, f"SELECT rowid FROM {table} WHERE {table} MATCH ? ORDER BY rowid DESC LIMIT ?")
    assert scope == damage.SCOPE_SEARCH_INDEX and "search index" in basis


def test_a_statement_that_also_reads_articles_still_cannot_say_which_failed():
    scope, _ = damage.scope_of(
        11, "SELECT rowid FROM article_fts_title WHERE article_fts_title MATCH ? AND EXISTS (SELECT 1 FROM articles a WHERE a.id = article_fts_title.rowid)"
    )
    assert scope == damage.SCOPE_DATA


def test_other_tables_that_merely_start_alike_are_not_the_index():
    assert damage.scope_of(11, "SELECT 1 FROM article_fts_norm")[0] == damage.SCOPE_DATA
