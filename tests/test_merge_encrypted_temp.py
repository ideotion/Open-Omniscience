"""An encrypted store's rows never reach a temp file during a merge (and what that costs).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FINDING (WAL, 2026-10-06, reproduced the same day): with SQLCipher and ``temp_store=FILE`` the
SORTER's spill file holds row text in the clear. The sorter writes through the VFS, not the pager, so
the codec never sees it, and ``merge_corpus`` used to set FILE on the working copy of an ENCRYPTED
store -- so any merge statement that sorted or built an index could leave plaintext rows in the temp
directory (a tmpfs on some machines, the disk on others). VACUUM's temporary database stayed encrypted
under FILE and is not part of this.

THE FIX has three halves and each is pinned below: an encrypted working copy holds its temp structures
in MEMORY and a plain one keeps FILE (its reason is RAM per inserted row, measured and recorded in
``test_merge_bounded.py``); a machine that cannot hold what MEMORY then needs is told so BEFORE a row
moves; and a plain store is never gated.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
sqlcipher3 = pytest.importorskip("sqlcipher3")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import src.database.connect as connect_mod  # noqa: E402
from src.backup import merge as merge_mod  # noqa: E402
from src.backup.merge import (  # noqa: E402
    MergeError,
    check_memory_for_encrypted_merge,
    merge_corpus,
)
from src.database.models import Article, Base, Source  # noqa: E402

_META = {
    "artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}
_KEY = "correct horse battery staple"
_MB = 1024 * 1024


def _plain_corpus(path: Path, *, articles: int, first: int = 0) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
        for i in range(first, first + articles):
            s.add(Article(
                url=f"https://wire.example/{i}", canonical_url=f"https://wire.example/{i}",
                source_id=src.id, title=f"t{i}", content=f"body {i}", hash=f"h{i:08d}", language="en",
            ))
        s.commit()
    engine.dispose()


@pytest.fixture
def encrypted_working_copy(tmp_path):
    """A working copy that is genuinely ENCRYPTED, opened through the app's own factory."""
    plain, enc = tmp_path / "plain.db", tmp_path / "working.db"
    _plain_corpus(plain, articles=2)
    connect_mod.reencrypt_plain_to(plain, enc, _KEY)
    plain.unlink()
    before = connect_mod.get_passphrase()
    connect_mod.set_passphrase(_KEY)
    try:
        yield enc
    finally:
        connect_mod.set_passphrase(before)


def _spy_pragmas(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = connect_mod.connect

    def spy(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        con = real(*a, **kw)
        con.set_trace_callback(seen.append)
        return con

    monkeypatch.setattr(connect_mod, "connect", spy)
    return seen


def _temp_pragmas(seen: list[str]) -> list[str]:
    return [s.lower() for s in seen if "temp_store" in s.lower()]


# --------------------------------------------------------------------------- #
#  which store gets which setting
# --------------------------------------------------------------------------- #
def test_an_encrypted_working_copy_holds_temp_structures_in_memory(
    tmp_path, encrypted_working_copy, monkeypatch
) -> None:
    seen = _spy_pragmas(monkeypatch)
    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", lambda *a, **k: None)
    staged = tmp_path / "staged.db"
    _plain_corpus(staged, articles=2, first=100)
    merge_corpus(staged, encrypted_working_copy, _META)
    pragmas = _temp_pragmas(seen)
    assert pragmas, "the merge never set temp_store on its own connection"
    assert any("memory" in p for p in pragmas) and not any("file" in p for p in pragmas), pragmas


def test_a_plain_working_copy_keeps_temp_storage_on_disk_and_is_never_gated(
    tmp_path, monkeypatch
) -> None:
    seen = _spy_pragmas(monkeypatch)

    def refuse(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("a plain working copy must never reach the encrypted-merge memory gate")

    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", refuse)
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _plain_corpus(working, articles=2)
    _plain_corpus(staged, articles=2, first=100)
    merge_corpus(staged, working, _META)
    pragmas = _temp_pragmas(seen)
    assert any("file" in p for p in pragmas) and not any("memory" in p for p in pragmas), pragmas


# --------------------------------------------------------------------------- #
#  the leak itself, and that the setting closes it
# --------------------------------------------------------------------------- #
def _spill_holds_rows(tmp_path: Path, temp_store: str) -> tuple[bool, int]:
    """Build an index over ~300,000 rows of an encrypted store with a 1 MiB cache and read every
    temp file the process holds open WHILE it runs. Returns (a marker was seen, files seen)."""
    work = tmp_path / f"spill-{temp_store}"
    work.mkdir()
    con = sqlcipher3.connect(str(work / "s.db"))
    try:
        con.execute(f"PRAGMA key='{_KEY}'")
        con.execute(f"PRAGMA temp_store={temp_store}")
        con.execute("PRAGMA cache_size=-1024")
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
        con.execute("BEGIN")
        con.executemany(
            "INSERT INTO t (a) VALUES (?)",
            [(f"MARKERROW{i:09d}-" + "x" * 40,) for i in range(300_000)],
        )
        con.execute("COMMIT")
        seen_files: set[str] = set()
        hit = [False]
        stop = threading.Event()
        pid = os.getpid()

        def watch() -> None:
            while not stop.is_set():
                for fd in glob.glob(f"/proc/{pid}/fd/*"):
                    try:
                        target = os.readlink(fd)
                    except OSError:
                        continue
                    # this process's own temp files only (SQLite unlinks them on open, so the link
                    # reads "(deleted)"); the database, its journal and /proc are not temp files
                    if "/proc" in target or target.endswith(("s.db", "-wal", "-shm", "-journal")):
                        continue
                    if "etilqs" not in target and "(deleted)" not in target:
                        continue
                    seen_files.add(target)
                    try:
                        with open(fd, "rb") as fh:
                            if b"MARKERROW" in fh.read():
                                hit[0] = True
                    except OSError:
                        pass
                time.sleep(0.005)

        th = threading.Thread(target=watch)
        th.start()
        try:
            con.execute("CREATE INDEX ix ON t (a DESC)")
            con.execute("SELECT a FROM t ORDER BY a || '' DESC").fetchall()  # a sort no index serves
        finally:
            stop.set()
            th.join()
        return hit[0], len(seen_files)
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc/<pid>/fd")
def test_the_sorters_spill_file_holds_plaintext_under_file_and_nothing_under_memory(tmp_path) -> None:
    """THE PREMISE, asserted rather than remembered (the same shape as the premise test in
    ``test_merge_bounded.py``): FILE spills row text in the clear on an encrypted store, MEMORY
    keeps the rows out of every temp file. If a future driver stops spilling in the clear the control goes
    red -- the cue to re-read this decision, not to delete the test."""
    leaked, files = _spill_holds_rows(tmp_path, "FILE")
    assert files and leaked, (
        "the control no longer leaks: temp_store=FILE did not put row text in a temp file on this "
        "driver, so the premise of the encrypted merge's MEMORY setting must be re-read"
    )
    leaked, _files = _spill_holds_rows(tmp_path, "MEMORY")
    assert not leaked, "an encrypted store's rows reached a temp file under temp_store=MEMORY"


# --------------------------------------------------------------------------- #
#  the gate
# --------------------------------------------------------------------------- #
def test_the_gate_asks_for_the_measured_need_plus_the_memory_guards_floor() -> None:
    need_mb = merge_mod._ENCRYPTED_TEMP_NEED_BYTES / _MB
    assert merge_mod._ENCRYPTED_TEMP_NEED_BYTES == 2 * merge_mod._MERGE_WINDOW_BYTES
    floor = 256.0
    # exactly enough passes, a megabyte short refuses
    check_memory_for_encrypted_merge(available_mb=need_mb + floor, floor_mb=floor)
    with pytest.raises(MergeError) as err:
        check_memory_for_encrypted_merge(available_mb=need_mb + floor - 1, floor_mb=floor)
    msg = str(err.value)
    assert msg.startswith("Not enough free memory to merge into an encrypted corpus: needs about ")
    assert "Nothing was written to your corpus." in msg
    # without the floor the same reading is enough: the floor is part of the need
    check_memory_for_encrypted_merge(available_mb=need_mb + floor - 1, floor_mb=0.0)


def test_an_unreadable_figure_is_never_a_refusal(monkeypatch) -> None:
    import src.database.maintenance as maintenance

    monkeypatch.setattr(maintenance, "_available_mb_now", lambda: None)
    check_memory_for_encrypted_merge()  # no figure, no refusal (the memory guard's own rule)


def test_the_gate_reads_the_live_guards_floor(monkeypatch) -> None:
    from src.scheduler import memguard

    monkeypatch.setattr(memguard.memory_guard, "avail_floor_mb", 1000.0)
    need_mb = merge_mod._ENCRYPTED_TEMP_NEED_BYTES / _MB
    with pytest.raises(MergeError):
        check_memory_for_encrypted_merge(available_mb=need_mb + 999)
    check_memory_for_encrypted_merge(available_mb=need_mb + 1000)


def test_incoming_rows_raise_the_need_by_the_largest_grouping_step_not_their_sum() -> None:
    base = merge_mod._ENCRYPTED_TEMP_NEED_BYTES
    rows = {"keywords": 6_900_000, "article_links": 4_200_000, "article_source_relationships": 0}
    per = merge_mod._ENCRYPTED_REP_BYTES_PER_ROW
    largest = max(rows["keywords"] * per["keywords"], rows["article_links"] * per["article_links"])
    expect = base + largest + 16 * sum(rows.values())
    expect_mb = expect / _MB
    check_memory_for_encrypted_merge(available_mb=expect_mb, floor_mb=0.0, incoming_rows=rows)
    with pytest.raises(MergeError):
        check_memory_for_encrypted_merge(available_mb=expect_mb - 1, floor_mb=0.0, incoming_rows=rows)
    # the steps run one after another: the SUM would have asked for more than this machine has
    summed = base + sum(rows[t] * per[t] for t in rows) + 16 * sum(rows.values())
    assert summed > expect
    # and the figure shown to the operator is the one the gate used
    with pytest.raises(MergeError) as err:
        check_memory_for_encrypted_merge(available_mb=1.0, floor_mb=0.0, incoming_rows=rows)
    from src.backup.folder_backup import human_bytes

    assert human_bytes(expect) in str(err.value)


def test_a_table_with_no_incoming_rows_adds_nothing() -> None:
    need_mb = merge_mod._ENCRYPTED_TEMP_NEED_BYTES / _MB
    check_memory_for_encrypted_merge(available_mb=need_mb, floor_mb=0.0, incoming_rows={})
    check_memory_for_encrypted_merge(
        available_mb=need_mb, floor_mb=0.0, incoming_rows={"keywords": 0, "article_links": 0}
    )


def _staged_with_keywords(path: Path, keywords: int) -> None:
    """A plain staged corpus holding ``keywords`` keyword rows, built where a SQLAlchemy URL can
    name it and then moved to ``path`` (a ``?`` or ``#`` would be read as URL syntax there)."""
    import sqlite3

    built = path.parent.parent / f"built-{path.parent.name.encode().hex()[:8]}.db"
    _plain_corpus(built, articles=1)
    con = sqlite3.connect(built)
    for i in range(keywords):
        con.execute(
            "INSERT INTO keywords (term, normalized_term, language) VALUES (?, ?, 'en')",
            (f"k{i}", f"k{i}"),
        )
    con.commit()
    con.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(path))


def _open_plain() -> object:
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.isolation_level = None
    return con


def test_incoming_rows_are_counted_through_the_merges_own_attach(tmp_path) -> None:
    staged = tmp_path / "d" / "staged.db"
    _staged_with_keywords(staged, 2)
    con = _open_plain()
    got = merge_mod._incoming_group_rows(con, staged)
    assert got["keywords"] == 2
    assert set(got) <= set(merge_mod._ENCRYPTED_REP_BYTES_PER_ROW)
    # the throwaway alias is gone again, so the merge's own attach of the same file still works
    assert "cnt" not in [r[1] for r in con.execute("PRAGMA database_list")]
    from src.database.connect import attach

    attach(con, staged, "inc")


def test_incoming_rows_are_counted_on_an_encrypted_connection_too(
    tmp_path, encrypted_working_copy
) -> None:
    staged = tmp_path / "d" / "staged.db"
    _staged_with_keywords(staged, 3)
    con = connect_mod.connect(encrypted_working_copy, check_same_thread=False)
    try:
        con.isolation_level = None
        assert merge_mod._incoming_group_rows(con, staged)["keywords"] == 3
        assert "cnt" not in [r[1] for r in con.execute("PRAGMA database_list")]
    finally:
        con.close()


def test_a_missing_table_counts_as_nothing_but_any_other_failure_refuses(tmp_path) -> None:
    import sqlite3

    # a table the artifact does not carry: a measured zero
    bare = tmp_path / "bare.db"
    c = sqlite3.connect(bare)
    c.execute("CREATE TABLE unrelated (x)")
    c.commit()
    c.close()
    assert merge_mod._incoming_group_rows(_open_plain(), bare) == {}
    # a file that cannot be read is a refusal that writes nothing, never a smaller need
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database" * 100)
    with pytest.raises(MergeError, match="Could not read the incoming file's row counts") as err:
        merge_mod._incoming_group_rows(_open_plain(), junk)
    assert "Nothing was written to your corpus." in str(err.value)
    # a missing file is a refusal too, and the count does not CREATE it (ATTACH would, and every
    # COUNT would then read as "no such table": an empty corpus nobody staged)
    absent = tmp_path / "absent.db"
    with pytest.raises(MergeError, match="Could not read the incoming file's row counts"):
        merge_mod._incoming_group_rows(_open_plain(), absent)
    assert not absent.exists()
    # only the message that names THIS table is a zero: a view over a table that is missing says
    # "no such table" about the OTHER table, and that is damage, not an empty corpus
    viewed = tmp_path / "viewed.db"
    c = sqlite3.connect(viewed)
    c.execute("CREATE VIEW keywords AS SELECT * FROM nonexistent")
    c.commit()
    c.close()
    with pytest.raises(MergeError, match="Could not read the incoming file's row counts"):
        merge_mod._incoming_group_rows(_open_plain(), viewed)


def test_a_count_that_fails_leaves_nothing_behind_and_quotes_nothing(tmp_path) -> None:
    """The passphrase rule, pinned: engine text can quote a path and, on a damaged encrypted page,
    more than that, so the refusal must carry only the exception class -- not in its message, its
    cause, its context or the traceback it prints -- and the throwaway alias must be gone."""
    import sqlite3
    import traceback

    secret_engine = "ENGINETEXT-4e1c disk image is malformed"
    staged = tmp_path / "PATHMARK-77b2" / "staged.db"
    _staged_with_keywords(staged, 1)

    class Boom(sqlite3.Connection):
        def execute(self, sql, *a, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
            if "COUNT(*)" in sql:
                raise sqlite3.DatabaseError(f"{secret_engine} {staged}")
            return super().execute(sql, *a, **kw)

    con = sqlite3.connect(":memory:", factory=Boom)
    con.isolation_level = None
    with pytest.raises(MergeError, match="Could not read the incoming file's row counts") as err:
        merge_mod._incoming_group_rows(con, staged)
    shown = "".join(traceback.format_exception(err.value))
    for needle in ("ENGINETEXT-4e1c", "PATHMARK-77b2", "malformed"):
        assert needle not in str(err.value), needle
        assert needle not in shown, needle
    assert "DatabaseError" in str(err.value)
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert "cnt" not in [r[1] for r in sqlite3.Connection.execute(con, "PRAGMA database_list")]


@pytest.mark.parametrize(
    "dirname",
    ["data#frag%41 dir"] + ([] if sys.platform == "win32" else ["data?x#frag%41 dir"]),
)
def test_a_staged_path_with_uri_characters_is_still_counted(tmp_path, dirname) -> None:
    staged = tmp_path / dirname / "staged.db"
    _staged_with_keywords(staged, 1)
    got = merge_mod._incoming_group_rows(_open_plain(), staged)
    assert got.get("keywords") == 1, "a path with ? # or % must not drop the count to nothing"


def test_merge_corpus_hands_the_incoming_counts_to_the_gate(
    tmp_path, encrypted_working_copy, monkeypatch
) -> None:
    seen: dict = {}

    def probe(**kw):  # noqa: ANN003, ANN202
        seen.update(kw)
        raise MergeError("stop here")

    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", probe)
    monkeypatch.setattr(merge_mod, "_incoming_group_rows", lambda _con, _p: {"keywords": 7})
    staged = tmp_path / "staged.db"
    _plain_corpus(staged, articles=1, first=100)
    with pytest.raises(MergeError, match="stop here"):
        merge_corpus(staged, encrypted_working_copy, _META)
    assert seen == {"incoming_rows": {"keywords": 7}}


def test_an_encrypted_merge_on_a_short_machine_is_refused_before_it_writes(
    tmp_path, encrypted_working_copy, monkeypatch
) -> None:
    import src.database.maintenance as maintenance

    monkeypatch.setattr(maintenance, "_available_mb_now", lambda: 10.0)
    opened: list = []
    real_connect = connect_mod.connect

    def recording(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        con = real_connect(*a, **kw)
        opened.append(con)
        return con

    monkeypatch.setattr(connect_mod, "connect", recording)
    staged = tmp_path / "staged.db"
    _plain_corpus(staged, articles=2, first=100)
    before = encrypted_working_copy.read_bytes()
    with pytest.raises(MergeError, match="Not enough free memory to merge into an encrypted corpus"):
        merge_corpus(staged, encrypted_working_copy, _META)
    assert encrypted_working_copy.read_bytes() == before, "a refused merge changed nothing"
    # the connection the refusal opened is closed: recorded by a spy, so it does not depend on
    # garbage-collection timing or on /proc
    assert opened, "the merge opened no connection"
    for con in opened:
        with pytest.raises(Exception):  # noqa: B017 - any driver's "closed" error
            con.execute("SELECT 1")


def test_a_plain_merge_runs_whatever_memory_is_reported(tmp_path, monkeypatch) -> None:
    import src.database.maintenance as maintenance

    monkeypatch.setattr(maintenance, "_available_mb_now", lambda: 1.0)
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _plain_corpus(working, articles=1)
    _plain_corpus(staged, articles=1, first=100)
    merge_corpus(staged, working, _META)  # does not raise


def test_the_refusal_sentence_is_read_back_by_the_page() -> None:
    """The page turns the server's English into a keyed frame (``ooServerText``); a reworded
    sentence would fall through unchanged in every locale, so the shape is pinned from the REAL
    refusal against the real page code. The translator is STUBBED to mark what it was handed: with
    the identity function the output equals the raw sentence whether or not the pattern matched,
    and the test could not fail."""
    import json
    import re
    import subprocess

    from tests.test_clickthrough_b13_leftovers import (
        app_js,
        array_literal,
        function_source,
        object_literal,
    )

    with pytest.raises(MergeError) as err:
        check_memory_for_encrypted_merge(available_mb=100.0, floor_mb=256.0)
    js = app_js()
    size_re = re.search(r'const _OO_SIZE_RE = "[^"\n]*";', js)
    assert size_re
    prog = "\n".join([
        "const OOI18N = { t: (x) => 'T:' + x,"
        " tf: (x, v) => 'FRAME<' + x + '>' + JSON.stringify(v) };",
        "const window = { OOI18N };",
        function_source(js, "_sizeText"),
        "const _OO_SPACE_WHAT = " + object_literal(js, "_OO_SPACE_WHAT") + ";",
        size_re.group(0),
        "const _OO_SPACE_RES = " + array_literal(js, "_OO_SPACE_RES") + ";",
        function_source(js, "ooServerText"),
        "process.stdout.write(JSON.stringify([" + json.dumps(str(err.value)) + ", 'unrelated']"
        ".map(ooServerText)));",
    ])
    proc = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out, other = json.loads(proc.stdout)
    assert other == "unrelated", "a sentence the page does not know comes back unchanged"
    frame, _, rest = out.partition(">")
    assert frame == (
        "FRAME<Not enough free memory to merge into an encrypted corpus: needs about {needed}, "
        "only {free} available. Close other programs and import again. Nothing was written to "
        "your corpus."
    ), out
    sizes = json.loads(rest)
    assert re.fullmatch(r"\S+\s*MB", sizes["needed"].strip("\u2068\u2069")) or "MB" in sizes["needed"]
    assert "100" in sizes["free"] and "MB" in sizes["free"], sizes
