"""
OO-01 regression: SQL injection via a table name in an untrusted restore artifact.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_unmerged_tables`` enumerates table names from ``inc.sqlite_master`` -- ``inc``
being the INCOMING/staged restore artifact, i.e. untrusted input, not the app's
own fixed schema. The pre-fix code interpolated each name raw into
``f'SELECT COUNT(*) FROM inc."{name}"'``, so a name containing a ``"`` could break
out of the quoted identifier (a single-statement UNION SELECT reachable via the
documented ``allow_unverified`` restore path).

The fix: every incoming table name is (a) validated against ``_SAFE_TABLE_NAME``
and, when interpolated, (b) quoted via ``_ident``. Names failing the allowlist are
surfaced under ``_rejected_tables`` -- never silently dropped, never run. These
tests prove the primitive is closed AND that honest reporting is preserved.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine

import src.backup.merge as merge

# A name whose identifier would break out of the double-quoted string in the
# pre-fix code and append a UNION SELECT against another table.
_HOSTILE = 'evil" UNION SELECT sql FROM sqlite_master --'


def _make_incoming(path: Path, tables: dict[str, int]) -> None:
    """A throwaway SQLite DB with the given tables, each holding ``rows`` rows.

    ``merge._ident`` is used only to CONSTRUCT the fixture (the builder trusts its
    own literals); it is exactly the quoting the production code now applies."""
    con = sqlite3.connect(path)
    try:
        for name, rows in tables.items():
            con.execute(f"CREATE TABLE {merge._ident(name)} (x)")  # noqa: S608 - test fixture, name is a literal
            con.executemany(
                f"INSERT INTO {merge._ident(name)} VALUES (?)",  # noqa: S608 - test fixture
                [(i,) for i in range(rows)],
            )
        con.commit()
    finally:
        con.close()


def test_hostile_table_name_is_rejected_not_injected(tmp_path):
    """(a) no exception/injection, (b) the crafted name is surfaced as rejected,
    (c) a legitimately-named extra table is still counted correctly."""
    inc = tmp_path / "inc.db"
    _make_incoming(
        inc,
        {
            _HOSTILE: 2,          # hostile identifier -> rejected, never counted
            "sneaky_extra": 3,    # legit unhandled name -> counted honestly
            "articles": 5,        # a handled table -> skipped (not reported)
        },
    )

    con = sqlite3.connect(":memory:")
    con.execute("ATTACH DATABASE ? AS inc", (str(inc),))
    try:
        # (a) must not raise -- the pre-fix code raised OperationalError here as
        # the injected identifier broke the SQL apart.
        unmerged, rejected = merge._unmerged_tables(con)
    finally:
        con.close()

    # (b) the crafted name is surfaced, not silently dropped, and never counted.
    assert _HOSTILE in rejected
    assert _HOSTILE not in unmerged
    # (c) a legitimately-named extra table is still counted correctly.
    assert unmerged.get("sneaky_extra") == 3
    # A handled table is not reported as unmerged.
    assert "articles" not in unmerged


def test_safe_table_name_allowlist_boundaries():
    """The allowlist is a plain SQL identifier: letters/underscore start, then
    word chars. Anything with a quote, dot, dash or space is rejected."""
    ok = ("articles", "zzz_extra", "_hidden", "T1", "a_b_c9")
    bad = (_HOSTILE, 'a"b', "a.b", "a-b", "a b", "1leading", "", "drop table x")
    assert all(merge._SAFE_TABLE_NAME.match(n) for n in ok)
    assert not any(merge._SAFE_TABLE_NAME.match(n) for n in bad)


def test_ident_doubles_embedded_quotes():
    assert merge._ident("plain") == '"plain"'
    assert merge._ident('a"b') == '"a""b"'


def _build_full_corpus(path: Path) -> None:
    """A plaintext SQLite corpus with the full ORM schema (incl. merge_batches /
    merged_rows), enough for ``merge_corpus`` to run end-to-end."""
    from src.database.models import Base

    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()


def test_rejected_table_surfaces_in_merge_corpus_result(tmp_path):
    """End-to-end: a hostile-named table planted in the incoming corpus lands in
    ``counts['_rejected_tables']`` (surfaced), the merge still completes, and a
    legit unhandled table is still reported under ``_unmerged_tables``."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_full_corpus(working)
    _build_full_corpus(staged)

    con = sqlite3.connect(staged)
    try:
        con.execute(f"CREATE TABLE {merge._ident(_HOSTILE)} (x)")  # noqa: S608 - test fixture
        con.execute(f"INSERT INTO {merge._ident(_HOSTILE)} VALUES (1)")  # noqa: S608 - test fixture
        con.execute("CREATE TABLE zzz_extra (id INTEGER PRIMARY KEY, v TEXT)")
        con.executemany("INSERT INTO zzz_extra (v) VALUES (?)", [("a",), ("b",)])
        con.commit()
    finally:
        con.close()

    counts, _batch = merge.merge_corpus(
        staged,
        working,
        {
            "artifact_kind": "oo-backup-2",
            "origin_fingerprint": "test",
            "app_version": "0.2.0",
            "alembic_rev": "head",
            "manifest": None,
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )

    assert _HOSTILE in counts.get("_rejected_tables", [])
    assert counts.get("_unmerged_tables", {}).get("zzz_extra") == 2
    # The hostile name is never counted, only surfaced.
    assert _HOSTILE not in counts.get("_unmerged_tables", {})
