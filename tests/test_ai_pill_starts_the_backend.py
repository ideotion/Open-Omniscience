"""Clicking the red AI pill starts the local AI — it does not just open a panel.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-30: "clicking the AI button of the top bar does not start vLLM, it
should start either vLLM or Ollama automatically and load the default model and then turn
green" — and "I don't see a 'download the default model'".

Two distinct defects, both pinned here:

  1. ``aiPillStartOrInstall`` only ever tried vLLM, and only when installed AND not
     running AND a GPU was present AND a vLLM model id was already stored. On an
     Ollama-only machine every path fell through to opening Settings. ``/api/llm/ollama/
     start`` existed and had no caller anywhere in the UI.
  2. ``loadLlmModels`` returned EARLY when Ollama was not answering, which hid the
     one-click default-model install in the exact state where it is the only useful
     control on the panel.

BROWSER-UNVERIFIED (fork-3): source guards + node --check, no click-through.
"""

from __future__ import annotations

from pathlib import Path
from tests.js_source_helper import function_body

_APP = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(
    encoding="utf-8"
)


def _fn(name: str) -> str:
    """One function's own body, brace-matched (tests.js_source_helper)."""
    return function_body(_APP, name)


def test_the_pill_can_start_ollama_not_only_vllm():
    """THE defect: the Ollama start endpoint had no caller, so the pill was inert on
    every machine without a GPU.

    ANCHOR MOVED, PROPERTY UNCHANGED (2026-08-04). The pill no longer names either
    start endpoint, because it no longer decides: it posts to ``/activation/start``
    and the server picks. That removed a FOURTH copy of "which backend" from the
    browser -- beside routing, provisioning and activation -- and the copy it removed
    had a real hole, which the test below now pins where the decision actually lives.
    Following the code rather than relaxing the assertion.
    """
    body = _fn("aiPillStartOrInstall")
    assert "/api/llm/activation/start" in body
    assert "method: \"POST\"" in body


def test_the_pill_delegates_the_choice_instead_of_re_deriving_it():
    """The browser must not hold its own precedence rule. It had one, and on a GPU
    machine with vLLM installed but no stored model id it silently fell through to
    Ollama -- a decision no other surface would have made."""
    body = _fn("aiPillStartOrInstall")
    assert "/api/llm/vllm/start" not in body, "the pill must not start a backend itself"
    assert "/api/llm/ollama/start" not in body


def test_the_preferred_backend_still_falls_back_to_one_that_works():
    """The property the old browser logic protected, kept -- now server-side, where
    every caller gets it rather than only the pill.

    Behavioural coverage is in tests/test_llm_activation.py
    (``test_a_blocked_preferred_backend_falls_back_to_one_that_works``); this only
    pins that the fallback exists at all, since its absence would be invisible from
    the frontend.
    """
    import inspect

    from src.llm import activation

    src = inspect.getsource(activation.activation_plan)
    assert "fell_back_from" in src


def test_a_missing_model_offers_the_default_rather_than_ending_red():
    """The 'load the default model' half of the ask: a running backend with no model
    still cannot answer, which is exactly the state that reads as broken."""
    assert "_aiPillEnsureModel" in _fn("aiPillStartOrInstall")
    ensure = _fn("_aiPillEnsureModel")
    # 2026-07-30: routed through the BACKEND-AWARE installer, so a vLLM machine no
    # longer gets the Ollama image (which would download the wrong artifact and still
    # leave the pill red). tests/test_default_model_install.py owns that property.
    assert "installDefaultModel" in ensure
    assert "d.installed" in ensure, "an already-installed model must not re-prompt"


def test_a_multi_gigabyte_download_is_never_started_by_a_single_pill_click():
    """The honest line. Starting a local daemon is free and reversible, so it is
    automatic; a model download is clearnet traffic (via the Ollama process, NOT Tor),
    so it keeps its confirm. A status pill must not silently pull gigabytes."""
    # ANCHOR MOVED, property unchanged (2026-07-31): `installDefaultModel` is now a
    # one-line delegator so the fused setup chain can pass an already-taken consent
    # through; the confirm itself lives in `_installDefaultModel`. Following the code
    # rather than relaxing the assertion -- the guarantee is that the PILL path
    # confirms, and the pill reaches the download through exactly this pair.
    assert "_installDefaultModel(btn, {})" in _fn("installDefaultModel"), (
        "the pill's entry point must not start passing a pre-taken consent"
    )
    assert "confirm(" in _fn("_installDefaultModel"), (
        "the download keeps its confirmation even when reached from the pill"
    )
    # The rationale lives in the comment block introducing the function, so the slice
    # starts at that block rather than at the `function` keyword.
    intro = _APP.split("async function aiPillStartOrInstall(", 1)[0][-2000:]
    assert "CLEARNET" in intro, "and the reason is stated where the decision is made"


def test_the_pill_rechecks_health_so_it_actually_turns_green():
    """A daemon needs a moment to answer. Leaving the pill red until the next poll
    would read as 'it didn't work' — which is how the defect was reported."""
    assert "loadLlmHealth" in _fn("_aiPillSettle")


def test_the_default_model_install_shows_when_ollama_is_DOWN():
    """The second report. loadLlmModels returned early in this state, hiding the one
    control that would fix it."""
    body = _fn("loadLlmModels")
    # Bounded by the statement that FOLLOWS the block, not by the first "}" — the
    # branch contains template literals full of them.
    down = body.split("if (!d.available)", 1)[1].split("const FIT", 1)[0]
    assert "_miniBlockHtml" in down, "the install block must render while Ollama is down"
    # SUPERSEDED IN FORM (maintainer review 2026-07-31), not in substance: this branch
    # used to carry its own "Start the local AI" button beside the top-bar AI pill --
    # two controls for one action. The button is gone; the requirement that this state
    # offer a way OUT of it is not, so the sentence must now POINT AT the pill. That is
    # also the only way a reader learns the pill is clickable at all.
    assert "AI pill in the top bar" in down, "and so must a way to start it"
    assert "aiPillClick" not in down, (
        "the duplicate in-panel start button must stay removed -- the pill is the one "
        "start control (maintainer review 2026-07-31)"
    )


def test_the_install_block_is_shared_by_both_panel_states():
    """One renderer, so the two states cannot drift into showing different caveats."""
    assert _APP.count("_miniBlockHtml(d, t)") >= 2
    # 2026-07-30: the block became a placeholder that _paintDefaultModel fills from the
    # server's per-backend plan, so the licence + caveats now render THERE. Still one
    # renderer, one source of truth -- just fed by the backend that will actually serve.
    painted = _fn("_paintDefaultModel")
    assert "card-caveat" in painted and "Licence:" in painted, (
        "the licence provenance travels with the button, visible before the click"
    )
    assert "p.caveats" in painted
