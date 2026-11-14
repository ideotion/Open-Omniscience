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
refused from its next statement, as at a restore or a repair.
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
    out = []
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
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        made = datetime.strptime(m.group(1), STAMP_FORMAT).replace(tzinfo=UTC).isoformat(timespec="seconds")
        out.append({"name": entry.name, "bytes": int(size), "made_at": made})
    return sorted(out, key=lambda k: k["made_at"], reverse=True)


def remove_kept_copy(name: str) -> dict[str, Any]:
    """Remove one file an earlier rebuild kept, on the operator's own request. Only a name :func:`kept_copies` lists now is
    removed (with its side files); anything else is refused. Answers ``{"removed": name, "bytes": n}``."""
    target = corpus_path()
    listed = {k["name"]: k for k in kept_copies(target)}
    if target is None or name not in listed:
        raise Declined("not-a-kept-copy", "that is not a file an earlier rebuild kept")
    path = target.parent / name
    path.unlink()
    for side in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            Path(str(path) + side).unlink()
    return {"removed": name, "bytes": listed[name]["bytes"]}


def sweep_partials(target: Path | None = None) -> int:
    """Remove the unfinished copies a stopped or crashed rebuild left beside the library (its own names only, matched whole).
    Not while a rebuild runs: the copy it is writing is one of them."""
    target = target or corpus_path()
    if target is None or REBUILD_JOB.status().get("state") == "running":
        return 0
    pattern, gone = _partial_pattern(target), 0
    with contextlib.suppress(OSError):
        for entry in list(os.scandir(target.parent)):
            if pattern.fullmatch(entry.name) and not entry.is_symlink():
                with contextlib.suppress(OSError):
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
    # The folder backup and the volume backup/restore keep their own managers rather than registry jobs; each reads the
    # library while it runs, so a switch under it would hand it half of one file and half of another.
    for name, getter in (("a folder backup", "src.backup.folder_backup:get_folder_manager"), ("a volume backup or restore", "src.backup.volume_job:get_volume_manager")):
        mod, fn = getter.split(":")
        try:
            import importlib

            running = bool(getattr(importlib.import_module(mod), fn)().status().get("running"))
        except Exception:  # noqa: BLE001 -- a manager that cannot say is treated as busy, never as idle
            running = True
        if running:
            busy.append(name)
    return busy


def _check_copy(copy: Path, target: Path) -> dict[str, Any]:
    """The new file proves itself before it is switched in: it opens through ``connect()`` with no page size given, reads the new
    settings back, passes ``quick_check``, and has the old file's schema and the same number of rows in every table."""
    from src.database.connect import connect

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
            n_old = int(old.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])  # nosec B608 - a name from sqlite_master, quoted
            n_new = int(new.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])  # nosec B608 - a name from sqlite_master, quoted
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
            raise Declined("no-room", room["detail"], free_bytes=room["free_bytes"], needed_bytes=room["needed_bytes"])
        sweep_partials(target)
        partial = _partial_name(target, stamp)
        kept = _kept_name(target, stamp)
        with repair._exclusive_window():
            _quiet(stopping)
            with write_lock():
                watch = repair._Probe(target)  # opened BEFORE the copy reads its first row
                try:
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
                    progress(FRAME_SWITCHING)
                    switched = _switch(target, partial, kept, watch)
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
        report.update(outcome="declined", reason=refusal.code, reason_text=refusal.detail)
        _LOG.warning("database rebuild: not done (%s)", refusal.code)
        raise
    except Stopped:
        report["outcome"] = "stopped"
        raise
    except Exception as exc:
        # The TYPE only, never the text: the copy runs on keyed connections and a driver's words can quote a statement that holds
        # the passphrase. The exception goes on with its chain cut for the same reason.
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


def _switch(target: Path, finished: Path, kept: Path, watch: Any) -> bool:
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
    repair._empty_the_log(target, watch)
    before = repair.fingerprint(target)
    try:
        os.link(target, kept)
    except OSError:
        raise Declined("no-hard-links", "the drive cannot give the library a second name, so the old file could not be kept") from None
    repair._fsync_dir(target.parent)

    def written_to_since() -> None:
        try:
            moved = watch.moved()
        except Exception as exc:  # noqa: BLE001 - the type only: the connection is keyed
            raise Declined(
                "writer-busy", f"another connection kept the library's write lock, so it could not be told whether it was written to ({type(exc).__name__})"
            ) from None
        if moved or repair.fingerprint(target) != before:
            raise Declined("saved-during-the-copy", "something was saved to the library while it was copied, so nothing was switched; start the rebuild again")
        watch.close()

    try:
        swap_in_corpus(finished, target, check=written_to_since)
    except library_generation.LibraryBusy as busy:
        raise Declined("writer-busy", str(busy)) from None
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


def _kv_invalidate() -> None:
    from src.config.kv_store import kv_invalidate

    kv_invalidate()  # the settings the old file held are read again from the new one


def _worker(ctx: JobContext, *, backup_answer: str) -> dict[str, Any]:
    return run(backup_answer, ctx)


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
        raise Declined("no-room", room["detail"])
    return REBUILD_JOB.start(backup_answer=backup_answer)
