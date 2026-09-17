"""The lane registry — what a versioned-source lane IS, before any of them runs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1003 (ruled 2026-09-15) makes ``src/versioned/`` shared by the wiki, law and OSM
lanes, the wiki adapter first. This module is the part every other part reads: the
KIND vocabulary, the database FILENAME each kind owns (Q719/Q1004), and the
TRANSPORT each kind declares (Q1014).

WHY A REGISTRY AND NOT THREE CONSTANTS. Every lane-shaped question in this package
— which file to open, which budget row applies, what the consent hover says, which
disclosure the reader is owed — is answered by kind. A registry makes an unknown
kind a loud refusal at one chokepoint instead of a silent fall-through at each of
them, and it is what lets ``law`` and ``osm`` exist as an INTERFACE in 0.4 with no
half-built implementation pretending to be a feature.

THE TRANSPORT FIELD IS A TOKEN, NEVER A SENTENCE. ``src/static/net-hosts.js``'s
header states the rule for the table it carries and the same rule binds here: a
user-facing sentence is composed by the UI through ``OOI18N.t`` and ships x12,
because a hover is a caveat surface. What travels is the literal token; the words
that explain it live in the locale files.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it opens nothing, reads no settings and
touches no network. It is imported by the boot path, so it stays a data module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# Transport tokens. The vocabulary is deliberately tiny and CLOSED: a lane either
# follows the operator's transport setting (Q722 = b, "everything follows the
# transport setting, including the walk over Tor") or it is clearnet-only and says
# so. There is no third value meaning "whatever is available", because that value
# IS the silent Tor -> clearnet downgrade the non-negotiable forbids.
TransportToken = Literal["setting", "clearnet"]

#: Rows per ``IN`` clause, everywhere in this package. MEASURED on this machine
#: rather than recited: both the stdlib ``sqlite3`` (3.45.1) and the bundled
#: ``sqlcipher3`` (3.51.1) accept 250,000 host parameters and refuse 250,001 — NOT the
#: 999 that circulates as SQLite's limit, which was the compile-time default before
#: 3.32. The chunking is kept anyway, and the honest reason is that the ceiling is a
#: PER-BUILD setting: this app ships to whatever SQLCipher an operator's platform
#: provides, and a query that works on the developer's build and raises ``too many SQL
#: variables`` on a user's is a failure that arrives only in the field, only on large
#: corpora. 400 is far below every plausible build's floor and costs one extra round
#: trip per 400 rows.
#:
#: WHAT THIS MEANS FOR THE TESTS: no affordable test can drive a lane past 250,000
#: parameters, so the chunking cannot be killed by reaching a limit. It is asserted
#: STRUCTURALLY instead — that the work is split into several statements — which is
#: the property that actually protects the operator.
#:
#: It lives HERE, in the module with no dependencies of its own, because two copies of
#: a tuning number drift and the copy that is not updated is the one that fails on
#: somebody else's machine.
CHUNK_SIZE: Final[int] = 400

#: Every kind this package knows. Ordered as the lanes were ruled, wiki first.
KINDS: Final[tuple[str, ...]] = ("wiki", "law", "osm")


@dataclass(frozen=True, slots=True)
class LaneSpec:
    """One lane's identity. Frozen: a lane's file and transport are not runtime state."""

    #: Machine name. Also the ``kind`` half of the ``(kind, external_id)`` identity.
    kind: str
    #: The database file this lane owns, beside ``corpus.db`` in the data directory.
    #: Q719 = a: "a 100 GB lane never bloats the corpus file or its encryption rekey."
    filename: str
    #: The row name in ``docs/SECURITY.md`` AND the i18n key, exactly as
    #: ``net-hosts.js`` uses ``label`` — one string, three jobs, no second list.
    label: str
    #: ``net-hosts.js`` lane id this lane's hosts are enumerated under. The hosts
    #: themselves stay THERE (Q1001: one source of truth); this slice adds a
    #: transport LINE to that table's rows, never a new host.
    net_lane_id: str
    #: How this lane reaches its sources. See ``TransportToken``.
    transport: TransportToken
    #: True once the lane has a working adapter. ``law`` and ``osm`` are an
    #: INTERFACE in 0.4 (the brief's S1) — declaring that here is what stops a
    #: caller mistaking an unimplemented lane for an idle one.
    implemented: bool


_SPECS: Final[dict[str, LaneSpec]] = {
    "wiki": LaneSpec(
        kind="wiki",
        filename="wiki.db",
        label="Wikipedia / Wikimedia",
        net_lane_id="wikipedia",
        transport="setting",
        implemented=True,
    ),
    "law": LaneSpec(
        kind="law",
        filename="law.db",
        label="Law",
        net_lane_id="law",
        transport="setting",
        implemented=False,
    ),
    "osm": LaneSpec(
        kind="osm",
        filename="osm.db",
        label="Maps / OpenStreetMap",
        net_lane_id="osm",
        transport="setting",
        implemented=False,
    ),
}


class UnknownLaneError(ValueError):
    """Raised for a kind this package does not know.

    A distinct type because callers legitimately catch it (an API handler turns it
    into a 404) while never wanting to catch a genuine programming ``ValueError``
    from the same block.
    """


def lane(kind: str) -> LaneSpec:
    """Return the spec for ``kind``, or refuse by name.

    Refusing is the point: a typo'd kind that fell through to a default would open
    the wrong file, and on a package whose whole subject is one encrypted database
    per lane that is the worst available failure.
    """
    try:
        return _SPECS[kind]
    except KeyError:
        raise UnknownLaneError(
            f"unknown lane kind {kind!r}; known kinds are {', '.join(KINDS)}"
        ) from None


def all_lanes() -> tuple[LaneSpec, ...]:
    """Every lane, in ``KINDS`` order. Includes the unimplemented ones by design.

    Settings -> Storage has to list a lane that has never run — reporting it ABSENT
    with a reason is the honest state, and a list built from "lanes with a file"
    could not say the word.
    """
    return tuple(_SPECS[k] for k in KINDS)


def implemented_lanes() -> tuple[LaneSpec, ...]:
    """Only the lanes with a working adapter. Use for scheduling, never for display."""
    return tuple(s for s in all_lanes() if s.implemented)
