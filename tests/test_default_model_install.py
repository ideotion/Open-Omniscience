"""One "download the default model" button, correct for whichever backend will serve.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ask 2026-07-30: "add a 'download default model' button that will download the
appropriate ministral from either vllm or ollama depending on which will be used".

THE THING THAT MAKES THIS HONEST rather than a cosmetic branch: the two backends do not
merely want different files, they DOWNLOAD DIFFERENTLY.

  * Ollama pulls a quantised image through the pull queue -- a real download, one at a
    time, cancellable, with real byte progress.
  * vLLM has NO separate download step at all. It fetches the HuggingFace weights when
    the server STARTS with ``--model``. There is no byte progress to show because there
    is no download job to show it for.

So the payload reports the MECHANISM, and the UI states it, rather than implying one
uniform "download" and then quietly doing something else on the GPU path.
"""

from __future__ import annotations

from pathlib import Path

_APP = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(
    encoding="utf-8"
)
_API = (Path(__file__).resolve().parents[1] / "src" / "api" / "llm.py").read_text(
    encoding="utf-8"
)


def _fn(name: str) -> str:
    marker = f"function {name}("
    assert marker in _APP, name
    tail = _APP.split(marker, 1)[1]
    for stop in ("\n    function ", "\n    async function ", "\n    const _", "\n    let _"):
        if stop in tail:
            tail = tail.split(stop, 1)[0]
    return tail


def _pyfn(name: str) -> str:
    marker = f"def {name}("
    assert marker in _API, name
    return _API.split(marker, 1)[1].split("\n@router", 1)[0].split("\ndef ", 1)[0]


# --------------------------------------------------------------------------- #
#  the backend choice is not re-derived
# --------------------------------------------------------------------------- #
def test_the_plan_uses_the_SAME_resolver_the_pill_and_inference_use():
    """A second copy of "which backend wins" could install for a backend that will not
    serve — the one failure this feature exists to prevent."""
    body = _pyfn("_default_model_plan")
    assert "resolve_backend" in body


def test_each_backend_gets_its_OWN_artifact():
    body = _pyfn("_default_model_plan")
    assert 'mini["vllm_model"]' in body, "vLLM gets the HuggingFace weights"
    assert 'mini["tag"]' in body, "Ollama gets the quantised image"


# --------------------------------------------------------------------------- #
#  the mechanisms are genuinely different, and said so
# --------------------------------------------------------------------------- #
def test_the_two_mechanisms_are_reported_distinctly():
    """They really are different operations -- a HuggingFace weights fetch and a
    registry image pull -- so the button says which one it is about to do."""
    body = _pyfn("_default_model_plan")
    assert '"mechanism": "download"' in body
    assert '"mechanism": "pull"' in body


def test_the_vllm_path_invents_no_progress_number():
    """AMENDED 2026-07-30. This used to pin the OPPOSITE: that vLLM claims no download
    job at all, because it fetched weights at server start. That was true and useless as
    a button (no download, no progress, no way to know if the GB were already there), so
    the plan now describes a real pre-fetch. What survives unchanged is the honesty
    constraint underneath: the downloader reports progress as text, so turning it into a
    percentage here would be a guess."""
    body = _pyfn("_default_model_plan")
    vllm = body.split('"backend": "vllm"', 1)[1].split('"backend": "ollama"', 1)[0]
    assert "would be a guess" in vllm
    # The note SAYS "No percentage" -- what must not appear is a percentage FIELD.
    assert not [k for k in ("percent", "progress_pct", "eta_seconds") if f'"{k}"' in vllm]


def test_an_unknown_install_state_is_None_not_a_guessed_false():
    """A guessed false nags a user who already has the weights; a guessed true hides a
    missing model. AMENDED 2026-07-30: the vLLM side no longer has to say "unknown" for
    the ORDINARY case -- it probes the HF cache -- but an unreadable cache is still
    None, never a False, and the probe is strict about a half-finished download."""
    body = _pyfn("_default_model_plan")
    assert "model_cache_state" in body, "vLLM: the HF cache IS probed now"
    assert 'cache["cached"]' in body, "and the probe's answer is what is reported"
    assert "installed = None" in body, "Ollama: the daemon being down is not 'absent'"

    from src.llm.vllm_lifecycle import model_cache_state

    st = model_cache_state("nope/does-not-exist-anywhere")
    assert st["cached"] is False and st["bytes"] is None


# --------------------------------------------------------------------------- #
#  egress
# --------------------------------------------------------------------------- #
def test_both_paths_are_refused_under_airplane_mode():
    """BOTH egress clearnet — Ollama's registry and Hugging Face — and neither goes
    through Tor. Gating only the path that happens to route through our own client
    would leave the other silently downloading while the user believes they are
    offline.

    ANCHOR MOVED, property unchanged (2026-08-01): the gate is now
    ``egress_permitted(PURPOSE_AI_INSTALL)`` rather than a bare
    ``kill_switch_active()``. That is still "refused under airplane mode" — the
    helper's FIRST question is the kill switch — but it additionally lets an
    operator-CONSENTED egress window through, which is the whole point of the
    window: installing the local AI without starting the collector. Asserted
    BEHAVIOURALLY below rather than by the old literal, so this pins the property
    instead of the spelling.
    """
    body = _pyfn("default_model_install")
    assert "egress_permitted" in body, "the endpoint must still gate its egress"
    assert "clearnet" in body.lower()

    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.ingest import egress_window as ew

    ew._reset_for_tests()
    try:
        activate_kill_switch()
        # Airplane mode, no window: refused, exactly as before.
        assert ew.egress_permitted(ew.PURPOSE_AI_INSTALL) is False
        # A consented window permits THIS purpose and nothing else.
        ew.open_window(ew.PURPOSE_AI_INSTALL)
        assert ew.egress_permitted(ew.PURPOSE_AI_INSTALL) is True
        assert ew.egress_permitted("collection") is False
    finally:
        ew._reset_for_tests()
        clear_kill_switch()


def test_the_confirm_names_the_real_artifact_and_that_it_is_not_tor():
    # ANCHOR MOVED, property unchanged (2026-07-31): `installDefaultModel` became a
    # one-line delegator to `_installDefaultModel` so the fused "Set up local AI"
    # chain can pass its already-taken consent through instead of asking twice for
    # the same bytes. The confirm and its wording live in the delegate now.
    body = _fn("_installDefaultModel")
    assert "p.artifact" in body and "p.size" in body, "the real artifact, not a generic prompt"
    assert "not through Tor" in body


def test_the_only_way_past_the_confirm_is_a_consent_already_taken():
    """The fused setup chain skips this prompt because it ALREADY asked, naming this
    exact artifact and size. Pinned so the bypass can never widen into a default: the
    ordinary entry point must pass no flag, and the chain's own confirm must be the
    thing that earns the skip."""
    assert "_installDefaultModel(btn, {})" in _fn("installDefaultModel")
    chain = _fn("runAiSetup")
    assert "confirm(" in chain, "the chain must take the consent it then passes through"
    assert "s.artifact" in chain and "s.size" in chain
    assert "_installDefaultModel(null, {confirmed: true})" in chain


# --------------------------------------------------------------------------- #
#  one path, not two
# --------------------------------------------------------------------------- #
def test_the_pill_uses_the_same_backend_aware_install():
    """The pill's no-model path used the Ollama-only installer, which on a vLLM machine
    downloads the wrong artifact AND leaves the pill red."""
    assert "installDefaultModel" in _fn("_aiPillEnsureModel")


def test_the_ollama_only_installer_is_gone():
    """Leaving it would be a second, backend-blind install path — exactly the drift this
    change removes."""
    assert "pullMinistral" not in _APP


def test_the_block_renders_in_both_panel_states():
    assert _APP.count("_paintDefaultModel()") >= 2
