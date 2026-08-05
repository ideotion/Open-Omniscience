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

import json
import time

import pytest
from fastapi import HTTPException

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
def _spawns_vllm(monkeypatch, *outcomes, log=None):
    """A vLLM ``start`` that succeeds, followed by the tri-state sequence its process
    then goes through. ``sleep`` is injected, so a six-second watch costs nothing."""
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "start", lambda m, **k: {"started": True, "log_path": "/tmp/x"})
    seq = list(outcomes)
    monkeypatch.setattr(vl, "start_outcome", lambda: seq.pop(0) if len(seq) > 1 else seq[0])
    monkeypatch.setattr(vl, "failure_excerpt", lambda **k: log or {"available": False})
    return {"confirm": {"grace": 1.0, "step": 0.25, "sleep": lambda _s: None}}


def test_a_loading_vllm_reports_started_but_not_ready(monkeypatch):
    """A model load takes tens of seconds. Reporting that as ready is the exact
    fabrication both lifecycle modules already refuse to make."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    kw = _spawns_vllm(monkeypatch, {"state": "starting", "pid": 42})
    out = activation.ensure_running(**kw)
    assert out["started"] is True
    assert out["ready"] is False, "spawned is not answering"
    assert "seconds" in out["detail"]


def test_a_vllm_that_comes_up_inside_the_window_is_reported_ready(monkeypatch):
    """The other twin: watching must not turn a fast, successful start into a
    perpetual "starting". A server that answers is answering."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, model="org/Fast-3B")
    kw = _spawns_vllm(monkeypatch, {"state": "starting"}, {"state": "ready", "pid": 7})
    out = activation.ensure_running(**kw)
    assert out["ready"] is True and out["started"] is True
    assert "org/Fast-3B" in out["detail"]


# --------------------------------------------------------------------------- #
#  A start that DIES is a failed start, not a slow one
# --------------------------------------------------------------------------- #
def test_a_vllm_whose_engine_dies_is_not_reported_as_starting(monkeypatch):
    """Field report 2026-08-04: "I just reinstalled the app, and still get the 'local
    model hiccup' error message. vLLM doesn't seem to start."

    ``start()`` returns the moment ``Popen`` succeeds, so this branch used to take
    that as the start succeeding. A child that then died during engine init reported
    ``started: True``, the coordinator's gate accepted it, and the sweep burned its
    whole retry budget on a server that was never coming -- the precise failure
    ``start_outcome()`` was built to expose, and which this module's own comment said
    it must not guess at, one line above where it guessed.
    """
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    kw = _spawns_vllm(
        monkeypatch,
        {"state": "exited", "returncode": 1, "detail": "…", "log_hint": "read the HEAD"},
    )
    out = activation.ensure_running(**kw)
    assert out["started"] is False, "a dead process is not a start in progress"
    assert out["ready"] is False
    assert "exited" in out["detail"] and "code 1" in out["detail"]
    assert "not still loading" in out["detail"], "waiting longer must be ruled out in words"


def test_the_exit_carries_the_servers_own_first_words(monkeypatch):
    """A path to a log file tells the operator to go and find the answer. The answer
    is what turns "vLLM doesn't seem to start" into a fixable fact -- and the HEAD is
    where it is, because EngineCore is a CHILD process whose traceback prints first."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    kw = _spawns_vllm(
        monkeypatch,
        {"state": "exited", "returncode": 1, "log_path": "/v/server.log"},
        log={
            "available": True,
            "signature": "gated-repo",
            "excerpt": "ValueError: gated repo org/Model-3B — accept the licence first",
            "advice": "The model repository requires accepting its licence first.",
        },
    )
    out = activation.ensure_running(**kw)
    assert "gated repo" in out["server_log_head"]
    assert "licence" in out["detail"], "the ADVICE leads, not a chore about reading a log"
    assert out["log_path"] == "/v/server.log"


def test_an_unreadable_log_still_reports_the_exit(monkeypatch):
    """The twin: losing the excerpt must never lose the FAILURE. An exit code with no
    log is still infinitely more than "starting"."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    kw = _spawns_vllm(monkeypatch, {"state": "exited", "returncode": 9})
    out = activation.ensure_running(**kw)
    assert out["started"] is False and "code 9" in out["detail"]
    assert "server_log_head" not in out, "an absent excerpt is absent, never an empty one"


def test_an_untrackable_child_is_not_called_a_failure(monkeypatch):
    """``not-started`` means the lifecycle has no handle on the process -- it does not
    mean the process died. Reporting that as a failed start would be a fabricated
    failure, which is exactly as dishonest as the fabricated success this fixes."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    kw = _spawns_vllm(monkeypatch, {"state": "not-started", "detail": "no handle"})
    out = activation.ensure_running(**kw)
    assert out["started"] is True and out["ready"] is False


def test_a_dead_vllm_falls_back_to_ollama_rather_than_serving_nothing(monkeypatch):
    """The maintainer's ask is "this should work". A GPU machine whose vLLM cannot
    launch, with Ollama installed right there, must end up serving -- the same rule
    the plan already applies to a structural blocker, since a start that exits will
    exit again on the next click."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True)
    kw = _spawns_vllm(monkeypatch, {"state": "exited", "returncode": 1})
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setattr(ol, "start", lambda **k: {"started": True, "ready": True})
    out = activation.ensure_running(**kw)
    assert out["backend"] == "ollama" and out["ready"] is True
    assert out["fell_back_from"]["backend"] == "vllm"
    assert "code 1" in out["fell_back_from"]["blocker"], "the reason is carried, not dropped"
    assert not out.get("error"), "a working backend is not an error"


def test_but_an_explicit_vllm_choice_is_never_second_guessed(monkeypatch):
    """The twin, and the one thing an explicit choice must not be. The operator gets
    the failure they need to see, not a quiet substitution."""
    _machine(
        monkeypatch, gpu=True, vllm_installed=True, ollama_installed=True, override="vllm"
    )
    kw = _spawns_vllm(monkeypatch, {"state": "exited", "returncode": 1})
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setattr(ol, "start", lambda **k: (_ for _ in ()).throw(AssertionError("no")))
    out = activation.ensure_running(override="vllm", **kw)
    assert out["backend"] == "vllm" and out["started"] is False
    assert out["error"] is True
    assert "fell_back_from" not in out


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


# --------------------------------------------------------------------------- #
#  ...and the operator can READ the reason without going to find a log file
# --------------------------------------------------------------------------- #
def test_the_ai_card_keeps_a_failed_start_on_screen():
    """A toast is gone by the time an operator goes looking for the reason, which is
    the whole shape of "vLLM doesn't seem to start"."""
    from tests.js_source_helper import assert_present, function_body, read_static

    js = read_static("app.js")
    hero = function_body(js, "loadAiHero")
    assert_present(hero, "act.last_start", why="the server's answer survives a reload")
    assert_present(hero, "server_log_head", why="the server's own first words belong here")
    assert_present(
        hero, "if (serving) _aiStartFailure = null", why="a stale failure must not outlive a fix"
    )
    start = function_body(js, "aiStartNow")
    assert_present(start, "_aiStartFailure =", why="the start records what it got")


# --------------------------------------------------------------------------- #
#  The coordinator's gate, driven for real
# --------------------------------------------------------------------------- #
def _coordinator(monkeypatch, act, *, installed=("a-model",)):
    """Drive ``ai_coordinator_run`` with a chosen activation result. Route function
    called directly (this file's siblings' style); nothing is spawned or fetched."""
    from src.api import diagnostics as d

    monkeypatch.setattr("src.llm.activation.ensure_running", lambda **k: act)
    monkeypatch.setattr(
        "src.ai_layer.coordinator.enabled_members",
        lambda: [type("M", (), {"key": "keyword_triage"})()],
    )
    # Takes the backend the coordinator actually brought up -- the whole point of the
    # 2026-08-04 identifier fix, so the double has to accept it.
    monkeypatch.setattr("src.api.llm.active_model", lambda backend=None: "a-model")
    monkeypatch.setattr(
        "src.llm.backend.get_client",
        lambda *a, **k: type("C", (), {"list_installed": lambda self: list(installed)})(),
    )
    monkeypatch.setattr(
        d._AI_COORDINATOR_JOB, "start", lambda **kw: {"state": "running", "kind": "ai-coordinator"}
    )
    return d.ai_coordinator_run


def test_the_lane_refuses_when_no_backend_could_be_started(monkeypatch):
    """The field defect's own shape: rather than starting a sweep that will fail every
    batch, say what is missing. Structural, so retrying cannot change it."""
    run = _coordinator(
        monkeypatch,
        {"backend": "vllm", "started": False, "ready": False, "detail": "vLLM is not installed"},
    )
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.status_code == 409
    assert "not installed" in str(e.value.detail)


def test_a_failed_start_hands_the_operator_the_servers_own_output(monkeypatch):
    """"vLLM doesn't seem to start" needs the reason WITH the refusal, not a pointer
    to a log file. Appended to the detail STRING because a dict ``detail`` renders as
    "[object Object]" in the frontend's error helper."""
    run = _coordinator(
        monkeypatch,
        {
            "backend": "vllm",
            "started": False,
            "ready": False,
            "detail": "vLLM's server process exited immediately (code 1)",
            "server_log_head": "ValueError: gated repo — accept the licence first",
        },
    )
    with pytest.raises(HTTPException) as e:
        run()
    assert "gated repo" in str(e.value.detail)


def test_a_running_backend_with_no_model_is_refused_by_name(monkeypatch):
    """The likeliest state after a reinstall: the model store moved into the app's own
    folder, so a healthy daemon can be pointed at an empty directory. The backend is
    REACHABLE, so ``outage_reason()`` says nothing -- which is how this reached the
    operator as "local model hiccup", ten times over."""
    run = _coordinator(
        monkeypatch, {"backend": "ollama", "started": True, "ready": True}, installed=()
    )
    with pytest.raises(HTTPException) as e:
        run()
    assert e.value.status_code == 409
    assert "no model is downloaded" in str(e.value.detail)
    assert "retrying cannot" in str(e.value.detail)


def test_but_a_probe_that_cannot_read_never_refuses(monkeypatch):
    """The twin, and the reason this checks for an EMPTY answer rather than a falsy
    one: an unreadable probe must not become a refusal, or a momentarily unhappy
    server ends a run the backoff exists to survive."""
    run = _coordinator(monkeypatch, {"backend": "ollama", "started": True, "ready": True})
    monkeypatch.setattr(
        "src.llm.backend.get_client",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("probe exploded")),
    )
    assert json.loads(run().body)["started"] is True


def test_and_a_ready_backend_with_a_model_simply_runs(monkeypatch):
    """The negative-space twin for the whole gate: every refusal above must leave the
    working case working, or the fix trades one broken button for another."""
    run = _coordinator(monkeypatch, {"backend": "ollama", "started": True, "ready": True})
    body = json.loads(run().body)
    assert body["started"] is True
    assert body["activation"]["backend"] == "ollama"


def test_a_still_loading_backend_is_started_anyway(monkeypatch):
    """A vLLM engine takes tens of seconds. Refusing there would make the backoff --
    which exists for exactly this -- unreachable."""
    run = _coordinator(monkeypatch, {"backend": "vllm", "started": True, "ready": False})
    assert json.loads(run().body)["started"] is True


def test_a_model_present_only_in_the_old_cache_is_told_apart_from_never_downloaded(
    monkeypatch,
):
    """The regression the 2026-08-04 store move introduced: weights fetched before it
    were still on the disk, and the guard said "not in the local model cache" -- an
    operator with several GB already downloaded, told they had none.

    It is still a REFUSAL (the server is spawned pointed at the app folder, so starting
    would re-fetch the same weights over the clear internet, which is the one egress
    this guard exists to prevent) -- but for the true reason, with the way out."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, model="org/Have-It-8B")
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(
        vl,
        "model_cache_state",
        lambda m: {"cached": True, "location": "legacy", "path": "/home/u/.cache/huggingface"},
    )
    plan = activation.activation_plan()
    assert plan["can_start"] is False
    assert "IS downloaded" in plan["blocker"], "never 'you have not downloaded it'"
    assert "/home/u/.cache/huggingface" in plan["blocker"], "name where it actually is"
    assert "downloaded twice" in plan["blocker"]


def test_and_the_same_model_in_the_app_folder_simply_starts(monkeypatch):
    """The twin. The new location check must not become a second way to refuse a
    perfectly ordinary start."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "model_cache_state", lambda m: {"cached": True, "location": "app"})
    assert activation.activation_plan()["can_start"] is True


def test_the_plan_reports_a_dead_start_on_every_read_not_only_at_click_time(monkeypatch):
    """A click-time watch can only see a death inside its own few seconds. A CUDA OOM
    forty seconds into a model load is just as fatal, and used to leave the card saying
    "starting" forever."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(
        vl,
        "start_outcome",
        lambda: {"state": "exited", "returncode": 2, "detail": "…", "log_path": "/v/s.log"},
    )
    monkeypatch.setattr(
        vl, "failure_excerpt", lambda **k: {"available": True, "excerpt": "CUDA OOM"}
    )
    plan = activation.activation_plan()
    assert plan["last_start"]["returncode"] == 2
    assert plan["last_start"]["server_log_head"] == "CUDA OOM"


def test_but_a_dead_start_never_becomes_a_blocker(monkeypatch):
    """THE load-bearing half. An operator fixes the cause and presses the button again;
    a state that latched until the next SUCCESSFUL start would make the button refuse
    the very retry that would have worked."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "start_outcome", lambda: {"state": "exited", "returncode": 1})
    monkeypatch.setattr(vl, "failure_excerpt", lambda **k: {"available": False})
    plan = activation.activation_plan()
    assert plan["can_start"] is True and plan["blocker"] is None


@pytest.mark.parametrize("state", ["not-started", "starting", "ready"])
def test_and_nothing_is_reported_for_any_other_state(monkeypatch, state):
    """The twin: a permanent notice on a card that is working fine is how a real one
    gets ignored."""
    _machine(monkeypatch, gpu=True, vllm_installed=True)
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "start_outcome", lambda: {"state": state})
    assert "last_start" not in activation.activation_plan()


# --------------------------------------------------------------------------- #
#  Finding the reason, instead of guessing which end of the log holds it
# --------------------------------------------------------------------------- #
def _server_log(tmp_path, monkeypatch, body: str):
    import src.llm.vllm_lifecycle as vl

    p = tmp_path / "server.log"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setattr(vl, "server_log_path", lambda: p)
    return vl


def _real_shaped_log(cause: str) -> str:
    """The operator's 2026-08-04 log, in shape: ~27 KB of banner and engine config,
    the cause, then ~19 KB of the parent re-raising it. Neither end holds the answer."""
    banner = "\n".join(f"(APIServer pid=1) INFO [config.py:{i}] non-default args ..." for i in range(400))
    tail = "\n".join(f"(APIServer pid=1)   File \"vllm/entrypoints/x.py\", line {i}" for i in range(300))
    # The real log puts ~25 lines of EngineCore stack between the config dump and the
    # cause, which is what the excerpt's lead-in is FOR (it names the call site).
    stack = "\n".join(
        f"(EngineCore pid=2) ERROR   File \"vllm/v1/worker/gpu/x.py\", line {i}, in capture"
        for i in range(25)
    )
    return (
        f"{banner}\n"
        "(EngineCore pid=2) ERROR EngineCore failed to start.\n"
        f"{stack}\n"
        "(EngineCore pid=2) ERROR     super().capture_end()\n"
        f"(EngineCore pid=2) ERROR {cause}\n"
        "(EngineCore pid=2) ERROR Search for `cudaErrorMemoryAllocation' in the CUDA docs.\n"
        f"{tail}\n"
        "(APIServer pid=1) RuntimeError: Engine core initialization failed. "
        "See root cause above. Failed core proc(s): {}\n"
    )


def test_the_reason_is_found_even_when_it_is_in_neither_end_of_the_log(tmp_path, monkeypatch):
    """This module got the log's shape wrong TWICE, and the operator's own 46,455-byte
    log is what refuted the second answer.

    The first fix kept the TAIL. The second kept both ends, reasoning that "EngineCore
    is a child process, so its traceback prints FIRST". True, and still wrong: the real
    cause sat 26,914 bytes in — past the 8,000-byte head, before the 8,000-byte tail.
    The head was a banner and a config dump; the tail was "See root cause above."

    Both were guesses about WHERE. So this searches instead."""
    vl = _server_log(tmp_path, monkeypatch, _real_shaped_log("torch.AcceleratorError: CUDA error: out of memory"))
    r = vl.failure_excerpt()
    assert r["available"] is True
    assert "out of memory" in r["excerpt"], "the cause, not an end of the file"
    assert "non-default args" not in r["excerpt"], "the banner is not the reason"
    assert "See root cause above" not in r["excerpt"], "nor is the pointer to it"


def test_a_recognised_failure_is_named_with_what_to_do(tmp_path, monkeypatch):
    """A traceback says what happened; this says what to do about it. The operator's
    card should not have to be read as CUDA documentation."""
    vl = _server_log(tmp_path, monkeypatch, _real_shaped_log("torch.AcceleratorError: CUDA error: out of memory"))
    r = vl.failure_excerpt()
    assert r["signature"] == "cuda-oom"
    assert "ran out of memory" in r["advice"]
    assert "gpu_memory_utilization" in r["advice"], "name the knob that fixes it"


def test_the_cause_beats_the_wrapper_that_points_at_it(tmp_path, monkeypatch):
    """Ordering is the whole design. "Engine core initialization failed. See root cause
    above." matches too, and matching it first would hand back the sentence whose entire
    content is that the answer is somewhere else."""
    vl = _server_log(tmp_path, monkeypatch, _real_shaped_log("torch.AcceleratorError: CUDA error: out of memory"))
    assert vl.failure_excerpt()["signature"] == "cuda-oom"


def test_an_unrecognised_failure_falls_back_rather_than_inventing_one(tmp_path, monkeypatch):
    """The twin. A log with no known signature must not be labelled with the nearest
    one — a fabricated diagnosis is worse than an honest excerpt."""
    vl = _server_log(tmp_path, monkeypatch, "something went wrong in a way we have never seen\n")
    r = vl.failure_excerpt()
    assert r["signature"] is None
    assert "advice" not in r
    assert "never seen" in r["excerpt"]


def test_no_log_at_all_is_an_absence_not_an_empty_string(tmp_path, monkeypatch):
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "server_log_path", lambda: tmp_path / "nope.log")
    assert vl.failure_excerpt()["available"] is False


# --------------------------------------------------------------------------- #
#  The utilization that caused the OOM in the first place
# --------------------------------------------------------------------------- #
def test_utilization_never_gets_more_aggressive_as_the_card_gets_smaller():
    """THE defect, and it is visible as a monotonicity: the old formula published 0.95
    on a 6 GiB card and 0.86 on an 80 GiB one, because the fixed weight reserve was
    added back at full value while only the remainder was discounted. The smallest cards
    — the ones this app is designed around — got the least headroom.

    STRICT direction, per the recorded lesson that a monotonicity assertion over a
    clamped value is satisfied by the constant it exists to catch."""
    from src.llm.vllm_lifecycle import compute_server_args

    seen = [compute_server_args(mb)["gpu_memory_utilization"]
            for mb in (4096, 6144, 8192, 12288, 16384, 24576, 81920)]
    assert seen == sorted(seen), f"utilization must not rise as VRAM falls: {seen}"
    assert seen[0] < seen[-1], "and it must actually VARY, not be a constant"


def test_the_field_card_gets_real_headroom_now():
    """The measurement: on this 8 GiB card the old rule left 0.48 GiB free and CUDA-graph
    capture died at 86% of 51 graphs. The reserve is absolute because the graph pool
    scales with the model and the graph count, not with the card."""
    from src.llm.vllm_lifecycle import compute_server_args

    a = compute_server_args(8192)
    free_gb = 8.0 * (1.0 - a["gpu_memory_utilization"])
    assert free_gb > 1.0, f"only {free_gb:.2f} GiB left for graph capture"
    assert a["gpu_memory_utilization"] <= 0.90, "never more aggressive than vLLM's own default"


def test_but_the_context_length_the_field_proved_works_is_not_regressed():
    """The negative-space twin, and the reason max_model_len keeps its own derivation:
    the field run served 5120 with 24,960 tokens of KV (4.88x concurrency), so this value
    was demonstrably NOT what failed. Tightening it would regress a number the
    measurement says works — conservatism in the wrong place is still a wrong answer."""
    from src.llm.vllm_lifecycle import compute_server_args

    assert compute_server_args(8192)["max_model_len"] == 5120


def test_an_operator_override_is_still_honoured_verbatim():
    from src.llm.vllm_lifecycle import compute_server_args

    a = compute_server_args(8192, gpu_memory_utilization_override=0.97)
    assert a["gpu_memory_utilization"] == 0.97, "an explicit choice is never second-guessed"


# --------------------------------------------------------------------------- #
#  A RUN THAT IS ALREADY GOING CAN BRING ITS OWN BACKEND UP
#
#  Field report 2026-08-04 (third of the chain): "explicit override (vllm), but its
#  server is NOT running -- start it from Settings -> AI". Every word true, and the
#  app was the only thing in a position to act on it. ``ensure_running`` had exactly
#  two callers and both are a human pressing a button, so a background sweep spent its
#  whole budget waiting for a click that a running app has no way to ask for.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _recovery_isolation(monkeypatch):
    """Two process-globals, both of which a shared pytest session gets wrong by default.

    The window is a module global, so one test's timestamp silently disables the next
    test's attempt. And ``conftest`` switches automatic starts OFF for the whole suite
    (a suite must not spawn a daemon on a machine that has one) -- so every test that
    is ABOUT the recovery has to turn the thing it tests back on, explicitly."""
    monkeypatch.setenv("OO_LLM_AUTOSTART", "1")
    activation._recovery_last_at = None
    activation._recovery_last = None
    yield
    activation._recovery_last_at = None
    activation._recovery_last = None


def _records_ensure_running(monkeypatch, **result):
    calls: list[dict] = []

    def _fake(**kw):
        calls.append(kw)
        return {"backend": "vllm", **result}

    monkeypatch.setattr(activation, "ensure_running", _fake)
    return calls


def test_a_reachable_backend_is_never_probed_for_recovery(monkeypatch):
    """``outage_reason()`` returns None precisely when the backend IS reachable, so a
    None here means there is nothing to recover. The negative space matters more than
    the positive: this branch runs on every retry of every sweep, including the ones
    that failed for reasons that have nothing to do with the backend being up."""
    calls = _records_ensure_running(monkeypatch, started=True)
    out = activation.recover_backend(None)
    assert out["attempted"] is False
    assert calls == [], "a reachable backend must not be started, probed or waited on"


def test_a_down_backend_is_started_and_says_so(monkeypatch):
    calls = _records_ensure_running(
        monkeypatch, started=True, ready=False, detail="vLLM is starting on org/M."
    )
    out = activation.recover_backend("explicit override (vllm), but its server is NOT running")
    assert len(calls) == 1
    assert out == {
        "attempted": True,
        "started": True,
        "ready": False,
        "detail": "vLLM is starting on org/M.",
        "backend": "vllm",
    }


def test_a_second_sweep_moments_later_does_not_start_a_second_server(monkeypatch):
    """Four sweeps share one backend and their backoff ladders start at a few seconds.
    Without a floor they would re-run an nvidia-smi and two health probes far more
    often than a start could change anything -- and a model load takes tens of
    seconds, so nothing they learned in between would be new."""
    calls = _records_ensure_running(monkeypatch, started=True)
    first = activation.recover_backend("down")
    second = activation.recover_backend("down")
    assert first["attempted"] is True
    assert second["attempted"] is False and "moments ago" in second["skipped"]
    assert len(calls) == 1


def test_but_the_window_reopens(monkeypatch):
    """The twin: a floor that never lifted would be a one-shot, and a backend that
    goes down an hour into a run would never be brought back."""
    calls = _records_ensure_running(monkeypatch, started=True)
    activation.recover_backend("down")
    activation._recovery_last_at -= activation._RECOVERY_MIN_INTERVAL_S + 1
    assert activation.recover_backend("down")["attempted"] is True
    assert len(calls) == 2


def test_a_recovery_that_raises_never_breaks_the_run(monkeypatch):
    """This runs inside a sweep's failure handler. An exception here would turn a
    retryable outage into a dead job -- the opposite of the point."""

    def _boom(**kw):
        raise RuntimeError("nvidia-smi went missing")

    monkeypatch.setattr(activation, "ensure_running", _boom)
    out = activation.recover_backend("down")
    assert out == {"attempted": True, "started": False, "ready": False, "detail": None}


def test_the_recovery_never_decides_the_retry(monkeypatch):
    """The recorded rule, pinned structurally: a reload, a restart and a busy server
    answer a probe identically, so this may enrich a message and must never end a run.
    It therefore returns words and facts -- no verdict, no budget, no stop."""
    _records_ensure_running(monkeypatch, started=False, ready=False, detail="cannot start")
    out = activation.recover_backend("down")
    assert set(out) <= {"attempted", "started", "ready", "detail", "backend", "skipped"}
    for banned in ("stop", "give_up", "fatal", "terminal", "abort", "retry"):
        assert not any(banned in k for k in out), f"{banned} is a control-flow decision"


# --------------------------------------------------------------------------- #
#  "already running" is not "answering"
# --------------------------------------------------------------------------- #
def _already_running_vllm(monkeypatch, outcome):
    """``start()`` says "already running" for ``process_alive() or is_running()``, and we
    only reach it after the plan's health probe said the backend does NOT answer."""
    import src.llm.vllm_lifecycle as vl

    monkeypatch.setattr(vl, "start", lambda m, **k: {"started": False, "reason": "already running"})
    monkeypatch.setattr(vl, "start_outcome", lambda: outcome)
    monkeypatch.setattr(vl, "failure_excerpt", lambda **k: {"available": False})
    return {"confirm": {"grace": 0.0, "step": 0.0, "sleep": lambda _s: None}}


def test_a_second_start_while_the_engine_loads_is_not_reported_ready(monkeypatch):
    """The defect the recovery path above would have hit on its very first retry: a
    live-but-silent engine came back ``ready: True``, so the coordinator handed a sweep
    to a server that 503s every call -- a fabricated ready, from a word about a process
    rather than a probe of the port."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, model="org/Loading-3B")
    kw = _already_running_vllm(monkeypatch, {"state": "starting", "pid": 9})
    out = activation.ensure_running(**kw)
    assert out["ready"] is False, "a loading engine is not answering"
    assert out["started"] is True, "but a live start IS in flight"
    assert "org/Loading-3B" in out["detail"] and "seconds" in out["detail"]


def test_and_one_that_has_come_up_is_reported_ready(monkeypatch):
    """The twin: the fix must not turn a server that IS answering into a permanent
    "starting", which would refuse every sweep on a perfectly healthy backend."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, model="org/Up-3B")
    kw = _already_running_vllm(monkeypatch, {"state": "ready", "pid": 9})
    out = activation.ensure_running(**kw)
    assert out["ready"] is True and out["started"] is True
    assert "org/Up-3B" in out["detail"]


def test_and_one_that_has_died_reports_the_death(monkeypatch):
    """The third state: a tracked process that exited is neither loading nor serving,
    and saying "already running" about it is the exact confusion start_outcome exists
    to end. Under an explicit vLLM choice, so the death is the whole answer rather
    than a fallback's -- the field scenario exactly."""
    _machine(monkeypatch, gpu=True, vllm_installed=True, override="vllm")
    kw = _already_running_vllm(monkeypatch, {"state": "exited", "returncode": 1})
    out = activation.ensure_running(**kw)
    assert out["ready"] is False
    assert "exited" in out["detail"]


def test_the_very_first_attempt_on_a_fresh_boot_is_not_rate_limited(monkeypatch):
    """``time.monotonic()``'s reference point is undefined and is small on a freshly
    booted machine, so a 0.0 "last attempt" sentinel silently swallowed the first
    attempt of every process -- exactly when the backend is most likely to be down.
    A sentinel that is also a legal value is not a sentinel."""
    calls = _records_ensure_running(monkeypatch, started=True)
    activation._recovery_last_at = None
    monkeypatch.setattr(activation.time, "monotonic", lambda: 3.9)  # 3.9s of uptime
    assert activation.recover_backend("down")["attempted"] is True
    assert len(calls) == 1


def test_the_suite_wide_switch_turns_automatic_starts_off(monkeypatch):
    """The opt-out itself, in both directions: an operator who wants a background run to
    report an outage and never act on it gets exactly that, and nothing is probed."""
    calls = _records_ensure_running(monkeypatch, started=True)
    monkeypatch.setenv("OO_LLM_AUTOSTART", "0")
    out = activation.recover_backend("down")
    assert out == {"attempted": False, "skipped": "automatic starts are switched off"}
    assert calls == []


# --------------------------------------------------------------------------- #
#  WHERE the weights must go, said by the app rather than looked up by the operator
#
#  Field report 2026-08-04: "Tell me where should the model be moved precisely."
#  The blocker named the SOURCE and pointed at a settings page for the destination --
#  the same go-and-find-it-yourself shape this chain has already fixed twice.
# --------------------------------------------------------------------------- #
def test_the_legacy_cache_blocker_names_the_destination_and_a_command_that_works(monkeypatch):
    _machine(monkeypatch, gpu=True, vllm_installed=True, model="org/Weights-3B")
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.model_cache_state",
        lambda m: {
            "cached": True,
            "path": "/home/u/.cache/huggingface/hub/models--org--Weights-3B",
            "location": "legacy",
            "expected": "/data/models/huggingface/hub/models--org--Weights-3B",
            "bytes": 1,
        },
    )
    blocker = activation.activation_plan()["blocker"]
    assert "/home/u/.cache/huggingface/hub/models--org--Weights-3B" in blocker, "the source"
    assert "/data/models/huggingface/hub/models--org--Weights-3B" in blocker, "the DESTINATION"
    # The parent, created first: the app makes HF_HOME on every launch but `hub/` is
    # huggingface_hub's, so on a machine where vLLM never started a bare mv would fail.
    assert "mkdir -p '/data/models/huggingface/hub'" in blocker
    assert "mv '/home/u/.cache/huggingface/hub/models--org--Weights-3B' " in blocker
    # And it no longer sends the operator to a settings page to find the answer.
    assert "Settings" not in blocker


def test_the_expected_path_is_reported_on_every_answer_not_just_the_legacy_one():
    """Including "not downloaded": that is exactly when an operator asks where a
    download will land, and a field that appears only in one branch is a field every
    caller has to re-derive."""
    from src.llm.vllm_lifecycle import hf_cache_dir, model_cache_state

    state = model_cache_state("org/Never-Fetched")
    assert state["cached"] is False
    assert state["expected"] == str(hf_cache_dir() / "models--org--Never-Fetched")


def test_the_folder_the_app_advertises_is_a_folder_the_app_creates(tmp_path, monkeypatch):
    """The negative-space twin of the command above: naming a destination that does not
    exist is only half an answer. A launch prepares HF_HOME *and* its hub/."""
    from src.llm import model_store

    monkeypatch.setattr(model_store, "data_dir", lambda: tmp_path)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    env = model_store.launch_env({})
    hub = tmp_path / "models" / "huggingface" / "hub"
    assert hub.is_dir(), "the path the blocker tells an operator to mv into"
    assert env["HF_HOME"] == str(hub.parent)


def test_a_download_lands_where_the_server_will_look_for_it():
    """The second half of the ask ("make sure any future model download points to the
    proper folder"), pinned structurally rather than trusted: the weights download, the
    server spawn and the cache probe must all derive ONE path. Three call sites that
    agree today can disagree tomorrow, and nothing would say so."""
    import inspect

    from src.llm import vllm_lifecycle as vl

    # SERVE: the process that reads the weights. Through _server_env, which adds the
    # offline flags on top -- so the chain is one hop longer and must still land on
    # the same resolver.
    assert "env=_server_env()" in inspect.getsource(vl.start)
    assert "launch_env()" in inspect.getsource(vl._server_env)
    # DOWNLOAD: the process that writes them, via the shared install env.
    dl = inspect.getsource(vl.run_model_download_job)
    assert "_install_env(" in dl, "the download must not build its own environment"
    assert "launch_env()" in inspect.getsource(vl._install_env)
    # PROBE: the question "is it already here?", which must ask about the same folder.
    assert "hf_home()" in inspect.getsource(vl.hf_cache_dir)


def test_a_rate_limited_call_still_says_what_is_going_on(monkeypatch):
    """Field report 2026-08-04, the fourth: the retry line came back BARE — the
    reachability sentence with no word about what the app had done. The window was
    eating the explanation. A ladder retries at 5s then 10s then 20s, so the first
    call inside a 30s window carried the blocker and every one after it dropped to
    nothing — and the ones after it are what an operator reads, over and over."""
    _records_ensure_running(
        monkeypatch, started=False, ready=False, detail="the weights are not downloaded"
    )
    first = activation.recover_backend("down")
    second = activation.recover_backend("down")
    assert first["attempted"] is True and second["attempted"] is False
    assert second["skipped"] == "a start was attempted moments ago", "and it says it is not new"
    assert second["detail"] == "the weights are not downloaded", "but the truth is carried"
    assert second["started"] is False


def test_and_the_remembered_words_reach_the_retry_line(monkeypatch):
    """End to end, because the composition rule lives in another module: the point of
    remembering is that the sentence an operator reads is the useful one."""
    from src.llm.backend import outage_detail

    _records_ensure_running(monkeypatch, started=True, detail="vLLM is starting on org/M.")
    activation.recover_backend("down")
    line = outage_detail(
        "its server is NOT running", None, recovery=activation.recover_backend("down")
    )
    assert line == "vLLM is starting on org/M."


def test_but_nothing_remembered_leaves_the_line_exactly_as_it_was(monkeypatch):
    """The negative-space twin: a process that has never attempted a recovery, or one
    whose attempt had nothing to say, must not have words invented for it."""
    from src.llm.backend import outage_detail

    activation._recovery_last = None
    activation._recovery_last_at = time.monotonic()  # inside the window, nothing remembered
    rec = activation.recover_backend("its server is NOT running")
    assert rec["attempted"] is False
    assert (
        outage_detail("its server is NOT running", None, recovery=rec)
        == "its server is NOT running"
    )


# --------------------------------------------------------------------------- #
#  SERVE IS OFFLINE, DOWNLOAD IS ONLINE
#
#  Field report 2026-08-05, the cause behind four rounds of "vLLM won't start": the
#  weights were cached and the server still died on
#  "[Errno -3] Temporary failure in name resolution" while doing a HEAD for
#  preprocessor_config.json. huggingface_hub revalidates repo METADATA over the
#  network even when every weight is local.
# --------------------------------------------------------------------------- #
def test_the_server_is_spawned_in_hugging_faces_offline_mode():
    """Not merely the working setting, the HONEST one: activation already refuses to
    start on uncached weights so the server never fetches GB from a subprocess the
    socket guard cannot see. Without this the promise held only for the weights, and
    only because DNS happened to fail."""
    from src.llm.vllm_lifecycle import _server_env

    env = _server_env()
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    # And the store still points at the app folder -- offline must not cost the
    # 2026-08-04 model-store move.
    from src.llm.model_store import hf_home

    assert env["HF_HOME"] == str(hf_home())


def test_but_the_weights_download_is_not(monkeypatch, tmp_path):
    """THE TWIN, and the one that would break everything: the download shares
    launch_env() with the server. Putting the offline flags there would make a model
    impossible to fetch — a fix that trades one dead end for a worse one."""
    from src.llm import model_store

    monkeypatch.setattr(model_store, "data_dir", lambda: tmp_path)
    dl = model_store.launch_env({})
    for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        assert flag not in dl, f"{flag} would make every weights download fail"


def test_the_server_sends_no_usage_statistics():
    """vLLM's usage reporter is opt-OUT. This project sends no telemetry, and a
    bundled subprocess doing it on the app's behalf is the same thing wearing a
    different process id."""
    from src.llm.vllm_lifecycle import _server_env

    env = _server_env()
    assert env["VLLM_NO_USAGE_STATS"] == "1"
    assert env["DO_NOT_TRACK"] == "1"


def test_the_start_actually_uses_that_environment():
    """A helper nothing calls is the recorded dead-end shape. Pinned at the spawn."""
    import inspect

    from src.llm import vllm_lifecycle as vl

    src = inspect.getsource(vl.start)
    assert "env=_server_env()" in src
    assert "env=launch_env()" not in src, "the server must not use the download's env"


def test_a_dns_failure_is_named_rather_than_its_hundred_line_traceback():
    """The operator's log ended in 'Cannot send a request, as the client has been
    closed' -- true, and not the reason. The specific signature must win over the
    generic traceback, and carry advice."""
    from src.llm import vllm_lifecycle as vl

    keys = [k for k, _, _ in vl._FATAL_SIGNATURES]
    assert keys.index("offline") < keys.index("traceback")
    advice = next(a for k, _, a in vl._FATAL_SIGNATURES if k == "offline")
    assert "offline mode" in advice and "cached" in advice
