"""What a "source" is when the app COUNTS sources (R773, row 39).

Field test 2026-11-14 row 39: about 25,000 rows of one press had never stored an article.
They were Wikidata discovery finds, inserted disabled on purpose and waiting their turn to
be judged, and every country, region and map figure counted them as sources. A country
"covered" by a disabled parish union nobody has checked is not covered.

One definition, read-side only (no stored row is rewritten, R755):

* a **source** is a row the app has collected from (at least one stored article), or one
  collection may take right now (enabled AND qualified, the ``select_sources`` gate);
* a **candidate not yet checked** is any other row still waiting for its first verdict
  (status ``unqualified``): a discovery find, a seeded entry not yet judged, one whose
  trial found no evidence;
* everything else (judged and refused, or switched off, and never collected from) is
  neither, and is counted only where the full breakdown is shown.

``enabled`` NULL means "never set", which the app reads as enabled (src/api/monitoring.py).
"""

from __future__ import annotations

from sqlalchemy import and_, exists, not_, or_

from src.catalog.qualification import STATUS_QUALIFIED, STATUS_UNQUALIFIED
from src.database.models import Article, Source

#: One short line, shown wherever the two figures sit side by side (keyed x12).
CANDIDATE_LINE = (
    "A candidate is a site the app found or was given but has not checked yet. "
    "It is not collected from and is not counted as a source."
)


def _has_article():
    return exists().where(Article.source_id == Source.id)


def counted_source_clause():
    """SQL filter: rows counted as sources (collected from, or enabled and qualified)."""
    enabled = or_(Source.enabled.is_(True), Source.enabled.is_(None))
    return or_(and_(enabled, Source.status == STATUS_QUALIFIED), _has_article())


def unchecked_candidate_clause():
    """SQL filter: rows waiting for their first verdict and never collected from."""
    return and_(Source.status == STATUS_UNQUALIFIED, not_(counted_source_clause()))


def counted_by_country(session) -> tuple[dict[str, int], dict[str, int]]:
    """Per lower-cased country code: (sources, candidates not yet checked). Rows with no
    country are keyed ``""``."""
    from sqlalchemy import func

    def _tally(clause) -> dict[str, int]:
        rows = (
            session.query(Source.country, func.count(Source.id))
            .filter(clause)
            .group_by(Source.country)
            .all()
        )
        out: dict[str, int] = {}
        for cc, n in rows:
            key = (cc or "").strip().lower()
            out[key] = out.get(key, 0) + int(n or 0)
        return out

    return _tally(counted_source_clause()), _tally(unchecked_candidate_clause())


def standing_totals(session) -> dict[str, int]:
    """Whole-table totals: ``sources``, ``candidates_not_checked`` and ``other`` (judged and
    refused, or switched off, never collected from); the three sum to the row count."""
    from sqlalchemy import func

    total = int(session.query(func.count(Source.id)).scalar() or 0)
    sources = int(session.query(func.count(Source.id)).filter(counted_source_clause()).scalar() or 0)
    cands = int(session.query(func.count(Source.id)).filter(unchecked_candidate_clause()).scalar() or 0)
    return {
        "sources": sources,
        "candidates_not_checked": cands,
        "other": max(0, total - sources - cands),
    }
