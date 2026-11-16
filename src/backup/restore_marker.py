"""ONE "a restore is in progress" marker, shared by every restore path (R712, export side).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. R712 runs both ways: a restore refuses while a backup export runs, and an export
refuses to start or resume while a restore runs. The export used to tell a restore apart
by the import queue's state and the restore MODES of the volume and folder managers -- so a
direct single-file restore (``POST /api/backup/legacy/restore``, synchronous, owning no
manager) was invisible to it, and an export could start in the middle of its swap.

WHAT IT IS. A counter under one lock. Every restore path runs inside :func:`restoring`
(the single-file restore, the volume restore's worker, the folder restore's worker, the
import queue's run; nesting counts, so a queue item inside the queue's own marker is fine).
:func:`src.backup.export_job.ExportJobManager` checks :func:`restore_in_progress` while
holding :data:`LOCK` and becomes live before it lets go of it.

WHY THAT CLOSES THE RACE. A restore enters the marker (under :data:`LOCK`) BEFORE its own
last check for a running export (``refuse_while_writer_jobs_run`` -> ``export_refusal``).
The export's check-and-go and the restore's entry are ordered by the same lock: either the
export went live first, and the restore's later check sees it and refuses; or the restore
entered first, and the export sees the marker and refuses. Nothing here stops a job or
waits: R659's and R689's stop semantics are untouched.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

#: The one lock: the marker's counter, and the export's check-and-go (R712).
LOCK = threading.RLock()
_DEPTH = 0


@contextmanager
def restoring() -> Iterator[None]:
    """Mark a restore as in progress for the duration of the block."""
    global _DEPTH
    with LOCK:
        _DEPTH += 1
    try:
        yield
    finally:
        with LOCK:
            _DEPTH -= 1


def marked[F: Callable[..., Any]](fn: F) -> F:
    """Run ``fn`` inside :func:`restoring` (the restore workers and the single-file restore)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with restoring():
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def restore_in_progress() -> bool:
    """Whether any restore path is inside its marker now."""
    with LOCK:
        return _DEPTH > 0
