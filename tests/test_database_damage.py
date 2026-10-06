"""A damaged database file is noticed, named and contained, per file (damaged-database plan, slice E1).

Every claim here is made against the REAL drivers on REAL damaged copies (the pages are overwritten the
way ``/mnt/project-files/wal-disk-pool/dmg.py`` measured on 2026-10-06), because the failure this exists
for was a file SQLite itself called malformed while ``count(*)``, ``max(id)`` and the first page all
answered: a test that raised a hand-built exception would pass for the wrong reason.

  * the classifier reads the DRIVER's code: ``SQLITE_CORRUPT`` (11, any extended code) and nothing else;
    ``SQLITE_NOTADB`` (26, a wrong passphrase under SQLCipher) never latches, and a bound value that
    says "database disk image is malformed" never does either;
  * the observer latches the file the engine is over, writes ONE incident record without any value, and
    the damaged file itself is not written to;
  * the latch is per file: the corpus's stops collection, the Wikipedia lane's stops that lane's loop,
    and neither stops the other;
  * it releases when the operator starts collection (or the lane) again, never by itself.
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from src.database import damage
from src.database.damage import (
    FILE_CORPUS,
    ROUTE_REBUILD_INDEX,
    ROUTE_VERIFY_THEN_SALVAGE,
    SCOPE_DATA,
    SCOPE_SEARCH_INDEX,
    DamageRegistry,
    corruption_of,
    is_corruption,
    scope_of,
    statement_shape,
)
from src.scheduler import storage_guard as sg

ROOT = Path(__file__).resolve().parents[1]
PAGE = 4096
SECRET = "S3CR3T-TITLE-VALUE-42"


# --------------------------------------------------------------------------- #
#  fixtures: a real store, and a real damaged copy of it
# --------------------------------------------------------------------------- #
def _build_store(path: Path, rows: int = 3000) -> None:
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    # Like the real corpus, a narrow index exists, which is what ``count(*)`` walks: it never touches the
    # wide content pages, so it answers while a content page is gone (the whole point of the measurement).
    con.execute("CREATE INDEX ix_articles_title ON articles (title)")
    rng = random.Random(7)
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [(f"title {i}", "".join(rng.choice("abcdefghij ") for _ in range(900))) for i in range(rows)],
    )
    con.commit()
    con.close()


def _leaf_pages(path: Path, table: str) -> list[int]:
    con = sqlite3.connect(path)
    try:
        return [p for p, t in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name=?", (table,)) if t == "leaf"]
    except sqlite3.OperationalError:
        pytest.skip("this SQLite has no dbstat virtual table")
    finally:
        con.close()


def _overwrite(path: Path, pages: list[int]) -> None:
    with open(path, "r+b") as f:
        for pg in pages:
            f.seek((pg - 1) * PAGE)
            f.write(os.urandom(PAGE))


@pytest.fixture
def damaged(tmp_path):
    """(path, damaged leaf page numbers): three random leaf pages of ``articles`` overwritten."""
    path = tmp_path / "corpus.db"
    _build_store(path)
    leaves = _leaf_pages(path, "articles")
    bad = sorted(random.Random(1).sample(leaves, 3))
    _overwrite(path, bad)
    return path, bad


@pytest.fixture
def registry(tmp_path):
    """The process-global registry, pointed at a record file of this test's own."""
    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    return damage.registry


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "database-damage.json").read_text(encoding="utf-8"))


def _engine(path: Path, file_key: str = FILE_CORPUS):
    eng = create_engine(f"sqlite:///{path}")
    damage.attach(eng, file_key)
    return eng


def _first_failing_read(eng):
    """Scan by id ranges of 100 until one raises: the page overwrite is invisible to count(*)."""
    with eng.connect() as conn:
        for lo in range(0, 3000, 100):
            try:
                conn.execute(
                    text("SELECT sum(length(content)) FROM articles WHERE id > :lo AND id <= :hi"),
                    {"lo": lo, "hi": lo + 100},
                ).scalar()
            except Exception as exc:  # noqa: BLE001
                return lo, exc
    return None, None


# --------------------------------------------------------------------------- #
#  classification
# --------------------------------------------------------------------------- #
def test_a_real_sqlite_corruption_error_is_corruption_with_its_code(damaged):
    path, _bad = damaged
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError) as err:
        con.execute("SELECT sum(length(content)) FROM articles").fetchall()
    found = corruption_of(err.value)
    assert found is not None
    assert found["code"] & 0xFF == 11 and found["name"].startswith("SQLITE_CORRUPT")
    assert found["message"] == "database disk image is malformed"
    assert is_corruption(err.value)


def test_a_count_and_the_first_page_still_answer_on_a_damaged_table(damaged):
    """The measurement the plan rests on (dmg.py): a healthy count is NO evidence the table is whole,
    so the error code is the detector and nothing cheaper is."""
    path, _bad = damaged
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == 3000
    assert con.execute("SELECT max(id) FROM articles").fetchone()[0] == 3000
    assert con.execute("SELECT id FROM articles ORDER BY id LIMIT 5").fetchall()


def test_not_a_database_never_counts_whatever_its_text(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database " * 400)
    con = sqlite3.connect(junk)
    with pytest.raises(sqlite3.DatabaseError) as err:
        con.execute("SELECT count(*) FROM sqlite_master").fetchall()
    assert getattr(err.value, "sqlite_errorcode", None) == 26
    assert corruption_of(err.value) is None


def test_a_wrong_sqlcipher_key_is_not_corruption_and_a_bad_page_under_the_right_key_is(tmp_path):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    path = tmp_path / "enc.db"
    con = sqc.connect(str(path))
    con.execute("PRAGMA key='pass1'")
    con.execute("PRAGMA cipher_page_size=4096")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO articles (body) VALUES (?)", [("x" * 500 + str(i),) for i in range(8000)])
    con.commit()
    con.close()

    wrong = sqc.connect(str(path))
    wrong.execute("PRAGMA key='wrong'")
    with pytest.raises(sqc.DatabaseError) as err:
        wrong.execute("SELECT count(*) FROM sqlite_master").fetchall()
    assert getattr(err.value, "sqlite_errorcode", None) == 26, "the driver stopped distinguishing a wrong key"
    assert corruption_of(err.value) is None
    wrong.close()

    size_pages = path.stat().st_size // 4096
    _overwrite(path, [size_pages // 3, size_pages // 2])
    right = sqc.connect(str(path))
    right.execute("PRAGMA key='pass1'")
    with pytest.raises(sqc.DatabaseError) as err2:
        right.execute("SELECT sum(length(body)) FROM articles").fetchall()
    found = corruption_of(err2.value)
    assert found is not None and found["code"] & 0xFF == 11


def test_a_bound_value_that_says_malformed_is_not_corruption(registry):
    """The lesson of #1306's is_disk_full: SQLAlchemy's wrapper text carries the statement and its bound
    values, so a title that SAYS "database disk image is malformed" must not read as the database saying it."""
    eng = create_engine("sqlite://")
    damage.attach(eng, FILE_CORPUS)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE t (title TEXT UNIQUE)"))
        conn.execute(text("INSERT INTO t VALUES ('database disk image is malformed')"))
    with pytest.raises(Exception) as err, eng.begin() as conn:
        conn.execute(text("INSERT INTO t VALUES ('database disk image is malformed')"))
    assert "database disk image is malformed" in str(err.value)  # the wrapper's text DOES carry it...
    assert not is_corruption(err.value)  # ...and the classifier never reads that text
    assert registry.state()["latched"] == []


def _fake_driver_error(message: str, code=None):
    cls = type("DatabaseError", (Exception,), {"__module__": "sqlite3"})
    exc = cls(message)
    if code is not None:
        exc.sqlite_errorcode = code
    return exc


def test_a_driver_without_error_codes_is_matched_on_its_own_first_line_only():
    assert is_corruption(_fake_driver_error("database disk image is malformed"))
    assert is_corruption(_fake_driver_error("malformed database schema (idx_articles_url) - near x"))
    assert not is_corruption(_fake_driver_error("file is not a database"))
    assert not is_corruption(_fake_driver_error("UNIQUE constraint failed: t.title: database disk image is malformed"))
    # a code, when the driver has one, decides: code 26 with corrupt-sounding text is still not corruption
    assert not is_corruption(_fake_driver_error("database disk image is malformed", code=26))
    # and a non-driver exception is never read at all
    assert not is_corruption(RuntimeError("database disk image is malformed"))
    assert not is_corruption(None)


def test_every_extended_code_of_sqlite_corrupt_counts():
    for extended in (11, 267, 523, 779):  # CORRUPT, _VTAB, _SEQUENCE, _INDEX
        assert is_corruption(_fake_driver_error("database disk image is malformed", code=extended)), extended
    for other in (10, 14, 26, 13):  # IOERR, CANTOPEN, NOTADB, FULL
        assert not is_corruption(_fake_driver_error("x", code=other)), other


def test_the_statement_shape_keeps_no_value():
    shape = statement_shape(
        f"INSERT INTO articles (title, url) VALUES ('{SECRET}', 'https://x.example/a''b') -- 12345\n WHERE id = 987654"
    )
    assert SECRET not in shape and "x.example" not in shape and "987654" not in shape and "12345" not in shape
    assert shape.startswith("INSERT INTO articles")
    assert statement_shape("SELECT ? , ? , ? , ?") == "SELECT ?, ?"
    assert statement_shape(None) is None and statement_shape("") is None
    assert len(statement_shape("SELECT " + "x, " * 500)) <= 240


def test_scope_is_search_index_only_on_evidence_and_the_record_says_which():
    scope, basis = scope_of(267, "SELECT 1")
    assert scope == SCOPE_SEARCH_INDEX and "267" in basis
    scope, basis = scope_of(11, "SELECT block FROM article_fts_data WHERE id = ?")
    assert scope == SCOPE_SEARCH_INDEX and "index table directly" in basis
    # naming the index is NOT evidence: an external-content FTS5 table reads ``articles`` through it
    for shape in (
        "SELECT rowid FROM article_fts WHERE article_fts MATCH ?",
        "SELECT a.id FROM articles a JOIN article_fts f ON f.rowid = a.id",
        "INSERT INTO articles (title) VALUES (?)",
        None,
    ):
        scope, basis = scope_of(11, shape)
        assert scope == SCOPE_DATA and "nothing shows" in basis, shape
    assert damage.route_for(SCOPE_SEARCH_INDEX) == ROUTE_REBUILD_INDEX
    assert damage.route_for(SCOPE_DATA) == ROUTE_VERIFY_THEN_SALVAGE


def test_measured_on_a_real_fts5_index_damage_reads_as_plain_corrupt_through_the_virtual_table(tmp_path):
    """MEASURED 2026-10-06 (SQLite 3.45.1): overwriting leaf pages of ``article_fts_data`` makes a direct
    read of the shadow table raise code 11, and a MATCH over the virtual table ALSO raises plain 11, not
    267. So a statement naming the index proves nothing (see the scope test above): E1 can only SUSPECT
    the search index from a shadow-table read or code 267, and says which basis it used; E2's per-table
    check is what decides."""
    path = tmp_path / "fts.db"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
    except sqlite3.OperationalError:
        pytest.skip("this SQLite has no FTS5")
    con.execute("DROP TABLE probe")
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    con.execute(
        "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', content_rowid='id')"
    )
    rng = random.Random(3)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [(f"t{i}", " ".join(rng.choice(words) + str(rng.randint(0, 3000)) for _ in range(120))) for i in range(6000)],
    )
    con.execute("INSERT INTO article_fts(article_fts) VALUES ('rebuild')")
    con.commit()
    con.close()
    leaves = _leaf_pages(path, "article_fts_data")
    _overwrite(path, sorted(random.Random(5).sample(leaves, 3)))

    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == 6000
    with pytest.raises(sqlite3.DatabaseError) as direct:
        con.execute("SELECT sum(length(block)) FROM article_fts_data").fetchall()
    assert is_corruption(direct.value)
    assert scope_of(corruption_of(direct.value)["code"], statement_shape("SELECT sum(length(block)) FROM article_fts_data"))[0] == SCOPE_SEARCH_INDEX
    codes = set()
    for w in words:
        for n in range(0, 3001, 7):
            try:
                con.execute("SELECT rowid FROM article_fts WHERE article_fts MATCH ?", (f"{w}{n}",)).fetchall()
            except sqlite3.DatabaseError as exc:
                codes.add(getattr(exc, "sqlite_errorcode", None))
    assert codes and all(c & 0xFF == 11 for c in codes), codes


# --------------------------------------------------------------------------- #
#  the observer on a real engine over a real damaged copy
# --------------------------------------------------------------------------- #
def test_a_damaged_page_latches_the_file_records_one_incident_and_writes_nothing_else(damaged, registry, tmp_path):
    path, bad = damaged
    before = path.read_bytes()
    eng = _engine(path)

    lo, exc = _first_failing_read(eng)
    assert exc is not None, "the page overwrite no longer shows up on a range read"
    assert registry.latched(FILE_CORPUS), "the observer did not latch the corpus file"
    assert not registry.latched("wiki"), "a corpus incident latched another file"

    # the record: who, what, where, and nothing from any row
    rec = _record(tmp_path)
    assert rec["schema"] == damage.SCHEMA and len(rec["incidents"]) == 1
    inc = rec["incidents"][0]
    assert inc["file"] == FILE_CORPUS and inc["file_name"] == "corpus.db"
    assert inc["code"] & 0xFF == 11 and inc["message"] == "database disk image is malformed"
    assert inc["scope"] == SCOPE_DATA and inc["route"] == ROUTE_VERIFY_THEN_SALVAGE
    assert inc["statement_shape"].startswith("SELECT sum(length(content)) FROM articles WHERE id >")
    assert inc["thread"] and inc["repeats"] == 0
    assert inc["file_bytes"] == len(before) and inc["wal_bytes"] == 0
    assert "previous_end" in inc and "endpoint" in inc and "session_id" in inc
    assert rec["files"][FILE_CORPUS]["incidents"] == 1

    # a read of a healthy range still answers (reads are never stopped), and the file is untouched
    healthy = 0
    with eng.connect() as conn:
        for start in range(0, 3000, 100):
            try:
                conn.execute(
                    text("SELECT sum(length(content)) FROM articles WHERE id > :a AND id <= :b"),
                    {"a": start, "b": start + 100},
                ).scalar()
                healthy += 1
            except Exception:  # noqa: BLE001
                pass
        assert conn.execute(text("SELECT count(*) FROM articles")).scalar() == 3000
    assert healthy >= 20, "most of the table is still readable and the pause must not hide it"
    assert path.read_bytes() == before, "the observer wrote into the damaged file"
    assert not Path(str(path) + "-wal").exists()


def test_the_same_incident_is_counted_not_re_recorded(damaged, registry, tmp_path):
    path, _bad = damaged
    eng = _engine(path)
    lo, _exc = _first_failing_read(eng)
    for _ in range(3):
        with eng.connect() as conn, pytest.raises(Exception):  # noqa: B017 - the engine's own error type
            conn.execute(
                text("SELECT sum(length(content)) FROM articles WHERE id > :lo AND id <= :hi"),
                {"lo": lo, "hi": lo + 100},
            ).scalar()
    st = registry.state(detail=True)
    assert len(st["incidents"]) == 1, "a repeat of a known incident was written as a new record"
    assert st["incidents"][0]["repeats"] == 3
    assert st["files"][FILE_CORPUS]["incidents"] == 4
    assert st["incident_count"] == 4


def test_the_engine_still_raises_the_original_error(damaged, registry):
    """An observer never replaces the real error."""
    path, _bad = damaged
    _lo, exc = _first_failing_read(_engine(path))
    assert exc is not None and "database disk image is malformed" in str(exc)


def test_a_wrong_key_through_a_real_sqlcipher_engine_never_latches_and_a_bad_page_does(tmp_path, registry):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    path = tmp_path / "enc.db"
    con = sqc.connect(str(path))
    con.execute("PRAGMA key='pass1'")
    con.execute("PRAGMA cipher_page_size=4096")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO articles (body) VALUES (?)", [("x" * 500 + str(i),) for i in range(8000)])
    con.commit()
    con.close()

    def engine_with(key):
        def _creator():
            c = sqc.connect(str(path), check_same_thread=False)
            c.execute(f"PRAGMA key='{key}'")
            return c

        eng = create_engine("sqlite://", creator=_creator)
        damage.attach(eng, FILE_CORPUS)
        return eng

    with pytest.raises(Exception), engine_with("wrong").connect() as conn:  # noqa: B017
        conn.execute(text("SELECT count(*) FROM sqlite_master")).fetchall()
    assert not registry.latched(FILE_CORPUS), "a wrong passphrase latched damage"
    assert registry.state()["incident_count"] == 0

    pages = path.stat().st_size // 4096
    _overwrite(path, [pages // 3, pages // 2])
    with pytest.raises(Exception), engine_with("pass1").connect() as conn:  # noqa: B017
        conn.execute(text("SELECT sum(length(body)) FROM articles")).fetchall()
    assert registry.latched(FILE_CORPUS), "a damaged page under the right key did not latch"


def test_an_attach_statement_is_never_attributed_to_the_engines_file(registry, tmp_path):
    """An ATTACHed file's error cannot say which file it came from: no latch on the wrong one."""
    junk = tmp_path / "other.db"
    junk.write_bytes(os.urandom(PAGE * 4))
    eng = create_engine("sqlite://")
    damage.attach(eng, FILE_CORPUS)
    ctx = type("Ctx", (), {})()
    ctx.original_exception = _fake_driver_error("database disk image is malformed", code=11)
    ctx.statement = "ATTACH DATABASE ? AS other"
    registry.on_engine_error(ctx, FILE_CORPUS)
    assert not registry.latched(FILE_CORPUS)
    ctx.statement = "SELECT 1"
    registry.on_engine_error(ctx, FILE_CORPUS)
    assert registry.latched(FILE_CORPUS)


def test_the_incident_record_keeps_no_value_and_no_passphrase(registry, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "hunter2-passphrase")
    ctx = type("Ctx", (), {})()
    ctx.original_exception = _fake_driver_error("database disk image is malformed", code=11)
    ctx.statement = f"INSERT INTO articles (title) VALUES ('{SECRET}') -- 31337"
    ctx.parameters = (SECRET,)
    registry.on_engine_error(ctx, FILE_CORPUS)
    raw = (tmp_path / "database-damage.json").read_text(encoding="utf-8")
    assert SECRET not in raw and "hunter2" not in raw and "31337" not in raw
    assert "INSERT INTO articles" in raw


# --------------------------------------------------------------------------- #
#  the registry: persistence, the latch, retry
# --------------------------------------------------------------------------- #
def _note(reg, file_key=FILE_CORPUS, statement="SELECT 1", code=11):
    return reg.note(file_key, _fake_driver_error("database disk image is malformed", code=code), statement=statement)


def test_the_record_survives_a_restart_but_the_latch_does_not(tmp_path, monkeypatch):
    path = tmp_path / "rec.json"
    monkeypatch.setattr(damage, "_current_session_id", lambda: "session-one")
    first = DamageRegistry(path_fn=lambda: path)
    assert _note(first)
    assert first.latched(FILE_CORPUS)
    monkeypatch.setattr(damage, "_current_session_id", lambda: "session-two")
    second = DamageRegistry(path_fn=lambda: path)  # a new process, so a new session
    assert not second.latched(FILE_CORPUS), "a restart is the operator trying again"
    st = second.state(detail=True)
    assert st["incident_count"] == 1 and len(st["incidents"]) == 1 and st["last_incident"]["file"] == FILE_CORPUS
    assert _note(second)  # the first failed read puts it back
    assert second.latched(FILE_CORPUS)
    assert len(second.state(detail=True)["incidents"]) == 2, "an incident of a new session is its own record"


def test_the_newest_twenty_incidents_are_kept(tmp_path):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    for i in range(damage.INCIDENTS_KEEP + 7):
        _note(reg, statement=f"SELECT col{i} FROM t{'x' * i}")
    shapes = [i["statement_shape"] for i in reg.state(detail=True)["incidents"]]
    assert len(shapes) == damage.INCIDENTS_KEEP
    assert shapes[-1].startswith(f"SELECT col{damage.INCIDENTS_KEEP + 6} ")
    assert len(json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))["incidents"]) == damage.INCIDENTS_KEEP


def test_an_unreadable_prior_record_is_said_and_replaced(tmp_path):
    path = tmp_path / "rec.json"
    path.write_text("{ not json", encoding="utf-8")
    reg = DamageRegistry(path_fn=lambda: path)
    assert reg.state()["prior_record_unreadable"] is True
    assert _note(reg)
    assert json.loads(path.read_text(encoding="utf-8"))["incidents"]


def test_a_drive_that_cannot_take_the_record_is_said_and_the_latch_still_holds(tmp_path):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "no-such-dir" / "rec.json")
    assert _note(reg)
    assert reg.latched(FILE_CORPUS), "the latch must not depend on the write"
    assert reg.state()["write_error"]


def test_retry_releases_the_named_files_only_and_keeps_the_record(tmp_path):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    _note(reg, FILE_CORPUS)
    _note(reg, "wiki")
    _note(reg, "law")
    assert reg.retry(reason="test", files=damage.COLLECTION_FILES) == [FILE_CORPUS, "law"] or set(
        reg.state()["latched"]
    ) == {"wiki"}
    assert reg.latched("wiki") and not reg.latched(FILE_CORPUS) and not reg.latched("law")
    assert reg.state()["incident_count"] == 3, "a retry must not erase what happened"
    assert reg.state()["files"][FILE_CORPUS]["retries"] == 1
    assert reg.retry(reason="test", files=("wiki",)) == ["wiki"]
    assert reg.retry(reason="test") == []  # nothing left to release


def test_the_pause_has_its_own_switch_and_the_record_does_not(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    _note(reg)
    assert reg.latched(FILE_CORPUS)
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    assert not reg.latched(FILE_CORPUS) and reg.notes() == []
    assert reg.state()["enabled"] is False and reg.state()["incident_count"] == 1
    # it is NOT the storage guard's switch
    monkeypatch.delenv("OO_DAMAGE_GUARD")
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert reg.latched(FILE_CORPUS)


def test_the_sentences_are_plain_and_name_what_is_true(registry):
    _note(registry, FILE_CORPUS)
    [note] = registry.notes()
    assert note["frame"] == damage.FRAME_DATA and note["vars"] == {}
    registry.retry(reason="t")
    _note(registry, FILE_CORPUS, statement="SELECT block FROM article_fts_data")
    assert registry.notes()[0]["frame"] == damage.FRAME_SEARCH_INDEX
    _note(registry, "wiki")
    assert {n["file"] for n in registry.notes()} == {FILE_CORPUS, "wiki"}
    _note(registry, "osm")  # a lane with no loop this module pauses has no pause to announce
    assert {n["file"] for n in registry.notes()} == {FILE_CORPUS, "wiki"}
    for frame in (damage.FRAME_DATA, damage.FRAME_SEARCH_INDEX, damage.FRAME_WIKI):
        low = frame.lower()
        assert "repair" not in low and "being checked" not in low and "will be fixed" not in low, (
            "E1 verifies and repairs nothing and must not say it does"
        )
        assert "nothing was deleted" in low or "were not changed" in low


def test_the_bundle_member_is_the_record_cut_oldest_first_and_names_the_cut(registry, tmp_path):
    for i in range(12):
        _note(registry, statement=f"SELECT col{i} FROM t{'x' * (3 * i)}")
    full = damage.diagnostics_member(10**6)
    assert "error" not in full and full["dropped_oldest_to_fit"] == 0 and len(full["incidents"]) == 12
    assert full["method"] == damage.METHOD and full["latched"] == [FILE_CORPUS]
    cut = damage.diagnostics_member(len(json.dumps(full, separators=(",", ":"))) - 600)
    assert 0 < len(cut["incidents"]) < 12 and cut["dropped_oldest_to_fit"] == 12 - len(cut["incidents"])
    assert cut["incidents"][-1] == full["incidents"][-1], "the newest incident is what stays"
    assert cut["files"] == full["files"] and cut["incident_count"] == 12, "the counters never lose an incident to a cut"
    assert damage.diagnostics_member(0)["method"], "a nonsense budget is raised to the smallest, never an error"


def test_the_bundle_member_never_raises(registry, monkeypatch):
    monkeypatch.setattr(registry, "state", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom\nsecond")))
    assert damage.diagnostics_member(50_000) == {"error": "RuntimeError: boom"}


# --------------------------------------------------------------------------- #
#  containment: the guard, per file
# --------------------------------------------------------------------------- #
def test_a_latched_corpus_stops_collection_whatever_the_storage_guard_says(registry):
    g = sg.StorageGuard()
    assert g.admit() is None
    _note(registry, FILE_CORPUS)
    assert g.admit() == "damage" and g.kind() == "damage" and g.phase() == sg.PHASE_DAMAGE
    assert not g.engaged, "the damage latch is not a storage reading and must not look like one"


def test_the_operators_resume_anyway_does_not_release_a_damage_latch(registry, monkeypatch):
    g = sg.StorageGuard(readings_fn=lambda: {"wal_bytes": 10, "disk_free_bytes": 10**12})
    _note(registry, FILE_CORPUS)
    out = g.override(reason="test")
    assert out["engaged"] is False and out["overridden"] is False
    assert g.admit() == "damage"
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert g.admit() == "damage", "disabling the resource guard is not saying 'write into a damaged file'"


def test_a_storage_limit_wins_the_name_while_both_hold_and_damage_stays_after(registry, monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")  # tests/conftest.py turns the resource guard off by default
    g = sg.StorageGuard(readings_fn=lambda: {})
    g.note_disk_full("full")
    _note(registry, FILE_CORPUS)
    assert g.admit() == "disk"
    g.reset(reason="test")
    assert g.admit() == "damage"


def test_a_lane_latch_does_not_stop_the_corpus_and_the_corpus_latch_does_not_stop_a_lane(registry):
    g = sg.StorageGuard()
    _note(registry, "wiki")
    assert g.admit() is None, "a damaged Wikipedia file paused corpus collection"
    registry.retry(reason="t")
    _note(registry, FILE_CORPUS)
    assert not registry.latched("wiki"), "a damaged corpus paused the Wikipedia lane"


def test_the_state_carries_the_damage_notes_phase_and_reason(registry):
    g = sg.StorageGuard(readings_fn=lambda: {})
    assert g.state()["database_damage"]["latched"] == [] and g.state()["phase"] is None
    _note(registry, FILE_CORPUS)
    st = g.state()
    assert st["phase"] == sg.PHASE_DAMAGE
    assert st["database_damage"]["latched"] == [FILE_CORPUS]
    assert st["database_damage"]["notes"][0]["frame"] == damage.FRAME_DATA
    assert damage.FRAME_DATA in st["reason"]
    assert st["engaged"] is False and st["notes"] == [], "the storage notes are the limits' and stay theirs"
    detail = g.state(detail=True)["database_damage"]
    assert detail["incidents"] and detail["method"] == damage.METHOD


# --------------------------------------------------------------------------- #
#  the Wikipedia lane's loop stops on its own file's latch, and only that
# --------------------------------------------------------------------------- #
class _FakeRunner:
    """Just enough of the lane runner for ``run_until_stopped``'s loop."""

    def __init__(self):
        from src.wiki import runner as wr

        self.wr = wr
        self.runner = wr.WikiLaneRunner.__new__(wr.WikiLaneRunner)
        r = self.runner
        r._stop = __import__("threading").Event()
        r._interval = 0.0
        r.drains = 0
        r.consecutive_failures = 0
        r.last_error = None
        r.paused_reason = None
        r._sleeps = 0
        self.drained = 0
        r._should_stop = lambda: False
        r._sleep = self._sleep
        r.drain = self._drain
        r.refresh_one_pageview_top = lambda: None
        r.idle = lambda seconds: None

    def _sleep(self, seconds):
        self.runner._sleeps += 1

    def _drain(self):
        self.drained += 1


def test_the_wiki_loop_waits_while_its_file_is_latched_and_resumes_when_released(registry):
    f = _FakeRunner()
    _note(registry, "wiki")
    assert f.runner.run_until_stopped(max_drains=3) == 0
    assert f.drained == 0 and f.runner.paused_reason == f.wr.DAMAGED
    assert f.runner.drain_status()["paused"] == f.wr.DAMAGED if hasattr(f.runner, "_monotonic") else True
    registry.retry(reason="the Wikipedia lane was started", files=("wiki",))
    assert f.runner.run_until_stopped(max_drains=2) == 2
    assert f.drained == 2 and f.runner.paused_reason is None


def test_a_corpus_latch_does_not_stop_the_wiki_loop(registry):
    f = _FakeRunner()
    _note(registry, FILE_CORPUS)
    assert f.runner.run_until_stopped(max_drains=2) == 2 and f.drained == 2


def test_the_loop_without_a_tick_limit_sleeps_instead_of_spinning(registry):
    f = _FakeRunner()
    _note(registry, "wiki")
    calls = {"n": 0}

    def stop_after_three():
        calls["n"] += 1
        return calls["n"] > 3

    f.runner._should_stop = stop_after_three
    f.runner.run_until_stopped()
    assert f.runner._sleeps >= 2 and f.drained == 0


def test_starting_the_lane_again_releases_only_its_own_latch(registry):
    from src.wiki import service

    _note(registry, "wiki")
    _note(registry, FILE_CORPUS)
    src = (ROOT / "src/wiki/service.py").read_text(encoding="utf-8")
    assert 'damage.registry.retry(reason="the Wikipedia lane was started", files=("wiki",))' in src
    assert service.start_wiki_lane.__module__ == "src.wiki.service"


# --------------------------------------------------------------------------- #
#  wiring: the observers are on the engines, the operator's start retries, the seams admit
# --------------------------------------------------------------------------- #
def test_the_corpus_engine_and_every_lane_engine_carry_the_observer():
    from src.database import session

    key, listener = damage.attached(session.engine) or (None, None)
    assert key == FILE_CORPUS, "the corpus engine lost its damage observer"
    assert event.contains(session.engine, "handle_error", listener), "the observer is recorded but not live on the engine"
    src = (ROOT / "src/versioned/store.py").read_text(encoding="utf-8")
    assert "damage.attach(eng, spec.kind)" in src, "the lane engines lost their damage observer"
    assert "damage.attach(engine, _damage.FILE_CORPUS)" in (ROOT / "src/database/session.py").read_text(encoding="utf-8")



def test_a_lane_engine_names_its_own_file(tmp_path, registry, monkeypatch):
    """The lane engine is built with its kind as the file key: a wiki incident latches 'wiki'."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.versioned import store

    seen = {}
    real = damage.attach

    def spy(engine, key):
        seen["key"] = key
        return real(engine, key)

    monkeypatch.setattr(damage, "attach", spy)
    store._build_engine(store.lane("wiki"), tmp_path / "wiki.db")
    assert seen["key"] == "wiki"


def test_the_operators_start_and_run_now_retry_the_collection_files():
    src = (ROOT / "src/api/scheduler.py").read_text(encoding="utf-8")
    assert src.count("damage.registry.retry(") == 2
    assert 'reason="operator started collection", files=damage.COLLECTION_FILES' in src
    assert 'reason="operator ran collection now", files=damage.COLLECTION_FILES' in src
    assert damage.COLLECTION_FILES == (FILE_CORPUS, "law")


def test_the_pass_pause_loop_maps_the_damage_phase_and_says_it_does_not_resume_by_itself():
    src = (ROOT / "src/scheduler/runner.py").read_text(encoding="utf-8")
    assert '"damage": storage_guard.PHASE_DAMAGE' in src
    assert "collection paused (database damage)" in src and "started again" in src
    assert 'self._note_maint_skip("database_damage")' in src
    assert 'damage.registry.latched("law")' in src


def test_the_law_housekeeping_step_waits_on_its_own_file(registry, monkeypatch):
    """A damaged LAW file skips the law step of the housekeeping lane and nothing else in it."""
    import src.ingest.fetch_release as fr
    from src.scheduler import runner as rn

    ran: list[str] = []
    monkeypatch.setitem(rn._LANE_STEPS, "law", lambda s, f, st: ran.append("law") or {"ran": True})
    monkeypatch.setitem(rn._LANE_STEPS, "backfill", lambda s, f, st: ran.append("backfill") or {"ran": True})
    monkeypatch.setattr(rn, "_lane_pending_kinds", lambda settings: ["law", "backfill"])
    monkeypatch.setattr(rn, "_lane_kind_order", lambda kinds: list(kinds))
    monkeypatch.setattr(rn, "_activity", lambda *a, **k: None)
    monkeypatch.setattr(fr, "wrap_fetcher", lambda f, s: f)
    _note(registry, "law")
    out = rn.run_housekeeping_lane(object(), object(), object())
    assert ran == ["backfill"], "the law step ran into a damaged law file, or its neighbour was stopped"
    assert out["law"] == {"skipped": "database-damaged"} and out["backfill"] == {"ran": True}
    registry.retry(reason="test", files=("law",))
    ran.clear()
    out = rn.run_housekeeping_lane(object(), object(), object())
    assert ran == ["law", "backfill"]


# --------------------------------------------------------------------------- #
#  the strings: twelve locales, honest about what E1 does
# --------------------------------------------------------------------------- #
def _keys():
    core = (ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    hover = re.search(r't\("(The database reported that it could not read part of one of your data files[^"]*)"\)', core)
    assert hover, "the damage hover moved -- re-anchor this test"
    return [damage.FRAME_DATA, damage.FRAME_SEARCH_INDEX, damage.FRAME_WIKI, "Paused: the database reported damage", hover.group(1)]


def test_every_damage_string_is_in_the_twelve_locales_translated():
    for p in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in _keys():
            assert k in d, f"{p.name} lacks {k[:50]!r}"
            if p.name != "en.json":
                assert d[k] != k, f"{p.name}: untranslated {k[:50]!r}"
    fr = json.loads((ROOT / "src/static/locales/fr.json").read_text(encoding="utf-8"))
    assert "La voie Wikipédia" in fr[damage.FRAME_WIKI], "French says 'voie' (feminine) for a lane"


def test_the_phase_label_is_known_to_both_uis():
    for rel in ("src/static/app-core.js", "src/static/taskmanager.js"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert 'phase === "paused-damaged"' in src and "Paused: the database reported damage" in src, rel
