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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func

from src.config.machine_floor import scan_budget
from src.database.models import Article

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.database.models import Source
    from src.ingest import EthicalFetcher

_LOG = logging.getLogger("catalog.qualification")

# The criteria VERSION stamped on every verdict (Source.qualification_criteria_version +
# SourceQualificationAttempt.criteria_version). Bump this if the judging criteria change
# so the history stays honest about which rules judged an old attempt.
CRITERIA_VERSION = "oo-source-qualification-2"
# -2 (S5.1, 2026-09-02 crash analysis): the cohort baselines a verdict is measured against
# are computed ONCE PER RUN and frozen, instead of re-read from the whole corpus for every
# batch of 20. A batch is therefore judged against a baseline up to one run old, and an
# attempt row must not read as though it were judged the old way -- which is exactly what
# this field is for ("a later criteria change is visible in the history rather than
# silently reinterpreted", SourceQualificationAttempt's own docstring). The per-run
# staleness numbers ride the pass RESULT (baseline_token / baseline_articles /
# baseline_age_s), because an age belongs in a measurement and not in a version string.

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

# A no-evidence outcome is logged to SourceQualificationAttempt (2026-07-23 livelock
# fix -- see select_unqualified) but is NEVER a Source.status value: the three-state
# admission-gate model (unqualified|qualified|disqualified) is untouched. It is a
# fourth, ATTEMPT-LOG-only verdict recording "we tried, there was nothing to judge".
VERDICT_NO_EVIDENCE = "no_evidence"

# A stamp this instance did NOT earn -- adopted from a restored backup or from the shipped
# qualification overlay (configs/source_qualification.yml). Like VERDICT_NO_EVIDENCE this is
# an ATTEMPT-LOG-only verdict and NEVER a Source.status value: the three-state admission-gate
# model is untouched. It records WHERE a verdict came from, so a history cannot read as
# though this instance had measured something it only inherited (maintainer ruling
# 2026-09-04: "trust it, then confirm in the background"). It is not a judgement, so like
# no_evidence it neither advances nor resets the re-qualification ladder, and it does not
# move the re-verification clock -- see `_last_judged_subquery`.
VERDICT_INHERITED = "inherited"

# The verdicts that are actual JUDGEMENTS -- a real evaluation of real evidence, by some
# instance. The other two attempt verdicts record why a judgement did NOT happen.
JUDGING_VERDICTS = (STATUS_QUALIFIED, STATUS_DISQUALIFIED)

# RE-VERIFICATION OF A QUALIFIED SOURCE (maintainer ruling 2026-09-04). A FLAT interval,
# never the disqualified ladder's doubling: doubling encodes diminishing hope after repeated
# failure and means nothing after a success.
#
# WHAT A RE-CHECK CAN HONESTLY CLAIM, stated here because the docstring is where a future
# session will look before trusting it: `source_audit` has NO recency window anywhere in its
# chain (`collect_article_stats` reads a source's whole stored history), so a re-check sees a
# source that is BROADLY broken and CANNOT see one that degraded recently against years of
# good history. Its real value is the COLD-START firming this module's own docstring already
# describes: a source admitted on 1-4 articles, when the language cohort sat below
# SOURCE_COHORT_FLOOR and only PATHOLOGY_ABS_FLOOR could fire, is judged against a real
# cohort baseline for the first time. A recency-windowed re-check is a named follow-up;
# claiming degradation detection without one would be a fabricated capability.
QUALIFIED_RECHECK_MONTHS = 6

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
    count (the ladder resets on the NEXT success, per the ruling). A ``no_evidence``
    entry (2026-07-23 livelock fix) or an ``inherited`` one (2026-09-04) is INCONCLUSIVE
    -- neither advances nor resets the ladder, so both are skipped rather than stopping
    the count; a source stays at its real ladder position until an attempt that actually
    judges it again. Inheriting a stamp is not this instance measuring anything, so it
    must not be able to reset a ladder that real failures built."""
    n = 0
    for v in verdicts_newest_first:
        if v == STATUS_DISQUALIFIED:
            n += 1
        elif v in (VERDICT_NO_EVIDENCE, VERDICT_INHERITED):
            continue
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
    STORED articles, never a throwaway probe.

    RSS-feed sources use the feed. A source with NO ``rss_url`` -- the FEEDLESS
    MAJORITY of the discovery backlog (2026-07-24 throughput brief C7: every
    Wikidata-catalog-generated source, confirmed by grep, never sets ``rss_url`` at
    all) -- now falls back to the sitemap trial channel
    (:func:`src.ingest.sitemap.sitemap_trial_ingest`): discover the source's own
    article URLs via its sitemap and ingest a bounded few, exactly like the RSS
    path. Only a source with NEITHER an rss_url NOR a discoverable sitemap is
    judged on whatever it has already collected by other means, if anything (the
    residual, narrower documented scope limit -- see run_qualification_pass)."""
    from src.ingest.pipeline import ingest_source

    if getattr(source, "rss_url", None):
        return ingest_source(session, source, fetcher=fetcher, max_items=max_items)

    from src.ingest.sitemap import sitemap_trial_ingest

    return sitemap_trial_ingest(session, source, fetcher, max_items=max_items)


def select_unqualified(session: Session, *, limit: int) -> list[Source]:
    """Never-yet-qualified candidates, bounded per pass.

    LIVELOCK FIX (2026-07-23, found by adversarial review + reproduced live against the
    real query): a pure ``ORDER BY id ASC`` starves the queue the moment several of the
    LOWEST-id candidates can never produce evidence (e.g. every source the world-catalog
    generator creates has no ``rss_url`` at all -- confirmed by grep,
    ``scripts/build_world_news_catalog.py`` never sets it -- so it can NEVER be resolved
    by a trial fetch). Since the no-evidence fix (above) correctly leaves such a source
    ``unqualified`` rather than silently qualifying it, the SAME lowest-id, permanently-
    unresolvable sources would be re-selected on EVERY future call forever, and once
    they fill an entire ``limit``-sized window, no candidate BEHIND them in id order is
    ever reached again -- reproduced empirically: 30 feed-less sources followed by one
    genuinely resolvable source never let the resolvable one through across 20 passes.

    FIX: order by LEAST-RECENTLY-ATTEMPTED instead of pure id -- a candidate that has
    NEVER been attempted (no ``SourceQualificationAttempt`` row at all, incl. one logged
    for a no-evidence outcome; see ``run_qualification_pass``) sorts FIRST, ahead of any
    candidate that already produced an inconclusive result; among already-attempted
    candidates the OLDEST attempt sorts first (fair rotation, so a permanently-stuck
    candidate still gets retried occasionally -- a transient failure deserves another
    chance -- but can never again BLOCK a candidate that hasn't been tried yet). ``id``
    stays the final tiebreaker for determinism. Mirrors the same LEFT-JOIN-a-last-attempt
    shape ``select_due_disqualified`` already uses.
    """
    from sqlalchemy import func

    from src.database.models import Source, SourceQualificationAttempt

    if limit <= 0:
        return []
    last_attempt = (
        session.query(
            SourceQualificationAttempt.source_id.label("source_id"),
            func.max(SourceQualificationAttempt.attempted_at).label("last_at"),
        )
        .group_by(SourceQualificationAttempt.source_id)
        .subquery()
    )
    return (
        session.query(Source)
        .outerjoin(last_attempt, last_attempt.c.source_id == Source.id)
        .filter(Source.status == STATUS_UNQUALIFIED)
        .order_by(last_attempt.c.last_at.asc().nullsfirst(), Source.id.asc())
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


def _last_judged_subquery(session: Session):
    """``{source_id: newest attempt that actually JUDGED it}``.

    Scoped to ``JUDGING_VERDICTS`` on purpose: a ``no_evidence`` or ``inherited`` row
    records why a judgement did NOT happen, and counting either as a judgement would make
    the re-verification clock lie in the one direction that matters. An ``inherited`` row
    is written at the moment a stamp is ADOPTED, so if it moved the clock, a stamp inherited
    from a two-year-old catalog would read as verified today -- exactly the fabricated
    freshness the ruling's "trust it, then confirm" wording exists to avoid.
    """
    from src.database.models import SourceQualificationAttempt as A

    return (
        session.query(
            A.source_id.label("source_id"),
            func.max(A.attempted_at).label("last_at"),
        )
        .filter(A.verdict.in_(JUDGING_VERDICTS))
        .group_by(A.source_id)
        .subquery()
    )


def qualified_recheck_due_at(last_judged_at: datetime) -> datetime:
    """When a qualified verdict falls due for re-verification: a FLAT interval, unlike the
    disqualified ladder's doubling backoff (see QUALIFIED_RECHECK_MONTHS)."""
    return last_judged_at + timedelta(days=_MONTH_DAYS * QUALIFIED_RECHECK_MONTHS)


def select_due_qualified(
    session: Session, *, now: datetime, limit: int
) -> list[Source]:
    """Qualified sources whose verdict has aged past QUALIFIED_RECHECK_MONTHS.

    THE CLOCK is the newest attempt that actually judged this source, falling back to
    ``Source.qualified_at`` when there is none. The fallback is what makes an INHERITED
    stamp work without a second queue: for a verdict adopted from a backup or the shipped
    overlay, ``qualified_at`` is the ORIGINATING instance's date, so a stamp that was
    already months old when it arrived comes due sooner, and a freshly-earned one waits its
    full interval. Ordered oldest-first, so the longest-unverified verdict goes first --
    which is also the ruling's "low priority" for inherited stamps, falling out of the
    ordering rather than needing a separate pool.

    A qualified row with NEITHER a judging attempt NOR a ``qualified_at`` is a data anomaly
    (``evaluate_and_stamp`` always writes both). It is treated as DUE rather than skipped:
    that is the direction that self-heals -- the source is re-judged and stamped properly --
    where skipping would leave it permanently unverifiable and invisible.
    """
    from src.database.models import Source

    if limit <= 0:
        return []
    last_judged = _last_judged_subquery(session)
    rows = (
        session.query(Source, last_judged.c.last_at)
        .outerjoin(last_judged, last_judged.c.source_id == Source.id)
        .filter(Source.status == STATUS_QUALIFIED)
        # Oldest clock first, and a row with no clock at all (the anomaly above) first of
        # all. COALESCE in SQL so the ordering is done by the database rather than by
        # loading every qualified source into Python -- there can be tens of thousands.
        .order_by(
            func.coalesce(last_judged.c.last_at, Source.qualified_at).asc().nullsfirst(),
            Source.id.asc(),
        )
        .limit(limit)
        .all()
    )
    due: list[Source] = []
    for source, last_at in rows:
        clock = last_at or source.qualified_at
        if clock is None:
            due.append(source)
            continue
        # SQLite/SQLAlchemy round-trips a DateTime as NAIVE even when an aware UTC value
        # was stored (the coverage.py skip_until convention) -- re-attach UTC before
        # comparing against an aware ``now``.
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=UTC)
        if qualified_recheck_due_at(clock) <= now:
            due.append(source)
    return due


def log_inherited_stamps(
    session: Session, sources: list[Source], *, now: datetime,
    criteria_version: str = CRITERIA_VERSION,
) -> int:
    """Record that each source's stamp was INHERITED, not measured here (2026-09-04
    ruling). Append-only, exactly like every other attempt row, and ``Source.status`` is
    NEVER touched -- the caller has already adopted the verdict; this only records where
    it came from, so a later reader cannot mistake an adopted stamp for local evidence."""
    from src.database.models import SourceQualificationAttempt

    for source in sources:
        session.add(SourceQualificationAttempt(
            source_id=source.id, attempted_at=now, verdict=VERDICT_INHERITED,
            criteria_version=criteria_version,
        ))
    return len(sources)


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
    qualified_ids: list[int] = []
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
            qualified_ids.append(source.id)
        else:
            source.qualified_at = None
            source.qualification_criteria_version = None
            disqualified += 1
    # C15 (2026-07-24 throughput brief, S-E slice 2): qualified_ids is returned
    # (never enqueued HERE, before the caller's own commit) so the caller can
    # enqueue archive backfill only AFTER the "qualified" stamp is actually
    # committed -- a rollback between this call and the commit must never
    # queue a backfill for a source that was never really admitted.
    return {"qualified": qualified, "disqualified": disqualified, "qualified_ids": qualified_ids}


def log_no_evidence_attempts(
    session: Session, sources: list[Source], *, now: datetime,
    criteria_version: str = CRITERIA_VERSION,
) -> int:
    """Record a NO-EVIDENCE attempt for each source (2026-07-23 livelock fix) -- an
    append-only log row exactly like ``evaluate_and_stamp`` writes, but ``Source.status``
    is NEVER touched (stays ``unqualified``; no free pass, per the zero-evidence fix).
    This is what lets :func:`select_unqualified` rotate PAST a source that just produced
    no evidence in favour of one that has never been attempted (or was attempted longer
    ago) -- without this log entry the source would look identical to a never-tried
    candidate and sort right back to the front of the queue next time, reproducing the
    same livelock."""
    from src.database.models import SourceQualificationAttempt

    for source in sources:
        session.add(SourceQualificationAttempt(
            source_id=source.id, attempted_at=now, verdict=VERDICT_NO_EVIDENCE,
            criteria_version=criteria_version,
        ))
    return len(sources)


def _corpus_articles(session: Session) -> int:
    """Cheap indexed COUNT of articles — the scale the scan's need is sized from.

    A count failure returns 0, which sizes the need at its floor and therefore
    DECLINES LESS: a machine is refused on a measurement, never on our inability
    to take one.
    """
    try:
        return int(session.query(func.count(Article.id)).scalar() or 0)
    except Exception:  # noqa: BLE001 - a count must never break the pass
        return 0


def run_qualification_pass(
    session: Session, fetcher: EthicalFetcher | None, *, per_pass: int,
    recheck_per_pass: int = 0,
    now: datetime | None = None,
    cohort_provider: Callable[[], dict] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> dict:
    """One bounded qualification pass: pick up to ``per_pass`` candidates (never-yet-
    qualified first, then due re-qualifications), best-effort trial-fetch each, then
    judge ALL of them together through source_audit's REUSED criteria (one whole-corpus
    metrics pass, not one per candidate -- so cohort baselines can "firm up" as the
    corpus grows, per the ruling's cold-start note), and stamp the verdict. One
    candidate's trial-fetch failure never aborts the pass (best-effort, like every other
    scheduler ride-along).

    NO-EVIDENCE CANDIDATES ARE NEVER STAMPED (2026-07-23 field-diagnostics fix -- verified
    LIVE against the field log's "qualification trial fetch failed for 'latimes.com'"):
    ``source_audit.per_source_metrics``/``flag_criteria`` OMIT a source ENTIRELY (not just
    from its BAD-tail flags) when it has zero stored articles -- this covers a totally-
    failed trial fetch (no rss_url reachable) AND, since C7 (2026-07-24 throughput brief)
    narrowed but did not close this gap, a candidate with NEITHER an rss_url NOR a
    discoverable sitemap (a documented, narrower scope limit: "judged on whatever it has
    already collected by other means, if anything"). Reading that absence as "no failing
    criteria" and defaulting to
    STATUS_QUALIFIED would silently ADMIT a candidate we never actually verified -- exactly
    the free pass the whole admission gate exists to prevent. So a candidate that produced
    NO evidence this round is left ``unqualified`` (its current status -- untouched, no
    stamp) and re-offered by :func:`select_unqualified` on a LATER pass, honestly tallied
    as ``no_evidence`` (never silently folded into "qualified").

    A no-evidence outcome IS logged (:func:`log_no_evidence_attempts`) -- not to
    ``Source.status``, but as a ``SourceQualificationAttempt`` row -- because
    ``select_unqualified`` orders by least-recently-attempted, and a source with no log
    entry at all looks identical to one that was NEVER tried, sorting right back to the
    front of every future pass. Without this, a permanently-unresolvable candidate (e.g.
    the world-catalog generator never sets ``rss_url``) would occupy its slot forever and
    LIVELOCK the whole backlog for every candidate behind it in id order -- reproduced
    empirically before this fix (30 feed-less sources blocked a genuinely resolvable one
    across 20 passes)."""
    from src.analytics import source_audit as sa
    from src.analytics import source_quality as sq

    if per_pass <= 0 and recheck_per_pass <= 0:
        return {"enabled": False}

    # S1.3 (2026-09-02 ruling 1): a machine below the memory floor DECLINES the
    # whole-corpus scan this pass is built on, with the numbers stated. Gated
    # HERE rather than at the two callers (the bulk job and the scheduler
    # ride-along) because this is the one place ``per_source_metrics`` is
    # reached -- an enumeration of callers is what the "gate EVERY entry point"
    # lesson keeps costing. And it is gated BEFORE the trial fetches: spending
    # Tor bandwidth on evidence we have already decided not to judge would be
    # the worst of both.
    budget = scan_budget(_corpus_articles(session))
    if budget["declines"]:
        return {
            "enabled": True,
            "evaluated": 0,
            "skipped": budget["skipped"],
            "available_mb": budget["available_mb"],
            "need_mb": budget["need_mb"],
            "reason": budget["reason"],
            "caveat": budget["caveat"],
            "override_env": budget["override_env"],
        }

    now = now or datetime.now(UTC)

    # ---- candidate selection: NEW candidates and RE-CHECKS have SEPARATE budgets ----
    # (2026-09-04 ruling.) Until now they shared ``per_pass``, and new candidates were
    # taken first: with a backlog of tens of thousands of unqualified sources (42.6k-66.7k
    # measured in the field) the first query ALWAYS returned a full window, the remainder
    # was always 0, and `select_due_disqualified` was never reached. The re-qualification
    # ladder was correct and unreachable -- the recurrent verification had never actually
    # run on a field instance. A separate budget makes that impossible by construction.
    #
    # Unused NEW slots still spill INTO re-checks (that is exactly today's behaviour, kept
    # so a small backlog is no slower to re-verify than before); the reserved re-check
    # budget deliberately does NOT spill the other way, because a budget that can be
    # consumed by the queue it is protecting against is not a reservation.
    new_candidates = select_unqualified(session, limit=per_pass)
    spill = max(0, per_pass - len(new_candidates))
    reserved = max(0, recheck_per_pass)

    # The two re-check kinds draw on DIFFERENT budgets, and the asymmetry is deliberate:
    #   * DISQUALIFIED re-checks may use the reserved budget AND unused new-candidate slots
    #     -- the spill is exactly today's behaviour, kept so a small backlog re-checks no
    #     more slowly than before this change.
    #   * QUALIFIED re-checks may use ONLY the reserved budget. Letting them take the spill
    #     would mean `qualification_recheck_per_pass = 0` still re-verified qualified
    #     sources, i.e. an explicit "off" that does not turn the thing off -- and a setting
    #     that does not mean what it says is worse than no setting.
    total = reserved + spill
    dq_pool: list[Source] = []
    ql_pool: list[Source] = []
    if total > 0:
        # Each pool is queried once at the budget it could possibly use, then allocated, so
        # an empty or short pool gives its slots to the other rather than wasting them.
        dq_pool = select_due_disqualified(session, now=now, limit=total)
    if reserved > 0:
        # `limit=reserved` IS the cap that keeps the spill out of qualified re-checks --
        # not a later min(), which would be a second place to enforce one rule. Querying
        # only what may actually be used also means an install with re-verification off
        # never pays for this query at all.
        ql_pool = select_due_qualified(session, now=now, limit=reserved)

    # Disqualified re-checks keep the priority they have today. At a reserved budget of 1
    # with a disqualified source always due, qualified re-verification therefore only runs
    # when none is -- stated rather than hidden; the default is 2, and 1 is the single
    # configuration where the split cannot be fair to both.
    take_dq = min(len(dq_pool), max(1, total // 2) if ql_pool else total)
    take_ql = min(len(ql_pool), total - take_dq)
    take_dq = min(len(dq_pool), total - take_ql)
    rechecks: list[Source] = dq_pool[:take_dq] + ql_pool[:take_ql]

    candidates = new_candidates + rechecks
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

    # S5.1: the COHORT is frozen (once per run, by the caller that knows what a run is) and
    # only the CANDIDATES' own metrics are read here, scoped in SQL. A caller that passes no
    # cohort gets one computed now, which is byte-identical to the old behaviour and is what
    # the per-pass ride-along does -- it calls this once per pass, so a per-pass freeze IS
    # once per call there and nothing about its verdicts changes.
    # Resolved HERE, after the candidates are known, so a pass with nothing to judge never
    # pays for a whole-corpus scan (the early return above happens first). The provider is a
    # CALLABLE rather than a dict for exactly that reason -- a caller that memoises it gets
    # one freeze per run, and a pass that never needs one never triggers it.
    try:
        frozen = cohort_provider() if cohort_provider is not None else sa.frozen_cohort(
            session, should_pause=should_pause, min_articles=TRIAL_MIN_ARTICLES,
        )
    except sq.ScanPaused as exc:
        # The FREEZE is itself a whole-corpus scan, so it can pause too -- and it is the
        # bigger of the two. Catching only the scoped read would have let the larger one
        # escape as an unhandled exception, which the job would report as a crash.
        _LOG.info("qualification pass paused during the cohort freeze: %s", exc)
        return {
            "enabled": True, "evaluated": 0, "paused": "memory", "reason": str(exc),
            "trial_fetch_errors": trial_errors,
        }
    # A cut frozen at another threshold is a DIFFERENT baseline -- it decides which sources
    # form the cohort at all. Refused rather than answered, because the failure is invisible:
    # frozen at the report's 20 against 4-article sources the cut comes out empty, and three
    # soft criteria simply stop being flaggable with nothing saying so.
    if frozen.get("min_articles") != TRIAL_MIN_ARTICLES:
        raise ValueError(
            f"cohort frozen at min_articles={frozen.get('min_articles')!r}, but this gate "
            f"judges at {TRIAL_MIN_ARTICLES} -- a cut frozen at another threshold is a "
            "different baseline"
        )
    try:
        per = sa.scoped_metrics(
            session, {int(s.id) for s in candidates}, frozen, should_pause=should_pause,
        )
    except sq.ScanPaused as exc:
        # S5.2: nothing is stamped from a paused scan. The candidates keep whatever status
        # they already had -- for a never-judged one that is ``unqualified``, which is the
        # truth, and the queue's least-recently-attempted ordering brings them back.
        _LOG.info("qualification pass paused: %s", exc)
        return {
            "enabled": True, "evaluated": 0, "paused": "memory", "reason": str(exc),
            "trial_fetch_errors": trial_errors,
        }
    fails_by_source = sa.flag_criteria(
        per, min_articles=TRIAL_MIN_ARTICLES, cohort_cut=frozen["cohort_cut"],
    )

    # A candidate absent from ``per`` has ZERO stored articles -- no evidence at all,
    # never stamped (see the docstring above). ``sid in per`` is the exact same test
    # ``flag_criteria`` uses internally (article_count >= TRIAL_MIN_ARTICLES == 1), so
    # this never disagrees with which sources actually got judged.
    judged = [s for s in candidates if s.id in per]
    no_evidence = [s for s in candidates if s.id not in per]

    tally = evaluate_and_stamp(session, judged, fails_by_source, now=now)
    log_no_evidence_attempts(session, no_evidence, now=now)
    session.commit()

    # C15 (2026-07-24 throughput brief, S-E slice 2): auto-enqueue a BOUNDED
    # archive backfill for every source that just got its "qualified" stamp
    # COMMITTED -- never before the commit (a rollback must never leave a
    # backfill queued for a source that was never really admitted). Always
    # full_history=False here: the automatic path never requests full
    # history, which is an explicit, separately-invoked per-source action.
    # Best-effort -- a queueing hiccup must never fail a qualification pass.
    for sid in tally.get("qualified_ids", []):
        try:
            from src.ingest.archive_backfill import enqueue_source

            enqueue_source(sid, full_history=False)
        except Exception:  # noqa: BLE001 - never fail qualification over a queueing hiccup
            _LOG.warning("archive backfill enqueue failed for source %s", sid, exc_info=True)

    return {
        "enabled": True, "evaluated": len(candidates), "trial_fetch_errors": trial_errors,
        "no_evidence": len(no_evidence),
        # Reported apart because they answer different questions: "is the backlog draining"
        # and "is the recurrent verification actually running". One number cannot say both,
        # and it was precisely the absence of the second that hid a ladder that never ran.
        "new_candidates": len(new_candidates),
        "rechecks": len(rechecks),
        # S5.1 staleness disclosure: WHICH corpus state the baseline reflects and how much of
        # it. Reported per pass rather than folded into the criteria version, because an age
        # is a measurement -- and because a reader must be able to tell a fresh baseline from
        # one carried across a long run without re-deriving it from timestamps.
        "baseline_token": frozen.get("token"),
        "baseline_articles": frozen.get("articles"),
        "baseline_sources": frozen.get("sources"),
        "baseline_frozen_by_caller": cohort_provider is not None,
        **tally,
    }


def _memory_pause_check() -> bool:
    """S5.2's OTHER half. The bulk job wires the memory guard's own poll into the scan; the
    per-pass ride-along is the second entry point to the SAME whole-corpus scan, and a fix
    that reaches one of two callers is the recorded gate-every-entry-point defect.

    ``poll()`` is the same call the collector's own loop already makes between sources, so
    the two can never disagree about the machine."""
    from src.scheduler import memguard

    return bool(memguard.memory_guard.poll())


def advance_qualification(
    session: Session, fetcher: EthicalFetcher | None, *, per_pass: int,
    recheck_per_pass: int = 0,
    now: datetime | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> dict:
    """The scheduler RIDE-ALONG (ruling clause (c): "like the world-discovery ride-
    along"): a bounded qualification pass per online collection pass, through the SAME
    guarded transport. Skips honestly under airplane mode (trial fetches ride the
    standing online-consent envelope -- never under airplane); the caller wraps this so
    a failure never breaks a scrape.

    ``should_pause`` defaults to the memory guard's own poll (S5.2), so the whole-corpus
    cohort scan this pass performs can be given up under pressure instead of being the one
    part of a collect pass nothing can interrupt."""
    # Either budget alone is reason enough to run: with `qualification_per_pass=0` and a
    # re-check budget set, an install that has finished admitting candidates still keeps its
    # verdicts verified. Returning early on `per_pass <= 0` alone would have made "stop
    # taking new candidates" silently also mean "stop re-verifying".
    if per_pass <= 0 and recheck_per_pass <= 0:
        return {"enabled": False}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode engaged"}
    return run_qualification_pass(
        session, fetcher, per_pass=max(0, per_pass),
        recheck_per_pass=recheck_per_pass, now=now,
        # S5.2: the ride-along's scan is interruptible too. A pass that gives up returns
        # ``paused`` and stamps NOTHING -- the candidates keep the status they had and the
        # queue's least-recently-attempted ordering brings them back next pass.
        should_pause=should_pause if should_pause is not None else _memory_pause_check,
    )
