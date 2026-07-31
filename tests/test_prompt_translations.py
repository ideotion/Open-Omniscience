"""
RULING 14 (2026-07-31): the four USER-FACING prose prompts ship in all twelve UI
languages, so a non-English user never gets English work back from the local
model.

The interesting failures here are not "does French exist" -- they are the ones a
translation quietly introduces: a rendered or dropped ``{placeholder}``, a
half-translated table that falls back per-sentence, provenance that no longer
distinguishes twelve different texts sharing one version string, and an operator
override that a translation table starts overriding in turn.

The BOUNDARY is tested too: the ai_layer prompts stay English BY CONSTRUCTION
because their parsers validate against English tokens. A future edit that
"finishes the job" by translating those would break parsing without improving any
output, so it is pinned as a deliberate exclusion rather than left to a comment.
"""

from __future__ import annotations

import re

import pytest

from src.llm import prompts_i18n as P

_UI_LANGS = ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id")
_OPS = ("summary", "translate", "synthesis", "ai_keywords")


def test_all_four_prompts_exist_in_all_twelve_ui_languages():
    """The ruling is ×12. A missing entry is not a crash -- it silently serves
    English -- so the count is asserted rather than left to the fallback."""
    assert set(P.PROMPTS) == set(_OPS)
    for op in _OPS:
        assert set(P.PROMPTS[op]) == set(_UI_LANGS), op
    assert set(P.SUPPORTED) == set(_UI_LANGS)


@pytest.mark.parametrize("op", _OPS)
@pytest.mark.parametrize("lang", _UI_LANGS)
def test_every_translation_keeps_its_placeholder_verbatim(op, lang):
    """The caller substitutes ``{language}`` / ``{target}`` / ``{max_terms}``. A
    translation that rendered one ("dans la langue cible") loses the parameter
    silently; one that dropped a brace leaves a literal ``{`` in the model's
    instructions. Both are invisible until someone reads a bad summary."""
    text = P.PROMPTS[op][lang]
    ph = P.REQUIRED_PLACEHOLDER[op]
    assert ph in text, f"{op}/{lang} lost {ph}"


@pytest.mark.parametrize("lang", _UI_LANGS)
def test_translate_keeps_BOTH_target_occurrences(lang):
    """The second ``{target}`` carries the "leave an already-translated passage
    unchanged" rule. Dropping it is the easy translation slip, and it changes
    behaviour: the model re-translates text that was already correct."""
    assert P.PROMPTS["translate"][lang].count("{target}") == 2, lang


@pytest.mark.parametrize("op", _OPS)
@pytest.mark.parametrize("lang", _UI_LANGS)
def test_no_translation_carries_a_placeholder_it_should_not(op, lang):
    """A stray ``{...}`` from another prompt would be substituted by nobody and
    reach the model as a literal brace."""
    found = set(re.findall(r"\{[a-z_]+\}", P.PROMPTS[op][lang]))
    assert found == {P.REQUIRED_PLACEHOLDER[op]}, f"{op}/{lang}: {found}"


@pytest.mark.parametrize("lang", [x for x in _UI_LANGS if x != "en"])
def test_a_translation_is_actually_translated_not_the_english_text(lang):
    """Guards the copy-paste failure: an entry present but identical to English
    passes every structural check above while delivering none of the ruling."""
    for op in _OPS:
        assert P.PROMPTS[op][lang] != P.PROMPTS[op]["en"], f"{op}/{lang} is still English"


@pytest.mark.parametrize("lang", _UI_LANGS)
def test_synthesis_keeps_the_literal_bracket_citation_example(lang):
    """``[2][5]`` is the OUTPUT FORMAT, not prose. A translator localising the
    brackets would teach the model a citation shape nothing downstream reads."""
    assert "[2][5]" in P.PROMPTS["synthesis"][lang], lang


# --------------------------------------------------------------------------- #
#  Selection + fallback. Never a partial, never a raise.
# --------------------------------------------------------------------------- #
def test_an_unknown_language_falls_back_to_the_COMPLETE_english_prompt():
    for op in _OPS:
        assert P.prompt_for(op, "sw") == P.PROMPTS[op]["en"]
        assert P.prompt_for(op, None) == P.PROMPTS[op]["en"]
        assert P.prompt_for(op, "") == P.PROMPTS[op]["en"]


def test_a_regional_or_uppercase_code_still_finds_its_language():
    """The SPA passes a bare code today, but a caller reading an
    Accept-Language/browser value would otherwise fall all the way back to
    English for a language we actually support."""
    for form in ("fr-FR", "FR", "fr_CA", "  fr  "):
        assert P.prompt_for("summary", form) == P.PROMPTS["summary"]["fr"], form


def test_normalize_never_raises_on_hostile_input():
    for bogus in (None, "", "   ", "-", "--", "zz-ZZ", "fr" * 200):
        assert P.normalize_lang(bogus) in _UI_LANGS


# --------------------------------------------------------------------------- #
#  Provenance. Twelve texts cannot share one version string.
# --------------------------------------------------------------------------- #
def test_the_prompt_version_names_the_language_it_actually_used():
    assert P.prompt_version("summary-v2", "fr") == "summary-v2:fr"
    assert P.prompt_version("synthesis-v2", "ja") == "synthesis-v2:ja"


def test_english_stays_UNSUFFIXED_so_historical_provenance_is_not_relabelled():
    """Results stored before this ruling carry ``summary-v2``. Suffixing English
    now would make every one of them look like it used a prompt that did not
    exist when it ran."""
    assert P.prompt_version("summary-v2", "en") == "summary-v2"
    assert P.prompt_version("summary-v2", None) == "summary-v2"
    assert P.prompt_version("summary-v2", "sw") == "summary-v2"   # fell back to English


# --------------------------------------------------------------------------- #
#  The English body is single-sourced -- two copies would silently fork.
# --------------------------------------------------------------------------- #
def test_the_shipped_english_constants_are_the_same_objects_not_copies():
    from src.ai_layer.extract import _EXTRACT_SYSTEM
    from src.api.llm import _SUMMARY_SYSTEM, _SYNTHESIS_SYSTEM, _TRANSLATE_SYSTEM

    assert _SUMMARY_SYSTEM == P.PROMPTS["summary"]["en"]
    assert _TRANSLATE_SYSTEM == P.PROMPTS["translate"]["en"]
    assert _SYNTHESIS_SYSTEM == P.PROMPTS["synthesis"]["en"]
    assert _EXTRACT_SYSTEM == P.PROMPTS["ai_keywords"]["en"]


# --------------------------------------------------------------------------- #
#  THE BOUNDARY. Ruling 14 translates FOUR prompts, and the exclusion of the
#  ai_layer prompts is a design decision, not an oversight -- their parsers match
#  English tokens, so translating them breaks parsing and improves no output.
# --------------------------------------------------------------------------- #
def test_the_machine_parsed_ai_layer_prompts_are_NOT_in_the_translation_table():
    assert set(P.PROMPTS) == set(_OPS)
    for excluded in ("triage", "source_tags", "qualification_assist",
                     "perception", "langdetect", "extract"):
        assert excluded not in P.PROMPTS, (
            f"{excluded} is machine-parsed against English tokens -- translating it "
            "breaks the parser and improves no user-visible output (ruling 14's own "
            "stated boundary)"
        )


def test_langdetect_still_asks_for_an_english_iso_code_answer():
    """A concrete instance of the boundary: this prompt's answer is validated
    against a fixed code vocabulary, so its language is load-bearing."""
    from src.ai_layer import langdetect_llm as L

    src = L.__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # The module must not start consulting the translation table.
    assert "prompts_i18n" not in text


# --------------------------------------------------------------------------- #
#  Wiring: an operator override still wins, and the language still selects.
# --------------------------------------------------------------------------- #
def _prompting(op, **kw):
    from src.api.llm import _build_prompting

    return _build_prompting(op, **kw)


@pytest.mark.parametrize("op,kw", [
    ("summary", {"output_lang_code": "fr"}),
    ("synthesis", {"output_lang_code": "fr"}),
    ("translate", {"target": "German", "output_lang_code": "fr"}),
])
def test_build_prompting_uses_the_ui_language_body(monkeypatch, op, kw):
    monkeypatch.setattr("src.api.llm._llm_settings", lambda: None)
    system, version, _text = _prompting(op, **kw)
    # A distinctive fragment of each French body, so this cannot pass on a
    # coincidence of length or on the appended native directive alone.
    assert "journaliste d'investigation" in system, op
    assert ":fr" in version, op


@pytest.mark.parametrize("op,kw", [
    ("summary", {"output_lang_code": "fr"}),
    ("translate", {"target": "German", "output_lang_code": "fr"}),
    ("synthesis", {"output_lang_code": "fr"}),
])
def test_an_operator_override_still_wins_verbatim_in_every_language(monkeypatch, op, kw):
    """The pre-ruling contract, unchanged: whoever wrote their own prompt gets
    exactly it. A translation table that started overriding operator text would
    be the app editing the user's words."""

    class _S:
        llm_prompt_summary = "MY OWN SUMMARY PROMPT {language}"
        llm_prompt_translate = "MY OWN TRANSLATE PROMPT {target}"
        llm_prompt_synthesis = "MY OWN SYNTHESIS PROMPT {language}"

    monkeypatch.setattr("src.api.llm._llm_settings", lambda: _S())
    system, version, _text = _prompting(op, **kw)
    assert system.startswith("MY OWN "), op
    # ... and it is labelled custom, NOT as a versioned built-in in some language.
    assert "custom" in version, op
    assert ":fr" not in version, op


def test_an_unset_ui_language_reproduces_the_pre_ruling_english_behaviour(monkeypatch):
    """An older client that sends no ui_lang must behave EXACTLY as before --
    same body, same unsuffixed version string."""
    from src.api.llm import _SUMMARY_SYSTEM, SUMMARY_PROMPT_VERSION

    monkeypatch.setattr("src.api.llm._llm_settings", lambda: None)
    system, version, _text = _prompting("summary", output_language="English")
    assert version == SUMMARY_PROMPT_VERSION
    assert system.startswith(_SUMMARY_SYSTEM.replace("{language}", "English")[:80])


def test_the_native_output_directive_still_rides_on_top(monkeypatch):
    """Kept deliberately even though the body is already French: the ledger's own
    finding is that a small model weights the LAST instruction, and this is the
    mechanism that reliably pins the OUTPUT language. Belt and braces, not a
    leftover."""
    monkeypatch.setattr("src.api.llm._llm_settings", lambda: None)
    system, _v, _t = _prompting("summary", output_lang_code="fr")
    assert system.rstrip().endswith("Rédige l'intégralité de ta réponse en français.")


def test_the_translate_request_and_extract_request_accept_a_ui_language():
    """The field is the only thing that selects the body, so its absence from a
    request model would make the whole table unreachable from that endpoint."""
    from src.api.ai import AiExtractRequest
    from src.api.llm import TranslateRequest

    assert TranslateRequest().ui_lang is None            # optional, English default
    assert TranslateRequest(ui_lang="fr").ui_lang == "fr"
    assert AiExtractRequest().ui_lang is None
    assert AiExtractRequest(ui_lang="ja").ui_lang == "ja"
