"""Read a folder backup's manifest (``oo-folder-backup.json``) from an untrusted folder.

The backup folder is untrusted input, and so is its manifest: it may be a link (to ``/dev/zero``, or
anywhere), a named pipe that would block a reader for ever, a file of many gigabytes, or JSON nested
deep enough to exhaust Python's recursion. Every reader that only needs the manifest's facts takes
them through :func:`read_manifest_json`, which opens it without following a link and without
blocking, requires a regular file within :data:`MANIFEST_MAX_BYTES`, and answers ``None`` whenever
the manifest cannot be read as one JSON value -- the same answer a missing manifest gives.

Kept import-light (no crypto, no app modules) so the import scan can use it.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import stat

#: A real manifest lists one small entry per file (about 200 bytes), so this holds some 300,000 files,
#: and keeps what ``json.loads`` builds from it bounded too.
MANIFEST_MAX_BYTES = 64 * 1024 * 1024


def read_manifest_json(path: str | os.PathLike, max_bytes: int | None = None) -> object | None:
    """The manifest's JSON value, or ``None`` when it is missing, not a regular file, a link,
    larger than ``max_bytes`` (:data:`MANIFEST_MAX_BYTES` unless the caller's own format allows more,
    row 308), unreadable, not UTF-8 or not JSON (nesting included)."""
    if max_bytes is None:  # read at call time, so the module's ceiling stays the one place it is set
        max_bytes = MANIFEST_MAX_BYTES
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        # Anything but a regular file is refused by name first: Windows has no O_NOFOLLOW, and opening a
        # device node a crafted drive carries can itself have effects before fstat could refuse it.
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            return None
        with os.fdopen(fd, "rb") as f:
            fd = -1
            raw = f.read(max_bytes + 1)
        if len(raw) > max_bytes:
            return None
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError, MemoryError):
        return None
    finally:
        if fd != -1:
            os.close(fd)


__all__ = ["MANIFEST_MAX_BYTES", "read_manifest_json"]
