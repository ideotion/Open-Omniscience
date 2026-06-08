"""
The "now"-status card producers — Briefing v0.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each producer composes data that *already returns real numbers* (the Insights
analytics, the framing/tone signal, the honest commodity correlation, the wiki
flagging, the market-rule outcomes) plus the new pure ``concentration`` primitive.
No producer fabricates: when its inputs or optional ``[analysis]`` dependencies are
missing it returns ``[]`` and logs why (loud degradation), never a fake card.

Build order is deliberately *de-risked* (FUTURE_DEVELOPMENTS §4 "Build order"):
ship the cheap, honest cards first so the idea→draft loop is proven before the
harder "new" analysis (echo/synchrony, lineage, novelty) is attempted.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func

from src.analytics.queries import resolve_keyword
from src.briefing.card import Card
from src.database.models import (
    Article,
    CommodityPrice,
    KeywordMention,
    MarketExtractionRule,
    Source,
    WikiPage,
    WikiRevision,
)

_LOG = logging.getLogger(__name__)

# Bounds — the same discipline as the bounded crawler: never an unbounded scan.
_MAX_RISING = 5
_MAX_WIKI = 5
_MAX_SYMBOLS = 5
_FRAMING_ARTICLE_CAP = 40
_DIET_DAYS = 30
_STALE_DAYS = 7


def _articles_for_term(session, keyword_id: int, *, days: int, limit: int):
    """Recent ``(Article, source_name)`` rows mentioning a keyword, newest first."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        session.query(Article, Source.name)
        .join(KeywordMention, KeywordMention.article_id == Article.id)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(KeywordMention.keyword_id == keyword_id)
        .filter(KeywordMention.observed_on >= cutoff)
        .order_by(KeywordMention.observed_on.desc(), Article.id.desc())
        .limit(limit)
        .all()
    )
    return rows


def _evidence_from_articles(rows, *, limit: int = 4) -> list[dict]:
    out: list[dict] = []
    seen: set[int] = set()
    for article, source_name in rows:
        if article.id in seen:
            continue
        seen.add(article.id)
        out.append({
            "title": article.title,
            "url": article.url,
            "source": source_name,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "article_id": article.id,
        })
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
#  Rising now — trending keywords/entities (composes /api/insights/trending)
# --------------------------------------------------------------------------- #
def rising_now(session) -> list[Card]:
    from src.analytics import queries as q

    data = q.trending(session, limit=_MAX_RISING)
    cards: list[Card] = []
    for term in data.get("terms", []):
        kw = resolve_keyword(session, term["term"])
        rows = _articles_for_term(session, kw.id, days=14, limit=6) if kw else []
        cards.append(Card(
            type="rising",
            title=f"“{term['term']}” is rising",
            summary=(f"Mentions of “{term['term']}” are running ~{term['growth']}× the "
                     f"prior-period rate ({term['recent']} recent vs {term['prior']} before)."),
            bucket="rising",
            signal={"metric": "growth_ratio", "value": term["growth"],
                    "recent": term["recent"], "prior": term["prior"], "kind": term["kind"]},
            method=data.get("method", "recent volume vs prior-period rate (a ratio, not a significance test)"),
            caveat=("A rising count reflects your source set, not the world; a ratio is not a "
                    "significance test, and small samples are noisy."),
            evidence=_evidence_from_articles(rows),
            n=term["recent"],
            key=term["normalized"],
        ))
    return cards


# --------------------------------------------------------------------------- #
#  Framing split — same topic, divergent tone per source (needs [analysis])
# --------------------------------------------------------------------------- #
def framing_split(session) -> list[Card]:
    try:
        from src.analytics import queries as q
        from src.awareness.framing import compare_framing
    except ImportError:
        _LOG.info("framing_split skipped: the [analysis] extra (VADER) is not installed.")
        return []

    trending = q.trending(session, limit=3).get("terms", [])
    for term in trending:
        kw = resolve_keyword(session, term["term"])
        if kw is None:
            continue
        rows = _articles_for_term(session, kw.id, days=21, limit=_FRAMING_ARTICLE_CAP)
        by_source: dict[str, list[dict]] = {}
        for article, source_name in rows:
            if not source_name:
                continue
            by_source.setdefault(source_name, []).append({
                "title": article.title,
                "content": article.get_content(),
                "url": article.url,
                "published_at": article.published_at.isoformat() if article.published_at else None,
            })
        if len(by_source) < 2:
            continue
        result = compare_framing(by_source)
        framings = result.get("framing", [])
        labels = {f["tone_label"] for f in framings}
        # A split = at least one source reads positive and another negative on the
        # SAME topic. We surface the divergence; we never call either one biased.
        if not ({"positive", "negative"} <= labels):
            continue
        framings_sorted = sorted(framings, key=lambda f: f["avg_tone"])
        low, high = framings_sorted[0], framings_sorted[-1]
        evidence = []
        for f in (high, low):
            for hd in f.get("headlines", [])[:2]:
                evidence.append({"title": hd.get("title"), "url": hd.get("url"),
                                 "source": f["source"], "published_at": hd.get("published_at")})
        return [Card(
            type="framing_split",
            title=f"“{term['term']}”: outlets frame it differently",
            summary=(f"On “{term['term']}”, {high['source']} reads {high['tone_label']} "
                     f"(tone {high['avg_tone']:+.2f}) while {low['source']} reads "
                     f"{low['tone_label']} (tone {low['avg_tone']:+.2f})."),
            bucket="debunk",
            signal={"metric": "tone_spread", "value": round(high["avg_tone"] - low["avg_tone"], 4),
                    "high": {"source": high["source"], "tone": high["avg_tone"]},
                    "low": {"source": low["source"], "tone": low["avg_tone"]}},
            method="VADER compound sentiment of each outlet's coverage of the term",
            caveat=(result.get("caveat", "")
                    + " Tone is valence, not stance: negative tone may be alarm, grief OR "
                    "skepticism. This is a signal to read, never a label that an outlet is biased."),
            evidence=evidence,
            n=result.get("total_articles"),
            key=term["normalized"],
        )]
    return []


# --------------------------------------------------------------------------- #
#  Record reshaped — large/flagged Wikipedia edits (composes the wiki flagging)
# --------------------------------------------------------------------------- #
def record_reshaped(session) -> list[Card]:
    rows = (
        session.query(WikiRevision, WikiPage)
        .join(WikiPage, WikiPage.id == WikiRevision.page_id)
        .filter(WikiRevision.flagged.is_(True))
        .order_by(WikiRevision.timestamp.desc(), WikiRevision.id.desc())
        .limit(_MAX_WIKI)
        .all()
    )
    cards: list[Card] = []
    for rev, page in rows:
        reasons = (rev.flag_reasons or "").replace(",", ", ")
        url = f"https://{page.wiki}.wikipedia.org/wiki/{page.title.replace(' ', '_')}?diff={rev.revid}"
        cards.append(Card(
            type="record_reshaped",
            title=f"Wikipedia ({page.wiki}): “{page.title}” reshaped",
            summary=(f"A flagged edit changed “{page.title}” by {rev.delta_bytes:+} bytes"
                     + (f" — {reasons}." if reasons else ".")),
            bucket="watch",
            signal={"metric": "delta_bytes", "value": rev.delta_bytes,
                    "flag_reasons": (rev.flag_reasons or "").split(",") if rev.flag_reasons else [],
                    "editor_anon": bool(rev.editor_anon)},
            method="Honest large-edit flagging at ingest (size delta, revert/blank tags, anon/burst, optional ORES).",
            caveat=("A flag marks an edit worth a human look — size or pattern — not a judgement that "
                    "it is vandalism or revisionism. Open the diff and decide."),
            evidence=[{"title": f"{page.title} (diff {rev.revid})", "url": url,
                       "source": f"{page.wiki}.wikipedia.org",
                       "published_at": rev.timestamp.isoformat() if rev.timestamp else None}],
            n=1,
            key=f"{page.wiki}:{page.title}:{rev.revid}",
        ))
    return cards


# --------------------------------------------------------------------------- #
#  Price ↔ narrative — honest commodity correlation (needs [analysis] / scipy)
# --------------------------------------------------------------------------- #
def price_narrative(session) -> list[Card]:
    try:
        from src.commodity.correlation import correlate_price_with_news
    except ImportError:
        _LOG.info("price_narrative skipped: the [analysis] extra (scipy) is not installed.")
        return []

    symbols = [s for (s,) in session.query(CommodityPrice.symbol).distinct().limit(_MAX_SYMBOLS * 3)]
    cards: list[Card] = []
    for symbol in symbols:
        if len(cards) >= _MAX_SYMBOLS:
            break
        points = [
            (d, float(p)) for d, p in
            session.query(CommodityPrice.observed_on, CommodityPrice.price)
            .filter(CommodityPrice.symbol == symbol)
            .order_by(CommodityPrice.observed_on.asc()).all()
        ]
        if len(points) < 4:
            continue
        rule = session.query(MarketExtractionRule).filter_by(symbol=symbol).first()
        label = (rule.label if rule and rule.label else symbol)
        kw = resolve_keyword(session, label) or resolve_keyword(session, symbol)
        if kw is None:
            continue
        article_dates = [
            d for (d,) in session.query(KeywordMention.observed_on)
            .filter(KeywordMention.keyword_id == kw.id, KeywordMention.observed_on.isnot(None)).all()
        ]
        result = correlate_price_with_news(points, article_dates)
        if result.insufficient_data or result.coefficient is None:
            continue
        cards.append(Card(
            type="price_narrative",
            title=f"{label}: price moves vs coverage",
            summary=(f"Daily price change and news volume for {label} correlate "
                     f"{result.coefficient:+.2f} (p={result.p_value:.3g}, n={result.n})."),
            bucket="context",
            signal={"metric": f"{result.method}_r", "value": round(result.coefficient, 4),
                    "p_value": result.p_value, "significant": result.significant, "symbol": symbol},
            method=f"{result.method} correlation of daily price change vs daily article count on shared dates",
            caveat=result.caveat,
            evidence=[{"title": f"{label} price series & coverage", "url": "/#markets",
                       "source": (rule.market if rule and rule.market else None)}],
            n=result.n,
            key=symbol,
        ))
    return cards


# --------------------------------------------------------------------------- #
#  Stale data — feeds gone cold / extraction rules that stopped matching
# --------------------------------------------------------------------------- #
def stale_data(session) -> list[Card]:
    rules = session.query(MarketExtractionRule).filter_by(enabled=True).all()
    if not rules:
        return []
    now = datetime.now(UTC)
    stale: list[MarketExtractionRule] = []
    for r in rules:
        last = r.last_run_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        cold = last is None or (now - last) > timedelta(days=_STALE_DAYS)
        failed = bool(r.last_status) and any(
            w in r.last_status.lower() for w in ("fail", "no match", "error", "missing")
        )
        if cold or failed:
            stale.append(r)
    if not stale:
        return []
    sample = ", ".join(f"{r.label or r.symbol}" for r in stale[:5])
    return [Card(
        type="stale_data",
        title=f"{len(stale)} price feed(s) need attention",
        summary=(f"{len(stale)} enabled extraction rule(s) are cold (>{_STALE_DAYS}d) or last "
                 f"reported a problem — e.g. {sample}."),
        bucket="trust",
        signal={"metric": "stale_rules", "value": len(stale),
                "rules": [{"symbol": r.symbol, "label": r.label,
                           "last_status": r.last_status,
                           "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None}
                          for r in stale[:20]]},
        method=f"Extraction rules whose last_run_at is older than {_STALE_DAYS} days or whose last_status reports a failure.",
        caveat="A stale feed means the *number* may be old or its selector broke — not that the price moved. Re-run or fix the rule.",
        evidence=[{"title": "Markets — extraction rules", "url": "/#markets", "source": None}],
        n=len(stale),
        key="stale-feeds",
    )]


# --------------------------------------------------------------------------- #
#  Diet self-audit — concentration of *your* corpus over its sources
# --------------------------------------------------------------------------- #
def diet_self_audit(session) -> list[Card]:
    from src.signals import concentration

    cutoff = datetime.now(UTC) - timedelta(days=_DIET_DAYS)
    rows = (
        session.query(Source.name, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= cutoff)
        .group_by(Source.id)
        .all()
    )
    counts = {name or "(unknown)": int(c) for name, c in rows if c}
    if sum(counts.values()) < 10 or len(counts) < 2:
        return []  # too little to say anything honest about a "diet"
    result = concentration(counts, top_n=3)
    if result.top_share is None:
        return []
    top_labels = ", ".join(s["label"] for s in result.shares[:3])
    pct = round(result.top_share * 100)
    return [Card(
        type="diet_self_audit",
        title="Your reading diet leans on a few sources",
        summary=(f"Over the last {_DIET_DAYS} days, the top 3 of {result.n} sources account for "
                 f"~{pct}% of what you collected (Gini {result.gini:.2f}). Top: {top_labels}."),
        bucket="context",
        signal={"metric": "top3_share", "value": result.top_share,
                "gini": result.gini, "sources": result.n,
                "shares": result.shares[:10]},
        method=result.method,
        caveat=(result.caveat
                + " This groups by source, not owner: several sources may share one owner, so true "
                "concentration may be higher. Selection is yours — this is a prompt, not a cap."),
        evidence=[{"title": "Sources — manage your coverage", "url": "/#sources", "source": None}],
        n=result.n,
        key="diet",
    )]


_DEFAULT_PRODUCERS = (
    ("rising_now", rising_now),
    ("framing_split", framing_split),
    ("record_reshaped", record_reshaped),
    ("price_narrative", price_narrative),
    ("stale_data", stale_data),
    ("diet_self_audit", diet_self_audit),
)


def register_default_producers() -> None:
    """Register the Briefing v0 producers (idempotent)."""
    from src.briefing.registry import register

    for name, producer in _DEFAULT_PRODUCERS:
        register(name, producer)
