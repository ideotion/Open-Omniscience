"""
User-guided actor-collapse — propose → the user disposes (never silent).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Anti-amplification is **never** a transform the app performs behind the user's back
(that would make the app the arbiter §6 forbids). The model is *propose → the user
disposes*:

  * **Default = "equal but aware".** The raw equal-treatment view is the baseline; a
    coordinated cluster is *annotated on it* (see the echo-chamber card), not silently
    collapsed.
  * **The user applies a collapse**, globally or per-cluster. Only then does a
    coordinated flood fold into a single actor in any count that measures *consensus*
    (how many independent voices carry a story).
  * **Every applied collapse stays flagged and reversible.** Toggling it off reproduces
    the raw equal counts exactly. No collapse is ever applied without an explicit action.

Decisions persist as a small JSON file under the data dir (the same local-first pattern
as the briefing dismissals); an actor is identified by the stable signature of its
member set (:func:`src.integrity.actors.actor_signature`).
"""

from __future__ import annotations

import json
import logging

from src.integrity.actors import corpus_actors
from src.signals.near_dup import near_duplicate_clusters

_LOG = logging.getLogger(__name__)
COLLAPSE_VERSION = "oo-integrity-collapse-1"


def _path():
    from src.paths import data_dir

    return data_dir() / "integrity_collapse.json"


def applied_signatures() -> set[str]:
    path = _path()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text("utf-8")).get("applied", []))
    except Exception:  # noqa: BLE001 - a bad file must not break the feed
        _LOG.warning("integrity_collapse.json unreadable; treating as empty", exc_info=True)
        return set()


def _save(sigs: set[str]) -> None:
    path = _path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": COLLAPSE_VERSION, "applied": sorted(sigs)}, indent=2), "utf-8")
    tmp.replace(path)


def is_applied(signature: str) -> bool:
    return signature in applied_signatures()


def apply_collapse(signature: str) -> set[str]:
    """Apply a proposed collapse (the user's explicit action)."""
    sigs = applied_signatures()
    sigs.add(signature)
    _save(sigs)
    return sigs


def revert_collapse(signature: str) -> set[str]:
    """Undo an applied collapse — the raw equal view returns for that cluster."""
    sigs = applied_signatures()
    sigs.discard(signature)
    _save(sigs)
    return sigs


def apply_all(session, **kwargs) -> set[str]:
    """Apply every currently-proposed actor (the 'collapse globally' action)."""
    result = corpus_actors(session, **kwargs)
    sigs = applied_signatures()
    for actor in result.actors:
        sigs.add(actor.signature)
    _save(sigs)
    return sigs


def revert_all() -> set[str]:
    _save(set())
    return set()


def collapse_status(session, **kwargs) -> dict:
    """The proposed actors annotated with whether the user has applied each."""
    from src.integrity.actors import actor_view

    result = corpus_actors(session, **kwargs)
    applied = applied_signatures()
    actors = actor_view(result)
    for a in actors:
        a["applied"] = a["signature"] in applied
    return {
        "method": result.method,
        "caveat": result.caveat,
        "n_documents": result.n_documents,
        "n_sources": result.n_sources,
        "applied_count": sum(1 for a in actors if a["applied"]),
        "actors": actors,
    }


def story_prominence(session, *, days: int = 14, threshold: float = 0.6,
                     min_chars: int = 200, limit: int = 2000,
                     weight_by_novelty: bool = False) -> dict:
    """How many **independent voices** carry each story — raw vs actor-collapsed.

    A *story* is a near-duplicate cluster of recent articles (singletons included). Its
    prominence is the number of distinct sources covering it. When the user has applied
    a collapse, every member source of an applied actor counts as **one** voice for that
    story — so a 40-puppet flood reads as 1 voice, not 40, and a genuine single-source
    story is no longer drowned. With nothing applied, ``voices_collapsed == voices_raw``
    (the equal view, exactly).

    ``weight_by_novelty`` (opt-in, off by default — anti-amplification is user-guided,
    never silent) adds, per story, the **novelty** of its earliest article against the
    corpus in time order: a story that merely re-tells earlier-seen text scores low even
    if it sits just under the near-dup threshold, and ``novelty_weighted_voices`` scales
    the collapsed voice count by that novelty. The equal view is reproduced exactly by
    leaving this off.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func

    from src.database.models import Article, Source

    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        session.query(Article.id, Source.name, Source.domain, Article.title, Article.content)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(Article.id.desc())
        .limit(limit)
        .all()
    )
    source_of: dict[str, str] = {}
    texts: dict[str, str] = {}
    title_of: dict[str, str] = {}
    for aid, name, domain, title, content in rows:
        sid = str(aid)
        text = content or title or ""
        if len(text) < min_chars:
            continue
        source_of[sid] = name or domain or f"source-{aid}"
        texts[sid] = text
        title_of[sid] = title or "(untitled)"

    nd = near_duplicate_clusters(texts, threshold=threshold)
    clustered: set[str] = set()
    stories: list[set[str]] = []
    for cluster in nd.clusters:
        members = set(cluster.members)
        stories.append(members)
        clustered |= members
    # Singletons (a story told by one piece) are stories too.
    for sid in texts:
        if sid not in clustered:
            stories.append({sid})

    applied = applied_signatures()
    applied_member_sets: list[set[str]] = []
    if applied:
        for actor in corpus_actors(session, days=days, threshold=threshold,
                                   min_chars=min_chars, limit=limit).actors:
            if actor.signature in applied:
                applied_member_sets.append(set(actor.sources))

    def _collapsed_voices(srcs: set[str]) -> int:
        if not applied_member_sets:
            return len(srcs)
        remaining = set(srcs)
        voices = 0
        for members in applied_member_sets:
            if remaining & members:
                voices += 1               # the whole actor = one voice
                remaining -= members
        return voices + len(remaining)

    # Optional novelty per story (opt-in): process stories oldest-first (the earliest
    # member id approximates the earliest sighting) so an original scores ~1 and a
    # late near-echo scores low — the §6 "information contributed" weighting.
    novelty_of: dict[str, float] = {}
    if weight_by_novelty:
        from src.signals.novelty import NoveltyIndex

        index = NoveltyIndex()
        ordered_stories = sorted(stories, key=lambda m: min(int(x) for x in m))
        for members in ordered_stories:
            rep = sorted(members, key=int)[0]
            r = index.measure_and_add(texts[rep])
            novelty_of[rep] = 1.0 if r.ratio is None else round(r.ratio, 3)

    out = []
    for members in stories:
        srcs = {source_of[m] for m in members}
        rep = sorted(members)[0]
        item = {
            "representative": rep,
            "title": title_of[rep],
            "articles": len(members),
            "voices_raw": len(srcs),
            "voices_collapsed": _collapsed_voices(srcs),
            "sources": sorted(srcs),
        }
        if weight_by_novelty:
            nov = novelty_of.get(rep, 1.0)
            item["novelty"] = nov
            item["novelty_weighted_voices"] = round(item["voices_collapsed"] * nov, 3)
        out.append(item)
    if weight_by_novelty:
        out.sort(key=lambda s: (-s["novelty_weighted_voices"], -s["voices_collapsed"], -s["articles"]))
    else:
        out.sort(key=lambda s: (-s["voices_collapsed"], -s["voices_raw"], -s["articles"]))
    return {"applied": bool(applied), "weighted_by_novelty": weight_by_novelty, "stories": out}


# Back-compat alias for the package export.
actor_weighted_source_counts = story_prominence
