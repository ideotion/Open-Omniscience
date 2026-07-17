"""
Honest large-edit / suspicious-edit detection for Wikipedia revisions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Flags an edit as worth a journalist's attention using transparent, defined
signals; it surfaces *candidates* (with reason codes), it does not judge an edit
"disinformation". Thresholds are explicit constants. ORES is an optional,
attributed model score (a labelled-by-ORES assertion), never the sole arbiter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Byte thresholds for "large" content change (wikitext bytes).
LARGE_CHANGE_BYTES = 1000
MEDIUM_CHANGE_BYTES = 400
# MediaWiki change tags that indicate reverts/blanking.
_REVERT_TAGS = {"mw-reverted", "mw-undo", "mw-rollback", "mw-manual-revert", "revert"}
_BLANK_TAGS = {"mw-blank", "mw-replace"}
# ORES "damaging" probability at/above which we flag.
ORES_DAMAGING_AT = 0.7
# Edits to the same page within the burst window to call it a burst.
BURST_COUNT = 5


@dataclass
class FlagResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)

    def reasons_csv(self) -> str:
        return ",".join(self.reasons)


def flag_revision(
    *,
    delta_bytes: int | None,
    tags: list[str] | None = None,
    editor_anon: bool = False,
    minor: bool = False,
    ores_damaging: float | None = None,
    burst_count: int = 0,
) -> FlagResult:
    """Return an honest flag + reason codes for one revision.

    Reason codes: large_removal, large_addition, revert, blank, anon_large,
    burst, ores_damaging. A minor edit with a tiny delta is never flagged
    on size alone -- but an independently-observed signal (a revert/blank
    tag, an ORES score, or a computed edit burst) still stands.
    """
    tagset = {t.lower() for t in (tags or [])}
    reasons: list[str] = []
    d = delta_bytes or 0

    if tagset & _BLANK_TAGS:
        reasons.append("blank")
    if tagset & _REVERT_TAGS:
        reasons.append("revert")
    if d <= -LARGE_CHANGE_BYTES:
        reasons.append("large_removal")
    elif d >= LARGE_CHANGE_BYTES:
        reasons.append("large_addition")
    if editor_anon and abs(d) >= MEDIUM_CHANGE_BYTES:
        reasons.append("anon_large")
    if burst_count >= BURST_COUNT:
        reasons.append("burst")
    if ores_damaging is not None and ores_damaging >= ORES_DAMAGING_AT:
        reasons.append("ores_damaging")

    # A flagged-by-tag/score/burst edit stands even if small; only the PURE size-based
    # reasons (large_removal/large_addition/anon_large) need a real byte delta.
    #
    # Audit finding 2026-07-17 (L2): `minor` is the SELF-DECLARED MediaWiki flag (any
    # editor can mark any edit "minor"), unlike the revert/blank tags (software-applied)
    # and ORES score (model-scored) this suppression already correctly treats as
    # override-worthy. burst_count is likewise an independently-COMPUTED signal (from
    # the timestamps of the fetched revision batch, never user-declared) -- so it must
    # get the same treatment, or a bad-faith burst of tiny edits self-tagged "minor"
    # would silently evade detection no matter how large the burst, defeating the exact
    # threat (coordinated/rapid small-edit vandalism) burst_count exists to catch.
    flagged = bool(reasons) and not (
        minor
        and abs(d) < MEDIUM_CHANGE_BYTES
        and not (tagset & (_REVERT_TAGS | _BLANK_TAGS))
        and ores_damaging is None
        and "burst" not in reasons
    )
    return FlagResult(flagged=flagged, reasons=reasons if flagged else [])
