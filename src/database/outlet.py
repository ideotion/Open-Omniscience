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

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from src.database.models import Source

FEEDS_NOT_OUTLETS = (
    "Sources here are feeds (the rows of your sources list), not outlets: one outlet can hold several."
)
"""The sentence every user-visible FEED-level source count carries (row J, R146 (b)): a count that is the size of the
sources list is a true count of feeds, and reads as a count of independent voices unless it says what it counts."""


def outlet_key(source_id: int | None, domain: str | None) -> str:
    """The outlet of ONE source, from its own row values: its domain, or ``source-<id>`` when the row is gone.

    The single definition: ``OutletMap.key`` and ``outlet_expr`` agree with it, and a record that has to carry its outlet
    with it (a briefing card's evidence, stored long before anything reads it) writes this value."""
    return domain or f"source-{source_id}"


def outlet_expr(source_id_col: Any, outlet_id_col: Any, *, unhealed: bool = False) -> Any:
    """SQL: the outlet an article's source belongs to, as an INTEGER -- the lowest id among the sources of its domain
    (``sources.outlet_id``), or the bare source id when the source row is gone.

    For ``count(distinct ...)``: ``outlet_id_col`` must be ``Source.outlet_id`` from a join to ``sources`` on the same row,
    and the join must be OUTER where an article may lack a source, or the unmatched rows leave the count. An outlet id is the
    id of a row that exists and shares the domain (three triggers on ``sources`` keep it so, ``SOURCE_OUTLET_ID_TRIGGERS``), so
    it can never equal an orphan's own source id: an orphan stays its own outlet.

    ``outlet_id`` is NULL only on a row written before the boot step reached it, or when that step failed (trigger creation or
    the heal) until the next boot. Read plainly, such a row counts as its own outlet, which OVERCOUNTS outlets -- the unsafe
    direction (R146: manufactured agreement). ``unhealed=True`` adds the exact reading, the lowest id of the row's own domain,
    as a correlated subquery. It is NOT the default: always on, it measured +29 % on a 2.34 M-mention window (encrypted), so a
    gate asks ``outlets_unhealed`` ONCE per run and passes the answer, and a healed store reads the plain form.

    Why an integer and not the domain: a text key costs a hash of a string per scanned mention row. On a 2.34 M-mention window
    ``source_id`` alone read 4.28 s plain (5.07 s encrypted); the text join 6.47 s (5.97 s); ``coalesce(domain, source_id)``
    5.37 s plain and, on an ENCRYPTED store, 5.89 s, which is NOT distinguishable from the text join there; this integer 4.51 s
    plain and 5.21 s encrypted (R177; ``plan-row-j/outlet-key-design-2026-10-17``). The value is only counted, never read back;
    the Python spelling for display, ``outlet_key``, stays the domain or ``source-<id>``. SQLite only."""
    if not unhealed:
        return func.coalesce(outlet_id_col, source_id_col)
    sibling = aliased(Source)
    oldest = (
        select(func.min(sibling.id)).where(sibling.domain == Source.domain).correlate(Source).scalar_subquery()
    )
    return func.coalesce(outlet_id_col, oldest, source_id_col)


def outlets_unhealed(session: Session) -> bool:
    """True when at least one source row has no ``outlet_id`` yet (a store the boot step has not reached, or reached and failed).

    One indexed probe (``LIMIT 1``; 0.044 s at 700,000 sources); a gate asks it once per run and passes it as ``unhealed=``."""
    return session.query(Source.id).filter(Source.outlet_id.is_(None)).first() is not None


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
        return outlet_key(source_id, domain)

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


def outlets_per_language(session: Session, source_ids: Any, outlets: OutletMap, normalize_lang: Any) -> dict[str, int]:
    """``language -> number of distinct OUTLETS with at least one source of that language among ``source_ids``.

    The denominator of a language-ubiquity ratio whose numerator counts outlets: an outlet that carries a Spanish
    service counts as a Spanish outlet whichever of its feeds happens to be the oldest, so numerator and denominator
    are the same unit (the ratio of 3 of 8 must not read 3 of 5 because a sibling's language was ignored)."""
    ids = sorted({int(x) for x in source_ids})
    pairs: set[tuple[str, str]] = set()
    for i in range(0, len(ids), 500):
        for sid, lang in session.query(Source.id, Source.language).filter(Source.id.in_(ids[i:i + 500])):
            lg = normalize_lang(lang)
            if lg:
                pairs.add((lg, outlets.key(int(sid))))
    by_lang: dict[str, int] = {}
    for lg, _outlet in pairs:
        by_lang[lg] = by_lang.get(lg, 0) + 1
    return by_lang
