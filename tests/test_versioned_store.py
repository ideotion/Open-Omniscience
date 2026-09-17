"""S2: one encrypted database file per lane, through the ONE keyed path.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief's S2 acceptance clause, verbatim: *"the lane files exist encrypted with
the corpus passphrase (gate); an unkeyed open fails CLOSED (``DatabaseLockedError``
family)."* Every test here is one clause of that, plus the negative space around it:
the states a lane must REFUSE, and the states it must report rather than invent.

Each test drives the real ``store`` module against a real SQLCipher file. Nothing is
mocked, because the property under test IS what the bytes on disk look like — a
double would agree with whatever the code did.

THE SUITE RUNS PLAINTEXT BY DEFAULT (``conftest`` sets ``OO_DB_PLAINTEXT=1``, the
ruled opt-out). Every encrypted test here therefore removes that variable with
``monkeypatch.delenv`` — never ``os.environ.pop``, which is a session-wide edit whose
failure surfaces in an unrelated file thousands of tests later.
"""

from __future__ import annotations

import pytest

from src.database.connect import (
    DatabaseLockedError,
    WrongPassphraseError,
    connect,
    is_encrypted_file,
    set_passphrase,
)
from src.versioned import store
from src.versioned.lanes import UnknownLaneError, all_lanes
from src.versioned.models import VersionedEntity

PASSPHRASE = "a lane shares the corpus passphrase"


@pytest.fixture
def encrypted_lane(tmp_path, monkeypatch):
    """A data directory whose lanes are created ENCRYPTED, as production creates them.

    Disposes every cached lane engine on the way in AND on the way out: the engine
    map is process-global, so a lane left open by an earlier test would hold a
    connection to a directory this one is about to replace.
    """
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", PASSPHRASE, raising=False)
    try:
        yield tmp_path
    finally:
        store.dispose_all()
        set_passphrase(None)


def test_a_lane_file_is_encrypted_with_the_corpus_passphrase(encrypted_lane):
    """The gate clause: the file on disk is ciphertext, and the corpus key opens it.

    ``is_encrypted_file`` reads the first sixteen bytes of the file itself, so this
    is a fact about the artifact rather than about the configuration that produced
    it — the distinction the encrypted click-through ritual exists to keep.
    """
    path = store.create_lane("wiki")
    assert path.is_file()
    assert is_encrypted_file(path) is True, "the lane file is not encrypted at rest"

    # And the CORPUS passphrase — not a lane-specific one — is what opens it.
    con = connect(str(path), key=PASSPHRASE)
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master").fetchall()}
    finally:
        con.close()
    assert "versioned_entities" in names
    assert "lane_meta" in names


def test_an_unkeyed_open_of_a_lane_fails_CLOSED(encrypted_lane):
    """No passphrase: ``DatabaseLockedError``. Not an empty lane, not a fresh one."""
    path = store.create_lane("wiki")
    store.dispose_all()
    set_passphrase(None)
    with pytest.raises(DatabaseLockedError):
        connect(str(path))


def test_a_wrong_passphrase_fails_CLOSED_and_keeps_its_cause(encrypted_lane):
    """A wrong key is ``WrongPassphraseError``, chained — never a silent empty open.

    The chained cause matters for the same reason it does on the corpus: the
    page-size probe tries several candidates, and a bare refusal with no
    ``__cause__`` would hide which attempt actually failed.
    """
    path = store.create_lane("wiki")
    store.dispose_all()
    with pytest.raises(WrongPassphraseError) as excinfo:
        connect(str(path), key="not the corpus passphrase")
    assert excinfo.value.__cause__ is not None


def test_a_lane_is_never_created_plaintext_while_the_store_is_encrypted(encrypted_lane):
    """Q1005 = a has no per-lane plaintext option, and this proves the absence.

    The mechanism is that ``store`` passes NEITHER ``key=`` nor
    ``create_encrypted=`` to the factory — so there is no argument a caller could
    supply to get a plaintext lane beside an encrypted corpus. Asserted as
    behaviour rather than by reading the source, because a source guard here would
    be satisfied by the comment explaining the omission.
    """
    for spec in all_lanes():
        path = store.create_lane(spec.kind)
        assert is_encrypted_file(path) is True, f"{spec.filename} is plaintext"


def test_creating_a_lane_while_LOCKED_refuses_NAMING_THE_LANE(tmp_path, monkeypatch):
    """A locked store cannot make a lane, and the refusal names the LANE.

    THE MESSAGE IS THE CLAIM, and that is a correction. A mutation that deleted
    ``create_lane``'s own guard left an earlier version of this test green, because
    ``connect()`` refuses a fresh unkeyed file by itself — so asserting only the
    exception TYPE proved something about the factory rather than about this
    function. The lane-specific wording is what the guard actually adds, so the
    lane-specific wording is what is asserted; the mutant that removes the guard
    then fails by name, and the redundant-outcome measurement lives in
    ``create_lane``'s docstring so the next matrix does not re-find it.
    """
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", None, raising=False)
    try:
        with pytest.raises(DatabaseLockedError) as excinfo:
            store.create_lane("wiki")
        message = str(excinfo.value)
        assert "wiki lane" in message, message
        assert "same passphrase as the corpus" in message, message
        assert not store.lane_exists("wiki"), "a refused create still made a file"
    finally:
        store.dispose_all()


def test_an_absent_lane_is_ABSENT_and_never_a_zero_byte_lane(tmp_path, monkeypatch):
    """``None`` and ``0`` are different facts; the size reader refuses to merge them.

    The negative-space half is the one that matters: merely ASKING about a lane
    must not bring it into existence. ``connect()`` creates a missing file, so a
    size reader that went through the factory would answer by creating the thing.
    """
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    try:
        assert store.lane_exists("law") is False
        assert store.lane_file_bytes("law") is None
        with pytest.raises(store.LaneAbsentError):
            store.lane_engine("law")
        assert not store.lane_path("law").exists(), "asking about a lane created it"
    finally:
        store.dispose_all()


def test_a_present_lane_reports_a_real_size_including_its_wal(encrypted_lane):
    """A present lane reports bytes, and the figure counts the sidecars the disk holds."""
    store.create_lane("wiki")
    with store.lane_session("wiki") as session:
        for i in range(50):
            session.add(VersionedEntity(external_id=f"oo:Page {i}"))
    size = store.lane_file_bytes("wiki")
    assert size is not None and size > 0
    main_only = store.lane_path("wiki").stat().st_size
    assert size >= main_only, "the reported size is smaller than the file itself"


def test_the_engine_cache_is_keyed_on_the_PATH_not_only_the_kind(tmp_path, monkeypatch):
    """Re-pointing ``OO_DATA_DIR`` must give the SECOND store, not the first.

    The recorded defect is "the engine binds once per process, so a function-scoped
    fixture that re-points OO_DATA_DIR gets the first store", and its failure is
    silent: the second lane reads and writes the first one's rows. A cache keyed on
    ``kind`` alone reproduces it exactly.
    """
    store.dispose_all()
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    try:
        monkeypatch.setenv("OO_DATA_DIR", str(first))
        store.create_lane("wiki")
        with store.lane_session("wiki") as session:
            session.add(VersionedEntity(external_id="oo:Only In A"))

        monkeypatch.setenv("OO_DATA_DIR", str(second))
        store.create_lane("wiki")
        with store.lane_session("wiki") as session:
            ids = [r.external_id for r in session.query(VersionedEntity).all()]
        assert ids == [], f"the second lane is reading the first one's rows: {ids}"

        # ...and the first store is intact, so the isolation is two-way rather than
        # the second engine having clobbered the first.
        monkeypatch.setenv("OO_DATA_DIR", str(first))
        with store.lane_session("wiki") as session:
            ids = [r.external_id for r in session.query(VersionedEntity).all()]
        assert ids == ["oo:Only In A"]
    finally:
        store.dispose_all()


def test_a_lane_file_that_says_it_holds_another_kind_is_REFUSED(encrypted_lane):
    """A wiki lane opened as a law lane would write rows that read as real.

    There is no safe repair for this, so the refusal is the whole behaviour. Driven
    by rewriting ``lane_meta``'s own row — the state a file copied under the wrong
    name would really be in — rather than by patching the check.
    """
    from src.versioned.models import LaneMeta

    store.create_lane("wiki")
    with store.lane_session("wiki") as session:
        session.query(LaneMeta).one().kind = "law"
    store.dispose_all()

    with pytest.raises(ValueError, match="law"):
        store.create_schema("wiki")


def test_an_unknown_kind_is_refused_before_any_path_is_built():
    """A typo'd kind must not resolve to a path at all — the worst available failure
    on a package whose subject is one encrypted database per lane."""
    with pytest.raises(UnknownLaneError):
        store.lane_path("wikipedia")
    with pytest.raises(UnknownLaneError):
        store.lane_exists("")


def test_every_lane_owns_a_distinct_file_beside_the_corpus(tmp_path, monkeypatch):
    """Q1004's shape: ``corpus.db`` + ``wiki.db`` + ``osm.db`` + ``law.db``, distinct.

    Also asserts none of them IS the corpus file — a lane that resolved to the
    corpus path would put lane tables in ``corpus.db``, which is the exact bloat
    Q719 exists to prevent, arriving through a filename instead of a metadata.
    """
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    names = [store.lane_path(spec.kind).name for spec in all_lanes()]
    assert sorted(names) == ["law.db", "osm.db", "wiki.db"]
    assert len(set(names)) == len(names), "two lanes share a file"
    assert "open_omniscience.db" not in names
