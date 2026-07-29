"""
Framing comparison: how do different outlets cover the same event?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

For a given topic/event (a set of articles already selected by search), this lines
up, per source, honest *framing signals*:

  * tone -- the real VADER compound sentiment of the coverage (-1..1),
  * emphasis -- the terms each outlet leans on most,
  * coverage -- how many pieces, with linked headlines as evidence.

These are SIGNALS, not a verdict. The function never emits a "bias score" or
labels an outlet biased; it surfaces measurable differences a journalist can
inspect and attribute. Every number comes from a real method (VADER / term
frequency), and every claim links back to a source article.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.services.keyword_extractor import KeywordExtractor

_analyzer = SentimentIntensityAnalyzer()
_extractor = KeywordExtractor()

_CAVEAT = (
    "These are measurable framing SIGNALS (tone via VADER sentiment; emphasised "
    "terms via frequency), not a judgement that any outlet is biased. VADER is an "
    "ENGLISH lexicon, so tone is measured ONLY for English articles: an outlet with "
    "no English coverage here reports NO tone at all. That is an honest gap, never a "
    "'neutral' -- an unreadable language scores 0.0 on an English lexicon, which is "
    "the absence of a measurement, not a measurement of absence. Each outlet states "
    "how many of its articles the lexicon could actually read. Read the linked "
    "articles and attribute for yourself."
)

# VADER is an ENGLISH lexicon. Text it cannot read yields compound 0.0 -- indistinguishable
# from a genuinely neutral English sentence -- so scoring a non-English article publishes a
# FABRICATED "measured neutral" (verified 2026-07-29: fr/ru/zh news bodies all score exactly
# 0.0). Same rail, same reason, as src/analytics/sentiment.py:55, which refuses this by
# design. NOTE for anyone re-reading the old code: the `if tones else 0.0` this replaced was
# unreachable (the loop already `continue`s on an empty article list) -- the live fabrication
# was always the ungated scoring, not the empty-set branch.
_TONE_LANGUAGE = "en"


def _scorable(language: str | None) -> bool:
    """Only English is measurable by VADER. Unknown language is a GAP, not a licence."""
    return (language or "").strip().lower() == _TONE_LANGUAGE


def _tone_label(compound: float | None) -> str | None:
    """positive / negative / neutral -- or ``None`` when nothing was measured.

    "neutral" means MEASURED and near zero. An absent measurement returns ``None`` and is
    never labelled: that relabelling is precisely the fabrication this module used to ship.
    """
    if compound is None:
        return None
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


@dataclass
class SourceFraming:
    source: str
    article_count: int
    # mean VADER compound over this source's ENGLISH articles; None = nothing measurable
    avg_tone: float | None
    tone_label: str | None
    top_terms: list[str]
    tone_articles: int = 0  # the DENOMINATOR of avg_tone -- articles VADER could read
    tone_unmeasured: int = 0  # articles skipped: VADER cannot read their language
    headlines: list[dict] = field(default_factory=list)  # {title, url, published_at}

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "article_count": self.article_count,
            "avg_tone": round(self.avg_tone, 4) if self.avg_tone is not None else None,
            "tone_label": self.tone_label,
            # n travels with the number, always: "tone over 2 of this outlet's 7 pieces".
            "tone_articles": self.tone_articles,
            "tone_unmeasured": self.tone_unmeasured,
            "top_terms": self.top_terms,
            "headlines": self.headlines,
        }


def compare_framing(articles_by_source: dict[str, list[dict]], *, top_terms: int = 8) -> dict:
    """Compare framing across sources.

    ``articles_by_source`` maps a source name to a list of article dicts, each with
    keys: ``title``, ``content``, ``url``, ``published_at`` (ISO str or None) and
    ``language`` (ISO code or None). ``language`` is LOAD-BEARING: tone is computed only
    for English articles, and an article that arrives without one is treated as
    unmeasurable -- the honest default, since guessing English would resurrect the
    fabricated neutral this gate removes.
    """
    per_source: list[SourceFraming] = []
    for source, articles in sorted(articles_by_source.items()):
        if not articles:
            continue
        # LANGUAGE-GATED: only English articles are scored. The rest are COUNTED as
        # unmeasured -- never scored as 0.0 and never averaged in as a pseudo-neutral.
        tones = [
            _analyzer.polarity_scores(a.get("content") or a.get("title") or "")["compound"]
            for a in articles
            if _scorable(a.get("language"))
        ]
        avg = (sum(tones) / len(tones)) if tones else None
        combined = " ".join((a.get("content") or "") for a in articles)
        terms = [w for w, _ in _extractor.get_top_keywords(combined, top_n=top_terms)]
        headlines = [
            {"title": a.get("title"), "url": a.get("url"), "published_at": a.get("published_at")}
            for a in articles[:5]
        ]
        per_source.append(
            SourceFraming(
                source=source,
                article_count=len(articles),
                avg_tone=avg,
                tone_label=_tone_label(avg),
                top_terms=terms,
                tone_articles=len(tones),
                tone_unmeasured=len(articles) - len(tones),
                headlines=headlines,
            )
        )

    total = sum(s.article_count for s in per_source)
    measured = sum(s.tone_articles for s in per_source)
    # Terms that appear for one source but not the (combined) others = distinctive emphasis.
    all_terms = [t for s in per_source for t in s.top_terms]
    return {
        "sources_compared": len(per_source),
        "total_articles": total,
        # The tone gap, stated at the top level so a mostly-non-English comparison cannot
        # look fully measured: emphasis/volume cover every article, tone covers only these.
        "tone_measured_articles": measured,
        "tone_unmeasured_articles": total - measured,
        "caveat": _CAVEAT,
        "framing": [s.to_dict() for s in per_source],
        "shared_terms": sorted({t for t in all_terms if all_terms.count(t) > 1}),
    }
