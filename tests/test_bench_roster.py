"""The bench roster tells the truth about its models, including where it has none.

Maintainer ask 2026-08-02: buttons that install a chosen set of bench models on
whichever backend serves. The identifiers came from an internet-connected session,
because the build sandbox cannot reach huggingface.co or ollama.com (the gateway 403s
both) -- the exact condition under which this project has shipped invented model tags
before, and the reason ``src/llm/ollama.py`` still carries the line "(The previous
catalog -- gemma4:e2b, llama4, qwen3.5 -- was hallucinated.)". One row is at the weaker
``search-verified`` tier and says so; the tests below make that impossible to omit.

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
from tests.js_source_helper import function_body as _slice

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
    """Asking for every model and receiving a subset with no explanation is the silence
    the whole roster exists to prevent."""
    keys = [e["key"] for e in R.BENCH_ROSTER]
    ok, refused = R.identifiers_for("ollama", keys)
    assert len(ok) + len(refused) == len(keys), "every requested key is accounted for"
    assert refused, "several rows genuinely have no Ollama tag"
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
    """Two rows were already verified in-tree, and the acquisition run confirmed
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


# --------------------------------------------------------------------------- #
#  Following the install: the panel must read its OWN backend's progress
# --------------------------------------------------------------------------- #
def test_the_follower_reads_the_job_the_install_started(monkeypatch, machine):
    """A vLLM panel installing on a machine that would otherwise provision Ollama must
    not follow the Ollama queue and report a stranger's progress as its own.

    This is the routing-vs-provisioning confusion that shipped a real field bug, one
    level down: there, a download was PLANNED for a backend that was not there; here, it
    would be WATCHED on one."""
    import src.api.llm as L

    machine(gpu=True, vllm_installed=True, ollama_installed=True, ollama_running=True)

    class _Job:
        def status(self):
            return {"state": "running", "detail": "downloading 2 of 3"}

    monkeypatch.setattr(L, "_get_vllm_model_job", lambda: _Job())
    out = L.bench_roster_status("vllm")
    assert out["backend"] == "vllm"
    assert out["state"] == "running" and out["detail"] == "downloading 2 of 3"
    # Its scope is exact, and it says so: this job is only ever this batch.
    assert out["queue_is_shared"] is False


def test_the_ollama_follower_admits_the_queue_is_shared(monkeypatch, machine):
    """The Ollama path enqueues into the one pull queue, which may already be carrying
    somebody else's pull. Reporting that as "your batch" would be a small lie that makes
    a progress line untrustworthy; the flag lets a caller know which it is reading."""
    import src.api.llm as L

    machine(gpu=False, vllm_installed=False, ollama_installed=True, ollama_running=True)

    class _Mgr:
        def status(self):
            return {"active": {"model": "phi4-mini:3.8b-q4_K_M", "percent": 41}, "queue": ["x"]}

    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: _Mgr())
    out = L.bench_roster_status("ollama")
    assert out["queue_is_shared"] is True
    assert out["state"] == "running"
    assert "phi4-mini" in out["detail"] and "41" in out["detail"]


def test_an_idle_queue_terminates_the_follower(monkeypatch, machine):
    """A poller with no terminal state is indistinguishable from work that never ends --
    the exact defect that hung the default-model chain (field report 2026-08-02)."""
    import src.api.llm as L

    machine(gpu=False, vllm_installed=False, ollama_installed=True, ollama_running=True)

    class _Mgr:
        def status(self):
            return {"active": None, "queue": []}

    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: _Mgr())
    out = L.bench_roster_status("ollama")
    assert out["state"] != "running", "the follower must be able to stop"


# --------------------------------------------------------------------------- #
#  The panel (source-level, browser-unverified per fork-3)
# --------------------------------------------------------------------------- #
def _app_js() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(
        encoding="utf-8"
    )


def _fn_body(js: str, name: str) -> str:
    """One function's body, brace-matched. Shared slicer."""
    return _slice(js, name)


def test_the_body_extractor_is_not_vacuous():
    """The guard on the guards. A body that came back empty -- or swallowed the rest of
    the file -- would make every source assertion below pass for free."""
    js = _app_js()
    for name in ("loadBenchRoster", "installBenchModels"):
        body = _fn_body(js, name)
        assert 10 < body.count("\n") < 120, f"{name}: implausible body ({body.count(chr(10))} lines)"
        assert body.startswith("{") and body.rstrip().endswith("}")
    # And the two are genuinely different slices, not the same over-broad one twice.
    assert _fn_body(js, "loadBenchRoster") != _fn_body(js, "installBenchModels")
    assert "installBenchModels" not in _fn_body(js, "loadBenchRoster").replace(
        "installBenchModels('", "X"
    ).replace('installBenchModels("', "X")


def test_each_panel_asks_for_its_own_backend():
    """Both sections render from ONE function, so the guard that matters is that each
    call names its backend -- otherwise a click under the vLLM heading downloads
    whatever the machine happens to prefer."""
    js = _app_js()
    assert 'loadBenchRoster("vllm")' in js
    assert 'loadBenchRoster("ollama")' in js
    assert "bench-roster?backend=" in js, "the roster is fetched for a named backend"
    # And the install posts the backend it rendered, never an implicit one.
    assert "JSON.stringify({keys, backend})" in js


def test_an_absent_model_is_rendered_disabled_rather_than_hidden():
    """A row with nothing to install is a finding, not clutter. Hiding it would make the
    table look complete and leave the operator wondering where the model went."""
    js = _app_js()
    body = _fn_body(js, "loadBenchRoster")
    assert "if (!m.installable)" in body
    assert 'type="checkbox" disabled' in body
    assert "absent_reason" in body and "Searched:" in body


def test_the_install_reports_refusals_and_needs_consent():
    """Ticking several and getting a subset with no explanation is exactly the silence
    the roster exists to prevent; and the download is clearnet, so it passes the AI
    egress consent like every sibling."""
    js = _app_js()
    body = _fn_body(js, "installBenchModels")
    assert "ensureAiEgress(" in body
    assert "if (!await ensureAiEgress" in body, "a declined consent must stop the install"
    assert "r.refused" in body
    assert "nothing_to_do" in body


def test_the_bench_strings_are_translated():
    """Server-side notes travel with the data, but the panel's own chrome is keyed x12
    like every operator-facing surface."""
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    for lang in ("en", "fr", "ar", "zh"):
        data = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
        assert "Comparative-bench models" in data
        assert "Download the ticked models" in data
        assert data["Comparative-bench models"], f"{lang}: empty translation"


# --------------------------------------------------------------------------- #
#  Every identifier states its own provenance tier
# --------------------------------------------------------------------------- #
def test_no_identifier_can_be_added_without_saying_how_it_was_verified():
    """The field only works if absence is impossible.

    A default would silently claim the STRONGER tier for whoever forgot to think about
    it, which inverts the point: this file exists because the project once shipped model
    tags nobody had checked."""
    for entry in R.BENCH_ROSTER:
        for channel in ("hf", "ollama"):
            block = entry.get(channel)
            if block is None:
                continue
            assert "verification" in block, f"{entry['key']}.{channel}: no verification tier"
            assert block["verification"] in {"fetched", "search-verified"}, entry["key"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_tier_reaches_the_panel(backend):
    """Recorded but not rendered is the same as not recorded, for the operator."""
    for row in R.roster_for(backend)["models"]:
        if row["installable"]:
            assert row["verification"], f"{row['key']}: tier lost in the projection"


def test_exactly_the_rows_that_were_fetched_claim_to_have_been():
    """The docstring says "almost every" precisely because one is not. If a later
    session verifies it, this test is the place that notices the claim changed."""
    weaker = {
        e["key"] for e in R.BENCH_ROSTER
        if (e.get("hf") or {}).get("verification") == "search-verified"
    }
    assert weaker == {"lfm25-1-2b-instruct"}, (
        "a row moved provenance tier -- update the module docstring in the same commit"
    )


# --------------------------------------------------------------------------- #
#  The LFM2.5 decision (maintainer, 2026-08-02): ADD the Instruct row, keep Base
# --------------------------------------------------------------------------- #
def test_the_base_row_survives_the_instruct_row_being_added():
    """The regression guard for the decision itself. Base is what was ASKED for; the
    Instruct row exists because the bench cannot measure a base checkpoint, not because
    Base was wrong. A later tidy-up that collapses the two would be the substitution
    this whole module refuses."""
    keys = [e["key"] for e in R.BENCH_ROSTER]
    assert "lfm25-1-2b-base" in keys
    assert "lfm25-1-2b-instruct" in keys
    base = next(e for e in R.BENCH_ROSTER if e["key"] == "lfm25-1-2b-base")
    inst = next(e for e in R.BENCH_ROSTER if e["key"] == "lfm25-1-2b-instruct")
    assert base["hf"]["repo"] != inst["hf"]["repo"]
    assert "base_model" in base["flags"], "Base must keep saying what it is"
    assert "base_model" not in inst["flags"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_neither_liquidai_row_is_pre_ticked(backend):
    """Nobody has read the licence on either. An unread licence is not a default."""
    rows = {r["key"]: r for r in R.roster_for(backend)["models"]}
    for key in ("lfm25-1-2b-base", "lfm25-1-2b-instruct"):
        assert rows[key]["default_on"] is False
        assert "licence_unverified" in rows[key]["flags"]


def test_the_instruct_row_does_not_borrow_facts_from_its_sibling():
    """Two repos, one of which was read. Copying the Base card's parameter split or
    licence badge across would invent agreement between pages -- the same move as
    substituting a near-match, one field down."""
    inst = next(e for e in R.BENCH_ROSTER if e["key"] == "lfm25-1-2b-instruct")["hf"]
    assert inst["params"] is None and inst["context_length"] is None
    assert "unconfirmed" in inst["licence"]


def test_an_unresolved_absence_says_what_would_settle_it():
    """`LiquidAI/lfm2.5-1.2b-instruct` is the right variant at the right size; the only
    question is whether that Ollama account is the publisher's. That is one lookup, and
    a panel that renders it identically to a settled absence hides the cheap fix."""
    row = next(r for r in R.roster_for("ollama")["models"] if r["key"] == "lfm25-1-2b-instruct")
    assert row["installable"] is False
    assert row["open_question"] and "first-party" in row["open_question"]
    ok, refused = R.identifiers_for("ollama", ["lfm25-1-2b-instruct"])
    assert ok == [], "an open question is not permission to install the guess"
    assert refused[0]["reason"]


def test_the_thinking_variant_is_not_offered_under_the_instruct_name():
    """library/lfm2.5-thinking is first-party and the right size -- and emits reasoning
    traces that fail format validity on three of the four constrained-output tasks. That
    is a finding about reasoning models, not a LiquidAI capability measurement."""
    entry = next(e for e in R.BENCH_ROSTER if e["key"] == "lfm25-1-2b-instruct")
    assert entry["ollama"] is None
    absent = entry["ollama_absent"]
    assert "thinking" in absent["searched"].lower()
    assert absent["passthrough_tag"] is None
    for alt in R.ALTERNATIVES:
        assert "thinking" not in alt["tag"].lower()


def test_the_panel_renders_the_weaker_tier_and_the_open_question():
    """Recorded but not rendered is, for the operator, the same as not recorded --
    and both of these exist precisely to reach a human before a multi-GB click."""
    body = _fn_body(_app_js(), "loadBenchRoster")
    assert 'm.verification === "fetched"' in body, "the weaker tier must be marked"
    assert "search-verified" in body
    assert "m.open_question" in body, "an absence somebody can close must say so"
