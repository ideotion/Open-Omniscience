"""Did a verdict survive? — the 0.4 Row A closing clause, as a number rather than a memory.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK. ``docs/product/RELEASE_0.4_GATE.md`` Row A closes on a committed import at scale
"**and a spot-check confirms a previously-disqualified source is still disqualified
afterwards**", with the reason spelled out: "a pass that only counts ``qualified`` rows
cannot see the inversion this row exists to catch." Row E adds that the spot-check needs
tooling, because on an instance with tens of thousands of sources a check performed by hand
"is exactly the shape of check that gets reported as done without being done."

WHY IT NEEDS TO EXIST AT ALL. On 2026-07-24 ``_merge_sources``' explicit column allowlist
dropped the three qualification-stamp columns, so a merged-in source arrived carrying
``Source.status``' ``server_default='unqualified'``. That is a plausible legal value -- not
a NULL, not an error, nothing missing in a spot check -- and ``select_unqualified`` matches
exactly ``'unqualified'``, so a source another instance had DISQUALIFIED was laundered back
into the trial queue with its backoff ladder reset. Invisible at every layer above the
INSERT. It is fixed and unit-covered; what Row A wants is the field proof.

THE DESIGN POINT, and it is what makes this checkable AFTER THE FACT rather than only
during a carefully-instrumented import: **the attempt log is the "before".**
``source_qualification_attempts`` is append-only (the vintage convention), it is merged by
``_merge_source_qualification_attempts`` with ids remapped, and ``evaluate_and_stamp``
writes the attempt row and ``Source.status`` in the SAME transaction. So for any source that
has ever been judged, the two must agree:

    status == the verdict of its NEWEST judging attempt

A violation is the inversion, and no before/after snapshot is required to see it -- which
means an operator who has already run the import can still answer Row A's clause, months
later, from the corpus itself.

BOTH DIRECTIONS ARE COUNTED, AND KEPT APART. "Judged disqualified, no longer disqualified"
is the LAUNDERING direction Row A names -- a known-bad source back in the queue. "Judged
qualified, no longer qualified" is the same stamp loss pointing the other way -- a source
starved out of collection until it is re-trialled over the network. They are different
facts with different costs, so a single "inconsistent: 4" would tell a reader neither.

WHAT IT CANNOT SEE, stated rather than implied. If a regression dropped the stamp columns
*and* the attempt rows together, the receiving instance holds no "before" either, and this
check has nothing to compare against -- it would report zero inversions over a corpus it
could not examine. That is why ``checked.with_judging_attempt`` is published beside the
verdict and why the report refuses to call an unexaminable corpus clean: a rate whose
denominator is unstated is unreadable, and "nothing wrong" and "nothing to look at" are
opposite findings.

Read-only. Counts and names only -- never a score, never a percentage of anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from src.catalog.qualification import (
    JUDGING_VERDICTS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SCHEMA = "oo-qualification-integrity-1"

# A bounded sample of the sources this check EXAMINED and found sound -- Row E asks the
# tooling to "name the sources verified", and a count alone names nobody. The inversions
# themselves are named up to NAME_CAP, with the exact total stated beside the list so a
# truncation is never silent.
VERIFIED_SAMPLE = 25
NAME_CAP = 200


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _newest_judging(session: Session, source_id: int):
    """The one attempt that decides what this source was last JUDGED to be.

    Ordered ``(attempted_at DESC, id DESC)``: a batch stamps every source in it with the
    same ``now``, so two judging attempts for one source CAN share a timestamp, and a merge
    assigns local ids in merge order rather than time order -- so neither field alone is a
    deterministic "newest". Time decides first; the append order breaks the tie.
    """
    from src.database.models import SourceQualificationAttempt as A

    return (
        session.query(A)
        .filter(A.source_id == source_id, A.verdict.in_(JUDGING_VERDICTS))
        .order_by(A.attempted_at.desc(), A.id.desc())
        .first()
    )


def qualification_integrity_report(
    session: Session, *, verified_sample: int = VERIFIED_SAMPLE
) -> dict[str, Any]:
    """Does every judged source still carry the verdict its history recorded?"""
    from src.database.models import Source
    from src.database.models import SourceQualificationAttempt as A

    sources_total = int(session.query(func.count(Source.id)).scalar() or 0)
    judged_ids = {
        int(sid)
        for (sid,) in session.query(A.source_id)
        .filter(A.verdict.in_(JUDGING_VERDICTS))
        .distinct()
    }
    with_attempt = len(judged_ids)

    by_status = {
        str(status): int(n)
        for status, n in session.query(Source.status, func.count(Source.id))
        .group_by(Source.status)
        .all()
    }

    # CANDIDATES first, then an exact re-check. The grouped MAX() cannot break a
    # same-timestamp tie on its own, so a source whose tied rows disagree would be
    # reported on the strength of whichever row the join happened to return. The
    # candidate set is the finding set -- small by construction on a healthy corpus --
    # so re-reading each one's true newest attempt costs nothing and makes the answer
    # exact rather than probable.
    newest_at = (
        session.query(
            A.source_id.label("source_id"),
            func.max(A.attempted_at).label("last_at"),
        )
        .filter(A.verdict.in_(JUDGING_VERDICTS))
        .group_by(A.source_id)
        .subquery()
    )
    candidates = (
        session.query(Source.id)
        .join(newest_at, newest_at.c.source_id == Source.id)
        .join(
            A,
            (A.source_id == Source.id) & (A.attempted_at == newest_at.c.last_at),
        )
        .filter(A.verdict.in_(JUDGING_VERDICTS), Source.status != A.verdict)
        .distinct()
        .all()
    )

    laundered: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    n_laundered = n_demoted = n_other = 0
    resolved_by_tie = 0
    for (sid,) in candidates:
        attempt = _newest_judging(session, int(sid))
        source = session.get(Source, int(sid))
        if attempt is None or source is None:  # pragma: no cover - defensive
            continue
        if (source.status or "") == attempt.verdict:
            # A tie the grouped query surfaced and the exact re-read cleared. Counted,
            # never dropped in silence: a corpus that produces many of these is telling
            # us something about how its attempts were written.
            resolved_by_tie += 1
            continue
        row = {
            "domain": source.domain,
            "live_status": source.status,
            "last_judged": attempt.verdict,
            "judged_at": _iso(attempt.attempted_at),
            "criteria_version": attempt.criteria_version,
        }
        if attempt.verdict == STATUS_DISQUALIFIED:
            n_laundered += 1
            if len(laundered) < NAME_CAP:
                laundered.append(row)
        elif attempt.verdict == STATUS_QUALIFIED:
            n_demoted += 1
            if len(demoted) < NAME_CAP:
                demoted.append(row)
        else:  # pragma: no cover - JUDGING_VERDICTS has exactly two members today
            n_other += 1
            if len(other) < NAME_CAP:
                other.append(row)

    inversions_total = n_laundered + n_demoted + n_other
    consistent = with_attempt - inversions_total

    # Name the sources actually EXAMINED, not only count them (Row E). The disqualified
    # ones lead: they are the population Row A's clause is about, and seeing them by name
    # is what turns "the spot-check passed" into something a reader can re-open.
    verified_disqualified = [
        d
        for (d,) in session.query(Source.domain)
        .filter(Source.status == STATUS_DISQUALIFIED, Source.id.in_(judged_ids))
        .order_by(Source.domain.asc())
        .limit(max(0, verified_sample))
        .all()
    ] if judged_ids else []
    n_verified_disqualified = (
        int(
            session.query(func.count(Source.id))
            .filter(Source.status == STATUS_DISQUALIFIED, Source.id.in_(judged_ids))
            .scalar()
            or 0
        )
        if judged_ids
        else 0
    )

    if with_attempt == 0:
        verdict = "not-measurable-here"
        reason = (
            "No source in this corpus carries a qualification judgement, so there is "
            "nothing to check a live status against. This is not a pass: it is the "
            "absence of the evidence the check reads."
        )
    elif inversions_total == 0:
        verdict = "consistent"
        reason = (
            f"Every one of the {with_attempt} judged sources still carries the verdict "
            "its own attempt history last recorded."
        )
    else:
        verdict = "inversions-found"
        reason = (
            f"{inversions_total} of {with_attempt} judged sources no longer carry the "
            f"verdict their history recorded ({n_laundered} previously disqualified, "
            f"{n_demoted} previously qualified)."
        )

    return {
        "schema": SCHEMA,
        "generated_at": _iso(datetime.now(UTC)),
        "verdict": verdict,
        "reason": reason,
        "checked": {
            "sources_total": sources_total,
            # THE DENOMINATOR. Zero inversions over zero judged sources is not a clean
            # bill of health, and this is the number that says which one you are reading.
            "with_judging_attempt": with_attempt,
            "without_judging_attempt": sources_total - with_attempt,
            "live_status_counts": by_status,
            "currently_disqualified_and_judged": n_verified_disqualified,
            "verified_disqualified_sample": verified_disqualified,
            "verified_disqualified_sample_cap": max(0, verified_sample),
        },
        "consistent": consistent,
        "inversions_total": inversions_total,
        # THE DIRECTION ROW A NAMES: judged disqualified, no longer disqualified -- a
        # known-bad source back in the trial queue with its backoff ladder reset.
        "laundered_total": n_laundered,
        "laundered": laundered,
        # The same stamp loss pointing the other way: judged qualified, no longer
        # qualified -- starved out of collection until re-trialled over the network.
        "demoted_total": n_demoted,
        "demoted": demoted,
        "other_total": n_other,
        "other": other,
        "names_cap": NAME_CAP,
        "ties_resolved_by_append_order": resolved_by_tie,
        "method": (
            "For every source with at least one judging attempt (qualified|disqualified) "
            "in source_qualification_attempts, compare Source.status against the verdict "
            "of its newest such attempt, ordered by (attempted_at, id). evaluate_and_stamp "
            "writes both in one transaction, so they can only disagree if something later "
            "changed one without the other. Counts and names only; no score."
        ),
        "caveat": (
            "The attempt log is what stands in for a before-snapshot, so this can be run "
            "after an import rather than around one. It cannot see a regression that "
            "dropped the stamp AND the attempt rows together: on such an instance there "
            "is no history left to compare against, and with_judging_attempt is the "
            "number that shows it. A source promoted by the pre-2026-07 boot self-heal "
            "(status set from its collected articles, no attempt written) is outside this "
            "check by construction -- it was never judged, so there is no verdict to lose."
        ),
    }


def repair_inversions(session: Session, *, dry_run: bool = True) -> dict[str, Any]:
    """Reconcile every inversion :func:`qualification_integrity_report` finds: for a
    source whose ``Source.status`` no longer agrees with its own newest JUDGING attempt,
    restore ``status`` (+ the stamp columns) to what that history recorded.

    THIS RE-DERIVES THE FINDING FROM THE SAME QUERY THE CHECKER USES, never a cached or
    re-implemented one -- it runs the identical candidate join (``func.max(attempted_at)``
    grouped by source, JUDGING_VERDICTS only) and the identical exact re-read
    (``_newest_judging``, ordered ``attempted_at DESC, id DESC``) that
    ``qualification_integrity_report`` runs, so "what this repairs" and "what that report
    counts" can never silently drift apart.

    THIS WRITES NO NEW ``SourceQualificationAttempt`` ROW. It reconciles EXISTING history
    -- it does not make a fresh judgement, and the append-only attempt log is untouched.
    The stamp mirrors ``evaluate_and_stamp``'s own rule exactly: a row restored to
    'disqualified' carries no ``qualified_at``/``qualification_criteria_version``; a row
    restored to 'qualified' carries the ATTEMPT's own ``attempted_at``/``criteria_version``,
    never "now" -- restoring a stale verdict must never make it read as freshly re-checked.

    ``dry_run=True`` (the default) computes and RETURNS the exact tally without writing
    anything -- ``Source`` objects are left untouched and nothing is flushed. Passing
    ``dry_run=False`` applies the reconciliation to the given ``session`` (flushed, not
    committed -- the caller controls the transaction, exactly like ``evaluate_and_stamp``).

    THIS FUNCTION MUST NEVER BE CALLED FROM AN AUTOMATIC PATH (boot, the scheduler, or any
    code that runs without an operator's own say-so). Re-admitting a potentially large
    population of sources into live collection at once is a real behaviour change --
    bandwidth, per-host politeness, and the operator's own expectations of what is being
    collected -- and it is the maintainer's call, never this code's. The only sanctioned
    entry point is ``scripts/repair_qualification_inversions.py``, an operator-run CLI
    that defaults to a dry run and requires an explicit ``--apply`` to write.

    Both directions are reconciled, and named apart, for the same reason the report keeps
    them apart: restoring a recorded ``disqualified`` (a known-bad source that was
    laundered back into the trial queue) matters as much as restoring a ``qualified`` (a
    source starved out of collection) -- treating this as qualified-only would launder
    known-bad sources back into the trial queue on every run.
    """
    from src.database.models import Source
    from src.database.models import SourceQualificationAttempt as A

    newest_at = (
        session.query(
            A.source_id.label("source_id"),
            func.max(A.attempted_at).label("last_at"),
        )
        .filter(A.verdict.in_(JUDGING_VERDICTS))
        .group_by(A.source_id)
        .subquery()
    )
    candidates = (
        session.query(Source.id)
        .join(newest_at, newest_at.c.source_id == Source.id)
        .join(
            A,
            (A.source_id == Source.id) & (A.attempted_at == newest_at.c.last_at),
        )
        .filter(A.verdict.in_(JUDGING_VERDICTS), Source.status != A.verdict)
        .distinct()
        .all()
    )

    restored_to_qualified: list[dict[str, Any]] = []
    restored_to_disqualified: list[dict[str, Any]] = []
    n_restored_to_qualified = n_restored_to_disqualified = 0
    resolved_by_tie = 0
    for (sid,) in candidates:
        attempt = _newest_judging(session, int(sid))
        source = session.get(Source, int(sid))
        if attempt is None or source is None:  # pragma: no cover - defensive
            continue
        if (source.status or "") == attempt.verdict:
            # Same tie the grouped candidate query cannot break on its own; the exact
            # re-read cleared it -- nothing to repair here, exactly as the report treats it.
            resolved_by_tie += 1
            continue
        row = {
            "domain": source.domain,
            "was": source.status,
            "restored_to": attempt.verdict,
            "judged_at": _iso(attempt.attempted_at),
            "criteria_version": attempt.criteria_version,
        }
        if attempt.verdict == STATUS_QUALIFIED:
            n_restored_to_qualified += 1
            if len(restored_to_qualified) < NAME_CAP:
                restored_to_qualified.append(row)
        elif attempt.verdict == STATUS_DISQUALIFIED:
            n_restored_to_disqualified += 1
            if len(restored_to_disqualified) < NAME_CAP:
                restored_to_disqualified.append(row)
        else:  # pragma: no cover - JUDGING_VERDICTS has exactly two members today
            continue
        if not dry_run:
            source.status = attempt.verdict
            if attempt.verdict == STATUS_QUALIFIED:
                source.qualified_at = attempt.attempted_at
                source.qualification_criteria_version = attempt.criteria_version
            else:
                source.qualified_at = None
                source.qualification_criteria_version = None

    if not dry_run and (restored_to_qualified or restored_to_disqualified):
        session.flush()

    total = n_restored_to_qualified + n_restored_to_disqualified
    return {
        "schema": SCHEMA,
        "generated_at": _iso(datetime.now(UTC)),
        "dry_run": dry_run,
        "applied": (not dry_run) and total > 0,
        "reconciled_total": total,
        # THE LAUNDERING DIRECTION: restored to 'disqualified' -- a known-bad source that
        # had been laundered back into the trial queue is pulled back out.
        "restored_to_disqualified_total": n_restored_to_disqualified,
        "restored_to_disqualified": restored_to_disqualified,
        # THE DEMOTION DIRECTION: restored to 'qualified' -- a source starved out of live
        # collection (the 2026-09-11 field finding's own signature) is re-admitted.
        "restored_to_qualified_total": n_restored_to_qualified,
        "restored_to_qualified": restored_to_qualified,
        "names_cap": NAME_CAP,
        "ties_resolved_by_append_order": resolved_by_tie,
        "method": (
            "Re-runs qualification_integrity_report's own candidate join (newest judging "
            "attempt per source, JUDGING_VERDICTS only, exact re-read on "
            "attempted_at DESC, id DESC to break a same-timestamp tie) and, unless "
            "dry_run, sets Source.status (+ qualified_at/qualification_criteria_version, "
            "mirroring evaluate_and_stamp's own stamp rule) to the verdict of that "
            "attempt. Writes NO new SourceQualificationAttempt row -- this reconciles "
            "existing history, it does not judge anything fresh."
        ),
        "caveat": (
            "Only reconciles a source this instance's OWN history has a judging verdict "
            "for -- a source with no judging attempt on record is outside this repair by "
            "construction (see qualification_integrity_report's own caveat). "
            "dry_run=True changes nothing; run scripts/repair_qualification_inversions.py "
            "--apply to actually write the reconciliation -- never call this with "
            "dry_run=False from an automatic path."
        ),
    }
