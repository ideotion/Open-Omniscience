"""
Layer A's section registry — the edition's body, one bundle per section.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §11. Sections are registered producers over facts, so the list is
cheap to change — which is the whole reason they are registered rather than
hardcoded into the assembler.

Three rules govern every section here:

* **It prints its REAL window** (§12). A monthly edition showing a 14-day number
  must be visible in the output rather than hidden, so each bundle carries the
  window it actually used and whether that matches the period.
* **It declares its own limits.** A section that cannot answer for this period
  says so, with the reason, and is still emitted — an absent section reads as
  "nothing happened", which is the one thing it must never mean.
* **Counts only.** No composite score, no editorial lead, no field whose name
  contains score / ranking / rating / grade.

DELIBERATELY OMITTED, and it belongs here rather than in a commit message: there
is no "top story" section. That is exactly where an implicit composite score
creeps in — the moment one item is elevated above the others, something had to
rank them, and nothing in this corpus can do that honestly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, func

from src.bulletin.period import Period

_LOG = logging.getLogger(__name__)

# A bounded EXAMPLE list never bounds a reported count — the counts beside these
# are exact. Named so the distinction cannot be lost at a call site.
_EXAMPLES = 12

# through_time matches calendar days across earlier years by (month, day). One bind
# per day of the period keeps it far under SQLite's ~999-variable ceiling; past that
# the lens stops being a lens (a yearly period's "same days last year" is just last
# year) and the section says so instead of running a scan that means nothing.
_ANNIVERSARY_MAX_DAYS = 62


def _bounds(period: Period) -> tuple[datetime, datetime]:
    return datetime.combine(period.start, time.min), datetime.combine(period.end, time.min)


def _window_of(period: Period, *, days: int | None = None, note: str = "") -> dict:
    """The window a section actually used, declared beside its content (§12)."""
    used = period.days if days is None else int(days)
    out = {
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "days": used,
        "matches_period": used == period.days,
    }
    if note:
        out["window_note"] = note
    return out


def _source_classes(session) -> dict[int, dict]:
    """Every source's provenance CLASS and display facts, keyed by id.

    The class is derived, not stored, so it is computed once here rather than at
    each call site — and it is the honest name for "channel": a wiki edition and a
    hazard feed are different KINDS of thing, which ``source_type`` alone does not
    always say.
    """
    from src.catalog.provenance import provenance_of
    from src.database.models import Source

    out: dict[int, dict] = {}
    for sid, name, domain, stype in session.query(
        Source.id, Source.name, Source.domain, Source.source_type
    ):
        out[int(sid)] = {
            "name": name,
            "domain": domain,
            "source_type": stype or "news",
            "provenance": provenance_of(domain, stype),
        }
    return out


# --------------------------------------------------------------------------- #
#  across channels
# --------------------------------------------------------------------------- #


def across_channels(session, period: Period, *, terms: list[dict] | None = None) -> dict:
    """Which channel carried each concept EARLIEST in this period.

    Not "who broke it" — that is a claim this corpus cannot support. Earliest here
    means earliest *observed in this corpus, within this period*, which is a fact
    about collection order as much as about publication, and the caveat says so.

    Scoped to the terms the rising section already surfaced, so the query is
    ``keyword_id IN (…) AND observed_on IN period`` — served by the
    ``ix_mention_keyword_date`` index rather than a whole-period mention scan.
    Without those terms there is nothing to attribute, and the section says so.
    """
    from src.database.models import Keyword, KeywordMention

    rows_in = [t for t in (terms or []) if t.get("normalized")]
    if not rows_in:
        return {
            "section": "across_channels",
            "window": _window_of(period),
            "channels": [],
            "terms": [],
            "skipped": "no rising concepts to attribute for this period",
            "method": "earliest in-period mention per keyword per provenance class",
            "caveat": _CHANNEL_CAVEAT,
        }

    # Ring rows carry a synthetic "ring:<id>" normalized form with real members
    # behind it; take the members, since only a real keyword has mentions.
    wanted: list[str] = []
    label_of: dict[str, str] = {}
    for t in rows_in:
        members = t.get("members") or []
        for m in members or [{"normalized": t["normalized"], "term": t.get("term")}]:
            n = m.get("normalized")
            if n and not str(n).startswith("ring:"):
                wanted.append(n)
                label_of[n] = t.get("term") or n
    if not wanted:
        return {
            "section": "across_channels",
            "window": _window_of(period),
            "channels": [],
            "terms": [],
            "skipped": "the period's concepts resolved to no plain keywords",
            "method": "earliest in-period mention per keyword per provenance class",
            "caveat": _CHANNEL_CAVEAT,
        }

    ids = dict(
        session.query(Keyword.normalized_term, Keyword.id).filter(
            Keyword.normalized_term.in_(wanted[:900])
        )
    )
    if not ids:
        return {
            "section": "across_channels",
            "window": _window_of(period),
            "channels": [],
            "terms": [],
            "skipped": "none of the period's concepts resolved to a stored keyword",
            "method": "earliest in-period mention per keyword per provenance class",
            "caveat": _CHANNEL_CAVEAT,
        }

    by_id = {int(v): k for k, v in ids.items()}
    lo, hi = period.start, period.end
    rows = (
        session.query(
            KeywordMention.keyword_id,
            KeywordMention.source_id,
            func.min(KeywordMention.observed_on),
        )
        .filter(
            KeywordMention.keyword_id.in_(list(by_id)),
            KeywordMention.observed_on >= lo,
            KeywordMention.observed_on < hi,
        )
        .group_by(KeywordMention.keyword_id, KeywordMention.source_id)
        .all()
    )

    classes = _source_classes(session)
    # Ties are REAL and must survive: two channels can carry a concept on the same
    # day, and the mention clock is a date, so there is no finer order to appeal to.
    # Collect (earliest day -> the set of classes on that day) in one pass rather
    # than picking a winner and inventing a sequence the data does not contain.
    earliest: dict[int, date] = {}
    on_earliest: dict[int, set[str]] = {}
    unattributed = 0
    for kid, sid, first in rows:
        if first is None:
            continue
        day = first if isinstance(first, date) else date.fromisoformat(str(first)[:10])
        info = classes.get(int(sid)) if sid is not None else None
        if info is None:
            unattributed += 1
            continue
        cls = info["provenance"]
        kid = int(kid)
        prev = earliest.get(kid)
        if prev is None or day < prev:
            earliest[kid] = day
            on_earliest[kid] = {cls}
        elif day == prev:
            on_earliest[kid].add(cls)

    per_class: dict[str, int] = {}
    out_terms = []
    for kid, day in sorted(earliest.items(), key=lambda kv: kv[1]):
        tied = sorted(on_earliest.get(kid, set()))
        norm = by_id.get(kid, "")
        out_terms.append(
            {
                "term": label_of.get(norm, norm),
                "normalized": norm,
                "first_seen": day.isoformat(),
                "channel": tied[0] if len(tied) == 1 else None,
                "channels_tied": tied if len(tied) > 1 else None,
            }
        )
        # A tie credits nobody: counting it for each tied channel would inflate the
        # table past the number of concepts examined.
        if len(tied) == 1:
            per_class[tied[0]] = per_class.get(tied[0], 0) + 1

    return {
        "section": "across_channels",
        "window": _window_of(period),
        "channels": [
            {"provenance": c, "concepts_first_here": n}
            for c, n in sorted(per_class.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "terms": out_terms,
        "concepts_examined": len(by_id),
        "mentions_without_a_source": unattributed,
        "method": (
            "earliest in-period mention date per keyword, attributed to the provenance "
            "class of the source that carried it; ties are reported as ties, never "
            "broken. Keyed off the denormalised KeywordMention.source_id, so no "
            "mention-to-article join."
        ),
        "caveat": _CHANNEL_CAVEAT,
    }


_CHANNEL_CAVEAT = (
    "Earliest IN THIS CORPUS, IN THIS PERIOD — a fact about collection order as much "
    "as publication order. A channel collected more often will appear earlier more "
    "often, and the mention clock is a date, so same-day is as fine as it gets. This "
    "is not a claim about who reported anything first."
)


# --------------------------------------------------------------------------- #
#  by topic tag
# --------------------------------------------------------------------------- #


def by_topic_tag(session, period: Period) -> dict:
    """The period's mentions grouped by the curated TOPIC axis.

    Uses the documented safe join: ``keyword_mentions`` to the small
    ``keyword_tags`` only, never to ``articles`` (that join is the SQLCipher codec
    trap — it drags whole ~35 KB rows through the codec to read one small column).

    A tag is a LABELLED ASSERTION with a recorded source, never ground truth: the
    curated baseline tagged it, or the operator did. Most keywords carry no topic
    tag at all, so the untagged share is reported — a topic table that quietly
    covers a tenth of the corpus while looking complete is worse than none.
    """
    from src.database.models import KeywordMention, KeywordTag

    lo, hi = period.start, period.end
    in_period = and_(KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi)

    try:
        rows = (
            session.query(
                KeywordTag.tag,
                func.count(func.distinct(KeywordMention.article_id)),
                func.sum(KeywordMention.count),
            )
            .join(KeywordTag, KeywordTag.keyword_id == KeywordMention.keyword_id)
            .filter(in_period, KeywordTag.axis == "topic")
            .group_by(KeywordTag.tag)
            .all()
        )
        total_mentions = int(
            session.query(func.sum(KeywordMention.count)).filter(in_period).scalar() or 0
        )
        tagged_mentions = int(
            session.query(func.sum(KeywordMention.count))
            .join(KeywordTag, KeywordTag.keyword_id == KeywordMention.keyword_id)
            .filter(in_period, KeywordTag.axis == "topic")
            .scalar()
            or 0
        )
    except Exception as exc:  # noqa: BLE001 - a section degrades, never loses the edition
        _LOG.warning("bulletin: by_topic_tag failed", exc_info=True)
        return {
            "section": "by_topic_tag",
            "window": _window_of(period),
            "topics": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    topics = [
        {"topic": t, "articles": int(a or 0), "mentions": int(m or 0)}
        for t, a, m in rows
    ]
    topics.sort(key=lambda r: (-r["mentions"], r["topic"]))

    return {
        "section": "by_topic_tag",
        "window": _window_of(period),
        "topics": topics,
        "mentions_total": total_mentions,
        "mentions_tagged": tagged_mentions,
        "mentions_untagged": max(0, total_mentions - tagged_mentions),
        "method": (
            "period mentions joined to the curated keyword_tags topic axis only; a "
            "mention counts once per tag it carries, so tagged sums may exceed the "
            "distinct total where a keyword has several topics"
        ),
        "caveat": (
            "A topic tag is a labelled assertion with a recorded source — the curated "
            "baseline or the operator — never ground truth. Most keywords carry no "
            "topic tag, so this table describes the TAGGED slice; the untagged count "
            "beside it is the rest of the period, not an empty category."
        ),
    }


# --------------------------------------------------------------------------- #
#  changes of record
# --------------------------------------------------------------------------- #


def changes_of_record(session, period: Period) -> dict:
    """Tracked law and Wikipedia revisions observed during the period.

    These are the corpus's versioned sources: documents that change under a stable
    identity, where the CHANGE is the news rather than the document. Counts are
    exact; the example lists are bounded and say so.
    """
    from src.database.models import LawDocument, LawRevision, WikiPage, WikiRevision

    lo, hi = _bounds(period)
    out: dict[str, Any] = {"section": "changes_of_record", "window": _window_of(period)}

    try:
        law_q = session.query(LawRevision).filter(
            LawRevision.observed_at >= lo, LawRevision.observed_at < hi
        )
        out["law_revisions"] = int(law_q.count())
        out["law_revisions_flagged"] = int(law_q.filter(LawRevision.flagged.is_(True)).count())
        rows = (
            session.query(
                LawRevision.observed_at,
                LawRevision.delta_bytes,
                LawRevision.flagged,
                LawDocument.title,
                LawDocument.jurisdiction,
            )
            .outerjoin(LawDocument, LawDocument.id == LawRevision.document_id)
            .filter(LawRevision.observed_at >= lo, LawRevision.observed_at < hi)
            .order_by(LawRevision.observed_at.desc())
            .limit(_EXAMPLES)
            .all()
        )
        out["law_examples"] = [
            {
                "observed_at": str(r[0]) if r[0] else None,
                "delta_bytes": int(r[1]) if r[1] is not None else None,
                "flagged": bool(r[2]),
                "title": r[3],
                "jurisdiction": r[4],
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: law changes unreadable", exc_info=True)
        out["law_error"] = f"{type(exc).__name__}: {exc}"

    try:
        wiki_q = session.query(WikiRevision).filter(
            WikiRevision.timestamp >= lo, WikiRevision.timestamp < hi
        )
        out["wiki_revisions"] = int(wiki_q.count())
        out["wiki_revisions_flagged"] = int(wiki_q.filter(WikiRevision.flagged.is_(True)).count())
        rows = (
            session.query(
                WikiRevision.timestamp,
                WikiRevision.delta_bytes,
                WikiRevision.flagged,
                WikiRevision.editor_anon,
                WikiPage.title,
                WikiPage.wiki,  # the language-edition code; the column is `wiki`, not `lang`
            )
            .outerjoin(WikiPage, WikiPage.id == WikiRevision.page_id)
            .filter(WikiRevision.timestamp >= lo, WikiRevision.timestamp < hi)
            .order_by(WikiRevision.timestamp.desc())
            .limit(_EXAMPLES)
            .all()
        )
        out["wiki_examples"] = [
            {
                "timestamp": str(r[0]) if r[0] else None,
                "delta_bytes": int(r[1]) if r[1] is not None else None,
                "flagged": bool(r[2]),
                "editor_anonymous": bool(r[3]),
                "title": r[4],
                "edition": r[5],
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: wiki changes unreadable", exc_info=True)
        out["wiki_error"] = f"{type(exc).__name__}: {exc}"

    out["examples_limit"] = _EXAMPLES
    out["method"] = (
        "law revisions by observed_at and wiki revisions by their own timestamp, both "
        f"half-open in the period. Counts are exact; the example lists stop at "
        f"{_EXAMPLES} and the counts above them do not."
    )
    out["caveat"] = (
        "A revision is an observed CHANGE, not a judgement about it: `flagged` is the "
        "ingest-time large-change heuristic, and a large edit is as often a reorganisation "
        "as a substantive one. Only tracked documents are here — the absence of a "
        "jurisdiction means it is not tracked, not that its law stood still."
    )
    return out


# --------------------------------------------------------------------------- #
#  alerts
# --------------------------------------------------------------------------- #


def alerts(session, period: Period) -> dict:
    """Provider-declared hazard alerts that entered the corpus during the period.

    Hazards ingest as Articles under synthetic ``hazard.<provider>.local`` sources,
    with the provider's own event metadata on a linked detail row. Everything here
    is ASSERTED by USGS/GDACS — magnitude, severity tier, coordinates — and none of
    it is re-derived, re-scaled or combined into anything.

    The ruled alert boundary holds: urgent means a provider DECLARED a hazard. This
    section reports those declarations; it never promotes anything else into one.
    """
    from src.database.models import Article, HazardEventDetail

    clock = func.coalesce(Article.published_at, Article.created_at)
    lo, hi = _bounds(period)

    try:
        # ONE pass. Hazard declarations in a period are tens of rows, not thousands,
        # and every field is small, so materialising them costs less than the three
        # separate scans a count + group-by + example query would take.
        rows = (
            session.query(
                HazardEventDetail.provider,
                HazardEventDetail.event_type,
                HazardEventDetail.severity,
                HazardEventDetail.magnitude,
                HazardEventDetail.place,
                HazardEventDetail.event_time,
                Article.id,
                Article.title,
            )
            .join(Article, Article.id == HazardEventDetail.article_id)
            .filter(clock >= lo, clock < hi, Article.quarantined.isnot(True))
            .order_by(HazardEventDetail.event_time.desc())
            .all()
        )
        total = len(rows)
        by_provider: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for r in rows:
            by_provider[r[0]] = by_provider.get(r[0], 0) + 1
            key = r[1] or "unspecified"
            by_type[key] = by_type.get(key, 0) + 1
        rows = rows[:_EXAMPLES]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: alerts unreadable", exc_info=True)
        return {
            "section": "alerts",
            "window": _window_of(period),
            "events": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "section": "alerts",
        "window": _window_of(period),
        "events": total,
        "by_provider": [
            {"provider": p, "events": n}
            for p, n in sorted(by_provider.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_event_type": [
            {"event_type": t, "events": n}
            for t, n in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "examples": [
            {
                "provider": r[0],
                "event_type": r[1],
                "severity": r[2],
                "magnitude": r[3],
                "place": r[4],
                "event_time": str(r[5]) if r[5] else None,
                "article_id": int(r[6]),
                "title": r[7],
            }
            for r in rows
        ],
        "examples_limit": _EXAMPLES,
        "method": (
            "hazard-provenance articles in the period with their provider-asserted "
            "detail row; counts exact, examples bounded"
        ),
        "caveat": (
            "Every field here is what the provider published — magnitude, severity tier, "
            "coordinates, time — carried through unchanged and never combined. A quiet "
            "period means these providers declared little, or that this corpus was not "
            "collecting from them, and those two are not the same thing."
        ),
    }


# --------------------------------------------------------------------------- #
#  through time
# --------------------------------------------------------------------------- #


def through_time(session, period: Period, *, years_back: int = 5) -> dict:
    """The same calendar days, in earlier years — the cross-time counterweight.

    A periodic document structurally teaches a reader that recent equals important.
    This is the deliberate counterweight, and the design record calls it sacred: it
    is a LENS, never a reweighting. Nothing here re-ranks the period; it only shows
    what the corpus already holds for the same days in earlier years.

    A shared calendar date is a coincidence, not a connection — the caveat says so,
    because the temptation to read one is exactly why this section is easy to abuse.
    """
    from src.database.models import Article

    if period.days > _ANNIVERSARY_MAX_DAYS:
        return {
            "section": "through_time",
            "window": _window_of(period),
            "years": [],
            "skipped": (
                f"the period spans {period.days} days; past {_ANNIVERSARY_MAX_DAYS} the "
                "'same days in earlier years' lens stops being a lens — it becomes the "
                "whole of an earlier year, which the corpus already shows elsewhere"
            ),
            "method": "same (month, day) set, earlier years only",
            "caveat": _TIME_CAVEAT,
        }

    days = []
    d = period.start
    while d < period.end:
        days.append(f"{d.month:02d}-{d.day:02d}")
        d += timedelta(days=1)

    clock = func.coalesce(Article.published_at, Article.created_at)
    try:
        rows = (
            session.query(func.strftime("%Y", clock), func.count(Article.id))
            .filter(
                Article.quarantined.isnot(True),
                func.strftime("%m-%d", clock).in_(days),
                func.strftime("%Y", clock) < str(period.start.year),
                func.strftime("%Y", clock) >= str(period.start.year - int(years_back)),
            )
            .group_by(func.strftime("%Y", clock))
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("bulletin: through_time unreadable", exc_info=True)
        return {
            "section": "through_time",
            "window": _window_of(period),
            "years": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    years = [{"year": int(y), "articles": int(n or 0)} for y, n in rows if y]
    years.sort(key=lambda r: -r["year"])

    return {
        "section": "through_time",
        "window": _window_of(
            period, note=f"same {len(days)} calendar days, up to {years_back} earlier years"
        ),
        "years": years,
        "days_matched": len(days),
        "years_back": int(years_back),
        "method": (
            "articles on the same (month, day) set in earlier years, on the same "
            "coalesce(published_at, created_at) clock, quarantined excluded"
        ),
        "caveat": _TIME_CAVEAT,
    }


_TIME_CAVEAT = (
    "A lens, never a reweighting — cross-time recall is not traded for recency here. "
    "A shared calendar date is a coincidence, not a connection. An empty earlier year "
    "means this corpus holds nothing from it, which is almost always about when "
    "collection started rather than about the world."
)


# --------------------------------------------------------------------------- #
#  the registry
# --------------------------------------------------------------------------- #


def _rising(session, period, ctx):
    from src.bulletin.facts import rising_concepts

    return rising_concepts(session, period, limit=ctx.get("rising_limit", 20),
                           target_lang=ctx.get("target_lang"))


def _across(session, period, ctx):
    return across_channels(session, period, terms=(ctx.get("rising") or {}).get("terms"))


# (key, builder). Order is the edition's order. A builder takes
# ``(session, period, ctx)`` where ctx carries the run's options and any earlier
# section's output, so a later section can be scoped by an earlier one without
# recomputing it.
SECTIONS: tuple[tuple[str, Any], ...] = (
    ("rising_concepts", _rising),
    ("across_channels", _across),
    ("by_topic_tag", lambda s, p, _c: by_topic_tag(s, p)),
    ("changes_of_record", lambda s, p, _c: changes_of_record(s, p)),
    ("alerts", lambda s, p, _c: alerts(s, p)),
    ("through_time", lambda s, p, c: through_time(s, p, years_back=c.get("years_back", 5))),
)


def build_sections(session, period: Period, **options) -> list[dict]:
    """Run every registered section, in order, over one period.

    A section that raises is reported IN PLACE with its error and the run
    continues: one failing producer must not cost the edition, and a section that
    silently vanished would read as "nothing to report".
    """
    ctx: dict[str, Any] = dict(options)
    out: list[dict] = []
    for key, build in SECTIONS:
        try:
            bundle = build(session, period, ctx)
        except Exception as exc:  # noqa: BLE001 - one section never loses the edition
            _LOG.warning("bulletin: section %s failed", key, exc_info=True)
            bundle = {"section": key, "error": f"{type(exc).__name__}: {exc}"}
        ctx[key] = bundle
        if key == "rising_concepts":
            ctx["rising"] = bundle
        out.append(bundle)
    return out
