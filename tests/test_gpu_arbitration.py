"""
One GPU, two backends: Ollama must let go before vLLM starts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD REPORT 2026-08-05. vLLM started five times in ten minutes and exited 1 every
time, while the operator watched VRAM climb and vanish -- and, decisively, reported
that the card was NEVER saturated: roughly 900 MB was still free at the peak. That
last fact is what rules out a plain out-of-memory crash and points at the real
mechanism: ``gpu_memory_utilization`` is a fraction of the card's TOTAL memory, so a
budget computed from the total asks for memory another process is already holding,
and vLLM refuses that request up front rather than filling the card and dying.

Two things were missing, and both are fixed here:

  * nothing ever asked Ollama to release the card before starting vLLM -- and there
    is deliberately no ``ollama_lifecycle.stop()``, because that daemon is usually not
    ours to kill, so the release had to be a request the daemon already honours;
  * ``detect_gpu()`` read ``memory.total`` only, so the budget described a card that
    was not there.

The tests below pin both directions of each: the release happens and is reported, and
it never becomes a fabricated refusal on a machine where nothing is holding anything.
"""

from __future__ import annotations

import pytest

from src.llm import ollama_lifecycle as OL
from src.llm import vllm_lifecycle as V


@pytest.fixture(autouse=True)
def _isolate_venv(tmp_path, monkeypatch):
    """Same isolation the sibling suite uses: a per-test venv dir, and ``_proc`` reset
    so a fake process left alive by one test does not make the next one read as
    "already running"."""
    monkeypatch.setenv("OO_VLLM_VENV_DIR", str(tmp_path / "vllm_venv"))
    V._proc = None
    V._history_disabled = False
    V._history_disabled_reason = None
    yield
    V._proc = None
    V._history_disabled = False
    V._history_disabled_reason = None


class _FakeClient:
    """Stands in for OllamaClient. Records what was asked of it, so a test can assert
    that the daemon was never STOPPED -- only asked to drop residency."""

    def __init__(self, loaded=None, *, available=True, accepts=True, **kw):
        self._loaded = list(loaded or [])
        self._available = available
        self._accepts = accepts
        self.calls: list[tuple[str, str]] = []

    def is_available(self):
        self.calls.append(("is_available", ""))
        return self._available

    def loaded_models(self):
        self.calls.append(("loaded_models", ""))
        return list(self._loaded)

    def unload(self, model):
        self.calls.append(("unload", model))
        if self._accepts:
            self._loaded = [m for m in self._loaded if m["model"] != model]
        return self._accepts


@pytest.fixture()
def fake_ollama(monkeypatch):
    """Install a fake client factory and return a handle to the instance it made."""
    made: list[_FakeClient] = []

    def _install(loaded=None, **kw):
        def factory(*a, **kwargs):
            c = _FakeClient(loaded, **kw)
            made.append(c)
            return c

        monkeypatch.setattr("src.llm.ollama.OllamaClient", factory)
        monkeypatch.setattr(OL, "is_installed", lambda: kw.pop("installed", True))
        return made

    return _install


# --------------------------------------------------------------------------- #
# release_vram -- a request, never a kill
# --------------------------------------------------------------------------- #
def test_every_resident_model_is_released_and_reported(fake_ollama):
    made = fake_ollama([
        {"model": "ministral-3:8b", "vram_bytes": 4_400_000_000, "size_bytes": 4_600_000_000},
        {"model": "nomic-embed", "vram_bytes": 300_000_000, "size_bytes": 300_000_000},
    ])
    out = OL.release_vram()
    assert [r["model"] for r in out["released"]] == ["ministral-3:8b", "nomic-embed"]
    # Real numbers, so a caller can say what was recovered rather than "some memory".
    assert out["released"][0]["vram_bytes"] == 4_400_000_000
    assert made[0].calls[-2:] == [("unload", "ministral-3:8b"), ("unload", "nomic-embed")]


def test_freeing_the_card_never_stops_the_daemon(fake_ollama, monkeypatch):
    """THE CONSTRAINT this whole design bends around: freeing the GPU means dropping
    model RESIDENCY, a request Ollama already exposes and reverses itself on the next
    call. Killing the process is a different act.

    Pinned as behaviour rather than as ``not hasattr(OL, "stop")``. A stop() now exists
    (2026-08-10) and refuses any daemon this app did not spawn -- but the property that
    matters here is narrower and unchanged: the RELEASE path must never reach it, so a
    machine whose Ollama is a system service keeps running it while the card is handed
    to vLLM.
    """
    made = fake_ollama([{"model": "m", "vram_bytes": 1, "size_bytes": 1}])
    stopped: list = []
    monkeypatch.setattr(OL, "stop", lambda **kw: stopped.append(kw) or {})
    monkeypatch.setattr("os.kill", lambda *a, **kw: stopped.append(a))

    OL.release_vram()

    assert stopped == [], "the release path reached for a stop"
    assert {c[0] for c in made[0].calls} <= {"is_available", "loaded_models", "unload"}


def test_an_ollama_that_is_holding_nothing_is_a_clean_no_op(fake_ollama):
    fake_ollama([])
    out = OL.release_vram()
    assert out["released"] == [] and out["attempted"] is True
    assert "holding nothing" in out["reason"]


def test_an_absent_or_unreachable_ollama_is_a_reason_not_an_error(monkeypatch, fake_ollama):
    monkeypatch.setattr(OL, "is_installed", lambda: False)
    assert OL.release_vram() == {
        "released": [], "reason": "Ollama is not installed", "attempted": False
    }
    fake_ollama([], available=False)
    assert "not running" in OL.release_vram()["reason"]


def test_a_client_that_explodes_never_blocks_a_start(monkeypatch):
    """A courtesy release is not allowed to become the thing that stops vLLM."""
    monkeypatch.setattr(OL, "is_installed", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("src.llm.ollama.OllamaClient", boom)
    out = OL.release_vram()
    assert out["released"] == [] and "connection reset" in out["reason"]


# --------------------------------------------------------------------------- #
# clear_gpu_for_vllm -- measure, release, measure again
# --------------------------------------------------------------------------- #
def test_the_reading_is_taken_before_and_after_so_the_gain_is_real(monkeypatch):
    """before/after is the honest form: it states what was recovered instead of
    asserting that something was."""
    readings = iter([3700, 3700, 8100, 8100])
    monkeypatch.setattr(V, "_free_vram_mb", lambda: next(readings, 8100))
    monkeypatch.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [{"model": "m", "vram_bytes": 4_400_000_000}], "attempted": True},
    )
    out = V.clear_gpu_for_vllm(settle=1.0)
    assert out["free_mb_before"] == 3700
    assert out["free_mb_after"] == 8100
    assert out["ollama"]["released"]


def test_nothing_released_means_nothing_waited_for(monkeypatch):
    """The settle wait is paid only when there is something to settle. Charging every
    start for the worst case is how a fix becomes a tax."""
    monkeypatch.setattr(V, "_free_vram_mb", lambda: 8100)
    monkeypatch.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": "Ollama was holding nothing"},
    )
    out = V.clear_gpu_for_vllm(settle=5.0)
    assert out["waited_s"] == 0.0
    assert out["free_mb_before"] == out["free_mb_after"] == 8100


def test_a_gpu_that_cannot_be_read_still_clears_without_claiming_numbers(monkeypatch):
    monkeypatch.setattr(V, "_free_vram_mb", lambda: None)
    monkeypatch.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [{"model": "m", "vram_bytes": None}], "attempted": True},
    )
    out = V.clear_gpu_for_vllm(settle=1.0)
    assert out["free_mb_before"] is None and out["free_mb_after"] is None


# --------------------------------------------------------------------------- #
# start() -- the chokepoint every entry point goes through
# --------------------------------------------------------------------------- #
@pytest.fixture()
def installed_gpu(monkeypatch):
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr(V, "is_running", lambda: False)
    return monkeypatch


def _gpu(monkeypatch, *, total=8188, free=None):
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu",
        lambda: {"available": True, "vram_mb": total, "vram_free_mb": free},
    )


class _FakeProc:
    pid = 99

    def poll(self):
        return None


def test_the_start_clears_the_card_before_it_sizes_the_budget(installed_gpu):
    """Order matters: a free reading taken before the release describes the machine we
    are about to change. Driven through the real start(), because the direct endpoint
    POST /api/llm/vllm/start reaches it without passing activation -- a gate on one
    entry point is not a gate."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=3700)
    seen: dict = {}
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: seen.setdefault("asked", True)
        and {"released": [{"model": "m", "vram_bytes": 1}], "attempted": True}
        or {"released": [{"model": "m", "vram_bytes": 1}], "attempted": True},
    )
    # After the release the card reads free; the budget must use THAT.
    mp.setattr(V, "_free_vram_mb", lambda: 8100)
    out = V.start("someorg/tiny-1b", popen=lambda *a, **k: _FakeProc())
    assert seen.get("asked") is True
    assert out["server_args"]["gpu_memory_utilization"] >= 0.75, (
        "the budget was sized before the release, not after"
    )
    assert out["vram_release"]["free_mb_after"] == 8100


def test_the_journal_records_what_was_freed(installed_gpu):
    """A start that failed for want of memory should say what the card looked like at
    the moment it was attempted -- the whole reason the journal exists."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=8100)
    mp.setattr(V, "_free_vram_mb", lambda: 8100)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": "Ollama was holding nothing"},
    )
    V.start("someorg/tiny-1b", popen=lambda *a, **k: _FakeProc())
    last = V.start_history(limit=1)[-1]
    assert last["event"] == "spawned"
    assert last["vram_release"]["free_mb_after"] == 8100


def test_a_card_someone_else_is_holding_is_refused_by_name(installed_gpu):
    """The sibling of the existing too-large refusal: the model fits the HARDWARE and
    not the MOMENT. Silence here is what reached the field as "exited immediately
    (code 1)" on a card that was never even full."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=1200)
    mp.setattr(V, "_free_vram_mb", lambda: 1200)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": "Ollama declined to unload"},
    )
    with pytest.raises(V.VllmUnsupportedError) as exc:
        V.start("someorg/tiny-7b", popen=lambda *a, **k: pytest.fail("must not spawn"))
    msg = str(exc.value)
    # BOTH numbers, because either alone is unactionable: what the model needs, and
    # what was actually free -- not the card's size, which is what the operator would
    # otherwise reasonably assume was available.
    assert "needs about 7.0 GB" in msg
    assert "only 1.2 GB of this 8.0 GB GPU is free" in msg
    assert "nvidia-smi" in msg, "the refusal must be actionable, not just true"


def test_but_a_card_with_room_starts_normally(installed_gpu):
    """THE TWIN. An over-eager refusal would break every healthy machine, and would be
    invisible -- it reads as caution."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=8100)
    mp.setattr(V, "_free_vram_mb", lambda: 8100)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": "Ollama was holding nothing"},
    )
    assert V.start("someorg/tiny-1b", popen=lambda *a, **k: _FakeProc())["started"] is True


def test_no_free_reading_never_refuses(installed_gpu):
    """A missing measurement is not a measurement of zero. On a driver that reports no
    free figure, the start proceeds exactly as it did before this existed."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=None)
    mp.setattr(V, "_free_vram_mb", lambda: None)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": False, "reason": "Ollama is not installed"},
    )
    assert V.start("someorg/tiny-7b", popen=lambda *a, **k: _FakeProc())["started"] is True


def test_an_operator_override_still_starts_a_doomed_looking_server(installed_gpu):
    """allow_oversized is the operator saying they know better. It must mean that in
    both refusals, or it is only half an override."""
    mp = installed_gpu
    _gpu(mp, total=8188, free=1200)
    mp.setattr(V, "_free_vram_mb", lambda: 1200)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": None},
    )
    out = V.start("someorg/tiny-7b", allow_oversized=True, popen=lambda *a, **k: _FakeProc())
    assert out["started"] is True


def test_the_server_is_told_the_concurrency_the_app_will_actually_use(installed_gpu):
    """--max-num-seqs is DERIVED from the app's own bound, never a second number to
    keep in sync. It caps the activation peak vLLM's startup profiling sizes for."""
    from src.llm.concurrency import concurrency_for

    mp = installed_gpu
    _gpu(mp, total=8188, free=8100)
    mp.setattr(V, "_free_vram_mb", lambda: 8100)
    mp.setattr(
        "src.llm.ollama_lifecycle.release_vram",
        lambda **k: {"released": [], "attempted": True, "reason": None},
    )
    seen: dict = {}
    V.start("someorg/tiny-1b", popen=lambda argv, **k: seen.setdefault("argv", argv) or _FakeProc())
    argv = seen["argv"]
    assert argv[argv.index("--max-num-seqs") + 1] == str(concurrency_for("vllm"))


# --------------------------------------------------------------------------- #
#  "Nothing was serving" is a state a run has to be able to restore.
#
#  Field report 2026-08-12: "I did the model benchmark, and noticed the last model
#  didn't unload from memory." The bench read the prior holder and handed the card
#  back afterwards -- correct whenever something WAS serving, and a no-op when
#  nothing was, which left whatever it had last benched holding the card. On vLLM
#  that is the server's whole lifetime, so the sitting that ran next found no GPU
#  and fell back to the CPU.
# --------------------------------------------------------------------------- #
def test_a_run_that_found_nothing_serving_leaves_nothing_serving(monkeypatch):
    """THE ONE THAT MATTERS. Against the pre-fix code this returned "nothing to
    restore" and released nothing."""
    from src.llm import arbitration as A

    released: list[str] = []
    monkeypatch.setattr(
        A, "release_backend",
        lambda b: (released.append(b), {"backend": b, "released": True, "method": "test"})[1],
    )
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)

    out = A.restore_or_release(None)

    assert out["action"] == "release"
    assert out["restored"] is True
    assert sorted(released) == ["ollama", "vllm"], (
        "a cold-start run must release BOTH backends -- releasing only the one it "
        "happened to end on leaves the other holding the card"
    )
    assert "nothing is serving after it" in out["reason"]


def test_a_release_that_freed_nothing_says_so_rather_than_claiming_a_gain(monkeypatch):
    """The negative-space twin: reporting a release that did not happen would be a
    fabricated tidy-up."""
    from src.llm import arbitration as A

    monkeypatch.setattr(A, "release_backend", lambda b: {"backend": b, "released": False})
    monkeypatch.setattr(A, "free_vram_mb", lambda: 8000)

    out = A.restore_or_release(None)
    assert out["released"] == []
    assert "nothing was left holding the card" in out["reason"]


def test_a_backend_that_WAS_serving_is_handed_back_not_released(monkeypatch):
    """The other direction, which must not regress: a run that found Ollama serving
    puts Ollama back, rather than leaving the machine on nothing."""
    from src.llm import arbitration as A

    handed: list[tuple] = []
    monkeypatch.setattr(A, "current_holder", lambda: {"backend": "vllm", "model": "x"})
    monkeypatch.setattr(
        A, "hand_gpu_to",
        lambda b, **kw: (handed.append((b, kw.get("model"))), {"ready": True})[1],
    )

    out = A.restore_or_release({"backend": "ollama", "model": None})
    assert out["action"] == "restore" and out["restored"] is True
    assert handed == [("ollama", None)]


def test_a_vllm_prior_whose_model_is_unknown_is_left_alone(monkeypatch):
    """Restarting on the default would put the machine on a model it was not on --
    a silent change, which is worse than a stated gap."""
    from src.llm import arbitration as A

    monkeypatch.setattr(A, "hand_gpu_to", lambda b, **kw: pytest.fail("must not guess a model"))
    out = A.restore_or_release({"backend": "vllm", "model": None})
    assert out["restored"] is False and "could not be read" in out["reason"]


def test_the_bench_no_longer_treats_a_cold_start_as_nothing_to_do(monkeypatch):
    """The bench's own path, since that is where it was reported."""
    from src.ai_layer import model_bench as MB

    called: list = []
    monkeypatch.setattr(
        "src.llm.arbitration.restore_or_release",
        lambda prior: (called.append(prior), {"action": "release", "restored": True})[1],
    )
    out = MB._restore_holder(None, switch=lambda **kw: pytest.fail("no switch here"))
    assert called == [None], "a cold-start restore must reach the release path"
    assert out is not None and out["action"] == "release", (
        "returning None here is what left the last benched model resident"
    )
