"""What a lane adapter must provide, and what the substrate promises it in return.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1003 = a: one substrate, three lanes, "the wiki adapter first". This module is the
seam. An adapter knows one source's vocabulary — what an id looks like, how to ask
for a change list, how a version's text is fetched, what the reader must be told
about the licence — and knows nothing about databases, cursors, gaps or budgets.
The substrate knows those and nothing about MediaWiki, CLML or OSM.

THE ADAPTER IS HANDED ITS CLIENT; IT NEVER BUILDS ONE. That single rule is what
makes Q1018's "every lane's pipeline runs end-to-end in CI without a socket" true by
construction rather than by a mock nobody can see: the fixture passes a client that
reads files, production passes one that reads the network through the guarded
session, and the code between them is byte-identical. An adapter that reached for
``WikiClient()`` itself would put a socket inside the thing under test.

WHY A PROTOCOL AND NOT A BASE CLASS. ``law`` and ``osm`` are an INTERFACE in 0.4 —
the brief's S1 is explicit — and a structural type lets that be true without
shipping two abstract classes whose only method bodies are ``raise
NotImplementedError``. A stub that pretends to be a lane is worse than an absence:
the registry's ``implemented`` flag is a fact a caller can read, and an abstract
method that raises at runtime is one it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from src.versioned.feed import ChangeBatch


@dataclass(frozen=True, slots=True)
class FetchedVersion:
    """One version of one entity, as the source served it.

    Everything here is the SOURCE's, verbatim. The substrate hashes the text,
    diffs it and stores it; it does not parse ``revision_ref`` or interpret
    ``revised_at``'s provenance.
    """

    external_id: str
    revision_ref: str
    text: str
    revised_at: datetime | None = None
    title: str | None = None
    qid: str | None = None
    language: str | None = None
    #: ISO 3166-1 **alpha-3** where the source states a country. Alpha-3 from birth
    #: (Q312 = a): an adapter that has alpha-2 converts before returning, so no
    #: alpha-2 ever reaches a lane column.
    country_alpha3: str | None = None


@dataclass(frozen=True, slots=True)
class ReadBudget:
    """What one read of a feed may spend. Set by the caller, honoured by the adapter.

    An adapter that cannot finish inside the budget returns what it has AND a
    ``GapReport`` with reason ``budget`` on its batch — the substrate then records a
    gap rather than a silently short answer, which is the whole difference between
    "nothing else changed" and "we stopped looking".
    """

    #: Maximum requests this read may make. ``None`` means the caller is not
    #: bounding requests — never "unlimited by default": every production call site
    #: passes a number.
    max_requests: int | None = None
    #: Maximum entity versions to FETCH TEXT for. Metadata for every change is
    #: cheap and is always recorded; text is what costs bytes.
    max_versions: int | None = None
    #: Wall-clock deadline for this read, as a monotonic deadline the adapter
    #: compares against. ``None`` means no deadline.
    deadline_s: float | None = None


@runtime_checkable
class VersionedAdapter(Protocol):
    """The contract a lane adapter satisfies."""

    #: Must equal one of ``src.versioned.lanes.KINDS``.
    kind: str

    def feeds(self) -> tuple[str, ...]:
        """The feed names this adapter reads. One lane may have several."""
        ...

    def read_changes(self, *, feed: str, since: str | None, budget: ReadBudget) -> ChangeBatch:
        """Read one batch of changes from ``feed``, resuming at ``since``.

        ``since`` is the token the substrate stored. An adapter that cannot resume
        from it MUST say so on the returned batch (``gap=GapReport(...)``) rather
        than starting over quietly — the substrate cannot tell the two apart from
        the outside, and a silent restart is a permanent hole.
        """
        ...

    def fetch_version(self, external_id: str) -> FetchedVersion | None:
        """Fetch the CURRENT version of one entity, or ``None`` if the source has none.

        ``None`` means the source says the thing is not there (deleted, never
        existed). A FAILURE raises — the two must not share a return value, because
        "the page is gone" and "we could not ask" lead to opposite decisions.
        """
        ...

    def to_article(self, session: Session, version: FetchedVersion) -> int | None:
        """Put this version into the CORPUS as an Article, returning its id.

        Goes through the real ``index_article`` — never a second indexing path, so a
        lane's articles are searched, counted and analysed exactly like any other.
        ``None`` when this kind does not produce Articles.
        """
        ...

    def disclosure_keys(self) -> tuple[str, ...]:
        """i18n KEYS for what the reader must be told about this lane's data.

        Keys, never sentences: the record of what an operator was shown has to
        survive a locale change and a rewording, and storing English would make it
        a claim about a language they may not read.
        """
        ...


def check_adapter(adapter: object) -> None:
    """Refuse an object that does not satisfy the contract, by name.

    ``runtime_checkable`` Protocols check only that the ATTRIBUTES exist, never
    their signatures — so this adds the one check that matters in practice (the
    ``kind`` is a known lane) and states plainly what it does not check. A test
    pins the signatures against ``inspect.signature``, which is the recorded remedy
    for a hand-written double that drifts from the class it doubles.
    """
    from src.versioned.lanes import lane

    if not isinstance(adapter, VersionedAdapter):
        missing = [
            name
            for name in ("kind", "feeds", "read_changes", "fetch_version", "to_article")
            if not hasattr(adapter, name)
        ]
        raise TypeError(f"{type(adapter).__name__} is not a versioned adapter; missing {missing}")
    lane(adapter.kind)  # raises UnknownLaneError for a kind the registry does not know
