"""What identifies a Wikipedia page in this app, and what to do with the old answer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q715 = a: "``WikiPage`` keyed ``(wiki, pageid)`` with ``qid``; the Article carries
``wiki_pageid``, ``qid``, ``source_revision`` (exists), ``source_type="wikipedia"``,
the edition as language."

THE REASON THE KEY IS NOT THE TITLE. A page MOVE changes the title and nothing else:
same page, same history, same watchers, new name. A title-keyed store sees a move as
a DELETION plus a CREATION — two entities where there is one, the older one frozen
forever at its last pre-move revision and never updated again. Nothing in the data
says this happened, so the corpus quietly acquires a duplicate whose divergence from
reality grows with every later edit. The page id does not move.

WHY THIS BECAME POSSIBLE ONLY NOW, stated because the previous answer was recorded as
a constraint rather than a preference. ``src/versioned/adapters/wiki.py`` chose the
title because "``list=recentchanges`` reports ``title`` and no ``pageid``", which was
a conclusion drawn from ``src.wiki.mediawiki.parse_recentchanges`` — our parser — and
not from the API. The parser was dropping the field: its request already asks for
``rcprop=ids`` and it already keeps ``revid`` and ``old_revid``, which come from that
same prop. It now keeps ``pageid`` too. EventStreams carries ``page_id`` on every
event besides. So both of this lane's change sources name the page id, and the ruled
identity costs nothing.

THE TWO FORMS COEXIST ON PURPOSE. A lane written before this module used
``"{wiki}:{title}"``; this one writes ``"{wiki}:p{pageid}"``. They are distinguishable
by construction — a MediaWiki title cannot begin with a lowercase ``p`` followed only
by digits and then end, because the first character of a title is capitalised by the
software — so :func:`parse_external_id` can read either without a schema version to
consult. That is what lets :func:`reconcile_to_page_id` upgrade a legacy row AT THE
MOMENT the stream first names both the title and the id for that page, with no
network call, no guess, and no migration that would have had to invent the mapping it
cannot know offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``{wiki}:p{pageid}``. A lowercase ``p`` then digits then the end — a shape no
#: MediaWiki title can take, since titles are capitalised on the first character.
_PAGE_ID_FORM = re.compile(r"^p(\d+)$")


@dataclass(frozen=True, slots=True)
class WikiIdentity:
    """A parsed lane identity. Exactly one of ``page_id`` / ``title`` is set."""

    wiki: str
    page_id: int | None = None
    title: str | None = None

    @property
    def is_legacy(self) -> bool:
        """True for the title-keyed form this lane no longer writes."""
        return self.page_id is None


def external_id_for(wiki: str, page_id: int) -> str:
    """The ruled identity. The ONE place the format is written.

    Refuses a non-positive id rather than encoding it: MediaWiki page ids start at 1,
    so a 0 here means a caller read an absent field through an ``or 0`` and is about
    to give every page with a missing id the SAME identity — one entity accumulating
    the revisions of many, which no later repair could untangle.
    """
    if not isinstance(page_id, int) or isinstance(page_id, bool) or page_id <= 0:
        raise ValueError(
            f"a wiki lane identity needs a real page id, got {page_id!r}; "
            "an absent id must be handled as absent, never encoded as 0"
        )
    if not wiki:
        raise ValueError("a wiki lane identity needs an edition code")
    return f"{wiki}:p{page_id}"


def legacy_external_id_for(wiki: str, title: str) -> str:
    """The title-keyed form, for READING rows written before Q715 was built.

    Kept as a named function rather than an f-string at a call site so that every
    place still capable of producing the old shape is greppable — and so that the day
    the last legacy row is gone, deleting this function shows exactly what breaks.
    """
    if not wiki or not title:
        raise ValueError("a legacy wiki lane identity needs an edition and a title")
    return f"{wiki}:{title}"


def parse_external_id(external_id: str) -> WikiIdentity:
    """Read either form. Splits on the FIRST colon only.

    Titles legitimately contain colons (``Category:Physics``, ``Talk:X``), so a naive
    ``split(":")`` would truncate a namespaced title and address a different, equally
    plausible page — silently. That trap is the reason this is a function.
    """
    wiki, sep, rest = external_id.partition(":")
    if not sep or not wiki or not rest:
        raise ValueError(f"not a wiki lane external id: {external_id!r}")
    match = _PAGE_ID_FORM.match(rest)
    if match is not None:
        return WikiIdentity(wiki=wiki, page_id=int(match.group(1)))
    return WikiIdentity(wiki=wiki, title=rest)


def reconcile_to_page_id(session, *, wiki: str, title: str, page_id: int) -> str | None:
    """Upgrade a legacy title-keyed entity to the ruled id. Returns the new id, or ``None``.

    Called when a change names BOTH the title and the page id — which every
    EventStreams event does, and every ``list=recentchanges`` row now does too. That
    is the only moment the mapping is known without asking the network, so it is the
    moment to use it.

    IT REFUSES TO MERGE. If an entity already exists under the ruled id, this returns
    ``None`` and leaves the legacy row alone rather than folding one into the other.
    Merging two entities means deciding which baseline survives, which revisions are
    duplicates and which article link is canonical — decisions with no safe default,
    made here on a background thread, unlogged. Leaving both is visible and
    repairable; a wrong merge is neither. The collision is returned to the caller as
    a ``None`` so it can be counted and surfaced.
    """
    from src.versioned.models import VersionedEntity

    ruled = external_id_for(wiki, page_id)
    legacy = legacy_external_id_for(wiki, title)
    if ruled == legacy:
        return None
    row = (
        session.query(VersionedEntity)
        .filter(VersionedEntity.external_id == legacy)
        .one_or_none()
    )
    if row is None:
        return None
    clash = (
        session.query(VersionedEntity.id)
        .filter(VersionedEntity.external_id == ruled)
        .first()
    )
    if clash is not None:
        return None
    row.external_id = ruled
    row.title = row.title or title
    session.flush()
    return ruled
