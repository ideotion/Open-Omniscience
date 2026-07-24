"""
Tests for the B6 (2026-07-24 Session B) LLM-backed perception extraction adapter
(src/ai_layer/perception.py). Pure parser tests -- no network, no client.
Negative-space is mandatory here (the standing skeptic doctrine): every
should-be-empty/malformed input must yield empty lists, never a guess.
"""

from __future__ import annotations

from src.ai_layer import perception as P


def test_parses_a_well_formed_three_line_reply():
    raw = "WHO: World Health Organization; Jane Doe\nWHERE: Geneva\nWHEN: 2024-03-05"
    out = P.parse_perception_reply(raw)
    assert out == {
        "who": ["World Health Organization", "Jane Doe"],
        "where": ["Geneva"],
        "when": ["2024-03-05"],
    }


def test_case_insensitive_labels():
    raw = "who: A\nWhErE: B\nWHEN: 2020"
    out = P.parse_perception_reply(raw)
    assert out == {"who": ["A"], "where": ["B"], "when": ["2020"]}


def test_none_value_yields_empty_list_never_a_fabricated_item():
    raw = "WHO: none\nWHERE: none\nWHEN: none"
    out = P.parse_perception_reply(raw)
    assert out == {"who": [], "where": [], "when": []}


def test_missing_field_line_defaults_to_empty_never_guessed():
    """A reply that only states WHO (WHERE/WHEN lines entirely absent) must NOT
    be treated as "everything else is empty and confirmed" vs "unmeasured" --
    it simply yields empty lists for the missing fields (miss over invent)."""
    raw = "WHO: Someone"
    out = P.parse_perception_reply(raw)
    assert out == {"who": ["Someone"], "where": [], "when": []}


def test_completely_unparseable_reply_yields_all_empty():
    raw = "I cannot help with that request."
    out = P.parse_perception_reply(raw)
    assert out == {"who": [], "where": [], "when": []}


def test_empty_string_and_none_input_yield_all_empty():
    assert P.parse_perception_reply("") == {"who": [], "where": [], "when": []}
    assert P.parse_perception_reply(None) == {"who": [], "where": [], "when": []}


def test_strips_stray_punctuation_and_whitespace_around_items():
    raw = "WHO:  Jane Doe. ; \"John Smith\"  \nWHERE: Paris,\nWHEN: 2024-01-01"
    out = P.parse_perception_reply(raw)
    assert out["who"] == ["Jane Doe", "John Smith"]
    assert out["where"] == ["Paris"]
    assert out["when"] == ["2024-01-01"]


def test_extra_commentary_lines_are_ignored_not_treated_as_a_field():
    raw = "Here is the extraction:\nWHO: A\nWHERE: B\nWHEN: 2020\nHope that helps!"
    out = P.parse_perception_reply(raw)
    assert out == {"who": ["A"], "where": ["B"], "when": ["2020"]}


def test_llm_perception_extract_calls_generate_with_the_constrained_system_prompt():
    calls = []

    class _FakeResult:
        text = "WHO: A\nWHERE: B\nWHEN: 2020"

    class _FakeClient:
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            calls.append((prompt, model, system, keep_alive))
            return _FakeResult()

    out = P.llm_perception_extract(_FakeClient(), "some text", model="m", keep_alive="5m")
    assert out == {"who": ["A"], "where": ["B"], "when": ["2020"]}
    assert len(calls) == 1
    prompt, model, system, keep_alive = calls[0]
    assert prompt == "some text"
    assert model == "m"
    assert system == P.build_system()
    assert keep_alive == "5m"


def test_llm_perception_extract_propagates_client_errors_for_the_caller_to_handle():
    from src.llm.ollama import LLMUnavailable

    class _RaisingClient:
        def generate(self, *a, **kw):
            raise LLMUnavailable("down")

    import pytest

    with pytest.raises(LLMUnavailable):
        P.llm_perception_extract(_RaisingClient(), "text", model="m")


def test_a_hallucinated_extra_field_label_is_ignored_not_stored():
    """A model inventing a fourth field (e.g. "WHAT:") must never be captured --
    the standing ruling scopes LLM perception to who/where/when only, no "what"."""
    raw = "WHO: A\nWHERE: B\nWHEN: 2020\nWHAT: something happened"
    out = P.parse_perception_reply(raw)
    assert out == {"who": ["A"], "where": ["B"], "when": ["2020"]}
    assert "what" not in out


# --------------------------------------------------------------------------- #
# run_perception_eval_against_model -- wires the S6.5 harness to the REAL
# adapter over an injected client (no network; a stub stands in for the model).
# --------------------------------------------------------------------------- #


def test_run_perception_eval_against_model_reports_ok_with_metadata():
    class _AlwaysNothingClient:
        """A model that always says "none" for every field -- a real client
        stand-in that never invents anything; the harness scores it honestly
        (low recall, but zero hallucination on the negative case)."""

        def generate(self, prompt, *, model, system=None, keep_alive=None):
            class _R:
                text = "WHO: none\nWHERE: none\nWHEN: none"

            return _R()

    out = P.run_perception_eval_against_model(
        _AlwaysNothingClient(), model="stub:test", backend_name="ollama"
    )
    assert out["status"] == "ok"
    assert out["model"] == "stub:test"
    assert out["backend"] == "ollama"
    assert out["prompt_version"] == P.PERCEPTION_PROMPT_VERSION
    report = out["report"]
    assert report["n_cases"] > 0
    # a should-be-empty (negative) case must yield ZERO hallucination for a
    # model that says "none" for everything.
    assert report["by_phenomenon"]["negative"]["who"]["fp"] == 0
    # recall is 0 across the board (it never extracts anything) -- an honest,
    # measured low score, not a fabricated pass.
    assert report["by_field_overall"]["who"]["recall"] == 0.0


def test_run_perception_eval_against_model_degrades_honestly_on_an_outage():
    from src.llm.ollama import LLMUnavailable

    class _RaisingClient:
        def generate(self, *a, **kw):
            raise LLMUnavailable("simulated outage")

    out = P.run_perception_eval_against_model(_RaisingClient(), model="stub:test")
    assert out["status"] == "unavailable"
    assert "simulated outage" in out["detail"]
    assert "report" not in out  # never a fabricated partial report
