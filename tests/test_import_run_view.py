"""The import run view (row 440): hero card, Simple / Detailed views, top-bar pill.

The behavioural half is ``tests/import_run_view_node_test.js`` (the renderers are
extracted from the shipped module and executed). This file runs it, and pins the
structure the node suite cannot see: which surfaces the Simple view may fold, that the
pill and the switch are keyboard reachable with names, and that the pill is painted from
the dialog's existing chain rather than a poll of its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]
_HTML = read_static("index.html")
_CSS = read_static("app.css")
_SRC = strip_comments(app_js())


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_import_run_view_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "import_run_view_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def _dialog() -> str:
    return _HTML.split('<dialog id="ux-import"', 1)[1].split("</dialog>", 1)[0]


def test_simple_view_folds_only_repetition_and_method() -> None:
    """Simple folds `.imp-detail` and the per-backup rows that carry no warning. Every
    caveat surface (the run note, the stage rows, the statements, the checkpoint caveat)
    must stay outside both."""
    dlg = _dialog()
    folded = re.findall(r'<[^>]*class="[^"]*\bimp-detail\b[^"]*"[^>]*>', dlg)
    assert folded, "the Detailed-only surfaces are marked"
    for tag in folded:
        for caveat in ("ux-imp-queue-note", "ux-imp-stages", "ux-imp-statements", "ux-imp-checkpoint",
                       "ux-imp-pass", "ux-imp-trust", "ux-imp-hero"):
            assert caveat not in tag, f"{caveat} must not be Detailed-only"
    rules = re.findall(r'#ux-imp-queue\[data-view="simple"\][^{]*\{[^}]*\}', _CSS)
    assert len(rules) == 2, rules
    assert any(".imp-detail" in r for r in rules)
    assert any(":not(:has(.imp-row-alert))" in r for r in rules), "rows with a warning stay in Simple"
    body = function_body(_SRC, "_uxImRenderQueue")
    assert "imp-row-alert" in body and 'it.state === "staged"' in body and "err ||" in body


def test_the_switch_and_the_pill_are_buttons_with_names() -> None:
    dlg = _dialog()
    for v in ("simple", "detailed"):
        tag = re.search(rf'<button[^>]*id="ux-imp-view-{v}"[^>]*>', dlg)
        assert tag and "aria-pressed=" in tag.group(0) and 'type="button"' in tag.group(0)
    assert 'role="group" aria-label="How much of the import to show"' in dlg
    pill = re.search(r'<button[^>]*id="imp-pill"[^>]*>', _HTML)
    assert pill and "aria-label=" in pill.group(0) and "title=" in pill.group(0)
    assert 'data-on-click="ooOpenImportFromPill()"' in pill.group(0)


def test_the_pill_rides_the_dialogs_chain() -> None:
    """No poll of its own: the queue renderer and the failed-read branch paint it, and the
    one start-up read hands a running run to the same chain."""
    assert "_ooImportPillPaint(st)" in function_body(_SRC, "_uxImRenderQueue")
    assert "_ooImportPillPaint(null, true)" in function_body(_SRC, "_uxImTick")
    boot = function_body(_SRC, "ooImportPillBoot")
    assert "_uxImWatchQueue()" in boot and "setInterval" not in boot and "setTimeout" not in boot
    assert "ooImportPillBoot()" in read_static("app-boot.js")
