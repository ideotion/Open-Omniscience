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


# Markup/URL tokens that should never be content keywords (the leak class from the
# 2026-06-18 log). Mirrors the global stoplist's web-junk batch; here it is a
# DETECTOR (counts what still leaked), not a filter.
_MARKUP_TOKENS = frozenset(
    "https http www href img colspan rowspan tbody thead nbsp px utf "
    "span div src rel nofollow noopener stylesheet javascript "
    "margin-left margin-right padding-left padding-right font-size text-align".split()
)


def _extraction_noise(session: Session, cap: int = 60000) -> dict:
    """Bounded audit of keyword HYGIENE — how much of the index is extraction noise,
    by actionable CLASS, with examples. No score; counts only. Each class points at a
    concrete fix (de-elision, HTML stripping, a stoplist), so a maintainer can see the
    backlog shrink after a re-index / a new batch lands."""
    import re

    from src.analytics.extract import _ELISION, _is_code_token  # elision + code-token

    rows = session.query(Keyword.normalized_term).limit(cap).all()
    terms = [r[0] or "" for r in rows]
    scanned = len(terms)

    classes: dict[str, dict] = {
        "elision_contaminated": {
            "what": "a keyword still carrying an elided article/pronoun (l'/d'/qu'…) — pre de-elision backlog; clears on re-index",
            "count": 0, "examples": [],
        },
        "markup_token": {
            "what": "an HTML/CSS/URL token that leaked from un-stripped page chrome (https/colspan/margin-left…)",
            "count": 0, "examples": [],
        },
        "mostly_digits": {
            "what": "a token that is all digits or digit-heavy (rarely a useful content keyword)",
            "count": 0, "examples": [],
        },
        "has_markup_char": {
            "what": "a token containing a markup/structural character (<, >, {, }, =, /, ;) — almost always leaked HTML/CSS",
            "count": 0, "examples": [],
        },
        "code_token": {
            "what": "a digit-segmented code or underscore identifier the extraction code-token filter (§2.5/§2.6) drops on re-index (a-10c, gd_combo_table) — the PROJECTED reduction; a re-index clears it",
            "count": 0, "examples": [],
        },
    }

    def _hit(key: str, term: str) -> None:
        c = classes[key]
        c["count"] += 1
        if len(c["examples"]) < 10:
            c["examples"].append(term)

    markup_char_re = re.compile(r"[<>{}=;/]")
    for t in terms:
        if not t:
            continue
        head = t.split()[0] if " " in t else t
        if _ELISION.search(t):
            _hit("elision_contaminated", t)
        if head in _MARKUP_TOKENS or any(w in _MARKUP_TOKENS for w in t.split()):
            _hit("markup_token", t)
        if markup_char_re.search(t):
            _hit("has_markup_char", t)
        digits = sum(1 for ch in t if ch.isdigit())
        alpha = sum(1 for ch in t if ch.isalpha())
        if digits and digits >= max(1, alpha):
            _hit("mostly_digits", t)
        # The extraction code-token filter drops these on the next re-index (an n-gram
        # carrying a code token is dropped too, so check every token in the keyword).
        if any(_is_code_token(w) for w in t.split()):
            _hit("code_token", t)

    total_noise = sum(c["count"] for c in classes.values())
    return {
        "method": (
            "Bounded scan of keyword normalized_terms (cap stated), classified by actionable "
            "noise type with examples. Classes can overlap. Counts only — no score."
        ),
        "scanned": scanned,
        "cap": cap,
        "capped": scanned >= cap,
        "total_flagged": total_noise,
        "pct_flagged": _pct(total_noise, scanned),
        "classes": classes,
    }


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


def _mention_distribution(session: Session) -> dict:
    """How the keyword count splits by support — the answer to "why so many keywords?".

    Cheap O(keywords) reads of the denormalised counters (never a mention scan). The
    ``zero_mention`` bucket is the prunable backlog: keywords no view references (their
    only contribution was deleted/merged, or they were markup tokens drained by a
    re-index). ``single_article`` = hapax (one article only). Counts only — no score."""

    def c(*filters) -> int:
        q = session.query(func.count(Keyword.id))
        for f in filters:
            q = q.filter(f)
        return int(q.scalar() or 0)

    mc = Keyword.mention_count
    return {
        "method": (
            "Keywords bucketed by their maintained mention/article counters. "
            "zero_mention = prunable orphans (no view references them). No score."
        ),
        "zero_mention": c(mc == 0),
        "single_article": c(Keyword.article_count == 1),
        "by_mentions": {
            "1": c(mc == 1),
            "2-5": c(mc >= 2, mc <= 5),
            "6-50": c(mc >= 6, mc <= 50),
            "51+": c(mc >= 51),
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
            "mention_distribution": _mention_distribution(session),
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
        "extraction_noise": _extraction_noise(session),
        "curation": {
            "rings": rings_total,
            "family_overrides": int(session.query(func.count(KeywordFamilyOverride.id)).scalar() or 0),
            "supergroups": int(session.query(func.count(KeywordSuperGroup.id)).scalar() or 0),
            "tags": int(session.query(func.count(KeywordTag.id)).scalar() or 0),
        },
        "selftest": run_keyword_selftest()["summary"],
        "performance": _performance(session, sample_articles),
    }
