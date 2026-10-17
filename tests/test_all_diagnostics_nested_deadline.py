"""The all-diagnostics zip job keeps a member's own deadline after the member opens a nested one.

A DB-touching member runs inline under ``statement_deadline(db, deadline_used)`` (bundle.py, the member loop). Several
members call helpers that open a deadline of their own; on the old teardown the inner block's exit disarmed the
connection, so the member's deadline could not stop the next long statement and the member ran to the end of it.
This drives the REAL zip job (``_write_all_diagnostics_zip``) on a real pooled engine, not ``statement_deadline`` alone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import time
import zipfile

from sqlalchemy.orm import sessionmaker

from src.api import diagnostics as d
from src.api.diagnostics import bundle as _diag_bundle
from src.database.maintenance import statement_deadline
from tests.test_statement_deadline_pool import _LONG, _SHORT, _engine


def test_a_member_that_opens_a_nested_deadline_is_still_stopped_by_its_own(tmp_path, monkeypatch):
    """MUTATION TARGET: the restore of the enclosing handler in ``statement_deadline``'s teardown."""
    monkeypatch.setattr(_diag_bundle, "_all_diag_db_member_deadline_s", lambda: 0.3)
    s = sessionmaker(bind=_engine(tmp_path))()
    db = s

    def _nesting_member():
        db.execute(_SHORT)  # the connection is held, in a transaction
        with statement_deadline(db, 60.0):  # what a helper inside a member does
            db.execute(_SHORT)
        time.sleep(0.35)  # the member's own 0.3 s has elapsed
        db.execute(_LONG)  # only the restored outer handler can stop this one
        return {"ran_to_the_end": True}

    assert d._member_touches_db(_nesting_member) is True
    members = [("nesting.json", _nesting_member), ("after.json", lambda: {"ok": 1})]
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w") as z:
            results = d._write_all_diagnostics_zip(members, z, db=db)
            names = set(z.namelist())
    finally:
        s.rollback()
        s.close()
    by_file = {r["file"]: r for r in results}
    assert by_file["nesting.json"]["outcome"] == "skipped-deadline"
    assert "nesting.json.skipped-deadline.txt" in names
    assert "nesting.json" not in names, "a member the deadline stopped leaves no payload"
    assert by_file["after.json"]["outcome"] == "ok", "one deadline stop must not abort the bundle"
