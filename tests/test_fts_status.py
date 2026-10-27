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

import contextlib
import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError as _SADatabaseError
from sqlalchemy.orm import sessionmaker

from src.database import damage
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
    assert st["indexed_documents"] == 1 and st["indexed_status"] == "ok" and st["index_state"] == "ends-agree"


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
    assert st["error"] == "RuntimeError", "the class of the failure; the exception's own words are not kept"


def _driver_failure(line: str, code: int, name: str) -> Exception:
    """What the session raises for a driver error: SQLAlchemy's wrapper (its text carries the statement and
    every bound value) around the driver's own exception, which carries the engine's line."""
    inner = sqlite3.OperationalError(line)
    inner.sqlite_errorcode = code  # type: ignore[attr-defined]
    inner.sqlite_errorname = name  # type: ignore[attr-defined]
    return _SADatabaseError("SELECT rowid FROM article_fts WHERE x = 'MARKER-BOUND-VALUE'", ("MARKER-BOUND-VALUE",), inner)


@pytest.mark.parametrize(
    "fails_on, line, code, name, expected, where",
    [
        pytest.param(
            "rowid FROM article_fts", "malformed database schema (secret_index_name) - near \"MARKER-FRAGMENT\"",
            11, "SQLITE_CORRUPT", "OperationalError: " + damage.CORRUPT_SCHEMA, "the health probe, a damaged schema", id="health-schema",
        ),
        pytest.param(
            "rowid FROM article_fts", "database disk image is malformed MARKER-PAGE",
            11, "SQLITE_CORRUPT", "OperationalError: " + damage.CORRUPT_IMAGE, "the health probe, a damaged page", id="health-page",
        ),
        pytest.param(
            "rowid FROM article_fts", "disk I/O error MARKER-IO", 10, "SQLITE_IOERR", "OperationalError: SQLITE_IOERR",
            "the health probe, an I/O error", id="health-io",
        ),
        pytest.param(
            "count(*) FROM article_fts", "disk I/O error MARKER-IO", 10, "SQLITE_IOERR", "OperationalError: SQLITE_IOERR",
            "the row count", id="count-io",
        ),
        pytest.param(
            "sqlite_master", "disk I/O error MARKER-IO", 10, "SQLITE_IOERR", "OperationalError: SQLITE_IOERR",
            "the presence read", id="presence-io",
        ),
        pytest.param(
            "FROM article_fts_docsize", "disk I/O error MARKER-IO", 10, "SQLITE_IOERR", "OperationalError: SQLITE_IOERR",
            "the index's own population count", id="population-io",
        ),
    ],
)
def test_a_failed_probe_is_recorded_as_a_class_and_a_fixed_label_never_the_engines_words(fails_on, line, code, name, expected, where):
    """The integrity report that carries ``error`` rides the diagnostics bundle, and a database error
    ends in the engine's own line (the name of a schema object and a fragment of its definition) beside
    SQLAlchemy's statement and bound values: engine text into a record is class-only."""
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        if fails_on in str(stmt):
            raise _driver_failure(line, code, name)
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["error"] == expected, where
    assert "MARKER" not in repr(st) and "secret_index_name" not in repr(st) and "SELECT" not in repr(st), where


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


# ------- the index's own population: the probe and the count cannot see it (0.5.1 item 29) ------- #
#
# ``article_fts`` is an EXTERNAL-CONTENT table, so ``SELECT rowid ... LIMIT 1`` and ``COUNT(*)`` are answered
# from ``articles``: they read healthy and full over an index that holds nothing. The index's own record is
# its shadow table ``article_fts_docsize``.


def _empty_the_index(s) -> None:
    s.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))
    s.commit()


def _add_an_article_the_index_never_sees(s) -> None:
    """A second article that no trigger indexes: a PARTIAL index (what an interrupted or mismatched rebuild would leave)."""
    s.execute(text("DROP TRIGGER article_fts_ai"))
    s.add(Article(
        url="u2", canonical_url="u2", source_id=1, title="Second", content="second article",
        hash="h2", language="en", created_at=datetime.now(UTC),
    ))
    s.commit()


def test_an_index_emptied_under_its_articles_is_not_healthy_though_the_probe_and_the_count_read_full():
    s = _corpus()
    _empty_the_index(s)
    st = fts_status(s)
    assert st["rows"] == 1 and st["count_status"] == "ok", "the count is still answered from articles: the reason indexed_documents exists"
    assert st["indexed_documents"] == 0 and st["indexed_status"] == "ok"
    assert st["index_state"] == "empty" and st["healthy"] is False and st["error"] == "EmptyIndex"
    assert st["present"] is True, "an empty index is present, never absent"


def test_an_empty_index_over_no_articles_is_healthy_and_not_called_empty():
    s = _corpus()
    s.execute(text("DELETE FROM articles"))
    s.commit()
    st = fts_status(s)
    assert st["indexed_documents"] == 0 and st["index_state"] == "ends-agree" and st["healthy"] is True and st["error"] is None


def test_a_tail_missing_from_the_index_is_named_partial_inferred_and_refuses_the_healthy_verdict():
    """A second article that no trigger indexed: the index's highest document id (1) is below the articles' (2)."""
    from src.monitoring.integrity import corpus_integrity

    s = _corpus()
    _add_an_article_the_index_never_sees(s)
    st = fts_status(s)
    assert st["indexed_documents"] == 1 and st["index_state"] == "partial (inferred)"
    assert st["healthy"] is False and st["error"] == "PartialIndex" and st["present"] is True
    assert st["rows"] == 2, "the content count reads the articles, so it cannot show the missing document"
    fts = corpus_integrity(s, sample=50)["fts"]
    assert fts["articles"] == 2 and fts["indexed_documents"] == 1 and fts["delta"] == 1, fts
    assert fts["indexed_status"] == "ok" and fts["index_state"] == "partial (inferred)" and fts["healthy"] is False
    assert fts["fts_rows"] == 2, "kept for readers of earlier reports; it is the content table's count"


def test_a_hole_in_the_middle_is_not_seen_by_the_ends_and_the_integrity_delta_is_what_shows_it():
    """THE STATED LIMIT: the highest ids agree, so ``index_state`` says ``ends-agree`` (and what that means is "the ends", not "whole");
    the count comparison the integrity report makes is what sees the document that is missing. A missing TAIL becomes exactly this
    at the next ingest: the verdict ``partial (inferred)`` closes the moment the next article is indexed by its trigger."""
    from src.monitoring.integrity import corpus_integrity

    s = _corpus()
    ddl = s.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='article_fts_ai'")).scalar()
    s.execute(text("DROP TRIGGER article_fts_ai"))
    for i in (2, 3):
        if i == 3:
            assert fts_status(s)["index_state"] == "partial (inferred)", "article 2 is a missing tail: seen, until the next ingest"
            s.execute(text(ddl))  # the trigger is back: article 3 is indexed, article 2 never was
        s.add(Article(
            url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=f"Story {i}", content=f"story number {i}",
            hash=f"h{i}", language="en", created_at=datetime.now(UTC),
        ))
        s.commit()
    st = fts_status(s)
    assert st["indexed_documents"] == 2 and st["index_state"] == "ends-agree" and st["healthy"] is True, "the ends agree: nothing to see"
    fts = corpus_integrity(s, sample=50)["fts"]
    assert fts["articles"] == 3 and fts["delta"] == 1, "the delta is what sees the hole"


def test_an_index_that_holds_documents_beyond_its_articles_reads_ends_agree_which_is_not_agreement():
    """The label says "neither problem was seen"; an index AHEAD of its articles (a document whose article is gone, here with the
    delete trigger dropped) is neither empty nor partial, and the integrity ``delta`` is negative."""
    from src.monitoring.integrity import corpus_integrity

    s = _corpus()
    s.execute(text("DROP TRIGGER article_fts_ad"))
    s.execute(text("DELETE FROM articles"))
    s.commit()
    st = fts_status(s)
    assert st["rows"] == 0 and st["indexed_documents"] == 1
    assert st["index_state"] == "ends-agree" and st["healthy"] is True and st["error"] is None
    assert corpus_integrity(s, sample=50)["fts"]["delta"] == -1


def test_an_id_that_a_delete_freed_and_an_ingest_took_again_is_indexed_and_reads_whole():
    """Ids are reused (no AUTOINCREMENT): the top article is deleted, its index row goes with it, and the next article takes the same
    id and is indexed by its trigger. This is why the three numbers are read in ONE statement (see the statement-shape test)."""
    s = _corpus()
    s.add(Article(
        url="u2", canonical_url="u2", source_id=1, title="Second", content="second article",
        hash="h2", language="en", created_at=datetime.now(UTC),
    ))
    s.commit()
    s.execute(text("DELETE FROM articles WHERE id = 2"))
    s.commit()
    s.add(Article(
        url="u3", canonical_url="u3", source_id=1, title="Third", content="third article",
        hash="h3", language="en", created_at=datetime.now(UTC),
    ))
    s.commit()
    assert s.execute(text("SELECT max(id) FROM articles")).scalar() == 2, "the id was reused"
    st = fts_status(s)
    assert st["indexed_documents"] == 2 and st["index_state"] == "ends-agree" and st["healthy"] is True and st["error"] is None


def test_the_integrity_report_names_an_empty_index():
    from src.monitoring.integrity import corpus_integrity

    s = _corpus()
    _empty_the_index(s)
    fts = corpus_integrity(s, sample=50)["fts"]
    assert fts["healthy"] is False and fts["index_state"] == "empty" and fts["indexed_documents"] == 0 and fts["delta"] == 1, fts
    assert fts["indexed_status"] == "ok"
    assert fts["error"] == "EmptyIndex"


def test_a_slow_population_count_is_a_status_and_leaves_the_rest_of_the_answer_alone():
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        if "count(*) FROM article_fts_docsize" in str(stmt):
            raise StatementTimeout("simulated slow population count")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["indexed_status"] == "timed_out" and st["indexed_documents"] is None and st["index_state"] is None
    assert st["healthy"] is True and st["rows"] == 1 and st["count_status"] == "ok"


def test_the_three_numbers_of_the_ends_are_read_in_one_statement():
    """The articles' top id, the index's count and the index's top id come from ONE statement: one statement is one read snapshot, so an
    ingest or a delete cannot fall between them. Separate reads cannot be ordered safely: ids are reused after the top articles are deleted
    (no AUTOINCREMENT), so a re-read after a delete and an ingest sees a new article under an old id and reads a tail the index never
    saw (a fully indexed store called ``partial (inferred)``). A statement that carries only one or two of the numbers is red."""
    s = _corpus()
    seen: list[str] = []
    orig = s.execute

    def spy(stmt, *a, **k):
        seen.append(" ".join(str(stmt).split()))
        return orig(stmt, *a, **k)

    s.execute = spy  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["indexed_documents"] == 1 and st["index_state"] == "ends-agree"
    ends = [x for x in seen if "max(id) FROM articles" in x or ("article_fts_docsize" in x and "sqlite_master" not in x)]
    assert len(ends) == 1, ends
    assert "max(id) FROM articles" in ends[0] and "count(*) FROM article_fts_docsize" in ends[0]
    assert "max(id) FROM article_fts_docsize" in ends[0]


def test_the_population_count_runs_inside_a_deadline_of_its_own(monkeypatch):
    """Bounded: the shadow-table count is read inside ``statement_deadline`` (the count's 15 s), not bare."""
    from src.database import maintenance

    s = _corpus()
    depth = {"open": 0}
    seen: list[int] = []
    real_deadline = maintenance.statement_deadline

    @contextlib.contextmanager
    def watching(session, seconds):
        depth["open"] += 1
        try:
            with real_deadline(session, seconds=seconds):
                yield
        finally:
            depth["open"] -= 1

    orig = s.execute

    def fake(stmt, *a, **k):
        text_of = str(stmt)
        if "article_fts_docsize" in text_of or "max(id) FROM articles" in text_of:
            seen.append(depth["open"])
        return orig(stmt, *a, **k)

    monkeypatch.setattr(maintenance, "statement_deadline", watching)
    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["indexed_documents"] == 1
    assert len(seen) == 2 and all(inside == 1 for inside in seen), seen  # the shadow table's presence, then the three numbers


def test_a_failed_read_of_the_ends_claims_nothing_and_keeps_the_class_only():
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        if "max(id) FROM articles" in str(stmt):
            raise _driver_failure("disk I/O error MARKER-IO", 10, "SQLITE_IOERR")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["indexed_status"] == "error" and st["indexed_documents"] is None and st["index_state"] is None
    assert st["healthy"] is True, "an index this probe could not judge is not called damaged"
    assert st["error"] == "OperationalError: SQLITE_IOERR" and "MARKER" not in repr(st)


def test_a_failure_of_the_population_does_not_replace_the_error_an_earlier_step_named():
    s = _corpus()
    orig = s.execute

    def fake(stmt, *a, **k):
        text_of = str(stmt)
        if "count(*) FROM article_fts_docsize" in text_of:
            raise _driver_failure("disk I/O error MARKER-IO", 10, "SQLITE_IOERR")
        if "count(*) FROM article_fts" in text_of:
            raise RuntimeError("the content count failed")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["count_status"] == "error" and st["indexed_status"] == "error"
    assert st["error"] == "RuntimeError", "the first failure stays the one named; indexed_status says the second happened"


@pytest.mark.parametrize("damage_the_index, state, label", [
    (lambda s: _empty_the_index(s), "empty", "EmptyIndex"),
    (lambda s: _add_an_article_the_index_never_sees(s), "partial (inferred)", "PartialIndex"),
])
def test_a_verdict_does_not_replace_the_error_the_count_named_and_still_refuses_the_healthy_verdict(damage_the_index, state, label):
    """A torn copy is where a corruption error on the content count is likely: the class the count named stays the one named (and
    ``count_status`` says it failed), while ``index_state`` and ``healthy`` carry the verdict. The fixed label is only for a clean count."""
    s = _corpus()
    damage_the_index(s)
    orig = s.execute

    def fake(stmt, *a, **k):
        if "count(*) FROM article_fts" in str(stmt) and "docsize" not in str(stmt):
            raise _driver_failure("database disk image is malformed MARKER-PAGE", 11, "SQLITE_CORRUPT")
        return orig(stmt, *a, **k)

    s.execute = fake  # type: ignore[method-assign]
    st = fts_status(s)
    assert st["count_status"] == "error" and st["rows"] is None
    assert st["error"] == "OperationalError: " + damage.CORRUPT_IMAGE and "MARKER" not in repr(st), st
    assert st["index_state"] == state and st["healthy"] is False and st["indexed_status"] == "ok"
    s.execute = orig  # type: ignore[method-assign]
    assert fts_status(s)["error"] == label, "with a clean count the fixed label is what names it"


def test_a_row_ingested_after_the_index_was_read_is_never_a_missing_document_in_the_integrity_delta(monkeypatch):
    """The article count is taken BEFORE the index's: an ingest between the two reads can push ``delta`` below zero, never above."""
    from src.database import fts as fts_module
    from src.monitoring.integrity import corpus_integrity

    s = _corpus()
    real = fts_module.fts_status

    def then_an_ingest(session):
        status = real(session)  # the index was read ...
        session.add(Article(
            url="u3", canonical_url="u3", source_id=1, title="Third", content="third article",
            hash="h3", language="en", created_at=datetime.now(UTC),
        ))
        session.commit()  # ... and then an article arrived (its trigger indexes it, as ingest does)
        return status

    monkeypatch.setattr(fts_module, "fts_status", then_an_ingest)
    fts = corpus_integrity(s, sample=50)["fts"]
    assert fts["articles"] == 1 and fts["indexed_documents"] == 1 and fts["delta"] == 0, fts


def test_an_index_built_without_the_shadow_table_is_unprobeable_and_never_called_empty_or_partial():
    s = _corpus(with_fts=False)
    s.execute(text(
        "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', content_rowid='id', columnsize=0)"
    ))
    s.commit()
    st = fts_status(s)
    assert st["present"] is True and st["healthy"] is True
    assert st["indexed_status"] == "unprobeable" and st["indexed_documents"] is None and st["index_state"] is None
    assert st["error"] is None


def test_no_index_and_no_backend_leave_the_population_unasked():
    assert fts_status(_corpus(with_fts=False))["indexed_status"] == "skipped"
    st = fts_status(type("S", (), {"get_bind": lambda self: type("B", (), {"dialect": type("D", (), {"name": "postgresql"})})()})())
    assert st["indexed_status"] == "skipped" and st["indexed_documents"] is None and st["index_state"] is None


# ------- a prefix index, at test size ------- #


def test_a_prefix_index_over_many_articles_is_named_partial_and_no_article_is_counted():
    """Export's construction (a front part of the articles indexed, the rest not), at test size: the reads are the two highest ids and the
    index's own count; ``count(*) FROM articles`` (the 74 s cold scan the boot refuses) is never run, whichever way it is spelled, on any
    route to the engine (the statements are taken at the cursor, not at ``session.execute``)."""
    import re

    from sqlalchemy import event

    from src.database.fts import index_articles

    s = _corpus()
    s.execute(text("DROP TRIGGER article_fts_ai"))
    for i in range(2, 21):
        s.add(Article(
            url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=f"Story {i}", content=f"story number {i}",
            hash=f"h{i}", language="en", created_at=datetime.now(UTC),
        ))
    s.commit()
    s.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))  # emptied, then the first half indexed back
    s.commit()
    con = s.connection()
    index_articles(con, list(range(1, 11)))
    s.commit()
    statements: list[str] = []
    engine = s.get_bind()

    def spy(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        st = fts_status(s)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert st["indexed_documents"] == 10 and st["index_state"] == "partial (inferred)" and st["healthy"] is False, st
    assert st["error"] == "PartialIndex"
    assert any("article_fts_docsize" in x for x in statements), "the spy saw the population read: it is listening"
    counting_articles = re.compile(r"count\(\s*(\*|1)?\s*\)\s+from\s+articles\b", re.IGNORECASE)
    assert not [x for x in statements if counting_articles.search(x)], "the corpus scan the boot refuses must not run"
