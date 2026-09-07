"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

J3 / audit ARCH-06, ruled 2026-09-07: **SQLite is the only supported backend.**

``docs/ARCHITECTURE.md`` already said so at the top ("the default and the only
supported, tested backend"; "PostgreSQL -- experimental scaffolding, NOT
supported") while the same file's lower half still handed out PostgreSQL FTS,
monitoring, troubleshooting and ``pg_dump`` recipes as though it were a parallel
choice, and ``session.py``'s own docstring called a PostgreSQL URL "honoured".

Nothing REFUSES such a URL -- that would break an install this project never
promised to support in the first place, in the name of documenting it. It warns,
once, at engine build, naming what is actually absent. The negative twin matters
as much: a warning on the ordinary SQLite boot would be noise on every start, and
noise is how a real warning stops being read.
"""

from __future__ import annotations

import logging

import pytest

import src.database.session as sess


def _stub_create_engine(monkeypatch):
    """Record the call instead of resolving a dialect: ``create_engine`` imports the
    DBAPI eagerly, so a real ``postgresql://`` URL needs psycopg installed to get as
    far as the branch under test."""
    calls: list[tuple] = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(sess, "create_engine", _fake)
    return calls


def test_a_non_sqlite_url_warns_and_still_builds(monkeypatch, caplog):
    calls = _stub_create_engine(monkeypatch)
    monkeypatch.setattr(sess, "_IS_SQLITE", False)
    monkeypatch.setattr(sess, "DATABASE_URL", "postgresql://someone:hunter2@db.host/oo")

    with caplog.at_level(logging.WARNING, logger="database.session"):
        sess._build_engine()

    assert calls, "the engine must STILL be built -- this degrades loudly, it does not refuse"
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "only supported backend" in msg
    # It must name what is actually lost, not "some PRAGMAs".
    for claim in ("at-rest encryption", "full-text search", "single-writer gate"):
        assert claim in msg, f"the warning must name {claim!r}"


def test_the_warning_never_logs_the_credentials_in_the_url(monkeypatch, caplog):
    """A DATABASE_URL carries a password. Only the SCHEME may reach the log -- the
    error log ships inside the diagnostics bundle an operator hands to somebody else."""
    _stub_create_engine(monkeypatch)
    monkeypatch.setattr(sess, "_IS_SQLITE", False)
    monkeypatch.setattr(sess, "DATABASE_URL", "postgresql://someone:hunter2@db.host/oo")

    with caplog.at_level(logging.WARNING, logger="database.session"):
        sess._build_engine()

    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "postgresql://..." in msg, "the scheme is the useful half and is safe to print"
    for secret in ("hunter2", "someone", "db.host", "/oo"):
        assert secret not in msg, f"{secret!r} leaked into the log"


def test_the_ordinary_sqlite_boot_does_not_warn(monkeypatch, caplog):
    """The negative-space twin. Without it, a warning that fires unconditionally
    passes every assertion above while making every start noisier."""
    calls = _stub_create_engine(monkeypatch)
    monkeypatch.setattr(sess, "_IS_SQLITE", True)

    with caplog.at_level(logging.WARNING, logger="database.session"):
        sess._build_engine()

    assert calls, "the SQLite branch must still build an engine"
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name == "database.session"
    ]
    assert not warnings, f"the supported backend must boot quietly: {warnings}"


@pytest.mark.parametrize(
    "claim",
    [
        "only supported, tested backend",
        "experimental scaffolding, NOT supported",
    ],
)
def test_architecture_md_states_the_ruling_at_the_top(claim):
    """A guard on the DOC, because the defect this slice fixed was not a missing
    statement -- it was a correct statement at the top of a file whose lower half
    contradicted it for a hundred lines."""
    from pathlib import Path

    doc = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md"
    assert claim in doc.read_text(encoding="utf-8")


def _fenced_code(markdown: str) -> str:
    """Every ``` fenced block, concatenated.

    Scoped this way ON PURPOSE, and it is the recorded trap rather than convenience: a
    whole-file "this must be GONE" assertion trips on the sentence that RECORDS the
    removal -- the new Full-Text Search section necessarily names the ``to_tsvector``
    recipe it deleted, and the store section has always named the ``tsvector`` search
    path as what parity would require. Those sentences are what a future session reads
    before deciding the removal was a mistake, so the guard is narrowed instead. The
    distinction is exact for this claim: the page may NAME PostgreSQL, and must not
    INSTRUCT anyone to run it -- an instruction is a command in a code block.
    """
    out, inside = [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def test_the_fence_extractor_actually_finds_the_code_blocks():
    """Anti-vacuity: an extractor that returned "" would make the guard below pass
    against any document at all."""
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )
    code = _fenced_code(doc)
    assert len(code) > 500, f"only {len(code)} chars of fenced code found"
    assert "sqlite3 data/open_omniscience.db" in code, "a known SQLite recipe is missing"


def test_architecture_md_no_longer_hands_out_postgres_recipes():
    """The contradiction, pinned so it cannot come back: the top of the file has said
    since the v0.0.7 audit that PostgreSQL is "experimental scaffolding, NOT supported",
    while a hundred lines further down the same page handed out PostgreSQL FTS,
    monitoring, troubleshooting and pg_dump recipes as though it were a parallel
    choice."""
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )
    code = _fenced_code(doc)
    for recipe in ("psql", "pg_dump", "pg_stat_activity", "postgresql", "to_tsvector",
                   "pgAdmin", "GRANT ALL PRIVILEGES"):
        assert recipe not in code, (
            f"docs/ARCHITECTURE.md still hands out a runnable PostgreSQL recipe "
            f"({recipe!r}) while its own store section calls PostgreSQL unsupported "
            "scaffolding"
        )
