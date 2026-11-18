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
from collections.abc import Callable
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
            atomic_replace(path, json.dumps(doc, indent=1, sort_keys=True))
    except OSError as exc:
        log_failure(_LOG, "the at-rest record could not be written (the files still say which stores are encrypted)", exc)


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


def _room_for(path: Path) -> bool:
    """Free space beside ``path`` for two copies of it (the snapshot and the encrypted copy). True when it cannot be measured: the
    encryption itself then says what failed."""
    import shutil

    try:
        return shutil.disk_usage(path.parent).free >= 2 * os.stat(path).st_size
    except OSError:
        return True


def _present(path: Path) -> bool:
    """A non-empty file is there (or cannot be ruled out): only a clean "no such file" or a zero size reads as absent."""
    try:
        return os.stat(path).st_size > 0
    except FileNotFoundError:
        return False
    except OSError:
        return True


def status(main: Path | None = None) -> dict[str, Any]:
    """The at-rest state of every store, by header read. ``pending`` names the stores still plaintext beside an encrypted corpus;
    ``complete`` is true only when the corpus is encrypted and no store is plaintext; ``plaintext_snapshots`` names the
    pre-encrypt copies still on the disk (plaintext until the operator deletes them), so "complete" is never read as "no plaintext
    anywhere"."""
    from src.database.connect import is_encrypted_file

    rows = stores(main)
    record = read_record(rows[0][1]) if rows else {"stores": {}}
    out_rows = []
    for name, path in rows:
        header = is_encrypted_file(path)
        if header is None:
            # None is "missing or empty" AND "could not be read" (a Windows sharing refusal, a permission): a file that is there and
            # unreadable is never counted as absent, so "complete" can never be said over it.
            state = "unreadable" if _present(path) else "absent"
        else:
            state = "encrypted" if header else "plaintext"
        out_rows.append({"store": name, "state": state, "recorded_at": (record["stores"].get(name) or {}).get("encrypted_at")})
    corpus_encrypted = bool(out_rows) and out_rows[0]["state"] == "encrypted"
    pending = [r["store"] for r in out_rows if r["state"] in ("plaintext", "unreadable")] if corpus_encrypted else []
    return {
        "corpus_encrypted": corpus_encrypted,
        "complete": corpus_encrypted and not pending,
        "pending": pending,
        "stores": out_rows,
        "plaintext_snapshots": _plaintext_snapshots(rows),
    }


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
    if st["corpus_encrypted"]:
        remove_leftover_replaced(main, key=key)
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
                if not _room_for(paths[name]):
                    # A store is copied twice beside itself (the snapshot, then the encrypted copy) under the write gate: without the
                    # room for both it would hold every save for hours and end on a full disk. It waits for the encrypt button.
                    _LOG.warning("the %s store was not encrypted yet: not enough free space beside it; it stays pending", name)
                    failed.append(name)
                    continue
                try:
                    # an automatic retry that fails before touching the store drops the snapshot it made (no copy per start)
                    run(name, paths[name], key, main=main, keep_snapshot_on_failure=False)
                except Exception as exc:  # noqa: BLE001 - one store's failure never blocks the others or the app
                    log_failure(
                        _LOG, f"the {name} store could not be encrypted yet; it stays pending", exc, key, level=logging.WARNING
                    )
                    failed.append(name)
                else:
                    finished.append(name)
    return {"finished": finished, "still_pending": failed}
