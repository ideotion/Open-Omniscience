"""The repair of a damaged library file at start-up (damaged-database plan, slice E3, R121).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THE USER RULED (R121, answer 27a). When damage is confirmed the app repairs the file itself, by a salvage copy
and a swap, and DELETES NOTHING. This module is that: ``database/salvage.py`` makes the copy; this decides whether
and when, asks for the room first, checks the copy with the same per-table check the start-up uses, and switches to it
without ever having a moment in which no library file exists.

WHEN. The boot sequence's step ``repair-database`` runs right after ``verify-database`` and before the article list's
index build, while the app is still offline and nothing of collection writes. It acts on exactly one thing: a CORPUS
file whose per-table check THIS process measured as ``damaged`` (``damage.registry.confirmed_damage``). An ``unchecked``
file, a finding an earlier process made that this one did not read again, a Wikipedia or law file (their latches
contain them; a repair for them is a later slice), and a file damaged while the app runs (it is latched and repaired at
the next start) are all left alone. ``OO_BOOT_REPAIR=0`` turns the step off.

THE ORDER OF THINGS.

1. Refuse before a byte is copied, in words, with the file untouched: the list of tables cannot be read (nothing can
   be copied: ``schema-unreadable``); the drive cannot give a file a second name (``no-hard-links``: probed by making
   one); the drive has less free than the file, its log and the disk guard's own reserve (``no-room``: what it
   protects is the drive filling while the copy grows, which would fail every writer; an unreadable figure is not a
   refusal); two starts in a row ended mid-repair (``unfinished-starts``, as the index build's).
2. The copy, under the write gate and the exclusive window for the WHOLE repair, so nothing can be written to the damaged
   file between the moment a row is read and the moment the new file replaces it: anything the app saves waits, and the
   job row says so. A copy that cannot be read to the end of any table, a failed index, or a copy that does not read clean
   under ``salvage.check_copy`` ends the repair: the partial file is deleted (it is the app's own scratch) and NOTHING
   else changes.
3. The swap, the restore's machinery with one change. The engine is disposed (SQLite folds the log into the damaged file
   as the last connection closes; the copy already holds every committed change the log carried), the finished copy is
   renamed into place beside a sidecar that records the damaged file's identity, the damaged file is given a second name
   ``<stem>.damaged-<UTC time><suffix>`` by a HARD LINK (one inode under two names: no second 14 GB, and the live name
   keeps existing until the very replace), the live log and shared-memory names are removed so the old log can never be
   replayed into the new file, and ``os.replace`` puts the copy under the live name. A drive that cannot hard-link is
   refused up front, not served by a rename pair with a moment in which no library exists.

A POWER CUT BETWEEN THOSE STEPS is the only window with no clean answer, and it is answered at the next start
(``find_resumable``): a finished copy with its sidecar, beside a live file whose identity (size, modification time, inode)
is still the one the sidecar recorded, is switched in; one that does not match has been written to since and is
discarded (it is the app's own scratch) so a fresh copy is made from the file as it is now, log included.

WHAT IS DELETED. Three things, and nothing else. Two are the app's own scratch: an unfinished ``.partial`` copy (and a
finished one whose source has since changed), and the extra name a failed hard-link step had just made. The third is the
damaged file the repair set aside, which the app removes ``KEPT_COPY_DAYS`` days after the new file first read clean (R129,
the user's answer 35 = b): see :func:`sweep_kept_copies` for every condition, among them that it deletes only the file the
repair itself recorded (its name, its inode, in the data folder, not a link) and never while a repair or a check runs or the
library is latched damaged again.

PASSPHRASE. The record holds counts, table names, id ranges and reason CODES; an engine's text enters it only through
``secret_scrub`` and only in the report's ``failure`` line.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import stat
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.database import damage, salvage
from src.jobs.background import BackgroundJob, Framed, JobContext, register_job

_LOG = logging.getLogger(__name__)

JOB_KIND = "repair-database"
LABEL = "Repairing the damaged library file"
ATTEMPT_FILE = "database-repair-attempt.json"

#: Starts in a row that began a repair and did not see it end, after which the repair is not tried again until the app is
#: updated. WHAT IT PROTECTS: a boot that never reaches collection because the repair itself brings the process down (a
#: machine too small for the index sort, a power cut every time): the same guard the index build has.
MAX_UNFINISHED_STARTS = 2

#: How long the swap waits for another job's batch already in flight (``corpus_lease``) before it refuses. The restore's
#: figure for the same wait; at start-up nothing holds a lease, so this is a ceiling, not an expectation.
QUIESCE_S = 180.0

STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

#: How many days the damaged file a repair set aside is kept, counted from the moment the repaired file first read clean (the
#: per-table check of the new file, before the swap). WHAT IT PROTECTS: the user's chance to get rows the salvage could not
#: read (the damaged file may still hold them for a recovery tool) against a second copy of the library, up to 14 GB, sitting on
#: the drive for ever. It is the user's own number (R129): the app removes the file once, at the first start on or after the date,
#: and says the date wherever it says the file exists. The number itself is ``damage.KEPT_COPY_DAYS`` (the notices need it).
KEPT_COPY_DAYS = damage.KEPT_COPY_DAYS

# The job row's own sentences (keyed, x12). The refusals reuse ``damage.FRAME_REPAIR_*`` so the row and the damage block
# cannot say two things.
FRAME_COPYING = (
    "Repairing the damaged library file: table {index} of {total} ({table}), {kept} rows copied so far, {lost} entries "
    "could not be read. Anything the app saves waits until it is done."
)
FRAME_INDEXES = (
    "Repairing the damaged library file: rebuilding its indexes ({index} of {total}). Anything the app saves waits "
    "until it is done."
)
FRAME_SEARCH = (
    "Repairing the damaged library file: rebuilding the search index. Anything the app saves waits until it is done."
)
FRAME_CHECKING = (
    "Repairing the damaged library file: checking the new file. Anything the app saves waits until it is done."
)
FRAME_SWITCHING = (
    "Repairing the damaged library file: switching to the new file. Anything the app saves waits until it is done."
)


def switch_on() -> bool:
    return damage.repair_switch_on()


class Declined(RuntimeError):
    """Refused for a stated reason, with every file as it was. ``code`` keys the sentence (``no-room``,
    ``schema-unreadable``, ``no-hard-links``, ``writer-busy``, ``unfinished-starts``)."""

    def __init__(self, code: str, detail: str, **facts: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.facts = facts


_LOCK = threading.Lock()
_LAST: dict[str, Any] = {}
_CANCEL = threading.Event()
_ARMED = False


def _record(**fields: Any) -> None:
    with _LOCK:
        _LAST.update(fields)


def snapshot() -> dict[str, Any]:
    """What the repair step did in this process (``{}`` before it has run): its outcome and the numbers. A copy at every
    depth. Counts, names and times only."""
    import copy

    with _LOCK:
        return copy.deepcopy(_LAST)


def stop() -> None:
    """Shutdown: the copy in hand ends at its next batch and the attempt is given back (an orderly quit is not a repair
    that brought the process down). Never raises."""
    global _ARMED
    _CANCEL.set()
    try:
        with _LOCK:
            armed, _ARMED = _ARMED, False
        if not armed:
            return
        left = _unfinished_starts() - 1
        if left <= 0:
            with contextlib.suppress(OSError):
                _marker_path().unlink()
        else:
            _write_marker(left, gave_back=True)
    except Exception:  # noqa: BLE001 - best-effort shutdown
        _LOG.debug("database repair: could not give back an attempt", exc_info=True)


def _reset_for_tests() -> None:
    global _ARMED
    with _LOCK:
        _LAST.clear()
        _ARMED = False
    _CANCEL.clear()


# --- the record of an attempt (the index build's pattern) ---------------------------------------------------------------


def _marker_path() -> Path:
    from src.paths import data_dir

    return data_dir() / ATTEMPT_FILE


def _unfinished_starts() -> int:
    """How many starts in a row began a repair and did not see it end; 0 when there is no record, when another version of
    the app wrote it (an update may have fixed what stopped it) and when it cannot be read."""
    from src import __version__

    try:
        doc = json.loads(_marker_path().read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != __version__:
            return 0
        return max(0, int(doc.get("attempts") or 0))
    except (OSError, ValueError, TypeError):
        return 0


def _write_marker(attempts: int, **facts: Any) -> bool:
    from src import __version__

    doc = {
        "schema": 1,
        "version": __version__,
        "attempts": int(attempts),
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **facts,
    }
    try:
        path = _marker_path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        _LOG.warning("database repair: the attempt could not be recorded", exc_info=True)
        return False


def _arm(attempts: int) -> None:
    global _ARMED
    ok = _write_marker(attempts)
    with _LOCK:
        _ARMED = ok


def _disarm() -> None:
    """The repair ended however it ended: the record is cleared (a failure is a recorded failure, tried again at the next
    start; only a start that never saw the end leaves the record behind)."""
    global _ARMED
    with _LOCK:
        _ARMED = False
    with contextlib.suppress(OSError):
        _marker_path().unlink()


# --- what is on disk ----------------------------------------------------------------------------------------------------


def corpus_path() -> Path | None:
    path, _name = damage._file_paths(damage.FILE_CORPUS)
    return path


def _salvage_target(target: Path, stamp: str) -> Path:
    return target.with_name(f"{target.stem}.salvage-{stamp}{target.suffix}")


def _damaged_name(target: Path, stamp: str) -> Path:
    base = target.with_name(f"{target.stem}.damaged-{stamp}{target.suffix}")
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = target.with_name(f"{target.stem}.damaged-{stamp}-{n}{target.suffix}")
    return candidate


def _side(path: Path, suffix: str) -> Path:
    return Path(str(path) + suffix)


def fingerprint(path: Path) -> dict[str, int] | None:
    """The identity a file has until it is written to or replaced: size, modification time and inode."""
    try:
        st = path.stat()
    except OSError:
        return None
    return {"size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ino": int(st.st_ino)}


def _remove_scratch(target: Path) -> int:
    """Delete the app's own unfinished scratch beside ``target``: ``.partial`` copies and their side files. Returns how
    many files went. The only deletion of this module besides a failed link step's own extra name, and it can only ever
    touch a file whose name this module made."""
    gone = 0
    for path in target.parent.glob(f"{target.stem}.salvage-*{target.suffix}.partial*"):
        with contextlib.suppress(OSError):
            path.unlink()
            gone += 1
    return gone


def find_resumable(target: Path) -> dict[str, Any] | None:
    """A finished copy whose swap a power cut or a crash interrupted, when the damaged file is still the one it was made
    from. ``{"finished": Path, "sidecar": Path, "doc": dict}``; ``None`` otherwise. A copy that no longer matches (the file
    was written to since), a sidecar with no copy and a copy with no sidecar are the app's own scratch and are cleaned
    up here: a stale copy swapped in would lose what was written since."""
    resumable: dict[str, Any] | None = None
    for sidecar in sorted(target.parent.glob(f"{target.stem}.salvage-*{target.suffix}.json")):
        try:
            doc = json.loads(sidecar.read_text(encoding="utf-8"))
            finished = sidecar.with_name(str(doc["finished"]))
        except (OSError, ValueError, KeyError, TypeError):
            with contextlib.suppress(OSError):
                sidecar.unlink()
            continue
        if not finished.is_file():
            # The copy is not there: it is the live file already (the swap ran and the sidecar outlived it), or it was
            # never finished. Either way the sidecar is spent.
            doc["swapped"] = True
            _record(late_sidecar=doc)
            with contextlib.suppress(OSError):
                sidecar.unlink()
            continue
        if fingerprint(target) == doc.get("source"):
            resumable = {"finished": finished, "sidecar": sidecar, "doc": doc}
            continue
        _LOG.warning(
            "database repair: a finished copy no longer matches the file it was made from (the file was written to); "
            "it is discarded and a new copy is made"
        )
        for stale in (finished, sidecar):
            with contextlib.suppress(OSError):
                stale.unlink()
    return resumable


def _can_hard_link(folder: Path) -> bool:
    """Whether the drive gives a file a second name, tried on a file of its own that is gone again."""
    probe = folder / f".oo-linkprobe-{uuid.uuid4().hex[:8]}"
    twin = probe.with_name(probe.name + ".twin")
    try:
        probe.write_bytes(b"0")
        os.link(probe, twin)
        return True
    except OSError:
        return False
    finally:
        for p in (twin, probe):
            with contextlib.suppress(OSError):
                p.unlink()


def preflight(target: Path) -> dict[str, Any]:
    """Is there room? The file, its log and the disk guard's own reserve (below which collection pauses): a repair that
    ends with the drive under that line has swapped one problem for another. ``sufficient`` is ``None`` when the free
    space could not be read, and then the repair goes ahead and says it was not measured."""
    from src.config.hardware_reading import disk_bytes
    from src.scheduler.storage_guard import disk_reserve_bytes

    main = target.stat().st_size if target.exists() else 0
    wal = 0
    with contextlib.suppress(OSError):
        wal = _side(target, "-wal").stat().st_size
    free, total = disk_bytes(target.parent)
    reserve = disk_reserve_bytes(total)
    needed = main + wal + reserve
    report: dict[str, Any] = {
        "file_bytes": main,
        "wal_bytes": wal,
        "reserve_bytes": reserve,
        "needed_bytes": needed,
        "free_bytes": free,
        "method": (
            "the file, its write-ahead log and the disk guard's own reserve (the larger of 1 GiB and 2% of the "
            "drive): the new file is about the size of the damaged one, and the repair must not end with the drive "
            "below the line that pauses collection"
        ),
    }
    report["sufficient"] = None if free is None else free >= needed
    return report


# --- the decision -------------------------------------------------------------------------------------------------------


def plan() -> dict[str, Any] | None:
    """What the step has to do, or ``None``. ``{"kind": "resume", ...}`` for an interrupted swap, ``{"kind": "repair",
    ...}`` for a corpus this process's check confirmed damaged."""
    if not switch_on():
        return None
    target = corpus_path()
    if target is None or not target.exists():
        return None
    resumable = find_resumable(target)
    if resumable is not None:
        return {"kind": "resume", "target": target, "resume": resumable}
    confirmed = damage.registry.confirmed_damage(damage.FILE_CORPUS)
    if confirmed is None:
        return None
    return {"kind": "repair", "target": target, "tables": confirmed["tables"]}


# --- the job ------------------------------------------------------------------------------------------------------------


def _frame(frame: str, **values: Any) -> Framed:
    return Framed(frame.format(**values), frame, **values)


def _mb(n: int) -> int:
    return -(-int(n) // 1_000_000)


@contextmanager
def _exclusive_window() -> Iterator[None]:
    """Collection's exclusive window for the whole repair: no pass and no re-index batch STARTS meanwhile (the restore's
    own). Re-entrant. The single-writer gate is taken after the wait for work already in flight (``_quiet``), never before
    it: a batch that has begun may need the gate to finish, and waiting for it while holding the gate would be a deadlock."""
    from src.scheduler.runner import exclusive_window

    with exclusive_window():
        yield


def _quiet(timeout: float) -> None:
    """Wait for any job already in flight on the corpus (``corpus_lease``) to finish; refuse, naming it, when one does not."""
    from src.database.corpus_lease import wait_for_quiescence

    held = wait_for_quiescence(timeout, should_stop=_CANCEL.is_set)
    if _CANCEL.is_set():
        raise salvage.SalvageStopped
    if held:
        raise Declined(
            "writer-busy",
            "another job is still writing to the library (" + ", ".join(held) + f") after waiting {timeout:.0f} s",
        )


def _worker(ctx: JobContext, *, work: dict[str, Any]) -> dict[str, Any]:
    return run(work, ctx)


REPAIR_JOB = register_job(BackgroundJob(JOB_KIND, LABEL, _worker, is_writer=True, cancellable=False))


def run_now_and_wait() -> str:
    """The boot step's call. Returns ``repaired``, ``declined``, ``failed``, ``stopped`` or ``skipped`` (nothing to repair).
    A store with nothing to repair never starts a job (no row flashes by). Afterwards, at this start and no other time, the
    damaged file an earlier repair kept is removed when its thirty days are over (:func:`sweep_kept_copies`)."""
    outcome = _repair_once()
    try:
        sweep_kept_copies()
    except Exception:  # noqa: BLE001 - a removal that went wrong must never be the boot's failure
        _LOG.warning("database repair: the sweep of kept copies failed", exc_info=True)
    return outcome


def _repair_once() -> str:
    work = plan()
    if work is None:
        _record(outcome="skipped")
        return "skipped"
    try:
        REPAIR_JOB.start(work=work)
    except RuntimeError:
        if REPAIR_JOB.status().get("state") != "running":
            _LOG.warning("database repair could not start its worker thread")
            return "failed"
        _LOG.info("database repair is already running; waiting for it")
    REPAIR_JOB.join()
    outcome = str(snapshot().get("outcome") or "failed")
    if REPAIR_JOB.status()["state"] == "error" and outcome not in ("declined",):
        return "failed"
    return outcome


def run(work: dict[str, Any], ctx: JobContext | None = None) -> dict[str, Any]:
    """Do the repair (or finish an interrupted swap). Raises ``Declined`` for a refusal (the job row shows it as a failed
    row carrying the keyed sentence) and any other exception for a failure; both leave every file as it was, except the
    scratch this module made."""
    target: Path = work["target"]
    rec_id = uuid.uuid4().hex[:8]
    started = time.monotonic()
    report: dict[str, Any] = {
        "outcome": "skipped",
        "kind": work["kind"],
        "started_at": time.time(),
        "damaged_tables": list(work.get("tables") or []),
    }
    _record(**report)
    damage.registry.repair_upsert(
        rec_id,
        file=damage.FILE_CORPUS,
        trigger="boot",
        kind=work["kind"],
        state="running",
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        folder=str(target.parent),
    )
    armed = False
    try:
        from src.database.writer import write_lock

        with _exclusive_window():
            if work["kind"] == "repair":
                armed = _prepare(work, target, report, ctx)
            _quiet(QUIESCE_S)
            # The write gate for the WHOLE repair: nothing the app saves can land in the damaged file between a row being
            # read and the new file replacing it (a save waits; the job row says so).
            with write_lock():
                if work["kind"] == "resume":
                    report["outcome"] = _resume(work, report, ctx)
                else:
                    report["outcome"] = _repair(work, target, report, ctx)
    except Declined as refusal:
        report.update(outcome="declined", reason=refusal.code, reason_text=refusal.detail, **refusal.facts)
        _LOG.warning("database repair: not done (%s): %s", refusal.code, refusal.detail)
        raise
    except salvage.SalvageStopped:
        report["outcome"] = "stopped"
        _LOG.info("database repair: stopped (the app is shutting down); the copy is removed at the next start")
    except salvage.SalvageRefused as refusal:
        report.update(outcome="declined", reason=refusal.code, reason_text=refusal.detail)
        _LOG.warning("database repair: not done (%s): %s", refusal.code, refusal.detail)
        raise Declined(refusal.code, refusal.detail) from refusal
    except Exception as exc:
        report.update(outcome="failed", reason="copy-failed", failure=salvage._failure_text(exc))
        _LOG.warning("database repair failed", exc_info=True)
        raise
    finally:
        report["finished_at"] = time.time()
        report["seconds"] = round(time.monotonic() - started, 1)
        if armed:
            _disarm()
        _record(**report)
        state = {"repaired": "done", "stopped": "stopped"}.get(str(report["outcome"]), "refused" if report["outcome"] == "declined" else "failed")
        damage.registry.repair_upsert(rec_id, **_registry_fields(report, state))
        if report["outcome"] != "repaired":
            with contextlib.suppress(Exception):
                _remove_scratch(target)
    return report


def _registry_fields(report: dict[str, Any], state: str) -> dict[str, Any]:
    keep = (
        "reason", "failure", "free_mb", "needed_mb", "seconds", "kept_rows", "unreadable_ids", "open_ended", "kept_file", "kept_file_bytes",
        "copy_bytes", "reconnects", "orphans", "replaced_text_values", "tables", "search_index", "indexes_seconds",
        "preflight", "post_steps", "resumed", "clean_at", "kept_file_ino", "kept_file_dev", "kept_wal_ino", "kept_wal_bytes",
        "kept_file_removal_after",
    )
    out: dict[str, Any] = {"state": state, "finished_at": datetime.now(UTC).isoformat(timespec="seconds")}
    out.update({k: report[k] for k in keep if k in report})
    return out


def _prepare(work: dict[str, Any], target: Path, report: dict[str, Any], ctx: JobContext | None) -> bool:
    """The refusals that cost nothing, in the order a user can act on them. Returns whether an attempt was armed."""
    if _schema_unreadable(work.get("tables") or []):
        raise Declined("schema-unreadable", "the list of tables in the damaged file cannot be read, so nothing can be copied")
    prior = _unfinished_starts()
    report["unfinished_starts"] = prior
    if prior >= MAX_UNFINISHED_STARTS:
        raise Declined(
            "unfinished-starts",
            f"{prior} starts in a row ended while the repair was running, so it is not tried again until the app is updated",
        )
    room = preflight(target)
    report["preflight"] = room
    if room["sufficient"] is False:
        free_mb, need_mb = int(room["free_bytes"] // 1_000_000), _mb(room["needed_bytes"])
        detail = (
            f"the drive has {room['free_bytes']:,} bytes free and the repair needs about {room['needed_bytes']:,} "
            f"(the file, its log and the disk guard's reserve of {room['reserve_bytes']:,})"
        )
        if ctx is not None:
            ctx.set_progress(done=0, total=1, detail=_frame(damage.FRAME_REPAIR_NO_ROOM, free=free_mb, needed=need_mb))
        raise Declined("no-room", detail, free_mb=free_mb, needed_mb=need_mb)
    if not _can_hard_link(target.parent):
        raise Declined(
            "no-hard-links",
            "the drive the library is on cannot give a file a second name, which the safe switch needs",
        )
    _arm(prior + 1)
    return True


def _schema_unreadable(tables: list[str]) -> bool:
    """The check could not list the file's tables (it named ``(schema)`` instead of a table)."""
    from src.database.verify import SCHEMA_ENTRY

    return SCHEMA_ENTRY in tables


def _repair(work: dict[str, Any], target: Path, report: dict[str, Any], ctx: JobContext | None) -> str:
    stamp = datetime.now(UTC).strftime(STAMP_FORMAT)
    _remove_scratch(target)
    partial = _salvage_target(target, stamp).with_name(_salvage_target(target, stamp).name + ".partial")
    report["stamp"] = stamp
    _CANCEL.clear()

    def progress(event: dict[str, Any]) -> None:
        if ctx is None:
            return
        phase = event.get("phase")
        if phase == "tables":
            ctx.set_progress(
                done=int(event["table_index"]) - 1,
                total=int(event["tables_total"]),
                detail=_frame(
                    FRAME_COPYING, index=int(event["table_index"]), total=int(event["tables_total"]),
                    table=str(event["table"]), kept=int(event["kept"]), lost=int(event["unreadable_ids"]),
                ),
            )
        elif phase == "indexes":
            ctx.set_progress(detail=_frame(FRAME_INDEXES, index=int(event["index"]), total=int(event["total"])))
        elif phase == "search-index":
            ctx.set_progress(detail=_frame(FRAME_SEARCH))

    t0 = time.monotonic()
    try:
        copy_report = salvage.Salvage(target, partial, cancel=_CANCEL, progress=progress).run()
    except salvage.SalvageFailed as exc:
        report["failure"] = f"{exc.where}: {exc.reason}"
        raise
    report["copy_seconds"] = round(time.monotonic() - t0, 1)
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_CHECKING))
    clean, bad = salvage.check_copy(partial, cancel=_CANCEL)
    if not clean:
        report["failure"] = "the new file did not read clean: " + ", ".join(str(b.get("table")) for b in bad[:6])
        raise salvage.SalvageFailed("the check of the new file", ", ".join(str(b.get("table")) for b in bad[:6]))
    # The first clean read of the repaired file: the clock R129's thirty days run from.
    report["clean_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    for side in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            _side(partial, side).unlink()
    tables = copy_report["tables"]
    report.update(
        kept_rows=sum(int(t.get("kept") or 0) for t in tables),
        unreadable_ids=sum(int(t.get("unreadable_ids") or 0) for t in tables),
        open_ended=any(bool(t.get("open_ended")) for t in tables),
        tables=[t for t in tables if t.get("unreadable_ids") or t.get("note") or t.get("truncated") or t.get("open_ended")],
        tables_copied=len(tables),
        reconnects=copy_report.get("reconnects"),
        replaced_text_values=copy_report.get("replaced_text_values"),
        search_index=copy_report.get("search_index"),
        indexes_seconds=copy_report.get("indexes_seconds"),
        orphans=copy_report.get("orphans"),
        copy_bytes=partial.stat().st_size,
        page_size=copy_report.get("page_size"),
        encrypted=copy_report.get("encrypted"),
    )
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_SWITCHING))
    _swap(partial, target, stamp, report)
    return "repaired"


def _resume(work: dict[str, Any], report: dict[str, Any], ctx: JobContext | None) -> str:
    resume = work["resume"]
    doc = resume["doc"]
    target: Path = work["target"]
    report["resumed"] = True
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_SWITCHING))
    report.update(
        kept_rows=doc.get("kept_rows"), unreadable_ids=doc.get("unreadable_ids"), open_ended=bool(doc.get("open_ended")),
        copy_bytes=doc.get("copy_bytes"), reconnects=doc.get("reconnects"), tables=doc.get("tables") or [],
        clean_at=doc.get("clean_at"),
    )
    stamp = str(doc.get("stamp") or datetime.now(UTC).strftime(STAMP_FORMAT))
    _swap(resume["finished"], target, stamp, report, sidecar=resume["sidecar"], damaged=target.parent / str(doc["damaged"]))
    return "repaired"


def _swap(
    source: Path, target: Path, stamp: str, report: dict[str, Any], *, sidecar: Path | None = None, damaged: Path | None = None
) -> Path:
    """Put the finished copy under the live name, keeping the damaged file. ``source`` is the ``.partial`` copy of a fresh
    repair (renamed here once the damaged file's identity is recorded) or the finished copy of an interrupted one."""
    from src.backup.merge import _clear_stale_side_files, _replace_live_corpus
    from src.database.session import dispose_engine, init_db

    _quiet(10.0)  # nothing new could start under the exclusive window: this only confirms what the first wait found
    dispose_engine()
    if damaged is None:
        damaged = _damaged_name(target, stamp)
    finished = source
    if sidecar is None:
        # The damaged file's identity AFTER the engine let go (SQLite folds the log into it as the last connection closes),
        # recorded before the copy is given its final name: a copy with no sidecar is scratch, a copy with one is resumable.
        finished = source.with_name(source.name[: -len(".partial")])
        sidecar = finished.with_name(finished.name + ".json")
        doc = {
            "schema": 1,
            "stamp": stamp,
            "finished": finished.name,
            "damaged": damaged.name,
            "source": fingerprint(target),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "kept_rows": report.get("kept_rows"),
            "unreadable_ids": report.get("unreadable_ids"),
            "open_ended": bool(report.get("open_ended")),
            "copy_bytes": report.get("copy_bytes"),
            "reconnects": report.get("reconnects"),
            "tables": report.get("tables"),
            "clean_at": report.get("clean_at"),
        }
        _write_json_atomic(sidecar, doc)
        os.replace(source, finished)
    made: list[Path] = []
    try:
        for suffix in ("", "-wal"):
            live, kept = _side(target, suffix), _side(damaged, suffix)
            if not live.exists():
                continue
            try:
                os.link(live, kept)
                made.append(kept)
            except FileExistsError:
                twin, original = fingerprint(kept), fingerprint(live)
                if twin is None or original is None or twin["ino"] != original["ino"]:
                    raise  # a different file already has that name: never overwrite it
            except OSError as exc:
                for extra in made:
                    with contextlib.suppress(OSError):
                        extra.unlink()
                for spent in (finished, sidecar):
                    with contextlib.suppress(OSError):
                        spent.unlink()
                raise Declined("no-hard-links", "the drive cannot give the damaged file a second name") from exc
    except Declined:
        raise
    _note_what_was_set_aside(report, damaged)
    _clear_stale_side_files(target)
    _replace_live_corpus(finished, target)
    report["kept_file"] = damaged.name
    with contextlib.suppress(OSError):
        report["kept_file_bytes"] = damaged.stat().st_size
    init_db()
    report["post_steps"] = _after_the_swap()
    with contextlib.suppress(OSError):
        sidecar.unlink()
    _LOG.warning(
        "database repair: the library file was replaced by a repaired copy (%s rows kept, up to %s entries unreadable); the "
        "damaged file is kept as %s",
        report.get("kept_rows"), report.get("unreadable_ids"), damaged.name,
    )
    return finished


def _identity(path: Path) -> dict[str, int] | None:
    """Which file a name is, as the filesystem says it: inode and device (never the size or the time, which a write changes)."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return {"ino": int(st.st_ino), "dev": int(st.st_dev)}


def _note_what_was_set_aside(report: dict[str, Any], damaged: Path) -> None:
    """Record, while the damaged file's second name exists and before the swap, WHICH file it is (inode and device, and its log's)
    and the date R129 removes it on, so the removal later acts on that file and on nothing else a name might come to point at."""
    ident = _identity(damaged)
    if ident is not None:
        report["kept_file_ino"], report["kept_file_dev"] = ident["ino"], ident["dev"]
    wal = _identity(_side(damaged, "-wal"))
    if wal is not None:
        report["kept_wal_ino"] = wal["ino"]
        with contextlib.suppress(OSError):
            report["kept_wal_bytes"] = _side(damaged, "-wal").stat().st_size
    clean = _parse_time(report.get("clean_at")) or datetime.now(UTC)
    report["clean_at"] = clean.isoformat(timespec="seconds")
    report["kept_file_removal_after"] = (clean + timedelta(days=KEPT_COPY_DAYS)).isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _kept_name_pattern(live: Path) -> re.Pattern[str]:
    """The names a repair gives the damaged file it sets aside (``_damaged_name``): ``<stem>.damaged-<UTC time>[-n]<suffix>``."""
    return re.compile(re.escape(live.stem) + r"\.damaged-\d{8}T\d{6}Z(?:-\d+)?" + re.escape(live.suffix))


def _why_not_now() -> str | None:
    """Why nothing may be removed at this moment, or ``None``: a repair or a check is running, or the live library is latched
    damaged (a removal while it is would take away the only other copy of rows the repair may not have read)."""
    if REPAIR_JOB.status().get("state") == "running" or any(r.get("state") == "running" for r in damage.registry.repairs()):
        return "repair-running"
    if damage.registry.verifying():
        return "check-running"
    if damage.registry.latched(damage.FILE_CORPUS):
        return "corpus-latched"
    return None


def sweep_kept_copies(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """R129 (the user's answer 35 = b): remove the damaged file a repair set aside ``KEPT_COPY_DAYS`` days after the repaired
    file first read clean. Called at the end of the repair step of every start, never from a timer: a library that runs for
    weeks removes it at the first start after the date, and the notice says so. Returns one dict per kept copy looked at,
    ``{"id", "name", "outcome", "reason"}`` (``outcome``: ``removed``, ``waiting``, ``refused``, ``gone``, ``failed``; a copy
    that is not due yet or was dealt with before is not listed). Never raises.

    EVERY condition, because this is the one place the app deletes a file the user may care about:

    * ``OO_BOOT_REPAIR=0`` switches it off with the repair: a user who switched the repair off has not asked for file work;
    * nothing is removed while a repair or a check runs or the live library is latched damaged again (``waiting``, retried at
      the next start): the copy may hold rows the live file lost, and a library that is damaged again is when it matters;
    * only the file the repair itself recorded: the record's folder must be the folder of the live library, the name must be
      exactly ``<stem>.damaged-<UTC time>[-n]<suffix>`` of it, the name must not be a link and not anything but a regular file,
      and its inode must be the one the swap noted when it made the second name (the device number is noted too and not
      compared: it is not stable across mounts). Any of those failing is
      ``refused`` FOR GOOD (recorded, said in the notice, never tried again): a name that points at something else now is not
      the file the user was told about;
    * the ``-wal`` hard link the swap made goes with it, by the same identity (an unrecognised ``-wal`` is left and recorded);
    * a copy the user removed already is recorded ``gone`` (nothing to say); a failed unlink is retried at the next start;
    * the removal (date, bytes) is written into the repair record the damage notice and the Diagnostics zip read."""
    out: list[dict[str, Any]] = []
    try:
        if not switch_on():
            return out
        when = now or datetime.now(UTC)
        for rec in damage.registry.repairs():
            if rec.get("state") != "done" or not rec.get("kept_file"):
                continue
            if rec.get("kept_file_removed_at") or rec.get("kept_file_gone_at") or rec.get("kept_file_removal_refused"):
                continue
            due = _parse_time(rec.get("kept_file_removal_after"))
            if due is None or when < due:
                continue
            result: dict[str, Any] = {"id": rec.get("id"), "name": str(rec.get("kept_file"))}
            hold = _why_not_now()
            if hold is not None:
                result.update(outcome="waiting", reason=hold)
            else:
                result.update(_remove_kept_copy(rec, when))
            out.append(result)
    except Exception:  # noqa: BLE001
        _LOG.warning("database repair: the sweep of kept copies stopped", exc_info=True)
    return out


def _remove_kept_copy(rec: dict[str, Any], when: datetime) -> dict[str, Any]:
    """The removal of ONE kept copy, every condition of :func:`sweep_kept_copies` checked here. Returns ``{"outcome",
    "reason"}`` and writes the record."""
    rec_id = str(rec.get("id"))
    name = str(rec.get("kept_file") or "")

    def refuse(code: str) -> dict[str, Any]:
        _LOG.warning("database repair: the kept copy %s is not removed (%s) and will not be", name or "?", code)
        damage.registry.repair_upsert(rec_id, kept_file_removal_refused=code)
        return {"outcome": "refused", "reason": code}

    live = corpus_path()
    if live is None:
        return {"outcome": "waiting", "reason": "no-live-file"}
    if not name or name != Path(name).name or not _kept_name_pattern(live).fullmatch(name):
        return refuse("name-pattern")
    try:
        if Path(str(rec.get("folder") or "")).resolve() != live.parent.resolve():
            return refuse("outside-data-folder")
    except OSError:
        return {"outcome": "failed", "reason": "folder"}
    path = live.parent / name
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        damage.registry.repair_upsert(rec_id, kept_file_gone_at=when.isoformat(timespec="seconds"))
        return {"outcome": "gone", "reason": "already-removed"}
    except OSError:
        return {"outcome": "failed", "reason": "stat"}
    if stat.S_ISLNK(st.st_mode):
        return refuse("symlink")
    if not stat.S_ISREG(st.st_mode):
        return refuse("not-a-file")
    # The inode is the identity (it was noted in the swap, while the second name was made). The device number is recorded but
    # NOT compared: it is not stable across mounts (btrfs subvolumes, a drive re-attached), and a mismatch there would make
    # the refusal permanent for a file that is exactly the one set aside; the name, the folder and the inode already bind it.
    if rec.get("kept_file_ino") != st.st_ino:
        return refuse("not-the-file-set-aside")
    live_id = _identity(live)
    if live_id is not None and live_id["ino"] == st.st_ino and live_id["dev"] == st.st_dev:
        return refuse("is-the-live-file")
    wal = _side(path, "-wal")
    wal_out = False
    wal_left = False
    try:
        wst = os.lstat(wal)
    except OSError:
        wst = None
    if wst is not None:
        if stat.S_ISREG(wst.st_mode) and rec.get("kept_wal_ino") == wst.st_ino and wst.st_dev == st.st_dev:
            wal_out = True
        else:
            wal_left = True
    try:
        os.unlink(path)
    except OSError:
        _LOG.warning("database repair: the kept copy %s could not be removed; it is tried again at the next start", name, exc_info=True)
        return {"outcome": "failed", "reason": "unlink"}
    if wal_out:
        with contextlib.suppress(OSError):
            os.unlink(wal)
    fields: dict[str, Any] = {
        "kept_file_removed_at": when.isoformat(timespec="seconds"),
        "kept_file_removed_bytes": int(st.st_size),
    }
    if wal_out:
        fields["kept_wal_removed"] = True
    if wal_left:
        fields["kept_wal_left"] = True
    damage.registry.repair_upsert(rec_id, **fields)
    _LOG.warning(
        "database repair: the damaged file kept by the repair (%s, %d bytes) was removed, %d days after the repaired file first read clean",
        name, int(st.st_size), KEPT_COPY_DAYS,
    )
    return {"outcome": "removed", "reason": "due"}


def _after_the_swap() -> dict[str, Any]:
    """What a new file needs that the copy cannot carry: the derived stores re-read it (the corpus epoch), and a source's
    stored article count, which the lost rows made stale-high, is cleared so the read fallback counts live. Each is best
    effort and said: the repair has happened."""
    out: dict[str, Any] = {}
    try:
        from src.analytics.corpus_epoch import bump_corpus_epoch
        from src.database.session import session_scope

        with session_scope() as session:
            out["corpus_epoch"] = bump_corpus_epoch(session, reason="salvage")
    except Exception:  # noqa: BLE001
        _LOG.warning("database repair: the corpus epoch was not bumped", exc_info=True)
        out["corpus_epoch"] = None
    try:
        from sqlalchemy import update

        from src.database.models import Source
        from src.database.session import session_scope

        with session_scope() as session:
            result = session.execute(update(Source).values(article_count=None))
            out["source_counts_cleared"] = int(getattr(result, "rowcount", 0) or 0)
    except Exception:  # noqa: BLE001
        _LOG.warning("database repair: the stored source counts were not cleared", exc_info=True)
        out["source_counts_cleared"] = None
    return out


def _write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    with open(tmp, "rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, path)
