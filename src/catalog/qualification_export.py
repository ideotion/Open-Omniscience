"""
REMEMBER what this instance qualified -- the export half of the accumulation loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-09-04): "a tool to allow us to remember qualified sources so that
the initial list of sources ... is updated to include only qualified sources, and the rest
... added to the list of sources that aren't yet qualified ... so that any newly fresh
install comprises a list of app-qualified sources to begin with."

This reads a live corpus and emits the overlay ``src.catalog.qualification_overlay`` consumes
(``configs/source_qualification.yml``), plus the SPLIT the ask asks to see: of the sources
that shipped with the app, how many are qualified, how many disqualified, how many still
awaiting a verdict. The round trip is real -- the same schema out as in -- so what an
instance exports is exactly what the next fresh install adopts.

FOUR THINGS IT REFUSES TO BLUR, each of which a single number would hide:

  * SCOPE. Only APP-PROVIDED sources are exported (``catalog.provenance_scope``, reused
    rather than re-derived -- its docstring documents the via:wikidata /
    via:wikidata-discovery trap that makes the naive version silently wrong). A verdict for
    a domain no shipped catalog contains would adopt onto nothing on a fresh install, so
    shipping it is dead weight; the count excluded for that reason is REPORTED, never
    silently dropped.

  * BASIS. Each verdict says whether this instance MEASURED it or INHERITED it (from a
    backup or an earlier overlay). Without that, two instances "agreeing" about a domain
    one of them merely copied from the other reads as independent corroboration -- the
    anti-false-triangulation rule the project already applies to article sources, applied
    to its own verdicts.

  * AGE. ``qualified_at`` travels as reached, never as exported. Re-stamping it would
    restart the re-verification clock on every accumulation run, so a verdict would never
    grow old enough to be re-checked -- an expiry that can never fire.

  * WHAT IS NOT YET JUDGED. The pending count is a first-class figure beside the verdicts,
    because "3,600 sources, 900 qualified" and "3,600 sources, 900 qualified and 2,700 still
    unexamined" are different states of the world and the verdict list alone shows only one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func

from src.catalog.provenance_scope import app_provided_filter
from src.catalog.qualification import (
    CRITERIA_VERSION,
    JUDGING_VERDICTS,
    QUALIFIED_RECHECK_MONTHS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    qualified_recheck_due_at,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# A bounded sample of the not-yet-judged domains, so the report SHOWS the pending list
# rather than only counting it -- without embedding tens of thousands of rows in a
# diagnostic that has to stay readable.
PENDING_SAMPLE = 50

BASIS_MEASURED = "measured"
BASIS_INHERITED = "inherited"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _locally_measured_ids(session: Session) -> set[int]:
    """Sources this instance actually JUDGED at some point -- an attempt row whose verdict
    is a real judgement. ``inherited`` and ``no_evidence`` rows are excluded because neither
    is this instance measuring anything."""
    from src.database.models import SourceQualificationAttempt as A

    return {
        int(sid)
        for (sid,) in session.query(A.source_id)
        .filter(A.verdict.in_(JUDGING_VERDICTS))
        .distinct()
    }


def build_overlay_export(session: Session, *, now: datetime | None = None) -> dict:
    """The exportable record of what this instance knows about its shipped sources."""
    from src.database.models import Source

    now = now or datetime.now(UTC)
    measured = _locally_measured_ids(session)

    app_only = app_provided_filter(Source.tags)
    judged = (
        session.query(Source)
        .filter(app_only, Source.status.in_((STATUS_QUALIFIED, STATUS_DISQUALIFIED)))
        .order_by(Source.domain.asc())
        .all()
    )

    verdicts = []
    stamp_dates: list[datetime] = []
    past_recheck = 0
    basis_counts = {BASIS_MEASURED: 0, BASIS_INHERITED: 0}
    status_counts = {STATUS_QUALIFIED: 0, STATUS_DISQUALIFIED: 0}
    for s in judged:
        basis = BASIS_MEASURED if s.id in measured else BASIS_INHERITED
        basis_counts[basis] += 1
        status_counts[s.status] += 1
        if s.qualified_at is not None:
            stamped = s.qualified_at
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=UTC)
            stamp_dates.append(stamped)
            if qualified_recheck_due_at(stamped) <= now:
                past_recheck += 1
        verdicts.append({
            "domain": s.domain,
            "status": s.status,
            # As REACHED, never as exported -- see the module docstring.
            "qualified_at": _iso(s.qualified_at),
            "criteria_version": s.qualification_criteria_version or CRITERIA_VERSION,
            "basis": basis,
        })

    pending_q = (
        session.query(Source)
        .filter(app_only, Source.status == STATUS_UNQUALIFIED)
        .order_by(Source.domain.asc())
    )
    pending_total = pending_q.count()

    # Judged sources this instance found for ITSELF. Counted rather than exported: a fresh
    # install has no such row for the verdict to land on. Reported so the difference between
    # "we judged 900" and "we are shipping 900" is visible.
    out_of_scope = (
        session.query(func.count(Source.id))
        .filter(~app_only, Source.status.in_((STATUS_QUALIFIED, STATUS_DISQUALIFIED)))
        .scalar()
    ) or 0

    app_total = session.query(func.count(Source.id)).filter(app_only).scalar() or 0

    return {
        "generated_at": now.isoformat(),
        "criteria_version": CRITERIA_VERSION,
        "scope": {
            "app_provided_sources": int(app_total),
            "note": (
                "Only sources that SHIPPED with the app are exported: a verdict for a domain "
                "no shipped catalog contains would adopt onto nothing on a fresh install."
            ),
            "judged_but_not_app_provided": int(out_of_scope),
        },
        # THE SPLIT the ask asks to see. `pending` is the second of the two lists -- the
        # sources that are not yet qualified and should be -- and it is a real figure here
        # rather than an absence the reader has to infer from the verdict list's length.
        "split": {
            "qualified": status_counts[STATUS_QUALIFIED],
            "disqualified": status_counts[STATUS_DISQUALIFIED],
            "pending": int(pending_total),
            "total": int(app_total),
        },
        # AGE OF THE VERDICTS. A fresh install defers its first local re-verification by a
        # full QUALIFIED_RECHECK_MONTHS from the day it ADOPTS a shipped stamp, which is what
        # keeps a first download quiet -- so the freshness of the shipped catalog is no longer
        # something each install re-establishes for itself. It is re-established when the
        # maintainer re-cuts the overlay, and this block is how they see that it is time:
        # `past_recheck_interval` is the number of exported verdicts already older than the
        # interval. Dates are the ones the verdicts were REACHED on, never today's.
        "verdict_age": {
            "oldest": _iso(min(stamp_dates)) if stamp_dates else None,
            "newest": _iso(max(stamp_dates)) if stamp_dates else None,
            "past_recheck_interval": past_recheck,
            "dated": len(stamp_dates),
            "recheck_months": QUALIFIED_RECHECK_MONTHS,
            "note": (
                "Counted over verdicts carrying a date (a disqualified row carries none by "
                "design). A high past_recheck_interval means the shipped catalog is due to be "
                "re-cut from fresh instance exports -- installs adopting it will not "
                "re-verify it for themselves until their own interval elapses."
            ),
        },
        "basis": {
            **basis_counts,
            "note": (
                "'measured' means this instance judged the source itself; 'inherited' means "
                "it adopted the verdict from a backup or an earlier overlay. Two instances "
                "agreeing about an inherited verdict is one measurement seen twice, not two."
            ),
        },
        "pending_sample": [s.domain for s in pending_q.limit(PENDING_SAMPLE).all()],
        "pending_sample_note": (
            f"first {PENDING_SAMPLE} by domain of {pending_total}"
            if pending_total > PENDING_SAMPLE
            else "complete"
        ),
        "verdicts": verdicts,
    }


def to_overlay_yaml(export: dict) -> str:
    """Render an export as the overlay file the seeder reads.

    ``basis`` is carried through: it is not consumed by ``load_overlay`` (which ignores
    unknown keys), but it is what a human merging several instances' exports needs in order
    to tell corroboration from an echo.
    """
    import yaml

    doc = {
        "generated_at": export["generated_at"],
        "criteria_version": export["criteria_version"],
        "verdicts": export["verdicts"],
    }
    header = (
        "# Source qualification verdicts, EARNED BY MEASUREMENT on real instances.\n"
        "# Generated by GET /api/diagnostics/source-qualification-export -- do not hand-edit;\n"
        "# merge additional instances' exports with scripts/merge_source_qualification.py.\n"
        "# A domain absent from this file ships unqualified and is judged by the install's\n"
        "# own first qualification pass, exactly as before this file existed.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
