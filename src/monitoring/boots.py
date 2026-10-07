"""The last boots of this install, each with how its session ended, as one diagnostics-bundle member (2026-10-07).

The same slot contract as ``session_hwm.diagnostics_member`` (``(max_bytes) -> dict``, never raises, keeps the newest, names the
cut): the session ledger's last :data:`BOOTS_KEPT` boots, each joined with its ``end`` record, so a reader sees a crash loop as a
list (which build, which memory tier, which allocator and core-guard setting, how each ended and what the peak was) and not as
one session's report. Counts, times and labels only: no path, no text of an exception.

What it does not carry: the unlock timing fields (the WAL work's, not in this build's ledger), and anything the ledger did not
record at the head that wrote the boot (a field a build did not know is ABSENT, never ``null`` standing for "none").
"""

from __future__ import annotations

import json
from typing import Any

#: How many boots the member shows at most (the ledger holds up to 4,000 lines). WHAT IT PROTECTS: the member's size and a reader's
#: patience: ten boots show a crash loop's shape (which build, which tier, how each ended); older ones are counted in
#: ``boots_in_ledger`` and ``boots_not_shown``, never silently dropped.
BOOTS_KEPT = 10
#: What the bundle gives the member at most. WHAT IT PROTECTS: the single Diagnostics zip's 4 MB budget (R119), of which this member
#: takes a small share; ten boots with their end records (each up to about 5 KiB) can exceed it, and the member then drops the OLDEST
#: boots until it fits and says how many.
DEFAULT_MAX_BYTES = 30 * 1024
#: The longest the text of an error the member itself met may be (a ledger that cannot be read): WHAT IT PROTECTS: the member's size
#: against an engine's message; it is scrubbed first and its paths tokenised, and only then cut.
_ERROR_TEXT_MAX = 160

_BOOT_FIELDS = (
    "session_id", "at", "pid", "app_version", "build", "previous_sentinel_state", "previous_closed_by_this_boot",
    "clocks", "ledger_features", "memory_budget", "allocator", "rollup_serve_mode", "core_guard",
)
_END_FIELDS = (
    "at", "clean", "written_by", "basis", "uptime_s", "span_s", "sentinel_state", "reason", "exit", "source",
    "previous_peaks", "previous_at_peak", "previous_pressure",
)


def _joined(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ends: dict[Any, dict[str, Any]] = {}
    for rec in records:
        if rec.get("kind") == "end" and rec.get("session_id") is not None:
            ends[rec["session_id"]] = rec  # the last end line of a session wins
    out = []
    for rec in records:
        if rec.get("kind") != "boot":
            continue
        row = {k: rec[k] for k in _BOOT_FIELDS if k in rec}
        end = ends.get(rec.get("session_id"))
        row["end"] = {k: end[k] for k in _END_FIELDS if k in end} if end else None
        out.append(row)
    return out


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def diagnostics_member(max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """The newest :data:`BOOTS_KEPT` boots of the ledger, cut oldest-first to fit ``max_bytes`` with the count named. The cut's own
    counts are part of what is measured, so the member the caller gets is never over the budget by the size of its own bookkeeping."""
    try:
        from src.monitoring import session_history

        budget = int(max_bytes)
        boots = _joined(session_history.read_records())
        total = len(boots)
        kept = boots[-BOOTS_KEPT:]
        out: dict[str, Any] = {
            "method": "the session ledger's boot records, each joined with its end record (the last end line of a session wins)",
            "boots_in_ledger": total,
            "boots": kept,
            "dropped_oldest_to_fit": 0,
            "boots_not_shown": total - len(kept),
            "not_in_this_build": ["unlock timing"],
        }
        while kept and _size(out) > budget:
            kept = kept[1:]
            out["boots"] = kept
            out["dropped_oldest_to_fit"] += 1
            out["boots_not_shown"] = total - len(kept)
        if _size(out) > budget:
            return {"omitted": "max_bytes is below the member's fixed part", "needs_at_least_bytes": _size(out)}
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        return {"error": _error_text(exc)}


def _error_text(exc: BaseException) -> str:
    """What the member says of an error it met: the engine's words with every held passphrase taken out (a ``UnicodeDecodeError``
    is the class and a fixed note: its text names a character), the paths in it tokenised, and only then cut."""
    try:
        from src.monitoring.path_tokens import tokenise_paths
        from src.monitoring.secret_scrub import exception_text

        return tokenise_paths(exception_text(exc))[:_ERROR_TEXT_MAX]
    except Exception:  # noqa: BLE001 - the member never raises
        return type(exc).__name__
