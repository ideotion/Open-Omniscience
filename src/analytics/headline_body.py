"""Headline-body mismatch (manipulation-pattern card #7, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent or truth (the manipulation-card doctrine): an
article whose HEADLINE leads with content the BODY does not substantiate. Two
deterministic, language-honest measures from the maintainer's nine-card spine
(``docs/FUTURE_DEVELOPMENTS.md`` card #7):

  * **lexical divergence** ``d_lex = 1 - |H ∩ B_top| / |H|`` — the fraction of the
    headline's content keywords that are NOT among the body's TOP keywords. A real
    ratio in [0, 1], language-agnostic (it reuses the same keyword extractor for
    both title and body, so it works in every language the extractor supports).
  * **sentiment gap** ``Δs = |sent(H) - sent(B)|`` — how far the headline's tone is
    from the body's. VADER is English-only, so this is computed ONLY for English
    articles and is ``None`` otherwise — never a fabricated neutral (the standing
    VADER-English-only disclosure).

Fires when the headline is rich enough to mismatch meaningfully (``|H| >=
min_headline_terms``) AND (``d_lex >= d_min`` OR ``Δs >= sentiment_gap_min``). This
is a DIVERGENCE card (bucket ``debunk``), so it fires per-article — the convergence
"no single-signal" gate is for the cross-source coordination cards, not this one.

HONESTY (enforced in code, not just prose):
  * the signal carries its COMPONENTS (``lexical_div``, ``sentiment_gap``, ``lang``,
    the exact absent headline terms) — never a blended "clickbait score";
  * the innocent twin is stated beside the pattern (a summarising / metaphorical
    headline does exactly this without deceiving — read both and judge);
  * the sentiment half is labelled English-only and is ``None`` elsewhere;
  * precision-biased: strict thresholds + a minimum headline richness, so a punchy
    one-word headline never trivially fires (when in doubt, stay silent);
  * the scan is bounded (a recent pool, the body capped at ``body_max_chars`` — its
    lead carries the salient terms) and that bound is stated in the method.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

HEADLINE_BODY_CAVEAT = (
    "The headline leads with content the article body does not substantiate. A "
    "summarising or metaphorical headline does exactly this without deceiving — and "
    "the sentiment gap, when shown, is VADER English-only — so the shape is "
    "'headline ≠ body', never a claim it was deliberate. Read both and judge."
)


def find_headline_body_mismatch(
    session,
    *,
    recent_days: int = 14,
    min_headline_terms: int = 3,
    d_min: float = 0.67,
    sentiment_gap_min: float = 0.6,
    top_body_terms: int = 25,
    min_chars: int = 200,
    body_max_chars: int = 8000,
    recent_limit: int = 800,
    max_items: int = 12,
) -> dict:
    """Recent articles whose headline diverges from the body — lexically or in tone.

    Pulls a bounded RECENT pool (``observed >= now - recent_days``), and for each
    article compares the HEADLINE's content keywords ``H`` to the BODY's TOP keywords
    ``B_top`` (same extractor for both, so language-agnostic) and, for English only,
    the headline-vs-body sentiment gap. Read-only; real ratios + components only; no
    score. Bounded: up to ``recent_limit`` articles, body capped at ``body_max_chars``.
    """
    from src.analytics.extract import BaselineExtractor
    from src.analytics.sentiment import score_article
    from src.database.models import Article, Source

    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=recent_days)).replace(tzinfo=None)
    observed = func.coalesce(Article.published_at, Article.created_at)
    rows = (
        session.query(Article, Source.name, Source.domain)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(observed >= cutoff)
        .order_by(Article.id.desc())
        .limit(recent_limit)
        .all()
    )

    ext = BaselineExtractor()
    items: list[dict] = []
    for a, sname, sdom in rows:
        title = (a.title or "").strip()
        body = (a.get_content() or "").strip()
        if not title or len(body) < min_chars:
            continue
        lang = (a.language or "").lower()
        ex_lang = a.language or "en"

        # Headline content keywords — UNIGRAMS only (single content words), casefolded
        # so an UPPER-case acronym aligns with its lower-case body form (WHO -> who).
        # N-grams are dropped from both sides: a title bigram rarely appears verbatim
        # among the body's top terms even on-topic, which would inflate d_lex (noise).
        head = {
            t.normalized.casefold()
            for t in ext.extract(title, language=ex_lang)
            if " " not in t.normalized
        }
        if len(head) < min_headline_terms:
            continue  # too thin to mismatch meaningfully — stay silent

        # The body's TOP unigram keywords (the salient single words), from its lead.
        body_terms = [
            t
            for t in ext.extract(body[:body_max_chars], language=ex_lang)
            if " " not in t.normalized
        ][:top_body_terms]
        b_top = {t.normalized.casefold() for t in body_terms}
        overlap = len(head & b_top)
        d_lex = round(1.0 - overlap / len(head), 3)
        absent = sorted(head - b_top)

        # Sentiment gap — English only (VADER); None elsewhere, never a fake neutral.
        s_gap: float | None = None
        if lang == "en":
            ts, _ = score_article(title, "en")
            bs, _ = score_article(body[:body_max_chars], "en")
            if ts is not None and bs is not None:
                s_gap = round(abs(float(ts) - float(bs)), 3)

        if not (d_lex >= d_min or (s_gap is not None and s_gap >= sentiment_gap_min)):
            continue

        when = a.published_at or a.created_at
        items.append(
            {
                "article_id": a.id,
                "title": a.title,
                "source": sname or sdom or f"source-{a.source_id}",
                "url": a.url,
                "lang": lang or None,
                "lexical_div": d_lex,
                "sentiment_gap": s_gap,
                "headline_terms": sorted(head),
                "absent_terms": absent,
                "when": when.date().isoformat() if when else None,
            }
        )

    # Precision-biased ordering: the strongest divergence first.
    items.sort(key=lambda x: (-(x["lexical_div"] or 0.0), -(x["sentiment_gap"] or 0.0)))
    items = items[:max_items]

    return {
        "items": items,
        "count": len(items),
        "recent_days": recent_days,
        "d_min": d_min,
        "sentiment_gap_min": sentiment_gap_min,
        "method": (
            "Per recent article (last {r} days, up to {rl} scanned): lexical divergence "
            "d_lex = 1 - |H ∩ B_top| / |H| of the headline's content keywords H vs the "
            "body's top {tb} keywords B_top (same extractor, language-agnostic), and, for "
            "English only, the headline-vs-body VADER sentiment gap. Fires when |H| >= {mh} "
            "AND (d_lex >= {dm} OR sentiment_gap >= {sg}). Body capped at {bc} chars. Real "
            "ratios, not a score.".format(
                r=recent_days,
                rl=recent_limit,
                tb=top_body_terms,
                mh=min_headline_terms,
                dm=d_min,
                sg=sentiment_gap_min,
                bc=body_max_chars,
            )
        ),
        "caveat": HEADLINE_BODY_CAVEAT,
    }
