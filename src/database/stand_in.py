"""What marks a STAND-IN row, and the one condition every reader of such a table uses to leave it out.

A salvage copy (:mod:`src.database.salvage`) that keeps a row whose parent could not be read writes ONE stand-in row into the parent table at
the lost id, so that an id is never handed out again and the kept row does not seem to belong to a new one. A stand-in is a place-holder, never
data: it carries no title, no text, no address, and it must not be shown, counted, searched, exported, qualified or collected as if it were an
article or a source the user once saved. This module is the one place that says how a stand-in is recognised (so the copy that writes it and the
readers that leave it out cannot disagree) and no more: it imports nothing from the app until a condition is asked for.
"""

from __future__ import annotations

from typing import Any

#: The text a stand-in row carries in a text column that must not be NULL: ``(lost <table> <id>)``.
LOST_TEXT = "(lost {table} {row_id})"

#: The start of a stand-in SOURCE's domain (and name): ``LOST_TEXT`` for the ``sources`` table. A real domain cannot start with a parenthesis.
SOURCE_DOMAIN_PREFIX = "(lost sources "

#: The reason a stand-in ARTICLE is quarantined with. It is the one mark that tells a stand-in from an article the app judged to be not an
#: article, so a reader that includes quarantined items (the advanced search) can still leave the stand-ins out.
ARTICLE_REASON = "stand-in for a lost row"

#: Columns a stand-in is given beyond the ones its table requires, per table (written only where the table has the column): a stand-in article
#: is quarantined, which every quarantine-aware reader already leaves out (``Article.quarantined.isnot(True)``, the search, the browse, the
#: export, the analyses); a stand-in source is not enabled, so no collection pass takes it.
MARKS: dict[str, dict[str, Any]] = {
    "articles": {"quarantined": 1, "quarantine_reason": ARTICLE_REASON},
    "sources": {"enabled": 0},
}


def lost_text(table: str, row_id: int) -> str:
    """The text of a stand-in row's required text column."""
    return LOST_TEXT.format(table=table, row_id=int(row_id))


def not_a_stand_in_source() -> Any:
    """The SQL condition that leaves stand-in sources out of a list, a count, a qualification pass or an export (``Source`` rows)."""
    from src.database.models import Source

    return ~Source.domain.startswith(SOURCE_DOMAIN_PREFIX, autoescape=True)


def not_a_stand_in_article() -> Any:
    """The SQL condition that leaves stand-in articles out, for the readers that INCLUDE quarantined articles (``Article`` rows). NULL-safe: an
    article that was never judged has no reason at all."""
    from src.database.models import Article

    return Article.quarantine_reason.is_distinct_from(ARTICLE_REASON)


def is_a_stand_in_article(session: Any, article_id: int) -> bool:
    """Whether ``article_id`` is a stand-in article: for a route that is asked about an article by its id and never loads the row itself, and
    so must refuse the stand-in's id as it refuses an id that names nothing. It is the complement of :func:`not_a_stand_in_article`, so the
    two cannot disagree."""
    from src.database.models import Article

    return session.query(Article.id).filter(Article.id == article_id, ~not_a_stand_in_article()).first() is not None
