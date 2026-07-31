"""
The Settings -> AI subtab, after the maintainer's 2026-07-31 review.

Three findings, three guards:

  1. the same "no GPU detected" sentence appeared in FOUR separate boxes on one
     tab, which reads as nagging and buries the one statement that carries the
     actual consequence;
  2. three separate installs (the Ollama binary, vLLM, the default model) were
     scattered across three panels, so "get local AI working" meant finding all
     three and knowing which applied to this machine;
  3. a "Start the local AI" button sat in the models panel beside the top-bar AI
     pill, which is the one start control -- two controls for one action.

BROWSER-UNVERIFIED (fork-3 / Q6a): this is a source-level guard on the wiring and
the honesty properties, not a rendering test. A human click-through is owed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_ROOT / "app.js").read_text(encoding="utf-8")
_HTML = (_ROOT / "index.html").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """The source of ONE top-level function.

    Scoped deliberately: a whole-file substring search cannot distinguish "this
    box stopped saying it" from "some other box still says it", which is the
    exact distinction every assertion below turns on. (The lesson from the
    duty-cycle guard that passed against both the code it meant to reject and
    the code it meant to accept.)
    """
    m = re.search(rf"\n    (?:async )?function {re.escape(name)}\(", _APP)
    assert m, f"{name} not found"
    rest = _APP[m.end():]
    nxt = re.search(r"\n    (?:async )?function ", rest)
    return rest[: nxt.start()] if nxt else rest


def _code(name: str) -> str:
    """``_fn`` with whole-line ``//`` comments removed.

    Every "this string must be GONE" assertion needs this: the comment that
    RECORDS the removal necessarily quotes the removed string, so a raw search
    fails on the explanation rather than on the code. (The same trap the
    hardware-damage guard documents -- which is why that one is behavioural.)
    Only lines that are entirely a comment are dropped, so a ``https://`` inside
    a string literal is untouched.
    """
    return "\n".join(
        ln for ln in _fn(name).splitlines() if not ln.lstrip().startswith("//")
    )


# --------------------------------------------------------------------------- #
#  1. ONE hardware statement.
# --------------------------------------------------------------------------- #
def test_the_backend_facts_line_names_the_gpu_only_when_there_IS_one():
    """Absence is stated once, in the hardware block below it. A permanent
    "GPU: not detected" made this the first of four identical sentences."""
    src = _code("loadAiBackendPanel")
    assert 'gpu.available ? "GPU: "' in src, "the facts line no longer branches on presence"
    assert "not detected" not in src


def test_the_vllm_status_line_does_not_restate_gpu_presence():
    src = _code("loadVllmStatusPanel")
    assert "no GPU detected" not in src
    assert "parts.push(s.gpu" not in src


def test_the_vllm_install_box_states_the_CONSEQUENCE_not_a_second_detection():
    """What this box owes the operator is why vLLM is not offered and what serves
    instead -- not a repeat of the detection."""
    src = _code("loadVllmStatusPanel")
    assert "No GPU detected on this machine" not in src
    assert "vLLM needs a dedicated NVIDIA GPU" in src
    # ... and it must still point at the thing that DOES work here, or the box is
    # a dead end on exactly the machines that read it.
    assert "Ollama" in src


def test_a_disabled_vllm_start_button_says_why():
    """A disabled control with no explanation is a dead end; the reason rides the
    #oo-tip hover (invariant #17) rather than becoming a fifth copy in the body."""
    src = _fn("loadVllmStatusPanel")
    assert "btn.title" in src
    assert "vLLM is not installed." in src


def test_the_hardware_block_renders_ruling_15_warnings():
    """The tier between "refused" and "fine" -- CPU-only, thin VRAM, a small
    unified-memory Mac. If the warnings are never rendered, ruling 15's whole
    middle tier is invisible and the tab is back to a silent pass."""
    src = _fn("loadAiBackendPanel")
    assert "hw.warnings" in src
    assert "hw.name" in src, "a detected accelerator should be named where it is judged"


def test_the_override_checkbox_and_both_disclosure_directions_survive():
    """Never a silent block, never a silent enable -- the property the whole gate
    rests on, so the review must not have quietly dropped either half."""
    src = _fn("loadAiBackendPanel")
    assert "ai-hw-override" in src
    assert "setAllowImpracticalHw" in src
    assert "AI features are off by default on this hardware." in src
    assert "AI features are enabled by your override, not by this hardware." in src


# --------------------------------------------------------------------------- #
#  2. ONE setup control.
# --------------------------------------------------------------------------- #
def test_the_fused_setup_box_exists_and_is_wired_into_the_subtab():
    assert 'id="ai-setup-box"' in _HTML
    assert "loadAiSetup()" in _APP
    # Painted when the AI subtab opens, alongside the panels it summarises.
    m = re.search(r'if \(cat === "models"\) \{[^\n]*', _APP)
    assert m and "loadAiSetup()" in m.group(0)


def test_the_setup_box_chooses_the_backend_from_the_HARDWARE():
    """vLLM is GPU-first: proposing it on a CPU-only machine would install
    several GB into a backend that could never usefully serve there."""
    src = _fn("_aiSetupPlan")
    assert 'gpu.available ? "vllm" : "ollama"' in src


def test_the_setup_box_hides_itself_when_there_is_nothing_left_to_do():
    """It is a shortcut past the scatter, not a permanent banner -- a setup
    prompt on a fully-configured machine is the nagging this review removed."""
    src = _fn("loadAiSetup")
    assert "!plan.steps.length" in src
    assert 'box.style.display = "none"' in src


def test_a_failed_status_read_hides_the_box_rather_than_proposing_a_guess():
    """Every step comes from the server. A plan built on an unread status could
    tell the operator to install something they already have."""
    src = _fn("_aiSetupPlan")
    assert "return null" in src
    assert "catch (e) { return null; }" in src


def test_the_whole_chain_takes_ONE_consent_that_names_every_artifact_and_size():
    """The "state the cost before the bytes" rule, asked once instead of three
    times -- and a consent asked three times for one action teaches people to
    click through it."""
    src = _fn("runAiSetup")
    assert "confirm(" in src
    assert "Set up local AI on this machine?" in src
    assert "s.size" in src and "s.artifact" in src
    assert "This downloads over the clearnet — not through Tor." in src


def test_the_model_step_does_not_ask_a_SECOND_time_for_the_same_bytes():
    src = _fn("runAiSetup")
    assert "_installDefaultModel(null, {confirmed: true})" in src
    # ... and the flag is honoured only as an explicit opt-out of the prompt, so
    # the ordinary button still confirms.
    body = _fn("_installDefaultModel")
    assert "opts && opts.confirmed" in body
    assert "|| confirm(" in body


def test_the_standalone_download_button_still_confirms():
    """The per-component controls are unchanged (the Desk lesson): the fused box
    is additive, and a user who ignores it must still be asked."""
    assert 'onclick="installDefaultModel(this)"' in _APP
    src = _fn("installDefaultModel")
    assert "_installDefaultModel(btn, {})" in src


def test_a_platform_with_no_scripted_installer_links_the_real_one():
    """macOS/Windows have no scripted Ollama install, so a "one click" button
    there would be a promise the app cannot keep."""
    src = _fn("loadAiSetup")
    assert "scripted" in src
    assert "ollama.com/download" in src


def test_the_setup_run_never_clobbers_its_own_output():
    src = _fn("loadAiSetup")
    assert "_aiSetupRunning" in src


# --------------------------------------------------------------------------- #
#  3. ONE start control.
# --------------------------------------------------------------------------- #
def test_the_duplicate_start_button_is_gone_from_the_models_panel():
    src = _code("loadLlmModels")
    assert "Start the local AI" not in src, (
        "the top-bar AI pill is the one start control (maintainer review 2026-07-31)"
    )
    assert 'onclick="aiPillClick()"' not in src


def test_the_message_POINTS_AT_the_pill_instead_of_duplicating_it():
    """Nothing is lost only if the sentence tells the reader where the control
    is -- which is also the only way anyone learns the pill is clickable."""
    src = _fn("loadLlmModels")
    assert "AI pill in the top bar" in src


def test_the_pill_itself_is_still_the_start_control():
    """The removal is safe ONLY because this path exists. Pinned so a future edit
    cannot retire the pill's click handler and leave no start control at all."""
    assert "el.onclick = aiPillClick" in _APP
    assert "async function aiPillStartOrInstall()" in _APP


# --------------------------------------------------------------------------- #
#  No egress promise is quietly broken.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fn", ["loadAiSetup", "_aiSetupPlan"])
def test_the_setup_box_reads_only_loopback_status_endpoints(fn):
    """Painting the box must not itself download anything -- it runs on every
    visit to the AI subtab."""
    src = _fn(fn)
    for m in re.findall(r'api\("([^"]+)"', src):
        assert m.startswith("/api/"), m
    assert "method: \"POST\"" not in src
