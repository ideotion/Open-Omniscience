"""The lane SCHEMA's own guards: no scores, no cross-contamination, no naive clocks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every assertion here is a MEASUREMENT taken from the live metadata rather than a
reading of the source, because the failures these catch all look like nothing in a
diff: one column hung off the wrong base, one timestamp declared the ordinary way,
one field named ``relevance_score``. They arrive one line at a time and none of them
reddens a behavioural test.

The fixture-parity pair at the bottom is the same idea one level out: a synthetic
client that has drifted from the real one still passes every test written against
it, and proves nothing at all.
"""

from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import DateTime, String

from src.versioned.models import (
    LANE_MODELS,
    LaneBase,
    LaneCompressedText,
    LaneUTCDateTime,
    VersionedEntity,
)

#: The measured ceiling, not an aspiration. The Q1140 NOTE asks new tables to
#: anticipate PostgreSQL's column limits; this pins the widest lane table so a slice
#: that widens one has to raise the number deliberately and say why in its diff.
COLUMN_CEILING = 15

#: A column name containing any of these would be this project forming an opinion.
FORBIDDEN_NAME_PARTS = ("score", "rating", "ranking", "grade", "confidence", "trust")


def _lane_tables():
    return LaneBase.metadata.tables


def test_no_lane_column_is_a_SCORE_by_any_of_its_names():
    """Honesty by construction: the lane stores what a source said and when.

    Checked over the column NAMES rather than over a list of models, so a table
    added by a later slice is covered the day it is written rather than the day
    somebody remembers to extend a list.
    """
    offenders = []
    for table_name, table in _lane_tables().items():
        for column in table.columns:
            lowered = column.name.lower()
            for part in FORBIDDEN_NAME_PARTS:
                if part in lowered:
                    offenders.append(f"{table_name}.{column.name}")
    assert offenders == [], f"the lane schema grew an opinion: {offenders}"


def test_the_widest_lane_table_stays_within_its_measured_ceiling():
    """Re-measured from ``__table__.columns`` — the docstrings' figure is not trusted.

    An earlier draft of this package carried a column count in prose that was wrong
    twice in one session (16 claimed, 14 real, then 15). A number in a docstring is
    not a measurement; this is.
    """
    widths = {name: len(table.columns) for name, table in _lane_tables().items()}
    widest = max(widths, key=lambda k: widths[k])
    assert widths[widest] <= COLUMN_CEILING, (
        f"{widest} carries {widths[widest]} columns, past the ceiling of "
        f"{COLUMN_CEILING} — raise it deliberately, with a reason"
    )
    # ...and the ceiling has zero slack, so it cannot quietly stop meaning anything.
    assert widths[widest] == COLUMN_CEILING, (
        f"the widest table is now {widest} at {widths[widest]}; lower COLUMN_CEILING "
        "to match, or the ceiling is no longer a measurement of anything"
    )


def test_every_lane_TIMESTAMP_goes_through_the_refusing_decorator():
    """Not one bare ``DateTime``. The naive-datetime hazard returns one column at a time.

    ``DateTime(timezone=True)`` on SQLite is a declaration of intent that the backend
    does not honour: the value comes back naive and the first comparison against an
    aware one raises — or, worse, does not.
    """
    bare = []
    for table_name, table in _lane_tables().items():
        for column in table.columns:
            if isinstance(column.type, DateTime) and not isinstance(column.type, LaneUTCDateTime):
                bare.append(f"{table_name}.{column.name}")
    assert bare == [], f"these columns store a timestamp the naive way: {bare}"


def test_the_lane_metadata_and_the_CORPUS_metadata_cannot_see_each_other():
    """The structural reason ``LaneBase`` exists, asserted rather than described.

    If the lane tables hung off the corpus base, ``init_db``'s ``create_all`` would
    put them in ``corpus.db`` and ``alembic check`` would demand migrations for them.
    Both failures are silent in the diff that causes them.
    """
    from src.database.models import Base

    lane_names = set(LaneBase.metadata.tables)
    corpus_names = set(Base.metadata.tables)
    assert lane_names, "the lane metadata is empty — this test would pass vacuously"
    assert lane_names & corpus_names == set(), (
        f"these tables are in BOTH schemas: {sorted(lane_names & corpus_names)}"
    )
    # The direction that actually bites: a lane model reachable from the corpus base.
    for model in LANE_MODELS:
        assert model.__table__.metadata is LaneBase.metadata, (
            f"{model.__name__} hangs off the wrong metadata"
        )


def test_both_compressors_are_the_SAME_object_not_two_implementations():
    """One compressor, two decorators' worth of plumbing. The ledger's standing rule
    is that two implementations of one thing drift; this makes the drift red."""
    from src.database.models import CompressedText

    lane = LaneCompressedText()
    corpus = CompressedText()
    assert lane.compressor is corpus.compressor, (
        "the lane and the corpus compress through different objects"
    )


def test_the_country_column_is_ALPHA_3_wide_from_birth():
    """Q312: alpha-3 from birth. A 2-wide column is a migration nobody schedules."""
    column = VersionedEntity.__table__.columns["country_alpha3"]
    assert isinstance(column.type, String)
    assert column.type.length == 3, f"country_alpha3 is {column.type.length} wide"


def test_the_change_table_names_what_changed_even_with_no_entity():
    """The column that lets an unwatched change be attached later, and be NAMED now."""
    from src.versioned.models import VersionedChange

    column = VersionedChange.__table__.columns["external_id"]
    assert column.nullable is True, "a feed may report an event with nothing to point at"
    assert VersionedChange.__table__.columns["entity_id"].nullable is True


# ------------------------------------------------------------------ fixture parity


def test_the_FIXTURE_client_matches_the_REAL_client_method_for_method():
    """A drifted double still passes every test written against it.

    Compares the public fetch surface by NAME and by SIGNATURE. If ``WikiClient``
    grows a parameter the fixture does not have, the lane tests are exercising a
    contract the production client no longer offers — and they stay green while
    doing it, which is the whole failure.
    """
    from src.testing.wiki_fixture import FixtureWikiClient
    from src.wiki.client import WikiClient

    real = {
        name
        for name, _ in inspect.getmembers(WikiClient, inspect.isfunction)
        if name.startswith("fetch_")
    }
    fake = {
        name
        for name, _ in inspect.getmembers(FixtureWikiClient, inspect.isfunction)
        if name.startswith("fetch_")
    }
    assert real, "no fetch surface found — the comparison would be vacuous"
    missing = real - fake
    assert missing == set(), f"the fixture does not implement: {sorted(missing)}"

    for name in sorted(real):
        want = inspect.signature(getattr(WikiClient, name))
        got = inspect.signature(getattr(FixtureWikiClient, name))
        assert list(want.parameters) == list(got.parameters), f"{name}: real{want} vs fixture{got}"


def test_the_fixture_file_is_exactly_what_its_generator_produces():
    """Deterministic regeneration, asserted by re-running the generator.

    A committed fixture nobody can reproduce is a binary blob with a story attached.
    This regenerates it into a temporary path and compares digests, so an edit made
    to the JSON by hand — the way a fixture quietly stops matching its own spec —
    reddens here.
    """
    root = Path(__file__).resolve().parents[1]
    committed = root / "tests/fixtures/wiki/oowiki.json"
    generator = root / "scripts/make_wiki_fixture.py"
    assert committed.is_file() and generator.is_file()

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "oowiki.json"
        proc = subprocess.run(
            [sys.executable, str(generator), "--out", str(out)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        regenerated = hashlib.sha256(out.read_bytes()).hexdigest()

    on_disk = hashlib.sha256(committed.read_bytes()).hexdigest()
    assert regenerated == on_disk, (
        "the committed fixture is not what the generator produces; regenerate it "
        f"(generator {regenerated[:12]} vs committed {on_disk[:12]})"
    )


def test_the_PROVENANCE_note_records_the_digest_the_file_actually_has():
    """A provenance note carrying a stale digest is worse than none: it is a check
    that reads as having been performed."""
    root = Path(__file__).resolve().parents[1]
    committed = root / "tests/fixtures/wiki/oowiki.json"
    note = (root / "tests/fixtures/wiki/PROVENANCE.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(committed.read_bytes()).hexdigest()
    assert digest in note, f"PROVENANCE.md does not carry the file's digest ({digest})"
    assert str(committed.stat().st_size) in note, "PROVENANCE.md does not carry its size"


@pytest.mark.parametrize("model", LANE_MODELS)
def test_every_lane_model_has_a_docstring_saying_what_it_is_FOR(model):
    """Not decoration. Each of these tables encodes a refusal (the baseline is written
    once; a change is recorded whether or not its text was fetched), and a table whose
    reason is unwritten is one a later slice will simplify away."""
    assert (model.__doc__ or "").strip(), f"{model.__name__} has no docstring"
