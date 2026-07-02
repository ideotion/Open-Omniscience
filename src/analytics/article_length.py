"""Article-length diagnostic (Home "Latest in your corpus" slice S0).

The maintainer wants a Home "recently collected" strip that filters out very short
click-bait on TWO transparent gates — ``word_count`` and the number of in-article
cited sources (outbound external links) — with per-content-type defaults. But no
existing export carries the per-article distribution of either, so honest default
thresholds cannot be set (the only anchor is ~190 content-words/article average).

This is that missing diagnostic: the DISTRIBUTION of article length + cited-source
count over the corpus, broken down per content type and per language, so real
thresholds can be chosen from evidence rather than guessed. Read-only, counts
only, NO score (a long article is not "good", a well-linked one is not "true").

Two honesty notes baked in:
  * SCRIPT-AWARE: ``word_count = len(text.split())`` is meaningless for unsegmented
    languages (zh/ja/th) — a long Chinese article looks like a handful of "words".
    Those languages are FLAGGED so a word-gate is never applied to them blindly.
  * The cited-source count is an APPROXIMATION (outbound external links, gameable by
    link-stuffing, content-type-dependent) — a tunable filter, never a truth signal.

Perf: the global word_count distribution reads the covering ``idx_article_word_count``
(index-only, no article decrypt); the per-language / per-type breakdown needs
``language`` + the source's type, so it scans the article rows once (a diagnostic
the operator runs occasionally, like the keyword export). The cited-source counts
come from ``article_links`` (no article content) — cheap.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics.managed import UNSEGMENTED
from src.database.models import Article, ArticleLink, Source

# Human-readable, fixed buckets (a histogram the operator can eyeball to pick a
# gate). Each is (label, lower_inclusive, upper_inclusive_or_None).
_WORD_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-99", 0, 99), ("100-299", 100, 299), ("300-599", 300, 599),
    ("600-999", 600, 999), ("1000-1999", 1000, 1999), ("2000+", 2000, None),
)
_LINK_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3", 3, 3),
    ("4-5", 4, 5), ("6-9", 6, 9), ("10+", 10, None),
)


def _percentile(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile on a pre-sorted list (deterministic, no numpy)."""
    if not sorted_vals:
        return 0
    idx = int(round(q / 100.0 * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(idx, len(sorted_vals) - 1))]


def _histogram(values: list[int], buckets: tuple[tuple[str, int, int | None], ...]) -> dict[str, int]:
    out = {label: 0 for label, _, _ in buckets}
    for v in values:
        for label, lo, hi in buckets:
            if v >= lo and (hi is None or v <= hi):
                out[label] += 1
                break
    return out


def summarize(values: list[int], buckets: tuple[tuple[str, int, int | None], ...]) -> dict:
    """Distribution of an integer list: n, min/max, mean, median, key percentiles,
    and a fixed-bucket histogram. Pure — the testable core. Never a score."""
    n = len(values)
    if n == 0:
        return {"n": 0, "min": None, "max": None, "mean": None, "median": None,
                "p10": None, "p25": None, "p75": None, "p90": None, "p95": None,
                "histogram": {label: 0 for label, _, _ in buckets}}
    sv = sorted(values)
    total = sum(sv)
    return {
        "n": n,
        "min": sv[0],
        "max": sv[-1],
        "mean": round(total / n, 1),
        "median": _percentile(sv, 50),
        "p10": _percentile(sv, 10),
        "p25": _percentile(sv, 25),
        "p75": _percentile(sv, 75),
        "p90": _percentile(sv, 90),
        "p95": _percentile(sv, 95),
        "histogram": _histogram(sv, buckets),
    }


def _words_summary(values: list[int]) -> dict:
    return summarize(values, _WORD_BUCKETS)


def article_length_report(session: Session) -> dict:
    """Corpus article-length + cited-source distributions, per content type and
    per language, so honest Home-filter defaults can be set from evidence.

    Counts only, NO score. Word counts for unsegmented languages carry a flag so a
    word-gate is never applied to them blindly.
    """
    # One pass over the article rows: word_count + language + source_id (the small
    # columns S0 needs). source_type lives on Source — resolved via a small map.
    source_type = {sid: (st or "news") for sid, st in session.query(Source.id, Source.source_type)}

    all_words: list[int] = []
    by_type: dict[str, list[int]] = {}
    by_lang: dict[str, list[int]] = {}
    scanned = 0
    with_word_count = 0
    for wc, lang, sid in session.query(Article.word_count, Article.language, Article.source_id):
        scanned += 1
        if wc is None:
            continue
        with_word_count += 1
        all_words.append(wc)
        stype = source_type.get(sid, "news")
        by_type.setdefault(stype, []).append(wc)
        base = (lang or "?").split("-", 1)[0].strip().lower() or "?"
        by_lang.setdefault(base, []).append(wc)

    # Cited-source (outbound external link) counts per article, from article_links
    # (no article content) — cheap. Articles with none don't appear in the group-by,
    # so the zeros are the rest of the corpus.
    link_counts: list[int] = []
    linked_articles = 0
    for _aid, c in (
        session.query(ArticleLink.article_id, func.count(ArticleLink.id))
        .filter(ArticleLink.link_type == "external")
        .group_by(ArticleLink.article_id)
    ):
        link_counts.append(int(c))
        linked_articles += 1
    zeros = max(0, scanned - linked_articles)
    link_counts.extend([0] * zeros)

    per_type = {
        stype: _words_summary(vals)
        for stype, vals in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    }
    per_language = {}
    for base, vals in sorted(by_lang.items(), key=lambda kv: -len(kv[1])):
        s = _words_summary(vals)
        s["unsegmented"] = base in UNSEGMENTED  # word_count is unreliable here
        per_language[base] = s

    return {
        "scanned": scanned,
        "with_word_count": with_word_count,
        "word_count": _words_summary(all_words),
        "word_count_by_content_type": per_type,
        "word_count_by_language": per_language,
        "cited_sources": summarize(link_counts, _LINK_BUCKETS),
        "unsegmented_languages": sorted(UNSEGMENTED),
        "method": (
            "word_count = len(text.split()) at ingest; cited sources = outbound "
            "external ArticleLink rows per article (articles with none counted as 0). "
            "Distributions over the whole corpus; percentiles are nearest-rank."
        ),
        "caveat": (
            "Counts only, never a score — a long article is not necessarily good, a "
            "well-linked one not necessarily true, a short one not necessarily "
            "click-bait. word_count is unreliable for unsegmented languages (zh/ja/th); "
            "the cited-source count is an approximation (gameable, content-type-"
            "dependent). Use these to set per-content-type thresholds, not to rank."
        ),
    }
