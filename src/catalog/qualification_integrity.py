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

import contextlib
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from src.catalog.qualification import (
    JUDGING_VERDICTS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_LOG = logging.getLogger("catalog.qualification_integrity")

SCHEMA = "oo-qualification-integrity-1"

# A bounded sample of the sources this check EXAMINED and found sound -- Row E asks the
# tooling to "name the sources verified", and a count alone names nobody. The inversions
# themselves are named up to NAME_CAP, with the exact total stated beside the list so a
# truncation is never silent.
VERIFIED_SAMPLE = 25
NAME_CAP = 200

# THE REVERT RECORD of the automatic repair (see ``auto_repair_inversions``). It lives in the
# ``app_state`` key-value table -- no schema change -- as ONE INDEX KEY plus ONE KEY PER RUN, so no
# single value keeps growing and nothing is ever dropped: there is deliberately NO cap on how many
# repairs are remembered (the count is bounded by the number of sources anyway), because a capped
# revert record would silently make the oldest repairs irreversible, which is what a revert
# record exists to prevent. ``app_state`` is never merged on restore (it is in ``merge._MERGE_IGNORED``),
# so a record made on one machine can never be imported over another's; the attempt the repair
# FOLLOWS is ordinary corpus data and rides backups, so a restored copy still shows why a source
# is disqualified.
REPAIR_INDEX_KEY = "qualification.repairs"
REPAIR_RUN_PREFIX = "qualification.repairs.run."
# Set to 0 ONLY by the test conftest (the way OO_STORAGE_GUARD=0 is): the boot repair writes to
# the corpus, so a test that boots the app must not have it as a side effect.
AUTO_REPAIR_ENV = "OO_QUALIFICATION_AUTO_REPAIR"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def live_stamp_class(source) -> str:
    """What stands behind a row's LIVE verdict, by its stamp.

    ``none`` (status unqualified), ``catalogue`` (qualified with the shipped catalogue's own
    stamp: nothing was measured here, and a local pass that qualifies a row replaces that stamp
    with the real criteria version, see ``evaluate_and_stamp``), or ``measured`` (anything else:
    a verdict this instance's engine reached, or one adopted from an import). Only the first two
    are rows whose live verdict is not data this install produced, so only they may be changed
    without anyone's say-so (rule 12 = b); a ``measured`` row is reported and left for a local
    re-check.
    """
    from src.catalog.qualification import CURATED_CRITERIA_VERSION

    if (source.status or "") == STATUS_UNQUALIFIED:
        return "none"
    if (
        (source.status or "") == STATUS_QUALIFIED
        and (source.qualification_criteria_version or "") == CURATED_CRITERIA_VERSION
    ):
        return "catalogue"
    return "measured"


def _held_domains() -> set[str]:
    """Domains a maintainer reverted and held out of the boot repair (empty if unreadable)."""
    try:
        return set(_read_repair_index()["reverted_domains"])
    except Exception:  # noqa: BLE001 - a report must never fail for want of its side record
        return set()


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

    # WHEN THE ENGINE LAST SPOKE, and how much it did in the last day. A `with_judging_attempt`
    # of 2,088 proves nothing about this instance's own fleet: those rows can be copied in from
    # a backup (2026-09-30, the 16-instance diagnostics). ANY attempt row counts for the first
    # pair (no_evidence, inherited and curated included -- the engine ran), only a real judgement
    # for the second. Naive UTC, as every writer stores it.
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    last_attempt_at = session.query(func.max(A.attempted_at)).scalar()
    last_judging_at = (
        session.query(func.max(A.attempted_at)).filter(A.verdict.in_(JUDGING_VERDICTS)).scalar()
    )
    attempts_24h = int(
        session.query(func.count(A.id)).filter(A.attempted_at >= since).scalar() or 0
    )
    judging_24h = int(
        session.query(func.count(A.id))
        .filter(A.attempted_at >= since, A.verdict.in_(JUDGING_VERDICTS))
        .scalar()
        or 0
    )

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
    n_laundered = n_demoted = n_other = n_auto_repairable = n_kept_measured = n_held = 0
    held_domains = _held_domains()
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
            "live_stamp": live_stamp_class(source),
            "last_judged": attempt.verdict,
            "judged_at": _iso(attempt.attempted_at),
            "criteria_version": attempt.criteria_version,
        }
        if attempt.verdict == STATUS_DISQUALIFIED:
            n_laundered += 1
            if row["live_stamp"] == "measured":
                n_kept_measured += 1
            elif source.domain in held_domains:
                n_held += 1
            else:
                n_auto_repairable += 1
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
            "last_attempt_at": _iso(last_attempt_at),
            "last_judging_attempt_at": _iso(last_judging_at),
            "attempts_last_24h": attempts_24h,
            "judging_attempts_last_24h": judging_24h,
            "live_status_counts": by_status,
            "currently_disqualified_and_judged": n_verified_disqualified,
            "verified_disqualified_sample": verified_disqualified,
            "verified_disqualified_sample_cap": max(0, verified_sample),
        },
        "consistent": consistent,
        "inversions_total": inversions_total,
        # Of those, the ones the boot repair may withdraw by itself (judged disqualified, and the
        # live verdict is the catalogue's own stamp or nothing, and nobody reverted it). The REST
        # are left alone on purpose: a verdict measured here (or taken from an import) is data, and
        # an imported history never overrides it by itself (rule 12 = b).
        "auto_repairable_total": n_auto_repairable,
        # ...and the ones it does NOT change, by reason (they add up to inversions_total minus the
        # line above): a verdict measured here, a domain a maintainer reverted and held, and the
        # opposite direction (judged qualified, no longer qualified), which only an operator
        # restores.
        "not_auto_repaired_total": inversions_total - n_auto_repairable,
        "not_auto_repaired_measured_here_total": n_kept_measured,
        "not_auto_repaired_held_total": n_held,
        "not_auto_repaired_requalify_direction_total": n_demoted + n_other,
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
        # What the automatic repair (``auto_repair_inversions``) has done on this instance, read
        # from its own revert record: EVERY repair, never a capped sample.
        **repair_summary(),
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
            "number that shows it. The attempt timestamps (last_attempt_at, "
            "last_judging_attempt_at, the 24 h counts) cannot tell an attempt this instance's "
            "engine made from one copied in by an import: both carry the clock of the machine "
            "that wrote them. A source promoted by the pre-2026-07 boot self-heal "
            "(status set from its collected articles, no attempt written) is outside this "
            "check by construction -- it was never judged, so there is no verdict to lose."
        ),
    }


def repair_inversions(
    session: Session, *, dry_run: bool = True, only_to: str | None = None,
    skip_domains: frozenset[str] | set[str] = frozenset(), name_cap: int | None = NAME_CAP,
    only_source_ids: frozenset[int] | set[int] | None = None,
    only_without_own_verdict: bool = False,
) -> dict[str, Any]:
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

    WHICH DIRECTION MAY RUN BY ITSELF (amended 2026-09-30, diagnostics rank 14; the note that
    used to stand here, "never call from an automatic path", was a docstring from PR #1117
    and not a ruling). Restoring a recorded ``disqualified`` only ever WITHDRAWS a source from
    collection, so it cannot spend bandwidth or politeness the operator did not expect: that
    direction is what :func:`auto_repair_inversions` runs at boot, with a revert record.
    Restoring a recorded ``qualified`` RE-ADMITS sources into live collection, potentially a
    large population at once -- bandwidth, per-host politeness, the operator's own expectations
    -- so that direction stays operator-run, through
    ``scripts/repair_qualification_inversions.py`` (dry run by default, ``--apply`` to write).
    ``only_to`` selects a direction (``'disqualified'`` | ``'qualified'``); ``None`` does both.
    ``skip_domains`` are sources an operator deliberately reverted: they are never touched.
    ``name_cap`` bounds the NAMES in the returned lists (the counts are always exact); the
    automatic repair passes ``None`` because its revert record must name every source.
    ``only_source_ids`` limits the repair to exactly the sources a previous (dry-run) call
    planned, each re-checked against the live state, so what is recorded is what is applied.
    ``only_without_own_verdict`` keeps only rows whose live verdict is not data this install
    produced (live stamp ``none`` or ``catalogue``, see :func:`live_stamp_class`): the automatic
    repair passes it, because a verdict measured here is never changed by an imported history
    on its own (rule 12 = b); the operator script does not.

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
    held_by_revert = 0
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
        if only_to is not None and attempt.verdict != only_to:
            continue
        if source.domain in skip_domains:
            held_by_revert += 1
            continue
        if only_source_ids is not None and int(source.id) not in only_source_ids:
            continue
        if only_without_own_verdict and live_stamp_class(source) == "measured":
            continue
        row = {
            "domain": source.domain,
            "source_id": int(source.id),
            "was": source.status,
            # What a revert needs to put the row back EXACTLY: the stamp, not only the status.
            "was_qualified_at": _iso(source.qualified_at),
            "was_criteria_version": source.qualification_criteria_version,
            "restored_to": attempt.verdict,
            "judged_at": _iso(attempt.attempted_at),
            "criteria_version": attempt.criteria_version,
        }
        if attempt.verdict == STATUS_QUALIFIED:
            n_restored_to_qualified += 1
            if name_cap is None or len(restored_to_qualified) < name_cap:
                restored_to_qualified.append(row)
        elif attempt.verdict == STATUS_DISQUALIFIED:
            n_restored_to_disqualified += 1
            if name_cap is None or len(restored_to_disqualified) < name_cap:
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
        "names_cap": name_cap,
        "ties_resolved_by_append_order": resolved_by_tie,
        "held_by_operator_revert": held_by_revert,
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
            "dry_run=True changes nothing; the restore-to-disqualified direction runs at boot "
            "(auto_repair_inversions), the restore-to-qualified direction only when an "
            "operator runs scripts/repair_qualification_inversions.py --apply."
        ),
    }


# --------------------------------------------------------------------------- #
#  The automatic repair (the SAFE direction only) and its revert record
# --------------------------------------------------------------------------- #
def _read_repair_index(*, strict: bool = False) -> dict[str, Any]:
    """The index of repair runs and holds. ``strict`` raises when the store cannot be READ, so a
    caller that will rewrite it never mistakes an unreadable index for an empty one (which would
    drop every earlier run and every hold the next time it writes)."""
    from src.config.kv_store import kv_get_json, kv_get_json_strict

    raw = (kv_get_json_strict if strict else kv_get_json)(REPAIR_INDEX_KEY) or {}
    return {
        "runs": [str(r) for r in (raw.get("runs") or [])],
        "last_run_at": raw.get("last_run_at"),
        "reverted_domains": [str(d) for d in (raw.get("reverted_domains") or [])],
    }


def _write_repair_index(idx: dict[str, Any]) -> None:
    from src.config.kv_store import kv_set_json

    kv_set_json(REPAIR_INDEX_KEY, {
        "runs": idx["runs"], "last_run_at": idx["last_run_at"],
        "reverted_domains": idx["reverted_domains"],
    })


def repair_summary() -> dict[str, Any]:
    """What the automatic repair has done here, read from its own revert record.

    EVERY repair is listed -- never a capped sample (a cap would hide exactly the long tail an
    operator wants to audit; the list is bounded by the number of sources anyway). A run is
    INDEXED before its change is applied, so a crash can never leave a repair nobody can see:
    a run whose confirmation never landed is listed with ``confirmed: false`` and counted apart
    (``repairs_unconfirmed``) rather than in ``repaired_total``. Read-only, and it degrades to an
    empty, zero-count summary where the key-value store is unavailable.
    """
    from src.config.kv_store import kv_get_json, kv_invalidate

    try:
        # The maintainer's revert tool runs in ANOTHER process and writes these keys there, and
        # kv_store caches per process: forget them so a report never shows a repair that has
        # since been reverted. The report is a rare, read-only call, so the extra reads are cheap.
        kv_invalidate(REPAIR_INDEX_KEY)
        idx = _read_repair_index(strict=True)
        for _run_at in idx["runs"]:
            kv_invalidate(REPAIR_RUN_PREFIX + _run_at)
        repairs: list[dict[str, Any]] = []
        confirmed = unconfirmed = 0
        for run_at in idx["runs"]:
            run = kv_get_json(REPAIR_RUN_PREFIX + run_at) or {}
            done = bool(run.get("applied"))
            for r in run.get("repairs") or []:
                if done:
                    confirmed += 1
                else:
                    unconfirmed += 1
                repairs.append({
                    "domain": r.get("domain"),
                    "run_at": run_at,
                    "confirmed": done,
                    "was_status": r.get("was"),
                    "restored_to": r.get("restored_to"),
                    "judged_at": r.get("judged_at"),
                    "reverted_at": r.get("reverted_at"),
                })
        return {
            "repaired_total": confirmed,
            "repairs_unconfirmed": unconfirmed,
            "repair_runs": len(idx["runs"]),
            "last_repair_at": idx["last_run_at"],
            "repairs": repairs,
            "repairs_held_by_revert": idx["reverted_domains"],
            "repairs_note": (
                "Only the SAFE direction (restore to disqualified, a withdrawal from collection) "
                "runs by itself, and only for a source whose live verdict is the shipped "
                "catalogue's own stamp or nothing; each repair follows the newest judging attempt "
                "in this instance's own history, is listed here with the status it replaced, and "
                "can be reverted by the maintainer tool. A verdict measured here is never changed "
                "by an imported history on its own, and restoring to qualified is operator-run."
            ),
        }
    except Exception:  # noqa: BLE001 - a report must never fail for want of its side record
        return {
            "repaired_total": 0, "repairs_unconfirmed": 0, "repair_runs": 0,
            "last_repair_at": None, "repairs": [], "repairs_held_by_revert": [],
            "repairs_note": "the repair record could not be read on this instance",
        }


def auto_repair_inversions(*, now: datetime | None = None) -> dict[str, Any]:
    """The boot-time reconciliation: restore every source the integrity check finds LIVE-not-
    disqualified although its newest judging attempt says DISQUALIFIED, to disqualified.

    WHICH ROWS: only a source whose LIVE verdict is the shipped catalogue's own stamp or nothing
    (:func:`live_stamp_class`). A verdict measured here is data this install produced, and an
    imported history does not override it by itself (rule 12 = b, ruled for the restore merge);
    such rows stay in the integrity report (``not_auto_repaired_measured_here_total``) and are left to
    the install's own re-check. The field's own inversions (085639, 091717) are all catalogue-stamped.

    WHY THIS DIRECTION AND ONLY THIS ONE. It withdraws a known-bad source from collection, so
    it cannot spend bandwidth or politeness the operator did not expect; the opposite direction
    re-admits sources and stays operator-run (see :func:`repair_inversions`). It runs at
    deferred boot and touches the LOCAL database only, so airplane mode does not stop it.

    IT NEEDS NO NEW SCHEMA, and its ORDER is the point. (1) The plan is computed without
    writing. (2) The run is recorded AND INDEXED (``applied: false``) with the status and stamp
    each source is about to lose, BEFORE anything changes -- so no crash or failed write after the
    commit can leave a repair that nothing lists. (3) Exactly the planned sources are re-checked
    and changed, in one transaction. (4) The record is rewritten with what was really applied and
    marked ``applied: true``. A failure of step 4 leaves a listed, revertable run reported as
    unconfirmed; a failure of step 2 changes nothing. Nothing is capped. A source an operator has
    deliberately reverted is never repaired again.

    It runs at deferred boot, before the storage guard's supervisor starts, and does not consult
    the guard: its writes are a few kilobytes (one row update per source plus a few key writes),
    and on a full drive or a pinned WAL the write fails, which the boot wrapper logs and the next
    boot retries (the unconfirmed record is reconciled, see :func:`_confirm_applied_runs`).

    Returns counts only. A failure anywhere raises to the caller, which logs it: a repair that
    could not run must never block startup.
    """
    from src.config.kv_store import kv_get_json, kv_set_json
    from src.database.session import session_scope

    if os.getenv(AUTO_REPAIR_ENV, "1") == "0":
        return {"repaired": 0, "skipped": f"disabled by {AUTO_REPAIR_ENV}=0"}
    now = now or datetime.now(UTC)
    # FAIL CLOSED: if the index cannot be read, repair nothing this boot. Reading it as empty and
    # writing the new run would replace the stored index and lose every earlier run (so they could
    # no longer be reverted) and every hold a maintainer set.
    try:
        idx = _read_repair_index(strict=True)
    except Exception:  # noqa: BLE001 - reported, never raised: a repair that cannot run is skipped
        _LOG.warning("qualification repair skipped: its revert index cannot be read", exc_info=True)
        return {"repaired": 0, "skipped": "the revert index cannot be read"}
    skip = set(idx["reverted_domains"])
    _confirm_applied_runs(idx)
    with session_scope() as session:
        plan = repair_inversions(
            session, dry_run=True, only_to=STATUS_DISQUALIFIED, skip_domains=skip, name_cap=None,
            only_without_own_verdict=True,
        )
    rows = plan["restored_to_disqualified"]
    if not rows:
        return {"repaired": 0, "held_by_operator_revert": plan["held_by_operator_revert"]}

    planned_ids = {int(r["source_id"]) for r in rows}
    run_at = _iso(now) or ""
    # An apply that keeps failing must not add a record per boot: when the newest run is still
    # unconfirmed and planned exactly these sources, nothing was applied, so this attempt
    # REPLACES its plan instead of appending a second one. (A run that applied but could not
    # confirm leaves different sources to plan, so it is never overwritten here.)
    last = idx["runs"][-1] if idx["runs"] else None
    prior = (kv_get_json(REPAIR_RUN_PREFIX + last) or {}) if last else {}
    if (
        last is not None and not prior.get("applied")
        and {int(r.get("source_id", -1)) for r in prior.get("repairs") or []} == planned_ids
    ):
        run_at = last
    run_key = REPAIR_RUN_PREFIX + run_at
    # 2. record and index the intent (outside any ORM write transaction: kv_set_json's contract)
    kv_set_json(run_key, {"run_at": run_at, "applied": False, "repairs": rows})
    if run_at != last:
        idx["runs"] = [*idx["runs"], run_at]
    idx["last_run_at"] = run_at
    _write_repair_index(idx)
    # 3. the planned sources, re-checked, in one transaction
    with session_scope() as session:
        done = repair_inversions(
            session, dry_run=False, only_to=STATUS_DISQUALIFIED, skip_domains=skip,
            name_cap=None, only_source_ids=planned_ids, only_without_own_verdict=True,
        )
    applied_rows = done["restored_to_disqualified"]
    # 4. what was REALLY applied replaces the plan
    kv_set_json(run_key, {"run_at": run_at, "applied": True, "repairs": applied_rows})
    return {"repaired": len(applied_rows), "run_at": run_at,
            "held_by_operator_revert": done["held_by_operator_revert"]}


def _confirm_applied_runs(idx: dict[str, Any]) -> None:
    """Close a run whose change landed but whose confirmation write failed.

    A run still marked ``applied: false`` was either never applied (its sources are re-planned and
    the record replaced) or applied without its confirmation: then every source it lists already
    reads what it restored, nothing is left to plan for it, and without this it would read
    "unconfirmed" for good. Only a run whose EVERY row reads its ``restored_to`` is confirmed.
    """
    from src.config.kv_store import kv_get_json, kv_set_json
    from src.database.models import Source
    from src.database.session import session_scope

    for run_at in idx["runs"]:
        run = kv_get_json(REPAIR_RUN_PREFIX + run_at) or {}
        rows = run.get("repairs") or []
        if run.get("applied") or not rows:
            continue
        with session_scope() as session:
            statuses = {
                int(i): st for i, st in session.query(Source.id, Source.status).filter(
                    Source.id.in_([int(r["source_id"]) for r in rows if "source_id" in r])
                ).all()
            }
        if all(statuses.get(int(r.get("source_id", -1))) == r.get("restored_to") for r in rows):
            # closing an old record never blocks the new plan
            with contextlib.suppress(Exception):
                kv_set_json(REPAIR_RUN_PREFIX + run_at, {**run, "applied": True})


def revert_repairs(*, dry_run: bool = True) -> dict[str, Any]:
    """MAINTAINER TOOL: put every automatically repaired source back exactly as it was.

    Only the NEWEST unreverted record of each domain is applied (a domain repaired in two runs
    would otherwise get the oldest stamp back), and only while the row still reads what the
    repair gave it AND its newest judging attempt is still the one the repair followed -- a later
    judgement that confirms the disqualification produces exactly the state the repair writes,
    and must never be undone by this. Each reverted domain is HELD out of later automatic
    repairs, and the hold is written BEFORE the change, so a failure part-way can never be
    silently repaired again at the next boot. Dry run by default; nothing in the app or its
    documentation asks a user to run this.
    """
    from src.config.kv_store import kv_get_json, kv_set_json
    from src.database.models import Source
    from src.database.session import session_scope

    idx = _read_repair_index(strict=True)   # raises rather than rewrite an index it could not read
    plan: list[tuple[str, dict[str, Any]]] = []
    moved_on = 0
    runs: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    with session_scope() as session:
        for run_at in reversed(idx["runs"]):                      # newest run first
            run = kv_get_json(REPAIR_RUN_PREFIX + run_at) or {}
            runs[run_at] = run
            for r in run.get("repairs") or []:
                domain = r.get("domain")
                # `seen` first: once a domain's NEWEST record is reverted, an older record of it
                # must not become eligible (it would put back a stamp that is not the latest).
                if domain in seen:
                    continue
                seen.add(domain)
                if r.get("reverted_at"):
                    continue
                source = session.query(Source).filter(Source.domain == domain).first()
                newest = _newest_judging(session, int(source.id)) if source is not None else None
                if (
                    source is None or newest is None
                    or source.status != r.get("restored_to")
                    or _iso(newest.attempted_at) != r.get("judged_at")
                ):
                    moved_on += 1
                    continue
                plan.append((run_at, r))
    result = {
        "dry_run": dry_run, "reverted": len(plan), "moved_on_since_repair": moved_on,
        "sources": [{"domain": r["domain"], "to": r.get("was"), "run_at": run_at}
                    for run_at, r in plan],
    }
    if dry_run or not plan:
        return result

    # 1. the hold, BEFORE the change. It covers every planned domain, including one whose row
    #    then moves on before the write below: that domain is simply not repaired again by the
    #    boot, which is the conservative side.
    idx["reverted_domains"] = sorted({*idx["reverted_domains"], *(r["domain"] for _, r in plan)})
    _write_repair_index(idx)
    # 2. the change, re-checking each row inside the transaction
    stamp = _iso(datetime.now(UTC))
    with session_scope() as session:
        for _run_at, r in plan:
            source = session.query(Source).filter(Source.domain == r["domain"]).first()
            if source is None or source.status != r.get("restored_to"):
                continue
            source.status = r.get("was") or STATUS_UNQUALIFIED
            source.qualified_at = _parse_iso(r.get("was_qualified_at"))
            source.qualification_criteria_version = r.get("was_criteria_version")
            r["reverted_at"] = stamp
    # 3. mark the records
    for run_at in {run_at for run_at, _ in plan}:
        kv_set_json(REPAIR_RUN_PREFIX + run_at, runs[run_at])
    return result


def _parse_iso(value: str | None) -> datetime | None:
    """An ISO stamp back to the naive UTC every writer stores."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
