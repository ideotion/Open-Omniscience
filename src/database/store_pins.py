"""The stores whose read descriptor stays open while their name leads to them (R789, row 310).

A module of its own, with no imports of the app, so the session can name the library at import time without importing
``src.database.connect`` (importing the app must open no store: tests/test_env_passphrase_taken.py). ``connect`` reads
:data:`PINNED` when it decides whether a descriptor may be closed."""

from __future__ import annotations

import os
import threading

PINNED: set[str] = set()  # realpaths of the stores named here
_lock = threading.Lock()


def pin_store(path: str | os.PathLike[str]) -> None:
    """Keep the descriptor of ours on ``path`` open for as long as the name leads to the same file."""
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return
    with _lock:
        PINNED.add(real)
