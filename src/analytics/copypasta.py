"""Copypasta / shared-talking-point detection (manipulation-pattern card, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent or truth (the manipulation-card doctrine): an identical
VERBATIM span appears across articles from several DIFFERENT sources whose full articles
are NOT duplicates of one another. The articles differ overall but carry the same exact
sentence — the shape a coordinated talking point (copypasta) makes when it is dropped into
otherwise-original coverage.

This is the SPAN-level sibling of the existing whole-article signals, and it is deliberately
DISTINCT from them:
  * ``echo_chamber`` / coordination fire on WHOLE-article near-duplication (a wire story
    republished verbatim) — that is exactly the innocent twin here, so this card EXCLUDES it:
    if the sharing articles are themselves near-duplicates across that many sources, the
    shared text is just a republished story and is left to echo_chamber;
  * ``recycled_claim`` is whole-article near-dup across a long time GAP.
What this catches that those miss: the SAME sentence embedded in articles that are otherwise
different — a fragment, not a republished whole.

HONESTY (enforced in code, not just prose):
  * independence is measured by DISTINCT SOURCES, never article count (a single source
    repeating a line cannot manufacture the pattern — the gate is >= ``min_sources``
    distinct sources);
  * the metric reported is the distinct-source count + the phrase length, never a score;
  * the innocent explanations are stated beside the pattern (a shared quote, a press-release
    line, a wire snippet, common boilerplate) — the user judges;
  * the scan is bounded (a recent pool, capped) and that bound is stated in the method; the
    exact phrase + the exact article set travel with the card.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

COPYPASTA_CAVEAT = (
    "Identical wording copied verbatim across articles from several DIFFERENT sources, where "
    "the articles themselves are not whole duplicates of one another. Shared verbatim text is "
    "often innocent — a quoted statement, a press-release line, a wire snippet, or common "
    "boilerplate — so the shape flagged is only 'the same text in otherwise-different articles "
    "across several sources', never a claim it was coordinated. Read them and judge."
)


def find_copypasta(
    session,
    *,
    recent_days: int = 14,
    k: int = 8,
    min_sources: int = 3,
    whole_dup_threshold: float = 0.7,
    min_chars: int = 200,
    recent_limit: int = 800,
    max_items: int = 12,
) -> dict:
    """Verbatim phrases copied across many DISTINCT sources, in NON-duplicate articles.

    Pulls a bounded RECENT pool, finds verbatim ``k``-word(+) phrases shared across distinct
    sources (via the pure :func:`shared_word_ngrams`), and keeps a phrase only when (a) it
    spans >= ``min_sources`` distinct sources AND (b) the sharing articles are NOT whole
    near-duplicates across that many sources (wire republish — left to echo_chamber).
    Read-only; counts + the exact phrase only; no score.
    """
    from src.database.models import Article, Source

    now = datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=recent_days)).replace(tzinfo=None)
    observed = func.coalesce(Article.published_at, Article.created_at)

    rows = (
        session.query(Article, Source.name, Source.domain)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(observed >= recent_cutoff)
        .order_by(Article.id.desc())
        .limit(recent_limit)
        .all()
    )

    docs: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for a, sname, sdom in rows:
        text = ((a.title or "") + "\n" + (a.get_content() or "")).strip()
        if len(text) < min_chars:
            continue
        docs[str(a.id)] = text
        meta[str(a.id)] = {
            "id": a.id,
            "title": a.title,
            "source": sname or sdom or f"source-{a.source_id}",
            "source_id": a.source_id,
            "url": a.url,
        }

    from src.signals.near_dup import near_duplicate_clusters, shared_word_ngrams

    phrases = shared_word_ngrams(docs, k=k, min_docs=2, max_phrases=200)

    items: list[dict] = []
    for ph in phrases:
        ids = [i for i in ph["doc_ids"] if i in meta]
        sources = sorted({meta[i]["source"] for i in ids})
        if len(sources) < min_sources:
            continue
        # Exclude wire republish: if the WHOLE articles are near-duplicates spanning
        # >= min_sources sources, the shared text is a republished story (echo_chamber's
        # job), not a span planted into otherwise-different articles.
        nd = near_duplicate_clusters({i: docs[i] for i in ids}, threshold=whole_dup_threshold)
        wire = any(
            len({meta[m]["source"] for m in c.members if m in meta}) >= min_sources
            for c in nd.clusters
        )
        if wire:
            continue
        items.append({
            "phrase": ph["phrase"],
            "n_words": len(ph["phrase"].split()),
            "distinct_sources": len(sources),
            "n_articles": len(ids),
            "sources": sources,
            "example_titles": [meta[i]["title"] for i in ids[:4] if meta[i]["title"]],
            "article_ids": sorted(meta[i]["id"] for i in ids),
        })

    items.sort(key=lambda x: (-x["distinct_sources"], -x["n_words"]))
    items = items[:max_items]

    return {
        "items": items,
        "count": len(items),
        "recent_days": recent_days,
        "min_sources": min_sources,
        "k": k,
        "method": (
            "Verbatim {k}-word(+) phrases shared by >= {ms} distinct sources within the last "
            "{rd} days, EXCLUDING spans whose whole articles are near-duplicates across that "
            "many sources (Jaccard >= {th} = a republished wire story, not a planted line). "
            "Bounded scan: up to {rl} recent articles. Independence is distinct sources, not "
            "article count; no score.".format(
                k=k, ms=min_sources, rd=recent_days, th=whole_dup_threshold, rl=recent_limit
            )
        ),
        "caveat": COPYPASTA_CAVEAT,
    }
