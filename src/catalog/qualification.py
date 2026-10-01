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
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func

from src.config.machine_floor import scan_budget
from src.database.models import Article

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.database.models import Source, SourceAdmissionEvent
    from src.ingest import EthicalFetcher

_LOG = logging.getLogger("catalog.qualification")

# The criteria VERSION stamped on every verdict (Source.qualification_criteria_version +
# SourceQualificationAttempt.criteria_version). Bump this if the judging criteria change
# so the history stays honest about which rules judged an old attempt.
CRITERIA_VERSION = "oo-source-qualification-3"
# -3 (B6, 2026-09-15): the criteria SET changed -- `link_density_rate` joins `pathology_rate`
# as a second extraction-failure criterion, so a source can now reach `failing` on two
# independent extraction signatures rather than one signature plus a soft corroborator. That
# is exactly what this field is for: a verdict reached under -2 was measured against a
# different set of criteria, and must read as such in the history rather than be silently
# reinterpreted. Nothing re-judges on a version mismatch -- the field is a LABEL, not a
# trigger -- so bumping it costs no re-qualification pass.
# -2 (S5.1, 2026-09-02 crash analysis): the cohort baselines a verdict is measured against
# are computed ONCE PER RUN and frozen, instead of re-read from the whole corpus for every
# batch of 20. A batch is therefore judged against a baseline up to one run old, and an
# attempt row must not read as though it were judged the old way -- which is exactly what
# this field is for ("a later criteria change is visible in the history rather than
# silently reinterpreted", SourceQualificationAttempt's own docstring). The per-run
# staleness numbers ride the pass RESULT (baseline_token / baseline_articles /
# baseline_age_s), because an age belongs in a measurement and not in a version string.

# FD03 option b (built 2026-09-29, R93): a verdict judged against a COHORT SAMPLE rather than
# the whole corpus carries this label instead, so the history says which baseline judged it.
# Like the -2 bump above it is a LABEL, never a trigger: nothing re-judges on it.
CRITERIA_VERSION_SAMPLED = CRITERIA_VERSION + "+sample"

# How many of the most recently stored articles a sampled cohort is built from. Sized from
# the floor's own measurement (1.2 KB per article, see src.config.machine_floor): 20,000
# articles need ~188 MB with the page cache and overhead, where the whole corpus of the field
# VMs that declined (200k-2M articles) needs 400 MB to 2.5 GB. A percentile over 20,000
# articles is a stable baseline; the whole history was never needed for one.
QUALIFICATION_SAMPLE_ARTICLES = 20_000

# A CANDIDATE'S OWN read is bounded to its newest articles (2026-09-30, follow-up to R93):
# judging N candidates at once used to materialise every candidate's whole history, and the
# candidates that matter most for re-checks are the long-lived ones (hundreds of thousands of
# articles each). The bound is SIZED FROM THE MACHINE (`candidate_history_cap`): half of the
# memory available, less the scan's fixed overhead, divided by the floor's own measured cost
# per article and by the number of candidates in the pass. The constant below is the fallback
# for a machine whose memory cannot be read, and the least a candidate is ever given.
QUALIFICATION_HISTORY_FALLBACK = 2_000
# What the wall-clock budget below protects: a pass runs INSIDE the housekeeping lane, which is
# one lock shared with world discovery, country data, crawl and backfill, and its trial fetches
# are sequential over the polite (often Tor) fetcher -- so cores buy no parallelism there.
# Without a bound, a budget that grows with the machine would hold that lock for hours. The
# candidates not reached are not lost: they were never attempted, so they stay first in line.
_TRIAL_FETCH_BUDGET_S = 600.0
_HISTORY_MEMORY_SHARE = 0.5  # of the available memory a pass may spend on candidate reads

# The adaptive per-pass budgets (maintainer preference 2026-09-29: no fixed caps, limits
# follow the hardware, generous defaults). The configured settings are the FLOOR, and the
# only fixed numbers left are the shipped defaults below, which are that floor.
_AUTO_NEW_MIN = 5
_AUTO_RECHECK_MIN = 2
_AUTO_MB_PER_SLOT = 100.0   # available memory one candidate slot is allowed to claim
_AUTO_SLOTS_PER_CORE = 6    # the pass's fetch, read and judge work per core; the fetches themselves stay sequential (see _TRIAL_FETCH_BUDGET_S)


def candidate_history_cap(n_candidates: int, *, available_mb: float | None = None) -> int:
    """How many of its newest articles each of ``n_candidates`` may be read from this pass.

    The pass may spend ``_HISTORY_MEMORY_SHARE`` of the memory available, less the scan's
    fixed overhead, at the floor's measured cost per article; that budget is shared by the
    candidates. On a large machine this is effectively the whole history, on a small one a
    few thousand, and it is never below ``QUALIFICATION_HISTORY_FALLBACK`` (a candidate is
    always given at least the fallback's worth of evidence) -- which is also what an unreadable
    machine gets. The memory guard's pause still applies inside the read.
    """
    if available_mb is None:
        from src.config.machine_floor import _mem_readings

        available_mb = _mem_readings()[1]
    if available_mb is None:
        return QUALIFICATION_HISTORY_FALLBACK
    from src.config.machine_floor import scan_need_mb

    per_article_mb = (scan_need_mb(1_000_000) - scan_need_mb(0)) / 1_000_000
    budget_mb = available_mb * _HISTORY_MEMORY_SHARE - scan_need_mb(0)
    share = int(budget_mb / per_article_mb / max(1, int(n_candidates))) if budget_mb > 0 else 0
    return max(QUALIFICATION_HISTORY_FALLBACK, share)


def effective_qualification_budgets(settings) -> tuple[int, int]:
    """(new, re-checks) per pass the lane actually runs for ``settings``: the configured
    numbers, grown to the machine while ``qualification_budget_auto`` is on. ONE definition,
    so the lane, the queue view, the activity ledger and the Quality gates panel cannot
    quote different budgets for the same pass."""
    new = int(getattr(settings, "qualification_per_pass", 0))
    rech = int(getattr(settings, "qualification_recheck_per_pass", 0))
    if getattr(settings, "qualification_budget_auto", False):
        b = adaptive_pass_budgets(new, rech)
        return b["new"], b["rechecks"]
    return new, rech


def adaptive_pass_budgets(
    configured_new: int, configured_recheck: int, *,
    available_mb: float | None = None, cpus: int | None = None,
) -> dict:
    """The per-pass qualification budgets this machine can carry, never below what the
    operator configured. Pure given its inputs; ``available_mb=None`` reads the machine.

    An explicit 0 stays 0 (that is how an operator switches a lane off), and an unreadable
    machine returns the configured numbers unchanged. The ceiling is memory / cores because
    that is what a pass actually spends: the scoped read of each candidate (bounded by
    ``candidate_history_cap``) and the trial fetches. The memory guard's pause still
    applies inside the pass, so a generous budget is still given up under pressure.
    """
    if available_mb is None:
        from src.config.machine_floor import _mem_readings

        available_mb = _mem_readings()[1]
    if cpus is None:
        import os

        cpus = os.cpu_count() or 1
    new, rech = int(configured_new), int(configured_recheck)
    if available_mb is None:
        return {"new": new, "rechecks": rech, "auto": False, "available_mb": None, "cpus": cpus}
    # A number BELOW the shipped default is a deliberate lowering (the low power profile writes
    # 2, an operator may write 1) and is kept as given: auto grows a budget, it never overrides
    # someone who asked for less.
    slots = int(min(cpus * _AUTO_SLOTS_PER_CORE, available_mb // _AUTO_MB_PER_SLOT))
    auto_new = max(_AUTO_NEW_MIN, slots)
    auto_rech = max(_AUTO_RECHECK_MIN, auto_new // 2)
    return {
        "new": max(new, auto_new) if new >= _AUTO_NEW_MIN else new,
        "rechecks": max(rech, auto_rech) if rech >= _AUTO_RECHECK_MIN else rech,
        "auto": True, "available_mb": round(float(available_mb), 1), "cpus": cpus,
    }

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
# move the re-verification clock -- see `_last_clock_subquery`.
VERDICT_INHERITED = "inherited"

# A stamp the CURATED CATALOGUE carries BY RULING (maintainer, 2026-09-10: "make the curated
# catalogue qualified, and as with any other qualified sources, they should go through the
# same periodic re-qualification process as any other source"). This AMENDS the 2026-07-20
# no-grandfathering clause: a hand-vetted catalogue row is admitted at seed instead of waiting
# its turn behind a discovery backlog of tens of thousands, and the re-verification
# clock is what keeps the stamp honest -- a failed re-check disqualifies it like any other.
# Like `inherited` and `no_evidence` it is an ATTEMPT-LOG-only verdict, never a Source.status
# value: it records WHY the row reads qualified (curation, not measurement), it neither
# advances nor resets the disqualified ladder, and it starts the local re-verification clock
# exactly as adoption does (see CLOCK_VERDICTS). Scope = `provenance_scope.CURATED_PROVENANCES`.
VERDICT_CURATED = "curated"

# Written to `Source.qualification_criteria_version` by a curated stamp, so the STAMP ITSELF
# says what judged it -- nothing did. A re-check that passes replaces it with the real
# CRITERIA_VERSION; the overlay loader treats it as adoptable (a measured verdict outranks
# curation, in either direction); the export reports it as basis `curated` and never ships it
# as an earned verdict.
CURATED_CRITERIA_VERSION = "oo-curated-catalog-1"

# The verdicts that are actual JUDGEMENTS -- a real evaluation of real evidence, by some
# instance. The other attempt verdicts record why a judgement did NOT happen, or where a
# stamp came from instead.
JUDGING_VERDICTS = (STATUS_QUALIFIED, STATUS_DISQUALIFIED)

# The verdicts that RESET the local re-verification clock. Deliberately WIDER than
# JUDGING_VERDICTS by exactly one entry: adopting a stamp is not a judgement (it never
# touches the ladder, and the export still reports it as basis "inherited"), but it IS the
# moment this instance took responsibility for the source, so it is where the local clock
# starts. `no_evidence` is in neither set -- it records that a judgement could not happen,
# so counting it either way would be a lie in a different direction. `curated` (2026-09-10)
# joins for the same reason as `inherited`: the stamp is not a judgement, but it is the moment
# this instance admitted the source, and "the same periodic re-qualification process as any
# other source" means the re-verification clock starts there.
CLOCK_VERDICTS = (*JUDGING_VERDICTS, VERDICT_INHERITED, VERDICT_CURATED)

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
#
# QUARTERLY (R94, the maintainer 2026-09-29: «source "re-qualification" should be managed as a
# queue, not as a calendar. All sources should be qualified on a regular basis, such as every
# quarter, or semester ... it's more urgent to qualify a new source than to re-qualify an
# existing one»). Was 6. The DISQUALIFIED ladder keeps its 1-2-4-6 months: its cap is the
# semester the same answer names, and the calendar-feed ladder mirrors it by ruling 12. The
# interval only says when a source JOINS the queue; the queue order is the pass's own (new
# candidates first, then the longest-unverified re-check), and nothing runs at a set date.
QUALIFIED_RECHECK_MONTHS = 3

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
    entry (2026-07-23 livelock fix), an ``inherited`` one (2026-09-04) or a ``curated`` one
    (2026-09-10) is INCONCLUSIVE -- none advances or resets the ladder, so all are skipped
    rather than stopping the count; a source stays at its real ladder position until an
    attempt that actually judges it again. Inheriting or curating a stamp is not this
    instance measuring anything, so it must not be able to reset a ladder that real
    failures built."""
    n = 0
    for v in verdicts_newest_first:
        if v == STATUS_DISQUALIFIED:
            n += 1
        elif v in (VERDICT_NO_EVIDENCE, VERDICT_INHERITED, VERDICT_CURATED):
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


def _last_clock_subquery(session: Session):
    """``{source_id: newest attempt that RESET this instance's re-verification clock}``.

    Scoped to ``CLOCK_VERDICTS``: the two real judgements, plus ``inherited``.

    CORRECTION (2026-09-04, maintainer ask). An earlier version of this scoped to
    ``JUDGING_VERDICTS`` and argued that letting an ``inherited`` row move the clock would
    make a stamp from an old catalog "read as verified today -- fabricated freshness". That
    was wrong in KIND. Nothing here claims local verification: ``Source.qualified_at`` still
    holds the ORIGINATING date, the attempt row still says ``inherited``, and the export
    still reports ``basis: inherited``. What the narrow scope actually did was make every
    shipped verdict arrive ALREADY EXPIRED -- any release reaches users more than
    QUALIFIED_RECHECK_MONTHS after it was cut -- so a fresh install spent its qualification
    budget re-verifying the whole shipped catalog on day one. That defeats the accumulation
    the overlay exists for: the point is that a verdict earned once does not have to be
    earned again on every machine.

    Measured before the change: a 10-source overlay stamped 9 months earlier adopted
    cleanly and then reported 10 of 10 already due on the first pass.

    Where the freshness guarantee actually lives is the RELEASE process -- the maintainer
    periodically merges instance exports and re-cuts the overlay, which is the "qualified
    periodically" half of the ruling. Long-running instances still re-verify for real on
    this clock and feed those measurements back. The residual risk, stated rather than
    hidden: a catalog nobody re-cuts ossifies, since each install defers a further
    QUALIFIED_RECHECK_MONTHS. ``build_overlay_export`` reports the age of the inherited
    verdicts so that staleness is visible rather than silent.

    NOTE the asymmetry this repairs: ``select_due_disqualified`` already clocks on
    ``max(attempted_at)`` across ALL attempts, so inherited DISQUALIFIED stamps have always
    deferred from adoption. Only the qualified side read the origin date, which was an
    inconsistency rather than a decision.
    """
    from src.database.models import SourceQualificationAttempt as A

    return (
        session.query(
            A.source_id.label("source_id"),
            func.max(A.attempted_at).label("last_at"),
        )
        .filter(A.verdict.in_(CLOCK_VERDICTS))
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

    THE CLOCK is the newest attempt that reset it -- a real judgement, or the ``inherited``
    row written when a stamp was adopted here (``CLOCK_VERDICTS``; see
    ``_last_clock_subquery`` for why adoption counts and for the correction that made it
    so). It falls back to ``Source.qualified_at`` only when there is no attempt at all,
    which is the pre-existing-corpus case rather than the inherited one.

    So a stamp adopted from a backup or the shipped overlay waits a full interval from the
    day THIS instance took it on, not from the day another instance earned it. That is what
    lets a fresh install start with a working catalog instead of spending its first passes
    re-verifying verdicts that were already paid for elsewhere -- while ``qualified_at``
    keeps the true originating date, so nothing reads as measured here.

    Ordered oldest-clock-first, so the longest-unverified verdict goes first.

    A qualified row with NEITHER a judging attempt NOR a ``qualified_at`` is a data anomaly
    (``evaluate_and_stamp`` always writes both). It is treated as DUE rather than skipped:
    that is the direction that self-heals -- the source is re-judged and stamped properly --
    where skipping would leave it permanently unverifiable and invisible.
    """
    from src.database.models import Source

    if limit <= 0:
        return []
    last_judged = _last_clock_subquery(session)
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


# THE FORCED RE-CHECK LIST (PR 3 of the rank 14 fix, 2026-10-01). A source whose live verdict was
# MEASURED here (or taken from an import) but whose newest JUDGING attempt now disagrees with it --
# typically a verdict another instance reached later, merged in beside ours -- is never changed by
# that history on its own (rule 12 = b). Its own re-check would be due only a re-verification
# interval after the OTHER instance's attempt, because a copied-in attempt resets this instance's
# re-verification clock (``CLOCK_VERDICTS``). So the boot integrity step lists such sources here and
# the pass takes them ahead of the two ordinary pools, within the existing re-check budget: the
# install's own measurement then settles the disagreement.
RECHECK_FIRST_KEY = "qualification.recheck_first"


def _naive_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):     # a stored value of the wrong shape reads as absent
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


# A flagged source whose local re-check keeps NOT settling it (no articles, no feed or sitemap to
# judge it on, an imported attempt dated after this machine's clock) would otherwise be forced
# again whenever it reaches the head of the line, each time with a trial fetch against its host.
# After this many forced tries the entry stays listed (so it is not re-flagged from scratch at
# boot, but the queue view no longer counts it as checked first) and is no longer taken ahead of
# the queue: the ordinary ladder handles it. The count belongs to ONE disagreement: the boot step
# resets it when the attempt that disagrees changes.
MAX_FORCED_TRIES = 3


def _load_recheck_first() -> tuple[dict[int, tuple[datetime, datetime | None, int]], str]:
    """``({source_id: (flagged_at, last_tried_at, tries)}, turn)`` from the stored list.

    ``last_tried_at`` is when THIS install last tried the entry (stamped by the pass, never taken
    from the attempt log, whose newest row for a flagged source is usually the copied-in one that
    inverted it and carries another machine's clock). ``turn`` is which side gets the odd slot of
    an odd budget this pass. An unreadable or absent store reads as empty, which means today's
    order: a pass never fails for want of this list.
    """
    from src.config.kv_store import kv_get_json

    try:
        raw = kv_get_json(RECHECK_FIRST_KEY) or {}
    except Exception:  # noqa: BLE001 - the list is an optimisation of ORDER, never a dependency
        return {}, "ordinary"
    out: dict[int, tuple[datetime, datetime | None, int]] = {}
    flagged_raw = raw.get("flagged")
    for key, entry in (flagged_raw.items() if isinstance(flagged_raw, dict) else ()):
        try:
            sid = int(key)
        except (TypeError, ValueError):
            continue
        tries = 0
        if isinstance(entry, dict):
            flagged, tried = _naive_utc(entry.get("flagged_at")), _naive_utc(entry.get("last_tried_at"))
            raw_tries = entry.get("tries")
            tries = raw_tries if isinstance(raw_tries, int) and not isinstance(raw_tries, bool) else 0
        else:
            flagged, tried = _naive_utc(entry if isinstance(entry, str) else None), None
        out[sid] = (flagged or datetime.min, tried, max(0, tries))
    return out, ("list" if raw.get("turn") == "list" else "ordinary")


def record_forced_tries(ids: set[int], *, now: datetime | None = None, odd_budget: bool = False) -> None:
    """Stamp ``last_tried_at`` on the flagged sources a pass just tried, and hand the odd slot to
    the other side next pass. Called AFTER the pass committed (``kv_set_json`` must never run
    inside an open ORM write transaction). Fails closed and quietly: an unreadable list is left
    exactly as it was, because rewriting it from a failed read would lose the flags."""
    from src.config.kv_store import kv_get_json_strict, kv_set_json

    if not ids and not odd_budget:
        return
    try:
        raw = dict(kv_get_json_strict(RECHECK_FIRST_KEY) or {})
        flagged = {str(k): (dict(v) if isinstance(v, dict) else {"flagged_at": v})
                   for k, v in (raw.get("flagged") or {}).items()}
        moment = now or datetime.now(UTC)
        stamp = (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).replace(
            tzinfo=None).isoformat()
        for sid in ids:
            if str(sid) in flagged:
                flagged[str(sid)]["last_tried_at"] = stamp
                done = flagged[str(sid)].get("tries")
                flagged[str(sid)]["tries"] = (done if isinstance(done, int) else 0) + 1
        raw["flagged"] = flagged
        if odd_budget:
            raw["turn"] = "ordinary" if raw.get("turn") == "list" else "list"
        kv_set_json(RECHECK_FIRST_KEY, raw)
    except Exception:  # noqa: BLE001 - bookkeeping for an ORDER hint never fails a pass
        _LOG.warning("could not record the forced re-check tries", exc_info=True)


def pending_forced_rechecks(session: Session) -> list[Source]:
    """The flagged sources still waiting for their local re-check, LEAST RECENTLY TRIED FIRST.

    An entry is pending while the source exists and is still inverted (its live status differs
    from its newest judging attempt). A local re-check that judges the source settles that --
    ``evaluate_and_stamp`` writes the verdict and the status together -- so the entry clears
    itself, whatever the re-check decided, with no separate bookkeeping.

    THE ORDER is the instant this install last TRIED the entry (``last_tried_at``, stamped by the
    pass after each forced try), never-tried first, then the flag time, then the id. It is not the
    attempt log's newest row: for a flagged source that row is usually the copied-in one that
    inverted it, carrying another machine's clock. A host that stays unreachable writes
    ``no_evidence`` every pass and is stamped each time, so it moves to the back and a dead host
    cannot hold the head of the line; after ``MAX_FORCED_TRIES`` tries that did not settle it the
    entry stops being forced at all. Read-only; the stored list is rewritten only by the boot
    step and, after a pass has committed, by :func:`record_forced_tries`.
    """
    from src.database.models import Source
    from src.database.models import SourceQualificationAttempt as A

    flagged, _turn = _load_recheck_first()
    if not flagged:
        return []
    newest_verdict = (
        session.query(A.verdict)
        .filter(A.source_id == Source.id, A.verdict.in_(JUDGING_VERDICTS))
        .order_by(A.attempted_at.desc(), A.id.desc())
        .limit(1)
        .correlate(Source)
        .scalar_subquery()
    )
    pending: list[tuple[tuple, Source]] = []
    for chunk in _id_chunks(sorted(flagged)):
        for source, verdict in (
            session.query(Source, newest_verdict).filter(Source.id.in_(chunk)).all()
        ):
            at, tried, tries = flagged[int(source.id)]
            if verdict is None or source.status == verdict:
                continue  # no longer inverted: nothing left to settle
            if source.status not in JUDGING_VERDICTS:
                continue  # reset to unqualified since: the new-candidate queue owns it
            if tries >= MAX_FORCED_TRIES:
                continue  # tried here repeatedly without settling: the ordinary ladder takes over
            pending.append(((tried is not None, tried or datetime.min, at, int(source.id)), source))
    pending.sort(key=lambda item: item[0])
    return [source for _key, source in pending]


def allocate_rechecks(
    forced: list[Source], dq_pool: list[Source], ql_pool: list[Source], total: int,
    *, odd_to_list: bool = False,
) -> list[Source]:
    """Split ``total`` re-check slots between the forced list and the two ordinary pools.

    THE SHARE. The forced list takes half of the slots (plus any the ordinary queue cannot use),
    and the ordinary queue keeps the rest. A CONTESTED slot goes to each side in turn, pass by
    pass (``odd_to_list`` says whose turn it is; :func:`record_forced_tries` flips it): with an
    ODD budget the extra slot is contested between the list and the ordinary queue (rounding it up
    for the list would hand a budget of one slot to the list every pass), and when the ordinary
    side is left ONE slot with both its pools due (the default budget of 2) that slot is
    contested between the disqualified and the qualified side, the list's turn giving it to the
    qualified one -- otherwise qualified re-verification would stop while the list has entries
    and a disqualified re-check is due (R94: each queue keeps moving). Both draw on the one budget
    the operator set, and a bulk import can flag thousands. Neither side wastes a slot: what one
    cannot fill goes to the other, and no source is taken twice. Without a forced list this is
    exactly the ordinary split (disqualified first, half each while both are due).
    """
    return allocate_rechecks_detail(forced, dq_pool, ql_pool, total, odd_to_list=odd_to_list)[0]


def allocate_rechecks_detail(
    forced: list[Source], dq_pool: list[Source], ql_pool: list[Source], total: int,
    *, odd_to_list: bool = False,
) -> tuple[list[Source], bool]:
    """:func:`allocate_rechecks` plus whether a CONTESTED slot was decided this pass (the caller
    then hands the turn to the other side, see :func:`record_forced_tries`)."""
    if total <= 0:
        return [], False
    share = (total // 2 + (1 if odd_to_list and total % 2 else 0)) if forced else 0
    taken = forced[:share]
    taken_ids = {int(x.id) for x in taken}
    dq = [x for x in dq_pool if int(x.id) not in taken_ids]
    ql = [x for x in ql_pool if int(x.id) not in taken_ids]
    room = total - len(taken)
    contested = bool(forced) and (total % 2 == 1)
    if room <= 0:
        take_dq = take_ql = 0
    elif forced and room == 1 and dq and ql:
        take_dq, take_ql = (0, 1) if odd_to_list else (1, 0)
        contested = True
    else:
        take_dq = min(len(dq), max(1, room // 2) if ql else room)
        take_ql = min(len(ql), room - take_dq)
        take_dq = min(len(dq), room - take_ql)
    chosen = taken + dq[:take_dq] + ql[:take_ql]
    # slots the ordinary pools could not use go back to the forced list; a source already chosen
    # (a flagged one can also be due in an ordinary pool) is never taken twice
    spare = total - len(chosen)
    if spare > 0:
        chosen_ids = {int(x.id) for x in chosen}
        chosen += [x for x in forced[share:] if int(x.id) not in chosen_ids][:spare]
    return chosen, contested


# How far down the due-disqualified pool the queue view counts. Each one costs a ladder read,
# so a count past this says "at least" rather than walking an unbounded pool on a panel load.
_QUEUE_COUNT_CAP = 200


def qualification_queue(session: Session, *, now: datetime | None = None,
                        next_limit: int = 10,
                        recheck_per_pass: int | None = None) -> dict:
    """THE QUALIFICATION QUEUE, as the pass will take it (R94, 2026-09-29: «managed as a queue,
    not as a calendar ... it's more urgent to qualify a new source than to re-qualify one»).

    Read-only, counts and domains only, never a score. Built from the SAME selectors the pass
    calls (``select_unqualified``, ``select_due_disqualified``, ``select_due_qualified``), so
    the view cannot describe an order the pass does not follow:

    1. ``new`` -- never-judged sources, never-tried first, then the least recently tried (a
       source whose trial found nothing to judge goes back in line behind the untried ones);
    2. ``rechecks`` -- sources whose verdict has come due: a disqualified source on its
       1-2-4-6-month ladder, a qualified one every ``QUALIFIED_RECHECK_MONTHS`` months,
       the longest-unverified first.

    ``waiting`` counts qualified sources not yet due, with the earliest moment one joins the
    queue -- the one date on this view, and it is when a source ENTERS the line, never when
    it will be judged: that depends on the per-pass budgets and on how long the line is.

    ``recheck_per_pass`` (the setting) is what tells the view whether qualified re-verification
    is ON: at 0 the pass takes no qualified source, spill included, so the view lists none and
    says ``qualified_rechecks_on: false`` rather than naming a line that never moves.
    """
    from src.database.models import Source, SourceQualificationAttempt

    now = now or datetime.now(UTC)
    attempted = session.query(SourceQualificationAttempt.source_id).distinct().subquery()
    unq = session.query(Source).filter(Source.status == STATUS_UNQUALIFIED)
    new_total = int(unq.count())
    new_untried = int(
        unq.filter(~Source.id.in_(session.query(attempted.c.source_id))).count()
    )

    dq_due = select_due_disqualified(session, now=now, limit=_QUEUE_COUNT_CAP)
    cutoff = now - timedelta(days=_MONTH_DAYS * QUALIFIED_RECHECK_MONTHS)
    clock = _last_clock_subquery(session)
    when = func.coalesce(clock.c.last_at, Source.qualified_at)
    ql = (
        session.query(func.count())
        .select_from(Source)
        .outerjoin(clock, clock.c.source_id == Source.id)
        .filter(Source.status == STATUS_QUALIFIED)
    )
    # A qualified row with no clock at all is DUE (the self-healing direction
    # `select_due_qualified` takes), so it is counted as due here too.
    ql_due = int(ql.filter((when.is_(None)) | (when <= cutoff)).scalar() or 0)
    ql_waiting = int(ql.filter(when > cutoff).scalar() or 0)
    next_join = (
        session.query(func.min(when))
        .select_from(Source)
        .outerjoin(clock, clock.c.source_id == Source.id)
        .filter(Source.status == STATUS_QUALIFIED, when > cutoff)
        .scalar()
    )
    if next_join is not None and next_join.tzinfo is None:
        next_join = next_join.replace(tzinfo=UTC)

    nxt = max(0, int(next_limit))
    ql_on = recheck_per_pass is None or recheck_per_pass > 0
    next_new = [s.domain for s in select_unqualified(session, limit=nxt)]
    # The "next" list is what a pass with `nxt` re-check slots WOULD take: the pass's own pool
    # (the oldest-tried few, not the whole due count) and its own split between the two kinds.
    forced = pending_forced_rechecks(session) if ql_on else []
    nxt_pool = nxt + ((nxt + 1) // 2 if forced else 0)
    dq_pool = select_due_disqualified(session, now=now, limit=nxt_pool)
    ql_pool = select_due_qualified(session, now=now, limit=nxt_pool) if ql_on else []
    next_rechecks = [
        {"domain": s.domain, "status": s.status}
        for s in allocate_rechecks(
            forced, dq_pool, ql_pool, nxt,
            odd_to_list=bool(forced) and _load_recheck_first()[1] == "list")
    ]
    return {
        "order": ["new", "rechecks"],
        "new": {"total": new_total, "untried": new_untried,
                "tried_without_evidence": new_total - new_untried, "next": next_new},
        "rechecks": {
            "disqualified_due": len(dq_due),
            "disqualified_due_capped": len(dq_due) >= _QUEUE_COUNT_CAP,
            "qualified_due": ql_due if ql_on else 0,
            "qualified_rechecks_on": ql_on,
            "flagged": len(forced),
            "next": next_rechecks,
        },
        "waiting": {
            "qualified": ql_waiting,
            "next_joins_at": _audit_stamp(next_join + timedelta(
                days=_MONTH_DAYS * QUALIFIED_RECHECK_MONTHS)) if next_join else None,
        },
        "cycle": {"qualified_months": QUALIFIED_RECHECK_MONTHS,
                  "disqualified_ladder_months": [1, 2, 4, _LADDER_CAP_MONTHS]},
        "method": (
            "Read from the selectors the qualification pass itself calls, in the order it "
            "takes them: new candidates first, then due re-checks, the longest-unverified "
            "first. Counts and domains only."
        ),
    }


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


def log_curated_stamps(session: Session, sources: list[Source], *, now: datetime) -> int:
    """Record that each source's stamp comes from the CURATED CATALOGUE (2026-09-10 ruling),
    not from a measurement. Append-only like every other attempt row; ``Source.status`` is
    the caller's to set. The attempt carries ``CURATED_CRITERIA_VERSION`` because no judging
    criteria were applied, and a history that named one would be a lie about what happened."""
    from src.database.models import SourceQualificationAttempt

    for source in sources:
        session.add(SourceQualificationAttempt(
            source_id=source.id, attempted_at=now, verdict=VERDICT_CURATED,
            criteria_version=CURATED_CRITERIA_VERSION,
        ))
    return len(sources)


# SQLite caps host parameters at 999 before 3.32, and the SQLCipher builds this app ships
# against vary by platform. Anything that builds an IN clause from a collection whose size
# the catalogue decides goes through here, so a bigger catalogue can never become a runtime
# error on somebody's older install. 400 leaves room for the rest of a statement's binds.
_ID_CHUNK = 400


def _id_chunks(ids: list[int], size: int = _ID_CHUNK):
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def stamp_curated_catalog(session: Session, *, now: datetime | None = None) -> dict:
    """Admit the curated catalogue by ruling (maintainer, 2026-09-10) -- the seed-time and
    boot-time reconcile that stamps every hand-vetted catalogue row ``qualified``.

    WHAT IT TOUCHES, and only that: rows in ``provenance_scope.CURATED_PROVENANCES`` that
    still read ``unqualified`` AND have never been JUDGED (no attempt row with a judging
    verdict). Everything else is left exactly as it is:

    * a ``disqualified`` catalogue row keeps its verdict -- the ruling admits the catalogue,
      it does not launder a source this instance measured and refused;
    * a ``qualified`` row (measured, inherited, or stamped by an earlier boot) is not
      re-stamped, so the clock it already carries is never restarted;
    * a discovered, cited or hand-added row is out of scope by provenance, whatever it reads.

    Idempotent: a stamped row stops matching (``qualified`` is not ``unqualified``), so every
    later boot is one indexed query and no writes. Runs AFTER ``apply_overlay`` at boot, so a
    shipped, measured verdict for a catalogue domain -- a ``disqualified`` in particular --
    lands first and wins.

    Returns counts, kept apart because they are different facts: ``stamped`` (this call),
    ``already_qualified`` (an earlier boot, a measurement, or an adoption), ``disqualified``
    (measured and refused; untouched), ``kept_local`` (an unqualified row that nevertheless
    carries a judging attempt -- an anomaly this never overwrites), ``curated`` (the scope).
    """
    from src.catalog.provenance_scope import curated_catalogue_domains, is_curated_tags
    from src.database.models import Source, SourceQualificationAttempt

    now = now or datetime.now(UTC)
    # SCOPE = the provenance tag OR the catalogue itself, and the two answer different
    # halves. The TAG catches a row the seeder created whose domain has since been retired
    # from the shipped file -- a catalogue edit must not silently un-qualify a running
    # instance. CATALOGUE MEMBERSHIP catches a shipped domain whose row never got a tag,
    # which is every row on an install older than tagging (2026-06-08); see
    # `curated_catalogue_domains` for the field report and the measurement.
    #
    # Decided in PYTHON over three columns rather than through a `domain IN (...)` of the
    # ~6,400 curated domains, deliberately: SQLite caps host parameters at 999 before
    # 3.32, and the SQLCipher builds this app ships against vary by platform, so a large
    # IN would raise "too many SQL variables" on exactly the older installs this fixes.
    # The scan is three columns over a table of thousands, already indexed by nothing it
    # needs -- cheap next to the catalogue parse it sits beside at boot.
    domains = curated_catalogue_domains()
    counts = {"curated": 0, "stamped": 0, "already_qualified": 0, "disqualified": 0,
              "kept_local": 0}
    pending_ids: list[int] = []
    for sid, domain, tags, status in session.query(
        Source.id, Source.domain, Source.tags, Source.status
    ):
        if not (is_curated_tags(tags) or str(domain or "").strip().lower() in domains):
            continue
        counts["curated"] += 1
        if status == STATUS_QUALIFIED:
            counts["already_qualified"] += 1
        elif status == STATUS_DISQUALIFIED:
            counts["disqualified"] += 1
        elif status == STATUS_UNQUALIFIED:
            pending_ids.append(int(sid))
    if not pending_ids:
        return counts
    judged = {
        int(sid)
        for (sid,) in session.query(SourceQualificationAttempt.source_id)
        .filter(SourceQualificationAttempt.verdict.in_(JUDGING_VERDICTS))
        .distinct()
    }
    to_stamp = [sid for sid in pending_ids if sid not in judged]
    counts["kept_local"] = len(pending_ids) - len(to_stamp)
    stamped: list[Source] = []
    for chunk in _id_chunks(to_stamp):          # chunked for the same 999-parameter reason
        for source in session.query(Source).filter(Source.id.in_(chunk)):
            source.status = STATUS_QUALIFIED
            source.qualified_at = now
            source.qualification_criteria_version = CURATED_CRITERIA_VERSION
            stamped.append(source)
    if stamped:
        log_curated_stamps(session, stamped, now=now)
        session.commit()
    counts["stamped"] = len(stamped)
    return counts


def is_collectable(enabled: bool | None, status: str | None) -> bool:
    """Can regular collection reach a source in this state?

    THE ONE AUTHORITY on that question, in Python. ``select_sources`` asks it in SQL
    (``enabled=True AND status == STATUS_QUALIFIED``) and this is the same predicate for a
    row already in hand -- the admission audit needs it to decide whether a verdict
    ADMITTED anything, and two separate readings of "is this source collecting" is exactly
    how a surface and a gate come to disagree about one quantity.

    ``enabled`` is three-valued: NULL means "never set", which is not True, so a
    never-set source is not collecting. That matches the SQL, where ``enabled=True``
    excludes NULL.
    """
    return enabled is True and status == STATUS_QUALIFIED


def record_admission(
    session: Session, source: Source, *,
    prior_enabled: bool | None, prior_status: str | None,
    now: datetime, verdict: str, criteria_version: str,
) -> bool:
    """Write the audit row when a write has just made a source COLLECTABLE that was not.

    THE ONE PLACE AN ADMISSION IS RECORDED, because there is more than one way into
    collection. ``evaluate_and_stamp`` is the one Q1101 names; the SHIPPED OVERLAY is the
    other, and an adversarial pass live-reproduced it going unrecorded: a catalogue row
    (``enabled=True``, awaiting a verdict) adopting a shipped ``qualified`` verdict went
    from ``select_sources`` returning nothing to returning it, with no audit row and so
    nothing to undo. Exactly the defect the audit's own unit was rewritten to close, alive
    in a path that fix never touched -- which is why the decision lives here rather than
    inline at each call site.

    Both ends are checked against ``is_collectable``: this returns False for a source that
    was ALREADY collecting (a re-check is not an admission) and for one that still is not
    (a stamp that admits nothing is not an admission either). ``prior_*`` are read by the
    caller BEFORE it writes, because the row's purpose is to put the source back.
    """
    from src.database.models import SourceAdmissionEvent

    if is_collectable(prior_enabled, prior_status):
        return False
    if not is_collectable(source.enabled, source.status):
        return False
    session.add(SourceAdmissionEvent(
        source_id=source.id, occurred_at=now, verdict=verdict,
        criteria_version=criteria_version,
        prior_enabled=prior_enabled, prior_status=prior_status,
    ))
    return True


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
    admitted = 0
    qualified_ids: list[int] = []
    for source in sources:
        fails = fails_by_source.get(source.id, [])
        verdict = decide_verdict(fails)
        session.add(SourceQualificationAttempt(
            source_id=source.id, attempted_at=now, verdict=verdict,
            criteria_version=criteria_version,
        ))
        # Q1101 = a (2026-09-15): QUALIFICATION IS THE ADMISSION GATE. Read the prior
        # state BEFORE anything is written, because the audit row's whole purpose is to
        # let an operator put it back -- and `enabled` is three-valued (True / False /
        # NULL = never set), so the prior value is captured as-is rather than coerced.
        prior_enabled = source.enabled
        prior_status = source.status
        source.status = verdict
        if verdict == STATUS_QUALIFIED:
            source.qualified_at = now
            source.qualification_criteria_version = criteria_version
            qualified += 1
            qualified_ids.append(source.id)
            # THE FLIP, and ONLY on this verdict. `disqualified` never reaches here, and
            # a source that produced no evidence never reaches `evaluate_and_stamp` at
            # all (`log_no_evidence_attempts` handles it and touches neither status nor
            # `enabled`) -- which is what keeps the 2026-07-24 inversion class closed:
            # a never-judged source cannot be admitted by an absence of findings.
            source.enabled = True
            # THE AUDIT'S UNIT IS "BECAME COLLECTABLE", NOT "`enabled` CHANGED".
            #
            # An earlier cut of this recorded a row only when `enabled` itself moved, and
            # an adversarial pass live-reproduced what that misses: the shipped catalogue
            # seeds essentially every source `enabled: true`, so the ordinary first
            # qualification of a catalogue source goes `enabled=True/unqualified` ->
            # `enabled=True/qualified` -- from excluded to actively scraped -- while
            # `enabled` never moves and no row was written. The same hole swallowed every
            # re-admission on the disqualification ladder, where `enabled` stays True
            # across the whole cycle. That is the recorded "a proxy for a fact drifts from
            # it" defect: `enabled` moving was a PROXY for admission, and the FACT is
            # whether collection can now reach the source.
            #
            # So the predicate is the gate itself (`select_sources`), read through the one
            # shared helper both call -- which is what stops the two drifting apart again.
            if record_admission(
                session, source, prior_enabled=prior_enabled, prior_status=prior_status,
                now=now, verdict=verdict, criteria_version=criteria_version,
            ):
                admitted += 1
        else:
            source.qualified_at = None
            source.qualification_criteria_version = None
            disqualified += 1
    # C15 (2026-07-24 throughput brief, S-E slice 2): qualified_ids is returned
    # (never enqueued HERE, before the caller's own commit) so the caller can
    # enqueue archive backfill only AFTER the "qualified" stamp is actually
    # committed -- a rollback between this call and the commit must never
    # queue a backfill for a source that was never really admitted.
    return {
        "qualified": qualified,
        "disqualified": disqualified,
        "qualified_ids": qualified_ids,
        # How many of those `qualified` stamps actually ADMITTED a source that was not
        # already collecting. A re-check of an enabled source is a qualified verdict and
        # not an admission, so reporting `qualified` where a reader wants "how many new
        # sources did this pass let in" would over-state it on every later pass.
        "admitted": admitted,
    }


def _audit_stamp(value: datetime | None) -> str | None:
    """An audit timestamp as the panel should receive it: whole seconds, zone stated.

    The columns hold naive UTC (every writer strips the zone), and an undo stamps the
    live clock, so a bare ``isoformat()`` sent ``2026-09-26T19:56:47.189553`` beside
    seeded rows reading to the second -- and, being zone-less, a browser parses it as
    LOCAL time. Stated as UTC here, the client can render it in the reader's own zone
    and language through the shared date formatter. Storage is untouched."""
    if value is None:
        return None
    stamped = value if value.tzinfo else value.replace(tzinfo=UTC)
    return stamped.astimezone(UTC).isoformat(timespec="seconds")


def admission_audit(
    session: Session, *, limit: int = 100, include_undone: bool = True,
) -> dict:
    """The AUDIT VIEW behind Q1101's safety valve: every automatic ``enabled`` flip this
    instance has made, newest first, with the state each one replaced.

    Counts are taken over the WHOLE table and the LIST is what the limit bounds -- the
    anti-capping rule (a displayed figure is never secretly a cap). ``shown`` and
    ``total`` are both published so a reader can tell a short list from a short history.
    """
    from src.database.models import Source, SourceAdmissionEvent

    q = session.query(SourceAdmissionEvent)
    if not include_undone:
        q = q.filter(SourceAdmissionEvent.undone_at.is_(None))
    total = int(q.count())
    undone_total = int(
        session.query(func.count(SourceAdmissionEvent.id))
        .filter(SourceAdmissionEvent.undone_at.isnot(None))
        .scalar()
        or 0
    )
    rows = q.order_by(SourceAdmissionEvent.occurred_at.desc(), SourceAdmissionEvent.id.desc()).limit(
        max(1, int(limit))
    ).all()

    names: dict[int, tuple[str, str]] = {}
    # The ROW ITSELF, not only its name, because reversibility is a question about the
    # source's CURRENT state and `admission_undo_refusal` is what answers it.
    srcs: dict[int, Source] = {}
    if rows:
        for src_row in (
            session.query(Source)
            .filter(Source.id.in_([r.source_id for r in rows]))
            .all()
        ):
            srcs[int(src_row.id)] = src_row
            names[int(src_row.id)] = (str(src_row.domain or ""), str(src_row.name or ""))

    events = []
    for r in rows:
        domain, name = names.get(int(r.source_id), ("", ""))
        # WHY THE PANEL ASKS AT ALL: an Undo button that renders unconditionally claims a
        # capability, and this endpoint would have refused it for two whole classes of row
        # (a later admission standing, a later verdict replacing this one). Reading the
        # refusal HERE, through the same function the undo raises from, is what keeps the
        # button and the handler from disagreeing about one row.
        refusal = admission_undo_refusal(session, r, srcs.get(int(r.source_id)))
        events.append({
            "id": int(r.id),
            "source_id": int(r.source_id),
            "domain": domain,
            "name": name,
            "occurred_at": _audit_stamp(r.occurred_at),
            "verdict": r.verdict,
            "criteria_version": r.criteria_version,
            "prior_enabled": r.prior_enabled,
            "prior_status": r.prior_status,
            "undone_at": _audit_stamp(r.undone_at),
            "undone": r.undone_at is not None,
            # Two fields, never one: `reversible` is the decision the panel acts on and
            # `blocked_by` is WHY, as a token the client keys ×12. `blocked_by` is None
            # exactly when `reversible` is True, so neither has to stand in for the other.
            "reversible": refusal is None,
            "blocked_by": refusal,
        })
    # WHAT THIS AUDIT DOES NOT COVER, counted rather than described.
    #
    # The audit records admissions made by the qualification ENGINE'S VERDICT. It is not
    # the whole population of "how did this source come to be collecting": the shipped
    # curated catalogue stamps its own domains at boot (`stamp_curated_catalog`), a
    # shipped overlay can carry an inherited stamp (`qualification_overlay.apply_overlay`),
    # and a restore-merge copies another corpus's `enabled`/`status` verbatim. None of
    # those is an unattended judgement by this engine, so none writes an admission row --
    # and a panel that said "every admission" while three other routes existed would be
    # making a claim its own table cannot support. So the DIFFERENCE is published: how
    # many sources collection can currently reach, and how many of those this audit can
    # account for. A gap is published as a gap.
    collecting = int(
        session.query(func.count(Source.id))
        .filter(Source.enabled.is_(True), Source.status == STATUS_QUALIFIED)
        .scalar()
        or 0
    )
    accounted = int(
        session.query(func.count(func.distinct(SourceAdmissionEvent.source_id)))
        .join(Source, Source.id == SourceAdmissionEvent.source_id)
        .filter(
            SourceAdmissionEvent.undone_at.is_(None),
            Source.enabled.is_(True),
            Source.status == STATUS_QUALIFIED,
        )
        .scalar()
        or 0
    )
    return {
        "events": events,
        "shown": len(events),
        "total": total,
        "undone_total": undone_total,
        "collecting": collecting,
        "accounted_for": accounted,
        "unaccounted": max(0, collecting - accounted),
        "method": (
            "Every row is one automatic admission: the qualification engine judged the "
            "source's extraction valid, so collection can now reach it. The stored prior "
            "state is what an undo restores. A row is written when a verdict makes a "
            "source COLLECTABLE -- not merely when it changes the enabled flag, because "
            "a catalogue source is already enabled and is admitted by the verdict alone."
        ),
        # Both are drawn on the Quality gates panel and are keys in all twelve locales, so
        # they are written with the typographic dash the rest of the UI uses: the ASCII
        # "--" showed only in English (re-walk S-9).
        "caveat": (
            "Admission is about EXTRACTION VALIDITY only — never editorial merit, and "
            "never a score. An undo reverses this instance's decision; it does not "
            "disqualify the source, so a later pass may admit it again."
        ),
        "coverage_note": (
            "This lists admissions made by judging. Sources can also be collecting "
            "because they came stamped in the shipped catalogue, carried an inherited "
            "stamp, or arrived in a restored backup — those are not judgements made "
            "here and have no row to undo."
        ),
    }


class AdmissionUndoRefused(Exception):
    """A named refusal, so a caller can tell 'we declined' from 'we crashed'."""


# The closed vocabulary of reasons an admission cannot be reversed. Tokens, never prose:
# the UI translates them (a reason string is documentation for a reader, so it is subject
# to i18n), and a token is what a closed vocabulary must be so the renderer can key it.
UNDO_ALREADY_UNDONE = "already-undone"
UNDO_LATER_ADMISSION = "later-admission-in-effect"
UNDO_LATER_VERDICT = "later-verdict-in-effect"
UNDO_SOURCE_GONE = "source-no-longer-exists"

# The English sentence each token raises to a DIRECT API caller. The rendered panel does
# not read these -- it keys the token ×12 -- so they are the backstop for someone driving
# the endpoint, and they say what is standing rather than only that the undo was refused.
UNDO_REFUSAL_MESSAGES = {
    UNDO_ALREADY_UNDONE: "this admission was already undone",
    UNDO_SOURCE_GONE: "the source this admission refers to no longer exists",
    UNDO_LATER_ADMISSION: (
        "a later admission of this source is still in effect; undo that one first"
    ),
    UNDO_LATER_VERDICT: (
        "a later verdict replaced this one, so this admission is no longer in effect "
        "and collection already cannot reach the source"
    ),
}


def admission_undo_refusal(
    session: Session, ev: SourceAdmissionEvent, source: Source | None
) -> str | None:
    """THE ONE AUTHORITY on whether an admission can still be reversed.

    Returns a token from the closed vocabulary above, or ``None`` when the undo may run.
    Both the undo itself and the AUDIT VIEW call this, because a panel that draws an Undo
    button the endpoint will always refuse is the surface claiming a capability it does
    not have -- and two separate readings of "is this reversible" is how a button and a
    handler come to disagree about one row.
    """
    from src.database.models import SourceAdmissionEvent  # module convention: lazy import

    if ev.undone_at is not None:
        return UNDO_ALREADY_UNDONE
    if source is None:
        return UNDO_SOURCE_GONE
    # THE ORDER OF THESE TWO REFUSALS IS LOAD-BEARING, and an adversarial pass
    # live-reproduced why it has to be THIS one: a refusal that gives ADVICE must give
    # advice that works. `later-admission-in-effect` tells the operator "undo that one
    # first" -- and when a later verdict has taken the source out of `qualified`, the
    # event it points AT is refused too, for this very reason, so the operator follows a
    # refusal into a second refusal and no row for that source can be reversed at all.
    # Reading the source's CURRENT state first makes the advice true by construction: a
    # row is only ever told to defer to a newer admission while the source is still
    # qualified, which is exactly when that newer admission is itself reversible. Put the
    # cheaper query first and that property is lost, for no gain a caller can see.
    #
    # A LATER VERDICT IS THE SAME CLASS OF EVENT AS A LATER ADMISSION, and it was not
    # guarded at all until this pass. Found by the skeptic pass Q1101's own acceptance
    # asks for, and REPRODUCED live before it was believed: admit -> a later pass
    # DISQUALIFIES -> the operator undoes the original admission. The disqualification
    # writes no admission row, so the admission guard below is structurally blind to it;
    # the undo then restored `prior_status = "unqualified"` over a `disqualified` the
    # engine had reached on its own evidence.
    #
    # MEASURED, on the real selectors: a disqualified source waits out its backoff ladder
    # (`select_due_disqualified`, 1 -> 2 -> 4 -> 6 months; not due at +0d or +20d, due at
    # +40d), and after the undo it is in `select_unqualified` THE SAME DAY with no ladder
    # at all. So the undo did not merely rewrite a column: it returned a source the engine
    # had judged and refused to the un-laddered trial queue -- the recorded laundering
    # direction ("known-bad sources back into the trial queue with their backoff ladder
    # reset"), reached through a path that lesson never touched.
    #
    # By this point the admission is not in effect ANYWAY -- the source is not collecting,
    # so there is nothing left for an undo to take back. Refusing therefore costs the
    # operator nothing real and cannot erase a verdict; the token names the later one so
    # the panel can say which decision is standing.
    if source.status != STATUS_QUALIFIED:
        return UNDO_LATER_VERDICT
    # A source can be admitted more than once (admit, the operator disables it, a later
    # pass admits it again), and each event stores the state IT replaced. Undoing the
    # OLDER one writes a prior state that the newer admission has since superseded -- so
    # the source silently takes a value from two decisions ago, while the newer event
    # still renders as live and reversible, inviting a second click that would revive a
    # status the operator had deliberately cleared.
    #
    # Refuse, rather than silently reordering: which admission an operator meant to
    # reverse is their decision, and the honest move is to tell them a later one is in
    # effect. Undone events do not block -- only one still standing can be superseded.
    newer = (
        session.query(SourceAdmissionEvent)
        .filter(
            SourceAdmissionEvent.source_id == ev.source_id,
            SourceAdmissionEvent.undone_at.is_(None),
            SourceAdmissionEvent.id != ev.id,
            SourceAdmissionEvent.occurred_at >= ev.occurred_at,
        )
        .order_by(SourceAdmissionEvent.occurred_at.desc(), SourceAdmissionEvent.id.desc())
        .first()
    )
    if newer is not None and (newer.occurred_at, newer.id) > (ev.occurred_at, ev.id):
        return UNDO_LATER_ADMISSION
    return None


def undo_admission(session: Session, event_id: int, *, now: datetime) -> dict:
    """Reverse ONE automatic admission, restoring BOTH halves of the prior state.

    Restoring only ``enabled`` would leave a source stamped ``qualified`` and disabled --
    a state the next pass has no reason to re-examine and no surface reports as reversed,
    so the undo would look like it worked and quietly strand the row. The stamp columns
    (``qualified_at`` / ``qualification_criteria_version``) follow the status for the same
    reason: a cleared status beside a live ``qualified_at`` is two answers to one question.

    Append-only: the event is STAMPED, never deleted. Every refusal is by NAME, and every
    one of them comes from :func:`admission_undo_refusal` -- the same predicate the audit
    view reads to decide whether to offer the button at all.
    """
    from src.database.models import Source, SourceAdmissionEvent

    ev = session.get(SourceAdmissionEvent, int(event_id))
    if ev is None:
        raise AdmissionUndoRefused("no such admission event")
    source = session.get(Source, int(ev.source_id))
    refusal = admission_undo_refusal(session, ev, source)
    if refusal is not None:
        raise AdmissionUndoRefused(UNDO_REFUSAL_MESSAGES[refusal])
    assert source is not None  # nosec B101 - admission_undo_refusal returns a token first

    source.enabled = ev.prior_enabled
    # NARROWED, not cast. `Source.status` is NOT NULL with `server_default="unqualified"`,
    # so a stored `prior_status` of NULL cannot be written back as one -- and NULL on that
    # column means exactly what "unqualified" means there, never judged. `prior_status` is
    # nullable in the audit table anyway, because a column that can only ever hold one
    # shape is a column nobody checks; a cast would assert the union away and turn a
    # legacy row into a constraint violation at flush, where this lands on the value the
    # schema itself calls "no verdict".
    source.status = ev.prior_status if ev.prior_status is not None else STATUS_UNQUALIFIED
    if ev.prior_status != STATUS_QUALIFIED:
        source.qualified_at = None
        source.qualification_criteria_version = None
    ev.undone_at = now
    session.commit()
    return {
        "undone": True,
        "event_id": int(ev.id),
        "source_id": int(source.id),
        "domain": source.domain,
        "restored_enabled": ev.prior_enabled,
        "restored_status": ev.prior_status,
    }


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


def cohort_plan(session: Session, *, articles: int | None = None) -> dict:
    """WHICH baseline a qualification pass can afford on this machine right now (FD03 b).

    THE ONE PLACE the question is answered, because three surfaces ask it -- the pass itself,
    the Sources panel (whether the bulk button can start) and the release run's arm step --
    and two estimators giving opposite answers is exactly what the 2026-09-24 field round
    found (QUAL-1: the arm step called the job safe, the pass declined).

    * ``whole``    -- above the memory floor (or overridden): the whole-corpus cohort, as
      before this existed. Byte-identical for every machine that could already qualify.
    * ``sample``   -- below the floor, and the bounded sample fits in what is available (or
      availability cannot be read, which never declines -- the floor's own rule): the cohort
      is built from the newest ``QUALIFICATION_SAMPLE_ARTICLES`` articles. THE FLOOR STAYS
      (FD03 = a): the whole-corpus scan is still declined; the gate no longer depends on it.
    * ``declined`` -- below the floor AND the sample does not fit either: nothing is judged,
      and the result names both needs, so the refusal is a measurement.
    """
    from src.config.machine_floor import scan_need_mb

    n = _corpus_articles(session) if articles is None else int(articles)
    budget = scan_budget(n)
    sample = min(QUALIFICATION_SAMPLE_ARTICLES, n) if n else QUALIFICATION_SAMPLE_ARTICLES
    sample_need = scan_need_mb(sample)
    avail = budget.get("available_mb")
    if not budget["declines"]:
        mode = "whole"
    elif avail is None or avail >= sample_need:
        mode = "sample"
    else:
        mode = "declined"
    return {
        "mode": mode,
        "budget": budget,
        "sample_articles": QUALIFICATION_SAMPLE_ARTICLES,
        "sample_need_mb": sample_need,
        "available_mb": avail,
    }


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
    #
    # FD03 option b (2026-09-29, R93): below the floor the pass no longer declines outright.
    # Every field VM sits at 3.8 GiB, under the 4 GiB floor, so this return fired on every
    # pass of every one of them and no source was ever judged -- 80,000 candidates waited on
    # one machine with a qualified count that never moved. The whole-corpus scan stays
    # declined; the cohort is built from a bounded sample instead (see ``cohort_plan``), and
    # the pass declines only when even the sample does not fit.
    plan = cohort_plan(session)
    budget = plan["budget"]
    if plan["mode"] == "declined":
        return {
            "enabled": True,
            "evaluated": 0,
            "skipped": budget["skipped"],
            "available_mb": budget["available_mb"],
            "need_mb": budget["need_mb"],
            # What the bounded sample would have needed -- the refusal names both, so a
            # reader can see the pass did not merely decline the scan it could not afford.
            "sample_need_mb": plan["sample_need_mb"],
            "reason": budget["reason"],
            # The reason's keyed frame, so the refusal is written in the UI language.
            "reason_i18n": budget.get("reason_i18n"),
            "reason_vars": budget.get("reason_vars"),
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

    # THE QUEUE ORDER (R94, 2026-09-29): new candidates first, then due re-checks, oldest
    # clock first. Both re-check kinds may use the reserved budget AND the new candidates'
    # unused slots -- except that with `qualification_recheck_per_pass = 0` qualified
    # re-verification is OFF and takes nothing, spill included: a setting that does not
    # mean what it says is worse than no setting. (Until R94 qualified re-checks took only
    # the reserved budget, so a drained backlog still re-verified at two per pass.)
    total = reserved + spill
    dq_pool: list[Source] = []
    ql_pool: list[Source] = []
    # THE FORCED LIST (see RECHECK_FIRST_KEY) rides the same re-check budget, so `reserved == 0`
    # (re-checks switched off) switches it off too. The ordinary pools are queried a share deeper,
    # because a flagged source can also sit in one of them and is taken from the list instead.
    forced = pending_forced_rechecks(session) if reserved > 0 and total > 0 else []
    odd_to_list = _load_recheck_first()[1] == "list" if forced else False
    pool_limit = total + ((total + 1) // 2 if forced else 0)
    if total > 0:
        # Each pool is queried once at the budget it could possibly use, then allocated, so
        # an empty or short pool gives its slots to the other rather than wasting them.
        dq_pool = select_due_disqualified(session, now=now, limit=pool_limit)
    if reserved > 0:
        # R94 (2026-09-29, «a queue, not a calendar»): once the new candidates are served,
        # their unused slots go on down the queue to EITHER kind of re-check, so a drained
        # backlog re-verifies at the full per-pass rate instead of at the reserved trickle.
        # `recheck_per_pass = 0` still turns qualified re-verification OFF: the spill reaches
        # this query only when the operator has it on, so "off" keeps meaning off. Querying
        # only when it may be used also means an install with it off never pays for it.
        ql_pool = select_due_qualified(session, now=now, limit=pool_limit)

    # Disqualified re-checks keep the priority they have today. At a reserved budget of 1
    # with a disqualified source always due, qualified re-verification therefore only runs
    # when none is -- stated rather than hidden; the default is 2, and 1 is the single
    # configuration where the split cannot be fair to both.
    rechecks, slot_contested = allocate_rechecks_detail(
        forced, dq_pool, ql_pool, total, odd_to_list=odd_to_list)
    forced_ids = {int(x.id) for x in forced}

    # One source is evaluated once per pass: a row reset to unqualified can be both a new
    # candidate and (stale) on the forced list, and a flagged one can also be due in a pool.
    candidates: list[Source] = []
    _seen_ids: set[int] = set()
    for _cand in [*new_candidates, *rechecks]:
        if int(_cand.id) not in _seen_ids:
            _seen_ids.add(int(_cand.id))
            candidates.append(_cand)
    if not candidates:
        return {"enabled": True, "evaluated": 0}

    trial_errors = 0
    deferred = 0
    if fetcher is not None:
        started = time.monotonic()
        attempted: list[Source] = []
        for source in candidates:
            # The first candidate is always tried; after that a pass gives up on the rest when
            # its wall-clock budget is spent or the memory guard says stop.
            if attempted and (
                time.monotonic() - started > _TRIAL_FETCH_BUDGET_S
                or (should_pause is not None and should_pause())
            ):
                break
            attempted.append(source)
            try:
                trial_fetch(session, source, fetcher)
            except Exception:  # noqa: BLE001 - one bad candidate must not abort the pass
                trial_errors += 1
                _LOG.warning(
                    "qualification trial fetch failed for %r",
                    getattr(source, "domain", "?"), exc_info=True,
                )
        deferred = len(candidates) - len(attempted)
        if deferred:
            done = {int(x.id) for x in attempted}
            new_candidates = [x for x in new_candidates if int(x.id) in done]
            rechecks = [x for x in rechecks if int(x.id) in done]
            candidates = attempted

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
            sample_articles=(
                QUALIFICATION_SAMPLE_ARTICLES if plan["mode"] == "sample" else None
            ),
        )
    except sq.ScanPaused as exc:
        # The FREEZE is itself a whole-corpus scan, so it can pause too -- and it is the
        # bigger of the two. Catching only the scoped read would have let the larger one
        # escape as an unhandled exception, which the job would report as a crash.
        _LOG.info("qualification pass paused during the cohort freeze: %s", exc)
        return {
            "enabled": True, "evaluated": 0, "paused": "memory", "reason": str(exc),
            "trial_fetch_errors": trial_errors, "deferred": deferred,
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
    history_cap = candidate_history_cap(len(candidates))
    try:
        per = sa.scoped_metrics(
            session, {int(s.id) for s in candidates}, frozen, should_pause=should_pause,
            per_source_recent=history_cap,
        )
    except sq.ScanPaused as exc:
        # S5.2: nothing is stamped from a paused scan. The candidates keep whatever status
        # they already had -- for a never-judged one that is ``unqualified``, which is the
        # truth, and the queue's least-recently-attempted ordering brings them back.
        _LOG.info("qualification pass paused: %s", exc)
        return {
            "enabled": True, "evaluated": 0, "paused": "memory", "reason": str(exc),
            "trial_fetch_errors": trial_errors, "deferred": deferred,
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

    # The label follows the cohort ACTUALLY used, not the plan: a caller's provider (the bulk
    # job freezes once per run) may have frozen under a different plan than this pass read.
    sampled = frozen.get("sample_articles") is not None
    criteria_version = CRITERIA_VERSION_SAMPLED if sampled else CRITERIA_VERSION
    tally = evaluate_and_stamp(
        session, judged, fails_by_source, now=now, criteria_version=criteria_version,
    )
    log_no_evidence_attempts(session, no_evidence, now=now, criteria_version=criteria_version)
    # Plain ints, read before the commit: reading ``.id`` off an expired row afterwards would
    # begin a new transaction on the session just before the key-value write below.
    forced_tried = {int(x.id) for x in rechecks if int(x.id) in forced_ids} if forced else set()
    session.commit()

    # C15 (2026-07-24 throughput brief, S-E slice 2): auto-enqueue a BOUNDED
    # archive backfill for every source that just got its "qualified" stamp
    # COMMITTED -- never before the commit (a rollback must never leave a
    # backfill queued for a source that was never really admitted). Always
    # full_history=False here: the automatic path never requests full
    # history, which is an explicit, separately-invoked per-source action.
    # Best-effort -- a queueing hiccup must never fail a qualification pass.
    # The forced re-checks this pass tried are stamped now that the pass has committed (the list
    # lives in the key-value store, which must not be written inside an open ORM transaction),
    # and the odd slot of an odd budget changes hands.
    if forced:
        record_forced_tries(forced_tried, now=now, odd_budget=slot_contested)

    for sid in tally.get("qualified_ids", []):
        try:
            from src.ingest.archive_backfill import enqueue_source

            enqueue_source(sid, full_history=False)
        except Exception:  # noqa: BLE001 - never fail qualification over a queueing hiccup
            _LOG.warning("archive backfill enqueue failed for source %s", sid, exc_info=True)

    return {
        "enabled": True, "evaluated": len(candidates), "trial_fetch_errors": trial_errors,
        # Candidates picked but not reached because the pass ran out of time or memory; they
        # were not attempted, so they are first in line next pass.
        "deferred": deferred,
        "no_evidence": len(no_evidence),
        # Reported apart because they answer different questions: "is the backlog draining"
        # and "is the recurrent verification actually running". One number cannot say both,
        # and it was precisely the absence of the second that hid a ladder that never ran.
        "new_candidates": len(new_candidates),
        "rechecks": len(rechecks),
        # Of those, the ones taken from the forced list (a measured verdict an imported history
        # disagrees with): reported apart so a reader can see the list draining.
        "forced_rechecks": sum(1 for x in rechecks if int(x.id) in forced_ids),
        # S5.1 staleness disclosure: WHICH corpus state the baseline reflects and how much of
        # it. Reported per pass rather than folded into the criteria version, because an age
        # is a measurement -- and because a reader must be able to tell a fresh baseline from
        # one carried across a long run without re-deriving it from timestamps.
        "baseline_token": frozen.get("token"),
        "baseline_articles": frozen.get("articles"),
        "baseline_sources": frozen.get("sources"),
        "baseline_frozen_by_caller": cohort_provider is not None,
        # FD03 b: which baseline judged this pass. `sample` means the newest
        # `baseline_sample_articles` articles, because this machine is below the memory floor.
        "baseline": "sample" if sampled else "whole",
        "baseline_sample_articles": frozen.get("sample_articles"),
        "criteria_version": criteria_version,
        # Candidates whose stored history reached the read cap: their verdict rests on their
        # newest `history_cap` articles, not on everything stored.
        "history_cap": history_cap,
        "history_capped": sum(
            1 for m in per.values() if int(m.get("article_count") or 0) >= history_cap
        ),
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
