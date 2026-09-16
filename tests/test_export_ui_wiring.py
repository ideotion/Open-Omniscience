"""The export dialog's wiring (S04-03; R4, R5, Q208–Q213, Q218, Q219).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Source-level properties only — what the RENDERER does is proved by running it
(`tests/export_panel_node_test.js`, driven below), and what the page LOOKS like is
proved by the click-through. What is left for a source test is the wiring a rendered
panel cannot show: that the folder is allocated ONCE and reaches both phases, that a
resume re-enters the folder it paused in, and that a failure to write the summary is
not reported as a failed backup.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]
_APP = app_js()
_HTML = read_static("index.html")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_export_panel_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "export_panel_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok" in proc.stdout


def test_the_dated_folder_is_allocated_once_and_reaches_both_phases():
    run = function_body(_APP, "_uxRun")
    assert "/api/backup/export-folder" in run, "the dated folder is never allocated"
    # The destination box is the PARENT; `dest` is the allocated folder, and it is what
    # both phase starts are given. A phase computing its own name would give two folders
    # whenever an export crosses a minute boundary.
    assert 'const parent = (document.getElementById("ux-dest").value || "").trim();' in run
    assert "JSON.stringify({ parent })" in run
    assert run.count("/api/backup/export-folder") == 1, "the folder is allocated more than once"
    assert "{ dest, passphrase: pass" in run, "the volumes phase does not get the folder"
    assert "JSON.stringify({ dest, categories: blobs })" in run, (
        "the large-data phase does not get the same folder"
    )


def test_a_resume_re_enters_the_folder_it_paused_in():
    """A resumable job that re-reads its inputs instead of carrying them is where the
    extra state quietly drops: re-reading the destination box would allocate a SECOND
    dated folder and orphan the volumes already written into the first."""
    assert "async function _uxRun(btn, resumeDir)" in _APP
    run = function_body(_APP, "_uxRun")
    assert "let dest = resumeDir || null;" in run
    assert "if (!dest) {" in run, "a resume must skip the allocation, not repeat it"
    resume = function_body(_APP, "_uxResume")
    assert '_uxRun(document.getElementById("ux-run"), _uxExportDir)' in resume
    # …and after a page reload the folder comes back from the job manager's own dest.
    recover = function_body(_APP, "_uxShowLastCompletedExportSummary")
    assert "_uxExportDir = shown.dest || null;" in recover


def test_the_verify_choice_is_re_supplied_on_every_start_including_a_resume():
    run = function_body(_APP, "_uxRun")
    assert 'document.getElementById("ux-verify")' in run
    assert "const verifyAfterWrite = !vBox || vBox.checked;" in run, (
        "a missing checkbox must fall back to ON, which is the ruled default"
    )
    assert "verify_after_write: verifyAfterWrite" in run


def test_the_verify_control_is_present_and_checked_by_default():
    assert 'id="ux-verify"' in _HTML
    box = _HTML[_HTML.index('id="ux-verify"') - 400 : _HTML.index('id="ux-verify"') + 120]
    assert "checked" in box, "Q218 = a rules the default ON"
    # It carries its cost on the hover (the layered-disclosure convention).
    assert "doubles the time an export takes" in box


def test_the_summary_is_written_last_and_a_failure_is_not_a_failed_backup():
    run = function_body(_APP, "_uxRun")
    i_corpus = run.index("/api/backup/v2/volumes/start")
    i_folder = run.index("/api/backup/folder/start")
    i_summary = run.index("/api/backup/export-summary")
    assert i_corpus < i_folder < i_summary, (
        "BACKUP_SUMMARY.md must be written after BOTH phases, so it can carry the "
        "verify verdict instead of promising one"
    )
    # The summary POST has its OWN try/catch: the bytes are on the drive and verified by
    # then, so a failure here degrades to a named note beside a completion line that
    # stands — never to "Backup failed".
    tail = run[i_summary - 400 :]
    assert "The backup is written, but its summary file could not be:" in tail


def test_the_panel_renders_the_SERVER_S_facts_and_computes_no_figure_of_its_own():
    """A panel that recomputed a number would be a second source of truth for it, and
    the gate row's whole ask is that the panel and the file agree."""
    panel = function_body(_APP, "_uxRenderExportPanel")
    for banned in ("reduce(", "+ 1", "Math.round(100", "/ total"):
        assert banned not in panel, f"the panel computes {banned!r} rather than reading a fact"
    assert "facts.tables" in panel and "facts.attribution" in panel


def test_the_panel_owns_its_own_translation_because_it_carries_DATA():
    """A table NAME is data. The string-matching i18n walker rendered `articles` as
    `\u0645\u0642\u0627\u0644\u0629` in the facts table on the Arabic click-through — a translated
    table name claims a table that does not exist. The panel is therefore opted out of
    the walker and translates itself, which also keeps the walker from caching an
    already-translated render as "the original English".
    """
    assert '<div id="ux-summary" data-i18n-dyn>' in _HTML, (
        "the completion panel must be opted out of the i18n DOM walker"
    )
    # Opting out means nothing redraws it on a language switch unless the panel does.
    assert 'document.addEventListener("oo:langchange"' in _APP
    panel = function_body(_APP, "_uxRenderExportPanel")
    assert "_uxExportFacts = facts;" in panel, (
        "the facts must be retained, or a language switch has nothing to redraw"
    )
    # …and the panel's own strings go through the keyed helpers, never raw English.
    assert 't("Encrypted volumes")' in panel and 't("Destination")' in panel


def test_member_sizes_come_from_the_inventory_and_the_categories_from_the_member():
    """Q219: the size shown before the export starts is the size the export writes."""
    inv = function_body(_APP, "_uxLoadInventory")
    assert "inv.members" in inv, "the dialog no longer reads the server's member list"
    assert 'data-cats="' in inv, "a member must carry the categories its tick exports"
    run = function_body(_APP, "_uxRun")
    assert "el.dataset.cats" in run, "the run must take the categories from the member row"
    for hardcoded in ('blobs.push("hf_models")', 'blobs.push("osm_regions")'):
        assert hardcoded not in run, (
            "a second copy of the member→category mapping is how the size shown beside "
            "the models tick came to count only one of its two stores"
        )
