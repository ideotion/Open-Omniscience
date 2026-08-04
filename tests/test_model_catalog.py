"""ONE model list, either backend -- and never a guessed identifier.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Maintainer 2026-08-04: "a list of dual use buttons for additional models ... also
dynamically choosing the proper version for either ollama or vLLM".

The arithmetic is trivial; the honesty is not, and it is what these pin:

  * NO IDENTIFIER IS RE-TYPED HERE. Every tag and repo id is imported from the dated
    catalogue that verified it, so a stale one is caught by that catalogue's freshness
    test instead of by an operator's failed download. Pinned behaviourally -- patch
    the source, the catalogue must follow -- because a string-equality test would pass
    just as well against a hard-coded copy.
  * A MISSING BUILD IS STATED, NOT INVENTED and NOT HIDDEN. Granite has verified
    Ollama tags and no recorded HF repo. ``ibm-granite/granite-4.1-3b`` reads
    perfectly plausible and is exactly the kind of guess that 404s.
  * REFUSALS TRAVEL WITH THE RESULT: four asked for, two possible, an account of four.
"""

from __future__ import annotations

import pytest

from src.llm import model_catalog


BACKENDS = ("ollama", "vllm")


# --------------------------------------------------------------------------- #
#  Shape
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS)
def test_every_model_appears_for_every_backend(backend):
    """A model with no build here is listed as unavailable, not dropped -- otherwise
    the list is silently shorter on one machine than another and nothing says why."""
    keys = [m["key"] for m in model_catalog.catalog_for(backend)["models"]]
    assert keys == list(model_catalog.CATALOG_ORDER)


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_default_is_marked_and_available_on_both_backends(backend):
    """The one-click setup downloads this; if it resolved to nothing on a backend the
    setup button would have nothing to do."""
    models = model_catalog.catalog_for(backend)["models"]
    default = [m for m in models if m["is_default"]]
    assert len(default) == 1, "exactly one default"
    assert default[0]["key"] == model_catalog.DEFAULT_KEY
    assert default[0]["available"] is True
    assert default[0]["artifact"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_an_available_model_always_carries_its_verification_tier(backend):
    """"fetched" and "search-verified" are different claims, and an unlabelled
    identifier would quietly assume the stronger one."""
    for m in model_catalog.catalog_for(backend)["models"]:
        if m["available"]:
            assert m["verification"] in {"fetched", "search-verified"}, m


@pytest.mark.parametrize("backend", BACKENDS)
def test_an_unavailable_model_always_says_why(backend):
    for m in model_catalog.catalog_for(backend)["models"]:
        if not m["available"]:
            assert m["absent_reason"], f"{m['key']} is unavailable with no reason"
            assert m["artifact"] is None


def test_the_two_backends_resolve_to_different_artifacts():
    """The whole point: one logical model, two incompatible builds. A catalogue that
    handed the same string to both would be handing an Ollama tag to vLLM, which is a
    guaranteed failure the recorded ``active_model`` lesson already names."""
    o = {m["key"]: m["artifact"] for m in model_catalog.catalog_for("ollama")["models"]}
    v = {m["key"]: m["artifact"] for m in model_catalog.catalog_for("vllm")["models"]}
    both = [k for k in o if o[k] and v[k]]
    assert both, "at least one model must resolve on both backends"
    for k in both:
        assert o[k] != v[k], f"{k}: the same identifier cannot serve both backends"


# --------------------------------------------------------------------------- #
#  The identifiers are IMPORTED, never re-typed
# --------------------------------------------------------------------------- #
def test_ollama_rows_are_read_from_their_source_catalogue(monkeypatch):
    """Behavioural, because a string-equality assertion passes just as well against a
    hard-coded copy -- which is the thing being prevented. The size travels with the
    tag, so changing it upstream must change what the catalogue publishes."""
    import src.llm.ollama as O

    patched = [dict(row) for row in O.MODEL_CATALOG]
    for row in patched:
        if row.get("tag") == "granite4.1:3b":
            row["size"] = "~999 GB"
    monkeypatch.setattr(O, "MODEL_CATALOG", patched)

    got = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    assert got["granite-4-1-3b"]["size"] == "~999 GB", (
        "the catalogue must READ its rows, not carry its own copy"
    )


def test_a_tag_renamed_upstream_is_reported_never_a_silent_disappearance(monkeypatch):
    """The tag is the join key -- ``MODEL_CATALOG`` rows have no other identity -- so a
    rename leaves this reference dangling.

    That is survivable; a model vanishing from the operator's list with nothing saying
    why is not. This exact case was caught by the previous test failing against the
    first implementation, which returned an empty row and rendered an unavailable entry
    with no reason at all.
    """
    import src.llm.ollama as O

    patched = [dict(row) for row in O.MODEL_CATALOG]
    for row in patched:
        if row.get("tag") == "granite4.1:3b":
            row["tag"] = "granite4.2:3b"
    monkeypatch.setattr(O, "MODEL_CATALOG", patched)

    got = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    entry = got["granite-4-1-3b"]
    assert entry["available"] is False
    assert "drifted apart" in entry["absent_reason"]
    assert "granite4.1:3b" in entry["absent_reason"], "the dangling reference is named"


def test_hf_identifiers_follow_the_bench_roster(monkeypatch):
    import src.llm.bench_roster as B

    patched = [dict(e) for e in B.BENCH_ROSTER]
    for e in patched:
        if e["key"] == "qwen35-0-8b":
            e["hf"] = dict(e["hf"], repo="Qwen/CHANGED")
    monkeypatch.setattr(B, "BENCH_ROSTER", patched)

    got = {m["key"]: m["artifact"] for m in model_catalog.catalog_for("vllm")["models"]}
    assert got["qwen35-0-8b"] == "Qwen/CHANGED"


def test_the_default_follows_its_own_constants(monkeypatch):
    import src.llm.ollama as O

    monkeypatch.setattr(O, "MINISTRAL_VLLM_MODEL", "mistralai/CHANGED")
    got = {m["key"]: m["artifact"] for m in model_catalog.catalog_for("vllm")["models"]}
    assert got[model_catalog.DEFAULT_KEY] == "mistralai/CHANGED"


def test_the_module_states_both_source_dates():
    """The rows come from two dated registries; one "as of" would be true of half the
    list."""
    as_of = model_catalog.catalog_for("ollama")["as_of"]
    from src.llm.bench_roster import BENCH_ROSTER_AS_OF
    from src.llm.ollama import CATALOG_AS_OF

    assert as_of["roster"] == BENCH_ROSTER_AS_OF
    assert as_of["ollama_catalog"] == CATALOG_AS_OF


# --------------------------------------------------------------------------- #
#  The specific absences, named
# --------------------------------------------------------------------------- #
def test_granite_has_no_invented_huggingface_repo():
    """The plausible guess is the defect. Nothing in this tree records Granite's HF
    repo id, so vLLM must be told that rather than handed a name."""
    v = {m["key"]: m for m in model_catalog.catalog_for("vllm")["models"]}
    for key in ("granite-4-1-3b", "granite-4-1-8b"):
        assert v[key]["available"] is False
        assert v[key]["artifact"] is None
        assert "never guesses" in v[key]["absent_reason"]


def test_but_granite_is_perfectly_available_on_ollama():
    """The negative-space twin: an over-cautious catalogue that dropped Granite
    everywhere would lose a model the operator asked for and CAN have."""
    o = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    assert o["granite-4-1-3b"]["available"] is True
    assert o["granite-4-1-3b"]["artifact"] == "granite4.1:3b"


def test_lfm_instruct_has_no_substituted_ollama_tag():
    """A community re-upload under a name nobody verified is not the same model, and
    substituting one is the recorded roster rule this catalogue inherits."""
    o = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    entry = o["lfm25-1-2b-instruct"]
    assert entry["available"] is False
    assert "community re-upload" in entry["absent_reason"]


# --------------------------------------------------------------------------- #
#  WHERE a build exists, as a fact about the MODEL rather than the machine
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS)
def test_every_model_says_which_backends_have_a_build(backend):
    """"When a model only exists in one, mention it like 'ollama only'."

    Distinct from ``available``, which is about the backend serving right now. A
    reader needs both: "Ollama only" is a fact about the model, "not available for
    vllm" is a fact about this machine, and collapsing them makes an Ollama-only
    model look discontinued to someone running vLLM.
    """
    for m in model_catalog.catalog_for(backend)["models"]:
        assert m["available_on"], f"{m['key']} has no build anywhere -- it should not be listed"
        assert set(m["available_on"]) <= {"ollama", "vllm"}
        if len(m["available_on"]) == 1:
            assert m["only_label"] in {"Ollama only", "Hugging Face only"}
        else:
            assert m["only_label"] is None, "a model on both backends is not 'only' anything"


def test_the_only_label_names_the_backend_that_HAS_it_not_the_active_one():
    """The label must not flip with the active backend -- it describes the model.

    Granite is Ollama-only whether or not you are running Ollama; a label computed
    from the active backend would read "Hugging Face only" to a vLLM user, which is
    exactly backwards.
    """
    for backend in BACKENDS:
        by = {m["key"]: m for m in model_catalog.catalog_for(backend)["models"]}
        assert by["granite-4-1-3b"]["only_label"] == "Ollama only"
        assert by["lfm25-1-2b-instruct"]["only_label"] == "Hugging Face only"


def test_an_unusable_row_still_names_the_identifier_that_does_exist():
    """A refusal that also says what exists elsewhere is informative; one that only
    says "no" sends the operator looking for a model that is right there."""
    v = {m["key"]: m for m in model_catalog.catalog_for("vllm")["models"]}
    assert v["granite-4-1-3b"]["available"] is False
    assert v["granite-4-1-3b"]["other_artifact"] == "granite4.1:3b"

    o = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    assert o["lfm25-1-2b-instruct"]["available"] is False
    assert o["lfm25-1-2b-instruct"]["other_artifact"] == "LiquidAI/LFM2.5-1.2B-Instruct"


def test_a_dual_build_model_reports_the_other_side_too():
    """The twin: ``other_artifact`` is not an unavailable-only field, so a row can
    always say what the other backend would fetch."""
    o = {m["key"]: m for m in model_catalog.catalog_for("ollama")["models"]}
    mini = o[model_catalog.DEFAULT_KEY]
    assert mini["available"] is True
    assert mini["other_artifact"] == "mistralai/Ministral-3-3B-Instruct-2512"
    assert mini["artifact"] != mini["other_artifact"]


# --------------------------------------------------------------------------- #
#  Resolving a selection
# --------------------------------------------------------------------------- #
def test_identifiers_for_resolves_what_it_can_and_accounts_for_the_rest():
    ok, refused = model_catalog.identifiers_for(
        "vllm", ["qwen35-0-8b", "granite-4-1-3b", model_catalog.DEFAULT_KEY]
    )
    assert [m["key"] for m in ok] == ["qwen35-0-8b", model_catalog.DEFAULT_KEY]
    assert [r["key"] for r in refused] == ["granite-4-1-3b"]
    assert refused[0]["reason"], "a refusal without a reason is just a disappearance"


def test_an_unknown_key_is_refused_not_ignored():
    ok, refused = model_catalog.identifiers_for("ollama", ["not-a-model"])
    assert ok == []
    assert refused[0]["reason"] == "not in the model catalogue"


def test_nothing_selected_resolves_to_nothing():
    assert model_catalog.identifiers_for("ollama", []) == ([], [])


@pytest.mark.parametrize("weird", ["VLLM", " vllm ", "nonsense", ""])
def test_a_malformed_backend_falls_back_to_ollama_rather_than_erroring(weird):
    """Ollama is the ruled fallback everywhere else in this app; a catalogue that
    raised here would take the whole AI tab down over a query-string typo."""
    out = model_catalog.catalog_for(weird)
    assert out["backend"] in BACKENDS
