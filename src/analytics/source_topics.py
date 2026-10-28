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

from src.database.stand_in import is_a_stand_in_source, not_a_stand_in_source

#: Sources read and written per statement. WHAT IT PROTECTS: the read binds one variable per id, and SQLite's default ceiling is 999
#: variables per statement (3.32+ and SQLCipher 4 allow 32766, but the constant must hold on the old ceiling); it is also the size of
#: one ``executemany`` batch inside the write window, so no single statement grows with the source table.
SOURCE_TOPICS_CHUNK = 900


def _union_topics(tags: str | None, topics: Iterable[str]) -> tuple[str, int] | None:
    """``tags`` with the topics it lacks appended (additive, order kept), and how many were added; ``None`` when there is nothing to add."""
    existing = [t.strip() for t in (tags or "").split(",") if t.strip()]
    have = set(existing)
    fresh = [t for t in topics if t not in have]
    return (",".join(existing + fresh), len(fresh)) if fresh else None


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

    **A keyword the stoplist hides is not evidence of a topic (R111 step T2).** The tagged
    keywords are few (a controlled axis), so the hidden ones are resolved FIRST, from the
    tag table and the small ``keywords`` columns, and left out of the aggregation in SQL:
    summing per-keyword counts afterwards would count an article twice wherever it carries two
    keywords of one topic, and that is the one thing this query's ``COUNT(DISTINCT article)``
    exists to prevent. Only the LIST hides here (shipped stopwords + the user's exclusions), not
    the too-short / numeric rule: a topic tag is a deliberate, curated label on a keyword
    (``ai`` is one), and a length rule would silently erase its evidence.
    """
    from sqlalchemy import func, select

    from src.analytics.filters import hidden_set
    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Keyword, KeywordTag, Source
    from src.database.stand_in import not_a_stand_in_article_id

    hidden = hidden_set()
    tagged = session.execute(
        select(KeywordTag.keyword_id, Keyword.normalized_term)
        .join(Keyword, Keyword.id == KeywordTag.keyword_id)
        .where(KeywordTag.axis == "topic")
        .distinct()
    ).all()
    hidden_ids = sorted({int(kid) for kid, norm in tagged if norm in hidden})

    stmt = (
        select(
            Source.domain,
            KeywordTag.tag,
            func.count(func.distinct(KeywordMentionRead.article_id)),
        )
        .join(KeywordTag, KeywordTag.keyword_id == KeywordMentionRead.keyword_id)
        .join(Source, Source.id == KeywordMentionRead.source_id)
        # a mention kept for a lost article is no article of the source: it would count toward the source's floor and its topic ranking
        .where(KeywordTag.axis == "topic", not_a_stand_in_article_id(KeywordMentionRead.article_id))
        .group_by(Source.domain, KeywordTag.tag)
    )
    if hidden_ids:
        # ONE NOT IN. WHAT BOUNDS IT: the topic axis is curated (the baseline files carry about a hundred
        # entries across seven languages, each tagging a few keywords), so the hidden ones are a handful,
        # and SQLite 3.32+ and SQLCipher 4 bind 32766 variables per statement. Chunking would not bound it:
        # ANDed chunks are still one statement.
        stmt = stmt.where(KeywordTag.keyword_id.notin_(hidden_ids))
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
    for i in range(0, len(domains), SOURCE_TOPICS_CHUNK):
        batch = domains[i : i + SOURCE_TOPICS_CHUNK]
        rows = session.query(Source.id, Source.domain).filter(Source.domain.in_(batch), not_a_stand_in_source())  # a stand-in is given no tags
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
    from src.database.writer import connection_first, write_lock

    updated = added = 0
    connection_first(session)  # the connection, then the gate (writer.connection_first)
    with write_lock():
        proposed = {
            r["domain"]: r["topics"]
            for r in derive_source_topics(session, min_articles=min_articles, top_n=top_n)
        }
        if not proposed:
            return {"sources_updated": 0, "tags_added": 0}
        for src in session.query(Source).filter(not_a_stand_in_source()).all():
            topics = proposed.get(src.domain)
            if not topics:
                continue
            merged = _union_topics(src.tags, topics)
            if merged:
                src.tags = merged[0]
                updated += 1
                added += merged[1]
        session.commit()
    return {"sources_updated": updated, "tags_added": added}


def _write_topics_in_bulk(session, candidates: list[dict]) -> tuple[int, int]:
    """Union each candidate's topics into its source's tags, :data:`SOURCE_TOPICS_CHUNK` sources per statement. Returns ``(sources_updated,
    tags_added)``. Runs INSIDE the write window of :func:`apply_source_topics`; the caller commits.

    WHY NOT ``session.get`` PER SOURCE (R390, measured 2026-10-28): that shape cost one SELECT per candidate and one UPDATE per changed
    source inside the window. Harness ``/mnt/project-files/keyword-lane/st_measure.py`` (not in the repo), 86,470 sources (the field
    corpus's count) each given 3 topics, fresh copy of one database per run, 4 cores, 3 runs: the window was held 26.7 / 28.9 / 27.5 s with
    86,472 statements (encrypted store, one run: 29.9 s), and 17.7 / 18.6 s with 86,471 statements when there was nothing to add. This
    shape reads ``(id, domain, tags, rss_url)`` in chunks and writes by primary key with ``executemany``: 1.6 to 1.8 s with 195 statements
    (this function, five runs, two of them on the encrypted store: 1.77 / 1.79 s), 0.37 / 0.40 s and 98 statements when there is nothing to
    add, and the same final state as the per-source path, a hash over ``(id, tags, feed_key)`` of every row. Every writer queues behind the window, so those seconds were a stall of the whole app once a day
    (the scheduler tail's enrichment) and on every call of the Diagnostics ``enrich-sources`` endpoint. 86,470 is the upper bound: a real
    run writes only the sources that qualify.

    WHAT THE ORM PATH DID THAT A BULK UPDATE SKIPS, AND WHERE EACH IS KEPT. The Source model has ONE mapper event, ``before_update``
    (``models._derive_source_feed_key``: ``feed_key`` is re-derived from ``rss_url`` on every ORM write of the row), so the same
    ``feed_key(rss_url)`` is written in the same UPDATE (a stale value is healed exactly as before; ``tests/test_source_topics_bulk.py``).
    There is no ``@validates``, no ``after_update``, no ``onupdate`` column and no versioned row on Source; the three database triggers on
    ``sources`` fire on ``UPDATE OF domain, id`` (or insert / delete) and this writes neither. The session-level events are kept because the
    statement is still an ORM one (``session.execute(update(Source), rows)``, not Core): the write gate's ``do_orm_execute`` and
    ``database.session._wrote_on_bulk_dml`` both see ``is_update``. The stand-in skip is the same predicate (:func:`is_a_stand_in_source`, read on
    the row), a source deleted since the decide phase is simply absent from the read, and the union is computed against the tags AS THEY ARE
    NOW, inside the window, so an edit made in the gap is never clobbered.
    """
    from sqlalchemy import select, update

    from src.database.feed_key import feed_key
    from src.database.models import Source

    by_id = {c["id"]: c["topics"] for c in candidates}
    ids = list(by_id)
    updated = added = 0
    for i in range(0, len(ids), SOURCE_TOPICS_CHUNK):
        rows = session.execute(
            select(Source.id, Source.domain, Source.tags, Source.rss_url).where(Source.id.in_(ids[i : i + SOURCE_TOPICS_CHUNK]))
        ).all()
        writes = []
        for row in rows:
            if is_a_stand_in_source(row):
                continue  # tags are never written onto a stand-in source
            merged = _union_topics(row.tags, by_id[row.id])
            if merged:
                writes.append({"id": row.id, "tags": merged[0], "feed_key": feed_key(row.rss_url)})
                updated += 1
                added += merged[1]
        if writes:
            session.execute(update(Source), writes)  # ORM bulk UPDATE by primary key
    return updated, added


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

    from src.database.writer import connection_first, write_lock

    decided = source_topic_candidates(session, min_articles=min_articles, top_n=top_n)
    candidates = decided["candidates"]
    if not candidates:
        return {"sources_updated": 0, "tags_added": 0}

    # End the read snapshot before taking the write gate -- see the docstring above.
    session.rollback()

    connection_first(session)  # the rollback gave the connection back: check one out BEFORE the gate, not under it
    with write_lock():
        # Re-derive the union against Source.tags AS IT IS NOW, not the decide-phase snapshot -- the row could have been curated in the gap
        # between the read and the gate, and recomputing here means that edit is never clobbered. A source that vanished in the gap is
        # skipped honestly.
        updated, added = _write_topics_in_bulk(session, candidates)
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
