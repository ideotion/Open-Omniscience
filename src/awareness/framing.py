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
    "terms via frequency), not a judgement that any outlet is biased. Read the "
    "linked articles and attribute for yourself."
)


def _tone_label(compound: float) -> str:
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


@dataclass
class SourceFraming:
    source: str
    article_count: int
    avg_tone: float  # mean VADER compound across the source's coverage
    tone_label: str
    top_terms: list[str]
    headlines: list[dict] = field(default_factory=list)  # {title, url, published_at}

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "article_count": self.article_count,
            "avg_tone": round(self.avg_tone, 4),
            "tone_label": self.tone_label,
            "top_terms": self.top_terms,
            "headlines": self.headlines,
        }


def compare_framing(articles_by_source: dict[str, list[dict]], *, top_terms: int = 8) -> dict:
    """Compare framing across sources.

    ``articles_by_source`` maps a source name to a list of article dicts, each with
    keys: ``title``, ``content``, ``url``, ``published_at`` (ISO str or None).
    """
    per_source: list[SourceFraming] = []
    for source, articles in sorted(articles_by_source.items()):
        if not articles:
            continue
        tones = [
            _analyzer.polarity_scores(a.get("content") or a.get("title") or "")["compound"]
            for a in articles
        ]
        avg = sum(tones) / len(tones) if tones else 0.0
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
                headlines=headlines,
            )
        )

    total = sum(s.article_count for s in per_source)
    # Terms that appear for one source but not the (combined) others = distinctive emphasis.
    all_terms = [t for s in per_source for t in s.top_terms]
    return {
        "sources_compared": len(per_source),
        "total_articles": total,
        "caveat": _CAVEAT,
        "framing": [s.to_dict() for s in per_source],
        "shared_terms": sorted({t for t in all_terms if all_terms.count(t) > 1}),
    }
