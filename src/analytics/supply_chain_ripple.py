"""Supply-chain ripple — commodity / keyword coverage CO-MOVEMENT (never causation).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a SHAPE, never a cause: when a tracked commodity's daily COVERAGE rises and falls
together with another topic's daily coverage across your corpus, that co-movement is a
prompt to investigate a possible supply-chain / market linkage — NEVER proof one drives
the other. Two topics can co-move because both respond to a common driver, or by chance.

Honesty by construction:
  * CO-OCCURRENCE, NEVER CAUSATION — the verbatim non-negotiable rides every result;
  * the measure is a Pearson correlation of daily article-COUNT series (coverage volume),
    with a Fisher-z significance test computed natively (no scipy needed) — an
    APPROXIMATION that does NOT model day-to-day autocorrelation, stated in the caveat;
  * the WHOLE FAMILY of (commodity, topic) pairs is corrected with Benjamini-Hochberg FDR
    (:mod:`src.stats.fdr`) so screening many pairs cannot manufacture a co-movement;
  * a pair is surfaced only if it survives FDR AND the correlation is a real positive
    co-movement (r >= r_min); components are reported (r, p, adjusted q, n, counts) — no
    composite score.

Efficient by construction: reads ONLY the denormalised ``keyword_mentions`` (keyword_id +
observed_on + article_id) — never the article-content decrypt. Commodities are the ones
the operator already tracks (market rules / price series), so the vocabulary is honest,
not a fabricated seed list.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import distinct, func

from src.database.models import (
    CommodityPrice,
    Keyword,
    KeywordMention,
    MarketExtractionRule,
)

_LOG = logging.getLogger(__name__)

_IN_CHUNK = 600

SUPPLY_CHAIN_CAVEAT = (
    "Co-occurrence in your coverage, NEVER causation. Two topics whose daily coverage "
    "rises and falls together may both respond to a common driver, or line up by chance — "
    "a co-movement is a prompt to investigate a possible supply-chain or market linkage, "
    "never proof one moves the other. The measure is a correlation of each term's SHARE of "
    "that day's total corpus activity (not raw counts, and not prices) — so a busier "
    "scraping day cannot make two unrelated terms look co-moving — and its significance "
    "test is an approximation that does not model day-to-day autocorrelation, so treat "
    "borderline results with care. Independence is guarded: both topics must be carried by "
    "MULTIPLE DISTINCT SOURCES over the window, so one outlet's editorial rhythm cannot "
    "manufacture a co-movement. Screening many pairs is corrected with false-discovery-rate "
    "control. Counts + statistics only, no score."
)

SUPPLY_CHAIN_METHOD = (
    "For each tracked commodity keyword (resolved by an EXACT match on its label or symbol "
    "only — never a substring/homograph guess) x each frequent topic keyword, a Pearson "
    "correlation of their daily SHARE-of-corpus-activity series over the window (each "
    "term's daily count divided by that day's total mentioned-article count, guarding "
    "against a shared-volume confound), with a Fisher-z two-sided p-value computed "
    "natively. Both terms must be covered by >= min_sources_per_term DISTINCT sources (so "
    "a single chatty source cannot manufacture a co-movement). The whole family of pairs is "
    "corrected with Benjamini-Hochberg FDR; a pair is surfaced only if it survives at the "
    "FDR level AND r >= r_min (a real positive co-movement). Reads the denormalised "
    "keyword_mentions only (no content decrypt). Counts + statistics only, no score."
)


def _phi(z: float) -> float:
    """Standard-normal CDF via ``math.erf`` (no scipy)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length series, or None if either has no variance."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    return sxy / math.sqrt(sxx * syy)


def _fisher_pvalue(r: float, n: int) -> float | None:
    """Two-sided p-value for Pearson r via the Fisher z-transformation (native).

    z = atanh(r) * sqrt(n - 3) ~ N(0, 1) under H0 (rho = 0). Requires n >= 5. Clamps |r|
    just below 1 so a perfect correlation yields a finite, tiny p rather than infinity.
    """
    if n < 5 or abs(r) >= 1.0:
        r = max(min(r, 0.999999), -0.999999)
    if n < 5:
        return None
    stat = math.atanh(r) * math.sqrt(n - 3)
    return max(0.0, min(1.0, 2.0 * (1.0 - _phi(abs(stat)))))


def _exact_keyword_id(session, term: str | None) -> int | None:
    """EXACT normalized-term match only -- never the fuzzy ``LIKE %term%`` fallback
    :func:`src.analytics.queries.resolve_keyword` uses for other, human-driven callers
    (S2.1, row 13a). A commodity label/symbol that has no keyword under its OWN exact
    normalized form must resolve to NOTHING, never an unrelated keyword that merely
    CONTAINS it as a substring (the "significant words of the label" homograph vector —
    a commodity "Lead" silently matching the unrelated common word/verb "lead")."""
    from src.analytics.queries import _normalize

    norm = _normalize(term or "")
    if not norm:
        return None
    row = session.query(Keyword.id).filter_by(normalized_term=norm).first()
    return int(row[0]) if row else None


def _commodity_keywords(session) -> dict[int, str]:
    """Resolve the operator's TRACKED commodities to keyword ids -> display label.

    The vocabulary is the commodities the operator already configured (market extraction
    rules) plus any symbol with a price series — honest, never a fabricated seed list. Each
    is resolved to a stored keyword by an EXACT match on its label OR its exact symbol only
    (S2.1) — never a substring/"significant words" heuristic, which is a homograph vector
    (a commodity labelled "Lead" silently matching the unrelated common word "lead"). A
    commodity whose exact label AND exact symbol both fail to resolve contributes nothing —
    an honest gap, never an invented match.
    """
    candidates: list[tuple[str, str]] = []  # (label, probe)
    for symbol, label in session.query(MarketExtractionRule.symbol, MarketExtractionRule.label).all():
        candidates.append((label or symbol, label or symbol))
        if symbol:
            candidates.append((label or symbol, symbol))
    for (symbol,) in session.query(CommodityPrice.symbol).distinct().all():
        if symbol:
            rule = session.query(MarketExtractionRule).filter_by(symbol=symbol).first()
            label = rule.label if rule and rule.label else symbol
            candidates.append((label, label))
            candidates.append((label, symbol))

    out: dict[int, str] = {}
    for label, probe in candidates:
        kid = _exact_keyword_id(session, probe)
        if kid is not None:
            out.setdefault(kid, label or probe)
    return out


def _daily_series(session, kw_ids: list[int], cutoff: date, hi: date) -> dict[int, dict[date, int]]:
    """Per-keyword daily distinct-article counts over the window (denormalised only)."""
    series: dict[int, dict[date, int]] = defaultdict(dict)
    for i in range(0, len(kw_ids), _IN_CHUNK):
        chunk = kw_ids[i : i + _IN_CHUNK]
        for kid, on, cnt in (
            session.query(
                KeywordMention.keyword_id,
                KeywordMention.observed_on,
                func.count(distinct(KeywordMention.article_id)),
            )
            .filter(
                KeywordMention.keyword_id.in_(chunk),
                KeywordMention.observed_on >= cutoff,
                KeywordMention.observed_on < hi,
                KeywordMention.observed_on.isnot(None),
            )
            .group_by(KeywordMention.keyword_id, KeywordMention.observed_on)
            .all()
        ):
            series[int(kid)][on] = int(cnt or 0)
    return series


def _daily_totals(session, cutoff: date, hi: date) -> dict[date, int]:
    """Total DISTINCT articles carrying ANY keyword mention, per day, over the window --
    the volume-confound denominator (S2.2, row 13b). Correlating raw daily COUNTS lets
    any two terms that merely both track total collection volume "co-move" (a day with
    more scraping produces more mentions of everything); dividing by this total turns
    each series into a SHARE of that day's activity, so a pair that only tracks shared
    volume collapses to a constant (zero variance, no correlation), while a pair that
    genuinely moves together independent of volume still does."""
    out: dict[date, int] = {}
    for on, cnt in (
        session.query(
            KeywordMention.observed_on, func.count(distinct(KeywordMention.article_id))
        )
        .filter(
            KeywordMention.observed_on >= cutoff,
            KeywordMention.observed_on < hi,
            KeywordMention.observed_on.isnot(None),
        )
        .group_by(KeywordMention.observed_on)
        .all()
    ):
        out[on] = int(cnt or 0)
    return out


def _source_counts(session, kw_ids: list[int], cutoff: date, hi: date) -> dict[int, int]:
    """Per-keyword count of DISTINCT sources over the window (denormalised source_id only)."""
    out: dict[int, int] = {}
    for i in range(0, len(kw_ids), _IN_CHUNK):
        chunk = kw_ids[i : i + _IN_CHUNK]
        for kid, n in (
            session.query(
                KeywordMention.keyword_id, func.count(distinct(KeywordMention.source_id))
            )
            .filter(
                KeywordMention.keyword_id.in_(chunk),
                KeywordMention.observed_on >= cutoff,
                KeywordMention.observed_on < hi,
                KeywordMention.source_id.isnot(None),
            )
            .group_by(KeywordMention.keyword_id)
            .all()
        ):
            out[int(kid)] = int(n or 0)
    return out


def find_supply_chain_ripples(
    session,
    *,
    window_days: int = 90,
    min_days: int = 21,
    min_nonzero_days: int = 6,
    min_sources_per_term: int = 3,
    r_min: float = 0.5,
    fdr_q: float = 0.05,
    max_candidates: int = 250,
    max_articles_per_item: int = 300,
    max_items: int = 8,
    today: date | None = None,
) -> dict:
    """Surface commodity/keyword coverage co-movements (FDR-corrected). See module docstring."""
    from src.analytics.queries import _hidden_predicate
    from src.stats.fdr import benjamini_hochberg

    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=window_days)
    hi = today + timedelta(days=1)
    axis = [cutoff + timedelta(days=i) for i in range((today - cutoff).days + 1)]
    n_days = len(axis)

    def _empty(note: str) -> dict:
        return {"items": [], "count": 0, "window_days": window_days, "r_min": r_min,
                "fdr_q": fdr_q, "tests": 0, "note": note,
                "method": SUPPLY_CHAIN_METHOD, "caveat": SUPPLY_CHAIN_CAVEAT}

    if n_days < min_days:
        return _empty("window shorter than min_days")

    commodities = _commodity_keywords(session)
    if not commodities:
        return _empty("no tracked commodity resolves to a keyword")

    # Frequent candidate topics in the window (denormalised distinct-article counts).
    cand_rows = (
        session.query(
            KeywordMention.keyword_id,
            func.count(distinct(KeywordMention.article_id)).label("n"),
        )
        .filter(
            KeywordMention.observed_on >= cutoff,
            KeywordMention.observed_on < hi,
            KeywordMention.observed_on.isnot(None),
        )
        .group_by(KeywordMention.keyword_id)
        .order_by(func.count(distinct(KeywordMention.article_id)).desc())
        .limit(max_candidates)
        .all()
    )
    is_hidden = _hidden_predicate()
    all_ids = sorted(set(commodities) | {int(kid) for kid, _ in cand_rows})
    kw_terms: dict[int, str] = {}
    for i in range(0, len(all_ids), _IN_CHUNK):
        chunk = all_ids[i : i + _IN_CHUNK]
        for kid, norm in session.query(Keyword.id, Keyword.normalized_term).filter(Keyword.id.in_(chunk)).all():
            kw_terms[int(kid)] = norm
    candidate_ids = [
        int(kid) for kid, _ in cand_rows if not is_hidden(kw_terms.get(int(kid)))
    ]
    if not candidate_ids:
        return _empty("no frequent candidate topic in the window")

    series_raw = _daily_series(session, all_ids, cutoff, hi)
    daily_totals = _daily_totals(session, cutoff, hi)
    series: dict[int, list[float]] = {}
    nonzero: dict[int, int] = {}
    for kid in all_ids:
        by_day = series_raw.get(kid, {})
        raw_vec = [float(by_day.get(d, 0)) for d in axis]
        nonzero[kid] = sum(1 for v in raw_vec if v > 0)
        # S2.2 (row 13b): correlate SHARES of the day's total corpus activity, not raw
        # counts -- two terms that both merely track total collection volume collapse
        # to a constant share (no variance, no spurious co-movement); a genuine
        # co-movement, independent of volume, still shows up.
        series[kid] = [
            v / daily_totals[d] if daily_totals.get(d, 0) > 0 else 0.0
            for d, v in zip(axis, raw_vec, strict=True)
        ]
    # Distinct-source breadth per term (the independence gate): a co-movement carried by
    # only one outlet is that outlet's editorial rhythm, not a corpus-wide pattern.
    src_counts = _source_counts(session, all_ids, cutoff, hi)

    def _thin(kid: int) -> bool:
        return nonzero.get(kid, 0) < min_nonzero_days or src_counts.get(kid, 0) < min_sources_per_term

    # The test family: every (commodity, candidate) pair, both with enough non-zero days
    # AND enough distinct sources.
    tests: list[dict] = []
    pvals: list[float] = []
    seen: set[frozenset[int]] = set()
    for cid in commodities:
        if _thin(cid):
            continue
        for kid in candidate_ids:
            if kid == cid:
                continue
            pair = frozenset((cid, kid))
            if pair in seen:
                continue
            if _thin(kid):
                continue
            r = _pearson(series[cid], series[kid])
            if r is None:
                continue
            p = _fisher_pvalue(r, n_days)
            if p is None:
                continue
            seen.add(pair)
            tests.append({"cid": cid, "kid": kid, "r": r, "p": p,
                          "nz_c": nonzero[cid], "nz_k": nonzero[kid]})
            pvals.append(p)

    if not tests:
        return _empty("no comparable commodity/topic pair")

    fdr = benjamini_hochberg(pvals, q=fdr_q)
    survivors = set(fdr.rejected)
    hits = [
        (idx, t) for idx, t in enumerate(tests)
        if idx in survivors and t["r"] >= r_min  # survive FDR AND a real positive co-movement
    ]
    hits.sort(key=lambda it: -it[1]["r"])
    hits = hits[:max_items]

    items: list[dict] = []
    for idx, t in hits:
        cid, kid = t["cid"], t["kid"]
        article_ids = _pair_article_ids(session, cid, kid, cutoff, hi, max_articles_per_item)
        items.append(
            {
                "commodity": commodities[cid],
                "commodity_keyword_id": cid,
                "keyword": kw_terms.get(kid, str(kid)),
                "keyword_id": kid,
                "correlation": round(t["r"], 3),
                "p_value": round(t["p"], 5),
                "fdr_qvalue": round(fdr.adjusted[idx], 5),
                "n_days": n_days,
                "nonzero_days_commodity": t["nz_c"],
                "nonzero_days_keyword": t["nz_k"],
                "distinct_sources_commodity": src_counts.get(cid, 0),
                "distinct_sources_keyword": src_counts.get(kid, 0),
                "article_ids": article_ids,
                "n_articles": len(article_ids),
            }
        )

    return {
        "items": items,
        "count": len(items),
        "window_days": window_days,
        "r_min": r_min,
        "fdr_q": fdr_q,
        "tests": len(tests),
        "survivors": len(survivors),
        "commodities_resolved": len(commodities),
        "method": SUPPLY_CHAIN_METHOD,
        "caveat": SUPPLY_CHAIN_CAVEAT,
    }


def _pair_article_ids(session, cid: int, kid: int, cutoff, hi, cap: int) -> list[int]:
    """The pair's evidence corpus: articles mentioning BOTH terms in the window
    (the tightest co-occurrence set), falling back to the commodity's own coverage
    when the two never share an article. Bounded and denormalised (no content decrypt)."""

    def _ids(k):
        return {
            int(r[0])
            for r in session.query(KeywordMention.article_id)
            .filter(
                KeywordMention.keyword_id == k,
                KeywordMention.observed_on >= cutoff,
                KeywordMention.observed_on < hi,
            )
            .distinct()
        }

    c_ids = _ids(cid)
    k_ids = _ids(kid)
    both = c_ids & k_ids
    chosen = both if both else c_ids
    return sorted(chosen)[:cap]
