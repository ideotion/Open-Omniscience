"""Keyword-growth (vocabulary) curve — how fast new keywords appear per word added.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bounded, read-only diagnostic answering the maintainer's question (2026-06-24,
at 59,646 articles / 909,463 keywords): plot *cumulative distinct keywords* against
*cumulative words (token occurrences) added*, and report the local growth rate.

The SHAPE is the payoff. By Heaps' law a healthy vocabulary grows sub-linearly —
``V ~ K * N^beta`` with ``beta`` well under 1 — because new articles mostly reuse
words already seen, so the curve BENDS OVER (saturates). A junk-dominated corpus
(markup tokens, code/underscore identifiers, un-segmented scripts, function words in
not-yet-managed languages) keeps minting brand-new keywords for every article, so the
curve stays nearly LINEAR (``beta`` ~ 1). The "new keywords per 1,000 words" rate at
the START versus the END of the corpus says directly whether the minting is slowing.

DECRYPT-FREE BY CONSTRUCTION: every figure comes from ``keyword_mentions`` alone via
the denormalised ``observed_on`` date (and the ``ix_mention_date_keyword`` covering
index) — it NEVER joins to ``articles``, so it does not drag encrypted article pages
through the SQLCipher codec (the standing perf-trap rule). Counts only, NO score.

HONEST FRAMING (carried in the payload ``caveat``):
  * The accumulation order is by article DATE (``observed_on``), a proxy for collection
    order — the scrape timestamp is not stored on a mention.
  * "Words" = keyword token-occurrences (``SUM(count)``), i.e. content words after the
    stoplist — a faithful proxy for words added, not the raw word count.
  * A multilingual corpus legitimately carries a larger vocabulary (each language its
    own words), so a higher ``beta`` is expected here than for a single-language corpus.
  * Mentions with no ``observed_on`` are reported, never silently dropped.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Cap the number of plotted points so the payload stays small regardless of how many
# distinct article dates the corpus spans (the curve is sampled at even token strides).
_MAX_POINTS = 120


def _fit_heaps(tokens: list[int], vocab: list[int]) -> dict[str, Any]:
    """Least-squares fit of log(V) = log(K) + beta*log(N) over the cumulative points
    where both N (tokens) and V (vocab) are > 0. Returns beta, K and r^2 (an honesty
    measure of how Heaps-like the corpus actually is). Pure Python — no numpy needed."""
    xs: list[float] = []
    ys: list[float] = []
    for n, v in zip(tokens, vocab, strict=True):
        if n > 0 and v > 0:
            xs.append(math.log(n))
            ys.append(math.log(v))
    if len(xs) < 3:
        return {"beta": None, "k": None, "r2": None, "n_points": len(xs)}
    m = len(xs)
    mx = sum(xs) / m
    my = sum(ys) / m
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0:
        return {"beta": None, "k": None, "r2": None, "n_points": m}
    beta = sxy / sxx
    intercept = my - beta * mx
    # r^2 of the log-log fit
    syy = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + beta * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    r2 = (1.0 - ss_res / syy) if syy > 0 else None
    return {
        "beta": round(beta, 4),
        "k": round(math.exp(intercept), 4),
        "r2": (round(r2, 4) if r2 is not None else None),
        "n_points": m,
    }


def _rate_per_1k(d_vocab: int, d_tokens: int) -> float | None:
    """New keywords per 1,000 words over a slice (None when the slice has no words)."""
    if d_tokens <= 0:
        return None
    return round(1000.0 * d_vocab / d_tokens, 3)


def keyword_growth_curve(session: Session) -> dict[str, Any]:
    """Build the vocabulary-growth curve from ``keyword_mentions`` (decrypt-free).

    Returns a JSON-able dict: a cumulative ``series`` of {date, tokens, keywords,
    articles}, the Heaps fit, the start-vs-end minting rate, totals, and the honesty
    envelope. NO score.
    """
    # new DISTINCT keywords introduced on each date = keywords whose earliest mention
    # falls on that date. (MIN(observed_on) per keyword, then grouped by that date.)
    new_kw_rows = session.execute(
        text(
            "SELECT first_date AS d, COUNT(*) AS new_kw FROM ("
            "  SELECT keyword_id, MIN(observed_on) AS first_date"
            "  FROM keyword_mentions WHERE observed_on IS NOT NULL"
            "  GROUP BY keyword_id"
            ") GROUP BY first_date"
        )
    ).all()
    # words (token occurrences) and distinct articles per date
    per_date_rows = session.execute(
        text(
            "SELECT observed_on AS d, SUM(count) AS toks, COUNT(DISTINCT article_id) AS arts"
            " FROM keyword_mentions WHERE observed_on IS NOT NULL GROUP BY observed_on"
        )
    ).all()
    undated = session.execute(
        text("SELECT COUNT(*) FROM keyword_mentions WHERE observed_on IS NULL")
    ).scalar() or 0

    new_kw_by_date: dict[str, int] = {str(r.d): int(r.new_kw) for r in new_kw_rows}
    toks_by_date: dict[str, int] = {}
    arts_by_date: dict[str, int] = {}
    for r in per_date_rows:
        toks_by_date[str(r.d)] = int(r.toks or 0)
        arts_by_date[str(r.d)] = int(r.arts or 0)

    dates = sorted(set(new_kw_by_date) | set(toks_by_date))
    full: list[dict[str, Any]] = []  # each entry holds a str "date" + int counts
    cum_kw = cum_tok = cum_art = 0
    for d in dates:
        cum_kw += new_kw_by_date.get(d, 0)
        cum_tok += toks_by_date.get(d, 0)
        cum_art += arts_by_date.get(d, 0)
        full.append({"date": d, "keywords": cum_kw, "tokens": cum_tok, "articles": cum_art})

    total_keywords = cum_kw
    total_tokens = cum_tok
    total_articles = cum_art

    # Down-sample to <= _MAX_POINTS by even strides over the full date-ordered curve
    # (endpoints always kept). The cumulative values are exact at each kept point.
    series = full
    if len(full) > _MAX_POINTS:
        step = len(full) / _MAX_POINTS
        idx = sorted({int(i * step) for i in range(_MAX_POINTS)} | {len(full) - 1})
        series = [full[i] for i in idx]

    heaps = _fit_heaps([p["tokens"] for p in full], [p["keywords"] for p in full])

    # Minting rate at the start vs the end: new keywords per 1,000 words over the first
    # decile of WORDS versus the last decile. A big drop = the vocabulary is saturating
    # (healthy); little change = still minting (junk-heavy).
    start_rate = end_rate = None
    if total_tokens > 0 and len(full) >= 2:
        lo_cut = total_tokens * 0.10
        hi_cut = total_tokens * 0.90
        lo = next((p for p in full if p["tokens"] >= lo_cut), full[-1])
        hi = next((p for p in full if p["tokens"] >= hi_cut), full[-1])
        start_rate = _rate_per_1k(lo["keywords"], lo["tokens"])
        end_rate = _rate_per_1k(
            total_keywords - hi["keywords"], total_tokens - hi["tokens"]
        )

    return {
        "kind": "keyword-growth-curve",
        "schema": "oo-keyword-growth-1",
        "totals": {
            "keywords": total_keywords,
            "tokens": total_tokens,
            "articles": total_articles,
            "undated_mentions": int(undated),
        },
        "series": series,
        "points_full": len(full),
        "points_returned": len(series),
        "heaps": heaps,
        "minting_rate_per_1000_words": {
            "start": start_rate,
            "end": end_rate,
            "interpretation": (
                "new keywords per 1,000 words; a large drop start->end means the "
                "vocabulary is saturating (healthy); little change means new keywords "
                "are still minted for nearly every word added (junk-heavy)"
            ),
        },
        "method": (
            "cumulative distinct keywords vs cumulative words (token occurrences), "
            "ordered by article date (observed_on); read from keyword_mentions only "
            "(no article decrypt); Heaps fit log(V)=log(K)+beta*log(N)"
        ),
        "caveat": (
            "Counts only, never a score. Ordered by article date (a proxy for "
            "collection order — scrape time is not stored per mention). 'Words' = "
            "content-word occurrences after the stoplist. A multilingual corpus "
            "legitimately carries a larger vocabulary, so a higher beta is expected. "
            "beta near 1 (a near-straight line) means new keywords keep appearing for "
            "almost every word added — the signature of markup/code/unsegmented junk; "
            "beta well under 1 (a curve that bends over) means the vocabulary is "
            "saturating. " + (f"{int(undated)} mentions have no date and are excluded."
                              if undated else "")
        ),
    }
