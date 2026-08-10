"""One card, two backends, and a bench that has to keep swapping which one holds it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-10: "I'm not sure the app is currently able to manage turning
ollama service on / off, I'm not sure for vLLM. Fix this otherwise the automated AI
tests won't be useful."

The direction is what these tests pin, because both mistakes are easy and neither is
visible in a diff:

  * a ``stop`` that reaches an Ollama daemon the operator started would break the
    ruling this module narrows (their terminal, their systemd unit, their other work),
    so the refusal has to be tested as a PRODUCTION path, not assumed;
  * a ``stop`` that refuses a vLLM server THIS app installed -- merely because the app
    was restarted since -- leaves the card occupied and the bench unable to proceed,
    which is the gap that made the ask necessary.

And the asymmetry between them is deliberate: making room for vLLM must never stop
Ollama, only ask it to drop residency.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from src.llm import arbitration as A
from src.llm import ollama_lifecycle as OL


# --------------------------------------------------------------------------- #
#  Ollama: ours to stop, or the machine's?
# --------------------------------------------------------------------------- #
def test_stopping_a_daemon_we_did_not_start_is_refused_by_name(monkeypatch):
    """THE LOAD-BEARING NEGATIVE. A running daemon nobody here spawned belongs to the
    machine, and the refusal must say so AND point at what does work instead."""
    monkeypatch.setattr(OL, "_proc", None)
    monkeypatch.setattr(OL, "is_running", lambda **_kw: True)

    out = OL.stop()

    assert out["stopped"] is False
    assert out["owned"] is False
    assert "not started by this app" in out["reason"]
    assert "release_vram" in out["reason"], "a refusal owes the caller the way forward"


def test_a_daemon_this_process_started_is_ours_to_stop():
    """The one case the narrowing allows. Uses a real child process rather than a
    double: ``stop`` terminates a ``Popen``, and a fake that merely records the call
    would pass whether or not the process ever ended."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        OL._proc = proc
        assert OL.owns_daemon() is True

        out = OL.stop(timeout=5)

        assert out == {"stopped": True, "owned": True}
        assert proc.poll() is not None, "the process must actually be gone"
        assert OL.owns_daemon() is False, "ownership is released with the process"
    finally:
        if proc.poll() is None:  # pragma: no cover - only on a failed stop
            proc.kill()
        OL._proc = None


def test_a_dead_handle_is_not_ownership(monkeypatch):
    """A tracked-but-exited daemon is not ours to stop either — the operator may have
    restarted it by other means, and the handle we hold says nothing about who owns
    the one now answering."""
    class _Dead:
        def poll(self):
            return 0

    monkeypatch.setattr(OL, "_proc", _Dead())
    monkeypatch.setattr(OL, "is_running", lambda **_kw: True)

    assert OL.owns_daemon() is False
    assert OL.stop()["owned"] is False


def test_state_publishes_ownership_so_a_control_is_not_offered_blind(monkeypatch):
    monkeypatch.setattr(OL, "_proc", None)
    monkeypatch.setattr(OL, "is_installed", lambda: True)
    monkeypatch.setattr(OL, "is_running", lambda **_kw: True)

    s = OL.state()

    assert s["owned"] is False
    assert s["can_stop"] is False, "offering a stop that will refuse is worse than none"


# --------------------------------------------------------------------------- #
#  vLLM: a server we installed, from a process that has since restarted
# --------------------------------------------------------------------------- #
def test_only_a_server_from_our_own_venv_is_adoptable(tmp_path, monkeypatch):
    """The ownership claim is the executable's PATH, not the port. A vLLM the operator
    runs from their own environment answers on the same port and must be left alone."""
    from src.llm import vllm_lifecycle as VL

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    monkeypatch.setattr(VL, "venv_dir", lambda: venv)

    ours = [str(venv / "bin" / "vllm"), "serve", "some/model"]
    theirs = ["/usr/local/bin/vllm", "serve", "some/model"]
    not_a_server = [str(venv / "bin" / "python"), "-m", "pip", "install", "vllm"]

    seen = _fake_proc_scan(monkeypatch, VL, {101: ours, 202: theirs, 303: not_a_server})

    assert seen() == [101]


def test_both_of_server_argv_s_own_launch_shapes_are_recognised(tmp_path, monkeypatch):
    """DERIVED FROM THE BUILDER, not from a hand-written command line.

    ``server_argv`` produces two shapes -- the console script, and a module fallback for
    installs where that entry point is absent. An earlier cut of the matcher recognised
    only the first, so on exactly the layout the fallback exists for, ``stop`` would
    have refused to adopt a server this app had started. Generating the argv here means
    a change to how the server is launched cannot leave the matcher behind.
    """
    from src.llm import vllm_lifecycle as VL

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    monkeypatch.setattr(VL, "venv_dir", lambda: venv)
    monkeypatch.setattr(VL, "venv_bin", lambda n: venv / "bin" / n)
    monkeypatch.setattr(VL, "venv_python", lambda: venv / "bin" / "python")

    # (a) the console script is present -> `vllm serve <model>`
    (venv / "bin" / "vllm").write_text("#!/bin/sh\n", encoding="utf-8")
    console = VL.server_argv("org/model", port=8001)
    assert VL._looks_like_our_server(console), console

    # (b) it is absent -> the module fallback, which the first cut missed entirely
    (venv / "bin" / "vllm").unlink()
    module = VL.server_argv("org/model", port=8001)
    assert module != console, "the fixture did not actually exercise the second shape"
    assert VL._looks_like_our_server(module), module


def test_another_tool_from_the_same_venv_is_not_a_server():
    """The ownership half is the venv; this half stops us terminating a pip install
    that happens to be running out of it."""
    from src.llm import vllm_lifecycle as VL

    assert not VL._looks_like_our_server(["/v/bin/python", "-m", "pip", "install", "vllm"])
    assert not VL._looks_like_our_server(["/v/bin/vllm", "--help"])
    assert not VL._looks_like_our_server([])


def test_an_unowned_vllm_is_refused_with_the_path_that_would_have_matched(monkeypatch):
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "_proc", None)
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL, "_adoptable_server_pids", list)

    out = VL.stop()

    assert out["stopped"] is False
    assert "managed venv" in out["reason"]
    # A refusal owes the caller the way forward -- the Ollama one points at
    # release_vram(), and this one is what an operator hits when the bench cannot
    # switch models on a server they started by hand.
    assert "Settings" in out["reason"] and "start it from" in out["reason"]


def test_stop_without_adopt_keeps_the_old_narrow_answer(monkeypatch):
    """The previous behaviour stays reachable, so a caller that genuinely means "only
    if you spawned it in this process" can still say so."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "_proc", None)
    assert VL.stop(adopt=False) == {"stopped": False, "reason": "not tracked by this process"}


def _fake_proc_scan(monkeypatch, VL, table: dict[int, list[str]]):
    """Drive the real ``_adoptable_server_pids`` over a synthetic /proc."""
    import pathlib

    class _Entry:
        def __init__(self, pid: int, argv: list[str]) -> None:
            self.name = str(pid)
            self._argv = argv

        def __truediv__(self, other):
            assert other == "cmdline"
            return self

        def read_bytes(self):
            return b"\0".join(a.encode() for a in self._argv) + b"\0"

    class _Root:
        def is_dir(self):
            return True

        def iterdir(self):
            return [_Entry(pid, argv) for pid, argv in table.items()]

    real_path = pathlib.Path
    monkeypatch.setattr(
        VL, "Path", lambda p: _Root() if str(p) == "/proc" else real_path(p)
    )
    return lambda: sorted(VL._adoptable_server_pids())


# --------------------------------------------------------------------------- #
#  The asymmetry: what "make room" means for each backend
# --------------------------------------------------------------------------- #
def test_making_room_for_vllm_unloads_ollama_and_never_stops_it(monkeypatch):
    """THE RULING, as a test. Ollama drops model residency and keeps running; it
    reloads on its next request, so nothing the operator started is stopped."""
    calls: list[str] = []
    monkeypatch.setattr(
        OL, "release_vram", lambda **_kw: (calls.append("release"), {"released": [{"model": "m"}]})[1]
    )
    monkeypatch.setattr(OL, "stop", lambda **_kw: calls.append("stop") or {})
    monkeypatch.setattr(A, "free_vram_mb", lambda: 4000)

    out = A.release_backend("ollama")

    assert calls == ["release"], "stop() must not be reached for Ollama"
    assert out["method"] == "unload-models"
    assert out["released"] is True


def test_making_room_for_ollama_stops_vllm(monkeypatch):
    """vLLM holds its allocation for its whole lifetime and exposes no 'let go', so
    the only way to give the card back is to stop the server."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL, "stop", lambda **_kw: {"stopped": True, "how": "adopted"})
    monkeypatch.setattr(A, "free_vram_mb", lambda: 7000)

    out = A.release_backend("vllm")

    assert out["method"] == "stop-server"
    assert out["released"] is True


def test_releasing_a_backend_that_holds_nothing_is_a_clean_no_op(monkeypatch):
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: False)
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)

    out = A.release_backend("vllm")

    assert out["released"] is False
    assert out["method"] == "none"
    assert out["free_mb_before"] == out["free_mb_after"] == 8000


def test_an_unreadable_card_reports_none_not_zero(monkeypatch):
    """'We could not look' and 'the card is full' lead to opposite decisions, and this
    number is read at the moment a caller decides whether to start something."""
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"vram_free_mb": None})
    assert A.free_vram_mb() is None

    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: (_ for _ in ()).throw(RuntimeError("no driver"))
    )
    assert A.free_vram_mb() is None


# --------------------------------------------------------------------------- #
#  Handing the card over
# --------------------------------------------------------------------------- #
def test_hand_over_releases_every_other_backend_first(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        A, "release_backend", lambda b: (order.append(f"release:{b}"), {"backend": b})[1]
    )
    monkeypatch.setattr(A, "_start", lambda b, m: order.append(f"start:{b}") or {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: True)
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)

    out = A.hand_gpu_to("vllm", model="org/model")

    assert order == ["release:ollama", "start:vllm"], "release before start, never after"
    assert out["ready"] is True
    assert out["model"] == "org/model"


def test_a_backend_that_did_not_come_up_says_why_rather_than_claiming_ready(monkeypatch):
    """A start that was ATTEMPTED is not a backend that is SERVING, and the caller's
    next move is to send it work."""
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b, _m=None: "still loading its model")
    monkeypatch.setattr(A, "free_vram_mb", lambda: 1000)

    out = A.hand_gpu_to("vllm", model="m", wait_ready_s=0.0)

    assert out["ready"] is False
    assert out["reason"] == "still loading its model"


def test_a_start_that_raises_is_recorded_not_propagated(monkeypatch):
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(
        A, "_start", lambda _b, _m: (_ for _ in ()).throw(RuntimeError("no CUDA here"))
    )
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b, _m=None: "exited")
    monkeypatch.setattr(A, "free_vram_mb", lambda: None)

    out = A.hand_gpu_to("vllm", model="m", wait_ready_s=0.0)

    assert "no CUDA here" in out["started"]["error"]
    assert out["ready"] is False


def test_a_still_loading_vllm_is_not_reported_as_a_failure(monkeypatch):
    """The fabricated-failure mirror of the fabricated-success this chain removes: a
    model load runs to tens of seconds, and calling that 'died' would send an operator
    to fix something that is working."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "start_outcome", lambda: {"state": "starting"})

    why = A._why_not_ready("vllm")

    assert "still loading" in why
    assert "not the same as failed" in why


def test_switching_vllm_to_another_model_restarts_it(monkeypatch):
    """vLLM serves ONE model per server. Asking for a second without a restart would
    measure the first under the second's name."""
    from src.llm import vllm_lifecycle as VL

    calls: list[str] = []
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL, "stop", lambda **_kw: calls.append("stop") or {"stopped": True})
    monkeypatch.setattr(VL, "start", lambda m=None, **_kw: calls.append(f"start:{m}") or {})
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/first")
    monkeypatch.setattr(A, "_settle", lambda *_a, **_kw: (8000, 0.0))
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)

    A._start("vllm", "org/second")

    assert calls == ["stop", "start:org/second"]


def test_asking_for_the_model_already_served_does_not_restart(monkeypatch):
    """A needless restart costs a model load, and the bench does this once per pair."""
    from src.llm import vllm_lifecycle as VL

    calls: list[str] = []
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL, "stop", lambda **_kw: calls.append("stop") or {})
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/same")

    out = A._start("vllm", "org/same")

    assert calls == []
    assert out["reason"] == "already running"


def test_a_refused_stop_is_reported_instead_of_being_walked_past(monkeypatch):
    """THE FIELD DEFECT (2026-08-10). ``stop()`` can legitimately refuse -- a server
    this app did not start, or one it could not signal -- and its answer used to be
    discarded. ``start()`` then said "already running" (its word for a live PROCESS,
    not for a served model), and the handover reported success while the previous
    model kept the card."""
    from src.llm import vllm_lifecycle as VL

    started: list[str] = []
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(
        VL, "stop", lambda **_kw: {"stopped": False, "reason": "not started from this app's venv"}
    )
    monkeypatch.setattr(VL, "start", lambda m=None, **_kw: started.append(m) or {})
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/first")

    out = A._start("vllm", "org/second")

    assert started == [], "a refused stop must not be followed by a start attempt"
    assert out["switch_refused"] is True
    assert out["served"] == "org/first"
    assert "org/first" in out["reason"] and "org/second" in out["reason"]
    assert "not started from this app's venv" in out["reason"], "the refusal's own words"


def test_a_refused_switch_is_not_waited_out(monkeypatch):
    """The negative-space twin of the wait: there is nothing to wait FOR when the
    switch was refused, and polling five minutes per pair would turn one honest
    sentence into an hour of stalling on a seven-model roster."""
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(
        A,
        "_start",
        lambda _b, _m: {"started": False, "switch_refused": True, "reason": "serving org/other"},
    )
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(A, "free_vram_mb", lambda: 1000)

    def _never(*_a, **_kw):
        raise AssertionError("a refused switch must not sleep")

    monkeypatch.setattr(A.time, "sleep", _never)

    out = A.hand_gpu_to("vllm", model="org/wanted", wait_ready_s=600.0)

    assert out["ready"] is False
    assert out["reason"] == "serving org/other", "the refusal's reason, not a probe of the aftermath"


def test_readiness_asks_which_model_is_served_not_merely_whether_a_port_answers(monkeypatch):
    """A vLLM server serves ONE model. A port that answers proves some model is
    loaded, which is exactly what made six of seven benched models return nothing
    while the handover reported ready."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/first")

    assert A._is_ready("vllm", "org/first") is True
    assert A._is_ready("vllm", "org/second") is False, "a different model is NOT ready"
    assert A._is_ready("vllm") is True, "with no model named, a live server is the whole claim"


def test_the_mismatch_is_named_rather_than_reported_as_not_answering(monkeypatch):
    """"It is serving something else" and "it is not answering" need different words
    because they need different actions."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/first")

    why = A._why_not_ready("vllm", "org/second")

    assert "org/first" in why and "org/second" in why
    assert "did not take effect" in why


def test_a_server_that_is_still_loading_is_waited_for(monkeypatch):
    """``vllm_lifecycle.start`` returns the moment the process is spawned, so a
    one-shot probe taken straight afterwards reads not-ready for a perfectly healthy
    model load. Without this wait, fixing the readiness probe would simply have moved
    the defect to the other side."""
    probes: list[int] = []

    def _ready(_b, _m=None):
        probes.append(1)
        return len(probes) >= 3

    monkeypatch.setattr(A, "_is_ready", _ready)
    monkeypatch.setattr(A, "_vllm_exited", lambda: False)
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)

    assert A._wait_ready("vllm", "org/model", timeout=60.0) is True
    assert len(probes) == 3


def test_the_wait_is_abandoned_the_moment_the_server_is_known_to_have_died(monkeypatch):
    """The other half: waiting out a server the lifecycle already knows exited is the
    fabricated-patience mirror. Only ``exited`` ends it -- "starting" must not."""
    slept: list[float] = []
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(A, "_vllm_exited", lambda: True)
    monkeypatch.setattr(A.time, "sleep", lambda s: slept.append(s))

    assert A._wait_ready("vllm", "org/model", timeout=600.0) is False
    assert slept == [], "a known death is reported at once, not waited out"


def test_a_zero_timeout_still_probes_once(monkeypatch):
    """So a caller that wants the old one-shot behaviour keeps it exactly."""
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: True)
    monkeypatch.setattr(A, "_vllm_exited", lambda: False)
    assert A._wait_ready("vllm", "m", timeout=0.0) is True


def test_current_holder_names_the_model_for_vllm_and_nothing_when_idle(monkeypatch):
    from src.llm import ollama_lifecycle as OL
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/held")
    assert A.current_holder() == {"backend": "vllm", "model": "org/held"}

    monkeypatch.setattr(VL, "is_running", lambda **_kw: False)
    monkeypatch.setattr(OL, "is_running", lambda **_kw: True)
    assert A.current_holder() == {"backend": "ollama", "model": None}

    monkeypatch.setattr(OL, "is_running", lambda **_kw: False)
    assert A.current_holder()["backend"] is None, "nothing holding it is a real answer"


def test_no_field_name_carries_a_banned_substring(monkeypatch):
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b, "released": False})
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: True)
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)
    banned = ("score", "ranking", "rating", "grade")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(A.hand_gpu_to("vllm", model="m"))


@pytest.mark.parametrize("backend", ["ollama", "vllm"])
def test_every_backend_this_app_can_serve_with_is_arbitrable(backend):
    """A backend the arbitration does not know is one the bench cannot sequence, so
    the two lists must not drift apart."""
    from src.ai_layer.model_bench import BENCH_BACKENDS

    assert backend in BENCH_BACKENDS
    out = A.release_backend(backend)
    assert out["method"] in {"unload-models", "stop-server", "none"}


def test_a_refused_release_reaches_the_reason_for_the_failure_that_follows(monkeypatch):
    """vLLM reports "exited", never "exited because another process held four gigabytes".

    The release refusal is the one fact the failing backend's own diagnosis cannot see,
    so it travels with the reason rather than sitting in a nested step nobody reads.
    """
    monkeypatch.setattr(
        A,
        "release_backend",
        lambda b: {
            "backend": b,
            "released": False,
            "detail": {"reason": "not started by this app"},
        },
    )
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(
        A, "_why_not_ready", lambda _b, _m=None: "the vLLM server exited during startup"
    )
    monkeypatch.setattr(A, "free_vram_mb", lambda: 500)

    out = A.hand_gpu_to("vllm", model="m", wait_ready_s=0.0)

    assert "exited during startup" in out["reason"], "the backend's own diagnosis survives"
    assert "not released by: ollama" in out["reason"]
    assert "not started by this app" in out["reason"]


def test_a_successful_release_adds_nothing_to_the_reason(monkeypatch):
    """The negative-space twin: a start that failed for its own reasons must not be
    given a second, irrelevant cause to chase."""
    monkeypatch.setattr(
        A, "release_backend", lambda b: {"backend": b, "released": True, "detail": {}}
    )
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(
        A, "_why_not_ready", lambda _b, _m=None: "the vLLM server exited during startup"
    )
    monkeypatch.setattr(A, "free_vram_mb", lambda: 7000)

    assert (
        A.hand_gpu_to("vllm", model="m", wait_ready_s=0.0)["reason"]
        == "the vLLM server exited during startup"
    )


def test_only_vllm_is_waited_for(monkeypatch):
    """``ollama_lifecycle.start`` already blocks until the daemon answers or gives up,
    so waiting again for one that has ALREADY failed is the same fabricated patience,
    one backend over."""
    slept: list[float] = []
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b, _m=None: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b, _m=None: "the daemon is not answering")
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)
    monkeypatch.setattr(A.time, "sleep", lambda s: slept.append(s))

    out = A.hand_gpu_to("ollama", wait_ready_s=600.0)

    assert out["ready"] is False
    assert slept == [], "an Ollama start that failed was already waited for"


def test_the_tracked_stop_waits_for_the_port_not_just_for_the_parent(monkeypatch):
    """vLLM runs its engine in CHILD processes, so the parent can be reaped while the
    server still answers and still holds the card. The adopted path always waited for
    the port; this one returned the instant `proc.wait()` came back -- the same
    requirement, one implementation. A caller's next move is to start another model,
    which then reads "already running" and keeps serving the old one."""
    from src.llm import vllm_lifecycle as VL

    class _Proc:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    answering = [True, True, False]  # still up for two polls after the parent is gone
    monkeypatch.setattr(VL, "_proc", _Proc())
    monkeypatch.setattr(VL, "is_running", lambda **_kw: answering.pop(0) if answering else False)
    monkeypatch.setattr(VL.time, "sleep", lambda _s: None)

    out = VL.stop(timeout=5)

    assert out["stopped"] is True
    assert out["port_quiet"] is True, "the stop is only done when nothing answers"
    assert answering == [], "it polled until the port went quiet"


def test_a_stop_whose_port_never_goes_quiet_says_so(monkeypatch):
    from src.llm import vllm_lifecycle as VL

    class _Proc:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(VL, "_proc", _Proc())
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL.time, "sleep", lambda _s: None)

    out = VL.stop(timeout=1)

    assert out["port_quiet"] is False
    assert "still answering" in out["note"]


def test_a_stop_that_did_not_take_is_treated_as_a_refusal(monkeypatch):
    """For the caller it IS one: starting the new model would read "already running"
    and keep serving the old one, which is the whole defect."""
    from src.llm import vllm_lifecycle as VL

    started: list[str] = []
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(
        VL,
        "stop",
        lambda **_kw: {"stopped": True, "port_quiet": False, "note": "still answering after 10s"},
    )
    monkeypatch.setattr(VL, "start", lambda m=None, **_kw: started.append(m) or {})
    monkeypatch.setattr(A, "_served_vllm_model", lambda: "org/first")

    out = A._start("vllm", "org/second")

    assert started == [], "a stop that did not take must not be followed by a start"
    assert out["switch_refused"] is True
    assert "still answering after 10s" in out["reason"]


def test_a_vllm_stop_that_did_not_take_has_released_nothing(monkeypatch):
    """The sibling of the switch-path rule, and the same defect one function over: a
    server still answering is still holding the card, so reporting it as released
    would send Ollama onto memory vLLM has not given back."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(
        VL, "stop", lambda **_kw: {"stopped": True, "port_quiet": False, "note": "still answering"}
    )
    monkeypatch.setattr(A, "free_vram_mb", lambda: 1496)

    out = A.release_backend("vllm")

    assert out["released"] is False, "a stop that did not take released nothing"
    assert out["detail"]["note"] == "still answering"


def test_a_vllm_stop_that_took_is_a_real_release(monkeypatch):
    """The negative-space twin: the ordinary success must survive the new check, and a
    stop path that reports no `port_quiet` at all (an older shape) is not called a
    failure on the strength of an absent field."""
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(A, "free_vram_mb", lambda: 1496)
    monkeypatch.setattr(A, "_settle", lambda *_a, **_kw: (7000, 1.0))

    monkeypatch.setattr(VL, "stop", lambda **_kw: {"stopped": True, "port_quiet": True})
    assert A.release_backend("vllm")["released"] is True

    monkeypatch.setattr(VL, "stop", lambda **_kw: {"stopped": True})
    assert A.release_backend("vllm")["released"] is True, "an absent field is not a failure"
