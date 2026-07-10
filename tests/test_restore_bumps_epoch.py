"""DB-7: a committed restore-merge bumps the corpus epoch (invalidates the rollup serves).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The corpus epoch is the coordination watermark that forces the disposable derived rollups
(``keyword_daily`` / ``source_coverage`` serves) to FULL-rebuild after a non-append
mutation. It was wired into re-index/prune but NOT the restore-merge — "the one residual
mutator" (P1.6 / A7). This drives the REAL commit path through the torture helper (which
runs ``run_restore(..., reindex_imported=False)`` — precisely the path that previously did
not bump) and asserts the epoch advances and the serve-gate change token reflects it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"


def _helper(data_dir: Path, *args: str) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=180,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _inspect_epoch(data_dir: Path) -> dict:
    """Read the corpus epoch AND the serve-gate change token (its first element IS the
    epoch) in the SAME OO_DATA_DIR — proving the rollup serves would see the bump."""
    code = (
        "import json;"
        "from src.database.session import session_scope;"
        "from src.analytics.corpus_epoch import get_corpus_epoch;"
        "from src.analytics.serve_gate import change_token;"
        "s=session_scope();db=s.__enter__();"
        "tok=change_token(db, articles=True, sources=True);"
        "print(json.dumps({'epoch': get_corpus_epoch(db), 'token_epoch': tok[0]}));"
        "s.__exit__(None,None,None)"
    )
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(_REPO), env=env, timeout=120)
    assert proc.returncode == 0, f"inspect failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_committed_restore_bumps_the_corpus_epoch(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-e7").get("artifact")
    _helper(a, "build", "A")

    # Fresh corpus A: ingest appends without bumping, so the epoch is still 0.
    before = _inspect_epoch(a)
    assert before["epoch"] == 0
    assert before["token_epoch"] == 0

    # First committed restore -> the explicit DB-7 bump lands (reindex_imported=False path).
    report = _helper(a, "merge", str(art), "--passphrase", "pw-e7", "--commit")["report"]
    assert report["committed"] is True
    assert report["corpus_epoch"] == 1, "restore-merge must bump the corpus epoch"

    after = _inspect_epoch(a)
    assert after["epoch"] == 1, "the bump is persisted in derived_meta"
    assert after["token_epoch"] == 1, "the serve-gate change token reflects the bump"

    # A second committed restore bumps again (monotonic; the serves rebuild each time).
    report2 = _helper(a, "merge", str(art), "--passphrase", "pw-e7", "--commit")["report"]
    assert report2["corpus_epoch"] == 2
    assert _inspect_epoch(a)["epoch"] == 2
