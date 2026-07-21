"""
Source QUALIFICATION lifecycle -- the ADMISSION GATE (0.3 CLOSE GATE ruling,
maintainer-amended + RE-QUALIFICATION RULED, 2026-07-19/20; see the ledger CLAUDE.md
"SOURCE QUALIFICATION" thread).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING, in three clauses this module implements:

  (b) the verdict is a categorical STAMP, never a score: ``Source.status`` is exactly
      unqualified|qualified|disqualified, ``qualified_at`` + ``qualification_criteria_version``
      record WHAT was checked (extraction validity) and WHEN -- never a quality figure.
      "Trial" is the PROCESS (a consented few-article scrape), never a persisted status.

  (c) qualification runs as a background, task-manager-visible job, PARALLEL to other
      tasks -- a NETWORK job kind whose trial fetches ride the standing online-consent
      envelope exactly like the world-discovery ride-along (src.catalog.discover_job):
      never under airplane, best-effort, bounded per pass. See :func:`advance_qualification`,
      wired into the scheduler's collection pass (src.scheduler.runner).

  RE-QUALIFICATION RULED: a disqualified source gets a SECOND CHANCE -- the CLOCK is the
  ONLY re-trigger (event-driven re-checks like a re-import or a fresh citation stay
  suppressed; see the admission gate in src.scheduler.runner.select_sources). Every
  attempt is RECORDED, append-only (the vintage convention -- never overwritten;
  SourceQualificationAttempt), so the ladder position is always DERIVED from the real
  history, never a mutable counter. The interval is a per-source BACKOFF: 1st
  disqualification -> re-check in 1 month, doubling toward a 6-month cap (1->2->4->6),
  reset to 1 the moment a re-check succeeds (see :func:`consecutive_disqualifications`
  and :func:`backoff_months`).

REUSE, never duplicate: the extraction-validity JUDGING itself is
src.analytics.source_audit's existing criteria (per_source_metrics / flag_criteria /
derive_status) -- this module adds ORCHESTRATION (candidate selection, the trial fetch,
the ladder, the stamp), never a second scoring mechanism. A candidate is DISQUALIFIED
only on the high-confidence extraction-failure signature (status degraded/failing --
pathology_rate, the furniture-repetition nav-DOM pattern, alone or corroborated) --
NEVER on a soft/style-ambiguous flag alone (terse prose is legitimate variety). Passing
``min_articles=TRIAL_MIN_ARTICLES`` (not source_audit's default 20) to ``flag_criteria``
is what lets a small trial be judged at all: with n as low as 1 the language cohort sits
below SOURCE_COHORT_FLOOR, so the soft criteria stay honestly unflaggable (no baseline)
and ONLY the criteria pathology's ABSOLUTE floor (PATHOLOGY_ABS_FLOOR) can fire --
exactly the ruling's COLD START design note ("qualification initially decides on the
hard extraction-validity floor only, firming as the corpus grows": as the corpus grows
past the cohort floor, the SAME call starts honouring cohort-relative soft signals too).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.database.models import Source
    from src.ingest import EthicalFetcher

_LOG = logging.getLogger("catalog.qualification")

# The criteria VERSION stamped on every verdict (Source.qualification_criteria_version +
# SourceQualificationAttempt.criteria_version). Bump this if the judging criteria change
# so the history stays honest about which rules judged an old attempt.
CRITERIA_VERSION = "oo-source-qualification-1"

# Exactly the three states the ruling names -- never "candidate"/"trial" (the process,
# not a persisted state) and never a fourth state.
STATUS_UNQUALIFIED = "unqualified"
STATUS_QUALIFIED = "qualified"
STATUS_DISQUALIFIED = "disqualified"

# The "consented few-article scrape" -- bounded, so a trial never turns into a full crawl.
TRIAL_MAX_ITEMS = 5
# Passed to source_audit.flag_criteria in place of its default MIN_SOURCE_ARTICLES=20, so a
# trial-sized source is judged at all (see the module docstring's COLD START note).
TRIAL_MIN_ARTICLES = 1

# The re-qualification ladder cap (RE-QUALIFICATION RULED: "1 to 6 months").
_LADDER_CAP_MONTHS = 6
# 1 calendar month approximated as 30 days -- the ruling's own interval is casual ("1 to
# 6 months"), not calendar-exact; a Settings knob (not yet wired -- out of this build's
# scope) can override the whole ladder if the maintainer wants calendar-month precision.
_MONTH_DAYS = 30


def backoff_months(consecutive_disqualifications: int) -> int:
    """The re-qualification ladder: 1st disqualification -> 1 month, doubling each
    REPEATED disqualification, capped at 6 (1 -> 2 -> 4 -> 6 -> 6 -> ...). Resetting to 1
    on a qualified verdict is NOT this function's job -- it falls out of
    :func:`consecutive_disqualifications` counting only the TRAILING run of
    ``disqualified`` verdicts (a qualified verdict breaks the run -> next count is 0 ->
    the next disqualification starts the ladder over at 1)."""
    n = max(1, consecutive_disqualifications)
    return min(2 ** (n - 1), _LADDER_CAP_MONTHS)


def reattempt_due_at(last_attempt_at: datetime, consecutive_disqualifications: int) -> datetime:
    """The next re-qualification check is due this many months after the last attempt."""
    months = backoff_months(consecutive_disqualifications)
    return last_attempt_at + timedelta(days=_MONTH_DAYS * months)


def consecutive_disqualifications_from_verdicts(verdicts_newest_first: list[str]) -> int:
    """PURE core: count the TRAILING run of ``disqualified`` verdicts from the newest
    attempt backwards -- a single ``qualified`` verdict anywhere in the run stops the
    count (the ladder resets on the NEXT success, per the ruling)."""
    n = 0
    for v in verdicts_newest_first:
        if v == STATUS_DISQUALIFIED:
            n += 1
        else:
            break
    return n


def consecutive_disqualifications(session: Session, source_id: int) -> int:
    """DB-facing wrapper: the source's real attempt history, newest attempt first."""
    from src.database.models import SourceQualificationAttempt

    rows = (
        session.query(SourceQualificationAttempt.verdict)
        .filter(SourceQualificationAttempt.source_id == source_id)
        .order_by(SourceQualificationAttempt.attempted_at.desc())
        .all()
    )
    return consecutive_disqualifications_from_verdicts([r[0] for r in rows])


def decide_verdict(failing_criteria: list[dict]) -> str:
    """Map source_audit's categorical status onto a qualification verdict: disqualified
    ONLY on the extraction-failure signature (status degraded or failing -- pathology_rate,
    alone or corroborated); qualified otherwise (healthy, or watch = soft-only flags,
    which the reframe forbids ever failing a source for). Reuses derive_status -- never
    re-derives the criteria logic."""
    from src.analytics.source_audit import derive_status

    status = derive_status(failing_criteria)
    return STATUS_DISQUALIFIED if status in ("degraded", "failing") else STATUS_QUALIFIED


def trial_fetch(session: Session, source: Source, fetcher: EthicalFetcher,
                 *, max_items: int = TRIAL_MAX_ITEMS) -> dict:
    """The consented few-article trial scrape, reusing the SAME ingest path the regular
    collection pass uses -- "no wasted fetch": whatever is fetched is kept as normal
    STORED articles, never a throwaway probe. RSS-feed sources only in this build (the
    overwhelming common case for scheduled collection); a source with no ``rss_url`` is
    judged on whatever it has already collected by other means, if anything (a known,
    documented scope limit -- see run_qualification_pass)."""
    from src.ingest.pipeline import ingest_source

    if not getattr(source, "rss_url", None):
        return {}
    return ingest_source(session, source, fetcher=fetcher, max_items=max_items)


def select_unqualified(session: Session, *, limit: int) -> list[Source]:
    """Never-yet-qualified candidates, oldest (lowest id) first, bounded per pass."""
    from src.database.models import Source

    if limit <= 0:
        return []
    return (
        session.query(Source)
        .filter(Source.status == STATUS_UNQUALIFIED)
        .order_by(Source.id.asc())
        .limit(limit)
        .all()
    )


def select_due_disqualified(
    session: Session, *, now: datetime, limit: int, pool_multiplier: int = 5
) -> list[Source]:
    """Disqualified sources whose re-qualification ladder has come due -- the CLOCK is the
    ONLY re-trigger (event-driven re-checks stay suppressed elsewhere, per the admission
    gate). Bounded: only a working pool of the oldest-last-attempt candidates is pulled
    and ladder-checked, so a large disqualified backlog never swamps one pass (mirrors
    ``world_discovery_per_pass``'s per-pass budget)."""
    from sqlalchemy import func

    from src.database.models import Source, SourceQualificationAttempt

    if limit <= 0:
        return []
    pool_size = max(limit * pool_multiplier, limit)
    last_attempt = (
        session.query(
            SourceQualificationAttempt.source_id.label("source_id"),
            func.max(SourceQualificationAttempt.attempted_at).label("last_at"),
        )
        .group_by(SourceQualificationAttempt.source_id)
        .subquery()
    )
    rows = (
        session.query(Source, last_attempt.c.last_at)
        .join(last_attempt, last_attempt.c.source_id == Source.id)
        .filter(Source.status == STATUS_DISQUALIFIED)
        .order_by(last_attempt.c.last_at.asc())
        .limit(pool_size)
        .all()
    )
    due: list[Source] = []
    for source, last_at in rows:
        if len(due) >= limit:
            break
        # SQLite/SQLAlchemy round-trips a DateTime as NAIVE even when an aware UTC
        # value was stored -- the coverage.py skip_until convention: re-attach UTC
        # explicitly before comparing against an aware ``now``.
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=UTC)
        n = consecutive_disqualifications(session, source.id)
        if reattempt_due_at(last_at, n) <= now:
            due.append(source)
    return due


def evaluate_and_stamp(
    session: Session, sources: list[Source], fails_by_source: dict[int, list[dict]],
    *, now: datetime, criteria_version: str = CRITERIA_VERSION,
) -> dict:
    """Persist ONE attempt (append-only) + the categorical stamp for each evaluated
    source. Never a score: only the three-state status + the DATE + the criteria version
    are stamped. ``qualified_at``/``qualification_criteria_version`` are cleared on a
    disqualified verdict -- a stale 'qualified' stamp must never survive a later failure."""
    from src.database.models import SourceQualificationAttempt

    qualified = disqualified = 0
    for source in sources:
        fails = fails_by_source.get(source.id, [])
        verdict = decide_verdict(fails)
        session.add(SourceQualificationAttempt(
            source_id=source.id, attempted_at=now, verdict=verdict,
            criteria_version=criteria_version,
        ))
        source.status = verdict
        if verdict == STATUS_QUALIFIED:
            source.qualified_at = now
            source.qualification_criteria_version = criteria_version
            qualified += 1
        else:
            source.qualified_at = None
            source.qualification_criteria_version = None
            disqualified += 1
    return {"qualified": qualified, "disqualified": disqualified}


def run_qualification_pass(
    session: Session, fetcher: EthicalFetcher | None, *, per_pass: int,
    now: datetime | None = None,
) -> dict:
    """One bounded qualification pass: pick up to ``per_pass`` candidates (never-yet-
    qualified first, then due re-qualifications), best-effort trial-fetch each, then
    judge ALL of them together through source_audit's REUSED criteria (one whole-corpus
    metrics pass, not one per candidate -- so cohort baselines can "firm up" as the
    corpus grows, per the ruling's cold-start note), and stamp the verdict. One
    candidate's trial-fetch failure never aborts the pass (best-effort, like every other
    scheduler ride-along)."""
    from src.analytics import source_audit as sa

    if per_pass <= 0:
        return {"enabled": False}
    now = now or datetime.now(UTC)

    candidates = select_unqualified(session, limit=per_pass)
    remaining = per_pass - len(candidates)
    if remaining > 0:
        candidates += select_due_disqualified(session, now=now, limit=remaining)
    if not candidates:
        return {"enabled": True, "evaluated": 0}

    trial_errors = 0
    if fetcher is not None:
        for source in candidates:
            try:
                trial_fetch(session, source, fetcher)
            except Exception:  # noqa: BLE001 - one bad candidate must not abort the pass
                trial_errors += 1
                _LOG.warning(
                    "qualification trial fetch failed for %r",
                    getattr(source, "domain", "?"), exc_info=True,
                )

    per = sa.per_source_metrics(session)
    # per_source_metrics does not itself compute furniture_share (audit_sources adds it
    # as a separate enrichment step) -- flag_criteria's CRITERIA panel requires the key
    # to be present on every entry, so reuse the SAME cross-source fingerprint helper
    # audit_sources uses, rather than re-deriving it.
    shares = sa._furniture_share_by_source(session, list(per))  # noqa: SLF001 - reuse, not duplicate
    for sid, m in per.items():
        m["furniture_share"] = shares.get(sid, 0.0)
    fails_by_source = sa.flag_criteria(per, min_articles=TRIAL_MIN_ARTICLES)
    tally = evaluate_and_stamp(session, candidates, fails_by_source, now=now)
    session.commit()

    return {
        "enabled": True, "evaluated": len(candidates), "trial_fetch_errors": trial_errors,
        **tally,
    }


def advance_qualification(
    session: Session, fetcher: EthicalFetcher | None, *, per_pass: int,
    now: datetime | None = None,
) -> dict:
    """The scheduler RIDE-ALONG (ruling clause (c): "like the world-discovery ride-
    along"): a bounded qualification pass per online collection pass, through the SAME
    guarded transport. Skips honestly under airplane mode (trial fetches ride the
    standing online-consent envelope -- never under airplane); the caller wraps this so
    a failure never breaks a scrape."""
    if per_pass <= 0:
        return {"enabled": False}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode engaged"}
    return run_qualification_pass(session, fetcher, per_pass=per_pass, now=now)
