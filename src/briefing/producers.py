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
import re
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

# --- Young-corpus adaptation (maintainer-flagged: cards must appear sooner) -- #
# A fresh install has a tiny corpus for days; with mature-corpus minimums the
# Home feed stays empty exactly when a new operator is judging the app. Below
# this size the producers lower their volume gates AND say so on the card
# (honest small-n caveat) — the numbers shown are always real counts.
_YOUNG_CORPUS_ARTICLES = 200


def _corpus_articles(session) -> int:
    return int(session.query(func.count(Article.id)).scalar() or 0)


def _is_young(session) -> bool:
    return _corpus_articles(session) < _YOUNG_CORPUS_ARTICLES


def _small_corpus_note(session) -> str:
    total = _corpus_articles(session)
    return (
        f" Early-corpus note: only {total} article(s) collected so far — read this as a "
        "first hint from a small sample, not an established pattern."
    )


# --- Corpus maturity tier (evidence-tier header, ruled 2026-06-15) ---------- #
# A DESCRIPTIVE stage (never a score, never a composite) so a Home reader can
# calibrate how much weight to give the evidence cards. Derived only from REAL
# corpus facts: the article COUNT and the corpus AGE (first->last article span).
# The "early" boundary REUSES the existing young-corpus definition
# (_YOUNG_CORPUS_ARTICLES / _is_young) rather than inventing a second one, so the
# whole app agrees on what "young" means. The other constants are named here and
# surfaced verbatim in the UI hover (informed consent: the thresholds are shown).
#
#   early       -> a young corpus by article count (_is_young, < 200) OR a span
#                  shorter than _TIER_MIN_SPAN_DAYS: the cards rest on thin
#                  evidence, read with care.
#   established -> at least _TIER_ESTABLISHED_ARTICLES articles AND at least
#                  _TIER_ESTABLISHED_DAYS days of span: enough breadth and time
#                  for patterns to be more than a first hint.
#   developing  -> everything in between.
_TIER_MIN_SPAN_DAYS = 14
_TIER_ESTABLISHED_ARTICLES = 1000
_TIER_ESTABLISHED_DAYS = 90


def _corpus_age_days(session) -> int:
    """Days spanned by the corpus (oldest -> newest article), 0 if undated.

    Uses ``published_at`` when present, falling back to ``created_at`` (the ingest
    time) so an undated feed still yields an honest span. Cheap: one min/max query.
    """
    earliest = func.min(func.coalesce(Article.published_at, Article.created_at))
    latest = func.max(func.coalesce(Article.published_at, Article.created_at))
    lo, hi = session.query(earliest, latest).one()
    if lo is None or hi is None:
        return 0
    return max(0, (hi - lo).days)


def corpus_tier(session) -> dict:
    """The corpus maturity STAGE plus the real numbers + thresholds behind it.

    Pure (read-only); returns a plain dict — NO score field, NO composite. The UI
    shows the stage word beside the real ``articles``/``age_days`` and explains the
    thresholds (carried here) in the hover.
    """
    articles = _corpus_articles(session)
    age_days = _corpus_age_days(session)
    if _is_young(session) or age_days < _TIER_MIN_SPAN_DAYS:
        tier = "early"
    elif articles >= _TIER_ESTABLISHED_ARTICLES and age_days >= _TIER_ESTABLISHED_DAYS:
        tier = "established"
    else:
        tier = "developing"
    return {
        "tier": tier,
        "articles": articles,
        "age_days": age_days,
        "thresholds": {
            "young_articles": _YOUNG_CORPUS_ARTICLES,
            "min_span_days": _TIER_MIN_SPAN_DAYS,
            "established_articles": _TIER_ESTABLISHED_ARTICLES,
            "established_days": _TIER_ESTABLISHED_DAYS,
        },
    }


# --- "Why am I seeing this?" (evidence-tiered cards, ruled 2026-06-10) ------- #
# Every trigger carries (a) ONE constant plain-language sentence per card type —
# constant so the exact-match i18n engine translates it into all 12 languages —
# and (b) math rows whose labels are constant (translated the same way) and
# whose values are numbers/symbols only (language-neutral). The specifics (term,
# source names) already live in the card title/summary; the plain sentence must
# stay generic or translation breaks.


def _trigger(plain: str, math_rows: list[tuple[str, str]]) -> dict:
    return {"plain": plain, "math": [{"label": lb, "value": v} for lb, v in math_rows]}


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
        out.append(
            {
                "title": article.title,
                "url": article.url,
                "source": source_name,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "article_id": article.id,
            }
        )
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
#  Rising now — trending keywords/entities (composes /api/insights/trending)
# --------------------------------------------------------------------------- #
def rising_now(session) -> list[Card]:
    from src.analytics import queries as q
    from src.signals.intervals import rate_ratio_interval

    young = _is_young(session)
    min_recent = 2 if young else 3
    data = q.trending(session, limit=_MAX_RISING, min_recent=min_recent)
    note = _small_corpus_note(session) if young else ""
    scanned = data.get("scanned", 0)
    cards: list[Card] = []
    for term in data.get("terms", []):
        kw = resolve_keyword(session, term["term"])
        rows = _articles_for_term(session, kw.id, days=14, limit=6) if kw else []
        ci = rate_ratio_interval(
            term["recent"], term["prior"], window_days=7, baseline_days=30
        )
        math_rows = [
            ("Mentions in the last 7 days", str(term["recent"])),
            ("Mentions in the 30 days before that", str(term["prior"])),
            (
                "Growth = recent rate ÷ earlier rate"
                if term["prior"]
                else "Brand-new term — no earlier mentions to compare against",
                f"({term['recent']} ÷ 7) ÷ ({term['prior']} ÷ 30) = ×{term['growth']}"
                if term["prior"]
                else f"×{term['growth']}",
            ),
            (
                "How sure can we be? (95% interval)"
                if ci
                else "Too few mentions for a confidence interval",
                f"×{round(ci.low, 2)} – ×{round(ci.high, 2)}" if ci else "—",
            ),
            ("Minimum recent mentions required", f"≥ {min_recent} ✓"),
            ("Terms scanned to pick the top few", f"{scanned} → {_MAX_RISING}"),
        ]
        cards.append(
            Card(
                type="rising",
                title=f"“{term['term']}” is rising",
                # S4.5 reference producer: a TRANSLATABLE title — the frame is a fixed
                # keyable template ×12, the keyword term stays DATA (never translated).
                title_i18n="“{term}” is rising",
                title_vars={"term": term["term"]},
                summary=(
                    f"Mentions of “{term['term']}” are running ~{term['growth']}× the "
                    f"prior-period rate ({term['recent']} recent vs {term['prior']} before)."
                ),
                bucket="rising",
                signal={
                    "metric": "growth_ratio",
                    "value": term["growth"],
                    "recent": term["recent"],
                    "prior": term["prior"],
                    "kind": term["kind"],
                    "ci95": [round(ci.low, 4), round(ci.high, 4)] if ci else None,
                    "scanned": scanned,
                },
                trigger=_trigger(
                    "This word or name suddenly appears much more often in the articles "
                    "you collected than it did before. A jump like that usually means a "
                    "story is moving.",
                    math_rows,
                ),
                method=data.get(
                    "method",
                    "recent volume vs prior-period rate (a ratio, not a significance test)",
                ),
                caveat=(
                    "A rising count reflects your source set, not the world; a ratio is not a "
                    "significance test, and small samples are noisy." + note
                ),
                evidence=_evidence_from_articles(rows),
                n=term["recent"],
                key=term["normalized"],
            )
        )
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

    young = _is_young(session)
    trending = q.trending(session, limit=3, min_recent=2 if young else 3).get("terms", [])
    for term in trending:
        kw = resolve_keyword(session, term["term"])
        if kw is None:
            continue
        rows = _articles_for_term(session, kw.id, days=21, limit=_FRAMING_ARTICLE_CAP)
        by_source: dict[str, list[dict]] = {}
        for article, source_name in rows:
            if not source_name:
                continue
            by_source.setdefault(source_name, []).append(
                {
                    "title": article.title,
                    "content": article.get_content(),
                    "url": article.url,
                    "published_at": article.published_at.isoformat()
                    if article.published_at
                    else None,
                }
            )
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
                evidence.append(
                    {
                        "title": hd.get("title"),
                        "url": hd.get("url"),
                        "source": f["source"],
                        "published_at": hd.get("published_at"),
                    }
                )
        spread = round(high["avg_tone"] - low["avg_tone"], 2)
        math_rows = [
            ("Most-positive outlet's tone (VADER, −1…+1)", f"{high['avg_tone']:+.2f}"),
            ("Most-negative outlet's tone (VADER, −1…+1)", f"{low['avg_tone']:+.2f}"),
            ("Tone spread = positive − negative", f"{spread:+.2f}"),
            ("Outlets compared on this topic", str(len(by_source))),
            ("Pieces of coverage analysed", str(result.get("total_articles") or 0)),
        ]
        return [
            Card(
                type="framing_split",
                # F1 follow-up (2026-07-01): hard-link the exact articles the framing
                # comparison analysed so the click opens them, not a broad term search.
                article_ids=sorted({a.id for a, _ in rows}),
                trigger=_trigger(
                    "Two of your sources cover the same topic but in opposite emotional "
                    "registers — one reads positive, another negative. That divergence is "
                    "worth a closer look; it never means either outlet is biased.",
                    math_rows,
                ),
                title=f"“{term['term']}”: outlets frame it differently",
                summary=(
                    f"On “{term['term']}”, {high['source']} reads {high['tone_label']} "
                    f"(tone {high['avg_tone']:+.2f}) while {low['source']} reads "
                    f"{low['tone_label']} (tone {low['avg_tone']:+.2f})."
                ),
                bucket="debunk",
                signal={
                    "metric": "tone_spread",
                    "value": round(high["avg_tone"] - low["avg_tone"], 4),
                    "high": {"source": high["source"], "tone": high["avg_tone"]},
                    "low": {"source": low["source"], "tone": low["avg_tone"]},
                },
                method="VADER compound sentiment of each outlet's coverage of the term",
                caveat=(
                    result.get("caveat", "")
                    + " Tone is valence, not stance: negative tone may be alarm, grief OR "
                    "skepticism. This is a signal to read, never a label that an outlet is biased."
                ),
                evidence=evidence,
                n=result.get("total_articles"),
                key=term["normalized"],
            )
        ]
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
        reason_count = len([r for r in (rev.flag_reasons or "").split(",") if r])
        url = f"https://{page.wiki}.wikipedia.org/wiki/{page.title.replace(' ', '_')}?diff={rev.revid}"
        math_rows = [
            ("Size change of this edit (bytes)", f"{rev.delta_bytes:+}"),
            ("Flag reasons raised on it", str(reason_count)),
            ("Made by an anonymous editor", "✓" if rev.editor_anon else "—"),
            ("Revision id (anchors the diff)", str(rev.revid)),
        ]
        cards.append(
            Card(
                type="record_reshaped",
                trigger=_trigger(
                    "An edit to a tracked Wikipedia page tripped one of the honest "
                    "large-edit flags — by its size or its pattern. The flag only means "
                    "a human should open the diff and judge; it is never a verdict of vandalism.",
                    math_rows,
                ),
                title=f"Wikipedia ({page.wiki}): “{page.title}” reshaped",
                summary=(
                    f"A flagged edit changed “{page.title}” by {rev.delta_bytes:+} bytes"
                    + (f" — {reasons}." if reasons else ".")
                ),
                bucket="watch",
                signal={
                    "metric": "delta_bytes",
                    "value": rev.delta_bytes,
                    "flag_reasons": (rev.flag_reasons or "").split(",") if rev.flag_reasons else [],
                    "editor_anon": bool(rev.editor_anon),
                },
                method="Honest large-edit flagging at ingest (size delta, revert/blank tags, anon/burst, optional ORES).",
                caveat=(
                    "A flag marks an edit worth a human look — size or pattern — not a judgement that "
                    "it is vandalism or revisionism. Open the diff and decide."
                ),
                evidence=[
                    {
                        "title": f"{page.title} (diff {rev.revid})",
                        "url": url,
                        "source": f"{page.wiki}.wikipedia.org",
                        "published_at": rev.timestamp.isoformat() if rev.timestamp else None,
                    }
                ],
                n=1,
                key=f"{page.wiki}:{page.title}:{rev.revid}",
            )
        )
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

    symbols = [
        s for (s,) in session.query(CommodityPrice.symbol).distinct().limit(_MAX_SYMBOLS * 3)
    ]
    cards: list[Card] = []
    for symbol in symbols:
        if len(cards) >= _MAX_SYMBOLS:
            break
        points = [
            (d, float(p))
            for d, p in session.query(CommodityPrice.observed_on, CommodityPrice.price)
            .filter(CommodityPrice.symbol == symbol)
            .order_by(CommodityPrice.observed_on.asc())
            .all()
        ]
        if len(points) < 4:
            continue
        rule = session.query(MarketExtractionRule).filter_by(symbol=symbol).first()
        label = rule.label if rule and rule.label else symbol
        kw = resolve_keyword(session, label) or resolve_keyword(session, symbol)
        if kw is None:
            continue
        mentions = (
            session.query(KeywordMention.article_id, KeywordMention.observed_on)
            .filter(KeywordMention.keyword_id == kw.id, KeywordMention.observed_on.isnot(None))
            .all()
        )
        article_dates = [d for _, d in mentions]
        result = correlate_price_with_news(points, article_dates)
        if result.insufficient_data or result.coefficient is None:
            continue
        math_rows = [
            ("Correlation r (−1…+1)", f"{result.coefficient:+.2f}"),
            ("p-value (how likely by chance)", f"{result.p_value:.3g}"),
            ("Overlapping days compared (n)", str(result.n)),
            (
                "Significant at p < 0.05",
                ("✓" if result.significant else "—") if result.significant is not None else "—",
            ),
        ]
        cards.append(
            Card(
                type="price_narrative",
                trigger=_trigger(
                    "On the days where you have both a price for this commodity and "
                    "coverage about it, the price moves and the volume of coverage tend "
                    "to rise and fall together. Moving together is not proof one causes the other.",
                    math_rows,
                ),
                title=f"{label}: price moves vs coverage",
                summary=(
                    f"Daily price change and news volume for {label} correlate "
                    f"{result.coefficient:+.2f} (p={result.p_value:.3g}, n={result.n})."
                ),
                bucket="context",
                signal={
                    "metric": f"{result.method}_r",
                    "value": round(result.coefficient, 4),
                    "p_value": result.p_value,
                    "significant": result.significant,
                    "symbol": symbol,
                },
                method=f"{result.method} correlation of daily price change vs daily article count on shared dates",
                caveat=result.caveat,
                evidence=[
                    {
                        "title": f"{label} price series & coverage",
                        "url": "/#markets",
                        "source": (rule.market if rule and rule.market else None),
                    }
                ],
                # The actual analyzed set: the articles carrying the RESOLVED keyword
                # (kw.normalized_term may differ from the raw commodity symbol/ticker --
                # e.g. "crude oil" vs "CL=F" -- so the key must be the term that was
                # really searched, never the ticker, or a click re-runs a search for a
                # string the keyword index never indexed and finds nothing).
                article_ids=sorted({a for a, _ in mentions})[:2000],
                n=result.n,
                key=kw.normalized_term,
            )
        )
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
    math_rows = [
        ("Price feeds you have enabled", str(len(rules))),
        ("Of which, silent or failing", str(len(stale))),
        ("A feed counts as cold after this many days", f"> {_STALE_DAYS}"),
    ]
    return [
        Card(
            type="stale_data",
            trigger=_trigger(
                "Some of the price feeds you rely on have stopped delivering fresh "
                "numbers, or reported an error on their last run. The figures they "
                "show may be out of date until they run again.",
                math_rows,
            ),
            title=f"{len(stale)} price feed(s) need attention",
            summary=(
                f"{len(stale)} enabled extraction rule(s) are cold (>{_STALE_DAYS}d) or last "
                f"reported a problem — e.g. {sample}."
            ),
            bucket="trust",
            signal={
                "metric": "stale_rules",
                "value": len(stale),
                "rules": [
                    {
                        "symbol": r.symbol,
                        "label": r.label,
                        "last_status": r.last_status,
                        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                    }
                    for r in stale[:20]
                ],
            },
            method=f"Extraction rules whose last_run_at is older than {_STALE_DAYS} days or whose last_status reports a failure.",
            caveat="A stale feed means the *number* may be old or its selector broke — not that the price moved. Re-run or fix the rule.",
            evidence=[{"title": "Markets — extraction rules", "url": "/#markets", "source": None}],
            n=len(stale),
            key="stale-feeds",
        )
    ]


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
    total = sum(counts.values())
    # Young-corpus gate: 5 articles over >=2 sources is enough to STATE the split
    # honestly (it is a real count) — the small-n caveat says how early it is.
    if total < 5 or len(counts) < 2:
        return []  # too little to say anything honest about a "diet"
    note = _small_corpus_note(session) if total < 20 else ""
    result = concentration(counts, top_n=3)
    if result.top_share is None:
        return []
    top_labels = ", ".join(s["label"] for s in result.shares[:3])
    pct = round(result.top_share * 100)
    from src.signals.intervals import wilson_interval

    top3_count = round(result.top_share * total)
    ci = wilson_interval(top3_count, total)
    # The exact analyzed set for a click-through: every article the concentration stat
    # was computed over (bounded, most-recent-first -- a whole-corpus aggregate has no
    # single narrower topic, so this IS the honest set, never a synthetic "diet" text
    # search that would re-run an unrelated literal-word query on click).
    article_ids = [
        r[0]
        for r in session.query(Article.id)
        .filter(Article.created_at >= cutoff)
        .order_by(Article.created_at.desc())
        .limit(2000)
        .all()
    ]
    math_rows = [
        (f"Articles collected in the last {_DIET_DAYS} days", str(total)),
        ("Of which, from your top 3 sources", str(top3_count)),
        ("Top-3 share = top-3 articles ÷ all articles", f"{top3_count} ÷ {total} = {pct}%"),
        (
            "How sure can we be? (95% interval)",
            f"{round(ci.low * 100)}% – {round(ci.high * 100)}%" if ci else "—",
        ),
        ("Minimum required: 5 articles across 2 sources", f"{total} · {len(counts)} ✓"),
    ]
    return [
        Card(
            type="diet_self_audit",
            trigger=_trigger(
                "Most of what you've collected recently comes from just a few sources. "
                "This Lead shows you that share, so you can decide whether your reading "
                "mix is what you want it to be.",
                math_rows,
            ),
            title="Your reading diet leans on a few sources",
            summary=(
                f"Over the last {_DIET_DAYS} days, the top 3 of {result.n} sources account for "
                f"~{pct}% of what you collected (Gini {result.gini:.2f}). Top: {top_labels}."
            ),
            bucket="context",
            signal={
                "metric": "top3_share",
                "value": result.top_share,
                "gini": result.gini,
                "sources": result.n,
                "shares": result.shares[:10],
            },
            method=result.method,
            caveat=(
                result.caveat
                + " This groups by source, not owner: several sources may share one owner, so true "
                "concentration may be higher. Selection is yours — this is a prompt, not a cap."
                + note
            ),
            evidence=[
                {"title": "Sources — manage your coverage", "url": "/#sources", "source": None}
            ],
            article_ids=article_ids,
            n=result.n,
            key="diet",
        )
    ]


# --------------------------------------------------------------------------- #
#  Echo chamber — one story carried across N coordinated sources (§6/§1)
# --------------------------------------------------------------------------- #
_MAX_ECHO = 3
_ECHO_DAYS = 14
_ECHO_MIN_SOURCES = 3


def _articles_by_id(session, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    int_ids = [int(i) for i in ids if str(i).isdigit()]
    rows = (
        session.query(Article, Source.name)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(int_ids))
        .all()
    )
    return {
        str(a.id): {
            "title": a.title,
            "url": a.url,
            "source": name,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a, name in rows
    }


def echo_chamber(session) -> list[Card]:
    """Surface coordinated near-duplicate floods — annotated by default (§6 'equal but
    aware'); the card invites the user to *apply* a collapse, never auto-applied."""
    from src.integrity.actors import corpus_actors
    from src.integrity.collapse import is_applied

    result = corpus_actors(session, days=_ECHO_DAYS)
    cards: list[Card] = []
    for actor in result.actors:
        if len(actor.sources) < _ECHO_MIN_SOURCES:
            continue
        if len(cards) >= _MAX_ECHO:
            break
        sig = actor.signature
        applied = bool(sig and is_applied(sig))
        # The FULL coordinated set (deduped, order-preserving) for exact analysis-window
        # seeding; the evidence is a 4-item sample of the same.
        all_ids = list(dict.fromkeys(ev.representative for ev in actor.events))
        rep_ids = all_ids[:4]
        ev_lookup = _articles_by_id(session, rep_ids)
        evidence = [ev_lookup[i] for i in rep_ids if i in ev_lookup]
        n = len(actor.sources)
        summary = (
            f"{n} sources published near-identical text on {actor.shared_stories} "
            f"story(ies)"
            + (f", sharing host {actor.shared_hosts[0]}" if actor.shared_hosts else "")
            + (
                ". You have collapsed this into one actor."
                if applied
                else ". Apply a collapse to count it as one voice, or expand to inspect."
            )
        )
        math_rows = [
            ("Sources that published near-identical text", str(n)),
            ("Stories they shared", str(actor.shared_stories)),
            ("Minimum sources for this Lead", f"≥ {_ECHO_MIN_SOURCES} ✓"),
            (
                "Hours between the first and the median copy",
                str(actor.median_span_hours) if actor.median_span_hours is not None else "—",
            ),
        ]
        cards.append(
            Card(
                type="echo_chamber",
                trigger=_trigger(
                    "Several of your sources published almost exactly the same text on "
                    "the same story. That can be a shared newswire — or coordination. "
                    "Either way, those voices may count as one, not many.",
                    math_rows,
                ),
                title=(
                    f"{n} sources moving in lockstep"
                    if not applied
                    else f"Coordinated actor ({n} sources) — collapsed"
                ),
                summary=summary,
                bucket="overtold",
                signal={
                    "metric": "coordinated_sources",
                    "value": n,
                    "shared_stories": actor.shared_stories,
                    "signature": sig,
                    "sources": actor.sources,
                    "shared_hosts": actor.shared_hosts,
                    "median_span_hours": actor.median_span_hours,
                    "collapse_applied": applied,
                },
                method=result.method,
                caveat=result.caveat,
                evidence=evidence,
                # The EXACT coordinated article set, so the card opens the analysis
                # window over precisely these articles (the actor's near-duplicates).
                article_ids=all_ids,
                n=n,
                key=sig or ",".join(actor.sources),
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Lonely signal — a substantive single-source story that did not echo (§4)
# --------------------------------------------------------------------------- #
_MAX_LONELY = 3


def lonely_signal(session) -> list[Card]:
    """Recent single-source stories that did NOT echo — candidate undertold items.

    This states *only* that one source carried it and nobody near-duplicated it: it may
    be a genuine exclusive or simply minor. The human decides (strong caveat)."""
    from src.integrity.collapse import story_prominence

    data = story_prominence(session, days=_ECHO_DAYS)
    singles = [s for s in data["stories"] if s["voices_raw"] == 1]
    # Most-recent first: representative id is the article id (higher = newer).
    singles.sort(key=lambda s: -int(s["representative"]))
    cards: list[Card] = []
    for story in singles[:_MAX_LONELY]:
        ev = _articles_by_id(session, [story["representative"]])
        evidence = list(ev.values())
        cards.append(
            Card(
                type="lonely_signal",
                article_ids=[int(story["representative"])],  # F1: carry the exact article so the click opens it
                trigger=_trigger(
                    "Only one of your sources carried this story, and nobody else "
                    "repeated it. That can mean an exclusive worth a look — or just a "
                    "minor item. The Lead makes no judgement; you decide.",
                    [
                        ("Sources that carried this story", "1"),
                        ("Sources that repeated it (near-identical text)", "0"),
                        ("Window scanned (days)", str(_ECHO_DAYS)),
                    ],
                ),
                title=f"Single-source: “{story['title'][:80]}”",
                summary=(
                    f"Only {story['sources'][0] if story['sources'] else 'one source'} carried this; "
                    "no other source published near-identical text. It could be an exclusive — or minor."
                ),
                bucket="undertold",
                signal={
                    "metric": "voices",
                    "value": 1,
                    "source": story["sources"][0] if story["sources"] else None,
                },
                method="A near-duplicate story cluster of size 1 (one source, no echo) over the recent window.",
                caveat=(
                    "‘Single-source, did not echo’ is the ONLY claim — not that it is important, true, or "
                    "suppressed. Many minor items are single-source. Read it and judge."
                ),
                evidence=evidence,
                n=1,
                key=f"lonely:{story['representative']}",
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Capacity implausible — output rate far above the corpus norm (§6 B)
# --------------------------------------------------------------------------- #
_CAPACITY_DAYS = 14
_CAPACITY_MIN_PER_DAY = 20  # absolute floor before we even ask the question
_CAPACITY_FACTOR = 8.0  # and well above the corpus median


def capacity_implausible(session) -> list[Card]:
    """Sources whose article rate is implausibly high vs the corpus — a question, never
    a verdict of automation (a wire agency or big newsroom can be legitimately prolific)."""
    cutoff = datetime.now(UTC) - timedelta(days=_CAPACITY_DAYS)
    rows = (
        session.query(Source.id, Source.name, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .group_by(Source.id)
        .all()
    )
    if len(rows) < 3:
        return []
    id_by_name = {(name or "(unknown)"): sid for sid, name, _ in rows}
    rates = {(name or "(unknown)"): c / _CAPACITY_DAYS for _, name, c in rows}
    ordered = sorted(rates.values())
    median = ordered[len(ordered) // 2]
    flagged = [
        {"source": name, "per_day": round(rate, 2)}
        for name, rate in sorted(rates.items(), key=lambda kv: -kv[1])
        if rate >= _CAPACITY_MIN_PER_DAY and (median == 0 or rate >= median * _CAPACITY_FACTOR)
    ]
    if not flagged:
        return []
    top = flagged[0]
    # The exact analyzed set for a click-through: the flagged (fastest) source's own
    # articles in the window -- the actual subject of the headline, never a synthetic
    # "capacity" text search that would re-run an unrelated literal-word query on click.
    top_source_id = id_by_name.get(top["source"])
    article_ids = (
        [
            r[0]
            for r in session.query(Article.id)
            .filter(
                Article.source_id == top_source_id,
                func.coalesce(Article.published_at, Article.created_at) >= cutoff,
            )
            .limit(2000)
            .all()
        ]
        if top_source_id is not None
        else []
    )
    math_rows = [
        (f"Fastest source: articles per day (last {_CAPACITY_DAYS} days)", str(top["per_day"])),
        ("Typical source in your corpus (median per day)", str(round(median, 2))),
        ("Absolute floor before this Lead can appear", f"≥ {_CAPACITY_MIN_PER_DAY} ✓"),
        (
            "Must also be many times the typical rate",
            f"{top['per_day']} ≥ {_CAPACITY_FACTOR:.0f} × {round(median, 2)} ✓",
        ),
    ]
    return [
        Card(
            type="capacity_implausible",
            trigger=_trigger(
                "One of your sources is publishing far faster than the others — so fast "
                "that it's worth asking how. Big newsrooms and wire agencies can be this "
                "fast legitimately; this Lead only raises the question.",
                math_rows,
            ),
            title=f"{len(flagged)} source(s) publishing unusually fast",
            summary=(
                f"{top['source']} averaged ~{top['per_day']}/day over {_CAPACITY_DAYS}d — "
                f"≥{_CAPACITY_FACTOR:.0f}× the corpus median ({round(median, 2)}/day)."
            ),
            bucket="investigate",
            signal={
                "metric": "max_articles_per_day",
                "value": top["per_day"],
                "corpus_median_per_day": round(median, 2),
                "flagged": flagged[:20],
            },
            method=(
                f"Sources whose articles/day over {_CAPACITY_DAYS}d is ≥ {_CAPACITY_MIN_PER_DAY} and "
                f"≥ {_CAPACITY_FACTOR:.0f}× the corpus median per-source rate."
            ),
            caveat=(
                "High output is often legitimate (wire agencies, large newsrooms, aggregators). This "
                "is a capacity *question* for a human, never a determination that a source is automated."
            ),
            evidence=[{"title": "Sources — review output", "url": "/#sources", "source": None}],
            article_ids=article_ids,
            n=len(flagged),
            key="capacity",
        )
    ]


# --------------------------------------------------------------------------- #
#  Emotion profile — emotion categories around a trending term (§4; new lexicon)
# --------------------------------------------------------------------------- #
def emotion_profile_card(session) -> list[Card]:
    """Emotion-category word-pattern around the top trending term (degrades loudly if
    no lexicon). A pattern to read, never a label that an outlet is 'fearmongering'."""
    from src.analytics import queries as q
    from src.awareness.emotion import emotion_profile

    trending = q.trending(
        session, limit=1, min_recent=2 if _is_young(session) else 3
    ).get("terms", [])
    if not trending:
        return []
    term = trending[0]
    ctx = q.context(session, term["term"], limit=20)
    snippets = [m.get("snippet", "") for m in ctx.get("mentions", []) if m.get("snippet")]
    if not snippets:
        return []
    prof = emotion_profile(snippets)
    if not prof["total_hits"] or not prof["dominant"]:
        return []
    kw = resolve_keyword(session, term["term"])  # resolve once (F-009)
    rows = _articles_for_term(session, kw.id, days=21, limit=4) if kw else []
    dom_hits = prof["categories"][prof["dominant"]]
    dom_share = round(dom_hits / prof["total_hits"] * 100) if prof["total_hits"] else 0
    math_rows = [
        ("Context windows scanned around the term", str(prof["n_snippets"])),
        ("Emotion-associated words found in them", str(prof["total_hits"])),
        (f"Of which in the leading category ({prof['dominant']})", str(dom_hits)),
        (
            "Leading category's share = its hits ÷ all hits",
            f"{dom_hits} ÷ {prof['total_hits']} = {dom_share}%",
        ),
    ]
    return [
        Card(
            type="emotion_profile",
            # F1 follow-up (2026-07-01): hard-link the mention articles the emotion
            # profile was computed over, so the click opens that exact corpus.
            article_ids=sorted({m["article_id"] for m in ctx.get("mentions", []) if m.get("article_id")}),
            trigger=_trigger(
                "The words used around this topic lean toward one emotional category "
                "more than the others. That is a pattern in the wording to read, never "
                "a label that an outlet is fearmongering.",
                math_rows,
            ),
            title=f"“{term['term']}”: coverage skews {prof['dominant']}",
            summary=(
                f"Across {prof['n_snippets']} context windows around “{term['term']}”, "
                f"{prof['dominant']}-associated words are the most frequent "
                f"({prof['categories'][prof['dominant']]} of {prof['total_hits']} hits)."
            ),
            bucket="context",
            signal={
                "metric": "dominant_emotion",
                "value": prof["dominant"],
                "categories": prof["categories"],
                "lexicon": prof["lexicon_source"],
            },
            method=prof["method"],
            caveat=prof["caveat"],
            evidence=_evidence_from_articles(rows),
            n=prof["total_hits"],
            key=f"emotion:{term['normalized']}",
        )
    ]


# --------------------------------------------------------------------------- #
#  IP / legal news cards (§4) — thin: trends + deal verbs over the NEWS corpus
# --------------------------------------------------------------------------- #
_IP_TERMS = {
    "patent",
    "patents",
    "lawsuit",
    "lawsuits",
    "injunction",
    "infringement",
    "licensing",
    "antitrust",
    "copyright",
    "trademark",
    "litigation",
    "settlement",
}
_DEAL_RE = re.compile(
    r"\b(acquir\w+|merg\w+|takeover|buyout|divest\w+|sold to|sells? to|"
    r"acquisition|stake in|controlling stake)\b",
    re.IGNORECASE,
)
_MAX_DEAL = 4
_IP_DAYS = 30


def ip_litigation_pulse(session) -> list[Card]:
    """Surface rising IP/legal terms in the news (a pulse, not a verdict)."""
    from src.analytics import queries as q

    rising = q.trending(
        session, limit=50, min_recent=2 if _is_young(session) else 3
    ).get("terms", [])
    hits = [t for t in rising if t["normalized"] in _IP_TERMS]
    if not hits:
        return []
    from src.signals.intervals import rate_ratio_interval

    top = max(hits, key=lambda t: t["growth"])
    kw = resolve_keyword(session, top["term"])
    rows = _articles_for_term(session, kw.id, days=_IP_DAYS, limit=6) if kw else []
    names = ", ".join(sorted({t["term"] for t in hits}))
    ci = rate_ratio_interval(top["recent"], top["prior"], window_days=7, baseline_days=30)
    math_rows = [
        ("IP/legal terms rising in your corpus", str(len(hits))),
        ("Fastest of them: mentions in the last 7 days", str(top["recent"])),
        ("Its mentions in the 30 days before that", str(top["prior"])),
        (
            "Its growth = recent rate ÷ earlier rate"
            if top["prior"]
            else "Brand-new term — no earlier mentions to compare against",
            f"×{top['growth']}",
        ),
        (
            "How sure can we be? (95% interval)" if ci else "Too few mentions for a confidence interval",
            f"×{round(ci.low, 2)} – ×{round(ci.high, 2)}" if ci else "—",
        ),
    ]
    return [
        Card(
            type="ip_litigation_pulse",
            trigger=_trigger(
                "Words about patents, lawsuits and other legal disputes are showing up "
                "in your collection more than before. This tracks how much such language "
                "is being reported — never the merits of any actual case.",
                math_rows,
            ),
            title="IP / legal terms are rising",
            summary=(
                f"IP/legal vocabulary is trending in your corpus ({names}); “{top['term']}” "
                f"is up ~{top['growth']}× vs the prior period."
            ),
            bucket="context",
            signal={
                "metric": "ip_terms_rising",
                "value": len(hits),
                "terms": [t["term"] for t in hits],
                "top": top["term"],
            },
            method="trending IP/legal terms (recent-vs-prior ratio) over the news corpus",
            caveat=(
                "Measures *coverage* of IP/legal language, not the merits of any case. The tool "
                "sees reporting about filings, not the filings themselves."
            ),
            evidence=_evidence_from_articles(rows),
            n=len(hits),
            key="ip-pulse",
        )
    ]


def ownership_change(session) -> list[Card]:
    """Candidate ownership-change stories — articles whose text reports a deal (§4 IP/legal).

    States only that deal language appears; it never asserts the deal happened or that IP
    was 'stripped' — the tool reads reporting, not filings. The human confirms."""
    cutoff = datetime.now(UTC) - timedelta(days=_IP_DAYS)
    rows = (
        session.query(Article, Source.name)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(Article.id.desc())
        .limit(400)
        .all()
    )
    matches = []
    for article, source_name in rows:
        text = (article.title or "") + " " + (article.get_content() or "")[:1200]
        if _DEAL_RE.search(text):
            matches.append((article, source_name))
        if len(matches) >= _MAX_DEAL:
            break
    if not matches:
        return []
    evidence = [
        {
            "title": a.title,
            "url": a.url,
            "source": name,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a, name in matches
    ]
    lead = matches[0][0].title or "(untitled)"
    math_rows = [
        ("Recent articles scanned for deal language", str(len(rows))),
        ("Of which match an acquisition/merger/divestiture verb", str(len(matches))),
        ("Recency window scanned (days)", str(_IP_DAYS)),
        ("Most this Lead surfaces at once", str(_MAX_DEAL)),
    ]
    return [
        Card(
            type="ownership_change",
            article_ids=[a.id for a, _ in matches],  # F1: carry the deal-report articles so the click opens them
            trigger=_trigger(
                "Some recent articles use the language of corporate deals — acquired, "
                "merged, divested. This flags the wording for you to verify against the "
                "primary filing; it never asserts a deal actually happened.",
                math_rows,
            ),
            title=f"{len(matches)} possible ownership-change report(s)",
            summary=(
                f"Recent articles use deal language (acquired / merger / divested), e.g. "
                f"“{lead[:80]}”. Candidate corporate-control stories to verify."
            ),
            bucket="investigate",
            signal={"metric": "deal_reports", "value": len(matches)},
            method="recent articles whose text matches acquisition/merger/divestiture verbs",
            caveat=(
                "Matches *reporting language*, not confirmed deals — and never asserts IP was "
                "transferred or stripped. Foreground the primary filing; the human confirms."
            ),
            evidence=evidence,
            n=len(matches),
            key="ownership-change",
        )
    ]


# --------------------------------------------------------------------------- #
#  World-law (§5) — change watch + cross-jurisdiction model-legislation near-dup
# --------------------------------------------------------------------------- #
_MAX_LAW = 4


def law_change(session) -> list[Card]:
    """Recently flagged changes to tracked legal documents (a watch signal, never a verdict)."""
    from src.database.models import LawDocument, LawRevision

    rows = (
        session.query(LawRevision, LawDocument)
        .join(LawDocument, LawDocument.id == LawRevision.document_id)
        .filter(LawRevision.flagged.is_(True))
        .order_by(LawRevision.observed_at.desc(), LawRevision.id.desc())
        .limit(_MAX_LAW)
        .all()
    )
    cards: list[Card] = []
    for rev, doc in rows:
        reasons = (rev.flag_reasons or "").replace(",", ", ")
        reason_count = len([r for r in (rev.flag_reasons or "").split(",") if r])
        math_rows = [
            ("Size change of this revision (bytes)", f"{rev.delta_bytes:+}"),
            ("Flag reasons raised on it", str(reason_count)),
            ("Compared against", "the stored baseline text"),
        ]
        cards.append(
            Card(
                type="law_change",
                trigger=_trigger(
                    "A legal document you track changed compared with the version stored "
                    "before, and the size of the change tripped a flag. The flag only means "
                    "a human should read the diff — it is never a judgement about the law.",
                    math_rows,
                ),
                title=f"Law changed ({doc.jurisdiction}): {doc.title[:70]}",
                summary=(
                    f"A tracked legal document changed by {rev.delta_bytes:+} bytes vs its baseline"
                    + (f" — {reasons}." if reasons else ".")
                ),
                bucket="watch",
                signal={
                    "metric": "delta_bytes",
                    "value": rev.delta_bytes,
                    "jurisdiction": doc.jurisdiction,
                    "category": doc.category,
                    "flag_reasons": (rev.flag_reasons or "").split(",") if rev.flag_reasons else [],
                },
                method="Baseline → normalised-text diff on re-fetch; large-change flag (reused wiki thresholds).",
                caveat=(
                    "A research mirror, NOT the authoritative source and not legal advice. A flag marks "
                    "a change worth a human look — not a judgement of the law. Open the official source."
                ),
                evidence=[
                    {
                        "title": f"{doc.title} (official)",
                        "url": doc.official_url or doc.url,
                        "source": doc.jurisdiction,
                    }
                ],
                n=1,
                key=f"law:{doc.id}:{rev.content_hash[:12]}",
            )
        )
    return cards


def model_legislation(session) -> list[Card]:
    """Near-identical legal text across jurisdictions — measurable model-legislation/diffusion."""
    from src.database.models import LawDocument
    from src.signals.near_dup import near_duplicate_clusters

    docs = session.query(LawDocument).filter(LawDocument.baseline_text.isnot(None)).all()
    if len(docs) < 2:
        return []
    texts = {str(d.id): (d.baseline_text or "") for d in docs if d.baseline_text}
    by_id = {str(d.id): d for d in docs}
    result = near_duplicate_clusters(texts, threshold=0.5)
    cards: list[Card] = []
    for cluster in result.clusters:
        jurs = sorted({by_id[m].jurisdiction for m in cluster.members})
        if len(jurs) < 2:
            continue  # same-jurisdiction near-dup is not cross-border model legislation
        if len(cards) >= _MAX_LAW:
            break
        titles = [by_id[m] for m in cluster.members]
        math_rows = [
            ("Distinct jurisdictions sharing the text", str(len(jurs))),
            ("Documents in this near-identical cluster", str(len(cluster.members))),
            ("Average text similarity (Jaccard, 0…1)", f"{cluster.avg_similarity:.2f}"),
            ("Minimum similarity to cluster", f"≥ {result.threshold:.2f}"),
        ]
        cards.append(
            Card(
                type="model_legislation",
                trigger=_trigger(
                    "Legal texts in different places are nearly word-for-word the same. "
                    "That is a measurable diffusion pattern worth a look — shared templates "
                    "and treaties also share text, so it is never proof of coordinated lobbying.",
                    math_rows,
                ),
                title=f"Near-identical law across {len(jurs)} jurisdictions",
                summary=(
                    f"Legal text is near-duplicate across {', '.join(jurs)} "
                    f"(e.g. “{titles[0].title[:60]}”) — possible model legislation / diffusion."
                ),
                bucket="investigate",
                signal={
                    "metric": "jurisdictions",
                    "value": len(jurs),
                    "jurisdictions": jurs,
                    "avg_similarity": cluster.avg_similarity,
                },
                method=result.method,
                caveat=(
                    "Shared *text* across jurisdictions — a measurable diffusion pattern, not proof of "
                    "coordinated lobbying. Common templates and treaties also share text. Read the sources."
                ),
                evidence=[
                    {
                        "title": f"{by_id[m].title} ({by_id[m].jurisdiction})",
                        "url": by_id[m].official_url or by_id[m].url,
                        "source": by_id[m].jurisdiction,
                    }
                    for m in cluster.members[:5]
                ],
                n=len(cluster.members),
                key=f"model:{','.join(sorted(cluster.members))}",
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Story lineage — trace an echoed story toward its primal source (§2, Theme 4)
# --------------------------------------------------------------------------- #
_LINEAGE_DAYS = 14
_LINEAGE_MIN_SOURCES = 3


def story_lineage(session) -> list[Card]:
    """For the most-echoed recent story, show primary → first report → echoes."""
    from src.signals.lineage import trace_lineage
    from src.signals.near_dup import near_duplicate_clusters

    cutoff = datetime.now(UTC) - timedelta(days=_LINEAGE_DAYS)
    rows = (
        session.query(Article.id, Source.name, Article.title, Article.content, Article.published_at)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(Article.id.desc())
        .limit(2000)
        .all()
    )
    by_id = {}
    texts = {}
    for aid, name, title, content, pub in rows:
        text = content or title or ""
        if len(text) < 200:
            continue
        sid = str(aid)
        texts[sid] = text
        by_id[sid] = {"id": sid, "source": name, "text": text, "published_at": pub}
    if len(texts) < _LINEAGE_MIN_SOURCES:
        return []
    nd = near_duplicate_clusters(texts, threshold=0.6)
    for cluster in nd.clusters:
        docs = [by_id[m] for m in cluster.members]
        sources = {d["source"] for d in docs if d["source"]}
        if len(sources) < _LINEAGE_MIN_SOURCES:
            continue
        lin = trace_lineage(docs)
        if lin.primary is None:
            continue
        ev = _articles_by_id(session, [i.doc_id for i in lin.chain[:5]])
        evidence = [ev[i.doc_id] for i in lin.chain[:5] if i.doc_id in ev]
        math_rows = [
            ("Outlets carrying near-identical text", str(len(sources))),
            ("Documents in the traced chain", str(len(cluster.members))),
            ("Average text similarity (Jaccard, 0…1)", f"{cluster.avg_similarity:.2f}"),
            ("Minimum similarity to cluster", f"≥ {nd.threshold:.2f}"),
            ("Attributed to a named wire agency", "✓" if lin.wire_origin else "—"),
        ]
        return [
            Card(
                type="story_lineage",
                article_ids=[int(m) for m in cluster.members],  # F1: carry the echoed cluster so the click opens it
                trigger=_trigger(
                    "Many of your outlets ran near-identical text on one story. Ordering the "
                    "copies by publication time points back toward the earliest one — a "
                    "candidate origin to foreground, not a proven first source.",
                    math_rows,
                ),
                title=f"One story, {len(sources)} outlets — tracing the source",
                summary=(
                    f"A story echoed across {len(sources)} sources traces earliest to "
                    f"{lin.primary.source or 'an unknown source'}"
                    + (f", attributed to the wire **{lin.wire_origin}**" if lin.wire_origin else "")
                    + ". Foreground the original; weigh the echoes."
                ),
                bucket="context",
                signal={
                    "metric": "echoing_sources",
                    "value": len(sources),
                    "primary_source": lin.primary.source,
                    "wire_origin": lin.wire_origin,
                    "chain": [i.to_dict() for i in lin.chain[:20]],
                },
                method=lin.method,
                caveat=lin.caveat,
                evidence=evidence,
                n=len(sources),
                key=f"lineage:{lin.primary.doc_id}",
            )
        ]
    return []


# --------------------------------------------------------------------------- #
#  Coverage advisor — gentle, overridable diet guidance (§1/§3, Theme 4)
# --------------------------------------------------------------------------- #
_COVERAGE_DAYS = 30
_COVERAGE_DOMINANCE = 0.6  # one country/language ≥ 60% of recent collection


def coverage_advisor(session) -> list[Card]:
    """Surface geographic/linguistic skew in *your* recent collection — suggestive, never enforced."""
    from src.signals import concentration

    cutoff = datetime.now(UTC) - timedelta(days=_COVERAGE_DAYS)

    def _share(col):
        rows = (
            session.query(col, func.count(Article.id))
            .join(Article, Article.source_id == Source.id)
            .filter(Article.created_at >= cutoff, col.isnot(None))
            .group_by(col)
            .all()
        )
        counts = {str(k): int(c) for k, c in rows if c}
        if sum(counts.values()) < 5:
            return None  # too little collected to say anything honest
        res = concentration(counts, top_n=1)
        if res.top_share is None or not res.shares:
            return None
        # A single bucket (100% one country/language) is the strongest skew — surface it.
        return res.shares[0]["label"], res.top_share, res.n

    country = _share(Source.country)
    lang = _share(Source.language)
    flagged = []
    if country and country[1] >= _COVERAGE_DOMINANCE:
        flagged.append(("country", *country))
    if lang and lang[1] >= _COVERAGE_DOMINANCE:
        flagged.append(("language", *lang))
    if not flagged:
        return []
    kind, label, share, n = flagged[0]
    pct = round(share * 100)
    note = _small_corpus_note(session) if _is_young(session) else ""
    from src.signals.intervals import wilson_interval

    # Recompute the bucket totals for the audit trail (real counts, by design).
    col = Source.country if kind == "country" else Source.language
    rows2 = (
        session.query(func.count(Article.id))
        .join(Source, Article.source_id == Source.id)
        .filter(Article.created_at >= cutoff, col.isnot(None))
        .scalar()
    )
    total_arts = int(rows2 or 0)
    top_count = round(share * total_arts)
    ci = wilson_interval(top_count, total_arts) if total_arts else None
    math_rows = [
        (f"Articles collected in the last {_COVERAGE_DAYS} days", str(total_arts)),
        ("Of which, from the single biggest origin", str(top_count)),
        ("Its share = its articles ÷ all articles", f"{top_count} ÷ {total_arts} = {pct}%"),
        (
            "How sure can we be? (95% interval)",
            f"{round(ci.low * 100)}% – {round(ci.high * 100)}%" if ci else "—",
        ),
        ("Threshold for this Lead: one origin at or above 60%", f"{pct}% ≥ 60% ✓"),
    ]
    return [
        Card(
            type="coverage_advisor",
            trigger=_trigger(
                "More than half of your recent collection comes from one single country "
                "or language. That can quietly narrow what you see — this Lead points it "
                "out so you can balance your sources if you want to.",
                math_rows,
            ),
            title=f"Your recent collection leans on one {kind}",
            summary=(
                f"~{pct}% of what you collected in {_COVERAGE_DAYS} days is from {kind} "
                f"“{label}” (of {n}). Consider adding under-represented {kind}s — a fuller "
                "picture is harder to skew. This is a suggestion you can ignore."
            ),
            bucket="context",
            signal={
                "metric": f"top_{kind}_share",
                "value": share,
                "label": label,
                "n": n,
                "all": flagged,
            },
            method=f"concentration (top share) of recent articles by source {kind}",
            caveat=(
                "Selection is yours: this surfaces a coverage fact, it never filters or caps "
                "anything. A skewed corpus skews every downstream signal — see your World "
                "coverage view to balance it." + note
            ),
            evidence=[{"title": "Sources — World coverage", "url": "/#sources", "source": None}],
            n=n,
            key=f"coverage:{kind}",
        )
    ]


# --------------------------------------------------------------------------- #
#  Weather corroboration — "if this, then SUGGEST user to fetch" (2026-06-12)
# --------------------------------------------------------------------------- #
def weather_corroboration(session) -> list[Card]:
    """Clusters of climate-event terms × deduced places => an OFFER to check
    independent weather data. The producer itself NEVER touches the network:
    the bounded Open-Meteo fetch happens only from the card's button, behind
    the one consent popup (informed consent, maintainer-ruled 2026-06-12)."""
    try:
        from src.analytics.corroboration import find_weather_opportunities

        found = find_weather_opportunities(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("weather corroboration scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for op in found.get("opportunities", []):
        ev_rows = (
            session.query(Article.id, Article.title, Article.url, Article.published_at)
            .filter(Article.id.in_(op["article_ids"][:4]))
            .all()
        )
        evidence = [
            {
                "article_id": aid,
                "title": title or url,
                "url": url,
                "published_at": pub.isoformat() if pub else None,
            }
            for aid, title, url, pub in ev_rows
        ]
        place_label = op["place"] + (f" ({op['place_country'].upper()})" if op["place_country"] else "")
        cards.append(
            Card(
                type="weather_corroboration",
                article_ids=[int(x) for x in op["article_ids"]],  # F1: carry the cluster so the click opens it
                title=f"{op['rule_label']} near {op['place']}: independent weather check available",
                summary=(
                    f"{op['n_articles']} articles mention {', '.join(op['terms_matched'])} "
                    f"together with {place_label} between {op['window_start']} and "
                    f"{op['window_end']}. Open-Meteo reanalysis for that place and window "
                    f"can corroborate or challenge the narrative — it is fetched only if you ask."
                ),
                bucket="investigate",
                method=(
                    "exact lexical match of the curated multilingual climate-event vocabulary "
                    "(configs/corroboration_rules.yml) against indexed keywords, joined to "
                    "deduced place mentions (lexical-v1) and article dates; computed locally — "
                    "this Lead made no network call"
                ),
                caveat=(
                    "Word–place co-occurrence is not a confirmed event: articles may discuss "
                    "past, forecast or figurative weather. The window is built from article "
                    "publication dates, not the event's own dates. Reanalysis is a model "
                    "estimate, not a station record; corroboration is never proof. "
                    f"Place precision: {op['geocode']}."
                ),
                signal={
                    "metric": "articles_in_cluster",
                    "value": op["n_articles"],
                    "rule": op["rule"],
                    "rule_label": op["rule_label"],
                    "place": op["place"],
                    "place_country": op["place_country"],
                    "lat": op["lat"],
                    "lon": op["lon"],
                    "geocode": op["geocode"],
                    "window_start": op["window_start"],
                    "window_end": op["window_end"],
                    "variables": ",".join(op["variables"]),
                    "languages": ",".join(op["languages"]),
                    "clusters_total": found.get("clusters_total", 0),
                },
                evidence=evidence,
                n=op["n_articles"],
                key=f"{op['rule']}|{op['place_country'] or ''}|{op['place']}|{op['window_start']}",
                trigger=_trigger(
                    "Several collected articles mention the same weather-event word and the "
                    "same place inside one time window.",
                    [
                        ("Articles in the cluster", str(op["n_articles"])),
                        ("Matched terms", ", ".join(op["terms_matched"])),
                        ("Place (as deduced)", place_label),
                        ("Window (article dates ± 3 days)",
                         f"{op['window_start']} → {op['window_end']}"),
                    ],
                ),
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Space-time convergence — the 0.0.9 flagship, slice 1 (read-only).
#  Articles converging on the SAME PLACE within the SAME TIME WINDOW, gated by
#  DISTINCT-SOURCE independence (anti-false-triangulation). Co-occurrence is
#  NEVER causation; a single chatty source cannot manufacture a convergence.
# --------------------------------------------------------------------------- #
_MAX_CONVERGENCE = 4


def space_time_convergence(session) -> list[Card]:
    """Surface clusters of articles converging on one place within one window.

    A NEW producer over the persisted When×Where×Who substrate (places + event
    dates). The honest measure is DISTINCT-SOURCE spread (not raw article count):
    articles sharing one origin are one source wearing many hats. The surfacing
    gate (≥3 articles AND ≥2 distinct sources) makes a single source unable to
    fabricate a convergence; the shared-outbound-link flag exposes when even
    distinct sources lean on one common citation. No causation, ever.
    """
    try:
        from src.analytics.convergence import (
            CONVERGENCE_CAVEAT,
            find_convergences,
        )

        found = find_convergences(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("space-time convergence scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for c in found.get("clusters", [])[:_MAX_CONVERGENCE]:
        ev_rows = (
            session.query(Article.id, Article.title, Article.url, Article.published_at)
            .filter(Article.id.in_(c["article_ids"][:4]))
            .all()
        )
        # Map article -> source name for honest per-evidence attribution.
        src_lookup = dict(
            session.query(Article.id, Source.name)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(Article.id.in_(c["article_ids"][:4]))
            .all()
        )
        evidence = [
            {
                "article_id": aid,
                "title": title or url,
                "url": url,
                "source": src_lookup.get(aid),
                "published_at": pub.isoformat() if pub else None,
            }
            for aid, title, url, pub in ev_rows
        ]
        place_label = c["place"] + (
            f" ({c['place_country'].upper()})" if c["place_country"] else ""
        )
        shared = c["shared_origin_links"]
        math_rows = [
            ("Articles converging on this place + window", str(c["n_articles"])),
            ("Distinct sources (the independence measure)", str(c["distinct_sources"])),
            ("Minimum distinct sources for this Lead", f"≥ {found['min_sources']} ✓"),
            ("Minimum articles for this Lead", f"≥ {found['min_articles']} ✓"),
            ("Time window (deduced event dates)", f"{c['window_start']} → {c['window_end']}"),
            (
                "Outbound links shared by >1 member (false-triangulation flag)",
                str(shared),
            ),
        ]
        cards.append(
            Card(
                type="space_time_convergence",
                title=f"{c['distinct_sources']} sources converge on {place_label}",
                summary=(
                    f"{c['n_articles']} articles from {c['distinct_sources']} distinct "
                    f"sources mention {place_label} around {c['window_start']}"
                    + (f"–{c['window_end']}" if c["window_end"] != c["window_start"] else "")
                    + (
                        f". {shared} outbound link(s) are shared across members — read those "
                        "as one possible common origin, not independent confirmation."
                        if shared
                        else ". No shared outbound links among them in your corpus."
                    )
                ),
                bucket="investigate",
                signal={
                    "metric": "distinct_sources",
                    "value": c["distinct_sources"],
                    "n_articles": c["n_articles"],
                    "place": c["place"],
                    "place_country": c["place_country"],
                    "place_kind": c["place_kind"],
                    "lat": c["lat"],
                    "lon": c["lon"],
                    "window_start": c["window_start"],
                    "window_end": c["window_end"],
                    "shared_origin_links": shared,
                    "shared_origin_examples": c["shared_origin_examples"],
                    "source_names": c["source_names"],
                    "clusters_total": found.get("clusters_total", 0),
                },
                method=c["method"],
                caveat=CONVERGENCE_CAVEAT,
                evidence=evidence,
                # The EXACT converging article set, so clicking the card opens the
                # analysis window over precisely these articles (not a re-run search).
                article_ids=list(c.get("article_ids", [])),
                n=c["n_articles"],
                key=f"{c['place_country'] or ''}|{c['place']}|{c['window_start']}",
                trigger=_trigger(
                    "Several of your sources mention the same place inside the same time "
                    "window. Things lining up in space and time is worth a look — but it "
                    "is never proof that one thing caused another.",
                    math_rows,
                ),
            )
        )
    return cards


def watch_matches(session) -> list[Card]:
    """Surface watches that recently FIRED as "watch" Lead cards (ruling #3, ON by default).

    A watch is a saved local condition (an FTS query + threshold + window) the user
    asked the engine to keep an eye on. When the corpus gained enough NEW matching
    articles, the engine fired and recorded it; this turns each recent firing into ONE
    Lead card whose exact article set the user can open. Counts only — the card states
    the real count + the user's own threshold, never a fabricated urgency or score.
    There are NO escalation tiers beyond this card (the ruling).
    """
    try:
        from src.analytics.watches import recent_fired_watches

        fired = recent_fired_watches(session)
    except Exception:  # noqa: BLE001 - a watch problem must never blank the feed
        _LOG.warning("watch-engine card pass failed", exc_info=True)
        return []

    cards: list[Card] = []
    for f in fired:
        n, new = f["n_articles"], f["new_articles"]
        cards.append(
            Card(
                type="watch_match",
                title=f"Watch “{f['name']}” matched",
                summary=(
                    f"Your watch for “{f['query']}” now matches {n} article(s) in its "
                    f"window ({new} new since it last fired). You asked to keep an eye "
                    "on this — open the set to read it."
                ),
                bucket="watch",
                signal={
                    "metric": "matching_articles",
                    "value": n,
                    "new_articles": new,
                    "query": f["query"],
                    "watch_id": f["id"],
                },
                method=(
                    "A saved local watch fired: the count of articles matching your "
                    "query in its recent window crossed the threshold you set, with new "
                    "evidence since it last fired. No score, no network."
                ),
                caveat=(
                    "A watch is a saved search reaching your own threshold — a prompt to "
                    "read, never a verdict that something happened or is important."
                ),
                # The EXACT firing set, so the card opens the analysis window over it.
                article_ids=list(f.get("article_ids", [])),
                n=n,
                key=str(f["id"]),
                trigger=_trigger(
                    "You saved a watch for this. The engine fires it when enough new "
                    "articles match the condition you set — it is your reminder to look, "
                    "nothing more.",
                    [
                        ("Articles matching the watch in its window", str(n)),
                        ("New since the watch last fired", str(new)),
                    ],
                ),
            )
        )
    return cards


_MAX_LAUNDERING = 4


def source_laundering(session) -> list[Card]:
    """Surface origins cited by many DISTINCT sources — apparent corroboration that
    isn't (manipulation-pattern card #6, ruling #13).

    Names a STRUCTURE, never intent: several sources citing one external origin are not
    independent confirmation (the anti-false-triangulation rule, surfaced proactively).
    Independence is measured by DISTINCT SOURCES (a chatty single source can't trip it);
    social/storefront origins are excluded; the innocent explanation (a widely-cited
    primary source looks identical) is stated beside the pattern. No score.
    """
    try:
        from src.analytics.laundering import LAUNDERING_CAVEAT, find_source_laundering

        found = find_source_laundering(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("source-laundering scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for c in found.get("clusters", [])[:_MAX_LAUNDERING]:
        dom = c["origin_domain"] or c["origin"]
        names = ", ".join(c["source_names"][:4]) + ("…" if len(c["source_names"]) > 4 else "")
        cards.append(
            Card(
                type="source_laundering",
                title=f"{c['distinct_sources']} sources, one origin: {dom}",
                summary=(
                    f"{c['n_articles']} articles from {c['distinct_sources']} distinct "
                    f"sources ({names}) all cite the same origin — apparent corroboration "
                    "that traces to ONE source. It may be a legitimate primary source, or a "
                    "single-origin claim dressed as consensus. Read the origin yourself."
                ),
                bucket="overtold",
                signal={
                    "metric": "distinct_sources",
                    "value": c["distinct_sources"],
                    "n_articles": c["n_articles"],
                    "origin": c["origin"],
                    "origin_domain": c["origin_domain"],
                    "source_names": c["source_names"],
                },
                method=found.get("method", ""),
                caveat=LAUNDERING_CAVEAT,
                # The exact citing-article set, so the card opens the analysis window over it.
                article_ids=list(c.get("article_ids", [])),
                n=c["n_articles"],
                key=c["origin"],
                trigger=_trigger(
                    "Several of your sources cite the very same origin for this. Lots of "
                    "coverage that all leans on one source is not independent confirmation — "
                    "it could be a perfectly good primary source, or one claim wearing many "
                    "hats. Read the origin and judge.",
                    [
                        ("Articles citing this origin", str(c["n_articles"])),
                        ("Distinct sources (the independence measure)", str(c["distinct_sources"])),
                        ("Minimum distinct sources for this Lead", f"≥ {found['min_sources']} ✓"),
                    ],
                ),
            )
        )
    return cards


_MAX_RECYCLED = 4


def recycled_claim(session) -> list[Card]:
    """Surface recent text that near-duplicates a much OLDER article — a claim
    resurfacing after dormancy (manipulation-pattern card, ruling #13).

    Names a STRUCTURE, never intent: the same text reappearing long after it first ran.
    The trigger is a measured time GAP (days), never a score; a single source recycling
    its own evergreen is flagged ``single_source``; the innocent explanations (anniversary
    piece, evergreen re-run, wire re-publish) are stated beside the pattern.
    """
    try:
        from src.analytics.recycled_claim import RECYCLED_CAVEAT, find_recycled_claims

        found = find_recycled_claims(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("recycled-claim scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for c in found.get("clusters", [])[:_MAX_RECYCLED]:
        title = c["recent_title"] or c["original_title"] or "(untitled)"
        if len(title) > 70:
            title = title[:67] + "…"
        spread = (
            f"across {c['distinct_sources']} sources"
            if not c["single_source"]
            else "by the same source"
        )
        cards.append(
            Card(
                type="recycled_claim",
                title=f"Resurfaced after {c['gap_days']} days: {title}",
                summary=(
                    f"Near-identical text first seen {c['first_seen']} reappeared "
                    f"{c['resurfaced']} ({spread}) — a {c['gap_days']}-day gap. It may be an "
                    "anniversary piece or an evergreen re-run, or old content recycled as "
                    "new. Read both and judge."
                ),
                bucket="watch",
                signal={
                    "metric": "gap_days",
                    "value": c["gap_days"],
                    "n_articles": c["n_articles"],
                    "distinct_sources": c["distinct_sources"],
                    "single_source": c["single_source"],
                    "first_seen": c["first_seen"],
                    "resurfaced": c["resurfaced"],
                    "sources": c["sources"],
                },
                method=found.get("method", ""),
                caveat=RECYCLED_CAVEAT,
                # The exact article set (old + recent), so the card opens the window over it.
                article_ids=list(c.get("article_ids", [])),
                n=c["n_articles"],
                key=f"recycled:{c['first_seen']}:{title}",
                trigger=_trigger(
                    "This reads almost word-for-word like something published much earlier. "
                    "Old text coming back is often innocent — an anniversary, an evergreen "
                    "re-run — but it can also be recycled to look like fresh news. Read both "
                    "and judge.",
                    [
                        ("Dormancy gap", f"{c['gap_days']} days"),
                        ("Articles in the cluster", str(c["n_articles"])),
                        (
                            "Spread",
                            "same source"
                            if c["single_source"]
                            else f"{c['distinct_sources']} distinct sources",
                        ),
                        ("Minimum gap for this Lead", f">= {found['min_gap_days']} days ✓"),
                    ],
                ),
            )
        )
    return cards


_MAX_HEADLINE_BODY = 4


def headline_body_mismatch(session) -> list[Card]:
    """Surface a RECENT article whose headline leads with content the body does not
    substantiate (manipulation-pattern card #7, ruling #13).

    Names a STRUCTURE, never intent: lexical divergence d_lex (headline content words
    vs the body's top words — language-agnostic) and, for English only, a headline-vs-
    body sentiment gap. The signal carries its COMPONENTS, never a clickbait score; the
    innocent twin (a summarising / metaphorical headline) is stated beside the pattern.
    """
    try:
        from src.analytics.headline_body import (
            HEADLINE_BODY_CAVEAT,
            find_headline_body_mismatch,
        )

        found = find_headline_body_mismatch(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("headline-body-mismatch scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_HEADLINE_BODY]:
        title = it["title"] or "(untitled)"
        if len(title) > 70:
            title = title[:67] + "…"
        absent = it.get("absent_terms", [])
        absent_str = ", ".join(absent[:4]) + ("…" if len(absent) > 4 else "")
        gap_clause = (
            f" Its tone also diverges (sentiment gap {it['sentiment_gap']})."
            if it.get("sentiment_gap") is not None
            and it["sentiment_gap"] >= found["sentiment_gap_min"]
            else ""
        )
        cards.append(
            Card(
                type="headline_body_mismatch",
                title=f"Headline ≠ body: {title}",
                summary=(
                    "The headline leads with terms the article body barely covers"
                    + (f" ({absent_str})" if absent_str else "")
                    + f" — lexical divergence {it['lexical_div']}.{gap_clause} A "
                    "summarising or metaphorical headline does this innocently. Read both "
                    "and judge."
                ),
                bucket="debunk",
                signal={
                    "metric": "lexical_div",
                    "value": it["lexical_div"],
                    "sentiment_gap": it.get("sentiment_gap"),
                    "lang": it.get("lang"),
                    "absent_terms": absent,
                    "n_absent": len(absent),
                },
                method=found.get("method", ""),
                caveat=HEADLINE_BODY_CAVEAT,
                # article = corpus of 1: the card opens the analysis window over it.
                article_ids=[it["article_id"]],
                n=1,
                key=f"hbmismatch:{it['article_id']}",
                trigger=_trigger(
                    "The headline names things the article itself barely discusses. A "
                    "summarising or metaphorical headline does this innocently — but it is "
                    "also how a misleading headline works. Read both and judge.",
                    [
                        ("Lexical divergence", f"{it['lexical_div']} (>= {found['d_min']} fires)"),
                        (
                            "Sentiment gap (English only)",
                            str(it["sentiment_gap"]) if it.get("sentiment_gap") is not None else "—",
                        ),
                        ("Headline terms absent from the body", absent_str or "—"),
                        ("Language", it.get("lang") or "unknown"),
                    ],
                ),
            )
        )
    return cards


_MAX_EMERGENCE = 4


def manufactured_emergence(session) -> list[Card]:
    """Surface a NEW keyword that appeared wide-and-sudden across many sources with NO
    datable anchor (manipulation-pattern card #3, ruling #13; the full anchor-gated form).

    Names a STRUCTURE, never intent: born-wide independence is distinct SOURCES (a chatty
    source can't manufacture it); the anchor gate suppresses genuine breaking news (which
    leaves a datable trace); the innocent twin + the false-negative caveat are stated.
    """
    try:
        from src.analytics.emergence import EMERGENCE_CAVEAT, find_manufactured_emergence

        found = find_manufactured_emergence(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("manufactured-emergence scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_EMERGENCE]:
        term = it["term"]
        cards.append(
            Card(
                type="manufactured_emergence",
                title=f"Appeared everywhere at once: “{term}”",
                summary=(
                    f"“{term}” has almost no prior history yet showed up in "
                    f"{it['recent_articles']} articles across {it['recent_sources']} distinct "
                    "sources at once, and the articles cite no datable event to anchor it. "
                    "Breaking news also appears wide and fast — but usually with a datable "
                    "trigger. Read the sources and judge."
                ),
                bucket="rising",
                signal={
                    "metric": "recent_sources",
                    "value": it["recent_sources"],
                    "recent_articles": it["recent_articles"],
                    "prior_count": it["prior_count"],
                    "anchored": it["anchored"],
                },
                method=found.get("method", ""),
                caveat=EMERGENCE_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["recent_articles"],
                key=f"emergence:{term}",
                trigger=_trigger(
                    "A term with almost no past suddenly turned up across many separate "
                    "sources, and none of the articles points to a datable event behind it. "
                    "Real breaking news does this too — but it usually has a datable trigger; "
                    "an anchor-less one is worth a look. Read the sources and judge.",
                    [
                        ("Distinct sources (born wide)", str(it["recent_sources"])),
                        ("Recent articles", str(it["recent_articles"])),
                        ("Prior-period mentions", f"{it['prior_count']} (≈ new)"),
                        ("Datable anchor near onset", "none found"),
                        ("Minimum sources to surface", f">= {found['min_sources']} ✓"),
                    ],
                ),
            )
        )
    return cards


_MAX_FLOOD = 4


def flooded_topic(session) -> list[Card]:
    """Surface a SOURCE flooding a single topic far above its OWN history
    (manipulation-pattern card #4, ruling #13 + Q8 — the flood half).

    Names a STRUCTURE, never intent: the comparison is the source's own prior share
    (a two-proportion z-test), so a source that always covers a beat heavily does not
    flag; the innocent twin (volume is not importance) is stated; no score.
    """
    try:
        from src.analytics.concentration import FLOOD_CAVEAT, find_flooded_topics

        found = find_flooded_topics(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("flood scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_FLOOD]:
        pct_now = round(100 * it["share_now"])
        pct_base = round(100 * it["baseline_share"])
        cards.append(
            Card(
                type="flooded_topic",
                title=f"{it['source']} is flooding “{it['term']}”",
                summary=(
                    f"{it['source']} gave {pct_now}% of its recent coverage to "
                    f"“{it['term']}” ({it['recent_articles']} of {it['recent_total']} "
                    f"articles), vs {pct_base}% historically. Volume isn't importance — a "
                    "big story legitimately dominates — so read it and judge."
                ),
                bucket="overtold",
                signal={
                    "metric": "share_zscore",
                    "value": it["share_zscore"],
                    "share_now": it["share_now"],
                    "baseline_share": it["baseline_share"],
                    "recent_articles": it["recent_articles"],
                    "recent_total": it["recent_total"],
                    "source": it["source"],
                },
                method=found.get("method", ""),
                caveat=FLOOD_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["recent_articles"],
                key=f"flood:{it['source_id']}:{it['term']}",
                trigger=_trigger(
                    "One source is giving an unusually large slice of its recent coverage to "
                    "a single topic, far above its own past. A genuinely big story does this "
                    "too — volume is not importance — so read it and judge.",
                    [
                        ("Recent share of this source's coverage", f"{pct_now}%"),
                        ("Its historical share", f"{pct_base}%"),
                        ("Jump (two-proportion z)", str(it["share_zscore"])),
                        ("Recent articles on the topic", f"{it['recent_articles']} of {it['recent_total']}"),
                    ],
                ),
            )
        )
    return cards


_MAX_COPYPASTA = 4


def copypasta(session) -> list[Card]:
    """Surface verbatim text copied across many DISTINCT sources in articles that are NOT
    whole duplicates — a coordinated talking point / copypasta (manipulation-pattern card).

    Names a STRUCTURE, never intent: independence is distinct SOURCES (not article count);
    spans whose whole articles are near-dups across that many sources are EXCLUDED as wire
    republish (that is echo_chamber's job); the innocent twin (a shared quote / press-release
    line / boilerplate) is stated beside the pattern. No score.
    """
    try:
        from src.analytics.copypasta import COPYPASTA_CAVEAT, find_copypasta

        found = find_copypasta(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("copypasta scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_COPYPASTA]:
        phrase = it["phrase"]
        shown = phrase if len(phrase) <= 80 else phrase[:77] + "…"
        cards.append(
            Card(
                type="copypasta",
                title=f"Identical wording in {it['distinct_sources']} sources: “{shown}”",
                summary=(
                    f"The verbatim phrase “{shown}” appears in {it['n_articles']} articles "
                    f"across {it['distinct_sources']} distinct sources whose full articles are "
                    "not duplicates of one another. A shared quote, press-release line or "
                    "boilerplate does this innocently — read them and judge."
                ),
                bucket="overtold",
                signal={
                    "metric": "distinct_sources",
                    "value": it["distinct_sources"],
                    "n_articles": it["n_articles"],
                    "n_words": it["n_words"],
                    "sources": it["sources"],
                },
                method=found.get("method", ""),
                caveat=COPYPASTA_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["n_articles"],
                key=f"copypasta:{phrase[:60]}",
                trigger=_trigger(
                    "The exact same sentence turns up word-for-word across several separate "
                    "sources, in articles that are otherwise different. A shared quote, a "
                    "press-release line or common boilerplate explains most of these — but it "
                    "is also how a coordinated talking point spreads. Read them and judge.",
                    [
                        ("Distinct sources sharing the phrase", str(it["distinct_sources"])),
                        ("Articles", str(it["n_articles"])),
                        ("Phrase length", f"{it['n_words']} words"),
                        ("Whole-article wire republish", "excluded ✓"),
                    ],
                ),
            )
        )
    return cards


_MAX_BURY = 4


def buried_topic(session) -> list[Card]:
    """Surface a SOURCE under-covering a topic that is big across the rest of the corpus
    (manipulation-pattern card #4 — the BURY half, the inverse of flooded_topic).

    Names a STRUCTURE, never intent: a two-proportion z-test of the source's share of the
    topic vs the rest-of-corpus share, over a family of (source, topic) pairs corrected with
    Benjamini-Hochberg FDR (so the many comparisons cannot manufacture a finding). The
    overwhelming innocent explanation — specialization (a different beat/region/language) —
    is stated; no score.
    """
    try:
        from src.analytics.concentration import BURY_CAVEAT, find_buried_topics

        found = find_buried_topics(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("bury scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_BURY]:
        pct_src = round(100 * it["source_share"], 1)
        pct_corpus = round(100 * it["corpus_share"], 1)
        cards.append(
            Card(
                type="buried_topic",
                title=f"{it['source']} under-covers “{it['term']}”",
                summary=(
                    f"{it['source']} gave {pct_src}% of its coverage to “{it['term']}” "
                    f"({it['source_articles_on_topic']} of {it['source_total']} articles), vs "
                    f"{pct_corpus}% across the rest of the corpus. A different beat, region or "
                    "language usually explains a low share — read it and judge."
                ),
                bucket="investigate",
                signal={
                    "metric": "gap_zscore",
                    "value": it["gap_zscore"],
                    "source_share": it["source_share"],
                    "corpus_share": it["corpus_share"],
                    "source_articles_on_topic": it["source_articles_on_topic"],
                    "source_total": it["source_total"],
                    "corpus_articles_on_topic": it["corpus_articles_on_topic"],
                    "fdr_qvalue": it["fdr_qvalue"],
                    "source": it["source"],
                },
                method=found.get("method", ""),
                caveat=BURY_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["source_total"],
                key=f"bury:{it['source_id']}:{it['term']}",
                trigger=_trigger(
                    "One source covered a widely-covered topic far below where the rest of the "
                    "corpus sits. Specialization — a different beat, region or language — "
                    "explains most low shares, so this is a shape to look at, never a claim it "
                    "was deliberate. It survived multiple-testing correction. Read it and judge.",
                    [
                        ("This source's share of the topic", f"{pct_src}%"),
                        ("The rest of the corpus's share", f"{pct_corpus}%"),
                        ("Gap (two-proportion z, below)", str(it["gap_zscore"])),
                        ("On the topic", f"{it['source_articles_on_topic']} of {it['source_total']}"),
                        ("FDR-adjusted q-value", str(it["fdr_qvalue"])),
                    ],
                ),
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Severity-tiered LOCAL alert layer (info / watch / urgent) — Cards batch E.
#  A transparent rule over real, locally-cached signals: hazard records (the
#  provider's OWN severity), fired local watches, recent space-time convergences.
#  NO network, NO notifications, NO fabricated urgency (src/analytics/alerts.py).
# --------------------------------------------------------------------------- #
_TIER_LABELS = {"urgent": "Urgent", "watch": "Watch", "info": "Info"}
_TIER_PLAIN = {
    "urgent": (
        "A hazard provider itself declared a RED alert here. That is the provider's own "
        "top severity — this layer never invents urgency. Read it and judge."
    ),
    "watch": (
        "Signals worth keeping an eye on: a hazard provider's ORANGE alert, or a watch you "
        "saved that crossed the threshold YOU set. Not urgent — a prompt to look."
    ),
    "info": (
        "Informational signals: a hazard provider's GREEN alert, a relayed observation, or "
        "a recent space-time convergence in your corpus (a co-occurrence prompt, not proof)."
    ),
}


def severity_alerts(session) -> list[Card]:
    """Info/watch/urgent Home banner from LOCAL alert signals — one card per active tier.

    Aggregates hazard records (from the local snapshot — never the network), fired local
    watches, and recent space-time convergences into transparent severity tiers. 'Urgent'
    is ONLY ever a provider-declared red hazard alert; nothing is a fabricated urgency, and
    no figure is a score. Degrades to [] when there is nothing to show."""
    try:
        from src.analytics.alerts import ALERT_CAVEAT, ALERT_METHOD, compute_alerts

        alerts = compute_alerts(session)
    except Exception:  # noqa: BLE001 - an alert-scan problem must never blank the feed
        _LOG.warning("severity-alert scan failed", exc_info=True)
        return []

    tiers = alerts.get("tiers", {})
    cards: list[Card] = []
    for tier in ("urgent", "watch", "info"):  # most severe first
        data = tiers.get(tier) or {}
        count = int(data.get("count", 0))
        if not count:
            continue
        hazards = data.get("hazards", [])
        watches = data.get("watches", [])
        convergences = data.get("convergences", [])
        n_haz, n_watch, n_conv = len(hazards), len(watches), len(convergences)
        parts = []
        if n_haz:
            parts.append(f"{n_haz} hazard alert(s)")
        if n_watch:
            parts.append(f"{n_watch} fired watch(es)")
        if n_conv:
            parts.append(f"{n_conv} space-time convergence(s)")
        evidence: list[dict] = []
        for h in hazards[:4]:
            evidence.append(
                {
                    "title": h.get("title") or h.get("type") or "hazard alert",
                    "url": h.get("url"),
                    "source": (str(h.get("source") or "").upper() or None),
                    "published_at": h.get("time"),
                }
            )
        for w in watches[:4]:
            evidence.append({"title": f"Watch: {w.get('name')}", "url": "/#home", "source": None})
        for c in convergences[:4]:
            place = c.get("place") or "a place"
            evidence.append(
                {"title": f"Convergence: {place} ({c.get('window_start')})", "url": None, "source": None}
            )
        stale_note = (
            " Hazard records are a cached relay and may be stale." if alerts.get("hazards_stale") else ""
        )
        cards.append(
            Card(
                type="severity_alert",
                title=f"{_TIER_LABELS[tier]}: {count} alert signal(s)",
                summary=(f"{_TIER_LABELS[tier]}: {', '.join(parts)} in view." + stale_note),
                bucket="watch",
                signal={
                    "metric": "signals_in_tier",
                    "value": count,
                    "tier": tier,
                    "hazards": n_haz,
                    "watches": n_watch,
                    "convergences": n_conv,
                    "hazards_stale": bool(alerts.get("hazards_stale")),
                    "hazards_as_of": alerts.get("hazards_as_of"),
                },
                method=ALERT_METHOD,
                caveat=ALERT_CAVEAT,
                evidence=evidence,
                # The corpus article ids behind the tier's watch/convergence evidence
                # (hazard records are external feed items, not corpus articles).
                article_ids=list(data.get("article_ids", [])),
                n=count,
                key=f"alert:{tier}",
                trigger=_trigger(
                    _TIER_PLAIN[tier],
                    [
                        ("Signals in this tier", str(count)),
                        ("From hazard provider alerts", str(n_haz)),
                        ("From watches you saved", str(n_watch)),
                        ("From space-time convergences", str(n_conv)),
                    ],
                ),
            )
        )
    return cards


_MAX_DISPUTED = 4


def disputed_chronology(session) -> list[Card]:
    """Surface a near-identical STORY dated differently across DISTINCT sources
    (Cards batch E). Names a SHAPE — sources disagree on WHEN — never a verdict; the
    innocent twins (date-extraction ambiguity, a timeline piece, an update date) ride the
    caveat, and independence is measured by distinct sources. Dates are deduced, never
    confirmed. No score."""
    try:
        from src.analytics.disputed_chronology import (
            DISPUTED_CAVEAT,
            find_disputed_chronology,
        )

        found = find_disputed_chronology(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("disputed-chronology scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_DISPUTED]:
        dates = it["disputed_dates"]
        cards.append(
            Card(
                type="disputed_chronology",
                title=f"Same story, {it['distinct_dates']} conflicting event dates",
                summary=(
                    f"{it['distinct_sources']} sources tell a near-identical story but date "
                    f"the event differently ({', '.join(dates)}) — the conflicting dates span "
                    f"{it['span_days']} days. Date-extraction quirks or a timeline piece can "
                    "explain it; read both and judge."
                ),
                bucket="debunk",
                signal={
                    "metric": "disputed_dates",
                    "value": it["distinct_dates"],
                    "span_days": it["span_days"],
                    "distinct_sources": it["distinct_sources"],
                    "dates": dates,
                    "sources": it["sources"],
                    "dates_by_source": it["dates_by_source"],
                },
                method=found.get("method", ""),
                caveat=DISPUTED_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["n_articles"],
                key=f"disputed:{'|'.join(dates)}:{it['article_ids'][0] if it['article_ids'] else ''}",
                trigger=_trigger(
                    "Several of your sources tell what is clearly the same story but put the "
                    "event on different dates. That is worth a look — though a date-extraction "
                    "quirk, a timeline article, or an update date can all explain it. Read "
                    "both and judge.",
                    [
                        ("Conflicting event dates", ", ".join(dates)),
                        ("Distinct sources disagreeing", str(it["distinct_sources"])),
                        ("Span of the conflicting dates", f"{it['span_days']} days"),
                        ("Story text similarity (Jaccard)", f"{it['avg_similarity']:.2f}"),
                    ],
                ),
            )
        )
    return cards


_MAX_PROPAGATION = 4


def story_propagation(session) -> list[Card]:
    """Surface the TEMPORAL cascade of a topic across DISTINCT sources (Cards batch E).
    Names a SHAPE — who carried it first, then the sequence over time — never an origin or
    a cause (a shared wire or independent coverage look identical). Efficient: reads the
    denormalised keyword_mentions only. No score."""
    try:
        from src.analytics.story_propagation import (
            STORY_PROPAGATION_CAVEAT,
            find_story_propagation,
        )

        found = find_story_propagation(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("story-propagation scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_PROPAGATION]:
        cascade = it["cascade"]
        cards.append(
            Card(
                type="story_propagation",
                title=f"“{it['term']}” spread across {it['distinct_sources']} sources",
                summary=(
                    f"Coverage of “{it['term']}” propagated across {it['distinct_sources']} "
                    f"sources over {it['span_days']} days, first carried by "
                    f"{it['first_source']} on {it['first_seen']}. A shared wire or "
                    "independent coverage can look the same — a shape to read, never a cause."
                ),
                bucket="context",
                signal={
                    "metric": "distinct_sources",
                    "value": it["distinct_sources"],
                    "span_days": it["span_days"],
                    "first_source": it["first_source"],
                    "first_seen": it["first_seen"],
                    "cascade": cascade,
                },
                method=found.get("method", ""),
                caveat=STORY_PROPAGATION_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["n_articles"],
                key=f"propagation:{it['keyword_id']}:{it['first_seen']}",
                trigger=_trigger(
                    "A topic showed up in one source first, then rippled out to others over "
                    "the following days. That spread is a shape to read — a shared newswire or "
                    "independent coverage both look like this, and it is never proof of a cause.",
                    [
                        ("Distinct sources reached", str(it["distinct_sources"])),
                        ("Days from first to last source", str(it["span_days"])),
                        ("First carried by", f"{it['first_source']} ({it['first_seen']})"),
                        ("Sources in the cascade", str(len(cascade))),
                    ],
                ),
            )
        )
    return cards


_MAX_RIPPLE = 4


def supply_chain_ripple(session) -> list[Card]:
    """Surface a commodity/keyword coverage CO-MOVEMENT (Cards batch E). Names a SHAPE —
    two topics whose daily coverage rises and falls together — CO-OCCURRENCE, NEVER
    causation. The pair family is FDR-corrected so many comparisons cannot manufacture it;
    the signal carries its components (r, p, adjusted q, n), never a score."""
    try:
        from src.analytics.supply_chain_ripple import (
            SUPPLY_CHAIN_CAVEAT,
            find_supply_chain_ripples,
        )

        found = find_supply_chain_ripples(session)
    except Exception:  # noqa: BLE001 - a scan problem must never blank the feed
        _LOG.warning("supply-chain-ripple scan failed", exc_info=True)
        return []

    cards: list[Card] = []
    for it in found.get("items", [])[:_MAX_RIPPLE]:
        cards.append(
            Card(
                type="supply_chain_ripple",
                title=f"{it['commodity']} coverage co-moves with “{it['keyword']}”",
                summary=(
                    f"Daily coverage of {it['commodity']} and “{it['keyword']}” rise and fall "
                    f"together (r={it['correlation']:+.2f}, p={it['p_value']:.3g}, over "
                    f"{it['n_days']} days) — a co-movement to investigate, never proof one "
                    "drives the other."
                ),
                bucket="context",
                signal={
                    "metric": "coverage_correlation",
                    "value": it["correlation"],
                    "p_value": it["p_value"],
                    "fdr_qvalue": it["fdr_qvalue"],
                    "n_days": it["n_days"],
                    "commodity": it["commodity"],
                    "keyword": it["keyword"],
                },
                method=found.get("method", ""),
                caveat=SUPPLY_CHAIN_CAVEAT,
                article_ids=list(it.get("article_ids", [])),
                n=it["n_articles"],
                key=f"ripple:{it['commodity_keyword_id']}:{it['keyword_id']}",
                trigger=_trigger(
                    "When this commodity is in the news more, another topic tends to be too, "
                    "and when one quiets down so does the other. That co-movement is worth a "
                    "look — but coverage moving together is never proof one causes the other.",
                    [
                        ("Correlation of daily coverage (r)", f"{it['correlation']:+.2f}"),
                        ("How likely by chance (p, before FDR)", f"{it['p_value']:.3g}"),
                        ("FDR-adjusted q-value", str(it["fdr_qvalue"])),
                        ("Days of coverage compared", str(it["n_days"])),
                    ],
                ),
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  S6.4 — the two attention producers the board was missing.
# --------------------------------------------------------------------------- #
def on_the_horizon(session, *, today: "date | None" = None, events=None) -> list[Card]:
    """Upcoming agenda dates that touch a topic currently MOVING in the corpus — a heads-up,
    never a forecast. An agenda event (scheduled or deduced) whose title/tags contain a
    currently-trending keyword. Counts only, no score; the link is lexical (the keyword
    appears in the event), never causal. Bucket ``watch`` — NEVER an urgent alert.

    ``today`` / ``events`` are injectable for deterministic tests; by default it reads the
    real agenda catalog for today."""
    from datetime import date, timedelta

    from src.analytics import queries as q
    from src.events import catalog

    today = today or date.today()
    horizon = (today + timedelta(days=45)).isoformat()
    all_events = catalog.agenda(today=today) if events is None else events
    events = [
        e
        for e in all_events
        if e.get("next_occurrence") and e["next_occurrence"] <= horizon
    ]
    if not events:
        return []
    terms = {
        t["term"].lower(): t
        for t in q.trending(session, limit=30).get("terms", [])
        if len(t.get("term", "")) >= 4
    }
    if not terms:
        return []
    cards: list[Card] = []
    seen: set[str] = set()
    for e in events:
        hay = ((e.get("title") or "") + " " + " ".join(e.get("tags") or [])).lower()
        hit = next((t for term_l, t in terms.items() if term_l in hay), None)
        if hit is None:
            continue
        key = (e.get("title") or "")[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        days = (date.fromisoformat(e["next_occurrence"]) - today).days
        cards.append(
            Card(
                type="on_the_horizon",
                title=f"On the horizon: {e['title']}",
                summary=(
                    f"“{hit['term']}” — moving in your corpus now — has an agenda date on "
                    f"{e['next_occurrence']} ({days} days away): {e['title']}."
                ),
                bucket="watch",
                signal={
                    "metric": "days_until",
                    "value": days,
                    "term": hit["term"],
                    "recent": hit.get("recent"),
                },
                trigger=_trigger(
                    "An upcoming date in your agenda touches a topic that is currently moving "
                    "in the articles you collected — a prompt to prepare, never a prediction "
                    "that anything will happen.",
                    [
                        ("Event date", e["next_occurrence"]),
                        ("Days away", str(days)),
                        ("Matched trending term", f"“{hit['term']}”"),
                    ],
                ),
                method=(
                    "An agenda event whose title/tags contain a currently-trending corpus "
                    "keyword (a lexical match). Counts only, no score."
                ),
                caveat=(
                    "An agenda date is scheduled or deduced, never a forecast; the link is "
                    "that the keyword appears in the event, not that one causes the other."
                ),
                n=len(events),
                key=hit.get("normalized") or hit["term"],
            )
        )
        if len(cards) >= 4:
            break
    return cards


def through_time(session, *, today: "date | None" = None) -> list[Card]:
    """An anniversary LENS: articles the corpus holds that were published on TODAY's calendar
    date in earlier years — a way to revisit how a day was covered over time. Counts only, no
    score; cross-time recall is SACRED, so this is a lens, NEVER a reweighting of the corpus
    toward the past. A shared calendar date is a coincidence, not a connection. ``today`` is
    injectable for deterministic tests."""
    from datetime import date

    from sqlalchemy import func

    today = today or date.today()
    md = f"{today.month:02d}-{today.day:02d}"
    # A background-refresh producer (not a hot request path): the month-day match is a
    # strftime scan. Bounded by the limit; past years only (never the current year).
    rows = (
        session.query(Article, Source.name)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.published_at.isnot(None))
        .filter(func.strftime("%m-%d", Article.published_at) == md)
        .filter(func.strftime("%Y", Article.published_at) < str(today.year))
        .order_by(Article.published_at.desc())
        .limit(40)
        .all()
    )
    if len(rows) < 3:  # honest floor — too few for an anniversary lens
        return []
    years = sorted({a.published_at.year for a, _ in rows}, reverse=True)
    ids = [a.id for a, _ in rows]
    return [
        Card(
            type="through_time",
            title="Through time: this day in past years",
            summary=(
                f"{len(rows)} articles in your corpus were published on {today.strftime('%B')} "
                f"{today.day} in earlier years ({years[-1]}–{years[0]})."
            ),
            bucket="context",
            signal={"metric": "articles_on_this_day", "value": len(rows), "years": years},
            article_ids=ids,
            trigger=_trigger(
                "Articles you collected that were published on today's calendar date in "
                "earlier years — a way to revisit how a day was covered. A calendar "
                "coincidence, never a claim the stories are related.",
                [
                    ("Today", today.isoformat()),
                    ("Matching articles", str(len(rows))),
                    ("Years spanned", f"{years[-1]}–{years[0]}"),
                ],
            ),
            method=(
                "Articles whose publication date falls on today's month-and-day in a prior "
                "year. Counts only, no score."
            ),
            caveat=(
                "Publication dates can be imprecise or missing, and a shared calendar date is "
                "a coincidence, not a connection. Cross-time recall is sacred: this is a lens, "
                "never a reweighting."
            ),
            n=len(rows),
            key=md,
            evidence=_evidence_from_articles(rows),
        )
    ]


_DEFAULT_PRODUCERS = (
    ("rising_now", rising_now),
    ("framing_split", framing_split),
    ("record_reshaped", record_reshaped),
    ("price_narrative", price_narrative),
    ("stale_data", stale_data),
    ("diet_self_audit", diet_self_audit),
    ("echo_chamber", echo_chamber),
    ("lonely_signal", lonely_signal),
    ("capacity_implausible", capacity_implausible),
    ("emotion_profile", emotion_profile_card),
    ("ip_litigation_pulse", ip_litigation_pulse),
    ("ownership_change", ownership_change),
    ("law_change", law_change),
    ("model_legislation", model_legislation),
    ("story_lineage", story_lineage),
    ("coverage_advisor", coverage_advisor),
    # Registered last (fail-safe order): the newest producer must never cost
    # the operator the established feed.
    ("weather_corroboration", weather_corroboration),
    ("space_time_convergence", space_time_convergence),
    ("watch_matches", watch_matches),
    ("source_laundering", source_laundering),
    ("recycled_claim", recycled_claim),
    ("headline_body_mismatch", headline_body_mismatch),
    ("manufactured_emergence", manufactured_emergence),
    ("flooded_topic", flooded_topic),
    ("buried_topic", buried_topic),
    ("copypasta", copypasta),
    # Cards batch E (registered last — fail-safe order): a new producer must never
    # cost the operator the established feed if it misbehaves.
    ("severity_alerts", severity_alerts),
    ("disputed_chronology", disputed_chronology),
    ("story_propagation", story_propagation),
    ("supply_chain_ripple", supply_chain_ripple),
    # S6.4 — attention producers (registered last, fail-safe): a heads-up + an anniversary
    # lens. Buckets watch/context; NEVER promoted into an urgent alert (the ruled boundary).
    ("on_the_horizon", on_the_horizon),
    ("through_time", through_time),
)


def register_default_producers() -> None:
    """Register the Briefing v0 producers (idempotent).

    FAIL-SAFE BY ORDER (CLAUDE.md: Home must never go blank): the core
    producers register FIRST; the recipe pack is additive and any problem in it
    must never cost the operator the whole briefing.
    """
    from src.briefing.registry import register

    for name, producer in _DEFAULT_PRODUCERS:
        register(name, producer)
    try:
        # Investigation-recipe producers (0.0.8 WP8 / RM-20) -- space-time
        # scenario cards with a one-click /investigate deep-link.
        from src.briefing.recipes import RECIPE_PRODUCERS

        for name, producer in RECIPE_PRODUCERS:
            register(name, producer)
    except Exception:  # noqa: BLE001 - additive pack must not kill the core feed
        import logging

        logging.getLogger(__name__).warning(
            "recipe producers failed to register; core briefing continues", exc_info=True
        )
