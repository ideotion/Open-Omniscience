"""Row 280 (R696): the simple view's Climate list marks a dataset whose latest attempt failed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The twin of row 275 (#2236) for simple mode (R682): a failed attempt keeps the visible stale mark
and its date and reason one click away behind the ⓘ, beside the last success, which stays shown.
The behaviour is pinned by ``tests/simple_climate_node_test.js`` (real code, extracted); this file
runs it and pins the wiring and the wording shared with the full view.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]
_SIMPLE_JS = _ROOT / "src" / "static" / "simple" / "simple.js"
_FULL_JS = _ROOT / "src" / "static" / "app-climate.js"


def _words(src: str, name: str) -> set[str]:
    return set(re.findall(r'return t\("((?:[^"\\]|\\.)*)"\)', function_body(src, name)))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_simple_climate_rows_and_words_behave():
    proc = subprocess.run(["node", str(_ROOT / "tests" / "simple_climate_node_test.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_failed_dataset_is_marked_and_explained_beside_its_last_fetch():
    climate = function_body(_SIMPLE_JS.read_text(encoding="utf-8"), "Climate")
    assert "climateRows(" in climate
    assert 'x.failed ? html`<${Mark} kind="stale"/><${Details}' in climate, "the mark and the ⓘ come together"
    assert 't("Fetched {d}"' in climate, "the last success is still shown"
    assert "climateFailureWords(x.failed.reason)" in climate
    # The ⓘ is a sibling of the row's button, never nested inside it (a button in a button).
    assert climate.index("</button>\n          ${x.failed") > 0


def test_the_simple_view_names_each_failure_as_the_full_view_does():
    simple = _words(_SIMPLE_JS.read_text(encoding="utf-8"), "climateFailureWords")
    full = _words(_FULL_JS.read_text(encoding="utf-8"), "climateFailureReason")
    assert len(simple) == 15  # 14 tokens plus "other", the fallback
    assert simple == full, "the two views word a failure differently"
