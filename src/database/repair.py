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
   job row says so. The gate must be ON (``OO_WRITE_GATE=0`` declines the repair: a save made while the copy runs could not be
   held back). The gate does not see every writer (a write on a Core connection, any write with the gate off), so a connection of the
   repair's own is opened before the copy reads its first row and its ``PRAGMA data_version`` is read again at the switch, inside the
   window below: if ANY other connection committed in between, nothing is switched (``saved-during-the-copy``). A copy that cannot be read to the end of any table, a failed index, or a copy that does not read clean
   under ``salvage.check_copy`` ends the repair: the partial file is deleted (it is the app's own scratch) and NOTHING
   else changes.
3. The swap, the restore's machinery with one change. The engine is disposed (SQLite folds the log into the damaged file
   as the last connection closes; the copy already holds every committed change the log carried), the finished copy is
   renamed into place beside a sidecar that records the damaged file's identity, the damaged file is given a second name
   ``<stem>.damaged-<UTC time><suffix>`` by a HARD LINK (one inode under two names: no second 14 GB, and the live name
   keeps existing until the very replace), the live log and shared-memory names are removed so the old log can never be
   replayed into the new file, and ``os.replace`` puts the copy under the live name. A drive that cannot hard-link is
   refused up front, not served by a rename pair with a moment in which no library exists. The removal of the log names and the
   replace happen inside ``backup.merge.swap_in_corpus`` (the restore's own swap): one window of ``database/library_generation.py`` in
   which no connection is being opened, every connection made before it is refused from its first statement (the generation moves
   FIRST), and the data-version check above runs after that and before anything changes on disk.

A POWER CUT BETWEEN THOSE STEPS is the only window with no clean answer, and it is answered at the next start
(``find_resumable``): a finished copy with its sidecar, beside a live file whose identity (size, modification time, inode)
is still the one the sidecar recorded, is switched in; one that does not match has been written to since and is
discarded (it is the app's own scratch) so a fresh copy is made from the file as it is now, log included.

WHAT IS DELETED. Three things, and nothing else. Two are the app's own scratch: an unfinished ``.partial`` copy (and a
finished one whose source has since changed), and the extra name a failed hard-link step had just made. The third is the
damaged file the repair set aside, which the app removes ``KEPT_COPY_DAYS`` days after the new file first read clean (R129,
the user's answer 35 = b): see :func:`sweep_kept_copies` for every condition, among them that it deletes only the file the
repair itself recorded (its name, its inode, in the data folder, not a link) and never while a repair or a check runs or the
library is latched damaged again. NOR A FILE THE DRIVE COULD NOT READ: SQLite 3.43 and later answer a failed read as
``SQLITE_CORRUPT``, so the per-table check cannot tell a failing drive from an overwritten file, and the repair therefore reads
the damaged file raw once (:func:`_disk_unread_pages`); a page the drive could not give, here or in the start-up check's own page
pass, means the file is kept for ever (no date is recorded) and the notice says to check the drive.

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

from src.database import damage, library_generation, salvage
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
    ``schema-unreadable``, ``no-hard-links``, ``writer-busy``, ``unfinished-starts``, ``write-gate-off``, ``copy-stale`` and
    ``saved-during-the-copy``: the library was written to after the copy began)."""

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


def _probe_open(path: Path) -> Any:
    """The connection the data-version check reads, from the app's one factory (an encrypted file is opened with its key). A name tests
    replace."""
    from src.database.connect import connect

    return connect(str(path), check_same_thread=False, timeout=30)


class _Probe:
    """One connection to the live file, opened before the copy reads its first row and kept to the switch, whose ``PRAGMA data_version``
    answers the question the write gate cannot: did ANY other connection commit to the file since? The value changes when another
    connection commits (measured: a commit that sits only in the log moves it, a checkpoint does not, the connection's own commits
    do not). The gate sees ORM writes; a write on a Core connection, a ``text()`` write on a connection that is not a session's, and any
    write with the gate off reach the file without it, and a save made after the copy read its table is in the damaged file only (the
    deep read of E3, NEW-1). ``moved`` is read INSIDE the swap window, after every earlier connection has been refused (the generation
    moves first), so a save can only have landed before it, where this sees it; it takes SQLite's write lock first, which waits for a
    commit that is under way."""

    def __init__(self, path: Path) -> None:
        self._con: Any = _probe_open(path)
        with contextlib.suppress(Exception):  # autocommit mode: the explicit BEGIN below is then the only transaction
            self._con.isolation_level = None
        self.baseline = self._version()

    def _version(self) -> int:
        return int(self._con.execute("PRAGMA data_version").fetchone()[0])

    def fold(self, wait_ms: int) -> tuple[int, int] | None:
        """One TRUNCATE checkpoint of the live log ON THIS CONNECTION: ``(frames in the log, frames moved into the file)`` as the checkpoint
        answers (``(-1, -1)`` when there is no log), or ``None`` when the answer could not be read. It runs here and nowhere else because a
        TRUNCATE checkpoint made by ANY OTHER connection moves this connection's data version, even with nothing in the log (measured on
        plaintext and on SQLCipher), so the repair's own fold would read as a save made by someone else; the connection's own does not."""
        con = self._con
        previous = con.execute("PRAGMA busy_timeout").fetchone()
        try:
            con.execute(f"PRAGMA busy_timeout={int(wait_ms)}")
            row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            with contextlib.suppress(Exception):
                con.execute(f"PRAGMA busy_timeout={int(previous[0]) if previous else 30000}")
        try:
            return int(row[1]), int(row[2])
        except (TypeError, ValueError, IndexError):
            return None

    def moved(self) -> bool:
        self._con.execute("BEGIN IMMEDIATE")
        try:
            return self._version() != self.baseline
        finally:
            with contextlib.suppress(Exception):
                self._con.execute("ROLLBACK")

    def close(self) -> None:
        con, self._con = self._con, None
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def _open_probe(target: Path) -> _Probe:
    try:
        return _Probe(target)
    except Exception as exc:  # noqa: BLE001 - the type only: the connection is keyed
        raise Declined(
            "unwatchable",
            f"the library file could not be opened to tell whether it is written to while it is copied ({type(exc).__name__}), so "
            "nothing was switched",
        ) from exc


def fingerprint(path: Path) -> dict[str, int] | None:
    """The identity a file has until it is written to or replaced: size, modification time and inode of the file, and the size of
    its write-ahead log (0 when there is none). THE LOG IS PART OF IT because in WAL mode a commit does not touch the main file at
    all: a save made after the copy was taken sits in the log, the file's size, time and inode all still match, and a copy that
    "matches" would be switched in over it (the deep read of E3, B2)."""
    try:
        st = path.stat()
    except OSError:
        return None
    wal = 0
    with contextlib.suppress(OSError):
        wal = int(_side(path, "-wal").stat().st_size)
    return {"size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ino": int(st.st_ino), "wal": wal}


def _durable(path: Path) -> None:
    """Make the file's data durable (``fsync``): the copy is written with ``synchronous=OFF``, and a name must not be handed to a
    file whose last pages may still be only in the cache (the deep read of E3, S7). Opened for writing because Windows refuses
    to flush a read-only handle."""
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(folder: Path) -> None:
    """Make a folder's entries (a rename, a link) durable. A platform that cannot open a folder (Windows) has nothing to call."""
    flags = getattr(os, "O_RDONLY", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(folder, flags)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def _scratch_pattern(live: Path, tail: str) -> re.Pattern[str]:
    """The names this module gives its own scratch beside ``live``: ``<stem>.salvage-<UTC time><suffix><tail>`` (``_salvage_target``)."""
    return re.compile(re.escape(live.stem) + r"\.salvage-\d{8}T\d{6}Z" + re.escape(live.suffix) + tail)


def _remove_scratch(target: Path) -> int:
    """Delete the app's own unfinished scratch beside ``target``: ``.partial`` copies and their side files. Returns how
    many files went. The only deletion of this module besides a failed link step's own extra name, and it can only ever
    touch a file whose name this module made (the name is matched whole, never by a glob alone)."""
    gone = 0
    pattern = _scratch_pattern(target, r"\.partial(?:-wal|-shm|-journal)?")
    for path in target.parent.glob(f"{target.stem}.salvage-*{target.suffix}.partial*"):
        if not pattern.fullmatch(path.name):
            continue
        with contextlib.suppress(OSError):
            path.unlink()
            gone += 1
    return gone


_SOURCE_KEYS = ("size", "mtime_ns", "ino", "wal")

#: What the copy measured and the start that finishes the switch needs for the record: carried through the sidecar (the deep read of E3,
#: NEW-5: the sidecar and the resume dropped the orphans, the search index and the encryption flag).
_CARRIED = (
    "kept_rows", "unreadable_ids", "open_ended", "copy_bytes", "reconnects", "tables", "clean_at", "page_size", "disk_unread_pages",
    "disk_unread_first", "check_pages_unread", "orphans", "orphans_verdict_tables", "set_null", "stand_ins", "stand_ins_note",
    "id_reuse_possible", "replaced_text_values", "search_index", "indexes_seconds", "encrypted",
)


def _sidecar_problem(sidecar: Path, target: Path, doc: Any) -> str | None:
    """Why a sidecar cannot be trusted, or ``None``. A sidecar names files this module is about to act on (the finished copy it
    deletes when stale, the damaged file it swaps), so it is read as the untrusted input it is: the name of the finished copy
    must be its own name without ``.json`` and nothing else, the damaged file's name must be one a repair gives, and the
    identity it records must be a whole one (the deep read of E3, B3: a sidecar naming the live library as ``finished`` made
    ``plan()`` delete the library, and ``"source": null`` matched a file that was not there)."""
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        return "it is not a sidecar this version wrote"
    if not _scratch_pattern(target, r"\.json").fullmatch(sidecar.name):
        return "its own name is not one a repair gives"
    if doc.get("finished") != sidecar.name[: -len(".json")]:
        return "it names a finished copy that is not its own"
    damaged = doc.get("damaged")
    if not isinstance(damaged, str) or not _kept_name_pattern(target).fullmatch(damaged):
        return "it names a damaged file that is not one a repair sets aside"
    source = doc.get("source")
    if not isinstance(source, dict) or any(type(source.get(k)) is not int for k in _SOURCE_KEYS):
        return "it records no whole identity of the damaged file"
    if type(doc.get("finished_ino")) is not int:
        return "it records no identity of the finished copy"
    if _parse_time(doc.get("created_at")) is None:
        return "it records no time it was made"
    return None


def _drop_extra_names(target: Path, damaged: Path) -> None:
    """Remove the second names a repair that did not finish gave the LIVE file (``damaged`` and its log's): a name is removed only
    when it is the same file as the live one (inode and device), so the damaged file a finished swap set aside, which is a different
    file, can never be touched here, and unlinking a second name of a file loses nothing."""
    for suffix in ("", "-wal"):
        extra, original = _side(damaged, suffix), _side(target, suffix)
        if extra == original:
            continue
        a, b = _identity(extra), _identity(original)
        if a is not None and a == b:
            with contextlib.suppress(OSError):
                extra.unlink()


def _swap_ran(target: Path, doc: dict[str, Any]) -> bool:
    """Whether the switch the sidecar describes already happened: the live name is now the finished copy (its inode is the one the
    sidecar recorded for the copy, which a rename keeps) and the damaged file's second name is there and is a different file. The
    deep read of E3 found the weaker test (the second name exists and is not the live inode) true after a repair that was cut
    between the hard link and the replace by a second, unrelated change of the live file."""
    damaged = target.parent / str(doc["damaged"])
    if damaged.is_symlink() or not damaged.is_file():
        return False
    kept, live = _identity(damaged), _identity(target)
    return (
        kept is not None and live is not None and kept["ino"] != live["ino"] and live["ino"] == doc.get("finished_ino")
    )


def find_resumable(target: Path, *, late: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """A finished copy whose swap a power cut or a crash interrupted, when the damaged file is still the one it was made
    from. ``{"finished": Path, "sidecar": Path, "doc": dict}``; ``None`` otherwise. A copy that no longer matches (the file
    was written to since, its log counted), a sidecar with no copy and a copy with no sidecar are the app's own scratch and are
    cleaned up here: a stale copy swapped in would lose what was written since. A sidecar this module did not write, or that was
    edited, is never believed: only the sidecar itself is removed, never a file it names. A sidecar whose copy is gone BECAUSE
    THE SWITCH RAN (the copy is the live file now and the damaged file is kept beside it) is appended to ``late`` when the
    caller passes a list: a cut right after the replace left the repair's record unwritten and its follow-up steps undone, and
    :func:`_finish` writes and does them; without a list such a sidecar is spent."""
    resumable: dict[str, Any] | None = None
    for sidecar in sorted(target.parent.glob(f"{target.stem}.salvage-*{target.suffix}.json")):
        if not _scratch_pattern(target, r"\.json").fullmatch(sidecar.name):
            continue  # not a name a repair gives: not this module's file, left exactly as it is
        try:
            doc = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        problem = _sidecar_problem(sidecar, target, doc)
        if problem is not None:
            _LOG.warning("database repair: a repair sidecar is discarded (%s); the file it names is left alone", problem)
            with contextlib.suppress(OSError):
                sidecar.unlink()
            continue
        finished = sidecar.with_name(str(doc["finished"]))
        if finished.is_symlink() or not finished.is_file():
            # The copy is not there: it is the live file already (the swap ran and the sidecar outlived it), or it was never
            # finished.
            if late is not None and _swap_ran(target, doc):
                late.append({"sidecar": sidecar, "doc": doc})
                continue
            doc["swapped"] = True
            _record(late_sidecar=doc)
            _drop_extra_names(target, target.parent / str(doc["damaged"]))
            with contextlib.suppress(OSError):
                sidecar.unlink()
            continue
        if fingerprint(target) == doc["source"]:
            resumable = {"finished": finished, "sidecar": sidecar, "doc": doc}
            continue
        _LOG.warning(
            "database repair: a finished copy no longer matches the file it was made from (the file was written to); "
            "it is discarded and a new copy is made"
        )
        for stale in (finished, sidecar):
            with contextlib.suppress(OSError):
                stale.unlink()
        _drop_extra_names(target, target.parent / str(doc["damaged"]))
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


#: How many bytes the raw read of the damaged file asks for at once. WHAT IT PROTECTS: the time of the pass (one sequential read
#: of a file that may be 14 GB) against how many pages a failing chunk makes the pass read one by one to find the bad ones.
RAW_CHUNK_BYTES = 4 << 20

#: How many unread pages the record NAMES (the count of all of them is kept). WHAT IT PROTECTS: the record against a drive with ten
#: thousand bad pages becoming ten thousand numbers long, while an operator can still go and look at the first ones with the drive's own
#: tools.
FIRST_PAGES_LISTED = 8

#: Opens the damaged file for the raw read (no SQLite, no key): a name tests replace with a file whose reads fail, because a drive
#: that fails to read cannot be made on demand.
_raw_open = open


def _bytes_read(handle: Any, offset: int, want: int) -> int:
    """How many of ``want`` bytes at ``offset`` the drive gave. A read that returns fewer than asked is asked again for the rest (a
    signal can cut one short), and an EMPTY answer ends it: that is end of file or a page the drive would not give. A read that raises
    raises."""
    handle.seek(offset)
    got = 0
    while got < want:
        part = handle.read(want - got)
        if not part:
            break
        got += len(part)
    return got


def _disk_unread_pages(path: Path, page_size: int, cancel: threading.Event) -> tuple[int, list[int]]:
    """How many pages of the damaged file the DRIVE cannot give, by reading every page raw: ``(count, the first few, 1-based)``.
    A read that raises (``EIO`` from a failing drive, a CRC error, a vanished device) is a page the disk could not read, and so is a
    read that comes back SHORT: Linux answers a read that crosses a bad page with the bytes before it, not with ``EIO``, so a 4 MiB
    read can return 1,622,016 bytes and no error (measured on a FUSE drive by the deep read of E3, NEW-2). The bytes asked for are
    ``min(asked, file size - offset)``; a chunk that falls short is read again page by page, and a page that falls short is counted. A
    page that reads and is wrong is damage, which SQLite names, and is not counted here. WHY IT EXISTS: SQLite 3.43 and later answer
    a failed READ as ``SQLITE_CORRUPT``, so the per-table check cannot tell a drive that failed from a file that was overwritten,
    and past 4 GiB the page pass is not run at all (:data:`verify.PAGE_PASS_LIMIT_BYTES`): this pass may be the only witness. R129's
    removal of the kept copy must not rest on a verdict that may be the drive's. The file is quiescent (the repair holds the write
    gate and the engine has not been touched since the copy) and the pass is one sequential read, which the copy has already
    warmed. A file that cannot be OPENED raises: the repair then fails with every file as it was and is tried again at the next
    start. The stop is checked before every chunk AND before every page of a chunk that is read one by one, so a run of bad sectors
    (each a slow failed read) delays a stop by one read, not by the chunk."""
    size = path.stat().st_size
    unit = max(512, int(page_size))
    total = -(-size // unit)
    chunk_pages = max(1, RAW_CHUNK_BYTES // unit)
    failed = 0
    first: list[int] = []
    with _raw_open(path, "rb", buffering=0) as handle:
        page = 0
        while page < total:
            if cancel.is_set():
                raise salvage.SalvageStopped
            count = min(chunk_pages, total - page)
            offset = page * unit
            want = min(count * unit, size - offset)
            try:
                whole = _bytes_read(handle, offset, want) >= want
            except OSError:
                whole = False
            if not whole:
                for single in range(page, page + count):
                    if cancel.is_set():
                        raise salvage.SalvageStopped
                    where = single * unit
                    one = min(unit, size - where)
                    try:
                        bad = _bytes_read(handle, where, one) < one
                    except OSError:
                        bad = True
                    if bad:
                        failed += 1
                        if len(first) < FIRST_PAGES_LISTED:
                            first.append(single + 1)
            page += count
    return failed, first


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
    """What the step has to do, or ``None``. ``{"kind": "finish", ...}`` for a switch that ran and whose record and follow-up steps
    a cut left undone, ``{"kind": "resume", ...}`` for an interrupted swap, ``{"kind": "repair", ...}`` for a corpus this
    process's check confirmed damaged. A resume needs that confirmation too (R100: an earlier process's finding is not this
    install's measurement: a file this process read clean is not switched out from under it); a copy that is not resumed stays
    where it is until a start that confirms the damage, or until the file is written to (``find_resumable`` then discards it)."""
    if not switch_on():
        return None
    target = corpus_path()
    if target is None or not target.exists():
        return None
    late: list[dict[str, Any]] = []
    resumable = find_resumable(target, late=late)
    if late:
        return {"kind": "finish", "target": target, "late": late}  # oldest first: every one is recorded, the newest carries the run's own
    confirmed = damage.registry.confirmed_damage(damage.FILE_CORPUS)
    if confirmed is None:
        return None
    if resumable is not None:
        return {
            "kind": "resume", "target": target, "resume": resumable, "tables": confirmed["tables"],
            "pages_unread": int(confirmed.get("pages_unread") or 0),
        }
    return {"kind": "repair", "target": target, "tables": confirmed["tables"], "pages_unread": int(confirmed.get("pages_unread") or 0)}


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
    damage.registry.settle_interrupted_repairs()  # a record an earlier process left ``running`` is not a repair under way
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
        from src.database.writer import gate_enabled, write_lock

        if work["kind"] != "finish" and not gate_enabled():
            # With the gate off a save made while the copy runs is not held back, and ``write_lock()`` does nothing: it would commit into
            # the damaged file and be lost under the new one (the deep read of E3, NEW-1). Nothing is copied.
            raise Declined(
                "write-gate-off",
                "the single-writer gate is switched off (OO_WRITE_GATE=0), so a save made while the library is copied could not be held "
                "back and would be lost",
            )
        with _exclusive_window():
            if work["kind"] == "repair":
                armed = _prepare(work, target, report, ctx)
            _quiet(QUIESCE_S)
            # The write gate for the WHOLE repair: nothing the app saves can land in the damaged file between a row being
            # read and the new file replacing it (a save waits; the job row says so).
            with write_lock():
                if work["kind"] == "finish":
                    report["outcome"] = _finish(work, report, ctx)
                elif work["kind"] == "resume":
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
        # The TYPE only, never the text or a traceback: the copy runs on keyed connections, so what a driver says (and the error it
        # was raised from, which a traceback prints too) can carry a statement that holds the passphrase. The record above carries
        # the driver's first line, scrubbed; this log carries neither.
        _LOG.warning("database repair failed (%s)", type(exc).__name__)
        raise
    finally:
        report["finished_at"] = time.time()
        report["seconds"] = round(time.monotonic() - started, 1)
        if armed or (work["kind"] != "repair" and report["outcome"] == "repaired"):
            # A finished resume or finish clears the attempt the cut start left behind (it counted one that never saw its end).
            _disarm()
        _record(**report)
        state = {"repaired": "done", "stopped": "stopped"}.get(str(report["outcome"]), "refused" if report["outcome"] == "declined" else "failed")
        damage.registry.repair_upsert(rec_id, **_registry_fields(report, state))
        if report["outcome"] != "repaired":
            with contextlib.suppress(Exception):
                _remove_scratch(target)
        elif report.get("sidecars_spent"):
            _settle_sidecars(target, list(report["sidecars_spent"]))
    return report


def _settle_sidecars(target: Path, names: list[str]) -> None:
    """The sidecars of a switch that ran are spent ONLY once the repair's record is on the drive (the deep read of E3, NEW-6). The record
    is how the kept file (the size of the whole library) is named and, thirty days later, removed; it is written by a daemon thread that
    does not ``fsync`` and swallows its errors, so a kill or a full drive between the switch and that write left neither the record nor
    the sidecar. The record is now written here, ``fsync``ed (file and folder), and a record that cannot be made durable leaves the
    sidecar where it is: the next start finds a switch that ran and writes the record again."""
    if not damage.registry.flush_durable():
        _LOG.warning(
            "database repair: the record of the repair could not be made durable, so its sidecar stays and the next start writes the "
            "record again"
        )
        return
    for name in names:
        with contextlib.suppress(OSError):
            (target.parent / name).unlink()
    _fsync_dir(target.parent)


def _registry_fields(report: dict[str, Any], state: str) -> dict[str, Any]:
    keep = (
        "reason", "failure", "free_mb", "needed_mb", "seconds", "kept_rows", "unreadable_ids", "open_ended", "kept_file", "kept_file_bytes",
        "copy_bytes", "reconnects", "orphans", "orphans_verdict_tables", "set_null", "stand_ins", "stand_ins_note", "id_reuse_possible",
        "replaced_text_values", "tables", "search_index", "indexes_seconds", "encrypted",
        "preflight", "post_steps", "resumed", "clean_at", "kept_file_ino", "kept_file_dev", "kept_wal_ino", "kept_wal_bytes",
        "kept_file_removal_after", "kept_file_removal_withheld", "kept_file_disk_unread_pages", "disk_unread_pages", "disk_unread_first",
        "check_pages_unread",
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
    watch = _open_probe(target)
    try:
        return _copy_and_swap(work, target, partial, stamp, report, ctx, progress, watch, t0)
    finally:
        watch.close()


def _copy_and_swap(
    work: dict[str, Any], target: Path, partial: Path, stamp: str, report: dict[str, Any], ctx: JobContext | None, progress: Any,
    watch: _Probe, t0: float,
) -> str:
    try:
        copy_report = salvage.Salvage(target, partial, cancel=_CANCEL, progress=progress).run()
    except salvage.SalvageFailed as exc:
        report["failure"] = f"{exc.where}: {exc.reason}"
        raise
    report["copy_seconds"] = round(time.monotonic() - t0, 1)
    report["page_size"] = copy_report.get("page_size")
    # What the DRIVE could not read, measured raw while the file is quiescent: the kept copy is never removed on the strength of
    # a file the disk itself could not give (see :func:`_disk_unread_pages`). The check's own count of pages it could not read
    # (the page pass answers them apart from damage) is carried beside it.
    report["check_pages_unread"] = int(work.get("pages_unread") or 0)
    report["disk_unread_pages"], report["disk_unread_first"] = _disk_unread_pages(target, int(copy_report.get("page_size") or 4096), _CANCEL)
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
        orphans_verdict_tables=copy_report.get("orphans_verdict_tables"),
        set_null=copy_report.get("set_null"),
        stand_ins=copy_report.get("stand_ins"),
        stand_ins_note=copy_report.get("stand_ins_note"),
        id_reuse_possible=copy_report.get("id_reuse_possible"),
        copy_bytes=partial.stat().st_size,
        page_size=copy_report.get("page_size"),
        encrypted=copy_report.get("encrypted"),
    )
    report["run_seconds"] = int(time.monotonic() - t0) + 1  # what the sidecar's clean-read time is checked against
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_SWITCHING))
    _swap(partial, target, stamp, report, probe=watch)
    return "repaired"


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_read_time(doc: dict[str, Any]) -> str:
    """When the repaired file first read clean, as the sidecar says it, when that is a time the repair can have had: not after the sidecar
    was made and not earlier than the repair had been running when it was made (the clean read happens in between). R129's thirty days
    run from it, so a value outside that (a past one would remove the kept copy at once, a future one would keep it for ever) is not
    believed and the time the sidecar was made is used instead, which only ever makes the file live longer (the deep read of E3)."""
    created = _parse_time(doc.get("created_at")) or datetime.now(UTC)
    clean = _parse_time(doc.get("clean_at"))
    if clean is not None and created - timedelta(seconds=_int(doc.get("run_seconds")) + 1) <= clean <= created:
        return clean.isoformat(timespec="seconds")
    return created.isoformat(timespec="seconds")


def _carry_from(report: dict[str, Any], doc: dict[str, Any], target: Path) -> None:
    """What the start that made the copy measured, read back from its sidecar for the start that finishes the switch: every number and
    list the record needs (``_CARRIED``: the deep read of E3 found the orphans, the search index and the encryption flag dropped), the
    first clean read (R129's clock runs from it, not from the start that finished the swap), and what the drive could not read. A
    value that is not the kind of value it should be is not believed: a count is a count or zero, and a drive measurement that is not
    a whole number is no measurement (the resume measures it again)."""
    report["resumed"] = True
    for key in _CARRIED:
        if key in doc:
            report[key] = doc[key]
    for key in ("kept_rows", "unreadable_ids", "check_pages_unread"):
        report[key] = _int(doc.get(key))
    report["open_ended"] = bool(doc.get("open_ended"))
    report["tables"] = doc["tables"] if isinstance(doc.get("tables"), list) else []
    report["disk_unread_first"] = doc["disk_unread_first"] if isinstance(doc.get("disk_unread_first"), list) else []
    measured = doc.get("disk_unread_pages")
    report["disk_unread_pages"] = measured if type(measured) is int and measured >= 0 else None
    report["page_size"] = doc["page_size"] if type(doc.get("page_size")) is int and doc["page_size"] > 0 else None
    report["clean_at"] = _clean_read_time(doc)


def _resume(work: dict[str, Any], report: dict[str, Any], ctx: JobContext | None) -> str:
    resume = work["resume"]
    doc = resume["doc"]
    target: Path = work["target"]
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_SWITCHING))
    _carry_from(report, doc, target)
    # What this start's own check could not read counts beside what the start that made the copy found: a resume after a start whose
    # check found unreadable pages must not decide on that start's figure alone (the deep read of E3, NEW-3).
    report["check_pages_unread"] = max(_int(report.get("check_pages_unread")), _int(work.get("pages_unread")))
    if report["disk_unread_pages"] is None:
        # A sidecar that does not carry the measurement (never written by this code): measured now, on the damaged file, which the
        # fingerprint check of ``find_resumable`` has just shown is still the file the copy was made from.
        report["disk_unread_pages"], report["disk_unread_first"] = _disk_unread_pages(target, int(report.get("page_size") or 4096), _CANCEL)
    stamp = str(doc.get("stamp") or datetime.now(UTC).strftime(STAMP_FORMAT))
    _swap(
        resume["finished"], target, stamp, report, sidecar=resume["sidecar"], damaged=target.parent / str(doc["damaged"]),
        expect=doc["source"],
    )
    return "repaired"


def _kept_facts(report: dict[str, Any], doc: dict[str, Any], target: Path) -> Path:
    """What a switch that ran left, read from its sidecar and the files as they are: the record's numbers, the kept file's identity and
    removal date. Returns the kept file."""
    damaged = target.parent / str(doc["damaged"])
    _carry_from(report, doc, target)
    _note_what_was_set_aside(report, damaged)
    report["kept_file"] = damaged.name
    with contextlib.suppress(OSError):
        report["kept_file_bytes"] = damaged.stat().st_size
    return damaged


def _finish(work: dict[str, Any], report: dict[str, Any], ctx: JobContext | None) -> str:
    """A cut right after the replace: the new file is the library and the damaged file is kept beside it, but the repair's record
    was never written, the corpus epoch and the source counts were never brought up to date, and the attempt marker still counts
    a start that did not see its end. Nothing is copied or switched here: the record is written from the sidecar and the file as
    it is, the follow-up steps run, and the sidecar is spent once the record is on the drive (the deep read of E3, S2 and NEW-6). Every
    sidecar a cut left is finished, not only the newest (NEW-10): an older one's kept file would otherwise be named in memory only and
    never removed; each gets a record of its own, and the newest's is the run's."""
    late = work["late"]
    target: Path = work["target"]
    if ctx is not None:
        ctx.set_progress(detail=_frame(FRAME_SWITCHING))
    spent = []
    for earlier in late[:-1]:
        older: dict[str, Any] = {"kind": "finish"}
        _kept_facts(older, earlier["doc"], target)
        damage.registry.repair_upsert(
            uuid.uuid4().hex[:8], file=damage.FILE_CORPUS, trigger="boot", kind="finish", folder=str(target.parent),
            started_at=datetime.now(UTC).isoformat(timespec="seconds"), **_registry_fields(older, "done"),
        )
        spent.append(earlier["sidecar"].name)
    newest = late[-1]
    damaged = _kept_facts(report, newest["doc"], target)
    report["post_steps"] = _after_the_swap()
    report["sidecars_spent"] = [*spent, newest["sidecar"].name]
    _LOG.warning(
        "database repair: a switch to a repaired library file that a stop interrupted was finished (%s rows kept); the damaged file "
        "is kept as %s",
        report.get("kept_rows"), damaged.name,
    )
    return "repaired"


#: How long the checkpoint that empties the live log waits for a reader that holds it (ms). WHAT IT PROTECTS: a boot that waits for a
#: request that will never end against a swap that gives up quickly and is tried again at the next start; a reader that is only slow
#: gets this long.
FOLD_WAIT_MS = 2000


#: How long the fold of the log is tried again when a connection that is reading holds frames back (seconds, in steps of half a second).
#: WHAT IT PROTECTS: hours of copy against a reader that is only slow (a request that reads for a moment), while a reader that holds the
#: log for longer than this is refused with the numbers and the repair is made again at the next start; a stop ends the wait at once.
FOLD_RETRY_S = 30.0


def _empty_the_log(target: Path, watch: _Probe) -> None:
    """Fold the live file's write-ahead log into the file, BEFORE the file's identity is recorded or a name is given to it. A commit
    sits in the log until a checkpoint moves it into the file; ``dispose_engine`` closes the pool's idle connections and SQLite
    folds the log in as the last one closes, but a connection a request has checked out stays open and keeps the log. Unlinking a
    log that still holds commits loses them, and a copy made before them would replace the file that has them (the deep read of
    E3, B2). The restore's swap does the same before it lets go of the engine. The checkpoint runs on the data-version connection (``watch``):
    any other connection's TRUNCATE would move that connection's version and read as a save.

    A log that is still not EMPTY afterwards is accepted when every frame in it was moved into the file (the checkpoint says how many
    there are and how many it moved): a reader that is still reading keeps the log from being truncated, not from being folded, and a
    log whose frames are all in the file loses nothing when it is unlinked. Otherwise the fold is tried again, with the gate held (no
    gated save can add frames), for :data:`FOLD_RETRY_S`; then it is refused, with every file as it was and the numbers in the text
    (the deep read of E3, NEW-11: a reader that held the log for two seconds threw away a whole copy, and the text claimed unsaved
    bytes where the checkpoint had copied every frame and only the truncate was blocked)."""
    wal = _side(target, "-wal")
    if not wal.exists():
        return
    deadline = time.monotonic() + FOLD_RETRY_S
    while True:
        frames = watch.fold(FOLD_WAIT_MS)
        left = 0
        with contextlib.suppress(OSError):
            left = int(wal.stat().st_size)
        if not left:
            return
        if frames is not None and (frames[0] < 0 or frames[1] >= frames[0]):
            return
        if _CANCEL.is_set():
            raise salvage.SalvageStopped
        if time.monotonic() >= deadline:
            break
        _CANCEL.wait(0.5)
    held = "" if frames is None else f" ({max(0, frames[0] - frames[1]):,} of {frames[0]:,} pages in the log are not in the file yet)"
    raise Declined(
        "writer-busy",
        f"a connection to the library was still reading after {FOLD_RETRY_S:.0f} s and kept saves in its write-ahead log from being "
        f"moved into the file{held}, so nothing was switched",
    )


def _swap(
    source: Path, target: Path, stamp: str, report: dict[str, Any], *, sidecar: Path | None = None, damaged: Path | None = None,
    expect: dict[str, int] | None = None, probe: _Probe | None = None,
) -> Path:
    """Put the finished copy under the live name, keeping the damaged file. ``source`` is the ``.partial`` copy of a fresh
    repair (renamed here once the damaged file's identity is recorded) or the finished copy of an interrupted one, whose
    sidecar's ``source`` identity is ``expect``: the damaged file must STILL be that file once its log is folded in, or the copy is
    stale (a save committed since would be lost under it) and is discarded. ``probe`` is the connection that was opened before the
    copy began (a resume has none, and opens its own here, before the fold): inside the swap window it is asked whether any
    other connection committed since, and if so nothing is switched."""
    from src.backup.merge import swap_in_corpus
    from src.database.session import dispose_engine, init_db

    _quiet(10.0)  # nothing new could start under the exclusive window: this only confirms what the first wait found
    dispose_engine()
    watch = probe if probe is not None else _open_probe(target)  # a resume opens it here: before the fold, which it runs
    try:
        _empty_the_log(target, watch)
        now = fingerprint(target)
        if damaged is None:
            damaged = _damaged_name(target, stamp)
        finished = source
        if expect is not None and now != expect:
            assert sidecar is not None
            for stale in (finished, sidecar):
                with contextlib.suppress(OSError):
                    stale.unlink()
            _drop_extra_names(target, damaged)
            raise Declined(
                "copy-stale",
                "the library file was written to after the copy was made, so the copy is discarded and a new one is made at the next start",
            )
        if sidecar is None:
            # The damaged file's identity AFTER the engine let go and its log was folded in, recorded before the copy is given its
            # final name: a copy with no sidecar is scratch, a copy with one is resumable.
            finished = source.with_name(source.name[: -len(".partial")])
            sidecar = finished.with_name(finished.name + ".json")
            doc = {
                "schema": 1,
                "stamp": stamp,
                "finished": finished.name,
                "finished_ino": int(os.stat(source).st_ino),  # a rename keeps it: ``_swap_ran`` proves the replace by it
                "damaged": damaged.name,
                "source": now,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "run_seconds": _int(report.get("run_seconds")),
                **{k: report[k] for k in _CARRIED if k in report},
            }
            _write_json_atomic(sidecar, doc)
            os.replace(source, finished)
        # The copy is written with ``synchronous=OFF``: its data is made durable BEFORE any name is given to it and the folder entries
        # before the replace (the deep read of E3, S7), so a power cut after the switch cannot leave a library whose last pages never
        # reached the drive.
        _durable(finished)
        _fsync_dir(target.parent)
        made: list[Path] = []
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
        _note_what_was_set_aside(report, damaged)

        def written_to_since() -> None:
            """Inside the swap window (every earlier connection is refused) and before anything changes on disk: has ANY connection
            committed to the damaged file since the copy began, or has the file's identity moved since the sidecar recorded it? Either
            way a save is in the file the copy does not have, and nothing is switched."""
            try:
                moved = watch.moved()
            except Exception as exc:  # noqa: BLE001 - the type only: the connection is keyed
                # Could not tell (a writer kept SQLite's lock): the copy and its sidecar stay, and the next start resumes it if the
                # file is still the one the sidecar recorded, or discards it if not.
                raise Declined(
                    "writer-busy", f"another connection kept the library's write lock, so it could not be told whether it was written to ({type(exc).__name__})"
                ) from exc
            if moved or fingerprint(target) != now:
                raise Declined(
                    "saved-during-the-copy",
                    "something was saved to the library file after the repaired copy was started, so the copy would have missed it and "
                    "nothing was switched; the repair is made again at the next start",
                )
            watch.close()  # nothing may hold the file while its log names are removed and it is replaced

        try:
            swap_in_corpus(finished, target, check=written_to_since)
        except library_generation.LibraryBusy as busy:
            raise Declined("writer-busy", str(busy)) from busy
        except Declined as refusal:
            if refusal.code == "saved-during-the-copy":
                # AFTER the window has ended (it reads the copy's existence to tell whether the file moved, and gives the earlier
                # connections their validity back when it did not): the copy is stale and is the app's own scratch.
                for stale in (finished, sidecar):
                    with contextlib.suppress(OSError):
                        stale.unlink()
                _drop_extra_names(target, damaged)
            raise
    finally:
        watch.close()
    dispose_engine()
    _fsync_dir(target.parent)
    report["kept_file"] = damaged.name
    with contextlib.suppress(OSError):
        report["kept_file_bytes"] = damaged.stat().st_size
    init_db()
    report["post_steps"] = _after_the_swap()
    report["sidecars_spent"] = [sidecar.name]  # removed by ``run`` once the record is on the drive
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
    unread = max(int(report.get("disk_unread_pages") or 0), int(report.get("check_pages_unread") or 0))
    if unread:
        # A file the drive could not read is kept, not removed after the thirty days: no date is recorded, the record says why, and
        # the notice tells the person to check the drive (the coordinator's ruling of 2026-10-06 on the SQLite 3.43 read-error case).
        report["kept_file_removal_withheld"] = "disk-read-failed"
        report["kept_file_disk_unread_pages"] = unread
    else:
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
    # Each hold reads the registry's own state and NOT ``latched()``/``verifying()``: those answer False under ``OO_DAMAGE_GUARD=0``,
    # which turns off the PAUSE and must not turn off the holds of a removal that is waiting for exactly this. And only a repair of
    # THIS process counts as running: one a crash, a power cut or a stop ended is ``interrupted`` (``settle_interrupted_repairs``).
    if REPAIR_JOB.status().get("state") == "running" or damage.registry.repairing_now():
        return "repair-running"
    if damage.registry.check_is_running():
        return "check-running"
    if damage.registry.latch_is_set(damage.FILE_CORPUS):
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
    * a copy whose repair recorded ``kept_file_removal_withheld`` (the drive could not read a page of the damaged file) is never
      removed, whatever date a record carries: it is not listed, nothing is written, and the notice says to check the drive;
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
            if rec.get("kept_file_removal_withheld"):
                continue  # the drive could not read the file: it is kept, whatever date a record may carry
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
    if rec.get("kept_file_removal_withheld") or int(rec.get("kept_file_disk_unread_pages") or 0) > 0:
        return {"outcome": "withheld", "reason": "disk-read-failed"}  # the one place a file goes: never one the drive could not read

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
    except Exception as exc:  # noqa: BLE001
        # The TYPE only (see ``run``): these two write through the keyed engine.
        _LOG.warning("database repair: the corpus epoch was not bumped (%s)", type(exc).__name__)
        out["corpus_epoch"] = None
    try:
        from sqlalchemy import update

        from src.database.models import Source
        from src.database.session import session_scope

        with session_scope() as session:
            result = session.execute(update(Source).values(article_count=None))
            out["source_counts_cleared"] = int(getattr(result, "rowcount", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("database repair: the stored source counts were not cleared (%s)", type(exc).__name__)
        out["source_counts_cleared"] = None
    return out


def _write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    with open(tmp, "rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)
