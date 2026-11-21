"""
The never-judged candidate backlog: what holds world discovery, and how fast judging drains it (R773 (2) and (4), row 249).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE BACKLOG is the found sites not checked yet: the candidates the source counts call unchecked
(:func:`src.catalog.source_standing.unchecked_candidate_clause`, R773 (1): never judged AND never collected from), stand-ins
excluded, that have NO attempt on record. A candidate a trial already reached but that gave nothing to judge yet is NOT in it
(security read 2, S3): it is checked again later by the requalification ladder, and counting it would let a run of silent
sites hold discovery for good and make the estimate promise a drain that judging does not deliver. Those are counted on
their own line (``tried_without_evidence``) so the panel still names them.

THE GATE. World discovery's ride-along pauses while the backlog is at or above ``world_discovery_backlog_bound`` and
resumes by itself once it is below; a country whose own backlog is at or above ``world_discovery_country_backlog_bound``
is passed over (never marked done, so it is asked again once it drains). 0 switches a bound off. Candidates are never
deleted: the bound only stops more from being added. One pass may add a little past a bound (it is read before the pass).

THE PACE. How many sources were checked for the first time (their first attempt of any verdict) over the last
``PACE_DAYS`` days, measured from the attempt records, divided by the days the records cover (the window, or less when the
first attempt on record is younger, never under one day); the time to clear the backlog is the backlog over that rate. No
first check in the window means no estimate, said so, never a made-up date. Counts only, never a score.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

PACE_DAYS = 7


def _unchecked(session: Session):
    from src.catalog.source_standing import unchecked_candidate_clause
    from src.database.models import Source
    from src.database.stand_in import not_a_stand_in_source

    return session.query(Source).filter(unchecked_candidate_clause(), not_a_stand_in_source())


def _unjudged(session: Session):
    """The backlog: unchecked candidates no trial has reached yet."""
    from src.database.models import Source, SourceQualificationAttempt

    tried = session.query(SourceQualificationAttempt.source_id)
    return _unchecked(session).filter(Source.id.notin_(tried))


def tried_without_evidence(session: Session) -> int:
    """Unchecked candidates a trial already reached that gave nothing to judge yet (not in the backlog)."""
    from src.database.models import Source, SourceQualificationAttempt

    tried = session.query(SourceQualificationAttempt.source_id)
    return int(_unchecked(session).filter(Source.id.in_(tried)).count())


def unjudged_backlog(session: Session) -> int:
    """How many found sites no trial has reached yet."""
    return int(_unjudged(session).count())


def unjudged_by_country(session: Session) -> dict[str, int]:
    """The backlog (found sites no trial has reached yet) per recorded country (lowercase ISO code); a candidate with no country is left out."""
    from src.database.models import Source

    rows = (
        _unjudged(session)
        .with_entities(Source.country, func.count(Source.id))
        .filter(Source.country.isnot(None))
        .group_by(Source.country)
        .all()
    )
    return {str(c).lower(): int(n) for c, n in rows if c}


def discovery_gate(session: Session, *, bound: int, country_bound: int) -> dict:
    """Whether world discovery's ride-along may add more now, with the numbers that decide it.

    ``paused`` is True while the backlog is at or above ``bound`` (``bound`` 0: never). ``held_countries`` lists the
    countries at or above ``country_bound`` (``country_bound`` 0: none), largest first.
    """
    backlog = unjudged_backlog(session)
    paused = bound > 0 and backlog >= bound
    held: list[dict] = []
    if country_bound > 0:
        held = sorted(
            ({"country": c, "unjudged": n} for c, n in unjudged_by_country(session).items() if n >= country_bound),
            key=lambda r: (-r["unjudged"], r["country"]),
        )
    return {
        "paused": paused,
        "backlog": backlog,
        "bound": int(bound),
        "country_bound": int(country_bound),
        "held_countries": held,
        "tried_without_evidence": tried_without_evidence(session),
    }


def judging_pace(session: Session, *, backlog: int, now: datetime | None = None, days: int = PACE_DAYS) -> dict:
    """The measured rate at which found sites were checked for the first time, and the time it implies for ``backlog``.

    A source counts once, on the day of its FIRST attempt of any verdict: that is the step that takes it out of the
    backlog. The rate divides by the days the attempt records actually cover inside the window (an install whose first
    attempt is two days old divides by two, never by seven), at least one day. ``eta_days`` is None when nothing was
    checked for the first time in the window (no rate, so no date). The panel states the method in its own keyed words
    (``_qualDiscoveryRows``).
    """
    from src.database.models import SourceQualificationAttempt

    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    first = (
        session.query(
            SourceQualificationAttempt.source_id.label("sid"),
            func.min(SourceQualificationAttempt.attempted_at).label("first_at"),
        )
        .group_by(SourceQualificationAttempt.source_id)
        .subquery()
    )
    judged = int(session.query(func.count()).select_from(first).filter(first.c.first_at >= since).scalar() or 0)
    earliest = session.query(func.min(SourceQualificationAttempt.attempted_at)).scalar()
    covered = float(days)
    if earliest is not None:
        if earliest.tzinfo is None and now.tzinfo is not None:
            earliest = earliest.replace(tzinfo=UTC)
        elif earliest.tzinfo is not None and now.tzinfo is None:
            earliest = earliest.replace(tzinfo=None)
        age = (now - earliest).total_seconds() / 86400.0
        covered = min(float(days), max(1.0, age))
    per_day = judged / covered if covered > 0 else 0.0
    eta = (backlog / per_day) if per_day > 0 else None
    return {
        "days": days,
        "judged": judged,
        "per_day": round(per_day, 1),
        "eta_days": (round(eta, 1) if eta is not None else None),
    }


__all__ = ["PACE_DAYS", "discovery_gate", "judging_pace", "tried_without_evidence", "unjudged_backlog", "unjudged_by_country"]
