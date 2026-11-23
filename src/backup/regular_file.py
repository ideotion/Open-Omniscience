"""Open a file that sits on a drive anyone may have written to, as a regular file or not at all (row 312).

A backup folder, an export destination and a folder offered to the import scan are untrusted input: any name
there may be a named pipe (an ``open`` waits for a writer for ever), a link to ``/dev/zero`` (a read never ends)
or a link out of the folder. :func:`open_regular` refuses all of them BEFORE a byte is read: the name is examined
without following a link, the open never blocks (``O_NONBLOCK``: a pipe opens at once) and never follows a link
(``O_NOFOLLOW`` where the platform has it), and only once ``fstat`` of what was OPENED says it is a regular file
is the handle handed back. A regular file reads exactly as before: ``O_NONBLOCK`` changes nothing for one, so
the descriptor is never switched back (``os.set_blocking`` works on pipes only on Windows, row 124).

``follow_links=True`` is for a path the app itself may legitimately reach through a link (its own data folder on
another drive): the link is followed, but a pipe, a device or a directory at its end is still refused, and still
without blocking.

:func:`create_new` and :func:`replace_with` are the WRITE side (row 313): a name in such a folder is created
exclusively, never opened through a link planted there.

Kept import-light (no app modules) so the import scan (crypto-free) and the crypto layer can both use it.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import os
import stat
from typing import BinaryIO

#: The bit Windows sets in every reparse tag that stands for ANOTHER NAME (IsReparseTagNameSurrogate): symbolic links,
#: junctions and mount points. Cloud placeholders and deduplicated files carry tags without it.
_NAME_SURROGATE = 0x20000000


class NotARegularFile(OSError):
    """The name is a link, a pipe, a device or a folder: nothing was read from it."""


def _flags(follow_links: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOCTTY", 0)
    if not follow_links:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def open_regular_fd(path: str | os.PathLike[str], *, follow_links: bool = False, dir_fd: int | None = None) -> int:
    """A raw read-only descriptor on ``path`` once it is known to be a regular file; :class:`NotARegularFile`
    otherwise, and any other ``OSError`` as the open raised it. The caller closes the descriptor."""
    # Examined by name first: Windows has no O_NOFOLLOW, and opening a device node a crafted drive carries can
    # itself have effects before fstat could refuse it.
    kw = {} if dir_fd is None else {"dir_fd": dir_fd}
    st = os.stat(path, follow_symlinks=follow_links, **kw)
    if not stat.S_ISREG(st.st_mode):
        raise NotARegularFile(f"not a regular file: {os.fspath(path)!s}")
    fd = os.open(path, _flags(follow_links), **kw)  # a link swapped in after the look fails here (ELOOP)
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):  # the file OPENED, not the name looked at
            raise NotARegularFile(f"not a regular file: {os.fspath(path)!s}")
        # The file OPENED is the file EXAMINED. Where there is no O_NOFOLLOW (Windows), this is what refuses a name
        # swapped for a link to a regular file between the look and the open. A file system that reports no inode (0)
        # cannot be compared; a mismatch is confirmed by a second look at the NAME, because lstat and fstat come from
        # different Windows calls that may give one file's identity at different widths (volumes.load_manifest).
        if not follow_links and (st.st_ino and fst.st_ino) and (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            try:
                again = os.stat(path, follow_symlinks=False, **kw)
            except OSError:
                again = None
            if again is None or not stat.S_ISREG(again.st_mode) or (again.st_dev, again.st_ino) != (st.st_dev, st.st_ino):
                raise NotARegularFile(f"changed while it was being opened: {os.fspath(path)!s}")
    except BaseException:
        os.close(fd)
        raise
    return fd


class _AdoptedFileIO(io.FileIO):
    """A ``FileIO`` that closes its descriptor only once :func:`adopt_fd` has handed it over (row 344).

    Built with ``closefd=False``, so dropping it before the hand-over closes nothing; ``_owns`` is set as the last step."""

    _owns = False

    def close(self) -> None:
        fd = -1 if self.closed else self.fileno()
        try:
            super().close()
        finally:
            if self._owns and fd >= 0:
                self._owns = False
                os.close(fd)


_BUFFERED: dict[str, type[io.BufferedReader] | type[io.BufferedWriter]] = {"rb": io.BufferedReader, "wb": io.BufferedWriter}


def adopt_fd(fd: int, mode: str) -> BinaryIO:
    """``fd`` as a buffered binary file object (``mode`` ``"rb"`` or ``"wb"``) that closes it, with the descriptor closed
    exactly once whatever is raised on the way (row 344).

    ``os.fdopen`` inside ``try: ... except BaseException: os.close(fd)`` closes it TWICE when the exception comes after
    the file object exists: an interrupt between the object's construction and the ``return``, or an error building the
    buffer (``io.open`` then closes the raw file itself). The second close may land on a number another open has taken
    meanwhile, a SQLite connection's above all, and closing any descriptor of a file drops the process's locks on it
    (R789). Here nothing owns ``fd`` until the very last statement: until then a failure closes it here, once, and a
    file object dropped half-built closes nothing; after it, only the file object does. That statement (an attribute store)
    and the ``return`` after it run no check for a pending signal; one landing in the caller just after the call drops a
    finished file object, which its finaliser closes, once. A signal at this function's own entry, before its ``try``,
    leaves the descriptor open: a leak, never a second close."""
    try:
        raw = _AdoptedFileIO(fd, mode, closefd=False)
        f = _BUFFERED[mode](raw)
    except BaseException:
        os.close(fd)  # nothing owns it yet: a FileIO built with closefd=False never closes it, built or half-built
        raise
    raw._owns = True
    return f  # type: ignore[return-value]


def open_regular(path: str | os.PathLike[str], *, follow_links: bool = False, dir_fd: int | None = None) -> BinaryIO:
    """:func:`open_regular_fd` as a binary file object (``"rb"``) that closes the descriptor with it."""
    fd = open_regular_fd(path, follow_links=follow_links, dir_fd=dir_fd)
    return adopt_fd(fd, "rb")


def create_new(path: str | os.PathLike[str], *, mode: int = 0o666) -> BinaryIO:
    """A new, empty regular file at ``path``, opened for writing, that no link can redirect (row 313).

    A backup folder, an export destination or a restore staging folder may already hold the name: a link planted there
    turned a plain ``open(path, "wb")`` into a write wherever the link pointed. Whatever the name holds is removed
    first, a link as a link (``unlink`` never follows one), and the file is then CREATED exclusively (``O_CREAT |
    O_EXCL``, plus ``O_NOFOLLOW`` where the platform has it): a link or a file that appears between the two makes the
    create fail rather than be followed or truncated. A folder at the name is refused, never removed; on Windows a
    name-surrogate reparse point (a symbolic link, a junction, a mount point) is refused rather than removed, while a
    file that merely carries another reparse tag (a cloud placeholder, a deduplicated file) is a file like any other."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISDIR(st.st_mode) or int(getattr(st, "st_reparse_tag", 0) or 0) & _NAME_SURROGATE:
            raise NotARegularFile(f"refusing to write over a folder or a reparse point: {os.fspath(path)!s}")
        os.unlink(path)
    flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOCTTY", 0)
    )
    fd = os.open(path, flags, mode)
    return adopt_fd(fd, "wb")


def replace_with(path: str | os.PathLike[str], data: bytes, *, tmp: str | os.PathLike[str] | None = None) -> None:
    """Write ``data`` to ``path`` through a temporary file made by :func:`create_new`, flushed to disk and then renamed
    over ``path`` (a rename replaces a link at ``path`` itself, never what it points at). A reader sees the old file or
    the new one, whole. ``tmp`` defaults to ``<name>.<random>.oopart`` beside ``path``."""
    import secrets

    p = os.fspath(path)
    t = os.fspath(tmp) if tmp is not None else f"{p}.{secrets.token_hex(4)}.oopart"
    made = False
    try:
        with create_new(t) as fh:
            made = True
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(t, p)
    except BaseException:
        if made:  # only the file this call created: never one that appeared at the name meanwhile
            try:
                os.unlink(t)
            except OSError:
                pass
        raise


__all__ = ["NotARegularFile", "adopt_fd", "create_new", "open_regular", "open_regular_fd", "replace_with"]
