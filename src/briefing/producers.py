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
        .filter(Article.id.in_(int_ids)).all()
    )
    return {str(a.id): {"title": a.title, "url": a.url, "source": name,
                        "published_at": a.published_at.isoformat() if a.published_at else None}
            for a, name in rows}


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
        rep_ids = [ev.representative for ev in actor.events][:4]
        ev_lookup = _articles_by_id(session, rep_ids)
        evidence = [ev_lookup[i] for i in rep_ids if i in ev_lookup]
        n = len(actor.sources)
        summary = (f"{n} sources published near-identical text on {actor.shared_stories} "
                   f"story(ies)" + (f", sharing host {actor.shared_hosts[0]}" if actor.shared_hosts else "")
                   + (". You have collapsed this into one actor." if applied
                      else ". Apply a collapse to count it as one voice, or expand to inspect."))
        cards.append(Card(
            type="echo_chamber",
            title=(f"{n} sources moving in lockstep" if not applied
                   else f"Coordinated actor ({n} sources) — collapsed"),
            summary=summary,
            bucket="overtold",
            signal={"metric": "coordinated_sources", "value": n,
                    "shared_stories": actor.shared_stories, "signature": sig,
                    "sources": actor.sources, "shared_hosts": actor.shared_hosts,
                    "median_span_hours": actor.median_span_hours, "collapse_applied": applied},
            method=result.method,
            caveat=result.caveat,
            evidence=evidence,
            n=n,
            key=sig or ",".join(actor.sources),
        ))
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
        cards.append(Card(
            type="lonely_signal",
            title=f"Single-source: “{story['title'][:80]}”",
            summary=(f"Only {story['sources'][0] if story['sources'] else 'one source'} carried this; "
                     "no other source published near-identical text. It could be an exclusive — or minor."),
            bucket="undertold",
            signal={"metric": "voices", "value": 1, "source": story["sources"][0] if story["sources"] else None},
            method="A near-duplicate story cluster of size 1 (one source, no echo) over the recent window.",
            caveat=("‘Single-source, did not echo’ is the ONLY claim — not that it is important, true, or "
                    "suppressed. Many minor items are single-source. Read it and judge."),
            evidence=evidence,
            n=1,
            key=f"lonely:{story['representative']}",
        ))
    return cards


# --------------------------------------------------------------------------- #
#  Capacity implausible — output rate far above the corpus norm (§6 B)
# --------------------------------------------------------------------------- #
_CAPACITY_DAYS = 14
_CAPACITY_MIN_PER_DAY = 20      # absolute floor before we even ask the question
_CAPACITY_FACTOR = 8.0          # and well above the corpus median


def capacity_implausible(session) -> list[Card]:
    """Sources whose article rate is implausibly high vs the corpus — a question, never
    a verdict of automation (a wire agency or big newsroom can be legitimately prolific)."""
    cutoff = datetime.now(UTC) - timedelta(days=_CAPACITY_DAYS)
    rows = (
        session.query(Source.name, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .group_by(Source.id).all()
    )
    if len(rows) < 3:
        return []
    rates = {name or "(unknown)": c / _CAPACITY_DAYS for name, c in rows}
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
    return [Card(
        type="capacity_implausible",
        title=f"{len(flagged)} source(s) publishing unusually fast",
        summary=(f"{top['source']} averaged ~{top['per_day']}/day over {_CAPACITY_DAYS}d — "
                 f"≥{_CAPACITY_FACTOR:.0f}× the corpus median ({round(median,2)}/day)."),
        bucket="investigate",
        signal={"metric": "max_articles_per_day", "value": top["per_day"],
                "corpus_median_per_day": round(median, 2), "flagged": flagged[:20]},
        method=(f"Sources whose articles/day over {_CAPACITY_DAYS}d is ≥ {_CAPACITY_MIN_PER_DAY} and "
                f"≥ {_CAPACITY_FACTOR:.0f}× the corpus median per-source rate."),
        caveat=("High output is often legitimate (wire agencies, large newsrooms, aggregators). This "
                "is a capacity *question* for a human, never a determination that a source is automated."),
        evidence=[{"title": "Sources — review output", "url": "/#sources", "source": None}],
        n=len(flagged),
        key="capacity",
    )]


# --------------------------------------------------------------------------- #
#  Emotion profile — emotion categories around a trending term (§4; new lexicon)
# --------------------------------------------------------------------------- #
def emotion_profile_card(session) -> list[Card]:
    """Emotion-category word-pattern around the top trending term (degrades loudly if
    no lexicon). A pattern to read, never a label that an outlet is 'fearmongering'."""
    from src.analytics import queries as q
    from src.awareness.emotion import emotion_profile

    trending = q.trending(session, limit=1).get("terms", [])
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
    return [Card(
        type="emotion_profile",
        title=f"“{term['term']}”: coverage skews {prof['dominant']}",
        summary=(f"Across {prof['n_snippets']} context windows around “{term['term']}”, "
                 f"{prof['dominant']}-associated words are the most frequent "
                 f"({prof['categories'][prof['dominant']]} of {prof['total_hits']} hits)."),
        bucket="context",
        signal={"metric": "dominant_emotion", "value": prof["dominant"],
                "categories": prof["categories"], "lexicon": prof["lexicon_source"]},
        method=prof["method"],
        caveat=prof["caveat"],
        evidence=_evidence_from_articles(
            _articles_for_term(session, resolve_keyword(session, term["term"]).id, days=21, limit=4)
            if resolve_keyword(session, term["term"]) else []),
        n=prof["total_hits"],
        key=f"emotion:{term['normalized']}",
    )]


# --------------------------------------------------------------------------- #
#  IP / legal news cards (§4) — thin: trends + deal verbs over the NEWS corpus
# --------------------------------------------------------------------------- #
_IP_TERMS = {
    "patent", "patents", "lawsuit", "lawsuits", "injunction", "infringement",
    "licensing", "antitrust", "copyright", "trademark", "litigation", "settlement",
}
_DEAL_RE = re.compile(
    r"\b(acquir\w+|merg\w+|takeover|buyout|divest\w+|sold to|sells? to|"
    r"acquisition|stake in|controlling stake)\b", re.IGNORECASE)
_MAX_DEAL = 4
_IP_DAYS = 30


def ip_litigation_pulse(session) -> list[Card]:
    """Surface rising IP/legal terms in the news (a pulse, not a verdict)."""
    from src.analytics import queries as q

    rising = q.trending(session, limit=50).get("terms", [])
    hits = [t for t in rising if t["normalized"] in _IP_TERMS]
    if not hits:
        return []
    top = max(hits, key=lambda t: t["growth"])
    kw = resolve_keyword(session, top["term"])
    rows = _articles_for_term(session, kw.id, days=_IP_DAYS, limit=6) if kw else []
    names = ", ".join(sorted({t["term"] for t in hits}))
    return [Card(
        type="ip_litigation_pulse",
        title="IP / legal terms are rising",
        summary=(f"IP/legal vocabulary is trending in your corpus ({names}); “{top['term']}” "
                 f"is up ~{top['growth']}× vs the prior period."),
        bucket="context",
        signal={"metric": "ip_terms_rising", "value": len(hits),
                "terms": [t["term"] for t in hits], "top": top["term"]},
        method="trending IP/legal terms (recent-vs-prior ratio) over the news corpus",
        caveat=("Measures *coverage* of IP/legal language, not the merits of any case. The tool "
                "sees reporting about filings, not the filings themselves."),
        evidence=_evidence_from_articles(rows),
        n=len(hits),
        key="ip-pulse",
    )]


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
    evidence = [{"title": a.title, "url": a.url, "source": name,
                 "published_at": a.published_at.isoformat() if a.published_at else None}
                for a, name in matches]
    lead = matches[0][0].title or "(untitled)"
    return [Card(
        type="ownership_change",
        title=f"{len(matches)} possible ownership-change report(s)",
        summary=(f"Recent articles use deal language (acquired / merger / divested), e.g. "
                 f"“{lead[:80]}”. Candidate corporate-control stories to verify."),
        bucket="investigate",
        signal={"metric": "deal_reports", "value": len(matches)},
        method="recent articles whose text matches acquisition/merger/divestiture verbs",
        caveat=("Matches *reporting language*, not confirmed deals — and never asserts IP was "
                "transferred or stripped. Foreground the primary filing; the human confirms."),
        evidence=evidence,
        n=len(matches),
        key="ownership-change",
    )]


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
)


def register_default_producers() -> None:
    """Register the Briefing v0 producers (idempotent)."""
    from src.briefing.registry import register

    for name, producer in _DEFAULT_PRODUCERS:
        register(name, producer)
