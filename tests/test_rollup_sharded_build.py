"""The rollup build is cut into shards sized from the memory limit, so a corpus the old build could not hold is built.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install (1,004 MB DuckDB limit, offload off for an encrypted corpus): the boot's build staged
every mention into ONE table and ran ONE GROUP BY with COUNT(DISTINCT) over it, and stopped at DuckDB's limit after
921 s, every boot. Reproduced on a seeded corpus of 12,000,000 mentions / 1,500,000 keywords at the same limit
(out of memory at the aggregate, 71 s in). The build now stages each mention into one of ``shards`` tables by
``keyword_id % shards``, aggregates them one at a time and drops each stage as it is aggregated.

These tests pin what that must never get wrong, on small seeded corpora (the numbers on the 12 M corpus are in the
PR, measured, not asserted here):

  * the answer is the SAME for any shard count (equal to an independent GROUP BY over the rows);
  * the shard count is derived from the limit and the corpus size, not fixed, and follows the measured model;
  * a shard that fails (any error, the engine's limit included) leaves the rollup that was there untouched and no
    stage or half-built table behind: a half-filled rollup is never served;
  * a shard that runs out of memory is halved and tried again before the build gives up, and gives up as the
    same ``duckdb-limit`` decline the single-pass build raised, carrying the shard count;
  * the ids stay 32-bit only while they fit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from src.analytics import columnar
from tests.test_rollup_build_streaming import (  # noqa: F401 - fixture
    _con,
    _reference_daily,
    _seed,
    session,
)

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


def _daily(con):
    return sorted(
        (int(k), str(d), int(m), int(a))
        for k, d, m, a in con.execute("SELECT keyword_id, day, mentions, articles_on_day FROM keyword_daily").fetchall()
    )


def _tables(con):
    return sorted(r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall())


def _force_shards(monkeypatch, shards):
    real = columnar.plan_build_shards
    monkeypatch.setattr(columnar, "plan_build_shards", lambda rows, limit_mb: {**real(rows, limit_mb), "shards": shards})


class OutOfMemoryException(Exception):  # noqa: N818 - the engine's own class name is what the build matches on
    pass


class _FailingCon:
    """A real connection whose aggregate INSERTs can be made to fail; everything else is forwarded."""

    def __init__(self, con, fail):
        self._con = con
        self._fail = fail
        self.aggregates: list[str] = []

    def execute(self, sql, *args, **kw):
        if sql.lstrip().startswith("INSERT INTO keyword_daily_building"):
            self.aggregates.append(sql)
            exc = self._fail(sql, len(self.aggregates))
            if exc is not None:
                raise exc
        return self._con.execute(sql, *args, **kw)

    def __getattr__(self, name):
        return getattr(self._con, name)


# --------------------------------------------------------------------------- #
# the answer does not depend on the shard count
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("shards", [1, 2, 3, 7])
def test_any_shard_count_gives_the_independent_group_by(session, monkeypatch, shards):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7, undated_every=11)
    _force_shards(monkeypatch, shards)
    con = _con()
    tally = columnar.build_keyword_daily(con, session, batch_size=50)
    assert _daily(con) == _reference_daily(session)
    assert tally["shards"] == shards and tally["shard_splits"] == 0
    assert tally["keyword_daily_rows"] == len(_reference_daily(session))


def test_the_stage_is_cut_by_keyword_and_every_stage_is_gone_when_the_build_ends(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 4)
    seen: dict[str, list] = {}
    real = columnar._bulk_insert

    def spy(con, table, types, rows):
        if table.startswith("keyword_daily_stage_"):
            seen.setdefault(table, []).extend(rows)
            assert types == ("INTEGER", "DATE", "BIGINT", "INTEGER")
        return real(con, table, types, rows)

    monkeypatch.setattr(columnar, "_bulk_insert", spy)
    con = _con()
    columnar.build_keyword_daily(con, session, batch_size=50)
    assert sorted(seen) == [f"keyword_daily_stage_{j}" for j in range(4)]
    for j in range(4):
        assert seen[f"keyword_daily_stage_{j}"] and all(r[0] % 4 == j for r in seen[f"keyword_daily_stage_{j}"])
    assert sum(len(v) for v in seen.values()) == 200
    left = _tables(con)
    assert "keyword_daily" in left and not [n for n in left if "stage" in n or "building" in n]


def test_each_stage_is_dropped_as_soon_as_it_is_aggregated(session, monkeypatch):  # noqa: F811
    """What keeps the resident total flat: the stages not yet aggregated shrink as the rollup grows."""
    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 4)
    con = _con()
    remaining: list[int] = []

    def hook(stage, done):
        if stage == "aggregate":
            remaining.append(len([n for n in _tables(con) if n.startswith("keyword_daily_stage_")]))

    columnar.build_keyword_daily(con, session, batch_size=50, on_batch=hook)
    assert remaining == [4, 3, 2, 1, 0]


def test_ids_beyond_32_bits_get_wide_columns_and_the_same_answer(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=12, mentions_per=3)
    big = 3_000_000_000
    session.execute(text(
        "INSERT INTO keywords (id, term, normalized_term, is_entity, mention_count, frequency, is_ngram, ngram_size, "
        "relevance_score) VALUES (:i, 'wide', 'wide', 0, 2, 0, 0, 1, 0.0)"), {"i": big})
    session.execute(text(
        "INSERT INTO keyword_mentions (id, keyword_id, article_id, count, observed_on, created_at) VALUES "
        "(1000, :k, :a, 2, '2026-03-02', '2026-03-10 00:00:01'), (1001, :k, :a2, 1, '2026-03-02', '2026-03-10 00:00:02')"),
        {"k": big, "a": big + 1, "a2": big + 2})
    session.commit()
    seen = set()
    real = columnar._bulk_insert
    monkeypatch.setattr(columnar, "_bulk_insert",
                        lambda con, table, types, rows: (seen.add(types) if "stage" in table else None, real(con, table, types, rows))[1])
    _force_shards(monkeypatch, 3)
    con = _con()
    columnar.build_keyword_daily(con, session)
    assert seen == {("BIGINT", "DATE", "BIGINT", "BIGINT")}
    assert _daily(con) == _reference_daily(session)


# --------------------------------------------------------------------------- #
# the shard count is derived from the limit, and follows the measured model
# --------------------------------------------------------------------------- #

def test_a_small_corpus_is_one_shard_and_a_big_one_is_cut_from_the_limit():
    assert columnar.plan_build_shards(0, 1004)["shards"] == 1
    assert columnar.plan_build_shards(50_000, 1004)["shards"] == 1
    tier = columnar.plan_build_shards(12_000_000, 1004)  # the install that stopped, and the corpus it was seeded as
    assert tier["shards"] == 6 and tier["fits"] is True and tier["limit_mib"] == 957.5  # DuckDB prints 957.4 MiB for "1004MB"
    assert tier["predicted_peak_mib"] <= 0.7 * tier["limit_mib"]
    assert columnar.plan_build_shards(12_000_000, 4000)["shards"] == 1, "a limit with room needs no cut"


def test_the_count_grows_with_the_corpus_and_shrinks_with_the_limit():
    counts = [columnar.plan_build_shards(n, 1004)["shards"] for n in range(1_000_000, 40_000_000, 3_000_000)]
    assert counts == sorted(counts)
    by_limit = [columnar.plan_build_shards(12_000_000, lim)["shards"] for lim in (600, 800, 1004, 1500, 3000)]
    assert by_limit == sorted(by_limit, reverse=True)


def test_past_the_point_where_another_table_costs_more_than_it_saves_the_count_stops_and_says_it_does_not_fit():
    import math

    huge = columnar.plan_build_shards(2_000_000_000, 1004)
    cap = math.isqrt(int(2_000_000_000 * columnar._BUILD_AGGREGATE_BYTES_PER_ROW / columnar._MIB
                         / columnar._BUILD_TABLE_OVERHEAD_MIB))
    assert huge["shards"] == cap and huge["fits"] is False
    assert columnar.plan_build_shards(12_000_000, 300)["fits"] is False


@pytest.mark.parametrize("shards,measured", [(4, 754), (8, 615), (16, 546)])
def test_the_model_reproduces_the_peaks_measured_on_the_12_million_mention_corpus(shards, measured):
    """DuckDB 1.5.6, offload off, 2 threads, ``duckdb_memory()`` sampled every 20 ms; see the note above
    ``plan_build_shards``. A model that drifts from what was measured is a plan nobody can trust."""
    assert columnar.predicted_build_peak_mib(12_000_000, shards) == pytest.approx(measured, rel=0.05)


# --------------------------------------------------------------------------- #
# a shard that fails serves nothing; one that runs out of memory is halved first
# --------------------------------------------------------------------------- #

def _sentinel(con):
    con.execute("CREATE OR REPLACE TABLE keyword_daily (keyword_id BIGINT, day DATE, mentions BIGINT, articles_on_day BIGINT)")
    con.execute("INSERT INTO keyword_daily VALUES (999, DATE '2026-01-01', 5, 5)")


def test_a_shard_that_fails_leaves_the_rollup_untouched_and_no_table_behind(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 4)
    real = _con()
    _sentinel(real)
    con = _FailingCon(real, lambda sql, n: RuntimeError("shard 3 broke") if n == 3 else None)
    with pytest.raises(RuntimeError, match="shard 3 broke"):
        columnar.build_keyword_daily(con, session, batch_size=50)
    assert real.execute("SELECT * FROM keyword_daily").fetchall() == [(999, __import__("datetime").date(2026, 1, 1), 5, 5)]
    assert not [n for n in _tables(real) if "stage" in n or "building" in n]


def test_a_build_stopped_while_streaming_leaves_no_stage_behind(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 4)
    con = _con()

    def stop(stage, done):
        if stage == "mentions" and done >= 100:
            raise columnar.BuildDeclined("mem-low", {"rows_done": done})

    with pytest.raises(columnar.BuildDeclined):
        columnar.build_keyword_daily(con, session, batch_size=50, on_batch=stop)
    assert not [n for n in _tables(con) if "stage" in n or "building" in n]


def test_a_shard_that_runs_out_of_memory_is_halved_and_the_answer_is_unchanged(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7)
    _force_shards(monkeypatch, 3)
    failed: set[str] = set()

    def fail_each_whole_shard_once(sql, n):
        if "WHERE" in sql or sql in failed:
            return None
        failed.add(sql)
        return OutOfMemoryException("limit")

    con = _FailingCon(_con(), fail_each_whole_shard_once)
    tally = columnar.build_keyword_daily(con, session, batch_size=50)
    assert tally["shard_splits"] == 3, "each of the three whole shards was halved once"
    assert _daily(con) == _reference_daily(session)


def test_a_shard_that_cannot_be_halved_small_enough_is_the_duckdb_limit_decline_with_the_count(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 4)
    real = _con()
    _sentinel(real)
    con = _FailingCon(real, lambda sql, n: OutOfMemoryException("limit"))
    with pytest.raises(columnar.BuildDeclined) as caught:
        columnar.build_keyword_daily(con, session, batch_size=50)
    d = caught.value
    assert d.reason == "duckdb-limit"
    assert d.detail["stage"] == "aggregate" and d.detail["shards"] == 4 and d.detail["shard"] == 0
    assert d.detail["split"] == columnar._BUILD_MAX_SPLIT and d.detail["rows_done"] == 200
    assert "limit" not in {str(v) for v in d.detail.values()}, "the engine's own words are not carried"
    assert len(con.aggregates) == 5, "whole, halves, quarters, eighths, sixteenths: then it gives up"
    assert real.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0] == 1
    assert not [n for n in _tables(real) if "stage" in n or "building" in n]


def test_an_error_that_is_not_the_engines_limit_is_never_retried_by_halving(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=20, mentions_per=3)
    _force_shards(monkeypatch, 2)
    con = _FailingCon(_con(), lambda sql, n: ValueError("not a memory problem"))
    with pytest.raises(ValueError):
        columnar.build_keyword_daily(con, session)
    assert len(con.aggregates) == 1
