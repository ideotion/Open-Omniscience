"""Poll transparency — a disclosure CHECKLIST (Tier 2), never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling (elections/civic vertical, poll analysis): poll analysis is an audit
METHOD, near-neutral (survey science, not values), never a RESULT. Tier 2 is a transparency
CHECKLIST plus a verbatim display of the question wording when the data allows -- the
strongest, safest, language-agnostic signal. The BINDING rules, enforced here:

  * NO composite poll score. This records, per standard methodological disclosure, only
    whether it was STATED (present / absent) -- NEVER whether a stated value is "good". A
    fully-disclosed poll can still be wrong; a sparsely-disclosed one can still be right.
  * NON-DISCLOSURE OUTRANKS DISCLOSED-IMPERFECTION. Opacity is what disqualifies a reader
    from checking a poll -- disclosed ugliness never does. So a disclosed n=100 is treated
    exactly like a disclosed n=10000 (both "disclosed"); we never punish transparency by
    judging the value.
  * NEVER label a poll "useless". A poll below the disclosure floor is described as "cannot
    be independently interpreted without X", and the user concludes.
  * Per-language caveat on anything semantic (the question wording is echoed as STRUCTURE;
    its meaning is the reader's to judge).

A poll is an INSTANCE of the official-statistics pattern (a stanced/sponsored source stated
as a descriptive caveat, never a verdict label).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.briefing.card import assert_no_score_fields

# The standard methodological disclosures (AAPOR Transparency Initiative-style). CORE is the
# floor a reader needs to interpret a poll AT ALL; SUPPLEMENTARY strengthens the audit. Each
# is (key, human label, one plain sentence of why it matters). Presence, not quality.
CORE_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("pollster", "Who conducted the poll",
     "the organization that ran it — needed to trace method and track record"),
    ("sponsor", "Who paid for or commissioned it",
     "funding is a stance to weigh, disclosed as a fact, never a verdict"),
    ("fielding_dates", "When it was in the field",
     "a poll is a snapshot of a moment; without the dates it cannot be placed in time"),
    ("sample_size", "How many people were asked (n)",
     "the base every uncertainty statement rests on"),
    ("population", "Who was sampled (the frame / population)",
     "'adults', 'likely voters', 'members' — a result only means something for a stated group"),
    ("question_wording", "The exact question asked",
     "wording drives answers; the verbatim text is the most checkable, language-agnostic fact"),
)
SUPPLEMENTARY_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("sampling_method", "Probability vs non-probability sampling",
     "whether classical margin-of-error statements even apply"),
    ("margin_of_error", "The stated margin of error / credibility interval",
     "the disclosed uncertainty (its correctness is not judged here)"),
    ("mode", "How respondents were reached (phone / online / in-person …)",
     "mode shapes who is reachable and how they answer"),
    ("weighting", "How the sample was weighted / adjusted",
     "adjustments to match the population — a disclosed methodological choice"),
    ("response_rate", "The response / completion rate",
     "how many asked actually answered"),
)

_QUESTION_CAVEAT = (
    "The question wording is shown verbatim as STRUCTURE — its meaning, framing and any "
    "leading effect are for you to judge (and translation can shift nuance)."
)

_METHOD = (
    "For each standard methodological disclosure (AAPOR Transparency Initiative-style), "
    "records PRESENT or ABSENT only — never the value's quality. Core disclosures are the "
    "floor needed to interpret a poll; their absence is highlighted. The count of disclosed "
    "items is a plain tally, not a score. The question wording is echoed verbatim when "
    "disclosed. Presence only, no composite score, no ranking, no 'useless' label."
)

_CAVEAT = (
    "This is a DISCLOSURE checklist, not a quality grade. It records only whether each "
    "methodological fact was STATED — never whether a stated value is good. A fully-disclosed "
    "poll can still be wrong, and a sparsely-disclosed one can still be right; opacity does "
    "not make a poll 'useless', it only stops you checking it yourself. Non-disclosure of a "
    "CORE item (who, who paid, when, n, who was sampled, the exact question) matters more than "
    "any disclosed imperfection — transparency is never penalized here."
)


@dataclass(frozen=True)
class PollTransparency:
    """A poll's disclosure checklist. Counts + presence flags only, never a score.

    Fields:
      * ``disclosed`` / ``undisclosed`` -- keys stated / not stated.
      * ``core_gaps``     -- the undisclosed CORE items (the floor a reader lacks).
      * ``n_disclosed`` / ``n_items`` -- a plain tally (NOT a grade; see the caveat).
      * ``checklist``     -- per item ``{key, label, why, tier, disclosed, note}``.
      * ``question``      -- the verbatim question wording when disclosed (else None).
      * ``notes``         -- factual DISCLOSURE-GAP notes (never quality judgments).
      * ``meets_floor``   -- whether every CORE item is disclosed (a factual completeness
                             statement of the FLOOR, not a pass/fail verdict on the poll).
    """

    disclosed: tuple[str, ...]
    undisclosed: tuple[str, ...]
    core_gaps: tuple[str, ...]
    n_disclosed: int
    n_items: int
    checklist: tuple[dict, ...]
    question: str | None
    notes: tuple[str, ...]
    meets_floor: bool
    method: str
    caveat: str

    def to_dict(self) -> dict:
        return {
            "disclosed": list(self.disclosed),
            "undisclosed": list(self.undisclosed),
            "core_gaps": list(self.core_gaps),
            "n_disclosed": self.n_disclosed,
            "n_items": self.n_items,
            "checklist": list(self.checklist),
            "question": self.question,
            "notes": list(self.notes),
            "meets_floor": self.meets_floor,
            "method": self.method,
            "caveat": self.caveat,
        }


def _present(value) -> bool:
    """A disclosure is PRESENT when the caller supplied a non-empty, non-null value. The
    VALUE's quality is never judged (0 or a huge n are both 'disclosed')."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    if isinstance(value, bool):
        return value  # an explicit False means "not disclosed / not applicable"
    return True  # a number (incl. 0), or any other supplied value


def assess_poll_transparency(fields: dict | None) -> PollTransparency:
    """Build the transparency checklist from a poll's disclosed ``fields``.

    ``fields`` maps a disclosure key (see CORE_ITEMS / SUPPLEMENTARY_ITEMS) to its value; a
    key that is absent, None, or empty is treated as NOT disclosed. Presence only -- the
    value's quality is never judged. Returns a :class:`PollTransparency` (counts + a
    checklist, never a score). A couple of purely FACTUAL disclosure-gap notes are added
    (e.g. a margin is claimed but n is not disclosed, so the margin can't be checked) --
    these are gaps in the disclosure, not quality judgments.
    """
    f = dict(fields or {})
    checklist: list[dict] = []
    disclosed: list[str] = []
    undisclosed: list[str] = []
    core_gaps: list[str] = []

    for tier, items in (("core", CORE_ITEMS), ("supplementary", SUPPLEMENTARY_ITEMS)):
        for key, label, why in items:
            is_disc = _present(f.get(key))
            checklist.append({
                "key": key,
                "label": label,
                "why": why,
                "tier": tier,
                "disclosed": is_disc,
                # A factual note ONLY about the disclosure gap, never the value.
                "note": None if is_disc else "not disclosed",
            })
            (disclosed if is_disc else undisclosed).append(key)
            if not is_disc and tier == "core":
                core_gaps.append(key)

    notes: list[str] = []
    # Factual cross-checks about the DISCLOSURE (not the value's quality):
    if _present(f.get("margin_of_error")) and not _present(f.get("sample_size")):
        notes.append(
            "A margin of error is stated but the sample size is not disclosed, so the margin "
            "cannot be independently checked."
        )
    if _present(f.get("margin_of_error")) and not _present(f.get("sampling_method")):
        notes.append(
            "A margin of error is stated but the sampling method is not disclosed — a classical "
            "margin of error assumes probability sampling, which is not confirmed here."
        )
    if not _present(f.get("population")):
        notes.append("Who was sampled (the population/frame) is not stated, so it is unclear "
                     "who the result speaks for.")
    if _present(f.get("question_wording")):
        notes.append(_QUESTION_CAVEAT)

    core_n = len(CORE_ITEMS)
    return PollTransparency(
        disclosed=tuple(disclosed),
        undisclosed=tuple(undisclosed),
        core_gaps=tuple(core_gaps),
        n_disclosed=len(disclosed),
        n_items=len(CORE_ITEMS) + len(SUPPLEMENTARY_ITEMS),
        checklist=tuple(checklist),
        question=(f.get("question_wording") or None) if _present(f.get("question_wording")) else None,
        notes=tuple(notes),
        meets_floor=len(core_gaps) == 0 and core_n > 0,
        method=_METHOD,
        caveat=_CAVEAT,
    )


# Enforce the no-composite-score ban on the dataclass field names at import time (same
# guard as Card/Envelope) -- a contributor who added a "...score" field would fail here.
assert_no_score_fields(PollTransparency)
