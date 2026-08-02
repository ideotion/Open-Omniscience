"""Per-language task gates read off the comparative bench (E-S3, ruling 16).

The interesting assertions here are about the two DIRECTIONS. A gate that licenses
must refuse the unmeasured, or it grants permission on an absence of measurement. A
gate that vetoes must NOT refuse the unmeasured, or it silently disables everything
the gold set was never written to cover. Both are the conservative choice; getting
them backwards is a real, easy mistake, so both are pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ai_layer import task_gates as TG


def _bench(tasks: dict, *, model="m1", backend="ollama") -> dict:
    return {"results": {f"{backend}|{model}": {"model": model, "backend": backend, "tasks": tasks}}}


# --------------------------------------------------------------------------- #
#  The licensing gate (triage / source tags: the language is known before the call).
# --------------------------------------------------------------------------- #
def test_a_language_the_model_garbles_is_gated_and_a_clean_one_is_not() -> None:
    gate = TG.gate_from_bench(
        _bench({"triage": {"status": "ok", "by_language": {
            "en": {"asked": 40, "format_validity": 0.95},
            "ar": {"asked": 40, "format_validity": 0.10},
        }}}),
        "triage",
    )
    assert TG.task_gate("en", gate)[0] is True
    ok, reason = TG.task_gate("ar", gate)
    assert ok is False and "below" in reason


def test_a_language_with_too_few_observations_is_unmeasured_not_judged() -> None:
    """One item deciding a language's fate is a coin toss wearing a number."""
    gate = TG.gate_from_bench(
        _bench({"triage": {"status": "ok", "by_language": {
            "sv": {"asked": 1, "format_validity": 1.0},
        }}}),
        "triage",
    )
    assert gate["sv"]["active"] is None
    ok, reason = TG.task_gate("sv", gate)
    assert ok is False and "UNMEASURED" in reason and "failed" not in reason


def test_a_language_absent_from_the_bench_is_never_assumed_safe() -> None:
    gate = TG.gate_from_bench(
        _bench({"triage": {"status": "ok", "by_language": {"en": {"asked": 9, "format_validity": 1.0}}}}),
        "triage",
    )
    assert TG.task_gate("th", gate) == (False, "never evaluated")


def test_no_bench_at_all_licenses_nothing() -> None:
    assert TG.gate_from_bench(None, "triage") == {}
    assert TG.task_gate("en", {})[0] is False


def test_a_task_that_errored_yields_no_evidence_rather_than_a_pass() -> None:
    gate = TG.gate_from_bench(_bench({"triage": {"status": "error", "detail": "boom"}}), "triage")
    assert gate == {}


def test_source_tags_uses_the_same_shape() -> None:
    gate = TG.gate_from_bench(
        _bench({"source_tags": {"status": "ok", "by_language": {
            "fr": {"asked": 6, "format_validity": 1.0},
        }}}),
        "source_tags",
    )
    assert TG.task_gate("fr", gate)[0] is True


def test_an_unknown_task_is_refused_loudly() -> None:
    with pytest.raises(ValueError):
        TG.gate_from_bench(_bench({}), "summarize")


# --------------------------------------------------------------------------- #
#  Picking the right row.
# --------------------------------------------------------------------------- #
def test_a_model_that_was_not_benched_gets_no_evidence_from_another_model() -> None:
    """Reading one model's numbers as another's would be a fabricated verdict about
    the model actually running."""
    bench = _bench({"triage": {"status": "ok", "by_language": {"en": {"asked": 9, "format_validity": 1.0}}}})
    assert TG.gate_from_bench(bench, "triage", model="a-different-model") == {}


def test_the_same_model_on_two_backends_is_disambiguated() -> None:
    bench = {
        "results": {
            "ollama|m": {"model": "m", "backend": "ollama", "tasks": {
                "triage": {"status": "ok", "by_language": {"en": {"asked": 9, "format_validity": 1.0}}}}},
            "vllm|m": {"model": "m", "backend": "vllm", "tasks": {
                "triage": {"status": "ok", "by_language": {"en": {"asked": 9, "format_validity": 0.1}}}}},
        }
    }
    assert TG.gate_from_bench(bench, "triage", model="m", backend="ollama")["en"]["active"] is True
    assert TG.gate_from_bench(bench, "triage", model="m", backend="vllm")["en"]["active"] is False


def test_several_models_and_no_name_given_picks_none_rather_than_guessing() -> None:
    bench = {
        "results": {
            "ollama|a": {"model": "a", "backend": "ollama", "tasks": {}},
            "ollama|b": {"model": "b", "backend": "ollama", "tasks": {}},
        }
    }
    assert TG.gate_from_bench(bench, "triage") == {}


# --------------------------------------------------------------------------- #
#  The veto (langdetect: the language is the ANSWER, so the input cannot be gated).
# --------------------------------------------------------------------------- #
def _langdetect_bench(by_answer: dict) -> dict:
    return _bench({"langdetect": {"status": "ok", "by_answer": by_answer}})


def test_the_langdetect_gate_is_built_from_precision_over_the_models_own_labels() -> None:
    """Recall per TRUE language says nothing about whether the label just emitted can
    be trusted; using it would substitute one measure for another silently."""
    gate = TG.gate_from_bench(
        _langdetect_bench({
            "zh": {"answered": 4, "precision": 0.25},
            "en": {"answered": 5, "precision": 1.0},
        }),
        "langdetect",
    )
    assert gate["zh"]["active"] is False and gate["en"]["active"] is True
    assert "precision" in gate["zh"]["reason"]


def test_a_measured_wrong_label_is_vetoed() -> None:
    gate = TG.gate_from_bench(_langdetect_bench({"zh": {"answered": 4, "precision": 0.25}}), "langdetect")
    refused, why = TG.answer_vetoed("zh", gate)
    assert refused is True and "precision" in why


def test_an_UNMEASURED_label_is_not_vetoed_and_that_asymmetry_is_deliberate() -> None:
    """THE direction that matters. The gold set covers thirteen languages; the
    detector can name far more. Refusing every unmeasured label would disable
    detection for languages nobody ever tested rather than for languages that failed
    — an over-tight gate reading as conservative while deleting data that works."""
    gate = TG.gate_from_bench(_langdetect_bench({"zh": {"answered": 4, "precision": 0.25}}), "langdetect")
    assert TG.answer_vetoed("sw", gate) == (False, "")
    # ...and a label present but under-observed is likewise not vetoed on one case.
    gate2 = TG.gate_from_bench(_langdetect_bench({"sw": {"answered": 1, "precision": 0.0}}), "langdetect")
    assert gate2["sw"]["active"] is None
    assert TG.answer_vetoed("sw", gate2)[0] is False


def test_no_bench_vetoes_nothing() -> None:
    """Absence of a bench must not silently disable a feature that has run since B15."""
    assert TG.answer_vetoed("zh", {}) == (False, "")


def test_a_cleared_label_is_not_vetoed() -> None:
    gate = TG.gate_from_bench(_langdetect_bench({"en": {"answered": 5, "precision": 1.0}}), "langdetect")
    assert TG.answer_vetoed("en", gate)[0] is False
