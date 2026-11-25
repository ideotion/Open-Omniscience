"""The split corpus's segment opener (R826, row 409, stage 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS STAGE IS. How a segment file in ``<data>/corpus/`` is opened, checked and held, and how the set of them is
opened in the background after an unlock. Nothing reads an article from a segment yet (stage 4) and nothing writes
one (stage 3): :func:`create_segment` exists so the opener can be tested on real files, behind
:data:`SEGMENT_WRITES_ENABLED`, which stays False until the erase, backup/restore and passphrase stages are on main.
With an empty registry (every corpus today) :func:`start_background_open` opens nothing and starts no thread.

EVERY OPEN (R826 b and d):

1. The folder is the data folder's own ``corpus`` folder, a real directory; the file is ``seg-<n>.db`` exactly, a
   regular file with one name, and so is any ``-wal``, ``-shm`` or ``-journal`` beside it. Anything else is never
   opened. Its first 100 bytes are read BEFORE any driver sees the file: a plaintext file must be in rollback-journal
   mode (header bytes 18 and 19 both 1, as every segment this app makes is), so a read-only open never creates or
   writes a ``-wal`` or ``-shm``, and its encryption must already match the shared file's (step 3).
2. The open goes through the app's factory (:func:`src.database.connect.connect`), READ-ONLY, so it never creates a
   file and never writes one, with the corpus key and the page size this app creates segments at. A key that does not
   open the file makes THIS segment unavailable: the wrong-passphrase verdict comes from the shared file alone (R826
   Q4), never from a segment.
3. The segment must be encrypted exactly when the shared file is: checked on the header before the open, and again on
   the driver the open actually used (sqlcipher3 or the standard one), never on evidence kept from an earlier open.
   A plaintext segment beside an encrypted corpus is refused, never read: it would be a file this app did not make,
   or a downgrade.
4. Before any row is read: ``trusted_schema`` off, ``cell_size_check`` on, ``writable_schema`` off, no memory map,
   and SQLite's defensive setting where the driver exposes it (the standard driver does; SQLCipher's driver has no
   ``db_config``, so on an encrypted segment the exact schema check below is what stands in its place).
5. The schema must be EXACTLY the schema this build makes a segment with (:data:`SEGMENT_DDL`, compared object by
   object, SQL text included): no trigger, view, virtual table, index or table more or less. Only SQLite's own
   statistics tables may be there besides, with SQLite's own SQL.
6. The file's recorded identity (number and id range, written by ``segments.commit_segment``) must equal its
   registry row, so a file swapped in under a segment's name is never read as that segment.

A segment that fails any step is "segment N unavailable" with a fixed reason code, never a smaller count (R775).
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.database.segments import (
    _SEGMENT_META_DDL,
    SEGMENT_NAME_RE,
    Reservation,
    Segment,
    SegmentError,
    commit_segment,
    registry,
    segment_identity,
)
from src.monitoring.secret_scrub import log_failure

#: The plaintext SQLite header's first 16 bytes.
_SQLITE_MAGIC = b"SQLite format 3\x00"

#: What a segment's sidecar files may be called; each, if present, must be a regular file with one name.
_SIDECARS = ("-wal", "-shm", "-journal")

_LOG = logging.getLogger(__name__)

#: Stays False until stages 6, 7 and 8 (erase, backup/restore, passphrase change) are on main (R826). Nothing in the
#: app sets it; tests turn it on to make real segment files.
SEGMENT_WRITES_ENABLED = False

#: The schema a segment of this build is made with, in order. Stage 3 adds the per-article tables here; the opener's
#: check compares against exactly what these statements make, so the two can never drift apart.
SEGMENT_DDL: tuple[str, ...] = (_SEGMENT_META_DDL,)

#: SQLite's own statistics tables (``ANALYZE``, ``PRAGMA optimize``), allowed with exactly the SQL this SQLite writes for them:
#: read from an in-memory database ``ANALYZE`` just ran in, on the driver that opened the segment, never typed here.
def _sqlite_own(con: Any = None) -> frozenset[tuple[str, str, str, str]]:
    import importlib

    driver = importlib.import_module(type(con).__module__) if con is not None else sqlite3
    mem = driver.connect(":memory:")
    try:
        mem.executescript("CREATE TABLE t(x); CREATE INDEX i ON t(x); INSERT INTO t VALUES (1), (2); ANALYZE;")
        return frozenset(row for row in _schema_of(mem) if row[1].startswith("sqlite_stat"))
    finally:
        mem.close()

#: A closed segment is only read: its page cache is capped so 64 of them stay near 512 MB (Q4 measurement).
CLOSED_CACHE_KIB = 8192

#: Segments open on this many threads, newest first (R826 Q4; Q4 measured 2 vCPUs).
OPEN_THREADS = 2

#: The page size this app creates every encrypted segment at, declared on open so a wrong key costs one derivation.
SEGMENT_PAGE_SIZE = 16384

#: Why a segment is unavailable. Fixed codes: never a driver's text, a path or a key.
REASONS = (
    "missing",  # no file at the segment's name
    "not_a_segment_file",  # a link, a directory, a file with a second name, or a folder that is not the corpus folder
    "locked",  # the corpus is locked: no key to open it with
    "wrong_key",  # the corpus key does not open this file
    "in_use",  # another program holds a lock on the file
    "encryption_differs",  # plaintext beside an encrypted corpus, or the reverse
    "schema",  # the schema is not exactly the one this app makes
    "identity",  # the file records another segment, or no identity
    "changed_while_opening",  # the name led to another file by the end of the open
    "unreadable",  # anything else: damaged, held by another program, I/O
)


class SegmentUnavailable(Exception):
    """One segment could not be opened. ``reason`` is one of :data:`REASONS`; the message is fixed words only."""

    def __init__(self, seg_no: int, reason: str) -> None:
        assert reason in REASONS, reason
        super().__init__(f"segment {seg_no} unavailable")
        self.seg_no = seg_no
        self.reason = reason


def corpus_folder() -> Path:
    from src.database.at_rest_state import SEGMENT_DIR
    from src.paths import data_dir_path

    return data_dir_path() / SEGMENT_DIR


def _normal_sql(sql: Any) -> str:
    return " ".join(str(sql or "").split())


def reference_schema() -> frozenset[tuple[str, str, str, str]]:
    """What :data:`SEGMENT_DDL` makes, as (type, name, tbl_name, SQL with whitespace folded), read from an in-memory
    database the statements just ran in. Computed on every call: cheap, and never a stale copy."""
    con = sqlite3.connect(":memory:")
    try:
        for ddl in SEGMENT_DDL:
            con.execute(ddl)
        return _schema_of(con)
    finally:
        con.close()


def _schema_of(con: Any) -> frozenset[tuple[str, str, str, str]]:
    rows = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
    return frozenset((str(t), str(n), str(tb), _normal_sql(s)) for t, n, tb, s in rows)


def check_schema(con: Any) -> bool:
    """True when the open file's schema is exactly :func:`reference_schema`, plus at most SQLite's own statistics tables;
    False only for a schema that was READ and differs. A read that fails raises (the opener names it: "in_use" when another
    program holds a lock, "unreadable" otherwise), so a held or damaged file is never reported as a foreign schema. Reads
    ``sqlite_master`` only."""
    return _schema_of(con) - _sqlite_own(con) == reference_schema()


def harden(con: Any, *, closed: bool) -> bool:
    """The settings a segment is read under, before any row is read. Returns whether SQLite's defensive setting is on
    (the standard driver only; see the module text)."""
    con.execute("PRAGMA trusted_schema = OFF")
    con.execute("PRAGMA cell_size_check = ON")
    con.execute("PRAGMA writable_schema = OFF")
    con.execute("PRAGMA mmap_size = 0")
    if closed:
        con.execute(f"PRAGMA cache_size = -{int(CLOSED_CACHE_KIB)}")
    setconfig = getattr(con, "setconfig", None)
    if setconfig is None:
        return False
    setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    return True


def _identity_of_name(path: Path) -> tuple[int, int] | None:
    """(device, inode) of the regular, single-named file at ``path`` inside the corpus folder, else None."""
    folder = corpus_folder()
    if path.parent != folder:
        return None
    try:
        fst = os.lstat(folder)
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISDIR(fst.st_mode):
        return None  # a link where the corpus folder should be
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        return None
    return (st.st_dev, st.st_ino)


def _sidecars_are_plain(path: Path) -> bool:
    """Every ``-wal``/``-shm``/``-journal`` beside ``path`` is absent or a regular file with one name: SQLite would open
    and could write one, and a hard link or a link there would point that write at another file."""
    for suffix in _SIDECARS:
        try:
            st = os.lstat(f"{path}{suffix}")
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return False
    return True


def _absent_sidecars(path: Path) -> frozenset[str]:
    """The sidecar suffixes with nothing at their name now."""
    out = []
    for suffix in _SIDECARS:
        try:
            os.lstat(f"{path}{suffix}")
        except FileNotFoundError:
            out.append(suffix)
        except OSError:
            pass
    return frozenset(out)


def _remove_sidecars_made(path: Path, absent_before: frozenset[str]) -> None:
    """After a refused open: remove the ``-wal``/``-shm`` an open of a WAL-mode file made (a read-only open of one creates
    both). Only a name that was empty before the open and is now a regular file with one name, and a ``-wal`` only while
    it is empty (it then holds no page); never a ``-journal``, which a writer of the same file may be using. Best effort."""
    for suffix in ("-wal", "-shm"):
        if suffix not in absent_before:
            continue
        side = f"{path}{suffix}"
        try:
            st = os.lstat(side)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or (suffix == "-wal" and st.st_size != 0):
            continue
        with contextlib.suppress(OSError):
            os.unlink(side)


def _held_or_unreadable(exc: BaseException) -> str:
    from src.database.connect import held_by_another

    return "in_use" if held_by_another(exc) else "unreadable"


def _header_of(path: Path, ident: tuple[int, int]) -> bytes | None:
    """The first 100 bytes of the file at ``path``, read through the store's shared read descriptor (R789: never closes a
    descriptor another of this process's connections may hold a lock through), or None when the descriptor is not on
    the file ``ident`` names."""
    from src.database.connect import read_at, store_reader

    try:
        with store_reader(path) as fd:
            got = os.fstat(fd)
            if (got.st_dev, got.st_ino) != ident:
                return None
            return read_at(fd, 100, 0)
    except OSError:
        return None


def _header_encrypted(header: bytes) -> bool | None:
    """True: not a plaintext SQLite header (SQLCipher's page 1 begins with its random salt). False: a plaintext header in
    rollback-journal mode. None: a plaintext header in any other journal mode (WAL), or too short to be a segment."""
    if len(header) < 100:
        return None
    if header[:16] != _SQLITE_MAGIC:
        return True
    return False if (header[18], header[19]) == (1, 1) else None


def _shared_is_encrypted() -> bool | None:
    """The shared file's header, read now (never the cached reading: an encrypt-in-place changes it under the same name)."""
    from src.api.unlock import main_db_path
    from src.database.connect import is_encrypted_file

    main = main_db_path()
    return None if main is None else is_encrypted_file(main)


def open_segment(seg: Segment, *, key: str | None = None):
    """Open one registered segment for reading, checked as the module text says. Returns the connection (the caller
    closes it) or raises :class:`SegmentUnavailable`. ``key`` defaults to the process passphrase."""
    from src.database.connect import (
        DatabaseLockedError,
        StoreHeldError,
        WrongPassphraseError,
        _is_sqlcipher_conn,
        connect,
    )

    if seg.implicit or seg.file_name is None or seg.seg_no < 1:
        raise SegmentError("segment 0 is the shared file itself; it is not opened here")
    if SEGMENT_NAME_RE.match(seg.file_name) is None:
        raise SegmentUnavailable(seg.seg_no, "not_a_segment_file")
    path = corpus_folder() / seg.file_name
    try:
        os.lstat(path)
    except FileNotFoundError:
        raise SegmentUnavailable(seg.seg_no, "missing") from None
    except OSError:
        raise SegmentUnavailable(seg.seg_no, "unreadable") from None
    before = _identity_of_name(path)
    if before is None or not _sidecars_are_plain(path):
        raise SegmentUnavailable(seg.seg_no, "not_a_segment_file")
    header = _header_of(path, before)
    if header is None:
        raise SegmentUnavailable(seg.seg_no, "changed_while_opening")
    on_disk = _header_encrypted(header)
    if on_disk is None:
        raise SegmentUnavailable(seg.seg_no, "not_a_segment_file")
    shared_encrypted = _shared_is_encrypted()
    if shared_encrypted is None or on_disk != shared_encrypted:
        raise SegmentUnavailable(seg.seg_no, "encryption_differs")
    absent_before = _absent_sidecars(path)
    try:
        con = connect(path, key=key, read_only=True, check_same_thread=False, cipher_page_size=SEGMENT_PAGE_SIZE)
    except StoreHeldError:
        raise SegmentUnavailable(seg.seg_no, "in_use") from None
    except WrongPassphraseError:
        raise SegmentUnavailable(seg.seg_no, "wrong_key") from None
    except DatabaseLockedError:
        # No key: the corpus is locked, or (a plaintext corpus) the file is not plaintext like the corpus is.
        reason = "locked" if shared_encrypted else "encryption_differs"
        raise SegmentUnavailable(seg.seg_no, reason) from None
    except FileNotFoundError:
        _remove_sidecars_made(path, absent_before)
        raise SegmentUnavailable(seg.seg_no, "missing") from None
    except Exception as exc:  # noqa: BLE001 - damaged, held, I/O: one fixed reason, the text stays in the debug log
        log_failure(_LOG, "a corpus segment could not be opened", exc, level=logging.DEBUG)
        _remove_sidecars_made(path, absent_before)
        raise SegmentUnavailable(seg.seg_no, _held_or_unreadable(exc)) from None
    try:
        if _identity_of_name(path) != before:
            raise SegmentUnavailable(seg.seg_no, "changed_while_opening")
        # An encrypted header hides the journal mode, so it is asked here: a segment is always in rollback-journal mode
        # (the mode this app makes it in). A WAL-mode file is refused, and the -wal/-shm its open made are removed below.
        mode = con.execute("PRAGMA journal_mode").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise SegmentUnavailable(seg.seg_no, "not_a_segment_file")
        # The driver the open used, never evidence from an earlier open: a plaintext file swapped in for the open and back
        # out again is opened by the standard driver, and is refused here.
        if _is_sqlcipher_conn(con) != bool(shared_encrypted):
            raise SegmentUnavailable(seg.seg_no, "encryption_differs")
        harden(con, closed=seg.state == "closed")
        if not check_schema(con):
            raise SegmentUnavailable(seg.seg_no, "schema")
        if segment_identity(con) != (seg.seg_no, seg.id_lo, seg.id_hi):
            raise SegmentUnavailable(seg.seg_no, "identity")
    except SegmentUnavailable:
        con.close()
        _remove_sidecars_made(path, absent_before)
        raise
    except Exception as exc:  # noqa: BLE001 - see above
        con.close()
        _remove_sidecars_made(path, absent_before)
        log_failure(_LOG, "a corpus segment could not be checked", exc, level=logging.DEBUG)
        raise SegmentUnavailable(seg.seg_no, _held_or_unreadable(exc)) from None
    return con


def create_segment(r: Reservation, *, key: str | None = None) -> Path:
    """Make the new, empty segment file of a reservation (``segments.reserve_segment`` step 2): created through the app's
    factory with the corpus key (SQLCipher gives every new file its own random salt in page 1), the schema of
    :data:`SEGMENT_DDL` and its identity written in the file's own transaction, then read back with the key and named in
    the at-rest record while that keyed read is open (R828). Refused unless :data:`SEGMENT_WRITES_ENABLED`."""
    from src.database.at_rest_state import record_segment
    from src.database.connect import connect
    from src.paths import refuse_if_erased

    if not SEGMENT_WRITES_ENABLED:
        raise SegmentError("segment files are not written by this build yet")
    if SEGMENT_NAME_RE.match(r.file_name) is None:
        raise SegmentError("not a segment file name")
    folder = corpus_folder()
    refuse_if_erased(folder)
    with contextlib.suppress(FileExistsError):
        os.mkdir(folder, 0o700)
    st = os.lstat(folder)
    if not stat.S_ISDIR(st.st_mode):
        raise SegmentError("the corpus folder is not a folder")
    encrypted = _shared_is_encrypted()
    if encrypted is None:
        raise SegmentError("the shared file's encryption could not be read")
    path = folder / r.file_name
    # The name is TAKEN here, empty, by this call alone: O_EXCL refuses any file or link already there, O_NOFOLLOW any link,
    # and the factory then treats the empty file as fresh. Its (device, inode) is checked again before anything is written,
    # so a name swapped for a link to another file (the shared corpus, under the same key) gets no table and no row.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    except FileExistsError:
        raise SegmentError("a file already has this segment's name; it is never overwritten") from None
    try:
        made = os.fstat(fd)
    finally:
        os.close(fd)  # nothing of this process holds the new, empty file yet (R789)
    ident = (made.st_dev, made.st_ino)
    try:
        if encrypted:
            con = connect(path, key=key, create_encrypted=True, cipher_page_size=SEGMENT_PAGE_SIZE)
        else:
            con = connect(path, create_encrypted=False)
        try:
            if _identity_of_name(path) != ident:
                raise SegmentError("the segment's name led to another file while it was being made; nothing was written")
            con.isolation_level = None
            for ddl in SEGMENT_DDL:
                if ddl is _SEGMENT_META_DDL:
                    continue
                con.execute(ddl)
            if _identity_of_name(path) != ident:
                raise SegmentError("the segment's name led to another file while it was being made; nothing was written")
            commit_segment(con, r)
        finally:
            con.close()
        if encrypted:
            # A fresh file counts as keyed only once it is reopened with the key (lane D, R828).
            seg = Segment(r.seg_no, r.file_name, "reserved", r.id_lo, r.id_hi)
            back = open_segment(seg, key=key)
            try:
                if not record_segment(path):
                    raise SegmentError("the new segment could not be named in the at-rest record")
            finally:
                back.close()
    except BaseException:
        if not _remove_failed_create(folder, r.file_name, ident):
            raise SegmentError(
                "the segment could not be made, and the file at its name is not the one this call made; it was left in place"
            ) from None
        raise
    return path


def _remove_failed_create(folder: Path, name: str, ident: tuple[int, int]) -> bool:
    """A create that failed frees its name: the file goes when the name still leads to the very file this call made (same
    device and inode, regular, one name), looked at and removed relative to the corpus folder's own descriptor where the
    system offers one. Anything else at the name is never touched, and False says so. True also when the name is already
    empty. Once the file is gone, a regular single-named sidecar left at its name goes too: a journal left beside a name
    would otherwise be rolled into the next file made there."""
    if os.unlink in os.supports_dir_fd and os.lstat in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            dfd = os.open(folder, flags)
        except OSError:
            return False
        try:
            return _remove_at(name, ident, dfd)
        finally:
            os.close(dfd)
    if _identity_of_name(folder / name) not in (None, ident):
        return False
    return _remove_at(str(folder / name), ident, None)


def _remove_at(name: str, ident: tuple[int, int], dfd: int | None) -> bool:
    def plain(n: str) -> os.stat_result | None:
        st = os.lstat(n, dir_fd=dfd)
        return st if stat.S_ISREG(st.st_mode) and st.st_nlink == 1 else None

    try:
        try:
            st = plain(name)
        except FileNotFoundError:
            gone = True
        else:
            if st is None or (st.st_dev, st.st_ino) != ident:
                return False
            os.unlink(name, dir_fd=dfd)
            gone = True
        for suffix in _SIDECARS:
            with contextlib.suppress(OSError):
                if plain(name + suffix) is not None:
                    os.unlink(name + suffix, dir_fd=dfd)
        return gone
    except OSError:
        return False


@dataclass
class SegmentSet:
    """The registered segments of the corpus and their connections, opened in the background newest first. Thread-safe;
    :meth:`status` is what the UI and every count read while opening (R826 Q4: "N of M segments")."""

    segments: list[Segment] = field(default_factory=list)
    _cons: dict[int, Any] = field(default_factory=dict)
    _unavailable: dict[int, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _done: threading.Event = field(default_factory=threading.Event)
    _closed: bool = False

    @staticmethod
    def wanted(all_segments: list[Segment]) -> list[Segment]:
        """The segments that hold articles in their own file: open or closed, numbered 1 and up, newest first."""
        out = [s for s in all_segments if not s.implicit and s.seg_no >= 1 and s.state in ("open", "closed")]
        return sorted(out, key=lambda s: s.seg_no, reverse=True)

    def open_all(self, *, threads: int = OPEN_THREADS, key: str | None = None) -> None:
        """Open every wanted segment, newest first, on ``threads`` threads; returns when all have been tried."""
        try:
            if not self.segments:
                return
            with ThreadPoolExecutor(max_workers=max(1, threads), thread_name_prefix="oo-segment-open") as pool:
                for _ in pool.map(lambda s: self._open_one(s, key), self.segments):
                    pass
        finally:
            self._done.set()

    def _open_one(self, seg: Segment, key: str | None) -> None:
        with self._lock:
            if self._closed:
                return  # a closed set opens nothing more
        try:
            con = open_segment(seg, key=key)
        except SegmentUnavailable as exc:
            with self._lock:
                self._unavailable[seg.seg_no] = exc.reason
            return
        except Exception as exc:  # noqa: BLE001 - one segment never stops the others
            log_failure(_LOG, "a corpus segment could not be opened", exc, level=logging.DEBUG)
            with self._lock:
                self._unavailable[seg.seg_no] = "unreadable"
            return
        with self._lock:
            if self._closed:
                con.close()
                return
            self._cons[seg.seg_no] = con

    def connection(self, seg_no: int):
        with self._lock:
            return self._cons.get(seg_no)

    def status(self) -> dict:
        """``total`` M, ``opened`` N, ``opening`` (still trying), and each unavailable segment with its reason code. Numbers
        only, never a path."""
        with self._lock:
            return {
                "total": len(self.segments),
                "opened": len(self._cons),
                "opening": not self._done.is_set(),
                "unavailable": [
                    {"segment": n, "reason": self._unavailable[n]} for n in sorted(self._unavailable)
                ],
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            cons, self._cons = list(self._cons.values()), {}
        for con in cons:
            try:
                con.close()
            except Exception as exc:  # noqa: BLE001 - closing is best effort
                log_failure(_LOG, "a corpus segment did not close cleanly", exc, level=logging.DEBUG)


_CURRENT: SegmentSet | None = None
_CURRENT_LOCK = threading.Lock()
#: Bumped by every :func:`close_all` (each disposal: lock, erase, restore): a set built from a registry read that a disposal
#: overtook is closed, never installed.
_EPOCH = 0
#: True when the last start could not read the registry: health then says so, never "no segments".
_REGISTRY_UNREAD = False

#: What the status says when the registry could not be read: the number of segments is unknown, never 0 (R775).
REGISTRY_UNREADABLE: dict[str, Any] = {"total": None, "opened": None, "opening": False, "unavailable": [], "registry": "unreadable"}


def current_status() -> dict:
    """The live set's :meth:`SegmentSet.status`; :data:`REGISTRY_UNREADABLE` when the last start could not read the
    registry; an empty set's (``total`` 0) when none is registered or nothing was started."""
    with _CURRENT_LOCK:
        cur, unread = _CURRENT, _REGISTRY_UNREAD
    if cur is None:
        return dict(REGISTRY_UNREADABLE) if unread else {"total": 0, "opened": 0, "opening": False, "unavailable": []}
    return cur.status()


def start_background_open(shared_con_factory: Any = None) -> SegmentSet | None:
    """Read the registry from the shared file and open its segments in a background thread, replacing (and closing) any
    set opened before. With no segment file registered (every corpus today) nothing starts and None is returned.
    ``shared_con_factory`` returns a DB-API connection to the shared file (default: one from the app's pool)."""
    global _CURRENT, _REGISTRY_UNREAD
    if shared_con_factory is None and not _shared_is_sqlite():
        return None  # segments are SQLite files beside a SQLite corpus; another backend has none
    with _CURRENT_LOCK:
        epoch = _EPOCH
    try:
        con = shared_con_factory() if shared_con_factory is not None else _shared_read_only()
        try:
            segs = SegmentSet.wanted(registry(con))
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - an unreadable registry opens nothing, and the status says it was not read
        log_failure(_LOG, "the corpus segment registry could not be read", exc, level=logging.DEBUG)
        with _CURRENT_LOCK:
            if epoch == _EPOCH:
                old, _CURRENT, _REGISTRY_UNREAD = _CURRENT, None, True
            else:
                old = None
        if old is not None:
            old.close()
        return None
    new = SegmentSet(segments=segs) if segs else None
    with _CURRENT_LOCK:
        if epoch != _EPOCH:
            # A disposal ran while the registry was read: that registry may be the old store's, and the key may be gone.
            return None
        old, _CURRENT, _REGISTRY_UNREAD = _CURRENT, new, False
    if old is not None:
        old.close()
    if new is None:
        return None
    threading.Thread(target=new.open_all, name="oo-segment-opener", daemon=True).start()
    return new


def close_all() -> None:
    """Close the live set (lock, erase, shutdown)."""
    global _CURRENT, _EPOCH, _REGISTRY_UNREAD
    with _CURRENT_LOCK:
        old, _CURRENT, _REGISTRY_UNREAD = _CURRENT, None, False
        _EPOCH += 1
    if old is not None:
        old.close()


class _PooledShared:
    """A pooled connection to the shared file, with the two calls :func:`segments.registry` makes."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, *args: Any):
        return self._raw.driver_connection.execute(sql, *args)

    def close(self) -> None:
        self._raw.close()  # back to the pool, never a close of the store


def _shared_is_sqlite() -> bool:
    from src.database.session import engine

    return engine.dialect.name == "sqlite"


def _shared_read_only() -> _PooledShared:
    from src.database.session import engine

    return _PooledShared(engine.raw_connection())
