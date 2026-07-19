"""Story propagation — the TEMPORAL cascade of a topic across your sources.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a SHAPE, never a cause: for a term that spread across many DISTINCT sources in a
recent window, order the sources by WHEN each first carried the term — the diffusion
cascade (who carried it first, then the sequence of others, with the day-gaps between
them). It answers "how did this spread across my sources over time?" as a descriptive
timeline.

Deliberately DISTINCT from the neighbouring cards, so it is not a duplicate:
  * ``story_lineage`` traces a near-duplicate story toward a candidate PRIMARY/wire
    origin — this makes NO origin claim (the first source in time is not "the source");
  * ``echo_chamber`` measures near-identical TEXT coordination — this is topic (keyword)
    diffusion, which needs no shared wording;
  * ``manufactured_emergence`` fires on a term BORN WIDE with no prior history — this
    fires on any term with a genuine temporal SPREAD (a span, an ordering), new or not.

The innocent explanations are stated: a shared newswire, an event every outlet
independently covers, or coincidence all produce a cascade; and a keyword is a TOPIC, not
a specific claim. Independence is measured by DISTINCT SOURCES. Efficient by construction —
reads ONLY the denormalised ``keyword_mentions`` (source_id + observed_on), never the
article-content decrypt. No composite score; every figure is a real count or a day-gap.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import distinct, func

from src.database.models import Keyword, KeywordMention, Source

_LOG = logging.getLogger(__name__)

_IN_CHUNK = 600

STORY_PROPAGATION_CAVEAT = (
    "This is the ORDER in which your sources first carried a topic over time — a "
    "descriptive shape, never a cause and never an origin claim (the earliest source in "
    "time is not 'the source'). A shared newswire, an event every outlet independently "
    "covers, or plain coincidence all produce a cascade like this. A keyword is a TOPIC, "
    "not a specific claim. Independence is measured by distinct sources. Read it and judge."
)

STORY_PROPAGATION_METHOD = (
    "For a term mentioned across >= min_sources DISTINCT sources in the recent window, each "
    "source's FIRST mention date (keyword_mentions.observed_on) is taken and the sources are "
    "ordered by it — the diffusion cascade, with the day-gaps between successive sources. A "
    "term is surfaced only when the cascade spans >= min_span_days (a genuine temporal "
    "spread, not an all-at-once appearance). A term carried by an implausibly large share of "
    "same-language active sources is excluded as publishing furniture / a corpus-volume "
    "tracker, not a real topic (the DF-ubiquity gate). Reads the denormalised "
    "source_id/observed_on only (no content decrypt). Counts + day-gaps only, no score."
)


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def find_story_propagation(
    session,
    *,
    lookback_days: int = 21,
    min_sources: int = 3,
    min_span_days: int = 2,
    max_terms: int = 300,
    max_articles_per_item: int = 400,
    max_items: int = 8,
    today: date | None = None,
) -> dict:
    """Surface terms whose coverage propagated across sources over time.

    Returns ``{"items": [...], "count": n, "terms_scanned": n, "lookback_days": ...,
    "min_sources": ..., "min_span_days": ..., "method": ..., "caveat": ...}``. Bounded
    (recent window + capped candidate terms); degrades to an honest empty result.
    """
    from src.analytics.queries import _hidden_predicate

    today = today or datetime.now(timezone.utc).date()
    from datetime import timedelta

    cutoff = today - timedelta(days=lookback_days)
    hi = today + timedelta(days=1)
    win = [
        KeywordMention.observed_on >= cutoff,
        KeywordMention.observed_on < hi,
        KeywordMention.source_id.isnot(None),
        KeywordMention.observed_on.isnot(None),
    ]

    # Candidate terms: mentioned across >= min_sources distinct sources in the window.
    cand_rows = (
        session.query(
            KeywordMention.keyword_id,
            func.count(distinct(KeywordMention.source_id)).label("n_src"),
        )
        .filter(*win)
        .group_by(KeywordMention.keyword_id)
        .having(func.count(distinct(KeywordMention.source_id)) >= min_sources)
        .order_by(func.count(distinct(KeywordMention.source_id)).desc())
        .limit(max_terms)
        .all()
    )
    if not cand_rows:
        return _empty(lookback_days, min_sources, min_span_days)
    cand_ids = [int(kid) for kid, _ in cand_rows]
    n_src_by_kid = {int(kid): int(n or 0) for kid, n in cand_rows}

    # Per-language active-source counts over the WHOLE window (the DF-ubiquity gate's
    # denominator, S1.2) -- one small query, not per-candidate.
    from src.analytics.generic_terms import is_generic_by_df_ubiquity
    from src.analytics.managed import normalize_lang

    active_sids = [r[0] for r in session.query(distinct(KeywordMention.source_id)).filter(*win)]
    active_by_lang: dict[str, int] = {}
    for chunk in _chunks(active_sids):
        for _sid, lang in session.query(Source.id, Source.language).filter(
            Source.id.in_(chunk)
        ):
            lg = normalize_lang(lang)
            if lg:
                active_by_lang[lg] = active_by_lang.get(lg, 0) + 1

    # One grouped query: per (keyword, source) FIRST mention date in the window.
    first_seen: dict[int, dict[int, date]] = defaultdict(dict)
    for chunk in _chunks(cand_ids):
        for kid, sid, first in (
            session.query(
                KeywordMention.keyword_id,
                KeywordMention.source_id,
                func.min(KeywordMention.observed_on),
            )
            .filter(*win)
            .filter(KeywordMention.keyword_id.in_(chunk))
            .group_by(KeywordMention.keyword_id, KeywordMention.source_id)
            .all()
        ):
            if first is not None:
                first_seen[int(kid)][int(sid)] = first

    # Keyword terms (drop stoplisted + generic/furniture terms) + source names.
    is_hidden = _hidden_predicate()
    kw_terms: dict[int, str] = {}
    for chunk in _chunks(cand_ids):
        for kid, norm, lang in (
            session.query(Keyword.id, Keyword.normalized_term, Keyword.language)
            .filter(Keyword.id.in_(chunk))
            .all()
        ):
            if is_hidden(norm):
                continue
            kid = int(kid)
            kw_lang = normalize_lang(lang)
            if kw_lang and is_generic_by_df_ubiquity(
                n_src_by_kid.get(kid, 0), active_by_lang.get(kw_lang, 0)
            ):
                continue  # publishing furniture / a term nearly every active source carries
            kw_terms[kid] = norm
    live_ids = [k for k in cand_ids if k in kw_terms]
    if not live_ids:
        return _empty(lookback_days, min_sources, min_span_days, terms_scanned=len(cand_ids))

    src_ids = {sid for k in live_ids for sid in first_seen.get(k, {})}
    src_name: dict[int, str] = {}
    for chunk in _chunks(sorted(src_ids)):
        for sid, name in (
            session.query(Source.id, Source.name).filter(Source.id.in_(chunk)).all()
        ):
            src_name[int(sid)] = name or f"source-{sid}"

    items: list[dict] = []
    for kid in live_ids:
        per_source = first_seen.get(kid, {})
        if len(per_source) < min_sources:
            continue
        ordered = sorted(per_source.items(), key=lambda kv: (kv[1], kv[0]))
        span = (ordered[-1][1] - ordered[0][1]).days
        if span < min_span_days:
            continue  # an all-at-once appearance is not a temporal cascade
        cascade = []
        prev: date | None = None
        for sid, first in ordered:
            cascade.append(
                {
                    "source": src_name.get(sid, f"source-{sid}"),
                    "first_seen": first.isoformat(),
                    "gap_days": (first - prev).days if prev is not None else 0,
                }
            )
            prev = first
        items.append(
            {
                "term": kw_terms[kid],
                "keyword_id": kid,
                "distinct_sources": len(per_source),
                "span_days": span,
                "first_source": cascade[0]["source"],
                "first_seen": cascade[0]["first_seen"],
                "last_seen": ordered[-1][1].isoformat(),
                "cascade": cascade,
            }
        )

    items.sort(key=lambda it: (-it["distinct_sources"], -it["span_days"]))
    items = items[:max_items]
    # Fetch article ids ONLY for the survivors (never per-term inside the scan loop — that
    # would run one query for every qualifying term while only max_items are kept).
    for it in items:
        it["article_ids"] = _term_article_ids(session, it["keyword_id"], cutoff, hi, max_articles_per_item)
        it["n_articles"] = len(it["article_ids"])
    return {
        "items": items,
        "count": len(items),
        "terms_scanned": len(cand_ids),
        "lookback_days": lookback_days,
        "min_sources": min_sources,
        "min_span_days": min_span_days,
        "method": STORY_PROPAGATION_METHOD,
        "caveat": STORY_PROPAGATION_CAVEAT,
    }


def _term_article_ids(session, kid: int, cutoff, hi, cap: int) -> list[int]:
    rows = (
        session.query(KeywordMention.article_id)
        .filter(
            KeywordMention.keyword_id == kid,
            KeywordMention.observed_on >= cutoff,
            KeywordMention.observed_on < hi,
        )
        .distinct()
        .limit(cap)
        .all()
    )
    return sorted(int(r[0]) for r in rows)


def _empty(
    lookback_days: int, min_sources: int, min_span_days: int, *, terms_scanned: int = 0
) -> dict:
    return {
        "items": [],
        "count": 0,
        "terms_scanned": terms_scanned,
        "lookback_days": lookback_days,
        "min_sources": min_sources,
        "min_span_days": min_span_days,
        "method": STORY_PROPAGATION_METHOD,
        "caveat": STORY_PROPAGATION_CAVEAT,
    }
