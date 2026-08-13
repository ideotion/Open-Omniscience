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


def test_the_general_diagnostics_followed_into_advanced():
    """SUPERSEDED 2026-08-11 and deliberately, which is why it was written this way.

    Through 2026-08-09 this asserted the general diagnostics stayed in Data & backup,
    on the reasoning that the AI move was a move of the AI half and "sweeping them
    along would be a different, unasked-for change". The maintainer then asked for
    exactly that change — "move all diagnostics from the data / backup subtab into a
    new section in the advanced subtab" — so the guard is updated rather than deleted:
    the AI diagnostics must still not be the only ones there.

    What it pins now is that the two halves ended up TOGETHER. Their whole reason for
    living in Advanced is the same one, and a future tidy-up that pulls either back
    into Data & backup has to argue with this test.
    """
    assert _view_of('id="all-diag-btn"') == "set-advanced"
    assert _view_of('id="aicheck-btn"') == "set-advanced"


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

    The cost itself changed with the one-model ruling: the roster bench ran for HOURS
    because it loaded every model in turn, and the one that replaced it measures the one
    model on whatever is already serving. So the label must state the cost it has now,
    not the one it inherited -- an "hours" warning on a tens-of-minutes run is as
    unreadable as no warning, and in the other direction it would understate.
    """
    src = strip_comments(HTML)
    at = src.index('id="aicheck-btn"')
    title = src[at:src.index(">", at)]
    assert "bench" in title.lower(), "the button must name what the tick adds"

    box = src.index('id="aicheck-deep"')
    label = src[src.rindex("<label", 0, box):src.index("</label>", box)]
    assert "hours" not in label.lower(), "the roster's hours are gone; do not inherit them"
    assert "tens of minutes" in label.lower(), "the real cost, stated before it is ticked"
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
    # The PROPERTY, not the literal: this used to pin `JSON.stringify({ deep })`, which
    # went red the day a second field joined the same body — a stale anchor guarding
    # correct code. What matters is that the choice reaches the endpoint at all.
    run_call = body.split("/api/diagnostics/ai-check/run", 1)[1][:200]
    assert "deep" in run_call, "the choice must reach the endpoint"


def test_the_confirm_names_every_way_the_run_rearranges_the_machine():
    """It used to name three: the deep run STARTED a stopped backend, RESTARTED vLLM
    between roster models, and put the machine BACK afterwards. With one model there is
    nothing to switch between, and the bench deliberately manages nothing -- so the
    honest count of side effects is now zero, and the confirm says so outright.

    That is the assertion, and it is not a weaker one: a confirm that stayed silent
    about backend management would be indistinguishable from the old one that did it,
    and a future edit re-introducing a handover has to change this sentence to pass.
    """
    body = strip_comments(function_body(APP, "runAiCheck"))
    sentence = body[body.index("confirm(t(") : body.index("))) return;")].lower()

    assert "starts, stops and switches nothing" in sentence, (
        "the run manages no backend; if that ever changes, the consent must say so first"
    )
    assert "already running" in sentence, "it measures what is up, and names that"
    assert "resumable" in sentence, "cancelling keeps what it measured — the honest promise"
    assert "restarts your ai backend" not in sentence, "an inherited claim it no longer does"


def test_the_confirm_sentence_is_translated_in_every_locale():
    """It is a keyed string, so EXTENDING it would have silently reverted eleven
    locales to English (the DOM walker matches a key exactly). Pinned so the next edit
    has to re-key rather than append."""
    import json
    import pathlib

    body = strip_comments(function_body(APP, "runAiCheck"))
    start = body.index('confirm(t("') + len('confirm(t("')
    key = body[start : body.index('"', start)]

    for f in sorted(pathlib.Path("src/static/locales").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert key in d, f"{f.stem} is missing the deep-run confirm"
        if f.stem != "en":
            assert d[key] != key, f"{f.stem} fell back to the English sentence"


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


def test_the_check_downloads_nothing_and_asks_nobody_to():
    """Three tests used to live here, and all three were about a roster: a survey that
    priced the models this machine lacked, a guard so a failed survey still benched what
    was present, and a default of `download_missing = false` so the confirm was not
    decorative. With one model app-wide (maintainer ruling 2026-08-12) there is no
    roster to price, and the survey endpoint is gone with it.

    What survives is the property those three were protecting, and it is worth keeping
    as a NEGATIVE: ticking the box is consent to a long RUN, never to fetching weights.
    A future edit that wires a download back in behind this checkbox has to fail here
    first, and it would — the words are the ones a fetch reaches for.
    """
    body = strip_comments(function_body(APP, "runAiCheck"))
    # Anti-vacuity: an all-negative test passes for free over an empty slice, so pin
    # that the slice is the real function first.
    assert "/api/diagnostics/ai-check/run" in body, "the slice is the real runAiCheck"
    for gone in ("provision", "download_missing", "models/install", "pull"):
        assert gone not in body, (
            f"runAiCheck reaches for {gone!r} — the one-button check must never turn a "
            "tick into a multi-gigabyte download"
        )
