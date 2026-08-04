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
    monkeypatch.setattr(vl, "server_log_tail", lambda **k: log or {"available": False})
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
            "truncated": True,
            "head": "ValueError: gated repo org/Model-3B — accept the licence first",
            "tail": "See root cause above.",
        },
    )
    out = activation.ensure_running(**kw)
    assert "gated repo" in out["server_log_head"]
    assert "root cause above" not in out["server_log_head"], "the TAIL is the wrong end"
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
    monkeypatch.setattr("src.api.llm.active_model", lambda: "a-model")
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
    monkeypatch.setattr(vl, "server_log_tail", lambda **k: {"available": True, "tail": "CUDA OOM"})
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
    monkeypatch.setattr(vl, "server_log_tail", lambda **k: {"available": False})
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
