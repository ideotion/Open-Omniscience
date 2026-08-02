"""The bench roster tells the truth about six models, including where it has none.

Maintainer ask 2026-08-02: buttons that install a chosen set of bench models on
whichever backend serves. The identifiers came from an internet-connected session,
because the build sandbox cannot reach huggingface.co or ollama.com (the gateway 403s
both) -- the exact condition under which this project has shipped invented model tags
before, and the reason ``src/llm/ollama.py`` still carries the line "(The previous
catalog -- gemma4:e2b, llama4, qwen3.5 -- was hallucinated.)".

So what is pinned here is not "these strings are correct" -- no test in this repo can
establish that. It is the SHAPE of the honesty around them: a model absent from a
backend stays absent, an alternative channel never quietly becomes the model itself, a
warning never appears on a backend it does not describe, and a refusal is returned
rather than a row silently dropped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.llm import bench_roster as R

BACKENDS = ("vllm", "ollama")


# --------------------------------------------------------------------------- #
#  Nothing is silent
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS)
def test_every_row_either_installs_or_says_why_not(backend):
    """The failure this prevents is a table that looks complete because the rows it
    could not fill were dropped."""
    rows = R.roster_for(backend)["models"]
    assert len(rows) == len(R.BENCH_ROSTER), "every model appears on every backend's table"
    for row in rows:
        if row["installable"]:
            assert row["identifier"], f"{row['key']}: installable with no identifier"
        else:
            assert row["absent_reason"], f"{row['key']}: absent with no reason"


@pytest.mark.parametrize("backend", BACKENDS)
def test_an_absent_model_names_what_was_searched(backend):
    """"Not found" is only useful if it says where it looked -- otherwise the next
    session repeats the search, or worse, assumes nobody tried."""
    for row in R.roster_for(backend)["models"]:
        if not row["installable"] and row["absent_reason"] != "no Hugging Face repository recorded":
            assert row.get("searched"), f"{row['key']}: absent without a search record"


def test_selecting_an_unavailable_model_is_refused_not_dropped():
    """Asking for six and receiving four downloads with no explanation is the silence
    the whole roster exists to prevent."""
    keys = [e["key"] for e in R.BENCH_ROSTER]
    ok, refused = R.identifiers_for("ollama", keys)
    assert len(ok) + len(refused) == len(keys), "every requested key is accounted for"
    assert refused, "two of the six are genuinely not on Ollama"
    for r in refused:
        assert r["reason"]


def test_an_unknown_key_is_refused_by_name():
    ok, refused = R.identifiers_for("vllm", ["not-a-model"])
    assert ok == []
    assert refused == [{"key": "not-a-model", "reason": "not in the bench roster"}]


# --------------------------------------------------------------------------- #
#  Nothing is substituted
# --------------------------------------------------------------------------- #
def test_a_model_absent_from_ollama_is_not_filled_in_by_its_alternative():
    """SmolLM3 has a reachable third-party GGUF. That does NOT make the row installable:
    picking a community build instead of the publisher's own is a decision the operator
    makes, not one the table makes for them."""
    row = next(r for r in R.roster_for("ollama")["models"] if r["key"] == "smollm3-3b")
    assert row["installable"] is False
    assert row["alternative_key"] == "smollm3-3b-gguf-passthrough"
    ok, refused = R.identifiers_for("ollama", ["smollm3-3b"])
    assert ok == [], "the alternative must never be resolved in the model's place"
    assert refused[0]["reason"]


def test_alternatives_are_labelled_third_party_and_never_pre_ticked():
    for alt in R.ALTERNATIVES:
        assert alt["first_party"] is False
        assert alt["caveat"], "a weaker provenance claim must say so"
        assert alt["substitutes"] in {e["key"] for e in R.BENCH_ROSTER}
        assert "default_on" not in alt, "an alternative is a choice, never a default"


def test_the_rejected_community_uploads_are_recorded():
    """Recorded so a later session does not 'helpfully' add one back. Their objection is
    provenance, which does not improve with time."""
    alt = next(a for a in R.ALTERNATIVES if a["key"] == "smollm3-3b-gguf-passthrough")
    assert len(alt["rejected"]) >= 4
    assert "provenance" in alt["rejected_reason"]
    tags = {a["tag"] for a in R.ALTERNATIVES}
    assert not (set(alt["rejected"]) & tags), "a rejected upload must not also be offered"


# --------------------------------------------------------------------------- #
#  No warning appears where it does not apply
# --------------------------------------------------------------------------- #
def test_gated_never_shows_on_the_backend_where_the_model_is_not_gated():
    """Gemma-3n is gated on Hugging Face and ungated on Ollama. Showing "gated" on the
    Ollama row is a fabricated warning -- the mirror image of a fabricated pass, and it
    would push an operator away from a model that is perfectly reachable there."""
    for row in R.roster_for("ollama")["models"]:
        assert "gated" not in row["flags"], f"{row['key']}: gated is a Hugging Face fact"
    vllm = {r["key"]: r for r in R.roster_for("vllm")["models"]}
    assert "gated" in vllm["gemma-3n-e2b-it"]["flags"], "...but it must still be said where it is true"
    assert vllm["gemma-3n-e2b-it"]["gated"] is True


def test_a_quant_specific_warning_stays_on_the_backend_that_has_quants():
    hf = {r["key"]: r for r in R.roster_for("vllm")["models"]}
    oll = {r["key"]: r for r in R.roster_for("ollama")["models"]}
    assert "context_varies_by_quant" in oll["phi-4-mini-instruct"]["flags"]
    assert "context_varies_by_quant" not in hf["phi-4-mini-instruct"]["flags"]


def test_every_flag_shown_has_a_meaning_an_operator_can_read():
    for backend in BACKENDS:
        r = R.roster_for(backend)
        for row in r["models"]:
            for flag in row["flags"]:
                assert flag in r["flag_meanings"], f"{flag} is shown but never explained"


# --------------------------------------------------------------------------- #
#  The default selection is defensible
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS)
def test_a_gated_base_or_unread_licence_model_is_never_pre_ticked(backend):
    """Each is a reason the operator might decline. A default tick would accept a
    licence on their behalf, or queue a base checkpoint into an instruct bench."""
    for row in R.roster_for(backend)["models"]:
        if {"gated", "base_model", "licence_unverified", "use_policy"} & set(row["flags"]):
            assert row["default_on"] is False, f"{row['key']} must not be pre-ticked"


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_apps_own_default_model_is_pre_ticked(backend):
    """The regression guard for an over-blunt honesty rule. Treating Ministral's
    third-party-rights RIDER as equivalent to Gemma's acceptable-use POLICY unticked
    this app's own default model over a sentence about IP rights -- an honesty rule
    destroying the thing it was meant to protect. Both are labelled; only the policy
    blocks a default."""
    row = next(
        r for r in R.roster_for(backend)["models"] if r["key"] == "ministral-3-3b-instruct-2512"
    )
    assert row["default_on"] is True
    assert "use_rider" in row["flags"], "the rider is still stated, just not blocking"
    assert "use_policy" not in row["flags"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_something_is_pre_ticked_so_the_button_is_not_a_no_op(backend):
    assert any(r["default_on"] for r in R.roster_for(backend)["models"])


# --------------------------------------------------------------------------- #
#  Agreement with what this repo already verified
# --------------------------------------------------------------------------- #
def test_the_calibration_rows_agree_with_the_shipped_catalog():
    """Two of the six were already verified in-tree, and the acquisition run confirmed
    both independently. Pinning the agreement means a later edit to EITHER side that
    breaks it reddens here, instead of the two quietly drifting apart."""
    from src.llm.ollama import MINISTRAL_SUGGESTION, MODEL_CATALOG

    row = next(r for r in R.roster_for("ollama")["models"] if r["key"] == "ministral-3-3b-instruct-2512")
    assert row["identifier"] == MINISTRAL_SUGGESTION["tag"]

    hf = next(r for r in R.roster_for("vllm")["models"] if r["key"] == "ministral-3-3b-instruct-2512")
    assert hf["identifier"] == MINISTRAL_SUGGESTION["vllm_model"]

    # phi4-mini is in the catalog under the bare name; the roster pins the explicit
    # size-and-quant tag. They must name the same model family, not two different ones.
    phi = next(r for r in R.roster_for("ollama")["models"] if r["key"] == "phi-4-mini-instruct")
    assert phi["identifier"].startswith("phi4-mini")
    assert any(m["tag"].startswith("phi4-mini") for m in MODEL_CATALOG)


def test_the_roster_states_its_own_date_and_method():
    for backend in BACKENDS:
        r = R.roster_for(backend)
        assert r["as_of"] == R.BENCH_ROSTER_AS_OF
        assert "read off a live model page" in r["method"]
        assert r["caveat"], "a dated roster must say it goes stale"


def test_the_roster_date_is_registered_in_the_external_artifact_registry():
    """The protocol guard already scans for *_AS_OF constants; this states the coupling
    from the roster's own side, so the reason for the entry is not only in a YAML file
    somebody has to find."""
    import pathlib

    reg = pathlib.Path(__file__).resolve().parents[1] / "configs" / "external_artifacts.yml"
    text = reg.read_text(encoding="utf-8")
    assert "BENCH_ROSTER_AS_OF" in text
    assert "bench-model-roster" in text


# --------------------------------------------------------------------------- #
#  The endpoints: what they install, and what they refuse
# --------------------------------------------------------------------------- #
@pytest.fixture
def machine(monkeypatch):
    """Drive the REAL resolver from a machine's facts, so these exercise the production
    path rather than a hand-written payload that could drift from it."""
    import src.llm.backend as B

    def _make(*, gpu, vllm_installed, ollama_installed, ollama_running=False):
        monkeypatch.setattr(
            B, "detect_gpu",
            lambda: {"available": True, "vram_mb": 8188} if gpu else {"available": False},
        )
        monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": vllm_installed, "running": False})
        monkeypatch.setattr(B, "_ollama_available", lambda: ollama_running)
        monkeypatch.setattr(B, "_ollama_installed", lambda: ollama_installed)
        monkeypatch.setenv("OO_LLM_BACKEND", "")

    return _make


def test_the_panel_gets_the_roster_for_the_backend_it_is_showing(machine):
    """The vLLM section must not be handed Ollama tags because the machine happens to
    prefer Ollama today -- it would install what it did not show."""
    import src.api.llm as L

    machine(gpu=True, vllm_installed=True, ollama_installed=False)
    assert L.bench_roster("vllm")["backend"] == "vllm"
    assert L.bench_roster("ollama")["backend"] == "ollama"
    # And asking for a backend that is not installed says so rather than offering a
    # download with nowhere to land.
    assert L.bench_roster("ollama")["prerequisite"] == "ollama"


def test_installing_returns_every_refusal_alongside_what_was_queued(monkeypatch, machine):
    """The operator asked for four and is owed an account of four."""
    import src.api.llm as L
    from src.ingest import egress_window as ew

    machine(gpu=False, vllm_installed=False, ollama_installed=True, ollama_running=True)
    sent: list[str] = []

    class _Mgr:
        def enqueue(self, tag):
            sent.append(tag)
            return {}

        def status(self):
            return {"active": None, "queue": list(sent), "history": []}

    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: _Mgr())
    ew._reset_for_tests()
    out = L.bench_roster_install(
        L.BenchRosterInstallRequest(
            keys=["phi-4-mini-instruct", "smollm3-3b", "lfm25-1-2b-base"], backend="ollama"
        )
    )
    assert out["queued"] == ["phi4-mini:3.8b-q4_K_M"]
    assert {r["key"] for r in out["refused"]} == {"smollm3-3b", "lfm25-1-2b-base"}
    assert all(r["reason"] for r in out["refused"])
    assert "smollm3" not in " ".join(sent).lower(), "an absent model must never be substituted"


def test_the_install_is_refused_under_airplane_mode(monkeypatch, machine):
    """Both paths egress clearnet, so both are refused -- gating only one would leave
    the other downloading while the operator believes they are offline."""
    from fastapi import HTTPException

    import src.api.llm as L
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.ingest import egress_window as ew

    machine(gpu=False, vllm_installed=False, ollama_installed=True, ollama_running=True)
    ew._reset_for_tests()
    activate_kill_switch()
    try:
        with pytest.raises(HTTPException) as exc:
            L.bench_roster_install(L.BenchRosterInstallRequest(keys=["phi-4-mini-instruct"]))
        assert exc.value.status_code == 409
        assert "airplane" in str(exc.value.detail).lower()
    finally:
        clear_kill_switch()
        ew._reset_for_tests()


def test_a_batch_survives_one_model_failing():
    """Gemma-3n is gated and WILL fail without a token, which the panel says before the
    click. If that aborted the run, ticking it would silently cost the other five."""
    from src.llm.vllm_lifecycle import VllmLifecycleError, run_models_download_job

    class _Ctx:
        stopping = False

        def set_progress(self, **kw):
            pass

    calls: list[str] = []

    def _fake(ctx, *, model, runner=None):
        calls.append(model)
        if "gemma" in model:
            raise VllmLifecycleError("401 gated repo")
        return {"downloaded": True, "state": "downloaded"}

    import src.llm.vllm_lifecycle as V

    orig = V.run_model_download_job
    V.run_model_download_job = _fake
    try:
        out = run_models_download_job(_Ctx(), models=["a/one", "google/gemma-x", "b/two"])
    finally:
        V.run_model_download_job = orig

    assert calls == ["a/one", "google/gemma-x", "b/two"], "the batch continued past the failure"
    assert out["downloaded"] == 2 and out["failed"] == 1
    assert out["partial"] is True, "a partial batch must never read as a clean one"
    assert "gated" in next(r["error"] for r in out["results"] if r["state"] == "error")
