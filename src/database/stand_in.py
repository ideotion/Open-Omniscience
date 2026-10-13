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

#: The start of a stand-in ARTICLE's hash: ``LOST_TEXT`` for the ``articles`` table, which fills the column the table keeps unique and indexes
#: (``idx_article_hash``). A real hash is a hex digest, so none starts with a parenthesis. :func:`stand_in_article_ids` and
#: :func:`not_a_stand_in_article_id` read the mark through that index as the RANGE ``ARTICLE_HASH_PREFIX <= hash < ARTICLE_HASH_END``: the
#: end is the prefix and the character that follows ``9``, so every ``(lost articles <digits>)`` is inside it and nothing else is. ``LIKE`` and
#: ``substr()`` do not seek an index (measured on SQLite 3.45.1: a scan of the table), a range does.
ARTICLE_HASH_PREFIX = "(lost articles "
ARTICLE_HASH_END = ARTICLE_HASH_PREFIX + ":"

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


def is_a_stand_in_source(source: Any) -> bool:
    """Whether a LOADED ``Source`` row is a stand-in, for the code that holds the row already and must not run a query per row (the newsletter
    import places thousands of messages). It is :func:`not_a_stand_in_source` read in Python, and a test pins that the two agree on every row."""
    return str(getattr(source, "domain", None) or "").startswith(SOURCE_DOMAIN_PREFIX)


def not_a_stand_in_article() -> Any:
    """The SQL condition that leaves stand-in articles out, for the readers that INCLUDE quarantined articles (``Article`` rows). NULL-safe: an
    article that was never judged has no reason at all."""
    from src.database.models import Article

    return Article.quarantine_reason.is_distinct_from(ARTICLE_REASON)


def is_a_stand_in_article(session: Any, article_id: int) -> bool:
    """Whether ``article_id`` is a stand-in article: for a route that is asked about an article by its id and never loads the row itself, and
    so cannot filter the row it loads (the date tags and the AI keywords of an article). It is the complement of :func:`not_a_stand_in_article`,
    so the two cannot disagree. It says nothing of an id that names no article at all: such a route answers an absent id as it always did (an
    empty list), and only the stand-in's id is refused."""
    from src.database.models import Article

    return session.query(Article.id).filter(Article.id == article_id, ~not_a_stand_in_article()).first() is not None


def _stand_in_article_id_select() -> Any:
    """``SELECT id FROM articles WHERE hash >= :prefix AND hash < :end``: every stand-in article's id, read from the hash index alone (``id`` is the
    row id, which every index entry carries), so no article row page is read whatever the size of the table. Never correlated to an enclosing
    query, so the same condition also leaves the stand-ins out of a scan of ``articles`` itself (``Article.id``)."""
    from sqlalchemy import select

    from src.database.models import Article

    return select(Article.id).where(Article.hash >= ARTICLE_HASH_PREFIX, Article.hash < ARTICLE_HASH_END).correlate(None)


def not_a_stand_in_article_id(column: Any) -> Any:
    """The SQL condition that leaves out the rows of a CHILD table (a link, a mention, a date tag, an entity) whose ``article_id`` names a
    stand-in article, without a JOIN to ``articles``: ``column NOT IN (SELECT id FROM articles WHERE hash >= :prefix AND hash < :end)``. A join
    drags whole article rows through the codec (measured 807 to 4,860 MiB on a large store); this asks the hash index only (0.03 MiB per call
    whatever the size of the set, +0.01 MiB on a 200,000-row scan). A child row whose column is NULL names no article and is kept."""
    from sqlalchemy import or_

    return or_(column.is_(None), column.not_in(_stand_in_article_id_select()))


def stand_in_article_ids(session: Any) -> set[int]:
    """Every stand-in article's id, in ONE index-only read (:func:`_stand_in_article_id_select`) whose cost does not depend on the set a caller
    holds: the caller subtracts them from its own ids in Python. Asking per id costs a row page each (the reason sits after the article text)."""
    return {int(r[0]) for r in session.execute(_stand_in_article_id_select())}


def stand_in_article_count(session: Any) -> int:
    """How many stand-in articles there are, in ONE index-only count over the same hash range as :func:`stand_in_article_ids`, for a caller that needs
    the number and not the ids (it holds nothing, whatever the size of the set)."""
    from sqlalchemy import func, select

    return int(session.execute(select(func.count()).select_from(_stand_in_article_id_select().subquery())).scalar() or 0)
