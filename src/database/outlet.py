"""An OUTLET is a domain; a source is one of its feeds (row J, S05-10 J2).

With ``UNIQUE (domain, feed_key)`` one outlet can hold several sources (BBC's thirty-one language services), and
every gate that states independence, coordination or convergence as a finding must count the OUTLET once: two feeds
of one site are one voice, and counting them as two would manufacture agreement out of a single publisher. A gate that
used to read "distinct sources" by id reads "distinct outlets" by domain here.

Identity is the DOMAIN, never the display name: names are not unique and a feed's name differs from its siblings'
(that is the point of a language service). The LABEL a gate shows, and the label a stored decision is keyed on (an
actor's signature is a hash of member NAMES), is the name of the outlet's OLDEST source -- the row every install
already has -- so on today's one-row-per-domain data nothing a user has saved changes meaning.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, func, literal
from sqlalchemy.orm import Session

from src.database.models import Source


def outlet_expr(source_id_col: Any, domain_col: Any) -> Any:
    """SQL: the outlet an article's source belongs to -- its domain, or ``source-<id>`` when the source row is gone.

    For ``count(distinct ...)``: the domain column must come from a join to ``sources`` on the same row, and the
    join must be OUTER where an article may lack a source, or the unmatched rows leave the count."""
    return func.coalesce(domain_col, literal("source-").op("||")(cast(source_id_col, String)))


class OutletMap:
    """``source_id -> outlet`` for one gate's run, read once (a few thousand rows)."""

    def __init__(self, session: Session) -> None:
        self._domain: dict[int, str] = {}
        self._label: dict[str, str] = {}
        self._primary: dict[str, int] = {}
        for sid, name, domain in session.query(Source.id, Source.name, Source.domain).order_by(Source.id):
            self._domain[int(sid)] = domain
            self._label.setdefault(domain, name or domain)
            self._primary.setdefault(domain, int(sid))

    def key(self, source_id: int | None, domain: str | None = None) -> str:
        """The outlet of a source: its domain. ``domain`` is the caller's own row value, used when the id is not
        in the map (an article whose source row is gone keeps the stable ``source-<id>`` it always had)."""
        if source_id is not None and int(source_id) in self._domain:
            return self._domain[int(source_id)]
        return domain or f"source-{source_id}"

    def primary_id(self, source_id: int) -> int:
        """The id of the outlet's OLDEST source -- a stable per-outlet integer for callers keyed on source ids."""
        d = self._domain.get(int(source_id))
        return self._primary[d] if d is not None else int(source_id)

    def label(self, source_id: int | None, name: str | None = None, domain: str | None = None) -> str:
        """The outlet's display label: the name of its oldest source, else the caller's own ``name or domain``
        fallback -- exactly the label every gate used before, for a one-source outlet."""
        d = self.key(source_id, domain)
        if d in self._label:
            return self._label[d]
        return name or domain or f"source-{source_id}"
