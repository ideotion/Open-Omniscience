"""
Crowdsourced source annotations — signed, portable, federated by trust (§6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The owner's key correction to §6: weighting sources is impossible for one person —
nobody can neutrally assess thousands of sources alone. So the weighting must be
**collective**, and the honest, local-first, non-centralised way to do that is
**signed, shareable annotation bundles**:

  * a user publishes their source annotations (coordination tags, transparency facts,
    corrections) as a **custody-signed, verifiable, portable bundle** — *mutualising*
    the hybrid-signature machinery already used for evidence;
  * other users **import** the bundles they choose to trust (opt-in **web-of-trust**,
    never a central authority);
  * aggregation is **transparent**: you always see *who asserted what*, and dissent is
    shown, never averaged into a hidden number.

No server, no accounts, no global score — federation by signed exchange.
"""

from __future__ import annotations

from src.annotations.bundle import (
    Annotation,
    build_signed_bundle,
    verify_bundle,
)
from src.annotations.store import (
    add_annotation,
    adopt_imported_record,
    aggregate_for_target,
    export_bundle,
    import_bundle,
    list_authors,
    load_mine,
    remove_annotation,
    remove_author,
    set_trusted,
)

__all__ = [
    "Annotation",
    "build_signed_bundle",
    "verify_bundle",
    "add_annotation",
    "adopt_imported_record",
    "remove_annotation",
    "load_mine",
    "export_bundle",
    "import_bundle",
    "list_authors",
    "set_trusted",
    "remove_author",
    "aggregate_for_target",
]
