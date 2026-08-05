"""Hourly Library-counter snapshots (2026-07-23 field-feedback S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Library tab showed a handful of counters (sources, keywords, Wikipedia
pages/revisions tracked, law documents/revisions tracked) as bare LIVE numbers
with no history. The maintainer asked for small evolution graphs instead
(2026-07-23 field feedback, item 3/5) with INFINITE retention ("I would prefer
infinite retention"). Most of these counters have no history anywhere else in
the store — unlike ``Article.created_at``, which already lets an articles/hour
graph be derived retroactively for free (see :func:`hourly_article_counts`
below) — so this module RECORDS one, honestly, starting from the moment
recording begins. Nothing here ever fabricates a value earlier than the first
real snapshot; the serving side must say "recording began at X" for any window
that predates it.

Each tracked metric is a cheap ``COUNT(*)`` over a small/indexed table — never
the SQLCipher codec column-order perf trap (a join dragging whole content rows
through the codec for one small field). ``StatSnapshot`` is append-only and its
own (metric, hour) unique constraint is the freshness gate — no separate marker
file, unlike the JSON-marker convention the heavier keyword-cleanup / incremental-
vacuum maintenance steps use (this is orders of magnitude cheaper per hour, so
the table itself is the driftproof source of truth for "already snapped this
hour").
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import StatSnapshot as StatSnapshotRow
from src.database.session import engine

_LOG = logging.getLogger("database.snapshots")

# Table name -> metric name. Each is a real COUNT(*) over a small/indexed table
# (never a full-content decrypt scan). Kept intentionally small: these are the
# Library-tab "Downloaded"/"Database" counters that had no history anywhere.
_SNAPSHOT_TABLES: dict[str, str] = {
    "articles": "articles",
    "sources": "sources",
    "keywords": "keywords",
    "wiki_pages": "wiki_pages",
    "wiki_revisions": "wiki_revisions",
    "law_documents": "law_documents",
    "law_revisions": "law_revisions",
}


def _count_sources_qualified(session: Session) -> int:
    from src.catalog.qualification import STATUS_QUALIFIED
    from src.database.models import Source

    return int(
        session.query(func.count(Source.id))
        .filter(Source.enabled.is_(True), Source.status == STATUS_QUALIFIED)
        .scalar()
        or 0
    )


def _count_sources_disqualified(session: Session) -> int:
    from src.catalog.qualification import STATUS_DISQUALIFIED
    from src.database.models import Source

    return int(
        session.query(func.count(Source.id))
        .filter(Source.enabled.is_(True), Source.status == STATUS_DISQUALIFIED)
        .scalar()
        or 0
    )


def _count_sources_never_judged(session: Session) -> int:
    """Enabled sources carrying no verdict yet.

    ⚠ THE METRIC KEY IS A MISNOMER AND MUST NOT BE "FIXED" BY REDEFINING IT.
    This counts ``status == 'unqualified'``, which is NOT the same as "never
    attempted": ``log_no_evidence_attempts`` writes a ``no_evidence``
    ``SourceQualificationAttempt`` row and deliberately leaves ``Source.status``
    untouched (``src/catalog/qualification.py:310-329``), so a source that has been
    tried repeatedly and concluded nothing sits here too — which is exactly the case
    an ENABLED source with no feed produces, forever. The genuinely-never-attempted
    count is ``_count_sources_never_attempted`` below.

    The key stays ``sources_never_judged`` because the snapshot store has infinite
    retention: changing what an existing key measures would make its own history
    incomparable with its future, a silent break in a time series. So the definition
    is frozen and the LABEL is what got corrected.
    """
    from src.catalog.qualification import STATUS_UNQUALIFIED
    from src.database.models import Source

    return int(
        session.query(func.count(Source.id))
        .filter(Source.enabled.is_(True), Source.status == STATUS_UNQUALIFIED)
        .scalar()
        or 0
    )


def _count_sources_never_attempted(session: Session) -> int:
    """Enabled, verdict-less sources that have never been through a qualification pass.

    The subset of ``sources_never_judged`` that the old label claimed the whole line
    was. The difference between the two is "attempted, concluded nothing" — a real,
    dated event that only ``source_qualification_attempts`` records, and which no
    surface in the app read before this metric existed.

    NOT EXISTS rather than a LEFT JOIN … IS NULL: measured identical in time on a
    76,679-source fixture (~9 ms both ways) and the plan is
    ``SEARCH sources USING INDEX idx_source_status`` with a per-candidate
    ``SEARCH … USING COVERING INDEX idx_qual_attempt_source_time`` — index-only on
    the attempts side, and it never touches ``articles``, so none of the SQLCipher
    row-decrypt cost that governs the article-side queries applies here.
    """
    from src.catalog.qualification import STATUS_UNQUALIFIED
    from src.database.models import Source, SourceQualificationAttempt

    tried = (
        select(SourceQualificationAttempt.id)
        .where(SourceQualificationAttempt.source_id == Source.id)
        .exists()
    )
    return int(
        session.query(func.count(Source.id))
        .filter(Source.enabled.is_(True), Source.status == STATUS_UNQUALIFIED, ~tried)
        .scalar()
        or 0
    )


def _count_sources_candidates(session: Session) -> int:
    from src.database.models import Source

    return int(session.query(func.count(Source.id)).filter(Source.enabled.is_(False)).scalar() or 0)


# The qualification lifecycle's own 4-way Source status/enabled split (2026-07-24
# field-feedback Session A §5), aligned with ``src/api/database.py``'s live
# database_stats() predicates -- ONE source of truth for what each bucket means
# (never two divergent definitions of "qualified"/"candidates"). Query-based
# (not a plain table COUNT(*)), so kept in a SEPARATE dict from _SNAPSHOT_TABLES;
# both feed the SAME StatSnapshotRow store keyed by metric name.
_FILTERED_METRICS: dict[str, Callable[[Session], int]] = {
    "sources_qualified": _count_sources_qualified,
    "sources_disqualified": _count_sources_disqualified,
    "sources_never_judged": _count_sources_never_judged,
    "sources_never_attempted": _count_sources_never_attempted,
    "sources_candidates": _count_sources_candidates,
}


def _gauge_wal_bytes(session: Session) -> int | None:
    """Size of the live ``-wal`` sidecar right now, in bytes — or None when there
    is nothing to measure.

    Returning None (rather than 0) on a non-SQLite/in-memory backend is the whole
    point: an unmeasurable gauge must leave a GAP in the series, never a recorded
    zero that reads as "the WAL was empty at that hour". A genuinely absent ``-wal``
    file on a real SQLite store IS a real zero, and is recorded as one.
    """
    from src.database.session import engine

    if engine.url.get_backend_name() != "sqlite":
        return None
    db_file = engine.url.database
    if not db_file or db_file == ":memory:":
        return None
    try:
        wal = Path(db_file + "-wal")
        return wal.stat().st_size if wal.exists() else 0
    except OSError:  # a stat failure is unmeasured, never a fabricated 0
        return None


# GAUGES: point-in-time measurements that are NOT a COUNT(*) over a table, so they
# live in their own dict (a gauge may legitimately report "unmeasurable" -> None,
# which the two count-based families never do). Recorded into the SAME append-only
# StatSnapshot store, keyed by metric name.
#
# ``wal_bytes`` closes the last of the three WAL-visibility gaps (field ruling
# 2026-07-29 item 8): storage-composition already reports the WAL's size RIGHT NOW
# and the scheduler's own checkpoint measurement, but neither can answer "is this
# WAL growing across days?" — the exact shape of the checkpoint-starvation hazard,
# which is invisible in any single reading. Deliberately NOT in ALL_METRICS: item 8
# ruled the WAL is diagnostics material, not a user-facing Library surface, and
# ALL_METRICS is the Library endpoint's allowlist. The series is served through the
# all-diagnostics bundle instead (see monitoring/storage.py).
_GAUGE_METRICS: dict[str, Callable[[Session], int | None]] = {
    "wal_bytes": _gauge_wal_bytes,
}

ALL_METRICS = tuple(_SNAPSHOT_TABLES) + tuple(_FILTERED_METRICS) + ("articles_per_hour",)


def _hour_bucket(now: datetime) -> datetime:
    """Truncate to the top of the hour, naive UTC (matches how other DateTime
    columns in this schema are stored — see ``Article.created_at`` etc.)."""
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    return now.replace(minute=0, second=0, microsecond=0)


def _count(session: Session, table_name: str) -> int:
    from sqlalchemy import table as sa_table

    return int(session.execute(select(func.count()).select_from(sa_table(table_name))).scalar() or 0)


def maybe_snapshot_library_stats(session: Session, *, now: datetime | None = None) -> dict:
    """Record one hourly snapshot of the tracked counters, if this hour has none yet.

    Freshness gate: the (metric, hour) unique constraint IS the marker — if a row
    for ``metric="articles"`` (an always-present table) already exists for this
    hour bucket, the snapshot is skipped as fresh. Only tables PRESENT in this
    build are counted (a core-only install with no law/wiki tables gets an
    honestly smaller set, never a crash). Never raises: a write failure rolls
    back and is reported, it must not break the caller's other maintenance steps.
    """
    now = now or datetime.now(UTC)
    bucket = _hour_bucket(now)
    present = set(inspect(engine).get_table_names())
    # Pick the first tracked metric whose backing table actually exists in this
    # build (never just the first dict key regardless of presence — a stripped
    # build without, say, "articles" must still gate correctly on whatever it does have).
    anchor = next((m for m, tbl in _SNAPSHOT_TABLES.items() if tbl in present), None)
    if anchor is None:
        return {"skipped": "no-tables"}
    already = (
        session.query(StatSnapshotRow)
        .filter(StatSnapshotRow.metric == anchor, StatSnapshotRow.taken_at == bucket)
        .first()
    )
    if already is not None:
        return {"skipped": "fresh", "hour": bucket.isoformat()}

    recorded: dict[str, int] = {}
    for metric, table_name in _SNAPSHOT_TABLES.items():
        if table_name not in present:
            continue
        try:
            value = _count(session, table_name)
        except Exception:  # noqa: BLE001 - one bad count must not lose the rest
            _LOG.warning("snapshot count failed for %s", metric, exc_info=True)
            continue
        try:
            # A SAVEPOINT (not the whole transaction) around each insert: a
            # rollback on IntegrityError must discard only THIS row, never the
            # metrics already flushed earlier in this same loop (the project's
            # own documented lesson about a bare ``session.rollback()`` mid-batch
            # silently discarding every prior uncommitted insert).
            with session.begin_nested():
                session.add(StatSnapshotRow(metric=metric, taken_at=bucket, value=value))
        except IntegrityError:
            # A concurrent writer beat us to this (metric, hour) — fine, it is
            # recorded either way; never a duplicate, never a crash.
            continue
        recorded[metric] = value

    # Filtered (query-based) metrics — same savepoint-per-insert discipline. Only
    # attempted when their backing table exists, so a stripped/core build degrades
    # honestly rather than crashing.
    if "sources" in present:
        for metric, fn in _FILTERED_METRICS.items():
            try:
                value = fn(session)
            except Exception:  # noqa: BLE001 - one bad count must not lose the rest
                _LOG.warning("snapshot count failed for %s", metric, exc_info=True)
                continue
            try:
                with session.begin_nested():
                    session.add(StatSnapshotRow(metric=metric, taken_at=bucket, value=value))
            except IntegrityError:
                continue
            recorded[metric] = value

    # Gauges — same savepoint-per-insert discipline. A gauge that cannot be measured
    # returns None and is SKIPPED, leaving an honest hole in the series rather than a
    # recorded zero (a fabricated "the WAL was empty" reading).
    for metric, gauge in _GAUGE_METRICS.items():
        try:
            measured = gauge(session)
        except Exception:  # noqa: BLE001 - one bad gauge must not lose the rest
            _LOG.warning("snapshot gauge failed for %s", metric, exc_info=True)
            continue
        if measured is None:
            continue
        try:
            with session.begin_nested():
                session.add(StatSnapshotRow(metric=metric, taken_at=bucket, value=int(measured)))
        except IntegrityError:
            continue
        recorded[metric] = int(measured)

    if not recorded:
        return {"skipped": "no-metrics"}
    return {"hour": bucket.isoformat(), "recorded": recorded}


def hourly_article_counts(session: Session, *, days: int, now: datetime | None = None) -> list[dict]:
    """The articles/hour series over the past ``days`` — DERIVED live from
    ``Article.created_at`` (real history that already exists since the article was
    first stored; no snapshot table needed, and no gap before "recording began").
    Bounded to ``days`` (validated by the caller); returns ``[{"t": iso, "n": int}]``
    for every hour that has at least one article, oldest first."""
    from src.database.models import Article

    now = now or datetime.now(UTC)
    since = _hour_bucket(now) - timedelta(days=days)
    if engine.url.get_backend_name() == "sqlite":
        bucket_expr = func.strftime("%Y-%m-%dT%H:00:00", Article.created_at)
    else:
        bucket_expr = func.date_trunc("hour", Article.created_at)
    rows = (
        session.query(bucket_expr.label("bucket"), func.count().label("n"))
        .filter(Article.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    out = []
    for bucket, n in rows:
        iso = bucket if isinstance(bucket, str) else (bucket.isoformat() if bucket else None)
        out.append({"t": iso, "n": int(n or 0)})
    return out


_BUCKETS = {"hour": timedelta(hours=1), "day": timedelta(days=1)}
#: The per-language series defaults to a DAY bucket past a week, so a ten-year
#: window stays a bounded number of points. This is BINNING, which the chart rules
#: permit "when supported and always labeled" — never downsampling, which they
#: forbid: every article in the window is counted, in one bin or another. The bin
#: is named in the payload so the axis can say what a point means.
_LANG_HOURLY_MAX_DAYS = 7
_LANG_TOP_N = 12


def _bucket_floor(dt: datetime, bucket: str) -> datetime:
    dt = dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo is not None else dt
    if bucket == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(minute=0, second=0, microsecond=0)


def _as_naive_dt(value) -> datetime | None:
    """A GROUP BY bucket back to a naive datetime, whichever backend produced it.

    SQLite's ``strftime`` yields a string and Postgres' ``date_trunc`` a datetime;
    keying the fold on the parsed DATETIME rather than on either backend's string
    means the zero-fill below never has to match two different text formats.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def article_counts_by_language(
    session: Session,
    *,
    days: int,
    top_n: int = _LANG_TOP_N,
    now: datetime | None = None,
) -> dict:
    """Articles stored per language per bucket — the feed for "which languages is
    my corpus actually growing in".

    DERIVED live from ``Article.created_at`` exactly like :func:`hourly_article_counts`,
    so it is retroactive: no snapshot table, no metric of unbounded cardinality, and
    no gap before "recording began".

    IT MUST PUBLISH THE SAME QUANTITY AS THE LEVER IT INFORMS. The reason to look at
    this graph is to tune ``scheduler.equilibrium``, which reads ``Article.language``
    and buckets it through ``normalize_lang``. So this does both the same way: the
    same column (never ``coalesce(language, detected_language)``, which would pool an
    asserted value with a deduced one) and the same key (so ``en`` / ``en-US`` / ``en_us``
    are ONE language here for the same reason they are one language there). A feed
    keyed differently from its lever describes a different corpus than the one the
    lever is steering — the defect class both modules were fixed for.

    Two honesty rules shape the response rather than the query:

    * ZERO-FILL, NOT NULL-FILL, and only back to the corpus's own beginning. A bucket
      where a language got nothing is a REAL ZERO — it was measured — so it is emitted
      as 0 and the time axis stays true. But a bucket before the first article ever
      stored was never measured at all, so the series simply starts later and
      ``begins_at`` says where; filling zeros there would claim observations that
      predate the corpus.
    * TOP-N IS RANKED, NEVER TRUNCATED SILENTLY. A corpus can carry fifty languages;
      the panels show the busiest ``top_n`` and ``other`` states exactly how many
      languages and articles are not drawn.

    ``unassigned`` counts the window's articles with NO asserted language. It is
    reported apart from the series (an "unknown" panel would often dominate and says
    nothing about growth) and it is load-bearing: the equilibrium lever cannot see
    those articles either, so the number is the size of that blind spot.

    QUARANTINE, deliberately: neither this nor ``corpus_language_shares`` excludes
    quarantined articles. That is arguably wrong for BOTH — the lever would then be
    steering partly on nav-soup — but it is the lever's own question, and the two must
    move TOGETHER. Gate one and this graph starts describing a corpus the lever is not
    steering, which is the entire failure the shared bucket key above was fixed for.
    """
    from src.analytics.managed import normalize_lang
    from src.database.models import Article

    now = now or datetime.now(UTC)
    bucket = "hour" if days <= _LANG_HOURLY_MAX_DAYS else "day"
    step = _BUCKETS[bucket]
    since = _bucket_floor(now, bucket) - timedelta(days=days)

    if engine.url.get_backend_name() == "sqlite":
        fmt = "%Y-%m-%dT%H:00:00" if bucket == "hour" else "%Y-%m-%d"
        bucket_expr = func.strftime(fmt, Article.created_at)
    else:
        bucket_expr = func.date_trunc(bucket, Article.created_at)

    # idx_article_created_lang covers exactly this shape. Without it the GROUP BY
    # reads `language` from the heap, dragging every ~35 KB article row through the
    # SQLCipher codec — the recorded column-order perf trap.
    #
    # The deduced tally rides the SAME grouped scan as a third dimension rather than
    # a second query, because a second query is where the planner escapes: asked
    # separately for `language IS NULL AND detected_language IS NOT NULL`, SQLite
    # prefers the narrower idx_article_language (an equality seek) and then reads the
    # heap for detected_language — index-only for the series, straight back into the
    # codec for the tally, on exactly the articles that are most numerous when a
    # corpus is under-tagged. Grouping on the predicate at most doubles the row
    # count and keeps one covered pass. (Found by the EXPLAIN test, not by reading:
    # a standalone probe of the same SQL had chosen the composite index and looked
    # fine.)
    has_deduced = Article.detected_language.isnot(None)
    rows = (
        session.query(
            bucket_expr.label("bucket"),
            Article.language,
            has_deduced.label("deduced"),
            func.count().label("n"),
        )
        .filter(Article.created_at >= since)
        .group_by("bucket", Article.language, "deduced")
        .all()
    )

    per_lang: dict[str, dict[datetime, int]] = {}
    totals: dict[str, int] = {}
    unassigned = 0
    deduced_only = 0
    undated = 0
    for raw_bucket, raw_lang, deduced, n in rows:
        count = int(n or 0)
        key = normalize_lang(raw_lang)
        if not key:
            unassigned += count
            if deduced:
                deduced_only += count
            continue
        at = _as_naive_dt(raw_bucket)
        if at is None:
            # A created_at that will not parse into a bucket (SQLite is dynamically
            # typed, so a malformed value can be stored and strftime then yields
            # NULL). Counted rather than dropped: this is a counting function, and
            # the conservation property below — that every article in the window
            # lands in exactly one published figure — is what lets a reader trust
            # any single one of them.
            undated += count
            continue
        slot = per_lang.setdefault(key, {})
        slot[at] = slot.get(at, 0) + count
        totals[key] = totals.get(key, 0) + count

    # Rank by window total, tie-broken by code, so panel order is stable between
    # calls: a view whose panels reshuffle on refresh cannot be read for change.
    ranked = sorted(totals, key=lambda lang: (-totals[lang], lang))
    shown, tail = ranked[: max(0, top_n)], ranked[max(0, top_n) :]

    first_article = session.query(func.min(Article.created_at)).scalar()
    corpus_began = _as_naive_dt(first_article)
    corpus_floor = _bucket_floor(corpus_began, bucket) if corpus_began else None
    begins = max(corpus_floor, since) if corpus_floor else since
    # Whether the series starts late because the CORPUS is younger than the window,
    # decided here rather than left to a caller re-deriving it from two timestamps
    # and getting the bucket arithmetic subtly wrong.
    clamped = bool(corpus_floor and corpus_floor > since)

    # The axis runs to `now` OR to the newest bucket that actually holds data,
    # whichever is later. They are normally the same; they diverge when a stored
    # article carries a created_at ahead of the clock (skew, or a corpus restored
    # from a machine that was ahead), and then a bucket counted in `total` would
    # have no slot to be drawn in — a panel silently claiming more than its bars
    # add up to.
    axis: list[datetime] = []
    newest = max((slot for slots in per_lang.values() for slot in slots), default=None)
    last = _bucket_floor(now, bucket)
    if newest and newest > last:
        last = newest
    at = begins
    while at <= last:
        axis.append(at)
        at += step

    series = [
        {
            "language": lang,
            "total": totals[lang],
            # Every bucket on the axis, so the x-position of a point is real elapsed
            # time and not its ordinal — the compression an omit-empties series causes.
            "points": [{"t": slot.isoformat(), "n": per_lang[lang].get(slot, 0)} for slot in axis],
        }
        for lang in shown
    ]

    return {
        "bucket": bucket,
        "days": days,
        "top_n": top_n,
        "series": series,
        "begins_at": begins.isoformat() if begins else None,
        "corpus_began_at": corpus_began.isoformat() if corpus_began else None,
        "clamped_to_corpus_start": clamped,
        "other": {"languages": len(tail), "articles": sum(totals[lang] for lang in tail)},
        "unassigned": {"articles": unassigned, "with_deduced_language": deduced_only},
        "undated": undated,
        "method": (
            f"Articles stored per {bucket}, counted by their asserted language "
            "(Article.language, region subtags folded) — the same column and the same "
            "bucket key the language-equilibrium lever reads. Deduced languages are "
            "never pooled in. Counts only, no score."
        ),
        "caveat": (
            "Articles with no asserted language are excluded from the panels and "
            "reported separately; the equilibrium lever cannot see them either."
        ),
    }


def metric_history(session: Session, *, metric: str, days: int) -> dict:
    """Bounded read of one recorded metric's snapshot series.

    Storage retention is infinite; the RESPONSE is bounded to ``days`` (the
    caller validates the range). Returns the series plus ``recording_began_at``
    (the timestamp of the metric's very first snapshot ever, regardless of the
    window) so the UI can state honestly "recording began at X" instead of
    implying a gap is a real absence of activity."""
    # Every RECORDED family is readable here, gauges included. This is deliberately
    # wider than ALL_METRICS (the Library endpoint's user-facing allowlist): a gauge
    # like wal_bytes is diagnostics material, so it must be queryable by the bundle
    # without also appearing as a Library counter.
    if metric not in _SNAPSHOT_TABLES and metric not in _FILTERED_METRICS and metric not in _GAUGE_METRICS:
        return {"metric": metric, "series": [], "recording_began_at": None, "error": "unknown metric"}
    now = datetime.now(UTC)
    since = _hour_bucket(now) - timedelta(days=days)
    first = (
        session.query(func.min(StatSnapshotRow.taken_at))
        .filter(StatSnapshotRow.metric == metric)
        .scalar()
    )
    rows = (
        session.query(StatSnapshotRow.taken_at, StatSnapshotRow.value)
        .filter(StatSnapshotRow.metric == metric, StatSnapshotRow.taken_at >= since)
        .order_by(StatSnapshotRow.taken_at)
        .all()
    )
    series = [{"t": t.isoformat(), "n": int(v)} for t, v in rows]
    return {
        "metric": metric,
        "series": series,
        "recording_began_at": first.isoformat() if first else None,
    }

