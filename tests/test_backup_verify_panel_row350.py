"""Row 350: the backup verify panel follows a live language switch, and says its counts in whole frames.

``_uxRenderVerify`` builds every line with t()/tf() at render time. The i18n walker caches the first
text it sees as "the English" and never re-keys translated output, so after a switch the panel stayed
in the language it was drawn in. It now draws a panel of its own, marked ``data-i18n-dyn``, keeps the report on it, and
the one ``oo:langchange`` listener repaints it from that report (no fetch). Its two fragment lines --
"Parity: N · can still lose K" and "Corrupt/missing: names" -- are whole keyed frames, with the names
isolated as data.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import event_listener_bodies, function_body, read_static

ROOT = Path(__file__).resolve().parent.parent
FRAMES = (
    "Corrupt or missing volumes: {names}",
    "Parity volumes: {n}",
    "Up to {n} more volumes can be lost and rebuilt from parity.",
    "No more volumes can be lost: any further loss cannot be rebuilt from parity.",
)
GONE = ("Corrupt/missing:", "Parity:", "can still lose")


def test_the_langchange_listener_repaints_the_verify_panel():
    bodies = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("_uxVerifyRepaint()" in b for b in bodies)


def test_the_panel_owns_its_words_and_keeps_its_report():
    body = function_body(read_static("app-backup.js"), "_uxRenderVerify")
    assert '<div data-oo-verify="" data-i18n-dyn="">' in body
    assert "panel._ooVerifyRep = rep" in body
    assert "host._ooVerifyRep" not in body
    for old in GONE:
        assert f't("{old}")' not in body


def test_frames_are_keyed_in_all_twelve_and_the_fragments_are_gone():
    files = sorted((ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for frame in FRAMES:
            assert d.get(frame), f"{f.name} lacks {frame}"
        for old in GONE:
            assert old not in d, f"{f.name} still carries {old!r}"


def test_the_panel_node_suite():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(ROOT / "tests" / "backup_verify_panel_row350_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_verify_forgets_the_import_summary_it_replaces():
    # The import half's oo:langchange listener redraws its last summary into the shared host whenever
    # it holds one; a verify that took the host over must drop it, or a switch paints the old import
    # summary over the verify result.
    body = function_body(read_static("app-backup.js"), "_uxImVerify")
    assert 'summary.innerHTML = ""; _uxImSummaryArgs = null;' in body
