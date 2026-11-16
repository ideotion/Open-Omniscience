"""The keyword grouping reads the incoming table straight through, not through the term index.

`_merge_keywords` keeps one incoming row per (normalized_term, language). Left to itself SQLite
walked `idx_keyword_normalized_term` and fetched every row by rowid for its `language`: random
reads over the largest table the merge copies. On 7M rows with a cold cache and field-like memory
and disk that took 104.9 s, against 20.0 s read straight through, with the same ids. This pins the
plan and that the answer is the one the index-walking plan gave.
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from src.backup import merge as merge_mod

_GROUP = "SELECT MIN(id) FROM inc.keywords NOT INDEXED GROUP BY normalized_term, COALESCE(language,'en')"


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS inc")
    con.execute(
        "CREATE TABLE inc.keywords (id INTEGER PRIMARY KEY, term TEXT, normalized_term TEXT NOT NULL,"
        " language TEXT)"
    )
    con.execute("CREATE INDEX inc.idx_keyword_normalized_term ON keywords(normalized_term)")
    con.execute("CREATE INDEX inc.idx_keyword_language ON keywords(language)")
    rnd = random.Random(5)
    rows = []
    for i in range(1, 4001):
        t = rnd.choice(["alpha", "beta", "gamma", "delta", "Alpha", "eps"]) + str(rnd.randint(0, 300))
        rows.append((i, t, t.lower(), rnd.choice(["en", None, "fr", "de", "EN"])))
    con.executemany("INSERT INTO inc.keywords VALUES (?,?,?,?)", rows)
    return con


def test_the_merge_runs_this_statement() -> None:
    src = Path(merge_mod.__file__).read_text(encoding="utf-8")
    assert f'"{_GROUP}"' in src


def test_the_grouping_scans_the_table_and_not_the_term_index() -> None:
    plan = " | ".join(r[3] for r in _con().execute("EXPLAIN QUERY PLAN " + _GROUP))
    assert "SCAN inc.keywords" in plan and "USING INDEX" not in plan, plan


def test_the_ids_are_the_ones_the_index_walk_gave() -> None:
    con = _con()
    walked = con.execute(_GROUP.replace(" NOT INDEXED", "")).fetchall()
    plan = " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + _GROUP.replace(" NOT INDEXED", "")))
    assert "USING INDEX idx_keyword_normalized_term" in plan, plan  # the old plan really was the index walk
    assert sorted(walked) == sorted(con.execute(_GROUP).fetchall())


def test_both_paths_build_the_same_set() -> None:
    con = _con()
    merge_mod._materialise_rep(con, "rep_keywords", _GROUP)
    via_temp = {r[0] for r in con.execute("SELECT rep_id FROM temp.rep_keywords")}
    assert merge_mod._REP_GROUP_SQL.fullmatch(_GROUP) is not None  # the low-memory path reads this shape too
    assert via_temp == {r[0] for r in con.execute(_GROUP.replace(" NOT INDEXED", ""))}
