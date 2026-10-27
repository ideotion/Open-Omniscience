"""The performance report's ``keyword_mentions`` count obeys the member deadline (S3 of WAL's deadline-bound sweep, R309).

A bare ``SELECT COUNT(*) FROM table`` is one VM opcode in SQLite, so the progress handler a ``statement_deadline`` arms is never asked
while it runs and the deadline cannot stop it (same as #1543). ``COUNT(1)`` runs about 3 opcodes a row, so on 30,000 rows the handler
(asked every 20,000 opcodes) is asked and the typed ``StatementTimeout`` comes. The test bounds the statement itself: the report runs inside
the real ``statement_deadline(session, seconds=1e-6)`` on a plain store built from the app's schema with 40,000 mention rows. A control
issues the bare ``COUNT(*)`` under the same deadline and must return whole, so the harness tells the two spellings apart (respelling the
report's statement back to ``COUNT(*)`` turns the first test red). Run in a subprocess: the app's engine is bound to ``DATABASE_URL`` at import.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARNESS = textwrap.dedent(
    """
    import os, sqlite3, sys
    d = sys.argv[3]
    os.environ.update(OO_DATA_DIR=d, OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1", DATABASE_URL=f"sqlite:///{d}/s.db")
    sys.path.insert(0, sys.argv[2])
    from sqlalchemy import text
    from src.database.maintenance import StatementTimeout, statement_deadline
    from src.database.models import Base
    from src.database.session import SessionLocal, engine
    Base.metadata.create_all(engine)
    raw = sqlite3.connect(f"{d}/s.db")
    raw.executemany(
        "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on, created_at) VALUES (?,?,?,?,?)",
        ((1, i, 1, "2026-01-01", "2026-01-01 00:00:00") for i in range(40000)),
    )
    raw.commit(); raw.close()
    db = SessionLocal()
    mode = sys.argv[1]
    try:
        with statement_deadline(db, seconds=1e-6):
            if mode == "report":
                from src.api.diagnostics.performance import performance_report
                performance_report(selftest=False, db=db)
            else:
                print("COUNT", db.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar())
        print("RETURNED")
    except StatementTimeout:
        print("TIMEOUT")
    """
)


def _run(mode: str, store_dir: Path) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _HARNESS, mode, str(ROOT), str(store_dir)], capture_output=True, text=True, timeout=300, cwd=ROOT, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip().splitlines()[-1]


def test_the_report_count_is_stopped_by_the_deadline(tmp_path: Path) -> None:
    assert _run("report", tmp_path) == "TIMEOUT"


def test_a_bare_count_star_is_not_stopped_by_the_same_deadline(tmp_path: Path) -> None:
    assert _run("bare", tmp_path) == "RETURNED"
