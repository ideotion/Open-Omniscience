"""
Two-phase secure wipe — crypto-erase (instant) + optional full free-space scrub.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The panic-wipe feature exists for a journalist who must destroy a corpus *now* in
the face of an imminent seizure. The old implementation overwrote only the first
4 MiB of every file before unlinking, so most of a multi-GB corpus survived,
forensically recoverable (audit OO-02). This module replaces that with two honest
phases:

  1. ``quick_crypto_erase`` — the surgical quick pass. The store is SQLCipher
     encrypted by default and its key is derived from a random 16-byte salt kept
     in the first database page. Destroy that page and the key can NEVER be
     re-derived: the ciphertext body (however many GB) becomes permanent noise
     without touching it. Instant at any size, safe if interrupted. It also
     destroys the on-disk signing keys, ``anchors.db`` (encrypted or plaintext,
     matching the corpus since audit finding L1, 2026-07-17 -- either way a full
     overwrite destroys it), clears the in-memory passphrase, and removes the
     data dir.

  2. ``full_secure_erase`` — an OPTIONAL defence-in-depth pass. Because the quick
     pass already unlinked the files, this scrubs the freed ciphertext blocks by
     filling the volume's free space with random data (chunked, ``passes`` times).
     Honest about its limit: on SSD/flash/copy-on-write filesystems wear-levelling
     can retain blocks, so this is belt-and-braces on top of crypto-erase, never a
     stronger guarantee than it.

Both refuse to run without an explicit ``confirm``. Neither implies physical
erasure it cannot deliver — the real guarantee is the destroyed salt.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import os
import re
import shutil
import stat
import threading
from pathlib import Path

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

# SQLCipher default scheme: the 16-byte random salt lives in the first page. The
# app applies no ``cipher_plaintext_header_size`` override (src/database/connect.py),
# so overwriting page 1 destroys the salt -> the PBKDF2 key is underivable forever.
_SQLCIPHER_PAGE1 = 4096

# Bound RAM/time for both the chunked full overwrite and the free-space scrub.
_CHUNK = 8 * 1024 * 1024

# The full-overwrite pass count is user-chosen from this set (Single/Triple/Octuple).
_ALLOWED_PASSES = (1, 3, 8)

# File names under the data dir (all resolved through the real resolvers for the
# default store; derived from the base dir when an explicit dir is passed).
_MAIN_DB = "open_omniscience.db"
_CUSTODY_DB = "custody_log.db"
_ANCHORS_DB = "anchors.db"
# The cache, the sidecar that holds the salt its key is stretched with (``columnar._KDF_SIDECAR_SUFFIX``), the log the engine
# leaves beside the cache after an unclean end (ciphertext under the same key, so with the sidecar gone it is noise, but it is
# the store's own file) and the gate's probe.
_DUCK_FILES = ("analytics.duckdb", "analytics.duckdb.kdf", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb")
_KEY_FILES = ("custody_ed25519.pem", "custody_ml_dsa_65.key")

_LIMIT_NOTE = (
    "The guarantee here is crypto-erase: the SQLCipher salt is destroyed, so the "
    "encrypted corpus is permanently unrecoverable regardless of storage medium. A "
    "byte-overwrite pass is defence-in-depth only — it does NOT guarantee "
    "unrecoverability on SSD/flash or copy-on-write filesystems (wear-levelling / "
    "snapshots may retain old blocks). For belt-and-braces on a plaintext store, use "
    "full-disk encryption (LUKS/Qubes/Tails) and destroy that key too."
)


def _overwrite(path: Path, *, head_bytes: int | None = None, zeros: bool = False) -> bool:
    """Overwrite ``path`` in place with random data, then fsync. When ``head_bytes``
    is given only that prefix is overwritten (the crypto-erase salt-page case);
    otherwise the whole file is overwritten in bounded chunks (small files only —
    the big encrypted corpus is handled by its header, never rewritten). Returns
    whether every byte was actually written and fsynced -- callers must NOT report
    a destructive overwrite as done just because no exception reached them; a
    silent False here with the outcome still reported as success is exactly the
    false-confidence bug audit OO-02 exists to eliminate.

    Writes ONLY a regular file at ``path`` itself: a symlink is never written through (its target may be anywhere,
    outside the data dir included) and a FIFO, socket or device is never opened to write (it would block or reach
    hardware); either is reported as not overwritten. ``O_NOFOLLOW`` where the platform has it, so a name swapped for
    a link between a check and the open is refused too; elsewhere the link check right before the open."""
    try:
        if path.is_symlink():
            raise OSError("a link is never written through")
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_BINARY", 0))
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError("not a regular file")
        except OSError:
            os.close(fd)
            raise
        size = st.st_size
        limit = size if head_bytes is None else min(size, head_bytes)
        with os.fdopen(fd, "r+b", buffering=0) as f:
            written = 0
            # ``while True: if not <wanted>: break``, not ``while <wanted>:``: the back-edge of the second sits outside the ``with``'s exception table
            # on CPython 3.13 (src/utils/interrupts.py; R161/R163)
            while True:
                if written >= limit:
                    break
                n = min(_CHUNK, limit - written)
                chunk = bytes(n) if zeros else os.urandom(n)
                f.write(chunk)
                written += len(chunk)
            f.flush()
            os.fsync(f.fileno())
        return True
    except OSError:
        _LOG.warning("crypto-erase: overwrite failed for %s (NOT destroyed)", path)
        return False


# Descriptors the panic wipe keeps on the files it unlinked, as (fd, whole), one list per wipe (its GENERATION): a transaction
# already under way when the erase ran still holds the unlinked file and, on commit, writes page 1 -- salt included -- into it.
# Per wipe (row 36), so the late pass of one wipe closes its own descriptors and never a second wipe's, whose own late pass then
# comes its full delay after that second erase.
_HELD: dict[int, list[tuple[int, bool]]] = {}
_HELD_LOCK = threading.Lock()
_GENERATIONS = itertools.count(1)


def new_hold_generation() -> int:
    """A number of its own for one wipe's kept descriptors."""
    return next(_GENERATIONS)


def _hold(path: Path, *, whole: bool, generation: int = 0) -> None:
    """Keep a descriptor on ``path`` for :func:`rescrub_held`. POSIX only: on Windows an open descriptor would make the
    unlink fail. Never raises."""
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:  # a FIFO, socket or device is never kept to write to
        os.close(fd)
        return
    # No lock: the erase waits on nothing, and a rescrub of an earlier wipe may hold it for a long rewrite. ``setdefault`` and a
    # list append are atomic, and a pass takes only the entries present when it starts, removing them from the front.
    _HELD.setdefault(generation, []).append((fd, whole))


def rescrub_held(*, close: bool, generation: int | None = None) -> int:
    """Overwrite again, through the kept descriptors, the head of every unlinked main file and the whole of every
    unlinked -wal and -journal; with ``close`` the descriptors are then let go. Only one wipe's with ``generation``, every
    wipe's without. Returns how many were rewritten. Never raises: the wipe is done, this closes the window a late commit
    leaves."""
    done = 0
    # The lock is held for the whole rewrite, so a closing pass can never close a descriptor another pass is still writing
    # through (its number could already belong to an unrelated file). Never on a latency path: the wipe has returned.
    with _HELD_LOCK:
        gens = list(_HELD) if generation is None else [generation]
        taken = {g: len(_HELD.get(g, ())) for g in gens}
        held = [e for g in gens for e in _HELD.get(g, [])[: taken[g]]]
        if close:
            _forget_held(taken)
        done = _rewrite_held(held, close=close)
    return done


def _forget_held(taken: dict[int, int]) -> None:
    """Drop the first ``n`` entries of each generation a closing pass took (later appends stay), and an emptied generation."""
    for g, n in taken.items():
        kept = _HELD.get(g)
        if kept is None:
            continue
        del kept[:n]
        if not kept:
            _HELD.pop(g, None)


def held_count(generation: int | None = None) -> int:
    """How many descriptors :func:`rescrub_held` still holds: one wipe's with ``generation``, every wipe's without."""
    if generation is not None:
        return len(_HELD.get(generation, ()))
    return sum(len(v) for v in list(_HELD.values()))


def _rewrite_held(held: list[tuple[int, bool]], *, close: bool) -> int:
    done = 0
    for fd, whole in held:
        try:
            size = os.fstat(fd).st_size
            limit = size if whole else min(size, _SQLCIPHER_PAGE1)
            os.lseek(fd, 0, os.SEEK_SET)
            written = 0
            while True:
                if written >= limit:
                    break
                written += os.write(fd, os.urandom(min(_CHUNK, limit - written)))
            os.fsync(fd)
            done += 1
        except OSError:
            _LOG.warning("crypto-erase: a held file could not be rewritten again")
        finally:
            if close:
                with contextlib.suppress(OSError):
                    os.close(fd)
    return done


def _is_link(p: Path) -> bool:
    """A symlink, or a Windows junction (which ``os.walk(followlinks=False)`` still enters)."""
    try:
        return p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)())
    except OSError:
        return True  # unknown: treated as a link, never entered


def _real(db: Path) -> Path:
    try:
        return db.resolve() if db.is_symlink() else db
    except OSError:
        return db


def _key_files_lock() -> contextlib.AbstractContextManager:
    """The lock every key-file name change in this process takes (``src/custody/keyfile.py``); a no-op
    stand-in when that module cannot be imported, since an erase must never be blocked by bookkeeping."""
    try:
        from src.custody.keyfile import KEY_FILES_LOCK
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not take the key-file lock for the erase", exc, level=logging.WARNING)
        return contextlib.nullcontext()
    return KEY_FILES_LOCK


#: The key files the app keeps beside the two named above: the evidence-signing key (src/reporting/evidence.py) and the
#: private copies a key change stages in ``keys/.pending`` (src/custody/keyfile.py). In a shared folder every file whose name
#: ends like one of the app's key forms goes too (the annotation signer, a key a restore placed: src/backup/merge.py _KEY_FORMS).
_OTHER_KEY_FILES = ("evidence_ed25519.pem",)
_KEYS_PENDING = ".pending"
KEY_FORM_SUFFIXES = ("_ed25519.pem", "_ml_dsa_65.key")


def _destroy_keys_folder(keys_dir: Path, track, keys_destroyed: list[str], unlisted=None, *, shared: bool = False) -> tuple[int, int]:
    """Step 2 and 2b of the quick erase, ``(seen, wiped)``: the named key files, then everything else in the keys folder
    (the evidence key, a private copy in ``keys/.pending``), then the folder itself, so nothing can be added to it
    before the caller lets the key-file lock go. In a SHARED data folder (R711) a ``keys`` folder may be the operator's
    own, so only the app's key files and its ``.pending`` folder go, and the folder is removed only if that left it empty. A function of its own with no handler, called inside the caller's
    ``with``: CPython 3.13 leaves a loop's back-edge outside the exception table of the block around it, so the loops
    live here (R163; tests/test_loop_heads_reach.py)."""
    seen = wiped = 0
    for name in _KEY_FILES:
        s, overwritten, w = track(keys_dir / name)
        seen += s
        wiped += w
        if s and overwritten:
            keys_destroyed.append(name)
    if shared:
        others = [e.name for e in _listing(keys_dir) if e.name.endswith(KEY_FORM_SUFFIXES) and e.name not in _KEY_FILES]
        for name in dict.fromkeys([*_OTHER_KEY_FILES, *others]):
            s, _overwritten, w = track(keys_dir / name)
            seen += s
            wiped += w
        pending = keys_dir / _KEYS_PENDING
        if _is_link(pending) or not pending.is_dir():
            with contextlib.suppress(OSError):
                keys_dir.rmdir()  # only when empty: what is left in it is not the app's to remove
            return seen, wiped
        keys_dir = pending  # walked and removed below, like the whole folder in the app's own data folder
    if keys_dir.is_dir():
        for root, dirs, names in os.walk(keys_dir, onerror=unlisted):
            dirs[:] = [d for d in dirs if not _is_link(Path(root, d))]  # a junction too, never entered
            for name in names:
                s, _overwritten, w = track(Path(root) / name)
                seen += s
                wiped += w
        shutil.rmtree(keys_dir, ignore_errors=True)
    if shared:
        with contextlib.suppress(OSError):
            keys_dir.parent.rmdir()  # only when empty: what is left in it is not the app's to remove
    return seen, wiped


def _shred(path: Path, *, head_bytes: int | None = None, zeros: bool = False) -> tuple[bool, bool, bool]:
    """Overwrite then unlink ``path``. Returns ``(seen, overwritten, unlinked)``:
    ``seen`` is whether the file existed, ``overwritten`` whether the destructive
    write actually completed, ``unlinked`` whether the directory entry was removed.
    These are reported separately -- a failed overwrite followed by a successful
    unlink is NOT destruction, it's just deletion, and callers must not conflate
    the two when claiming a salt page or key file was destroyed."""
    try:
        if not path.exists():
            return (False, False, False)
    except OSError:
        return (False, False, False)
    overwritten = _overwrite(path, head_bytes=head_bytes, zeros=zeros)
    try:
        path.unlink()
        return (True, overwritten, True)
    except OSError:
        _LOG.warning("crypto-erase: could not unlink %s", path)
        return (True, overwritten, False)


def _lane_dbs(base: Path) -> list[Path]:
    """Every versioned-source lane file under ``base``, present or not.

    WHY THESE ARE NOT "ANYTHING ELSE UNDER THE DATA DIR". Step 6 of the erase overwrites
    and unlinks whatever remains, and its own comment states the premise it rests on:
    *"remaining files are small side files, so a full overwrite here is cheap and
    complete"*. Q719 = a exists precisely because a lane may reach 100 GB. Left to step
    6, a lane would be FULLY rewritten — turning an operation whose whole promise is
    "instant at any corpus size" into an hours-long one, and quietly replacing the
    CRYPTO-erase guarantee (destroy the salt, the body is unreadable) with a DATA-erase
    that has to finish to be worth anything. Nothing would have caught it: no test
    asserts that the erase is fast.

    So lanes join step 1's head-shred, where the salt page is. Resolved from the lane
    REGISTRY rather than from a glob, so a lane kind added later is covered the day it
    is added, and a stray ``*.db`` an operator dropped in the folder is not mistaken for
    one of ours.
    """
    from src.versioned.lanes import all_lanes

    return [base / spec.filename for spec in all_lanes()]


def _resolve(data_dir: Path | None) -> dict:
    """Resolve every wipe target. For the default store (``data_dir is None``) the
    real resolvers are used so nothing is hardcoded; an explicit dir (tests/tools)
    derives the same layout from that base."""
    from src.paths import data_dir as _default_dir

    if data_dir is not None:
        base = Path(data_dir)
        return {
            "base": base,
            "main_db": base / _MAIN_DB,
            "keys_dir": base / "keys",
            "store_dir": base,
            "custody_db": base / _CUSTODY_DB,
            "anchors_db": base / _ANCHORS_DB,
            "lane_dbs": _lane_dbs(base),
        }
    base = _default_dir()
    from src.analytics.columnar import _store_dir
    from src.api.unlock import main_db_path
    from src.custody.signing import _keys_dir

    return {
        "base": base,
        "main_db": main_db_path(),  # honors DATABASE_URL; None on a non-SQLite backend
        "keys_dir": _keys_dir(),
        "store_dir": _store_dir(),
        "custody_db": base / _CUSTODY_DB,
        "anchors_db": base / _ANCHORS_DB,
        "lane_dbs": _lane_dbs(base),
    }


# The names the app gives a copy of one of its databases, kept beside it (row 29): a repair's salvage and damaged copies
# (src/database/repair.py), an encryption's pre-encrypt snapshot and in-progress copy (src/database/encrypt_tool.py), and,
# in the data folder only, a retained pre-restore snapshot (src/backup/merge.py). Each with the side files the app gives it.
_STAMP = r"\d{8}T\d{6}Z"
_COPY_TAIL = r"(?:(?:\.partial)?(?:-wal|-shm|-journal)?|\.json)"
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _copy_patterns(folder: Path, base: Path, dbs: list[Path]) -> list[re.Pattern[str]]:
    pats = []
    for db in dbs:
        if db.parent != folder:
            continue
        stem, suffix = re.escape(db.stem), re.escape(db.suffix)
        pats.append(re.compile(rf"{stem}\.(?:salvage|damaged)-{_STAMP}(?:-\d+)?{suffix}{_COPY_TAIL}"))
        pats.append(re.compile(rf"pre-encrypt-{_STAMP}-{re.escape(db.name)}{_COPY_TAIL}"))
        pats.append(re.compile(rf"{re.escape(db.name)}\.enc-{_STAMP}{_COPY_TAIL}"))
    if folder == base:
        pats.append(re.compile(rf"pre-restore-{_STAMP}\.db{_COPY_TAIL}"))
    return pats


def _listing(folder: Path) -> list[os.DirEntry]:
    """The top-level entries of ``folder``, or none when it cannot be listed. ``list`` closes the scan as it ends it."""
    try:
        return list(os.scandir(folder))
    except OSError:
        return []


def _db_copies(folder: Path, base: Path, dbs: list[Path]) -> list[Path]:
    """The app's own copies of a database in ``folder``, by name; regular files only (a link is left to step 6)."""
    pats = _copy_patterns(folder, base, dbs)
    if not pats:
        return []
    out = []
    for entry in _listing(folder):
        if not any(p.fullmatch(entry.name) for p in pats):
            continue
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        out.append(Path(entry.path))
    return out


def _copy_mode(p: Path, *, encrypted_store: bool) -> str:
    """How a copy is destroyed: ``whole`` (a log or a side file: the salt sits past the head, or there is no salt), ``zeros``
    (a -shm index: no page data), ``plain`` (a plaintext database: no salt to lose, so rewritten whole, later) or ``head``
    (an encrypted database: its salt is its first page). Only a copy of a store KNOWN to be encrypted is ever head-only: a
    damaged copy of a plaintext store can have a page 1 that no longer reads as SQLite and a plaintext body behind it. A
    head that cannot be read counts as plaintext: rewritten whole."""
    name = p.name
    if name.endswith(("-wal", "-journal", ".json")):
        return "whole"
    if name.endswith("-shm"):
        return "zeros"
    if name.startswith("pre-encrypt-") or not encrypted_store:
        return "plain"
    try:
        with open(p, "rb") as f:
            head = f.read(len(_SQLITE_MAGIC))
    except OSError:
        return "plain"
    return "plain" if head == _SQLITE_MAGIC else "head"


def _erase_roots(base: Path, *, app_only: bool) -> list[Path]:
    """What steps 5b and 6 reach: the data folder whole, or, in a folder the app does not own (R711), each top-level entry the app
    owns there, by name."""
    if not base.exists():
        return []
    if not app_only:
        return [base]
    from src.safety.data_scope import is_app_owned, owned_spec

    spec = owned_spec(shared=True)  # the app's common names (models, cache, keys...) are left: they may be the operator's
    return sorted(Path(e.path) for e in _listing(base) if is_app_owned(e.name, spec=spec))


def _files_under(roots: list[Path], base: Path, onerror, skip: Path | None = None):
    """Every file under ``roots``, never following a link or a junction below them. The data folder itself is entered even when it
    is a link (the operator put it there); a top-level entry that is a link is yielded as itself, so it is removed, never followed."""
    for root in roots:
        if root != base and (_is_link(root) or not root.is_dir()):
            yield root
            continue
        if skip is not None and root == skip:
            continue
        for top, dirs, names in os.walk(root, onerror=onerror):
            dirs[:] = [d for d in dirs if Path(top, d) != skip and not _is_link(Path(top, d))]
            for name in names:
                yield Path(top, name)


def _remove_app_folders(roots: list[Path]) -> None:
    """The app's own folders, once their files are destroyed; a top-level link of ours is removed, never followed."""
    for root in roots:
        if _is_link(root):
            with contextlib.suppress(OSError):
                root.unlink()
        elif root.is_dir():
            shutil.rmtree(root, ignore_errors=True)


def _left_entries(base: Path) -> dict[str, list[str]]:
    """What an app-only erase left at the top of the data folder, by name (never opened or read): ``others`` the app does not
    own, ``common`` the app's common names left because they may be the operator's, ``not_removed`` the app's own that a
    removal failed on (each also named in ``overwrite_failures`` when its overwrite failed)."""
    from src.safety.data_scope import is_app_owned, owned_spec

    full, shared = owned_spec(), owned_spec(shared=True)
    left: dict[str, list[str]] = {"others": [], "common": [], "not_removed": []}
    for name in sorted(e.name for e in _listing(base)):
        kind = "not_removed" if is_app_owned(name, spec=shared) else "common" if is_app_owned(name, spec=full) else "others"
        left[kind].append(name)
    return left


def quick_crypto_erase(
    confirm: bool = False, *, data_dir: Path | None = None, hold_for_rescrub: bool = False, hold_generation: int = 0
) -> dict:
    """Instant crypto-erase then remove the data dir. Requires ``confirm=True``.

    Order: (1) in three passes, the salt page of each encrypted DB (main, custody, lanes) with its -shm head zeroed,
    then its WAL and journal whole (they hold copies of page 1), then the salt pages again, unlinked; (2) the on-disk
    keys; (3) the DuckDB cache header and key sidecar; (4) ``anchors.db`` whole; (5) the in-memory passphrase;
    (5a) the copies the app made of a database beside it, wherever it is (an encrypted one head-only, a plaintext one whole);
    (5b) the head of every other file under the data dir (encrypted snapshots and copies); (6) a full overwrite and
    unlink of everything left, then ``rmtree``. In a data folder the app does not own (R711), 5b and 6 reach only the app's
    own entries and the folder is kept (``scope`` in the report). No link is written through except the app's own databases. Fast at any corpus size (the encrypted body is never rewritten —
    its key is gone). ``data_dir`` overrides the target (tests/tools).

    ``hold_for_rescrub`` (the panic wipe, POSIX only) keeps a descriptor on every main file, -wal and -journal before
    it is unlinked, so :func:`rescrub_held` can destroy what a transaction already under way writes into the unlinked
    file after this returns (its commit puts page 1, salt included, back on the disk), under ``hold_generation`` (one wipe's own)."""
    if not confirm:
        raise PermissionError("quick_crypto_erase requires confirm=True (this is irreversible)")

    from src.database.connect import is_encrypted_file

    paths = _resolve(data_dir)
    base: Path = paths["base"]
    # R711. Is the data folder the app's own? One the app did not choose that also holds other files (the operator's home folder, a
    # drive root, a mount point, a projects folder) is never walked whole or removed: steps 5b and 6 reach only the entries the app
    # owns there (src/safety/data_scope.py, by name, its common names such as "models" excepted), the keys folder keeps whatever is
    # not a key of the app's, and the report names every top-level entry left. Read before a byte is touched; bounded (the scan
    # stops at the first entry the app does not own). A scope that cannot be read is treated as shared: leaving an operator's file
    # is recoverable, destroying it is not.
    try:
        from src.safety.data_scope import folder_scope

        scope = folder_scope(base)
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not read the data folder's scope; erasing the app's own files only", exc, level=logging.WARNING)
        scope = {"broad": True, "reason": "unknown"}
    app_only = bool(scope["broad"])
    seen = wiped = 0
    headers: list[str] = []
    keys_destroyed: list[str] = []
    # Files that existed but whose destructive overwrite itself failed (e.g. ENOSPC on a
    # CoW filesystem mid-write) -- unlink may still have succeeded, but that is deletion,
    # not destruction. Reported honestly rather than folded into "headers_destroyed" /
    # "keys_destroyed", which must only ever mean the overwrite actually completed.
    overwrite_failures: list[str] = []

    def _unlisted(failed_listing) -> None:  # a folder a walk cannot list is named (its path only), never skipped in silence
        overwrite_failures.append(str(getattr(failed_listing, "filename", None) or "an unlistable folder"))

    def _track(p: Path, *, head_bytes: int | None = None) -> tuple[bool, bool, bool]:
        s, overwritten, w = _shred(p, head_bytes=head_bytes)
        if s and not overwritten:
            overwrite_failures.append(str(p))
        return s, overwritten, w

    # The columnar serves are the same kind of thing: a PERSISTED one keeps the cache's derived key inside DuckDB for the life of
    # the process and goes on answering from a file step 3 is about to overwrite. Closed here, before a byte is touched and
    # without waiting (a serve in use is left open and named: an erase is not held up behind a refresh).
    try:
        from src.scheduler.release import close_serves_for_cleared_key

        _serves = close_serves_for_cleared_key()
        if _serves.get("busy"):
            _LOG.warning("a columnar serve was in use during the erase and was left open: %s", _serves["busy"])
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not close the columnar serves before the erase", exc, level=logging.WARNING)

    # Was the corpus actually encrypted? Determines whether crypto-erase is the real
    # guarantee (encrypted) or degrades to header-overwrite (plaintext store -> the
    # optional full pass matters more; surfaced so the UI can recommend it).
    main_db: Path | None = paths["main_db"]
    encrypted = is_encrypted_file(main_db) if main_db is not None else None

    # 1) Destroy the salt/header page of each encrypted DB, then its sidecars. Head-only
    #    on the main file = instant even for a 100 GB corpus; the salt is what matters.
    # The lane files join this loop rather than falling through to step 6: each is an
    # encrypted SQLCipher database with its OWN salt page, and head-only is what keeps
    # the erase instant at 100 GB (see ``_lane_dbs``).
    # R708. Every main file's salt page goes first, so no long WAL write delays them.
    # The sidecars follow, and the write-ahead log and the rollback journal are overwritten WHOLE: SQLCipher keeps the
    # 16-byte salt in plaintext at the start of page 1, and every committed change to page 1 leaves a copy of that page
    # in a WAL frame (or, in rollback mode, in the journal) at an offset far past this file's first 4 KiB. Measured on a
    # 20-commit WAL with checkpoints off: the salt sat in 21 places in the -wal, 20 of them beyond the 4 KiB the old
    # head-only pass destroyed, so the old erase left the salt readable for as long as the WAL's blocks survived. The
    # journal_size_limit (session.py) caps only the size the WAL is cut back to after a checkpoint, never its growth, so
    # this pass costs one sequential write of the WAL's size (usually a few MiB, at worst the hundreds of MiB a long
    # un-checkpointed write leaves) -- and it waits on nothing else. The -shm index
    # holds frame numbers and checksums, never page data, so its head is only zeroed (see pass 1).
    # THREE PASSES, so no checkpoint can carry the salt back into a file this step has already left. Pass 1 overwrites
    # the head of every -shm (its header gone, no connection trusts the log index again, so none checkpoints) and of
    # every main file, unlinking nothing. Pass 2 rewrites the -wal and -journal whole. Pass 3 overwrites the main and
    # -shm heads once more and unlinks them, catching a checkpoint that was already copying page 1 home during pass 2.
    # A database reached through a link (a corpus kept on another drive and linked into place) is erased where it really
    # is: these are the app's own files, the one place a link is followed. Every other file is never written through one.
    dbs = [_real(db) for db in (main_db, paths["custody_db"], *paths.get("lane_dbs", ())) if db is not None]
    head_ok: dict[Path, bool] = {}
    # The -shm head is written with ZEROS, never random bytes: it holds no page data, and a connection that rolls back
    # after the erase reads its frame count from that header and grows the mapped file toward it -- a random count grew
    # it toward 32 GiB in the security read; a zeroed header reads as "rebuild from the log", which is already noise.
    for db in dbs:
        for p in (db.with_name(db.name + "-shm"), db):
            if p.exists():
                head_ok[p] = _overwrite(p, head_bytes=_SQLCIPHER_PAGE1, zeros=p != db)
    for db in dbs:
        for suffix in ("-wal", "-journal"):
            p = db.with_name(db.name + suffix)
            if hold_for_rescrub:
                _hold(p, whole=True, generation=hold_generation)
            s, overwritten, w = _shred(p)
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
    for db in dbs:
        for p in (db, db.with_name(db.name + "-shm")):
            if hold_for_rescrub and p == db:
                _hold(p, whole=False, generation=hold_generation)
            s, overwritten, w = _shred(p, head_bytes=_SQLCIPHER_PAGE1, zeros=p != db)
            overwritten = overwritten and head_ok.get(p, True)
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
            if s and overwritten and p == db:
                headers.append(db.name)

    # Only for a store known to be encrypted: a plaintext body has no salt to lose, and is rewritten whole by step 6.
    salt_gone = {os.path.realpath(db) for db in dbs if head_ok.get(db)} if encrypted is True else set()

    # Close every lane pool now that its salt is gone, and before step 5 drops the passphrase. A pooled SQLCipher connection holds
    # a derived key in memory and an open handle on its file: measured without the close, a connection this process already had
    # open went on serving PRE-ERASE rows from a file that had been randomised and unlinked, for as long as the process lived.
    # Not BEFORE step 1 (row 28): closing the last connection on a live file runs SQLite's write-back of its log, which for a
    # large lane is hundreds of MiB written while the salt is still on the disk. Closed here, the log index is zeroed and the log
    # is noise, so the close finds nothing to write back.
    try:
        from src.versioned.store import dispose_all as _dispose_lanes

        _dispose_lanes()
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not dispose the lane engines after their salt pages", exc, level=logging.WARNING)

    # 2) Destroy on-disk key material (the scrypt wrap-salt lives inside these files).
    # Under the lock every key-file change of THIS process takes (src/custody/keyfile.py KEY_FILES_LOCK), held
    # until the keys folder is gone: a wrap in place that waited finds its file gone and writes nothing, and a
    # creation that waited finds no folder (OPEN_QUEUE item 41(c)). Before it, a wrap that had checked the file
    # put the destroyed key back under its name after this step. Held for the keys folder only, never for the
    # rest of step 6, which rewrites everything left (a wiki dump can take hours) while a signing request waits.
    keys_dir: Path = paths["keys_dir"]
    with _key_files_lock():
        _s, _w = _destroy_keys_folder(keys_dir, _track, keys_destroyed, _unlisted, shared=app_only)
    seen += _s
    wiped += _w

    # 3) DuckDB cache header and its key-derivation sidecar (the cache's key is stretched from the passphrase and the
    #    salt in that sidecar, so with the sidecar destroyed the key is underivable even from the right passphrase;
    #    the cache is a derived copy, so this is defence-in-depth beside step 1 and the passphrase clearing in
    #    step 5 + the free-space scrub).
    store_dir: Path = paths["store_dir"]
    for name in _DUCK_FILES:
        _s, _overwritten, _w = _track(store_dir / name, head_bytes=_SQLCIPHER_PAGE1)
        seen += _s
        wiped += _w

    # 4) anchors.db now inherits the corpus's own encryption state (audit finding
    #    L1, 2026-07-17 -- it used to be always-plaintext regardless of the corpus).
    #    A full overwrite destroys it either way (it is small, so this is cheap
    #    even though a head-only pass would already crypto-erase it if encrypted).
    anchors_seen, _anchors_overwritten, anchors_wiped = _track(paths["anchors_db"])
    seen += anchors_seen
    wiped += anchors_wiped

    # 5) Clear the in-memory passphrase (never persisted) so the app holds no key. Only
    #    for the real default store — an explicit override dir must not mutate process
    #    state that belongs to a different (the live) corpus.
    passphrase_cleared = False
    if data_dir is None:
        from src.database.connect import set_passphrase

        try:
            set_passphrase(None)
        finally:
            # the store is gone by design, not vanished; this must never skip the overwrite below
            try:
                from src.config.kv_store import forget_stores

                forget_stores()
            except Exception:  # noqa: BLE001 - bookkeeping only; the wipe goes on
                pass
        passphrase_cleared = True

    # 5a) Copies of an app database kept beside it under the app's own names (row 29): a retained pre-restore-<ts>.db snapshot,
    #    a repair's salvage and damaged copies, an encryption's in-progress copy. An encrypted one carries its database's salt in
    #    its first page, so its head goes now and it is unlinked, and step 6 never rewrites a corpus-sized body whole (hours).
    #    Looked for beside EVERY database, not only in the data folder: a corpus that DATABASE_URL keeps elsewhere has its copies
    #    there, where no walk of the data folder would reach them. A PLAINTEXT copy (the pre-encrypt snapshot by design, or any
    #    copy of a plaintext store) has no salt to lose: it is rewritten whole, after 5b, wherever it is.
    copies_destroyed: list[str] = []
    plain_copies: list[Path] = []
    for folder in dict.fromkeys([base, *(db.parent for db in dbs)]):
        for p in _db_copies(folder, base, dbs):
            mode = _copy_mode(p, encrypted_store=encrypted is True)
            if mode == "plain":
                plain_copies.append(p)
                continue
            s, overwritten, w = _shred(p, head_bytes=None if mode == "whole" else _SQLCIPHER_PAGE1, zeros=mode == "zeros")
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
            elif s:
                copies_destroyed.append(p.name)

    # 5b) Every OTHER file the erase will reach gets the same treatment now, unlinking nothing, before the slow step 6.
    #    Encrypted copies of the corpus can live there under names no list here can keep up with, each with the corpus's
    #    salt in its first page, and step 6 alone (a full overwrite, hours at corpus size) would leave them readable if the
    #    erase were stopped before it got there. Fail toward shredding more: no file is told apart by its contents (an
    #    encrypted page is indistinguishable from noise), so every regular file's head goes, a -wal or -journal is rewritten
    #    whole and a -shm head is zeroed. It runs AFTER the keys, the cache, the anchors and the passphrase (a large folder
    #    costs one write and sync per file, and nothing may delay those). NOT covered by it, stated: PLAINTEXT staging (backup
    #    members, an extracted restore, a reassembling archive) has no salt to lose, and an encrypted member inside an archive
    #    sits past its head; both are destroyed only by step 6's full rewrite. A folder that cannot be listed is named as a
    #    failure. In a folder the app does not own, only the app's entries are reached.
    heads_elsewhere = 0
    roots = _erase_roots(base, app_only=app_only)
    for p in _files_under(roots, base, _unlisted, skip=paths["keys_dir"]):
        if p.is_symlink() or not p.is_file():
            continue
        name = p.name
        whole = name.endswith(("-wal", "-journal"))
        if _overwrite(p, head_bytes=None if whole else _SQLCIPHER_PAGE1, zeros=name.endswith("-shm")):
            heads_elsewhere += 1
        else:
            overwrite_failures.append(str(p))

    # The plaintext copies found in 5a, rewritten whole and unlinked: in the data folder or beside a database kept elsewhere.
    for p in plain_copies:
        s, overwritten, w = _track(p)
        seen += s
        wiped += w
        if s and overwritten:
            copies_destroyed.append(p.name)

    # 6) Overwrite + unlink everything else still under the data dir, then rmtree. The
    #    encrypted DBs/keys/anchors are already gone; remaining files are small side
    #    files, so a full overwrite here is cheap and complete (no 4 MiB cap — OO-02).
    #    THIS STEP REWRITES EVERY BYTE OF EVERY FILE IT FINDS. A future LARGE file under the data dir (a blob
    #    store, a dump kept inside it) must not fall through to here: give it its own step above that destroys what
    #    keys it and then only unlinks it, or the erase -- whose point is an imminent seizure -- runs for hours.
    #    In a folder the app does not own (R711): only the app's entries, each folder of ours removed, the data folder itself kept.
    # A folder the first-launch step marked on a drive (R86): forget its id first, or the
    # next start would wait for a drive that was erased on purpose, and the watchdog would
    # read the folder vanishing below as a disconnection.
    with contextlib.suppress(Exception):
        from src.safety.data_volume import configured_folder, forget_volume_id

        chosen = configured_folder()
        if chosen is not None and chosen.resolve() == base.resolve():
            forget_volume_id()
    roots = _erase_roots(base, app_only=app_only)  # listed again: a file the app wrote since 5b is the app's too
    for p in _files_under(roots, base, _unlisted):  # never follows a symlinked folder (followlinks=False) or a junction
        if p.is_symlink() or not p.is_file():
            # A link is removed, never written through: its target may be anywhere, outside the data dir included.
            # A FIFO, socket or device is removed too: opening one to write would block or reach hardware.
            with contextlib.suppress(OSError):
                p.unlink()
            continue
        if os.path.realpath(p) in salt_gone:
            # A database of an encrypted store whose salt page step 1 destroyed but could not unlink (on Windows a pool still
            # open holds it, and Windows keeps no descriptor for the late pass): its head is overwritten once more, for a
            # commit that put page 1 back since, and its body, noise already, is not rewritten whole (hours at corpus size).
            if not _overwrite(p, head_bytes=_SQLCIPHER_PAGE1):
                overwrite_failures.append(str(p))
            with contextlib.suppress(OSError):
                p.unlink()
            continue
        _s, _overwritten, _w = _track(p)
        seen += _s
        wiped += _w
    left: dict[str, list[str]] = {"others": [], "common": [], "not_removed": []}
    if app_only:
        _remove_app_folders(roots)
        left = _left_entries(base)
    else:
        with contextlib.suppress(OSError):
            shutil.rmtree(base, ignore_errors=True)

    overwrite_failures[:] = list(dict.fromkeys(overwrite_failures))  # a file failing in two steps is named once
    if overwrite_failures:
        _LOG.error(
            "CRYPTO-ERASE: %d file(s) could NOT be overwritten (only unlinked, if that): %s",
            len(overwrite_failures),
            overwrite_failures,
        )
    _LOG.warning(
        "CRYPTO-ERASE executed on %s (encrypted=%s, %d/%d files, %d headers, %d keys, "
        "%d overwrite failures)",
        base,
        encrypted,
        wiped,
        seen,
        len(headers),
        len(keys_destroyed),
        len(overwrite_failures),
    )
    return {
        "phase": "crypto-erase",
        "data_dir": str(base),
        "files_seen": seen,
        "files_wiped": wiped,
        "headers_destroyed": headers,
        "other_heads_destroyed": heads_elsewhere,
        "keys_destroyed": keys_destroyed,
        "overwrite_failures": overwrite_failures,
        "passphrase_cleared": passphrase_cleared,
        "encrypted_corpus": encrypted,
        "copies_destroyed": copies_destroyed,
        # R711: "data-folder" removes the folder whole; "app-only" reached only the app's own entries in a folder it does not
        # own. Names only, never read: ``left_untouched`` the entries that are not the app's, ``left_common_names`` the app's
        # common names left because they may be the operator's, ``not_removed`` the app's own whose removal failed.
        "scope": "app-only" if app_only else "data-folder",
        "scope_reason": scope["reason"],
        "left_untouched": left["others"],
        "left_common_names": left["common"],
        "not_removed": left["not_removed"],
        "removed": not base.exists(),
        "limit": _LIMIT_NOTE,
    }


def _fill_free_space(path: Path, cap: int | None) -> int:
    """Write random data to ``path`` until the volume is full (or ``cap`` bytes, a
    test-only bound), fsync, and return the bytes written. Best-effort."""
    written = 0
    try:
        with open(path, "wb", buffering=0) as f:
            while cap is None or written < cap:
                n = _CHUNK if cap is None else min(_CHUNK, cap - written)
                try:
                    f.write(os.urandom(n))
                except OSError:
                    break  # ENOSPC: the volume is full -> this pass is done
                written += n
            with contextlib.suppress(OSError):
                f.flush()
                os.fsync(f.fileno())
    except OSError:
        pass
    return written


def full_secure_erase(
    passes: int = 1, *, base_dir: Path | None = None, _cap_bytes: int | None = None
) -> dict:
    """Optional defence-in-depth free-space scrub of the corpus volume.

    Run AFTER ``quick_crypto_erase`` (which already unlinked the files): fills the
    volume's free space with random data ``passes`` times so the freed ciphertext
    blocks are overwritten. ``passes`` must be 1, 3, or 8 (Single/Triple/Octuple).
    ``base_dir`` chooses where the fill files land (defaults to the data dir, i.e.
    the corpus volume). ``_cap_bytes`` is a TEST-ONLY per-pass byte cap so the suite
    never has to fill a real disk."""
    if passes not in _ALLOWED_PASSES:
        raise ValueError(f"passes must be one of {_ALLOWED_PASSES}, got {passes!r}")

    if base_dir is not None:
        base = Path(base_dir)
    else:
        from src.paths import data_dir

        base = data_dir()  # recreated empty by the resolver if the quick pass removed it
    base.mkdir(parents=True, exist_ok=True)
    scrub_dir = base / ".oo_scrub"
    scrub_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for i in range(passes):
        fill = scrub_dir / f"scrub_{i}.bin"
        total += _fill_free_space(fill, _cap_bytes)
        with contextlib.suppress(OSError):
            fill.unlink()
    with contextlib.suppress(OSError):
        shutil.rmtree(scrub_dir, ignore_errors=True)

    _LOG.warning("SECURE-ERASE scrub on %s (%d passes, %d bytes total)", base, passes, total)
    return {
        "phase": "free-space-scrub",
        "data_dir": str(base),
        "passes": passes,
        "bytes_written": total,
        "limit": _LIMIT_NOTE,
    }
