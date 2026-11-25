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
   "erased", "destroyed" or "securely removed" (R797/R815). The freed size is measured from the file's own allocated blocks once
   its last name is gone, never assumed (R785). Its at-rest record entry goes with it (R828).
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
#: The record's one key that is not a copy's name: when the last import run completed and was checked
#: (``{"ns": <time.time_ns()>}``). A copy made before it belongs to a run at or before that one.
VERIFIED_KEY = "~last-verified-run"
#: The exact name of a safety copy: ``pre-restore-<UTC stamp>.db``.
COPY_NAME = r"^pre-restore-\d{8}T\d{6}Z\.db\Z"  # \Z: a name ending in a newline is never one

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


def _set_state(name: str, state: str | None, extra: dict | None = None) -> None:
    """Write ``state`` for ``name`` (None removes the entry), dropping the entries of copies no longer in the folder. The
    entry keeps what was recorded when the copy was made (row 428: its identity), plus ``extra``. Raises ``OSError`` when
    the record cannot be written."""
    from src.safety.file_lock import atomic_replace, file_lock
    from src.utils.interrupts import kept_items

    path = _record_path()
    with file_lock(path):
        cur = read_record() or {}
        folder = path.parent
        # kept_items: a filtered comprehension in a frame of its own, never under this file lock's cleanup (src/utils/interrupts.py)
        out = kept_items(
            cur, lambda k, v: isinstance(v, dict) and k != name and (k == VERIFIED_KEY or (folder / k).exists())
        )
        if state is not None:
            old = cur.get(name)
            out[name] = {**(old if isinstance(old, dict) else {}), **(extra or {}), "state": state,
                         "at": datetime.now(UTC).isoformat(timespec="seconds")}
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
        _set_state(net.name, MADE, {"file": list(_file_id(st)), "made_ns": time.time_ns()})
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

    shape = re.compile(r"^pre-restore-\d{8}T\d{6}Z\.db$")
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
NOT_IDENTIFIED = "This safety copy could not be identified, so nothing was deleted. You can delete it by hand from your data folder."
LATEST_UNFINISHED = (
    "This is the safety copy of the most recent import that was refused or did not finish. It can be deleted once a later "
    "import has completed and been checked."
)
NOT_DELETED = "The safety copy could not be deleted."
BUSY = "A safety copy cannot be deleted while an import, restore, backup, snapshot or erase is running."

_DELETE_LOCK = threading.Lock()


def note_run_verified() -> None:
    """An import run completed and its corpus was checked: every copy made before now is no longer the copy of the most
    recent unfinished run. Never raises: an unwritten mark only keeps the newest copy protected."""
    from src.safety.file_lock import atomic_replace, file_lock

    with suppress(Exception):
        path = _record_path()
        with file_lock(path):
            cur = read_record() or {}
            cur[VERIFIED_KEY] = {"ns": time.time_ns()}
            atomic_replace(path, json.dumps(cur, sort_keys=True))


def _recorded(entry: Any) -> tuple[tuple[int, ...], int] | None:
    """``(file identity, made_ns)`` of a record entry made with both, else None."""
    if not isinstance(entry, dict):
        return None
    f, made = entry.get("file"), entry.get("made_ns")
    if not (isinstance(f, list) and len(f) == 5 and all(isinstance(x, int) and not isinstance(x, bool) for x in f)):
        return None
    if not isinstance(made, int) or isinstance(made, bool):
        return None
    return tuple(f), made


def _protected_name(record: dict) -> str | None:
    """The copy of the most recent import that was refused or did not finish, when no import completed and was checked after
    it: the copy made last, unless the last verified run ended after it was made."""
    newest: tuple[int, str] | None = None
    for k, v in record.items():
        got = _recorded(v)
        if got is not None and (newest is None or got[1] > newest[0]):
            newest = (got[1], k)
    if newest is None:
        return None
    mark = record.get(VERIFIED_KEY)
    verified = mark.get("ns") if isinstance(mark, dict) else None
    if isinstance(verified, int) and not isinstance(verified, bool) and verified > newest[0]:
        return None
    return newest[1]


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
    protected = _protected_name(record)
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
                "deletable": name != protected,
                "reason": LATEST_UNFINISHED if name == protected else None,
                "plaintext": _plaintext(dfd, name, (st.st_dev, st.st_ino)),
            })
    except OSError:
        return {"copies": [], "unrecorded": None, "count": None, "bytes": None}
    finally:
        os.close(dfd)
    return out


def remove_copy(name: str, busy: list[str] | None = None) -> dict:
    """Delete the ONE safety copy ``name`` (R835 (b)). ``busy`` names what is running (an import, restore, backup, snapshot
    or erase); anything named refuses. ``{"removed": True, "name", "bytes_freed": n | None, "message": DELETED}`` or
    ``{"removed": False, "name", "message": <why>, "reason": <the OS's reason, for a failed delete>}``. Never raises."""
    import re

    out: dict = {"removed": False, "name": str(name)}
    if not isinstance(name, str) or not re.match(COPY_NAME, name):
        return {**out, "message": NOT_IDENTIFIED}
    if busy:
        return {**out, "message": BUSY, "busy": list(busy)}
    with _DELETE_LOCK:
        record = read_record()
        got = _recorded((record or {}).get(name))
        if record is None or got is None:
            return {**out, "message": NOT_IDENTIFIED}
        if _protected_name(record) == name:
            return {**out, "message": LATEST_UNFINISHED}
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
                try:
                    os.unlink(name, dir_fd=dfd)
                except OSError as exc:
                    return {**out, "message": NOT_DELETED, "reason": exc.strerror or type(exc).__name__}
                after = os.fstat(fd)
                blocks = getattr(after, "st_blocks", None)
                # R785: measured, not assumed: the held file's own allocated blocks, freed only once its last name is gone.
                freed = (int(blocks) * 512 if after.st_nlink == 0 else 0) if blocks is not None else None
            finally:
                os.close(fd)
        finally:
            os.close(dfd)
        with _LOCK:
            _OWN.pop(str(data_dir() / name), None)
        with suppress(Exception):
            _set_state(name, None)
        with suppress(Exception):
            from src.database import at_rest_state

            at_rest_state.forget_copy(data_dir() / name)  # R828 (4): its at-rest record entry goes with the file
    return {**out, "removed": True, "bytes_freed": freed, "message": DELETED}
