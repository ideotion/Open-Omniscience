"""The rollup build never holds the corpus in memory, and a killed build is not restarted blindly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Diagnostics of 2026-10-06: on eight 4.81 GiB VMs the in-memory keyword rollup build was killed by
the kernel 12 times in 4.7 days, and the app started the same build again after every restart. Two
causes were read off the code and measured: the build loaded every ``Keyword`` as an ORM entity into
one list (about 2,000 bytes a keyword), and it staged mentions with ``executemany`` (1.1 thousand
rows/s, hours for a corpus of millions). These tests pin the replacement from every direction it can
go wrong:

  * the answer is UNCHANGED (the rollup equals an independent GROUP BY over the same rows, and the
    keyword projection equals what the ORM path produced, kind included);
  * nothing materialised is larger than one batch (the property that makes the memory flat);
  * the bulk path never loses a row (it falls back to ``executemany`` for a batch it cannot take);
  * a build the memory guard stops part-way swaps nothing in and leaves no marker behind;
  * a build that was KILLED (a marker written by another process) is declined until the machine has
    what the dead process held, and an upgrade's old kills (no marker) block nothing;
  * the offload rule: an encrypted corpus gets no temporary directory at all.
"""

from __future__ import annotations

import json
import os
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, rollup_marker, rollup_serve
from src.database.models import Base

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


# --------------------------------------------------------------------------- #
# a seeded corpus, written with raw SQL so thousands of rows stay cheap
# --------------------------------------------------------------------------- #

def _seed(session, *, keywords: int, mentions_per: int, undated_every: int = 0):
    """``keywords`` keywords (a third entities of three kinds, one without a mention) and
    ``mentions_per`` mentions each over a few days, a distinct article per mention."""
    conn = session.connection()
    kw_rows = []
    for i in range(1, keywords + 1):
        if i % 3 == 0:
            ent, et = 1, ("person", "place", None)[(i // 3) % 3]
        else:
            ent, et = 0, None
        kw_rows.append({
            "id": i, "term": f"Term ü'{i}\"", "normalized_term": f"term ü'{i}\"",
            "language": "en" if i % 5 else None, "is_entity": ent, "entity_type": et,
            "mention_count": 0 if i == keywords else mentions_per,
        })
    conn.execute(
        text(
            "INSERT INTO keywords (id, term, normalized_term, language, is_entity, entity_type, "
            "mention_count, frequency, is_ngram, ngram_size, relevance_score) "
            "VALUES (:id, :term, :normalized_term, :language, :is_entity, :entity_type, "
            ":mention_count, 0, 0, 1, 0.0)"
        ),
        kw_rows,
    )
    m_rows = []
    mid = 0
    for kid in range(1, keywords + 1):
        for _ in range(mentions_per):
            mid += 1
            undated = undated_every and mid % undated_every == 0
            m_rows.append({
                "id": mid, "kid": kid, "aid": mid, "cnt": 1 + (mid % 4),
                "day": None if undated else f"2026-03-{1 + (mid % 9):02d}",
                "ts": f"2026-03-10 00:00:{mid % 60:02d}.{mid:06d}",
            })
    conn.execute(
        text(
            "INSERT INTO keyword_mentions (id, keyword_id, article_id, count, observed_on, created_at) "
            "VALUES (:id, :kid, :aid, :cnt, :day, :ts)"
        ),
        m_rows,
    )
    session.commit()
    return keywords, mid


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        c.execute(text("PRAGMA foreign_keys=OFF"))
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _con():
    con = columnar.connect(passphrase=None)
    assert con is not None
    return con


def _reference_daily(session):
    rows = session.execute(text(
        "SELECT keyword_id, substr(observed_on, 1, 10) d, SUM(count), COUNT(DISTINCT article_id) "
        "FROM keyword_mentions WHERE observed_on IS NOT NULL GROUP BY keyword_id, d"
    )).fetchall()
    return sorted((int(r[0]), r[1], int(r[2]), int(r[3])) for r in rows)


def _reference_meta(session):
    """What the ORM path produced: one row per keyword with mentions, ``kind_of`` and all."""
    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    return sorted(
        (int(kw.id), kw.normalized_term, kw.term, kind_of(kw), bool(kw.is_entity), kw.entity_type, kw.language)
        for kw in session.query(Keyword).filter(Keyword.mention_count > 0)
    )


# --------------------------------------------------------------------------- #
# the answer is unchanged
# --------------------------------------------------------------------------- #

def test_the_streamed_build_equals_an_independent_group_by_and_the_orm_projection(session):
    _seed(session, keywords=61, mentions_per=7, undated_every=11)
    con = _con()
    tally = columnar.build_keyword_daily(con, session, batch_size=50)  # many batches in both streams
    got_daily = sorted(
        (int(k), str(d), int(m), int(a))
        for k, d, m, a in con.execute("SELECT keyword_id, day, mentions, articles_on_day FROM keyword_daily").fetchall()
    )
    assert got_daily == _reference_daily(session)
    got_meta = sorted(
        tuple(r) for r in con.execute(
            "SELECT keyword_id, normalized_term, term, kind, is_entity, entity_type, language FROM keyword_meta"
        ).fetchall()
    )
    assert got_meta == _reference_meta(session)
    assert tally["keyword_meta_rows"] == len(got_meta) == 60  # the keyword with no mention is not projected
    assert tally["last_mention_id"] == 61 * 7  # undated rows still advance the watermark


def test_kind_from_is_the_one_rule_kind_of_uses():
    from src.analytics.queries import kind_from, kind_of
    from src.database.models import Keyword

    for is_entity, et in ((False, None), (False, "person"), (True, None), (True, "place"), (None, None)):
        kw = Keyword(term="x", normalized_term="x", is_entity=is_entity, entity_type=et)
        assert kind_from(is_entity, et) == kind_of(kw)


# --------------------------------------------------------------------------- #
# nothing materialised is larger than one batch
# --------------------------------------------------------------------------- #

def test_no_batch_handed_to_duckdb_is_larger_than_the_batch_size(session, monkeypatch):
    _seed(session, keywords=120, mentions_per=10)
    seen: list[tuple[str, int]] = []
    real = columnar._bulk_insert

    def spy(con, table, types, rows):
        seen.append((table, len(rows)))
        return real(con, table, types, rows)

    monkeypatch.setattr(columnar, "_bulk_insert", spy)
    columnar.build_keyword_daily(_con(), session, batch_size=100)
    stage = [n for t, n in seen if t == "keyword_daily_stage"]
    meta = [n for t, n in seen if t == "keyword_meta"]
    assert sum(stage) == 120 * 10 and max(stage) <= 100 and len(stage) >= 12
    assert sum(meta) == 119 and max(meta) <= 100 and len(meta) >= 2


def test_the_build_no_longer_loads_keyword_entities(session, monkeypatch):
    """The regression the VMs paid for: ``session.query(Keyword)`` over the whole table."""
    _seed(session, keywords=10, mentions_per=2)
    real_query = session.query

    def guard(*entities, **kw):
        from src.database.models import Keyword

        assert Keyword not in entities, "the build loaded Keyword ORM entities again"
        return real_query(*entities, **kw)

    monkeypatch.setattr(session, "query", guard)
    columnar.build_keyword_daily(_con(), session)


# --------------------------------------------------------------------------- #
# the bulk path never loses a row
# --------------------------------------------------------------------------- #

def test_bulk_insert_matches_executemany_for_every_column_type():
    rows = [
        (1, "a", "Å ü ' \" \\ \n tab\t", "person", True, None, "en"),
        (2, "b", "日本語", "term", False, "place", None),
        (3, "c", "", "entity", None, "", ""),
    ]
    ddl = (
        "CREATE TABLE {} (keyword_id BIGINT, normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
        "is_entity BOOLEAN, entity_type VARCHAR, language VARCHAR)"
    )
    con = _con()
    con.execute(ddl.format("t_bulk"))
    con.execute(ddl.format("t_many"))
    assert columnar._bulk_insert(con, "t_bulk", columnar._META_TYPES, rows) == 3
    con.executemany("INSERT INTO t_many VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    assert con.execute("SELECT * FROM t_bulk ORDER BY 1").fetchall() == con.execute("SELECT * FROM t_many ORDER BY 1").fetchall()
    assert columnar._bulk_insert(con, "t_bulk", columnar._META_TYPES, []) == 0


def test_a_batch_the_json_path_refuses_is_inserted_by_executemany_not_dropped():
    class Proxy:
        def __init__(self, con):
            self._con = con
            self.json_tried = 0

        def execute(self, sql, params=None):
            if "from_json" in sql:
                self.json_tried += 1
                raise RuntimeError("the JSON path refuses this batch")
            return self._con.execute(sql, params) if params is not None else self._con.execute(sql)

        def executemany(self, sql, rows):
            return self._con.executemany(sql, rows)

    con = _con()
    con.execute("CREATE TABLE s (k BIGINT, d VARCHAR, c BIGINT, a BIGINT)")
    proxy = Proxy(con)
    rows = [(1, "2026-03-01", 2, 9), (2, "2026-03-02", 1, 8)]
    assert columnar._bulk_insert(proxy, "s", columnar._STAGE_TYPES, rows) == 2
    assert proxy.json_tried == 1
    assert con.execute("SELECT * FROM s ORDER BY k").fetchall() == [tuple(r) for r in rows]


# --------------------------------------------------------------------------- #
# the guard is read after every batch, and a stopped build swaps nothing in
# --------------------------------------------------------------------------- #

def test_on_batch_is_called_after_every_batch_of_both_streams_and_can_stop_the_build(session):
    _seed(session, keywords=40, mentions_per=5)
    calls: list[tuple[str, int]] = []

    def hook(stage, done):
        calls.append((stage, done))

    columnar.build_keyword_daily(_con(), session, batch_size=50, on_batch=hook)
    assert {s for s, _ in calls} == {"mentions", "aggregate", "keywords"}
    stages = [s for s, _ in calls]
    assert stages.count("aggregate") == 1, "the final GROUP BY is announced once, before it runs"
    assert stages.index("aggregate") > max(i for i, s in enumerate(stages) if s == "mentions")
    assert stages.index("aggregate") < min(i for i, s in enumerate(stages) if s == "keywords")
    assert [d for s, d in calls if s == "mentions"] == sorted(d for s, d in calls if s == "mentions")

    def stop(stage, done):
        if stage == "mentions" and done >= 100:
            raise columnar.BuildDeclined("mem-low", {"rows_done": done})

    with pytest.raises(columnar.BuildDeclined) as caught:
        columnar.build_keyword_daily(_con(), session, batch_size=50, on_batch=stop)
    assert caught.value.reason == "mem-low" and caught.value.detail["rows_done"] >= 100


class _Guard:
    """Engages on the Nth poll; mirrors the real object's shape (``poll``, ``state``, ``avail_floor_mb``)."""

    avail_floor_mb = 256.0

    def __init__(self, engage_on: int):
        self.n = 0
        self.engage_on = engage_on

    def poll(self):
        self.n += 1
        return self.n >= self.engage_on

    def state(self):
        return {"reason": "available 90 MB", "last_reading": {"mem_avail_mb": 90.0}, "readings_available": True}

    def reset(self, *, reason: str = "user action") -> None:
        self.n = 0


@pytest.fixture(autouse=True)
def _no_real_exit_hooks(monkeypatch):
    """A real ``begin`` registers an ``atexit`` hook: keep the pytest process free of them, and put the
    marker module's exit flag and the serve's spill bookkeeping back as found."""
    import types

    monkeypatch.setattr(rollup_marker, "atexit", types.SimpleNamespace(register=lambda *a, **k: None))
    monkeypatch.setattr(rollup_marker, "_closed", False)
    monkeypatch.setattr(rollup_marker, "_exit_hook_registered", False)
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    monkeypatch.setattr(rollup_serve, "_LAST_VERDICT_POLL", float("-inf"))
    monkeypatch.setitem(rollup_serve._STATE, "spill", None)


@pytest.fixture()
def serve_env(session, monkeypatch, tmp_path):
    """The in-memory build pointed at the seeded corpus, a temp data dir, a plaintext corpus."""
    from contextlib import contextmanager

    import src.database.session as dbs
    import src.scheduler.memguard as mg

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(dbs, "session_scope", fake_scope)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    monkeypatch.setattr("src.analytics.serve_gate.change_token", lambda s: ("t", 1))
    guard = _Guard(engage_on=10**9)
    monkeypatch.setattr(mg, "memory_guard", guard)
    monkeypatch.setattr(rollup_serve, "_GUARD_POLL_EVERY_S", 0.0)  # ask on every batch, so a few batches suffice
    fresh = {"con": None, "built_at": None, "rows": None, "pending": True, "last_skip": None, "stopped": None}
    rollup_serve._STATE.update(fresh)
    yield guard
    rollup_serve._STATE.update(fresh)


def test_a_guard_that_engages_mid_build_stops_it_swaps_nothing_and_leaves_no_marker(serve_env, session):
    _seed(session, keywords=60, mentions_per=10)
    serve_env.engage_on = 2  # the second ask: the seeded mentions fit one batch, so it is the aggregation's
    previous = object()
    rollup_serve._STATE["con"] = previous  # what is serving now
    stopped = rollup_serve._build_inmemory_and_swap()
    assert stopped is not None and stopped["reason"] == "mem-low"
    assert stopped["guard_reason"] == "available 90 MB" and stopped["stage"] == "aggregate"
    assert rollup_serve._STATE["con"] is previous, "a stopped build must not replace the serving rollup"
    assert rollup_marker.read() is None, "a build that ended by a path Python saw leaves no marker"


def test_a_build_with_a_quiet_guard_swaps_in_and_clears_its_marker(serve_env, session):
    _seed(session, keywords=30, mentions_per=4)
    assert rollup_serve._build_inmemory_and_swap() is None
    assert rollup_serve._STATE["con"] is not None and rollup_serve._STATE["rows"] > 0
    assert rollup_marker.read() is None


def test_duckdb_reaching_its_limit_with_no_offload_is_a_decline_not_a_crash(serve_env, monkeypatch):
    class OutOfMemoryException(Exception):  # the class name is what the dispatcher keys on
        pass

    def boom(con, s, **kw):
        raise OutOfMemoryException("could not allocate block (limit reached)")

    monkeypatch.setattr(columnar, "build_keyword_daily", boom)
    stopped = rollup_serve._build_inmemory_and_swap()
    assert stopped["reason"] == "duckdb-limit" and "duckdb_limit_mb" in stopped
    assert rollup_marker.read() is None


def test_any_other_error_still_propagates_and_still_clears_the_marker(serve_env, monkeypatch):
    def boom(con, s, **kw):
        raise ValueError("a real defect")

    monkeypatch.setattr(columnar, "build_keyword_daily", boom)
    with pytest.raises(ValueError):
        rollup_serve._build_inmemory_and_swap()
    assert rollup_marker.read() is None


def test_the_dispatcher_records_a_stopped_build_as_declined_with_its_readings(serve_env, session, monkeypatch):
    _seed(session, keywords=60, mentions_per=10)
    serve_env.engage_on = 2
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")  # restored after the test
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    skip = rollup_serve.status()["last_skip"]
    assert skip["reason"] == "mem-low" and skip["guard_reason"] == "available 90 MB"
    assert rollup_serve.status()["built"] is False


# --------------------------------------------------------------------------- #
# the start check, from measured memory
# --------------------------------------------------------------------------- #

def test_the_start_check_declines_a_build_whose_ceiling_is_more_than_is_available(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 740.0)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 3000.0, "avail_mb": 1300.0})
    verdict = rollup_serve._affordability_verdict()
    assert verdict["reason"] == "mem-short"
    # more than the limit and the floor alone: the process grows past DuckDB's limit (measured 1.45x)
    assert verdict["available_mb"] == 1300.0 and verdict["needs_available_mb"] > 740 + 256 + 100
    assert verdict["limit_overshoot"] == rollup_serve._LIMIT_OVERSHOOT
    assert verdict["duckdb_limit_mb"] == 740.0 and verdict["guard_floor_mb"] == 256.0
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 900.0, "avail_mb": 2500.0})
    assert rollup_serve._affordability_verdict() is None


def test_unreadable_memory_never_blocks_a_build(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": None, "avail_mb": None})
    assert rollup_serve._affordability_verdict() is None
    assert rollup_serve._last_build_verdict() is None


# --------------------------------------------------------------------------- #
# a killed build is not restarted identically
# --------------------------------------------------------------------------- #

@pytest.fixture()
def marker_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    yield tmp_path
    rollup_marker.clear()


def _foreign_marker(marker_dir, **over):
    rec = {
        "format": rollup_marker.FORMAT, "process": "a-process-that-is-gone", "started_at": time.time() - 900,
        "stage": "keywords", "rows_done": 1_234_567, "rss_mb": 3900.0, "rss_begin_mb": 500.0,
        "rss_peak_mb": 3900.0, "avail_mb": 300.0,
        "duckdb_limit_mb": 740.0, "written_at": time.time() - 60,
    }
    rec.update(over)
    (marker_dir / "rollup_build.json").write_text(json.dumps(rec), encoding="utf-8")


def test_a_marker_from_this_process_is_not_a_kill(marker_dir):
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    assert rollup_marker.read()["stage"] == "start"
    assert rollup_marker.killed_build() is None
    rollup_marker.clear()
    assert rollup_marker.read() is None


def test_a_marker_from_another_process_is_a_killed_build_and_this_process_cannot_clear_it(marker_dir):
    _foreign_marker(marker_dir)
    assert rollup_marker.killed_build()["rows_done"] == 1_234_567
    rollup_marker.clear()  # a record of another process's build is not ours to remove
    assert rollup_marker.read() is not None


def test_the_retry_waits_for_what_the_dead_build_grew_by_plus_the_guard_floor(marker_dir):
    _foreign_marker(marker_dir)
    verdict = rollup_marker.retry_verdict(avail_mb=2000.0, floor_mb=256.0)
    assert verdict["reason"] == "last_build_killed"
    # grew = peak - the size it began with: the app's own baseline is not counted a second time
    assert verdict["killed_rss_mb"] == 3900.0 and verdict["killed_grew_mb"] == 3400.0
    assert verdict["needs_available_mb"] == 3656.0
    assert verdict["available_mb"] == 2000.0 and verdict["killed_stage"] == "keywords"
    assert rollup_marker.retry_verdict(avail_mb=3700.0, floor_mb=256.0) is None  # the machine now has it


def test_the_peak_not_the_last_reading_is_what_the_retry_rule_uses(marker_dir):
    _foreign_marker(marker_dir, rss_mb=900.0, rss_peak_mb=2500.0, rss_begin_mb=500.0)
    verdict = rollup_marker.retry_verdict(avail_mb=1000.0, floor_mb=256.0)
    assert verdict["killed_grew_mb"] == 2000.0 and verdict["needs_available_mb"] == 2256.0


def test_a_record_without_the_new_fields_still_reads_by_its_last_rss(marker_dir):
    rec = {"format": rollup_marker.FORMAT, "process": "gone", "stage": "keywords", "rows_done": 1,
           "rss_mb": 3000.0, "avail_mb": 1.0}
    (marker_dir / "rollup_build.json").write_text(json.dumps(rec), encoding="utf-8")
    assert rollup_marker.retry_verdict(avail_mb=1000.0, floor_mb=256.0)["needs_available_mb"] == 3256.0


def test_no_marker_means_no_block_which_is_what_an_upgrade_from_the_old_build_sees(marker_dir):
    assert rollup_marker.retry_verdict(avail_mb=10.0, floor_mb=256.0) is None


def test_an_unreadable_or_foreign_format_marker_blocks_nothing(marker_dir):
    (marker_dir / "rollup_build.json").write_text("{not json", encoding="utf-8")
    assert rollup_marker.read() is None and rollup_marker.retry_verdict(10.0, 256.0) is None
    _foreign_marker(marker_dir, format=99)
    assert rollup_marker.read() is None and rollup_marker.retry_verdict(10.0, 256.0) is None


def test_an_unreadable_memory_reading_is_no_evidence_of_a_kill_either(marker_dir):
    _foreign_marker(marker_dir)
    assert rollup_marker.retry_verdict(avail_mb=None, floor_mb=256.0) is None


def test_progress_refreshes_the_readings_but_only_for_its_own_record_and_only_so_often(marker_dir, monkeypatch):
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    rollup_marker.progress("mentions", 5, rss_mb=1400.0, avail_mb=1500.0)  # a new stage: written at once
    assert rollup_marker.read()["rss_mb"] == 1400.0
    rollup_marker.progress("mentions", 6, rss_mb=2200.0, avail_mb=1500.0)  # same stage, inside the window
    assert rollup_marker.read()["rss_mb"] == 1400.0
    monkeypatch.setattr(rollup_marker, "_last_write", time.monotonic() - 60.0)
    rollup_marker.progress("mentions", 7, rss_mb=900.0, avail_mb=1500.0)
    rec = rollup_marker.read()
    assert rec["rss_mb"] == 900.0 and rec["rows_done"] == 7 and rec["stage"] == "mentions"
    assert rec["rss_peak_mb"] == 2200.0, "the peak seen between two writes is kept, not lost"
    rollup_marker.clear()
    _foreign_marker(marker_dir)
    monkeypatch.setattr(rollup_marker, "_last_write", time.monotonic() - 60.0)
    rollup_marker.progress("mentions", 9, rss_mb=1.0, avail_mb=1.0)
    assert rollup_marker.read()["rss_mb"] == 3900.0  # someone else's record is left alone


def test_the_dispatcher_declines_on_a_killed_build_until_memory_returns(marker_dir, monkeypatch):
    _foreign_marker(marker_dir)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 800.0, "avail_mb": 1500.0})
    verdict = rollup_serve._last_build_verdict()
    assert verdict["reason"] == "last_build_killed"
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 800.0, "avail_mb": 5000.0})
    assert rollup_serve._last_build_verdict() is None


# --------------------------------------------------------------------------- #
# the offload rule
# --------------------------------------------------------------------------- #

def test_an_encrypted_corpus_gets_no_temporary_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    assert rollup_serve._spill_setting() == ""
    assert not (tmp_path / "duckdb_tmp").exists(), "nothing may be created for an encrypted corpus"
    con = columnar.connect(passphrase=None, spill="")
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0] == ""


def test_a_plaintext_corpus_offloads_under_the_data_dir_and_the_next_build_sweeps_dead_processes(
    monkeypatch, tmp_path
):
    psutil = pytest.importorskip("psutil")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    root = tmp_path / "duckdb_tmp"
    dead = 4_000_000
    while psutil.pid_exists(dead):
        dead += 1
    (root / f"{dead}-ab12cd34").mkdir(parents=True)
    (root / f"{dead}-ab12cd34" / "duckdb_temp_storage-1.tmp").write_bytes(b"x")
    (root / str(dead)).mkdir()  # the older single-folder name is swept too
    (root / "not-a-pid").mkdir()
    chosen = rollup_serve._spill_setting()
    assert os.path.dirname(chosen) == str(root) and os.path.basename(chosen).startswith(f"{os.getpid()}-")
    assert not (root / f"{dead}-ab12cd34").exists(), "the folder of a process that is gone is swept"
    assert not (root / str(dead)).exists()
    assert (root / "not-a-pid").exists(), "only pid-named folders are ever touched"
    con = columnar.connect(passphrase=None, spill=chosen)
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0].rstrip("/\\") == chosen


def test_every_connection_gets_its_own_folder_and_a_live_one_is_never_emptied(monkeypatch, tmp_path):
    """D1: a rebuild stages while the previous rollup still serves. Sharing (or recreating) one folder broke
    the serving connection's queries (IOException) and, in testing, crashed the process."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    first = rollup_serve._spill_setting()
    (tmp_path / "duckdb_tmp" / os.path.basename(first) / "duckdb_temp_storage-1.tmp").write_bytes(b"a live spill")
    second = rollup_serve._spill_setting()
    third = rollup_serve._spill_setting()
    assert len({first, second, third}) == 3
    assert (tmp_path / "duckdb_tmp" / os.path.basename(first) / "duckdb_temp_storage-1.tmp").read_bytes() == b"a live spill"


def test_the_folder_of_a_first_ever_build_survives_the_second_builds_sweep(monkeypatch, tmp_path):
    """The once-only sweep of this pid's folders must be marked done even when there was nothing to sweep."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    first = rollup_serve._spill_setting()  # creates duckdb_tmp itself
    rollup_serve._spill_setting()
    assert os.path.isdir(first)


def test_a_declined_build_removes_its_folder_and_a_swap_removes_the_retired_ones(serve_env, session, tmp_path):
    _seed(session, keywords=40, mentions_per=5)
    root = tmp_path / "duckdb_tmp"
    serve_env.engage_on = 1
    assert rollup_serve._build_inmemory_and_swap()["reason"] == "mem-low"
    assert list(root.iterdir()) == [], "a declined build's folder is gone with its connection"
    serve_env.engage_on = 10**9
    serve_env.n = 0
    assert rollup_serve._build_inmemory_and_swap() is None
    first = rollup_serve._STATE["spill"]
    assert first and os.path.isdir(first), "the serving connection's folder stays while it serves"
    assert rollup_serve._build_inmemory_and_swap() is None
    assert rollup_serve._STATE["spill"] != first and os.path.isdir(rollup_serve._STATE["spill"])
    assert not os.path.exists(first), "the retired connection's folder goes after the swap"
    assert len(list(root.iterdir())) == 1


def test_a_connection_without_a_spill_choice_keeps_duckdbs_own_default():
    """Other callers of ``connect`` are unchanged by this work."""
    assert "temp_directory" not in columnar._offline_config()
    assert columnar._offline_config(spill="")["temp_directory"] == ""


# --------------------------------------------------------------------------- #
# the review's findings (Opus read of 669b3168)
# --------------------------------------------------------------------------- #

def test_the_engines_own_memory_limit_is_never_retried_row_by_row():
    """B1: with no offload allowed, DuckDB's limit is the DECLINE signal. The JSON path raising it must
    not fall back to ``executemany`` (1.1 thousand rows/s, with the build lock held)."""
    con = columnar.connect(passphrase=None, spill="")
    con.execute("SET memory_limit='1MB'")
    con.execute("CREATE TABLE s (k BIGINT, d VARCHAR, c BIGINT, a BIGINT)")
    rows = [(i, "2026-03-01", 1, i) for i in range(20_000)]
    with pytest.raises(Exception) as caught:
        columnar._bulk_insert(con, "s", columnar._STAGE_TYPES, rows)
    assert type(caught.value).__name__ == "OutOfMemoryException"
    assert con.execute("SELECT COUNT(*) FROM s").fetchone()[0] == 0, "nothing was half-inserted"


def test_the_fallback_is_never_taken_for_an_interrupt():
    class InterruptException(Exception):
        pass

    class Proxy:
        many = 0

        def execute(self, sql, params=None):
            raise InterruptException("INTERRUPT Error")

        def executemany(self, sql, rows):
            Proxy.many += 1

    with pytest.raises(InterruptException):
        columnar._bulk_insert(Proxy(), "s", columnar._STAGE_TYPES, [(1, "2026-03-01", 1, 1)])
    assert Proxy.many == 0


def test_a_build_the_limit_stopped_is_not_started_again_until_the_limit_grows(serve_env, monkeypatch):
    """S1: a part-way stop is held by a measured condition, not retried by the next serve request."""
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 740.0)
    runs = []

    def stopped_build():
        runs.append(1)
        return {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 740.0}

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", stopped_build)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined" and len(runs) == 1
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined" and len(runs) == 1, "the corpus was not rescanned"
    held = rollup_serve.status()["last_skip"]
    assert held["reason"] == "duckdb-limit" and held["duckdb_limit_mb"] == 740.0
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1480.0)  # the budget grew
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: runs.append(1) or None)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "built" and len(runs) == 2
    assert rollup_serve._STATE["stopped"] is None, "a finished build clears the hold"


def test_a_build_the_guard_stopped_waits_for_what_it_had_grown_by_plus_the_floor(serve_env, monkeypatch):
    rollup_serve._STATE["stopped"] = {"reason": "mem-low", "at": time.time(), "grew_mb": 1200.0, "stage": "keywords"}
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 800.0, "avail_mb": 1000.0})
    verdict = rollup_serve._stopped_build_verdict()
    assert verdict["reason"] == "mem-low" and verdict["needs_available_mb"] == 1456.0
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 800.0, "avail_mb": 1500.0})
    assert rollup_serve._stopped_build_verdict() is None
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": None, "avail_mb": None})
    assert rollup_serve._stopped_build_verdict() is None, "no reading is no evidence"


def test_the_start_and_kill_checks_do_not_block_the_persisted_refresh(monkeypatch, marker_dir):
    _foreign_marker(marker_dir)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 1.0, "avail_mb": 1.0})
    assert rollup_serve._affordability_verdict() is None
    assert rollup_serve._last_build_verdict() is None


def test_a_declined_or_failed_build_closes_the_connection_it_opened(serve_env, session, monkeypatch):
    _seed(session, keywords=20, mentions_per=3)
    opened = []
    real_connect = columnar.connect

    def spy(*a, **kw):
        con = real_connect(*a, **kw)
        opened.append(con)
        return con

    monkeypatch.setattr(columnar, "connect", spy)
    serve_env.engage_on = 1
    assert rollup_serve._build_inmemory_and_swap()["reason"] == "mem-low"

    def boom(con, s, **kw):
        raise ValueError("a real defect")

    monkeypatch.setattr(columnar, "build_keyword_daily", boom)
    with pytest.raises(ValueError):
        rollup_serve._build_inmemory_and_swap()
    assert len(opened) == 2
    import duckdb

    for con in opened:
        with pytest.raises(duckdb.Error):
            con.execute("SELECT 1")  # closed


def test_the_guard_is_asked_at_most_once_per_interval_not_once_per_batch(serve_env, session, monkeypatch):
    _seed(session, keywords=60, mentions_per=10)
    monkeypatch.setattr(rollup_serve, "_GUARD_POLL_EVERY_S", 3600.0)
    serve_env.engage_on = 2
    assert rollup_serve._build_inmemory_and_swap() is None, "one ask is the first; the rest are skipped"
    assert serve_env.n == 1


def test_a_normal_quit_during_a_build_clears_the_marker_through_atexit(marker_dir, monkeypatch):
    import types

    registered = []
    monkeypatch.setattr(rollup_marker, "atexit", types.SimpleNamespace(register=lambda fn, *a, **k: registered.append(fn)))
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    assert registered == [rollup_marker._exit_clear], "the hook is the marker's own exit clear"
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    assert len(registered) == 1, "registered once"
    registered[0]()
    assert rollup_marker.read() is None


def test_a_build_thread_cannot_put_the_marker_back_after_the_exit_clear(marker_dir):
    """CPython runs atexit hooks before it stops daemon threads: a write that arrives after the clear (a
    progress refresh, or a build that begins during shutdown) must be dropped, not leave a false 'kill'."""
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    rollup_marker._exit_clear()
    assert rollup_marker.read() is None
    rollup_marker.progress("keywords", 9, rss_mb=900.0, avail_mb=1000.0)  # a stage change: would write
    rollup_marker.begin(rss_mb=500.0, avail_mb=2000.0, limit_mb=740.0)
    assert rollup_marker.read() is None, "nothing may write the marker once the process is exiting"


def test_the_sweep_runs_for_an_encrypted_corpus_too_and_a_reused_pids_leftovers_go_once(monkeypatch, tmp_path):
    psutil = pytest.importorskip("psutil")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    root = tmp_path / "duckdb_tmp"
    dead = 4_000_000
    while psutil.pid_exists(dead):
        dead += 1
    (root / f"{dead}-ab12cd34").mkdir(parents=True)
    (root / f"{dead}-ab12cd34" / "duckdb_temp_storage-1.tmp").write_bytes(b"left by a plaintext-era build")
    stale_same_pid = root / f"{os.getpid()}-00000000"  # an earlier process that had this very pid (a container)
    stale_same_pid.mkdir()
    (stale_same_pid / "stale.tmp").write_bytes(b"from an earlier process with this pid")
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    assert rollup_serve._spill_setting() == ""
    assert not (root / f"{dead}-ab12cd34").exists(), "what a plaintext build left must not outlive the encryption"
    assert not stale_same_pid.exists(), "before this process has made a folder, its pid's folders are a dead process's"
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    mine = rollup_serve._spill_setting()
    assert os.path.isdir(mine) and list(os.scandir(mine)) == []
    assert os.path.isdir(rollup_serve._spill_setting()) and os.path.isdir(mine), "once made, this pid's are live"


def test_a_limit_hold_is_released_when_the_corpus_epoch_changes_but_not_inside_the_rebuild_ttl(serve_env, monkeypatch):
    """D2: the limit never grows inside a process, so without this a corpus that shrank (a prune, a
    restore of a smaller backup, a re-index) would keep the rollup off until the next restart. Not before the
    TTL: ``/api/insights/reindex-all`` bumps the epoch on every 300-article call."""
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 740.0)
    ttl = rollup_serve.rollup_serve_ttl_s()
    old = time.time() - ttl - 60.0
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": old, "duckdb_limit_mb": 740.0, "epoch": 4}
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 4)
    assert rollup_serve._stopped_build_verdict()["reason"] == "duckdb-limit"
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 5)
    assert rollup_serve._stopped_build_verdict() is None
    assert rollup_serve._STATE["stopped"] is None, "released for good, not just for this check"
    # a stop younger than the TTL stays held through an epoch bump (a reindex-all drain bumps one per call)
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 740.0, "epoch": 4}
    assert rollup_serve._stopped_build_verdict() is not None
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: None)  # unreadable: no release
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": old, "duckdb_limit_mb": 740.0, "epoch": 4}
    assert rollup_serve._stopped_build_verdict() is not None


def test_a_guard_the_builds_own_poll_engaged_is_sampled_again_by_the_start_check(monkeypatch):
    """S10: only collection passes release the guard; with collection paused it stayed engaged and kept the
    rollup off for good. The verdict takes its own reading, at most once per interval."""
    class Latched:
        def __init__(self):
            self.engaged = True
            self.polls = 0

        def poll(self):
            self.polls += 1
            self.engaged = False  # memory is healthy again: the sample releases it
            return self.engaged

        def state(self):
            return {"reason": "available 90 MB", "last_reading": {}, "readings_available": True}

        def reset(self, *, reason: str = "") -> None:  # the suite's isolation fixture calls it
            self.engaged = False

    import src.scheduler.memguard as mg

    guard = Latched()
    monkeypatch.setattr(mg, "memory_guard", guard)
    monkeypatch.setattr(rollup_serve, "_GUARD_POLL_EVERY_S", 0.0)
    assert rollup_serve._memory_verdict() is None and guard.polls == 1
    # throttled: inside the interval a still-engaged guard is reported, not re-sampled
    guard.engaged = True
    monkeypatch.setattr(rollup_serve, "_GUARD_POLL_EVERY_S", 3600.0)
    assert rollup_serve._memory_verdict()["reason"] == "mem-low" and guard.polls == 1


def test_a_guard_stop_in_the_mentions_stage_is_held_on_the_projected_total(serve_env, session, monkeypatch):
    """D3: a build the guard stops when memory is already gone has only shown the LOWER bound of what it needs."""
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 4096.0)  # a ceiling above the projection
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap",
        lambda: {"reason": "mem-low", "at": time.time(), "stage": "mentions", "rows_done": 1_000_000,
                 "mentions_total": 4_000_000, "rss_mb": 1500.0, "begin_rss_mb": 500.0, "epoch": 3},
    )
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    held = rollup_serve._STATE["stopped"]
    assert held["observed_grew_mb"] == 1000.0 and held["grew_mb"] == 4000.0 and held["epoch"] == 3
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 3)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 500.0, "avail_mb": 2000.0})
    assert rollup_serve._stopped_build_verdict()["needs_available_mb"] == 4256.0, "2,000 MB is what it failed with"


def test_the_projection_never_asks_for_more_than_the_start_check_does(serve_env, monkeypatch):
    """E1: a stop at 2M of 40M mentions with 400 MB observed would project 8,000 MB on a machine with 4.8 GB in
    total, whose start check needs about 1.4 GB: the hold would keep the rollup off until a restart."""
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 740.0)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap",
        lambda: {"reason": "mem-low", "at": time.time(), "stage": "mentions", "rows_done": 2_000_000,
                 "mentions_total": 40_000_000, "rss_mb": 900.0, "begin_rss_mb": 500.0, "epoch": 3},
    )
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    held = rollup_serve._STATE["stopped"]
    ceiling = 740.0 * rollup_serve._LIMIT_OVERSHOOT + rollup_serve.columnar_batch_mb()
    assert held["observed_grew_mb"] == 400.0 and held["grew_mb"] == round(ceiling, 1) < 8000.0


def test_a_connect_that_raises_still_removes_the_folder_it_made(serve_env, monkeypatch, tmp_path):
    def boom(*a, **kw):
        raise RuntimeError("duckdb cannot start")

    monkeypatch.setattr(columnar, "connect", boom)
    with pytest.raises(RuntimeError):
        rollup_serve._build_inmemory_and_swap()
    assert list((tmp_path / "duckdb_tmp").iterdir()) == []


def test_the_stop_hold_does_not_gate_the_persisted_refresh(serve_env, monkeypatch):
    rollup_serve._STATE["stopped"] = {"reason": "mem-low", "at": 1.0, "grew_mb": 9999.0}
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    assert rollup_serve._stopped_build_verdict() is None


# --------------------------------------------------------------------------- #
# the second pass: every remaining row-by-row staging site goes through the bulk path
# --------------------------------------------------------------------------- #

def test_the_read_model_streams_by_keyset_and_equals_the_counters_at_any_batch_size(session, monkeypatch):
    _seed(session, keywords=47, mentions_per=3)
    sizes: list[int] = []
    real = columnar._bulk_insert

    def spy(con, table, types, rows):
        sizes.append(len(rows))
        return real(con, table, types, rows)

    monkeypatch.setattr(columnar, "_bulk_insert", spy)
    con = _con()
    n = columnar.build_keyword_read_model(con, session, batch_size=10)
    assert n == 46 and sizes == [10, 10, 10, 10, 6], "no batch handed to DuckDB is larger than the batch size"
    raw = {r["normalized"]: (r["mentions"], r["articles"], r["kind"]) for r in columnar.top_terms_raw(con, limit=1000)}
    con2 = _con()
    columnar.build_keyword_read_model(con2, session)  # one batch
    one = {r["normalized"]: (r["mentions"], r["articles"], r["kind"]) for r in columnar.top_terms_raw(con2, limit=1000)}
    assert raw == one and len(raw) == 46


def test_the_read_model_never_loads_the_keywords_as_orm_entities(session, monkeypatch):
    """The shape that held 7.5 to 8.8 GB in the rollup build: a query over the ORM class, listed."""
    import src.database.models as models

    _seed(session, keywords=20, mentions_per=2)

    def forbidden(*a, **kw):
        raise AssertionError("the read model queried the ORM Keyword class")

    monkeypatch.setattr(session, "query", forbidden)
    assert columnar.build_keyword_read_model(_con(), session, batch_size=7) == 19
    assert models.Keyword is not None


def _add_corpus_tail(session, *, first_keyword: int, keywords: int, first_mention: int):
    """New keywords and mentions AFTER what a first build saw (ids above its watermark)."""
    conn = session.connection()
    conn.execute(
        text(
            "INSERT INTO keywords (id, term, normalized_term, language, is_entity, entity_type, "
            "mention_count, frequency, is_ngram, ngram_size, relevance_score) "
            "VALUES (:id, :t, :n, 'en', 0, NULL, 2, 0, 0, 1, 0.0)"
        ),
        [{"id": first_keyword + i, "t": f"New {i}", "n": f"new {i}"} for i in range(keywords)],
    )
    rows, mid = [], first_mention
    for i in range(keywords):
        for _ in range(2):
            mid += 1
            rows.append({"id": mid, "kid": first_keyword + i, "aid": 10_000 + mid, "cnt": 1,
                         "day": f"2026-04-{1 + (mid % 5):02d}", "ts": f"2026-04-01 00:00:{mid % 60:02d}.{mid:06d}"})
    conn.execute(
        text(
            "INSERT INTO keyword_mentions (id, keyword_id, article_id, count, observed_on, created_at) "
            "VALUES (:id, :kid, :aid, :cnt, :day, :ts)"
        ),
        rows,
    )
    session.commit()


def test_the_incremental_refresh_stages_in_bulk_and_equals_a_full_build(session, monkeypatch):
    _seed(session, keywords=30, mentions_per=4)
    con = _con()
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1, batch_size=50)["mode"] == "full"
    _add_corpus_tail(session, first_keyword=100, keywords=6, first_mention=30 * 4)
    tables: list[tuple[str, int]] = []
    real = columnar._bulk_insert
    monkeypatch.setattr(
        columnar, "_bulk_insert", lambda c, table, types, rows: (tables.append((table, len(rows))), real(c, table, types, rows))[1]
    )
    out = columnar.refresh_keyword_daily(con, session, corpus_epoch=1, batch_size=5)
    assert out["mode"] == "incremental" and out["new_keywords"] == 6
    staged = [(t, n) for t, n in tables if t == "keyword_daily_stage"]
    assert staged and sum(n for _, n in staged) == 12 and max(n for _, n in staged) <= 5
    assert ("_new_meta", 6) in tables, "the new keywords' metadata goes in through the bulk path too"
    fresh = _con()
    columnar.build_keyword_daily(fresh, session)
    q = "SELECT keyword_id, day, mentions, articles_on_day FROM keyword_daily ORDER BY 1, 2"
    assert con.execute(q).fetchall() == fresh.execute(q).fetchall()
    qm = "SELECT keyword_id, normalized_term, term, kind, is_entity, entity_type, language FROM keyword_meta ORDER BY 1"
    assert con.execute(qm).fetchall() == fresh.execute(qm).fetchall()


# --------------------------------------------------------------------------- #
# the build's progress, as the boot sequence and the diagnostics show it
# --------------------------------------------------------------------------- #

def test_build_progress_is_absent_when_no_build_runs_and_counts_only_when_one_does(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_PROGRESS", None)
    assert rollup_serve.build_progress() is None
    now = [100.0]
    monkeypatch.setattr(rollup_serve.time, "time", lambda: now[0])
    rollup_serve._progress_begin()
    first = rollup_serve.build_progress()
    assert first["stage"] == "start" and first["rows_done"] == 0 and "rows_per_s" not in first
    rollup_serve._progress_note("mentions", 1_000)  # no time has passed: no rate, never 0
    now[0] = 102.0
    p = rollup_serve.build_progress()
    assert p["rows_done"] == 1_000 and "rows_per_s" not in p and p["idle_s"] == 2.0
    now[0] = 104.0
    rollup_serve._progress_note("mentions", 5_000)
    now[0] = 105.0
    assert rollup_serve.build_progress()["rows_per_s"] == 1250, "5,000 rows over the 4 s the stage has run"
    rollup_serve._progress_end()
    assert rollup_serve.build_progress() is None


def test_a_real_build_reports_progress_and_clears_it(serve_env, session, monkeypatch):
    _seed(session, keywords=40, mentions_per=5)
    seen: list[dict] = []
    real = rollup_serve._progress_note

    def spy(stage, rows):
        real(stage, rows)
        seen.append(rollup_serve.build_progress())

    monkeypatch.setattr(rollup_serve, "_progress_note", spy)
    assert rollup_serve._build_inmemory_and_swap() is None
    assert {p["stage"] for p in seen} == {"mentions", "aggregate", "keywords"}
    assert rollup_serve.build_progress() is None, "nothing is reported once the build has ended"
    assert rollup_serve.status()["build_progress"] is None


def test_the_boot_snapshot_shows_the_running_rollup_steps_progress(monkeypatch):
    from src.api import boot_sequence as bs

    bs._reset()
    with bs._LOCK:
        bs._STEPS["rollup"].update(state="running", started_at=time.time() - 5)
        bs._SEQUENCE["started_at"] = time.time() - 9
    monkeypatch.setattr(rollup_serve, "build_progress", lambda: {"stage": "mentions", "rows_done": 12, "idle_s": 1.0, "running_s": 4.0})
    rows = {r["step"]: r for r in bs.snapshot()["steps"]}
    assert rows["rollup"]["progress"]["rows_done"] == 12 and "progress" not in rows["warm-cache"]
    monkeypatch.setattr(rollup_serve, "build_progress", lambda: None)
    assert "progress" not in {r["step"]: r for r in bs.snapshot()["steps"]}["rollup"]
    bs._reset()


def test_the_slow_step_watch_warns_once_then_only_when_progress_has_stopped(monkeypatch, caplog):
    import logging
    import threading

    from src.api import boot_sequence as bs

    monkeypatch.setattr(bs, "SLOW_STEP_S", 0.05)
    state = {"idle": 0.0}
    monkeypatch.setattr(
        rollup_serve, "build_progress",
        lambda: {"stage": "keywords", "rows_done": 7_000, "rows_per_s": 500, "idle_s": state["idle"], "running_s": 9.0},
    )
    with caplog.at_level(logging.WARNING, logger=bs._LOG.name):
        watch = bs._SlowWatch("rollup", "the re-index")
        watch.start()
        threading.Event().wait(0.4)  # several intervals; the build keeps moving (idle_s stays 0)
        moving = [r.getMessage() for r in caplog.records]
        state["idle"] = 999.0  # ... and now it has not moved for longer than the limit
        threading.Event().wait(0.3)
        watch.cancel()
    assert len(moving) == 1 and "still running" in moving[0] and "7,000 rows at 500 rows/s" in moving[0]
    stuck = [r.getMessage() for r in caplog.records if "no progress" in r.getMessage()]
    assert stuck and "999 s" in stuck[0] and "the re-index waiting behind it" in stuck[0]
    after = len(caplog.records)
    threading.Event().wait(0.3)
    assert len(caplog.records) == after, "a cancelled watch is silent"


def test_a_stop_with_no_total_is_held_on_what_was_observed(serve_env, monkeypatch):
    """N14: without a total (no change token) there is nothing to project over: the hold is the observed growth."""
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 4096.0)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap",
        lambda: {"reason": "mem-low", "at": time.time(), "stage": "mentions", "rows_done": 1_000_000,
                 "mentions_total": None, "rss_mb": 1500.0, "begin_rss_mb": 500.0, "epoch": None},
    )
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    held = rollup_serve._STATE["stopped"]
    assert held["observed_grew_mb"] == 1000.0 and held["grew_mb"] == 1000.0
