"""R101 on the restore path: an article that arrives ALREADY quarantined adds nothing to the keyword counters.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The derived-row carry (``src/backup/merge.py``) copies an incoming article's mention rows and moves the counters by
what ``index_article`` would have moved them by. Under R101 a quarantined article contributes nothing to the counters,
so the carry's delta must leave it out: the post-merge reconcile is filtered the same way, but it is budgeted and can
stop part-way, so the delta has to be exact on its own. The rows themselves are still carried (quarantine is
reversible). Built on ``tests/test_derived_carry.py``'s backup and merge helpers.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.test_derived_carry import _backup, _merge_only, _scalar, _variant


@pytest.fixture(scope="module")
def backup(tmp_path_factory):
    from src.database.country_form import writing_in

    path = tmp_path_factory.mktemp("qcarry") / "backup.db"
    with writing_in("alpha2"):
        _backup(path)
    return path


_DRIFT_UNQUARANTINED = (
    "SELECT COUNT(*) FROM (SELECT k.id FROM keywords k LEFT JOIN ("
    " SELECT m.* FROM keyword_mentions m JOIN articles a ON a.id = m.article_id WHERE a.quarantined IS NOT 1"
    ") m ON m.keyword_id = k.id"
    " GROUP BY k.id HAVING k.mention_count <> COALESCE(SUM(m.count), 0) OR k.article_count <> COUNT(m.id))"
)


def test_a_carried_quarantined_article_adds_nothing_to_the_counters(backup, tmp_path, monkeypatch):
    from src.database.country_form import writing_in

    variant = _variant(
        backup, tmp_path, "quarantined.db",
        "UPDATE articles SET quarantined = 1, quarantine_reason = 'url_homepage' WHERE id = (SELECT MIN(id) FROM articles)",
    )
    with writing_in("alpha2"):
        _counts, _batch, working = _merge_only(variant, tmp_path, monkeypatch)

    con = sqlite3.connect(working)
    try:
        (q_id,) = con.execute("SELECT id FROM articles WHERE quarantined IS 1").fetchone()
        carried = con.execute("SELECT COUNT(*) FROM keyword_mentions WHERE article_id = ?", (q_id,)).fetchone()[0]
    finally:
        con.close()
    assert carried > 0, "the quarantined article's rows must still be carried: quarantine is reversible"
    assert not _scalar(working, _DRIFT_UNQUARANTINED), "the carry counted a quarantined article's mentions"


def test_the_carry_delta_reads_the_quarantine_index_not_the_article_rows():
    """The filter is answered from ``idx_article_quarantined``: reading ``quarantined`` off each article row would
    walk its overflow pages (the column was added by ALTER, so it sits after ``content``)."""
    import inspect

    from sqlalchemy import create_engine

    from src.backup import merge
    from src.database.models import Base

    # The plan below is of the statement merge.py actually runs: its filter text is pinned here first.
    assert " AND w.new NOT IN (SELECT id FROM main.articles WHERE quarantined IS 1)" in inspect.getsource(merge)
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TEMP TABLE carry_win (old INTEGER, new INTEGER, kw INTEGER)")
        c.exec_driver_sql("CREATE TEMP TABLE carry_kw (old INTEGER PRIMARY KEY, new INTEGER)")
        plan = " | ".join(
            r[3]
            for r in c.exec_driver_sql(
                "EXPLAIN QUERY PLAN SELECT ck.new, SUM(im.count), COUNT(*) FROM temp.carry_win w"
                " CROSS JOIN main.keyword_mentions im ON im.article_id = w.old"
                " JOIN temp.carry_kw ck ON ck.old = im.keyword_id WHERE w.kw = 1"
                " AND w.new NOT IN (SELECT id FROM main.articles WHERE quarantined IS 1)"
                " GROUP BY ck.new"
            )
        )
    assert "COVERING INDEX idx_article_quarantined" in plan, plan
    assert "articles USING INTEGER PRIMARY KEY" not in plan, plan
