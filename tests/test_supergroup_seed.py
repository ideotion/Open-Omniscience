"""The bundled super-group seeder (concept scaffold, reworked 2026-06-20):
ring members, idempotency / user-wins, and the safe retire of old topic groups.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.supergroup_seed import _RETIRED, seed_supergroups
from src.database.models import Base, KeywordSuperGroup, KeywordSuperGroupMember


def _session(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'sg.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def test_seed_creates_concept_groups_with_validated_ring_members(tmp_path):
    s = _session(tmp_path)
    res = seed_supergroups(s)
    assert res["created"] >= 50  # the concept scaffold
    groups = {g.name: g for g in s.query(KeywordSuperGroup).all()}
    assert "State & government" in groups
    assert "FIFA World Cup 2026" not in groups  # the old topic group is gone

    # every seeded member is a RING (ring_id set) and resolves to a real ring
    from src.analytics.equivalence import ring_meta

    mems = s.query(KeywordSuperGroupMember).all()
    assert mems and all(m.ring_id for m in mems)
    assert all(ring_meta(m.ring_id) is not None for m in mems)
    # a known concept maps to known rings
    ai = groups["Artificial intelligence"]
    rings = {m.ring_id for m in ai.members}
    assert {"artificial-intelligence", "machine-learning"} <= rings


def test_seed_is_idempotent_and_user_edits_win(tmp_path):
    s = _session(tmp_path)
    seed_supergroups(s)
    n1 = s.query(KeywordSuperGroup).count()

    # the user edits a seeded concept group: remove all but one member
    g = s.query(KeywordSuperGroup).filter_by(name="State & government").one()
    keep = g.members[0]
    for m in list(g.members):
        if m is not keep:
            s.delete(m)
    s.commit()

    res2 = seed_supergroups(s)  # second pass
    assert res2["created"] == 0  # nothing new
    assert s.query(KeywordSuperGroup).count() == n1  # no duplicate names
    g2 = s.query(KeywordSuperGroup).filter_by(name="State & government").one()
    assert len(g2.members) == 1  # the user's edit stuck


def test_retire_only_removes_untouched_old_topic_groups(tmp_path):
    s = _session(tmp_path)
    # simulate an OLD install: two pristine old topic groups + one the user edited
    name_clean, want = "Russia & Ukraine", _RETIRED["Russia & Ukraine"]
    sgc = KeywordSuperGroup(name=name_clean)
    s.add(sgc); s.flush()
    for t in want:
        s.add(KeywordSuperGroupMember(supergroup_id=sgc.id, normalized_term=t))

    sge = KeywordSuperGroup(name="Economy & markets")  # user added an extra member
    s.add(sge); s.flush()
    for t in list(_RETIRED["Economy & markets"]) + ["inflation"]:
        s.add(KeywordSuperGroupMember(supergroup_id=sge.id, normalized_term=t))
    s.commit()

    res = seed_supergroups(s)
    assert res["retired"] == 1  # only the pristine one
    names = {g.name for g in s.query(KeywordSuperGroup).all()}
    assert "Russia & Ukraine" not in names  # retired (untouched)
    # the user-edited "Economy & markets" survived AND was not re-seeded (name exists)
    eco = s.query(KeywordSuperGroup).filter_by(name="Economy & markets").one()
    assert any(m.normalized_term == "inflation" for m in eco.members)
