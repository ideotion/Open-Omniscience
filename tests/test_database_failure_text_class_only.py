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
