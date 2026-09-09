"""
Tests for `open-omniscience doctor` (src/diagnostics.py).

We assert the happy path returns 0 and reports the key sections, and that a
genuinely broken condition is reported as a critical failure and flips the exit
code to 1 -- so scripts/CI can trust it. (We trigger the failure by making data
dir resolution raise, which is root-independent, unlike chmod-based perm tests.)

THE HEALTHY-PATH TEST CONSTRUCTS ITS OWN CONDITION (2026-09-09). It used to call
``run_doctor()`` against whatever state the session happened to be in and assert
"healthy", which made it pass or fail on TEST ORDER: ``pytest tests/test_diagnostics.py
tests/test_a2_job_endpoints.py`` failed and the same two files in the other order
passed, deterministically, because collecting the API-app module stamps an alembic
revision into the isolated test database WITHOUT creating any table. A test that
asserts a positive fact about ambient state it does not set up is asserting about the
rest of the suite. It now calls ``init_db()`` first, so it tests the doctor.

That ordering failure also exposed a REAL defect, which the tests below pin: a
database file that exists with no schema was reported as a critical [XX] carrying a
raw fifteen-line SQL dump.
"""

from __future__ import annotations

import sqlalchemy as sa

import src.database.session as session
import src.diagnostics as diag


def test_doctor_healthy_returns_zero(capsys):
    from src.database.session import init_db

    init_db()  # the healthy path is a BUILT database -- construct it, never inherit it
    rc = diag.run_doctor()
    out = capsys.readouterr().out
    assert rc == 0
    for section in ("doctor", "Python", "Data directory", "Database", "Local LLM"):
        assert section in out


def test_doctor_flags_broken_data_dir(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("src.paths.data_dir", _boom)
    rc = diag.run_doctor()
    out = capsys.readouterr().out
    assert rc == 1
    assert "could not resolve" in out
    assert "critical checks failed" in out


def _schemaless_db(tmp_path, monkeypatch):
    """A database FILE that exists and carries no tables -- the reachable state an
    interrupted first launch (or a bare alembic stamp) leaves behind."""
    db = tmp_path / "open_omniscience.db"
    url = f"sqlite:///{db}"
    engine = sa.create_engine(url)
    with engine.connect() as c:  # touch it: the file now exists, with no schema
        c.execute(sa.text("select 1"))
    assert db.exists()
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(session, "DATABASE_URL", url)
    return db


def test_a_database_file_with_no_schema_is_a_warning_not_a_critical(tmp_path, monkeypatch, capsys):
    """The regression this file's own ordering failure was hiding.

    Before the fix this was ``[XX] Database  reachable but query failed:
    (sqlite3.OperationalError) no such table: sources [SQL: SELECT count(*) ...]``
    -- a critical exit code, and a report telling a non-technical operator that
    their install is broken when it simply has not finished being built."""
    _schemaless_db(tmp_path, monkeypatch)
    r = diag._Report()
    diag._check_database(r)
    out = capsys.readouterr().out

    assert r.failed is False, "a database that has not been built yet is not a critical failure"
    assert "no schema yet" in out
    assert "it builds on first launch" in out
    assert "no such table" not in out, "the driver's raw error must not reach the report"
    assert "SELECT" not in out, "the failing statement must not be dumped into the report"


def test_a_missing_database_file_still_reports_not_created_yet(tmp_path, monkeypatch, capsys):
    """The neighbouring branch must keep its own distinct wording: no FILE and no
    SCHEMA are different measurements, and the report says which one it made."""
    url = f"sqlite:///{tmp_path / 'absent.db'}"
    monkeypatch.setattr(session, "DATABASE_URL", url)
    r = diag._Report()
    diag._check_database(r)
    out = capsys.readouterr().out

    assert r.failed is False
    assert "not created yet" in out
    assert "no schema yet" not in out


def test_a_real_query_failure_is_still_critical_and_bounded(tmp_path, monkeypatch, capsys):
    """Narrowing the schemaless case must not swallow a genuine failure.

    The tables are PRESENT here, so the inspector lets the probe through; the query
    then fails. That must stay a critical -- with a bounded message."""
    from src.database.models import Base

    db = tmp_path / "open_omniscience.db"
    url = f"sqlite:///{db}"
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(session, "DATABASE_URL", url)

    def _boom():
        raise RuntimeError("simulated: " + "x" * 500)

    monkeypatch.setattr(session, "session_scope", _boom)
    r = diag._Report()
    diag._check_database(r)
    out = capsys.readouterr().out

    assert r.failed is True
    assert "reachable but query failed" in out
    assert "simulated:" in out
    assert len(max(out.splitlines(), key=len)) < 300, "a detail line must never become a page"


def test_brief_keeps_the_cause_and_drops_the_sql_dump():
    """`_brief` is what keeps the FAIL branch readable, so pin its contract directly:
    the first line survives, the appended statement does not."""
    exc = Exception(
        "(sqlite3.OperationalError) no such table: sources\n"
        "[SQL: SELECT count(*) AS count_1 FROM (SELECT sources.id AS sources_id) AS anon_1]\n"
        "(Background on this error at: https://sqlalche.me/e/20/e3q8)"
    )
    got = diag._brief(exc)
    assert got == "(sqlite3.OperationalError) no such table: sources"
    assert "SQL:" not in got and "sqlalche.me" not in got
    assert diag._brief(Exception("y" * 400)).endswith("…")
    assert len(diag._brief(Exception("y" * 400))) <= 200


def test_the_summary_does_not_call_every_warning_an_optional_extra(capsys):
    """The healthy-run footer used to say warnings "are optional extras you can add
    later". Two database warnings this report can emit are neither optional nor
    extras, so the claim was false exactly when it mattered most."""
    from src.database.session import init_db

    init_db()
    rc = diag.run_doctor()
    out = capsys.readouterr().out
    assert rc == 0
    assert "optional extras" not in out
    assert "not failures" in out
