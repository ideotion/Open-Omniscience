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

from src.database.models import Article, Keyword, KeywordFamilyOverride, KeywordMention


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
