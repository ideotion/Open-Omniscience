"""DB-8: align_stamp_to_head advances a lagging stamp ONLY when the schema is at head.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The boot self-heals bring an old store's SCHEMA to head without moving the alembic stamp,
leaving a "lying stamp" (behind head, schema ahead) that breaks the next migration and the
cross-version restore's `alembic upgrade`. align_stamp_to_head fixes the lie — but must
NEVER advance a store that is genuinely behind (a missing column), which still needs to
migrate. Both directions are pinned here.
"""

from __future__ import annotations

import warnings

from alembic import command
from sqlalchemy import create_engine, text

from src.database.fts import ensure_fts
from src.database.maintenance import ensure_hot_indexes, ensure_keyword_counter_columns
from src.database.migrate import (
    _alembic_config,
    _current_stamp,
    _head_revision,
    align_stamp_to_head,
    known_revisions,
)
from src.database.models import Base

_OLD_REV = "6ae5766d3136"  # the 0.0.8 baseline (a known ancestor of head)


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


def test_behind_stamp_with_at_head_schema_is_advanced(tmp_path):
    """The fix: a store stamped at the 0.0.8 baseline but self-healed to head gets its
    stamp advanced to head (no longer lies)."""
    eng = _healed_engine(tmp_path, stamp=_OLD_REV)
    assert _current_stamp(eng) == _OLD_REV
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "advanced"
    assert verdict["from"] == _OLD_REV
    assert verdict["to"] == _head_revision()
    assert _current_stamp(eng) == _head_revision()  # truly advanced on disk
    eng.dispose()


def test_genuinely_missing_column_is_not_stamped_forward(tmp_path):
    """The safety: a store stamped behind AND actually missing a head column must keep its
    stamp (so a real migration adds the column) — never be stamped to head."""
    eng = _healed_engine(tmp_path, stamp=_OLD_REV)
    # Simulate an old store that predates a column the head schema has.
    with eng.begin() as c:
        c.execute(text("ALTER TABLE articles DROP COLUMN detected_language"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        verdict = align_stamp_to_head(eng)
    assert verdict["action"] == "schema-behind"
    assert any("detected_language" in d for d in verdict["diffs"])
    assert _current_stamp(eng) == _OLD_REV  # NOT advanced — it must migrate
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


def test_old_rev_is_a_known_ancestor():
    """Guard: the baseline id this test stamps must stay a known revision (not head)."""
    assert _OLD_REV in known_revisions()
    assert _OLD_REV != _head_revision()
