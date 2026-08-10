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


def test_an_unowned_vllm_is_refused_with_the_path_that_would_have_matched(monkeypatch):
    from src.llm import vllm_lifecycle as VL

    monkeypatch.setattr(VL, "_proc", None)
    monkeypatch.setattr(VL, "is_running", lambda **_kw: True)
    monkeypatch.setattr(VL, "_adoptable_server_pids", list)

    out = VL.stop()

    assert out["stopped"] is False
    assert "managed venv" in out["reason"]


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
    monkeypatch.setattr(A, "_is_ready", lambda _b: True)
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
    monkeypatch.setattr(A, "_is_ready", lambda _b: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b: "still loading its model")
    monkeypatch.setattr(A, "free_vram_mb", lambda: 1000)

    out = A.hand_gpu_to("vllm", model="m")

    assert out["ready"] is False
    assert out["reason"] == "still loading its model"


def test_a_start_that_raises_is_recorded_not_propagated(monkeypatch):
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(
        A, "_start", lambda _b, _m: (_ for _ in ()).throw(RuntimeError("no CUDA here"))
    )
    monkeypatch.setattr(A, "_is_ready", lambda _b: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b: "exited")
    monkeypatch.setattr(A, "free_vram_mb", lambda: None)

    out = A.hand_gpu_to("vllm", model="m")

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


def test_no_field_name_carries_a_banned_substring(monkeypatch):
    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b, "released": False})
    monkeypatch.setattr(A, "_start", lambda _b, _m: {"started": True})
    monkeypatch.setattr(A, "_is_ready", lambda _b: True)
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
    monkeypatch.setattr(A, "_is_ready", lambda _b: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b: "the vLLM server exited during startup")
    monkeypatch.setattr(A, "free_vram_mb", lambda: 500)

    out = A.hand_gpu_to("vllm", model="m")

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
    monkeypatch.setattr(A, "_is_ready", lambda _b: False)
    monkeypatch.setattr(A, "_why_not_ready", lambda _b: "the vLLM server exited during startup")
    monkeypatch.setattr(A, "free_vram_mb", lambda: 7000)

    assert A.hand_gpu_to("vllm", model="m")["reason"] == "the vLLM server exited during startup"
