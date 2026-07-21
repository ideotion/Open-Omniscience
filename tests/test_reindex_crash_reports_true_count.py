"""Code-review fix: a genuine post-swap re-index CRASH must report the TRUE
imported-article count as "failed", never 0.

Found in review: when ``reindex_imported_articles`` raises (the whole re-index
batch fails, e.g. a DB lock/OOM), ``run_restore``'s exception handler used to set
``report["reindexed"] = {"reindexed": 0, "failed": 0, "skipped": "see server log"}``.
That object is truthy, so the UI's ``if (sm.reindexed) unindexed += sm.reindexed.failed
|| 0;`` branch fired and added 0 -- silently reporting "0 articles awaiting indexing"
even though NONE of the imported articles were re-indexed. This is exactly the
fabricated/omitted signal the surrounding comments say must never happen ("the true
count of never-reindexed imported articles is knowable, never guessed").

Drives the REAL commit path through the torture helper (its own OO_DATA_DIR), with
the re-index step forced to crash (``--crash-reindex``) after a real ``--reindex``
run, and asserts ``failed`` equals the plan's true imported-article count.
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
    env = dict(
        os.environ,
        OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1",
        PYTHONPATH=str(_REPO),
    )
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=180,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_reindex_crash_reports_true_failed_count_not_zero(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak"
    assert _helper(b, "build", "B", "--artifact", str(art)).get("artifact")
    _helper(a, "build", "A")

    report = _helper(
        a, "merge", str(art), "--commit", "--reindex", "--crash-reindex",
    )["report"]

    assert report["committed"] is True
    imported = report["plan"]["articles"]["new"]
    assert imported > 0, "fixture must actually import new articles to be meaningful"

    reindexed = report["reindexed"]
    assert reindexed["reindexed"] == 0, "the crash must not fabricate a reindexed count"
    assert reindexed["failed"] == imported, (
        "a whole-batch re-index crash must report the TRUE imported-article count as "
        f"failed (got {reindexed['failed']!r}, expected {imported!r}) -- reporting 0 here "
        "reads as 'nothing needed re-indexing', which is fabricated"
    )
