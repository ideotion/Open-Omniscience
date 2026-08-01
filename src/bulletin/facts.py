"""
Layer A — the Bulletin's deterministic record.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §4, §5, §11. Model-free, network-free, exact.

Layer A answers "what does the corpus say about this bounded period" in counts
that carry their own method. It is what the document contains when narration is
off, and it is what narration is grounded in when narration is on — so a number
that is wrong here is wrong everywhere downstream.

Four properties are load-bearing:

* **Exact and uncapped.** A cap may bound which EXAMPLES are listed; it must never
  bound a reported NUMBER. ``articles`` is a ``COUNT(*)``, not the length of a
  fetched page. (This is why ``analytics.latest`` is not reused: it is a rolling
  single-sided feed that caps its own scan at 2,000 rows and its output at 100,
  applies editorial gates, and orders by ``created_at`` on purpose.)
* **The clock is ``coalesce(published_at, created_at)``**, written literally so
  SQLite matches the ``ix_article_observed`` expression index — an expression
  index is used ONLY when the query expression is written identically. Written any
  other way the range filter becomes a bare ``SCAN articles``, dragging every
  ~35 KB row through the SQLCipher codec.
* **Quarantined articles are excluded**, via the one canonical condition
  ``Article.quarantined.isnot(True)`` (NULL means "never judged" and reads as not
  quarantined). The excluded count is reported, not silently dropped.
* **Small columns only.** Never a whole ORM row: ``content`` precedes ``language``
  in the table, so materialising rows to read one small field is the documented
  codec trap.

COST, stated rather than discovered: the two per-period aggregates read the
in-period article rows (``source_id``/``language`` are not in any index that also
carries the clock, and the quarantine filter needs the row as well), so this is
two scans of the period's articles. A weekly edition is cheap; a yearly edition on
a large corpus is a deliberate, occasional operation. A ``(clock, source_id,
language, quarantined)`` covering index would make it index-only — deliberately
NOT added here, because this repo's own rule is to measure a real edition before
adding a drift surface for it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import and_, func

from src.bulletin.period import Period, baseline_coverage, top_share
from src.database.models import Article, KeywordMention, Source

_LOG = logging.getLogger(__name__)

# The clock, written EXACTLY as ix_article_observed defines it. Do not reformat.
_CLOCK = func.coalesce(Article.published_at, Article.created_at)

# SQLite binds a parameter list one variable at a time; stay under the ~999 ceiling.
_CHUNK = 900

_ARTICLES_METHOD = (
    "exact COUNT over articles whose coalesce(published_at, created_at) falls in "
    "[start, end), excluding quarantined articles; never sampled, never capped"
)


def _bounds(period: Period) -> tuple[datetime, datetime]:
    """The period as datetimes at midnight.

    Bound as datetimes, not dates: the column is a DateTime and SQLAlchemy's
    SQLite bind processor formats datetimes only. Naive, because SQLAlchemy stores
    even a tz-aware UTC datetime as a naive string — binding naive UTC is what
    matches what is on disk.
    """
    return datetime.combine(period.start, time.min), datetime.combine(period.end, time.min)


def _in_period(period: Period):
    lo, hi = _bounds(period)
    return and_(_CLOCK >= lo, _CLOCK < hi, Article.quarantined.isnot(True))


def _source_directory(session, source_ids: list[int]) -> dict[int, dict]:
    """Display + lens metadata for the sources that actually contributed.

    Only the contributing sources are fetched, chunked under the bind-variable
    ceiling. The catalog now runs to tens of thousands of rows, most of them
    disabled discovery candidates that contributed nothing — loading all of them to
    describe a handful would be paying for the whole catalog on every edition.
    """
    out: dict[int, dict] = {}
    ids = [int(s) for s in source_ids if s is not None]
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        rows = session.query(
            Source.id, Source.name, Source.domain, Source.country, Source.source_type
        ).filter(Source.id.in_(chunk))
        for sid, name, domain, country, stype in rows:
            out[int(sid)] = {
                "name": name,
                "domain": domain,
                "country": (country or None),
                "source_type": (stype or "news"),
            }
    return out


def _by_source_and_language(session, period: Period) -> list[tuple[int | None, str | None, int]]:
    """One grouped scan giving BOTH the per-source and per-language distributions.

    Grouped together rather than queried twice because both need the same table
    rows: under SQLCipher a second pass is a second decrypt of the same pages. The
    result stays small — a source is almost always one language, so the row count
    is bounded by the number of contributing sources, not by their product.
    """
    rows = (
        session.query(Article.source_id, Article.language, func.count(Article.id))
        .filter(_in_period(period))
        .group_by(Article.source_id, Article.language)
        .all()
    )
    return [(r[0], r[1], int(r[2] or 0)) for r in rows]


def _by_day(session, period: Period) -> dict[str, int]:
    """Articles per calendar day of the period.

    ``substr(clock, 1, 10)`` is byte-literal against the stored ISO string and
    matches Python's ``.date()`` exactly — preferred over SQLite's ``date()``,
    which reinterprets the value.
    """
    day = func.substr(_CLOCK, 1, 10)
    rows = session.query(day, func.count(Article.id)).filter(_in_period(period)).group_by(day).all()
    return {str(r[0]): int(r[1] or 0) for r in rows if r[0]}


def _corpus_earliest(session) -> date | None:
    """The corpus's earliest observed date, for the baseline-coverage rail.

    No quarantine filter: this measures how far back the corpus REACHES, which is a
    fact about the archive rather than about what an edition may cite. Index-only
    — nothing but the clock expression is read.
    """
    val = session.query(func.min(_CLOCK)).scalar()
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except ValueError:
        return None


def masthead(session, period: Period) -> dict:
    """The mandatory masthead (§11): who and what this edition's corpus actually was.

    A periodic document structurally trains a reader that recent equals important,
    and that every source in it was equally present. The masthead is the
    counterweight — it states the lens in the same breath as the content: which
    sources contributed at all, how concentrated they were, which languages and
    countries the view came from, and how many of the period's days had any ingest
    whatsoever.

    Every figure is an exact count. ``top_3_share`` is a measured proportion with a
    stated denominator, not a score.
    """
    rows = _by_source_and_language(session, period)

    per_source: dict[int, int] = {}
    per_language: dict[str | None, int] = {}
    unknown_language = 0
    for sid, lang, n in rows:
        if sid is not None:
            per_source[int(sid)] = per_source.get(int(sid), 0) + n
        key = (lang or "").strip() or None
        per_language[key] = per_language.get(key, 0) + n
        if key is None:
            unknown_language += n

    total = sum(per_source.values()) + sum(n for sid, _l, n in rows if sid is None)
    directory = _source_directory(session, list(per_source))

    ranked = sorted(per_source.items(), key=lambda kv: (-kv[1], kv[0]))
    top_sources = [
        {
            "source_id": sid,
            "name": directory.get(sid, {}).get("name"),
            "domain": directory.get(sid, {}).get("domain"),
            "articles": n,
            "share": round(n / total, 4) if total else None,
        }
        for sid, n in ranked[:3]
    ]

    # The country and channel splits are the SOURCE's, not a place mentioned in the
    # text — the lens the corpus was collected through. Named so it cannot be read
    # as "articles about this country".
    per_country: dict[str | None, int] = {}
    per_channel: dict[str, int] = {}
    for sid, n in per_source.items():
        info = directory.get(sid, {})
        country = info.get("country") or None
        per_country[country] = per_country.get(country, 0) + n
        channel = info.get("source_type") or "news"
        per_channel[channel] = per_channel.get(channel, 0) + n

    days = _by_day(session, period)
    corpus_total = int(
        session.query(func.count(Article.id)).filter(Article.quarantined.isnot(True)).scalar() or 0
    )

    return {
        "articles": total,
        "corpus_articles": corpus_total,
        "corpus_share": round(total / corpus_total, 6) if corpus_total else None,
        "sources_contributing": len(per_source),
        "top_sources": top_sources,
        # Same denominator as each top_sources[].share above — see top_share's own note.
        "top_3_share": top_share(per_source.values(), 3, total=total),
        "languages": [
            {"language": lang, "articles": n}
            for lang, n in sorted(per_language.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ],
        "language_unknown_articles": unknown_language,
        "source_countries": [
            {"country": c, "articles": n}
            for c, n in sorted(per_country.items(), key=lambda kv: (-kv[1], str(kv[0])))
            if c is not None
        ],
        "source_unlocated_articles": per_country.get(None, 0),
        "channels": [
            {"source_type": c, "articles": n}
            for c, n in sorted(per_channel.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "days_with_ingest": len(days),
        "period_days": period.days,
        "articles_by_day": [{"day": d, "articles": days[d]} for d in sorted(days)],
        "method": (
            f"{_ARTICLES_METHOD}. Country and channel are the SOURCE's, from the "
            "catalog — the lens the corpus was collected through, never a place the "
            "text is about. Language is the authoritative Article.language; an "
            "untagged article is counted in its own bucket, never guessed into one. "
            "top_3_share is an exact proportion of this period's articles."
        ),
        "caveat": (
            "These figures describe the corpus, not the world: a country absent here "
            "is a country this corpus did not collect from during the period, which "
            "says nothing about whether anything happened there."
        ),
    }


def disclosures(session, period: Period) -> dict:
    """What this edition cannot see, counted rather than omitted.

    Four exclusions, each of which would otherwise read as an absence of events:

    * quarantined articles in the period — real rows, deliberately withheld;
    * mentions with a NULL ``observed_on`` — invisible to every window by
      construction, since both bounds exclude NULL;
    * the re-index backlog — imported articles that carry no keywords yet, so they
      are structurally invisible to every keyword aggregate. Its ``available:
      false`` means "could not be read", NEVER "zero";
    * baseline coverage — the long-cadence rail from §5.3.

    Each probe degrades on its own: a failing one reports its error and the others
    still report. A disclosure block that 500s takes the whole edition with it.

    ``reindex_backlog()`` deliberately reads through its own ``session_scope()``
    rather than the session passed here — the backlog is a fact about the store,
    not about this query, and it is the one canonical accessor for it.
    """
    lo, hi = _bounds(period)
    out: dict[str, Any] = {}

    try:
        out["quarantined_in_period"] = int(
            session.query(func.count(Article.id))
            .filter(and_(_CLOCK >= lo, _CLOCK < hi, Article.quarantined.is_(True)))
            .scalar()
            or 0
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: quarantine count failed", exc_info=True)
        out["quarantined_in_period"] = None
        out["quarantined_error"] = str(exc)

    try:
        out["mentions_without_a_date"] = int(
            session.query(func.count(KeywordMention.id))
            .filter(KeywordMention.observed_on.is_(None))
            .scalar()
            or 0
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: undated-mention count failed", exc_info=True)
        out["mentions_without_a_date"] = None
        out["mentions_without_a_date_error"] = str(exc)

    try:
        from src.backup.merge import reindex_backlog

        out["reindex_backlog"] = reindex_backlog()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: re-index backlog unreadable", exc_info=True)
        out["reindex_backlog"] = {"available": False, "reason": str(exc)}

    try:
        out["baseline_coverage"] = baseline_coverage(period, _corpus_earliest(session))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: baseline coverage failed", exc_info=True)
        out["baseline_coverage"] = baseline_coverage(period, None) | {"error": str(exc)}

    out["method"] = (
        "each exclusion counted directly; a probe that cannot read reports None with "
        "its error, never 0"
    )
    out["caveat"] = (
        "An excluded set is not an empty one. Quarantined articles exist and are "
        "reversible; undated mentions are invisible to every window in the app, not "
        "only to this edition; articles awaiting re-index carry no keywords yet, so "
        "they are missing from every keyword figure here."
    )
    return out


def rising_concepts(
    session,
    period: Period,
    *,
    limit: int = 20,
    min_recent: int = 3,
    target_lang: str | None = None,
) -> dict:
    """What rose during the period, against the immediately preceding baseline.

    Delegates to the shipped ``queries.trending``, anchored to the period's own
    closed windows via its ``end`` parameter — so the answer is reproducible and
    the recent window equals the coverage window exactly (§5.1). It is not
    re-implemented here: ``growth`` is a ruled, shipped ratio, and a second
    implementation of it would be a second thing to keep correct.

    The section declares its REAL window (§12), so an edition showing a window that
    does not match its cadence is visible in the output rather than hidden.
    """
    from src.analytics.queries import trending

    res = trending(
        session,
        window_days=period.days,
        baseline_days=period.baseline_days,
        limit=int(limit),
        min_recent=int(min_recent),
        target_lang=target_lang,
        end=period.end,
    )
    res["section"] = "rising_concepts"
    res["window"] = {
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "days": period.days,
        "baseline_start": period.baseline_start.isoformat(),
        "baseline_days": period.baseline_days,
        # Read back from what trending ACTUALLY used, not asserted from what it was
        # asked for. A section reporting its own intent rather than its own behaviour
        # is exactly the blind spot §12 exists to remove.
        "matches_period": (
            res.get("window_days") == period.days
            and res.get("baseline_days") == period.baseline_days
        ),
    }
    res["caveat"] = (
        (res.get("caveat", "") + " ") if res.get("caveat") else ""
    ) + (
        "A ratio, not a significance test: with many terms screened, some ratios are "
        "high by chance. `scanned` is how many were screened to surface these."
    )
    return res


def layer_a(
    session,
    period: Period,
    *,
    rising_limit: int = 20,
    target_lang: str | None = None,
) -> dict:
    """Assemble the whole deterministic record for one period.

    This is the document when narration is off, and narration's only ground truth
    when it is on. No model, no network.

    Sections are a list rather than named keys so the set is cheap to change (§11)
    and so each carries its own declared window beside its own content.

    A failing SECTION is caught and reported in place — one producer must not cost
    the edition. The masthead is deliberately NOT caught: if the corpus cannot be
    counted there is no record to publish, and a payload that quietly omits its own
    lens is worse than a loud failure.
    """
    from src.bulletin.sections import build_sections

    sections = build_sections(
        session, period, rising_limit=rising_limit, target_lang=target_lang
    )

    return {
        "schema": "oo-bulletin-layer-a-1",
        "layer": "A",
        "period": period.to_dict(),
        "masthead": masthead(session, period),
        "sections": sections,
        "disclosures": disclosures(session, period),
        "method": (
            "deterministic: exact SQL counts over a half-open period on "
            "coalesce(published_at, created_at), quarantined articles excluded and "
            "counted. No model was involved in producing any figure here."
        ),
        "caveat": (
            "This is Layer A — the record. It describes what this corpus collected "
            "during the period, ordered by disclosed measures. It contains no "
            "editorial lead and no composite score, and the absence of a subject is "
            "an absence of collection, not of events."
        ),
    }
