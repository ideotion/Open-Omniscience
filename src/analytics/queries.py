"""
Read-side analytics over the keyword-mention store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every figure here is a real aggregate over ``KeywordMention`` — counts, a defined
growth ratio for "trending", and PMI for associations — with sample sizes and an
explicit method/caveat. Nothing is invented. Context snippets are sliced from the
stored article text around the recorded first-occurrence offset.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import func

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedPlace,
    Keyword,
    KeywordFamilyOverride,
    KeywordMention,
    Source,
)


def kind_of(kw: Keyword) -> str:
    if not kw.is_entity:
        return "term"
    return kw.entity_type or "entity"


def _normalize(term: str) -> str:
    return " ".join(term.split()).casefold()


def load_overrides(session) -> dict[str, dict]:
    """User family overrides as ``{normalized: {family_key, label, kind}}`` (authoritative)."""
    return {
        o.normalized_term: {"family_key": o.family_key, "label": o.canonical_label, "kind": o.kind}
        for o in session.query(KeywordFamilyOverride).all()
    }


def resolve_keyword(session, term: str) -> Keyword | None:
    """Map a user term to a stored keyword: exact normalized match, else best LIKE."""
    norm = _normalize(term)
    if not norm:
        return None
    kw = session.query(Keyword).filter_by(normalized_term=norm).first()
    if kw:
        return kw
    rows = (
        session.query(Keyword, func.coalesce(func.sum(KeywordMention.count), 0).label("m"))
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .filter(Keyword.normalized_term.like(f"%{norm}%"))
        .group_by(Keyword.id)
        .order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(1)
        .all()
    )
    return rows[0][0] if rows else None


def _hidden_predicate():
    """Build is_hidden(normalized) from the keyword-filter settings.

    Hides built-in stopwords + user exclusions + too-short / numeric terms, so
    "dumb" keywords never appear in listings (even for already-stored mentions).
    """
    from src.analytics.filters import hidden_set, load_settings

    fs = load_settings()
    hidden = hidden_set()
    min_len, drop_numeric = fs.min_length, fs.drop_numeric

    def is_hidden(norm: str | None) -> bool:
        if not norm:
            return True
        if norm in hidden or len(norm) < min_len:
            return True
        return bool(drop_numeric and norm.replace(" ", "").isdigit())

    return is_hidden


def _apply_kind(query, kind: str | None):
    if not kind:
        return query
    if kind == "term":
        return query.filter(Keyword.is_entity.is_(False))
    if kind == "entity":
        return query.filter(Keyword.is_entity.is_(True))
    return query.filter(Keyword.entity_type == kind)


def _bucket_key(d: date, bucket: str) -> str:
    if bucket == "day":
        return d.isoformat()
    if bucket == "month":
        return d.strftime("%Y-%m")
    return d.strftime("%G-W%V")  # ISO week


def trend(session, term: str, *, bucket: str = "week", country: str | None = None) -> dict:
    """Mention volume over time for one keyword, bucketed by day/week/month."""
    kw = resolve_keyword(session, term)
    if kw is None:
        return {"term": term, "resolved": None, "points": [], "total": 0, "articles": 0}
    q = session.query(KeywordMention.observed_on, func.sum(KeywordMention.count)).filter(
        KeywordMention.keyword_id == kw.id, KeywordMention.observed_on.isnot(None)
    )
    if country:
        q = q.filter(KeywordMention.country == country.lower())
    rows = q.group_by(KeywordMention.observed_on).all()
    buckets: dict[str, int] = {}
    for d, c in rows:
        buckets[_bucket_key(d, bucket)] = buckets.get(_bucket_key(d, bucket), 0) + int(c or 0)
    points = [{"date": k, "count": v} for k, v in sorted(buckets.items())]
    articles = (
        session.query(func.count(func.distinct(KeywordMention.article_id)))
        .filter(KeywordMention.keyword_id == kw.id)
        .scalar()
        or 0
    )
    return {
        "term": term,
        "bucket": bucket,
        "resolved": {"term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw)},
        "points": points,
        "total": sum(p["count"] for p in points),
        "articles": int(articles),
    }


def top_terms(
    session,
    *,
    days: int | None = None,
    country: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    group: bool = False,
) -> dict:
    """Most-mentioned keywords (optionally within a window / country / kind).

    With ``group=True`` the surface variants of one entity are merged into a single
    family (``Trump`` / ``Trump's`` / ``Donald Trump`` -> one row) for display, with
    summed mentions and the member forms listed — see src/analytics/families.py.
    """
    q = session.query(
        Keyword,
        func.sum(KeywordMention.count).label("m"),
        func.count(func.distinct(KeywordMention.article_id)).label("arts"),
    ).join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
    if days:
        q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
    if country:
        q = q.filter(KeywordMention.country == country.lower())
    q = _apply_kind(q, kind)
    rows = (
        q.group_by(Keyword.id)
        .order_by(func.sum(KeywordMention.count).desc())
        .limit(limit * 4)
        .all()
    )
    is_hidden = _hidden_predicate()
    cap = limit * 4 if group else limit
    terms = []
    for k, m, a in rows:
        if is_hidden(k.normalized_term):
            continue
        terms.append(
            {
                "term": k.term,
                "normalized": k.normalized_term,
                "kind": kind_of(k),
                "mentions": int(m),
                "articles": int(a),
            }
        )
        if len(terms) >= cap:
            break
    if group:
        from src.analytics.families import build_families

        terms = [f.to_dict() for f in build_families(terms, load_overrides(session))]
    terms = terms[:limit]
    return {
        "count": len(terms),
        "days": days,
        "country": country,
        "kind": kind,
        "grouped": group,
        "terms": terms,
    }


def corpus_keywords(
    session,
    *,
    article_ids: list[int],
    kind: str | None = None,
    limit: int = 30,
) -> dict:
    """Top keywords across a GIVEN set of articles (the analysis-window corpus).

    Like ``top_terms`` but scoped to an explicit article set rather than a
    time/country window — so the analysis window can show "the keywords of THESE
    matched articles". Ordered by article SPREAD (how many of the set mention the
    term), then mentions. Hidden/function words are dropped (the shared policy).
    No score — counts only; the caller states the honest method + caveat + n.
    """
    if not article_ids:
        return {"count": 0, "n_articles": 0, "terms": []}
    q = (
        session.query(
            Keyword,
            func.sum(KeywordMention.count).label("m"),
            func.count(func.distinct(KeywordMention.article_id)).label("arts"),
        )
        .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .filter(KeywordMention.article_id.in_(article_ids))
    )
    q = _apply_kind(q, kind)
    rows = (
        q.group_by(Keyword.id)
        .order_by(
            func.count(func.distinct(KeywordMention.article_id)).desc(),
            func.sum(KeywordMention.count).desc(),
        )
        .limit(limit * 4)
        .all()
    )
    is_hidden = _hidden_predicate()
    terms = []
    for k, m, a in rows:
        if is_hidden(k.normalized_term):
            continue
        terms.append(
            {
                "term": k.term,
                "normalized": k.normalized_term,
                "kind": kind_of(k),
                "mentions": int(m),
                "articles": int(a),
            }
        )
        if len(terms) >= limit:
            break
    return {"count": len(terms), "n_articles": len(article_ids), "terms": terms}


def corpus_who(session, *, article_ids: list[int], limit: int = 40) -> dict:
    """WHO (people/orgs) deduced across a GIVEN article set — like who_aggregate
    but scoped to the analysis window's matched articles. Counts only, deduced
    from text, never a confirmed identity."""
    if not article_ids:
        return {"count": 0, "entities": []}
    arts = func.count(func.distinct(ArticleEntity.article_id))
    men = func.sum(ArticleEntity.mentions)
    rows = (
        session.query(ArticleEntity.name, ArticleEntity.entity_class, arts.label("a"), men.label("m"))
        .filter(ArticleEntity.article_id.in_(article_ids))
        .group_by(ArticleEntity.name, ArticleEntity.entity_class)
        .order_by(arts.desc(), men.desc())
        .limit(limit)
        .all()
    )
    entities = [
        {"name": n, "class": c, "articles": int(a or 0), "mentions": int(m or 0)}
        for n, c, a, m in rows
    ]
    return {"count": len(entities), "entities": entities,
            "caveat": "Deduced from text, never confirmed."}


def corpus_where(session, *, article_ids: list[int], limit: int = 40) -> dict:
    """WHERE (places) deduced across a GIVEN article set — like where_aggregate
    but scoped to the matched articles. lat/lon when the gazetteer knows the
    place (null otherwise — no fabricated position). Deduced, never confirmed."""
    if not article_ids:
        return {"count": 0, "places": []}
    arts = func.count(func.distinct(ArticleMentionedPlace.article_id))
    men = func.sum(ArticleMentionedPlace.mentions)
    rows = (
        session.query(
            ArticleMentionedPlace.name, ArticleMentionedPlace.country,
            ArticleMentionedPlace.kind, func.max(ArticleMentionedPlace.lat),
            func.max(ArticleMentionedPlace.lon), arts.label("a"), men.label("m"),
        )
        .filter(ArticleMentionedPlace.article_id.in_(article_ids))
        .group_by(ArticleMentionedPlace.name, ArticleMentionedPlace.country, ArticleMentionedPlace.kind)
        .order_by(arts.desc(), men.desc())
        .limit(limit)
        .all()
    )
    places = [
        {"name": n, "country": cc, "kind": k, "lat": lat, "lon": lon,
         "articles": int(a or 0), "mentions": int(m or 0)}
        for n, cc, k, lat, lon, a, m in rows
    ]
    return {"count": len(places), "places": places,
            "caveat": "Deduced from text, never confirmed."}


_SENTIMENT_CAVEAT = (
    "Tone is measured by VADER, an ENGLISH-lexicon method; scores for non-English "
    "articles are unreliable (see the English share). Counts only, never a verdict."
)


def corpus_sentiment(session, *, article_ids: list[int]) -> dict:
    """Tone distribution across a GIVEN article set, from the STORED per-article
    VADER valence (Article.sentiment_score/label). VADER is English-lexicon based, so
    the ``english_scored`` share is returned and the caveat says non-English scores
    are unreliable. Counts only; tone is a measured word-valence, not a verdict."""
    from collections import Counter

    if not article_ids:
        return {"n_articles": 0, "n_scored": 0, "labels": {}, "mean_score": None,
                "english_scored": 0, "caveat": _SENTIMENT_CAVEAT}
    rows = (
        session.query(Article.sentiment_label, Article.sentiment_score, Article.language)
        .filter(Article.id.in_(article_ids))
        .all()
    )
    labels: Counter = Counter()
    scores: list[float] = []
    english_scored = 0
    for label, score, lang in rows:
        if score is None:
            continue
        scores.append(float(score))
        labels[(label or "unlabeled").lower()] += 1
        if (lang or "").lower().startswith("en"):
            english_scored += 1
    n = len(scores)
    return {
        "n_articles": len(article_ids),
        "n_scored": n,
        "labels": dict(labels),
        "mean_score": round(sum(scores) / n, 3) if n else None,
        "english_scored": english_scored,
        "method": "Per-article VADER valence (stored at ingest), aggregated over the matched set.",
        "caveat": _SENTIMENT_CAVEAT,
    }


def corpus_sources(session, *, article_ids: list[int], limit: int = 40) -> dict:
    """How each SOURCE covers the matched set (the analysis window's source view):
    per source, the article VOLUME, mean VADER tone, and the TIMING span (first/last
    published) -- so different angles by volume/tone/timing are visible side by side.
    Counts + dates are exact; mean tone inherits the VADER English-only caveat. NO
    ranking, NO verdict -- presence here is coverage, not credibility."""
    if not article_ids:
        return {"count": 0, "sources": []}
    rows = (
        session.query(
            Source.name, Source.domain,
            func.count(Article.id).label("n"),
            func.avg(Article.sentiment_score),
            func.min(Article.published_at),
            func.max(Article.published_at),
        )
        .join(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(article_ids))
        .group_by(Source.id)
        .order_by(func.count(Article.id).desc())
        .limit(limit)
        .all()
    )
    sources = [
        {
            "name": name,
            "domain": dom,
            "articles": int(n or 0),
            "mean_tone": round(float(avg), 3) if avg is not None else None,
            "first": fp.isoformat() if fp else None,
            "last": lp.isoformat() if lp else None,
        }
        for name, dom, n, avg, fp, lp in rows
    ]
    return {
        "count": len(sources),
        "sources": sources,
        "method": "Matched articles grouped by source: exact volume + publication span; mean tone is VADER.",
        "caveat": (
            "Volume and timing are exact counts; mean tone is VADER (English-lexicon, "
            "unreliable for non-English). No ranking and no verdict -- coverage, not credibility."
        ),
    }


def trending(
    session,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    country: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    min_recent: int = 3,
) -> dict:
    """Rising keywords: recent volume vs the prior-period rate (a defined ratio).

    ``growth`` = recent_count / expected, where expected = (prior_count /
    baseline_days) * window_days. New terms (no prior) report growth as the recent
    count. This is a transparent ratio, not a significance test.
    """
    today = date.today()
    w_start = today - timedelta(days=window_days)
    b_start = w_start - timedelta(days=baseline_days)

    def _counts(lo, hi):
        q = session.query(KeywordMention.keyword_id, func.sum(KeywordMention.count)).filter(
            KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi
        )
        if country:
            q = q.filter(KeywordMention.country == country.lower())
        return dict(q.group_by(KeywordMention.keyword_id).all())

    recent = _counts(w_start, today + timedelta(days=1))
    prior = _counts(b_start, w_start)

    scored = []
    for kid, rc in recent.items():
        rc = int(rc or 0)
        if rc < min_recent:
            continue
        pc = int(prior.get(kid, 0) or 0)
        expected = (pc / baseline_days) * window_days
        growth = rc / expected if expected >= 1 else float(rc)
        scored.append((kid, rc, pc, round(expected, 2), round(growth, 2)))
    scored.sort(key=lambda x: (-x[4], -x[1]))

    is_hidden = _hidden_predicate()
    out = []
    for kid, rc, pc, expected, growth in scored:
        kw = session.get(Keyword, kid)
        if kw is None or (kind and kind_of(kw) != kind) or is_hidden(kw.normalized_term):
            continue
        out.append(
            {
                "term": kw.term,
                "normalized": kw.normalized_term,
                "kind": kind_of(kw),
                "recent": rc,
                "prior": pc,
                "expected": expected,
                "growth": growth,
            }
        )
        if len(out) >= limit:
            break
    return {
        "count": len(out),
        "window_days": window_days,
        "baseline_days": baseline_days,
        "country": country,
        "kind": kind,
        "terms": out,
        # Multiple-comparisons honesty (evidence-tiered cards): how many
        # candidates were screened to surface these winners — with many terms
        # scanned, some ratios will be high by chance (winner's curse).
        "scanned": len(scored),
        "keywords_with_recent_mentions": len(recent),
        "method": "recent volume vs prior-period rate (ratio, not a significance test)",
    }


# Preset windows for the Insights "Trends" view (maintainer-ruled 2026-06-16):
# rising keywords across past 24h · past week · past month, side by side. Each
# carries its own prior-period baseline (a longer look-back for the longer window).
_TREND_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("24h", 1, 7),    # 1-day window vs the prior 7 days
    ("7d", 7, 30),    # 1-week window vs the prior 30 days
    ("30d", 30, 90),  # 1-month window vs the prior 90 days
)


def trending_windows(
    session,
    *,
    country: str | None = None,
    kind: str | None = None,
    limit: int = 10,
) -> dict:
    """Rising keywords across THREE preset windows side by side (24h · 7d · 30d).

    The substrate for the Insights "Trends" redesign (maintainer-ruled 2026-06-16):
    each window reuses :func:`trending` (the SAME transparent recent-vs-prior rate
    ratio, never a composite score). Short windows are sparse on a young corpus, so
    each term carries its raw ``recent`` count (n) and the caller states the
    early-corpus honesty. No score; the ratio is a disclosed method.
    """
    windows = []
    for label, wdays, bdays in _TREND_WINDOWS:
        res = trending(
            session,
            window_days=wdays,
            baseline_days=bdays,
            country=country,
            kind=kind,
            limit=limit,
            # 24h on a young corpus is thin — don't gate it out; show n + caveat.
            min_recent=1 if wdays == 1 else 2,
        )
        windows.append(
            {
                "label": label,
                "window_days": wdays,
                "baseline_days": bdays,
                "terms": res["terms"],
                "count": res["count"],
                "scanned": res["scanned"],
            }
        )
    return {
        "windows": windows,
        "method": (
            "Rising keywords per window: recent volume vs the prior-period rate "
            "(a disclosed ratio, never a score)."
        ),
        "caveat": (
            "Short windows (24h) are sparse on a young corpus — read the count (n) "
            "before the ratio; with many terms scanned, some ratios run high by chance."
        ),
    }


def _group_pairs(pairs: list[dict], overrides: dict[str, dict] | None = None) -> list[dict]:
    """Merge co-occurring surface variants into one family node (for the mind-map).

    Summed co-occurrence, the strongest member PMI, and the member forms listed —
    so ``Trump`` / ``Trump's`` / ``Donald Trump`` are one neighbour, not three.
    User overrides (manual merge/split) are honoured.
    """
    from src.analytics.families import build_families

    by_norm = {p["normalized"]: p for p in pairs}
    out = []
    for fam in build_families(
        [
            {
                "normalized": p["normalized"],
                "term": p["term"],
                "kind": p["kind"],
                "mentions": p["cooccur"],
            }
            for p in pairs
        ],
        overrides or {},
    ):
        members = [by_norm[m["normalized"]] for m in fam.members if m["normalized"] in by_norm]
        out.append(
            {
                "term": fam.canonical,
                "normalized": fam.normalized,
                "kind": fam.kind,
                "cooccur": sum(p["cooccur"] for p in members),
                "n_b": max((p["n_b"] for p in members), default=0),
                "pmi": max((p["pmi"] for p in members), default=0.0),
                "variants": fam.variant_count,
                "members": [p["term"] for p in members],
            }
        )
    out.sort(key=lambda p: (-p["pmi"], -p["cooccur"]))
    return out


def _window_filter(q, start=None, end=None):
    """Apply an observed_on window (ISO dates / date objects) to a mention query."""
    if start:
        q = q.filter(KeywordMention.observed_on >= start)
    if end:
        q = q.filter(KeywordMention.observed_on <= end)
    return q


def associations(
    session,
    term: str,
    *,
    limit: int = 20,
    min_cooccur: int = 2,
    group: bool = False,
    days: int | None = None,
    start=None,
    end=None,
) -> dict:
    """Keywords that co-occur with ``term`` in the same articles, ranked by PMI.

    With ``group=True`` the neighbours are merged into entity families (one node
    per entity instead of one per surface form) — see src/analytics/families.py.
    ``days`` / ``start`` / ``end`` window the analysis (maintainer 2026-06-11:
    the date spectrum is tweakable); PMI is then computed WITHIN the window —
    the method string says so.
    """
    if days and not start:
        start = date.today() - timedelta(days=days)
    kw = resolve_keyword(session, term)
    if kw is None:
        return {"term": term, "resolved": None, "pairs": []}
    total = (
        _window_filter(
            session.query(func.count(func.distinct(KeywordMention.article_id))), start, end
        ).scalar()
        or 0
    )
    target_articles = [
        a
        for (a,) in _window_filter(
            session.query(KeywordMention.article_id).filter(
                KeywordMention.keyword_id == kw.id
            ),
            start,
            end,
        ).distinct()
    ]
    n_a = len(target_articles)
    if not target_articles or total == 0:
        return {
            "term": term,
            "resolved": {"term": kw.term, "kind": kind_of(kw)},
            "corpus_articles": int(total),
            "n_articles_with_term": n_a,
            "pairs": [],
        }

    co_rows = (
        _window_filter(
            session.query(
                KeywordMention.keyword_id, func.count(func.distinct(KeywordMention.article_id))
            ),
            start,
            end,
        )
        .filter(KeywordMention.article_id.in_(target_articles), KeywordMention.keyword_id != kw.id)
        .group_by(KeywordMention.keyword_id)
        .having(func.count(func.distinct(KeywordMention.article_id)) >= min_cooccur)
        .all()
    )
    is_hidden = _hidden_predicate()
    pairs = []
    for kid, co in co_rows:
        co = int(co)
        n_b = (
            _window_filter(
                session.query(func.count(func.distinct(KeywordMention.article_id))).filter(
                    KeywordMention.keyword_id == kid
                ),
                start,
                end,
            ).scalar()
            or 1
        )
        pmi = math.log2((co * total) / (n_a * n_b)) if co > 0 else 0.0
        k2 = session.get(Keyword, kid)
        if k2 is None or is_hidden(k2.normalized_term):
            continue
        pairs.append(
            {
                "term": k2.term,
                "normalized": k2.normalized_term,
                "kind": kind_of(k2),
                "cooccur": co,
                "n_b": int(n_b),
                "pmi": round(pmi, 3),
            }
        )
    pairs.sort(key=lambda p: (-p["pmi"], -p["cooccur"]))
    if group:
        pairs = _group_pairs(pairs, load_overrides(session))
    return {
        "term": term,
        "resolved": {"term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw)},
        "corpus_articles": int(total),
        "n_articles_with_term": n_a,
        "grouped": group,
        "pairs": pairs[:limit],
        "window": {"days": days, "start": str(start) if start else None, "end": str(end) if end else None},
        "method": "pointwise mutual information over article co-occurrence"
        + (" within the selected window" if (start or end) else ""),
        "caveat": "Association is not causation; PMI on small samples is noisy.",
    }


def context(session, term: str, *, limit: int = 10, window: int = 180) -> dict:
    """Recent mention snippets for a keyword, sliced from the stored article text."""
    kw = resolve_keyword(session, term)
    if kw is None:
        return {"term": term, "resolved": None, "mentions": []}
    rows = (
        session.query(KeywordMention, Article)
        .join(Article, Article.id == KeywordMention.article_id)
        .filter(KeywordMention.keyword_id == kw.id)
        .order_by(KeywordMention.observed_on.desc(), KeywordMention.id.desc())
        .limit(limit)
        .all()
    )
    items = []
    for m, a in rows:
        content = a.get_content() or ""
        off = m.first_offset or 0
        start, end = max(0, off - window), min(len(content), off + window)
        snippet = content[start:end].strip()
        items.append(
            {
                "article_id": a.id,
                "title": a.title,
                "url": a.url,
                "source": a.source.name if a.source else None,
                "observed_on": m.observed_on.isoformat() if m.observed_on else None,
                "country": m.country,
                "city": m.city,
                "snippet": ("…" if start > 0 else "")
                + snippet
                + ("…" if end < len(content) else ""),
            }
        )
    return {
        "term": term,
        "resolved": {"term": kw.term, "kind": kind_of(kw)},
        "count": len(items),
        "mentions": items,
    }


def map_data(
    session,
    *,
    days: int | None = 30,
    kind: str | None = None,
    top_per_area: int = 5,
    min_mentions: int = 1,
) -> dict:
    """Top keywords per country and per city (from denormalised mention facets)."""
    is_hidden = _hidden_predicate()

    def _kind_cols(is_entity, entity_type) -> str:
        # kind_of() over plain columns: the map aggregates thousands of
        # (area, keyword) groups, and materialising full ORM entities for each
        # measurably dominates the endpoint at corpus scale (perf batch).
        if not is_entity:
            return "term"
        return entity_type or "entity"

    def _agg(area_col):
        q = (
            session.query(
                area_col,
                Keyword.term,
                Keyword.normalized_term,
                Keyword.is_entity,
                Keyword.entity_type,
                func.sum(KeywordMention.count).label("m"),
            )
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(area_col.isnot(None))
        )
        if days:
            q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
        q = _apply_kind(q, kind)
        rows = (
            q.group_by(area_col, Keyword.id).order_by(func.sum(KeywordMention.count).desc()).all()
        )
        areas: dict[str, list] = {}
        for area, term, norm, is_ent, ent_type, m in rows:
            if is_hidden(norm):
                continue
            lst = areas.setdefault(area, [])
            if len(lst) < top_per_area and int(m) >= min_mentions:
                lst.append(
                    {"term": term, "kind": _kind_cols(is_ent, ent_type), "mentions": int(m)}
                )
        return areas

    def _agg_cities():
        q = (
            session.query(
                KeywordMention.city,
                KeywordMention.country,
                Keyword.term,
                Keyword.normalized_term,
                Keyword.is_entity,
                Keyword.entity_type,
                func.sum(KeywordMention.count).label("m"),
            )
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(KeywordMention.city.isnot(None))
        )
        if days:
            q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
        q = _apply_kind(q, kind)
        rows = (
            q.group_by(KeywordMention.city, KeywordMention.country, Keyword.id)
            .order_by(func.sum(KeywordMention.count).desc())
            .all()
        )
        out: dict[tuple, dict] = {}
        for city, country, term, norm, is_ent, ent_type, m in rows:
            if is_hidden(norm):
                continue
            slot = out.setdefault((city, country), {"name": city, "country": country, "top": []})
            if len(slot["top"]) < top_per_area and int(m) >= min_mentions:
                slot["top"].append(
                    {"term": term, "kind": _kind_cols(is_ent, ent_type), "mentions": int(m)}
                )
        return list(out.values())

    countries = _agg(KeywordMention.country)
    return {
        "days": days,
        "kind": kind,
        "countries": [{"code": c, "top": t} for c, t in sorted(countries.items())],
        "cities": sorted(_agg_cities(), key=lambda c: c["name"] or ""),
    }


def status(session) -> dict:
    """Indexing status for the Insights tab."""
    total_articles = session.query(func.count(Article.id)).scalar() or 0
    indexed = session.query(func.count(func.distinct(KeywordMention.article_id))).scalar() or 0
    keywords = session.query(func.count(Keyword.id)).scalar() or 0
    entities = (
        session.query(func.count(Keyword.id)).filter(Keyword.is_entity.is_(True)).scalar() or 0
    )
    mentions = session.query(func.count(KeywordMention.id)).scalar() or 0
    return {
        "total_articles": int(total_articles),
        "indexed_articles": int(indexed),
        "remaining": int(total_articles) - int(indexed),
        "keywords": int(keywords),
        "entities": int(entities),
        "mentions": int(mentions),
    }


def who_aggregate(
    session,
    *,
    entity_class: str | None = None,
    days: int | None = None,
    country: str | None = None,
    limit: int = 50,
    min_articles: int = 1,
) -> dict:
    """Corpus-wide WHO: people and organizations DEDUCED from article text
    (the When/Where/Who substrate, T12), aggregated by surface name + class.

    Honest counts only — there is NO score. Each row reports the number of
    DISTINCT articles the name appears in (``articles``) and the summed
    in-article occurrence count (``mentions``). Names are lexical surface
    forms: the extractor does not disambiguate identities (two different
    people sharing a name merge into one row; an organisation name that is
    also a common word is not separated), so every figure is DEDUCED from
    text, never a confirmed identity. Rows are ordered by article spread, then
    by mentions. ``coverage`` states the denominator honestly: how many
    articles carry any who-extraction at all.
    """
    cls = entity_class if entity_class in ("person", "organization") else None
    since = date.today() - timedelta(days=days) if days else None
    cc = country.lower() if country else None

    def _scoped(query):
        if cls:
            query = query.filter(ArticleEntity.entity_class == cls)
        if since is not None or cc is not None:
            query = query.join(Article, Article.id == ArticleEntity.article_id)
            if since is not None:
                query = query.filter(Article.published_at >= since)
            if cc is not None:
                query = query.filter(Article.country == cc)
        return query

    arts_expr = func.count(func.distinct(ArticleEntity.article_id))
    men_expr = func.sum(ArticleEntity.mentions)
    q = _scoped(
        session.query(
            ArticleEntity.name,
            ArticleEntity.entity_class,
            arts_expr.label("arts"),
            men_expr.label("m"),
        )
    ).group_by(ArticleEntity.name, ArticleEntity.entity_class)
    if min_articles > 1:
        q = q.having(arts_expr >= min_articles)
    rows = q.order_by(arts_expr.desc(), men_expr.desc()).limit(limit).all()

    coverage = (
        _scoped(session.query(func.count(func.distinct(ArticleEntity.article_id)))).scalar() or 0
    )

    entities = [
        {
            "name": name,
            "class": ecls,
            "articles": int(arts or 0),
            "mentions": int(m or 0),
        }
        for name, ecls, arts, m in rows
    ]
    return {
        "count": len(entities),
        "entity_class": cls,
        "days": days,
        "country": cc,
        "min_articles": min_articles,
        "coverage_articles": int(coverage),
        "method": (
            "Lexical surface names deduced from article text at ingest "
            "(extractor lexical-v1), aggregated by exact name + class. Names "
            "are NOT disambiguated: same-name people merge and a name is not "
            "a confirmed identity. Figures are distinct-article spread and "
            "summed in-text mentions; there is no score."
        ),
        "caveat": "Deduced from text, never confirmed.",
        "entities": entities,
    }


def where_aggregate(
    session,
    *,
    kind: str | None = None,
    days: int | None = None,
    country: str | None = None,
    limit: int = 50,
    min_articles: int = 1,
) -> dict:
    """Corpus-wide WHERE: places DEDUCED from article text (the When/Where/Who
    substrate, T12), aggregated by name + country.

    Honest counts only — there is NO score. Each row reports the number of
    DISTINCT articles the place appears in (``articles``) and the summed
    in-article occurrence count (``mentions``), ordered by article spread.
    ``lat``/``lon`` carry the gazetteer coordinate when the place is known
    (``null`` otherwise — no fabricated position; ``placed`` counts how many
    rows are mappable). The ``country`` filter selects places LOCATED in that
    country (the place's own ISO-2), not the source's country. Names are lexical
    surface forms the extractor does not disambiguate beyond a source-country
    hint, so every figure is DEDUCED from text, never a confirmed location.
    ``coverage_articles`` states the denominator: how many articles carry any
    place extraction at all.
    """
    k = kind if kind in ("city", "country") else None
    since = date.today() - timedelta(days=days) if days else None
    cc = country.lower() if country else None

    def _scoped(query):
        if k:
            query = query.filter(ArticleMentionedPlace.kind == k)
        if cc is not None:
            query = query.filter(ArticleMentionedPlace.country == cc)
        if since is not None:
            query = query.join(Article, Article.id == ArticleMentionedPlace.article_id)
            query = query.filter(Article.published_at >= since)
        return query

    arts_expr = func.count(func.distinct(ArticleMentionedPlace.article_id))
    men_expr = func.sum(ArticleMentionedPlace.mentions)
    q = _scoped(
        session.query(
            ArticleMentionedPlace.name,
            ArticleMentionedPlace.country,
            ArticleMentionedPlace.kind,
            func.max(ArticleMentionedPlace.lat),
            func.max(ArticleMentionedPlace.lon),
            arts_expr.label("arts"),
            men_expr.label("m"),
        )
    ).group_by(
        ArticleMentionedPlace.name,
        ArticleMentionedPlace.country,
        ArticleMentionedPlace.kind,
    )
    if min_articles > 1:
        q = q.having(arts_expr >= min_articles)
    rows = q.order_by(arts_expr.desc(), men_expr.desc()).limit(limit).all()

    coverage = (
        _scoped(session.query(func.count(func.distinct(ArticleMentionedPlace.article_id)))).scalar()
        or 0
    )

    placed = 0
    places = []
    for name, pcc, pkind, lat, lon, arts, m in rows:
        mappable = lat is not None and lon is not None
        if mappable:
            placed += 1
        places.append(
            {
                "name": name,
                "country": pcc,
                "kind": pkind,
                "lat": lat,
                "lon": lon,
                "articles": int(arts or 0),
                "mentions": int(m or 0),
            }
        )
    return {
        "count": len(places),
        "kind": k,
        "days": days,
        "country": cc,
        "min_articles": min_articles,
        "coverage_articles": int(coverage),
        "placed": placed,
        "method": (
            "Place names deduced from article text at ingest (extractor "
            "lexical-v1), aggregated by name + ISO-2 country. Coordinates come "
            "from the city/country gazetteer (null when unknown — no fabricated "
            "position). Figures are distinct-article spread and summed in-text "
            "mentions; there is no score."
        ),
        "caveat": "Deduced from text, never confirmed.",
        "places": places,
    }


# --------------------------------------------------------------------------- #
#  Layered keyword graph (maintainer-ruled 2026-06-10): keyword ↔ two-hop
#  relatives → families → super-groups. Every edge is real article
#  co-occurrence; every level states its method. Bounded by construction.
# --------------------------------------------------------------------------- #
def _article_set(session, normalized_terms: list[str], *, cap: int = 4000) -> set[int]:
    """Distinct article ids mentioning ANY of the given normalized terms."""
    if not normalized_terms:
        return set()
    rows = (
        session.query(KeywordMention.article_id)
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(Keyword.normalized_term.in_(normalized_terms))
        .distinct()
        .limit(cap)
        .all()
    )
    return {a for (a,) in rows}


def _overlap_edges(nodes: list[dict], sets: dict[str, set[int]], *, min_overlap: int = 2) -> list[dict]:
    edges = []
    ids = [n["id"] for n in nodes]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ov = len(sets.get(ids[i], set()) & sets.get(ids[j], set()))
            if ov >= min_overlap:
                edges.append({"a": ids[i], "b": ids[j], "weight": ov})
    edges.sort(key=lambda e: -e["weight"])
    return edges[: max(3 * len(nodes), 60)]  # keep the picture legible, not a hairball


def layered_graph(
    session,
    *,
    level: str = "keyword",
    term: str | None = None,
    hops: int = 2,
    limit_nodes: int = 36,
    days: int | None = None,
    start=None,
    end=None,
) -> dict:
    """One zoom level of the keyword graph: keyword (≤2 hops) / family / supergroup."""
    if level == "keyword":
        if not term:
            return {"level": level, "nodes": [], "edges": [], "error": "term required"}
        base = associations(session, term, limit=12, group=True, days=days, start=start, end=end)
        center = (base.get("resolved") or {}).get("term", term)
        nodes = [{"id": center, "label": center, "kind": "keyword", "center": True, "size": 13}]
        edges, seen = [], {center}
        for p in base.get("pairs", []):
            if p["term"] in seen:
                continue
            seen.add(p["term"])
            nodes.append(
                {
                    "id": p["term"],
                    "label": p["term"],
                    "kind": "keyword",
                    "size": p.get("cooccur", 1),
                    "members": p.get("members", []),
                    "pmi": p.get("pmi"),
                }
            )
            edges.append({"a": center, "b": p["term"], "weight": p.get("cooccur", 1), "pmi": p.get("pmi")})
        if hops >= 2:
            for p in base.get("pairs", [])[:5]:  # relatives of the strongest relatives
                second = associations(
                    session, p["term"], limit=4, group=True, days=days, start=start, end=end
                )
                for p2 in second.get("pairs", []):
                    if len(nodes) >= limit_nodes:
                        break
                    if p2["term"] not in seen:
                        seen.add(p2["term"])
                        nodes.append(
                            {
                                "id": p2["term"],
                                "label": p2["term"],
                                "kind": "keyword",
                                "hop": 2,
                                "size": p2.get("cooccur", 1),
                                "pmi": p2.get("pmi"),
                            }
                        )
                    edges.append(
                        {"a": p["term"], "b": p2["term"], "weight": p2.get("cooccur", 1), "pmi": p2.get("pmi")}
                    )
        return {
            "level": level,
            "term": center,
            "nodes": nodes,
            "edges": edges,
            "method": "PMI/co-occurrence association, two hops (relatives, and their relatives)",
            "caveat": "Association is not causation; PMI on small samples is noisy.",
        }

    if level == "family":
        top = top_terms(session, limit=limit_nodes, group=True, days=days)
        fams = top.get("terms", [])[:limit_nodes]
        nodes, sets = [], {}
        for f in fams:
            members = [m.get("normalized") for m in f.get("members", []) if m.get("normalized")] or [
                f.get("normalized")
            ]
            fid = f.get("normalized") or f.get("term")
            nodes.append(
                {
                    "id": fid,
                    "label": f.get("term"),
                    "kind": "family",
                    "size": f.get("mentions", 1),
                    "members": [m.get("term") for m in f.get("members", [])][:8],
                }
            )
            sets[fid] = _article_set(session, members[:3])
        return {
            "level": level,
            "nodes": nodes,
            "edges": _overlap_edges(nodes, sets),
            "method": "shared-article overlap between keyword FAMILIES (top members each)",
            "caveat": "Families group surface forms of one entity; overlap counts articles, not causation.",
        }

    if level == "supergroup":
        from src.database.models import KeywordSuperGroup

        sgs = session.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
        nodes, sets = [], {}
        for sg in sgs:
            members = [m.normalized_term for m in sg.members][:6]
            sid = f"sg:{sg.id}"
            nodes.append(
                {
                    "id": sid,
                    "label": sg.name,
                    "kind": "supergroup",
                    "size": max(len(members), 1) * 5,
                    "members": members,
                }
            )
            sets[sid] = _article_set(session, members)
        # Context: the top unassigned families, so super-groups sit in the landscape.
        assigned = {m for n in nodes for m in n["members"]}
        for f in top_terms(session, limit=10, group=True).get("terms", []):
            fid = f.get("normalized") or f.get("term")
            if fid in assigned or any(n["id"] == fid for n in nodes):
                continue
            nodes.append(
                {"id": fid, "label": f.get("term"), "kind": "family", "size": f.get("mentions", 1)}
            )
            sets[fid] = _article_set(session, [fid])
        return {
            "level": level,
            "nodes": nodes,
            "edges": _overlap_edges(nodes, sets, min_overlap=1),
            "method": "shared-article overlap between SUPER-GROUPS (curated groups of families); top unassigned families shown for context",
            "caveat": "Super-groups are the user's own curation; overlap counts articles, not causation.",
        }

    return {"level": level, "nodes": [], "edges": [], "error": f"unknown level {level!r}"}
