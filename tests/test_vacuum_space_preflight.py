"""VACUUM needs room for a second copy of the database, and nothing checked.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DB-10 §2 carry-over, recorded in ``docs/ledger/OPEN_QUEUE.md``: the frontend's
``_confirmVacuum`` discloses an estimated DURATION and confirms, but
``POST /api/database/vacuum`` would start a full rebuild on a corpus of any size
with no disk check at all. SQLite's VACUUM writes a COMPLETE second copy of the
file and only then swaps it in, so the peak requirement is about twice the
current size — and running out of space mid-rebuild is the worst possible moment
to discover it.

THREE THINGS THIS PINS, each of which is a way the check could be wrong rather
than absent.

1. BOTH VOLUMES ARE MEASURED. SQLite writes the rebuild to a temporary file in a
   directory it chooses (``SQLITE_TMPDIR`` / ``TMPDIR`` / ``/var/tmp`` / ``/tmp``
   on unix), which need not be the database's own volume. Checking only the
   database's volume would pass a machine whose /tmp is a small tmpfs.

2. AN UNREADABLE FIGURE IS NOT A REFUSAL. ``shutil.disk_usage`` can raise, and a
   fabricated 0 would manufacture a refusal out of an unreadable ``statvfs``.
   ``sufficient`` is then ``None`` and the vacuum PROCEEDS, with the response
   saying it was not preflighted — the same three-state discipline
   ``weights_pin`` uses when it omits a comparison nothing compared, and the
   same one ``vllm_lifecycle._free_disk_bytes`` already draws.

3. THE REFUSAL HAS ITS OWN STATUS. 507 for "the disk cannot hold this", kept
   distinct from the existing 409 "something else is writing". Collapsing two
   different refusals into one status is how an operator comes to fix the wrong
   thing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from src.database.maintenance import (
    VACUUM_HEADROOM,
    VacuumSpaceError,
    vacuum_database,
    vacuum_preflight,
)


@pytest.fixture
def sqlite_engine(tmp_path):
    from sqlalchemy import create_engine, text

    db = tmp_path / "store.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)"))
        conn.execute(text("INSERT INTO t (blob) SELECT hex(randomblob(400))"))
    return engine


def test_the_preflight_measures_twice_the_file_on_both_volumes(sqlite_engine) -> None:
    report = vacuum_preflight(sqlite_engine)
    assert report["checked"] is True
    assert report["sufficient"] is True, report
    assert report["db_bytes"] > 0
    assert report["needed_bytes"] == int(report["db_bytes"] * VACUUM_HEADROOM)
    assert set(report["free_bytes"]) == {"database", "temp"}, (
        "the rebuild can land on either volume, so both have to be measured"
    )


def test_a_measured_shortfall_refuses_before_taking_the_write_lock(
    sqlite_engine, monkeypatch
) -> None:
    """And it refuses BEFORE the exclusive lock, so nobody loses their writer to a
    vacuum that was never going to fit."""
    real = shutil.disk_usage

    def _tiny(path):
        got = real(path)
        return type(got)(got.total, got.used, 1)  # one byte free

    monkeypatch.setattr(shutil, "disk_usage", _tiny)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is False
    assert report["short_on"], report
    assert "needs about" in report["detail"]

    took_the_lock = []
    import src.database.writer as writer

    real_lock = writer.write_lock

    def _watched(*a, **k):
        took_the_lock.append(True)
        return real_lock(*a, **k)

    monkeypatch.setattr(writer, "write_lock", _watched)
    with pytest.raises(VacuumSpaceError) as excinfo:
        vacuum_database(sqlite_engine)
    assert excinfo.value.report["sufficient"] is False
    assert not took_the_lock, (
        "the refusal must come before the exclusive write lock; refusing after it "
        "would stall every other writer for a vacuum that never ran"
    )


def test_only_the_short_volume_needs_to_be_short(sqlite_engine, monkeypatch) -> None:
    """A roomy database volume must not excuse a full /tmp -- that is precisely
    the machine the one-volume version of this check would have waved through."""
    import tempfile

    real = shutil.disk_usage
    tmpdir = os.path.realpath(tempfile.gettempdir())

    def _tmp_is_full(path):
        got = real(path)
        if os.path.realpath(str(path)) == tmpdir:
            return type(got)(got.total, got.used, 1)
        return got

    monkeypatch.setattr(shutil, "disk_usage", _tmp_is_full)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is False, report
    assert report["short_on"] == ["temp"], report


def test_an_unreadable_volume_is_not_a_refusal(sqlite_engine, monkeypatch) -> None:
    """A fabricated 0 would manufacture a refusal out of an unreadable statvfs."""
    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is None, report
    assert report["checked"] is False
    assert "not preflighted" in report["detail"]
    # And the vacuum still runs -- being unable to measure is not being unable to act.
    out = vacuum_database(sqlite_engine)
    assert out["supported"] is True
    assert out["preflight"]["sufficient"] is None


def test_a_successful_vacuum_carries_its_preflight(sqlite_engine) -> None:
    """So an operator can see the check happened -- and, when it could not, that
    it did not."""
    out = vacuum_database(sqlite_engine)
    assert out["supported"] is True
    assert out["preflight"]["sufficient"] is True
    assert "twice the file size" in out["method"]


def test_the_endpoint_maps_the_shortfall_to_its_own_status() -> None:
    """507, not the 409 that already means 'something else is writing'."""
    src = (Path(__file__).resolve().parents[1] / "src" / "api" / "database.py").read_text(
        encoding="utf-8"
    )
    block = src[src.index("def vacuum()"):]
    block = block[: block.index("served_cache.invalidate()")]
    assert "VacuumSpaceError" in block, "the endpoint must handle the space refusal"
    assert "status_code=507" in block, (
        "a disk shortfall needs its own status; 409 already means the store is busy"
    )
    assert "status_code=409" in block, "the busy refusal must not have been replaced"


def test_a_volume_holding_the_file_but_not_its_copy_is_still_refused(
    sqlite_engine, monkeypatch
) -> None:
    """The headroom is the load-bearing number, and asserting
    ``needed == db_bytes * VACUUM_HEADROOM`` pins nothing -- it is true for any
    value of the constant, including 1.0, which is the value that says "the
    rebuild needs no room of its own". Dropping the constant to 1.0 passed every
    other test in this file.

    So the claim is made behaviourally: a volume with room for the FILE but not
    for the SECOND COPY must be refused. That is exactly the disk on which the
    old, unchecked VACUUM would have failed halfway through.
    """
    real = shutil.disk_usage
    db_bytes = vacuum_preflight(sqlite_engine)["db_bytes"]

    def _just_over_one_copy(path):
        got = real(path)
        return type(got)(got.total, got.used, int(db_bytes * 1.2))

    monkeypatch.setattr(shutil, "disk_usage", _just_over_one_copy)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is False, (
        "1.2x the file is room for the file and not for the copy VACUUM writes "
        f"beside it; the preflight accepted it: {report}"
    )
    assert VACUUM_HEADROOM >= 2.0, (
        "VACUUM rebuilds into a complete second copy before swapping, so 2.0x is "
        f"the floor of the requirement, not a margin on top of it (found {VACUUM_HEADROOM})"
    )


def test_ample_space_is_still_accepted(sqlite_engine, monkeypatch) -> None:
    """The other half of the pair: a headroom raised until nothing ever passes
    would satisfy the refusal test above while breaking every real vacuum."""
    real = shutil.disk_usage
    db_bytes = vacuum_preflight(sqlite_engine)["db_bytes"]

    def _three_copies(path):
        got = real(path)
        return type(got)(got.total, got.used, int(db_bytes * 3) + 4096)

    monkeypatch.setattr(shutil, "disk_usage", _three_copies)
    assert vacuum_preflight(sqlite_engine)["sufficient"] is True
