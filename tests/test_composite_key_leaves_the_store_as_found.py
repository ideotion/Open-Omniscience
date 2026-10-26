"""A rebuild of ``sources`` that refuses or fails leaves the store exactly as it found it, the derived view included (audit 0.5.0 A-012,
routing 11).

``upgrade_sources_to_composite_key`` used to drop ``keyword_mentions_all`` first and decide its refusals afterwards, so a store holding a
column this build does not know was refused with the view gone, and ``ensure_source_composite_key`` recreates the view only after a
success: every query on the view failed until the next boot. The schema refusals are now decided before the first change, and the drop
sits inside the transaction, where a failure rolls it back.
"""
from __future__ import annotations

import pytest

from src.database.derived_views import ensure_derived_views
from src.database.source_identity import (
    SourceIdentityRefused,
    ensure_source_composite_key,
    source_identity_state,
    upgrade_sources_to_composite_key,
)
from tests.test_source_composite_key import _legacy_engine, _seed

_VIEW = "keyword_mentions_all"


def _view_present(engine) -> bool:
    with engine.connect() as c:
        return bool(c.exec_driver_sql("SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name=?", (_VIEW,)).scalar_one())


@pytest.fixture()
def legacy_with_view(tmp_path):
    engine = _legacy_engine(tmp_path)
    _seed(engine)
    ensure_derived_views(engine)
    assert _view_present(engine), "the fixture must start with the view, or the tests below prove nothing"
    yield engine
    engine.dispose()


def test_a_column_the_build_does_not_know_is_refused_with_the_view_still_there(legacy_with_view):
    with legacy_with_view.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN retired_note TEXT")
    assert ensure_source_composite_key(legacy_with_view) == {"state": "refused", "error": "SourceIdentityRefused"}
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "legacy"


def test_a_refusal_runs_before_the_pragma_and_before_any_statement_that_changes_the_store(legacy_with_view):
    with legacy_with_view.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN retired_note TEXT")
    seen: list[str] = []
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.connection.dbapi_connection.set_trace_callback(seen.append)
        with pytest.raises(SourceIdentityRefused, match="retired_note"):
            upgrade_sources_to_composite_key(conn)
        conn.connection.dbapi_connection.set_trace_callback(None)
    changing = [q for q in seen if q.split(None, 1)[0].upper() in {"DROP", "ALTER", "CREATE", "INSERT", "UPDATE", "BEGIN"}
                or "foreign_keys" in q]
    assert not changing, changing


def test_a_copy_that_fails_after_the_drop_rolls_the_view_back_with_the_rest(legacy_with_view, monkeypatch):
    import src.database.source_identity as si

    class _Fake:
        def __init__(self, table):
            self._t = table

        def compile(self, dialect=None):
            return "CREATE TABLE sources_composite_new (id INTEGER PRIMARY KEY, domain TEXT)"

    monkeypatch.setattr(si, "CreateTable", _Fake)
    assert ensure_source_composite_key(legacy_with_view)["state"] == "refused"
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "legacy"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_a_successful_rebuild_still_ends_with_the_view_recreated(legacy_with_view):
    result = ensure_source_composite_key(legacy_with_view)
    assert result["state"] == "rebuilt"
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "composite"


def test_the_feed_key_column_is_counted_as_present_when_the_requirement_check_runs(tmp_path):
    """The required-column refusal is decided before ``feed_key`` is added, so it must count it; a legacy table lacking ONLY ``feed_key``
    is the ordinary upgrade and must not be refused for it."""
    engine = _legacy_engine(tmp_path)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            assert "feed_key" not in [r[1] for r in conn.exec_driver_sql('PRAGMA table_info("sources")').fetchall()]
            assert upgrade_sources_to_composite_key(conn)["state"] == "rebuilt"
    finally:
        engine.dispose()

