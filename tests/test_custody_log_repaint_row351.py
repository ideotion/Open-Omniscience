"""Row 351: the custody log table follows a live language switch.

``viewChain`` drew its headers, Action and Time cells with t() into an unmarked table. The i18n
walker caches the first text it sees as "the English" and never re-keys translated output, so the
cells stayed in the language they were drawn in (and the English headers were translated only by
the walker). The table is now drawn by ``custodyEntriesPaint``, marked ``data-i18n-dyn``, keeps the
entries it shows, and the one ``oo:langchange`` listener repaints it from them (no fetch).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import event_listener_bodies, function_body, read_static

ROOT = Path(__file__).resolve().parent.parent
HEADERS = ("Action", "Actor", "Time", "Signature")


def test_the_langchange_listener_repaints_the_custody_log():
    bodies = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("custodyEntriesRepaint()" in b for b in bodies)


def test_the_table_owns_its_words_and_keeps_its_entries():
    src = read_static("app-ai-tools.js")
    paint = function_body(src, "custodyEntriesPaint")
    assert 'setAttribute("data-i18n-dyn"' in paint
    assert "_ooCustEntries = entries" in paint
    for h in HEADERS:
        assert f'tr("{h}")' in paint
    view = function_body(src, "viewChain")
    assert "custodyEntriesPaint(" in view
    assert "<th>Action</th>" not in view
    assert "_ooCustEntries = null" in view
    assert "Array.isArray(d.entries) ?" not in view


def test_the_headers_are_keyed_in_all_twelve():
    files = sorted((ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for h in HEADERS:
            assert d.get(h), f"{f.name} lacks {h}"


def test_the_custody_log_node_suite():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(ROOT / "tests" / "custody_log_repaint_row351_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
