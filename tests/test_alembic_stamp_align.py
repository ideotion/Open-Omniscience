"""DB-8: align_stamp_to_head advances a lagging stamp ONLY when the schema is at head AND
the stamp is at or after the data floor.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The boot self-heals bring an old store's SCHEMA to head without moving the alembic stamp,
leaving a "lying stamp" (behind head, schema ahead) that breaks the next migration and the
cross-version restore's `alembic upgrade`. align_stamp_to_head fixes the lie — but must
NEVER advance (a) a store genuinely behind at the schema level (a missing column still needs
to migrate), NOR (b) a store stamped before a pure-DATA migration that would leave fabricated
or wrong data (compare_metadata is blind to data-only migrations). All directions are pinned.
"""

from __future__ import annotations

import warnings

from alembic import command
from sqlalchemy import create_engine, text

from src.database.fts import ensure_fts
from src.database.maintenance import ensure_hot_indexes, ensure_keyword_counter_columns
from src.database.migrate import (
    _SAFE_ADVANCE_FLOOR,
    _alembic_config,
    _current_stamp,
    _head_revision,
    _stamp_at_or_after_floor,
    align_stamp_to_head,
    known_revisions,
)
from src.database.models import Base

_BELOW_FLOOR = "6ae5766d3136"  # the 0.0.8 baseline (before the fabricated-score data migration)
_AT_FLOOR = _SAFE_ADVANCE_FLOOR  # the floor itself: at-or-after -> eligible to advance


def _healed_engine(tmp_path, *, stamp: str | None):
    """A file-backed DB at the CURRENT (head) schema, optionally stamped at `stamp`."""
    eng = create_engine(f"sqlite:///{tmp_path / 'oo.db'}", future=True)
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    ensure_keyword_counter_columns(eng)
    ensure_hot_indexes(eng)
    if stamp is not None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with eng.begin() as conn:
                cfg = _alembic_config()
                cfg.attributes["connection"] = conn
                command.stamp(cfg, stamp)
    return eng


def test_at_head_schema_past_the_floor_is_advanced(tmp_path):
    """The fix: a store stamped at the data floor but self-healed to head gets its stamp
    advanced to head (no longer lies)."""
    eng = _healed_engine(tmp_path, stamp=_AT_FLOOR)
    assert _current_stamp(eng) == _AT_FLOOR
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "advanced"
    assert verdict["from"] == _AT_FLOOR
    assert verdict["to"] == _head_revision()
    assert _current_stamp(eng) == _head_revision()  # truly advanced on disk
    eng.dispose()


def test_stamped_below_the_data_floor_is_not_advanced(tmp_path):
    """The DATA safety: a store stamped before the fabricated-score/normalize migrations must
    keep its stamp (so those data migrations run), NEVER be stamped forward — even though its
    schema is fully at head."""
    eng = _healed_engine(tmp_path, stamp=_BELOW_FLOOR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "behind-data-floor"
    assert verdict["floor"] == _SAFE_ADVANCE_FLOOR
    assert _current_stamp(eng) == _BELOW_FLOOR  # NOT advanced
    eng.dispose()


def test_genuinely_missing_column_is_not_stamped_forward(tmp_path):
    """The SCHEMA safety: a store past the floor but actually missing a head column keeps its
    stamp (so a real migration adds the column)."""
    eng = _healed_engine(tmp_path, stamp=_AT_FLOOR)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE articles DROP COLUMN detected_language"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "schema-behind"
    assert any("detected_language" in d for d in verdict["diffs"])
    assert _current_stamp(eng) == _AT_FLOOR  # NOT advanced — it must migrate
    eng.dispose()


def test_already_at_head_is_a_noop(tmp_path):
    eng = _healed_engine(tmp_path, stamp=_head_revision())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "at-head"
    assert _current_stamp(eng) == _head_revision()
    eng.dispose()


def test_unstamped_is_left_to_stamp_if_unstamped(tmp_path):
    """A fresh unstamped DB is stamp_if_unstamped's job; align must not touch it."""
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}", future=True)
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "unstamped"
    assert _current_stamp(eng) is None
    eng.dispose()


def test_unknown_revision_is_left_alone(tmp_path):
    """A stamp from a NEWER app / foreign fork (unknown revision) is never advanced."""
    eng = _healed_engine(tmp_path, stamp=None)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        c.execute(text("INSERT INTO alembic_version VALUES ('deadbeefcafe')"))
    verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "unknown-revision"
    assert verdict["rev"] == "deadbeefcafe"
    assert _current_stamp(eng) == "deadbeefcafe"  # untouched
    eng.dispose()


def test_data_floor_matches_the_data_migrations():
    """Guard the floor invariant so a NEW fabricated/wrong-data migration forces a re-look:
    the two known data migrations must be at or BELOW the floor (already-applied by any store
    at/after the floor), and the floor itself must be a known revision that is not head."""
    at_after = _stamp_at_or_after_floor

    assert _SAFE_ADVANCE_FLOOR in known_revisions()
    assert _SAFE_ADVANCE_FLOOR != _head_revision()
    # The floor is at-or-after itself.
    assert at_after(_SAFE_ADVANCE_FLOOR) is True
    # The fabricated-score + normalize-country migrations are BELOW the floor: a store stamped
    # exactly at them is NOT eligible to advance (so those migrations always run).
    for rid in ("f4b5c6d7e8a9", "a3b4c5d6e7f8", _BELOW_FLOOR):
        assert rid in known_revisions()
        assert at_after(rid) is False, f"{rid} must be below the data floor"


def test_old_rev_is_a_known_ancestor():
    """Guard: the baseline id this test stamps must stay a known revision (not head)."""
    assert _BELOW_FLOOR in known_revisions()
    assert _BELOW_FLOOR != _head_revision()
