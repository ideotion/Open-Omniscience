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
    entry (2026-07-23 livelock fix) is INCONCLUSIVE -- it neither advances nor resets
    the ladder, so it is skipped rather than stopping the count; a source stays at its
    real ladder position until an attempt that actually judges it again."""
    n = 0
    for v in verdicts_newest_first:
        if v == STATUS_DISQUALIFIED:
            n += 1
        elif v == VERDICT_NO_EVIDENCE:
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

    if per_pass <= 0:
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
    if per_pass <= 0:
        return {"enabled": False}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode engaged"}
    return run_qualification_pass(
        session, fetcher, per_pass=per_pass, now=now,
        # S5.2: the ride-along's scan is interruptible too. A pass that gives up returns
        # ``paused`` and stamps NOTHING -- the candidates keep the status they had and the
        # queue's least-recently-attempted ordering brings them back next pass.
        should_pause=should_pause if should_pause is not None else _memory_pause_check,
    )
