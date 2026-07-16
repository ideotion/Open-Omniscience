"""``classify_restore_error`` must recognise an IntegrityError raised by the
ENCRYPTED store's driver, not just stdlib ``sqlite3`` (field bug 2026-07-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-16: a real 18 GB restore failure surfaced as the generic
"could not restore this backup: UNIQUE constraint failed: ..." instead of the
more informative "the backup's data conflicts with your corpus on a database
constraint ... this is a data-merge issue, not a version mismatch" wording that
``classify_restore_error`` (P0-2) is supposed to give for exactly this case.
Root cause: ``merge_corpus`` runs its raw SQL through ``sqlcipher3.dbapi2`` for
the default ENCRYPTED store, and ``sqlcipher3`` defines its OWN ``IntegrityError``
class -- it is NOT a subclass of stdlib ``sqlite3.IntegrityError`` -- so the old
``isinstance(exc, sqlite3.IntegrityError)`` check silently never matched for any
real (encrypted) user. This is the exact cross-driver class divergence
``src/database/write.py``'s ``is_locked_error`` already had to fix for
``OperationalError`` (field log 2026-07-14).
"""

from __future__ import annotations

import sqlite3
import sys
import types

from src.backup import merge as merge_mod
from src.backup.merge import classify_restore_error


def test_classify_restore_error_recognizes_stdlib_sqlite3_integrity_error():
    detail = classify_restore_error(
        "restore", sqlite3.IntegrityError("UNIQUE constraint failed: keyword_mentions.keyword_id")
    )
    assert "data-merge issue, not a version mismatch" in detail
    assert "UNIQUE constraint failed" in detail  # the original detail is kept, not lost


def test_classify_restore_error_recognizes_a_sqlcipher3_style_integrity_error(monkeypatch):
    """Simulate the encrypted store's driver WITHOUT requiring sqlcipher3 to be
    installed: a distinct IntegrityError class, unrelated to sqlite3's, raised the
    same way merge_corpus's raw sqlcipher3 connection would raise it."""

    class _FakeSqlcipherIntegrityError(Exception):
        pass

    assert not issubclass(_FakeSqlcipherIntegrityError, sqlite3.IntegrityError), (
        "the fixture must be a genuinely UNRELATED class -- the whole point of the bug"
    )

    fake_dbapi2 = types.SimpleNamespace(IntegrityError=_FakeSqlcipherIntegrityError)
    fake_pkg = types.SimpleNamespace(dbapi2=fake_dbapi2)
    monkeypatch.setitem(sys.modules, "sqlcipher3", fake_pkg)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", fake_dbapi2)
    merge_mod._db_integrity_error_types.cache_clear()
    try:
        detail = classify_restore_error(
            "restore",
            _FakeSqlcipherIntegrityError(
                "UNIQUE constraint failed: keyword_mentions.keyword_id, keyword_mentions.article_id"
            ),
        )
        assert "data-merge issue, not a version mismatch" in detail, (
            "a sqlcipher3-raised IntegrityError must get the same honest classification "
            "as a stdlib sqlite3 one -- this is the actual field-report wording gap"
        )
    finally:
        merge_mod._db_integrity_error_types.cache_clear()  # never leak the fake into other tests


def test_classify_restore_error_falls_back_honestly_for_unrelated_exceptions():
    """A non-integrity failure still gets the generic (never over-specific) wording."""
    detail = classify_restore_error("restore", RuntimeError("disk full"))
    assert "data-merge issue" not in detail
    assert "could not restore this backup" in detail
