"""
Which at-rest stores are encrypted, read from the files themselves (R742, row 146).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"Encrypt my store" covers several files under ONE passphrase: the corpus first, then the custody log, then the versioned-source
lanes (``encrypt_tool.encrypt_all``). A later store can fail after the corpus is already ciphertext (a file another program holds,
a full disk). Before R742 that left the app running keyless against an encrypted corpus, the other stores in the clear, and no way
to finish: the encrypt route only accepts a plaintext store.

So this module answers three questions, always from the files' own headers, never from what a run meant to do:

* :func:`status`: which stores exist, which are encrypted, which are still plaintext beside an encrypted corpus (``pending``), and
  whether the whole set is encrypted (``complete``). ``complete`` is never true while any store is plaintext.
* :func:`record_encrypted`: the persisted, non-secret record of the stores that were encrypted AND read back with the key, with the
  time. It holds store names and times only: no path, no key, no count.
* :func:`finish_pending`: encrypt the stores still pending, under the key the app holds. Run at the next unlock (the start-up upkeep)
  and by the encrypt route's retry. A store that fails stays pending and is said to be; the app stays usable.

An install that hit the old failure has no record at all; it is found the same way (an encrypted corpus beside a plaintext store)
and finished the same way, because the files, not the record, decide what is pending.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("database.at_rest_state")

#: The record's file name, beside the corpus. Store names and times only.
RECORD_NAME = "at_rest_encryption.json"
RECORD_VERSION = 1
#: How long the finish waits for work already in flight (a drain, a re-index batch) before leaving every store pending.
FINISH_QUIESCE_S = 60.0

#: The plaintext copy ``encrypt_database`` keeps beside each store ON PURPOSE (the operator's escape hatch, deleted by them once
#: they have unlocked). Named here so the status can say it is still on the disk.
_SNAPSHOT = re.compile(r"^pre-encrypt-\d{8}T\d{6}Z-.+$")
#: The second name a replaced plaintext store keeps when a crash came between the swap and its overwrite (``encrypt_tool``). Not
#: wanted by anyone: it is overwritten and removed at the next unlock once its store reads as encrypted.
_RETIRED = re.compile(r"^(?P<store>.+)\.replaced-\d{8}T\d{6}Z$")


def stores(main: Path | None = None) -> list[tuple[str, Path]]:
    """The at-rest stores, in the order ``encrypt_all`` encrypts them: the corpus FIRST. The same resolvers ``encrypt_all`` uses
    (the custody log from ``data_dir()``, the lanes beside the corpus), so the two can never disagree about a file."""
    from src.paths import data_dir
    from src.versioned.lanes import all_lanes

    if main is None:
        from src.api.unlock import main_db_path

        main = main_db_path()
    if main is None:
        return []
    out = [("corpus", main), ("custody", data_dir() / "custody_log.db")]
    out += [(f"lane:{spec.kind}", main.parent / spec.filename) for spec in all_lanes()]
    return out


def _record_path(main: Path) -> Path:
    return main.parent / RECORD_NAME


def read_record(main: Path | None = None) -> dict[str, Any]:
    """The record, or an empty one. Never raises: an unreadable record reads as empty, which only means the status has no times
    to show, since every state it reports is read from the files."""
    rows = stores(main)
    if not rows:
        return {"version": RECORD_VERSION, "stores": {}}
    try:
        doc = json.loads(_record_path(rows[0][1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": RECORD_VERSION, "stores": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("stores"), dict):
        return {"version": RECORD_VERSION, "stores": {}}
    return {"version": RECORD_VERSION, "stores": {str(k): v for k, v in doc["stores"].items() if isinstance(v, dict)}}


def record_encrypted(name: str, main: Path | None = None) -> None:
    """Add ``name`` to the record, atomically and under the record's lock (``file_lock``, then ``atomic_replace``). Called only after the store was encrypted AND read
    back with the key. A failure to write is logged by class and never undoes the encryption: the status reads the files."""
    rows = stores(main)
    if not rows:
        return
    from src.safety.file_lock import atomic_replace, file_lock

    path = _record_path(rows[0][1])
    try:
        # Read, add and replace under the record's own lock (R176), so a second server's write cannot fall between the read and the swap.
        with file_lock(path):
            doc = read_record(rows[0][1])
            doc["stores"][name] = {"encrypted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "read_back_with_key": True}
            store = dict(rows).get(name)
            ident = _identity(store) if store is not None else None
            if ident is not None:  # R820 (4): the identity of the file read back with the key, by path (R789)
                doc["stores"][name].update(dev=int(ident[0]), ino=int(ident[1]))
            atomic_replace(path, json.dumps(doc, indent=1, sort_keys=True))
    except OSError as exc:
        log_failure(_LOG, "the at-rest record could not be written (the files still say which stores are encrypted)", exc)


#: R820 (4): the record's identity fields. A store's (device, inode) when it was read back with the app's key, never a secret; an
#: entry without them (a record from before R820) is never evidence (R755: additive).
_IDENT_KEYS = ("dev", "ino")
#: R820 (3): the most of the record the erase reads; a longer file is not the app's record.
RECORD_MAX_BYTES = 64 * 1024
_NOTE_LOCK = threading.Lock()
#: The identities this process already wrote into the record (keyed) or checked against it (plaintext), so the hook on every new
#: pooled connection costs one ``stat`` and a set lookup after the first.
_NOTED_KEYED: set[tuple[int, int]] = set()
_NOTED_PLAIN: set[tuple[int, int]] = set()


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)  # by path: never an open and close of a store's file (R789)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _write_identity(name: str, path: Path, ident: tuple[int, int] | None) -> None:
    """Set (``ident``) or clear (None) the identity of ``name`` in the record, atomically and under its lock. Never raises."""
    from src.safety.file_lock import atomic_replace, file_lock

    try:
        with file_lock(path):
            doc = _read_record_at(path)
            entry = dict(doc["stores"].get(name) or {})
            if ident is None:
                if "dev" not in entry and "ino" not in entry:
                    return
                for k in _IDENT_KEYS:
                    entry.pop(k, None)
                entry["read_back_with_key"] = False
            else:
                entry.setdefault("encrypted_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
                entry.update(read_back_with_key=True, dev=int(ident[0]), ino=int(ident[1]))
            doc["stores"][name] = entry
            atomic_replace(path, json.dumps(doc, indent=1, sort_keys=True))
    except OSError as exc:
        log_failure(_LOG, "the at-rest record could not be written (the files still say which stores are encrypted)", exc)


def _read_record_at(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": RECORD_VERSION, "stores": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("stores"), dict):
        return {"version": RECORD_VERSION, "stores": {}}
    return {"version": RECORD_VERSION, "stores": {str(k): v for k, v in doc["stores"].items() if isinstance(v, dict)}}


def note_main_open(path: Path | str) -> None:
    """R820 (4): called after the app's own engine opened a connection on the corpus at ``path``. Opened with the app's key (a real
    keyed page read: :func:`src.database.connect.last_open_of`), its (device, inode) is written into the record once per process;
    opened as plaintext, an identity the record holds for it is removed. A failed write never fails the open. Never raises."""
    try:
        p = Path(path)
        ident = _identity(p)
        if ident is None:
            return
        from src.database.connect import last_open_of

        how = last_open_of(ident)
        if how is None:
            return  # no positive evidence either way (a disposal on another thread, say): the record is left as it is
        keyed = how == "keyed"
        with _NOTE_LOCK:
            seen = _NOTED_KEYED if keyed else _NOTED_PLAIN
            if ident in seen:
                return
            seen.add(ident)
            (_NOTED_PLAIN if keyed else _NOTED_KEYED).discard(ident)
        record = _record_path(p)
        if keyed:
            entry = _read_record_at(record)["stores"].get("corpus") or {}
            if (entry.get("dev"), entry.get("ino")) != ident:
                _write_identity("corpus", record, ident)
        elif record.exists():
            entry = _read_record_at(record)["stores"].get("corpus") or {}
            # Whatever identity it names: the corpus at this path is plaintext now, so an older one (a replaced file whose inode
            # the file system may hand out again) is never evidence either (security read, row 396).
            if "dev" in entry or "ino" in entry:
                _write_identity("corpus", record, None)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails an open
        log_failure(_LOG, "the at-rest record could not be updated after an open", exc, level=logging.DEBUG)


def record_names_identity(raw: bytes | None, ident: tuple[int, int]) -> bool:
    """R820 (1)/(3): whether the record's bytes ``raw`` (read by the erase, no-follow, regular file only, at most
    :data:`RECORD_MAX_BYTES`) name the corpus at ``ident`` as encrypted and read back with the key. Anything else is False: no record,
    a malformed one, an entry without an identity (a record from before R820) or with another one."""
    if not raw or len(raw) > RECORD_MAX_BYTES:
        return False
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    stores = doc.get("stores") if isinstance(doc, dict) else None
    entry = stores.get("corpus") if isinstance(stores, dict) else None
    if not isinstance(entry, dict) or entry.get("read_back_with_key") is not True:
        return False
    dev, ino = entry.get("dev"), entry.get("ino")
    if type(dev) is not int or type(ino) is not int:
        return False
    return (dev, ino) == tuple(ident)


def _names_beside(rows: list[tuple[str, Path]]) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for folder in sorted({p.parent for _name, p in rows}):
        try:
            out += [(folder, entry.name) for entry in os.scandir(folder) if entry.is_file(follow_symlinks=False)]
        except OSError:
            continue
    return out


def _plaintext_snapshots(rows: list[tuple[str, Path]]) -> list[str]:
    """The plaintext copies on the disk beside the stores: the deliberate pre-encrypt snapshots, and any replaced store a crash left
    under its second name (removed at the next unlock)."""
    store_names = {p.name for _name, p in rows}
    seen = set()
    for _folder, n in _names_beside(rows):
        m = _RETIRED.match(n)
        if _SNAPSHOT.match(n) or (m and m.group("store") in store_names):
            seen.add(n)
    return sorted(seen)


def remove_leftover_replaced(main: Path | None = None, *, key: str) -> int:
    """Overwrite and remove each ``<store>.replaced-<time>`` left by a crash between a store's swap and the overwrite of the file it
    replaced, ONLY when that store now reads as encrypted AND opens with ``key`` (otherwise the leftover may be the only readable
    copy, and it stays). Never raises; returns how many were removed."""
    from src.database.connect import is_encrypted_file
    from src.database.encrypt_tool import _table_counts_safe
    from src.safety.crypto_erase import _shred

    rows = stores(main)
    by_name = {p.name: p for _name, p in rows}
    removed = 0
    for folder, n in _names_beside(rows):
        m = _RETIRED.match(n)
        store = by_name.get(m.group("store")) if m else None
        if store is None or store.parent != folder or is_encrypted_file(store) is not True:
            continue
        with contextlib.suppress(OSError):
            if os.path.samefile(store, folder / n):  # never overwrite the store itself through a second name
                continue
        try:
            _table_counts_safe(store, key)
        except Exception:  # noqa: BLE001 - a store that does not open with the key keeps every other copy beside it
            continue
        try:
            _seen, _overwritten, unlinked = _shred(folder / n)
        except Exception as exc:  # noqa: BLE001 - a leftover that cannot be removed stays named in the status
            log_failure(_LOG, "a replaced plaintext store could not be removed", exc, level=logging.WARNING)
            continue
        removed += int(bool(unlinked))
    return removed


#: Why a store that is there could not be read (row 149). Fixed words, keyed in every locale; never the OS's own text, which can
#: name a path. A store in use right now is not unreadable: it reads ``busy`` (row 153).
UNREADABLE_REASONS = {
    "permission": "permission refused",
    "short_header": "the file is too short to be a database",
    "io": "a read error",
}
#: How long a status waits for a store swap in progress before it reports the stores' passphrase as not checked yet.
PROBE_WAIT_S = 0.5
#: The busy timeout of a probe's open, per page-size candidate: a store another connection holds reads as busy at once, never as a
#: wrong passphrase, and a probe never holds the swap of a store for long.
PROBE_BUSY_S = 0.25
_SQLITE_MAGIC = b"SQLite format 3\x00"
#: One status probe at a time, and never during a store's swap (``encrypt_store`` holds it around the swap): on Windows a probe's
#: connection open across ``os.replace`` would refuse the swap.
_PROBE_LOCK = threading.Lock()
#: (path, device, inode, size, mtime, key generation) -> the probe's answer. No key and nothing derived from one: the generation is a
#: counter. Size and mtime are in the key because a file rewritten in place (a copy over it) keeps its inode.
_probed: dict[tuple[Any, ...], dict[str, Any]] = {}


@contextlib.contextmanager
def probes_held() -> Iterator[None]:
    """Held by ``encrypt_store`` around a store's swap: no status probe has a connection open on a store while it is replaced."""
    with _PROBE_LOCK:
        yield


#: SQLite's "busy" and "locked" codes (primary: an extended code such as SQLITE_BUSY_SNAPSHOT is masked to them), and Windows'
#: sharing and lock violations: the store is in use right now (row 153).
_BUSY_SQLITE = (5, 6)
_BUSY_WINERROR = (32, 33)


def _is_busy(exc: BaseException | None) -> bool:
    """True for an error that says the store is in use right now (a lock another connection or program holds), never a fault."""
    code = getattr(exc, "sqlite_errorcode", None)
    return getattr(exc, "winerror", None) in _BUSY_WINERROR or (isinstance(code, int) and code & 0xFF in _BUSY_SQLITE)


def _reason(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "permission"
    return "io"


def _header_file(path: Path):
    """The store's bytes through the descriptor kept for it (R789, ``connect.store_file``): a status read must never close a
    descriptor of its own on a store this process may hold, which would drop every lock the process has on it."""
    from src.database.connect import store_file

    return store_file(path)


def _read_header(path: Path) -> tuple[str, str | None]:
    """``(state, reason)`` from the file's first 16 bytes: ``absent`` (no file, or an empty one), ``plaintext``, ``encrypted`` (a
    header that is not SQLite's), ``busy`` (another program holds the file: try again), or ``unreadable`` with the reason, so a file
    that is there is never counted as absent."""
    try:
        with _header_file(path) as fh:
            head = fh.read(16)
    except FileNotFoundError:
        return "absent", None
    except OSError as exc:
        return ("busy", None) if _is_busy(exc) else ("unreadable", _reason(exc))
    if not head:
        return "absent", None
    if len(head) < 16:
        return "unreadable", "short_header"
    return ("plaintext" if head == _SQLITE_MAGIC else "encrypted"), None


def _cache_key(path: Path) -> tuple[Any, ...] | None:
    """The probe cache's key for ``path``, or None (not cached) when the file cannot be told apart from another: no stat, or a file
    system with no inode numbers."""
    from src.database.connect import key_generation

    try:
        st = os.stat(path)
    except OSError:
        return None
    if not st.st_ino:
        return None
    return (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, key_generation())


def _refused_the_key(exc: BaseException) -> bool:
    """A ``WrongPassphraseError`` whose cause is the key check (SQLite error 26, "not a database") or unknown, as against a file that
    was busy, could not be opened, or failed past page 1: only the first is "not this passphrase"."""
    return getattr(exc.__cause__, "sqlite_errorcode", None) in (None, 26)


def _refusal_of(exc: BaseException) -> dict[str, Any]:
    """What a ``WrongPassphraseError`` from the probe's open says, from its chained SQLite error: busy (5, 6), the key check (26 or
    unknown: not this passphrase), or anything else (a read error)."""
    if _is_busy(exc.__cause__):
        return {"state": "busy"}
    return {"state": "not_this_key"} if _refused_the_key(exc) else {"state": "unreadable", "reason": "io"}


def _probe(path: Path, key: str) -> dict[str, Any]:
    """Open an encrypted store READ-ONLY with ``key`` (lock held): ``encrypted`` with ``key_checked`` and the cipher when it opens,
    ``not_this_key`` when SQLCipher refuses the key (another passphrase, or a damaged file: the two read the same), or
    ``busy`` when another connection holds it (row 153: in use right now, never a fault or a wrong key), or ``unreadable`` with a
    reason. Read-only: the probe never creates a file that went missing, and never folds or removes a leftover log. Cached per file
    state and key generation; a busy or unreadable answer is not cached (it can pass)."""
    from src.database.connect import WrongPassphraseError, connect

    cache_key = _cache_key(path)
    hit = _probed.get(cache_key) if cache_key is not None else None
    if hit is not None:
        return dict(hit)
    out: dict[str, Any]
    try:
        conn = connect(path, key=key, check_same_thread=False, timeout=PROBE_BUSY_S, read_only=True)
    except WrongPassphraseError as exc:
        out = _refusal_of(exc)
    except OSError as exc:
        out = {"state": "busy"} if _is_busy(exc) else {"state": "unreadable", "reason": _reason(exc)}
    except Exception:  # noqa: BLE001 - the status never raises; what failed is said by class
        out = {"state": "unreadable", "reason": "io"}
    else:
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            ver = conn.execute("PRAGMA cipher_version").fetchone()
            out = {"state": "encrypted", "key_checked": True, "cipher": ver[0] if ver else None}
        except Exception as exc:  # noqa: BLE001 - as above
            out = {"state": "busy"} if _is_busy(exc) else {"state": "unreadable", "reason": _reason(exc) if isinstance(exc, OSError) else "io"}
        finally:
            with contextlib.suppress(Exception):
                conn.close()
    if out["state"] in ("encrypted", "not_this_key") and cache_key is not None:
        if len(_probed) > 64:
            _probed.clear()
        _probed[cache_key] = dict(out)
    return out


def _evidence(name: str, path: Path, record: dict[str, Any]) -> str | None:
    """R821 (1)/(2): what makes a store with a header that is not SQLite's "encrypted" rather than "looks encrypted": ``"key"`` when
    this process read the very file under a key (the corpus: :func:`src.database.connect.opened_with_key`), ``"record"`` when this
    installation's record names its (device, inode) as read back with the key (R820), else None. The header alone never is. A
    ``stat`` and a set lookup: no store is opened here (R789)."""
    ident = _identity(path)
    if ident is None:
        return None
    if name == "corpus":
        from src.database.connect import opened_with_key

        if opened_with_key(ident):
            return "key"
    entry = record["stores"].get(name)
    if not isinstance(entry, dict) or entry.get("read_back_with_key") is not True:
        return None
    dev, ino = entry.get("dev"), entry.get("ino")
    if type(dev) is not int or type(ino) is not int or (dev, ino) != ident:
        return None
    return "record"


def _with_evidence(row: dict[str, Any], name: str, path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """R821 (1): a row whose header is not SQLite's and that no key opened here is "encrypted" only with :func:`_evidence`, and says
    which; otherwise it is ``looks_encrypted`` ("looks encrypted; not yet checked with your key"), never "encrypted"."""
    if row["state"] != "encrypted":
        return row
    if row.get("key_checked") is True:
        row["evidence"] = "key"
        return row
    ev = _evidence(name, path, record)
    if ev is None:
        row["state"] = "looks_encrypted"
        row["evidence"] = "header"
    else:
        row["evidence"] = ev
    return row


def _store_row(name: str, path: Path, key: str | None, probe_ok: bool, record: dict[str, Any] | None = None) -> dict[str, Any]:
    record = record if record is not None else {"stores": {}}
    state, reason = _read_header(path)
    row: dict[str, Any] = {"store": name, "state": state}
    if reason is not None:
        row["reason"] = reason
    if state != "encrypted" or name == "corpus":
        # The corpus is the file the app is open with (an unlocked encrypted app opened it with the key it holds): it is not
        # opened a second time here, where a probe could straddle a swap of the library.
        return _with_evidence(row, name, path, record)
    if key is None or not probe_ok:
        row["key_checked"] = False
        return _with_evidence(row, name, path, record)
    row.update(_probe(path, key))
    if row["state"] in ("busy", "unreadable"):
        # The header says encrypted; only the check with the passphrase did not run to its end. Never "still unencrypted" (row 153).
        row["key_checked"] = False
    return _with_evidence(row, name, path, record)


def status(main: Path | None = None) -> dict[str, Any]:
    """The at-rest state of every store, by header read and, when a key is held, by opening each encrypted store with it (row
    149). A store's ``state`` is ``absent``, ``plaintext``, ``encrypted`` (``key_checked`` says whether the held passphrase was
    seen to open it), ``not_this_key`` (encrypted, but the held passphrase does not open it: another passphrase, or damaged) or
    ``busy`` (in use right now: try again, row 153) or ``unreadable`` with a ``reason`` (:data:`UNREADABLE_REASONS`). ``pending``
    names the stores still plaintext, or unreadable with no encrypted header, beside an encrypted corpus; ``busy`` names those in use
    right now (never pending: what they hold is not known yet); ``not_this_key`` names those the passphrase does not open, which
    nothing here encrypts or touches; ``unchecked`` names the encrypted stores the passphrase was not tried on to its end (no key
    held, a swap in progress, busy or a read error after the header); ``complete`` is true only when the corpus is encrypted, nothing
    is pending, busy or ``not_this_key``, and, when a key is held, nothing is ``unchecked``; ``plaintext_snapshots`` names the
    pre-encrypt copies still on the disk (plaintext until the operator deletes them), so "complete" is never read as "no plaintext
    anywhere". The key tried is always the passphrase the app holds (the probe cache is keyed by its generation, so no other key
    may be passed)."""
    from src.database.connect import get_passphrase

    rows = stores(main)
    key = get_passphrase()
    record = read_record(rows[0][1]) if rows else {"stores": {}}
    probe_ok = key is not None and _PROBE_LOCK.acquire(timeout=PROBE_WAIT_S)
    try:
        out_rows = _rows_of(rows, key, probe_ok, record)
    finally:
        if probe_ok:
            _PROBE_LOCK.release()
    for r in out_rows:
        r["recorded_at"] = (record["stores"].get(r["store"]) or {}).get("encrypted_at")
    corpus_encrypted = bool(out_rows) and out_rows[0]["state"] == "encrypted"
    pending = _pending_of(out_rows) if corpus_encrypted else []
    busy = [r["store"] for r in out_rows if r["state"] == "busy"]
    not_this_key = [r["store"] for r in out_rows if r["state"] == "not_this_key"]
    unchecked = [r["store"] for r in out_rows if r.get("key_checked") is False]
    looks = [r["store"] for r in out_rows if r["state"] == "looks_encrypted"]
    return {
        "corpus_encrypted": corpus_encrypted,
        # With a key held, never said over a store it was not tried on (a swap in progress): "encrypted" by its header is not
        # "encrypted with yours". With no key held (locked) there is nothing to try: R821, a store is "encrypted" there only by this
        # installation's record, and one that only LOOKS encrypted (its header) keeps "complete" false.
        "complete": corpus_encrypted and not pending and not busy and not not_this_key and not looks
        and not (key is not None and unchecked),
        "looks_encrypted": looks,
        "key_held": key is not None,
        "pending": pending,
        "busy": busy,
        "not_this_key": not_this_key,
        "unchecked": unchecked,
        "stores": out_rows,
        "plaintext_snapshots": _plaintext_snapshots(rows),
    }


def _pending_of(rows: list[dict[str, Any]]) -> list[str]:
    """Plaintext stores, and unreadable ones whose header was never read (an unreadable store with an encrypted header has
    ``key_checked`` false and is not pending: it is not "still unencrypted")."""
    return [r["store"] for r in rows if r["state"] == "plaintext" or (r["state"] == "unreadable" and "key_checked" not in r)]


def _rows_of(rows: list[tuple[str, Path]], key: str | None, probe_ok: bool, record: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One row per store (a function of its own: the loop is not inside ``status``'s ``try``, R163)."""
    return [_store_row(name, path, key, probe_ok, record) for name, path in rows]


def _corpus_opens_with(st: dict[str, Any], main: Path | None, key: str) -> bool:
    """Whether the corpus whose header only looks encrypted opens READ-ONLY with ``key`` (the probe, under the probe lock: never
    beside a swap of it). Never raises."""
    rows = st.get("stores") or []
    if not rows or rows[0].get("state") != "looks_encrypted" or not key:
        return False
    corpus = stores(main)[0][1]
    if not _PROBE_LOCK.acquire(timeout=PROBE_WAIT_S):
        return False
    try:
        return _probe(corpus, key).get("state") == "encrypted"
    except Exception:  # noqa: BLE001 - not proven is "not proven", never an error here
        return False
    finally:
        _PROBE_LOCK.release()


def finish_pending(key: str, main: Path | None = None, *, encrypt: Callable[..., dict] | None = None) -> dict[str, Any]:
    """Encrypt every store still pending under ``key`` (the key the app holds). Held as the encrypt route holds the machine: the
    exclusive window (collection stands aside), the work in flight waited for, then the write gate, the lane pools closed first, and
    the custody log's own append lock around its swap (``encrypt_store``). When the work in flight does not end, nothing is touched
    and every store stays pending for the next unlock or the encrypt button. Each store is its own step: one that fails is logged by class and stays pending, and the others
    go on. Returns ``{"finished": [...], "still_pending": [...]}``. Does nothing when the corpus is not encrypted (there is nothing
    to finish: a plaintext corpus is encrypted by the operator's own request, never here)."""
    from src.database import encrypt_tool
    from src.database.corpus_lease import wait_for_quiescence
    from src.database.writer import write_lock
    from src.scheduler.runner import exclusive_window

    st = status(main)
    if not st["corpus_encrypted"] and _corpus_opens_with(st, main, key):
        # R821 (1): a corpus that only LOOKED encrypted (no keyed open on record in this process, no record naming it) is proven
        # here by a keyed read with the key this process holds, and recorded (R820 (4)); only then is anything finished under it.
        record_encrypted("corpus", main)
        st = status(main)
    if st["corpus_encrypted"]:
        remove_leftover_replaced(main, key=key)
    if st["corpus_encrypted"] and st["busy"]:
        # A store in use right now is not pending, and may still be plaintext when its header could not be read: said, never skipped
        # silently. It is looked at again at the next unlock or encrypt.
        _LOG.warning("a store was in use and could not be checked (%s); it is looked at again next time", ", ".join(st["busy"]))
    if not st["corpus_encrypted"] or not st["pending"]:
        return {"finished": [], "still_pending": []}
    run = encrypt or encrypt_tool.encrypt_store
    paths = dict(stores(main))
    finished: list[str] = []
    failed: list[str] = []
    with exclusive_window(resume_retries=0):
        held = wait_for_quiescence(FINISH_QUIESCE_S)
        if held:
            _LOG.warning("the other stores were not encrypted yet: work still in flight (%s); they stay pending", ", ".join(held))
            return {"finished": [], "still_pending": list(st["pending"])}
        with write_lock():
            encrypt_tool.dispose_lane_engines()
            for name in st["pending"]:
                if paths[name].is_file() and encrypt_tool.room_refusal(name, paths[name]) is not None:
                    # A store is copied twice beside itself (the snapshot, then the encrypted copy) under the write gate: without the
                    # room for both (its file and its write-ahead log, row 323) it would hold every save for hours and end on a full
                    # disk. The ONE check the operator's encrypt makes too (R793); a room that was not read refuses as well. It waits
                    # for the encrypt button, whose answer says which.
                    _LOG.warning("the %s store was not encrypted yet: no room for its copies, or the room was not read; it stays pending", name)
                    failed.append(name)
                    continue
                try:
                    # an automatic retry that fails before touching the store drops the snapshot it made (no copy per start)
                    run(name, paths[name], key, main=main, keep_snapshot_on_failure=False)
                except Exception as exc:  # noqa: BLE001 - one store's failure never blocks the others or the app
                    # R794: an unfinished plaintext copy that could not be removed is an error that names its path, never a warning.
                    left = isinstance(exc, encrypt_tool.SnapshotLeftOnDisk)
                    log_failure(
                        _LOG, f"the {name} store could not be encrypted yet; it stays pending", exc, key,
                        level=logging.ERROR if left else logging.WARNING,
                    )
                    failed.append(name)
                else:
                    finished.append(name)
    return {"finished": finished, "still_pending": failed}
