"""Row 427: a plaintext staged corpus is sealed at a 16 KiB cipher page, read once first when it fits, with temp in memory.

What is pinned here:

- the sealed copy is written at :data:`staged_key.SEAL_PAGE_SIZE` whatever the plaintext's page size, its key says so,
  and every row reads back through the keyed open;
- the seal's own connection sets ``temp_store = MEMORY`` before the export, so an index sort never spills the plaintext's
  rows to the OS temp folder, whatever the wheel was compiled with;
- the read before the seal runs only when the file and a margin fit in the SMALLER of the machine's and the cgroup's
  available memory, and never when in doubt (no figure, an unreadable cgroup limit, ``OO_VALIDATE_WARM=0``);
- a failure of that read never fails the seal.
"""

from __future__ import annotations

import sqlite3
import types
from pathlib import Path

import pytest

pytest.importorskip("sqlcipher3")

from src.backup import sqlite_backup, staged_key  # noqa: E402
from src.config import cgroup_memory  # noqa: E402

_MB = 1024 * 1024


def _db(path: Path, n: int = 200, page_size: int = 4096) -> Path:
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size = {page_size}")
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
        "CREATE INDEX ix_articles_content ON articles(content);"
    )
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i}", f"{i:05d}" + "z" * 400) for i in range(n)])
    con.commit()
    con.close()
    return path


@pytest.mark.parametrize("source_page", [1024, 4096, 16384, 65536])
def test_the_sealed_copy_is_written_at_16_kib_whatever_the_source_page(tmp_path, source_page):
    p = _db(tmp_path / "s.db", page_size=source_page)
    expected = sqlite3.connect(p).execute("SELECT hash, content FROM articles ORDER BY id").fetchall()
    staged_key.seal_plaintext(p)
    try:
        assert staged_key.key_for(p).page_size == staged_key.SEAL_PAGE_SIZE == 16384
        c = staged_key.open_staged(p)
        try:
            assert int(c.execute("PRAGMA page_size").fetchone()[0]) == 16384
            assert c.execute("SELECT hash, content FROM articles ORDER BY id").fetchall() == expected
            assert c.execute("PRAGMA quick_check").fetchone() == ("ok",)
        finally:
            c.close()
    finally:
        staged_key.forget(p)


def test_the_seal_holds_its_temp_structures_in_memory(tmp_path, monkeypatch):
    """Set on the seal's own connection before the export runs: read from the connection's statement trace, which the seal
    turns off only for the keyed ATTACH."""
    real = staged_key._driver()
    seen: list[str] = []
    modes: list[int] = []

    def connect(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        con = real.connect(*a, **kw)
        con.set_trace_callback(seen.append)
        return con

    monkeypatch.setattr(staged_key, "_driver", lambda: types.SimpleNamespace(connect=connect, DatabaseError=real.DatabaseError))
    real_check = staged_key.check_staged_schema

    def check(con):  # noqa: ANN001, ANN202 - runs after the pragma and before the export
        modes.append(con.execute("PRAGMA temp_store").fetchone()[0])
        return real_check(con)

    monkeypatch.setattr(staged_key, "check_staged_schema", check)
    p = _db(tmp_path / "s.db")
    staged_key.seal_plaintext(p)
    staged_key.forget(p)
    lowered = [s.lower().replace(" ", "") for s in seen]
    assert "pragmatemp_store=memory" in lowered, seen
    assert modes == [2]
    assert not any("sqlcipher_export" in s for s in lowered), "the trace must be off before the keyed attach and the export"


@pytest.mark.parametrize(
    "size_mb, available_mb, source, expected",
    [
        (1000, 2000, "machine", True),          # 1,000 + 512 margin fits in 2,000
        (1000, 1511, "machine", False),         # one MB short of the margin
        (1000, 1512, "machine", True),          # exactly fits
        (4000, 4999, "cgroup limit", False),    # a quarter of the file (1,000) is the margin above 512
        (4000, 5000, "cgroup limit", True),
        (1000, None, "machine", False),         # no figure: in doubt
        (10, 100_000, "machine (a cgroup limit could not be read)", False),  # a limit exists and could not be read
        (0, 100_000, "machine", False),         # nothing to read
    ],
)
def test_the_read_before_the_seal_runs_only_when_the_file_and_a_margin_fit(size_mb, available_mb, source, expected):
    assert staged_key.preread_fits(size_mb * _MB, available_mb, source) is expected


def _calls(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(sqlite_backup, "_warm_sequentially", lambda path, should_stop=None: calls.append(Path(path)))
    return calls


def test_under_a_cgroup_limit_the_cgroup_figure_decides(tmp_path, monkeypatch):
    """A machine with memory to spare inside a cgroup that has little: the file is not read (the cache would count against
    the limit). The same machine without a limit reads it."""
    p = _db(tmp_path / "s.db")
    calls = _calls(monkeypatch)
    monkeypatch.setattr(cgroup_memory, "machine_memory_mb", lambda: (64_000.0, 60_000.0))
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb",
                        lambda *a, **k: {"available_mb": 300.0, "limit_mb": 4096.0, "unreadable": False})
    assert staged_key._preread_before_seal(p) is False and calls == []
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb",
                        lambda *a, **k: {"available_mb": None, "limit_mb": None, "unreadable": True})
    assert staged_key._preread_before_seal(p) is False and calls == [], "an unreadable limit is doubt, never room"
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb",
                        lambda *a, **k: {"available_mb": None, "limit_mb": None, "unreadable": False})
    assert staged_key._preread_before_seal(p) is True and calls == [p]


def test_the_switch_turns_the_read_off(tmp_path, monkeypatch):
    p = _db(tmp_path / "s.db")
    calls = _calls(monkeypatch)
    monkeypatch.setattr(cgroup_memory, "machine_memory_mb", lambda: (64_000.0, 60_000.0))
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb", lambda *a, **k: {"available_mb": None, "unreadable": False})
    monkeypatch.setenv("OO_VALIDATE_WARM", "0")
    assert staged_key._preread_before_seal(p) is False and calls == []


def test_the_seal_reads_first_when_it_fits_and_a_failed_read_never_fails_it(tmp_path, monkeypatch):
    monkeypatch.setattr(cgroup_memory, "machine_memory_mb", lambda: (64_000.0, 60_000.0))
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb", lambda *a, **k: {"available_mb": None, "unreadable": False})
    calls = _calls(monkeypatch)
    p = _db(tmp_path / "a.db")
    staged_key.seal_plaintext(p)
    staged_key.forget(p)
    assert calls == [p], "the plaintext is read before it is sealed"

    def boom(path, should_stop=None):  # noqa: ANN001, ANN202
        raise OSError("read error")

    monkeypatch.setattr(sqlite_backup, "_warm_sequentially", boom)
    q = _db(tmp_path / "b.db")
    staged_key.seal_plaintext(q)
    try:
        c = staged_key.open_staged(q)
        try:
            assert c.execute("SELECT count(*) FROM articles").fetchone() == (200,)
        finally:
            c.close()
    finally:
        staged_key.forget(q)


class _NewFds:
    """Every descriptor this process opens while the block runs, read from ``/proc/self/fd`` by a polling thread, with what it
    points at. A file opened with ``O_TMPFILE`` has no name but still shows here (``/tmp/#123 (deleted)``), and so does one
    unlinked right after it was opened, which is how SQLite makes its temp files."""

    def __init__(self) -> None:
        import threading

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self.seen: set[str] = set()
        self._before: set[tuple[str, str]] = set()

    @staticmethod
    def _snapshot() -> set[tuple[str, str]]:
        import os

        out: set[tuple[str, str]] = set()
        for fd in os.listdir("/proc/self/fd"):
            try:
                out.add((fd, os.readlink(f"/proc/self/fd/{fd}")))
            except OSError:
                continue
        return out

    def _poll(self) -> None:
        while not self._stop.is_set():
            for _fd, target in self._snapshot() - self._before:
                self.seen.add(target)

    def __enter__(self):  # noqa: ANN204
        self._before = self._snapshot()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self._stop.set()
        self._thread.join()


def _files_outside(seen: set[str], *allowed: Path) -> list[str]:
    roots = [str(a) for a in allowed]
    # /proc, /sys and /dev are not storage: the read before the seal looks at the cgroup's memory files under /sys.
    return sorted(t for t in seen if t.startswith("/") and not t.startswith(("/proc/", "/sys/", "/dev/"))
                  and not any(t.startswith(r) for r in roots))


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="reads this process's open files from /proc")
def test_on_disk_the_seal_opens_no_file_outside_its_own_staging(tmp_path):
    """R842 on disk: whatever the seal opens while it runs is the plaintext, its copy and their journals, all in the private
    staging folder; no temp file anywhere else, named or not (``O_TMPFILE``). The control shows the watcher sees one: the
    same driver, made to sort to a temp FILE, is caught."""
    rows = [(f"h{i}", f"{(i * 7919) % 20000:05d}" + "z" * 400) for i in range(20000)]
    ctl = tmp_path / "control"
    ctl.mkdir()
    con = staged_key._driver().connect(str(ctl / "c.db"))
    con.execute("CREATE TABLE t(h TEXT, c TEXT)")
    con.executemany("INSERT INTO t VALUES(?,?)", rows)
    con.commit()
    con.execute("PRAGMA temp_store = FILE")
    con.execute("PRAGMA cache_size = 10")
    with _NewFds() as control:
        con.execute("CREATE INDEX ix_c ON t(c)")
    con.close()
    if not _files_outside(control.seen, ctl):
        pytest.skip("this SQLite build keeps even a FILE temp store in memory, so the watcher has nothing to see here")

    stage = tmp_path / "stage"
    stage.mkdir()
    p = stage / "s.db"
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
                    "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
                    "CREATE INDEX ix_articles_content ON articles(content);")
    c.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", rows)
    c.commit()
    c.close()
    with _NewFds() as seal:
        staged_key.seal_plaintext(p)
    staged_key.forget(p)
    assert _files_outside(seal.seen, stage) == []
