"""Audit 0.5.0 item 14: a trigger body that changed between builds reaches an EXISTING store, not only a new one.

``ensure_source_outlet_id`` skipped a trigger it found BY NAME, and ``CREATE TRIGGER IF NOT EXISTS`` can never replace one, so a store
created by an older build kept the old body for the life of the file. The boot step now compares the stored text with this build's
(whitespace collapsed, ``IF NOT EXISTS`` taken out: SQLite keeps neither) and drops and re-makes a trigger whose body differs, inside the
transaction that heals the rows. A matching trigger is left alone: the steady boot issues no ``DROP``.
"""

from __future__ import annotations

from sqlalchemy import event

from src.database.models import SOURCE_OUTLET_ID_TRIGGERS
from src.database.source_identity import ensure_source_outlet_id
from tests.test_source_outlet_id import _engine, _insert, _triggers, _wrong

#: What an older build might have written for the insert trigger: it sets the new row's outlet to ITS OWN id, so a second feed of a domain is wrong.
_OLD_AI = "CREATE TRIGGER trg_sources_outlet_id_ai AFTER INSERT ON sources BEGIN UPDATE sources SET outlet_id = NEW.id WHERE id = NEW.id; END"


def _stored(conn, name):
    return conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).scalar_one()


def _plant_old_insert_trigger(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER trg_sources_outlet_id_ai")
        conn.exec_driver_sql(_OLD_AI)


def test_a_trigger_with_an_older_body_is_replaced_and_the_rows_it_got_wrong_are_healed(tmp_path):
    engine = _engine(tmp_path)
    _plant_old_insert_trigger(engine)
    with engine.begin() as conn:
        _insert(conn, "a.com", "1")
        _insert(conn, "a.com", "2")  # under the old body this row names itself as the outlet
        assert _wrong(conn), "the planted old body did not produce the wrong value this test is about"
    result = ensure_source_outlet_id(engine)
    assert result["triggers"] == 1 and result["healed"] >= 1, result
    with engine.begin() as conn:
        assert _triggers(conn) >= set(SOURCE_OUTLET_ID_TRIGGERS)
        assert _stored(conn, "trg_sources_outlet_id_ai") != _OLD_AI
        assert not _wrong(conn)
        _insert(conn, "a.com", "3")
        assert not _wrong(conn), "the new body is not the one now firing"
    assert ensure_source_outlet_id(engine)["triggers"] == 0, "a second boot rewrote a trigger that already matches"


def test_a_matching_trigger_is_left_alone(tmp_path):
    engine = _engine(tmp_path)
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, *_a):
        statements.append(statement)

    assert ensure_source_outlet_id(engine)["triggers"] == 0
    assert not [s for s in statements if "DROP TRIGGER" in s.upper()], "the steady boot dropped a trigger that already matches"


def test_a_stored_body_that_differs_only_in_whitespace_is_not_a_change(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        spaced = _stored(conn, "trg_sources_outlet_id_ad").replace(" ", "   ").replace("BEGIN", "BEGIN\n")
        conn.exec_driver_sql("DROP TRIGGER trg_sources_outlet_id_ad")
        conn.exec_driver_sql(spaced)
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, *_a):
        statements.append(statement)

    assert ensure_source_outlet_id(engine)["triggers"] == 0
    assert not [s for s in statements if "DROP TRIGGER" in s.upper()], "a trigger was rewritten for a whitespace-only difference"


def test_the_comparison_reads_a_missing_stored_text_as_a_difference():
    from src.database.source_identity import _trigger_body_matches

    wanted = SOURCE_OUTLET_ID_TRIGGERS["trg_sources_outlet_id_ai"]
    assert not _trigger_body_matches(None, wanted) and not _trigger_body_matches("", wanted)
    assert _trigger_body_matches(wanted.replace("IF NOT EXISTS ", ""), wanted)
    assert not _trigger_body_matches(wanted.replace("AFTER INSERT", "AFTER DELETE").replace("IF NOT EXISTS ", ""), wanted)
