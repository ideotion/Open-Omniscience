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
import time
import traceback
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from src.paths import data_dir

_CAP = 2000  # newest records kept; the file is trimmed when it doubles that
_LOCK = threading.Lock()
_installed = False

# An HTTP error RESPONSE (status >= 400) returned to the client — the "not found",
# "internal error", etc. the UI actually saw. These are NOT necessarily app faults
# (a 404/409/400 is often the correct answer), so they get their OWN level kept OUT
# of _PROBLEM_LEVELS: recording them makes "every error code is in the diagnostic
# log" literally true WITHOUT muddying the problem/lock-error counts. Captured by
# the request middleware, which is the one place that sees the final status code for
# EVERY response — including a 404 on an unmatched route, which logs nothing today.
_HTTP_LEVEL = "HTTP"
# Throttle identical (method, path, status) records so a polling loop hammering one
# failing endpoint (or every poll hitting the locked-503 gate) cannot flood the
# capped log and evict real signal. Distinct errors are still all captured.
_HTTP_THROTTLE_S = 10.0
_HTTP_KEYS_CAP = 1024
_http_last: dict[tuple[str, str, int], float] = {}

# A session-start marker level. The rolling log is append-only and the data dir
# survives reinstalls, so a bundle can show errors from a PAST session that are
# now stale (field test 2026-06-22: a 2026-06-22 bundle showed only 2026-06-17
# lock errors — the gate fix had already stopped them, but with no session
# boundary the maintainer read them as live). A BOOT marker on every install()
# makes the boundary explicit: "newest error before the latest boot ⇒ no errors
# THIS session" is then distinguishable from "logging is broken (no records)".
_BOOT_LEVEL = "BOOT"
# A FRONTEND (browser) error the UI captured via window.onerror /
# unhandledrejection / a failed fetch (recursive-augmentation log #1). Kept on its
# OWN level so it rides the debug bundle + the this-session boundary WITHOUT muddying
# the backend problem counts — a JS error is a real fault, but a client-side one.
_FRONTEND_LEVEL = "FRONTEND"
# Throttle identical frontend errors (same kind+message+source) so a tight render
# loop throwing every frame cannot flood the capped log.
_FRONTEND_THROTTLE_S = 5.0
_FRONTEND_KEYS_CAP = 512
_frontend_last: dict[tuple[str, str, str], float] = {}
# Levels that count as a real (BACKEND) problem (BOOT/INFO/HTTP/FRONTEND markers do not).
_PROBLEM_LEVELS = {"WARNING", "ERROR", "CRITICAL"}

# S5 item 1 (field-feedback 2026-07-23): htmldate.meta.reset_caches() (reached
# via trafilatura's own reset_caches(), which src/scheduler/hygiene.py calls at
# EVERY pass boundary) hits an AttributeError on charset_normalizer's functions
# in the installed version pin and logs it as an ERROR every single time —
# measured 85 of 93 "problems" on one field session, drowning out real signal.
# TARGETED, never a blanket suppression of the whole logger: only this one
# known-benign message class from this one logger is dropped from the COUNTERS;
# any other record from htmldate.meta (e.g. a genuine import failure) still
# counts as a problem.
_HTMLDATE_NOISE_LOGGER = "htmldate.meta"
_HTMLDATE_NOISE_MESSAGE = "impossible to clear cache for function"


class _HtmldateCacheNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        if record.name != _HTMLDATE_NOISE_LOGGER:
            return True
        try:
            return _HTMLDATE_NOISE_MESSAGE not in record.getMessage()
        except Exception:  # noqa: BLE001 - never let the filter itself break logging
            return True


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


def note_http_error(method: str, path: str, status: int, *, detail: str | None = None) -> None:
    """Record an HTTP error RESPONSE (status >= 400) the client received, so the
    downloadable diagnostic log shows EVERY error code the UI saw — not only the ones
    an endpoint happened to log (a 404 on an unmatched route logs nothing otherwise).

    Best-effort; never raises. Identical (method, path, status) is throttled to once
    per ``_HTTP_THROTTLE_S`` so a poll loop cannot flood the capped log. Level
    ``HTTP`` keeps these out of the problem/lock counts (a response code is not, by
    itself, an app fault)."""
    try:
        key = (str(method), str(path), int(status))
        now = time.monotonic()
        with _LOCK:
            last = _http_last.get(key)
            if last is not None and (now - last) < _HTTP_THROTTLE_S:
                return
            if len(_http_last) > _HTTP_KEYS_CAP:
                _http_last.clear()
            _http_last[key] = now
        # _append (which re-acquires _LOCK) runs AFTER the `with` block releases it.
        msg = f"HTTP {status} {method} {path}"
        if detail:
            msg = f"{msg} — {str(detail)[:200]}"
        _append(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "level": _HTTP_LEVEL,
                "logger": "http",
                "status": status,
                "method": str(method),
                "path": str(path),
                "message": msg,
            }
        )
    except Exception:  # noqa: BLE001 - diagnostics must never break the app
        return


def note_frontend_error(
    kind: str,
    message: str,
    *,
    source: str | None = None,
    endpoint: str | None = None,
    lineno: int | None = None,
    ui_lang: str | None = None,
) -> None:
    """Record a BROWSER error captured by the frontend (window.onerror /
    unhandledrejection / a failed fetch), so the "browser-unverified" debt becomes
    OBSERVABLE — a ``t is not defined`` or a dead click shows in the debug bundle
    instead of the maintainer finding it one tab at a time (recursive-augmentation
    log #1).

    Local-only, no PII by design (error text + which function/endpoint only — the
    frontend is instructed to send nothing user-typed). Best-effort; never raises;
    identical (kind, message, source) is throttled so a render loop can't flood the log.
    """
    try:
        k = (str(kind)[:40], str(message)[:200], str(source or "")[:200])
        now = time.monotonic()
        with _LOCK:
            last = _frontend_last.get(k)
            if last is not None and (now - last) < _FRONTEND_THROTTLE_S:
                return
            if len(_frontend_last) > _FRONTEND_KEYS_CAP:
                _frontend_last.clear()
            _frontend_last[k] = now
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": _FRONTEND_LEVEL,
            "logger": "frontend",
            "kind": str(kind)[:40],
            "message": str(message)[:500],
        }
        if source:
            entry["source"] = str(source)[:300]
        if endpoint:
            entry["endpoint"] = str(endpoint)[:300]
        if lineno is not None:
            entry["lineno"] = int(lineno)
        if ui_lang:
            entry["ui_lang"] = str(ui_lang)[:16]
        _append(entry)
    except Exception:  # noqa: BLE001 - diagnostics must never break the app
        return


def install() -> None:
    """Attach the handler to the root logger (idempotent AND self-healing:
    if something cleared the root handlers — test frameworks do — re-attach).
    Records a session-start marker so bundles carry honest session boundaries."""
    global _installed
    root = logging.getLogger()
    if any(isinstance(h, _JsonlErrorHandler) for h in root.handlers):
        _installed = True
        return
    handler = _JsonlErrorHandler(level=logging.WARNING)
    handler.addFilter(_HtmldateCacheNoiseFilter())
    root.addHandler(handler)
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
            "http_errors_total": 0,
            "http_errors_this_session": 0,
            "http_status_breakdown": {},
            "note": "no error log yet — logging is installed at boot",
        }
    ats: list[str] = [str(r["at"]) for r in records if r.get("at")]
    boots: list[str] = [
        str(r["at"]) for r in records if r.get("level") == _BOOT_LEVEL and r.get("at")
    ]
    last_boot: str | None = max(boots) if boots else None

    def _is_problem(r: dict) -> bool:
        return r.get("level") in _PROBLEM_LEVELS

    def _is_locked(r: dict) -> bool:
        blob = (r.get("message", "") + r.get("traceback_tail", "")).lower()
        return "database is locked" in blob

    def _is_http(r: dict) -> bool:
        return r.get("level") == _HTTP_LEVEL

    def _this_session(r: dict) -> bool:
        # No boot marker yet (pre-this-change logs) ⇒ count nothing as "this
        # session" rather than fabricating a boundary.
        return bool(last_boot) and bool(r.get("at")) and r["at"] >= last_boot

    def _is_frontend(r: dict) -> bool:
        return r.get("level") == _FRONTEND_LEVEL

    http_status = Counter(
        str(r.get("status")) for r in records if _is_http(r) and r.get("status") is not None
    )
    frontend_kinds = Counter(
        str(r.get("kind")) for r in records if _is_frontend(r) and r.get("kind")
    )

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
        "http_errors_total": sum(1 for r in records if _is_http(r)),
        "http_errors_this_session": sum(1 for r in records if _is_http(r) and _this_session(r)),
        "http_status_breakdown": dict(http_status),
        "frontend_errors_total": sum(1 for r in records if _is_frontend(r)),
        "frontend_errors_this_session": sum(
            1 for r in records if _is_frontend(r) and _this_session(r)
        ),
        "frontend_kind_breakdown": dict(frontend_kinds),
    }
