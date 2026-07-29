"""A vLLM start that fails must SAY WHY, and one that cannot fit must refuse first.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-29: a maintainer set ``mistralai/Ministral-3-8B-Instruct-2512`` as
the vLLM model on an 8 GB GPU and got "doesn't work" — with nothing anywhere in the app
to act on. Two independent defects produced that:

  1. the server was spawned with stdout AND stderr to ``DEVNULL``, so every startup
     failure (gated repo, misspelled id, missing HF token, CUDA OOM) killed the process
     silently and the UI could only ever report "not running";
  2. an 8B model at fp16 needs ~16 GB of WEIGHTS ALONE, so on an 8 GB card it could
     never have started — and nothing checked before launching.

Both directions are pinned here. A refusal that fires on a guess would be its own
fabrication, so ``unknown`` must NOT refuse.
"""

from __future__ import annotations

import subprocess

import pytest

import src.llm.vllm_lifecycle as V


@pytest.fixture()
def gpu8(monkeypatch, tmp_path):
    """An 8 GB CUDA card, vLLM installed, nothing running — the maintainer's machine."""
    monkeypatch.setattr(V, "venv_dir", lambda: tmp_path)
    monkeypatch.setattr(V, "is_installed", lambda: True)
    monkeypatch.setattr(V, "is_running", lambda **kw: False)
    monkeypatch.setattr(V, "process_alive", lambda: False)
    import src.llm.backend as B

    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": True, "name": "RTX", "vram_mb": 8192})
    return tmp_path


# --------------------------------------------------------------------------- #
#  the footprint estimate
# --------------------------------------------------------------------------- #
def test_the_maintainers_model_is_measured_as_too_large_for_8gb():
    """THE reported case. 8B x 2 GB/B = ~16 GB of weights against an 8 GB card."""
    fit = V.vram_fit("mistralai/Ministral-3-8B-Instruct-2512", 8192)
    assert fit["verdict"] == "too_large"
    assert fit["estimate"]["params_b"] == 8
    assert fit["estimate"]["weights_gb"] == 16.0
    assert fit["vram_gb"] == 8.0


def test_a_quantised_variant_of_the_same_family_fits():
    """The point of the estimate is that it discriminates — otherwise it would just be
    a blanket refusal wearing a number."""
    fit = V.vram_fit("ministral-3:3b-instruct-2512-q4_K_M", 8192)
    assert fit["verdict"] == "fits"
    assert fit["estimate"]["quantised"] is True


def test_an_unparseable_name_is_unknown_never_a_guess():
    fit = V.vram_fit("someorg/a-model-with-no-size", 8192)
    assert fit["verdict"] == "unknown"
    assert fit["estimate"]["weights_gb"] is None
    assert fit["estimate"]["confident"] is False


def test_an_unreadable_vram_is_unknown_not_zero():
    """detect_gpu legitimately returns vram_mb=None. Treating that as 0 would refuse
    every model on a card whose size simply could not be read."""
    assert V.vram_fit("mistralai/Ministral-3-8B-Instruct-2512", None)["verdict"] == "unknown"


def test_the_method_string_states_it_read_the_NAME():
    """The figure is a heuristic over the model id, and must never read as a
    measurement of the actual repo."""
    est = V.estimate_weights_gb("mistralai/Ministral-3-8B-Instruct-2512")
    assert "model NAME" in est["method"]
    assert "weights only" in est["method"]


# --------------------------------------------------------------------------- #
#  the refusal
# --------------------------------------------------------------------------- #
def test_start_refuses_the_oversized_model_with_real_numbers(gpu8):
    with pytest.raises(V.VllmUnsupportedError) as exc:
        V.start("mistralai/Ministral-3-8B-Instruct-2512", popen=lambda *a, **k: None)
    msg = str(exc.value)
    assert "16.0 GB" in msg and "8.0 GB" in msg, "the numbers must be IN the refusal"
    assert "quantised" in msg or "AWQ" in msg, "and it must say what to do instead"


def test_the_refusal_is_acknowledgeable(gpu8):
    """The estimate reads the NAME, so a quantised repo that does not advertise it must
    still be startable by an operator who knows better. The guard exists to prevent a
    silent OOM, not to claim knowledge of every model's true footprint."""
    spawned = []
    out = V.start(
        "mistralai/Ministral-3-8B-Instruct-2512",
        allow_oversized=True,
        popen=lambda *a, **k: spawned.append(a) or None,
    )
    assert out["started"] is True
    assert spawned, "acknowledging must actually launch it"


def test_an_unknown_footprint_never_refuses(gpu8):
    """Refusing on a guess would be a fabricated blocker."""
    out = V.start("someorg/a-model-with-no-size", popen=lambda *a, **k: None)
    assert out["started"] is True


def test_a_fitting_model_starts_without_acknowledgement(gpu8):
    out = V.start("someorg/tiny-1b", popen=lambda *a, **k: None)
    assert out["started"] is True


# --------------------------------------------------------------------------- #
#  the output is captured, not discarded
# --------------------------------------------------------------------------- #
def test_the_server_output_is_captured_not_sent_to_devnull(gpu8):
    """The defect itself: stderr to DEVNULL made every failure unknowable."""
    seen = {}

    def _popen(argv, **kw):
        seen.update(kw)
        return None

    V.start("someorg/tiny-1b", popen=_popen)
    assert seen["stdout"] is not subprocess.DEVNULL, "the reason must be kept"
    assert seen["stderr"] is subprocess.STDOUT, "stderr folded into the same capture"
    assert V.server_log_path().exists()


def test_the_log_tail_is_readable_and_bounded(gpu8):
    V.server_log_path().write_bytes(b"x" * 50_000 + b"CUDA out of memory\n")
    tail = V.server_log_tail()
    assert tail["available"] is True
    assert "CUDA out of memory" in tail["tail"], "the END is the actionable part"
    assert tail["truncated"] is True
    assert len(tail["tail"]) <= V._LOG_TAIL_BYTES + 16


def test_a_missing_log_is_a_stated_absence_not_an_empty_string(gpu8):
    tail = V.server_log_tail()
    assert tail["available"] is False
    assert tail["reason"], "silence must be explained, never rendered as 'nothing wrong'"
    assert "tail" not in tail


def test_each_start_truncates_so_the_log_describes_the_CURRENT_attempt(gpu8):
    V.server_log_path().write_bytes(b"stale failure from a previous model\n")
    V.start("someorg/tiny-1b", popen=lambda *a, **k: None)
    assert "stale failure" not in V.server_log_path().read_text(), (
        "a stale log would misattribute an old error to the current attempt"
    )


def test_losing_the_log_never_blocks_the_start(gpu8, monkeypatch):
    """The log is a diagnostic aid. One that can prevent the thing it observes would be
    worse than none (the project's own crash-journal lesson)."""
    monkeypatch.setattr(V, "server_log_path", lambda: gpu8 / "nope" / "deep" / "x.log")
    monkeypatch.setattr(
        V.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    out = V.start("someorg/tiny-1b", popen=lambda *a, **k: None)
    assert out["started"] is True
    assert out["log_path"] is None, "and it says the log is unavailable rather than lying"
