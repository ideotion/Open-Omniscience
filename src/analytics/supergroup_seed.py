"""Seed the bundled initial super-groups (maintainer-ruled 2026-06-11, reworked
2026-06-20 into a concept scaffold).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The curated starter set lives in ``configs/keyword_supergroups.yml``. As of
2026-06-20 super-groups are durable umbrella CONCEPTS (one level broader than a
ring), and their members are cross-language RINGS (``rings:``), so every group
spans all 12 languages by construction. A group may still list family canonical
``normalized_term`` members (``members:``) for surface-term curation.

Seeding is IDEMPOTENT and never overrides the user: a group whose name already
exists in the database is skipped entirely -- edits and deletions stick.

The 2026-06-11 starter set was a handful of TOPICS (e.g. "FIFA World Cup 2026"),
which the rework replaced. ``_RETIRED`` lets the seeder remove those old bundled
groups -- but ONLY when a group still holds EXACTLY its originally-seeded members
(i.e. the user never touched it). A user-edited group of the same name is left
alone (the dispose rule, symmetric: we only un-seed what we seeded).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

_LOG = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_supergroups.yml"

# Old bundled (topic) super-groups retired by the 2026-06-20 concept rework, with
# the EXACT family members each was seeded with. Removed only when untouched.
_RETIRED: dict[str, frozenset[str]] = {
    "Middle East conflict": frozenset({"iran", "israel"}),
    "FIFA World Cup 2026": frozenset({"world cup", "fifa", "cup"}),
    "Artificial intelligence": frozenset(
        {"ai", "ia", "intelligence artificielle", "model", "models", "modèles", "data", "données"}
    ),
    "US politics & government": frozenset(
        {"trump", "donald trump", "government", "federal government",
         "president", "supreme court", "court"}
    ),
    "Climate & environment": frozenset({"climate", "climate change", "energy"}),
    "Security & defense": frozenset({"security", "military", "police"}),
    "Economy & markets": frozenset({"company", "companies", "euros"}),
    "Russia & Ukraine": frozenset({"russian"}),
}


def _retire_untouched(session) -> int:
    """Delete old bundled groups that still hold exactly their seeded members.

    A group the user edited (different member set) or one carrying ring members
    is NOT retired -- only the pristine auto-seeded topic groups."""
    from src.database.models import KeywordSuperGroup

    removed = 0
    for sg in session.query(KeywordSuperGroup).filter(
        KeywordSuperGroup.name.in_(list(_RETIRED))
    ).all():
        want = _RETIRED[sg.name]
        have = {m.normalized_term for m in sg.members}
        touched_ring = any(m.ring_id for m in sg.members)
        if have == want and not touched_ring:
            session.delete(sg)
            removed += 1
    return removed


def seed_supergroups(session) -> dict:
    """Create missing bundled super-groups; never touch existing (user) ones.

    Retires the pristine old topic groups first (so a renamed/repurposed concept
    group of the same name can take their place), then creates any bundled group
    whose name is absent. Ring members are validated against the live ring set; an
    unknown ring id is skipped rather than stored as a dead member."""
    from src.analytics.equivalence import ring_meta
    from src.database.models import KeywordSuperGroup, KeywordSuperGroupMember

    if not _PATH.exists():
        return {"created": 0, "skipped": 0, "retired": 0}

    retired = _retire_untouched(session)

    data = yaml.safe_load(_PATH.read_text("utf-8")) or {}
    existing = {sg.name for sg in session.query(KeywordSuperGroup).all()}
    created = skipped = 0
    for g in data.get("supergroups", []):
        name = str(g.get("name", "")).strip()
        families = [str(m).strip() for m in (g.get("members") or []) if str(m).strip()]
        ring_ids = [str(r).strip() for r in (g.get("rings") or []) if str(r).strip()]
        if not name or not (families or ring_ids):
            continue
        if name in existing:
            skipped += 1
            continue
        sg = KeywordSuperGroup(name=name)
        session.add(sg)
        session.flush()
        for m in dict.fromkeys(families):  # de-dup, keep order
            session.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=m))
        for rid in dict.fromkeys(ring_ids):
            if ring_meta(rid) is None:
                _LOG.warning("super-group %r: unknown ring %r skipped", name, rid)
                continue
            # A ring member stores the ring id in BOTH columns (the marker + the
            # unique (supergroup_id, normalized_term) key path stays unchanged).
            session.add(
                KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=rid, ring_id=rid)
            )
        created += 1
    session.commit()
    if created or retired:
        _LOG.info(
            "seeded %d bundled super-group(s); %d existed; retired %d old topic group(s)",
            created, skipped, retired,
        )
    return {"created": created, "skipped": skipped, "retired": retired}
