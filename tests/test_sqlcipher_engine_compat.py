"""A store made by one SQLCipher engine opens under the other, so lifting the sqlcipher3 ceiling cannot strand an existing store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``sqlcipher3`` is a wheel that bundles its own engine: 0.6.2 and 0.6.3 carry SQLCipher 4.12, 0.6.4 carries 4.19
(``configs/external_artifacts.yml``, ``sqlcipher3-driver``). Only one engine is installed in a process, so the two files in
``tests/fixtures/sqlcipher/`` are stores written ONCE by each engine through ``src.database.connect.connect`` (300 rows of
``notes``, an index, passphrase below); each CI run opens both under whichever engine it has, and the ``sqlcipher-engines`` job
runs this file on the floor and on the newest release (the other jobs run it on the engine they resolve). Measured when the ceiling was lifted (2026-10-13): both directions read every
row, ``quick_check`` is ``ok`` and ``cipher_integrity_check`` is empty.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from src.database.connect import connect

_FIXTURES = Path(__file__).parent / "fixtures" / "sqlcipher"
_KEY = "engine-compat-fixture"


@pytest.fixture(params=["made_by_sqlcipher_4_12.sqlcipher", "made_by_sqlcipher_4_19.sqlcipher"])
def store(request, tmp_path):
    dst = tmp_path / (request.param + ".db")
    shutil.copyfile(_FIXTURES / request.param, dst)
    return dst


def test_a_store_written_by_either_engine_reads_in_full_under_the_installed_one(store):
    con = connect(store, key=_KEY, check_same_thread=False)
    try:
        assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 300
        assert con.execute("SELECT body FROM notes WHERE id = 7").fetchone()[0] == "row 6 " + "x" * 6
        assert con.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert con.execute("PRAGMA cipher_integrity_check").fetchall() == []
    finally:
        con.close()


def test_the_installed_engine_writes_into_a_store_the_other_engine_made_and_reads_it_back(store):
    con = connect(store, key=_KEY, check_same_thread=False)
    try:
        con.execute("INSERT INTO notes(body) VALUES ('written by the installed engine')")
        con.commit()
    finally:
        con.close()
    con = connect(store, key=_KEY, check_same_thread=False)
    try:
        assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 301
        assert con.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert con.execute("PRAGMA cipher_integrity_check").fetchall() == []
    finally:
        con.close()



def test_the_ci_floor_leg_tells_the_tests_it_is_the_floor():
    """The floor-leg guards in ``test_poisoned_connection.py`` and ``test_database_verify_pages.py`` skip unless the job exports
    ``OO_EXPECT_SQLCIPHER_ENGINE``; this fails if the workflow stops exporting it, or the floor entry stops being named ``floor``."""
    ci = (Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci.split("  sqlcipher-engines:", 1)[1].split("\n  # ", 1)[0]
    assert re.search(r"-\s*\{engine: floor, spec: \"sqlcipher3==", job), "the floor matrix entry is not named `floor`"
    assert "OO_EXPECT_SQLCIPHER_ENGINE: ${{ matrix.engine }}" in job, "the job no longer exports the engine it runs"
