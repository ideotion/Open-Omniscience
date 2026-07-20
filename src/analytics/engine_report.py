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

# Language status lives in the ONE source of truth (src.analytics.managed) — shared
# with the source-language gating so the engine report and "which sources to disable"
# can never disagree. It is segmenter-aware: zh/ja/th report 'functional' when the
# optional [segmentation] extra is installed, 'unsegmented' otherwise.
from src.analytics.managed import language_status as _language_status


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
    # One source of truth (segmenter-aware): 'functional' | 'unsegmented' |
    # 'no_stoplist' | 'unknown'. zh/ja/th flip to functional when the [segmentation]
    # extra is installed; a core install still reports them 'unsegmented'.
    return _language_status(lang)


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


def _plural_rule_classification(members: list[str]) -> str:
    """Classify a lemma-preview group by how much the PLURAL rule (families.py step 1.5,
    which runs BEFORE the lemma step) already accounts for it — so the review shows the
    true DELTA lemmatization adds, not merges it was already getting for free.

    ``"plural_rule"`` — every member is already connected via the plural rule alone (a
    regular -s/-es/-ies relation, base not denylisted); the lemma step contributes NOTHING
    new here. ``"lemma_only"`` — no member pair is plural-connected (a genuine addition —
    typically a verb form or an irregular, e.g. study/studied). ``"mixed"`` — the lemma
    step bridges two-or-more plural-connected sub-clusters the plural rule alone would have
    kept apart. Pure, no DB access."""
    from src.analytics.families import _PLURAL_DENYLIST, _plural_bases

    ms = sorted(set(members))
    if len(ms) < 2:
        return "lemma_only"
    idx = {m: i for i, m in enumerate(ms)}
    parent = list(range(len(ms)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    connected = False
    for m in ms:
        for base in _plural_bases(m):
            if base in _PLURAL_DENYLIST:
                continue
            j = idx.get(base)
            if j is not None:
                union(idx[m], j)
                connected = True

    if not connected:
        return "lemma_only"
    roots = {find(i) for i in range(len(ms))}
    return "plural_rule" if len(roots) == 1 else "mixed"


def _lemma_preview(rows: list[tuple]) -> dict:
    """What lemmatization (P4.3, ON by default since 2026-07-18) MERGES among the top
    keywords — the precision-review instrument for the measure-before-trust discipline.
    Single-token TERMS (never entity NAMES) that share a lemma per (language) are the
    candidate conflations the maintainer eyeballs; a wrong merge becomes a
    ``_MISLEMMA_DENYLIST`` entry (and ``OO_FAMILY_LEMMA=0`` opts out entirely). Read-only,
    bounded, no score; reports "unavailable" honestly when the optional ``simplemma`` is
    absent.

    Each candidate group is also tagged ``plural_overlap`` (plural_rule / lemma_only /
    mixed, see ``_plural_rule_classification``) so a review shows the TRUE delta the lemma
    step adds beyond the plural rule already running before it — most groups a naive read
    flags as "new merges" turn out to already be collapsed by the plural step alone.

    ``rows`` are ``(normalized_term, language, is_entity)`` from the top-N keyword scan."""
    from src.analytics.families import _lemma, _lemma_enabled, _simplemma

    if _simplemma is None:
        return {
            "available": False,
            "method": "simplemma (optional [analysis] extra) is not installed; lemmatization is a no-op here.",
        }
    groups: dict[tuple, list[str]] = {}
    for norm, lang, is_entity in rows:
        n = norm or ""
        if is_entity or not n or " " in n:  # terms only, single-token (mirrors families step 1.6)
            continue
        groups.setdefault(((lang or "?"), _lemma(n, lang)), []).append(n)
    candidates = [
        {
            "lemma": lem,
            "language": lg,
            "members": sorted(set(ms)),
            "n": len(set(ms)),
            "plural_overlap": _plural_rule_classification(list(ms)),
        }
        for (lg, lem), ms in groups.items()
        if len(set(ms)) >= 2
    ]
    candidates.sort(key=lambda c: (-c["n"], c["lemma"]))
    by_overlap: dict[str, int] = {"plural_rule": 0, "mixed": 0, "lemma_only": 0}
    for c in candidates:
        by_overlap[c["plural_overlap"]] += 1
    return {
        "available": True,
        "enabled": _lemma_enabled(),  # whether OO_FAMILY_LEMMA is currently on (default: yes)
        "scanned_top_n": len(rows),
        "candidate_groups": len(candidates),
        "keywords_that_would_merge": sum(c["n"] for c in candidates),
        "by_plural_overlap": by_overlap,
        "examples": candidates[:15],
        "method": (
            "Among the most-mentioned single-token TERMS, the groups that share a lemma "
            "(study/studied -> study). plural_overlap on each group shows whether the "
            "plural rule (families step 1.5) already merges it ('plural_rule'/'mixed') or "
            "the lemma step is the ONLY reason it merges ('lemma_only' -- the true delta, "
            "e.g. verb forms/irregulars). REVIEW for precision -- a wrong merge means a "
            "_MISLEMMA_DENYLIST entry, or OO_FAMILY_LEMMA=0 to opt out entirely. No score."
        ),
    }


def lemma_preview_report(session: Session, *, top_n: int = 500) -> dict:
    """The lemma-conflation preview ALONE (S5.4) — the focused review instrument the
    Diagnostics panel surfaces next to the gold-set builder, WITHOUT running the full engine
    report (no timings / self-test). Reads the top-N keywords and returns what lemmatization
    (``OO_FAMILY_LEMMA``, on by default) MERGES, so a wrong merge can be noted for
    ``_MISLEMMA_DENYLIST`` (or the feature disabled) before trusting it further. Read-only,
    bounded, no score; honest ``available: false`` when simplemma is absent.
    """
    rows = (
        session.query(
            Keyword.id,
            Keyword.normalized_term,
            Keyword.language,
            Keyword.is_entity,
            func.coalesce(func.sum(KeywordMention.count), 0).label("m"),
        )
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
        .order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(max(1, top_n))
        .all()
    )
    return _lemma_preview([(r[1], r[2], r[3]) for r in rows])


def _generic_terms(session: Session, *, top_per_lang: int = 15, cap: int = 40000) -> dict:
    """OPEN-CLASS garbage surfacing — the in-app analog of ``scripts/analyze_keyword_log.py
    --generic-terms``: high-document-frequency single-word TERMS that survive the current
    stoplist (ubiquitous adjectives / common nouns / generic verbs — system, global, foto,
    nieuws — that no function-word list catches).

    POS-free, so DOCUMENT FREQUENCY is the only honest signal: a word in a large share of a
    language's articles is EITHER boilerplate OR a genuinely dominant topic (health/policy are
    real topics; system/global are not). With no POS tagger we CANNOT tell them apart, so every
    row is a REVIEW CANDIDATE the human dispositions — never a verdict, NEVER auto-applied (the
    no-blanket-rule discipline; the innocent 'a dominant topic looks identical' explanation
    rides with it). Folding it into the routine diagnostics export hands the maintainer the
    open-class stoplist worklist automatically. Excludes entities/acronyms, ring members, and
    already-stoplisted words (weekdays are already in the stoplist); a word carrying a baseline
    TAG is FLAGGED (a known topic, so almost certainly not garbage). ``df_ratio`` = the term's
    article spread vs the most-ubiquitous term in its language (self-normalising; ~1.0 = as
    common as the commonest word). Bounded, read-only, no score."""
    from src.analytics.equivalence import is_ring_term
    from src.analytics.extract import global_stopwords

    stop = global_stopwords()
    rows = (
        session.query(
            Keyword.id, Keyword.normalized_term, Keyword.term,
            Keyword.language, Keyword.article_count, Keyword.mention_count,
        )
        .filter(
            Keyword.is_entity.is_(False),
            Keyword.is_ngram.is_(False),
            Keyword.article_count > 1,
        )
        .order_by(Keyword.article_count.desc())
        .limit(cap)
        .all()
    )
    by_lang: dict[str, list[dict]] = {}
    ids: list[int] = []
    for kid, norm, term, lang, arts, ments in rows:
        n = norm or ""
        if not n or " " in n:  # single words only (n-gram boilerplate is a separate class)
            continue
        if n in stop or is_ring_term(n) or _is_acronym(n) or _is_acronym(term or ""):
            continue  # already caught / a ring concept / an acronym — not open-class garbage
        by_lang.setdefault((lang or "?"), []).append(
            {"id": int(kid), "term": term or n, "normalized": n,
             "articles": int(arts or 0), "mentions": int(ments or 0)}
        )
        ids.append(int(kid))

    tagged: set[int] = set()
    for i in range(0, len(ids), 900):  # bounded IN() (SQLite variable limit)
        chunk = ids[i : i + 900]
        tagged.update(
            int(t) for (t,) in session.query(KeywordTag.keyword_id)
            .filter(KeywordTag.keyword_id.in_(chunk)).distinct()
        )

    out: dict[str, list[dict]] = {}
    total = 0
    for lg, items in by_lang.items():
        lang_max = max((it["articles"] for it in items), default=1) or 1
        for it in items:
            it["df_ratio"] = round(it["articles"] / lang_max, 3)
            it["tagged"] = it.pop("id") in tagged  # a baseline tag => a known topic, likely NOT garbage
        items.sort(key=lambda x: -x["articles"])
        out[lg] = items[: max(top_per_lang, 0)]
        total += len(out[lg])
    return {
        "method": (
            "High-document-frequency single-word TERMS surviving the stoplist, per language, "
            "ranked by article spread (df_ratio, self-normalised). REVIEW candidates for the "
            "open-class stoplist — a dual-use call the human makes (health/policy stay; "
            "system/global go); never auto-applied, never a verdict. A tagged term is a known "
            "topic (flagged). No score."
        ),
        "top_per_language": top_per_lang,
        "candidate_terms": total,
        "by_language": out,
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
            Keyword.language,
            Keyword.is_entity,
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
        "lemma_preview": _lemma_preview([(r[1], r[2], r[3]) for r in top_rows]),
        "tag_coverage": {
            "top_n": len(top_ids),
            "tagged": int(tagged_top),
            "pct": _pct(int(tagged_top), len(top_ids)),
            "method": "share of the most-mentioned keywords carrying >=1 baseline/user tag (Item AC)",
        },
        "language_coverage": {
            "method": "functional = has a stoplist + tokenisable; unsegmented (zh/ja/th without the [segmentation] extra) = extraction broken; no_stoplist = function words leak",
            "languages": languages,
        },
        "extraction_noise": _extraction_noise(session),
        "generic_terms": _generic_terms(session),
        "curation": {
            "rings": rings_total,
            "family_overrides": int(session.query(func.count(KeywordFamilyOverride.id)).scalar() or 0),
            "supergroups": int(session.query(func.count(KeywordSuperGroup.id)).scalar() or 0),
            "tags": int(session.query(func.count(KeywordTag.id)).scalar() or 0),
        },
        "selftest": run_keyword_selftest()["summary"],
        "performance": _performance(session, sample_articles),
    }
