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
import os
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Keyword,
    KeywordFamilyOverride,
    KeywordMention,
    Source,
)


# Chunk size for id IN(...) queries -- stay under SQLite's historical ~999
# bound-variable ceiling, the same repo-wide invariant as latest.py:_SQL_IN_CHUNK
# and the per-module *_IN_CHUNK helpers (corroboration.py/story_propagation.py/
# convergence.py/disputed_chronology.py/source_quality.py) and this module's own
# GRAPH_ARTICLE_CAP. Used where a derived id list (e.g. distinct co-occurring
# keyword ids) has no independent bound of its own (audit finding 2026-07-17).
_IN_CHUNK = 900


def _chunked(ids: list[int], size: int = _IN_CHUNK):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


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


def _ring_lang_of(session, stored: dict[str, str | None]):
    """Build ``lang_of(normalized) -> effective language`` for cross-language rings.

    Effective language = the stored ``Keyword.language`` when known, else the
    dominant article-language of that keyword's mentions (a signature-supported
    join — so an en-dominant "main" stays out of the fr ``hand`` ring). Only ring
    members are resolved, and the signature query runs only for the unknown-
    language ones, so the overhead is bounded to a handful of terms.
    """
    from src.analytics import equivalence

    cand = {n for n in stored if equivalence.is_ring_term(n)}
    eff: dict[str, str | None] = {n: stored.get(n) for n in cand}
    need_sig = [n for n in cand if not eff.get(n)]
    if need_sig:
        rows = (
            session.query(
                Keyword.normalized_term,
                Article.language,
                func.count(func.distinct(KeywordMention.article_id)),
            )
            .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
            .join(Article, Article.id == KeywordMention.article_id)
            .filter(Keyword.normalized_term.in_(need_sig))
            .group_by(Keyword.normalized_term, Article.language)
            .all()
        )
        sig: dict[str, dict[str, int]] = {}
        for norm, lang, c in rows:
            sig.setdefault(norm, {})[lang or "?"] = int(c)
        for n in need_sig:
            s = sig.get(n)
            eff[n] = max(s, key=lambda k: s[k]) if s else None
    return lambda norm: eff.get(norm)


_RING_CAVEAT = (
    "Cross-language equivalents merged into one concept; per-language counts shown "
    "(language_breakdown); the user can split any ring."
)

# Languages without word-segmentation: keyword extraction is whitespace-based and does
# NOT segment these, so keyword analytics over articles in them are incomplete. The
# diagnostics engine_report flags the same set; this surfaces it to the user, by ruling
# (audit-07 B1 disclosure sweep: the app ships zh/ja locales, so the honesty gap must be
# stated where the user actually reads keywords, not only in a diagnostics export).
_UNSEGMENTED_LANGS = frozenset({"zh", "ja"})


def unsegmented_note(session, article_ids: list[int]) -> dict | None:
    """An honest disclosure when the matched set contains unsegmented-language articles.

    Returns ``{languages, n_articles, note}`` when any article in the set is in a
    language the keyword extractor cannot segment (zh/ja), else ``None``. One cheap
    indexed COUNT grouped by language — no extraction, no score. Surfaced so a user
    looking at sparse/empty keyword analytics for a Chinese/Japanese corpus learns WHY
    instead of mistaking it for "no keywords".
    """
    if not article_ids:
        return None
    rows = (
        session.query(Article.language, func.count(Article.id))
        .filter(Article.id.in_(article_ids))
        .filter(func.lower(Article.language).in_(sorted(_UNSEGMENTED_LANGS)))
        .group_by(Article.language)
        .all()
    )
    if not rows:
        return None
    langs = sorted({(lang or "").lower() for lang, _ in rows})
    n = int(sum(c for _, c in rows))
    return {
        "languages": langs,
        "n_articles": n,
        "note": (
            f"Keyword extraction does not segment {', '.join(langs)} (no word "
            f"boundaries), so keyword analytics for {n} article(s) in those languages "
            "are incomplete — this is a known limit, not an empty result."
        ),
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
    if kind in ("entity", "non_term"):
        # "non_term" (the Families "all" view, 2026-07-18 field fix) is the explicit
        # every-non-term-kind aggregation: it filters BEFORE the limit, so it never
        # falls back to a filter-after-limit trim that a term-dominated corpus would
        # starve down to a handful of stray entities. Currently identical to "entity"
        # (entity_type is only ever None/"entity" until a real NER/gazetteer pass
        # populates person/org/location -- out of scope here) -- this is an honest
        # consequence of today's taxonomy, not a bug to paper over.
        return query.filter(Keyword.is_entity.is_(True))
    return query.filter(Keyword.entity_type == kind)


def _annotate_translations(terms, target_lang, stored_lang=None):
    """Make the keyword rows LANGUAGE-AWARE: tag each row whose concept has a VERIFIED
    translation into ``target_lang`` (via its Wikidata-sourced ring) with
    ``translation`` + ``translation_source='ring'`` — so the UI can show the original
    AND its translation, never blinding the reader to a foreign-language keyword.

    Grouped ring rows resolve directly by ``ring_id``; solo rows resolve by
    (effective language, normalized). A same-language or self-identical result is
    skipped (nothing to add). No-op when ``target_lang`` is empty."""
    tl = (target_lang or "").strip().casefold()
    if not tl:
        return terms
    from src.analytics import equivalence

    stored_lang = stored_lang or {}
    for r in terms:
        rid = r.get("ring_id")
        if rid:
            tr = equivalence.ring_translation(rid, tl)
        else:
            norm = r.get("normalized") or ""
            lang = r.get("language") or stored_lang.get(norm)
            tr = equivalence.translate_term(lang, norm, tl)
        if not tr:
            continue
        trf = tr.casefold()
        if trf == (r.get("normalized") or "").casefold() or trf == (r.get("term") or "").casefold():
            continue
        r["translation"] = tr
        r["translation_source"] = "ring"
    return terms


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
    target_lang: str | None = None,
) -> dict:
    """Most-mentioned keywords (optionally within a window / country / kind).

    ``target_lang`` makes the rows language-aware: each row whose concept has a
    verified ring translation into that language gains ``translation`` (see
    :func:`_annotate_translations`), so the reader sees foreign keywords WITH a
    translation rather than being shown only their own language.

    With ``group=True`` the surface variants of one entity are merged into a single
    family (``Trump`` / ``Trump's`` / ``Donald Trump`` -> one row) for display, with
    summed mentions and the member forms listed — see src/analytics/families.py.
    """
    _rollup_rows: list[dict] | None = None
    if not days and not country:
        # CORPUS-WIDE top-N (the hot Home grouped view): read the denormalised
        # per-keyword counters maintained at index time instead of joining +
        # GROUP BY-ing the whole keyword_mentions table. mention_count == SUM(count)
        # and article_count == COUNT(DISTINCT article_id) BY CONSTRUCTION (see
        # src/analytics/store.py + tests/test_keyword_counters.py), so the rows are
        # byte-identical — but this is an index-only scan (idx_keyword_mention_count),
        # never the mention join that dragged article pages through the SQLCipher
        # codec. ``mention_count > 0`` reproduces the inner-join's "has mentions"
        # filter (a counter is 0 iff the keyword has no mentions).
        q = session.query(
            Keyword,
            Keyword.mention_count.label("m"),
            Keyword.article_count.label("arts"),
        ).filter(Keyword.mention_count > 0)
        q = _apply_kind(q, kind)
        rows = q.order_by(Keyword.mention_count.desc()).limit(limit * 4).all()
    else:
        # Windowed / per-country: the corpus-wide counters cannot serve a scoped
        # SUM, so this path aggregates the mention table (filtered, then grouped) — UNLESS
        # the opt-in in-memory rollup can serve the TIME window (it can't do per-country),
        # in which case we sum the tiny rollup instead of scanning mentions. The rollup
        # returns rows in the SAME shape/order this query would, so the honesty layers
        # below (hidden-word filter, families, rings, translations) are byte-identical.
        rows = []
        if days and not country:
            from src.analytics import rollup_serve

            _rollup_rows = rollup_serve.windowed_rows(session, days=days, kind=kind, limit=limit * 4)
        if _rollup_rows is None:  # not opted in / not built / per-country -> live query
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
    stored_lang: dict[str, str | None] = {}
    if _rollup_rows is not None:
        # Rollup rows are already {term, normalized, kind, language, mentions, articles};
        # apply the SAME hidden-word filter + cap the live path applies.
        for r in _rollup_rows:
            if is_hidden(r["normalized"]):
                continue
            stored_lang[r["normalized"]] = r["language"]
            terms.append(dict(r))
            if len(terms) >= cap:
                break
    else:
        for k, m, a in rows:
            if is_hidden(k.normalized_term):
                continue
            stored_lang[k.normalized_term] = k.language
            terms.append(
                {
                    "term": k.term,
                    "normalized": k.normalized_term,
                    "kind": kind_of(k),
                    "language": k.language,
                    "mentions": int(m),
                    "articles": int(a),
                }
            )
            if len(terms) >= cap:
                break
    ringed = False
    if group:
        from src.analytics import equivalence
        from src.analytics.families import build_families

        overrides = load_overrides(session)
        terms = [f.to_dict() for f in build_families(terms, overrides)]
        # Layer cross-language rings ON TOP of the (within-language) families.
        merged = equivalence.merge_equivalents(
            terms, lang_of=_ring_lang_of(session, stored_lang), overrides=overrides
        )
        ringed = any(t.get("ring_id") for t in merged)
        terms = merged
    terms = terms[:limit]
    _annotate_translations(terms, target_lang, stored_lang)
    out: dict[str, Any] = {
        "count": len(terms),
        "days": days,
        "country": country,
        "kind": kind,
        "grouped": group,
        "terms": terms,
    }
    if _rollup_rows is not None and days:  # disclose the served source + as-of (honesty by construction)
        from src.analytics import rollup_serve

        out["basis"] = rollup_serve.basis(days)
    if ringed:
        out["rings_merged"] = True
        out["caveat"] = _RING_CAVEAT
    return out


def corpus_keywords(
    session,
    *,
    article_ids: list[int],
    kind: str | None = None,
    limit: int = 30,
    target_lang: str | None = None,
) -> dict:
    """Top keywords across a GIVEN set of articles (the analysis-window corpus).

    Like ``top_terms`` but scoped to an explicit article set rather than a
    time/country window — so the analysis window can show "the keywords of THESE
    matched articles". Ordered by article SPREAD (how many of the set mention the
    term), then mentions. Hidden/function words are dropped (the shared policy).
    No score — counts only; the caller states the honest method + caveat + n.

    ``target_lang`` makes the rows language-aware (verified ring ``translation`` per
    row) so the analysis window does not show foreign keywords without a translation.
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
                "language": k.language,
                "mentions": int(m),
                "articles": int(a),
            }
        )
        if len(terms) >= limit:
            break
    _annotate_translations(terms, target_lang)
    out = {"count": len(terms), "n_articles": len(article_ids), "terms": terms}
    note = unsegmented_note(session, article_ids)
    if note:
        out["unsegmented"] = note  # honest "why so few keywords" disclosure (B1)
    return out


def article_graph(session, *, article_ids: list[int], limit_nodes: int = 24) -> dict:
    """A radial keyword mind-map over a GIVEN article set (the reader / analysis
    "corpus of 1+").

    Centre = the most-mentioned keyword; arms = the next keywords sized by mention
    count; every edge goes centre -> arm (deterministic, always OUTWARD — the
    mind-map rule, no cross-tangle). For a single article this is a concept map of
    its keywords; for several it is the set's dominant terms around the lead term.
    Reuses :func:`corpus_keywords` (same hidden-word policy + spread ordering),
    counts only — NO score.
    """
    kw = corpus_keywords(session, article_ids=article_ids, limit=max(1, limit_nodes))
    terms = kw.get("terms", [])
    n_articles = kw.get("n_articles", 0)
    method = (
        "Keywords of the selected article(s), sized by mention count, radiating "
        "from the most-mentioned term (deterministic, always outward)."
    )
    if not terms:
        empty = {
            "level": "article", "nodes": [], "edges": [], "n_articles": n_articles,
            "method": method,
            "caveat": "Too few keywords indexed for this selection to draw a map yet.",
        }
        # If the emptiness is because the set is in an unsegmented language, say so
        # (the honest "why", not a bare empty map).
        if kw.get("unsegmented"):
            empty["unsegmented"] = kw["unsegmented"]
            empty["caveat"] = kw["unsegmented"]["note"]
        return empty
    center = terms[0]
    nodes = [{
        "id": center["term"], "label": center["term"], "kind": "keyword",
        "center": True, "size": 13,
        "mentions": center["mentions"], "articles": center["articles"],
    }]
    edges, seen = [], {center["term"]}
    for tdat in terms[1:]:
        if tdat["term"] in seen:
            continue
        seen.add(tdat["term"])
        nodes.append({
            "id": tdat["term"], "label": tdat["term"], "kind": "keyword",
            "size": tdat["mentions"],
            "mentions": tdat["mentions"], "articles": tdat["articles"],
        })
        edges.append({"a": center["term"], "b": tdat["term"], "weight": tdat["mentions"]})
    graph = {
        "level": "article", "term": center["term"],
        "nodes": nodes, "edges": edges, "n_articles": n_articles,
        "method": method,
        "caveat": "A concept map of the keywords present, not a co-occurrence network; not causation.",
    }
    if kw.get("unsegmented"):  # a mixed-language set: keep the map but disclose the gap
        graph["unsegmented"] = kw["unsegmented"]
    return graph


def ring_country_split(session, *, ring_id: str, days: int | None = None, limit: int = 40) -> dict:
    """Split a cross-language equivalence RING's coverage by the SOURCE country.

    The trans-language layer already merges (fr:élection + en:election + de:wahl) into
    ONE concept; this asks the multi-perspective question the de-US-centring ethic cares
    about: WHO covers that concept, by the producing source's country? It aggregates the
    ring's keyword mentions across ALL its languages and groups them by Source.country —
    so a user sees, e.g., "the 'inflation' concept: 120 mentions / 30 articles from US
    sources, 45 / 12 from FR, 8 / 3 from BR…".

    Honest by construction: counts ONLY (mentions + distinct-article spread), NO score,
    NO ranking verdict — presence is coverage, not credibility. Membership reuses the
    established language-qualified resolver (``equivalence.ring_of``), so a keyword joins
    only when its stored language matches a ring member (never a fabricated merge); a
    keyword with no stored language is left out (stated in the method). Sources with no
    country are bucketed honestly as ``null`` (unlocated), never dropped or guessed.
    """
    from src.analytics import equivalence

    ring = equivalence.ring_meta(ring_id)
    if ring is None:
        return {"ring_id": ring_id, "found": False, "countries": [],
                "caveat": "No such equivalence ring."}
    member_terms = {term for _lang, term in ring.members}
    # Pre-filter in SQL to this ring's member terms, then confirm the language-qualified
    # ring membership in Python (so a term shared across rings/languages is attributed
    # correctly, never fabricated).
    cand = (
        session.query(Keyword.id, Keyword.language, Keyword.normalized_term)
        .filter(Keyword.normalized_term.in_(member_terms))
        .all()
    )
    kw_ids = [kid for kid, lang, norm in cand if equivalence.ring_of(lang, norm) == ring_id]
    languages = sorted({lang for _kid, lang, norm in cand
                        if equivalence.ring_of(lang, norm) == ring_id and lang})
    if not kw_ids:
        return {"ring_id": ring_id, "found": True, "countries": [], "n_keywords": 0,
                "languages": languages,
                "caveat": "No indexed keywords in this ring yet for your corpus."}
    q = (
        session.query(
            Source.country,
            func.sum(KeywordMention.count).label("m"),
            func.count(func.distinct(KeywordMention.article_id)).label("arts"),
        )
        .join(Article, Article.id == KeywordMention.article_id)
        .join(Source, Source.id == Article.source_id)
        .filter(KeywordMention.keyword_id.in_(kw_ids))
    )
    if days and days > 0:
        cutoff = date.today() - timedelta(days=days)
        q = q.filter(Article.published_at >= cutoff)
    rows = q.group_by(Source.country).order_by(func.count(func.distinct(KeywordMention.article_id)).desc()).all()
    countries = [
        {"country": (c or None), "mentions": int(m or 0), "articles": int(a or 0)}
        for c, m, a in rows[:limit]
    ]
    return {
        "ring_id": ring_id,
        "found": True,
        "label": ring.label,
        "n_keywords": len(kw_ids),
        "languages": languages,
        "countries": countries,
        "method": (
            "Mentions of every language member of the ring, grouped by the source's "
            "country. Keywords with no stored language are excluded (conservative). "
            "Counts only."
        ),
        "caveat": (
            "Coverage by producing-source country, never a credibility ranking or score. "
            "Unlocated sources are bucketed as null, not dropped. Co-occurrence in your "
            "corpus, never a claim about the country."
        ),
    }


def ring_country_article_ids(
    session, *, ring_id: str, country: str | None, days: int | None = None, limit: int = 2000,
) -> dict:
    """The exact article ids behind ONE (group, country) cell of ``ring_country_split``'s
    table — the concept-map §D drill (a country bar/row is clickable, never a dead
    end). ``country=None`` resolves the SAME "not mapped" bucket ring_country_split
    reports (a source with no stored country) — the largest bucket is often the
    unlocated one, and it must be investigable too, never a silent drop.

    Reuses the IDENTICAL language-qualified keyword resolution
    (``group_stats.resolve_group_keyword_ids``) that the summary table is built
    from, so a drilled set can never disagree with the number beside it. Bounded
    (never a silent truncation — ``bounded`` discloses when the real count exceeds
    ``limit``); a huge concept in one country still returns a usable exact corpus.
    """
    from src.analytics.equivalence import ring_meta
    from src.analytics.group_stats import resolve_group_keyword_ids

    ring = ring_meta(ring_id)
    if ring is None:
        return {"ring_id": ring_id, "found": False, "article_ids": [], "total": 0}

    kw_ids = resolve_group_keyword_ids(session, ring_id)
    if not kw_ids:
        return {
            "ring_id": ring_id, "found": True, "country": country,
            "article_ids": [], "total": 0, "bounded": False,
            "caveat": "No indexed keywords in this group yet for your corpus.",
        }

    # .distinct() the QUERY method (SELECT DISTINCT), never a bare func.distinct()
    # column wrap — the same pattern corpus_facet_article_ids uses for exact ids.
    q = (
        session.query(KeywordMention.article_id)
        .join(Article, Article.id == KeywordMention.article_id)
        .join(Source, Source.id == Article.source_id)
        .filter(KeywordMention.keyword_id.in_(list(kw_ids)))
        .distinct()
    )
    q = q.filter(Source.country.is_(None)) if country is None else q.filter(Source.country == country)
    if days and days > 0:
        cutoff = date.today() - timedelta(days=days)
        q = q.filter(Article.published_at >= cutoff)
    rows = q.order_by(KeywordMention.article_id).limit(limit + 1).all()
    ids = [int(r[0]) for r in rows]
    bounded = len(ids) > limit
    if bounded:
        ids = ids[:limit]
    return {
        "ring_id": ring_id, "found": True, "country": country,
        "article_ids": ids, "total": len(ids), "bounded": bounded,
        "method": (
            "The exact articles behind this (group, country) cell of the country "
            "breakdown — same keyword resolution and Source-country join as the "
            "summary table."
        ),
    }


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


def corpus_when(session, *, article_ids: list[int], limit: int = 40) -> dict:
    """WHEN the corpus is ABOUT — a TEMPORAL facet bucketed by YEAR over the
    mentioned-date tags across a GIVEN article set (the dates the text talks about,
    NOT the publication date). Counts only, deduced from text, never confirmed;
    user-rejected date tags are excluded. Cheap: grouped on the article_id-indexed
    ``article_mentioned_date`` table, never an article join."""
    if not article_ids:
        return {"count": 0, "years": []}
    yr = func.strftime("%Y", ArticleMentionedDate.mentioned_on)
    arts = func.count(func.distinct(ArticleMentionedDate.article_id))
    men = func.count(ArticleMentionedDate.id)
    rows = (
        session.query(yr.label("y"), arts.label("a"), men.label("m"))
        .filter(
            ArticleMentionedDate.article_id.in_(article_ids),
            ArticleMentionedDate.status != "rejected",
        )
        .group_by(yr)
        .order_by(arts.desc(), yr.desc())
        .limit(limit)
        .all()
    )
    years = [
        {"year": y, "articles": int(a or 0), "mentions": int(m or 0)}
        for y, a, m in rows
        if y
    ]
    return {"count": len(years), "years": years,
            "caveat": "Deduced from text, never confirmed."}


def corpus_facet_article_ids(
    session, *, article_ids: list[int], facet: str, value: str
) -> list[int]:
    """Article ids WITHIN the given corpus that carry a facet value — the DRILL that
    makes a facet co-equal with the text query (``entity`` name / ``place`` name /
    ``when`` year). The returned set is the corpus narrowed to that facet, in the
    corpus's own order (which may be FTS relevance). Cheap: an equality filter over an
    article_id-indexed mention table, never an article join. Returns ``[]`` for an empty
    corpus, a blank value, or an unknown facet."""
    if not article_ids or not value:
        return []
    if facet == "entity":
        rows = (
            session.query(ArticleEntity.article_id)
            .filter(ArticleEntity.article_id.in_(article_ids), ArticleEntity.name == value)
            .distinct()
            .all()
        )
    elif facet == "place":
        rows = (
            session.query(ArticleMentionedPlace.article_id)
            .filter(
                ArticleMentionedPlace.article_id.in_(article_ids),
                ArticleMentionedPlace.name == value,
            )
            .distinct()
            .all()
        )
    elif facet == "when":
        yr = func.strftime("%Y", ArticleMentionedDate.mentioned_on)
        rows = (
            session.query(ArticleMentionedDate.article_id)
            .filter(
                ArticleMentionedDate.article_id.in_(article_ids),
                ArticleMentionedDate.status != "rejected",
                yr == str(value),
            )
            .distinct()
            .all()
        )
    elif facet == "source":
        # Corpus-source/language filter build (L5, 2026-07-20 ruling): the id-seeded-
        # corpus INTERSECT path -- ids ∩ source -> the narrowed window, never a clear.
        # Matched by Source.ID, not name -- Source.name carries no uniqueness
        # constraint (only Source.domain does), so a name lookup can collide across
        # two same-named sources; the chip already carries source_id (it's how
        # corpus_source_language_facets built the chip in the first place), so the
        # drill uses it directly and never re-resolves a name back to an id.
        try:
            sid = int(value)
        except (TypeError, ValueError):
            return []
        rows = (
            session.query(Article.id)
            .filter(Article.id.in_(article_ids), Article.source_id == sid)
            .all()
        )
    elif facet == "language":
        rows = (
            session.query(Article.id)
            .filter(Article.id.in_(article_ids), Article.language == value)
            .all()
        )
    else:
        return []
    found = {r[0] for r in rows}
    return [aid for aid in article_ids if aid in found]


def corpus_source_language_facets(session, *, article_ids: list[int]) -> dict:
    """Sources + languages PRESENT in the given article-id corpus, with counts --
    powers the Articles-subtab facet controls (2026-07-20 ruling, item 3): a facet
    list of what the CURRENT corpus actually contains, not free text. Two column-
    projected group-bys over articles already in the corpus (never a full join);
    counts only, no ranking."""
    if not article_ids:
        return {"sources": [], "languages": []}
    src_rows = (
        session.query(Article.source_id, func.count(Article.id))
        .filter(Article.id.in_(article_ids))
        .group_by(Article.source_id)
        .all()
    )
    if not src_rows:
        return {"sources": [], "languages": []}
    src_ids = [sid for sid, _n in src_rows if sid is not None]
    names = dict(session.query(Source.id, Source.name).filter(Source.id.in_(src_ids))) if src_ids else {}
    domains = dict(session.query(Source.id, Source.domain).filter(Source.id.in_(src_ids))) if src_ids else {}
    sources = [
        {"source_id": sid, "name": names.get(sid, str(sid)), "domain": domains.get(sid), "n": int(n or 0)}
        for sid, n in sorted(src_rows, key=lambda kv: -kv[1])
        if sid is not None
    ]
    lang_rows = (
        session.query(Article.language, func.count(Article.id))
        .filter(Article.id.in_(article_ids), Article.language.isnot(None))
        .group_by(Article.language)
        .all()
    )
    languages = [
        {"language": lang, "n": int(n or 0)}
        for lang, n in sorted(lang_rows, key=lambda kv: -kv[1])
        if lang
    ]
    return {"sources": sources, "languages": languages}


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


def unlocated_language_breakdown(session) -> dict[str, int]:
    """``{language_code_or_"": count}`` — the per-LANGUAGE donut of the UNLOCATED articles
    (their source has no catalogued country). Column-projected (``Article.language`` + a
    COUNT over the indexed ``source_id`` join); never decrypts article content. Shared by
    the live :func:`source_country_counts` and the D4 map serve so both compute it identically
    (the rollup does not persist this breakdown). ``""`` = no/unknown language. No score."""
    rows = (
        session.query(Article.language, func.count(Article.id))
        .join(Source, Article.source_id == Source.id)
        .filter((Source.country.is_(None)) | (func.trim(Source.country) == ""))
        .group_by(Article.language)
        .all()
    )
    out: dict[str, int] = {}
    for lang, n in rows:
        key = (lang or "").strip().lower()
        out[key] = out.get(key, 0) + int(n or 0)
    return out


def source_country_counts(session) -> dict:
    """Per-country choropleth measures (ooMap), keyed by the source's catalogued
    country (ISO-2): the count of SOURCES, the ARTICLES collected from them, the
    KEYWORD MENTIONS in those articles, and the mean article TONE.

    Counts only, NO score. Sources without a country go into an ``unlocated``
    bucket and are NEVER guessed onto the map. The country is whatever the
    catalogue/operator asserted on the source -- this surfaces real catalogue
    skew (the de-US-centring lens), it does not correct it. Mean tone is VADER
    (English-lexicon only): ``sentiment`` is the average over the SCORED subset
    and ``sentiment_n`` is how many articles that was -- so a country with no
    English articles honestly reports ``sentiment=None`` (no data), never zero.
    """
    src_rows = (
        session.query(Source.country, func.count(Source.id))
        .group_by(Source.country)
        .all()
    )
    # Articles + mean tone per source-country in ONE scan. avg() ignores NULL
    # scores; count(sentiment_score) is the scored (English) subset size.
    art_rows = (
        session.query(
            Source.country,
            func.count(Article.id),
            func.avg(Article.sentiment_score),
            func.count(Article.sentiment_score),
        )
        .join(Article, Article.source_id == Source.id)
        .group_by(Source.country)
        .all()
    )
    # Keyword MENTIONS per source-country -- KeywordMention.country is the
    # denormalised SOURCE country, so this is an index scan (no Article join,
    # avoiding the keyword_mentions->articles row-decrypt cost).
    kw_rows = (
        session.query(KeywordMention.country, func.count())
        .group_by(KeywordMention.country)
        .all()
    )
    arts: dict[str, dict] = {}
    for cc, n, tone, tone_n in art_rows:
        arts[(cc or "").strip().lower()] = {
            "articles": int(n or 0),
            "sentiment": round(float(tone), 3) if tone is not None else None,
            "sentiment_n": int(tone_n or 0),
        }
    kws: dict[str, int] = {
        (cc or "").strip().lower(): int(n or 0) for cc, n in kw_rows
    }
    # Per-LANGUAGE breakdown of the UNLOCATED articles (source has no country) — the
    # donut for the Library world map (field remark 10: "all 'no country' articles shown
    # with a circular graph with per-language quantity"). Shared with the D4 map serve so
    # a served response is byte-identical here (the rollup does not persist this breakdown).
    unloc_by_language = unlocated_language_breakdown(session)

    by_country: list[dict] = []
    unlocated_sources = 0
    total_sources = 0
    for cc, n in src_rows:
        n = int(n or 0)
        total_sources += n
        code = (cc or "").strip().lower()
        if not code:
            unlocated_sources += n
            continue
        a = arts.get(code, {})
        by_country.append(
            {
                "country": code,
                "sources": n,
                "articles": a.get("articles", 0),
                "keywords": kws.get(code, 0),
                "sentiment": a.get("sentiment"),
                "sentiment_n": a.get("sentiment_n", 0),
            }
        )

    by_country.sort(key=lambda r: (-r["sources"], r["country"]))
    return {
        "by_country": by_country,
        "unlocated": {
            "sources": unlocated_sources,
            "articles": arts.get("", {}).get("articles", 0),
            "keywords": kws.get("", 0),
            # {language_code_or_"": count} — the donut (remark 10). "" = no/unknown language.
            "by_language": unloc_by_language,
        },
        "total_sources": total_sources,
        "total_articles": sum(v.get("articles", 0) for v in arts.values()),
    }


_SERVER_LOC_METHOD = (
    "Captured server IPs (the address we connected to at fetch) geolocated OFFLINE against "
    "a dated CC-licensed country DB; coordinates are a country stand-in point. Counts only, "
    "no score."
)
_SERVER_LOC_CAVEAT = (
    "Server location is OUR vantage point -- usually a CDN edge / anycast host, NOT proof of "
    "the publisher's origin; approximate; dated offline DB; unavailable over Tor. IP/host "
    "clustering (many distinct sources on one address) is a shape to investigate, never a verdict."
)


def server_locations(session) -> dict:
    """Aggregate CAPTURED server IPs (Slice 6a) geolocated OFFLINE (Slice 6b) for the
    ooMap "server location" layer (Slice 6c). Per-country counts + IP/host CLUSTERING +
    honest unavailable buckets.

    Reads only the small ``server_ip`` / ``server_ip_reason`` / ``source_id`` columns
    (no article body decrypt); geolocation is per DISTINCT IP (cached) -- bounded. Counts
    only, NO score. Clustering = IPs shared by 2+ DISTINCT sources (the network-layer
    cousin of source-laundering); surfaced as a shape to investigate, never a verdict.
    """
    from src.geo import ip_geo

    rows = (
        session.query(
            Article.server_ip,
            Article.server_ip_reason,
            Article.source_id,
            func.count(Article.id),
        )
        .group_by(Article.server_ip, Article.server_ip_reason, Article.source_id)
        .all()
    )
    names = {sid: nm for sid, nm in session.query(Source.id, Source.name)}

    by_country: dict[str, dict] = {}
    ip_sources: dict[str, set] = {}
    ip_articles: dict[str, int] = {}
    geo_cache: dict[str, dict] = {}
    unavailable = {"tor_or_proxy": 0, "not_captured": 0, "unknown_ip": 0}

    for ip, reason, sid, cnt in rows:
        cnt = int(cnt or 0)
        if not ip:
            r = (reason or "").lower()
            if "tor" in r or "proxy" in r:
                unavailable["tor_or_proxy"] += cnt
            else:
                unavailable["not_captured"] += cnt
            continue
        g = geo_cache.get(ip)
        if g is None:
            g = ip_geo.lookup(ip)
            geo_cache[ip] = g
        ip_sources.setdefault(ip, set()).add(sid)
        ip_articles[ip] = ip_articles.get(ip, 0) + cnt
        cc = g.get("country")
        if g.get("level") == "unavailable" or not cc:
            unavailable["unknown_ip"] += cnt
            continue
        b = by_country.setdefault(
            cc, {"articles": 0, "ips": set(), "sources": set(),
                 "lat": g.get("lat"), "lon": g.get("lon"), "level": g.get("level")}
        )
        b["articles"] += cnt
        b["ips"].add(ip)
        b["sources"].add(sid)

    # Sort the underlying (typed) data, then build the display dicts -- so the sort key
    # is a plain int, not a heterogeneous dict-value union.
    ordered_countries = sorted(by_country.items(), key=lambda kv: -int(kv[1]["articles"]))
    countries = [
        {
            "country": cc,
            "lat": b["lat"],
            "lon": b["lon"],
            "level": b["level"],
            "articles": b["articles"],
            "distinct_ips": len(b["ips"]),
            "distinct_sources": len(b["sources"]),
        }
        for cc, b in ordered_countries
    ]
    shared = sorted(
        ((ip, srcs) for ip, srcs in ip_sources.items() if len(srcs) >= 2),
        key=lambda t: -len(t[1]),  # shared by 2+ DISTINCT sources -> a shape to investigate
    )[:50]
    clusters = [
        {
            "ip": ip,
            "distinct_sources": len(srcs),
            "articles": ip_articles.get(ip, 0),
            "country": (geo_cache.get(ip) or {}).get("country"),
            "sources": [names.get(s) for s in list(srcs)[:20] if names.get(s)],
        }
        for ip, srcs in shared
    ]

    return {
        "countries": countries,
        "clusters": clusters,
        "unavailable": unavailable,
        "distinct_ips": len(ip_sources),
        "db_vintage": ip_geo.db_vintage(),
        "attribution": ip_geo.ATTRIBUTION,
        "method": _SERVER_LOC_METHOD,
        "caveat": _SERVER_LOC_CAVEAT,
    }


_COORD_METHOD = (
    "Near-duplicate clustering (MinHash + LSH, high-precision, Jaccard >= 0.7) within the "
    "matched set; independence is measured by DISTINCT SOURCES, never article count."
)
_COORD_CAVEAT = (
    "Structural near-duplication: articles sharing near-identical text count as ONE voice, "
    "not independent confirmation. This is NOT proof of collusion, and the absence of a "
    "flag is not the absence of coordination. Counts only, no score."
)


def corpus_coordination(
    session, *, article_ids: list[int], threshold: float = 0.7, min_members: int = 2
) -> dict:
    """Near-duplicate clusters WITHIN the matched set -- "N near-identical copies across M
    sources = effectively one voice" (the anti-false-triangulation surface, ruled ambient
    in the analysis window). Reuses the high-precision MinHash+LSH clusterer; independence
    is the count of DISTINCT SOURCES in a cluster (a single source repeating itself is one
    voice, flagged as such, not co-publication). Counts only, NO score; the honesty caveat
    travels with the data."""
    if not article_ids:
        return {"clusters": [], "n_articles": 0, "n_clusters": 0,
                "method": _COORD_METHOD, "caveat": _COORD_CAVEAT}
    rows = (
        session.query(Article, Source.name, Source.domain)
        .join(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(article_ids))
        .all()
    )
    docs: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for a, sname, sdom in rows:
        docs[str(a.id)] = ((a.title or "") + "\n" + (a.get_content() or "")).strip()
        meta[str(a.id)] = {
            "id": a.id, "title": a.title, "source": sname or sdom or "?",
            "domain": sdom, "url": a.url,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
    from src.signals.near_dup import near_duplicate_clusters

    res = near_duplicate_clusters(docs, threshold=threshold)
    clusters: list[dict] = []
    for c in res.clusters:
        members = [meta[m] for m in c.members if m in meta]
        if len(members) < min_members:
            continue
        srcs = sorted({m["source"] for m in members})
        clusters.append({
            "representative": int(c.representative),
            "size": len(members),
            "article_ids": [m["id"] for m in members],
            "members": members,
            "distinct_sources": len(srcs),
            "sources": srcs,
            "avg_similarity": round(c.avg_similarity, 3),
            "single_source": len(srcs) <= 1,
        })
    clusters.sort(key=lambda x: (-x["size"], -x["distinct_sources"]))
    return {
        "clusters": clusters, "n_articles": len(docs), "n_clusters": len(clusters),
        "method": _COORD_METHOD, "caveat": _COORD_CAVEAT,
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
    target_lang: str | None = None,
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

    # Opt-in rollup serve: sum the in-memory keyword_daily rollup for the two windows
    # instead of scanning keyword_mentions (the freeze). Time-window only — never per-country
    # (the rollup has no country dim). Ranges match _counts's half-open [lo, hi): the rollup
    # is INCLUSIVE [lo, hi-1day]. Mentions are exact, so the scored output is byte-identical.
    # Any miss (not opted in / not built / error) -> None -> the live _counts below.
    _served = False
    if not country:
        from src.analytics import rollup_serve

        _r = rollup_serve.windowed_counts(session, lo=w_start, hi=today)
        _p = rollup_serve.windowed_counts(session, lo=b_start, hi=w_start - timedelta(days=1))
        if _r is not None and _p is not None:
            recent, prior, _served = _r, _p, True
    if not _served:
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
    cap = limit * 4  # headroom so ring members below `limit` still merge
    cand = []
    stored_lang: dict[str, str | None] = {}
    for kid, rc, pc, expected, growth in scored:
        kw = session.get(Keyword, kid)
        if kw is None or (kind and kind_of(kw) != kind) or is_hidden(kw.normalized_term):
            continue
        stored_lang[kw.normalized_term] = kw.language
        cand.append(
            {
                "term": kw.term,
                "normalized": kw.normalized_term,
                "kind": kind_of(kw),
                "language": kw.language,
                "recent": rc,
                "prior": pc,
                "expected": expected,
                "growth": growth,
            }
        )
        if len(cand) >= cap:
            break

    # Layer cross-language rings: sum recent/prior across members, then recompute
    # expected & growth from the totals (the same defined ratio, not a re-fit).
    from src.analytics import equivalence

    lang_of = _ring_lang_of(session, stored_lang)
    out: list[dict] = []
    ringed = False
    for gk, payload in equivalence.group_rows(cand, lang_of=lang_of):
        if gk == "solo":
            out.append(payload)
            continue
        ring_id, members = payload
        meta = equivalence.ring_meta(ring_id)
        rc = sum(int(m["recent"]) for m in members)
        pc = sum(int(m["prior"]) for m in members)
        exp = (pc / baseline_days) * window_days
        lead = max(members, key=lambda m: m["recent"])
        row = {
            "term": meta.label if meta else ring_id,
            "normalized": f"ring:{ring_id}",
            "kind": lead["kind"],
            "recent": rc,
            "prior": pc,
            "expected": round(exp, 2),
            "growth": round(rc / exp if exp >= 1 else float(rc), 2),
            "ring_id": ring_id,
            "language_breakdown": {(lang_of(m["normalized"]) or "?"): int(m["recent"]) for m in members},
            "members": [
                {"term": m["term"], "normalized": m["normalized"],
                 "language": lang_of(m["normalized"]) or "?", "recent": int(m["recent"])}
                for m in members
            ],
        }
        if meta and meta.note:
            row["ring_note"] = meta.note
        out.append(row)
        ringed = True
    out.sort(key=lambda t: (-t["growth"], -t["recent"]))
    out = out[:limit]
    _annotate_translations(out, target_lang, stored_lang)
    res: dict[str, Any] = {
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
    if _served:  # disclose the served source + as-of (honesty by construction)
        from src.analytics import rollup_serve

        res["basis"] = rollup_serve.basis(window_days)
    if ringed:
        res["rings_merged"] = True
        res["caveat"] = _RING_CAVEAT
    return res


# Preset windows for the Insights "Trends" view (maintainer-ruled 2026-06-16):
# rising keywords across past 24h · past week · past month, side by side. Each
# carries its own prior-period baseline (a longer look-back for the longer window).
_TREND_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("24h", 1, 7),    # 1-day window vs the prior 7 days
    ("7d", 7, 30),    # 1-week window vs the prior 30 days
    ("30d", 30, 90),  # 1-month window vs the prior 90 days
)


def _window_daily_series(
    session, term: str, *, days: int, country: str | None = None
) -> list[dict]:
    """Daily mention-count series for ``term`` over the last ``days`` days.

    REUSES :func:`trend` (bucket="day") so the numbers match the existing trend
    chart exactly, then slices its full-history points to this window's date range
    ``[today - days, today]``. Counts only, no interpolation: only days that carry
    mentions appear (zero-count days are omitted, exactly as :func:`trend` does).
    """
    day_keys = trend(session, term, bucket="day", country=country)["points"]
    today = date.today()
    lo = (today - timedelta(days=days)).isoformat()
    hi = today.isoformat()
    # ISO date strings (YYYY-MM-DD) sort chronologically, so a string range is exact.
    return [p for p in day_keys if lo <= p["date"] <= hi]


def _merge_daily_series(serieses) -> list[dict]:
    """Sum several ``[{date, count}]`` series by date (for a cross-language ring)."""
    agg: dict[str, int] = {}
    for s in serieses:
        for p in s:
            agg[p["date"]] = agg.get(p["date"], 0) + int(p["count"])
    return [{"date": d, "count": c} for d, c in sorted(agg.items())]


def trending_windows(
    session,
    *,
    country: str | None = None,
    kind: str | None = None,
    limit: int = 10,
    series_top: int = 0,
    target_lang: str | None = None,
) -> dict:
    """Rising keywords across THREE preset windows side by side (24h · 7d · 30d).

    The substrate for the Insights "Trends" redesign (maintainer-ruled 2026-06-16):
    each window reuses :func:`trending` (the SAME transparent recent-vs-prior rate
    ratio, never a composite score). Short windows are sparse on a young corpus, so
    each term carries its raw ``recent`` count (n) and the caller states the
    early-corpus honesty. No score; the ratio is a disclosed method.

    ADDITIVE: with ``series_top > 0``, the first ``series_top`` terms of each window
    gain a ``series`` list of ``{"date", "count"}`` daily points spanning that
    window's range (24h→1 day, 7d→7 days, 30d→30 days), so the frontend can draw an
    ooChart per term. The series REUSES :func:`trend` (bucket="day") — the numbers
    match the existing trend chart, counts only. ``series_top == 0`` (the default)
    returns the unchanged response (no ``series`` keys).
    """
    windows = []
    served_basis = None  # the rollup disclosure (D3): stale/rebuilding/as_of, surfaced once
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
            target_lang=target_lang,
        )
        if served_basis is None and res.get("basis"):
            served_basis = res["basis"]
        terms = res["terms"]
        if series_top > 0:
            for t in terms[:series_top]:
                if t.get("ring_id"):
                    # A ring's series = the sum of its members' daily series (the
                    # merged "ring:<id>" normalized doesn't resolve to a keyword).
                    t["series"] = _merge_daily_series(
                        _window_daily_series(session, m["normalized"], days=wdays, country=country)
                        for m in t.get("members", [])
                    )
                else:
                    t["series"] = _window_daily_series(
                        session, t["normalized"], days=wdays, country=country
                    )
        windows.append(
            {
                "label": label,
                "window_days": wdays,
                "baseline_days": bdays,
                "terms": terms,
                "count": res["count"],
                "scanned": res["scanned"],
            }
        )
    out: dict[str, Any] = {
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
    if served_basis is not None:  # disclose that the windows were served from the (maybe stale) rollup
        out["basis"] = served_basis
    return out


def _group_pairs(
    pairs: list[dict],
    overrides: dict[str, dict] | None = None,
    lang_of=None,
) -> list[dict]:
    """Merge co-occurring surface variants into one family node (for the mind-map).

    Summed co-occurrence, the strongest member PMI, and the member forms listed —
    so ``Trump`` / ``Trump's`` / ``Donald Trump`` are one neighbour, not three.
    User overrides (manual merge/split) are honoured. When ``lang_of`` is given,
    cross-language rings are layered on top (``élection`` joins ``election``),
    with per-language counts kept visible.
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
    if lang_of is not None:
        out = _ring_merge_pairs(out, lang_of, overrides)
    out.sort(key=lambda p: (-p["pmi"], -p["cooccur"]))
    return out


def _ring_merge_pairs(rows: list[dict], lang_of, overrides) -> list[dict]:
    """Collapse association family-rows that belong to one cross-language ring."""
    from src.analytics import equivalence

    merged: list[dict] = []
    for gk, payload in equivalence.group_rows(rows, lang_of=lang_of, overrides=overrides):
        if gk == "solo":
            merged.append(payload)
            continue
        ring_id, members = payload
        meta = equivalence.ring_meta(ring_id)
        lead = max(members, key=lambda r: r["cooccur"])
        merged.append(
            {
                "term": meta.label if meta else ring_id,
                "normalized": f"ring:{ring_id}",
                "kind": lead["kind"],
                "cooccur": sum(r["cooccur"] for r in members),
                "n_b": max(r["n_b"] for r in members),
                "pmi": max(r["pmi"] for r in members),
                "variants": sum(r.get("variants", 1) for r in members),
                "members": [m for r in members for m in r["members"]],
                "ring_id": ring_id,
                "language_breakdown": {
                    (lang_of(r["normalized"]) or "?"): r["cooccur"] for r in members
                },
            }
        )
    return merged


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
    corpus_total: int | None = None,
    article_cap: int | None = None,
) -> dict:
    """Keywords that co-occur with ``term`` in the same articles, ranked by PMI.

    With ``group=True`` the neighbours are merged into entity families (one node
    per entity instead of one per surface form) — see src/analytics/families.py.
    ``days`` / ``start`` / ``end`` window the analysis (maintainer 2026-06-11:
    the date spectrum is tweakable); PMI is then computed WITHIN the window —
    the method string says so.

    ``corpus_total`` (the PMI denominator = distinct articles in the window) may be
    passed pre-computed so a caller running many associations() in a loop — the layered
    keyword graph — computes that scan ONCE instead of once per call; when ``None`` it is
    computed here (byte-identical). ``article_cap`` bounds a very frequent term's article
    set to a DETERMINISTIC, time-spanning sample so the co-occurrence aggregation stays
    bounded regardless of corpus size; when it truncates, ``articles_bounded`` is set and
    ``articles_sampled`` reports the sample size (never a silent cut). Both default to the
    un-bounded behaviour, so the /associations endpoint and every existing caller are
    unchanged.
    """
    if days and not start:
        start = date.today() - timedelta(days=days)
    kw = resolve_keyword(session, term)
    if kw is None:
        return {"term": term, "resolved": None, "pairs": []}
    total = (
        corpus_total
        if corpus_total is not None
        else (
            _window_filter(
                session.query(func.count(func.distinct(KeywordMention.article_id))), start, end
            ).scalar()
            or 0
        )
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
    articles_total = len(target_articles)
    articles_bounded = False
    # Audit finding 2026-07-17: with no explicit article_cap (the direct GET
    # /api/insights/associations endpoint -- "powers the mind-map" -- and the top_terms/
    # trending cooccur enrichment both call associations() this way), a term co-occurring
    # in more than SQLite's historical ~999 bound-variable ceiling worth of articles made
    # the .in_(target_articles) query below raise "OperationalError: too many SQL
    # variables" -- a real 500 on a popular term in any moderately large corpus. The
    # EFFECTIVE cap is always at least the SQLite-safe bound (GRAPH_ARTICLE_CAP=900,
    # the same repo-wide invariant as layered_graph/latest.py/_IN_CHUNK modules), even
    # when the caller passed none; an explicit article_cap above that is honestly
    # clamped down to it too (a crash-guaranteeing operator setting would be worse than a
    # disclosed, safe sample). This can only ever CHANGE behaviour that previously
    # crashed (any term whose article set already exceeded 900 was already broken).
    effective_cap = min(article_cap, GRAPH_ARTICLE_CAP) if article_cap is not None else GRAPH_ARTICLE_CAP
    if articles_total > effective_cap:
        # Bound a very frequent term to a DETERMINISTIC sample of EXACTLY ``effective_cap``
        # ids spread EVENLY across the full sorted range (index projection i*N//cap) —
        # no recency bias (cross-time recall is sacred), reproducible, and it caps both the
        # co-occurrence scan below and the IN() size. (A plain ``[::step]`` would waste half
        # the budget just past the boundary, e.g. 1201 ids -> 601.)
        ordered = sorted(target_articles)
        target_articles = [
            ordered[(i * articles_total) // effective_cap] for i in range(effective_cap)
        ]
        articles_bounded = True
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
    # De-N+1 (Slice-4 PR-3, via the Slice-2 counters): the old loop ran TWO queries per
    # co-occurring keyword — a COUNT(DISTINCT article_id) for n_b AND a session.get(Keyword)
    # — which dominated this endpoint on a large corpus (field report: 76 s). Both are now
    # batched:
    #   * the co-keyword Keyword rows in ONE query (not N gets);
    #   * n_b (distinct articles mentioning each co-keyword) corpus-wide == the maintained
    #     ``article_count`` counter (BYTE-IDENTICAL: it IS COUNT(DISTINCT article_id), kept
    #     exact by store.py + reconciled), so ZERO query; when a window is set the counters
    #     don't apply, so n_b comes from ONE grouped query over the co-keyword ids.
    # Audit finding 2026-07-17: `kids` is the set of DISTINCT co-occurring keyword
    # ids across `target_articles` (already bounded to GRAPH_ARTICLE_CAP articles),
    # but the number of DISTINCT KEYWORDS mentioned across those articles has no
    # independent bound of its own -- easily >900 in a large, multilingual,
    # many-source corpus even at min_cooccur's default of 2. Chunked below (the
    # same `.in_()` overflow class the neighbouring article_cap fix was written
    # for, on the query one step downstream of it).
    kids = [kid for kid, _ in co_rows]
    k2_by_id: dict[int, Any] = {}
    for chunk in _chunked(kids):
        k2_by_id.update({k.id: k for k in session.query(Keyword).filter(Keyword.id.in_(chunk))})
    nb_by_id: dict[int, int] = {}
    if kids and (start or end):
        for chunk in _chunked(kids):
            nb_by_id.update(
                {
                    int(kid): int(c)
                    for kid, c in _window_filter(
                        session.query(
                            KeywordMention.keyword_id,
                            func.count(func.distinct(KeywordMention.article_id)),
                        ),
                        start,
                        end,
                    )
                    .filter(KeywordMention.keyword_id.in_(chunk))
                    .group_by(KeywordMention.keyword_id)
                    .all()
                }
            )
    pairs = []
    stored_lang: dict[str, str | None] = {}
    for kid, co in co_rows:
        co = int(co)
        k2 = k2_by_id.get(kid)
        if k2 is None or is_hidden(k2.normalized_term):
            continue
        if start or end:
            n_b = nb_by_id.get(int(kid), 0) or 1
        else:
            # corpus-wide: the maintained counter == COUNT(DISTINCT article_id) for kid.
            n_b = int(k2.article_count or 0) or 1
        pmi = math.log2((co * total) / (n_a * n_b)) if co > 0 else 0.0
        stored_lang[k2.normalized_term] = k2.language
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
    ringed = False
    if group:
        pairs = _group_pairs(
            pairs, load_overrides(session), lang_of=_ring_lang_of(session, stored_lang)
        )
        ringed = any(p.get("ring_id") for p in pairs)
    caveat = "Association is not causation; PMI on small samples is noisy."
    if ringed:
        caveat += " " + _RING_CAVEAT
    result = {
        "term": term,
        "resolved": {"term": kw.term, "normalized": kw.normalized_term, "kind": kind_of(kw)},
        "corpus_articles": int(total),
        # The TRUE population (articles mentioning the term), even when the co-occurrence
        # below was computed over a bounded SAMPLE of them — the honest count, never the
        # sample size (which, when bounded, is reported separately as ``articles_sampled``).
        "n_articles_with_term": articles_total,
        "grouped": group,
        "pairs": pairs[:limit],
        "window": {"days": days, "start": str(start) if start else None, "end": str(end) if end else None},
        "method": "pointwise mutual information over article co-occurrence"
        + (" within the selected window" if (start or end) else ""),
        "caveat": caveat,
    }
    if article_cap is not None or articles_bounded:
        # Present when the caller asked for bounding (the graph) OR the internal
        # SQLite-safety net actually fired (audit finding 2026-07-17: this must never be
        # silent -- a truncated result with no disclosure is exactly the "no silent
        # truncation" honesty rule this codebase enforces elsewhere). Byte-unchanged for
        # every caller whose term's article set was already under the safety bound (the
        # overwhelming common case), which is what "byte-unchanged" ever meant in practice.
        result["articles_sampled"] = n_a
        result["articles_bounded"] = articles_bounded
        if articles_bounded:
            result["caveat"] = (
                f"{caveat} Computed over a {n_a}-of-{articles_total} time-spanning sample "
                "of this term's articles (bounded for responsiveness)."
            )
    return result


# The bucket for a source whose channel was never asserted (NULL/blank source_type).
# NOT coalesced to "news" (the ORM default) — a NULL was never ASSERTED as news, and
# labelling it so would fabricate the very "asserted fact" the class promises AND make
# the facet count disagree with the /api/articles?source_type= filter (which matches on
# the real value, so it excludes NULL rows). Both the facet and the filter treat this
# reserved key as "channel not asserted".
SOURCE_TYPE_UNTYPED = "untyped"


def source_type_facets(session) -> dict:
    """Article counts per raw source CHANNEL (Source.source_type) — the content-
    provenance S2 facet, so the corpus can be sliced by channel (news/newsletter/wiki/
    statistics/law/market/discovery/...).

    An ASSERTED descriptive fact known by construction (the ingest path / catalog sets
    the channel), NEVER a quality/credibility score. Counts only. A source whose channel
    was never asserted (NULL/blank source_type — e.g. a restore-merged or wikidata-
    untyped source) is bucketed HONESTLY under ``SOURCE_TYPE_UNTYPED``, never relabelled
    as the default 'news'. PERF: a GROUP BY over articles joined to the small sources
    table on source_type — index-friendly, never reads article content (no codec
    decrypt); Article.source_id is NOT NULL, so every article is counted exactly once.
    """
    counts: dict[str, int] = {}
    for st, c in (
        session.query(Source.source_type, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .group_by(Source.source_type)
    ):
        # Normalise identically to the filter (lowercase; NULL/blank -> untyped), so the
        # facet count for a channel EQUALS what clicking it in /api/articles returns.
        key = (st or "").strip().lower() or SOURCE_TYPE_UNTYPED
        counts[key] = counts.get(key, 0) + int(c)
    facets = [
        {"source_type": st, "articles": n}
        for st, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "facets": facets,
        "total": sum(f["articles"] for f in facets),
        "method": (
            "Article counts grouped by the source's asserted source_type channel "
            f"(lowercased; a source with no asserted channel is bucketed '{SOURCE_TYPE_UNTYPED}')."
        ),
        "caveat": (
            "An asserted descriptive channel known by construction (the ingest path / "
            "catalog), never a quality or credibility score. Counts only."
        ),
    }


def keyword_stats(
    session,
    term: str,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    cooccur_limit: int = 5,
) -> dict:
    """Compact hover stats for ONE keyword (the clickable-in-article-keyword hover):
    total mentions + distinct-article spread + a windowed recent-vs-prior RATE + the
    top co-occurring keywords. Counts only, method + caveat, NO score.

    PERF (codec-decrypt lesson): mention n and article spread come from a single
    aggregate over the keyword_mentions rows for THIS keyword_id (index-only via
    ix_mention_covering) — NEVER the keyword_mentions -> articles join that drags
    article pages through the SQLCipher codec. The trend windows scan the same
    keyword_id-scoped rows on observed_on; co-occurrences reuse :func:`associations`
    (which itself avoids the article join).
    """
    empty_trend = {
        "window_days": window_days, "baseline_days": baseline_days,
        "recent": 0, "prior": 0, "recent_per_day": 0.0, "prior_per_day": 0.0,
        "expected": 0.0, "growth": 0.0,
    }
    kw = resolve_keyword(session, term)
    if kw is None:
        return {
            "term": term, "resolved": None, "mentions": 0, "articles": 0,
            "trend": empty_trend, "cooccurrences": [],
            "method": "no stored keyword matched this term",
            "caveat": "This term is not in your corpus yet — no counts to show.",
        }

    # Exact mention n + distinct-article spread over this keyword's mention rows.
    # ix_mention_keyword_article is UNIQUE on (keyword_id, article_id), so a distinct
    # article count is the row count; both served index-only (no article decrypt).
    row = (
        session.query(
            func.count(func.distinct(KeywordMention.article_id)),
            func.coalesce(func.sum(KeywordMention.count), 0),
        )
        .filter(KeywordMention.keyword_id == kw.id)
        .one()
    )
    distinct_articles, total_mentions = int(row[0] or 0), int(row[1] or 0)

    # Windowed recent-vs-prior RATE for this keyword — the SAME transparent ratio
    # trending() uses (recent volume vs the prior-period rate), scanning only this
    # keyword's mention rows (keyword_id + observed_on range on ix_mention_keyword_date).
    # This is a BOUNDED mention-table read for one keyword (small rows, never article
    # content), NOT index-only (count isn't in that index) and NEVER the articles join.
    today = date.today()
    w_start = today - timedelta(days=window_days)
    b_start = w_start - timedelta(days=baseline_days)

    def _sum(lo, hi) -> int:
        return int(
            session.query(func.coalesce(func.sum(KeywordMention.count), 0))
            .filter(
                KeywordMention.keyword_id == kw.id,
                KeywordMention.observed_on >= lo,
                KeywordMention.observed_on < hi,
            )
            .scalar()
            or 0
        )

    recent = _sum(w_start, today + timedelta(days=1))
    prior = _sum(b_start, w_start)
    expected = (prior / baseline_days) * window_days
    growth = round(recent / expected, 2) if expected >= 1 else float(recent)
    trend_block = {
        "window_days": window_days,
        "baseline_days": baseline_days,
        "recent": recent,
        "prior": prior,
        "recent_per_day": round(recent / window_days, 3),
        "prior_per_day": round(prior / baseline_days, 3),
        "expected": round(expected, 2),
        "growth": growth,
    }

    # Top co-occurring keywords (count + PMI), reusing the vetted co-occurrence path.
    cooccur: list[dict] = []
    if cooccur_limit > 0:
        assoc = associations(session, kw.term, limit=cooccur_limit, min_cooccur=2, group=False)
        cooccur = [
            {"term": p["term"], "normalized": p.get("normalized"),
             "cooccur": p["cooccur"], "pmi": p["pmi"]}
            for p in assoc.get("pairs", [])
        ]

    return {
        "term": term,
        "resolved": {
            "term": kw.term, "normalized": kw.normalized_term,
            "kind": kind_of(kw), "language": kw.language,
        },
        "mentions": total_mentions,
        "articles": distinct_articles,
        "trend": trend_block,
        "cooccurrences": cooccur,
        "method": (
            "Mention n and article spread are exact counts over this keyword's "
            "mention index (no article decrypt). The trend is recent volume vs the "
            "prior-period rate (a transparent ratio, not a significance test). "
            "Co-occurrences are keywords sharing an article, by count and PMI."
        ),
        "caveat": (
            "Counts only, never a score. The trend ratio is noisy on a young corpus; "
            "co-occurrence and PMI are association, not causation. Deduced from your "
            "corpus, not a claim about the world."
        ),
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
    """Indexing status for the Insights tab.

    Every count here is the REAL, EXACT value. The field's cost from this endpoint —
    ``count(*) FROM keyword_mentions`` measured 724 ms × 172 polls = 124 s — is removed at
    the ENDPOINT by a data-aware cache (:func:`src.api.insights._status_cache_key`) that
    collapses repeat polls but invalidates on a commit by ANY connection (it reads
    ``PRAGMA data_version`` on a pinned probe connection, so a write on a DIFFERENT pooled
    connection than the poller's still bumps the key — the #595/A3 fix), NOT by trading the
    exact count for a maintained-counter sum. (A counter-derived ``SUM(article_count)`` would
    be cheaper per cold compute but can drift silently on a cascade delete — presenting a
    wrong number as exact would breach the honesty non-negotiable — so the exact count stays;
    a correctness-gated counter-serve is a possible future optimisation, but only once its
    basis is tied to the corpus epoch, not the reconcile watermark.)"""
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


# --- Keyword-graph bounding (Item 8, field-test 2026-07-08) ------------------- #
#
# ``GET /api/insights/graph?level=keyword&term=…&hops=2`` fanned out ~6 associations()
# calls (hop-1 + the top hop-2 relatives) over a 974K-keyword corpus and blew past the
# request deadline (60s -> 503 -> a broken frontend). These caps make the work BOUNDED
# regardless of corpus size; whenever a cap actually truncates the result the payload
# DISCLOSES it (a ``bounded`` flag + a disclosure appended to the visible caveat), never a
# silent truncation. The associations() batch-optimization (n_b via the maintained
# article_count counter, one Keyword IN, ZERO per-co-keyword COUNT(DISTINCT)/session.get)
# is inherited unchanged; on top we (a) compute the corpus-total denominator ONCE and
# thread it into every call (it was recomputed once per associations() call), and (b) bound
# each term's article set so a high-frequency seed can't drag the whole build past budget.
def _graph_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


# Per-term article sample: a term in more than this many articles has its co-occurrence
# computed over a DETERMINISTIC, time-spanning sample (bounds each associations() call so
# the whole build stays bounded no matter how frequent the seed is). Kept at 900 so the
# sampled set fed to co_rows' ``article_id.in_(...)`` stays UNDER SQLite's 999 bound-variable
# cap — the repo-wide invariant (cf. latest.py:_SQL_IN_CHUNK=900, the *_IN_CHUNK modules); a
# larger value would risk "too many SQL variables" (an OperationalError -> 500) on a build
# with the historical 999 limit, for exactly the high-frequency seeds this feature targets.
GRAPH_ARTICLE_CAP = _graph_int_env("OO_GRAPH_ARTICLE_CAP", 900)
# Hop-2 branches: relatives of the strongest hop-1 relatives to expand (was hardcoded 5).
GRAPH_HOP2_PARENTS = _graph_int_env("OO_GRAPH_HOP2_PARENTS", 4)
# Hard cap on total edges kept (the strongest by co-occurrence) — keeps the picture legible.
GRAPH_MAX_EDGES = _graph_int_env("OO_GRAPH_MAX_EDGES", 160)


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
    hop2_parents: int | None = None,
    article_cap: int | None = None,
    max_edges: int | None = None,
    time_budget_s: float | None = None,
) -> dict:
    """One zoom level of the keyword graph: keyword (≤2 hops) / family / supergroup.

    The keyword level is BOUNDED (Item 8): the corpus-total PMI denominator is computed
    ONCE and threaded into every associations() call; each term's article set is sampled to
    ``article_cap`` (deterministic, time-spanning — no recency bias); the hop-2 fan-out is
    ``hop2_parents`` branches; nodes are capped at ``limit_nodes`` and edges at
    ``max_edges``; an optional ``time_budget_s`` stops expanding to hop-2 once the wall
    clock exceeds it, returning the hop-1 graph already built. Any cap that truncates the
    result sets ``bounded`` and appends a visible disclosure to ``caveat`` — never a silent
    cut. ``None`` for a cap means "use the module default"."""
    hop2_parents = GRAPH_HOP2_PARENTS if hop2_parents is None else hop2_parents
    article_cap = GRAPH_ARTICLE_CAP if article_cap is None else article_cap
    max_edges = GRAPH_MAX_EDGES if max_edges is None else max_edges
    if level == "keyword":
        if not term:
            return {"level": level, "nodes": [], "edges": [], "error": "term required"}
        t0 = time.monotonic()
        bounded = False
        # Window resolution mirrors associations() so the corpus total we compute ONCE below
        # uses the SAME window the calls will use (byte-identical PMI to the un-bounded path).
        if days and not start:
            start = date.today() - timedelta(days=days)
        # The PMI corpus denominator, computed ONCE (was recomputed inside every call).
        corpus_total = (
            _window_filter(
                session.query(func.count(func.distinct(KeywordMention.article_id))), start, end
            ).scalar()
            or 0
        )
        base = associations(
            session, term, limit=12, group=True, days=days, start=start, end=end,
            corpus_total=corpus_total, article_cap=article_cap,
        )
        bounded = bounded or bool(base.get("articles_bounded"))
        center = (base.get("resolved") or {}).get("term", term)
        nodes = [{"id": center, "label": center, "kind": "keyword", "center": True, "size": 13}]
        edges, seen = [], {center}
        for p in base.get("pairs", []):
            if len(nodes) >= limit_nodes:
                bounded = True  # more hop-1 relatives than the node cap allows
                break
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
            for p in base.get("pairs", [])[:hop2_parents]:  # relatives of the strongest relatives
                if len(nodes) >= limit_nodes:
                    bounded = True
                    break
                if time_budget_s is not None and (time.monotonic() - t0) > time_budget_s:
                    # Out of budget: return the hop-1 graph already built rather than push
                    # into another heavy call and risk the hard deadline (never a 503).
                    bounded = True
                    break
                second = associations(
                    session, p["term"], limit=4, group=True, days=days, start=start, end=end,
                    corpus_total=corpus_total, article_cap=article_cap,
                )
                bounded = bounded or bool(second.get("articles_bounded"))
                for p2 in second.get("pairs", []):
                    if len(nodes) >= limit_nodes:
                        bounded = True
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
        if len(edges) > max_edges:
            # Keep the strongest edges by co-occurrence (deterministic); disclose the cut.
            edges = sorted(edges, key=lambda e: -(e.get("weight") or 0))[:max_edges]
            bounded = True
        caveat = "Association is not causation; PMI on small samples is noisy."
        out = {
            "level": level,
            "term": center,
            "nodes": nodes,
            "edges": edges,
            "method": "PMI/co-occurrence association, two hops (relatives, and their relatives)",
            "caveat": caveat,
        }
        if bounded:
            out["bounded"] = True
            out["disclosure"] = (
                f"Bounded view for responsiveness: up to {limit_nodes} nodes, "
                f"{hop2_parents} hop-2 branches, ≤{article_cap} articles sampled per term. "
                "Narrow the term or the time window for a finer view."
            )
            # Surface it in the field the frontend already renders (visible-by-default).
            out["caveat"] = caveat + " " + out["disclosure"]
        return out

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
