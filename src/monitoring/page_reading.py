"""What the database file says about its own size in pages, read once at each open (WAL / disk thread, diagnostics PR B).

A SQLite file states its length twice: in its header (bytes 28 to 31, "database size in pages") and by being as long as it is. On a
healthy file the two agree. They did not on the Asus machine, where the file held 14,981 pages more than its header counted, and
nothing in the bundle could say when that began, because the only place that read both was a verification that had already found
damage (``database/verify.py``). This module takes the reading at EVERY open and keeps it as a fact: ``pages_in_file``,
``pages_in_header`` and ``difference`` (positive = the file holds pages the header does not count). A difference is never a verdict
here; what it can and cannot mean is in :data:`CAVEAT`.

Two sources, because the store is plaintext or encrypted and only one of them has a header a reader can see:

* ``read_header(path)`` reads the first 100 bytes of the file and its length, and opens no engine, so it can run at boot before any
  connection exists (any connection that opens and closes a WAL store unlinks the ``-wal``; the boot reading is taken ahead of it).
  A SQLCipher file has no readable header (the page is encrypted), so for it the answer is ``encrypted-or-foreign`` with the file's
  length alone: pages are never guessed from a page size nobody could read.
* ``from_connection(conn, path)`` reads ``PRAGMA page_size`` and ``PRAGMA page_count`` off a connection the caller has ALREADY opened
  with the key (the unlock's verify connection), before anything writes. It is the engine's answer, not the bytes, and it is named
  for what it is (``pages_in_database``, never ``pages_in_header``): with a ``-wal`` it is the database's size at the log's last
  commit, and when the header's size is invalid SQLite falls back to the file's length, so a difference of 0 (or -1 with a torn
  tail) from this source does not rule out a stale header (``header_valid`` is therefore ``None`` here, never ``True``).

Either sign of the difference is expected while a ``-wal`` holds frames (the log's growth makes it negative, a shrink makes it positive
until a checkpoint truncates), so the one log line is only written when there is no log; the figures stay on the event either way.

Never raises. An error is its class and, for an ``OSError``, the NAME of its errno: never the message, which carries a path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

HEADER_BYTES = 100
_MAGIC = b"SQLite format 3\x00"
#: The page sizes SQLite accepts: a power of two from 512 to 32768, and 1 standing for 65536.
_PAGE_SIZES = frozenset(2**n for n in range(9, 16))

CAVEAT = (
    "A fact, not a verdict. pages_in_file is the file's length divided by the page size. The other count depends on the source. "
    "header-bytes: pages_in_header is the size the header states (bytes 28 to 31), valid only when the file change counter (bytes 24 to "
    "27) equals the version-valid-for number (bytes 92 to 95) and is not zero; otherwise SQLite uses the file's length and no difference "
    "is given. engine-pragma: pages_in_database is what PRAGMA page_count answered, which is the header's size when there is no -wal "
    "and the database's size at the -wal's last commit when there is one; it cannot show an invalid header, so a difference of 0 (or "
    "-1 with a torn tail) there does not rule out a stale header. difference is pages_in_file minus that count. With no -wal, a "
    "positive difference means the file holds pages the database does not count (SQLite ignores them, and the next page it allocates "
    "can overwrite them). While a -wal holds frames either sign is expected (the log's growth gives a negative difference, a shrink a "
    "positive one until a checkpoint truncates), so the log line is not written then. The unlock source is taken after any refused "
    "passphrase of this process (refused_attempts_before) and a refused passphrase folds the -wal into the file, so a 0 after one is "
    "not evidence of a healthy previous end."
)


def _error(exc: BaseException) -> str:
    from src.database.damage import failure_label

    return failure_label(exc)


def _int(data: bytes, start: int, width: int) -> int:
    return int.from_bytes(data[start : start + width], "big")


def _wal_bytes(path: Path) -> int | None:
    try:
        return path.with_name(path.name + "-wal").stat().st_size
    except OSError:
        return None


def read_header(path: Path) -> dict[str, Any]:
    """The reading from the file's own bytes, no engine. ``state`` says which kind of answer this is:

    * ``read``: a plaintext header, valid or not (``header_valid``); ``pages_in_file`` and ``pages_in_header`` set;
    * ``encrypted-or-foreign``: the first 16 bytes are not SQLite's magic, so this is a SQLCipher file (or not SQLite at all); only
      ``file_bytes`` is known;
    * ``no-file`` / ``empty`` / ``short`` / ``bad-page-size`` / ``unreadable``: the reason there is no pages figure, never a zero.
    """
    out: dict[str, Any] = {"source": "header-bytes"}
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEADER_BYTES)
            file_bytes = os.fstat(fh.fileno()).st_size
    except FileNotFoundError:
        out["state"] = "no-file"
        return out
    except Exception as exc:  # noqa: BLE001 - a reading that cannot be taken is a reading that says so
        out["state"] = "unreadable"
        out["error"] = _error(exc)
        return out
    out["file_bytes"] = file_bytes
    out["wal_bytes"] = _wal_bytes(path)
    if file_bytes == 0:
        out["state"] = "empty"
        return out
    if len(head) < len(_MAGIC):
        out["state"] = "short"  # too short to say whose it is: not "encrypted" (an encrypted page is at least 512 bytes)
        return out
    if head[:16] != _MAGIC:
        out["state"] = "encrypted-or-foreign"
        return out
    if len(head) < HEADER_BYTES:
        out["state"] = "short"
        return out
    page_size = _int(head, 16, 2)
    if page_size == 1:
        page_size = 65536
    if page_size not in _PAGE_SIZES and page_size != 65536:
        out["state"] = "bad-page-size"
        return out
    header_pages = _int(head, 28, 4)
    valid = header_pages != 0 and _int(head, 24, 4) == _int(head, 92, 4)
    out.update(
        state="read",
        page_size=page_size,
        pages_in_header=header_pages,
        header_valid=valid,
        pages_in_file=file_bytes // page_size,
        trailing_bytes=file_bytes % page_size,
    )
    if valid:
        out["difference"] = out["pages_in_file"] - header_pages
    return out


def from_connection(conn: Any, path: Path, *, refused_before: int = 0) -> dict[str, Any]:
    """The reading from a connection the caller opened with the key and has not written through: ``PRAGMA page_size`` and ``PRAGMA
    page_count`` (cheap header reads, no table is touched) against the file's length. ``conn`` is a DB-API connection.

    ``PRAGMA page_count`` is the header's size when there is no ``-wal`` and the database's size at the log's last commit when there is
    one, so the count is named ``pages_in_database`` and is never offered as the header's. The busy timeout is zeroed first: an
    instrument must not make an unlock wait, and a busy answer is an honest ``unreadable``. ``refused_before`` is how many refused
    passphrases this process saw before the reading (each one folds the ``-wal`` into the file, so the reading then describes the file
    after that and not the one the last session left); it is kept when it is not zero."""
    out: dict[str, Any] = {"source": "engine-pragma"}
    try:
        conn.execute("PRAGMA busy_timeout = 0")
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        counted = int(conn.execute("PRAGMA page_count").fetchone()[0])
        file_bytes = path.stat().st_size
    except Exception as exc:  # noqa: BLE001 - a reading that cannot be taken is a reading that says so
        out["state"] = "unreadable"
        out["error"] = _error(exc)
        return out
    out.update(
        state="read",
        file_bytes=file_bytes,
        wal_bytes=_wal_bytes(path),
        header_valid=None,
        refused_attempts_before=refused_before if refused_before > 0 else None,
    )
    if page_size > 0:
        out.update(
            page_size=page_size,
            pages_in_database=counted,
            pages_in_file=file_bytes // page_size,
            trailing_bytes=file_bytes % page_size,
            difference=file_bytes // page_size - counted,
        )
    else:
        out["state"] = "bad-page-size"
    return out


def compact(reading: dict[str, Any] | None) -> dict[str, Any] | None:
    """The part of a reading worth keeping on an ``open`` event: ``None`` when there is none."""
    if not isinstance(reading, dict):
        return None
    keep = (
        "source",
        "state",
        "pages_in_file",
        "pages_in_header",
        "pages_in_database",
        "difference",
        "page_size",
        "header_valid",
        "trailing_bytes",
        "file_bytes",
        "wal_bytes",
        "refused_attempts_before",
        "error",
    )
    return {k: reading[k] for k in keep if reading.get(k) is not None}


def line_of(reading: dict[str, Any] | None) -> str | None:
    """The one log sentence for a reading that found the file longer than the database it counts while there is NO ``-wal`` (with one
    either sign is expected, see :data:`CAVEAT`), else ``None``. Counts only."""
    if not isinstance(reading, dict):
        return None
    diff = reading.get("difference")
    if not isinstance(diff, int) or diff <= 0 or reading.get("wal_bytes"):
        return None
    if reading.get("source") == "engine-pragma":
        counted = f"{reading.get('pages_in_database')} counted by the engine"
        what = "the database the engine counts"
    else:
        counted = f"{reading.get('pages_in_header')} in the header"
        what = "its header counts"
    return (
        f"the database file holds {diff} pages more than {what} "
        f"({reading.get('pages_in_file')} in the file, {counted}, read by {reading.get('source')}, no -wal)"
    )
