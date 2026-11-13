"""
How a private key FILE is made, read and replaced, in one place.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The signing keys under ``keys/`` are the evidence key, and the Ed25519 and ML-DSA keys of
``HybridSigner`` (the custody log's, and the annotation signer's own pair). Each used to be
written by ``write_bytes`` then ``chmod`` (a window in which another account could read it under a
umask of 022) and created with a check-then-write (two first callers could each make a key, the
second silently orphaning what the first had already signed). The routines here are the fix,
written once and used by all of them, because an exclusive create is not an atomic one and the part
that makes it atomic is the part nobody should have two copies of.

What a file CONTAINS is not decided here: the callers parse and seal their own bytes. This module
only guarantees how those bytes arrive:

* a new file is written to a private file first (``O_EXCL``, 0600, flushed), then linked into place
  with ``os.link``, so no reader sees it half written and two creators end with ONE file;
* a file is replaced in place only by ``os.replace`` of a finished private copy, only after the
  caller's own check passed on the copy, and only if the file is still exactly the one that was
  read (device, inode, size, modification time).
* the key file's own name changes (the link of a creation, a replace and the alias removal after
  it, the restore taking back a key it placed) are flushed to their folder, so a power cut cannot
  bring back the NAME of what was replaced, and are made under :data:`KEY_FILES_LOCK`, which the
  erase holds too; the bytes a replace frees are overwritten where that can be done (not a promise
  on an SSD or a copy-on-write filesystem). Not flushed and not under the lock: the creation and
  removal of the empty ``keys/.pending`` folder, and the restore's creation of ``keys/`` itself.

Nothing here reads or logs a passphrase or key bytes.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import stat
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

#: Held by every change to a key file's name in this process, from the private copy to the folder flush
#: (:func:`create_new`, :func:`replace_in_place`, the restore's take-back in ``src/backup/merge.py``), and by
#: the erase from its key step until the keys folder is gone (``src/safety/crypto_erase.py``). Without it the
#: check that the file is still the one that was read and the ``os.replace`` that acts on it were two steps an
#: erase could fall between: the erase destroyed the key, and the replacement then put that same key (wrapped)
#: back under its name, after the erase had reported it destroyed (OPEN_QUEUE item 41(c)). Stated limits: a
#: process-level lock, so another process on the same data folder is not covered (as for the identity check);
#: and a restore running during an erase can create ``keys/`` again once the erase removed it and place the
#: backup's keys there, which may be this install's own (serialising a restore against an erase is not done here).
KEY_FILES_LOCK = threading.RLock()


def flush_key_folder(folder: Path, what: str) -> bool:
    """Flush ``folder`` so the rename, link or unlink just done in it survives a power cut.

    Until the folder is flushed, a power cut can bring back what the name held before: after a
    plaintext key was wrapped in place, that is the PLAINTEXT key, on a machine that is off, which
    is exactly the case the at-rest encryption is for (OPEN_QUEUE item 41(c)). ``True`` only when the
    folder was flushed (a platform or filesystem that cannot is named once by ``file_lock``). Never
    raises: the new name is already in place, and a failure here only means it may not survive a power
    cut, which the log says (the exception CLASS only).
    """
    try:
        from src.safety.file_lock import flush_folder

        return flush_folder(folder)
    except Exception as exc:  # noqa: BLE001 - the change is made; only its durability is unknown
        log.warning(
            "%s: the keys folder could not be flushed to disk (%s); a power cut now could bring the old file back",
            what,
            type(exc).__name__,
        )
        return False


def write_new(path: Path, data: bytes) -> None:
    """Create ``path`` (it must not exist), mode 0600 from the first byte, and flush it to disk.

    ``O_EXCL`` refuses a file that is already there (``FileExistsError``) and the mode is part of
    the creation, so there is no moment in which the key is readable by another account (the old
    ``write_bytes`` then ``chmod`` left one under a umask of 022).
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


#: Where a key's temporary files live: a subdirectory of the key's own directory, so a rename or a
#: link into place stays on one file system, and so the backups, which list the FILES directly in
#: ``keys/``, never pick one up (a temporary file is not part of the identity).
PENDING = ".pending"


def private_name(path: Path, kind: str) -> Path:
    """A temporary file name no other caller can hold: this host's process and thread, a random token.

    The token is what makes it true across machines too (two containers on one data volume can both
    be process 1 with the same thread number). A name is removed only by the caller that made it:
    a name shared by every caller let one delete another's finished copy and rename its own empty
    file over the key.
    """
    pending = path.parent / PENDING
    # os.mkdir, not Path.mkdir(exist_ok=True): that one answers EEXIST, then asks is_dir(), and a caller
    # that removed the (empty) folder in between made it raise FileExistsError for a folder that was
    # there when it looked. The folder is created by the first file written into it, and write_private
    # retries when it has gone again.
    with contextlib.suppress(FileExistsError):
        os.mkdir(pending, 0o700)
    token = secrets.token_hex(6)
    return pending / f"{path.name}.{os.getpid()}.{threading.get_ident()}.{token}.{kind}"


def write_private(path: Path, kind: str, data: bytes) -> Path:
    """Write ``data`` to a new private file for ``path`` and return its name; a failure leaves none.

    The directory is removed again when nothing is in it (:func:`drop_pending`), and another caller
    can do that between this one's ``mkdir`` and its create. Each retry means another caller finished and
    removed the folder, so one is starved only by more finishers than tries: eight cover it.
    """
    for _attempt in range(8):
        tmp = private_name(path, kind)
        try:
            write_new(tmp, data)
        except FileNotFoundError:
            continue
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise
        return tmp
    raise FileNotFoundError(
        f"{path.parent / PENDING}: kept disappearing while a key file was written"
    )


def drop_pending(path: Path) -> None:
    """Remove ``keys/.pending`` when it is empty, so the directory is not left in the keys listing
    (the encryption attestation names every entry of it). Refused by the file system while any
    caller's file is in it, which is exactly when it must stay."""
    with contextlib.suppress(OSError):
        (path.parent / PENDING).rmdir()


def pending_aliases(path: Path, old: os.stat_result) -> list[str]:
    """The names in ``keys/.pending`` that are hard links to the file ``path`` holds (``old`` is its ``lstat``).

    A creation that died between its ``os.link`` and the removal of its private name leaves that
    name as a second name for the key file's own bytes. A name is matched by file identity (device
    and inode), never by its text, so only an alias of that very file is listed: a caller's file that
    is not yet linked has an inode of its own.
    """
    if old.st_nlink < 2 or not old.st_ino:
        return []
    found: list[str] = []
    with contextlib.suppress(OSError), os.scandir(path.parent / PENDING) as entries:
        for entry in entries:
            try:
                # by path: ``DirEntry.stat()`` answers 0 for the device, inode and link count on
                # Windows, where a name would then never match and the sweep would do nothing
                st = os.stat(entry.path, follow_symlinks=False)
                if (st.st_dev, st.st_ino) == (old.st_dev, old.st_ino):
                    found.append(entry.path)
            except OSError:
                continue
    return found


def drop_aliases(path: Path, old: os.stat_result) -> None:
    """Remove the names in ``keys/.pending`` that are hard links to the file ``path`` just replaced.

    When the replaced bytes were the plaintext key, leaving that alias would leave the key readable
    there for good, in a folder nothing sweeps. A caller whose name goes this way finds it missing at
    its own removal, which it allows. Best effort: the wrapped file is already in place, and a
    leftover is the stated limit.
    """
    for name in pending_aliases(path, old):
        with contextlib.suppress(OSError):
            os.unlink(name)


def identity(st: os.stat_result) -> tuple[int, int, int, int]:
    """Which file, and which state of it: device, inode, size and modification time."""
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _open_replaced(path: Path, old: os.stat_result) -> int | None:
    """A handle on the file ``path`` holds now (``old`` is its ``lstat``), so its bytes can be overwritten once a
    replacement has taken its name; ``None`` where that cannot be done safely (Windows, where a file open here
    cannot be replaced; a file that is not the one checked; any error)."""
    if sys.platform == "win32":
        return None
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) == (old.st_dev, old.st_ino):
            return fd
    except OSError:
        pass
    os.close(fd)
    return None


def _scrub_replaced(fd: int | None, old: os.stat_result, what: str) -> None:
    """Overwrite the bytes of the file a replacement has just taken the name of, once nothing names it any more.

    ``os.replace`` and the alias removal UNLINK the old file; its blocks keep the old bytes, which for a key
    wrapped in place were the key in the clear, readable from a switched-off machine. Zeros, flushed, through the
    handle taken before the replace, and only when its link count is 0 (no other name kept it). Best effort, and
    no promise on an SSD or a copy-on-write filesystem, which can keep the old blocks anyway (the erase's stated
    limit, ``src/safety/crypto_erase.py``). A failure is logged by class and never undoes the replace."""
    if fd is None:
        return
    try:
        if os.fstat(fd).st_nlink != 0:
            return
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, b"\0" * old.st_size)
        os.fsync(fd)
    except OSError as exc:
        log.warning("%s: the replaced key file's bytes could not be overwritten (%s)", what, type(exc).__name__)


class ReplaceRefused(Exception):  # noqa: N818 - a refusal to replace, not an error condition
    """The key file changed while the replacement was made, so the replacement is not used.

    Expected when two callers load one legacy key at once: the loser stands down, the file is already
    what it wanted, and it is logged at debug level, not as a warning.
    """


class KeyFileLinked(Exception):  # noqa: N818 - a refusal to replace, not an error condition
    """The key file is a symbolic link, or has another name outside ``keys/.pending``.

    ``os.replace`` would swap the NAME for the new file and leave the old bytes, which may be the
    plaintext key, readable at the other name (the link's target, the other hard link). Nothing is
    replaced, and the caller reports the file as it is. A warning, since someone arranged it.
    """


def _refuse_a_linked_name(path: Path, old: os.stat_result) -> None:
    """Raise :class:`KeyFileLinked` when ``old`` (the ``lstat`` of ``path``) is a symbolic link or a file with
    another name outside ``keys/.pending``."""
    if stat.S_ISLNK(old.st_mode):
        raise KeyFileLinked("the key file is a symbolic link")
    if old.st_ino and old.st_nlink > 1 + len(pending_aliases(path, old)):
        raise KeyFileLinked("the key file has another name outside keys/.pending")


def replace_in_place(
    path: Path,
    make: Callable[[], bytes],
    check: Callable[[bytes], None],
    seen: os.stat_result | None,
    what: str,
) -> bool:
    """Replace the key file ``path`` by the bytes ``make()`` returns; ``True`` when it was replaced.

    The caller decides what the new bytes are (the SAME key in its sealed form: a new key would
    orphan everything already signed, whose public half is in shipped evidence) and how to tell
    that they still hold that key (``check`` raises if not). The new bytes go to a private file of
    this caller's, are read back and checked BEFORE they replace anything, so a failure at any step
    leaves the original file exactly as it was. ``seen`` is the state of the file when the caller
    read the key from it (``fstat`` of the open file; ``None`` takes it now); the replacement lands
    only if the file is still exactly that, so a key erased, restored over or sealed by another
    caller in the meantime is never replaced by this caller's copy of the key it read earlier. A path
    that is a symbolic link, or has another hard link outside ``keys/.pending``, is not replaced at
    all (:class:`KeyFileLinked`): the replacement would swap the name and leave the old bytes at the
    other one.
    Never raises: signing goes on with the key the caller holds and the next load tries again. The
    log names the exception CLASS only (a passphrase is in scope of every caller).
    """
    tmp: Path | None = None
    try:
        if seen is None:
            seen = os.stat(path)
        # A link is refused before the copy is paid for (``make`` derives a key from the passphrase), and
        # again below, since the name can change while the copy is made.
        _refuse_a_linked_name(path, os.lstat(path))
        sealed = make()  # the slow part (a key derivation), and the only part outside the lock
        # From the private copy to the folder flush, ONE step for every key-file change in this process, the
        # erase's among them (KEY_FILES_LOCK). An erase that ran while ``make`` did has removed the file, so the
        # ``lstat`` below fails and nothing is written at all: not the replacement, and not a private copy of the
        # key the erase destroyed, which it would otherwise leave behind in ``keys/.pending`` after its walk.
        with KEY_FILES_LOCK:
            # the NAME's own state: a symbolic link answers for itself, not for its target
            old = os.lstat(path)
            if stat.S_ISLNK(old.st_mode):
                raise KeyFileLinked("the key file is a symbolic link")
            if identity(old) != identity(seen):
                raise ReplaceRefused("the key file changed while the replacement was made")
            _refuse_a_linked_name(path, old)
            tmp = write_private(path, "rewrap", sealed)
            check(tmp.read_bytes())
            replaced = _open_replaced(path, old)
            try:
                os.replace(tmp, path)
                tmp = None  # it IS the key file now: never removed below
                drop_aliases(path, old)
                # Both folders of the rename (the private copy left ``keys/.pending``, where the removed aliases were
                # too), so a power cut cannot bring back the name of what was replaced, which here was the plaintext key.
                durable = flush_key_folder(path.parent, what)
                durable = flush_key_folder(path.parent / PENDING, what) and durable
                # Only once the rename is KNOWN to be on disk: zeros under a name a power cut could still hand back
                # would lose the key altogether (neither the old form nor the new one), where an unflushed rename
                # only risks the old form coming back, which the next load wraps again.
                if durable:
                    _scrub_replaced(replaced, old, what)
            finally:
                if replaced is not None:
                    with contextlib.suppress(OSError):
                        os.close(replaced)
        return True
    except Exception as exc:  # noqa: BLE001 - best effort by design; the original file is untouched
        if isinstance(exc, ReplaceRefused):
            log.debug("%s not wrapped by this caller: another caller changed the file", what)
        else:
            log.warning(
                "%s not wrapped under the passphrase this time (%s)", what, type(exc).__name__
            )
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return False
    finally:
        drop_pending(path)


def create_new(path: Path, data: bytes) -> None:
    """Create ``path`` (it must not exist) holding ``data``, so that no reader ever sees it half written.

    The bytes go to a private file first (``O_EXCL``, 0600, flushed), and ``os.link`` then makes
    the key file appear all at once; it is refused with ``FileExistsError`` when another caller got
    there first, which is the one answer that means "load theirs". A file system that has no hard
    links (a FAT or exFAT external drive), or one where the private file cannot be made, falls back
    to an exclusive create in place; there a reader can meet the file between its create and its
    write, which :func:`read_settled` waits out.
    """
    # Under the lock from the private copy on, so an erase never runs between this caller's copy and its link
    # (and a creation that waited on an erase finds ``keys/`` gone and writes nothing: FileNotFoundError).
    with KEY_FILES_LOCK:
        try:
            tmp = write_private(path, "new", data)
        except OSError:
            write_new(path, data)
            flush_key_folder(path.parent, path.name)
            return
        try:
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise
            except OSError:
                write_new(path, data)
            # the new name is what a power cut would lose: flushed before the private name goes, so the key
            # is never left with no name on disk at all
            flush_key_folder(path.parent, path.name)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            drop_pending(path)


def read_once(path: Path) -> tuple[bytes, os.stat_result]:
    """The bytes of the file and its state (``fstat`` of the same open file), read together.

    A file that no name holds any more when it has been read (``st_nlink`` 0) was replaced while it was
    open, and a wrap in place may have overwritten its bytes with zeros: the name is opened again, so a
    reader never parses the scrubbed bytes of a file the key has left."""
    for _ in range(3):
        with path.open("rb") as fh:
            raw, st = fh.read(), os.fstat(fh.fileno())
        if st.st_nlink != 0:
            break
    return raw, st


def read_settled(path: Path) -> tuple[bytes, os.stat_result]:
    """The bytes of the key file and its state, waiting a moment if it is there and still empty.

    An empty key file is never a key: it is another caller's create that has not been written yet
    (only on a file system without hard links, see :func:`create_new`). Five short looks cover that
    and nothing else; a file that stays empty is returned empty and fails as the unreadable key it is.
    """
    raw, seen = read_once(path)
    for _ in range(5):
        if raw:
            break
        time.sleep(0.02)
        raw, seen = read_once(path)
    return raw, seen
