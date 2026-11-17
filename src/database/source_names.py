"""The name a source is SHOWN under (field test 2026-11-14, row 71).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Some sources are stored under a bare Wikidata identifier (``Q11858063``) because the label was
never resolved: 315 shipped catalogue rows and many discovery candidates. A reader showing
"Q11858063" as the outlet tells the reader nothing. Every display path falls back to the
source's domain instead, which is what the reader can check. The STORED name is never changed
here: the consented label resolver (``POST /api/sources/resolve-qid-names``) and the
maintenance count (``GET /api/quarantine/raw-ids``) still find the row by its bare id.

Dependency-free on purpose: the label resolver's own test (``src.catalog.qid_labels``) imports
the Wikidata ring module, too heavy for a reader page. The pattern is the same one.
"""

from __future__ import annotations

import re

#: The same test as ``src.catalog.qid_labels.looks_like_bare_qid``; a test pins the two together.
_BARE_QID = re.compile(r"^\s*[Qq]\d+\s*$")


def is_bare_qid(name: str | None) -> bool:
    """Is this name only a Wikidata identifier, nothing else?"""
    return bool(name and _BARE_QID.match(name))


def shown_source_name(name: str | None, domain: str | None) -> str | None:
    """The name to display: the stored name, or the domain when the name is a bare identifier.

    A bare id with no domain stays as it is: showing nothing would hide that the source exists.
    """
    if is_bare_qid(name) and domain and domain.strip():
        return domain.strip()
    return name
