"""R829 (row 410-A): the staged copy of an incoming corpus stays encrypted on disk for the whole import.

Before this, every import wrote a full PLAINTEXT copy of the incoming corpus into its staging folder and kept it there
for the whole merge (hours on a large backup): an encrypted backup member was exported to plaintext first, and every
other path (a zip upload, a legacy volume set, a corpus not encrypted in its backup, a bare SQLite file) staged
plaintext as it arrived. Two ways out, one per kind of path:

- **A1, an encrypted member** (the normal volume set): it is not exported at all. The merge and the steps before it
  open the reassembled member as it is, with the passphrase that opens it. That also removes one full rewrite of the
  incoming corpus and halves the staging disk.
- **A2, everything else**: the plaintext member is re-keyed at once into a SQLCipher copy under a random 256-bit key
  that lives only in this process's memory, and the plaintext file is unlinked. A crash leaves a file nobody can read,
  which the boot sweep removes. The key is never written anywhere and never derived from the passphrase.

The custody log follows the same two rules. Lane, wiki, map and model members are public data and stay plaintext,
inside the private staging folder (R829 B).

**Where a key may go** (R829 A1): to SQLite only, and only as an argument, never as SQL text: ``set_key`` on a
connection that opens the file as its main database (the C API's ``sqlite3_key``), or the bound parameter of
``ATTACH ... KEY ?``. It is never in argv, a log, a report or an exception's text; :class:`StagedKey` has no readable
``repr``, and every failure here is raised with fixed words and no cause.

**The member is foreign input** (R829 A1, R826 b): every connection this module opens on a staged file has
``trusted_schema`` off and ``cell_size_check`` on, and :func:`check_staged_schema` refuses a file whose schema holds a
trigger, view or virtual table the app does not make itself, before any row of it is read.

The registry is per process and in memory only: a staged file the registry does not name is a plaintext file, read
the way it always was.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How a staged copy came to be keyed: ``member`` = the backup's own encrypted member, opened with the passphrase that
#: opens it (A1); ``ephemeral`` = a plaintext member re-keyed under a random key held only in this process (A2).
ORIGINS = ("member", "ephemeral")


class StagedKeyError(Exception):
    """A staged file could not be opened, sealed or checked. The message is fixed words only: never a key, never a
    driver's text (which can quote a damaged page), never a path beyond the file's own name."""


class NotADatabase(StagedKeyError):
    """The staged file does not open as a SQLite database at all: there is nothing to seal, and the validation refuses
    it in its own words a moment later."""


#: Why a staged database that opened could not be sealed: it could not be read to its end.
DAMAGED = "the backup's corpus is damaged: it could not be read in full, so nothing was imported"


@dataclass(frozen=True, eq=False)
class StagedKey:
    """The key of one staged file. ``secret`` is exactly what SQLite receives; it is never shown."""

    secret: bytes = field(repr=False)
    page_size: int | None
    origin: str

    def __repr__(self) -> str:  # never the secret, in any form
        return f"StagedKey(origin={self.origin!r}, page_size={self.page_size!r})"

    __str__ = __repr__

    def __reduce__(self):  # a key is never pickled: it would reach a file, a queue or another process
        raise TypeError("a staged key cannot be pickled")


_lock = threading.Lock()
_registry: dict[str, StagedKey] = {}


def _norm(path: os.PathLike[str] | str) -> str:
    return os.path.realpath(os.fspath(path))


def register(path: os.PathLike[str] | str, key: StagedKey) -> None:
    with _lock:
        _registry[_norm(path)] = key


def key_for(path: os.PathLike[str] | str) -> StagedKey | None:
    with _lock:
        return _registry.get(_norm(path))


def is_keyed(path: os.PathLike[str] | str) -> bool:
    return key_for(path) is not None


def forget(path: os.PathLike[str] | str) -> None:
    with _lock:
        _registry.pop(_norm(path), None)


def forget_under(folder: os.PathLike[str] | str) -> int:
    """Drop every key of a file in ``folder`` (a staging folder being removed). Returns how many."""
    root = _norm(folder).rstrip(os.sep) + os.sep
    with _lock:
        gone = [p for p in _registry if p.startswith(root)]
        for p in gone:
            del _registry[p]
    return len(gone)


def _driver():
    from sqlcipher3 import dbapi2 as sqc

    return sqc


def db_errors() -> tuple[type[BaseException], ...]:
    """The exception classes a staged-file read can raise: the stdlib's and sqlcipher3's, which share no base class."""
    try:
        return (sqlite3.Error, _driver().Error)
    except Exception:  # noqa: BLE001 - no driver: only the stdlib's
        return (sqlite3.Error,)


def _harden(conn: Any, schema: str | None = None) -> None:
    """The settings a foreign file is read under (R829 A1): functions in its schema run only if innocuous, and a cell
    whose size does not fit its page is an error rather than a read past it."""
    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute("PRAGMA cell_size_check = ON")
    if schema is None:
        conn.execute("PRAGMA mmap_size = 0")
    else:
        assert schema.isidentifier(), schema
        conn.execute(f'PRAGMA "{schema}".mmap_size = 0')


def _read_only_target(path: Path) -> str:
    from src.database.read_only_uri import read_only_uri

    return read_only_uri(path)


#: How long one open waits on another program's lock before it is refused as "in use" (row 156's answer).
BUSY_TIMEOUT_S = 5.0


def _open_with(path: Path, secret: bytes, page_size: int | None, *, read_only: bool, check_same_thread: bool):
    """One keyed open as the main database. Returns the connection once a read of the schema proves the key, else
    None (a wrong key, a wrong page size, or a file the driver cannot open), and closes what it opened either way.
    Another program's lock raises :class:`StagedKeyError` at once: no other key or size opens a held file (row 156)."""
    from src.database.connect import held_by_another, sqlite_opening

    sqc = _driver()
    conn = None
    try:
        with sqlite_opening():  # R789
            if read_only:
                conn = sqc.connect(
                    _read_only_target(path), uri=True, check_same_thread=check_same_thread, timeout=BUSY_TIMEOUT_S
                )
            else:
                conn = sqc.connect(str(path), check_same_thread=check_same_thread, timeout=BUSY_TIMEOUT_S)
        conn.set_key(secret)  # the C API, never SQL text
        if page_size is not None:
            conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqc.Error as exc:
        if conn is not None:
            with suppress(Exception):
                conn.close()
        if held_by_another(exc):
            raise StagedKeyError("another program is using the staged copy of the backup") from None
        return None
    except BaseException:
        if conn is not None:
            with suppress(Exception):
                conn.close()
        raise
    return conn


def open_staged(path: os.PathLike[str] | str, *, read_only: bool = True, check_same_thread: bool = True):
    """A connection to a staged file as its main database: keyed when the registry names it, else the plaintext open
    this file always had. Either way hardened for a foreign file."""
    p = Path(path)
    key = key_for(p)
    if key is None:
        if read_only:
            from src.database.read_only_uri import open_plain_read_only

            conn = open_plain_read_only(p)
        else:
            from src.database.connect import sqlite_opening

            with sqlite_opening():
                conn = sqlite3.connect(str(p), check_same_thread=check_same_thread)
        _harden(conn)
        return conn
    if not p.is_file():
        raise StagedKeyError("the staged copy of the backup is missing")
    conn = _open_with(p, key.secret, key.page_size, read_only=read_only, check_same_thread=check_same_thread)
    if conn is None:
        raise StagedKeyError("the staged copy of the backup no longer opens with its key")
    _harden(conn)
    return conn


def attach_staged(conn: Any, path: os.PathLike[str] | str, alias: str) -> bool:
    """ATTACH a keyed staged file on ``conn`` (a sqlcipher3 connection) with its key as a bound parameter. Returns
    False when the registry does not name the file (the caller attaches it as plaintext)."""
    key = key_for(path)
    if key is None:
        return False
    assert alias.isidentifier(), alias
    if "sqlcipher" not in type(conn).__module__:
        raise StagedKeyError("an encrypted staged copy can only be read through an encrypting connection")
    from src.database.connect import sqlite_opening

    old = None
    if key.page_size is not None:
        old = conn.execute("PRAGMA cipher_default_page_size").fetchone()
        conn.execute(f"PRAGMA cipher_default_page_size = {int(key.page_size)}")
    # A statement trace sees a statement with its bound values EXPANDED into the text (measured: ``select ?`` with
    # 'x' traces as ``select 'x'``, in both drivers), so none may watch the ATTACH: the merge's own statement timer is
    # installed per step, after this, and anything else watching is switched off here rather than handed the key.
    conn.set_trace_callback(None)
    try:
        with sqlite_opening():  # R789
            conn.execute(f'ATTACH DATABASE ? AS "{alias}" KEY ?', (str(path), key.secret))
    finally:
        if old is not None:
            with suppress(Exception):
                conn.execute(f"PRAGMA cipher_default_page_size = {int(old[0])}")
    try:
        _harden(conn, alias)
        conn.execute(f'SELECT count(*) FROM "{alias}".sqlite_master').fetchone()
    except BaseException:
        with suppress(Exception):
            conn.execute(f'DETACH DATABASE "{alias}"')
        raise StagedKeyError("the staged copy of the backup no longer opens with its key") from None
    return True


def _page_candidates() -> tuple[int, ...]:
    from src.database.connect import _PAGE_SIZE_CANDIDATES

    return _PAGE_SIZE_CANDIDATES


def adopt_member(path: os.PathLike[str] | str, passphrases: list[str]) -> bool:
    """A1: find the passphrase that opens an encrypted staged member, fold a carried write-ahead log into it, and
    register it. Returns False when none opens it (the caller names the fix). Never writes a plaintext byte."""
    from src.monitoring.secret_scrub import passphrase_bytes

    p = Path(path)
    for phrase in dict.fromkeys(k for k in passphrases if k):
        try:
            secret = passphrase_bytes(phrase)
        except Exception:  # noqa: BLE001 - a key that cannot be encoded opens nothing
            continue
        for size in _page_candidates():
            conn = _open_with(p, secret, size, read_only=False, check_same_thread=True)
            if conn is None:
                continue
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                conn.execute("PRAGMA journal_mode = DELETE").fetchone()
            except _driver().DatabaseError:
                raise StagedKeyError("the encrypted corpus in the backup could not be read") from None
            finally:
                with suppress(Exception):
                    conn.close()
            register(p, StagedKey(secret=secret, page_size=size, origin="member"))
            return True
    return False


def _raw_secret() -> bytes:
    # SQLCipher reads ``x'<64 hex>'`` handed to sqlite3_key / ATTACH KEY as a raw 256-bit key: no key derivation, and
    # nothing derived from any passphrase (R829 A2).
    return b"x'" + secrets.token_bytes(32).hex().encode("ascii") + b"'"


def seal_plaintext(path: os.PathLike[str] | str) -> None:
    """A2: re-key a plaintext staged file into a SQLCipher copy under a random in-memory key, put the copy at the same
    name, unlink the plaintext (and its ``-wal``/``-shm``), and register the key.

    The copy is made owner-only before a byte goes in, beside the original in the private staging folder; on any
    failure the unfinished copy is removed and the plaintext is left as it was (the caller's import then fails or goes
    on unsealed, never with a half-written file). The plaintext's blocks are unlinked, not overwritten: an erase of the
    data folder rewrites staging files whole (R797/R823), and a storage device that remaps blocks keeps old ones
    either way."""
    from src.backup.regular_file import create_new
    from src.database.connect import sqlite_opening

    p = Path(path)
    sealed = p.with_name(p.name + ".sealing")
    secret = _raw_secret()
    sqc = _driver()
    with sqlite_opening():  # R789
        src = sqc.connect(str(p), check_same_thread=True)
    try:
        _harden(src)
        try:
            src.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqc.DatabaseError:
            raise NotADatabase from None
        page_size = int(src.execute("PRAGMA page_size").fetchone()[0])
        auto_vacuum = int(src.execute("PRAGMA auto_vacuum").fetchone()[0])
        create_new(sealed, mode=0o600).close()
        src.set_trace_callback(None)  # as in attach_staged: a trace would see the key expanded into the ATTACH
        with sqlite_opening():
            src.execute("ATTACH DATABASE ? AS sealed KEY ?", (str(sealed), secret))
        src.execute(f"PRAGMA sealed.cipher_page_size = {page_size}")
        src.execute(f"PRAGMA sealed.auto_vacuum = {auto_vacuum}")
        cur = src.cursor()
        try:
            cur.execute("SELECT sqlcipher_export('sealed')")
        finally:
            cur.close()
        src.execute("DETACH DATABASE sealed")
    except BaseException as exc:
        with suppress(Exception):
            src.close()
        with suppress(OSError):
            sealed.unlink()
        if isinstance(exc, NotADatabase):
            raise
        if isinstance(exc, sqc.DatabaseError | sqlite3.DatabaseError):
            # It opened but could not be read to its end: damaged. Refused here, before hours of merging that its
            # integrity check would refuse at the end anyway, and never left on disk in plaintext for that time.
            raise StagedKeyError(DAMAGED) from None
        raise
    src.close()
    with open(sealed, "rb") as fh:  # the copy reaches the disk before the plaintext goes
        os.fsync(fh.fileno())
    os.replace(sealed, p)
    for suffix in ("-wal", "-shm", "-journal"):
        with suppress(FileNotFoundError):
            p.with_name(p.name + suffix).unlink()
    register(p, StagedKey(secret=secret, page_size=page_size, origin="ephemeral"))


# --------------------------------------------------------------------------- the schema of a foreign file

_OBJ_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


#: Triggers and virtual tables older builds made that this one no longer does, so an old backup still carries them.
#: Found from the history of every ``CREATE TRIGGER|VIEW|VIRTUAL TABLE`` in ``src/database``, ``src/analytics``,
#: ``src/backup`` and ``migrations`` (2026-11-24): the first search index's names. Everything current is read from the
#: live schema instead, so it is never listed twice.
_LEGACY_OBJECTS: dict[str, str] = {
    "articles_fts": "table",
    "articles_fts_insert": "trigger",
    "articles_fts_update": "trigger",
    "articles_fts_delete": "trigger",
}


def _known_objects() -> dict[str, str]:
    """``name -> type`` of every trigger, view and virtual table this app makes: the ones in the user's own corpus
    (made by this build: read from the live store's schema, never from the staged file) and the few older builds made
    (:data:`_LEGACY_OBJECTS`). Raises :class:`StagedKeyError` when the live schema cannot be read: the check fails closed."""
    try:
        from sqlalchemy import text

        from src.database.session import engine

        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')"
                    " OR (type = 'table' AND sql LIKE 'CREATE VIRTUAL TABLE%')"
                )
            ).fetchall()
    except Exception:  # noqa: BLE001 - fixed words; the reason is not the user's to act on
        raise StagedKeyError("the app's own schema could not be read, so the backup's corpus was not read") from None
    known = dict(_LEGACY_OBJECTS)
    known.update({str(name).lower(): str(typ) for typ, name in rows})
    return known



#: The modules a virtual table in a staged file may use: the app's own search index only.
_VTAB_MODULES = ("fts5", "fts5vocab")


def check_staged_schema(conn: Any, schema: str = "main") -> None:
    """Refuse a staged file whose schema holds anything the app does not make itself (R826 b, R829 A1): a trigger,
    view or virtual table of a name the app never creates, a virtual table on another module, or an object of a type
    SQLite does not make. Reads only ``sqlite_master``; raises :class:`StagedKeyError` with fixed words."""
    assert schema.isidentifier(), schema
    known = _known_objects()
    rows = conn.execute(f'SELECT type, name, sql FROM "{schema}".sqlite_master').fetchall()
    for typ, name, sql in rows:
        typ = str(typ)
        lname = str(name or "").lower()
        if typ not in ("table", "index", "trigger", "view"):
            raise StagedKeyError("the backup's corpus holds a schema object of an unknown kind; it was not read")
        if typ in ("trigger", "view"):
            if not _OBJ_NAME.match(lname) or known.get(lname) != typ:
                raise StagedKeyError(
                    f"the backup's corpus holds a {typ} this app does not make; it was not read"
                )
            continue
        if typ == "table" and sql and re.match(r"\s*CREATE\s+VIRTUAL\s+TABLE", str(sql), re.IGNORECASE):
            using = re.search(r"\bUSING\s+(\w+)", str(sql), re.IGNORECASE)
            module = using.group(1).lower() if using else ""
            if module not in _VTAB_MODULES or known.get(lname) != "table":
                raise StagedKeyError(
                    "the backup's corpus holds a virtual table this app does not make; it was not read"
                )
