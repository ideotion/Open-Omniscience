"""The all-history top-terms query sums per keyword id first, and answers what the one-step grouping answered.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_top_terms_query`` joined every ``keyword_daily`` row to ``keyword_meta`` and grouped the joined rows by four text columns, so the
engine held one text row per keyword and DAY. At the 1,004 MB tier that failed with the engine's memory error at 20, 24 and 28 M mentions
(one run per size on generated corpora). The query now sums per ``keyword_id`` (an integer key) in an inner query, joins the metadata to
that, and keeps the text grouping, so keywords that share their four text columns still add. These tests pin both halves: the rows are
the shipped query's rows, and the join feeds the text grouping one row per keyword.
"""

from __future__ import annotations

import datetime
import json

import pytest

from src.analytics import columnar

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

# (keyword_id, normalized_term, term, kind, is_entity, entity_type, language): ids 1+2 and 3+4 share their four text columns.
_META = [
    (1, "alpha", "Alpha", "term", False, None, "en"),
    (2, "alpha", "Alpha", "term", False, None, "en"),
    (3, "beta corp", "Beta Corp", "organization", True, "organization", "en"),
    (4, "beta corp", "Beta Corp", "organization", True, "organization", "en"),
    (5, "gamma", "Gamma", "term", False, None, "en"),
    (6, "delta", "Delta", "person", True, "person", "fr"),
    (7, "alpha", "Alpha", "term", False, None, "fr"),
    (8, "epsilon", "Epsilon", "term", False, None, "en"),
    (9, "zeta", "Zeta", "term", False, None, "en"),
]
# Ids 1 and 2 start high so that their merged pair is the top row and the largest single id is not.
_BASE = {1: 6000, 2: 6000, 3: 40, 4: 30, 5: 90, 6: 20, 7: 70, 8: 60, 9: 80}
_DAY0 = datetime.date(2026, 1, 1)
_DAYS = 12


def _rows() -> list[tuple]:
    out = []
    for kid, base in _BASE.items():
        for i in range(_DAYS):
            if (kid + i) % 5 == 0:
                continue  # a keyword is not present every day
            out.append((kid, _DAY0 + datetime.timedelta(days=i), base + 7 * kid + i, 1 + (kid * i) % 4))
    return out


@pytest.fixture()
def con():
    import duckdb

    c = duckdb.connect(":memory:")
    c.execute(columnar._KEYWORD_DAILY_DDL)
    c.execute(columnar._KEYWORD_META_DDL)
    c.executemany("INSERT INTO keyword_daily VALUES (?, ?, ?, ?)", _rows())
    c.executemany("INSERT INTO keyword_meta VALUES (?, ?, ?, ?, ?, ?, ?)", _META)
    yield c
    c.close()


def _shipped_query(start_day, end_day, kind, limit):
    """The text of the query as it was before this change, with the parameters in its order."""
    params: list = []
    where = ["d.day >= ?"] if start_day is not None else []
    if start_day is not None:
        params.append(start_day)
    if end_day is not None:
        where.append("d.day <= ?")
        params.append(end_day)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    kind_sql = columnar._kind_where(kind, params)
    params.append(int(limit))
    sql = (
        "SELECT m.term, m.normalized_term, m.kind, m.language, "
        "SUM(d.mentions) AS mentions, SUM(d.articles_on_day) AS articles "
        "FROM keyword_daily d JOIN keyword_meta m ON m.keyword_id = d.keyword_id"
        + where_sql + kind_sql
        + " GROUP BY m.term, m.normalized_term, m.kind, m.language "
        "ORDER BY mentions DESC LIMIT ?"
    )
    return sql, params


_WINDOWS = [
    (None, None),
    (_DAY0 + datetime.timedelta(days=4), None),
    (None, _DAY0 + datetime.timedelta(days=7)),
    (_DAY0 + datetime.timedelta(days=3), _DAY0 + datetime.timedelta(days=8)),
]


@pytest.mark.parametrize("kind", [None, "term", "entity", "organization"])
@pytest.mark.parametrize("window", _WINDOWS)
@pytest.mark.parametrize("limit", [1, 4, 80])
def test_the_pre_aggregated_query_answers_what_the_one_step_grouping_answered(con, kind, window, limit):
    start, end = window
    old_sql, old_params = _shipped_query(start, end, kind, limit)
    new_sql, new_params = columnar._top_terms_query(start, end, kind, limit)
    assert new_params == old_params
    old = con.execute(old_sql, old_params).fetchall()
    new = con.execute(new_sql, new_params).fetchall()
    # No two of the corpus's text tuples tie on mentions within a window, so the order below is the engine's, not a tie-break.
    mentions = [r[4] for r in old]
    assert len(set(mentions)) == len(mentions), "the corpus must not tie, or the comparison would test the engine's tie order"
    assert new == old


def test_keywords_sharing_their_text_columns_add_and_another_language_is_not_merged(con):
    sql, params = columnar._top_terms_query(None, None, None, 80)
    got = {(r[0], r[3]): int(r[4]) for r in con.execute(sql, params).fetchall()}
    by_id = {}
    for kid, _day, mentions, _articles in _rows():
        by_id[kid] = by_id.get(kid, 0) + mentions
    assert got[("Alpha", "en")] == by_id[1] + by_id[2]
    assert got[("Beta Corp", "en")] == by_id[3] + by_id[4]
    assert got[("Alpha", "fr")] == by_id[7]


def test_the_corpus_tells_the_shapes_apart(con):
    # Grouping by id alone, or by id and text, would not give the merged top row: this is what makes the equality test a test.
    sql, params = columnar._top_terms_query(None, None, None, 1)
    top = con.execute(sql, params).fetchall()[0]
    by_id = {}
    for kid, _day, mentions, _articles in _rows():
        by_id[kid] = by_id.get(kid, 0) + mentions
    assert top[0] == "Alpha" and top[3] == "en"
    assert int(top[4]) == by_id[1] + by_id[2] > max(by_id.values())


def _walk(node):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def _plan(con, sql, params):
    con.execute("PRAGMA enable_profiling = 'json'")
    rows = con.execute("EXPLAIN ANALYZE " + sql, params).fetchall()
    text = rows[-1][1] if len(rows[-1]) > 1 else rows[-1][0]
    return json.loads(text)


def test_the_join_feeds_the_text_grouping_one_row_per_keyword_not_one_per_keyword_and_day(con):
    sql, params = columnar._top_terms_query(None, None, None, 80)
    plan = _plan(con, sql, params)
    nodes = list(_walk(plan))
    joins = [n for n in nodes if n.get("operator_type") == "HASH_JOIN"]
    assert joins, [n.get("operator_type") for n in nodes]
    rows_out = [int(j["operator_cardinality"]) for j in joins]
    # nine keywords; the daily table holds many more rows than that
    assert max(rows_out) == len(_META), rows_out
    assert len(_rows()) > 5 * len(_META)
