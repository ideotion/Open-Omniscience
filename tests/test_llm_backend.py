"""
Tests for the dual-backend LLM resolution (B1, 2026-07-24 field-feedback
Session B, RULED A12: vLLM on GPU machines, Ollama KEPT for the CPU-only
fleet). Backend resolution never touches a real GPU/vLLM/Ollama process --
every probe is monkeypatched.
"""

from __future__ import annotations

import pytest

from src.llm import backend as B
from src.llm.ollama import OllamaClient
from src.llm.vllm_client import VllmClient


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    B._reset_clients_for_tests()
    monkeypatch.delenv("OO_LLM_BACKEND", raising=False)
    yield
    B._reset_clients_for_tests()


def _stub(monkeypatch, *, gpu, vllm_installed, vllm_running, ollama_ok=True):
    monkeypatch.setattr(B, "detect_gpu", lambda: gpu)
    monkeypatch.setattr(
        B, "_vllm_status", lambda: {"installed": vllm_installed, "running": vllm_running}
    )
    monkeypatch.setattr(B, "_ollama_available", lambda: ollama_ok)


# --------------------------------------------------------------------------- #
# LlmBackend Protocol conformance -- both real clients satisfy it structurally.
# --------------------------------------------------------------------------- #
def test_ollama_and_vllm_clients_satisfy_the_protocol_structurally():
    # runtime_checkable Protocol.__instancecheck__ only checks METHOD PRESENCE
    # (not signatures) -- both clients define generate/list_installed/
    # is_available/close, so isinstance() against the Protocol holds.
    ollama = OllamaClient.__new__(OllamaClient)  # no __init__ (avoid real construction)
    vllm = VllmClient.__new__(VllmClient)
    assert isinstance(ollama, B.LlmBackend)
    assert isinstance(vllm, B.LlmBackend)


# --------------------------------------------------------------------------- #
# resolve_backend() -- the decision matrix
# --------------------------------------------------------------------------- #
def test_cpu_only_machine_uses_ollama(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "no GPU" in r["reason"]


def test_gpu_but_vllm_not_installed_uses_ollama(monkeypatch):
    _stub(monkeypatch, gpu={"available": True, "vram_mb": 8192}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "not installed" in r["reason"]


def test_gpu_and_vllm_installed_but_not_running_uses_ollama_meanwhile(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "not running" in r["reason"]


def test_gpu_installed_and_running_prefers_vllm(monkeypatch):
    _stub(monkeypatch, gpu={"available": True, "vram_mb": 8192}, vllm_installed=True, vllm_running=True)
    r = B.resolve_backend()
    assert r["backend"] == "vllm"
    assert "concurrency" in r["reason"]


def test_explicit_override_ollama_wins_even_with_vllm_ready(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    r = B.resolve_backend(override="ollama")
    assert r["backend"] == "ollama"
    assert r["override"] == "ollama"


def test_explicit_override_vllm_wins_even_on_cpu_only(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend(override="vllm")
    assert r["backend"] == "vllm"


def test_env_override_is_honoured_when_no_explicit_override(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    monkeypatch.setenv("OO_LLM_BACKEND", "vllm")
    r = B.resolve_backend()
    assert r["backend"] == "vllm"


def test_explicit_override_beats_the_env_var(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    monkeypatch.setenv("OO_LLM_BACKEND", "vllm")
    r = B.resolve_backend(override="ollama")
    assert r["backend"] == "ollama"


def test_an_invalid_override_falls_back_to_auto(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend(override="not-a-real-backend")
    assert r["backend"] == "ollama"  # auto behaviour, not an error


# --------------------------------------------------------------------------- #
# get_client() -- one instance per KIND, re-resolved each call
# --------------------------------------------------------------------------- #
def test_get_client_returns_ollama_by_default(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    c = B.get_client()
    assert isinstance(c, OllamaClient)


def test_get_client_caches_one_instance_per_kind(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    c1 = B.get_client()
    c2 = B.get_client()
    assert c1 is c2


def test_get_client_switches_kind_when_the_decision_changes(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    ollama_client = B.get_client()
    assert isinstance(ollama_client, OllamaClient)
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    vllm_client = B.get_client()
    assert isinstance(vllm_client, VllmClient)
    # switching back reuses the SAME cached Ollama instance (never rebuilt).
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    assert B.get_client() is ollama_client


def test_detect_gpu_degrades_honestly_when_nvidia_smi_is_absent(monkeypatch):
    def _raise(*a, **kw):
        raise FileNotFoundError("no nvidia-smi")

    monkeypatch.setattr(B.subprocess, "run", _raise)
    r = B.detect_gpu()
    assert r["available"] is False
    assert "reason" in r


# --------------------------------------------------------------------------- #
# V4 (2026-07-29): SELECTION vs CAPABILITY. The operator's bundle read
# backend="ollama" / "using Ollama meanwhile" while ollama_available was false --
# true about selection, misleading about capability. `available` and `no_backend`
# make the difference explicit, and every reason must name the real situation.
# --------------------------------------------------------------------------- #
def test_no_backend_when_neither_ollama_nor_vllm_is_reachable(monkeypatch):
    """The operator's exact 2026-07-29 machine: a real GPU, vLLM not installed,
    Ollama not running. Selection still falls back to Ollama -- but NOTHING can
    serve a request, and the payload + reason must both say so."""
    _stub(
        monkeypatch,
        gpu={"available": True, "vram_mb": 8188},
        vllm_installed=False,
        vllm_running=False,
        ollama_ok=False,
    )
    r = B.resolve_backend()
    assert r["backend"] == "ollama"  # selection is unchanged
    assert r["available"] is False   # ... but it cannot serve
    assert r["no_backend"] is True
    assert B.NO_BACKEND_REASON in r["reason"]
    # the old, misleading promise of a working fallback must be gone
    assert "using Ollama meanwhile (Ollama is reachable)" not in r["reason"]


def test_selected_backend_down_but_the_other_one_is_up_is_not_no_backend(monkeypatch):
    """The middle state: an explicit vLLM override whose server is not running,
    while Ollama IS reachable. available=False (the SELECTED backend is down) but
    no_backend=False -- a backend exists, and the reason must point at it."""
    _stub(
        monkeypatch,
        gpu={"available": True},
        vllm_installed=True,
        vllm_running=False,
        ollama_ok=True,
    )
    r = B.resolve_backend(override="vllm")
    assert r["backend"] == "vllm"
    assert r["available"] is False
    assert r["no_backend"] is False
    assert B.NO_BACKEND_REASON not in r["reason"]
    assert "Ollama IS reachable" in r["reason"]


def test_a_running_vllm_never_reads_as_no_backend_even_when_not_auto_selected(monkeypatch):
    """is_running() detects "a server started by another means entirely", so vLLM
    can be SERVING while auto-selection declines it (no detected GPU). Ollama
    being down must NOT then be reported as "no AI backend" -- one IS reachable."""
    _stub(
        monkeypatch,
        gpu={"available": False},
        vllm_installed=False,
        vllm_running=True,
        ollama_ok=False,
    )
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert r["available"] is False
    assert r["no_backend"] is False, "a reachable vLLM server is a backend"
    assert B.NO_BACKEND_REASON not in r["reason"]


def test_vllm_installed_but_not_running_is_distinguished_from_not_installed(monkeypatch):
    """Two situations that both fall back to Ollama, and that the operator must
    be able to tell apart: one needs a START, the other an INSTALL."""
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False)
    not_running = B.resolve_backend()
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=False, vllm_running=False)
    not_installed = B.resolve_backend()
    assert not_running["reason"] != not_installed["reason"]
    assert "not running" in not_running["reason"]
    assert "not installed" in not_installed["reason"]
    assert not_running["available"] is True and not_installed["available"] is True


def test_available_is_true_only_when_the_selected_backend_is_reachable(monkeypatch):
    """available tracks the SELECTED backend, never "some backend somewhere"."""
    _stub(
        monkeypatch,
        gpu={"available": True},
        vllm_installed=True,
        vllm_running=True,
        ollama_ok=False,
    )
    r = B.resolve_backend()
    assert r["backend"] == "vllm" and r["available"] is True    # vLLM is up
    r2 = B.resolve_backend(override="ollama")
    assert r2["backend"] == "ollama" and r2["available"] is False  # Ollama is not


def test_capability_fields_are_present_in_EVERY_branch(monkeypatch):
    """Membership, not .get() -- a missing key must fail loudly rather than
    defaulting to a falsy value that reads like a measured answer."""
    cases = [
        (dict(gpu={"available": False}, vllm_installed=False, vllm_running=False), None),
        (dict(gpu={"available": True}, vllm_installed=False, vllm_running=False), None),
        (dict(gpu={"available": True}, vllm_installed=True, vllm_running=False), None),
        (dict(gpu={"available": True}, vllm_installed=True, vllm_running=True), None),
        (dict(gpu={"available": True}, vllm_installed=True, vllm_running=True), "ollama"),
        (dict(gpu={"available": False}, vllm_installed=False, vllm_running=False), "vllm"),
    ]
    for stub_kwargs, override in cases:
        _stub(monkeypatch, **stub_kwargs)
        r = B.resolve_backend(override=override)
        assert "available" in r, f"missing 'available' for {stub_kwargs} / {override}"
        assert "no_backend" in r, f"missing 'no_backend' for {stub_kwargs} / {override}"
        for k in ("backend", "reason", "override", "gpu", "vllm", "ollama_available"):
            assert k in r, f"V4 must be ADDITIVE -- lost {k!r}"


def test_available_and_no_backend_are_never_both_true(monkeypatch):
    """The whole 16-state auto matrix + both overrides: `available` implies a
    reachable backend, so it can never coexist with no_backend, and no_backend can
    never be claimed while a probe reported something reachable."""
    import itertools

    for gpu_ok, installed, running, ollama_ok in itertools.product([False, True], repeat=4):
        for override in (None, "ollama", "vllm"):
            _stub(
                monkeypatch,
                gpu={"available": gpu_ok},
                vllm_installed=installed,
                vllm_running=running,
                ollama_ok=ollama_ok,
            )
            r = B.resolve_backend(override=override)
            state = (gpu_ok, installed, running, ollama_ok, override)
            assert not (r["available"] and r["no_backend"]), state
            assert r["no_backend"] == (not (ollama_ok or running)), state
            # the reason NAMES the state, in both directions
            assert (B.NO_BACKEND_REASON in r["reason"]) == r["no_backend"], (state, r["reason"])
            # never a fabricated capability claim
            if r["available"]:
                assert ollama_ok if r["backend"] == "ollama" else running, state


def test_the_capability_fields_add_no_new_probe(monkeypatch):
    """The performance contract: `available`/`no_backend` are DERIVED from probes
    resolve_backend already ran. Each probe must still be called exactly ONCE per
    resolution -- a regression costs real latency, because _ollama_available()
    builds an OllamaClient whose default timeout is 120s and _vllm_status() makes
    a live HTTP health call."""
    calls = {"gpu": 0, "vllm": 0, "ollama": 0}

    def _count(key, value):
        def _fn():
            calls[key] += 1
            return value

        return _fn

    monkeypatch.setattr(B, "detect_gpu", _count("gpu", {"available": True}))
    monkeypatch.setattr(B, "_vllm_status", _count("vllm", {"installed": False, "running": False}))
    monkeypatch.setattr(B, "_ollama_available", _count("ollama", False))
    B.resolve_backend()
    assert calls == {"gpu": 1, "vllm": 1, "ollama": 1}


# --------------------------------------------------------------------------- #
#  the operator is told WHY, in the resolver's own words
# --------------------------------------------------------------------------- #
def test_no_backend_at_all_yields_the_resolvers_own_reason(monkeypatch):
    """Field report 2026-08-02: with vLLM installed but dead and Ollama not running,
    Start background AI said "local model hiccup (1/10) - retrying in 5s" and counted
    to ten. Not a hiccup, and the app already knew exactly what it was - the honest
    sentence was one field away while the operator read a misleading one."""
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False,
          ollama_ok=False)
    why = B.outage_reason()
    assert why, "the reason must be available to the sweeps' progress line"
    assert "not running" in why or "reachable" in why


def test_a_reachable_backend_gives_no_reason(monkeypatch):
    """None means "nothing to add": a backend IS there and a single call merely failed,
    so this probe has nothing useful to say about it.

    What the caller does with that None is the subject of ``outage_detail`` below --
    and until 2026-08-04 it fell through to the words "local model hiccup", which is
    how this correct, narrow answer became the hiding place for the failures that
    actually reach a sweep loop."""
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False,
          ollama_ok=True)
    assert B.outage_reason() is None


def test_it_never_decides_whether_to_keep_retrying(monkeypatch):
    """THE load-bearing property, and the first cut of this got it wrong.

    A health probe cannot tell a backend that is GONE from one that is momentarily
    unreachable - a model reload, a restart and a busy server all answer identically.
    Ending a multi-hour sweep on that probe would break the transient-retry guarantee
    the backoff exists to provide, so this returns a MESSAGE and nothing else: no
    verdict, no budget, no control flow. The repo's own progressive-sweep tests caught
    the earlier version immediately, which is why the contract is pinned here."""
    assert not hasattr(B, "classify_outage"), (
        "a helper that returns a retry VERDICT invites exactly the regression that was "
        "caught: this one reports why, and the retry budget stays the caller's"
    )
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False,
          ollama_ok=False)
    assert isinstance(B.outage_reason(), str)


def test_a_probe_that_cannot_read_says_nothing_rather_than_guessing(monkeypatch):
    """A message-enrichment probe must never break the run it annotates."""
    def _boom():
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(B, "resolve_backend", _boom)
    assert B.outage_reason() is None


# --------------------------------------------------------------------------- #
#  ...and when the resolver has nothing to add, the ERROR is not thrown away
# --------------------------------------------------------------------------- #
def test_the_resolvers_reason_wins_when_there_is_one():
    """"Connection refused" says what happened; "vLLM is installed but its server is
    not running" says what to DO. Where both exist, the actionable one leads."""
    assert B.outage_detail("vLLM's server is not running", RuntimeError("conn refused")) == (
        "vLLM's server is not running"
    )


def test_otherwise_the_actual_error_is_used_instead_of_a_symptom():
    """Field report 2026-08-04: "I just reinstalled the app, and still get the 'local
    model hiccup' error message."

    ``outage_reason()`` answers REACHABILITY, so it correctly returns None for the
    failures that most often reach a sweep loop -- a reachable Ollama with no model
    pulled, a 500 from a context overflow, a vLLM whose port opened before its engine
    died. The retry line then printed "local model hiccup", naming the symptom while
    the identifying fact sat one variable away."""
    said = B.outage_detail(None, RuntimeError("model 'ministral-3:3b' not found, try pulling it"))
    assert "not found" in said
    assert "hiccup" not in said


def test_an_error_with_no_message_still_yields_its_type():
    """A bare ``raise ReadTimeout`` has an empty str(). "ReadTimeout" is still a far
    better clue than "hiccup", and an empty retry line would be worse than either."""

    class ReadTimeout(Exception):
        pass

    assert B.outage_detail(None, ReadTimeout()) == "ReadTimeout"


def test_a_plain_reason_string_is_carried_through():
    """Two of the four sweep loops hold a reason STRING rather than an exception (the
    aborting event's own words), which is why this normalises rather than assuming."""
    assert B.outage_detail(None, "the local model is unavailable") == (
        "the local model is unavailable"
    )


def test_nothing_at_all_still_produces_a_sentence():
    """The last resort. Vague, but it does not pretend to know a cause, and it does
    not claim the failure was transient."""
    said = B.outage_detail(None, None)
    assert said and "hiccup" not in said


def test_a_runaway_error_body_cannot_run_away_with_the_progress_line():
    """An HTML error page or a multi-kilobyte traceback in a one-line progress field
    helps nobody."""
    assert len(B.outage_detail(None, RuntimeError("x" * 5000))) <= 200


def test_every_sweep_loop_actually_calls_it():
    """Four loops had the same defect and it was fixed in four places, so the guard is
    that each one still reaches for the shared helper. A bare import would not satisfy
    this -- the parenthesis makes it a CALL."""
    import pathlib

    for rel in (
        "src/ai_layer/triage_job.py",
        "src/ai_layer/source_tags_job.py",
        "src/ai_layer/perception_extract_job.py",
        "src/api/ai.py",
    ):
        src = pathlib.Path(rel).read_text(encoding="utf-8")
        assert "outage_detail(" in src, f"{rel} no longer reports the real failure"


# --------------------------------------------------------------------------- #
#  ONE answer to "which backend", not one per caller
# --------------------------------------------------------------------------- #
def _stored(monkeypatch, backend="auto", model="ollama-tag:3b", vllm_model="org/Repo-3B"):
    class S:
        llm_backend = backend
        llm_model = model
        llm_model_vllm = vllm_model

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: S())
    return S


def test_the_stored_backend_choice_reaches_resolution(monkeypatch):
    """Field report 2026-08-04: "Model 'mistralai/Ministral-3-3B-Instruct-2512' is not
    installed. Run: ollama pull mistralai/Ministral-3-3B-Instruct-2512" — an HF repo id
    handed to OLLAMA, on a machine where the Ollama model was installed all along.

    Two functions answered "which backend" from different sources. ``active_model()``
    passed the stored setting and got vLLM's identifier; the sweeps called
    ``get_client_with_name()`` with nothing, which read only the environment, and with
    vLLM installed-but-not-running resolved to Ollama. The model came from one answer
    and the client from the other."""
    _stored(monkeypatch, backend="vllm")
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False)
    assert B.resolve_backend()["backend"] == "vllm", (
        "an operator who chose vLLM in Settings must not be silently routed to Ollama"
    )


def test_an_explicit_argument_still_beats_the_stored_setting(monkeypatch):
    """Precedence, in both directions — a stored preference is a default, not a lock."""
    _stored(monkeypatch, backend="vllm")
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    assert B.resolve_backend(override="ollama")["backend"] == "ollama"
    monkeypatch.setenv("OO_LLM_BACKEND", "ollama")
    assert B.resolve_backend()["backend"] == "ollama", "the env var outranks the setting"


def test_auto_stays_auto(monkeypatch):
    """The twin. Reading the setting must not turn every machine into an override —
    "auto" is the default and has to keep meaning "decide from the hardware"."""
    _stored(monkeypatch, backend="auto")
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama", "vLLM is never auto-selected while its server is down"
    assert r["override"] is None


def test_an_unreadable_setting_never_breaks_resolution(monkeypatch):
    def _boom():
        raise RuntimeError("settings file is corrupt")

    monkeypatch.setattr("src.config.app_settings.load_settings", _boom)
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    assert B.resolve_backend()["backend"] == "ollama"


def test_the_model_id_follows_the_backend_it_was_chosen_for(monkeypatch):
    """The two backends consume DIFFERENT artifacts — a GGUF tag and an HF repo id —
    so a model name only means anything beside its backend. A caller that already knows
    which backend it brought up passes it, rather than letting this re-resolve and
    possibly disagree."""
    from src.api.llm import active_model

    _stored(monkeypatch, backend="auto")
    assert active_model("ollama") == "ollama-tag:3b"
    assert active_model("vllm") == "org/Repo-3B"
