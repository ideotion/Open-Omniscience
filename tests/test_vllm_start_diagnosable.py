"""A vLLM start that fails must SAY WHY, and one that cannot fit must refuse first.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-29: a maintainer set ``mistralai/Ministral-3-8B-Instruct-2512`` as
the vLLM model on an 8 GB GPU and got "doesn't work" — with nothing anywhere in the app
to act on. Two independent defects produced that:

  1. the server was spawned with stdout AND stderr to ``DEVNULL``, so every startup
     failure (gated repo, misspelled id, missing HF token, CUDA OOM) killed the process
     silently and the UI could only ever report "not running";
  2. the model could not fit that card, and nothing checked before launching. (The
     first fix mis-stated WHY, reporting ~16 GB on an fp16 assumption; Ministral 3's
     Instruct checkpoints actually ship FP8, so it is ~8 GB. Still too large — the
     weights alone meet the card, leaving nothing for the KV cache — but the estimate
     now reports a RANGE and judges on the optimistic end rather than inventing a
     single figure a model NAME cannot support.)

Both directions are pinned here. A refusal that fires on a guess would be its own
fabrication, so ``unknown`` must NOT refuse.
"""

from __future__ import annotations

import subprocess

import pytest

import src.llm.vllm_lifecycle as V
from tests.js_source_helper import app_js


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
    """THE reported case — and the CORRECTION that followed it.

    The first version of this estimate assumed fp16 and published "16.0 GB" to the
    maintainer. That was wrong: Ministral 3's Instruct checkpoints ship in FP8, so the
    8B is ~8 GB of weights. A model NAME does not carry its dtype, so claiming a single
    number was fabricated precision. The estimate now reports a RANGE and judges on the
    OPTIMISTIC end, which is the only claim it can actually support.

    The verdict survives the correction: even at FP8 the weights alone meet the card,
    leaving nothing for the KV cache. It genuinely could not have started."""
    fit = V.vram_fit("mistralai/Ministral-3-8B-Instruct-2512", 8192)
    assert fit["verdict"] == "too_large"
    est = fit["estimate"]
    assert est["params_b"] == 8
    assert (est["weights_gb_low"], est["weights_gb_high"]) == (8.0, 16.0)
    assert est["weights_gb"] == 8.0, "the single figure must be the OPTIMISTIC end"
    assert "NOT stated in the name" in est["method"]
    assert fit["vram_gb"] == 8.0


def test_the_3B_variant_the_card_says_fits_8gb_is_not_refused():
    """The maintainer's real GPU option: the card states the 3B is "capable of fitting
    in 8GB of VRAM in FP8". A guard that refused it would block the one model that
    works."""
    assert V.vram_fit("mistralai/Ministral-3-3B-Instruct-2512", 8192)["verdict"] != "too_large"


def test_an_explicit_fp8_name_is_not_charged_fp16_rates():
    est = V.estimate_weights_gb("someorg/model-8b-fp8")
    assert est["weights_gb_low"] == est["weights_gb_high"] == 8.0
    assert "FP8" in est["method"]


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
    """A running server that dies puts its reason at the END -- still true, still kept.
    AMENDED 2026-08-02: that is no longer the ONLY end retained; see the sibling test."""
    V.server_log_path().write_bytes(b"x" * 50_000 + b"CUDA out of memory\n")
    tail = V.server_log_tail()
    assert tail["available"] is True
    assert "CUDA out of memory" in tail["tail"], "the END is actionable when a live server dies"
    assert tail["truncated"] is True
    assert len(tail["tail"]) <= V._LOG_TAIL_BYTES + 16


def test_a_root_cause_at_the_START_survives_too(gpu8):
    """Field report 2026-08-02: the install and the model download both worked, the
    weights loaded (~5 GB of VRAM appeared) and the server then died. The bundle held
    29,855 bytes of log, of which the last 8,000 were kept -- and those 8,000 were the
    parent APIServer's own stack, ending in the words "See root cause above". The
    reason was in the 21,855 bytes thrown away.

    That is not bad luck, it is the SHAPE of this failure: vLLM's EngineCore is a child
    process, so it prints its traceback FIRST and the parent dumps ~20 KB after it. A
    tail-only instrument is guaranteed to keep the useless half of a startup failure."""
    root = b"ValueError: To serve at least one request, KV cache is 4.00 GiB > 2.55 GiB\n"
    V.server_log_path().write_bytes(root + b"x" * 40_000 + b"See root cause above.\n")
    out = V.server_log_tail()
    assert out["truncated"] is True
    assert "KV cache" in out["head"], "the reason the server died must survive"
    assert "See root cause above" in out["tail"], "and so must the end"
    # The gap between the two halves is STATED, so nobody reads them as contiguous.
    assert out["elided_bytes"] > 0
    assert out["elided_bytes"] == out["bytes"] - len(out["head"]) - len(out["tail"])
    assert len(out["head"]) <= V._LOG_HEAD_BYTES


def test_the_panel_renders_the_head_and_not_only_the_tail():
    """Keeping both ends in the payload is worth nothing if the UI still shows one.
    Scoped to the vLLM status panel's own renderer so an unrelated `lg.tail` elsewhere
    cannot satisfy it."""

    app = app_js()
    at = app.index("const lg = s.server_log || {};")
    block = app[at : app.index("box.innerHTML =", at)]
    assert "lg.head" in block, "the root cause of a startup failure lives in the head"
    assert "lg.elided_bytes" in block, "the gap between the halves must be stated"
    # And the two halves must be rendered in reading order, head first.
    assert block.index("lg.head") < block.index("lg.tail || \"\"")


def test_a_short_log_is_not_shown_twice(gpu8):
    """head+tail on a file that fits would repeat the same text and leave a reader
    wondering whether the server really said it twice."""
    V.server_log_path().write_bytes(b"CUDA out of memory\n")
    out = V.server_log_tail()
    assert out["truncated"] is False
    assert out["elided_bytes"] == 0
    assert "head" not in out
    assert out["tail"] == "CUDA out of memory\n"


def test_a_missing_log_is_a_stated_absence_not_an_empty_string(gpu8):
    tail = V.server_log_tail()
    assert tail["available"] is False
    assert tail["reason"], "silence must be explained, never rendered as 'nothing wrong'"
    assert "tail" not in tail


def test_each_start_truncates_so_the_log_describes_the_CURRENT_attempt(gpu8):
    V.server_log_path().write_bytes(b"stale failure from a previous model\n")
    V.start("someorg/tiny-1b", popen=lambda *a, **k: None)
    assert "stale failure" not in V.server_log_path().read_text(encoding="utf-8"), (
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


# --------------------------------------------------------------------------- #
#  a start that DIED must not be reported as one still loading
# --------------------------------------------------------------------------- #
class _Proc:
    """The subprocess.Popen surface start_outcome() reads."""

    def __init__(self, code=None, pid=4242):
        self._code = code
        self.pid = pid

    def poll(self):
        return self._code


def test_a_never_started_server_says_so(gpu8, monkeypatch):
    monkeypatch.setattr(V, "_proc", None)
    assert V.start_outcome()["state"] == "not-started"


def test_a_live_but_silent_process_is_STARTING_not_a_failure(gpu8, monkeypatch):
    """The normal path: a model load takes tens of seconds. Calling that a failure
    would make every healthy start look broken for its first minute."""
    monkeypatch.setattr(V, "_proc", _Proc(code=None))
    monkeypatch.setattr(V, "is_running", lambda **k: False)
    out = V.start_outcome()
    assert out["state"] == "starting"
    assert out["pid"] == 4242


def test_a_process_that_EXITED_is_a_failed_start_with_its_code(gpu8, monkeypatch):
    """The field defect, 2026-08-02. start() returns the moment Popen succeeds -- right,
    because blocking on a model load would be worse -- so when the child then died during
    engine init, `running: false` and `process_tracked: false` were the ONLY symptoms,
    and a server still loading shows exactly the same pair. The caller could not tell a
    dead start from a slow one, so it polled a port that would never open and reported
    'local model hiccup (1/10) -- retrying in 5s'."""
    monkeypatch.setattr(V, "_proc", _Proc(code=1))
    out = V.start_outcome()
    assert out["state"] == "exited"
    assert out["returncode"] == 1
    assert "FAILED" in out["detail"]
    assert "never succeed" in out["detail"], "polling must be named as futile, not implied"
    # NOT "read the head" any more. That was this module's SECOND guess about where a
    # reason lives, and the field refuted it in 2026-08-04 (the cause sat at byte 27,405,
    # outside both the head and the tail) -- `failure_excerpt` searches for the signature
    # instead. This assertion had pinned the refuted advice in place; it now pins the two
    # artifacts that actually carry the answer and outlive the next start.
    assert "start journal" in out["log_hint"]
    assert "preserved_log_path" in out["log_hint"]
    assert "HEAD" not in out["log_hint"], "the refuted guess must not come back"
    assert out["log_path"].endswith("server.log")


def test_a_ready_server_is_ready(gpu8, monkeypatch):
    monkeypatch.setattr(V, "_proc", _Proc(code=None))
    monkeypatch.setattr(V, "is_running", lambda **k: True)
    assert V.start_outcome()["state"] == "ready"


def test_the_status_payload_carries_the_outcome(gpu8, monkeypatch):
    """It has to reach the operator and the bundle, not just exist as a function."""
    monkeypatch.setattr(V, "_proc", _Proc(code=3))
    assert V.status()["start_outcome"]["state"] == "exited"
