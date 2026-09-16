"""All rings ride the backup, and a restored one never overrides the release's own (Q409 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DESIGN NOTE, AND WHY IT IS MET STRUCTURALLY. Gate row K's note asks that "a restored
backup's shipped rings must never override a newer release's shipped rings, so the
member carries the ring file's version and the newer wins". A version comparison needs a
version the ring files do not have, a comparison rule and a tie-break, and it fails OPEN
the day any of the three is wrong. Precedence by SOURCE needs none of them: the loader
reads the LOCAL file first and the shipped files last, so a shipped ring beats a restored
one whatever their dates -- and a shipped ring member is never placed at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analytics import equivalence as eq
from src.backup.artifact import (
    _RINGS_LOCAL_PREFIX,
    _RINGS_SHIPPED_PREFIX,
    _ring_members,
)

_RING_YAML = """rings:
  - id: test-only-local-ring
    members: ["en:widget", "fr:bidule"]
"""
_OVERRIDE_YAML = """rings:
  - id: {rid}
    members: ["en:hijacked", "fr:detourne"]
"""


class _Staged:
    """The member view a restore sees. Real enough to answer ``member_paths``, which is
    the only thing ``_restore_ring_members`` reads off it."""

    def __init__(self, pairs):
        self._pairs = pairs

    def member_paths(self, role):
        return list(self._pairs) if role == "rings" else []


@pytest.fixture(autouse=True)
def _clean_ring_caches():
    eq.invalidate_ring_caches()
    yield
    eq.invalidate_ring_caches()


# --------------------------------------------------------------------------- #
#  Collection
# --------------------------------------------------------------------------- #
def test_both_shipped_ring_files_are_members(tmp_path):
    names = [m.name for m in _ring_members(tmp_path)]
    assert f"{_RINGS_SHIPPED_PREFIX}keyword_equivalents.yml" in names
    assert f"{_RINGS_SHIPPED_PREFIX}keyword_rings_generated.yml" in names


def test_a_local_ring_file_is_a_member_when_it_exists(tmp_path, monkeypatch):
    local = tmp_path / "rings" / "keyword_rings_local.yml"
    local.parent.mkdir(parents=True)
    local.write_text(_RING_YAML, encoding="utf-8")
    monkeypatch.setattr(eq, "local_rings_path", lambda: local)

    names = [m.name for m in _ring_members(tmp_path)]

    assert f"{_RINGS_LOCAL_PREFIX}keyword_rings_local.yml" in names


def test_no_local_member_when_there_is_no_local_file(tmp_path, monkeypatch):
    """A member for a file that does not exist would be a member of nothing."""
    monkeypatch.setattr(eq, "local_rings_path", lambda: tmp_path / "absent.yml")

    names = [m.name for m in _ring_members(tmp_path)]

    assert not any(n.startswith(_RINGS_LOCAL_PREFIX) for n in names)


# --------------------------------------------------------------------------- #
#  Restore
# --------------------------------------------------------------------------- #
def test_a_local_ring_member_is_placed_into_the_data_dir(tmp_path):
    from src.backup.merge import _restore_ring_members

    member = tmp_path / "staging" / "local.yml"
    member.parent.mkdir(parents=True)
    member.write_text(_RING_YAML, encoding="utf-8")
    base = tmp_path / "data"
    base.mkdir()

    rep = _restore_ring_members(
        _Staged([(f"{_RINGS_LOCAL_PREFIX}keyword_rings_local.yml", member)]), base
    )

    placed = base / "rings" / "keyword_rings_local.yml"
    assert placed.read_text(encoding="utf-8") == _RING_YAML
    assert rep["restored"] == [f"{_RINGS_LOCAL_PREFIX}keyword_rings_local.yml"]
    assert rep["caches_invalidated"] is True


def test_an_existing_local_ring_file_is_never_overwritten(tmp_path):
    """The standing additive rule. The operator's own rings are theirs."""
    from src.backup.merge import _restore_ring_members

    member = tmp_path / "staging" / "local.yml"
    member.parent.mkdir(parents=True)
    member.write_text(_RING_YAML, encoding="utf-8")
    base = tmp_path / "data"
    (base / "rings").mkdir(parents=True)
    mine = base / "rings" / "keyword_rings_local.yml"
    mine.write_text("rings: []\n", encoding="utf-8")

    rep = _restore_ring_members(
        _Staged([(f"{_RINGS_LOCAL_PREFIX}keyword_rings_local.yml", member)]), base
    )

    assert mine.read_text(encoding="utf-8") == "rings: []\n"
    assert rep["kept_local"] == [f"{_RINGS_LOCAL_PREFIX}keyword_rings_local.yml"]
    assert rep["restored"] == []


def test_a_shipped_ring_member_is_carried_and_NEVER_placed(tmp_path):
    """The design note's guarantee. It is REPORTED rather than silently skipped: "we
    chose not to place this" and "there was nothing to place" are different facts."""
    from src.backup.merge import _restore_ring_members

    member = tmp_path / "staging" / "shipped.yml"
    member.parent.mkdir(parents=True)
    member.write_text(_OVERRIDE_YAML.format(rid="conflict"), encoding="utf-8")
    base = tmp_path / "data"
    base.mkdir()

    rep = _restore_ring_members(
        _Staged([(f"{_RINGS_SHIPPED_PREFIX}keyword_equivalents.yml", member)]), base
    )

    assert not (base / "rings").exists() or not list((base / "rings").glob("*.yml"))
    assert rep["carried_not_placed"] == [f"{_RINGS_SHIPPED_PREFIX}keyword_equivalents.yml"]
    assert rep["restored"] == []


def test_a_hostile_ring_member_name_is_refused_BY_NAME(tmp_path):
    """The member name becomes a filesystem path. Containment is checked with
    ``is_relative_to``, never a string prefix -- a sibling directory shares one."""
    from src.backup.merge import _restore_ring_members

    member = tmp_path / "staging" / "evil.yml"
    member.parent.mkdir(parents=True)
    member.write_text(_RING_YAML, encoding="utf-8")
    base = tmp_path / "data"
    base.mkdir()
    outside = tmp_path / "pwned.yml"

    rep = _restore_ring_members(
        _Staged(
            [
                (f"{_RINGS_LOCAL_PREFIX}../../pwned.yml", member),
                (f"{_RINGS_LOCAL_PREFIX}/etc/passwd", member),
                ("rings/unknown/x.yml", member),
            ]
        ),
        base,
    )

    assert not outside.exists()
    assert len(rep["refused"]) == 3
    reasons = {r["reason"] for r in rep["refused"]}
    assert "unsafe ring member name" in reasons
    assert "unknown ring member prefix" in reasons
    assert rep["restored"] == []


def test_the_containment_check_refuses_a_sibling_directory(tmp_path):
    """The recorded containment trap, directly: ``…/rings-old`` starts with ``…/rings``
    as a STRING and is a different directory."""
    from src.backup.merge import _safe_ring_target

    base = tmp_path / "data"
    (base / "rings").mkdir(parents=True)
    assert _safe_ring_target(base, "keyword_rings_local.yml") is not None
    assert _safe_ring_target(base, "../rings-old/x.yml") is None
    assert _safe_ring_target(base, "") is None


# --------------------------------------------------------------------------- #
#  Precedence, and the caches
# --------------------------------------------------------------------------- #
def test_a_shipped_ring_wins_over_a_local_one_of_the_same_id(tmp_path, monkeypatch):
    """The design note's property, driven through the REAL loader against a local file
    that tries to hijack a SHIPPED ring id. Reading the shipped set last is what makes
    it true, so the fixture has to collide on a real shipped id."""
    shipped_id = eq.load_rings()[0].id
    eq.invalidate_ring_caches()
    local = tmp_path / "keyword_rings_local.yml"
    local.write_text(_OVERRIDE_YAML.format(rid=shipped_id), encoding="utf-8")
    monkeypatch.setattr(eq, "local_rings_path", lambda: local)
    eq.invalidate_ring_caches()

    by_id = {r.id: r for r in eq.load_rings()}

    assert ("en", "hijacked") not in by_id[shipped_id].members, (
        "a local ring overrode a shipped one; the restored set must never win"
    )


def test_a_local_ring_with_a_NEW_id_is_loaded(tmp_path, monkeypatch):
    """The negative-space twin: a loader that simply ignored the local file would pass
    the precedence test above and make the whole member pointless."""
    local = tmp_path / "keyword_rings_local.yml"
    local.write_text(_RING_YAML, encoding="utf-8")
    monkeypatch.setattr(eq, "local_rings_path", lambda: local)
    eq.invalidate_ring_caches()

    ids = {r.id for r in eq.load_rings()}

    assert "test-only-local-ring" in ids


def test_invalidating_the_caches_clears_ALL_THREE_loaders(tmp_path, monkeypatch):
    """Clearing ``load_rings`` alone would leave ``_index`` and ``_multi_index`` serving
    the old set, which is the shape where a term resolves on one surface and not
    another. Driven through the indexes, not by reading ``cache_info``."""
    local = tmp_path / "keyword_rings_local.yml"
    monkeypatch.setattr(eq, "local_rings_path", lambda: local)
    eq.invalidate_ring_caches()
    assert eq.is_ring_term("widget") is False  # warms _index with the file absent
    eq.ring_matches("bidule", languages=["fr"])  # warms _multi_index

    local.write_text(_RING_YAML, encoding="utf-8")
    eq.invalidate_ring_caches()

    assert eq.is_ring_term("widget") is True, "_index still serves the pre-restore set"
    assert any(
        m.ring_id == "test-only-local-ring"
        for m in eq.ring_matches("bidule", languages=["fr"])
    ), "_multi_index still serves the pre-restore set"


def test_the_local_rings_path_follows_the_data_dir(monkeypatch, tmp_path):
    """``data_dir()`` re-reads the environment per call while a module constant freezes
    at import -- the C7 trap. A frozen path would make a restore write rings into the
    folder the operator left behind."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "somewhere"))
    assert Path(eq.local_rings_path()).is_relative_to(tmp_path / "somewhere")
