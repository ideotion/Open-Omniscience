"""A lane is a STORE, so every at-rest path has to know it exists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SHAPE OF DEFECT THIS FILE EXISTS FOR, because it is not one bug but a class.
Three separate places in this tree enumerate the app's databases as a LITERAL LIST:
``encrypt_all`` (make them ciphertext), ``quick_crypto_erase`` step 1 (destroy the
salt page), and ``GET /api/system/doctor`` (tell the operator the truth about all of
them). Each list was correct for as long as there were two databases. None of them is
anywhere near the code that adds a third, and none would fail a test when a third
arrives — the new store simply is not in the list, and everything stays green.

The consequences are not equivalent, and none is small:
  * out of ``encrypt_all``, a lane created while the store was plaintext stays
    plaintext FOREVER after the operator consents to encryption — every later open
    takes ``connect()``'s plaintext branch, which never consults the passphrase;
  * out of the crypto-erase's head-shred, a lane falls through to the full-overwrite
    path, whose own comment assumes "small side files" — against a store Q719 expects
    to reach 100 GB, that turns an instant guarantee into an hours-long one;
  * out of the doctor, the endpoint whose docstring is *"the honest answer to 'is my
    corpus encrypted?'"* answers while a plaintext store sits beside the one it
    describes. That is the fabricated security the non-negotiables forbid, arriving as
    an omission rather than as a claim.

So each is asserted here against a REAL file, and each assertion is written to fail
by name when a future lane kind is added to the registry and not to the path.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.database.connect import is_encrypted_file
from src.versioned import store
from src.versioned.lanes import all_lanes
from src.versioned.models import VersionedEntity

PASSPHRASE = "a passphrase long enough to pass the floor"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A data directory of this test's own, with every lane engine disposed on both edges."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    try:
        yield tmp_path
    finally:
        store.dispose_all()
        from src.database.connect import set_passphrase

        set_passphrase(None)


def _plaintext_corpus(path):
    con = sqlite3.connect(str(path / "open_omniscience.db"))
    con.execute("CREATE TABLE t(a)")
    con.commit()
    con.close()


# ------------------------------------------------------------------ encrypt_all


def test_ENCRYPTING_THE_STORE_encrypts_the_lanes_too(data_dir, monkeypatch):
    """The reported sequence, driven end to end against real files.

    A lane exists while the store is plaintext — an ordinary state, and this suite's own
    default. The operator then runs "Encrypt my store". Before the fix the corpus became
    ciphertext and the lane did not, with no surface anywhere that would have said so.
    """
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    _plaintext_corpus(data_dir)
    lane_path = store.create_lane("wiki")
    with store.lane_session("wiki") as session:
        session.add(VersionedEntity(external_id="oo:Written While Plaintext"))
    assert is_encrypted_file(lane_path) is False, "the fixture did not set up the state"

    from src.database.encrypt_tool import encrypt_all

    reports = encrypt_all(PASSPHRASE)

    assert is_encrypted_file(lane_path) is True, "the lane survived encryption in the clear"
    assert "lane:wiki" in reports, f"the lane is not in the report: {sorted(reports)}"
    # Every registered lane is named, so adding a kind without touching encrypt_all
    # fails HERE rather than in an operator's data directory.
    for spec in all_lanes():
        assert f"lane:{spec.kind}" in reports, f"{spec.kind} is not encrypted by encrypt_all"


def test_the_rows_SURVIVE_that_encryption_and_need_the_key_afterwards(data_dir, monkeypatch):
    """Encrypting must not be a quiet way of losing a store.

    The second half is the one that matters: after the swap, an unkeyed open must FAIL.
    A lane that is merely re-written and still openable without a key would pass the
    first assertion and none of the point.
    """
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    _plaintext_corpus(data_dir)
    store.create_lane("wiki")
    with store.lane_session("wiki") as session:
        session.add(VersionedEntity(external_id="oo:Survivor"))

    from src.database.connect import DatabaseLockedError, connect, set_passphrase
    from src.database.encrypt_tool import encrypt_all

    encrypt_all(PASSPHRASE)
    store.dispose_all()
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    set_passphrase(PASSPHRASE)

    with store.lane_session("wiki") as session:
        held = [r.external_id for r in session.query(VersionedEntity).all()]
    assert held == ["oo:Survivor"], held

    store.dispose_all()
    set_passphrase(None)
    with pytest.raises(DatabaseLockedError):
        connect(str(store.lane_path("wiki")))


# ----------------------------------------------------------------- crypto-erase


def test_CRYPTO_ERASE_destroys_each_lane_s_OWN_salt_page(data_dir, monkeypatch):
    """Head-only is the guarantee, and it is per FILE because the salt is per file.

    Asserted on the report's ``headers_destroyed`` rather than on the bytes, because the
    directory is removed by the time the call returns — and because that list is what an
    operator is shown. A lane missing from it is a lane that got the slow path.
    """
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", PASSPHRASE, raising=False)
    from src.database.connect import connect
    from src.safety.crypto_erase import quick_crypto_erase

    con = connect(str(data_dir / "open_omniscience.db"), key=PASSPHRASE, create_encrypted=True)
    con.execute("CREATE TABLE t(a)")
    con.close()
    store.create_lane("wiki")

    report = quick_crypto_erase(confirm=True, data_dir=data_dir)
    assert "wiki.db" in report["headers_destroyed"], report["headers_destroyed"]
    assert "open_omniscience.db" in report["headers_destroyed"]


def test_the_erase_CLOSES_the_lane_pool_before_it_touches_a_byte(data_dir, monkeypatch):
    """A pooled connection outlives the file it was opened on.

    Measured before the fix: a connection this process already held went on serving
    PRE-ERASE rows out of a file that had been randomised and unlinked, for as long as
    the process lived — and this feature's stated purpose is an imminent seizure of that
    machine. Asserted through the module's own engine map, because "the pool is closed"
    is a fact about this process rather than about the disk.
    """
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    _plaintext_corpus(data_dir)
    store.create_lane("wiki")
    with store.lane_session("wiki") as session:
        session.add(VersionedEntity(external_id="oo:Sensitive"))
    assert store._engines, "the fixture did not leave a live engine to dispose"

    from src.safety.crypto_erase import quick_crypto_erase

    quick_crypto_erase(confirm=True, data_dir=data_dir)
    assert store._engines == {}, "a lane engine survived the erase holding a key and a handle"


# ----------------------------------------------------------------- the doctor


def test_the_DOCTOR_reports_every_lane_s_real_at_rest_state(data_dir, monkeypatch):
    """The endpoint that answers "is my data encrypted?" must not answer about a subset.

    An absent lane reports ``absent`` — the honest state for one the operator has never
    opened, and a different fact from ``plaintext``.
    """
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", PASSPHRASE, raising=False)
    from src.api.unlock import doctor

    store.create_lane("wiki")
    out = doctor()
    assert "lanes" in out, "the doctor does not mention lanes at all"
    assert set(out["lanes"]) == {spec.kind for spec in all_lanes()}, out["lanes"]
    assert out["lanes"]["wiki"]["state"] == "encrypted", out["lanes"]["wiki"]
    assert out["lanes"]["law"]["state"] == "absent", out["lanes"]["law"]


def test_the_doctor_calls_a_PLAINTEXT_lane_plaintext(data_dir, monkeypatch):
    """The direction that matters: the report must be able to say the bad news.

    Anti-vacuity for the test above — a doctor that answered "encrypted" for everything
    would satisfy it and be exactly the fabricated security this row exists against.
    """
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.api.unlock import doctor

    store.create_lane("wiki")
    out = doctor()
    assert out["lanes"]["wiki"]["state"] == "plaintext", out["lanes"]["wiki"]
