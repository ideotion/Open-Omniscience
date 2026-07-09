"""Robust FTS presence/health probe (D4 — the 2026-07-09 present/absent contradiction).

The corpus-integrity probe reported article_fts ABSENT (fts_rows null) while schema-drift
reported it PRESENT — because integrity derived presence from ``SELECT COUNT(*) FROM
article_fts``, which on a large external-content FTS5 index enumerates the whole index, can
hit the statement deadline, and was then caught as "table missing". These pin the fix:
presence comes from sqlite_master (authoritative, the same source schema-drift reads, so the
two can't disagree), the row COUNT is best-effort with an honest status, and a post-crash
MALFORMED index is detected as unhealthy (a re-index heals it) rather than misread as absent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.fts import ensure_fts, fts_status
from src.database.maintenance import StatementTimeout
from src.database.models import Article, Base, Source


def _corpus(with_fts: bool = True):
    e = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(e)
    if with_fts:
        ensure_fts(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Source(name="S", domain="x.test"))
    s.commit()
    s.add(Article(
        url="u1", canonical_url="u1", source_id=1, title="Election news",
        content="election policy inflation", hash="h1", language="en",
        created_at=datetime.now(UTC),
    ))
    s.commit()
    return s


def test_present_healthy_and_counted_on_a_real_index():
    st = fts_status(_corpus())
    assert st["supported"] is True
    assert st["present"] is True
    assert st["healthy"] is True
    assert st["rows"] == 1 and st["count_status"] == "ok"
    assert st["error"] is None


def test_absent_reported_honestly_when_no_fts_table():
    st = fts_status(_corpus(with_fts=False))
    assert st["present"] is False
    assert st["rows"] is None  # nothing to count, not a failure


def test_slow_count_is_present_not_absent():
    """The exact bug: the row COUNT times out on a large index -> present STAYS true (from
    the schema), rows=None with count_status=timed_out — NEVER 'absent'."""
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        if "count(*) FROM article_fts" in str(stmt):
            raise StatementTimeout("simulated slow FTS count")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["present"] is True, "a slow count must never be read as an absent table"
    assert st["healthy"] is True  # the cheap LIMIT-1 probe still ran
    assert st["rows"] is None and st["count_status"] == "timed_out"


def test_corrupt_index_is_present_but_unhealthy_actionable():
    """A post-crash malformed FTS index: present=True (still in the schema) but healthy=False,
    with the error captured — the actionable 're-index heals it' signal, not 'absent'."""
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        if "rowid FROM article_fts" in str(stmt):
            raise RuntimeError("database disk image is malformed")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["present"] is True
    assert st["healthy"] is False
    assert st["count_status"] == "error"
    assert "malformed" in (st["error"] or "")


def test_non_sqlite_backend_is_unsupported_not_absent():
    class _FakeBind:
        class dialect:
            name = "postgresql"

    class _FakeSession:
        def get_bind(self):
            return _FakeBind()

    st = fts_status(_FakeSession())
    assert st["supported"] is False
    assert st["present"] is None  # unknown, never a false "absent"


# ------- the anti-contradiction guarantee: the two probes must never disagree ------- #


def test_integrity_and_schema_drift_agree_even_when_the_count_times_out():
    from src.monitoring.integrity import corpus_integrity
    from src.monitoring.schema_drift import schema_drift

    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        # Reproduce the field condition: the FTS row COUNT is too slow and aborts.
        if "count(*) FROM article_fts" in str(stmt):
            raise StatementTimeout("simulated slow FTS count")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    ci = corpus_integrity(s, sample=50)
    sd = schema_drift(s)

    assert ci["fts"]["present"] is True, "integrity no longer misreads a slow count as absent"
    assert sd["fts_present"] is True
    assert ci["fts"]["present"] == sd["fts_present"], "the two probes must never disagree"
    # The count could not complete, but that is disclosed as a status, not conflated with absence.
    assert ci["fts"]["fts_rows"] is None and ci["fts"]["count_status"] == "timed_out"


def test_integrity_reports_a_genuinely_absent_index():
    from src.monitoring.integrity import corpus_integrity
    from src.monitoring.schema_drift import schema_drift

    s = _corpus(with_fts=False)
    ci = corpus_integrity(s, sample=50)
    sd = schema_drift(s)
    assert ci["fts"]["present"] is False and sd["fts_present"] is False
