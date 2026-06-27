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
