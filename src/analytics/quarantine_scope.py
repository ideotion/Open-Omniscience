"""The one quarantine filter the keyword aggregates and the language series share (R101).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R101 (ruled 2026-09-30, the question ``D22`` / ``PRH-06``): an article the app quarantined as "not an
article" leaves the keyword figures, the per-language series and the equilibrium lever, in ONE slice,
so no call answers differently depending on which store served it. Every one of those readers takes
its filter from here, so they cannot drift apart:

* :func:`not_quarantined` is the SQL condition, written as ``<id> NOT IN (SELECT id FROM articles WHERE
  quarantined IS 1)``. That shape is deliberate: the subquery is answered from ``idx_article_quarantined``
  alone (SQLite carries the rowid in every index), so a reader that is index-only today stays
  index-only. A join to ``articles`` on ``quarantined`` would drag each article row through the SQLCipher
  codec, the recorded perf trap the language series and the mention scans were built to avoid.
* :func:`quarantined_article_ids` is the same set, read once, for the DuckDB rollup build, which filters
  rows as it stages them rather than asking SQLite again for every batch.

``quarantined`` NULL ("never judged") counts as not quarantined, as it does for every other reader.
Stand-in articles are quarantined (``src/database/stand_in.py``), so they leave these figures too.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Article


def quarantined_ids_select():
    """``SELECT id FROM articles WHERE quarantined IS 1``: the subquery every filter here uses."""
    return select(Article.id).where(Article.quarantined.is_(True))


def not_quarantined(article_id_column: Any):
    """The condition that keeps a row whose article is NOT quarantined. ``article_id_column`` is the
    column holding the article id: ``Article.id`` itself, or a mention's ``article_id``."""
    return article_id_column.not_in(quarantined_ids_select())


def quarantined_article_ids(session: Session) -> frozenset[int]:
    """Every quarantined article's id, read once (an index-only scan of ``idx_article_quarantined``)."""
    return frozenset(int(i) for (i,) in session.execute(quarantined_ids_select()))
