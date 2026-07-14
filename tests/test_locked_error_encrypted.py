"""
The 'database is locked' retry net must recognise the locked/busy condition on an ENCRYPTED
(sqlcipher3) store, where SQLAlchemy does NOT wrap the raw driver error (field log 2026-07-14:
297 fetched articles left unindexed because is_locked_error returned False and the backoff/redo
never engaged).

NEGATIVE-SPACE lens (mandatory): a non-lock error is NEVER treated as locked (no infinite backoff
on a permanent failure), a plain message that isn't on an OperationalError class is NOT locked (no
over-broadening), while a raw sqlite3/sqlcipher3 locked error AND a wrapped cause/context ARE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from src.database.write import is_locked_error


def _sa_operational(msg: str) -> OperationalError:
    # SQLAlchemy wraps the DBAPI error; str() includes the orig message (the plaintext path).
    return OperationalError("SELECT 1", {}, sqlite3.OperationalError(msg))


# --- POSITIVE: the locked/busy condition is recognised in every shape -------------------------

def test_sqlalchemy_wrapped_locked_still_matches():
    assert is_locked_error(_sa_operational("database is locked")) is True
    assert is_locked_error(_sa_operational("database is busy")) is True


def test_raw_stdlib_sqlite3_locked_matches():
    # THE FIELD BUG'S SHAPE: a RAW driver OperationalError SQLAlchemy did not wrap.
    assert is_locked_error(sqlite3.OperationalError("database is locked")) is True


def test_locked_error_as_a_wrapped_cause_or_context_matches():
    wrapper = RuntimeError("store failed")
    wrapper.__cause__ = sqlite3.OperationalError("database is locked")
    assert is_locked_error(wrapper) is True

    ctx = RuntimeError("outer")
    ctx.__context__ = _sa_operational("database is busy")
    assert is_locked_error(ctx) is True


# --- NEGATIVE SPACE: everything that must NOT loop --------------------------------------------

def test_non_lock_operational_error_is_not_locked():
    # a real schema error must surface immediately, never back off forever
    assert is_locked_error(sqlite3.OperationalError("no such table: x")) is False
    assert is_locked_error(_sa_operational("no such column: y")) is False


def test_integrity_error_is_never_locked_so_it_keeps_the_dedup_path():
    # an IntegrityError must take the redo/dedup-per-row path, NOT the lock backoff
    exc = IntegrityError("INSERT", {}, sqlite3.IntegrityError("UNIQUE constraint failed"))
    assert is_locked_error(exc) is False


def test_a_bare_message_without_an_operational_error_type_is_not_locked():
    # the anti-broadening guard: matching the WORDS is not enough -- it must be a DB
    # OperationalError class, or a stray log/ValueError mentioning the phrase would loop forever
    assert is_locked_error(ValueError("database is locked")) is False
    assert is_locked_error(Exception("the database is locked, apparently")) is False


# --- the ACTUAL encrypted driver (skip-guarded; runs in CI where sqlcipher3 is installed) -----

def test_raw_sqlcipher3_locked_matches():
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    err = sqlcipher3.dbapi2.OperationalError("database is locked")
    assert is_locked_error(err) is True
    # and a non-lock sqlcipher3 error is still NOT locked
    assert is_locked_error(sqlcipher3.dbapi2.OperationalError("disk I/O error")) is False
