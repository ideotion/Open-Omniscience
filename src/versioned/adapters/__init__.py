"""Lane adapters. ``wiki`` is built; ``law`` and ``osm`` are an INTERFACE in 0.4.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THERE IS NO ``law.py`` OR ``osm.py`` HERE, AND THAT IS THE DESIGN. The brief's S1
gives those two lanes "an INTERFACE only", and the interface is
``base.VersionedAdapter`` — a structural Protocol. Shipping two classes whose every
method raises ``NotImplementedError`` would be strictly worse than their absence: a
stub satisfies ``isinstance`` checks, appears in a registry walk, and is
indistinguishable from a working adapter until it is called, whereas
``lanes.lane("law").implemented`` is False and a caller can read it.

Their lane FILES, budgets, transport and Settings -> Storage rows all exist — the
substrate is complete for three kinds. What does not exist is the code that speaks
CLML or reads an OSM extract, which is S04-10's and 0.5's respectively.
"""

from src.versioned.adapters.base import (
    FetchedVersion,
    ReadBudget,
    VersionedAdapter,
    check_adapter,
)
from src.versioned.adapters.wiki import WikiLaneAdapter, external_id_for, split_external_id

__all__ = [
    "FetchedVersion",
    "ReadBudget",
    "VersionedAdapter",
    "WikiLaneAdapter",
    "check_adapter",
    "external_id_for",
    "split_external_id",
]
