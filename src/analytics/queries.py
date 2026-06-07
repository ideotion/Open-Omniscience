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

from src.database.models import Article, Keyword, KeywordMention


def kind_of(kw: Keyword) -> str:
    if not kw.is_entity:
        return "term"
    return kw.entity_type or "entity"


def _normalize(term: str) -> str:
    return " ".join(term.split()).casefold()


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
        .group_by(Keyword.id).order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(1).all()
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
    q = (
        session.query(KeywordMention.observed_on, func.sum(KeywordMention.count))
        .filter(KeywordMention.keyword_id == kw.id, KeywordMention.observed_on.isnot(None))
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
        .filter(KeywordMention.keyword_id == kw.id).scalar() or 0
    )
    return {
        "term": term, "bucket": bucket,
        "resolved": {"term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw)},
        "points": points, "total": sum(p["count"] for p in points), "articles": int(articles),
    }


def top_terms(session, *, days: int | None = None, country: str | None = None,
              kind: str | None = None, limit: int = 20) -> dict:
    """Most-mentioned keywords (optionally within a window / country / kind)."""
    q = (
        session.query(
            Keyword, func.sum(KeywordMention.count).label("m"),
            func.count(func.distinct(KeywordMention.article_id)).label("arts"),
        )
        .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
    )
    if days:
        q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
    if country:
        q = q.filter(KeywordMention.country == country.lower())
    q = _apply_kind(q, kind)
    rows = q.group_by(Keyword.id).order_by(func.sum(KeywordMention.count).desc()).limit(limit * 4).all()
    is_hidden = _hidden_predicate()
    terms = []
    for k, m, a in rows:
        if is_hidden(k.normalized_term):
            continue
        terms.append({"term": k.term, "normalized": k.normalized_term, "kind": kind_of(k),
                      "mentions": int(m), "articles": int(a)})
        if len(terms) >= limit:
            break
    return {"count": len(terms), "days": days, "country": country, "kind": kind, "terms": terms}


def trending(session, *, window_days: int = 7, baseline_days: int = 30,
             country: str | None = None, kind: str | None = None,
             limit: int = 20, min_recent: int = 3) -> dict:
    """Rising keywords: recent volume vs the prior-period rate (a defined ratio).

    ``growth`` = recent_count / expected, where expected = (prior_count /
    baseline_days) * window_days. New terms (no prior) report growth as the recent
    count. This is a transparent ratio, not a significance test.
    """
    today = date.today()
    w_start = today - timedelta(days=window_days)
    b_start = w_start - timedelta(days=baseline_days)

    def _counts(lo, hi):
        q = (
            session.query(KeywordMention.keyword_id, func.sum(KeywordMention.count))
            .filter(KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi)
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
        out.append({
            "term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw),
            "recent": rc, "prior": pc, "expected": expected, "growth": growth,
        })
        if len(out) >= limit:
            break
    return {
        "count": len(out), "window_days": window_days, "baseline_days": baseline_days,
        "country": country, "kind": kind, "terms": out,
        "method": "recent volume vs prior-period rate (ratio, not a significance test)",
    }


def associations(session, term: str, *, limit: int = 20, min_cooccur: int = 2) -> dict:
    """Keywords that co-occur with ``term`` in the same articles, ranked by PMI."""
    kw = resolve_keyword(session, term)
    if kw is None:
        return {"term": term, "resolved": None, "pairs": []}
    total = session.query(func.count(func.distinct(KeywordMention.article_id))).scalar() or 0
    target_articles = [
        a for (a,) in session.query(KeywordMention.article_id)
        .filter(KeywordMention.keyword_id == kw.id).distinct()
    ]
    n_a = len(target_articles)
    if not target_articles or total == 0:
        return {"term": term, "resolved": {"term": kw.term, "kind": kind_of(kw)},
                "corpus_articles": int(total), "n_articles_with_term": n_a, "pairs": []}

    co_rows = (
        session.query(KeywordMention.keyword_id, func.count(func.distinct(KeywordMention.article_id)))
        .filter(KeywordMention.article_id.in_(target_articles), KeywordMention.keyword_id != kw.id)
        .group_by(KeywordMention.keyword_id)
        .having(func.count(func.distinct(KeywordMention.article_id)) >= min_cooccur).all()
    )
    is_hidden = _hidden_predicate()
    pairs = []
    for kid, co in co_rows:
        co = int(co)
        n_b = (
            session.query(func.count(func.distinct(KeywordMention.article_id)))
            .filter(KeywordMention.keyword_id == kid).scalar() or 1
        )
        pmi = math.log2((co * total) / (n_a * n_b)) if co > 0 else 0.0
        k2 = session.get(Keyword, kid)
        if k2 is None or is_hidden(k2.normalized_term):
            continue
        pairs.append({
            "term": k2.term, "normalized": k2.normalized_term, "kind": kind_of(k2),
            "cooccur": co, "n_b": int(n_b), "pmi": round(pmi, 3),
        })
    pairs.sort(key=lambda p: (-p["pmi"], -p["cooccur"]))
    return {
        "term": term, "resolved": {"term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw)},
        "corpus_articles": int(total), "n_articles_with_term": n_a,
        "pairs": pairs[:limit],
        "method": "pointwise mutual information over article co-occurrence",
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
        .limit(limit).all()
    )
    items = []
    for m, a in rows:
        content = a.get_content() or ""
        off = m.first_offset or 0
        start, end = max(0, off - window), min(len(content), off + window)
        snippet = content[start:end].strip()
        items.append({
            "article_id": a.id, "title": a.title, "url": a.url,
            "source": a.source.name if a.source else None,
            "observed_on": m.observed_on.isoformat() if m.observed_on else None,
            "country": m.country, "city": m.city,
            "snippet": ("…" if start > 0 else "") + snippet + ("…" if end < len(content) else ""),
        })
    return {"term": term, "resolved": {"term": kw.term, "kind": kind_of(kw)},
            "count": len(items), "mentions": items}


def map_data(session, *, days: int | None = 30, kind: str | None = None,
             top_per_area: int = 5, min_mentions: int = 1) -> dict:
    """Top keywords per country and per city (from denormalised mention facets)."""
    is_hidden = _hidden_predicate()

    def _agg(area_col):
        q = (
            session.query(area_col, Keyword, func.sum(KeywordMention.count).label("m"))
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(area_col.isnot(None))
        )
        if days:
            q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
        q = _apply_kind(q, kind)
        rows = q.group_by(area_col, Keyword.id).order_by(func.sum(KeywordMention.count).desc()).all()
        areas: dict[str, list] = {}
        for area, kw, m in rows:
            if is_hidden(kw.normalized_term):
                continue
            lst = areas.setdefault(area, [])
            if len(lst) < top_per_area and int(m) >= min_mentions:
                lst.append({"term": kw.term, "kind": kind_of(kw), "mentions": int(m)})
        return areas

    def _agg_cities():
        q = (
            session.query(KeywordMention.city, KeywordMention.country, Keyword,
                          func.sum(KeywordMention.count).label("m"))
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(KeywordMention.city.isnot(None))
        )
        if days:
            q = q.filter(KeywordMention.observed_on >= date.today() - timedelta(days=days))
        q = _apply_kind(q, kind)
        rows = q.group_by(KeywordMention.city, KeywordMention.country, Keyword.id).order_by(
            func.sum(KeywordMention.count).desc()).all()
        out: dict[tuple, dict] = {}
        for city, country, kw, m in rows:
            if is_hidden(kw.normalized_term):
                continue
            slot = out.setdefault((city, country), {"name": city, "country": country, "top": []})
            if len(slot["top"]) < top_per_area and int(m) >= min_mentions:
                slot["top"].append({"term": kw.term, "kind": kind_of(kw), "mentions": int(m)})
        return list(out.values())

    countries = _agg(KeywordMention.country)
    return {
        "days": days, "kind": kind,
        "countries": [{"code": c, "top": t} for c, t in sorted(countries.items())],
        "cities": sorted(_agg_cities(), key=lambda c: (c["name"] or "")),
    }


def status(session) -> dict:
    """Indexing status for the Insights tab."""
    total_articles = session.query(func.count(Article.id)).scalar() or 0
    indexed = session.query(func.count(func.distinct(KeywordMention.article_id))).scalar() or 0
    keywords = session.query(func.count(Keyword.id)).scalar() or 0
    entities = session.query(func.count(Keyword.id)).filter(Keyword.is_entity.is_(True)).scalar() or 0
    mentions = session.query(func.count(KeywordMention.id)).scalar() or 0
    return {
        "total_articles": int(total_articles), "indexed_articles": int(indexed),
        "remaining": int(total_articles) - int(indexed),
        "keywords": int(keywords), "entities": int(entities), "mentions": int(mentions),
    }
