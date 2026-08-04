"""Backend ACTIVATION -- "which backend do I START, and can I".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Field report 2026-08-04: both backends installed, "Start background AI" answered
"local model hiccup (1/10) -- retrying in 5s". Nothing was wrong with the retry
budget; nothing had ever STARTED a backend. ``resolve_backend`` answers routing and
``provisioning_backend`` answers setup; the third question had no owner.

WHAT IS PINNED HERE is mostly the REFUSALS, because a one-click "start" is exactly
where a fabricated success or a silent several-GB download would land:

  * a start that would make vLLM fetch uncached weights from Hugging Face is refused
    BY NAME -- and the twin: a cached model is not refused, or the fix would simply
    break starting;
  * "not installed" is a named prerequisite, never a thing to retry;
  * ``ready`` is claimed only when a backend actually answers -- a vLLM engine that
    is still loading reports started-but-not-ready, which is the truth;
  * an operator's explicit choice wins over the hardware preference, in both
    directions.
"""

from __future__ import annotations

import pytest

from src.llm import activation


# --------------------------------------------------------------------------- #
#  A machine, described entirely by what the probes would say
# --------------------------------------------------------------------------- #
def _machine(
    monkeypatch,
    *,
    gpu=True,
    vllm_installed=False,
    vllm_running=False,
    ollama_installed=False,
    ollama_running=False,
    cached=True,
    override=None,
    model="org/Model-3B",
):
    """Patch every probe activation consults. No subprocess, no network, no GPU."""
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu",
        lambda: {"available": gpu, "vram_mb": 8192 if gpu else None},
    )
    monkeypatch.setattr(
        "src.llm.backend._vllm_status",
        lambda: {"installed": vllm_installed, "running": vllm_running},
    )
    monkeypatch.setattr("src.llm.backend._ollama_available", lambda: ollama_running)
    monkeypatch.setattr("src.llm.backend._ollama_installed", lambda: ollama_installed)
    monkeypatch.setenv("OO_LLM_BACKEND", override or "")

    import src.llm.ollama_lifecycle as ol
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "is_installed", lambda: vllm_installed)
    monkeypatch.setattr(vl, "is_running", lambda *a, **k: vllm_running)
    monkeypatch.setattr(vl, "model_cache_state", lambda m: {"cached": cached, "path": None})
    monkeypatch.setattr(ol, "is_installed", lambda: ollama_installed)
    monkeypatch.setattr(ol, "is_running", lambda *a, **k: ollama_running)
    monkeypatch.setattr(activation, "_vllm_model", lambda: model)


# --------------------------------------------------------------------------- #
#  The pick
# --------------------------------------------------------------------------- #
def test_vllm_wins_when_both_are_installed_on_a_gpu_machine(monkeypatch):
    """The maintainer's rule, and the shared precedence already encoded it: on a GPU
    machine vLLM is the one that can use the card."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True)
    plan = activation.activation_plan()
    assert plan["backend"] == "vllm"
    assert plan["can_start"] is True
    assert "GPU" in plan["chosen_because"] or "vLLM" in plan["chosen_because"]


def test_but_a_cpu_only_machine_picks_ollama_even_with_vllm_installed(monkeypatch):
    """The twin, and the reason "prefer vLLM" is implemented as "prefer vLLM where it
    can run": ``vllm_lifecycle.start`` REFUSES on a CPU-only machine by ruling, so
    preferring it here would hand the operator a guaranteed failure instead of the
    daemon that would have worked."""
    _machine(monkeypatch, gpu=False, vllm_installed=True, ollama_installed=True)
    plan = activation.activation_plan()
    assert plan["backend"] == "ollama"
    assert plan["can_start"] is True


def test_an_explicit_choice_beats_the_hardware_preference(monkeypatch):
    """"...but the user should be able to choose." Both directions, because a rule
    that only bends one way is not a choice."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True)
    assert activation.activation_plan(override="ollama")["backend"] == "ollama"
    _machine(monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True)
    assert activation.activation_plan(override="vllm")["backend"] == "vllm"


def test_the_installed_one_is_picked_when_only_one_is(monkeypatch):
    _machine(monkeypatch, gpu=True, vllm_installed=False, ollama_installed=True)
    assert activation.activation_plan()["backend"] == "ollama"


# --------------------------------------------------------------------------- #
#  Refusals -- the half that matters
# --------------------------------------------------------------------------- #
def test_starting_vllm_on_uncached_weights_is_refused_by_name(monkeypatch):
    """vLLM downloads its weights AT SERVER START, in a subprocess this app's socket
    guard cannot see. Several GB over the clear internet is a decision, not a side
    effect of clicking a toggle."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, cached=False, model="org/Big-8B")
    plan = activation.activation_plan()
    assert plan["can_start"] is False
    assert "org/Big-8B" in plan["blocker"], "the refusal must name the model"
    assert "download" in plan["blocker"].lower()


def test_but_a_cached_model_starts_normally(monkeypatch):
    """The negative-space twin. An over-eager cache guard would refuse every start and
    read as 'conservative' while making the feature useless."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, cached=True)
    assert activation.activation_plan()["can_start"] is True


def test_an_unreadable_cache_does_not_refuse(monkeypatch):
    """A probe that cannot read is not a "no". Refusing here would block a machine
    whose weights are present but whose cache directory we cannot stat -- the same
    reason ``model_cache_state`` returns None rather than False."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "model_cache_state", lambda m: {"cached": None})
    assert activation.activation_plan()["can_start"] is True


def test_nothing_installed_is_a_named_prerequisite_not_a_retry(monkeypatch):
    """The actual field condition's cousin: a blocker the lane must NOT burn ten
    retries on, because no amount of retrying installs a binary."""
    _machine(monkeypatch, gpu=True, vllm_installed=False, ollama_installed=False)
    plan = activation.activation_plan()
    assert plan["can_start"] is False
    assert "not installed" in plan["blocker"]
    assert "Neither backend is installed" in plan["blocker"]


def test_a_blocker_names_the_alternative_when_there_is_one(monkeypatch):
    """An operator told "vllm is not installed" on a machine with a working Ollama
    should be told that too -- otherwise the honest refusal reads as "no AI here"."""
    _machine(monkeypatch, gpu=True, vllm_installed=False, ollama_installed=True, override="vllm")
    plan = activation.activation_plan(override="vllm")
    assert plan["can_start"] is False
    assert "ollama is installed" in plan["blocker"]


# --------------------------------------------------------------------------- #
#  Falling back rather than refusing outright
# --------------------------------------------------------------------------- #
def test_a_blocked_preferred_backend_falls_back_to_one_that_works(monkeypatch):
    """A GPU machine whose vLLM has no weights yet, with a perfectly good Ollama
    installed, must get Ollama -- not nothing.

    The browser's old hand-rolled pill logic had this fallback; moving the decision
    server-side lost it, and its own test is what caught the regression. Refusing
    outright here would be honest and useless.
    """
    _machine(
        monkeypatch,
        gpu=True,
        vllm_installed=True,
        cached=False,
        ollama_installed=True,
        model="org/Uncached-8B",
    )
    plan = activation.activation_plan()
    assert plan["backend"] == "ollama"
    assert plan["can_start"] is True


def test_and_the_preferred_backend_s_blocker_is_carried_not_discarded(monkeypatch):
    """Silently getting the slower backend, with no word about why the faster one was
    skipped, is how an operator ends up wondering why their GPU is idle."""
    _machine(
        monkeypatch,
        gpu=True,
        vllm_installed=True,
        cached=False,
        ollama_installed=True,
        model="org/Uncached-8B",
    )
    plan = activation.activation_plan()
    assert plan["fell_back_from"]["backend"] == "vllm"
    assert "org/Uncached-8B" in plan["fell_back_from"]["blocker"]
    assert "vllm was preferred" in plan["chosen_because"]


def test_an_explicit_choice_never_falls_back(monkeypatch):
    """The twin. An operator who said "vLLM only" and gets Ollama has been
    second-guessed, which is the one thing an explicit choice must never be."""
    _machine(
        monkeypatch,
        gpu=True,
        vllm_installed=True,
        cached=False,
        ollama_installed=True,
        override="vllm",
    )
    plan = activation.activation_plan(override="vllm")
    assert plan["backend"] == "vllm"
    assert plan["can_start"] is False
    assert "fell_back_from" not in plan


def test_nothing_to_fall_back_to_keeps_the_real_blocker(monkeypatch):
    """With no alternative, the preferred backend's own reason must survive rather
    than being replaced by a vaguer one about the alternative."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, cached=False, model="org/X")
    plan = activation.activation_plan()
    assert plan["backend"] == "vllm"
    assert "org/X" in plan["blocker"]


# --------------------------------------------------------------------------- #
#  Already running
# --------------------------------------------------------------------------- #
def test_an_already_running_backend_is_never_started_again(monkeypatch):
    _machine(monkeypatch, gpu=True, vllm_installed=True, vllm_running=True)
    plan = activation.activation_plan()
    assert plan["running"] is True
    assert plan["can_start"] is False, "nothing to start"
    assert plan["blocker"] is None, "already running is not a blocker"


def test_ensure_running_spawns_nothing_when_it_already_answers(monkeypatch):
    _machine(monkeypatch, gpu=True, vllm_installed=True, vllm_running=True)
    import src.llm.vllm_lifecycle as vl

    def _boom(*a, **k):  # pragma: no cover - reaching this IS the failure
        raise AssertionError("start() must not be called for a running backend")

    monkeypatch.setattr(vl, "start", _boom)
    out = activation.ensure_running()
    assert out["ready"] is True and out["started"] is False


# --------------------------------------------------------------------------- #
#  ready is a claim, and it is made only when true
# --------------------------------------------------------------------------- #
def test_a_loading_vllm_reports_started_but_not_ready(monkeypatch):
    """A model load takes tens of seconds. Reporting that as ready is the exact
    fabrication both lifecycle modules already refuse to make."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "start", lambda m, **k: {"started": True, "log_path": "/tmp/x"})
    out = activation.ensure_running()
    assert out["started"] is True
    assert out["ready"] is False, "spawned is not answering"
    assert "seconds" in out["detail"]


def test_ollama_reports_ready_only_when_the_daemon_answers(monkeypatch):
    _machine(monkeypatch, gpu=False, ollama_installed=True)
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setattr(ol, "start", lambda **k: {"started": True, "ready": True, "path": "/x"})
    assert activation.ensure_running()["ready"] is True

    monkeypatch.setattr(
        ol, "start", lambda **k: {"started": True, "ready": False, "note": "still starting"}
    )
    out = activation.ensure_running()
    assert out["started"] is True and out["ready"] is False
    assert out["detail"] == "still starting"


def test_a_launch_failure_is_a_sentence_not_an_exception(monkeypatch):
    """The caller is a button. A stack trace is not an answer to "please start"."""
    _machine(monkeypatch, gpu=False, ollama_installed=True)
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setattr(
        ol, "start", lambda **k: (_ for _ in ()).throw(ol.OllamaLifecycleError("no binary"))
    )
    out = activation.ensure_running()
    assert out["started"] is False and out["ready"] is False
    assert out["error"] is True
    assert "no binary" in out["detail"]


def test_the_plan_reports_both_backends_so_the_alternative_is_visible(monkeypatch):
    _machine(monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True)
    cands = activation.activation_plan()["candidates"]
    assert set(cands) == {"vllm", "ollama"}
    assert cands["ollama"]["installed"] is True


# --------------------------------------------------------------------------- #
#  The rule has ONE home
# --------------------------------------------------------------------------- #
def test_activation_and_provisioning_share_one_precedence_rule():
    """A second copy of "which backend" is how two surfaces begin disagreeing about
    the same machine -- the defect the 2026-08-02 field report was."""
    import inspect

    from src.api import llm as api_llm

    src = inspect.getsource(activation.activation_plan)
    assert "provisioning_backend" in src, "activation must not re-derive the precedence"
    assert "provisioning_backend" in inspect.getsource(api_llm._provisioning_backend)


def test_the_coordinator_starts_a_backend_before_it_sweeps():
    """The field defect itself: the lane probed a backend nothing had started, then
    spent its retry budget. Behavioural coverage lives in the endpoint tests; this
    pins that the call site exists at all, since its absence is invisible."""
    import inspect

    from src.api import diagnostics

    src = inspect.getsource(diagnostics.ai_coordinator_run)
    assert "ensure_running" in src
    assert "409" in src or "status_code=409" in src


@pytest.mark.parametrize("bad", ["", "  ", "nonsense", "OLLAMA!"])
def test_a_meaningless_override_falls_back_rather_than_erroring(monkeypatch, bad):
    _machine(monkeypatch, gpu=False, ollama_installed=True)
    plan = activation.activation_plan(override=bad)
    assert plan["backend"] == "ollama"
    assert plan["override"] is None
