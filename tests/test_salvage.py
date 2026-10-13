"""The salvage copy of a damaged file (damaged-database plan, slice E3, R121).

Every claim is made against REAL stores damaged the way a bad sector damages them (whole pages overwritten with
random bytes), on the plaintext driver and on SQLCipher, through the app's own factory, never against a hand-built
exception: a salvage that only passes on a stub proves nothing about the pages SQLite actually reads.

  * the damaged file is never written (its bytes, and any leftover log, are identical after);
  * every row that CAN be read is copied, byte for byte, with its row id; an unreadable id is counted, never invented;
  * a damaged INDEX or a damaged search-index page loses no row (both are rebuilt from the rows);
  * a failure that is not corruption (an out-of-memory, a disk error) aborts the copy instead of being read as "this
    row is unreadable", because that would drop good data without saying so;
  * the end of a table whose last id cannot be read is reported as a tail of unknown size, not as a number of rows;
  * the copy is the same kind of file (page size, encryption, user version) and the passphrase appears nowhere.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from pathlib import Path

import pytest

from src.database import salvage
from src.database.salvage import Salvage, SalvageFailed, SalvageRefused, SalvageStopped

from . import damaged_store_helpers as H


# --------------------------------------------------------------------------- #
#  stores
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def plain_pristine(tmp_path_factory) -> Path:
    """A real app-schema store (plaintext): 1,500 articles over 12 sources, full-text index and triggers."""
    path = tmp_path_factory.mktemp("salvage-plain") / "pristine.db"
    H.build_app_store(path, articles=1500)
    return path


@pytest.fixture(scope="module")
def enc_pristine(tmp_path_factory) -> Path:
    H.needs_sqlcipher()
    path = tmp_path_factory.mktemp("salvage-enc") / "pristine.db"
    H.build_app_store(path, articles=800, encrypted=True)
    return path


@pytest.fixture()
def key_held():
    """The process holds the passphrase for the length of the test (as an unlocked app does), and gives it back."""
    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase(H.KEY)
    yield H.KEY
    connect.set_passphrase(previous)


def _fresh(tmp_path: Path, pristine: Path, name: str = "damaged.db") -> Path:
    return H.copy_store(pristine, tmp_path / name)


def _salvage(src: Path, tmp_path: Path, **kw) -> tuple[dict, Path]:
    out = tmp_path / "out.partial"
    return Salvage(src, out, **kw).run(), out


def _entry(report: dict, table: str) -> dict:
    return next(t for t in report["tables"] if t["table"] == table)


def _plain_tables(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    finally:
        con.close()
    return [n for n in names if not n.startswith("article_fts") and not n.startswith("sqlite_")]


def _one_store(path: Path, ddl: list[str], rows: dict[str, list[tuple]], *, page: int = 1024, version: int = 0) -> None:
    """A small plaintext store of the test's own schema (``rows``: table -> tuples, inserted positionally)."""
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size={page}")
    for sql in ddl:
        con.execute(sql)
    for table, tuples in rows.items():
        if tuples:
            marks = ", ".join("?" for _ in tuples[0])
            con.executemany(f"INSERT INTO {table} VALUES ({marks})", tuples)
    if version:
        con.execute(f"PRAGMA user_version={version}")
    con.commit()
    con.close()


# --------------------------------------------------------------------------- #
#  an undamaged file is copied exactly
# --------------------------------------------------------------------------- #
def test_an_undamaged_file_is_copied_row_for_row(tmp_path, plain_pristine):
    before = H.sha(plain_pristine)
    report, out = _salvage(plain_pristine, tmp_path)
    assert H.sha(plain_pristine) == before, "the source is read, never written"
    assert report["encrypted"] is False and report["page_size"] == 4096
    for table in _plain_tables(plain_pristine):
        assert H.rows_of(out, table) == H.rows_of(plain_pristine, table), table
    assert all(t["unreadable_ids"] == 0 and not t.get("open_ended") for t in report["tables"])
    assert _entry(report, "articles")["kept"] == 1500
    assert report["search_index"]["documents"] == 1500, "the search index is rebuilt from the copied articles"
    clean, bad = salvage.check_copy(out)
    assert clean and bad == []
    # the copy is a live-ready file: write-ahead log mode, finished (no log left behind)
    con = H.open_store(out)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("SELECT count(*) FROM article_fts WHERE article_fts MATCH 'w1'").fetchone()[0] >= 1
    finally:
        con.close()


def test_page_size_user_version_and_auto_vacuum_are_kept(tmp_path):
    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    con.execute("PRAGMA page_size=8192")
    con.execute("PRAGMA auto_vacuum=2")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [(f"v{i}",) for i in range(50)])
    con.execute("PRAGMA user_version=42")
    con.commit()
    con.close()
    report, out = _salvage(src, tmp_path)
    assert report["user_version"] == 42 and report["page_size"] == 8192
    con = sqlite3.connect(out)
    try:
        assert con.execute("PRAGMA page_size").fetchone()[0] == 8192
        assert con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        assert con.execute("PRAGMA user_version").fetchone()[0] == 42
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  damaged leaf, interior and index pages (plaintext, pages found through dbstat)
# --------------------------------------------------------------------------- #
def _spread(pages: list[int], count: int) -> list[int]:
    step = max(1, len(pages) // (count + 1))
    return [pages[step * (i + 1)] for i in range(count)]


def test_damaged_leaf_pages_lose_only_their_rows(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    H.overwrite_pages(src, _spread(H.leaf_pages(src, "articles"), 3), H.PLAIN_PAGE)
    before = H.sha(src)
    readable = H.readable_ids(src)  # the slow honest answer: one id at a time
    assert 1400 < len(readable) < 1500, "the damage cost some rows and not the table"
    report, out = _salvage(src, tmp_path)
    assert H.sha(src) == before, "the damaged file is byte-identical after"
    entry = _entry(report, "articles")
    kept = H.rows_of(out, "articles")
    assert set(kept) == readable, "exactly the readable rows are copied"
    pristine = H.rows_of(plain_pristine, "articles")
    assert all(kept[i] == pristine[i] for i in kept), "and each is the same row"
    lost = set(pristine) - readable
    covered = {i for a, b in entry["unreadable_listed"] for i in range(a, b + 1)}
    assert lost <= covered, "every lost id is inside a reported unreadable range"
    assert entry["unreadable_ranges"] == 3 and entry["unreadable_ids"] >= len(lost)
    assert entry["highest_unreadable_id"] == max(max(b for _a, b in entry["unreadable_listed"]), 0)
    assert not entry.get("open_ended")
    clean, bad = salvage.check_copy(out)
    assert clean, bad
    assert report["search_index"]["documents"] == len(readable)


def test_a_damaged_interior_page_loses_the_rows_under_it_and_no_more(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    internal = H.leaf_pages(src, "articles", "internal")
    assert internal, "1,500 articles span more than a root page"
    # the lowest interior page that is not the root: pages are numbered from 1, the root is the table's rootpage
    con = sqlite3.connect(src)
    root = con.execute("SELECT rootpage FROM sqlite_master WHERE name='articles'").fetchone()[0]
    con.close()
    victims = [p for p in internal if p != root][:1] or [root]
    if victims == [root]:
        pytest.skip("the table has a single interior page, which is the root: nothing under it can be damaged alone")
    H.overwrite_pages(src, victims, H.PLAIN_PAGE)
    readable = H.readable_ids(src)
    assert 0 < len(readable) < 1500
    report, out = _salvage(src, tmp_path)
    assert set(H.rows_of(out, "articles")) == readable
    assert _entry(report, "articles")["unreadable_ids"] >= 1500 - len(readable)
    assert salvage.check_copy(out)[0]


def test_a_damaged_index_page_loses_no_row(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    con = sqlite3.connect(src)
    index = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='articles' AND sql IS NOT NULL ORDER BY name"
    ).fetchone()[0]
    con.close()
    pages = H.leaf_pages(src, index)
    H.overwrite_pages(src, _spread(pages, 2) if len(pages) > 3 else pages[:1], H.PLAIN_PAGE)
    assert not salvage.check_copy(src)[0], "the damaged file does not check clean"
    report, out = _salvage(src, tmp_path)
    assert _entry(report, "articles")["kept"] == 1500 and _entry(report, "articles")["unreadable_ids"] == 0
    assert H.rows_of(out, "articles") == H.rows_of(plain_pristine, "articles")
    assert salvage.check_copy(out)[0], "the index is created again from the schema, over good rows"
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (index,)).fetchone()
    finally:
        con.close()


def test_a_damaged_search_index_page_loses_no_article_and_the_index_is_rebuilt(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    pages = H.leaf_pages(src, "article_fts_data")
    assert pages
    H.overwrite_pages(src, _spread(pages, 2) if len(pages) > 3 else pages[:1], H.PLAIN_PAGE)
    report, out = _salvage(src, tmp_path)
    assert _entry(report, "articles")["kept"] == 1500
    assert report["search_index"]["documents"] == 1500
    assert salvage.check_copy(out)[0]
    con = H.open_store(out)
    try:
        assert con.execute("SELECT count(*) FROM article_fts WHERE article_fts MATCH 'w7'").fetchone()[0] > 0
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  a table whose last id cannot be read: an open-ended tail
# --------------------------------------------------------------------------- #
def test_an_unreadable_last_page_is_a_tail_of_unknown_size_not_a_huge_number(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    pages = H.leaf_pages(src, "articles")
    con = sqlite3.connect(src)
    last_leaf = con.execute(
        "SELECT pageno FROM dbstat WHERE name='articles' AND pagetype='leaf' ORDER BY path DESC LIMIT 1"
    ).fetchone()[0]
    con.close()
    assert last_leaf in pages
    H.overwrite_pages(src, [last_leaf], H.PLAIN_PAGE)
    # `max(id)` seeks the right-most leaf: with it damaged the table's end is not readable
    con = H.open_store(src)
    with pytest.raises(Exception) as caught:  # noqa: PT011 - the driver's own error type is not the point
        con.execute("SELECT max(id) FROM articles").fetchone()
    con.close()
    assert "malformed" in str(caught.value).lower()
    report, out = _salvage(src, tmp_path)
    entry = _entry(report, "articles")
    assert entry["open_ended"] is True and entry["unreadable_from"] > 1000
    assert entry["unreadable_ids"] < 100, "the unknown tail is not counted as rows (it is not 2**62 ids)"
    assert "not known" in entry["note"] and "could not be read" in entry["note"]
    kept = H.rows_of(out, "articles")
    assert set(kept) == set(range(1, entry["unreadable_from"])) or len(kept) > 1000
    assert salvage.check_copy(out)[0]


# --------------------------------------------------------------------------- #
#  the schema, row ids, counters, tables without row ids, orphans, text
# --------------------------------------------------------------------------- #
def test_an_unreadable_schema_refuses_and_creates_nothing(tmp_path):
    src = tmp_path / "src.db"
    ddl = [f"CREATE TABLE tbl_{i:03d}_with_a_long_name_to_fill_the_schema_pages (id INTEGER PRIMARY KEY, a TEXT, b TEXT, c TEXT)" for i in range(150)]
    _one_store(src, ddl, {}, page=512)
    con = sqlite3.connect(src)
    leaves = [p for p, t in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name IN ('sqlite_master', 'sqlite_schema')") if t == "leaf"]
    con.close()
    assert len(leaves) > 3
    H.overwrite_pages(src, leaves[1:3], 512)
    out = tmp_path / "out.partial"
    with pytest.raises(SalvageRefused) as caught:
        Salvage(src, out).run()
    assert caught.value.code == "schema-unreadable"
    assert not out.exists(), "a refused copy leaves no file behind"


def test_row_ids_survive_with_gaps_with_and_without_an_integer_primary_key(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE keyed (id INTEGER PRIMARY KEY, v TEXT)",
            "CREATE TABLE loose (a TEXT, b TEXT)",
            "CREATE TABLE named (rowid_ INTEGER, c TEXT)",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO keyed (id, v) VALUES (?, ?)", [(i * 3, f"k{i}") for i in range(1, 400)])
    con.executemany("INSERT INTO loose (rowid, a, b) VALUES (?, ?, ?)", [(i * 7 + 5, f"a{i}", "x" * 40) for i in range(400)])
    con.executemany("INSERT INTO named (rowid, rowid_, c) VALUES (?, ?, ?)", [(i * 2 + 1, i, f"c{i}") for i in range(300)])
    con.commit()
    con.close()
    _report, out = _salvage(src, tmp_path)
    a, b = sqlite3.connect(src), sqlite3.connect(out)
    try:
        for q in (
            "SELECT id, v FROM keyed ORDER BY id",
            "SELECT rowid, a, b FROM loose ORDER BY rowid",
            "SELECT rowid, rowid_, c FROM named ORDER BY rowid",
        ):
            assert a.execute(q).fetchall() == b.execute(q).fetchall(), q
    finally:
        a.close()
        b.close()


def test_a_row_id_column_whose_name_needs_quoting_is_copied_like_any_other(tmp_path):
    """The row-id column's name comes from the file's own schema and is put into the statements that read it: a space, a quote
    character or a reserved word in it must not break (or steer) the copy, so it is quoted like every other name."""
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            'CREATE TABLE t_space ("order id" INTEGER PRIMARY KEY, v TEXT)',
            'CREATE TABLE t_quote ("a""b" INTEGER PRIMARY KEY, v TEXT)',
            'CREATE TABLE t_word ("select" INTEGER PRIMARY KEY, v TEXT)',
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    for table, column in (("t_space", "order id"), ("t_quote", 'a"b'), ("t_word", "select")):
        quoted = '"' + column.replace('"', '""') + '"'
        con.executemany(f'INSERT INTO {table} ({quoted}, v) VALUES (?, ?)', [(i * 3, f"{table}{i}") for i in range(1, 300)])
    con.commit()
    con.close()
    report, out = _salvage(src, tmp_path)
    a, b = sqlite3.connect(src), sqlite3.connect(out)
    try:
        for table in ("t_space", "t_quote", "t_word"):
            assert a.execute(f"SELECT rowid, v FROM {table} ORDER BY rowid").fetchall() == b.execute(
                f"SELECT rowid, v FROM {table} ORDER BY rowid"
            ).fetchall(), table
            assert _entry(report, table)["kept"] == 299, table
    finally:
        a.close()
        b.close()


def test_an_autoincrement_counter_never_goes_back_below_a_lost_id(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        ["CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)"],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 60 + str(i),) for i in range(900)])
    con.commit()
    seq_before = con.execute("SELECT seq FROM sqlite_sequence WHERE name='t'").fetchone()[0]
    leaves = [p for p, kind in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name='t'") if kind == "leaf"]
    con.close()
    H.overwrite_pages(src, _spread(leaves, 2), 1024)
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT seq FROM sqlite_sequence WHERE name='t'").fetchone()[0] >= seq_before
        con.execute("INSERT INTO t (v) VALUES ('new')")
        assert con.execute("SELECT max(id) FROM t").fetchone()[0] > seq_before, "a new row never takes a lost row's id"
    finally:
        con.close()
    assert _entry(report, "t")["unreadable_ids"] > 0


def test_a_table_without_row_ids_is_copied_to_its_first_unreadable_page_and_says_so(tmp_path):
    src = tmp_path / "src.db"
    _one_store(src, ["CREATE TABLE d (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID"], {}, page=1024)
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO d VALUES (?, ?)", [(f"key{i:05d}", "y" * 50) for i in range(1500)])
    con.commit()
    leaves = [p for p, kind in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name='d'") if kind == "leaf"]
    con.close()
    H.overwrite_pages(src, [leaves[len(leaves) // 2]], 1024)
    report, out = _salvage(src, tmp_path)
    entry = _entry(report, "d")
    assert entry["truncated"] is True and 0 < entry["kept"] < 1500
    assert "could not be read" in entry["note"]
    con = sqlite3.connect(out)
    try:
        keys = [r[0] for r in con.execute("SELECT k FROM d ORDER BY k")]
    finally:
        con.close()
    assert keys == [f"key{i:05d}" for i in range(len(keys))], "what was copied is the unbroken start of the table"


def test_children_of_a_lost_parent_are_kept_and_counted_as_orphans(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT)",
            "CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id), v TEXT)",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO parent VALUES (?, ?)", [(i, "p" * 60 + str(i)) for i in range(1, 801)])
    con.executemany("INSERT INTO child VALUES (?, ?, ?)", [(i, 1 + (i * 7) % 800, f"c{i}") for i in range(1, 801)])
    con.commit()
    leaves = [p for p, kind in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name='parent'") if kind == "leaf"]
    con.close()
    H.overwrite_pages(src, _spread(leaves, 1), 1024)
    report, out = _salvage(src, tmp_path)
    assert _entry(report, "child")["kept"] == 800, "no child is dropped because its parent is gone"
    assert _entry(report, "parent")["unreadable_ids"] > 0
    assert report["orphans"]["child"] > 0
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800
    finally:
        con.close()


def _lose_leaves(src: Path, table: str, which: list[int], page: int = 1024) -> None:
    con = sqlite3.connect(src)
    try:
        leaves = [p for p, kind in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name=?", (table,)) if kind == "leaf"]
    finally:
        con.close()
    H.overwrite_pages(src, [leaves[i] for i in which], page)


def _tree_store(src: Path, *, parent_ddl: str, count: int = 800) -> None:
    _one_store(
        src,
        [
            parent_ddl,
            "CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id), v TEXT)",
            "CREATE TABLE grandchild (id INTEGER PRIMARY KEY, cid INTEGER REFERENCES child(id), v TEXT)",
            "CREATE TABLE merged_rows (table_name TEXT, row_id INTEGER, PRIMARY KEY (table_name, row_id))",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO parent (id, name) VALUES (?, ?)", [(i, "p" * 60 + str(i)) for i in range(1, count + 1)])
    con.executemany("INSERT INTO child VALUES (?, ?, ?)", [(i, i, f"c{i}") for i in range(1, count + 1)])
    con.executemany("INSERT INTO grandchild VALUES (?, ?, ?)", [(i, i, f"g{i}") for i in range(1, count + 1)])
    con.executemany("INSERT INTO merged_rows VALUES (?, ?)", [("parent", i) for i in range(1, count + 1)])
    con.commit()
    con.close()


def test_nothing_readable_is_removed_and_a_new_row_cannot_inherit_the_children_of_a_lost_tail(tmp_path):
    """The deep read of E3 (S6) found that a lost tail lets the next row saved take a lost id and claim the rows kept for it; the first fold
    removed those rows, which the user's R100 forbids (local data never gives way). Nothing readable is removed now: ONE stand-in row,
    marked as lost, takes the highest id any child refers to, so the next row saved gets a higher one, and every lost id below it is a
    gap (never handed out again). Rows keyed by (table, row id) are copied whole."""
    src = tmp_path / "src.db"
    _tree_store(src, parent_ddl="CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    _lose_leaves(src, "parent", [-1])  # the tail
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800, "a readable child was removed"
        assert con.execute("SELECT count(*) FROM grandchild").fetchone()[0] == 800, "a readable grandchild was removed"
        assert con.execute("SELECT count(*) FROM merged_rows").fetchone()[0] == 800, "a merge record was removed"
        real = con.execute("SELECT max(id) FROM parent WHERE name NOT LIKE '(lost%'").fetchone()[0]
        assert real < 800, "the test needs a lost tail"
        stand = con.execute("SELECT id, name FROM parent WHERE name LIKE '(lost%'").fetchall()
        assert stand == [(800, "(lost parent 800)")], stand
        assert report["stand_ins"] == {"parent": 800} and "stand-in row" in report["stand_ins_note"]
        lost = 800 - con.execute("SELECT count(*) FROM parent WHERE name NOT LIKE '(lost%'").fetchone()[0]
        assert report["orphans"] == {"child": lost}, (report.get("orphans"), lost)
        con.execute("INSERT INTO parent (name) VALUES ('new')")
        new_id = con.execute("SELECT max(id) FROM parent").fetchone()[0]
        assert new_id == 801
        assert con.execute("SELECT count(*) FROM child WHERE pid = ?", (new_id,)).fetchone()[0] == 0, "a new row inherited a lost row's child"
    finally:
        con.close()
    for key in ("orphans_removed", "orphans_removed_note", "orphans_removed_verdicts"):
        assert key not in report, f"{key} is the vocabulary of a removal, which no longer happens"
    assert "id_reuse_possible" not in report


def test_the_children_of_a_lost_gap_are_kept_and_counted_and_no_stand_in_is_needed_below_the_top(tmp_path):
    src = tmp_path / "src.db"
    _tree_store(src, parent_ddl="CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    _lose_leaves(src, "parent", [3])  # a leaf in the middle: ids above it are all there
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        top = con.execute("SELECT max(id) FROM parent").fetchone()[0]
        assert top == 800, "the test needs the tail to survive"
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800
        missing = 800 - con.execute("SELECT count(*) FROM parent").fetchone()[0]
        assert missing > 0 and report["orphans"] == {"child": missing}
    finally:
        con.close()
    assert "stand_ins" not in report, "a stand-in was written where nothing could be handed a lost id"


def test_an_autoincrement_parent_gets_its_counter_raised_and_no_stand_in_row(tmp_path):
    src = tmp_path / "src.db"
    _tree_store(src, parent_ddl="CREATE TABLE parent (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    # The counter the damaged file kept is below the highest id its children refer to (its own page was lost too, or never reached the
    # drive): the copy's own rule raises it to the highest row it READ, which is below the lost tail, so only the orphans can raise it.
    con = sqlite3.connect(src)
    con.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'parent'")
    con.commit()
    con.close()
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM parent WHERE name LIKE '(lost%'").fetchone()[0] == 0, "a stand-in was written beside a counter"
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800
        con.execute("INSERT INTO parent (name) VALUES ('new')")
        assert con.execute("SELECT max(id) FROM parent").fetchone()[0] >= 801, "the next row took a lost id"
    finally:
        con.close()
    assert "stand_ins" not in report and report["orphans"]["child"] > 0


def test_a_key_that_sets_null_on_delete_is_nulled_as_the_app_would_have_and_the_row_is_kept(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT NOT NULL)",
            "CREATE TABLE places (id INTEGER PRIMARY KEY, article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL, name TEXT)",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO articles VALUES (?, ?)", [(i, "t" * 60 + str(i)) for i in range(1, 801)])
    con.executemany("INSERT INTO places VALUES (?, ?, ?)", [(i, i, f"place {i}") for i in range(1, 801)])
    con.commit()
    con.close()
    _lose_leaves(src, "articles", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM places").fetchone()[0] == 800, "a place was removed"
        lost = 800 - con.execute("SELECT count(*) FROM articles").fetchone()[0]
        assert lost > 0
        nulled = con.execute("SELECT count(*) FROM places WHERE article_id IS NULL").fetchone()[0]
        assert nulled == lost and report["set_null"] == {"places": lost}
        assert con.execute("PRAGMA foreign_key_check").fetchall() == [], "a key still points at nothing"
        con.execute("INSERT INTO articles (title) VALUES ('new')")
        new_id = con.execute("SELECT max(id) FROM articles").fetchone()[0]
        assert con.execute("SELECT count(*) FROM places WHERE article_id = ?", (new_id,)).fetchone()[0] == 0
    finally:
        con.close()
    assert "orphans" not in report and "stand_ins" not in report


def test_a_table_of_measured_verdicts_whose_parent_was_lost_is_kept_and_named_in_the_report(tmp_path):
    """The verdict rule (R100: a verdict this install measured never gives way silently to a repair): the source qualification attempts
    and admission events carry a ``verdict`` column; they are KEPT and the report names the tables among the orphans that hold one."""
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
            "CREATE TABLE source_qualification_attempts (id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources(id), verdict TEXT)",
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources(id), body TEXT)",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO sources VALUES (?, ?)", [(i, "s" * 60 + str(i)) for i in range(1, 601)])
    con.executemany("INSERT INTO source_qualification_attempts VALUES (?, ?, ?)", [(i, i, "qualified") for i in range(1, 601)])
    con.executemany("INSERT INTO notes VALUES (?, ?, ?)", [(i, i, "n") for i in range(1, 601)])
    con.commit()
    con.close()
    _lose_leaves(src, "sources", [-1])
    report, out = _salvage(src, tmp_path)
    assert set(report["orphans"]) == {"source_qualification_attempts", "notes"}, report.get("orphans")
    assert report["orphans_verdict_tables"] == ["source_qualification_attempts"], report.get("orphans_verdict_tables")
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM source_qualification_attempts WHERE verdict = 'qualified'").fetchone()[0] == 600
    finally:
        con.close()


def test_a_stand_in_row_takes_a_value_of_the_right_kind_for_every_column_that_must_have_one(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE owners (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
            "CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL, n INTEGER NOT NULL, flag BOOLEAN NOT NULL, x REAL NOT NULL, "
            "at DATETIME NOT NULL, raw BLOB NOT NULL, js JSON NOT NULL, owner_id INTEGER NOT NULL REFERENCES owners(id), "
            "defaulted TEXT NOT NULL DEFAULT 'kept', note TEXT)",
            "CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id))",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO owners VALUES (?, ?)", [(i, f"o{i}") for i in range(3, 6)])
    con.executemany(
        "INSERT INTO parent (id, name, n, flag, x, at, raw, js, owner_id, note) VALUES (?, ?, 1, 1, 1.5, '2026-01-01 00:00:00.000000', x'01', '{}', 3, ?)",
        [(i, "p" * 60 + str(i), "z" * 40) for i in range(1, 501)],
    )
    con.executemany("INSERT INTO child VALUES (?, ?)", [(i, i) for i in range(1, 501)])
    con.commit()
    con.close()
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    assert "id_reuse_possible" not in report, report.get("id_reuse_possible")
    con = sqlite3.connect(out)
    try:
        row = con.execute("SELECT id, name, n, flag, x, at, raw, js, owner_id, defaulted, note FROM parent WHERE name LIKE '(lost%'").fetchone()
        assert row is not None and row[1] == f"(lost parent {row[0]})"
        # the key is a stand-in owner, marked as lost, above every real one (the real ones are 3..5): never a real owner's row
        assert row[2:9] == (0, 0, 0, "1970-01-01 00:00:00.000000", b"", "{}", 6), row
        assert row[9] == "kept" and row[10] is None, "a column with a default or without NOT NULL was given a value"
        assert con.execute("SELECT id, name FROM owners ORDER BY id").fetchall() == [(3, "o3"), (4, "o4"), (5, "o5"), (6, "(lost owners 6)")]
    finally:
        con.close()
    assert report["stand_ins"] == {"owners": 6, "parent": 500}


def test_a_stand_in_the_tables_own_constraints_refuse_is_named_and_nothing_is_removed(tmp_path):
    src = tmp_path / "src.db"
    _tree_store(src, parent_ddl="CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK (name NOT LIKE '(lost%'))")
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800 and con.execute("SELECT count(*) FROM grandchild").fetchone()[0] == 800
    finally:
        con.close()
    assert report["id_reuse_possible"] == ["parent"] and "stand_ins" not in report


# --------------------------------------------------------------------------- #
#  a stand-in is never attributed to real data (the delta read of E3 fold 2, B)
# --------------------------------------------------------------------------- #
def _owned_store(src: Path, *, table: str = "parent", parent_extra: str = "", owner_extra: str = "", with_owner_children: bool = False) -> None:
    """``owners`` (800 rows) <- ``table`` (800 rows, each with a NOT NULL ``owner_id``) <- ``child``; optionally ``owner_note`` <- ``owners``."""
    ddl = [
        f"CREATE TABLE owners (id INTEGER PRIMARY KEY, name TEXT NOT NULL{owner_extra})",
        f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES owners(id){parent_extra})",
        f"CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES {table}(id), v TEXT)",
        "CREATE TABLE owner_note (id INTEGER PRIMARY KEY, oid INTEGER REFERENCES owners(id), v TEXT)",
    ]
    _one_store(src, ddl, {}, page=1024)
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO owners VALUES (?, ?)", [(i, "o" * 60 + str(i)) for i in range(1, 801)])
    con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?)", [(i, "p" * 60 + str(i), (i % 5) + 1) for i in range(1, 801)])
    con.executemany("INSERT INTO child VALUES (?, ?, ?)", [(i, i, f"c{i}") for i in range(1, 801)])
    if with_owner_children:
        con.executemany("INSERT INTO owner_note VALUES (?, ?, ?)", [(i, i, f"n{i}") for i in range(1, 801)])
    con.commit()
    con.close()


def test_a_stand_in_whose_key_needs_a_parent_gets_a_stand_in_parent_marked_as_lost_never_a_real_one(tmp_path):
    src = tmp_path / "src.db"
    _owned_store(src)
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        stand = con.execute("SELECT id, owner_id FROM parent WHERE name LIKE '(lost%'").fetchall()
        assert [r[0] for r in stand] == [800]
        owner = con.execute("SELECT id, name FROM owners WHERE id = ?", (stand[0][1],)).fetchone()
        assert owner == (801, "(lost owners 801)"), owner  # above the highest owner there is (800), and marked
        assert con.execute("SELECT count(*) FROM owners WHERE name NOT LIKE '(lost%'").fetchone()[0] == 800, "a real owner was changed"
        assert con.execute("SELECT count(*) FROM parent p JOIN owners o ON o.id = p.owner_id WHERE p.name LIKE '(lost%' AND o.name NOT LIKE '(lost%'").fetchone()[0] == 0
        con.execute("INSERT INTO owners (name) VALUES ('new owner')")
        assert con.execute("SELECT max(id) FROM owners").fetchone()[0] == 802, "the stand-in owner did not hold its place"
    finally:
        con.close()
    assert report["stand_ins"] == {"owners": 801, "parent": 800}
    assert "id_reuse_possible" not in report
    assert "deleted" in report["stand_ins_note"] and "handed out again" in report["stand_ins_note"], "the note does not say what deleting a stand-in does"


def test_a_stand_in_made_for_a_key_is_above_every_id_an_orphan_refers_to_and_is_the_tables_only_stand_in(tmp_path):
    """The owners lost their tail too, so their own children (``owner_note``) are orphans and the owners need a stand-in of their own: the one made
    for the parent's key is above every lost owner id, so it is that stand-in, and the table gets no second one."""
    src = tmp_path / "src.db"
    _owned_store(src, with_owner_children=True)
    _lose_leaves(src, "parent", [-1])
    _lose_leaves(src, "owners", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        lost_owner_ids = [r[0] for r in con.execute("SELECT oid FROM owner_note WHERE oid NOT IN (SELECT id FROM owners)")]
        assert lost_owner_ids, "the test needs orphans of the owners"
        stand = con.execute("SELECT id FROM owners WHERE name LIKE '(lost%'").fetchall()
        assert len(stand) == 1 and stand[0][0] > max(lost_owner_ids), (stand, max(lost_owner_ids))
        assert con.execute("SELECT owner_id FROM parent WHERE name LIKE '(lost%'").fetchone()[0] == stand[0][0]
    finally:
        con.close()
    assert report["stand_ins"]["owners"] == stand[0][0]
    assert "id_reuse_possible" not in report


def test_a_stand_in_parent_made_before_its_tables_own_turn_is_above_every_orphan_id_and_is_the_only_one(tmp_path):
    """The same store with the child table named so that it is handled FIRST (``book`` sorts before ``owners``): the stand-in owner is made for
    the key, with the orphans of the owners still unseen by anything but the need table, so it must be placed above them itself, and the owners
    then need no second one."""
    src = tmp_path / "src.db"
    _owned_store(src, table="book", with_owner_children=True)
    _lose_leaves(src, "book", [-1])
    _lose_leaves(src, "owners", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        lost_owner_ids = [r[0] for r in con.execute("SELECT oid FROM owner_note WHERE oid NOT IN (SELECT id FROM owners)")]
        assert lost_owner_ids, "the test needs orphans of the owners"
        stand = con.execute("SELECT id FROM owners WHERE name LIKE '(lost%'").fetchall()
        assert len(stand) == 1, f"the owners got {len(stand)} stand-ins"
        assert stand[0][0] > max(lost_owner_ids), (stand, max(lost_owner_ids))
        assert con.execute("SELECT owner_id FROM book WHERE name LIKE '(lost%'").fetchone()[0] == stand[0][0]
    finally:
        con.close()
    assert report["stand_ins"]["owners"] == stand[0][0] and "id_reuse_possible" not in report


def test_a_stand_in_whose_parent_cannot_be_made_is_refused_and_leaves_no_stand_in_behind(tmp_path):
    src = tmp_path / "src.db"
    _owned_store(src, owner_extra=", CHECK (name NOT LIKE '(lost%')")
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM child").fetchone()[0] == 800, "a readable row was removed"
        assert con.execute("SELECT count(*) FROM parent WHERE name LIKE '(lost%'").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM owners").fetchone()[0] == 800
    finally:
        con.close()
    assert report["id_reuse_possible"] == ["parent"] and "stand_ins" not in report


def test_the_parents_a_refused_stand_in_made_are_taken_back(tmp_path):
    """The stand-in owner was made for the parent's key; the parent's own constraints then refused the row: the owner goes too."""
    src = tmp_path / "src.db"
    _owned_store(src, parent_extra=", CHECK (name NOT LIKE '(lost%')")
    _lose_leaves(src, "parent", [-1])
    report, out = _salvage(src, tmp_path)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM owners").fetchone()[0] == 800, "a stand-in owner nobody needed was left in the table"
    finally:
        con.close()
    assert report["id_reuse_possible"] == ["parent"] and "stand_ins" not in report


def test_keys_that_lead_back_to_the_table_being_made_do_not_loop_and_refuse_the_stand_in(tmp_path):
    src = tmp_path / "src.db"
    _one_store(
        src,
        [
            "CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER NOT NULL REFERENCES b(id), pad TEXT)",
            "CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER NOT NULL REFERENCES a(id), pad TEXT)",
            "CREATE TABLE child (id INTEGER PRIMARY KEY, aid INTEGER REFERENCES a(id))",
        ],
        {},
        page=1024,
    )
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO a VALUES (?, ?, ?)", [(i, i, "x" * 60) for i in range(1, 801)])
    con.executemany("INSERT INTO b VALUES (?, ?, ?)", [(i, i, "y" * 60) for i in range(1, 801)])
    con.executemany("INSERT INTO child VALUES (?, ?)", [(i, i) for i in range(1, 801)])
    con.commit()
    con.close()
    _lose_leaves(src, "a", [-1])
    report, out = _salvage(src, tmp_path)
    assert report["id_reuse_possible"] == ["a"] and "stand_ins" not in report
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT count(*) FROM b").fetchone()[0] == 800, "a stand-in was left in b"
    finally:
        con.close()


def test_a_stand_in_article_belongs_to_a_stand_in_source_and_the_search_finds_none(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO article_links (article_id, url, normalized_url) VALUES (?, ?, ?)", [(i, f"https://l.example/{i}", f"l.example/{i}") for i in range(1, 1501)])
    con.commit()
    con.close()
    H.overwrite_pages(src, H.leaf_pages(src, "articles")[-2:], H.PLAIN_PAGE)  # the newest articles
    report, out = _salvage(src, tmp_path)
    assert report["stand_ins"] == {"articles": 1500, "sources": 13}, report.get("stand_ins")
    con = H.open_store(out)
    try:
        stand = con.execute("SELECT id, source_id, title, content, url FROM articles WHERE url LIKE '(lost%'").fetchall()
        assert len(stand) == 1 and stand[0][0] == 1500 and stand[0][2] is None and stand[0][3] == "", stand
        source = con.execute("SELECT id, name FROM sources WHERE id = ?", (stand[0][1],)).fetchone()
        assert source[0] == 13 and source[1].startswith("(lost sources"), source
        assert con.execute("SELECT count(*) FROM sources WHERE name NOT LIKE '(lost%'").fetchone()[0] == 12
        assert con.execute("SELECT count(*) FROM articles a JOIN sources s ON s.id = a.source_id WHERE a.url LIKE '(lost%' AND s.name NOT LIKE '(lost%'").fetchone()[0] == 0
        for word in ("lost", "articles", "sources", "1500"):
            assert con.execute("SELECT count(*) FROM article_fts WHERE article_fts MATCH ?", (word,)).fetchone()[0] == 0, f"the search found the stand-in by {word!r}"
        con.execute("INSERT INTO article_fts(article_fts) VALUES ('integrity-check')")  # raises when the index and the table disagree
    finally:
        con.close()
    assert salvage.check_copy(out)[0]


def test_the_columns_the_stand_ins_leave_unindexed_are_the_columns_the_search_index_reads(plain_pristine):
    con = sqlite3.connect(plain_pristine)
    try:
        indexed = tuple(r[1] for r in con.execute("PRAGMA table_info(article_fts)"))
    finally:
        con.close()
    assert {"articles": indexed} == salvage._SEARCH_INDEXED


def test_text_that_is_not_utf8_is_kept_with_a_replacement_character_and_counted(tmp_path):
    src = tmp_path / "src.db"
    _one_store(src, ["CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"], {}, page=1024)
    con = sqlite3.connect(src)
    con.execute("INSERT INTO t VALUES (1, 'plain')")
    con.execute("INSERT INTO t VALUES (2, CAST(x'61ff62' AS TEXT))")
    con.commit()
    con.close()
    report, out = _salvage(src, tmp_path)
    assert report["replaced_text_values"] == 1
    con = sqlite3.connect(out)
    try:
        assert [r[0] for r in con.execute("SELECT v FROM t ORDER BY id")] == ["plain", "a�b"]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  what is NOT read as "unreadable", cancel, memory
# --------------------------------------------------------------------------- #
class _FailsOnTheArticleRead:
    """A connection that behaves as the real one except that the table read dies with a non-corruption error."""

    def __init__(self, real, error):
        self._real, self._error = real, error

    def execute(self, sql, *args):
        if 'FROM "articles" WHERE' in sql:
            raise self._error
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name in ("_real", "_error"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._real, name, value)


_MARK = "MARKER-77-bound-value"


def _driver_error(message: str, code: int | None = None, name: str | None = None) -> sqlite3.OperationalError:
    exc = sqlite3.OperationalError(message)
    if code is not None:
        exc.sqlite_errorcode = code  # type: ignore[attr-defined]
        exc.sqlite_errorname = name  # type: ignore[attr-defined]
    return exc


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        pytest.param(MemoryError(_MARK), "MemoryError", id="memory"),
        pytest.param(_driver_error(f"disk I/O error {_MARK}"), "OperationalError", id="disk-io-without-a-code"),
        pytest.param(_driver_error(f"disk I/O error {_MARK}", 10, "SQLITE_IOERR"), "OperationalError: SQLITE_IOERR", id="disk-io-with-a-code"),
        pytest.param(_driver_error(f"database is locked {_MARK}"), "OperationalError", id="locked-without-a-code"),
        pytest.param(_driver_error(f"database is locked {_MARK}", 5, "SQLITE_BUSY"), "OperationalError: SQLITE_BUSY", id="locked-with-a-code"),
        pytest.param(_driver_error(f"near \"{_MARK}\": syntax error", 1, "SQLITE_ERROR"), "OperationalError: SQLITE_ERROR", id="generic-with-a-code"),
    ],
)
def test_a_failure_that_is_not_corruption_aborts_instead_of_dropping_rows(tmp_path, plain_pristine, monkeypatch, error, reason):
    real_open = salvage._Reader.open

    def patched(self):
        real_open(self)
        self.con = _FailsOnTheArticleRead(self.con, error)

    monkeypatch.setattr(salvage._Reader, "open", patched)
    out = tmp_path / "out.partial"
    with pytest.raises(SalvageFailed) as caught:
        Salvage(plain_pristine, out).run()
    assert "articles" in caught.value.where
    # the reason is the driver's class and a fixed label, never a word of its text: the repair record writes it as it is
    assert caught.value.reason == reason
    assert _MARK not in caught.value.reason and _MARK not in str(caught.value) and _MARK not in repr(caught.value)


class _FailsOnCreateIndex:
    """The destination connection, except that building an index dies with the given error."""

    def __init__(self, real, error):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_error", error)

    def execute(self, sql, *args):
        if str(sql).lstrip().upper().startswith(("CREATE INDEX", "CREATE UNIQUE INDEX")):
            raise self._error
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


@pytest.mark.parametrize("budget", [None, 0], ids=["indexes-after-the-rows", "indexes-before-the-rows"])
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        pytest.param(_driver_error(f"index {_MARK} is corrupt"), "OperationalError", id="without-a-code"),
        pytest.param(_driver_error(f"database or disk is full {_MARK}", 13, "SQLITE_FULL"), "OperationalError: SQLITE_FULL", id="with-a-code"),
    ],
)
def test_a_failed_index_build_names_the_index_and_the_class_of_the_error_and_no_word_of_its_text(
    tmp_path, plain_pristine, monkeypatch, error, reason, budget
):
    """Both sites that build an index (before the rows when the sort would not fit in memory, and after them): ``SalvageFailed.reason`` is
    ``damage.failure_text``, and the repair record writes it as it is (``{where}: {reason}``)."""
    real_open = Salvage._open_target

    def patched(self):
        real_open(self)
        self.dst = _FailsOnCreateIndex(self.dst, error)

    monkeypatch.setattr(Salvage, "_open_target", patched)
    kwargs = {} if budget is None else {"sort_budget": lambda: budget}
    with pytest.raises(SalvageFailed) as caught:
        Salvage(plain_pristine, tmp_path / "out.partial", **kwargs).run()
    assert caught.value.where.startswith("index ") and _MARK not in caught.value.where
    assert caught.value.reason == reason
    assert _MARK not in str(caught.value) and _MARK not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__, "the chain is dropped: a traceback would print the error's words"


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        pytest.param(_driver_error(f"unable to open database file {_MARK}"), "the damaged file could not be opened for reading (OperationalError)", id="without-a-code"),
        pytest.param(
            _driver_error(f"unable to open database file {_MARK}", 14, "SQLITE_CANTOPEN"),
            "the damaged file could not be opened for reading (OperationalError: SQLITE_CANTOPEN)",
            id="with-a-code",
        ),
        pytest.param(OSError(13, f"Permission denied {_MARK}", f"/home/{_MARK}/store.db"), "the damaged file could not be opened for reading (PermissionError EACCES)", id="an-oserror-with-a-path"),
    ],
)
def test_a_file_that_cannot_be_opened_is_refused_with_the_class_and_no_word_of_the_errors_text(tmp_path, plain_pristine, monkeypatch, error, detail):
    def refusing(self):
        raise error

    monkeypatch.setattr(salvage._Reader, "open", refusing)
    with pytest.raises(SalvageRefused) as caught:
        Salvage(plain_pristine, tmp_path / "out.partial").run()
    assert caught.value.code == "cannot-open"
    assert caught.value.detail == detail
    assert _MARK not in str(caught.value) and _MARK not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_cancel_stops_the_copy_and_leaves_the_source_alone(tmp_path, plain_pristine):
    cancel = threading.Event()
    seen: list[dict] = []

    def progress(event):
        seen.append(event)
        if event.get("kept"):
            cancel.set()

    src = _fresh(tmp_path, plain_pristine, "src.db")
    before = H.sha(src)
    with pytest.raises(SalvageStopped):
        Salvage(src, tmp_path / "out.partial", cancel=cancel, progress=progress).run()
    assert H.sha(src) == before and seen


def test_a_progress_callback_that_raises_does_not_stop_the_copy(tmp_path, plain_pristine):
    def progress(_event):
        raise RuntimeError("a surface that cannot draw")

    report, out = _salvage(plain_pristine, tmp_path, progress=progress)
    assert _entry(report, "articles")["kept"] == 1500 and salvage.check_copy(out)[0]


def test_indexes_are_built_before_the_rows_when_the_sort_would_not_fit_in_memory(tmp_path, plain_pristine):
    report, out = _salvage(plain_pristine, tmp_path, sort_budget=lambda: 0)
    assert _entry(report, "articles")["indexes_before_rows"] is True
    con_a, con_b = sqlite3.connect(plain_pristine), sqlite3.connect(out)
    try:
        q = "SELECT type, name, tbl_name FROM sqlite_master WHERE type IN ('index', 'trigger') ORDER BY type, name"
        assert con_a.execute(q).fetchall() == con_b.execute(q).fetchall()
    finally:
        con_a.close()
        con_b.close()
    assert H.rows_of(out, "articles") == H.rows_of(plain_pristine, "articles")
    assert salvage.check_copy(out)[0]


def test_indexes_are_built_after_the_rows_when_memory_is_plentiful_or_unknown(tmp_path, plain_pristine):
    for budget in (lambda: 10**12, lambda: None):
        out = tmp_path / "out.partial"
        for side in ("", "-wal", "-shm"):
            Path(str(out) + side).unlink(missing_ok=True)
        report = Salvage(plain_pristine, out, sort_budget=budget).run()
        assert not _entry(report, "articles").get("indexes_before_rows")


def test_the_sort_costs_what_the_article_lists_own_build_says_it_costs():
    """Two builds of the same index must not disagree about its memory: the figure is the article list's, by name."""
    from src.database import article_indexes

    assert salvage.SORT_RAM_BYTES_PER_ROW == article_indexes.RAM_BYTES_PER_ARTICLE


def test_the_sort_budget_is_what_is_free_minus_the_guards_floor(monkeypatch):
    from src.database import article_indexes

    monkeypatch.setattr(article_indexes, "_available_ram_bytes", lambda: 5_000_000_000)
    monkeypatch.setattr(article_indexes, "_floor_bytes", lambda: 1_000_000_000)
    assert salvage.sort_budget_bytes() == 4_000_000_000
    monkeypatch.setattr(article_indexes, "_available_ram_bytes", lambda: 500)
    assert salvage.sort_budget_bytes() == 0, "never negative"
    monkeypatch.setattr(article_indexes, "_available_ram_bytes", lambda: None)
    assert salvage.sort_budget_bytes() is None, "an unreadable figure is not a refusal"


# --------------------------------------------------------------------------- #
#  check_copy
# --------------------------------------------------------------------------- #
def test_check_copy_names_the_damaged_table_of_a_damaged_file(tmp_path, plain_pristine):
    src = _fresh(tmp_path, plain_pristine)
    H.overwrite_pages(src, _spread(H.leaf_pages(src, "articles"), 2), H.PLAIN_PAGE)
    clean, bad = salvage.check_copy(src)
    assert clean is False and any(b["table"] == "articles" for b in bad)
    assert salvage.check_copy(plain_pristine) == (True, [])


def test_check_copy_stops_on_cancel(tmp_path, plain_pristine):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SalvageStopped):
        salvage.check_copy(plain_pristine, cancel=cancel)


# --------------------------------------------------------------------------- #
#  the encrypted path: the one every real operator uses
# --------------------------------------------------------------------------- #
def test_an_encrypted_file_with_damaged_pages_is_salvaged_into_an_encrypted_file(
    tmp_path, enc_pristine, key_held, caplog
):
    src = _fresh(tmp_path, enc_pristine)
    bad_pages = H.damage_encrypted_pages(src, count=3)
    before = H.sha(src)
    events: list[dict] = []
    with caplog.at_level(logging.DEBUG):
        report, out = _salvage(src, tmp_path, progress=events.append)
    assert H.sha(src) == before, "the damaged file is byte-identical after"
    assert report["encrypted"] is True and report["page_size"] == H.CIPHER_PAGE
    from src.database import connect

    assert connect.is_encrypted_file(out), "the copy is encrypted too"
    pristine = H.rows_of(enc_pristine, "articles")
    kept = H.rows_of(out, "articles")
    assert kept and all(kept[i] == pristine[i] for i in kept), "every copied row is the original row"
    entry = _entry(report, "articles")
    lost = set(pristine) - set(kept)
    covered = {i for a, b in entry.get("unreadable_listed", []) for i in range(a, b + 1)}
    if not entry.get("open_ended"):
        assert lost <= covered, "every id that did not come across is inside a reported unreadable range"
    assert len(kept) + max(entry["unreadable_ids"], 0) >= len(pristine) - (0 if not entry.get("open_ended") else len(pristine))
    assert report["reconnects"] >= 1, "a failed read is followed by a fresh connection (the poisoned one is never read again)"
    assert report["reconnects"] <= 6 + 3 * math.ceil(3 * math.log2(len(pristine) + 2)) * 4, "reconnects are bounded by the search"
    assert bad_pages
    assert salvage.check_copy(out)[0]
    # the passphrase is in no record, event or log of the run
    blob = json.dumps(report, default=str) + json.dumps(events, default=str) + caplog.text
    assert H.KEY not in blob
    # nothing readable was written in the clear: a title that is in every article is not in the copy's bytes
    assert b"Title 5 " not in out.read_bytes()
    # and the copy opens with the key only
    con = H.open_store(out, key=H.KEY)
    try:
        assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == len(kept)
        # the copy is written at the damaged file's own page size (16 KiB here), not the driver's default: a file of another
        # page size would open only by luck and its length would not be a whole number of pages
        assert int(con.execute("PRAGMA cipher_page_size").fetchone()[0]) == H.CIPHER_PAGE
    finally:
        con.close()
    assert out.stat().st_size % H.CIPHER_PAGE == 0
    with pytest.raises(Exception):  # noqa: B017, PT011 - a wrong key fails whichever way the driver words it
        con = H.open_store(out, key="not the passphrase at all")
        try:
            con.execute("SELECT count(*) FROM articles").fetchone()
        finally:
            con.close()


def test_an_encrypted_file_of_the_older_4k_page_size_is_copied_at_that_size(tmp_path, key_held):
    """The copy takes the damaged file's own page size, never the driver's default (16 KiB for a new file): a 4 KiB file
    copied into 16 KiB pages would still open here (the opener tries both) and would quietly be a different file, three
    times the size of a store the drive was sized for."""
    H.needs_sqlcipher()
    src = tmp_path / "old.db"
    H.build_app_store(src, articles=150, encrypted=True, cipher_page_size=4096)
    report, out = _salvage(src, tmp_path)
    assert report["encrypted"] is True and report["page_size"] == 4096
    con = H.open_store(out, key=H.KEY)
    try:
        assert int(con.execute("PRAGMA cipher_page_size").fetchone()[0]) == 4096
        assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == 150
    finally:
        con.close()
    assert salvage.check_copy(out)[0]


def test_an_undamaged_encrypted_file_is_copied_row_for_row(tmp_path, enc_pristine, key_held):
    report, out = _salvage(enc_pristine, tmp_path)
    for table in ("articles", "sources"):
        assert H.rows_of(out, table) == H.rows_of(enc_pristine, table)
    assert report["search_index"]["documents"] == 800
    assert all(t["unreadable_ids"] == 0 for t in report["tables"])
    assert salvage.check_copy(out)[0]


def test_a_failure_is_recorded_as_the_drivers_class_and_a_fixed_label_never_a_word_of_its_text():
    """Engine text into a record is class-only (the coordinator's ruling, which replaces the scrubbed first line the check of E3 asked for at item 4):
    the driver's error is read to classify it, and the record carries its class and a fixed label. A passphrase with a line break, a schema name,
    a statement and a bound value that the driver echoes are in none of it, scrubbed or not."""
    import sqlite3

    from src.database import connect, damage

    previous = connect.get_passphrase()
    connect.set_passphrase("first-half-of-the-key\nsecond-half-of-the-key")
    try:
        def failing(message: str, code: int | None = None, name: str | None = None):
            exc = sqlite3.OperationalError(message)
            if code is not None:
                exc.sqlite_errorcode = code
                exc.sqlite_errorname = name
            return exc

        marker = "MARKER-bound-value-77"
        wrapped = RuntimeError(f"[SQL: INSERT INTO t VALUES ('{marker}')]")
        wrapped.__cause__ = failing(f"could not open with the key first-half-of-the-key\nsecond-half-of-the-key, sorry {marker}", 14, "SQLITE_CANTOPEN")
        cases = {
            "an error with SQLite's own name": (wrapped, "OperationalError: SQLITE_CANTOPEN"),
            "the generic error": (failing(f"near \"{marker}\": syntax error", 1, "SQLITE_ERROR"), "OperationalError: SQLITE_ERROR"),
            "a driver without a name": (failing(f"disk is {marker}"), "OperationalError"),
            "a damaged page": (failing(f"database disk image is malformed {marker}", 11, "SQLITE_CORRUPT"), "OperationalError: " + damage.CORRUPT_IMAGE),
            "a damaged schema": (failing(f"malformed database schema (ix_{marker}) - near x", 11, "SQLITE_CORRUPT"), "OperationalError: " + damage.CORRUPT_SCHEMA),
            "not a driver's at all": (RuntimeError(f"could not open with the key first-half-of-the-key\nsecond-half-of-the-key, sorry {marker}"), "RuntimeError"),
            "an OSError": (OSError(28, f"no space {marker}", f"/home/{marker}/x"), "OSError ENOSPC"),
            # text where SQLite's constant name belongs (or a name longer than any) is not a name
            "text in the name": (failing(f"disk is {marker}", 1, f"SQLITE_ERROR {marker}"), "OperationalError"),
            "a name too long": (failing("x", 1, "SQLITE_" + "X" * 60), "OperationalError"),
        }
        for what, (exc, expected) in cases.items():
            text = damage.failure_text(exc)
            assert text == expected, (what, text)
            assert marker not in text and "first-half-of-the-key" not in text and "second-half-of-the-key" not in text, (what, text)
    finally:
        connect.set_passphrase(previous)


def test_a_refusal_carries_no_driver_error_in_its_traceback(tmp_path, enc_pristine):
    """The job runner writes a failed job with its traceback, cause and context included. A refusal that names the driver's error as its
    cause would put the engine's own line in that record; the refusal says the class and a fixed label and the chain is dropped."""
    import traceback

    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase("a different passphrase entirely")
    try:
        with pytest.raises(SalvageRefused) as caught:
            Salvage(enc_pristine, tmp_path / "out.partial").run()
    finally:
        connect.set_passphrase(previous)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    text = "".join(traceback.format_exception(caught.value))
    assert "sqlcipher3" not in text and "sqlite3" not in text and "not a database" not in text.lower(), text


def test_a_wrong_key_refuses_to_open_and_writes_nothing(tmp_path, enc_pristine):
    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase("a different passphrase entirely")
    try:
        out = tmp_path / "out.partial"
        with pytest.raises(SalvageRefused) as caught:
            Salvage(enc_pristine, out).run()
        assert caught.value.code == "cannot-open"
        assert "a different passphrase entirely" not in caught.value.detail
        assert not out.exists()
    finally:
        connect.set_passphrase(previous)
