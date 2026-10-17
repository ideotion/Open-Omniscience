"""A new feed of an outlet starts from the outlet's DISQUALIFICATION, and from nothing else (R145 (2), R153, row J, S05-10 J3).

Keying a source on ``(domain, feed)`` makes a second feed of an outlet a NEW row. If any measured feed of the outlet is
``disqualified`` on this install, that verdict is handed to the new sibling: a known-bad outlet is not re-trialled
feed by feed, and a feed the catalogue adds later must not slip past a disqualification the operator's own
measurement reached. The copy is recorded for what it is -- an ``inherited`` attempt and an admission-audit row (the
same two the shipped overlay writes), never a ``disqualified`` attempt this install did not measure -- so the
re-verification clock and the undo behave as they do for any adopted stamp.

NOTHING IS HANDED ON IN THE QUALIFIED DIRECTION (R153, Q44 = A). A qualified outlet says nothing about a feed it has not
fetched: the new feed gets its own trial, like any unjudged source. (Until 2026-10-17 a measured ``qualified`` was copied
too, which put an untested feed into collection on a sibling's word.) The restore merge applies the same rule to a
backup's unmatched feed (``src.backup.merge._plan_sibling_feeds``), so two paths cannot disagree about it.

A catalogue-curated stamp (``CURATED_CRITERIA_VERSION``) is a fact about a row's PROVENANCE and was never a verdict; it is
not a candidate here at all now that only ``disqualified`` travels. A sibling that already holds any verdict keeps it
(local wins, both ways).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    log_inherited_stamps,
    record_admission,
)
from src.database.models import Source


def inherit_sibling_verdicts(session: Session, created: list[Source], *, now: datetime | None = None) -> dict:
    """Hand the outlet's disqualification to each of ``created`` that reads ``unqualified``. Returns the tally.

    ``left_to_own_trial`` counts the new siblings whose outlet holds a measured ``qualified`` and no disqualification:
    nothing is handed on, and the number says how many feeds start from a trial of their own."""
    if not created:
        return {"inherited": 0, "disqualified": 0, "left_to_own_trial": 0}
    now = now or datetime.now(UTC)
    domains = sorted({r.domain for r in created if r.domain})
    disqualified: dict[str, list[Source]] = {}
    qualified_domains: set[str] = set()
    for row in (
        session.query(Source)
        .filter(Source.domain.in_(domains), Source.status.in_((STATUS_QUALIFIED, STATUS_DISQUALIFIED)))
        .order_by(Source.id)
    ):
        if row.status == STATUS_DISQUALIFIED:
            disqualified.setdefault(row.domain, []).append(row)
        else:
            qualified_domains.add(row.domain)
    left_alone = 0
    inherited: list[Source] = []
    for row in created:
        if (row.status or STATUS_UNQUALIFIED) != STATUS_UNQUALIFIED:
            continue
        # THE STRICTER VERDICT WINS (R150): any measured disqualified feed of the outlet decides, the oldest of them.
        src = next((r for r in disqualified.get(row.domain, []) if r.id < row.id), None)
        if src is None:
            if row.domain in qualified_domains:
                left_alone += 1
            continue
        prior_enabled, prior_status = row.enabled, row.status
        row.status = STATUS_DISQUALIFIED
        row.qualified_at = None
        row.qualification_criteria_version = None
        record_admission(
            session, row, prior_enabled=prior_enabled, prior_status=prior_status, now=now,
            verdict=VERDICT_INHERITED, criteria_version=src.qualification_criteria_version or "",
        )
        inherited.append(row)
    if inherited:
        log_inherited_stamps(session, inherited, now=now)
        session.commit()
    return {"inherited": len(inherited), "disqualified": len(inherited), "left_to_own_trial": left_alone}
