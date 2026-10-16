"""A new feed of an outlet starts from the outlet's verdict (R145 (2), row J, S05-10 J3).

Keying a source on ``(domain, feed)`` makes a second feed of an outlet a NEW row. The outlet's existing row may already
carry a verdict this install reached, and a migration changes no verdict: a measured ``qualified`` or ``disqualified``
on the outlet's oldest row is copied onto each sibling the seeder creates. The copy is recorded for what it is -- an
``inherited`` attempt and an admission-audit row (the same two the shipped overlay writes), never a ``qualified``
attempt this install did not measure -- so the re-verification clock and the undo behave as they do for any adopted stamp.

What is NOT copied: a stamp the curated catalogue carries by ruling (``CURATED_CRITERIA_VERSION``). That one is a fact
about a row's PROVENANCE, applied by ``stamp_curated_catalog`` to the rows that have it; copying it would make a
spectrum-catalogue feed read as hand-vetted. A sibling that already holds any verdict keeps it (local wins, both ways).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.catalog.qualification import (
    CURATED_CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    log_inherited_stamps,
    record_admission,
)
from src.database.models import Source


def inherit_sibling_verdicts(session: Session, created: list[Source], *, now: datetime | None = None) -> dict:
    """Copy the outlet's measured verdict onto each of ``created`` that reads ``unqualified``. Returns the tally."""
    if not created:
        return {"inherited": 0, "qualified": 0, "disqualified": 0, "skipped_curated_stamp": 0}
    now = now or datetime.now(UTC)
    domains = sorted({r.domain for r in created if r.domain})
    measured: dict[str, list[Source]] = {}
    curated_domains: set[str] = set()
    for row in (
        session.query(Source)
        .filter(Source.domain.in_(domains), Source.status.in_((STATUS_QUALIFIED, STATUS_DISQUALIFIED)))
        .order_by(Source.id)
    ):
        # A catalogue-curated stamp is provenance, not a verdict: it is not a candidate, and it does not hide a MEASURED
        # verdict on a later row of the outlet (the restore merge reads it the same way, R148).
        if row.status == STATUS_QUALIFIED and row.qualification_criteria_version == CURATED_CRITERIA_VERSION:
            curated_domains.add(row.domain)
            continue
        measured.setdefault(row.domain, []).append(row)
    skipped_curated = 0
    inherited: list[Source] = []
    counts = {STATUS_QUALIFIED: 0, STATUS_DISQUALIFIED: 0}
    for row in created:
        if (row.status or STATUS_UNQUALIFIED) != STATUS_UNQUALIFIED:
            continue
        older = [r for r in measured.get(row.domain, []) if r.id < row.id]
        # THE STRICTER VERDICT WINS (R150, the same rule as a restored sibling): any measured disqualified feed of the
        # outlet decides; otherwise the oldest measured row does.
        src = next((r for r in older if r.status == STATUS_DISQUALIFIED), older[0] if older else None)
        if src is None:
            if row.domain in curated_domains:
                skipped_curated += 1
            continue
        prior_enabled, prior_status = row.enabled, row.status
        row.status = src.status
        if src.status == STATUS_QUALIFIED:
            row.qualified_at = src.qualified_at
            row.qualification_criteria_version = src.qualification_criteria_version
        else:
            row.qualified_at = None
            row.qualification_criteria_version = None
        record_admission(
            session, row, prior_enabled=prior_enabled, prior_status=prior_status, now=now,
            verdict=VERDICT_INHERITED, criteria_version=src.qualification_criteria_version or "",
        )
        counts[src.status] += 1
        inherited.append(row)
    if inherited:
        log_inherited_stamps(session, inherited, now=now)
        session.commit()
    return {
        "inherited": len(inherited), "qualified": counts[STATUS_QUALIFIED],
        "disqualified": counts[STATUS_DISQUALIFIED], "skipped_curated_stamp": skipped_curated,
    }
