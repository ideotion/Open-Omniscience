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
import sys
import threading
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
from src.scheduler import runner
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
        reason = "this SQLite build has no dbstat virtual table (SQLITE_ENABLE_DBSTAT_VTAB)"
        if os.getenv("CI") and sys.platform.startswith("linux"):
            # the Linux lane is where the real damaged-page tests are meant to run: a silent skip
            # there would leave the whole file asserting nothing
            pytest.fail(reason + " -- the Linux CI lane must run the damaged-page tests")
        pytest.skip(reason)
    finally:
        con.close()


def _overwrite(path: Path, pages: list[int]) -> None:
    with open(path, "r+b") as f:
        for pg in pages:
            f.seek((pg - 1) * PAGE)
            f.write(random.Random(pg).randbytes(PAGE))  # seeded: a failing run is reproducible


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
    # ERROR, BUSY, LOCKED, INTERRUPT, IOERR, FULL, CANTOPEN, NOTADB: a transient or another failure is not damage
    for other in (1, 5, 6, 9, 10, 13, 14, 26):
        assert not is_corruption(_fake_driver_error("x", code=other)), other
        assert not is_corruption(_fake_driver_error("database disk image is malformed", code=other)), other


def test_a_missing_capability_in_the_schema_is_not_corruption_even_with_its_corrupt_wording():
    """SQLite words a connection that lacks a function, module or collation the schema needs as
    "malformed database schema (x) - no such ...": a missing capability of the connection, not a damaged
    file. ONLY those three (the drivers the app ships word them differently, so this is a guard for an
    older SQLite)."""
    for what in ("function: fts_norm", "module: fts9", "collation sequence: nocase9"):
        msg = f"malformed database schema (ix_articles_norm) - no such {what}"
        assert not is_corruption(_fake_driver_error(msg)), what
        assert not is_corruption(_fake_driver_error(msg, code=11)), what
    assert is_corruption(_fake_driver_error("malformed database schema (ix_x) - near \"x\": syntax error", code=11))


def _lose_a_schema_row(path: Path, how: str) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a, b)")
    con.execute("CREATE INDEX ix_t ON t (a)")
    con.commit()
    con.execute("PRAGMA writable_schema=ON")
    if how == "table":
        con.execute("DELETE FROM sqlite_master WHERE type='table' AND name='t'")
    else:
        con.execute("UPDATE sqlite_master SET sql='CREATE INDEX ix_t ON t(nosuchcol)' WHERE name='ix_t'")
    con.commit()
    con.close()


@pytest.mark.parametrize("how, words", [("table", "no such table"), ("column", "no such column")])
def test_a_schema_row_that_names_nothing_real_is_damage_on_the_real_driver(tmp_path, registry, how, words):
    """MEASURED on both drivers with a schema row edited out (``writable_schema``): code 11, "malformed
    database schema (ix_t) - no such table/column". That is a damaged schema, not a missing capability."""
    path = tmp_path / "s.db"
    _lose_a_schema_row(path, how)
    con = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.DatabaseError) as err:
            con.execute("SELECT count(*) FROM sqlite_master").fetchall()
    finally:
        con.close()
    assert str(err.value).startswith("malformed database schema") and words in str(err.value)
    assert is_corruption(err.value)
    eng = _engine(path)
    try:
        with pytest.raises(Exception), eng.connect() as conn:  # noqa: B017 - the engine's own error type
            conn.execute(text("SELECT count(*) FROM sqlite_master")).fetchall()
        assert registry.latched(FILE_CORPUS)
    finally:
        eng.dispose()


def test_a_closed_connection_and_a_busy_database_are_never_corruption(tmp_path, registry):
    path = tmp_path / "busy.db"
    _build_store(path, rows=20)
    con = sqlite3.connect(path)
    con.close()
    with pytest.raises(sqlite3.ProgrammingError) as closed:
        con.execute("SELECT 1")
    assert not is_corruption(closed.value)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        eng = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.05})
        damage.attach(eng, FILE_CORPUS)
        with pytest.raises(Exception) as busy, eng.begin() as conn:  # noqa: B017 - the engine's own error type
            conn.execute(text("INSERT INTO articles (title, content) VALUES ('x', 'y')"))
        assert "locked" in str(busy.value).lower()
        assert not is_corruption(busy.value) and not registry.latched(FILE_CORPUS)
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_the_statement_shape_keeps_no_value():
    shape = statement_shape(
        f"INSERT INTO articles (title, url) VALUES ('{SECRET}', 'https://x.example/a''b') -- 12345\n WHERE id = 987654"
    )
    assert SECRET not in shape and "x.example" not in shape and "987654" not in shape and "12345" not in shape
    assert shape.startswith("INSERT INTO articles")
    assert statement_shape("SELECT ? , ? , ? , ?") == "SELECT ?, ?"
    assert statement_shape(None) is None and statement_shape("") is None
    assert len(statement_shape("SELECT " + "x, " * 500)) <= 240


def test_scope_is_search_index_when_the_statement_reads_the_index_and_the_record_says_which():
    scope, basis = scope_of(267, "SELECT 1")
    assert scope == SCOPE_SEARCH_INDEX and "267" in basis
    # MEASURED: a damaged index read through MATCH raises plain 11, so the statement is the evidence
    for shape in (
        "SELECT block FROM article_fts_data WHERE id = ?",
        "SELECT rowid FROM article_fts WHERE article_fts MATCH ?",
        "SELECT 1 FROM article_fts_docsize",
        "INSERT INTO article_fts(article_fts) VALUES (?)",
    ):
        scope, basis = scope_of(11, shape)
        assert scope == SCOPE_SEARCH_INDEX and "search index" in basis and "suspicion" in basis, shape
    for shape in ("INSERT INTO articles (title) VALUES (?)", "SELECT count(*) FROM keyword_mentions", None):
        scope, basis = scope_of(11, shape)
        assert scope == SCOPE_DATA and "nothing shows" in basis, shape
    # the app's own Search matches the index AND gates each hit on the articles table in the same statement:
    # damaged ARTICLE pages raise the same code from it (measured), so it cannot say which one failed
    for shape in (
        "SELECT rowid FROM article_fts WHERE article_fts MATCH ? AND EXISTS (SELECT N FROM articles a "
        "WHERE a.id = article_fts.rowid AND a.quarantined IS NOT N)",
        "SELECT a.id FROM article_fts JOIN articles a ON a.id = article_fts.rowid WHERE article_fts MATCH ?",
    ):
        scope, basis = scope_of(11, shape)
        assert scope == SCOPE_DATA and "either" in basis, shape
    assert scope_of(267, "SELECT 1 FROM articles")[0] == SCOPE_SEARCH_INDEX, "the virtual-table code still decides"
    assert damage.route_for(SCOPE_SEARCH_INDEX) == ROUTE_REBUILD_INDEX
    assert damage.route_for(SCOPE_DATA) == ROUTE_VERIFY_THEN_SALVAGE


_FTS_WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]


def _build_fts_store(path: Path) -> None:
    """A corpus-shaped file with an external-content FTS5 index over ``articles`` (skips without FTS5)."""
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
    except sqlite3.OperationalError:
        pytest.skip("this SQLite has no FTS5")
    con.execute("DROP TABLE probe")
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT, quarantined INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', content_rowid='id')"
    )
    rng = random.Random(3)
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [
            (f"t{i}", " ".join(rng.choice(_FTS_WORDS) + str(rng.randint(0, 3000)) for _ in range(120)))
            for i in range(6000)
        ],
    )
    con.execute("INSERT INTO article_fts(article_fts) VALUES ('rebuild')")
    con.commit()
    con.close()


def test_the_scope_is_decided_on_the_whole_statement_not_on_the_cut_the_record_keeps(registry):
    """A long statement can name the articles table after the 240 characters the record keeps."""
    long_statement = (
        "SELECT rowid FROM article_fts WHERE article_fts MATCH ?" + " AND x = ?" * 80
        + " AND EXISTS (SELECT 1 FROM articles a WHERE a.id = article_fts.rowid)"
    )
    kept = statement_shape(long_statement)
    assert len(kept) <= 240 and "articles" not in kept, "the premise: the cut hides the second table"
    _note(registry, statement=long_statement)
    [inc] = registry.state(detail=True)["incidents"]
    assert inc["scope"] == SCOPE_DATA and len(inc["statement_shape"]) <= 240


def test_measured_on_a_real_fts5_index_damage_reads_as_plain_corrupt_through_the_virtual_table(tmp_path):
    """MEASURED 2026-10-06 (SQLite 3.45.1): overwriting leaf pages of ``article_fts_data`` makes a direct
    read of the shadow table raise code 11, and a MATCH over the virtual table ALSO raises plain 11, not
    267. So the code cannot say "the index" and the STATEMENT is the evidence E1 has (a suspicion, with its
    basis recorded); E2's per-table check is what decides."""
    path = tmp_path / "fts.db"
    _build_fts_store(path)
    leaves = _leaf_pages(path, "article_fts_data")
    _overwrite(path, sorted(random.Random(5).sample(leaves, 3)))

    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == 6000
    with pytest.raises(sqlite3.DatabaseError) as direct:
        con.execute("SELECT sum(length(block)) FROM article_fts_data").fetchall()
    assert is_corruption(direct.value)
    assert scope_of(corruption_of(direct.value)["code"], statement_shape("SELECT sum(length(block)) FROM article_fts_data"))[0] == SCOPE_SEARCH_INDEX
    codes = set()
    for w in _FTS_WORDS:
        for n in range(0, 3001, 7):
            try:
                con.execute("SELECT rowid FROM article_fts WHERE article_fts MATCH ?", (f"{w}{n}",)).fetchall()
            except sqlite3.DatabaseError as exc:
                codes.add(getattr(exc, "sqlite_errorcode", None))
    assert codes and all(c & 0xFF == 11 for c in codes), codes


def test_a_real_match_on_a_damaged_index_is_filed_as_the_search_index_with_its_rebuild_route(tmp_path, registry):
    """The coordinator's condition: damage that the driver reports as plain 11 through a MATCH is routed
    to the index's own path, because the failing statement names the index."""
    path = tmp_path / "fts.db"
    _build_fts_store(path)
    leaves = _leaf_pages(path, "article_fts_data")
    _overwrite(path, sorted(random.Random(5).sample(leaves, 3)))
    eng = _engine(path)
    failed = None
    with eng.connect() as conn:
        for w in _FTS_WORDS:
            for n in range(0, 3001, 7):
                try:
                    conn.execute(
                        text("SELECT rowid FROM article_fts WHERE article_fts MATCH :q"), {"q": f"{w}{n}"}
                    ).fetchall()
                except Exception as exc:  # noqa: BLE001
                    failed = exc
                    break
            if failed:
                break
    assert failed is not None, "the index damage no longer shows up through MATCH"
    assert registry.latched(FILE_CORPUS)
    inc = registry.state(detail=True)["incidents"][0]
    assert inc["code"] & 0xFF == 11 and inc["code"] != damage.SQLITE_CORRUPT_VTAB, "measured: plain 11"
    assert inc["scope"] == SCOPE_SEARCH_INDEX and inc["route"] == ROUTE_REBUILD_INDEX
    assert "article_fts" in inc["statement_shape"] and "suspicion" in inc["scope_basis"]
    assert registry.notes()[0]["frame"] == damage.FRAME_SEARCH_INDEX
    # the data scope still wins afterwards: a later incident on the table itself is the worse news
    _note(registry, FILE_CORPUS, statement="SELECT sum(length(content)) FROM articles")
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA


def test_a_search_over_damaged_article_pages_is_filed_as_data_not_as_the_search_index(tmp_path, registry):
    """MEASURED (the deep read of 31e44b9d): with ARTICLE pages overwritten and every index page whole, the
    app's own gated Search statement raises 11, and filing that as the search index would tell the operator
    the wrong part is damaged and route it to the one repair that would not help."""
    from src.database import fts

    path = tmp_path / "fts.db"
    _build_fts_store(path)
    leaves = _leaf_pages(path, "articles")
    _overwrite(path, sorted(random.Random(9).sample(leaves, max(6, len(leaves) // 4))))
    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT sum(length(block)) FROM article_fts_data").fetchone()[0], "the index reads whole"
    finally:
        con.close()
    eng = _engine(path)
    sql = "SELECT rowid FROM article_fts WHERE article_fts MATCH :q" + fts._QUARANTINE_GATE
    failed = None
    with eng.connect() as conn:
        for w in _FTS_WORDS:
            for n in range(0, 3001, 7):
                try:
                    conn.execute(text(sql), {"q": f"{w}{n}"}).fetchall()
                except Exception as exc:  # noqa: BLE001
                    failed = exc
                    break
            if failed:
                break
    assert failed is not None, "the article damage no longer shows up through the gated search"
    inc = registry.state(detail=True)["incidents"][0]
    assert inc["code"] & 0xFF == 11
    assert inc["scope"] == SCOPE_DATA and inc["route"] == ROUTE_VERIFY_THEN_SALVAGE, inc
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA


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
    # what starting collection does: everything but the Wikipedia lane's file
    assert sorted(reg.retry(reason="test", except_files=damage.NOT_RELEASED_BY_COLLECTION)) == [FILE_CORPUS, "law"]
    assert reg.latched("wiki") and not reg.latched(FILE_CORPUS) and not reg.latched("law")
    assert reg.state()["incident_count"] == 3, "a retry must not erase what happened"
    assert reg.state()["files"][FILE_CORPUS]["retries"] == 1
    assert reg.retry(reason="test", files=("wiki",)) == ["wiki"]
    assert reg.retry(reason="test") == []  # nothing left to release
    # a named file that is also excepted stays latched (the exception wins)
    _note(reg, "wiki")
    assert reg.retry(reason="test", files=("wiki",), except_files=("wiki",)) == [] and reg.latched("wiki")


def test_the_pause_has_its_own_switch_and_the_record_does_not(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    _note(reg)
    assert reg.latched(FILE_CORPUS)
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    assert not reg.latched(FILE_CORPUS)
    # the damage is still NAMED, and the sentence says the pause is off: a silent switch must never
    # read as a healthy file
    [note] = reg.notes()
    assert note["file"] == FILE_CORPUS and note["frame"] == damage.FRAME_PAUSE_OFF
    assert "OO_DAMAGE_GUARD=0" in damage.FRAME_PAUSE_OFF and "carries on" in damage.FRAME_PAUSE_OFF
    assert reg.state()["enabled"] is False and reg.state()["incident_count"] == 1
    assert reg.state()["latched"] == [], "a paused file is one the writers stop for; this one they do not"
    # it is NOT the storage guard's switch
    monkeypatch.delenv("OO_DAMAGE_GUARD")
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert reg.latched(FILE_CORPUS)
    assert reg.notes()[0]["frame"] == damage.FRAME_DATA


def test_the_sentences_are_plain_and_name_what_is_true(registry):
    _note(registry, FILE_CORPUS)
    [note] = registry.notes()
    assert note["frame"] == damage.FRAME_DATA and note["vars"] == {}
    registry.retry(reason="t")
    _note(registry, FILE_CORPUS, statement="SELECT block FROM article_fts_data")
    assert registry.notes()[0]["frame"] == damage.FRAME_SEARCH_INDEX
    _note(registry, "wiki")
    _note(registry, "law")
    frames = {n["file"]: n["frame"] for n in registry.notes()}
    assert frames == {
        FILE_CORPUS: damage.FRAME_SEARCH_INDEX,
        "wiki": damage.FRAME_WIKI,
        "law": damage.FRAME_LAW,
    }
    # a file with no writer this module pauses is SAID, with a sentence that claims no pause
    _note(registry, "osm")
    assert {n["file"]: n["frame"] for n in registry.notes()}["osm"] == damage.FRAME_RECORDED
    for frame in (
        damage.FRAME_DATA,
        damage.FRAME_SEARCH_INDEX,
        damage.FRAME_WIKI,
        damage.FRAME_LAW,
        damage.FRAME_RECORDED,
        damage.FRAME_PAUSE_OFF,
    ):
        low = frame.lower()
        assert "repair" not in low and "being checked" not in low and "will be fixed" not in low, (
            "E1 verifies and repairs nothing and must not say it does"
        )
        assert "is still readable" not in low and "stays readable" not in low, "E1 has not looked"
    for frame in (damage.FRAME_DATA, damage.FRAME_SEARCH_INDEX, damage.FRAME_WIKI, damage.FRAME_LAW, damage.FRAME_RECORDED):
        low = frame.lower()
        # A sentence without an agent ("nothing was deleted") reads, beside "part of your data could not be read",
        # as "nothing was lost": E1 cannot say that (an overwritten page has lost its rows).
        assert "deleted nothing because of it" in low, frame
        assert "nothing was deleted" not in low and "nothing is deleted" not in low, frame
    assert "paused" not in damage.FRAME_RECORDED.lower(), "the recorded-only frame claims no pause"


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
def _bare_runner(**kw):
    """The REAL lane runner, built through its own constructor with every moving part injected as a stub: a
    ``__new__`` shell without the constructor stops matching the day the runner gains an attribute, and these
    tests then fail on a missing name, not on what they test."""
    from src.wiki import runner as wr

    args = dict(
        adapter=object(),
        stream=object(),
        lane_session=lambda: None,
        state_of=lambda: "running",
        hot_sets=dict,
        budget=lambda: None,
        drain_interval_s=0.0,
        sleep=lambda seconds: None,
    )
    args.update(kw)
    return wr.WikiLaneRunner(**args)


class _FakeRunner:
    """The lane runner with only what ``run_until_stopped``'s loop calls replaced."""

    def __init__(self):
        from src.wiki import runner as wr

        self.wr = wr
        self.runner = _bare_runner(sleep=self._sleep)
        r = self.runner
        r._sleeps = 0
        self.drained = 0
        r._should_stop = lambda: False
        r.revive_stream = lambda: None
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
    assert f.runner.drain_status()["paused"] == f.wr.DAMAGED, "the status must say why the loop is quiet"
    registry.retry(reason="the Wikipedia lane was started", files=("wiki",))
    assert f.runner.run_until_stopped(max_drains=2) == 2
    assert f.drained == 2 and f.runner.paused_reason is None


def test_a_corpus_latch_does_not_stop_the_wiki_loop(registry):
    f = _FakeRunner()
    _note(registry, FILE_CORPUS)
    assert f.runner.run_until_stopped(max_drains=2) == 2 and f.drained == 2


def _idle_runner(ran: list, on_index=None):
    """A lane runner with three fake tiers, enough for ``idle`` (the windows the drain loop gives them)."""

    class _Report:
        def as_dict(self):
            return {}

    class _Indexer:
        def index_for(self, seconds, *, should_stop):
            ran.append("index")
            if on_index:
                on_index()
            return _Report()

    class _Warm:
        def warm_for(self, seconds, *, should_stop):
            ran.append("warm")
            return _Report()

    class _Walker:
        def walk_for(self, seconds, *, should_stop):
            ran.append("walk")
            return _Report()

        def is_on(self):
            return True

    r = _bare_runner(indexer=_Indexer(), warm=_Warm(), walker=_Walker())
    r._should_stop = lambda: False
    return r


def test_a_latch_set_by_one_tier_stops_the_next_tier_in_the_same_window(registry):
    """The latch used to be read only at the top of the drain loop, so WARM and the walk kept writing for
    the rest of the window after the index window's read failed (the deep read, N5)."""
    ran: list = []
    _idle_runner(ran, on_index=lambda: _note(registry, "wiki")).idle(10.0)
    assert ran == ["index"], ran
    registry.retry(reason="reset between the two runs")
    ran.clear()
    _idle_runner(ran, on_index=lambda: _note(registry, FILE_CORPUS)).idle(10.0)
    assert ran == ["index", "warm", "walk"], "another file's latch does not stop the lane's tiers"


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


# --------------------------------------------------------------------------- #
#  wiring: the observers are on the engines, the operator's start retries, the seams admit
# --------------------------------------------------------------------------- #
def test_the_corpus_engine_and_every_lane_engine_carry_the_observer():
    from src.database import session

    key, listener = damage.attached(session.engine) or (None, None)
    assert key == FILE_CORPUS, "the corpus engine lost its damage observer"
    assert event.contains(session.engine, "handle_error", listener), "the observer is recorded but not live on the engine"
    # the lane engines are covered by test_a_lane_engine_names_its_own_file



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


def _all_three_latched(registry):
    for key in (FILE_CORPUS, "law", "wiki"):
        _note(registry, key)
    assert sorted(registry.state()["latched"]) == ["corpus", "law", "wiki"]


def test_the_operators_start_and_run_now_release_every_file_but_wikipedia(registry, monkeypatch):
    """Starting collection tries the corpus and the law file again; the Wikipedia lane has its own start,
    and a collection start that released its latch would un-pause a loop this button does not run."""
    import src.api.scheduler as api_sched

    fake = type("S", (), {"start": lambda self: True, "run_now": lambda self: True})()
    monkeypatch.setattr(api_sched, "get_scheduler", lambda: fake)
    monkeypatch.setattr(api_sched, "_status_payload", lambda: {})
    for call in (api_sched.scheduler_start, api_sched.scheduler_run_now):
        _all_three_latched(registry)
        call()
        assert registry.state()["latched"] == ["wiki"], call.__name__
        assert registry.state()["files"][FILE_CORPUS]["retries"] >= 1
        registry.retry(reason="reset between calls")


@pytest.mark.parametrize("lane_setting, latched_after", [("running", []), ("off", ["wiki"])])
def test_going_online_releases_what_starting_collection_releases_and_starts_the_lane(
    registry, monkeypatch, lane_setting, latched_after
):
    """The airplane button IS the operator starting collection (R117): it releases the corpus's and the law
    file's latch, and ALSO starts the Wikipedia lane, whose own start releases the Wikipedia file's (measured
    by the deep read: after airplane off and on nothing stayed latched). With the lane's setting off, the
    lane does not start and its file stays latched. The real ``start_wiki_lane`` runs here, not a stub."""
    import src.scheduler.runner as runner
    import src.wiki.service as wiki_service
    from src.api.system import set_network_mode
    from src.ingest import clear_kill_switch

    class _Sched:
        def start(self):
            return True

        def stop(self):
            return True

    class _Lane:
        streaming = False

        def start(self):
            return False  # no thread is wanted here

    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)
    monkeypatch.setattr(runner, "get_scheduler", lambda: _Sched())
    monkeypatch.setattr(wiki_service, "_state_of", lambda: lane_setting)
    monkeypatch.setattr(wiki_service, "_RUNNER", None)
    monkeypatch.setattr(wiki_service, "_build", lambda: _Lane())
    monkeypatch.setattr(wiki_service, "stop_wiki_lane", lambda: None)
    try:
        _all_three_latched(registry)
        set_network_mode({"online": True})
        assert registry.state()["latched"] == latched_after
    finally:
        clear_kill_switch()


def test_the_wikipedia_lanes_own_start_releases_its_file_and_nothing_else(registry, monkeypatch):
    from src.wiki import service

    started = {}

    class _Lane:
        streaming = False

        def start(self):
            started["yes"] = True
            return False  # no thread is wanted here

    monkeypatch.setattr(service, "_state_of", lambda: "running")
    monkeypatch.setattr(service, "_RUNNER", None)
    monkeypatch.setattr(service, "_build", lambda: _Lane())
    _all_three_latched(registry)
    service.start_wiki_lane()
    assert started.get("yes") and registry.state()["latched"] == [FILE_CORPUS, "law"]


def test_a_replaced_corpus_file_releases_the_corpus_latch_only(registry, tmp_path):
    """After a restore or a merge swaps the file in, the latch was about a file that no longer exists."""
    from src.backup import merge

    working, target = tmp_path / "working.db", tmp_path / "live.db"
    working.write_bytes(b"new")
    target.write_bytes(b"old")
    _all_three_latched(registry)
    merge._replace_live_corpus(working, target, wait_s=0.5)
    assert target.read_bytes() == b"new"
    assert registry.state()["latched"] == ["law", "wiki"]


def test_the_law_housekeeping_step_waits_on_its_own_file(registry, monkeypatch):
    """A damaged LAW file skips the law step of the housekeeping lane and nothing else in it."""
    import src.ingest.fetch_release as fr
    from src.scheduler import runner as rn

    ran: list[str] = []
    monkeypatch.setitem(rn._LANE_STEPS, "law", lambda s, f, st: ran.append("law") or {"ran": True})
    monkeypatch.setitem(rn._LANE_STEPS, "backfill", lambda s, f, st: ran.append("backfill") or {"ran": True})
    monkeypatch.setattr(rn, "_lane_pending_kinds", lambda settings: ["law", "backfill"])
    monkeypatch.setattr(rn, "_lane_kind_order", lambda kinds: list(kinds))
    shown: list[tuple] = []
    monkeypatch.setattr(rn, "_activity", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(fr, "wrap_fetcher", lambda f, s: f)
    _note(registry, "law")
    out = rn.run_housekeeping_lane(object(), object(), object())
    assert ran == ["backfill"], "the law step ran into a damaged law file, or its neighbour was stopped"
    assert out["law"] == {"skipped": "database-damaged"} and out["backfill"] == {"ran": True}
    assert any(a[0] == "lane:law" and a[1] == {"skipped": "database-damaged"} for a in shown), (
        "the skip must be drawn on the lane's activity line, or the page shows a lane that never ran as idle"
    )
    registry.retry(reason="test", files=("law",))
    ran.clear()
    out = rn.run_housekeeping_lane(object(), object(), object())
    assert ran == ["law", "backfill"]


# --------------------------------------------------------------------------- #
#  what the deep read of E1 found: behaviour that the first cut only asserted as source text
# --------------------------------------------------------------------------- #
GIB = 1 << 30


def _engaged_guard(monkeypatch, kind="wal", free=100 * GIB):
    """A storage guard that is genuinely engaged on injected readings (never the real drive)."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")  # tests/conftest.py turns the resource guard off
    fake = {"wal_bytes": 2 * GIB if kind == "wal" else 0, "disk_free_bytes": free if kind == "wal" else 1 << 20}

    def readings():
        return {"corpus_bytes": 10 * GIB, "disk_total_bytes": 500 * GIB, "lane_wal_bytes": {}, **fake}

    g = sg.StorageGuard(trip_after=2, resume_after=2, readings_fn=readings, drain_fn=lambda: {"busy": 1, "skipped": None})
    g.poll()
    g.poll()
    assert g.engaged and g.kind() == kind
    return g


def test_resume_anyway_is_refused_while_the_corpus_file_is_damaged(registry, monkeypatch):
    """The button is offered, and a click is answered, by ONE decision: a granted override that
    ``admit()`` then ignores would be a click that does nothing and a notice that lies."""
    g = _engaged_guard(monkeypatch)
    assert g.state()["override_refusal"] is None, "healthy file: the button is offered as before"
    _note(registry, FILE_CORPUS)
    st = g.state()
    assert st["override_refusal"] == {"kind": "damage", "frame": sg.FRAME_OVERRIDE_DAMAGE, "vars": {}}
    out = g.override(reason="test")
    assert out["overridden"] is False and out["refused"]["kind"] == "damage"
    assert g.state()["overridden"] is False
    assert g.admit() == "wal", "the storage limit still names itself first while both hold"


def test_an_override_granted_before_the_damage_does_not_bypass_it_and_is_not_told(registry, monkeypatch):
    g = _engaged_guard(monkeypatch)
    assert g.override(reason="test")["overridden"] is True
    assert g.admit() is None, "the override works while the file is whole"
    _note(registry, FILE_CORPUS)
    assert g.admit() == "damage", "collection must not write into a file the database called damaged"
    st = g.state()
    assert st["phase"] == sg.PHASE_DAMAGE, "the page must say what is stopping collection"
    assert st["notes"] == [] and st["kinds"] == [], "the override's own sentences ('you resumed') are not told"
    assert damage.FRAME_DATA in st["reason"] and "resumed" not in (st["reason"] or "").lower()
    assert st["overridden"] is True, "the override itself is still on record; only its sentences are not told"
    registry.retry(reason="test")
    assert g.admit() is None and g.state()["phase"] is None, "released: the override applies again"


def test_a_storage_phase_still_names_itself_while_both_hold(registry, monkeypatch):
    g = _engaged_guard(monkeypatch, kind="disk")
    _note(registry, FILE_CORPUS)
    assert g.state()["phase"] == sg.PHASE_DISK


def test_a_latch_never_releases_by_itself_however_long_it_stands(monkeypatch):
    """The file is not healed by the clock: a damaged file that is written to is the harm, and only a
    check (E2) or the operator can say it is not damaged."""
    now = {"t": 1_000_000.0}
    reg = DamageRegistry(path_fn=lambda: Path(os.devnull), clock=lambda: now["t"], mono=lambda: now["t"])
    monkeypatch.setattr(damage, "registry", reg)
    g = sg.StorageGuard(readings_fn=lambda: {})
    _note(reg)
    for hours in (1, 6, 24, 24 * 14):
        now["t"] += hours * 3600
        assert reg.latched(FILE_CORPUS) and g.admit() == "damage", f"released after {hours} h"
        assert reg.state()["latched"] == [FILE_CORPUS]
        assert g.state()["phase"] == sg.PHASE_DAMAGE
    reg.retry(reason="operator")
    assert not reg.latched(FILE_CORPUS)


def test_off_peak_maintenance_does_not_run_while_the_corpus_is_latched(registry):
    from src.scheduler.settings import SchedulerSettings

    sched = runner.BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings())
    _note(registry, FILE_CORPUS)
    assert sched._run_off_peak_maintenance() is False
    assert sched.status()["maintenance_skips"].get("database_damage") == 1
    # a lane's latch is not the corpus's: maintenance is a corpus writer and goes on
    registry.retry(reason="t")
    _note(registry, "wiki")
    sched2 = runner.BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings())
    sched2._run_off_peak_maintenance()
    assert "database_damage" not in sched2.status()["maintenance_skips"]


def test_the_pass_loop_waits_in_the_damage_phase_and_leaves_when_the_operator_retries(registry, monkeypatch):
    import time as _time

    from src.scheduler.settings import SchedulerSettings

    monkeypatch.setattr(sg, "storage_guard", sg.StorageGuard(readings_fn=lambda: {}))
    sched = runner.BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings())
    sched._storage_pause_poll_s = 0.02
    _note(registry, FILE_CORPUS)
    done = threading.Event()

    def _wait():
        sched._wait_while_storage_paused()
        done.set()

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    try:
        deadline = _time.monotonic() + 5.0
        while runner.current_phase() != "paused-damaged" and _time.monotonic() < deadline:
            _time.sleep(0.02)
        assert runner.current_phase() == "paused-damaged"
        assert not done.is_set() and sched.status()["next_run"] is None, "no stale countdown while paused"
        registry.retry(reason="operator started collection")
        assert done.wait(5.0), "the loop did not leave the pause when the latch was released"
        assert runner.current_phase() is None, "the phase must clear with the pause"
    finally:
        sched._stop.set()
        t.join(5.0)
        runner._phase_set(None)


def test_the_latch_is_set_before_the_record_and_the_record_does_not_hold_it_up(tmp_path, monkeypatch):
    """The failing statement's thread may hold the write gate and the drive may be the failing one: the
    latch (memory) is set first and read freely, and the record's write is waited for a bounded time."""
    import time as _time

    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.3)
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    release = threading.Event()
    entered = threading.Event()

    def _stuck_flush(doc):
        entered.set()
        release.wait(10.0)

    monkeypatch.setattr(reg, "_flush", _stuck_flush)
    result: dict = {}

    def _call():
        t0 = _time.monotonic()
        result["noted"] = _note(reg)
        result["waited"] = _time.monotonic() - t0

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    try:
        assert entered.wait(5.0), "the record was never written"
        t0 = _time.monotonic()
        assert reg.latched(FILE_CORPUS), "the latch waits on the drive"
        assert reg.notes() and reg.state()["latched"] == [FILE_CORPUS]
        assert _time.monotonic() - t0 < 0.2, "a reader of the latch queued behind the record's write"
        t.join(5.0)
        assert not t.is_alive() and result["noted"] is True
        assert result["waited"] < 3.0, "the failing statement was held by a hung drive"
    finally:
        release.set()


def test_a_second_corruption_error_that_reads_only_the_index_does_not_soften_a_data_incident(registry):
    _note(registry, FILE_CORPUS, statement="SELECT sum(length(content)) FROM articles")
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA
    _note(registry, FILE_CORPUS, statement="SELECT block FROM article_fts_data WHERE id = ?")
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA, "'your articles were not changed' after a data incident"
    assert registry.state()["files"][FILE_CORPUS]["scope"] == SCOPE_DATA
    registry.retry(reason="t")
    _note(registry, FILE_CORPUS, statement="SELECT block FROM article_fts_data WHERE id = ?")
    assert registry.notes()[0]["frame"] == damage.FRAME_SEARCH_INDEX, "a fresh latch takes its own scope"


def test_an_index_incident_followed_by_a_data_one_reads_as_data(registry):
    _note(registry, FILE_CORPUS, statement="SELECT block FROM article_fts_data WHERE id = ?")
    assert registry.notes()[0]["frame"] == damage.FRAME_SEARCH_INDEX
    _note(registry, FILE_CORPUS, statement="SELECT sum(length(content)) FROM articles")
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA, "the worst scope wins"
    _note(registry, FILE_CORPUS, statement="SELECT 1 FROM article_fts_docsize")
    assert registry.notes()[0]["frame"] == damage.FRAME_DATA, "...and stays"


def test_a_file_with_nothing_to_pause_is_named_but_is_not_a_paused_file(registry):
    _note(registry, "osm")
    st = registry.state()
    assert st["latched"] == [] and st["recorded_only"] == ["osm"]
    assert [n["frame"] for n in st["notes"]] == [damage.FRAME_RECORDED]
    _note(registry, FILE_CORPUS)
    assert registry.state()["latched"] == [FILE_CORPUS] and registry.state()["recorded_only"] == ["osm"]


def test_an_older_snapshot_never_overwrites_a_newer_one(tmp_path):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    _note(reg)
    with reg._lock:
        older = reg._doc_locked()
        reg._incidents[-1]["repeats"] = 5
        newer = reg._doc_locked()
    reg._flush(newer)
    reg._flush(older)  # the slower thread arrives last
    on_disk = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))
    assert on_disk["write_seq"] == newer["write_seq"] and on_disk["incidents"][-1]["repeats"] == 5


def test_the_record_keeps_a_route_template_never_a_raw_path(registry):
    from types import SimpleNamespace

    from src.database import pool_watch

    token = pool_watch.set_endpoint("GET /api/articles/123456/view", method="GET", scope=None)
    try:
        assert pool_watch.endpoint_template() is None
        _note(registry)
        assert registry.state(detail=True)["incidents"][0]["endpoint"] is None, "a raw path may carry an id"
        registry.retry(reason="t")
    finally:
        pool_watch.reset_endpoint(token)
    scope = {"route": SimpleNamespace(path="/api/articles/{id}/view")}
    token = pool_watch.set_endpoint("GET /api/articles/123456/view", method="GET", scope=scope)
    try:
        assert pool_watch.endpoint_template() == "GET /api/articles/{id}/view"
        _note(registry, statement="SELECT b FROM t")
        assert registry.state(detail=True)["incidents"][-1]["endpoint"] == "GET /api/articles/{id}/view"
    finally:
        pool_watch.reset_endpoint(token)


def test_the_unattended_start_releases_what_starting_collection_releases(registry, monkeypatch):
    """The unattended run is another way to start collecting (it goes online and starts the scheduler); the
    Wikipedia lane's file is released by the lane's own start, which this stubbed run does not make."""
    import contextlib

    import src.database.session as session_mod
    import src.scheduler.runner as runner
    from src.api import system as system_api
    from src.ingest import clear_kill_switch
    from src.monitoring import expedition

    class _Sched:
        def start(self):
            return True

        def is_running(self):
            return True

    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)
    monkeypatch.setattr(runner, "get_scheduler", lambda: _Sched())
    monkeypatch.setattr(session_mod, "session_scope", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(expedition, "qualification_safety", lambda db: {"safe": False, "reason": "t", "basis": "t"})
    monkeypatch.setattr(expedition, "arm", lambda **kw: {"started_at": "x"})
    monkeypatch.setattr(expedition, "record_event", lambda *a, **k: None)
    try:
        _all_three_latched(registry)
        system_api.unattended_start({})
        assert registry.state()["latched"] == ["wiki"]
    finally:
        clear_kill_switch()


def test_only_the_drivers_cause_chain_is_followed_never_the_context():
    corrupt = _fake_driver_error("database disk image is malformed", code=11)
    try:
        try:
            raise corrupt
        except Exception:  # noqa: BLE001
            raise TypeError("a bug in the handler") from None
    except TypeError as later:
        assert later.__context__ is corrupt and later.__cause__ is None
        assert not is_corruption(later), "an unrelated error raised while handling corruption is not corruption"
    try:
        try:
            raise corrupt
        except Exception as inner:  # noqa: BLE001
            raise RuntimeError("wrapped") from inner
    except RuntimeError as chained:
        assert is_corruption(chained), "an explicit 'raise ... from' is the cause and is followed"


@pytest.mark.parametrize(
    "statement",
    [
        "ATTACH DATABASE ? AS other",
        "attach ? as other",
        "  \n\tATTACH '/x/y.db' AS o",
        "ATTACH :p AS other",
    ],
)
def test_every_spelling_of_attach_is_skipped(registry, statement):
    ctx = type("Ctx", (), {})()
    ctx.original_exception = _fake_driver_error("database disk image is malformed", code=11)
    ctx.statement = statement
    registry.on_engine_error(ctx, FILE_CORPUS)
    assert not registry.latched(FILE_CORPUS), statement
    ctx.statement = "SELECT attached FROM t"
    registry.on_engine_error(ctx, FILE_CORPUS)
    assert registry.latched(FILE_CORPUS), "a statement that merely contains the word is not an ATTACH"


def test_the_read_snapshot_engine_names_the_corpus_file_when_it_meets_a_bad_page(damaged, registry):
    """The diagnostics routes read the whole corpus through this engine (the backup reads through raw drivers):
    the read most likely to meet a bad page must name it."""
    from src.database import read_snapshot

    path, _bad = damaged
    eng = read_snapshot._build_read_engine(f"sqlite:///{path}")
    try:
        found = damage.attached(eng)
        assert found is not None and found[0] == FILE_CORPUS
        with pytest.raises(Exception), eng.connect() as conn:  # noqa: B017 - the engine's own error type
            for lo in range(0, 3000, 100):
                conn.execute(
                    text("SELECT sum(length(content)) FROM articles WHERE id > :a AND id <= :b"),
                    {"a": lo, "b": lo + 100},
                ).scalar()
        assert registry.latched(FILE_CORPUS), "a bad page read through the snapshot engine was not named"
    finally:
        eng.dispose()


def test_an_incident_of_another_process_is_its_own_record_even_when_no_session_id_is_known(tmp_path, monkeypatch):
    """The session id can be unknown; two unknowns are not 'the same incident'. The process token is."""
    path = tmp_path / "rec.json"
    monkeypatch.setattr(damage, "_current_session_id", lambda: None)
    first = DamageRegistry(path_fn=lambda: path)
    _note(first)
    _note(first)  # same process: a repeat, counted
    assert len(first.state(detail=True)["incidents"]) == 1
    assert first.state(detail=True)["incidents"][0]["repeats"] == 1
    second = DamageRegistry(path_fn=lambda: path)  # a later process, same shape of failure
    _note(second)
    incidents = second.state(detail=True)["incidents"]
    assert len(incidents) == 2, "a new process's incident was swallowed as a repeat of the old one"
    assert incidents[0]["process"] != incidents[1]["process"]


def test_reading_the_record_never_happens_under_the_registrys_lock(tmp_path, monkeypatch):
    """``latched`` is read on every unit of collection work: the first read of a prior record (a file
    read, on a drive that may be the failing one) must not make it wait."""
    import time as _time

    path = tmp_path / "rec.json"
    path.write_text(json.dumps({"schema": 1, "files": {}, "incidents": []}), encoding="utf-8")
    release = threading.Event()
    entered = threading.Event()

    def _slow_path():
        entered.set()
        release.wait(10.0)
        return path

    reg = DamageRegistry(path_fn=_slow_path)
    t = threading.Thread(target=reg.state, daemon=True)
    t.start()
    try:
        assert entered.wait(5.0)
        t0 = _time.monotonic()
        assert reg.latched(FILE_CORPUS) is False
        assert _time.monotonic() - t0 < 0.2, "a latch read queued behind the record's first read"
    finally:
        release.set()
        t.join(5.0)


def test_a_relatch_after_the_operators_retry_is_logged_again(registry, caplog):
    import logging

    with caplog.at_level(logging.ERROR, logger="src.database.damage"):
        _note(registry)
        registry.retry(reason="t")
        _note(registry)  # the same incident, in the same process
    lines = [r for r in caplog.records if r.levelno == logging.ERROR and "database damage:" in r.getMessage()]
    assert len(lines) == 2, "the second latch was silent in the log"
    assert registry.state(detail=True)["incidents"][0]["repeats"] == 1, "...and the record counts it as a repeat"


def test_with_the_pause_off_the_log_does_not_say_the_writers_are_paused(registry, caplog, monkeypatch):
    import logging

    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    with caplog.at_level(logging.ERROR, logger="src.database.damage"):
        _note(registry)
    [line] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "OO_DAMAGE_GUARD=0" in line and "carry on" in line and "are paused" not in line


def test_the_method_names_the_blind_spot_of_a_damaged_first_page_encrypted_or_not():
    assert "BLIND SPOT" in damage.METHOD and "26" in damage.METHOD and "encrypted or not" in damage.METHOD


# --------------------------------------------------------------------------- #
#  the record path: one thread per job, the latch first, the write outside the lock
# --------------------------------------------------------------------------- #
def _settle(reg, timeout: float = 5.0) -> None:
    import time as _time

    end = _time.monotonic() + timeout
    while _time.monotonic() < end:
        with reg._lock:
            if not reg._jobs:
                return
        _time.sleep(0.01)
    raise AssertionError("a record job is still running")


def _record_threads() -> list:
    return [t for t in threading.enumerate() if t.name == "oo-damage-record" and t.is_alive()]


def _stuck_path(tmp_path, entered: threading.Event, release: threading.Event):
    def _path():
        entered.set()
        release.wait(10.0)
        return tmp_path / "rec.json"

    return _path


def test_a_write_that_hangs_holds_one_record_thread_not_one_per_failing_statement(tmp_path, monkeypatch):
    """Measured by the deep read: 50 repeats of one incident left 50 live record threads, each failing
    statement waiting the full bound."""
    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.05)
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    release = threading.Event()
    monkeypatch.setattr(reg, "_flush", lambda doc: release.wait(10.0))
    base = len(_record_threads())
    try:
        for _ in range(20):
            assert _note(reg)
        assert len(_record_threads()) - base <= 1, "a thread per failing statement"
        assert reg.latched(FILE_CORPUS)
    finally:
        release.set()
    _settle(reg)
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["repeats"] == 19


def test_a_gather_that_hangs_holds_one_record_thread_and_the_repeats_are_counted_when_it_ends(tmp_path, monkeypatch):
    """The stat on the failing drive hangs: nothing is recorded yet, so every repeat finds no incident. They
    wait on the one thread and are added to the incident's repeats when it ends."""
    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.05)
    release = threading.Event()

    def _stuck_sizes(path):
        release.wait(10.0)
        return {"file_bytes": None, "wal_bytes": None, "disk_free_bytes": None}

    monkeypatch.setattr(damage, "_sizes", _stuck_sizes)
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    base = len(_record_threads())
    try:
        for _ in range(20):
            assert _note(reg)
        assert len(_record_threads()) - base <= 1, "a thread per failing statement"
        assert reg.latched(FILE_CORPUS) and reg.state(detail=True)["incidents"] == []
    finally:
        release.set()
    _settle(reg)
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["repeats"] == 19 and reg.state()["files"][FILE_CORPUS]["incidents"] == 20


def test_a_write_that_fails_fast_is_tried_once_per_window_not_once_per_repeat(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "no-such-dir" / "rec.json")
    attempts: list[int] = []
    real = reg._flush
    monkeypatch.setattr(reg, "_flush", lambda doc: (attempts.append(1), real(doc))[1])
    for _ in range(50):
        assert _note(reg)
    _settle(reg)
    assert len(attempts) == 1, "a failing drive was asked again at every repeat"
    assert reg.state()["write_error"] and reg.latched(FILE_CORPUS)


def test_ten_threads_noting_one_new_incident_make_one_record(tmp_path):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    barrier = threading.Barrier(10)

    def _go():
        barrier.wait(5.0)
        _note(reg)

    threads = [threading.Thread(target=_go) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10.0)
    _settle(reg)
    st = reg.state(detail=True)
    assert len(st["incidents"]) == 1, "concurrent first failures made more than one record"
    assert st["incidents"][0]["repeats"] == 9 and st["files"][FILE_CORPUS]["incidents"] == 10


def test_a_record_thread_that_finds_its_incident_already_recorded_counts_a_repeat(tmp_path):
    """A record thread that ended just before another began finds the incident there: one record."""
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    found = {"code": 11, "name": "SQLITE_CORRUPT", "message": "m"}
    args = (FILE_CORPUS, found, "SELECT 1", SCOPE_DATA, "basis", "2026-10-06T00:00:00+00:00", None)
    reg._record_new(*args, thread_name="t", endpoint=None)
    reg._record_new(*args, thread_name="t", endpoint=None)
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["repeats"] == 1


def test_repeats_are_written_back_at_most_once_per_window(tmp_path, monkeypatch):
    clock = [1000.0]
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json", mono=lambda: clock[0])
    writes: list[int] = []
    real = reg._flush
    monkeypatch.setattr(reg, "_flush", lambda doc: (writes.append(doc["write_seq"]), real(doc))[1])
    _note(reg)
    assert len(writes) == 1, "the first record is written"
    for step in (1.0, 2.0):  # two repeats inside the window
        clock[0] = 1000.0 + step
        _note(reg)
    _settle(reg)
    assert len(writes) == 1, "a repeat inside the window was written back"
    clock[0] = 1000.0 + damage.FLUSH_EVERY_S + 1
    _note(reg)
    _settle(reg)
    assert len(writes) == 2, "the window passed and the repeats were never written"
    assert json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))["incidents"][0]["repeats"] == 3


def test_a_retry_that_arrives_while_the_record_is_being_written_is_written_too(tmp_path, monkeypatch):
    """What lands while a write-back is held is not lost: the thread snapshots again when it ends."""
    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.05)
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    _note(reg, FILE_CORPUS)
    _note(reg, "law")
    _settle(reg)
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []
    real = reg._flush

    def _held_first(doc):
        calls.append(doc["write_seq"])
        if len(calls) == 1:
            entered.set()
            release.wait(10.0)
        real(doc)

    monkeypatch.setattr(reg, "_flush", _held_first)
    try:
        reg.retry(reason="a", files=(FILE_CORPUS,))
        assert entered.wait(5.0)
        reg.retry(reason="b", files=("law",))  # the first write-back is still held
    finally:
        release.set()
    _settle(reg)
    assert len(calls) == 2, "the retry that arrived during the write was never written"
    files = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))["files"]
    assert files[FILE_CORPUS]["retries"] == 1 and files["law"]["retries"] == 1


def test_the_write_is_not_made_under_the_registrys_lock(tmp_path, monkeypatch):
    """``latched`` and ``state`` are read on every unit of collection work: a write that hangs inside the
    real ``_flush`` must not make them wait."""
    import time as _time

    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.2)
    entered, release = threading.Event(), threading.Event()
    path_fn = _stuck_path(tmp_path, entered, release)
    reg = DamageRegistry(path_fn=path_fn)
    reg._reset_for_tests(path_fn=path_fn)  # loaded: only the WRITE asks for the path
    t = threading.Thread(target=_note, args=(reg,), daemon=True)
    t.start()
    try:
        assert entered.wait(5.0), "the write never started"
        t0 = _time.monotonic()
        assert reg.latched(FILE_CORPUS) and reg.state()["latched"] == [FILE_CORPUS]
        assert _time.monotonic() - t0 < 0.1, "a reader of the latch queued behind the record's write"
    finally:
        release.set()
        t.join(5.0)


def test_the_latch_is_set_even_when_the_first_read_of_the_record_hangs(tmp_path, monkeypatch):
    """The first incident of a process used to read the earlier session's record on the failing thread BEFORE
    the latch: a hung drive then held both."""
    import time as _time

    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.2)
    entered, release = threading.Event(), threading.Event()
    reg = DamageRegistry(path_fn=_stuck_path(tmp_path, entered, release))  # not loaded yet
    t = threading.Thread(target=_note, args=(reg,), daemon=True)
    t.start()
    try:
        assert entered.wait(5.0), "the record thread never reached the read"
        t0 = _time.monotonic()
        assert reg.latched(FILE_CORPUS)
        assert _time.monotonic() - t0 < 0.1
        t.join(5.0)
        assert not t.is_alive(), "the failing statement was held longer than the bound"
    finally:
        release.set()


def test_the_history_of_an_earlier_session_joins_a_file_latched_before_the_record_was_read(tmp_path):
    path = tmp_path / "rec.json"
    first = "2026-01-01T00:00:00+00:00"
    path.write_text(
        json.dumps(
            {
                "schema": damage.SCHEMA,
                "files": {FILE_CORPUS: {"incidents": 4, "retries": 2, "first_at": first, "last_at": first, "scope": "data"}},
                "incidents": [],
            }
        ),
        encoding="utf-8",
    )
    reg = DamageRegistry(path_fn=lambda: path)
    _note(reg)  # the latch first; the record thread then reads the earlier session's record
    f = reg.state()["files"][FILE_CORPUS]
    assert f["incidents"] == 5 and f["retries"] == 2 and f["first_at"] == first
    assert reg.latched(FILE_CORPUS)


def test_a_failure_inside_the_record_thread_is_said_not_only_debug_logged(tmp_path, monkeypatch, caplog):
    import logging

    def _boom(path):
        raise RuntimeError("boom\nsecond")

    monkeypatch.setattr(damage, "_sizes", _boom)
    reg = DamageRegistry(path_fn=lambda: tmp_path / "rec.json")
    with caplog.at_level(logging.WARNING, logger="src.database.damage"):
        assert _note(reg)
        _settle(reg)
    assert reg.latched(FILE_CORPUS), "the latch does not depend on the record"
    assert reg.state()["write_error"] == "RuntimeError: boom"
    assert any(r.levelno == logging.WARNING and "could not be written" in r.getMessage() for r in caplog.records)


def test_starting_collection_releases_only_the_files_it_paused(registry):
    """A file that is only RECORDED (nothing to pause) is not 'released' by a start that never paused it."""
    for key in ("osm", FILE_CORPUS, "law", "wiki"):
        _note(registry, key)
    assert sorted(damage.retry_for_collection_start("t")) == [FILE_CORPUS, "law"]
    st = registry.state()
    assert st["latched"] == ["wiki"] and st["recorded_only"] == ["osm"]
    assert st["files"]["osm"]["retries"] == 0 and st["files"]["wiki"]["retries"] == 0


def test_a_courtesy_resume_after_a_backup_or_a_restore_leaves_a_damaged_file_paused(registry, monkeypatch):
    """The resume that puts collection back after an exclusive operation is not the operator trying again:
    only their own start releases a latch (a restore that un-paused a damaged file would be silent)."""
    import src.ingest as ingest
    import src.scheduler.runner as rn

    class _Sched:
        started = released = 0

        def start(self):
            self.started += 1
            return True

        def release_exclusive(self):
            self.released += 1

    sched = _Sched()
    monkeypatch.setattr(rn, "get_scheduler", lambda: sched)
    monkeypatch.setattr(rn, "exclusive_window_open", lambda: False)
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    _all_three_latched(registry)
    rn.resume_after_exclusive_operation(True)
    assert sched.started == 1 and sched.released == 1
    assert registry.state()["latched"] == [FILE_CORPUS, "law", "wiki"]


# --------------------------------------------------------------------------- #
#  the strings: twelve locales, honest about what E1 does
# --------------------------------------------------------------------------- #
def _keys():
    core = (ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    hover = re.search(r't\("(The database reported that it could not read part of one of your data files[^"]*)"\)', core)
    assert hover, "the damage hover moved -- re-anchor this test"
    return [
        damage.FRAME_DATA,
        damage.FRAME_SEARCH_INDEX,
        damage.FRAME_WIKI,
        damage.FRAME_LAW,
        damage.FRAME_RECORDED,
        damage.FRAME_PAUSE_OFF,
        sg.FRAME_OVERRIDE_DAMAGE,
        "Paused: the database reported damage",
        hover.group(1),
    ]


def test_every_damage_string_is_in_the_twelve_locales_translated():
    for p in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in _keys():
            assert k in d, f"{p.name} lacks {k[:50]!r}"
            if p.name != "en.json":
                assert d[k] != k, f"{p.name}: untranslated {k[:50]!r}"
    fr = json.loads((ROOT / "src/static/locales/fr.json").read_text(encoding="utf-8"))
    assert "la voie Wikipédia" in fr[damage.FRAME_WIKI], "French says 'voie' (feminine) for a lane"
