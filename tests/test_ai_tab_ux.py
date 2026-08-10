"""The AI tab is for a journalist, not a console operator.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer review 2026-08-09, verbatim: "Replace small tick boxes for model download
with big buttons. Replace the bla bla about default model with a drop down menu with
only the readily/downloaded models, and make the UI automatically remove useless
elements of the UI such as a button to download a model which is already downloaded ...
Let's move the entire Behaviour & prompts section to an AI section in the advanced
subtab."

Every assertion here runs over a PROPERLY SLICED function body (``js_source_helper``),
never a whole-file substring: the ledger records three separate guards that passed for
years while testing nothing, all of them whole-file matches against a needle that
occurred somewhere else entirely.
"""

from __future__ import annotations

from tests.js_source_helper import (
    assert_absent,
    function_body,
    object_literal,
    read_static,
    strip_comments,
)

APP = read_static("app.js")
HTML = read_static("index.html")


# --------------------------------------------------------------------------- #
#  one big button per model, and it goes away when it has nothing left to do
# --------------------------------------------------------------------------- #
def test_the_catalogue_offers_one_button_per_model_not_tickboxes():
    body = function_body(APP, "loadModelCatalog")
    assert 'onclick="installOneModel(' in body, "each row needs its own download action"
    # The tick-box + shared "Download selected" gesture is what this replaced. Comments
    # are stripped first: the comment EXPLAINING the removal necessarily quotes it, and
    # a guard that trips on its own explanation gets reworded rather than fixed.
    clean = strip_comments(body)
    assert_absent(clean, 'type="checkbox"', why="the per-model button replaced the tick-boxes")
    assert_absent(clean, "installSelectedModels", why="the shared multi-select is gone")


def test_a_downloaded_model_offers_no_download_button():
    """THE 'remove useless elements' RULE. A row for a model already on disk must
    render a state, never a live control for work that is already done."""
    body = function_body(APP, "loadModelCatalog")
    # The installed branch and the button must be on OPPOSITE sides of one condition.
    assert "m.installed === true" in body
    i_state = body.index('t("Downloaded")')
    i_button = body.index("installOneModel(")
    assert i_state < i_button, (
        "the installed case must be the FIRST arm of the conditional, so a downloaded "
        "model can never fall through to the download button"
    )


def test_an_unreadable_probe_still_offers_the_download():
    """Negative-space twin. ``installed === null`` is a stopped daemon that cannot
    tell us — hiding the button on that guess would strand the operator, and
    downloading something already present is harmless."""
    body = function_body(APP, "loadModelCatalog")
    assert "m.installed === null" in body, "the third state must keep its own answer"


def test_installOneModel_asks_consent_and_repaints():
    body = function_body(APP, "installOneModel")
    assert "ensureAiEgress" in body, "a multi-GB clearnet download passes the ONE consent"
    assert "/api/llm/models/install" in body, "same endpoint as the gesture it replaced"
    assert "loadModelCatalog()" in body, "the finished row must lose its button"
    # `t` is not a global in this file; the repo has a dedicated guard for that, and
    # this is the local half of it.
    assert "OOI18N.t" in body


# --------------------------------------------------------------------------- #
#  the default model becomes a picker over what is actually downloaded
# --------------------------------------------------------------------------- #
def test_the_default_model_block_is_a_picker_over_downloaded_models():
    body = function_body(APP, "_paintDefaultModel")
    assert 'id="llm-model-pick"' in body
    assert 'onchange="setActiveModel(' in body
    # ONLY downloaded ones — the whole point of the ask.
    assert "m.installed === true" in body, "the options are filtered to what is on disk"
    assert "/api/llm/models/catalog" in body, (
        "the list must come from the catalogue, which resolves `installed` against the "
        "backend that will actually serve — /api/llm/models answers about Ollama"
    )


def test_the_picker_falls_back_to_a_download_when_nothing_is_downloaded():
    """With an empty disk there is nothing to choose BETWEEN, so the honest control is
    the one that gets you a first model — not an empty dropdown."""
    body = function_body(APP, "_paintDefaultModel")
    assert "installDefaultModel(this)" in body


def test_the_catalogue_endpoint_publishes_the_active_model():
    """The picker shows the operator's own choice, so the payload has to carry it —
    re-deriving it in the browser is how two surfaces start disagreeing."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        .joinpath("src/api/llm.py")
        .read_text(encoding="utf-8")
    )
    assert 'out["active"] = active_model()' in src


# --------------------------------------------------------------------------- #
#  the developer surface moves to Advanced
# --------------------------------------------------------------------------- #
def test_prompts_and_extractors_live_under_advanced_ai():
    adv = HTML.index('id="set-advanced"')
    models = HTML.index('id="set-models"')
    for marker in ("Behaviour &amp; prompts", "Custom extractors"):
        at = HTML.index(marker)
        assert at > adv, f"{marker} must sit inside the Advanced view"
        assert at > models, f"{marker} must no longer sit inside the AI view"
    assert 'data-adv="ai"' in HTML, "it needs the foldable section wrapper"


def test_nothing_was_lost_in_the_move():
    """Absorption, the Desk lesson: the panels moved WHOLE. Every control the old AI
    tab carried must still exist somewhere in the document."""
    for el in (
        "llm-prompt-summary", "llm-prompt-translate", "llm-prompt-synthesis",
        "llm-prompt-ai_keywords", "llm-keep-alive", "ai-prompts-list",
        "ai-prompt-label", "ai-prompt-kind", "ai-prompt-text",
    ):
        assert f'id="{el}"' in HTML, f"{el} disappeared in the move"


def test_the_moved_panels_load_on_expand_not_with_the_subtab():
    """Folded must not mean fetched — the Advanced convention. And the AI subtab must
    no longer pay for panels it no longer shows."""
    loaders = object_literal(APP, "_ADV_LOADERS")
    assert "ai:" in loaders and "loadLlmPrompts()" in loaders and "loadCustomPrompts()" in loaders

    show = function_body(APP, "showSetCat")
    models_line = next(
        ln for ln in show.splitlines() if 'cat === "models"' in ln and "loadOllamaInstall" in ln
    )
    assert "loadLlmPrompts()" not in models_line, "the AI subtab must not load the moved panel"
    assert "loadCustomPrompts()" not in models_line


# --------------------------------------------------------------------------- #
#  the AI diagnostics move to Advanced, behind one button
#  Maintainer 2026-08-09: "the diagnostic section ... should be moved in the advanced
#  subtab", and "simplify all AI related diagnostics into one single button".
# --------------------------------------------------------------------------- #
#: Every AI diagnostic control that used to sit in the Data & backup panel. They move
#: WHOLE (the Desk lesson) -- a control that vanished in the move is the failure this
#: pins, not a tidier tab.
_MOVED_AI_DIAGNOSTICS = (
    "keyword-triage-box",
    "source-tags-box",
    "perception-extract-box",
    "model-bench-box",
)


def _view_of(anchor: str) -> str:
    """Which Settings sub-view an element ends up in."""
    import re

    views = [(m.start(), m.group(1)) for m in re.finditer(r'<div class="set-view" id="([^"]+)"', HTML)]
    at = HTML.index(anchor)
    return [name for pos, name in views if pos < at][-1]


def test_the_ai_diagnostics_moved_out_of_data_and_backup():
    for box in _MOVED_AI_DIAGNOSTICS:
        assert _view_of(f'id="{box}"') == "set-advanced", f"{box} is still outside Advanced"
    for endpoint in ("/api/diagnostics/llm-bench", "/api/diagnostics/llm-throughput"):
        assert _view_of(endpoint) == "set-advanced", f"{endpoint}'s button is still outside Advanced"


def test_the_general_diagnostics_stayed_where_they_were():
    """The negative-space twin: this was a move of the AI half, not of the panel.

    The all-diagnostics bundle, the keyword logs and the network verdicts are not AI
    diagnostics; sweeping them along would be a different, unasked-for change.
    """
    assert _view_of('id="all-diag-btn"') == "set-data"


def test_the_activity_feed_sits_beside_the_toggle_it_describes():
    """It reports what the background AI has been doing, so it belongs next to the
    control that turns the background AI on -- not in a diagnostics panel."""
    assert _view_of('id="ai-activity-box"') == "set-models"
    assert _view_of('id="aic-toggle-btn"') == "set-models"


def test_one_button_runs_every_ai_check():
    assert _view_of('id="aicheck-btn"') == "set-advanced"
    assert 'onclick="runAiCheck(this)"' in HTML
    body = function_body(APP, "runAiCheck")
    assert "/api/diagnostics/ai-check/run" in body
    assert "/api/diagnostics/ai-check/cancel" in body, "a multi-minute run needs a stop"


def test_the_one_button_offers_the_bench_rather_than_excluding_it():
    """The bench is now IN the button, behind a choice (maintainer ask 2026-08-10:
    "Fuse all AI related benchmark into one single button").

    It used to be excluded and said so. What must never happen is the third state --
    included silently, or excluded silently -- so the control names the choice and the
    checkbox's own title says what ticking it costs.
    """
    src = strip_comments(HTML)
    at = src.index('id="aicheck-btn"')
    title = src[at:src.index(">", at)]
    assert "comparative bench" in title.lower(), "the button must name what the tick adds"

    box = src.index('id="aicheck-deep"')
    label = src[src.rindex("<label", 0, box):src.index("</label>", box)]
    assert "hours" in label.lower(), "an hours-long run must say so before it is ticked"
    assert "resumable" in label.lower(), "and that cancelling keeps what it measured"


def test_the_deep_run_is_confirmed_and_the_quick_one_is_not():
    """Ticking it restarts the AI backend and takes hours. Not ticking it must stay a
    single click -- a confirm on the ordinary path is how a confirm stops being read."""
    body = function_body(APP, "runAiCheck")
    assert "aicheck-deep" in body
    assert "confirm(" in body
    assert "deep &&" in body or "deep && !confirm" in body, (
        "the confirm must be gated on deep, never asked for the quick check"
    )
    assert "JSON.stringify({ deep })" in body, "the choice must reach the endpoint"


def test_the_perception_harness_button_is_folded_into_the_one_check():
    """Maintainer ask: "Perception eval harness test should be included in those tests,
    bundle it and remove the button."

    It is a STEP of the check now. The control survives inside the run-one-on-its-own
    fold (never lose a tool), but it must no longer sit beside the extraction sweep as
    a thing to remember to press first, and the gate result it produces stays there.
    """
    from src.monitoring.ai_check import default_step_names

    assert "perception_eval" in default_step_names(), (
        "the harness must run as part of the one check"
    )

    src = strip_comments(HTML)
    assert src.index('id="pel-run-btn"') < src.index('id="perception-extract-box"'), (
        "the harness button moved out of the extraction box into the one-check fold"
    )
    assert 'id="pe-gate-result"' in src, "the gate result belongs beside the sweep it gates"


def test_the_check_toggles_instead_of_disabling():
    """A run takes minutes; a disabled button for that long is a dead control -- the
    langdetect pattern this project already settled on."""
    body = function_body(APP, "runAiCheck")
    assert "dataset.running" in body
    assert ".disabled = true" not in body
