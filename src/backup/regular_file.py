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

Kept import-light (no app modules) so the import scan (crypto-free) and the crypto layer can both use it.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import stat
from typing import BinaryIO


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


def open_regular(path: str | os.PathLike[str], *, follow_links: bool = False, dir_fd: int | None = None) -> BinaryIO:
    """:func:`open_regular_fd` as a binary file object (``"rb"``) that closes the descriptor with it."""
    fd = open_regular_fd(path, follow_links=follow_links, dir_fd=dir_fd)
    try:
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


__all__ = ["NotARegularFile", "open_regular", "open_regular_fd"]
