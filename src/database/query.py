"""Small shared SQLAlchemy query helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations


def capped(query, n: int | None):
    """Apply an OPTIONAL row cap.

    ``n <= 0`` (or ``None``/falsy) means **UNBOUNDED** -- return the query
    unchanged so every matching row is covered. A guard is required because
    SQLite ``LIMIT 0`` returns NO rows, the exact opposite of "no limit".

    Rationale (maintainer 2026-06-13): a per-run source cap silently *selects*
    which sources to skip, and that selection cannot be justified -- collection
    must reach every source. Ordering still decides what runs first; this only
    removes the exclusion.
    """
    return query.limit(n) if n and n > 0 else query
