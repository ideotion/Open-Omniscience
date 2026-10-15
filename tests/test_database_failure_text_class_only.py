"""The alias the AST guard cannot follow (``driver = driver_error(exc) or exc``): what the damage lane's record functions return for a driver
whose message holds a secret fragment never contains it."""

from __future__ import annotations

import sqlite3

import pytest

from src.database import damage, verify

FRAGMENT = "horse-battery"


def _drivers():
    yield sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
    yield sqlite3.DatabaseError(f"file is not a database {FRAGMENT}")
    yield sqlite3.IntegrityError(f"UNIQUE constraint failed: notes.{FRAGMENT}")
    try:
        try:
            raise sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
        except sqlite3.OperationalError as driver:
            raise RuntimeError("wrapper") from driver
    except RuntimeError as wrapped:
        yield wrapped
    yield OSError(5, f"disk /home/{FRAGMENT}/corpus.db")


@pytest.mark.parametrize("exc", list(_drivers()), ids=lambda e: type(e).__name__)
def test_the_damage_lane_records_carry_no_driver_words(exc):
    assert FRAGMENT not in damage.failure_text(exc)
    assert FRAGMENT not in damage.failure_label(exc)
    assert FRAGMENT not in repr(damage.corruption_of(exc))
    assert FRAGMENT not in repr(verify.classify_error(exc))


def test_the_disk_gone_poke_names_our_marker_never_the_drivers_words(monkeypatch):
    from types import SimpleNamespace

    from src.database import session
    from src.safety import data_volume

    seen: list[str] = []
    monkeypatch.setattr(data_volume.MONITOR, "poke", lambda why: seen.append(why))
    exc = RuntimeError("no such table: disk i/o error horse-battery")
    session._data_drive_on_disk_error(SimpleNamespace(original_exception=exc))
    assert seen == ["database error: disk i/o error"]
    assert "horse-battery" not in seen[0]
