"""Home "Latest in your corpus" — recency LENS with transparent substance FILTERS (S1).

A "latest news" surface for the redundant Home launchpad (invariant #8) that avoids
very short click-bait WITHOUT reweighting the corpus and WITHOUT a quality/click-bait
score. Two hard framings the maintainer set (docs/FUTURE_DEVELOPMENTS.md → "Home
'Latest in your corpus' section"):

  1. A recency LENS, never a reweighting — order by ``created_at`` (collection time,
     un-spoofable), NOT ``published_at`` (a publisher can back-date). Cross-time recall
     stays sacred: this is a view, not a re-ranking of the whole corpus.
  2. The substance gate is a TRANSPARENT FILTER, never a score — TWO gates the user
     sets AND sees (≥ min words AND ≥ min cited-sources), each shown article carrying
     its REAL values. Nothing is labelled "click-bait"; the reader judges.

Honesty baked in:
  * SCRIPT-AWARE length: ``word_count = len(text.split())`` is meaningless for the
    unsegmented languages (zh/ja/th) — they (and articles whose word_count is unknown)
    BYPASS the word gate and are FLAGGED, so a long Chinese article is never dropped as
    "too short" on a segmentation artifact.
  * NEAR-DUP COLLAPSE: wire reprints of one story are collapsed into the single freshest
    copy (``src/signals/near_dup``), so the latest strip is distinct stories, not five
    copies of the same AP wire. Each survivor reports how many copies it absorbed and
    which other sources ran it (transparency, not a score).
  * The cited-source count (outbound external links) is an APPROXIMATION — a tunable
    filter, gameable by link-stuffing, content-type-dependent — never a truth signal.

Perf (codec-decrypt lesson): the candidate scan reads only small columns (index-
friendly) bounded to the newest ``scan_cap`` in the window; the cited-source counts
come from ``article_links`` (no article decrypt); article CONTENT is read only for the
near-dup collapse and only for the freshest ``near_dup_cap`` survivors.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics.managed import UNSEGMENTED
from src.database.models import Article, ArticleLink, Source

_SQL_IN_CHUNK = 900  # stay under the SQLite bound-variable limit


def _split_tags(tags: str | None) -> list[str]:
    """A source's comma-separated tags -> a lowercase list (order preserved, deduped)."""
    if not tags:
        return []
    out: list[str] = []
    for t in tags.split(","):
        s = t.strip().lower()
        if s and s not in out:
            out.append(s)
    return out


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def latest_articles(
    session: Session,
    *,
    limit: int = 20,
    window_days: int = 30,
    min_words: int = 0,
    min_sources: int = 0,
    content_type: str | None = None,
    tag: str | None = None,
    collapse: bool = True,
    facets: bool = True,
    scan_cap: int = 500,
    near_dup_cap: int = 400,
) -> dict:
    """The newest articles in the corpus that pass the user's transparent gates.

    Ordered by ``created_at`` DESC (recency), filtered by ``min_words`` AND
    ``min_sources`` (both shown), optionally scoped to a content type / source tag,
    with near-identical wire reprints collapsed into the freshest copy. Counts only,
    NO score.
    """
    limit = max(1, min(int(limit), 100))
    window_days = max(1, min(int(window_days), 3650))
    min_words = max(0, int(min_words))
    min_sources = max(0, int(min_sources))
    scan_cap = max(1, min(int(scan_cap), 2000))
    near_dup_cap = max(0, min(int(near_dup_cap), 1000))
    ct = (content_type or "").strip().lower() or None
    tg = (tag or "").strip().lower() or None

    since = datetime.now(UTC) - timedelta(days=window_days)

    # Small source metadata map (the sources table is tiny): display info + the tag list.
    srcinfo: dict[int, dict] = {}
    for sid, name, domain, stype, tags in session.query(
        Source.id, Source.name, Source.domain, Source.source_type, Source.tags
    ):
        srcinfo[sid] = {
            "name": name,
            "domain": domain,
            "source_type": (stype or "news"),
            "tags": _split_tags(tags),
        }

    meta = {
        "returned": 0,
        "scanned": 0,
        "scan_capped": False,
        "candidates_after_gates": 0,
        "collapsed_total": 0,
        "collapse_bounded": False,
        "window_days": window_days,
        "gates": {"min_words": min_words, "min_sources": min_sources},
        "filters": {"content_type": ct, "tag": tg},
        "collapse": collapse,
        "articles": [],
    }
    if facets:
        opts = _facet_options(session, since)
        meta["available_content_types"] = opts[0]
        meta["available_tags"] = opts[1]

    # A tag scoped to zero sources means an empty (honest) result — never a guess.
    tag_source_ids: list[int] | None = None
    if tg is not None:
        tag_source_ids = [sid for sid, info in srcinfo.items() if tg in info["tags"]]
        if not tag_source_ids:
            return {**meta, **_method_caveat(scan_cap, near_dup_cap)}

    # Candidate rows: small columns only, newest first, bounded to scan_cap. NO content.
    cand_q = session.query(
        Article.id, Article.source_id, Article.title,
        Article.created_at, Article.published_at, Article.language, Article.word_count,
    ).filter(Article.created_at >= since)
    if ct is not None:
        cand_q = cand_q.join(Source, Article.source_id == Source.id).filter(
            func.lower(func.coalesce(Source.source_type, "news")) == ct
        )
    if tag_source_ids is not None:
        cand_q = cand_q.filter(Article.source_id.in_(tag_source_ids))
    rows = (
        cand_q.order_by(Article.created_at.desc(), Article.id.desc()).limit(scan_cap).all()
    )
    meta["scanned"] = len(rows)
    meta["scan_capped"] = len(rows) >= scan_cap

    # Cited-source (outbound external link) count per scanned article — cheap, no decrypt.
    ids = [r[0] for r in rows]
    link_count: dict[int, int] = {}
    for i in range(0, len(ids), _SQL_IN_CHUNK):
        chunk = ids[i : i + _SQL_IN_CHUNK]
        for aid, c in (
            session.query(ArticleLink.article_id, func.count(ArticleLink.id))
            .filter(ArticleLink.link_type == "external", ArticleLink.article_id.in_(chunk))
            .group_by(ArticleLink.article_id)
        ):
            link_count[aid] = int(c)

    # Apply the two transparent gates, preserving recency order.
    candidates: list[dict] = []
    for aid, sid, title, created, published, lang, wc in rows:
        base = (lang or "").split("-", 1)[0].strip().lower()
        unseg = base in UNSEGMENTED
        cited = link_count.get(aid, 0)
        if cited < min_sources:
            continue
        # Word gate is SCRIPT-AWARE: unsegmented languages and unknown word_count
        # bypass it (flagged), so a segmentation artifact never reads as click-bait.
        if min_words > 0 and not unseg and wc is not None and wc < min_words:
            continue
        info = srcinfo.get(sid, {})
        candidates.append(
            {
                "id": aid,
                "title": title,
                "url": f"/api/articles/{aid}/view",  # the LOCAL reader (invariant #6)
                "created_at": _iso(created),
                "published_at": _iso(published),
                "language": lang,
                "unsegmented": unseg,
                "word_count": wc,
                "cited_sources": cited,
                "source": {
                    "name": info.get("name"),
                    "domain": info.get("domain"),
                    "source_type": info.get("source_type", "news"),
                    "tags": info.get("tags", []),
                },
                "_source_domain": info.get("domain"),
            }
        )
    meta["candidates_after_gates"] = len(candidates)

    # Near-dup collapse: cluster the freshest survivors (bounded content reads), then
    # keep the FIRST (= freshest, recency order) member of each cluster and fold the
    # rest into it.
    cluster_of: dict[str, str] = {}
    if collapse and near_dup_cap > 0 and len(candidates) >= 2:
        subset = candidates[:near_dup_cap]
        meta["collapse_bounded"] = len(candidates) > near_dup_cap
        docs: dict[str, str] = {}
        sub_ids = [c["id"] for c in subset]
        text_by_id: dict[int, tuple[str | None, str | None]] = {}
        for i in range(0, len(sub_ids), _SQL_IN_CHUNK):
            chunk = sub_ids[i : i + _SQL_IN_CHUNK]
            for art in session.query(Article).filter(Article.id.in_(chunk)):
                body = art.get_content() if hasattr(art, "get_content") else (art.content or "")
                text_by_id[art.id] = (art.title, body)
        for c in subset:
            title, body = text_by_id.get(c["id"], (c["title"], ""))
            docs[str(c["id"])] = ((title or "") + "\n" + (body or "")).strip()
        if len([d for d in docs.values() if d]) >= 2:
            from src.signals.near_dup import near_duplicate_clusters

            result = near_duplicate_clusters(docs, threshold=0.7)
            for cl in result.clusters:
                for m in cl.members:
                    cluster_of[m] = cl.representative

    emitted: list[dict] = []
    by_cluster: dict[str, dict] = {}
    collapsed_total = 0
    for c in candidates:
        key = cluster_of.get(str(c["id"]))
        if key is not None and key in by_cluster:
            story = by_cluster[key]
            story["duplicates_collapsed"] += 1
            collapsed_total += 1
            dom = c.get("_source_domain")
            if dom and dom not in story["also_reported_by"]:
                story["also_reported_by"].append(dom)
            continue
        if len(emitted) >= limit:
            # Enough distinct stories; keep scanning only to attach dups of shown ones.
            continue
        story = {k: v for k, v in c.items() if k != "_source_domain"}
        story["duplicates_collapsed"] = 0
        story["also_reported_by"] = []
        if key is not None:
            by_cluster[key] = story
        emitted.append(story)

    meta["articles"] = emitted
    meta["returned"] = len(emitted)
    meta["collapsed_total"] = collapsed_total
    return {**meta, **_method_caveat(scan_cap, near_dup_cap)}


def _facet_options(session: Session, since: datetime) -> tuple[dict[str, int], list[dict]]:
    """Content-type + tag options present in the recent window (independent of the
    active filters), so a UI can offer every channel/tag the window contains. Counts
    only; article-count group-bys joined to the small sources table (no decrypt)."""
    type_counts: dict[str, int] = {}
    for stype, c in (
        session.query(func.coalesce(Source.source_type, "news"), func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= since)
        .group_by(func.coalesce(Source.source_type, "news"))
    ):
        type_counts[stype] = int(c)

    tag_counts: dict[str, int] = {}
    for tags, c in (
        session.query(Source.tags, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= since, Source.tags.isnot(None))
        .group_by(Source.tags)
    ):
        for t in _split_tags(tags):
            tag_counts[t] = tag_counts.get(t, 0) + int(c)

    types = dict(sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0])))
    tags_out = [
        {"tag": t, "articles": n}
        for t, n in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    ]
    return types, tags_out


def _method_caveat(scan_cap: int, near_dup_cap: int) -> dict:
    return {
        "method": (
            "Newest first by created_at (collection time, un-spoofable — never the "
            "publisher's claimed published_at) within the window. Each shown story "
            "passes your gates (word_count AND cited-source count); near-identical wire "
            "reprints are collapsed into the freshest copy. The scan is bounded to the "
            f"{scan_cap} newest candidates; near-dup collapse reads at most {near_dup_cap} "
            "of them."
        ),
        "caveat": (
            "Counts only, never a score — a recency LENS with transparent substance "
            "FILTERS, not a reweighting of your corpus and not a quality judgement; a "
            "short article is not necessarily click-bait, a long or well-linked one not "
            "necessarily good. word_count is unreliable for unsegmented languages "
            "(zh/ja/th) and unknown ones, which bypass the word gate (flagged). The "
            "cited-source count (outbound external links) is a gameable approximation."
        ),
    }
