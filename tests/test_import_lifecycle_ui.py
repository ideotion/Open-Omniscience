"""The import dialog's ONE poll chain and its four stage rows (`S04-02`, S1/S3).

The BEHAVIOURAL half lives in ``tests/import_stages_node_test.js`` (the renderers are
extracted from the real module and executed, because every claim here is about what a
line SAYS). What is left for a source guard is the half a behavioural test cannot see:
that there is exactly ONE timer, that nothing else paints the bar, and that the retired
"Show details" block did not come back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    app_js,
    event_listener_bodies,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_APP = app_js()
_SRC = strip_comments(_APP)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_import_stages_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "import_stages_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  Q206: ONE chain, ONE timer, ONE bar owner
# --------------------------------------------------------------------------- #
def test_exactly_one_timer_schedules_the_import_dialogs_polling():
    """Two chains at two cadences (the 1200 ms verify poll and the 1000 ms queue
    renderer) both painted #ux-imp-bar, and they never collided by construction --
    only by nobody pressing Verify during a reattached run. Counting the SCHEDULER is
    what makes "one chain" checkable: a second `setTimeout` writing a second timer
    variable is the regression, and it is invisible to any behavioural test that drives
    one path at a time."""
    timers = sorted(set(re.findall(r"_ux\w*PollTimer\b", _SRC)))
    assert timers == ["_uxImPollTimer"], f"more than one import-dialog timer: {timers}"
    # every scheduling site assigns THE timer and calls THE tick
    sites = re.findall(r"_uxImPollTimer\s*=\s*setTimeout\(\s*(\w+)", _SRC)
    assert sites, "no scheduling site found -- the chain does not schedule itself"
    assert set(sites) == {"_uxImTick"}, f"the chain schedules something else: {set(sites)}"


def test_only_the_chain_paints_the_run_bar():
    """ONE bar owner (Q206). `#ux-imp-bar` is written by the queue renderer and by the
    verify tick, and BOTH are reached only from `_uxImTick` -- so the element has one
    owner even though two modes draw into it. A third reader would be a second owner."""
    owners = set()
    for fn in re.findall(r"\n    (?:async )?function (\w+)\(", _APP):
        body = function_body(_APP, fn)
        if 'getElementById("ux-imp-bar")' in body:
            owners.add(fn)
    assert owners <= {"_uxImRenderQueue", "_uxImTickVerify", "openUnifiedImport", "_uxImVerify"}, (
        f"an unexpected function paints the run bar: {sorted(owners)}"
    )
    # ...and neither renderer is reachable except through the chain (or the opener,
    # which only HIDES the bar on a fresh page).
    assert "_uxImRenderQueue(st)" in function_body(_APP, "_uxImTickQueue")
    assert "_uxImTickVerify(st, t)" in function_body(_APP, "_uxImTick")


def test_the_generic_job_poller_is_no_longer_reached_from_the_import_dialog():
    """`_uxPoll` is the EXPORT dialog's chain and stays; what must not come back is the
    import dialog reaching it, which is how the second cadence existed."""
    for fn in ("_uxImVerify", "_uxImRun", "_uxImReattach", "_uxImStop"):
        body = strip_comments(function_body(_APP, fn))
        assert "_uxPoll(" not in body, f"{fn} polls through the export dialog's chain"
        assert "_uxStartThenPoll(" not in body, f"{fn} still starts the second chain"


def test_the_verify_start_keeps_its_job_state_as_truth_guard():
    """A transport hiccup that loses the START response must not print a fatal over a
    job that is genuinely running. Moving the polling into the chain must not drop the
    guard that used to travel with it."""
    body = function_body(_APP, "_uxImStartGuarded")
    assert 'api(statusUrl)' in body
    assert '"running"' in body and '"paused"' in body
    assert '"done"' not in body, (
        "a stale 'done' must never mask a failed start as complete"
    )
    assert "_uxImStartGuarded(" in function_body(_APP, "_uxImVerify")


# --------------------------------------------------------------------------- #
#  Q206: rows patched in place
# --------------------------------------------------------------------------- #
def test_the_queue_rows_are_patched_not_rebuilt():
    """`rows.innerHTML = items.map(...)` replaced every row's subtree once a second,
    which is the blinking R2 calls a defect. The no-write property itself is pinned
    behaviourally in the node suite; this is the half that stops the wholesale
    assignment coming back."""
    body = strip_comments(function_body(_APP, "_uxImRenderQueue"))
    assert "rows.innerHTML" not in body, "the wholesale row rebuild is back"
    assert "_uxPatchRow(rows" in body and "_uxPruneRows(rows" in body


def test_the_details_block_and_its_renderer_are_gone():
    """Q207 = a, an ASSUMPTION at the sheet's default. Named here as well as in the PR
    body, because this is the guard a session reversing it would edit."""
    assert "_uxImDetails" not in _SRC
    assert "ux-imp-details" not in _SRC
    # ...and the MARKUP, not only the script. Re-adding the empty `<div id="ux-imp-details">`
    # to index.html passed this test unchanged until 2026-09-16 (the second of two survivors
    # in the S04-02 mutation matrix): a guard that watches one half of a two-file removal
    # reports the removal as held while the other half walks back in.
    assert "ux-imp-details" not in read_static("index.html")


# --------------------------------------------------------------------------- #
#  Q201 / Q204 / Q222: the endpoints the dialog reaches
# --------------------------------------------------------------------------- #
def test_stage_four_is_the_first_frontend_caller_of_the_resume_status():
    """The resume endpoints had ZERO frontend callers: the backlog was reported and
    then nobody could act on it from the app. Stage 4 is the caller."""
    assert "/api/backup/reindex-backlog/resume/status" in _SRC
    assert "reindex-backlog/resume/status" in function_body(_APP, "_uxImTickQueue")


def test_the_stage_four_read_is_paced_rather_than_polled_every_tick():
    """MEASURED, not guessed: the backlog read is linear in the pending article count
    (0.97 ms at 10k, 10.5 ms at 100k, 101.9 ms at 1M on a plaintext fixture), and the
    figure moves on the scale of minutes. One chain, two cadences."""
    assert "_UX_IM_RX_INTERVAL_MS" in _SRC
    body = strip_comments(function_body(_APP, "_uxImTickQueue"))
    assert "_uxImRxAt" in body and "_UX_IM_RX_INTERVAL_MS" in body


def test_the_import_history_lives_in_settings_and_is_loaded_there():
    """Q222 = b. A moved panel takes its loader with it -- markup in one subtab and a
    sync left behind on another is the recorded 'can't find your keyword triage
    button' defect."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    data_view = html[html.index('id="set-data"'):]
    data_view = data_view[: data_view.index('class="set-view"', 1)] if 'class="set-view"' in data_view[1:] else data_view
    assert 'id="imp-history"' in data_view, "the history list is not in Settings -> Data & backup"
    shell = strip_comments((_ROOT / "src" / "static" / "app-shell.js").read_text(encoding="utf-8"))
    cat = shell[shell.index('if (cat === "data")'):]
    cat = cat[: cat.index("\n")]
    assert "loadImportHistory()" in cat, "the data subtab must load the history it contains"


def test_the_task_manager_has_no_history_subtab():
    """Q222 = b answers invariant #20's standing "REMAINING: History" as SETTINGS. A
    History subtab appearing in the task-manager window would be a second home for one
    fact, which is how two surfaces come to disagree."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    tm = html[html.index('id="tm-subtabs"'):] if 'id="tm-subtabs"' in html else ""
    assert 'data-tab="history"' not in tm


def test_a_language_switch_re_renders_the_interpolated_import_surfaces():
    """The recorded frozen-locale bug class, found AGAIN here by measurement.

    The i18n DOM walker re-translates a text node whose content is still an exact key;
    an already-interpolated ``OOI18N.tf()`` string ("once every 3 backups") is not a key
    and stays in whatever locale first rendered it. Every surface this slice adds is
    built that way, and the poll chain that would repaint them STOPS at a terminal
    state -- so after a finished import nothing repaints them at all.

    The 2026-09-16 Chromium sweep screenshotted the dialog in fr, ar and zh and found
    the checkpoint sentence still English in all three: a caveat about durability,
    reaching an operator in a language they did not choose. Guarded here because the
    listener is one line to delete and its absence is invisible without a browser.
    """
    body = strip_comments(_APP)
    assert 'document.addEventListener("oo:langchange"' in body, (
        "the import dialog no longer re-renders its interpolated surfaces on a "
        "language switch; the checkpoint sentence freezes in the first locale"
    )
    # the listener must reach all four: the sentence, the quiet line, the rows, the
    # statements -- the sweep's first version checked a concatenation and one
    # translated half masked the three that had not.
    handlers = event_listener_bodies(body, "oo:langchange", span=2200)
    # THIS module's listener, chosen by what it touches -- never "the first one", which
    # is the assumption that reddened three existing guards when this one was added.
    own = [h for h in handlers if "ux-import" in h]
    assert len(own) == 1, f"expected exactly one import-dialog langchange listener, got {len(own)}"
    listener = own[0]
    for fn in ("_uxImCheckpointNote()", "_uxImLastLine()", "_uxImRenderStages(",
               "_uxImRenderStatements("):
        assert fn in listener, f"{fn} is not re-rendered on a language switch"
    # ...and it re-renders from the SAME facts, never a re-fetch of the queue.
    assert "_uxImLastStatus" in listener
    assert "import-queue/status" not in listener, (
        "a language switch must not poll the queue: it is a render, not a tick"
    )


# --------------------------------------------------------------------------- #
#  The adversarial pass, 2026-09-16: the chain's own re-entrancy
# --------------------------------------------------------------------------- #
def test_the_chain_is_one_chain_by_generation_not_by_luck():
    """Clearing `_uxImPollTimer` cancels a SCHEDULED tick. A tick that is mid-fetch has
    already nulled that variable, so it survived every clear -- and the `_uxImWatch !==
    subject` guard could not see it either, because re-watching the SAME subject (Stop
    re-arms the queue watch; so does reopening the dialog on a live run) leaves the
    subject identical. Two concurrent queue chains then both reach the terminal branch:
    two "Import complete." toasts and a twice-rebuilt summary -- the overlapping-messages
    defect this chain exists to have removed.
    """
    body = strip_comments(_APP)
    assert "let _uxImGen = 0;" in body, "the chain no longer has a generation"
    for fn in ("_uxImStopChain", "_uxImWatchQueue", "_uxImWatchVerify"):
        assert "_uxImGen++" in strip_comments(function_body(_APP, fn)), (
            f"{fn} must supersede any in-flight tick"
        )
    tick = strip_comments(function_body(_APP, "_uxImTick"))
    assert "const gen = _uxImGen;" in tick, "the tick must capture its generation"
    assert tick.count("_uxImGen !== gen") >= 2, (
        "every await in the tick must be followed by a generation check, not just one"
    )
    # ...and the queue tick re-guards after ITS OWN await, which is the one that could
    # call _uxImStopChain() and silently kill a live Verify whose promise never settles.
    qtick = strip_comments(function_body(_APP, "_uxImTickQueue"))
    assert "_uxImGen !== gen" in qtick, (
        "a stale queue tick resuming after the re-index read can stop whoever owns the "
        "chain; it must abandon itself instead"
    )


def test_reopening_the_dialog_never_shows_the_previous_runs_reindex_snapshot():
    """`_uxImRx` is module-level and outlives the dialog, and `_uxImReattach` renders
    BEFORE the first tick -- so a reopen presented a minutes-old backlog figure and an
    "analytics are complete" statement as current. Unknown-until-read is honest;
    stale-as-current is the rule this app does not break."""
    opener = strip_comments(function_body(_APP, "openUnifiedImport"))
    assert "_uxImRx = null" in opener and "_uxImRxAt = 0" in opener, (
        "the opener must clear the cached re-index read"
    )


def test_the_safety_statements_cover_every_item_that_reads_the_folder():
    """"The import files can be removed" is an unscoped claim in plain words, so its
    test has to be unscoped too. Filtering to corpus/legacy announced it the moment a
    fast corpus restore finished, while a `blobs` item from the SAME click -- dumps,
    maps, models, gigabytes -- was still copying out of that same folder."""
    body = strip_comments(function_body(_APP, "_uxImStatements"))
    assert "items.every(done)" in body, (
        "the statement must require every item in the run, not only the restores"
    )
    assert "restores.length > 0 && restores.every(done)" in body, (
        "...and still require a restore, so a blobs-only run never claims the corpus"
    )
