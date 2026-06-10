"""
Rolling application error log — the debugging half of the diagnostics channel.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10): the operator clicks through the app, downloads
ONE debug bundle and hands it over — it must contain what a developer needs to
diagnose remotely. Warnings and errors are the heart of that, so a process-wide
logging handler appends every WARNING+ record (logger, message, traceback tail)
to ``data/app_errors.jsonl``, bounded by trimming to the newest _CAP lines.

Honesty/safety: local file, exported only when the operator clicks; the handler
must NEVER raise (a broken log must not break the app).
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path

from src.paths import data_dir

_CAP = 2000  # newest records kept; the file is trimmed when it doubles that
_LOCK = threading.Lock()
_installed = False


def _log_path() -> Path:
    return data_dir() / "app_errors.jsonl"


class _JsonlErrorHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            entry = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage()[:500],
            }
            if record.exc_info and record.exc_info[0] is not None:
                tb = "".join(traceback.format_exception(*record.exc_info))
                entry["traceback_tail"] = tb[-1500:]
            line = json.dumps(entry, ensure_ascii=False)
            with _LOCK:
                path = _log_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                # Bounded by construction: trim once the file doubles the cap.
                if path.stat().st_size > 512 * 1024:
                    lines = path.read_text(encoding="utf-8").splitlines()[-_CAP:]
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001, S110 - the log must never break the app
            pass


def install() -> None:
    """Attach the handler to the root logger (idempotent AND self-healing:
    if something cleared the root handlers — test frameworks do — re-attach)."""
    global _installed
    root = logging.getLogger()
    if any(isinstance(h, _JsonlErrorHandler) for h in root.handlers):
        _installed = True
        return
    root.addHandler(_JsonlErrorHandler(level=logging.WARNING))
    _installed = True


def recent_errors(limit: int = 300) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
