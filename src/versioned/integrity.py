"""The check that stands in for a foreign key SQLite cannot give us.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``VersionedRevision.article_id`` names a row in ``corpus.db``. SQLite has no
cross-database foreign keys — ``PRAGMA foreign_keys`` constrains one schema — so
that column has NO referential integrity behind it. Two ordinary operator actions
break it, neither of them a bug: deleting articles from the corpus, and restoring a
corpus backup taken before a lane pass.

WHAT THIS MODULE REFUSES TO DO. It does not repair. A dangling ``article_id`` is a
fact about two files that disagree, and the repairs available are both destructive
guesses: NULLing the column throws away the knowledge that a version WAS indexed,
and re-indexing rewrites the corpus from the lane on the assumption the lane is the
newer of the two. Which is right depends on what the operator did, and this code
does not know. So it REPORTS — a count, a sample, and the time it looked.

AND IT IS A POINT-IN-TIME READING, WHICH IS WHY THE RESULT CARRIES ITS CLOCK. The
two files are read one after the other without a shared transaction (they are
separate databases and separate connections); a write between the two reads is
invisible to this function. A result that named no instant would read as a standing
guarantee, which is exactly what it cannot be.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.versioned.lanes import CHUNK_SIZE
from src.versioned.models import VersionedRevision, _utcnow

_LOG = logging.getLogger("versioned.integrity")

#: How many dangling ids a report carries verbatim. A sample, never a page of a
#: result set: the figure a caller acts on is ``dangling``, and the examples are
#: there so an operator can open one and see what happened.
SAMPLE_SIZE = 20


@dataclass(frozen=True, slots=True)
class LinkReport:
    """What the two files said, and when they were asked.

    ``linked`` is how many revisions claim an Article; ``dangling`` is how many of
    those claims the corpus cannot honour. They are separate numbers because
    ``0 of 0`` and ``0 of 4,912`` are different facts and a ratio hides which one
    you have.
    """

    checked_at: datetime
    linked: int
    dangling: int
    sample: list[int] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.dangling == 0

    def as_dict(self) -> dict:
        return {
            "checked_at": self.checked_at.isoformat(),
            "linked": self.linked,
            "dangling": self.dangling,
            "sample": list(self.sample),
            "clean": self.clean,
            # The method travels with the numbers, per the standing rule that every
            # signal carries method + caveat: a reader of this dict must not have to
            # find this module to learn that it is a point-in-time reading.
            "method": "read the lane's article_id values, then asked the corpus which exist",
            "caveat": "two files read without a shared transaction; a write between the two reads is invisible",
        }


def check_article_links(lane: Session, corpus: Session) -> LinkReport:
    """Count the lane's Article links the corpus cannot honour.

    Takes TWO named sessions, as everything cross-file in this package does, so a
    caller cannot accidentally hand it one session and have it answer about one
    database — which would report ``0 dangling`` for the reassuring reason that it
    never asked the other file.
    """
    from src.database.models import Article

    ids = [
        row
        for row in lane.execute(
            select(VersionedRevision.article_id).where(VersionedRevision.article_id.is_not(None))
        ).scalars()
        if row is not None
    ]
    checked_at = _utcnow()
    if not ids:
        return LinkReport(checked_at=checked_at, linked=0, dangling=0, sample=[])

    wanted = set(ids)
    present: set[int] = set()
    # Chunked at CHUNK_SIZE; the measurement behind that number is in ``lanes.py``. A
    # lane with 50,000 linked revisions is an ordinary lane, and the failure a single
    # IN clause risks would arrive only on the corpora large enough for this check to
    # matter, and only on some operators' builds.
    ordered = sorted(wanted)
    for start in range(0, len(ordered), CHUNK_SIZE):
        chunk = ordered[start : start + CHUNK_SIZE]
        present.update(corpus.execute(select(Article.id).where(Article.id.in_(chunk))).scalars())

    missing = sorted(wanted - present)
    if missing:
        _LOG.warning(
            "versioned lane: %d of %d article links dangle (e.g. %s)",
            len(missing),
            len(wanted),
            missing[:5],
        )
    return LinkReport(
        checked_at=checked_at,
        linked=len(wanted),
        dangling=len(missing),
        sample=missing[:SAMPLE_SIZE],
    )
