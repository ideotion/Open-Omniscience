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
