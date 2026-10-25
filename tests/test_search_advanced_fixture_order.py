"""The advanced-search country filter must not depend on which test booted the app first.

``small`` (tests/test_search_advanced_api.py) writes Source rows with country "fr". In a fresh process the shared default
store holds no country-form marker until the first TestClient boot stamps it alpha-3, so a fixture that wrote before that
stored "fr" and a query for FRA then bound "FRA" against it: the case failed alone and passed after any other `small` test.

The module-level state that hid it (the settings store's cached form) is process-wide, so the only honest regression is a
FRESH process that runs the one case by itself. Red without the fixture's marker-before-rows order, green with it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FILE = Path(__file__).with_name("test_search_advanced_api.py")


def test_the_country_filter_case_passes_alone_in_a_fresh_process() -> None:
    node = f"{_FILE}::test_every_q601_filter_is_reachable"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", node],
        capture_output=True, text=True, timeout=600, cwd=_FILE.parent.parent,
    )
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
