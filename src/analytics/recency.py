"""Home "Latest in your corpus" — the recency endpoint core (slice S1).

A recency LENS over the corpus, NEVER a reweighting of it (cross-time recall is
sacred — search and analytics stay time-neutral). Home is the redundant launchpad,
so a "recently collected" strip is navigational.

Two framings from the design, enforced here:
  * Order by ``created_at`` (when WE collected it — un-spoofable, a fact about our
    corpus), NEVER ``published_at`` (source-claimed, back-datable). ``published_at``
    rides along as secondary, source-asserted.
  * The substance filter is a TRANSPARENT set of GATES the caller sets and sees
    (≥ min words AND ≥ min cited-sources), NEVER a quality/click-bait SCORE. Order
    stays recency; the gates only decide in/out; every returned row shows its REAL
    word_count + cited-source count; an excluded item simply didn't meet the
    caller's thresholds — the app never labels anything "click-bait".

Script-aware length rule (the CJK/Thai catch): ``word_count = len(text.split())``
is meaningless for unsegmented languages (zh/ja/th), so the length gate is SKIPPED
for them (and where word_count is unknown) — a word-gate is never applied blindly.

Cited sources = the article's outbound external ``ArticleLink`` rows (an honest
APPROXIMATION, gameable by link-stuffing, content-type-dependent — a tunable filter,
never a truth signal). Read from ``article_links`` (no article content decrypt).

Bounded by construction: only the most-recently-collected ``candidate_cap`` rows
matching the facets are scanned, and the window size is DISCLOSED — never a silent
cap. Counts only, NO score.

DEFERRED to a follow-up (S1b): near-duplicate collapse of wire reprints into one
fresh story (reuse ``src/signals/near_dup.py``) — the biggest practical win, but it
needs article content, so it is verified separately rather than baked into the first
cut.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Session

from src.analytics.managed import UNSEGMENTED
from src.catalog.provenance import (
    CITED,
    NEWSLETTER,
    NEWSLETTER_DOMAINS,
    PROVENANCE_CLASSES,
    STATISTICS,
    WEB,
    WIKIPEDIA,
    provenance_of,
)
from src.database.models import Article, ArticleLink, Source

_MAX_CANDIDATE_CAP = 2000
_MAX_LIMIT = 200


def passes_substance_gates(
    word_count: int | None, language: str | None, cited: int, min_words: int, min_sources: int
) -> bool:
    """The two transparent gates. The length gate is SKIPPED for unsegmented
    languages and where word_count is unknown (never hide on an unmeasurable
    length); the cited-source gate always applies (0 is a real, countable value).
    Pure — the testable core."""
    if cited < min_sources:
        return False
    if min_words > 0 and word_count is not None:
        base = (language or "").split("-", 1)[0].strip().lower()
        if base not in UNSEGMENTED and word_count < min_words:
            return False
    return True


def _content_type_condition(content_type: str):
    """A SQLAlchemy condition selecting one content-provenance class, mirroring
    ``provenance_of`` so the pre-limit filter and the per-row label never drift."""
    st = func.lower(func.coalesce(Source.source_type, ""))
    wiki = or_(func.lower(Source.domain) == "wikipedia.org",
               func.lower(Source.domain).like("%.wikipedia.org"))
    news = func.lower(Source.domain).in_(tuple(NEWSLETTER_DOMAINS))
    if content_type == WIKIPEDIA:
        return wiki
    if content_type == NEWSLETTER:
        return news
    if content_type == STATISTICS:
        return st == STATISTICS
    if content_type == CITED:
        return st == CITED
    if content_type == WEB:  # the catch-all: none of the above
        return and_(not_(wiki), not_(news), st != STATISTICS, st != CITED)
    return None


def recent_collected(
    session: Session,
    *,
    limit: int = 30,
    min_words: int = 0,
    min_sources: int = 0,
    content_type: str | None = None,
    tags: str | None = None,
    language: str | None = None,
    candidate_cap: int = 500,
) -> dict:
    """The Home "recently collected" stream: newest-by-``created_at`` articles that
    pass the substance gates, within the disclosed candidate window. Counts only,
    NO score."""
    limit = max(1, min(int(limit), _MAX_LIMIT))
    candidate_cap = max(limit, min(int(candidate_cap), _MAX_CANDIDATE_CAP))
    min_words = max(0, int(min_words))
    min_sources = max(0, int(min_sources))

    q = session.query(
        Article.id, Article.title, Article.word_count, Article.language,
        Article.created_at, Article.published_at,
        Source.name, Source.domain, Source.source_type,
    ).join(Source, Article.source_id == Source.id)

    if language:
        q = q.filter(Article.language == language)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            q = q.filter(or_(*[Source.tags.ilike(f"%{t}%") for t in tag_list]))
    if content_type:
        cond = _content_type_condition(content_type)
        if cond is not None:
            q = q.filter(cond)

    # The candidate window: the most-recently-COLLECTED rows matching the facets.
    q = q.order_by(Article.created_at.desc(), Article.id.desc()).limit(candidate_cap)
    candidates = q.all()

    # Outbound external-link counts for exactly this bounded set (cheap; no content).
    ids = [c[0] for c in candidates]
    counts: dict[int, int] = {}
    if ids:
        for aid, c in (
            session.query(ArticleLink.article_id, func.count(ArticleLink.id))
            .filter(ArticleLink.article_id.in_(ids), ArticleLink.link_type == "external")
            .group_by(ArticleLink.article_id)
        ):
            counts[aid] = int(c)

    rows: list[dict] = []
    matched = 0
    for aid, title, wc, lang, created, published, sname, sdomain, stype in candidates:
        cited = counts.get(aid, 0)
        if not passes_substance_gates(wc, lang, cited, min_words, min_sources):
            continue
        matched += 1
        if len(rows) >= limit:
            continue  # keep counting matches in the window, but only return `limit`
        base = (lang or "").split("-", 1)[0].strip().lower()
        rows.append({
            "id": aid,
            "title": title,
            "url": f"/api/articles/{aid}/view",   # the LOCAL reader (invariant #6)
            "source": sname,
            "content_type": provenance_of(sdomain, stype),
            "language": lang,
            "created_at": created.isoformat() if created else None,
            "published_at": published.isoformat() if published else None,   # source-asserted
            "word_count": wc,
            "cited_sources": cited,
            "unsegmented": base in UNSEGMENTED,
        })

    return {
        "articles": rows,
        "returned": len(rows),
        "matched": matched,               # matches within the scanned window
        "candidate_window": len(candidates),
        "filters": {
            "min_words": min_words, "min_sources": min_sources,
            "content_type": content_type, "tags": tags, "language": language,
        },
        "content_types": list(PROVENANCE_CLASSES),
        "method": (
            "Ordered by created_at (when we collected it — un-spoofable), newest "
            "first. Scanned the most-recently-collected articles matching the facets "
            f"(window {len(candidates)}); each row shows its real word_count and "
            "cited-source count (outbound external links). The length gate is skipped "
            "for unsegmented languages (zh/ja/th) and where word_count is unknown."
        ),
        "caveat": (
            "A recency lens, never a reweighting — search and analytics stay "
            "time-neutral. The two gates are transparent filters you set, never a "
            "quality or click-bait score: a long article isn't necessarily good, a "
            "well-sourced one isn't necessarily true, a short one isn't necessarily "
            "click-bait. Cited sources are outbound external links (gameable). An "
            "excluded item simply didn't meet your thresholds."
        ),
    }
