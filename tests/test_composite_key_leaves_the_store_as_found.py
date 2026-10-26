"""A rebuild of ``sources`` that refuses or fails leaves the store exactly as it found it, the derived view included (audit 0.5.0 A-012,
routing 11).

``upgrade_sources_to_composite_key`` used to drop ``keyword_mentions_all`` first and decide its schema refusals afterwards, so a store
holding a column this build does not know was refused with the view gone, and ``ensure_source_composite_key`` recreates the view only after
a success: ``init_db`` put it back a few steps later, but the steps in between, and any direct caller, ran without it. The schema refusals
are now decided before the first change, and the drop sits inside the transaction, where a failure rolls it back. The interrupt paths are
pinned too: an interrupt that keeps the ROLLBACK from reaching the driver must not let the ``finally`` commit a half-finished rebuild, and
one that lands after the COMMIT must stay the interrupt.
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


def test_a_column_added_by_another_process_during_the_rebuild_is_refused_not_dropped(legacy_with_view, monkeypatch):
    """The refusal is decided from the schema read before the first change AND again from the read that decides what is copied, so a column
    that appears in between (a second process, an older build) is named and refused instead of silently left out of the copy."""
    import src.database.source_identity as si

    real = si.backfill_feed_keys

    def _late(conn):
        conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN late_note TEXT")
        return real(conn)

    monkeypatch.setattr(si, "backfill_feed_keys", _late)
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, pytest.raises(
        SourceIdentityRefused, match="late_note"
    ):
        upgrade_sources_to_composite_key(conn)
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "legacy"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


class _Interrupting:
    """A connection whose ``exec_driver_sql`` raises ``KeyboardInterrupt`` at one statement, either before it reaches the driver
    (``after=False``: the statement never runs) or just after it ran (``after=True``), and only once ``once_seen`` has gone by (the backfill
    before the rebuild runs a COMMIT of its own)."""

    def __init__(self, conn, statement: str, *, after: bool, once_seen: str = ""):
        self._conn, self._statement, self._after, self._once_seen = conn, statement, after, once_seen
        self._armed = not once_seen

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def exec_driver_sql(self, statement, *args, **kwargs):
        if self._once_seen and self._once_seen in statement.upper():
            self._armed = True
        if not self._armed or statement.strip().upper() != self._statement:
            return self._conn.exec_driver_sql(statement, *args, **kwargs)
        if not self._after:
            raise KeyboardInterrupt
        self._conn.exec_driver_sql(statement, *args, **kwargs)
        raise KeyboardInterrupt


def test_an_interrupt_that_keeps_the_rollback_from_the_driver_does_not_commit_a_half_finished_rebuild(legacy_with_view, monkeypatch):
    """Setting ``isolation_level`` on Python 3.13 COMMITS an open transaction, so a ``finally`` that restores it with the transaction
    still open would commit whatever the rebuild had done by then. Here the copy fails, and the interrupt lands before the ROLLBACK."""
    import src.database.source_identity as si

    class _Fake:
        def __init__(self, table):
            self._t = table

        def compile(self, dialect=None):
            return "CREATE TABLE sources_composite_new (id INTEGER PRIMARY KEY, domain TEXT)"

    monkeypatch.setattr(si, "CreateTable", _Fake)
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        with pytest.raises(KeyboardInterrupt):
            upgrade_sources_to_composite_key(_Interrupting(conn, "ROLLBACK", after=False))
        assert not conn.connection.dbapi_connection.in_transaction
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "legacy"
        assert c.exec_driver_sql("SELECT COUNT(*) FROM sqlite_master WHERE name='sources_composite_new'").scalar_one() == 0
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_an_interrupt_after_the_commit_stays_the_interrupt(legacy_with_view):
    """It used to meet ``began`` still True, send a ROLLBACK, and have SQLite answer "no transaction is active": an OperationalError
    that replaced the interrupt and that boot then swallowed as an ordinary refusal."""
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        with pytest.raises(KeyboardInterrupt):
            upgrade_sources_to_composite_key(_Interrupting(conn, "COMMIT", after=True, once_seen="RENAME TO SOURCES"))
        assert not conn.connection.dbapi_connection.in_transaction
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "composite"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def _interrupt_in_the_driver(engine, monkeypatch, *, at: str, after: bool, once_seen: str = ""):
    """A real Ctrl-C lands inside SQLAlchemy's statement execution, which treats it as an exit exception and invalidates the connection
    (closing the driver one). The proxy above raises outside that code and so cannot show what the cleanup then meets."""
    real = engine.dialect.do_execute
    seen = {"armed": not once_seen}

    def _do_execute(cursor, statement, parameters, context=None):
        if once_seen and once_seen in statement.upper():
            seen["armed"] = True
        if seen["armed"] and at in statement.upper():
            if after:
                real(cursor, statement, parameters, context)
            raise KeyboardInterrupt
        return real(cursor, statement, parameters, context)

    monkeypatch.setattr(engine.dialect, "do_execute", _do_execute)


def test_an_interrupt_inside_a_statement_stays_the_interrupt_and_the_store_stays_as_found(legacy_with_view, monkeypatch):
    _interrupt_in_the_driver(legacy_with_view, monkeypatch, at="INSERT INTO SOURCES_COMPOSITE_NEW", after=False)
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, pytest.raises(KeyboardInterrupt):
        upgrade_sources_to_composite_key(conn)
    monkeypatch.undo()
    assert _view_present(legacy_with_view)
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "legacy"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_an_interrupt_inside_the_commit_statement_stays_the_interrupt(legacy_with_view, monkeypatch):
    """The COMMIT ran and the interrupt followed it inside SQLAlchemy: the connection is invalidated, the cleanup must not ask it anything,
    and the interrupt must not become a ProgrammingError that boot reads as a refusal."""
    _interrupt_in_the_driver(legacy_with_view, monkeypatch, at="COMMIT", after=True, once_seen="RENAME TO SOURCES")
    with legacy_with_view.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, pytest.raises(KeyboardInterrupt):
        upgrade_sources_to_composite_key(conn)
    monkeypatch.undo()
    with legacy_with_view.connect() as c:
        assert source_identity_state(c) == "composite"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
