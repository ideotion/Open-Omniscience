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
    body = _pyfn("_default_model_plan")
    assert '"mechanism": "server_start"' in body
    assert '"mechanism": "pull"' in body


def test_the_vllm_path_does_not_claim_a_download_job_that_does_not_exist():
    """vLLM fetches weights at server start. Reporting byte progress for it would be
    inventing a job — the note says so instead."""
    body = _pyfn("_default_model_plan")
    vllm = body.split('"backend": "vllm"', 1)[1].split('"backend": "ollama"', 1)[0]
    assert "no separate download step" in vllm
    assert "no byte progress" in vllm


def test_an_unknown_install_state_is_None_not_a_guessed_false():
    """A guessed false nags a user who already has the weights; a guessed true hides a
    missing model. Both backends have a genuinely unknowable case, and both say so."""
    body = _pyfn("_default_model_plan")
    assert '"installed": None' in body, "vLLM: the HF cache is not probed"
    assert "installed = None" in body, "Ollama: the daemon being down is not 'absent'"


# --------------------------------------------------------------------------- #
#  egress
# --------------------------------------------------------------------------- #
def test_both_paths_are_refused_under_airplane_mode():
    """BOTH egress clearnet — Ollama's registry and Hugging Face — and neither goes
    through Tor. Gating only the path that happens to route through our own client
    would leave the other silently downloading while the user believes they are
    offline."""
    body = _pyfn("default_model_install")
    assert "kill_switch_active" in body
    assert "clearnet" in body.lower()


def test_the_confirm_names_the_real_artifact_and_that_it_is_not_tor():
    body = _fn("installDefaultModel")
    assert "p.artifact" in body and "p.size" in body, "the real artifact, not a generic prompt"
    assert "not through Tor" in body


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
