"""Keyword -> super-group reverse lookup (supergroups brief S3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A keyword belongs to a super-group two ways: DIRECTLY as a plain family member
(matched by ``canonical_key`` — the same morphological match S1 uses), or
INDIRECTLY via a ring covering the keyword's own (language, normalized_term)
(the super-ring model). This module is the cheap REVERSE index — every
super-group's membership rows are already in the DB and small (a few hundred
rows at most), so the whole index is built ONCE, cached per process, and
invalidated on any curation write (create/delete a group, add/remove a member).

PLURAL membership is real (the same keyword can sit in more than one group,
directly or via more than one covering ring) — the lookup returns every hit,
never silently picks one.
"""

from __future__ import annotations

import threading

from src.analytics.families import canonical_key

_LOCK = threading.Lock()
_CACHE: dict | None = None  # {"family": {canonical_key: [(sg_id, sg_name)]},
#                             "ring": {ring_id: [(sg_id, sg_name)]}}


def invalidate() -> None:
    """Drop the cached reverse index — call after ANY super-group curation write
    (create/delete a group, add/remove a member) so the next lookup rebuilds it."""
    global _CACHE
    with _LOCK:
        _CACHE = None


def _build(db) -> dict:
    from src.database.models import KeywordSuperGroup

    family: dict[str, list[tuple[int, str]]] = {}
    ring: dict[str, list[tuple[int, str]]] = {}
    for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all():
        for m in sg.members:
            entry = (sg.id, sg.name)
            if m.ring_id:
                ring.setdefault(m.ring_id, []).append(entry)
            else:
                family.setdefault(canonical_key(m.normalized_term), []).append(entry)
    return {"family": family, "ring": ring}


def _index(db) -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = _build(db)
        return _CACHE


def supergroups_for_keyword(db, normalized_term: str, language: str | None = None) -> list[dict]:
    """Every super-group this keyword belongs to — directly (a plain family
    member matching its canonical key) or via a covering ring (when
    ``language`` is given, resolved through :func:`equivalence.ring_of`).

    Returns ``[{"id", "name", "via": "family"|"ring", "ring_id"?}]``, deduped by
    group id (a keyword covered by BOTH a direct family entry and a ring in the
    same group is listed once, tagged by whichever hit first). Empty (never a
    guess) when the keyword is in no group at all."""
    idx = _index(db)
    seen: set[int] = set()
    out: list[dict] = []

    for sg_id, sg_name in idx["family"].get(canonical_key(normalized_term), []):
        if sg_id not in seen:
            seen.add(sg_id)
            out.append({"id": sg_id, "name": sg_name, "via": "family"})

    if language:
        from src.analytics.equivalence import ring_of

        ring_id = ring_of(language, normalized_term)
        if ring_id:
            for sg_id, sg_name in idx["ring"].get(ring_id, []):
                if sg_id not in seen:
                    seen.add(sg_id)
                    out.append({"id": sg_id, "name": sg_name, "via": "ring", "ring_id": ring_id})

    return out


def supergroups_for_keywords(
    db, keywords: list[tuple[str, str | None]]
) -> dict[str, list[dict]]:
    """Batched reverse lookup for many ``(normalized_term, language)`` pairs — the
    index is built/cached ONCE regardless of batch size, so a search-results or
    Keywords-subtab list never pays an N+1 query cost for this chip."""
    _index(db)  # warm the cache once for the whole batch
    return {
        term: supergroups_for_keyword(db, term, language)
        for term, language in keywords
    }
