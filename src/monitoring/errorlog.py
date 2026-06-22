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

# A session-start marker level. The rolling log is append-only and the data dir
# survives reinstalls, so a bundle can show errors from a PAST session that are
# now stale (field test 2026-06-22: a 2026-06-22 bundle showed only 2026-06-17
# lock errors — the gate fix had already stopped them, but with no session
# boundary the maintainer read them as live). A BOOT marker on every install()
# makes the boundary explicit: "newest error before the latest boot ⇒ no errors
# THIS session" is then distinguishable from "logging is broken (no records)".
_BOOT_LEVEL = "BOOT"
# Levels that count as a real problem (BOOT/INFO markers do not).
_PROBLEM_LEVELS = {"WARNING", "ERROR", "CRITICAL"}


def _log_path() -> Path:
    return data_dir() / "app_errors.jsonl"


def _append(entry: dict) -> None:
    """Append one record to the rolling log, trimmed + best-effort (never raises)."""
    try:
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
        except Exception:  # noqa: BLE001 - the log must never break the app
            return
        _append(entry)


def note_boot() -> None:
    """Append a session-start marker so a debug bundle shows clear session
    boundaries. Best-effort; never raises. Called from install() at every boot."""
    _append(
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": _BOOT_LEVEL,
            "logger": "app",
            "message": "--- app session started ---",
        }
    )


def install() -> None:
    """Attach the handler to the root logger (idempotent AND self-healing:
    if something cleared the root handlers — test frameworks do — re-attach).
    Records a session-start marker so bundles carry honest session boundaries."""
    global _installed
    root = logging.getLogger()
    if any(isinstance(h, _JsonlErrorHandler) for h in root.handlers):
        _installed = True
        return
    root.addHandler(_JsonlErrorHandler(level=logging.WARNING))
    _installed = True
    note_boot()


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


def summary() -> dict:
    """Honest metadata about the rolling log so a bundle reader can tell whether
    the error window is CURRENT — no inference, counts + timestamps only.

    Crucially answers "is the data-loss happening NOW?": ``problems_this_session``
    and ``locked_errors_this_session`` count records SINCE the latest boot marker,
    so a clean current session reads zero even when the file still holds an old
    session's errors (which would otherwise look live)."""
    records = recent_errors(limit=_CAP)
    if not records:
        return {
            "records": 0,
            "first_at": None,
            "last_at": None,
            "last_session_started_at": None,
            "problems_total": 0,
            "problems_this_session": 0,
            "locked_errors_total": 0,
            "locked_errors_this_session": 0,
            "note": "no error log yet — logging is installed at boot",
        }
    ats = [r.get("at") for r in records if r.get("at")]
    last_boot = max(
        (r["at"] for r in records if r.get("level") == _BOOT_LEVEL and r.get("at")),
        default=None,
    )

    def _is_problem(r: dict) -> bool:
        return r.get("level") in _PROBLEM_LEVELS

    def _is_locked(r: dict) -> bool:
        blob = (r.get("message", "") + r.get("traceback_tail", "")).lower()
        return "database is locked" in blob

    def _this_session(r: dict) -> bool:
        # No boot marker yet (pre-this-change logs) ⇒ count nothing as "this
        # session" rather than fabricating a boundary.
        return bool(last_boot) and bool(r.get("at")) and r["at"] >= last_boot

    return {
        "records": len(records),
        "first_at": min(ats) if ats else None,
        "last_at": max(ats) if ats else None,
        "last_session_started_at": last_boot,
        "problems_total": sum(1 for r in records if _is_problem(r)),
        "problems_this_session": sum(1 for r in records if _is_problem(r) and _this_session(r)),
        "locked_errors_total": sum(1 for r in records if _is_locked(r)),
        "locked_errors_this_session": sum(
            1 for r in records if _is_locked(r) and _this_session(r)
        ),
    }
