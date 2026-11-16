"""Rebuild the library at the settings a new one is created with today (R702: DB-10's rebuild at new settings, 0.6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A library created before DB-10 keeps its page size (4 KiB) and its auto-vacuum mode (none) for good: SQLCipher cannot change a
page size in place, and every snapshot and restore keeps both on purpose (``connect._match_source_pragmas``). So an older install
never gets the measured gain of 16 KiB pages nor the idle incremental vacuum. This module rewrites the library ONCE into a new file
at today's settings and puts it in place of the old one, which it KEEPS under a second name until the operator removes it.

How, and why this way (the design note: /mnt/project-files/lanes-2026-11-14/laneD-r702-rebuild-design.md, approved by Plan):

* The copy is ``connect.copy_at_current_settings`` (``sqlcipher_export`` into a fresh attached file that declares the new
  settings). VACUUM cannot change SQLCipher's page size, and at 16 KiB it corrupted an encrypted store with ``temp_store=FILE``.
* It runs inside collection's exclusive window and under the single-writer gate for the whole copy (a save waits; the job row
  says so), after the work already in flight has finished (``repair._quiet``'s lease wait), exactly as the repair does.
* Whether ANY connection committed to the old file during the copy is read inside the one swap window
  (``merge.swap_in_corpus``) from a connection opened before the copy (``repair._Probe``: ``PRAGMA data_version``), so a save the
  gate did not see (a Core write, the gate switched off) refuses the switch instead of being lost under the new file.
* Before it is switched in, the new file must prove itself: it opens through ``connect()`` with no page size given, reads the new
  settings back, passes ``quick_check``, has the same schema and the same row count in every table.
* The old file is kept by a SECOND NAME (a hard link made before the swap), so nothing is copied twice and nothing of it is ever
  lost by the switch. It is never removed on its own (R702 Q-a): the Maintenance panel shows it with its size and date and offers
  to remove it, and a later rebuild's free-space check names it.

STATED LIMITS: the main library only (R702 Q-b: the other stores follow in a later change, and the panel says so). A file system
that cannot give a file a second name is refused before anything is copied. A reader that is still reading when the swap comes is
refused from its next statement, as at a restore or a repair. A Stop takes effect up to the moment the switch begins, never
after it. A second server on the same data folder is not held by this process's swap window (the R176 limit a restore and a
repair share): its writes after the switch land in the kept file, not the library.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.jobs.background import BackgroundJob, Framed, JobContext, register_job

_LOG = logging.getLogger(__name__)

JOB_KIND = "rebuild-database"
LABEL = "Rebuilding the library at the current settings"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
#: Bytes added to the estimate of the new file before it is compared with the free space: the new file's own log and the folder's
#: slack. WHAT IT PROTECTS: a copy that would fill the drive in its last minutes.
MARGIN_BYTES = 256 * 1024 * 1024
#: The new file is measured at most this much larger than the pages in use of the old one (the 16 KiB pages hold the same rows with
#: less per-page overhead, so it is usually SMALLER: 530.8 MB became 498.3 MB on the R702 bench). Kept above 1 so the estimate never
#: under-asks for a store whose pages are nearly empty.
SIZE_FACTOR = 1.10
#: A partial younger than this (seconds) may be one a rebuild is writing: the sweep leaves it, and the next look removes it.
PARTIAL_MIN_AGE_S = 600.0
#: How long the work already in flight on the library may take to finish before the rebuild refuses, naming it (seconds).
QUIESCE_S = 180.0

#: What the operator answered to "back up first?" (R702): the rebuild refuses without one of these.
BACKUP_ANSWERS = ("have_backup", "no_backup_understood")

FRAME_COPYING = "Copying the library into a new file at the current settings ({mb} MB in use)"
FRAME_CHECKING = "Checking the new file before it is switched in"
FRAME_SWITCHING = "Switching the new file in"


class Declined(RuntimeError):
    """Refused for a stated reason, with every file as it was. ``code`` keys the sentence."""

    def __init__(self, code: str, detail: str, **facts: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.facts = facts


class NoRoom(Declined):
    """The library's drive has not the room the new file needs (the route answers 507)."""


class Running(Declined):
    """A rebuild is running, and what was asked must wait for it (the route answers 409)."""


class Stopped(RuntimeError):
    """The operator stopped the rebuild (or the app is shutting down): the library is as it was and the partial copy is gone."""


_LOCK = threading.Lock()
_LAST: dict[str, Any] = {}


def _record(report: dict[str, Any]) -> None:
    with _LOCK:
        _LAST.clear()
        _LAST.update(report)


def last_report() -> dict[str, Any]:
    with _LOCK:
        return dict(_LAST)


def corpus_path() -> Path | None:
    from src.database import repair

    return repair.corpus_path()


def _partial_name(target: Path, stamp: str) -> Path:
    return target.with_name(f"{target.stem}.rebuild-{stamp}{target.suffix}.partial")


def _kept_name(target: Path, stamp: str) -> Path:
    return target.with_name(f"{target.stem}.pre-rebuild-{stamp}{target.suffix}")


def _kept_pattern(target: Path) -> re.Pattern[str]:
    return re.compile(re.escape(target.stem) + r"\.pre-rebuild-(\d{8}T\d{6}Z)" + re.escape(target.suffix))


def _partial_pattern(target: Path) -> re.Pattern[str]:
    return re.compile(
        re.escape(target.stem) + r"\.rebuild-\d{8}T\d{6}Z" + re.escape(target.suffix) + r"\.partial(?:-wal|-shm|-journal)?"
    )


def kept_copies(target: Path | None = None) -> list[dict[str, Any]]:
    """The files earlier rebuilds kept, newest first: name, size in bytes and when the rebuild made it. Never raises. A name is
    matched whole and only a regular file counts (a link is never offered for removal)."""
    target = target or corpus_path()
    if target is None:
        return []
    pattern = _kept_pattern(target)
    out: list[dict[str, Any]] = []
    found: list[tuple[tuple[int, int], dict[str, Any]]] = []
    try:
        entries = list(os.scandir(target.parent))
    except OSError:
        return []
    for entry in entries:
        m = pattern.fullmatch(entry.name)
        if m is None:
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            size = st.st_size
            made = datetime.strptime(m.group(1), STAMP_FORMAT).replace(tzinfo=UTC).isoformat(timespec="seconds")
        except (OSError, ValueError):
            continue  # a stamp that is not a real date is a name this module never gave
        if _same_file(Path(entry.path), target):
            continue  # a second name of the LIVE library (a rebuild cut between the link and the swap): not a kept copy
        found.append(((st.st_dev, st.st_ino), {"name": entry.name, "bytes": int(size), "made_at": made}))
    # two names of ONE file (a crash between the link and the swap, then a later rebuild) are listed once, under the older
    # name, so the room they take is counted once and "freed" is true of the removal
    seen: set[tuple[int, int]] = set()
    for file_id, row in sorted(found, key=lambda f: str(f[1]["made_at"])):
        if file_id not in seen:
            seen.add(file_id)
            out.append(row)
    return sorted(out, key=lambda k: str(k["made_at"]), reverse=True)


def remove_kept_copy(name: str) -> dict[str, Any]:
    """Remove one file an earlier rebuild kept, on the operator's own request. Only a name :func:`kept_copies` lists now is
    removed (with its side files); anything else is refused. Answers ``{"removed": name, "bytes": n}``."""
    if REBUILD_JOB.status().get("state") == "running":
        raise Running("running", "a rebuild is running; remove the kept file once it has finished")
    target = corpus_path()
    listed = {k["name"]: k for k in kept_copies(target)}
    if target is None or name not in listed:
        raise Declined("not-a-kept-copy", "that is not a file an earlier rebuild kept")
    chosen = listed[name]
    path = target.parent / str(chosen["name"])  # the name the folder listing gave, never the request's text
    path.unlink()
    for side in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            Path(str(path) + side).unlink()
    return {"removed": chosen["name"], "bytes": chosen["bytes"]}


def sweep_partials(target: Path | None = None) -> int:
    """Remove the unfinished copies a stopped or crashed rebuild left beside the library (its own names only, matched whole).
    Not while a rebuild runs: the copy it is writing is one of them."""
    target = target or corpus_path()
    if target is None or REBUILD_JOB.status().get("state") == "running":
        return 0
    pattern, gone = _partial_pattern(target), 0
    try:
        entries = list(os.scandir(target.parent))
    except OSError:
        return 0
    for entry in entries:
        if not pattern.fullmatch(entry.name) or entry.is_symlink():
            continue
        with contextlib.suppress(OSError):
            if time.time() - entry.stat(follow_symlinks=False).st_mtime < PARTIAL_MIN_AGE_S:
                continue  # a copy being written right now (a rebuild that started after the check above): never its own
            os.unlink(entry.path)
            gone += 1
    return gone


def _settings_of(path: Path) -> dict[str, int]:
    """The page size, auto-vacuum mode and pages in use of the file at ``path``, read on a connection from the app's factory."""
    from src.database.connect import connect

    con = connect(str(path), check_same_thread=False, timeout=30)
    try:
        page_size = int(con.execute("PRAGMA page_size").fetchone()[0])
        auto_vacuum = int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
        pages = int(con.execute("PRAGMA page_count").fetchone()[0])
        free = int(con.execute("PRAGMA freelist_count").fetchone()[0])
    finally:
        con.close()
    return {"page_size": page_size, "auto_vacuum": auto_vacuum, "bytes_in_use": max(0, pages - free) * page_size}


def target_settings() -> dict[str, int]:
    from src.database.connect import _FRESH_AUTO_VACUUM, _FRESH_PAGE_SIZE

    return {"page_size": int(_FRESH_PAGE_SIZE), "auto_vacuum": int(_FRESH_AUTO_VACUUM)}


def preflight(target: Path, bytes_in_use: int) -> dict[str, Any]:
    """Room on the library's drive for the new file: the pages in use times :data:`SIZE_FACTOR`, plus the log and
    :data:`MARGIN_BYTES`. The old file stays (as the kept copy), so nothing it holds is freed by the rebuild. The files earlier
    rebuilds kept are named with their size, since removing them is how room is made."""
    wal = 0
    with contextlib.suppress(OSError):
        wal = int(Path(str(target) + "-wal").stat().st_size)
    needed = int(bytes_in_use * SIZE_FACTOR) + wal + MARGIN_BYTES
    kept = kept_copies(target)
    report: dict[str, Any] = {"needed_bytes": needed, "kept_copies_bytes": sum(k["bytes"] for k in kept)}
    try:
        report["free_bytes"] = int(shutil.disk_usage(target.parent).free)
    except OSError:
        report["free_bytes"] = None
        report["sufficient"] = None
        report["detail"] = "the free space on the library's drive could not be read, so it was not checked"
        return report
    report["sufficient"] = report["free_bytes"] >= needed
    if report["sufficient"]:
        report["detail"] = "enough free space for the new file"
    else:
        report["detail"] = (
            f"the new file needs about {_mb(needed)} MB and the library's drive has {_mb(report['free_bytes'])} MB free"
            + (
                f"; the {len(kept)} file(s) earlier rebuilds kept take {_mb(report['kept_copies_bytes'])} MB and can be removed from this panel"
                if kept else ""
            )
        )
    return report


def _mb(n: int) -> int:
    return -(-int(n) // 1_000_000)


def status() -> dict[str, Any]:
    """What the Maintenance panel shows: the library's settings now and the ones a rebuild gives it, whether one would change
    anything, the files earlier rebuilds kept, and the last rebuild's report. Never raises; a figure that cannot be read is None and
    says so."""
    from src.database.connect import is_encrypted_file

    target = corpus_path()
    out: dict[str, Any] = {
        "supported": target is not None,
        "scope": "main library only",
        "target": target_settings(),
        "current": None,
        "needed": None,
        "kept_copies": [],
        "job": REBUILD_JOB.status(),
        "last": last_report(),
    }
    if target is None or is_encrypted_file(target) is None:
        out["supported"] = False
        return out
    if out["job"].get("state") == "running":
        # No keyed connection and no sweep while the rebuild runs: a connection opened as the swap window begins would make the
        # swap refuse, and the panel polls this every two seconds. The settings are read again once it has finished.
        out["running"] = True
        out["kept_copies"] = kept_copies(target)
        return out
    sweep_partials(target)
    out["kept_copies"] = kept_copies(target)
    try:
        now = _settings_of(target)
    except Exception as exc:  # noqa: BLE001 - the TYPE only: the connection is keyed
        out["current_unread"] = type(exc).__name__
        return out
    out["current"] = {"page_size": now["page_size"], "auto_vacuum": now["auto_vacuum"]}
    out["bytes_in_use"] = now["bytes_in_use"]
    out["needed"] = any(now[k] != v for k, v in out["target"].items())
    out["preflight"] = preflight(target, now["bytes_in_use"])
    return out


def _others_running() -> list[str]:
    """Every other background job that is running, and an import or restore that holds the machine, by its label. The rebuild
    swaps the file under every connection, so it waits for none of them: it refuses and names them."""
    from src.jobs.background import all_job_statuses
    from src.scheduler.runner import exclusive_window_open

    busy = [str(s.get("label") or s.get("kind")) for s in all_job_statuses() if s.get("state") == "running" and s.get("kind") != JOB_KIND]
    if exclusive_window_open():
        busy.append("an import or restore")
    # The folder backup and the volume backup/restore keep their own managers rather than registry jobs. The volume set reads the
    # library; the folder backup (large data: dumps, map regions, models) does not, and is named only so "every other job waits"
    # stays true. A manager that cannot say is counted as running, never as idle.
    if _manager_running("folder"):
        busy.append("a folder backup")
    if _manager_running("volume"):
        busy.append("a volume backup or restore")
    return busy


def _manager_running(which: str) -> bool:
    try:
        if which == "folder":
            from src.backup.folder_backup import get_folder_manager

            return bool(get_folder_manager().status().get("running"))
        from src.backup.volume_job import get_volume_manager

        return bool(get_volume_manager().status().get("running"))
    except Exception:  # noqa: BLE001 - the class is not needed: the answer is "running" either way
        return True


def _words_of(refusal: Declined) -> str:
    """A refusal's words as a record and a log may have them: scrubbed (every producer writes a fixed sentence and numbers today;
    this keeps the next one that quotes a driver from carrying a passphrase into the report the panel and the bundle read)."""
    from src.monitoring.secret_scrub import record_text

    return record_text(refusal, typed=False)


def _check_copy(copy: Path, target: Path) -> dict[str, Any]:
    """The new file proves itself before it is switched in: it opens through ``connect()`` with no page size given, reads the new
    settings back, passes ``quick_check``, and has the old file's schema and the same number of rows in every table."""
    from src.database.connect import connect, is_encrypted_file

    if is_encrypted_file(copy) is not is_encrypted_file(target):
        raise Declined("copy-check", "the new file is not encrypted the way the library is, so nothing was switched")
    want = target_settings()
    new = connect(str(copy), check_same_thread=False, timeout=30)
    old = connect(str(target), check_same_thread=False, timeout=30)
    try:
        got = {"page_size": int(new.execute("PRAGMA page_size").fetchone()[0]), "auto_vacuum": int(new.execute("PRAGMA auto_vacuum").fetchone()[0])}
        if got != want:
            raise Declined("copy-check", f"the new file reads {got} where {want} was declared, so nothing was switched")
        check = new.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise Declined("copy-check", "the new file failed its quick check, so nothing was switched")
        schema_sql = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        if new.execute(schema_sql).fetchall() != old.execute(schema_sql).fetchall():
            raise Declined("copy-check", "the new file's schema differs from the library's, so nothing was switched")
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()]
        rows = 0
        for name in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            n_old = int(old.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])  # nosec B608 # a name from sqlite_master, quoted
            n_new = int(new.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])  # nosec B608 # a name from sqlite_master, quoted
            if n_old == n_new:
                rows += n_old
                continue
            raise Declined("copy-check", f"the new file holds {n_new:,} rows in {name} where the library holds {n_old:,}, so nothing was switched")
        return {"tables": len(tables), "rows": rows, **got}
    finally:
        new.close()
        old.close()


def run(backup_answer: str, ctx: JobContext | None = None) -> dict[str, Any]:
    """Do the rebuild. Raises :class:`Declined` for a refusal and :class:`Stopped` for a stop, both with every file as it was, and
    for any other failure a ``RuntimeError`` that carries the failure's CLASS only: the copy runs on keyed connections and a driver's
    words can quote a statement that holds the passphrase, so the original is neither its text, its cause nor its context (it is
    raised outside the handler, so nothing chains it)."""
    failed: str | None = None
    try:
        return _run(backup_answer, ctx)
    except (Declined, Stopped):
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised below as its class, never its words
        failed = type(exc).__name__
    raise RuntimeError(f"the rebuild failed ({failed}); the library is as it was unless the report says it was switched")


def _run(backup_answer: str, ctx: JobContext | None) -> dict[str, Any]:
    from src.database import after_shutdown, repair
    from src.database.connect import SnapshotStopped, copy_at_current_settings, is_encrypted_file
    from src.database.writer import gate_enabled, write_lock

    started = time.monotonic()
    report: dict[str, Any] = {"outcome": "failed", "started_at": datetime.now(UTC).isoformat(timespec="seconds"), "backup_answer": backup_answer}
    stamp = datetime.now(UTC).strftime(STAMP_FORMAT)
    target = corpus_path()
    partial: Path | None = None
    kept: Path | None = None
    switched = False

    def stopping() -> bool:
        return bool(ctx is not None and ctx.stopping) or after_shutdown.refused_kind() is not None

    def progress(frame: str, **values: Any) -> None:
        if ctx is not None:
            ctx.set_progress(detail=Framed(frame.format(**values), frame, **values))

    try:
        if backup_answer not in BACKUP_ANSWERS:
            raise Declined("no-backup-answer", "the rebuild starts only once you have said whether you made a backup first")
        if target is None or is_encrypted_file(target) is None:
            raise Declined("no-library", "there is no library file to rebuild")
        if target.is_symlink():
            raise Declined(
                "library-is-a-link",
                "the library's name is a link to a file elsewhere; the switch would replace the link itself, so nothing was started",
            )
        if not gate_enabled():
            raise Declined(
                "write-gate-off",
                "the single-writer gate is switched off (OO_WRITE_GATE=0), so a save made while the library is copied could not be held back",
            )
        busy = _others_running()
        if busy:
            raise Declined("busy", "the rebuild waits until nothing else is running: " + "; ".join(busy), running=busy)
        now = _settings_of(target)
        report["before"] = {"page_size": now["page_size"], "auto_vacuum": now["auto_vacuum"]}
        if all(now[k] == v for k, v in target_settings().items()):
            raise Declined("nothing-to-change", "the library already has the current settings")
        room = preflight(target, now["bytes_in_use"])
        report["preflight"] = room
        if room.get("sufficient") is False:
            raise NoRoom("no-room", room["detail"], free_bytes=room["free_bytes"], needed_bytes=room["needed_bytes"])
        sweep_partials(target)
        partial = _partial_name(target, stamp)
        kept = _kept_name(target, stamp)
        with repair._exclusive_window():
            _quiet(stopping)
            with write_lock():
                origin = _identity(target)  # the FILE the probe watches: a library replaced under its name is not one it can see
                watch = repair._Probe(target)  # opened BEFORE the copy reads its first row
                try:
                    if _replaced_since(target, origin):  # replaced between the two looks: the probe may watch either file
                        raise Declined("replaced-during-the-copy", _REPLACED_WORDS)
                    progress(FRAME_COPYING, mb=_mb(now["bytes_in_use"]))
                    t0 = time.monotonic()
                    try:
                        copy_at_current_settings(target, partial, should_stop=stopping)
                    except SnapshotStopped:
                        raise Stopped("the rebuild was stopped while copying") from None
                    report["copy_seconds"] = round(time.monotonic() - t0, 1)
                    if stopping():
                        raise Stopped("the rebuild was stopped")
                    progress(FRAME_CHECKING)
                    report["checked"] = _check_copy(partial, target)
                    repair._durable(partial)
                    repair._fsync_dir(target.parent)
                    if stopping():
                        raise Stopped("the rebuild was stopped before the switch")  # the last point a stop can take effect
                    progress(FRAME_SWITCHING)
                    switched = _switch(target, partial, kept, watch, origin)
                finally:
                    watch.close()
        report["outcome"] = "rebuilt"
        report["kept_file"] = kept.name
        with contextlib.suppress(OSError):
            report["kept_file_bytes"] = int(kept.stat().st_size)
        with contextlib.suppress(Exception):
            report["after"] = {k: v for k, v in _settings_of(target).items() if k != "bytes_in_use"}
        _LOG.warning("database rebuild: the library now has the current settings; the old file is kept as %s", kept.name)
        return report
    except Declined as refusal:
        code = refusal.code
        report.update(outcome="declined", reason=code, reason_text=_words_of(refusal))
        _LOG.warning("database rebuild: not done (%s)", code)
        raise
    except Stopped:
        report["outcome"] = "stopped"
        raise
    except Exception as exc:
        # The TYPE only, never the text: the copy runs on keyed connections and a driver's words can quote a statement that holds
        # the passphrase. The exception goes on with its chain cut for the same reason.
        # A step after a successful replace can raise too (merge's own finally): whether the library IS the new file is read from
        # the files, not from how far the code got.
        switched = switched or (kept is not None and kept.exists() and not _same_file(kept, target))
        report.update(outcome="failed", failure=type(exc).__name__, switched=switched)
        _LOG.warning("database rebuild failed (%s)", type(exc).__name__)
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 1)
        if partial is not None:
            for side in ("", "-wal", "-shm", "-journal"):
                with contextlib.suppress(OSError):
                    Path(str(partial) + side).unlink()  # a copy that was never switched in (a switched one no longer has this name)
        if kept is not None and _same_file(kept, target):
            # The kept name still points at the library itself: nothing was switched, and the second name goes. Once the switch
            # happened the kept name is the ONLY name of the old file and is never removed here.
            with contextlib.suppress(OSError):
                kept.unlink()
        _record(report)


def _same_file(a: Path, b: Path | None) -> bool:
    if b is None:
        return False
    try:
        sa, sb = os.lstat(a), os.lstat(b)
    except OSError:
        return False
    return (sa.st_ino, sa.st_dev) == (sb.st_ino, sb.st_dev)


def _quiet(stopping: Any) -> None:
    from src.database.corpus_lease import foreign_note, wait_for_quiescence

    held = wait_for_quiescence(QUIESCE_S, should_stop=stopping)
    if stopping():
        raise Stopped("the rebuild was stopped")
    if held:
        raise Declined("writer-busy", "another job is still writing to the library (" + ", ".join(held) + f") after waiting {QUIESCE_S:.0f} s" + foreign_note(held))


def _identity(path: Path) -> tuple[int, int, bool | None]:
    """The file under ``path`` (device, inode) and whether it is encrypted at rest. The probe's data version answers for the file
    it opened only: if another path (Encrypt, a restore) put a different file under the name, the probe never moves, so the
    switch also compares this, taken when the probe was opened, with the file there at the swap."""
    from src.database.connect import is_encrypted_file

    st = os.stat(path)
    return (st.st_dev, st.st_ino, is_encrypted_file(path))


def _switch(target: Path, finished: Path, kept: Path, watch: Any, origin: tuple[int, int, bool | None]) -> bool:
    """Give the old file its second name, then put the new file in its place inside the one swap window. Returns True once the
    library IS the new file (the caller then keeps both names)."""
    from src.backup.merge import swap_in_corpus
    from src.database import library_generation, repair
    from src.database.connect import _last_good_page_size
    from src.database.session import dispose_engine, init_db

    dispose_engine()
    repair_cancel = repair._CANCEL  # _empty_the_log polls the repair's stop: a rebuild runs only when no repair does
    if repair_cancel.is_set():
        raise Stopped("the app is shutting down")
    from src.database import salvage

    stopped = refused = None
    try:
        repair._empty_the_log(target, watch)
    except salvage.SalvageStopped:
        stopped = True
    except repair.Declined as theirs:
        refused = theirs.code  # the repair's own refusal (a reader held the log): its code, said in this module's words
    if stopped:
        raise Stopped("the app is shutting down")
    if refused is not None:
        raise Declined(refused, "a reader kept the library's log open, so it could not be folded before the switch; nothing was switched")
    replaced = _replaced_since(target, origin)
    if replaced:
        raise Declined("replaced-during-the-copy", _REPLACED_WORDS)
    before = repair.fingerprint(target)
    taken = linked = False
    try:
        os.link(target, kept)
        linked = True
    except FileExistsError:
        taken = True
    except OSError:
        pass
    if taken:
        raise Declined("name-taken", "a file already has the name the old library would be kept under; start the rebuild again")
    if not linked:
        raise Declined("no-hard-links", "the drive cannot give the library a second name, so the old file could not be kept")
    repair._fsync_dir(target.parent)

    def written_to_since() -> None:
        moved, failed = False, None
        try:
            moved = watch.moved()
        except Exception as exc:  # noqa: BLE001 - the type only: the connection is keyed
            failed = type(exc).__name__
        if failed is not None:  # raised outside the handler, so the keyed connection's error is not carried as the context
            raise Declined("writer-busy", f"another connection kept the library's write lock, so it could not be told whether it was written to ({failed})")
        if _replaced_since(target, origin):
            raise Declined("replaced-during-the-copy", _REPLACED_WORDS)
        if moved or repair.fingerprint(target) != before:
            raise Declined("saved-during-the-copy", "something was saved to the library while it was copied, so nothing was switched; start the rebuild again")
        watch.close()

    try:
        swap_in_corpus(finished, target, check=written_to_since)
    except library_generation.LibraryBusy:
        busy = True
    else:
        busy = False
    if busy:
        raise Declined("writer-busy", "a connection opened before the switch was still in use, so nothing was switched")
    # From here the library IS the new file: what follows is best effort, and a step that fails is logged by its class and never
    # turns a rebuild that happened into one reported as failed.
    with contextlib.suppress(Exception):
        _last_good_page_size.pop(str(target.resolve()), None)  # the size cached for the old file is not the new one's
    for step in (_kv_invalidate, dispose_engine, lambda: repair._fsync_dir(target.parent), init_db):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - the TYPE only: these run on the keyed engine
            _LOG.warning("database rebuild: a step after the switch failed (%s)", type(exc).__name__)
    return True


_REPLACED_WORDS = (
    "another step (encrypting the library, or a restore) put a different file under the library's name while it was copied, "
    "so nothing was switched; start the rebuild again"
)


def _replaced_since(target: Path, origin: tuple[int, int, bool | None]) -> bool:
    """Whether the file now under ``target`` is not the one the copy was made from (an unreadable name counts as replaced)."""
    try:
        return _identity(target) != origin
    except OSError:
        return True


def _kv_invalidate() -> None:
    from src.config.kv_store import kv_invalidate

    kv_invalidate()  # the settings the old file held are read again from the new one


def _worker(ctx: JobContext, *, backup_answer: str) -> dict[str, Any]:
    """A refusal and a stop are ordinary outcomes, not crashes: the job ends with the report (the panel reads it from
    :func:`last_report`), so the task manager never shows "nothing to change" or a Stop as an error."""
    try:
        return run(backup_answer, ctx)
    except (Declined, Stopped):
        return last_report()


REBUILD_JOB = register_job(BackgroundJob(JOB_KIND, LABEL, _worker, is_writer=True, cancellable=True))


def start(backup_answer: str) -> dict[str, Any]:
    """Start the rebuild as a background job after the quick checks a page can be answered on at once (the backup answer, nothing
    else running, the settings, the free space); the job checks every one of them again before it copies."""
    if backup_answer not in BACKUP_ANSWERS:
        raise Declined("no-backup-answer", "the rebuild starts only once you have said whether you made a backup first")
    busy = _others_running()
    if busy:
        raise Declined("busy", "the rebuild waits until nothing else is running: " + "; ".join(busy), running=busy)
    st = status()
    if not st["supported"]:
        raise Declined("no-library", "there is no library file to rebuild")
    if st["needed"] is False:
        raise Declined("nothing-to-change", "the library already has the current settings")
    room = st.get("preflight") or {}
    if room.get("sufficient") is False:
        raise NoRoom("no-room", room["detail"])
    return REBUILD_JOB.start(backup_answer=backup_answer)
