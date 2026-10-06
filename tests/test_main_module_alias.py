"""``python -m src.api.main`` must not import the app twice (a 500 on the Mindmap graph).

Booted as ``__main__``, ``src/api/main.py`` is a different module object from ``src.api.main``,
so ``src/api/insights.py``'s runtime ``from src.api.main import _query_articles`` executed the file
a SECOND time and raised the Prometheus ``DuplicateTimeseries``; ``--ephemeral`` relaunches itself
that way, so it shipped the fault (found 2026-09-17, recorded again by the 2026-10-06 CSP sweep).
The ``__main__`` block now registers the running module under its real name.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = r"""
import runpy, sys
sys.argv = ["src/api/main.py", "help"]          # the cheap subcommand: prints usage, serves nothing
runpy.run_path("src/api/main.py", run_name="__main__")
from src.api.main import _query_articles        # what insights.py does at request time
assert callable(_query_articles)
print("ONE-MODULE-OK")
"""


def test_the_module_run_as_main_is_the_one_later_imports_find():
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
        env={"PATH": "", "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1", "OO_AUTOSEED": "0", "PYTHONPATH": str(ROOT)},
    )
    assert "ONE-MODULE-OK" in out.stdout, out.stdout[-800:] + out.stderr[-1500:]
