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
from typing import Any

from src.monitoring.secret_scrub import TRACEBACK_ATTRIBUTE, scrubbed
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

# S5 item 1 (field-feedback 2026-07-23) + the 2026-07-26 hardware-diagnostics batch:
# htmldate.meta.reset_caches() (reached via trafilatura's own reset_caches(), which
# src/scheduler/hygiene.py calls at EVERY pass boundary) hits an AttributeError on
# charset_normalizer's functions in the installed version pin and logs it as an ERROR
# every single time -- measured 85 of 93 "problems" on one field session, and,
# independently, live-confirmed printing to the CONSOLE on a fresh install (25 repeated
# lines) despite the 2026-07-23 fix, because that fix only filtered this app's OWN
# JSONL handler, never the source logger -- so the noise still reached every OTHER
# handler on the chain (console, uvicorn's, Python's own last-resort stderr fallback).
# A second, structurally identical noise source was independently found the same day:
# trafilatura.metadata's "error in JSON metadata extraction" (58% of one field
# instance's 300-record error-log sample). Both are fixed with ONE mechanism, applied
# at the LOGGER level (not the handler level) so the record is dropped before it can
# reach ANY handler in the process -- never a blanket suppression of either logger:
# only this ONE known-benign message class per logger is dropped; any other message
# from either logger (e.g. a genuine import failure) still counts as a problem and
# still reaches the console.
_HTMLDATE_NOISE_LOGGER = "htmldate.meta"
_HTMLDATE_NOISE_MESSAGE = "impossible to clear cache for function"
_TRAFILATURA_NOISE_LOGGER = "trafilatura.metadata"
_TRAFILATURA_NOISE_MESSAGE = "error in JSON metadata extraction"
_THIRD_PARTY_NOISE_RULES: dict[str, str] = {
    _HTMLDATE_NOISE_LOGGER: _HTMLDATE_NOISE_MESSAGE,
    _TRAFILATURA_NOISE_LOGGER: _TRAFILATURA_NOISE_MESSAGE,
}


class _ThirdPartyCacheNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        needle = _THIRD_PARTY_NOISE_RULES.get(record.name)
        if needle is None:
            return True
        try:
            return needle not in record.getMessage()
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


def _flags(message: str, traceback_tail: str) -> dict[str, bool]:
    """What the summary counts a record for (``database is locked``, an aborted statement), read off the text AS LOGGED. The
    journal's text has the passphrases out of it, and a passphrase that is a piece of those phrases (``database``,
    ``interrupted``) would take the phrase out with it and zero the count: so the flags are taken before the scrub and kept as
    fields, which hold a boolean and no text."""
    blob = (message[:500] + traceback_tail[-1500:]).lower()
    found = {}
    if "database is locked" in blob:
        found["locked"] = True
    if "interrupted" in blob or ("exceeded the" in blob and "deadline" in blob):
        found["interrupted"] = True
    return found


class _JsonlErrorHandler(logging.Handler):
    """Every WARNING-or-above record of every logger in the process enters THIS journal here, and the debug bundle carries
    the journal (``recent_errors``): the text of every module's exception, however it was logged, becomes an entry here. It is
    not the only place a record is written (the log files and the console that ``setup_logging`` attaches are their own sinks:
    docs/ledger/OPEN_QUEUE.md). The message and the traceback are scrubbed of every passphrase the process holds
    (``secret_scrub.scrubbed``: as typed, as an SQL literal, as ``repr`` and as JSON write it, and written again by each other,
    up to three deep) BEFORE the cut that keeps their first 500 and last 1,500 characters, because a text cut first can split a
    passphrase and keep half of it. It is the net under the per-site scrubs (``log_failure`` and the handlers the static guard
    reads), and it knows only the passphrases the process holds: one typed into a request being served, or a backup's, is the
    site's to take out. When what the process holds cannot be read the entry carries ``secret_scrub.UNREADABLE_TEXT`` where the
    message and the traceback would be: the record is still counted, and nothing it said is kept."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            raw_message = record.getMessage()
            entry: dict[str, Any] = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": scrubbed(raw_message)[:500],
            }
            raw_tb = ""
            if record.exc_info and record.exc_info[0] is not None:
                raw_tb = "".join(traceback.format_exception(*record.exc_info))
            else:
                # A handler that holds a passphrase logs through ``secret_scrub.log_failure``, which writes the
                # traceback as TEXT with the secrets out of it (a record's ``exc_info`` carries the message as raised)
                # and hands it over as an attribute, so the bundle keeps the frames that say where the failure was.
                attached = getattr(record, TRACEBACK_ATTRIBUTE, None)
                if isinstance(attached, str):
                    raw_tb = attached
            if raw_tb:
                entry["traceback_tail"] = scrubbed(raw_tb)[-1500:]
            entry.update(_flags(raw_message, raw_tb))
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


def note_http_error(method: str, path: str, status: int) -> None:
    """Record an HTTP error RESPONSE (status >= 400) the client received, so the
    downloadable diagnostic log shows EVERY error code the UI saw — not only the ones
    an endpoint happened to log (a 404 on an unmatched route logs nothing otherwise).

    Best-effort; never raises. Identical (method, path, status) is throttled to once
    per ``_HTTP_THROTTLE_S`` so a poll loop cannot flood the capped log. Level
    ``HTTP`` keeps these out of the problem/lock counts (a response code is not, by
    itself, an app fault). It records the status, the method and the path and NEVER the
    response's text (``tests/test_restore_paths_scrub_passphrase.py`` pins that it takes none):
    the words of a response are the caller's own."""
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

        def clean(value: object, cut: int) -> str:
            """The browser's words with the passphrases the process holds out of them, and only then cut: a text cut first can
            split a passphrase and keep half of it (the browser sends its words whole for the same reason)."""
            return scrubbed(str(value))[:cut]

        k = (clean(kind, 40), clean(message, 200), clean(source or "", 200))
        now = time.monotonic()
        with _LOCK:
            last = _frontend_last.get(k)
            if last is not None and (now - last) < _FRONTEND_THROTTLE_S:
                return
            if len(_frontend_last) > _FRONTEND_KEYS_CAP:
                _frontend_last.clear()
            _frontend_last[k] = now
        entry: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": _FRONTEND_LEVEL,
            "logger": "frontend",
            "kind": clean(kind, 40),
            "message": clean(message, 500),
        }
        if source:
            entry["source"] = clean(source, 300)
        if endpoint:
            entry["endpoint"] = clean(endpoint, 300)
        if lineno is not None:
            entry["lineno"] = int(lineno)
        if ui_lang:
            entry["ui_lang"] = clean(ui_lang, 16)
        _append(entry)
    except Exception:  # noqa: BLE001 - diagnostics must never break the app
        return


def install() -> None:
    """Attach the handler to the root logger (idempotent AND self-healing:
    if something cleared the root handlers — test frameworks do — re-attach).
    Records a session-start marker so bundles carry honest session boundaries.

    Also attaches the third-party noise filter DIRECTLY to the noisy loggers
    themselves — not just to this app's own JSONL handler — so the known-benign
    message classes never reach ANY handler (console included), while a genuinely
    different message from the same logger still does. A handler-level filter only
    suppresses a record for THAT ONE handler; a logger-level filter is checked
    before the record reaches any handler in the process at all (2026-07-26:
    live-confirmed on a fresh install that the prior handler-only filter still let
    htmldate.meta's noise print to the console)."""
    global _installed
    root = logging.getLogger()
    handler_present = any(isinstance(h, _JsonlErrorHandler) for h in root.handlers)
    if not handler_present:
        handler = _JsonlErrorHandler(level=logging.WARNING)
        root.addHandler(handler)
    for _name in _THIRD_PARTY_NOISE_RULES:
        _lg = logging.getLogger(_name)
        if not any(isinstance(f, _ThirdPartyCacheNoiseFilter) for f in _lg.filters):
            _lg.addFilter(_ThirdPartyCacheNoiseFilter())
    _installed = True
    if not handler_present:
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
            "records_cap": _CAP,
            "first_at": None,
            "last_at": None,
            "last_session_started_at": None,
            "problems_total": 0,
            "problems_this_session": 0,
            "locked_errors_total": 0,
            "locked_errors_this_session": 0,
            "interrupted_errors_total": 0,
            "interrupted_errors_this_session": 0,
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
        # The flag the record was written with (taken before the scrub, :func:`_flags`); the text for a record written
        # before the flags existed.
        blob = (r.get("message", "") + r.get("traceback_tail", "")).lower()
        return bool(r.get("locked")) or "database is locked" in blob

    def _is_interrupted(r: dict) -> bool:
        """A statement that was ABORTED mid-flight, either shape.

        Two things produce it and both matter to the same reader. ``statement_deadline``
        raises a typed ``StatementTimeout`` when a read overruns its budget; and SQLite
        itself raises "interrupted" when a progress handler returns non-zero, which is how
        that abort reaches the driver and also how a handler left armed on a POOLED
        connection interrupts the NEXT checkout on the first holder's clock. Counting them
        together is deliberate: the question a soak asks is "was work being cut short", and
        splitting the two would make each look rarer than the condition is.
        """
        blob = (r.get("message", "") + r.get("traceback_tail", "")).lower()
        return bool(r.get("interrupted")) or "interrupted" in blob or ("exceeded the" in blob and "deadline" in blob)

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
        # The retention that bounds every count below, travelling WITH them: this log
        # is a rolling ring, so ``records == records_cap`` means older records were
        # trimmed and each total is a FLOOR, not a census. A count published without
        # its own ceiling is the shape of a figure that is secretly a cap.
        "records_cap": _CAP,
        "first_at": min(ats) if ats else None,
        "last_at": max(ats) if ats else None,
        "last_session_started_at": last_boot,
        "problems_total": sum(1 for r in records if _is_problem(r)),
        "problems_this_session": sum(1 for r in records if _is_problem(r) and _this_session(r)),
        "locked_errors_total": sum(1 for r in records if _is_locked(r)),
        "locked_errors_this_session": sum(
            1 for r in records if _is_locked(r) and _this_session(r)
        ),
        "interrupted_errors_total": sum(1 for r in records if _is_interrupted(r)),
        "interrupted_errors_this_session": sum(
            1 for r in records if _is_interrupted(r) and _this_session(r)
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
