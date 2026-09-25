"""The versioned-source substrate: one shared spine for the wiki, law and OSM lanes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1003 = a (ruled 2026-09-15): ``src/versioned/`` shared by the wiki, law and OSM
lanes, the wiki adapter first. The package answers one question for three kinds of
external, mutable, authoritative corpus — *what did this source say, when, and what
changed* — so that a lane is an ADAPTER over a common spine rather than a third
implementation of versioning.

The pieces, in the order a change travels through them:

* ``lanes``      — the kind vocabulary, each kind's file and transport.
* ``store``      — one encrypted database file per lane, through the ONE keyed path.
* ``models``     — the lane tables, on their own declarative base.
* ``feed``       — the change feed: a cursor, dedup, and gap detection that PUBLISHES.
* ``revisions``  — the baseline, the revision store, the diff, the point-in-time read.
* ``budget``     — the published per-lane budgets and the measured-bytes arithmetic.
* ``politeness`` — a HOOK onto the fetcher's own politeness, never a second authority.
* ``integrity``  — the cross-file link check SQLite cannot express as a constraint.
* ``adapters``   — ``wiki`` (built), ``law`` and ``osm`` (interface only in 0.4).

NOTHING HERE TOUCHES THE NETWORK. An adapter is handed a client; the substrate calls
it. That is what lets the whole pipeline run in CI against a fixture with the
airplane socket guard armed (Q1018), and it is the property
``tests/test_versioned_lane.py::test_a_full_pass_makes_ZERO_NAME_RESOLUTIONS`` pins.
"""

from src.versioned.lanes import (
    KINDS,
    LaneSpec,
    UnknownLaneError,
    all_lanes,
    implemented_lanes,
    lane,
)

__all__ = [
    "KINDS",
    "LaneSpec",
    "UnknownLaneError",
    "all_lanes",
    "implemented_lanes",
    "lane",
]
