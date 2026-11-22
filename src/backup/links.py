"""What counts as a link in a backup folder or a restore destination (R779).

A restore never follows a link. That rule was checked on each member with ``Path.is_symlink()``,
which misses two things: the category folder itself (``wiki_dumps`` being a link to some other
place on the machine, whose files a restore then copied into the live data folder) and, on
Windows, a junction or another reparse point, which ``is_symlink()`` answers ``False`` for.
One test here, read from ``lstat`` so the link is never followed while it is being looked at.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# 0x400 on Windows; the attribute is absent elsewhere, so the test reads 0 and costs nothing.
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# The "name surrogate" bit of a reparse tag: set for every reparse point that STANDS FOR ANOTHER NAME
# (a symbolic link, a junction or mount point, and the like). Not set for a OneDrive "files on demand"
# placeholder or a deduplicated file, which are the file's own data stored another way: refusing those
# would refuse a backup kept in a OneDrive folder, which is not a link at all.
_NAME_SURROGATE = 0x20000000


def is_link_stat(st: os.stat_result) -> bool:
    """True for a symbolic link, and on Windows also for a junction or any other reparse point that
    stands for another name. A tag that cannot be read on a reparse point counts as a link (fail closed)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    if not getattr(st, "st_file_attributes", 0) & _REPARSE:
        return False
    tag = getattr(st, "st_reparse_tag", None)
    return tag is None or bool(tag & _NAME_SURROGATE)


def is_link(path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` is a link, read without following it. ``False`` when nothing is there.

    Any other refusal raises: a path that could not be looked at is not known to be safe. The scan
    counts it as not read; the restore counts it as not read and goes on (R778)."""
    try:
        return is_link_stat(os.lstat(path))
    except FileNotFoundError:
        return False


def link_on_the_way(root: Path, rel: Path) -> bool:
    """Whether any part of ``root / rel`` below ``root`` is a link (``rel`` itself included).

    ``root`` is not checked: it is the place the person chose (a backup folder they picked, or a
    data folder they moved with a link), so it is measured from where it really is. Parts that do
    not exist yet stop the walk: nothing is there to write through."""
    cur = root
    for part in rel.parts:
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return False
        if is_link_stat(st):
            return True
    return False


def stays_inside(path: str | os.PathLike[str], base_real: str) -> bool:
    """Whether ``path``, with every link resolved, is ``base_real`` or below it. Fails closed."""
    try:
        real = os.path.realpath(path, strict=False)
    except (OSError, ValueError):
        return False
    return real == base_real or real.startswith(base_real.rstrip(os.sep) + os.sep)
