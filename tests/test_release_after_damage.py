"""``release_idle_connection`` on a session whose connection the pool discarded under it (a damaged page), on a REAL encrypted store
(WAL / disk, 2026-10-16, the independent read of PR 1418).

The damage observer invalidates the connection under the session's transaction. The session cannot run another statement until it is rolled
back, and what ran on that connection went with it, so the release must ROLL BACK. The first version of the primitive read the dead
connection's ``info`` (which raises), took that for "cannot say" and declined: the next reader of the session, the all-diagnostics build's next
member, got ``PendingRollbackError``. The builders are ``tests/test_poisoned_connection.py``'s (a really overwritten page of an encrypted store).
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlcipher3")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.database import damage  # noqa: E402
from src.database.session import release_idle_connection  # noqa: E402
from tests import test_poisoned_connection as sqlcipher_tests  # noqa: E402


@pytest.fixture
def damaged(tmp_path):
    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    store = tmp_path / "corpus.db"
    sqlcipher_tests._build(store)
    eng, _opened = sqlcipher_tests._engine(store, observed=True, pool_size=2)
    yield eng
    eng.dispose()


def test_a_damaged_page_leaves_a_session_that_can_read_again_after_the_release(damaged):
    """Main answered True here (the rollback cleared the dead transaction); the first version of the primitive declined and the next read
    raised ``PendingRollbackError``. The next read is the load-bearing line."""
    session = Session(damaged)
    try:
        assert session.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        sqlcipher_tests._read_bad_range(session)
        assert release_idle_connection(session) is True
        assert session.execute(text("SELECT count(*) FROM small")).scalar_one() == 3, "the dead transaction was left in place"
    finally:
        session.close()


def test_the_all_diagnostics_build_still_reads_the_member_after_the_one_that_met_the_damage(damaged):
    import io
    import json
    import zipfile

    from src.api.diagnostics import bundle

    db = Session(damaged)

    def bad():
        db.execute(text("SELECT count(*) FROM small")).scalar()
        for lo in range(1, 901, 100):
            db.execute(text(sqlcipher_tests._BAD_RANGE), {"lo": lo, "hi": lo + 99}).fetchall()
        return {"bad": "not reached"}

    def healthy():
        return {"small": db.execute(text("SELECT count(*) FROM small")).scalar()}

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w") as z:
            results = bundle._write_all_diagnostics_zip([("bad.json", bad), ("healthy.json", healthy)], z, db=db, profile="full")
    finally:
        db.close()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        names = z.namelist()
        manifest = json.loads(z.read("manifest.json"))
        healthy_json = json.loads(z.read("healthy.json")) if "healthy.json" in names else None
    outcomes = {(r.get("file") or r.get("name")): r.get("outcome") for r in results}
    assert outcomes.get("healthy.json") == "ok", outcomes
    assert healthy_json == {"small": 3}
    assert manifest["run"]["read_release"]["released"] == 2 and manifest["run"]["read_release"]["declined"] == 0
