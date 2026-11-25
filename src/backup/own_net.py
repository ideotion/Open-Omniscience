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
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
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

REMOVED = "safety copy removed: the import was refused before any change"

#: Why a copy was kept (the report says which).
KEPT_NOT_OURS = "kept: this run did not make it"
KEPT_ACTIVATED = "kept: the import may have reached the change (its record says so, or could not be read)"
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


def _set_state(name: str, state: str | None) -> None:
    """Write ``state`` for ``name`` (None removes the entry), dropping the entries of copies no longer in the folder.
    Raises ``OSError`` when the record cannot be written."""
    from src.safety.file_lock import atomic_replace, file_lock

    path = _record_path()
    with file_lock(path):
        cur = read_record() or {}
        folder = path.parent
        out = {k: v for k, v in cur.items() if isinstance(v, dict) and (folder / k).exists() and k != name}
        if state is not None:
            out[name] = {"state": state, "at": datetime.now(UTC).isoformat(timespec="seconds")}
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
        _set_state(net.name, MADE)
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
