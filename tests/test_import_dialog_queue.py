"""The import dialog shows a RUN, not one anonymous bar.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field remarks 2026-07-29 remark 2. Six backups produced one shared progress bar with
no per-item identity, no true rate, no pause and no stop. The rendering could not have
been fixed on its own: the sequencing lived in the browser, so there was nothing to
render per item and nothing to stop. These pin the dialog against the SERVER-side run
it now mirrors.

BROWSER-UNVERIFIED (fork-3): node --check plus these source guards, no click-through.
"""

from __future__ import annotations

from pathlib import Path
from tests.js_source_helper import function_body

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """One function's own body, brace-matched (tests.js_source_helper)."""
    return function_body(_APP, name)


# --------------------------------------------------------------------------- #
#  the run replaced the client-side loop
# --------------------------------------------------------------------------- #
def test_the_client_side_sequencing_loop_is_gone():
    """THE structural defect. _uxImRun used to `for (const c of corpus)` and await each
    restore in turn, which is why a reload killed the import and Stop could not exist."""
    body = _fn("_uxImRun")
    assert "/api/backup/import-queue/start" in body
    for gone in ("/api/backup/v2/volumes/restore", "/api/newsletters/import-folder"):
        assert gone not in body, (
            f"{gone} is still called directly from the dialog — the server must own the run"
        )


def test_every_selected_item_is_queued_with_its_own_identity():
    body = _fn("_uxImRun")
    for kind in ("corpus", "legacy", "blobs", "newsletters"):
        assert f'kind: "{kind}"' in body, kind
    assert "_uxImLabel(" in body, "a backup set's own folder name is its identity"


def test_the_dialog_reattaches_to_a_run_after_a_reload():
    """Ruling item 16. The state lives on the server precisely so this is possible."""
    assert "_uxImReattach" in _APP
    assert "_uxImReattach()" in _fn("openUnifiedImport")


# --------------------------------------------------------------------------- #
#  per-item rendering
# --------------------------------------------------------------------------- #
def test_the_markup_has_a_per_item_run_panel_and_a_details_disclosure():
    for needle in (
        'id="ux-imp-queue"', 'id="ux-imp-queue-rows"', 'id="ux-imp-details"',
        'id="ux-imp-stop"',
    ):
        assert needle in _HTML, needle


def test_each_row_carries_its_state_and_a_real_elapsed_time():
    body = _fn("_uxImRenderQueue")
    assert "_UX_IM_STATE_LABEL" in body
    assert "_uxImDur(it.elapsed_s)" in body, "measured, never estimated"
    assert "it.error" in body, "a failed item must say why, in place"


def test_the_run_states_that_collection_is_paused():
    """Ruling item 12: the user is told, not left to infer it."""
    assert "collection_paused" in _fn("_uxImRenderQueue")


def test_an_interrupted_run_says_it_cannot_resume():
    """A run killed with the process cannot resume — the passphrase was never stored.
    Showing it as merely 'stopped' would leave the user waiting for a restart that is
    never coming."""
    body = _fn("_uxImRenderQueue")
    assert "interrupted" in body
    assert "cannot resume" in body.lower()


# --------------------------------------------------------------------------- #
#  the rate is the CURRENT PHASE's own unit (ruling item 14)
# --------------------------------------------------------------------------- #
def test_the_live_line_uses_the_phases_own_unit_never_a_whole_run_percentage():
    # The facts moved into _uxImPhaseBits when the header needed them without the
    # per-row separator; _uxImLive is now the wrapper. The CLAIM is unchanged and is
    # asserted where the units actually live, plus on the wrapper, so neither half can
    # acquire a whole-run percentage.
    bits = _fn("_uxImPhaseBits")
    assert "merge_steps" in bits and "reindex_total" in bits
    assert "phase_index" in bits and "phase_total" in bits
    for body in (bits, _fn("_uxImLive")):
        assert "%" not in body, (
            "the items are different kinds of work over different units, so a whole-run "
            "percentage would be a fabricated number"
        )


# --------------------------------------------------------------------------- #
#  Stop says which of the two things it does (ruling item 15)
# --------------------------------------------------------------------------- #
def test_stop_is_wired_to_the_run_not_to_one_job():
    body = _fn("_uxImStop")
    assert "/api/backup/import-queue/stop" in body


def test_the_stop_confirmation_never_implies_an_undo_that_does_not_exist():
    """The honest half. Pre-swap the abort is complete; post-swap the merge stands and
    only the remaining work stops. A confirmation that said 'cancel the import' would
    be a promise the engine cannot keep."""
    body = _fn("_uxImStop")
    low = body.lower()
    assert "no undo" in low or "there is no undo" in low
    assert "corpus is untouched" in low, "the pre-swap half must be stated too"
