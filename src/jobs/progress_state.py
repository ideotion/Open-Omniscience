"""Shared persisted sweep-cursor read/write for the resumable, progressive job modules.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ai_layer/triage_job.py``, ``src/ai_layer/source_tags_job.py``,
``src/ai_layer/perception_extract_job.py`` and ``src/bulletin/narration_job.py`` each
drive a batched, restartable PROGRESSIVE sweep over their own domain (keywords,
sources, articles, editions) and need to persist a small JSON cursor so a pause, a
cancel, or an app restart can resume from where it left off. This is exactly the
category ``src/jobs/background.py`` says, in its own module docstring, it does NOT
serve -- that module manages BOUNDED one-shot operations with no persisted cursor by
design; the four modules above are the "persisted, resumable managers" it contrasts
itself with, so this generic read/write pair lives here, beside it, instead.

The four modules had each grown their own byte-for-byte copy of this logic (a
copy-paste-drift audit finding); only WHERE each module's cursor file lives is
genuinely module-specific (different filenames/directories) and stays local to each
module's own ``_progress_state_path()`` / ``_state_path()`` helper. This module holds
only the generic "read this JSON path as a dict, defaulting to ``{}`` on any failure"
and "atomically replace this path with this dict" logic, so a hardening fix (like the
``mkdir`` + tmp-file cleanup below, previously present in only one of the four copies)
now reaches every caller at once.

No score, local only, no network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_progress_state(path: Path) -> dict:
    """The persisted sweep cursor ({} when no sweep ever ran / the file is
    unreadable -- a corrupt/missing state file just means "start fresh")."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable cursor is "no paused run"
        return {}


def save_progress_state(state: dict, path: Path) -> None:
    """Atomic write (tmp + os.replace) so a crash mid-save never leaves a cursor
    that parses.

    Creates the state directory first (a fresh install, or a module whose state
    directory nothing else has created yet, must not crash on its very first save)
    and cleans up the tmp file even when the write succeeds but ``os.replace`` itself
    fails partway (e.g. a permissions issue) -- so a stray ``.tmp`` file is never
    left behind forever.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
