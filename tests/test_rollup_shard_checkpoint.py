"""R169: the build checkpoints the rollup it is building BEFORE each shard's aggregate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every shard lands uncompressed in the in-memory rollup being built, so the rollup alone is hundreds of MiB by the last shards.
Measured at 1,004 MB with no other cursor reading (16 M mentions, 26 shards): the build's own reads 576 -> 199 MiB, the process
high-water mark 1,121 -> 508 MiB, and a limit of 600 MB builds where the unchanged build is declined; a 20 M corpus that was a kept
stop builds and serves. These tests pin the shape: once per shard and BEFORE its aggregate, the engine's wall at the checkpoint is a
stop at stage ``checkpoint``, any other fatal is an unusable instance, any other error carries on and is named, and the rollup is
the same rows with or without it.
"""

from __future__ import annotations

import pytest

from src.analytics import columnar
from tests.test_rollup_build_streaming import (  # noqa: F401 - fixtures
    _FATAL_WORDS,
    FatalException,
    _con,
    _FatalAt,
    _reference_daily,
    _seed,
    session,
)
from tests.test_rollup_sharded_build import _daily, _force_shards

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


class _Recorder:
    """A real connection that notes the order of the checkpoints and the whole-shard aggregates."""

    def __init__(self, con):
        self._con = con
        self.order: list[str] = []

    def execute(self, sql, *a, **k):
        head = sql.strip()
        if head.upper() == "CHECKPOINT":
            self.order.append("checkpoint")
        elif head.startswith("INSERT INTO keyword_daily_building") and " WHERE " not in head:
            self.order.append("aggregate")
        return self._con.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._con, name)


def test_every_shard_is_checkpointed_once_and_before_its_own_aggregate(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7)
    _force_shards(monkeypatch, 4)
    con = _Recorder(_con())
    tally = columnar.build_keyword_daily(con, session, batch_size=50)
    assert con.order == ["checkpoint", "aggregate"] * 4, "each shard's aggregate is preceded by its own checkpoint"
    assert tally["shard_checkpoints"] == 4 and tally["shard_checkpoint_failures"] == 0
    assert tally["shard_checkpoint_first_failure"] is None and tally["shard_checkpoint_secs"] >= 0


def test_the_rollup_is_the_same_rows_with_the_checkpoints_and_without_them(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7, undated_every=11)
    _force_shards(monkeypatch, 3)
    with_ck = _con()
    columnar.build_keyword_daily(with_ck, session, batch_size=50)
    monkeypatch.setattr(columnar, "_checkpoint", lambda con: {
        "outcome": "ok", "compacted": False, "reason": None, "resident_before_mib": None, "resident_after_mib": None, "secs": 0.0})
    without = _con()
    columnar.build_keyword_daily(without, session, batch_size=50)
    assert _daily(with_ck) == _daily(without) == _reference_daily(session)
    meta = "SELECT * FROM keyword_meta ORDER BY keyword_id"
    assert with_ck.execute(meta).fetchall() == without.execute(meta).fetchall()


def test_a_fatal_allocation_error_at_the_checkpoint_is_a_limit_stop_at_stage_checkpoint_naming_the_shard(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7)
    _force_shards(monkeypatch, 4)
    con = _FatalAt(_con(), "CHECKPOINT", after=2)  # the third shard's checkpoint
    with pytest.raises(columnar.BuildDeclined) as got:
        columnar.build_keyword_daily(con, session, batch_size=50, snapshot=columnar.budget_snapshot())
    d = got.value.detail
    assert got.value.reason == "duckdb-limit" and d["stage"] == "checkpoint" and d["shard"] == 2 and d["shards"] == 4
    assert d["engine_error_class"] == "FatalException" and d["duckdb_limit_mb"] > 0
    assert con.fired == 1, "nothing is retried on the invalid instance"
    assert "allocate" not in repr(d) and "957" not in repr(d), "the engine's words go nowhere"


def test_any_other_fatal_error_at_the_checkpoint_is_an_unusable_instance_not_a_stop(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=30, mentions_per=4)
    _force_shards(monkeypatch, 2)
    con = _FatalAt(_con(), "CHECKPOINT", words="FATAL Error: database has been invalidated")
    with pytest.raises(RuntimeError, match="unusable"):
        columnar.build_keyword_daily(con, session, batch_size=50)


def test_any_other_error_at_the_checkpoint_carries_on_and_is_named_with_its_shard_and_class(session, monkeypatch):  # noqa: F811
    _seed(session, keywords=61, mentions_per=7)
    _force_shards(monkeypatch, 3)

    class Refusing(_Recorder):
        def execute(self, sql, *a, **k):
            if sql.strip().upper() == "CHECKPOINT":
                raise RuntimeError("engine words that must not be kept")
            return super().execute(sql, *a, **k)

    con = Refusing(_con())
    tally = columnar.build_keyword_daily(con, session, batch_size=50)
    assert _daily(con) == _reference_daily(session), "the rollup is whole, only less compact"
    assert tally["shard_checkpoints"] == 0 and tally["shard_checkpoint_failures"] == 3
    assert tally["shard_checkpoint_first_failure"] == {"shard": 0, "error_class": "RuntimeError"}
    assert "engine words" not in repr(tally)


def test_the_build_record_names_the_checkpoints(session, monkeypatch, tmp_path):  # noqa: F811
    """The rollup serve's last_build carries the count, the seconds and the failures (a failure is never only a log line)."""
    from contextlib import contextmanager

    import src.database.session as dbs
    from src.analytics import rollup_serve

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(dbs, "session_scope", fake_scope)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(columnar, "serve_canary", lambda con: {"query": "q", "outcome": "ok", "rows": 1, "resident_mib": 1.0,
                                                               "peak_mib": 1.0, "secs": 0.1})
    _seed(session, keywords=30, mentions_per=4)
    rollup_serve._STATE["last_build"] = None
    assert rollup_serve._build_inmemory_and_swap() is None
    lb = rollup_serve.status()["last_build"]
    assert lb["shard_checkpoints"] >= 1 and lb["shard_checkpoint_failures"] == 0
    assert lb["shard_checkpoint_first_failure"] is None and lb["shard_checkpoint_secs"] is not None


class InterruptException(Exception):  # noqa: N818 - the engine's own class name, which the build matches by name
    pass


def test_an_interrupt_at_a_shard_checkpoint_ends_the_build_instead_of_carrying_on(session, monkeypatch):  # noqa: F811
    """An interrupt is someone asking the statement to stop. At the aggregate and the bulk insert it already propagated
    (``_NEVER_RETRIED``); at the checkpoint it was counted as a checkpoint that "failed", the build carried on, and every remaining shard
    was aggregated after the stop was asked for."""
    _seed(session, keywords=61, mentions_per=7)
    _force_shards(monkeypatch, 4)

    class Interrupted(_Recorder):
        def execute(self, sql, *a, **k):
            if sql.strip().upper() == "CHECKPOINT" and self.order.count("checkpoint") == 1:
                self.order.append("interrupted")
                raise InterruptException("INTERRUPT Error")
            return super().execute(sql, *a, **k)

    con = Interrupted(_con())
    with pytest.raises(InterruptException):
        columnar.build_keyword_daily(con, session, batch_size=50)
    assert con.order == ["checkpoint", "aggregate", "interrupted"], "no shard was aggregated after the interrupt"


def test_an_interrupt_at_the_compacting_checkpoint_propagates_and_is_no_outcome():
    from tests.test_rollup_build_streaming import _CheckpointCon

    with pytest.raises(InterruptException):
        columnar.compact(_CheckpointCon(InterruptException("INTERRUPT Error")))


def test_a_checkpoint_that_fails_and_carries_on_is_logged_by_class_not_only_tallied(session, monkeypatch, caplog):  # noqa: F811
    """The tally names the first failure; the log names every one, so a run of them is visible in the error log the bundle keeps."""
    import logging

    _seed(session, keywords=40, mentions_per=5)
    _force_shards(monkeypatch, 2)

    class Refusing(_Recorder):
        def execute(self, sql, *a, **k):
            if sql.strip().upper() == "CHECKPOINT":
                raise RuntimeError("engine words")
            return super().execute(sql, *a, **k)

    with caplog.at_level(logging.WARNING, logger=columnar._LOG.name):
        columnar.build_keyword_daily(Refusing(_con()), session, batch_size=50)
    lines = [r.getMessage() for r in caplog.records if "serves uncompacted" in r.getMessage()]
    assert len(lines) == 2 and all("RuntimeError" in ln for ln in lines), lines
