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
    assert {s for s, _ in calls} == {"mentions", "keywords"}
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
    rollup_serve._STATE.update({"con": None, "built_at": None, "rows": None, "pending": True, "last_skip": None})
    yield guard
    rollup_serve._STATE.update({"con": None, "built_at": None, "rows": None, "pending": True, "last_skip": None})


def test_a_guard_that_engages_mid_build_stops_it_swaps_nothing_and_leaves_no_marker(serve_env, session):
    _seed(session, keywords=60, mentions_per=10)
    serve_env.engage_on = 2  # the second batch (the first of the keyword stream)
    previous = object()
    rollup_serve._STATE["con"] = previous  # what is serving now
    stopped = rollup_serve._build_inmemory_and_swap()
    assert stopped is not None and stopped["reason"] == "mem-low"
    assert stopped["guard_reason"] == "available 90 MB" and stopped["stage"] in ("mentions", "keywords")
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
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 3000.0, "avail_mb": 900.0})
    verdict = rollup_serve._affordability_verdict()
    assert verdict["reason"] == "mem-short"
    assert verdict["available_mb"] == 900.0 and verdict["needs_available_mb"] > 740 + 256
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
        "stage": "keywords", "rows_done": 1_234_567, "rss_mb": 3900.0, "avail_mb": 300.0,
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


def test_the_retry_waits_for_what_the_dead_process_held_plus_the_guard_floor(marker_dir):
    _foreign_marker(marker_dir, rss_mb=3900.0)
    verdict = rollup_marker.retry_verdict(avail_mb=2000.0, floor_mb=256.0)
    assert verdict["reason"] == "last_build_killed"
    assert verdict["killed_rss_mb"] == 3900.0 and verdict["needs_available_mb"] == 4156.0
    assert verdict["available_mb"] == 2000.0 and verdict["killed_stage"] == "keywords"
    assert rollup_marker.retry_verdict(avail_mb=4200.0, floor_mb=256.0) is None  # the machine now has it


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
    rollup_marker.progress("mentions", 5, rss_mb=900.0, avail_mb=1500.0)  # inside the throttle window
    assert rollup_marker.read()["rss_mb"] == 500.0
    monkeypatch.setattr(rollup_marker, "_last_write", time.monotonic() - 60.0)
    rollup_marker.progress("mentions", 5, rss_mb=900.0, avail_mb=1500.0)
    rec = rollup_marker.read()
    assert rec["rss_mb"] == 900.0 and rec["rows_done"] == 5 and rec["stage"] == "mentions"
    rollup_marker.clear()
    _foreign_marker(marker_dir)
    monkeypatch.setattr(rollup_marker, "_last_write", time.monotonic() - 60.0)
    rollup_marker.progress("mentions", 9, rss_mb=1.0, avail_mb=1.0)
    assert rollup_marker.read()["rss_mb"] == 3900.0  # someone else's record is left alone


def test_the_dispatcher_declines_on_a_killed_build_until_memory_returns(marker_dir, monkeypatch):
    _foreign_marker(marker_dir, rss_mb=3900.0)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
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


def test_a_plaintext_corpus_offloads_under_the_data_dir_and_the_next_start_sweeps_dead_processes(
    monkeypatch, tmp_path
):
    psutil = pytest.importorskip("psutil")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    root = tmp_path / "duckdb_tmp"
    dead = 4_000_000
    while psutil.pid_exists(dead):
        dead += 1
    (root / str(dead)).mkdir(parents=True)
    (root / str(dead) / "duckdb_temp_storage-1.tmp").write_bytes(b"x")
    (root / "not-a-pid").mkdir()
    chosen = rollup_serve._spill_setting()
    assert chosen == str(root / str(os.getpid()))
    assert not (root / str(dead)).exists(), "the folder of a process that is gone is swept"
    assert (root / "not-a-pid").exists(), "only pid-named folders are ever touched"
    con = columnar.connect(passphrase=None, spill=chosen)
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0].rstrip("/\\") == chosen


def test_a_connection_without_a_spill_choice_keeps_duckdbs_own_default():
    """Other callers of ``connect`` are unchanged by this work."""
    assert "temp_directory" not in columnar._offline_config()
    assert columnar._offline_config(spill="")["temp_directory"] == ""
