"""R833 (row 426): an import refused before activation removes the safety copy it made itself, and only that one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Each import run takes a full copy of the live corpus before it changes anything (the pre-restore safety net, R827
R5/R6). Only a commit pruned old copies, so a run refused before its swap left its copy behind: lane S measured 5.4 GB per
refused run (row 422), and three refusals in a row could fill the disk the free-space check guards.

WHAT IS REMOVED, AND WHEN (R833):

1. Only a copy THIS process made in THIS run, known by what was recorded when it was made: its path, and the (device,
   inode, size, modification and change times) of the file the copy wrote, so a new file on a reused inode is not it. Never a name pattern: a ``pre-restore-*.db`` this process did not make is
   never touched here.
2. Only when the durable record says the run never reached its swap. The record (``import-safety-copies.json`` in the
   data folder) says ``made`` when the copy is made and ``activated`` just before the swap; a record that is missing,
   unreadable or says anything else is read as "after activation", and the copy is kept. The in-memory record is
   dropped first at the swap, so even a record that could not be rewritten never lets an activated copy go.
3. Only when the live corpus is still the file the copy was taken from, unchanged since the copy ended: the same (device, inode), size and
   modification time, the same first 100 bytes, and the same log state (the ``-wal`` file's size, time and 32-byte
   header). The bytes are read through :func:`src.database.connect.store_reader`, which never closes a descriptor
   SQLite still relies on (R789), and only an HMAC of them under a key held in memory is kept: no header or salt byte is
   ever written anywhere (R828). Anything that cannot be confirmed keeps the copy, and the report says why.
4. The removal is an ordinary delete of one regular file, never through a link, inside the data folder (R783/R799),
   worded "safety copy removed: the import was refused before any change", never "destroyed" or "wiped".
5. Nothing here runs at a start: a crash between the refusal and the removal leaves the copy, and it is listed with the
   others (:func:`leftovers`) rather than removed silently.

Copies made after an activation, by an earlier run or by another process stay; :func:`leftovers` counts them and their
total size for the import report and the backups screen.

ROW 428 (R835 (b)): ONE COPY REMOVED BY HAND, BY ONE CLICK. :func:`list_copies` lists every copy with what the app recorded when
it made it; :func:`remove_copy` deletes one, and only one the record names:

1. Identity is what was recorded when the copy was made: its name in the data folder and the (device, inode, size, modification
   and change times) of the file, written into the durable record beside its state (never a byte of the file). It is checked
   through a descriptor held on the file at delete time; a missing record, a missing entry or a mismatch refuses with "could not
   be identified" and touches nothing. A copy with no record is never offered, only counted.
2. Refused while an import, restore, backup, snapshot or erase is running (the caller names them, :func:`remove_copy`'s
   ``busy``), and for the copy of the most recent import that was refused or did not finish until a later import has completed
   and been checked (:func:`note_run_verified`, :data:`VERIFIED_KEY`).
3. An ordinary delete: one regular file, never through a link, inside the data folder (R783/R799), worded "deleted", never
   "erased", "destroyed" or "securely removed" (R797/R815). The freed size is the drive's free space measured before and
   after the delete, never assumed, and absent when it did not go up (R785). Its at-rest record entry goes with it (R828).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

#: The durable record of each safety copy's state: ``{"<file name>": {"state": "made" | "activated", "at": iso}}``. Names and
#: states only; never a byte of the corpus.
RECORD_NAME = "import-safety-copies.json"
MADE = "made"
ACTIVATED = "activated"
#: The record's two keys that are not a copy's name. ``SEQ_KEY``: the last serial given to a copy (each copy's entry carries
#: its own ``seq``). ``VERIFIED_KEY``: ``{"covers": <seq>}``, the highest serial when the last import run completed and was
#: checked. Serials, never the clock: a clock stepped back must never make a later copy look older than the mark.
SEQ_KEY = "~seq"
VERIFIED_KEY = "~last-verified-run"
#: R843: ``{"covers": <seq>}``, the highest serial when the last import run ended "done" WITHOUT a whole-file check of the
#: corpus it left (``note_run_unchecked``). It frees nothing; it only says why the copies it covers are still held.
UNCHECKED_KEY = "~last-done-unchecked"
_RESERVED = (SEQ_KEY, VERIFIED_KEY, UNCHECKED_KEY)
#: The exact name of a safety copy: ``pre-restore-<UTC stamp>.db``. ASCII digits only; \Z: a name ending in a newline is
#: never one.
COPY_NAME = r"^pre-restore-[0-9]{8}T[0-9]{6}Z\.db\Z"

REMOVED = "safety copy removed: the import was refused before any change"

#: Why a copy was kept (the report says which).
KEPT_NOT_OURS = "kept: this run did not create it"
KEPT_ACTIVATED = "kept: the import may already have changed your corpus (its record says so, or could not be read)"
KEPT_UNCONFIRMED = "kept: the corpus could not be confirmed unchanged since the copy was made"
KEPT_CHANGED = "kept: your corpus changed after the copy was made"
KEPT_NOT_THE_FILE = "kept: the file at that name is not the copy this run made"
KEPT_NOT_REMOVED = "kept: the copy could not be removed"

_KEY = secrets.token_bytes(32)  # process-local: what the state holds is an HMAC under it, never the bytes (R828)
_LOCK = threading.Lock()


@dataclass(frozen=True)
class _Own:
    path: str
    file: tuple[int, ...]  # (st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns) of the copy as it was made: a reused inode differs
    live: dict | None  # the live corpus as the copy ended; None when it could not be read


_OWN: dict[str, _Own] = {}


def _file_id(st: os.stat_result) -> tuple[int, ...]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _mac(b: bytes) -> str:
    return hmac.new(_KEY, b, hashlib.sha256).hexdigest()


def _head_of(path: Path, n: int, ident: tuple[int, int]) -> str | None:
    """HMAC of the first ``n`` bytes of the file at ``path``, only if the bytes read are of the file ``ident`` names. R789: through
    the lock-safe reader."""
    from src.database.connect import store_reader

    with store_reader(path) as fd:
        head = os.pread(fd, n, 0)
        after = os.fstat(fd)
    if (after.st_dev, after.st_ino) != ident:
        return None
    return _mac(head)


def live_state() -> dict | None:
    """The live corpus's identity and change state, or None when any part of it cannot be read (an unread state confirms
    nothing). Never raises."""
    from src.backup.sqlite_backup import live_db_path

    try:
        live = live_db_path()
        st = os.stat(live)
        if not stat.S_ISREG(st.st_mode):
            return None
        ident = (st.st_dev, st.st_ino)
        head = _head_of(live, 100, ident)
        if head is None:
            return None
        wal_path = live.with_name(live.name + "-wal")
        try:
            wst = os.stat(wal_path)
        except FileNotFoundError:
            wal: Any = None
        else:
            if not stat.S_ISREG(wst.st_mode):
                return None
            wal_head = _head_of(wal_path, 32, (wst.st_dev, wst.st_ino)) if wst.st_size else ""
            if wal_head is None:
                return None
            wal = [wst.st_size, wst.st_mtime_ns, wal_head]
        return {"ident": list(ident), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "head": head, "wal": wal}
    except Exception:  # noqa: BLE001 - an unread state confirms nothing: the copy is kept
        return None


def _record_path() -> Path:
    return data_dir() / RECORD_NAME


def read_record() -> dict | None:
    """The durable record, or None when it is missing or unreadable (both read as "after activation")."""
    try:
        got = json.loads(_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _record_for_write() -> dict:
    """The record to rewrite: ``{}`` only when there is none; a record that is there but cannot be read raises ``OSError``,
    so a write never replaces the other copies' entries with nothing (row 428 security read)."""
    path = _record_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        got = json.loads(raw)
    except ValueError as exc:
        raise OSError("the safety-copy record could not be read; it is left as it is") from None
    if not isinstance(got, dict):
        raise OSError("the safety-copy record could not be read; it is left as it is")
    return got


def _set_state(name: str, state: str | None, extra: dict | None = None, *, new_seq: bool = False) -> None:
    """Write ``state`` for ``name`` (None removes the entry), dropping the entries of copies no longer in the folder. The
    entry keeps what was recorded when the copy was made (row 428: its identity), plus ``extra``; ``new_seq`` gives it the
    next serial. Raises ``OSError`` when the record cannot be read or written."""
    from src.safety.file_lock import atomic_replace, file_lock
    from src.utils.interrupts import kept_items

    path = _record_path()
    with file_lock(path):
        cur = _record_for_write()
        folder = path.parent
        # kept_items: a filtered comprehension in a frame of its own, never under this file lock's cleanup (src/utils/interrupts.py)
        out = kept_items(
            cur, lambda k, v: k != name and (k in _RESERVED or (isinstance(v, dict) and (folder / k).exists()))
        )
        if state is not None:
            old = cur.get(name)
            entry = {**(old if isinstance(old, dict) else {}), **(extra or {}), "state": state,
                     "at": datetime.now(UTC).isoformat(timespec="seconds")}
            if new_seq:
                seq = cur.get(SEQ_KEY)
                seq = (seq if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0 else 0) + 1
                out[SEQ_KEY] = seq
                entry["seq"] = seq
            out[name] = entry
        atomic_replace(path, json.dumps(out, sort_keys=True))


def note_made(net: Path) -> None:
    """Record ``net`` as a safety copy this process made in this run, with the live corpus's state as the copy ended. A copy
    is taken under the write gate with the log drained, so its end is the moment the two match; a later change to the
    corpus, the swap above all, moves that state, and the copy is then kept. Never raises: a copy that could not be
    recorded is simply never removed here."""
    try:
        st = os.lstat(net)
        if not stat.S_ISREG(st.st_mode):
            return
        live = live_state()
        # Row 428: what identifies the copy later, for a removal by hand after a restart (never a byte of it).
        _set_state(net.name, MADE, {"file": list(_file_id(st)), "made_ns": time.time_ns()}, new_seq=True)
        with _LOCK:
            _OWN[str(net)] = _Own(str(net), _file_id(st), live)
    except Exception:  # noqa: BLE001 - unrecorded = kept, the safe side
        with _LOCK:
            _OWN.pop(str(net), None)


def forget(net: Path) -> None:
    """The copy is gone another way (a read-back that failed removed it): drop both records. Never raises."""
    with _LOCK:
        _OWN.pop(str(net), None)
    with suppress(Exception):
        _set_state(Path(net).name, None)


def note_activation(net: Path | None) -> None:
    """Just before a swap: the copy is now the state to return to. The in-memory record goes first (it cannot fail), so
    nothing in this process removes the copy even if the durable record below cannot be written; the durable record then
    says ``activated``. Never raises: the swap's own course is not changed here."""
    if net is None:
        return
    with _LOCK:
        _OWN.pop(str(net), None)
    with suppress(Exception):
        _set_state(Path(net).name, ACTIVATED)


def is_own(net: Path) -> bool:
    with _LOCK:
        return str(net) in _OWN


def remove_if_refused_before_activation(net: Path) -> dict:
    """The R833 removal: ``{"removed": True, "name", "bytes", "message": REMOVED}`` or ``{"removed": False, "name", "bytes",
    "message": <why it was kept>}``. Never raises; anything unconfirmed keeps the copy."""
    net = Path(net)
    with _LOCK:
        own = _OWN.get(str(net))
    out: dict = {"removed": False, "name": net.name, "bytes": None}
    if own is None:
        return {**out, "message": KEPT_NOT_OURS}
    out["bytes"] = own.file[2]
    entry = (read_record() or {}).get(net.name)
    if not isinstance(entry, dict) or entry.get("state") != MADE:
        return {**out, "message": KEPT_ACTIVATED}
    if own.live is None:
        return {**out, "message": KEPT_UNCONFIRMED}
    now = live_state()
    if now is None:
        return {**out, "message": KEPT_UNCONFIRMED}
    if now != own.live:
        return {**out, "message": KEPT_CHANGED}
    try:
        folder = data_dir()
        if net.parent != folder:
            return {**out, "message": KEPT_NOT_THE_FILE}
        dfd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            st = os.stat(net.name, dir_fd=dfd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or _file_id(st) != own.file:
                return {**out, "message": KEPT_NOT_THE_FILE}
            # By name through the folder handle, right after the identity check: there is no unlink-by-inode, and nothing in
            # the app renames a file onto a pre-restore name, so the gap between the stat and the unlink is accepted.
            os.unlink(net.name, dir_fd=dfd)
        finally:
            os.close(dfd)
    except FileNotFoundError:
        return {**out, "message": KEPT_NOT_THE_FILE}
    except OSError:
        return {**out, "message": KEPT_NOT_REMOVED}
    with _LOCK:
        _OWN.pop(str(net), None)
    with suppress(Exception):
        _set_state(net.name, None)
    with suppress(Exception):
        from src.database import at_rest_state

        at_rest_state.forget_copy(net)  # R823 / R828 (4): its at-rest record entry goes with the file
    return {**out, "removed": True, "message": REMOVED}


def leftovers() -> dict:
    """The safety copies in the data folder, by count and total size (R833 point 3): ``{"count", "bytes", "names"}``. File
    names only: the folder's path is added by the import status at read time, for the screen, and never stored (R835). Regular
    files of the exact ``pre-restore-<UTC stamp>.db`` shape only; never follows a link. Never raises."""
    import re

    shape = re.compile(COPY_NAME)
    count, total, names = 0, 0, []
    try:
        for entry in os.scandir(data_dir()):
            if not shape.match(entry.name):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                count += 1
                total += st.st_size
                names.append(entry.name)
    except OSError:
        return {"count": None, "bytes": None, "names": []}
    return {"count": count, "bytes": total, "names": sorted(names)}


# --------------------------------------------------------------------------------------------------------------------------
# Row 428 (R835 (b)): one safety copy removed by hand.
# --------------------------------------------------------------------------------------------------------------------------

DELETED = "Safety copy deleted."
DELETED_FREED = "Safety copy deleted. Free space on that drive went up by {size}."
NOT_IDENTIFIED = "This safety copy could not be identified, so nothing was deleted. You can delete it by hand from your data folder."
LATEST_UNFINISHED = (
    "This safety copy was made after the last import that completed and was checked. It can be deleted once a later "
    "import has completed and been checked."
)
NOT_CHECKED_WHOLE = (
    "The corpus has not been checked whole since this safety copy was made. It can be deleted once a later import has "
    "completed and the whole corpus has been checked."
)
NOT_DELETED = "The safety copy could not be deleted."
BUSY = "A safety copy cannot be deleted while an import, restore, backup, snapshot or erase is running."

_DELETE_LOCK = threading.Lock()


def current_seq() -> int | None:
    """The last serial given to a copy (0 when none yet), or None when the record cannot be read."""
    rec = read_record()
    if rec is None:
        return 0 if not _record_path().exists() else None
    seq = rec.get(SEQ_KEY, 0)
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else None


def _mark(key: str, covers: int | None) -> None:
    """Set ``key`` to ``{"covers": n}``: ``covers`` (the serial the caller read when its evidence held), never above the
    record's own serial, and never below the mark already there (a mark only moves forward)."""
    from src.safety.file_lock import atomic_replace, file_lock

    path = _record_path()
    with file_lock(path):
        cur = _record_for_write()
        seq = cur.get(SEQ_KEY)
        top = seq if isinstance(seq, int) and not isinstance(seq, bool) else 0
        want = top if covers is None else min(int(covers), top)
        old = cur.get(key)
        had = old.get("covers") if isinstance(old, dict) else None
        if isinstance(had, int) and not isinstance(had, bool) and had > want:
            want = had
        cur[key] = {"covers": want}
        atomic_replace(path, json.dumps(cur, sort_keys=True))


def note_run_verified(covers: int | None) -> None:
    """An import run completed and its corpus was checked whole: every copy up to serial ``covers`` -- the serial read
    when that check passed (R843), so a copy made after the check is never covered -- is no longer the copy of the most
    recent unfinished run. ``covers`` is required and None moves nothing: no serial read at the check is no evidence for
    any copy. Never raises: an unwritten mark only keeps the newest copies protected."""
    if covers is None:
        return
    with suppress(Exception):
        _mark(VERIFIED_KEY, covers)


def note_run_unchecked(covers: int | None = None) -> None:
    """R843: an import run ended "done" but the corpus it left was not checked whole in that state, so the mark does NOT
    move; the copies up to serial ``covers`` (read when the run's end decided) are noted as held for that reason
    (:data:`NOT_CHECKED_WHOLE`). Never raises."""
    with suppress(Exception):
        _mark(UNCHECKED_KEY, covers)


def _hold_reason(record: dict, name: str) -> str:
    """Why a held-back copy is held: the corpus was not checked whole since a run that ended "done" (R843), or the copy
    is newer than the last run that completed and was checked."""
    got = _recorded(record.get(name))
    mark = record.get(UNCHECKED_KEY)
    covers = mark.get("covers") if isinstance(mark, dict) else None
    if got is not None and isinstance(covers, int) and not isinstance(covers, bool) and covers >= got[2]:
        return NOT_CHECKED_WHOLE
    return LATEST_UNFINISHED


def _int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _recorded(entry: Any) -> tuple[tuple[int, ...], int, int] | None:
    """``(file identity, made_ns, seq)`` of a record entry made with all three, else None."""
    if not isinstance(entry, dict):
        return None
    f, made, seq = entry.get("file"), entry.get("made_ns"), entry.get("seq")
    if not (isinstance(f, list) and len(f) == 5 and all(_int(x) for x in f)):
        return None
    if not (isinstance(made, int) and not isinstance(made, bool) and isinstance(seq, int) and not isinstance(seq, bool)):
        return None
    return tuple(f), made, seq


def _held_back(record: dict, name: str) -> bool:
    """Whether ``name`` may not be deleted yet: every copy made after the last import run that completed and was checked
    (a serial above the mark's), so the copy of the most recent refused or unfinished run is always among them, whatever
    else made a copy since (a restore outside the import queue never sets the mark). A record without a serial for it
    holds it back too."""
    got = _recorded(record.get(name))
    if got is None:
        return True
    mark = record.get(VERIFIED_KEY)
    covers = mark.get("covers") if isinstance(mark, dict) else None
    return not (isinstance(covers, int) and not isinstance(covers, bool) and covers >= got[2])


def _plaintext(dfd: int, name: str, ident: tuple[int, int]) -> bool | None:
    """True when the file's first 16 bytes are SQLite's own header (a plaintext copy), False when they are not, None when they
    could not be read from that very file. Never says "encrypted": a header that is not SQLite's is not evidence (R821)."""
    try:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=dfd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != ident or not stat.S_ISREG(st.st_mode):
            return None
        head = os.pread(fd, 16, 0)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(head) < 16:
        return None
    return head == b"SQLite format 3\x00"


def _open_folder() -> int:
    return os.open(data_dir(), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))


def list_copies() -> dict:
    """Every safety copy in the data folder, for the list with its Delete buttons: ``{"copies": [{"name", "bytes", "made_at",
    "deletable", "reason", "plaintext"}], "unrecorded": n, "count": n, "bytes": n}``. Only a copy the record identifies is
    listed; any other is counted in ``unrecorded`` and never offered (R835 (b)). ``reason`` says why one cannot be deleted now
    (the most recent unfinished import's copy). ``plaintext``: True, False, or None when not read. Never raises."""
    import re

    shape = re.compile(COPY_NAME)
    record = read_record() or {}
    out: dict = {"copies": [], "unrecorded": 0, "count": 0, "bytes": 0}
    try:
        dfd = _open_folder()
    except OSError:
        return {"copies": [], "unrecorded": None, "count": None, "bytes": None}
    try:
        for name in sorted(os.listdir(dfd)):
            if not shape.match(name):
                continue
            try:
                st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            out["count"] += 1
            out["bytes"] += st.st_size
            got = _recorded(record.get(name))
            if got is None or tuple(got[0]) != _file_id(st):
                out["unrecorded"] += 1
                continue
            out["copies"].append({
                "name": name,
                "bytes": st.st_size,
                "made_at": datetime.fromtimestamp(got[1] / 1e9, UTC).isoformat(timespec="seconds"),
                "deletable": not _held_back(record, name),
                "reason": _hold_reason(record, name) if _held_back(record, name) else None,
                "plaintext": _plaintext(dfd, name, (st.st_dev, st.st_ino)),
            })
    except OSError:
        return {"copies": [], "unrecorded": None, "count": None, "bytes": None}
    finally:
        os.close(dfd)
    return out


def _free_bytes(dfd: int) -> int | None:
    """The free space the user can write on the data folder's drive, read through its handle; None when not readable."""
    try:
        v = os.statvfs(dfd)
    except (OSError, AttributeError, TypeError):
        return None
    return int(v.f_bavail) * int(v.f_frsize)


def remove_copy(name: str, busy: list[str] | Callable[[], list[str]] | None = None) -> dict:
    """Delete the ONE safety copy ``name`` (R835 (b)). ``busy`` names what is running (an import, restore, backup, snapshot
    or erase), or is a function that does, asked again just before the file is opened; anything named refuses.
    ``{"removed": True, "name", "freed": n | None, "message": DELETED or DELETED_FREED}`` or ``{"removed": False, "name",
    "message": <why>, "reason": <the OS's reason, for a failed delete>}``. ``freed`` is how much the drive's free space went
    up across the delete, measured (R785), and None when it did not go up or could not be read: a copy sharing blocks with
    the corpus (a cloned file), another name for it, or another program holding it open frees less than its size, and other
    writes on the drive meanwhile move the figure too. Never raises."""
    import re

    out: dict = {"removed": False, "name": None}
    if not isinstance(name, str) or not re.match(COPY_NAME, name):
        return {**out, "message": NOT_IDENTIFIED}  # a refused name is never echoed back
    out["name"] = name

    def _running() -> list[str]:
        if callable(busy):
            try:
                return list(busy())
            except Exception:  # noqa: BLE001 - unreadable = running
                return ["unknown"]
        return list(busy or [])

    if _running():
        return {**out, "message": BUSY, "busy": _running()}
    with _DELETE_LOCK:
        record = read_record()
        got = _recorded((record or {}).get(name))
        if record is None or got is None:
            return {**out, "message": NOT_IDENTIFIED}
        # From here the file is named by the record's own key (equal to the request's name, which already matched
        # COPY_NAME): the path the delete opens never comes from the request itself.
        name = next(k for k in record if k == name)
        if _held_back(record, name):
            return {**out, "message": _hold_reason(record, name)}
        now_busy = _running()
        if now_busy:
            return {**out, "message": BUSY, "busy": now_busy}
        try:
            dfd = _open_folder()
        except OSError as exc:
            return {**out, "message": NOT_DELETED, "reason": exc.strerror or type(exc).__name__}
        try:
            try:
                # The kept handle: the very file the name leads to, never through a link, checked against the record.
                fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=dfd)
            except OSError:
                return {**out, "message": NOT_IDENTIFIED}
            try:
                held = os.fstat(fd)
                if not stat.S_ISREG(held.st_mode) or _file_id(held) != tuple(got[0]):
                    return {**out, "message": NOT_IDENTIFIED}
                # The name must still lead to the held file just before the delete; the gap between this and the unlink is
                # the one R833's removal accepts (there is no unlink by inode, and nothing in the app renames onto this name).
                at = os.stat(name, dir_fd=dfd, follow_symlinks=False)
                if (at.st_dev, at.st_ino) != (held.st_dev, held.st_ino):
                    return {**out, "message": NOT_IDENTIFIED}
                before = _free_bytes(dfd)
                try:
                    os.unlink(name, dir_fd=dfd)
                except OSError as exc:
                    return {**out, "message": NOT_DELETED, "reason": exc.strerror or type(exc).__name__}
            finally:
                os.close(fd)
            after = _free_bytes(dfd)
        finally:
            os.close(dfd)
        with _LOCK:
            _OWN.pop(str(data_dir() / name), None)
        with suppress(Exception):
            _set_state(name, None)
        with suppress(Exception):
            from src.database import at_rest_state

            at_rest_state.forget_copy(data_dir() / name)  # R828 (4): its at-rest record entry goes with the file
    # R785: measured, not assumed: the drive's own free space, before the delete and after the file's last handle closed.
    freed = (after - before) if (before is not None and after is not None and after > before) else None
    return {**out, "removed": True, "freed": freed, "message": DELETED_FREED if freed else DELETED}
