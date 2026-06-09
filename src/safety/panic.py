"""
Panic wipe — a deliberate, confirmed destruction of the local data directory.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

For a journalist who must remove the corpus, keys and caches *now* (e.g. an imminent
seizure). It best-effort overwrites file contents before unlinking, but is **honest about
the limit**: on SSDs and copy-on-write filesystems, overwrite-in-place does not guarantee
the old blocks are gone — only full-disk encryption (LUKS / Qubes / Tails) makes a wipe
truly unrecoverable. Refuses to run without an explicit confirmation.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from pathlib import Path

_LOG = logging.getLogger(__name__)

_LIMIT_NOTE = (
    "Overwrite-in-place does NOT guarantee unrecoverability on SSD/flash or copy-on-write "
    "filesystems (wear-levelling/snapshots may retain old blocks). For a guaranteed wipe, "
    "use full-disk encryption (LUKS/Qubes/Tails) and destroy the key."
)


def _overwrite(path: Path) -> None:
    try:
        size = path.stat().st_size
        with open(path, "r+b", buffering=0) as f:
            f.write(os.urandom(min(size, 4 * 1024 * 1024)))
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass  # best-effort; deletion below still happens


def panic_wipe(data_dir: Path | None = None, *, confirm: bool = False) -> dict:
    """Best-effort overwrite then delete everything under the data dir. Requires ``confirm``."""
    if not confirm:
        raise PermissionError("panic_wipe requires confirm=True (this is irreversible)")
    from src.paths import data_dir as _default_dir

    target = Path(data_dir) if data_dir else _default_dir()
    files = wiped = 0
    for root, _dirs, names in os.walk(target):
        for name in names:
            files += 1
            p = Path(root) / name
            _overwrite(p)
            try:
                p.unlink()
                wiped += 1
            except OSError:
                _LOG.warning("panic: could not unlink %s", p)
    with contextlib.suppress(OSError):
        shutil.rmtree(target, ignore_errors=True)
    _LOG.warning("PANIC WIPE executed on %s (%d/%d files)", target, wiped, files)
    return {"data_dir": str(target), "files_seen": files, "files_wiped": wiped,
            "limit": _LIMIT_NOTE}
