"""Keyword-engine efficacy + performance report (the maintainer's hand-back tool).

A bounded, read-only diagnostic over the LIVE corpus that measures how the keyword
engine is doing — composition, entity precision (post the Title-case drop),
cross-language TRANSLATION coverage (the number that tracks the ring/pre-translation
work), tag coverage, per-language functional status, the curation surface, the
golden-case self-test, and indicative performance (extraction throughput + grouped
query latency). Counts and measured timings only — NO composite "quality score"
(the non-negotiable); every block carries its own method.

Surfaced at ``GET /api/diagnostics/keyword-engine`` (schema ``oo-keyword-engine-1``)
so the maintainer runs it and sends the JSON back; diffing two reports over time
shows whether each optimization (more rings, more tags, fewer junk keywords) landed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import (
    Article,
    Keyword,
    KeywordFamilyOverride,
    KeywordMention,
    KeywordSuperGroup,
    KeywordTag,
)

# Languages with FUNCTIONAL keyword extraction today live in the ONE source of
# truth (src.analytics.managed) — shared with the source-language gating so the
# engine report and "which sources to disable" can never disagree.
from src.analytics.managed import MANAGED_LANGUAGES as _FUNCTIONAL
from src.analytics.managed import UNSEGMENTED as _UNSEGMENTED


def _is_acronym(n: str) -> bool:
    return len(n) >= 2 and n.isupper() and any(c.isalpha() for c in n)


def _lang_status(lang: str) -> str:
    if lang in _UNSEGMENTED:
        return "unsegmented"  # no word segmentation -> extraction broken
    if lang in _FUNCTIONAL:
        return "functional"
    return "no_stoplist"  # tokenises, but function words leak (analytics unreliable)


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def _performance(session: Session, sample_articles: int) -> dict:
    """Indicative timings on THIS machine (bounded sample) — not a benchmark."""
    from src.analytics import queries as q
    from src.analytics.extract import BaselineExtractor

    ex = BaselineExtractor()
    rows = (
        session.query(Article.content, Article.title, Article.language)
        .limit(sample_articles)
        .all()
    )
    arts = [(c, t, lg) for (c, t, lg) in rows if (c or "").strip()]
    chars = 0
    t0 = time.perf_counter()
    for content, title, lang in arts:
        ex.extract(content or "", title=title or "", language=lang or "en")
        chars += len(content or "")
    extract_dt = time.perf_counter() - t0

    t1 = time.perf_counter()
    grouped = q.top_terms(session, limit=50, group=True)
    grouped_dt = time.perf_counter() - t1

    return {
        "method": "wall-clock over a bounded sample on this machine; indicative, not a benchmark",
        "extraction": {
            "articles_sampled": len(arts),
            "chars": chars,
            "ms_per_article": round(1000 * extract_dt / len(arts), 2) if arts else None,
        },
        "grouped_top_terms": {
            "rows": len(grouped.get("terms", []) if isinstance(grouped, dict) else []),
            "ms": round(1000 * grouped_dt, 2),
            "method": "top_terms(group=True): families + cross-language ring merge",
        },
    }


def keyword_engine_report(session: Session, *, top_n: int = 500, sample_articles: int = 25) -> dict:
    """Compute the efficacy + performance report (bounded, read-only, no score)."""
    from src.analytics.equivalence import is_ring_term, load_rings
    from src.analytics.selftest import run_keyword_selftest

    total = session.query(func.count(Keyword.id)).scalar() or 0
    entities = session.query(func.count(Keyword.id)).filter(Keyword.is_entity.is_(True)).scalar() or 0
    ngrams = session.query(func.count(Keyword.id)).filter(Keyword.is_ngram.is_(True)).scalar() or 0

    # Entity precision: post-2026-06-16 an entity should be an ALL-CAPS acronym;
    # a non-acronym entity is legacy/residual case-noise.
    ent_norms = [
        n for (n,) in session.query(Keyword.normalized_term)
        .filter(Keyword.is_entity.is_(True))
        .limit(100000)
    ]
    ent_acronyms = sum(1 for n in ent_norms if _is_acronym(n or ""))

    # Top-N most-mentioned keywords: cross-language ring + tag coverage.
    top_rows = (
        session.query(
            Keyword.id,
            Keyword.normalized_term,
            func.coalesce(func.sum(KeywordMention.count), 0).label("m"),
        )
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
        .order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(top_n)
        .all()
    )
    top_ids = [r[0] for r in top_rows]
    top_norms = [r[1] for r in top_rows]
    ring_hits = sum(1 for n in top_norms if is_ring_term(n))
    tagged_top = 0
    if top_ids:
        tagged_top = (
            session.query(func.count(func.distinct(KeywordTag.keyword_id)))
            .filter(KeywordTag.keyword_id.in_(top_ids))
            .scalar()
            or 0
        )

    # Per-language coverage + functional status.
    languages = [
        {"language": (lang or "?"), "keywords": int(n), "status": _lang_status(lang or "?")}
        for lang, n in session.query(Keyword.language, func.count(Keyword.id))
        .group_by(Keyword.language)
        .all()
    ]
    languages.sort(key=lambda x: -int(x["keywords"]))

    rings_total = len(load_rings())

    return {
        "kind": "keyword-engine-report",
        "schema": "oo-keyword-engine-1",
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "Counts + bounded samples over the live corpus. No score; each block states its method.",
        "composition": {
            "keywords": int(total),
            "entities": int(entities),
            "terms": int(total) - int(entities),
            "ngrams": int(ngrams),
        },
        "entity_precision": {
            "entities": int(entities),
            "valid_acronyms": ent_acronyms,
            "pct_acronym": _pct(ent_acronyms, int(entities)),
            "method": "entities should be ALL-CAPS acronyms (Title-case dropped 2026-06-16); the rest are legacy/residual",
        },
        "translation_coverage": {
            "top_n": len(top_norms),
            "in_a_ring": ring_hits,
            "pct": _pct(ring_hits, len(top_norms)),
            "rings_total": rings_total,
            "method": "share of the most-mentioned keywords that belong to a cross-language ring; grows as rings are added",
        },
        "tag_coverage": {
            "top_n": len(top_ids),
            "tagged": int(tagged_top),
            "pct": _pct(int(tagged_top), len(top_ids)),
            "method": "share of the most-mentioned keywords carrying >=1 baseline/user tag (Item AC)",
        },
        "language_coverage": {
            "method": "functional = has a stoplist + space-segmented; unsegmented (zh/ja) = extraction broken; no_stoplist = function words leak",
            "languages": languages,
        },
        "curation": {
            "rings": rings_total,
            "family_overrides": int(session.query(func.count(KeywordFamilyOverride.id)).scalar() or 0),
            "supergroups": int(session.query(func.count(KeywordSuperGroup.id)).scalar() or 0),
            "tags": int(session.query(func.count(KeywordTag.id)).scalar() or 0),
        },
        "selftest": run_keyword_selftest()["summary"],
        "performance": _performance(session, sample_articles),
    }
