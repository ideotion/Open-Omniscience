"""
Portable path resolution -- the single source of truth for *where data lives*.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app must behave correctly whether it is run from a source checkout (the
developer / Qubes ``pip install -e .`` case) or installed as a wheel into a
read-only location (pipx / system package). Historically every module computed
``REPO_ROOT / "data"`` independently, which meant an installed copy tried to
write its database *inside its own install tree* -- often read-only, and always
polluting the package. This module centralises the decision with a clear,
documented precedence:

    1. ``OO_DATA_DIR``         -- explicit override, always wins.
    2. source checkout         -- if we are importing from a writable tree that
                                  contains ``pyproject.toml`` (dev / editable
                                  install / Qubes ``$HOME`` install), keep data
                                  alongside the code in ``<repo>/data`` so the
                                  existing developer workflow is unchanged.
    3. per-user data directory -- otherwise follow the XDG Base Directory spec:
                                  ``$XDG_DATA_HOME/open-omniscience`` or
                                  ``~/.local/share/open-omniscience``. This is
                                  the correct, portable home for an installed app.

Nothing here reaches the network or imports heavy deps; it is safe to import
anywhere, including at module load.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

APP_DIRNAME = "open-omniscience"

# src/paths.py -> parents[1] is the repo root (where pyproject.toml lives).
_REPO_ROOT = Path(__file__).resolve().parents[1]


class DataVolumeMissing(OSError):
    """The chosen data folder (on a drive the first-launch step marked) is not there.

    Raised INSTEAD of creating it: a folder made where an unplugged drive's mount point
    sits would boot the app as an empty fresh install beside nothing (R86, 2026-09-29;
    see ``src/safety/data_volume.py``)."""


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    # Lock the data dir to the owner (S-011): the corpus, signing keys, custody log and
    # caches live here; on a shared host this stops other local users reading them.
    # Best-effort — POSIX only; full at-rest encryption remains the host's (Qubes/LUKS) job.
    try:
        path.chmod(0o700)
    except (OSError, NotImplementedError):  # pragma: no cover - non-POSIX / odd FS
        pass
    return path


def _is_source_checkout() -> bool:
    """True when we are running from a writable tree that looks like the repo."""
    return (_REPO_ROOT / "pyproject.toml").is_file() and os.access(_REPO_ROOT, os.W_OK)


def repo_root() -> Path:
    """The repository root as seen by the importing code (for tests/tooling)."""
    return _REPO_ROOT


# Memo for :func:`data_dir` (F3, 2026-11-07): the oo-wiki-stream thread reaches it through
# load_settings() once per firehose event, and the full path (mkdir + chmod + is_file +
# os.access) made it one of the busiest threads in the process. Keyed on every environment
# input the resolution reads, so changing OO_DATA_DIR / XDG_DATA_HOME / HOME in-process
# (tests do) simply misses the memo; guarded by ONE stat so a deleted folder is re-created.
_memo: tuple[tuple[str | None, ...], Path] | None = None


def _memo_key() -> tuple[str | None, ...]:
    return (
        os.getenv("OO_DATA_DIR"),
        os.getenv("XDG_DATA_HOME"),
        os.getenv("HOME"),
        os.getenv("USERPROFILE"),
        str(_REPO_ROOT),  # tests re-point it to simulate an installed (non-checkout) layout
    )


#: What a request that met the latch is answered (keyed in every locale): a 503 with these words, never the catch-all's 500.
ERASED_WORDS = "This app's data was erased while it was running: nothing is read or saved again until the app is restarted. Restart the app."


class DataFolderErased(OSError):
    """The folder asked for is one an erase in this process has started on (R802).

    From the moment an erase starts and for the rest of the process, nothing in the app writes into the folder being erased or
    makes it again: :func:`data_dir` raises this instead of answering it, and an audit hook (:func:`_erase_audit`) raises it for
    every Python open for writing, folder creation, rename, link or symlink that lands in it, so a writer that kept the path from
    before the erase, or a library, is stopped too. Reading is let through. A restart clears it."""

    def __init__(self) -> None:
        super().__init__(errno.EACCES, "the data folder was erased in this process; nothing is written into it or makes it again "
                         "until the app restarts")


#: The folders an erase in this process has started on (R802), each in two spellings: as given and with its links resolved,
#: both taken when the erase starts, while the folder still exists. Never cleared but by a restart (the test suite's own reset aside).
_ERASED: tuple[str, ...] = ()
_ERASED_LOCK = threading.Lock()
#: R805 (c)1: the device each latched folder was on, read at the latch (None: could not be read), keyed by its spellings.
_ERASED_DEV: dict[str, int | None] = {}
_ERASE_OWN = threading.local()
_HOOKED = False
#: The flags that make an open a write (``O_CREAT`` makes a file; the others change one).
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _spellings(path: str | bytes | os.PathLike) -> tuple[str, str]:
    raw = os.path.abspath(os.fsdecode(path))
    return os.path.normcase(raw), os.path.normcase(os.path.realpath(raw))


def erased_folder_of(path: str | bytes | os.PathLike) -> bool:
    """True when ``path`` is a folder an erase in this process started on, or lies under one (R802). Cheap while none is."""
    if not _ERASED:
        return False
    try:
        forms = _spellings(path)
    except (OSError, ValueError, TypeError):
        return True  # a path that cannot even be spelled is not let through while a folder is latched
    return any(f == e or f.startswith(e.rstrip(os.sep) + os.sep) for f in forms for e in _ERASED)


def refuse_if_erased(path: str | bytes | os.PathLike) -> None:
    """Raise :class:`DataFolderErased` when ``path`` is in a folder an erase in this process started on (R802); the erase's own
    work (:func:`erase_owned`) excepted."""
    if _ERASED and not getattr(_ERASE_OWN, "on", False) and erased_folder_of(path):
        raise DataFolderErased()


def _at(target: object, dir_fd: object) -> object:
    """``target`` as the path a call relative to the folder handle ``dir_fd`` reaches, read from the handle's own name
    (``/proc/self/fd``). A handle whose folder cannot be named answers None, which is refused: while a folder is latched, a call
    this hook cannot place is not let through."""
    if dir_fd in (None, -1, -100) or not isinstance(target, (str, bytes)):
        return target
    name = os.fsdecode(target)
    if os.path.isabs(name):
        return name
    try:
        folder = os.readlink(f"/proc/self/fd/{int(dir_fd)}")  # type: ignore[call-overload]
    except (OSError, ValueError, TypeError):
        return None
    if not os.path.isabs(folder):
        return None  # "anon_inode:..." and the like: not a folder
    return os.path.join(folder, name)


def sqlite_target(name: str) -> str | None:
    """The file a SQLite open of ``name`` reaches (a plain path, or a ``file:`` URI read the way SQLite reads it: its query
    dropped, an empty or ``localhost`` authority dropped, %-escapes decoded); None for an in-memory store."""
    from urllib.parse import unquote

    if name in ("", ":memory:"):
        return None
    if not name.startswith("file:"):
        return name
    rest = name[5:].split("?", 1)[0].split("#", 1)[0]
    if "mode=memory" in name or rest in ("", ":memory:"):
        return None
    if rest.startswith("//"):
        authority, _, tail = rest[2:].partition("/")
        rest = "/" + tail if authority in ("", "localhost") else rest
    return unquote(rest)


def _erase_audit(event: str, args: tuple) -> None:
    """R802 (2): the interpreter's audit events for a file opened to write, a folder made, a rename, a link, a symlink or a stdlib
    SQLite connect, refused when the target is in a latched folder. A ``mkdir``/``rename``/``link``/``symlink`` relative to a folder
    handle (``dir_fd``) is placed through the handle's name, and refused when it cannot be placed. An ``open`` event does not carry
    its ``dir_fd``, so a relative path there is read against the working folder; a call on a descriptor already open is let through.
    Python fires no audit event for ``mkfifo`` or ``mknod``. Reading is never refused. NOT covered: writes from C code into files it
    already holds open, and child processes (see docs/SECURITY.md)."""
    if not _ERASED:
        return
    if event == "open":
        target, mode, flags = (tuple(args) + (None, None, None))[:3]
        writes = (isinstance(flags, int) and flags & _WRITE_FLAGS) or (isinstance(mode, str) and any(c in mode for c in "wax+"))
        if not writes:
            return
    elif event == "os.mkdir":
        target = _at(args[0], args[2] if len(args) > 2 else None)
    elif event in ("os.rename", "os.link"):
        target = _at(args[1], args[3] if len(args) > 3 else None)
    elif event == "os.symlink":
        target = _at(args[1], args[2] if len(args) > 2 else None)
    elif event == "sqlite3.connect":
        # SQLite's own C code fires no "open": a stdlib connect that would make a fresh store in the folder is refused here.
        target = args[0] if args else None
        if isinstance(target, str):
            if target == ":memory:" or target == "":
                return
            target = sqlite_target(target)
            if target is None:
                return
    else:
        return
    if target is None:
        if not getattr(_ERASE_OWN, "on", False):
            raise DataFolderErased()
        return
    if isinstance(target, (str, bytes, os.PathLike)):
        refuse_if_erased(target)


def latch_erased(folder: str | os.PathLike) -> None:
    """Mark ``folder`` as being erased, for the rest of the process (R802). Called by the erase before it touches a byte."""
    global _ERASED, _memo, _HOOKED
    try:
        dev: int | None = os.stat(folder).st_dev
    except OSError:
        dev = None
    with _ERASED_LOCK:
        for spelling in _spellings(folder):
            _ERASED_DEV.setdefault(spelling, dev)
        add = [s for s in _spellings(folder) if s not in _ERASED]
        _ERASED = _ERASED + tuple(dict.fromkeys(add))
        _memo = None  # the memo would answer a folder that is still there without asking
        if not _HOOKED:
            sys.addaudithook(_erase_audit)  # once per process; free while nothing is latched
            _HOOKED = True


def erased_device(folder: str | bytes | os.PathLike) -> int | None:
    """The device ``folder`` was on when an erase latched it (R805 (c)1), None when it is not latched or that could not be read."""
    try:
        forms = _spellings(folder)
    except (OSError, ValueError, TypeError):
        return None
    for f in forms:
        if _ERASED_DEV.get(f) is not None:
            return _ERASED_DEV[f]
    return None


@contextlib.contextmanager
def erase_owned() -> Iterator[None]:
    """For the erase's own work in a folder it latched (its overwrites, and the free-space scrub's private files, removed before it
    returns): this thread only, never a writer of the app's."""
    before = getattr(_ERASE_OWN, "on", False)
    _ERASE_OWN.on = True
    try:
        yield
    finally:
        _ERASE_OWN.on = before


def _reset_erased_for_tests() -> None:
    """The test suite's reset between tests: a real process keeps the latch until it ends."""
    global _ERASED, _memo
    with _ERASED_LOCK:
        _ERASED = ()
        _ERASED_DEV.clear()
        _memo = None


def data_dir_path() -> Path:
    """Where :func:`data_dir` would answer, WITHOUT making it or checking it (R802): for a reader, and for the error journal,
    which never makes a missing data folder. Not for a writer."""
    override = os.getenv("OO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if _is_source_checkout():
        return _REPO_ROOT / "data"
    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / APP_DIRNAME


def data_dir() -> Path:
    """Return the writable data directory, creating it if necessary.

    See the module docstring for the precedence rules. Repeat calls are cheap: the result
    is memoised per resolved environment and revalidated with a single ``stat`` (a data
    folder that vanished is created again, exactly as before) -- except a folder an erase in this
    process has started on, which is never answered or made again (R802: :class:`DataFolderErased`).
    """
    global _memo
    if _ERASED and erased_folder_of(data_dir_path()):
        raise DataFolderErased()  # whatever thread asks: the erase's own work never goes through here
    override = os.getenv("OO_DATA_DIR")
    if override and os.getenv("OO_DATA_VOLUME_ID"):
        # A folder the first-launch step marked: never recreated when it is missing, and
        # the check must run every time (the drive can be unplugged mid-session).
        from src.safety.data_volume import guard_data_dir

        guard_data_dir(Path(override).expanduser())

    key = _memo_key()
    memo = _memo
    if memo is not None and memo[0] == key and memo[1].is_dir():
        return memo[1]

    if override:
        chosen = _ensure(Path(override).expanduser())
    elif _is_source_checkout():
        chosen = _ensure(_REPO_ROOT / "data")
    else:
        xdg = os.getenv("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        chosen = _ensure(base / APP_DIRNAME)
    _memo = (key, chosen)
    return chosen


#: The file in the data folder that holds its instance tag (see ``instance_tag``).
INSTANCE_ID_FILE = ".oo-instance-id"   # app-specific, like .oos-volume: a shared folder can hold a generic "instance_id" of its own
_INSTANCE_LOCK = threading.Lock()


def instance_tag() -> str:
    """Eight hex characters that tell this data folder's exports apart from another instance's, without saying anything about it.

    The Field data button puts it in every file name and manifest it saves (2026-11-14: the maintainer runs several
    instances, each with its own ``OO_DATA_DIR`` and port, and sends their files back together). It is RANDOM, made once
    and kept in the data folder's ``.oo-instance-id`` file: a hash of the folder's path would be reversible by guessing
    (``/home/<a common name>/...`` has few candidates and eight hex characters are 32 bits), a random value carries no
    information at all. A copied data folder keeps its tag, which is right: it is the same corpus. A folder that cannot
    be written answers ``"no-id"`` rather than fail an export, and so does a ``.oo-instance-id`` that is not a regular
    file (a symlink, a folder, a FIFO): it is never followed or replaced, and its exports cannot be told apart by tag."""
    import re
    import secrets
    import stat

    with _INSTANCE_LOCK:   # two exports at once on a new folder must not each make (and name files with) their own tag
        try:
            path = data_dir() / INSTANCE_ID_FILE
        except OSError:   # an unplugged data drive (DataVolumeMissing): the export says so itself
            return "no-id"
        try:
            # only a regular file is read: a FIFO would block here, holding the lock for every later export
            if not stat.S_ISREG(path.lstat().st_mode):
                return "no-id"
            with path.open("rb") as fh:
                tag = fh.read(64).decode("ascii", "replace").strip()   # a capped read: the file is 9 bytes when it is ours
            if re.fullmatch(r"[0-9a-f]{8}", tag):
                return tag
        except FileNotFoundError:
            pass
        except OSError:
            return "no-id"
        tag = secrets.token_hex(4)
        try:
            from src.safety.file_lock import atomic_replace

            atomic_replace(path, tag + "\n", encoding="ascii")
        except OSError:
            return "no-id"
        return tag


def diagnostics_dir() -> Path:
    """``<data dir>/diagnostics``, created if missing (the folder the reports and bundles are written to)."""
    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_sqlite_url() -> str:
    """The default SQLite URL rooted in :func:`data_dir`."""
    return f"sqlite:///{data_dir() / 'open_omniscience.db'}"


def wal_file_bytes(db_file: Path) -> int | None:
    """Bytes in the write-ahead log beside ``db_file`` (``<db_file>-wal``), read by stat only.

    ``None`` when the store itself is absent, as its ``db_bytes`` is; ``0`` when it has no log (a store in
    rollback-journal mode, or one whose log a checkpoint just removed). Never opens either file (R789: closing a
    Python handle on a live store drops SQLite's locks), so it is safe beside a running app (row 321).
    """
    if not db_file.exists():
        return None
    try:
        return Path(str(db_file) + "-wal").stat().st_size
    except OSError:
        return 0
