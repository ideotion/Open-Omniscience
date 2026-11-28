"""Row 450 (R850): a judging qualification attempt records the NAMES of the criteria that failed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R850's one-time re-check found that main kept no verdict reasons: the field analysis could name the criterion behind
a disqualification only by elimination. ``source_qualification_attempts.failing_criteria`` now holds the failing
criteria's names (sorted, comma-separated; "" = nothing failed; NULL = not recorded), never article text or a value,
and it is self-healed onto an older store, carried by a restore when the backup has it, and exported.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.analytics.source_audit import CRITERIA
from src.catalog.qualification import evaluate_and_stamp, failing_criteria_names
from src.database.models import Article, Base, FeedFetchState, Source, SourceQualificationAttempt
from tests._app_engine import app_sqlite_engine


def _fail(name: str, *, ef: bool = False) -> dict:
    return {"criterion": name, "value": 0.9, "direction": "high", "extraction_failure": ef}


def test_names_are_sorted_known_and_never_anything_else():
    assert failing_criteria_names([]) == ""
    assert failing_criteria_names([_fail("pathology_rate"), _fail("link_density_rate"), _fail("pathology_rate")]) \
        == "link_density_rate,pathology_rate"
    # a name the registry does not know (or any text that is not a name) is dropped, never stored
    assert failing_criteria_names([_fail("Subscribe now to read <b>this</b> article"), _fail("short_article_rate")]) \
        == "short_article_rate"
    assert all(set(c["name"]) <= set("abcdefghijklmnopqrstuvwxyz_") for c in CRITERIA)  # what the merge copy admits


@pytest.fixture
def db():
    eng = app_sqlite_engine(":memory:")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def test_evaluate_and_stamp_writes_the_failing_names(db):
    a = Source(name="A", domain="a.example", enabled=True)
    b = Source(name="B", domain="b.example", enabled=True)
    db.add_all([a, b])
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    evaluate_and_stamp(db, [a, b], {a.id: [_fail("link_density_rate", ef=True), _fail("furniture_share")]}, now=now)
    db.commit()
    got = {r.source_id: (r.verdict, r.failing_criteria) for r in db.query(SourceQualificationAttempt)}
    assert got[a.id] == ("disqualified", "furniture_share,link_density_rate")
    assert got[b.id] == ("qualified", "")  # judged, nothing failed: "", never NULL


def test_the_self_heal_adds_the_column_to_an_older_store_once(tmp_path):
    from src.database.maintenance import ensure_qualification_attempt_failing_column

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE source_qualification_attempts (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, "
                "attempted_at DATETIME NOT NULL, verdict VARCHAR(20) NOT NULL, criteria_version VARCHAR(40) NOT NULL)")
    con.execute("INSERT INTO source_qualification_attempts VALUES (1, 1, '2026-01-01', 'qualified', 'v1')")
    con.commit()
    con.close()
    eng = app_sqlite_engine(path)
    try:
        assert ensure_qualification_attempt_failing_column(eng) == ["failing_criteria"]
        assert ensure_qualification_attempt_failing_column(eng) == []
        with eng.connect() as c:
            assert c.execute(text("SELECT failing_criteria FROM source_qualification_attempts")).scalar() is None
    finally:
        eng.dispose()


@pytest.mark.parametrize(("incoming", "kept"), [
    ("link_density_rate,pathology_rate", "link_density_rate,pathology_rate"),
    ("", ""),
    (None, None),
    ("Subscribe now", None),               # a capital or a space: not a name list
    ("pathology_rate; DROP TABLE x", None),
    ("a" * 401, None),                      # over the column
    ("a" * 400, "a" * 400),                 # exactly the column
    ("pathology_rate\x00https://example.invalid/" + "z" * 500, None),  # GLOB and length() stop at a NUL
    (b"pathology_rate", None),              # a BLOB keeps its type in a TEXT column
    (b"ab\x00xyz", None),
    (7, None),
])
def test_a_restore_copies_only_a_list_of_names(incoming, kept):
    from src.backup.merge import _FAILING_CRITERIA_COPY

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE i (failing_criteria TEXT)")
    con.execute("INSERT INTO i VALUES (?)", (incoming,))
    assert con.execute(f"SELECT {_FAILING_CRITERIA_COPY} FROM i").fetchone()[0] == kept  # noqa: S608 - a module constant


def test_the_restore_carries_the_column_when_both_sides_have_it():
    import inspect

    from src.backup import merge

    src = inspect.getsource(merge)
    assert '_has_column(con, "inc", "source_qualification_attempts", "failing_criteria")' in src
    assert '_has_column(con, "main", "source_qualification_attempts", "failing_criteria")' in src


def test_the_field_data_export_names_the_last_attempts_failing_criteria():
    from src.api.diagnostics.source_samples import build_sample_zip

    eng = app_sqlite_engine(":memory:")
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__, SourceQualificationAttempt.__table__,
                                          FeedFetchState.__table__])
    with Session(eng) as db:
        db.add_all([Source(id=1, name="S1", domain="s1.example"), Source(id=2, name="S2", domain="s2.example"),
                    Source(id=3, name="S3", domain="s3.example")])
        db.flush()
        db.add(Article(url="https://s1.example/a", canonical_url="https://s1.example/a", source_id=1, title="t",
                       content="x " * 50, hash="1" * 64))
        db.add_all([
            SourceQualificationAttempt(source_id=1, attempted_at=datetime(2026, 11, 1), verdict="qualified",
                                       criteria_version="v", failing_criteria=""),
            SourceQualificationAttempt(source_id=2, attempted_at=datetime(2026, 10, 1), verdict="qualified",
                                       criteria_version="v", failing_criteria=""),
            SourceQualificationAttempt(source_id=2, attempted_at=datetime(2026, 11, 1), verdict="disqualified",
                                       criteria_version="v", failing_criteria="link_density_rate,not_a_criterion"),
            SourceQualificationAttempt(source_id=3, attempted_at=datetime(2026, 11, 1), verdict="qualified",
                                       criteria_version="v", failing_criteria=None),
        ])
        db.commit()
        data, *_ = build_sample_zip(db, after=0, seed=1, cap=4_000_000)
    man = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    sampled = {r["source_id"]: r for r in man["sources"]}
    assert sampled[1]["last_qualification"] == "qualified" and sampled[1]["last_failing_criteria"] == []
    rows = {r[0]: r for r in man["sources_without_article"]["rows"]}
    assert rows[2][4] == ["link_density_rate"]  # the newest attempt's; an unknown name never leaves
    assert rows[3][4] is None                    # not recorded, never guessed
