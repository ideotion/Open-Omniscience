"""Seed the bundled initial super-groups (maintainer-ruled 2026-06-11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The curated starter set lives in ``configs/keyword_supergroups.yml`` (drafted
from the maintainer's field logs, members verified present in real corpora).
Seeding is IDEMPOTENT and never overrides the user: a group whose name already
exists in the database is skipped entirely — edits and deletions stick.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

_LOG = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_supergroups.yml"


def seed_supergroups(session) -> dict:
    """Create missing bundled super-groups; never touch existing ones."""
    from src.database.models import KeywordSuperGroup, KeywordSuperGroupMember

    if not _PATH.exists():
        return {"created": 0, "skipped": 0}
    data = yaml.safe_load(_PATH.read_text("utf-8")) or {}
    existing = {sg.name for sg in session.query(KeywordSuperGroup).all()}
    created = skipped = 0
    for g in data.get("supergroups", []):
        name = str(g.get("name", "")).strip()
        members = [str(m).strip() for m in (g.get("members") or []) if str(m).strip()]
        if not name or not members:
            continue
        if name in existing:
            skipped += 1
            continue
        sg = KeywordSuperGroup(name=name)
        session.add(sg)
        session.flush()
        for m in dict.fromkeys(members):  # de-dup, keep order
            session.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=m))
        created += 1
    session.commit()
    if created:
        _LOG.info("seeded %d bundled super-group(s); %d already existed", created, skipped)
    return {"created": created, "skipped": skipped}
