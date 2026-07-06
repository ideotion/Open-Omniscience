"""Dismiss-with-reason capture — closing the evidence-tier feedback loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

When a user dismisses a Lead they may say WHY ("not relevant", "already knew",
"wrong", "noise"…). Recording that optional reason makes the feedback loop real: an
operator can see WHICH card TYPES get dismissed and for WHAT reasons, and tune the
producers accordingly. It is a small, local, JSON-backed store (single-user,
local-first) — the same pattern as the briefing draft / dismissed-id set — and it is
kept SEPARATE from the dismissed-id set (:mod:`src.briefing.service`) so this additive
feedback capture never risks the dismissal mechanic itself.

Honest + bounded: reasons are trimmed and length-capped, the store keeps the most
recent N, and the read side aggregates COUNTS only — never a score, never a verdict.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

REASONS_VERSION = "oo-dismiss-reasons-1"
_MAX_ENTRIES = 1000
_MAX_REASON_LEN = 500


def _path():
    from src.paths import data_dir

    return data_dir() / "briefing_dismiss_reasons.json"


def _load() -> dict:
    path = _path()
    if not path.exists():
        return {"version": REASONS_VERSION, "reasons": []}
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        # A version-matching payload with a non-list "reasons" must not crash the
        # append/iterate paths — coerce to an empty list (like hazards/store filters).
        if not isinstance(data.get("reasons"), list):
            data["reasons"] = []
        return data
    except Exception:  # noqa: BLE001 - a bad file must not break the capture
        _LOG.warning("briefing_dismiss_reasons.json unreadable; starting fresh", exc_info=True)
        return {"version": REASONS_VERSION, "reasons": []}


def _save(data: dict) -> dict:
    data["version"] = REASONS_VERSION
    path = _path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return data


def record_reason(
    card_id: str,
    reason: str,
    *,
    card_type: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Record an optional dismissal reason for a card. Returns the stored entry.

    ``card_id`` is required (the dismissed card's stable id). ``reason`` is trimmed and
    length-capped; an empty reason is still recorded (an explicit "dismissed, no reason"
    is real feedback). The store is bounded to the most recent ``_MAX_ENTRIES``.
    """
    if not card_id or not str(card_id).strip():
        raise ValueError("a card_id is required to record a dismissal reason")
    entry = {
        "card_id": str(card_id).strip(),
        "card_type": (str(card_type).strip() or None) if card_type else None,
        "reason": (reason or "").strip()[:_MAX_REASON_LEN],
        "at": (now or datetime.now(UTC)).isoformat(),
    }
    data = _load()
    data["reasons"].append(entry)
    if len(data["reasons"]) > _MAX_ENTRIES:
        data["reasons"] = data["reasons"][-_MAX_ENTRIES:]
    _save(data)
    return entry


def all_reasons() -> list[dict]:
    """Every recorded dismissal reason, newest last (the raw local capture)."""
    return list(_load().get("reasons", []))


def reason_summary() -> dict:
    """Aggregate the captured reasons — COUNTS only (never a score).

    Returns ``{"total": n, "with_reason": n, "by_card_type": {type: count},
    "by_reason": [{"reason": text, "count": n}], "recent": [...]}``. The ``by_reason``
    list groups on the trimmed, case-folded reason text so "Not relevant" and
    "not relevant" count together; blank reasons are grouped as ``"(no reason given)"``.
    """
    reasons = all_reasons()
    by_type: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    with_reason = 0
    for r in reasons:
        by_type[str(r.get("card_type") or "(unknown)")] += 1
        text = (r.get("reason") or "").strip()
        if text:
            with_reason += 1
            by_reason[text.casefold()] += 1
        else:
            by_reason["(no reason given)"] += 1
    return {
        "total": len(reasons),
        "with_reason": with_reason,
        "by_card_type": dict(by_type.most_common()),
        "by_reason": [{"reason": k, "count": v} for k, v in by_reason.most_common(50)],
        "recent": reasons[-20:],
        "method": (
            "Local capture of optional dismissal reasons; counts grouped by card type and "
            "by case-folded reason text. Counts only, no score, no network."
        ),
    }


def clear_reasons() -> dict:
    """Reset the capture (local maintenance)."""
    return _save({"version": REASONS_VERSION, "reasons": []})
