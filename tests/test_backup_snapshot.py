"""A backup never carries a residual write-ahead log: it copies the corpus instead.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (2026-10-01 plan, ``wal-disk-pool/backup-wal-plan.md``). The volume backup used to
drain the log into the main file and, when a reader older than a later commit kept frames only in
the log, stream the ``-wal`` file as a second member. Restore had to fold it back in, and a store
whose log held growth was sized, and refused for lack of room, from the MAIN file's ``stat()``
which under-counts exactly that case (measured: main file 8,192 bytes, logical size 8,220,672).

WHAT THESE TESTS PIN, on real SQLite files behind the patched global engine (so the PRAGMAs are
the real ones and a fake cannot agree with itself):

  * the decision is the checkpoint's own row, not the size of the ``-wal`` file: a reader that
    started AFTER the last commit costs nothing, a reader OLDER than a later commit makes the
    backup copy the corpus through a read transaction, and neither writes a ``corpus-wal`` member;
  * the space check counts the store through the log (``page_count`` x ``page_size``) and refuses
    BEFORE a byte is copied, in the standard "needs about X, only Y free at Z" words;
  * a reader that appears after the sizing is handled late, inside the same pause window;
  * the copy takes the collection pause but NOT the write gate, and is consistent whatever
    commits while it runs; the facts in the manifest are the copy's own;
  * stopping: an encrypted copy is interrupted within seconds, a plaintext copy ends first, and in
    both the temporary directory is gone;
  * a crash's leftover copy is swept (dead owner at once, live owner never, unmarked by age) and
    a remembered destination is swept at boot on a thread of its own;
  * the clean path is today's sequence, byte for byte of call order, plus one free PASSIVE probe;
  * an archive written by the old code, with a ``corpus-wal`` member, still restores.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from src.backup import stream_backup as sb
from src.backup.artifact import BackupSpaceError
from src.backup.stream_backup import (
    CorpusSource,
    MemberFile,
    SnapshotCopy,
    read_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import VolumeStopped, load_manifest
from src.database import connect as connect_mod
from src.database import session as session_mod
from src.database import writer

VOL = 65536
ROW = "x" * 2000  # ~2 KB a row: a few hundred rows span many pages
BATCH = 25


# --------------------------------------------------------------------------- #
#  A real WAL store behind the patched global engine
# --------------------------------------------------------------------------- #
class Store:
    """The live store: a WAL SQLite file with auto-checkpointing OFF (so frames stay in the log
    until something asks), a pooled engine, and plain ``sqlite3`` readers that pin a snapshot."""

    def __init__(self, engine, db: Path):
        self.engine, self.db = engine, db
        self._readers: list[tuple[sqlite3.Connection, sqlite3.Cursor]] = []

    def commit(self, lo: int, hi: int) -> None:
        with self.engine.begin() as c:
            c.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS articles("
                "id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT)"
            )
            c.exec_driver_sql(
                "INSERT INTO articles(hash, content) VALUES (?, ?)",
                [(f"h{i:06d}", ROW) for i in range(lo, hi)],
            )

    def pin(self) -> None:
        """A reader whose snapshot is held open: it pins the log up to the last commit so far."""
        con = sqlite3.connect(self.db)
        cur = con.execute("SELECT id FROM articles")
        cur.fetchone()
        self._readers.append((con, cur))

    def release(self) -> None:
        for con, cur in self._readers:
            cur.close()
            con.close()
        self._readers.clear()

    def main_file_alone_rows(self, where: Path) -> int:
        """Rows in a copy of the MAIN file with no log beside it: what a naive copy would carry."""
        lone = where / "main-only.db"
        shutil.copyfile(self.db, lone)
        return _rows(lone)


def _rows(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return int(con.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
    except sqlite3.OperationalError:
        return 0
    finally:
        con.close()


@pytest.fixture
def live(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    db = data / "live.db"
    # A short busy timeout: a TRUNCATE against a pinned reader returns busy in milliseconds, and
    # the drain's own wait is shortened to match, so the suite does not spend 30 s a test.
    eng = create_engine(f"sqlite:///{db}", connect_args={"timeout": 0.05})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _rec):  # noqa: ANN001
        dbapi.execute("PRAGMA journal_mode=WAL")
        dbapi.execute("PRAGMA wal_autocheckpoint=0")

    monkeypatch.setattr(session_mod, "engine", eng)
    monkeypatch.setattr(sb, "_CHECKPOINT_WAIT_S", 0.3)
    store = Store(eng, db)
    store.commit(0, 200)
    yield store
    store.release()
    eng.dispose()


@pytest.fixture
def snap_calls(monkeypatch):
    """Every ``snapshot_preserving`` call, delegating to the real one."""
    calls: list[Path] = []
    real = connect_mod.snapshot_preserving

    def spy(src, dest, **kw):
        calls.append(Path(dest))
        return real(src, dest, **kw)

    monkeypatch.setattr(connect_mod, "snapshot_preserving", spy)
    return calls


def _members(tmp: Path) -> list[MemberFile]:
    a = tmp / "app_settings.json"
    a.write_text('{"k": 1}', encoding="utf-8")
    return [MemberFile("app_settings.json", "state", a)]


def _backup(tmp_path: Path, dest: Path | None = None, **kw):
    dest = dest or tmp_path / "dest"
    return write_stream_backup(
        dest, "pw", side_members=_members(tmp_path), volume_size=VOL, **kw
    )


def _restore(tmp_path: Path, dest: Path | None = None):
    staged = read_stream_backup(dest or tmp_path / "dest", "pw", staging_root=tmp_path / "st")
    return _rows(staged.corpus_path), staged


def _no_wal_member(dest: Path) -> None:
    man = load_manifest(dest)
    assert man["wal_member"] is None
    assert not [m for m in man["members"] if m["role"] == "corpus-wal"]


def _temps(dest: Path) -> list[Path]:
    return sorted(dest.glob(".bak-build-*"))


# --------------------------------------------------------------------------- #
#  1-2: the checkpoint's own row decides
# --------------------------------------------------------------------------- #
def test_a_reader_that_started_after_the_last_commit_costs_nothing(live, tmp_path, snap_calls):
    """MUTATION TARGET. This reader leaves a non-empty ``-wal`` and ``busy=1`` but every frame is
    already in the main file: the live file is streamed as it always was."""
    live.pin()
    assert (live.db.with_name("live.db-wal")).stat().st_size > 0
    s = _backup(tmp_path)
    assert snap_calls == [], "no copy: the main file alone was a complete image"
    assert s["snapshot_s"] is None and s["snapshot_bytes"] is None
    assert not [n for n in s["notes"] if "temporary copy" in n]
    _no_wal_member(tmp_path / "dest")
    n, _ = _restore(tmp_path)
    assert n == 200


def test_a_reader_older_than_a_later_commit_gets_a_copy_and_no_log_member(
    live, tmp_path, snap_calls
):
    """MUTATION TARGET. Frames 201-400 exist only in the log, so the main file is NOT the data:
    the corpus is copied through a read transaction, and the archive has every row and no log."""
    live.pin()
    live.commit(200, 400)
    assert live.main_file_alone_rows(tmp_path) < 400, "the fixture left the main file complete"
    s = _backup(tmp_path)
    assert len(snap_calls) == 1
    _no_wal_member(tmp_path / "dest")
    n, staged = _restore(tmp_path)
    assert n == 400
    assert staged.manifest["corpus"]["tables"]["articles"] == 400
    assert s["snapshot_bytes"] and s["snapshot_s"] is not None
    [note] = [n for n in s["notes"] if "temporary copy" in n]
    assert "incremental volume reuse does not apply" in note
    for word in ("reader", "holder", "process", "thread", "WAL", "checkpoint"):
        assert word not in note, f"the note names plumbing: {word!r}"
    assert _temps(tmp_path / "dest") == [], "the copy is gone after the run"


def test_the_decision_reads_the_row_not_the_size_of_the_log(live, monkeypatch):
    """The 428 KB ``-wal`` of a reader at the end of the log is not a reason to copy; an unreadable
    row with a non-empty log is not proof of anything either."""
    assert sb._wal_complete(live.db, (1, 104, 104)) is True
    assert sb._wal_complete(live.db, (1, 206, 104)) is False
    assert sb._wal_complete(live.db, (0, -1, -1)) is True, "not in WAL mode"
    live.pin()  # a non-empty -wal exists
    assert sb._wal_complete(live.db, None) is None, "no row and a non-empty log: unknown"
    assert sb._wal_complete(Path(str(live.db) + ".gone"), None) is True


# --------------------------------------------------------------------------- #
#  3: the space check counts the log
# --------------------------------------------------------------------------- #
def test_a_log_that_holds_growth_is_counted_and_refused_before_any_copy(
    live, tmp_path, snap_calls, monkeypatch
):
    """MUTATION TARGET. The main file can be a few KB while the log holds megabytes; sizing or
    refusing from ``stat()`` promised room the copy then did not have."""
    live.pin()
    live.commit(200, 1700)  # ~3 MB, all of it in the log
    main = live.db.stat().st_size
    logical = sb._logical_db_bytes(live.db)
    assert logical > main + 2_000_000, "the fixture's log holds no growth"

    seen: list[int] = []
    real = sb._preflight_snapshot
    monkeypatch.setattr(
        sb, "_preflight_snapshot", lambda d, c, s, p: (seen.append(c), real(d, c, s, p))[1]
    )
    # exactly the room a stat()-based size would have asked for, plus 1 MiB of slack
    free = main + sb._volumes_need(main, 0, 0.1) + main + (1 << 20)
    monkeypatch.setattr("src.backup.folder_backup.free_bytes", lambda _p: free)

    dest = tmp_path / "dest"
    with pytest.raises(BackupSpaceError) as ei:
        _backup(tmp_path, dest)
    msg = str(ei.value)
    assert "needs about" in msg and "free at" in msg
    assert "Free up space or choose another location" in msg
    assert "again" not in msg.lower()
    assert seen == [logical], "the check was sized from the store through the log"
    assert snap_calls == [], "refused before a byte of the copy was written"
    assert _temps(dest) == []


# --------------------------------------------------------------------------- #
#  4: a reader that appears after the sizing
# --------------------------------------------------------------------------- #
def _late_source(live, tmp_path, notes, **hooks):
    tmp_dir = tmp_path / "stage"
    tmp_dir.mkdir(exist_ok=True)
    src = sb._live_corpus_source(tmp_dir, True, notes, sb._LiveHooks(**hooks))
    assert src.snapshot is None, "the probe saw a complete image"
    live.pin()  # the reader appears AFTER the probe, with a later commit behind it
    live.commit(200, 400)
    return src


def test_a_reader_after_the_probe_is_copied_late_inside_the_freeze(live, tmp_path, monkeypatch):
    monkeypatch.setattr("src.backup.folder_backup.free_bytes", lambda _p: 1 << 40)
    notes: list[str] = []
    src = _late_source(live, tmp_path, notes)
    with src.freeze() as frozen:
        assert isinstance(frozen, SnapshotCopy)
        assert _rows(frozen.path) == 400
        assert frozen.gate_held_s >= 0.0 and frozen.seconds >= 0.0
    assert [n for n in notes if "temporary copy" in n]


def test_a_late_copy_with_no_room_refuses_in_the_standard_words(live, tmp_path, monkeypatch):
    """No "run it again": the sentence is the one a user already knows, from the same helper."""
    monkeypatch.setattr("src.backup.folder_backup.free_bytes", lambda _p: 1024)
    src = _late_source(live, tmp_path, [])
    with pytest.raises(BackupSpaceError) as ei, src.freeze():
        pytest.fail("the freeze yielded although there was no room for the copy")
    msg = str(ei.value)
    assert "needs about" in msg and "Free up space or choose another location" in msg
    assert "again" not in msg.lower()


# --------------------------------------------------------------------------- #
#  5: no write gate for the copy, and a consistent image whatever commits
# --------------------------------------------------------------------------- #
def test_the_copy_holds_no_write_gate_and_its_facts_are_the_copys_own(
    live, tmp_path, monkeypatch
):
    """MUTATION TARGET. The copy is one read transaction, so it needs no gate; holding one for
    minutes is the incident tests/test_export_pauses_collection.py records. A writer commits
    while the copy runs (a thread, batch after batch): the image is whole, and the manifest's
    counts and commitment are the image's, not the live store's."""
    live.pin()
    live.commit(200, 400)
    gate_seen: list[bool] = []
    stop = threading.Event()
    committed = [0]

    def writer_loop() -> None:
        i = 400
        while not stop.is_set():
            live.commit(i, i + BATCH)
            i += BATCH
            committed[0] += 1
            time.sleep(0.005)

    real = connect_mod.snapshot_preserving

    def spy(src, dest, **kw):
        gate_seen.append(writer.write_gate.held_by_current_thread())
        t = threading.Thread(target=writer_loop, daemon=True)
        t.start()
        try:
            time.sleep(0.05)  # let a few commits land first
            return real(src, dest, **kw)
        finally:
            stop.set()
            t.join(5)

    monkeypatch.setattr(connect_mod, "snapshot_preserving", spy)
    _backup(tmp_path)
    assert gate_seen == [False], "the write gate was held while the corpus was copied"
    assert committed[0] > 0, "the writer never ran: the test proved nothing"
    n, staged = _restore(tmp_path)
    assert n >= 400 and n % BATCH == 0, "the image tore a commit"
    assert staged.manifest["corpus"]["tables"]["articles"] == n
    assert staged.manifest["corpus"]["articles_commitment"]["n"] == n
    con = sqlite3.connect(staged.corpus_path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  6: stopping
# --------------------------------------------------------------------------- #
def test_a_stop_during_a_plaintext_copy_waits_for_it_and_leaves_nothing(
    live, tmp_path, monkeypatch
):
    """The plaintext copy is one backup-API step that cannot be interrupted (measured): the stop
    takes effect when it ends, and the temporary directory is gone."""
    live.pin()
    live.commit(200, 400)
    state = {"copied": False}
    real = connect_mod.snapshot_preserving

    def spy(src, dest, **kw):
        out = real(src, dest, **kw)
        state["copied"] = Path(dest).exists()
        return out

    monkeypatch.setattr(connect_mod, "snapshot_preserving", spy)
    dest = tmp_path / "dest"
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, should_stop=lambda: state["copied"])
    assert state["copied"], "the stop cut a plaintext copy short"
    assert _temps(dest) == []


def test_a_snapshot_stop_maps_to_a_volume_stop_and_tells_the_journal(
    live, tmp_path, monkeypatch
):
    live.pin()
    live.commit(200, 400)
    hooks_called: list[str] = []

    def stopped(_src, _dest, **_kw):
        raise connect_mod.SnapshotStopped("stop")

    monkeypatch.setattr(connect_mod, "snapshot_preserving", stopped)
    tmp_dir = tmp_path / "stage"
    tmp_dir.mkdir()
    monkeypatch.setattr("src.backup.folder_backup.free_bytes", lambda _p: 1 << 40)
    with pytest.raises(VolumeStopped):
        sb._take_snapshot(
            live.db,
            tmp_dir,
            "corpus.db",
            sb._LiveHooks(on_stopped=lambda: hooks_called.append("stopped")),
            gate_held_s=0.0,
        )
    assert hooks_called == ["stopped"]


@pytest.mark.skipif(not connect_mod.have_driver(), reason="sqlcipher3 not installed")
def test_an_encrypted_copy_is_interrupted_within_seconds_and_leaves_no_file(tmp_path, monkeypatch):
    """The encrypted copy is ONE long statement; the watcher interrupts it, the partial file is
    removed and ``SnapshotStopped`` is raised. The export is replaced by a statement that never
    ends on its own, so the test measures the interrupt, not a corpus."""
    pw = "correct horse battery staple"
    src = tmp_path / "live.db"
    con = connect_mod.connect(src, key=pw, check_same_thread=False)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, content TEXT)")
        con.execute("INSERT INTO articles(content) VALUES ('x')")
        con.commit()
    finally:
        con.close()
    before = connect_mod.get_passphrase()
    connect_mod.set_passphrase(pw)
    try:

        def endless(conn, _alias):
            conn.execute(
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
                "SELECT count(*) FROM c"
            ).fetchone()

        monkeypatch.setattr(connect_mod, "_export", endless)
        dest = tmp_path / "copy.db"
        t0 = time.monotonic()
        with pytest.raises(connect_mod.SnapshotStopped):
            connect_mod.snapshot_preserving(src, dest, should_stop=lambda: True)
        assert time.monotonic() - t0 < 10.0, "the stop was not honoured within seconds"
        assert not dest.exists(), "a partial copy was left to be mistaken for a copy"
    finally:
        connect_mod.set_passphrase(before)


# --------------------------------------------------------------------------- #
#  7: crash leftovers
# --------------------------------------------------------------------------- #
def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _leftover(root: Path, name: str, owner: dict | None, age_hours: float = 0.0) -> Path:
    d = root / name
    d.mkdir()
    (d / "corpus.db").write_bytes(b"x" * 64)
    if owner is not None:
        (d / ".owner.json").write_text(json.dumps(owner), encoding="utf-8")
    if age_hours:
        old = time.time() - age_hours * 3600
        for p in (d / "corpus.db", d / ".owner.json", d):
            if p.exists():
                os.utime(p, (old, old))
    return d


def test_a_dead_owners_copy_goes_at_once_a_live_owners_never(tmp_path):
    """MUTATION TARGET. A crashed backup left 8 to 40 GB on the user's drive and the 24 h age rule
    refused the retry for lack of the space it held. The owner decides: a dead process's dir goes
    now whatever its age; a live one's stays whatever its age; a recycled pid is a dead owner; a
    dir with no marker keeps the age rule."""
    root = tmp_path / "drive"
    root.mkdir()
    import psutil

    me = psutil.Process()
    dead = _leftover(root, ".bak-build-dead", {"pid": _dead_pid(), "started": 1.0})
    recycled = _leftover(root, ".bak-build-recycled", {"pid": me.pid, "started": 1.0})
    alive = _leftover(
        root,
        ".bak-build-alive",
        {"pid": me.pid, "started": round(me.create_time(), 3)},
        age_hours=72,
    )
    old_unmarked = _leftover(root, ".bak-build-old", None, age_hours=48)
    young_unmarked = _leftover(root, ".bak-build-young", None)
    volumes = root / "volumes.json"
    volumes.write_text("{}", encoding="utf-8")

    assert sb.sweep_stale_backup_temps(root) == 3
    assert not dead.exists() and not recycled.exists() and not old_unmarked.exists()
    assert alive.exists() and young_unmarked.exists() and volumes.exists()


def test_a_running_backup_marks_its_staging_with_its_owner(live, tmp_path, monkeypatch):
    seen: list[dict] = []
    real = sb._emit_member
    dest = tmp_path / "dest"

    def spy(st, mf):
        if not seen:
            for p in dest.glob(".bak-build-*/.owner.json"):
                seen.append(json.loads(p.read_text(encoding="utf-8")))
        return real(st, mf)

    monkeypatch.setattr(sb, "_emit_member", spy)
    _backup(tmp_path, dest)
    import psutil

    assert seen and seen[0]["pid"] == os.getpid()
    assert abs(seen[0]["started"] - psutil.Process().create_time()) < 1.0


def _sweep_remembered_now() -> None:
    """The boot sweep is one-at-a-time on a thread of its own; wait for a running one, then run."""
    for _ in range(100):
        t = sb.sweep_remembered_destinations_in_background()
        if t is not None:
            t.join(10)
            assert not t.is_alive()
            return
        time.sleep(0.1)
    pytest.fail("a remembered-destination sweep never finished")


def test_a_remembered_destination_is_swept_at_boot_on_its_own_thread(live, tmp_path, monkeypatch):
    """A drive that was given a copy and crashed is cleaned at the next boot even if the user
    never exports there again; an unmounted drive is skipped and kept for a later boot."""
    drive = tmp_path / "drive"
    drive.mkdir()
    gone = tmp_path / "unmounted"  # never created: not mounted now
    sb.remember_snapshot_destination(gone)
    sb.remember_snapshot_destination(drive)
    leftover = _leftover(drive, ".bak-build-crash", {"pid": _dead_pid(), "started": 1.0})

    main = threading.current_thread()
    ran_on: list[threading.Thread] = []
    real = sb.sweep_remembered_destinations

    def spy():
        ran_on.append(threading.current_thread())
        return real()

    monkeypatch.setattr(sb, "sweep_remembered_destinations", spy)
    _sweep_remembered_now()
    assert ran_on and ran_on[0] is not main and ran_on[0].name == "oo-backup-remembered-sweep"
    assert not leftover.exists()
    kept = json.loads((Path(os.environ["OO_DATA_DIR"]) / sb._DESTS_FILE).read_text("utf-8"))
    assert str(gone.resolve()) in kept, "an unmounted drive must be looked at again next boot"
    assert str(drive.resolve()) not in kept, "a drive that holds nothing more is forgotten"


def test_the_boot_janitor_starts_the_remembered_sweep(live, monkeypatch):
    started: list[int] = []
    monkeypatch.setattr(
        sb, "sweep_remembered_destinations_in_background", lambda: started.append(1)
    )
    from src.backup.artifact import cleanup_stale_staging

    cleanup_stale_staging()
    assert started == [1]


def test_the_remembered_destinations_are_bounded(live):
    for i in range(sb._DESTS_KEEP + 5):
        sb.remember_snapshot_destination(Path(f"/nowhere/{i}"))
    kept = json.loads((Path(os.environ["OO_DATA_DIR"]) / sb._DESTS_FILE).read_text("utf-8"))
    assert len(kept) == sb._DESTS_KEEP
    assert kept[0].endswith(str(sb._DESTS_KEEP + 4)), "newest first"


# --------------------------------------------------------------------------- #
#  8: the clean path is today's sequence plus one free probe
# --------------------------------------------------------------------------- #
@pytest.fixture
def seq(monkeypatch, tmp_path):
    """The call order of the pause, the gate, the drain and the copy, with the checkpoint's
    answer under the test's control (``rig['row']`` for the probe, ``rig['drains']`` for what each
    drain finds)."""
    log: list[str] = []
    rig: dict = {"row": (0, 10, 10), "drains": []}
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    store = tmp_path / "corpus.db"
    store.write_bytes(b"x" * 1024)

    import src.backup.sqlite_backup as sqlite_backup
    import src.scheduler.runner as runner

    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: store)
    monkeypatch.setattr(connect_mod, "is_encrypted_file", lambda _p: False)

    @contextmanager
    def window(timeout: float = 10.0):
        log.append("pause")
        try:
            yield True
        finally:
            log.append("resume")

    @contextmanager
    def lock(timeout=None):
        log.append("gate")
        try:
            yield
        finally:
            log.append("ungate")

    monkeypatch.setattr(runner, "exclusive_window", window)
    monkeypatch.setattr(writer, "write_lock", lock)
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    monkeypatch.setattr(sb, "_wal_row", lambda mode: rig["row"])
    monkeypatch.setattr(
        sb, "_drain_wal", lambda _p: log.append("drain") or rig["drains"].pop(0)
    )
    monkeypatch.setattr(sb, "_logical_db_bytes", lambda _p: 1024)
    monkeypatch.setattr("src.backup.folder_backup.free_bytes", lambda _p: 1 << 40)

    def fake_snapshot(_src, dest, **_kw):
        log.append("snapshot")
        Path(dest).write_bytes(b"x")

    monkeypatch.setattr(connect_mod, "snapshot_preserving", fake_snapshot)
    return log, rig, tmp_path


def test_a_complete_probe_is_todays_sequence_with_no_copy_and_no_second_pause(seq):
    log, rig, tmp = seq
    rig["drains"] = [None]
    src = sb._live_corpus_source(tmp / "stage", True, [])
    assert src.snapshot is None and log == [], "the probe pauses nothing and takes no gate"
    with src.freeze() as frozen:
        assert frozen is None
        log.append("copy")
    assert log == ["pause", "gate", "drain", "copy", "ungate", "resume"]


def test_a_reader_that_left_by_the_early_window_leaves_no_note_behind(seq):
    """The probe said "incomplete", the early drain found the log folded in: nothing was copied
    and no sentence about a copy may survive."""
    log, rig, tmp = seq
    (tmp / "stage").mkdir()
    rig["row"] = (1, 206, 104)
    rig["drains"] = [None, None]
    notes: list[str] = []
    src = sb._live_corpus_source(tmp / "stage", True, notes)
    assert log == ["pause", "gate", "drain", "ungate", "resume"]
    assert src.snapshot is None and not [n for n in notes if "temporary copy" in n]
    del log[:]
    with src.freeze() as frozen:
        assert frozen is None
    assert log == ["pause", "gate", "drain", "ungate", "resume"], "the stream is today's freeze"


def test_an_early_copy_runs_under_the_pause_with_the_gate_released(seq):
    """MUTATION TARGET. The gate wraps the drain only; the copy follows it, still inside the
    pause, and the source then streams from the copy with nothing left to freeze."""
    log, rig, tmp = seq
    (tmp / "stage").mkdir()
    rig["row"] = (1, 206, 104)
    rig["drains"] = [tmp / "corpus.db-wal"]
    notes: list[str] = []
    src = sb._live_corpus_source(tmp / "stage", True, notes)
    assert log == ["pause", "gate", "drain", "ungate", "snapshot", "resume"]
    assert src.snapshot is not None and src.path == src.snapshot.path
    del log[:]
    with src.freeze() as frozen:
        assert frozen is None
    assert log == [], "nothing is paused or gated again for the stream"
    assert [n for n in notes if "temporary copy" in n]


def test_a_late_copy_runs_under_the_same_pause_with_the_gate_released(seq):
    log, rig, tmp = seq
    (tmp / "stage").mkdir()
    rig["drains"] = [tmp / "corpus.db-wal"]  # the probe said complete; the drain finds a reader
    src = sb._live_corpus_source(tmp / "stage", True, [])
    assert log == []
    with src.freeze() as frozen:
        assert isinstance(frozen, SnapshotCopy)
    assert log == ["pause", "gate", "drain", "ungate", "snapshot", "resume"]


def test_the_write_gate_disabled_warning_is_unchanged_on_the_clean_path(seq, monkeypatch):
    log, rig, tmp = seq
    rig["drains"] = [None]
    monkeypatch.setattr(writer, "gate_enabled", lambda: False)
    notes: list[str] = []
    src = sb._live_corpus_source(tmp / "stage", True, notes)
    with src.freeze():
        pass
    assert any("OO_WRITE_GATE=0" in n for n in notes)


# --------------------------------------------------------------------------- #
#  9: an archive the old code wrote still restores
# --------------------------------------------------------------------------- #
def test_an_old_archive_with_a_corpus_wal_member_still_restores(tmp_path):
    """The engine no longer writes a ``corpus-wal`` member; the restore side still reads one, so
    a backup made before this change is as restorable as it was."""
    work = tmp_path / "work"
    img = tmp_path / "img"
    work.mkdir()
    img.mkdir()
    con = sqlite3.connect(work / "crash.db")
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute(
            "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT)"
        )
        con.executemany(
            "INSERT INTO articles(hash, content) VALUES (?, ?)",
            [(f"h{i:05d}", ROW) for i in range(300)],
        )
        con.commit()
        # a crash image: the main file and its log, copied while the log still holds the data
        shutil.copyfile(work / "crash.db", img / "corpus.db")
        shutil.copyfile(work / "crash.db-wal", img / "corpus.db-wal")
    finally:
        con.close()
    wal = img / "corpus.db-wal"
    assert wal.stat().st_size > 0

    @contextmanager
    def freeze():
        yield wal

    src = CorpusSource(
        path=img / "corpus.db", member_name="corpus.db", encrypted=False, freeze=freeze
    )
    dest = tmp_path / "dest"
    write_stream_backup(
        dest, "pw", corpus_source=src, side_members=_members(tmp_path), volume_size=VOL
    )
    man = load_manifest(dest)
    assert man["wal_member"] == "corpus.db-wal"
    n, _ = _restore(tmp_path, dest)
    assert n == 300
