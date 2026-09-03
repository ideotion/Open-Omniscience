"""
S3.5 (2026-09-02 crash analysis): the rollup's full build stops full-scanning.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The keyset was correct and unservable. ``COALESCE(created_at, :epoch)`` is an
expression, so no index on ``created_at`` could satisfy the range or the ORDER BY,
and each 50k batch was a bare ``SCAN keyword_mentions`` plus a temp B-tree sort --
109-194 s a batch over 187 batches in the field.

The plan is asserted over the statements the REAL build EMITS, captured with a
``before_cursor_execute`` listener, never a hand-written lookalike: the recorded
lesson is that a standalone probe differs from the shipped query in the table's
other indexes, its stats and its ANALYZE state, and all three move the planner.

The equivalence half matters as much as the plan half. The fix drops the COALESCE
and splits the scan in two, so the guard that the rollup still absorbs exactly the
same mentions is what makes the speedup safe rather than merely fast.
"""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("duckdb", reason="the columnar rollup needs the [columnar] extra")

from sqlalchemy import create_engine, event, insert, select, text
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.database.models import Base, Keyword, KeywordMention

_EPOCH = "1970-01-01 00:00:00"


def _corpus(tmp_path: pathlib.Path, *, n=400, null_every=0, all_null=False):
    """A real store built from the real metadata, so the index set, the column
    order and the stats are the shipped ones."""
    eng = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    s.add_all([Keyword(term=f"k{i}", normalized_term=f"k{i}") for i in range(1, 21)])
    s.flush()
    base = datetime(2026, 5, 1, tzinfo=UTC).replace(tzinfo=None)
    rows = []
    for i in range(1, n + 1):
        if all_null:
            ca = None
        elif null_every and i % null_every == 0:
            ca = None
        else:
            ca = base + timedelta(minutes=i)
        rows.append({
            "keyword_id": 1 + (i % 20),
            "article_id": i,
            "count": 1 + (i % 3),
            "observed_on": (base + timedelta(days=i % 30)).date(),
            "created_at": ca,
        })
    s.execute(insert(KeywordMention), rows)
    s.commit()
    s.execute(text("ANALYZE"))
    s.commit()
    return eng, s


def _captured_selects(eng, s, con):
    """Drive the REAL build and keep every SELECT it issues against the table."""
    seen: list[tuple[str, dict]] = []

    def _listen(conn, cursor, statement, parameters, context, executemany):
        if "keyword_mentions" in statement and statement.lstrip().upper().startswith("SELECT"):
            seen.append((statement, parameters))

    event.listen(eng, "before_cursor_execute", _listen)
    try:
        columnar.build_keyword_daily(con, s, batch_size=50)
    finally:
        event.remove(eng, "before_cursor_execute", _listen)
    return seen


def _plan(raw: sqlite3.Connection, sql: str, params) -> list[str]:
    return [r[3] for r in raw.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]


def test_the_real_builds_batch_query_is_an_index_search_not_a_table_scan(tmp_path):
    eng, s = _corpus(tmp_path, n=400, null_every=50)
    con = columnar.connect(passphrase=None)
    assert con is not None
    seen = _captured_selects(eng, s, con)
    s.close()

    # Only the batch loops read this table with a LIMIT; MAX(created_at) does not.
    batches = [(q, p) for q, p in seen if "LIMIT" in q.upper()]
    assert batches, "the build issued no batch query at all — nothing was measured"

    raw = sqlite3.connect(str(tmp_path / "c.db"))
    scanned = []
    for q, p in batches:
        plan = _plan(raw, q, p)
        joined = " | ".join(plan)
        # A bare `SCAN <table>` with no USING is the only real smell: an index-only
        # `SCAN ... USING COVERING INDEX` is healthy (the recorded classification).
        if "SCAN keyword_mentions" in joined and "USING" not in joined:
            scanned.append((joined, q))
        assert "USE TEMP B-TREE FOR ORDER BY" not in joined, (
            f"the batch still sorts its whole match set per batch: {joined}"
        )
        assert "ix_mention_created_id" in joined, (
            f"the ordering index is not serving the batch: {joined}\n{q}"
        )
    raw.close()
    assert not scanned, f"a batch query still full-scans the table: {scanned}"


def test_the_coalesce_expression_is_gone_from_the_emitted_sql(tmp_path):
    """The mechanism, not the wording: an expression over the indexed column is
    what made the index unreachable, so its absence is the property."""
    eng, s = _corpus(tmp_path, n=120, null_every=40)
    con = columnar.connect(passphrase=None)
    assert con is not None
    seen = _captured_selects(eng, s, con)
    s.close()
    offenders = [q for q, _ in seen if "COALESCE" in q.upper()]
    assert not offenders, f"a batch query still wraps the indexed column: {offenders}"


def test_the_split_scan_absorbs_exactly_the_rows_the_old_keyset_did(tmp_path):
    """The equivalence half. The old single-loop keyset is reproduced here from the
    pre-fix SQL and its row set compared against what the shipped build streams."""
    eng, s = _corpus(tmp_path, n=500, null_every=37)
    raw = sqlite3.connect(str(tmp_path / "c.db"))
    bound = raw.execute("SELECT MAX(created_at) FROM keyword_mentions").fetchone()[0]

    # -- the OLD loop, verbatim in shape, driven to exhaustion.
    old_ids: list[int] = []
    cursor_ts, cursor_id = None, 0
    while True:
        base = ("SELECT id, created_at FROM keyword_mentions "
                "WHERE COALESCE(created_at, :epoch) <= :bound ")
        p = {"epoch": _EPOCH, "bound": bound, "batch_size": 50}
        if cursor_ts is None:
            sql = base + "ORDER BY COALESCE(created_at, :epoch), id LIMIT :batch_size"
        else:
            sql = base + ("AND (COALESCE(created_at, :epoch) > :cursor_ts "
                          "OR (COALESCE(created_at, :epoch) = :cursor_ts AND id > :cursor_id)) "
                          "ORDER BY COALESCE(created_at, :epoch), id LIMIT :batch_size")
            p |= {"cursor_ts": cursor_ts, "cursor_id": cursor_id}
        chunk = raw.execute(sql, p).fetchall()
        if not chunk:
            break
        old_ids.extend(int(r[0]) for r in chunk)
        cursor_ts = chunk[-1][1] if chunk[-1][1] is not None else _EPOCH
        cursor_id = int(chunk[-1][0])

    # -- the SHIPPED build, its emitted batches replayed for their ids.
    con = columnar.connect(passphrase=None)
    assert con is not None
    seen = _captured_selects(eng, s, con)
    new_ids: list[int] = []
    for q, p in seen:
        if "LIMIT" not in q.upper():
            continue
        new_ids.extend(int(r[0]) for r in raw.execute(q, p).fetchall())
    raw.close()
    s.close()

    assert sorted(set(old_ids)) == sorted(set(new_ids)), (
        "the split scan absorbs a different set of mentions than the keyset it replaced"
    )
    assert len(new_ids) == len(set(new_ids)), "a mention was streamed twice"
    assert len(old_ids) > 400, "the fixture never exercised more than one batch"


def test_a_corpus_whose_created_at_is_entirely_null_is_no_longer_dropped(tmp_path):
    """The one behaviour change, in the honest direction. MAX(created_at) is NULL
    there, the old code skipped its whole loop, and the rollup came out EMPTY —
    real mentions with real observed_on dates, silently absent."""
    eng, s = _corpus(tmp_path, n=80, all_null=True)
    con = columnar.connect(passphrase=None)
    assert con is not None
    tally = columnar.build_keyword_daily(con, s, batch_size=25)
    s.close()
    assert tally["streamed_mentions"] == 80, (
        f"the NULL-created_at phase streamed {tally['streamed_mentions']} of 80"
    )
    assert tally["last_mention_id"] == 80, "the watermark ignored the NULL phase"
    assert con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0] > 0


def test_no_insert_path_leaves_created_at_null(tmp_path):
    """Phase A orders by rowid alone, which is safe ONLY because nothing can ADD a
    row to that phase mid-scan. That rests on the column default reaching both real
    idioms — a plain ORM add and the bulk insert index_article uses — so it is
    asserted rather than assumed."""
    eng = create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Keyword(term="k", normalized_term="k"))
    s.flush()
    s.add(KeywordMention(keyword_id=1, article_id=1, count=1))
    s.flush()
    s.execute(insert(KeywordMention), [{"keyword_id": 1, "article_id": 2, "count": 1}])
    s.commit()
    created = s.execute(select(KeywordMention.created_at)).scalars().all()
    s.close()
    assert created and all(c is not None for c in created), (
        "an insert path leaves created_at NULL, so phase A's set can GROW mid-scan "
        "and its rowid keyset is no longer safe"
    )


def test_the_ordering_index_is_declared_on_the_model_and_the_boot_self_heal(tmp_path):
    """A HOT_INDEXES entry that no model declares reads as schema drift to
    alembic_stamp_align (the recorded 2026-08-20 lesson), so the two must agree."""
    from src.database.maintenance import HOT_INDEXES

    assert "ix_mention_created_id" in HOT_INDEXES
    names = {ix.name for ix in KeywordMention.__table__.indexes}
    assert "ix_mention_created_id" in names, "the boot self-heal creates an undeclared index"
    ix = next(i for i in KeywordMention.__table__.indexes if i.name == "ix_mention_created_id")
    assert [c.name for c in ix.columns] == ["created_at", "id"]
    # Plain columns only: an expression index is what alembic cannot compare.
    assert all(hasattr(c, "name") for c in ix.expressions)
