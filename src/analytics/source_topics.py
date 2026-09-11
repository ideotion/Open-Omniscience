"""
Derive each source's topical fingerprint from the keywords it actually publishes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Most catalog sources carry only a ``news`` tag. But the corpus already records,
per source, which keywords appear in its articles -- and many keywords are tagged
with a controlled TOPIC (``keyword_tags`` axis="topic": politics, science, ...).
So a source's real subject coverage is OBSERVABLE: aggregate the topic tags of the
keywords it publishes, weighted by how many distinct articles carry each.

This is the LOCAL, zero-network, on-mission strategy -- it literally attributes
keywords to sources, improves as the corpus grows, and fabricates nothing (a topic
is proposed only when the source has >= ``min_articles`` distinct articles bearing
keywords of that topic). Results are DEDUCED, never asserted: they carry a
``deduced:corpus`` note + a confidence, and a human reviews them via the additive
merge before they enter the catalog.

PERF NOTE (the ledger's codec column-order trap): the query keys off the
DENORMALISED ``keyword_mentions.source_id`` and counts ``article_id`` on that table
joined only to the small ``keyword_tags`` -- it NEVER joins keyword_mentions to
articles (which would drag whole encrypted article rows through the SQLCipher codec).

The aggregation is pure + unit-tested here; the SQL runner lives in
scripts/derive_source_topics.py (needs the live DB, run by the maintainer).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable


def aggregate_source_topics(
    rows: Iterable[tuple[str, str, int]],
    *,
    min_articles: int = 5,
    top_n: int = 4,
    strong_factor: int = 3,
) -> list[dict]:
    """Turn ``(domain, topic, article_count)`` rows into deduced topic proposals.

    For each domain, keep topics with at least ``min_articles`` distinct articles,
    take the ``top_n`` by article count, and emit a merge-format row. Confidence is
    ``medium`` when the strongest kept topic clears ``min_articles * strong_factor``
    distinct articles, else ``low`` -- deduced topics are NEVER ``high`` (they are
    inferred from coverage, not asserted).
    """
    by_domain: dict[str, dict[str, int]] = defaultdict(dict)
    for domain, topic, count in rows:
        if not domain or not topic or count is None:
            continue
        by_domain[domain][topic] = by_domain[domain].get(topic, 0) + int(count)

    out: list[dict] = []
    for domain in sorted(by_domain):
        kept = [(t, c) for t, c in by_domain[domain].items() if c >= min_articles]
        if not kept:
            continue
        # strongest first, then alphabetical for determinism
        kept.sort(key=lambda tc: (-tc[1], tc[0]))
        topics = [t for t, _ in kept[:top_n]]
        strongest = kept[0][1]
        confidence = "medium" if strongest >= min_articles * strong_factor else "low"
        out.append(
            {
                "domain": domain,
                "topics": topics,
                "confidence": confidence,
                "note": "deduced:corpus",
            }
        )
    return out


def derive_source_topics(session, *, min_articles: int = 5, top_n: int = 4) -> list[dict]:
    """Run the corpus query and aggregate. Pure logic is in ``aggregate_source_topics``.

    SQL keys off ``keyword_mentions.source_id`` (denormalised) and joins only the
    small ``keyword_tags`` (axis="topic"); no keyword_mentions->articles join.
    """
    from sqlalchemy import func, select

    from src.database.models import KeywordMention, KeywordTag, Source

    stmt = (
        select(
            Source.domain,
            KeywordTag.tag,
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .join(KeywordTag, KeywordTag.keyword_id == KeywordMention.keyword_id)
        .join(Source, Source.id == KeywordMention.source_id)
        .where(KeywordTag.axis == "topic")
        .group_by(Source.domain, KeywordTag.tag)
    )
    rows = session.execute(stmt).all()  # Row objects unpack as (domain, tag, count)
    return aggregate_source_topics(rows, min_articles=min_articles, top_n=top_n)


def source_topic_candidates(session, *, min_articles: int = 5, top_n: int = 4) -> dict:
    """DECIDE phase: PURE reads. Derives the corpus-wide topic proposals
    (:func:`derive_source_topics`, a GROUP BY over keyword_mentions/keyword_tags --
    see the module docstring's PERF NOTE) then looks up ONLY the sources those
    proposals could possibly touch: a targeted ``Source.domain IN (...)`` lookup,
    chunked under SQLite's 999-variable cap -- never the whole-table
    ``session.query(Source).all()`` (86,470 rows on the field corpus) the old shape
    ran INSIDE the write gate (finding A2, the other half of run_discovery's).

    Returns plain primitives (``{"id", "topics"}`` per candidate) -- never ORM
    objects -- so nothing here can lazy-load once the caller ends the read
    transaction. Does NOT decide the final tag diff: `topics` is the proposal, not
    yet compared against `Source.tags`, because a source's tags can change in the
    gap between this read and the write below; :func:`apply_source_topics`
    recomputes the diff against the CURRENT row under the gate instead of trusting
    a snapshot that may be stale by then.
    """
    from src.database.models import Source

    proposed = {
        r["domain"]: r["topics"]
        for r in derive_source_topics(session, min_articles=min_articles, top_n=top_n)
    }
    if not proposed:
        return {"candidates": []}

    domains = list(proposed)
    candidates: list[dict] = []
    for i in range(0, len(domains), 900):
        batch = domains[i : i + 900]
        rows = session.query(Source.id, Source.domain).filter(Source.domain.in_(batch))
        for sid, domain in rows:
            candidates.append({"id": sid, "topics": proposed[domain]})
    return {"candidates": candidates}


def _apply_source_topics_on_a_shared_session(session, *, min_articles: int, top_n: int) -> dict:
    """FALLBACK shape, used only when the caller handed ``apply_source_topics`` a
    session that ALREADY had an open transaction (pending work from before this
    call). Mirrors ``src.discovery.channels._run_discovery_on_a_shared_session``:
    the old (pre-A2) gate-before-the-scan shape, which never ends a snapshot it did
    not itself open, so it is safe on ANY session. Both of THIS function's real
    callers today hand it a fresh session (see ``apply_source_topics``'s
    docstring), so this branch is not expected to run in production -- it exists
    so a future/unexpected caller degrades to the safe, slower shape rather than
    risking a stale-session rollback.
    """
    from src.database.models import Source
    from src.database.writer import write_lock

    updated = added = 0
    with write_lock():
        proposed = {
            r["domain"]: r["topics"]
            for r in derive_source_topics(session, min_articles=min_articles, top_n=top_n)
        }
        if not proposed:
            return {"sources_updated": 0, "tags_added": 0}
        for src in session.query(Source).all():
            topics = proposed.get(src.domain)
            if not topics:
                continue
            existing = [t.strip() for t in (src.tags or "").split(",") if t.strip()]
            have = set(existing)
            fresh = [t for t in topics if t not in have]
            if fresh:
                src.tags = ",".join(existing + fresh)
                updated += 1
                added += len(fresh)
        session.commit()
    return {"sources_updated": updated, "tags_added": added}


def apply_source_topics(session, *, min_articles: int = 5, top_n: int = 4) -> dict:
    """Write deduced topics into the live ``Source.tags`` (additive, idempotent).

    Unions the derived topics into each source's tag list -- never removes or
    overwrites existing (curated) tags, so a second run adds nothing. Takes the
    single-writer gate. Returns ``{"sources_updated", "tags_added"}``.

    THE SHAPE (A2 fix, 2026-09-11): decide (:func:`source_topic_candidates`, a pure
    read) then end that read transaction BEFORE taking the write gate, then apply
    (mechanical Source.tags updates + commit) under the gate. Same reasoning as
    ``src.discovery.channels.run_discovery`` (see its comment for the full
    mechanism): with no snapshot held when the gate is taken, the write below opens
    a FRESH transaction while the gate is already held, so no other writer's commit
    can land between a read and a write promotion -- the exact precondition
    SQLITE_BUSY_SNAPSHOT needs. The old shape held the gate across
    `derive_source_topics` (a corpus-wide GROUP BY) AND `session.query(Source).all()`
    (86,470 ORM entities) -- both now happen before the gate.

    Ending the read snapshot via ``session.rollback()`` is SAFE ONLY because every
    caller of this function hands it its OWN short-lived session, never one shared
    with other pending work: the Diagnostics endpoint's request-scoped session
    (``src/api/diagnostics.py`` `/enrich-sources`, via FastAPI's ``get_db`` --
    closed at the end of that one request, with nothing else done on it) and the
    scheduler tail's `_enr_session` from `session_scope()`
    (``src/scheduler/runner.py``, S2.4's `run_auto_source_enrichment` ride-along --
    its own session, never the pass's). Confirmed at both call sites -- and, as a
    second line of defence for any OTHER caller,
    ``session.in_transaction()`` is checked below (the same signal
    ``run_discovery`` uses): False only on a session with nothing pending since its
    last commit/rollback, which is the only case in which the rollback is provably
    ours alone to make.
    """
    if session.in_transaction():
        return _apply_source_topics_on_a_shared_session(session, min_articles=min_articles, top_n=top_n)

    from src.database.models import Source
    from src.database.writer import write_lock

    decided = source_topic_candidates(session, min_articles=min_articles, top_n=top_n)
    candidates = decided["candidates"]
    if not candidates:
        return {"sources_updated": 0, "tags_added": 0}

    # End the read snapshot before taking the write gate -- see the docstring above.
    session.rollback()

    updated = added = 0
    with write_lock():
        for cand in candidates:
            src = session.get(Source, cand["id"])
            if src is None:
                continue  # the row vanished between decide and apply; skip honestly
            # Re-derive `fresh` against Source.tags AS IT IS NOW, not the decide-phase
            # snapshot -- the row could have been curated in the gap between the read
            # and the gate, and recomputing here means that edit is never clobbered.
            existing = [t.strip() for t in (src.tags or "").split(",") if t.strip()]
            have = set(existing)
            fresh = [t for t in cand["topics"] if t not in have]
            if fresh:
                src.tags = ",".join(existing + fresh)
                updated += 1
                added += len(fresh)
        session.commit()
    return {"sources_updated": updated, "tags_added": added}


def _state_path():
    from src.paths import data_dir

    return data_dir() / "source_enrich.json"


def enrichment_due(*, min_interval_hours: int = 24) -> bool:
    """True if the auto source-topic pass has not run within the interval."""
    import json
    from datetime import UTC, datetime

    try:
        last = json.loads(_state_path().read_text(encoding="utf-8")).get("last_run")
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= min_interval_hours * 3600
    except Exception:  # noqa: BLE001 - missing/bad marker => due
        return True


def run_auto_source_enrichment(session, *, min_interval_hours: int = 24) -> dict:
    """Freshness-gated wrapper for the scheduler's post-pass housekeeping.

    Local + zero-network (reads the corpus, writes tags). Best-effort by the
    caller; returns ``{"ran": bool, ...}``.
    """
    import contextlib
    import json
    from datetime import UTC, datetime

    if not enrichment_due(min_interval_hours=min_interval_hours):
        return {"ran": False}
    result = apply_source_topics(session)
    # a marker-write failure must not break the pass
    with contextlib.suppress(Exception):
        _state_path().write_text(
            json.dumps({"last_run": datetime.now(UTC).isoformat()}), encoding="utf-8"
        )
    return {"ran": True, **result}
