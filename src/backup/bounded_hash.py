"""The one bounded SHA-256 read for every backup check that hashes a file a manifest lists (rows 336, 342).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Its own module because ``regular_file`` stays import-light on purpose (the crypto-free import scan imports it).
"""

from __future__ import annotations

import hashlib
import os
from typing import BinaryIO


class LongerThanListed(Exception):  # noqa: N818 - says what was found, as NotARegularFile does
    """A file read past the size a manifest lists for it (rows 336, 342): it is not the file listed, whatever its
    digest. Not an ``OSError`` on purpose: a caller that turns read errors into "unreadable" must still say mismatch."""


def sha256_read(f: BinaryIO, max_bytes: int | None = None, *, chunk: int = 1 << 20) -> str:
    """The SHA-256 of what ``f`` (open, at its start) holds, read no further than one byte past ``max_bytes``.

    With ``max_bytes`` (the size a manifest lists) a file whose size is larger raises :class:`LongerThanListed` before
    a byte is read, and one that grows while it is read raises it once a byte past the size arrives: a file swapped for
    a huge sparse one, or one that keeps growing, is never hashed to its end. The one shared bounded read for the
    volume-set, parity and folder-backup checks."""
    h = hashlib.sha256()
    if max_bytes is not None and os.fstat(f.fileno()).st_size > max_bytes:
        raise LongerThanListed(getattr(f, "name", ""))
    read = 0
    while True:
        blk = f.read(chunk if max_bytes is None else min(chunk, max_bytes - read + 1))
        if not blk:
            break
        read += len(blk)
        if max_bytes is not None and read > max_bytes:
            raise LongerThanListed(getattr(f, "name", ""))
        h.update(blk)
    return h.hexdigest()
