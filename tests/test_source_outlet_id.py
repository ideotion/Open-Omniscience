"""R177: ``sources.outlet_id`` is the outlet as an integer, kept right by three triggers; none of it may touch a verdict.

The invariant every test below reduces to: a source's ``outlet_id`` is the id of an EXISTING row that shares its domain
(the lowest such id). A text outlet key cost a hash per scanned mention; this integer replaces it, so it must never be
wrong, including while the collector writes, after the J1 table rebuild drops the triggers, and after the oldest feed
of a domain is deleted (the rowid-reuse hazard).
"""

from __future__ import annotations

import random
import sqlite3
import threading

import pytest
from sqlalchemy import create_engine, event

from src.database.models import SOURCE_OUTLET_ID_TRIGGERS, Base
from src.database.source_identity import (
    ensure_source_composite_key,
    ensure_source_outlet_id,
    install_source_outlet_id,
)
from tests.test_source_composite_key import _legacy_engine, _seed


def _engine(tmp_path, name="o.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}", future=True, connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi, _rec):
        dbapi.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _insert(conn, domain, feed="", name=None):
    conn.exec_driver_sql(
        "INSERT INTO sources (name, domain, rss_url, feed_key, status) VALUES (?,?,?,?, 'unqualified')",
        (name or domain, domain, None, feed),
    )


def _wrong(conn):
    """Rows whose outlet_id is not the lowest id of their domain (what the invariant forbids)."""
    return conn.exec_driver_sql(
        "SELECT s.id, s.domain, s.outlet_id FROM sources s"
        " WHERE s.outlet_id IS NOT (SELECT MIN(x.id) FROM sources x WHERE x.domain = s.domain)"
    ).fetchall()


def _triggers(conn):
    return {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='sources'")}


def test_create_all_installs_the_three_triggers_and_the_column(tmp_path):
    engine = _engine(tmp_path)
    with engine.connect() as conn:
        assert _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)
        assert "outlet_id" in {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(sources)")}


def test_insert_sets_the_lowest_id_of_the_domain(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        _insert(conn, "a.com", "f:a.com/1")
        _insert(conn, "a.com", "f:a.com/2")
        _insert(conn, "b.com")
        rows = {r[0]: r[1] for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources")}
    assert rows == {1: 1, 2: 1, 3: 3}


def test_a_domain_edit_moves_the_row_and_repairs_both_domains(tmp_path):
    """R167: an operator edit of a domain flows into outlet_id and nothing else changes."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "3"), ("b.com", "4")]:
            _insert(conn, dom, feed)
        before = conn.exec_driver_sql("SELECT id, name, domain, feed_key, status, qualified_at FROM sources ORDER BY id").fetchall()
        conn.exec_driver_sql("UPDATE sources SET domain='b.com' WHERE id=1")  # a.com's oldest feed leaves
        assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources ORDER BY id")] == [(1, 1), (2, 2), (3, 1), (4, 1)]
        assert not _wrong(conn)
        after = conn.exec_driver_sql("SELECT id, name, domain, feed_key, status, qualified_at FROM sources ORDER BY id").fetchall()
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(changed) == 1 and changed[0][0][2] == "a.com" and changed[0][1][2] == "b.com"  # only the edited domain moved


def test_deleting_the_oldest_feed_promotes_the_next_and_a_reused_rowid_stays_correct(tmp_path):
    """The rowid-reuse hazard: delete the oldest feed of a domain, then insert; ids are reused only at the table's top."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for feed in "123":
            _insert(conn, "a.com", feed)
        _insert(conn, "z.com")  # id 4, the table's top
        conn.exec_driver_sql("DELETE FROM sources WHERE id=1")
        assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources WHERE domain='a.com' ORDER BY id")] == [(2, 2), (3, 2)]
        conn.exec_driver_sql("DELETE FROM sources WHERE id=4")  # the top row: its rowid is handed out again
        _insert(conn, "a.com", "4")
        _insert(conn, "y.com")
        assert not _wrong(conn)
        ids = [r[0] for r in conn.exec_driver_sql("SELECT id FROM sources ORDER BY id")]
        assert ids == [2, 3, 4, 5]  # 4 was reused, by a sibling this time
        assert {r[0]: r[1] for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources")} == {2: 2, 3: 2, 4: 2, 5: 5}


def test_random_writes_never_leave_a_wrong_outlet(tmp_path):
    engine = _engine(tmp_path)
    rng = random.Random(177)
    domains = [f"d{i}.com" for i in range(6)]
    with engine.begin() as conn:
        for step in range(400):
            op = rng.choice(["ins", "ins", "ins", "del", "edit"])
            ids = [r[0] for r in conn.exec_driver_sql("SELECT id FROM sources")]
            if op == "ins" or not ids:
                _insert(conn, rng.choice(domains), f"f{step}")
            elif op == "del":
                conn.exec_driver_sql("DELETE FROM sources WHERE id=?", (rng.choice(ids),))
            else:
                conn.exec_driver_sql("UPDATE sources SET domain=? WHERE id=?", (rng.choice(domains), rng.choice(ids)))
            assert not _wrong(conn), (step, op)


def test_the_boot_step_adds_the_column_heals_stale_rows_and_is_idempotent(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "")]:
            _insert(conn, dom, feed)
        conn.exec_driver_sql("DROP TRIGGER trg_sources_outlet_id_ai")
        conn.exec_driver_sql("UPDATE sources SET outlet_id = NULL WHERE id=2")  # a row the triggers never saw
        conn.exec_driver_sql("UPDATE sources SET outlet_id = 3 WHERE id=1")  # and a wrong one
    result = ensure_source_outlet_id(engine)
    assert result == {"added": False, "triggers": 1, "healed": 2}
    with engine.connect() as conn:
        assert not _wrong(conn) and _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)
    assert ensure_source_outlet_id(engine) == {"added": False, "triggers": 0, "healed": 0}


def test_a_refusal_part_way_leaves_no_triggers_and_no_half_state(tmp_path, monkeypatch):
    """The three triggers and the heal are one transaction (the independent read's F1). A third trigger that is refused used to
    leave two of them standing with no heal: a store whose non-NULL values nothing corrects, which ``outlets_unhealed`` (it
    looks for NULL rows) cannot see. All or none: none leaves every row NULL, which the gates read exactly."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "")]:
            _insert(conn, dom, feed)
        for name in SOURCE_OUTLET_ID_TRIGGERS:
            conn.exec_driver_sql(f"DROP TRIGGER {name}")
        conn.exec_driver_sql("UPDATE sources SET outlet_id = NULL")
    names = list(SOURCE_OUTLET_ID_TRIGGERS)
    broken = {**SOURCE_OUTLET_ID_TRIGGERS, names[-1]: "CREATE TRIGGER this is not sql"}
    monkeypatch.setattr("src.database.source_identity.SOURCE_OUTLET_ID_TRIGGERS", broken)
    result = ensure_source_outlet_id(engine)
    assert result["state"] == "refused"
    with engine.connect() as conn:
        assert not _triggers(conn), "two triggers stood with no heal"
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE outlet_id IS NOT NULL").scalar_one() == 0
    monkeypatch.undo()
    assert ensure_source_outlet_id(engine) == {"added": False, "triggers": 3, "healed": 3}  # the next boot completes it
    with engine.connect() as conn:
        assert not _wrong(conn)


def test_a_store_that_never_had_the_column_gets_it_and_a_correct_value_for_every_row(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, domain TEXT NOT NULL)")
    raw.executemany("INSERT INTO sources (id, name, domain) VALUES (?,?,?)", [(1, "a", "a.com"), (2, "b", "a.com"), (3, "c", "c.com")])
    raw.commit()
    raw.close()
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        assert ensure_source_outlet_id(engine) == {"added": True, "triggers": 3, "healed": 3}
        with engine.connect() as conn:
            assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources ORDER BY id")] == [(1, 1), (2, 1), (3, 3)]
    finally:
        engine.dispose()


def test_no_sources_table_is_a_named_non_event(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}", future=True)
    try:
        with engine.connect() as conn:
            assert install_source_outlet_id(conn) == {"state": "absent"}
    finally:
        engine.dispose()


def test_the_j1_table_rebuild_keeps_the_triggers_and_the_values(tmp_path):
    """The rebuild DROPs the table, which drops its triggers; it replays what it found, and the boot step finds nothing to add."""
    engine = _legacy_engine(tmp_path)
    _seed(engine)
    with engine.begin() as conn:
        install_source_outlet_id(conn)
        assert _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)
    assert ensure_source_composite_key(engine)["state"] == "rebuilt"
    with engine.connect() as conn:
        assert _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)  # read back from sqlite_master, not assumed
        assert not _wrong(conn)
        assert {r[0]: r[1] for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources")} == {1: 1, 2: 2, 3: 3}
    assert ensure_source_outlet_id(engine) == {"added": False, "triggers": 0, "healed": 0}
    with engine.begin() as conn:
        _insert(conn, "a.com", "f:a.com/other")  # a second feed after the rebuild: the replayed trigger fires
        assert conn.exec_driver_sql("SELECT outlet_id FROM sources WHERE feed_key='f:a.com/other'").scalar_one() == 1


def test_the_rebuild_after_a_store_that_has_no_triggers_yet_is_still_healed_by_the_boot_step(tmp_path):
    engine = _legacy_engine(tmp_path)
    _seed(engine)
    assert ensure_source_composite_key(engine)["state"] == "rebuilt"
    with engine.begin() as conn:
        for name in SOURCE_OUTLET_ID_TRIGGERS:
            conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    result = ensure_source_outlet_id(engine)
    assert result["triggers"] == 3 and result["added"] is False
    with engine.connect() as conn:
        assert not _wrong(conn)


def test_nothing_but_outlet_id_is_written_by_the_heal(tmp_path):
    """R100: a verdict, a qualification date, an attempt count and a criteria version are byte-identical across the heal."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "")]:
            _insert(conn, dom, feed)
        conn.exec_driver_sql("UPDATE sources SET status='qualified', qualified_at='2026-01-02 03:04:05' WHERE id=2")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(sources)") if r[1] != "outlet_id"]
        sel = f"SELECT {', '.join(cols)} FROM sources ORDER BY id"  # noqa: S608  # nosec B608 - column names read from PRAGMA table_info
        before = [tuple(r) for r in conn.exec_driver_sql(sel)]
        conn.exec_driver_sql("UPDATE sources SET outlet_id = NULL")
    ensure_source_outlet_id(engine)
    with engine.connect() as conn:
        assert [tuple(r) for r in conn.exec_driver_sql(sel)] == before
        assert not _wrong(conn)


def test_an_insert_through_the_orm_and_through_a_raw_restore_both_fire_the_triggers(tmp_path):
    """The restore merge writes rows with explicit ids, not through the ORM; a trigger sees both."""
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Source

    engine = _engine(tmp_path)
    session = sessionmaker(bind=engine, future=True)()
    try:
        session.add(Source(name="A", domain="a.com", rss_url="https://a.com/one.xml"))
        session.commit()
        session.add(Source(name="A2", domain="a.com", rss_url="https://a.com/two.xml"))
        session.commit()
        assert [s.outlet_id for s in session.query(Source).order_by(Source.id)] == [1, 1]
    finally:
        session.close()
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO sources (id, name, domain, feed_key, status) VALUES (50, 'old', 'a.com', '3', 'unqualified')")
        conn.exec_driver_sql("INSERT INTO sources (id, name, domain, feed_key, status) VALUES (0, 'zero', 'a.com', '0', 'unqualified')")
        assert not _wrong(conn)
        assert conn.exec_driver_sql("SELECT DISTINCT outlet_id FROM sources WHERE domain='a.com'").fetchall() == [(0,)]


def test_source_writers_beside_a_writer_of_another_column_leave_every_outlet_right(tmp_path):
    """Four threads insert and delete sources while a fifth keeps writing ``sources.last_crawled_at``. SQLite serialises the
    writers and the triggers run inside each statement, so this is a smoke test of the connection pattern (30 s busy timeout, one
    transaction per write): it pins that no writer errors and no state is wrong at the end, and it cannot fail in a way a serial
    run would not. It writes no mention rows."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for i in range(4):
            _insert(conn, f"seed{i}.com", "")
    errors: list[BaseException] = []
    stop = threading.Event()

    def crawler():
        try:
            while not stop.is_set():
                with engine.begin() as conn:
                    conn.exec_driver_sql("UPDATE sources SET last_crawled_at = datetime('now') WHERE id = 1")
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            errors.append(exc)

    def writer(seed):
        rng = random.Random(seed)
        try:
            for step in range(150):
                with engine.begin() as conn:
                    ids = [r[0] for r in conn.exec_driver_sql("SELECT id FROM sources")]
                    if step % 3 == 2 and len(ids) > 8:
                        conn.exec_driver_sql("DELETE FROM sources WHERE id=?", (rng.choice(ids),))
                    else:
                        _insert(conn, f"d{rng.randrange(5)}.com", f"{seed}-{step}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    bg = threading.Thread(target=crawler)
    bg.start()
    workers = [threading.Thread(target=writer, args=(s,)) for s in range(4)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    stop.set()
    bg.join()
    assert not errors, errors
    with engine.connect() as conn:
        assert not _wrong(conn)
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one() > 8


def test_the_counted_outlets_equal_the_distinct_domains_and_an_orphan_stays_its_own_outlet(tmp_path):
    from sqlalchemy import distinct, func, select

    from src.database.models import Source
    from src.database.outlet import outlet_expr

    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "")]:
            _insert(conn, dom, feed)
        conn.exec_driver_sql("CREATE TABLE t (source_id INTEGER)")
        conn.exec_driver_sql("INSERT INTO t VALUES (1),(2),(3),(999)")  # 999: the source row is gone
        n = conn.exec_driver_sql(
            "SELECT COUNT(DISTINCT COALESCE(s.outlet_id, t.source_id)) FROM t LEFT JOIN sources s ON s.id = t.source_id"
        ).scalar_one()
    assert n == 3  # a.com, b.com and the orphan: the two a.com feeds are ONE outlet
    stmt = select(func.count(distinct(outlet_expr(Source.id, Source.outlet_id))))
    assert "coalesce(sources.outlet_id, sources.id)" in str(stmt).lower()
    with engine.connect() as conn:
        assert conn.execute(stmt).scalar_one() == 2


@pytest.mark.parametrize("name", sorted(SOURCE_OUTLET_ID_TRIGGERS))
def test_every_trigger_is_idempotent_to_install_twice(tmp_path, name):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(SOURCE_OUTLET_ID_TRIGGERS[name])  # IF NOT EXISTS: a second install is a no-op, never an error
        assert name in _triggers(conn)


def test_the_real_restore_merge_gives_every_restored_source_a_right_outlet_id(tmp_path):
    """The merge INSERTs sources by raw SQL with ids of its own and never names ``outlet_id``; the triggers answer."""
    from sqlalchemy.orm import sessionmaker

    from src.backup.merge import merge_corpus
    from src.database.models import Source

    meta = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}
    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    for path, rows in [
        (working, [("a.com", "https://a.com/local.xml")]),
        (staged, [("a.com", "https://a.com/in1.xml"), ("a.com", "https://a.com/in2.xml"), ("b.com", "https://b.com/rss")]),
    ]:
        eng = _engine(tmp_path, path.name)
        s = sessionmaker(bind=eng, future=True)()
        for dom, feed in rows:
            s.add(Source(name=f"{dom} {feed}", domain=dom, rss_url=feed))
        s.commit()
        s.close()
        eng.dispose()
    merge_corpus(staged, working, meta)
    eng = create_engine(f"sqlite:///{working}", future=True)
    try:
        with eng.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one() == 4
            assert not _wrong(conn)
            assert conn.exec_driver_sql("SELECT COUNT(DISTINCT outlet_id) FROM sources").scalar_one() == 2
    finally:
        eng.dispose()


def test_an_id_change_repairs_the_siblings_that_pointed_at_the_old_one(tmp_path):
    """Opus read F1(b): ``UPDATE sources SET id`` used to leave the siblings pointing at an id that no longer existed."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "3")]:
            _insert(conn, dom, feed)
        conn.exec_driver_sql("UPDATE sources SET id = 10 WHERE id = 1")
        assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources ORDER BY id")] == [(2, 2), (3, 3), (10, 2)]
        assert not _wrong(conn)


def test_an_insert_or_replace_across_domains_is_the_documented_gap_and_the_next_boot_repairs_it(tmp_path):
    """Opus read F1(a). REPLACE's implicit delete fires no DELETE trigger while ``recursive_triggers`` is off (the repo never
    turns it on), so a row replaced by another domain's leaves its old siblings pointing at the replaced id. The gap is stated in
    the trigger docstring, nothing in ``src/`` writes that way (the scan below), and the boot step is what repairs it."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "3")]:
            _insert(conn, dom, feed)
        assert conn.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 0, "the premise: the repo never sets it"
        conn.exec_driver_sql("INSERT OR REPLACE INTO sources (id, name, domain, feed_key, status) VALUES (1, 'c', 'c.com', '', 'unqualified')")
        gap = conn.exec_driver_sql("SELECT outlet_id FROM sources WHERE id = 2").scalar_one()
    assert gap == 1, "row 2 (a.com) still points at id 1, which is now c.com: the stated gap"
    ensure_source_outlet_id(engine)
    with engine.connect() as conn:
        assert not _wrong(conn)
        assert conn.exec_driver_sql("SELECT outlet_id FROM sources WHERE id = 2").scalar_one() == 2


def test_nothing_in_src_writes_sources_by_replace_or_by_id_update():
    """The two shapes the triggers do not cover (REPLACE across domains) or only cover by ``UPDATE OF id`` must not appear in
    ``src/`` unnoticed: a new writer of that shape has to read the docstring on ``SOURCE_OUTLET_ID_TRIGGERS`` first."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src"
    pattern = re.compile(
        r"(INSERT\s+OR\s+REPLACE\s+INTO\s+sources\b|REPLACE\s+INTO\s+sources\b|UPDATE\s+sources\s+SET\s+id\b|ON\s+CONFLICT[^;]{0,200}\bsources\b)",
        re.IGNORECASE,
    )
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert hits == [], hits


def test_init_db_boots_a_pre_r177_store_into_a_right_one(tmp_path, monkeypatch):
    """Opus read F3: deleting the ``ensure_source_outlet_id`` line from ``init_db`` passed every other test, because ``create_all``
    installs the triggers by itself. This boots a store that has sources, no ``outlet_id`` and no trigger through the real
    ``init_db`` and reads the result."""
    from src.database import session as session_mod

    engine = _engine(tmp_path, "pre.db")
    with engine.begin() as conn:
        for dom, feed in [("a.com", "1"), ("a.com", "2"), ("b.com", "3")]:
            _insert(conn, dom, feed)
        for name in SOURCE_OUTLET_ID_TRIGGERS:
            conn.exec_driver_sql(f"DROP TRIGGER {name}")  # noqa: S608  # nosec B608 - names are this module's own constants
        conn.exec_driver_sql("ALTER TABLE sources DROP COLUMN outlet_id")
    engine.dispose()
    monkeypatch.setattr(session_mod, "engine", engine)
    session_mod.init_db()
    with engine.connect() as conn:
        assert "outlet_id" in {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(sources)")}
        assert _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)
        assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, outlet_id FROM sources ORDER BY id")] == [(1, 1), (2, 1), (3, 3)]
        assert not _wrong(conn)
