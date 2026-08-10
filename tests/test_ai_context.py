"""Context budgeting (E-S4, ruling 16).

The load-bearing assertions are the two absences: an unmeasured machine gets NO
recommendation rather than a guessed one, and a user-driven chunking covers 100 % of
the text rather than a plausible-looking prefix.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ai_layer import context as C


# --------------------------------------------------------------------------- #
#  Script + estimate.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,script",
    [
        ("The summit opened in Geneva on Tuesday.", "latin"),
        ("Саммит прошёл в Москве вчера утром.", "cyrillic"),
        ("峰会在北京举行，与会者众多。", "cjk"),
        ("عُقد الاجتماع في القاهرة أمس.", "arabic"),
        ("शिखर सम्मेलन दिल्ली में हुआ।", "devanagari"),
        ("", "latin"),
        ("1234 5678 !!!", "latin"),
    ],
)
def test_the_dominant_script_is_read_off_the_text(text, script) -> None:
    assert C.dominant_script(text) == script


def test_a_denser_script_gets_a_smaller_character_budget() -> None:
    """A Chinese character is roughly a token; a Latin word is roughly four
    characters. Using one ratio for both would overflow the window on one and waste
    it on the other."""
    assert C.text_budget_chars(8192, "cjk") < C.text_budget_chars(8192, "latin")


def test_the_budget_reserves_room_for_the_answer() -> None:
    """A summary shares the window with its input; spending all of it on the article
    leaves the model no room to reply."""
    assert C.text_budget_chars(8192, "latin") < 8192 * C.chars_per_token("latin")


def test_no_configured_context_keeps_the_old_constant_rather_than_guessing() -> None:
    assert C.text_budget_chars(None) == C.LEGACY_TEXT_BUDGET_CHARS
    assert C.text_budget_chars(0) == C.LEGACY_TEXT_BUDGET_CHARS
    # ...and so does a context too small to hold prompt + answer at all.
    assert C.text_budget_chars(64) == C.LEGACY_TEXT_BUDGET_CHARS


# --------------------------------------------------------------------------- #
#  The recommendation — both absences.
# --------------------------------------------------------------------------- #
def test_an_unmeasured_corpus_gets_no_recommendation() -> None:
    out = C.recommend_num_ctx(p95_chars=None, ram_gb=32)
    assert out["recommended"] is None
    assert "unmeasured" in out["reason"]


def test_an_unmeasured_machine_gets_no_recommendation() -> None:
    """psutil is an optional extra, so RAM genuinely can be unreadable. A number
    proposed anyway would be one nobody measured."""
    out = C.recommend_num_ctx(p95_chars=8000, ram_gb=None, vram_mb=None)
    assert out["recommended"] is None
    assert "UNMEASURED" in out["reason"]


def test_a_measured_machine_gets_a_real_recommendation_on_a_standard_step() -> None:
    out = C.recommend_num_ctx(p95_chars=8000, script="latin", vram_mb=8192)
    assert out["recommended"] in C._CTX_STEPS
    assert out["needed_tokens_estimate"] > 0
    assert out["afford_basis"] == "VRAM"


def test_vram_is_preferred_over_system_ram_when_both_are_known() -> None:
    out = C.recommend_num_ctx(p95_chars=8000, vram_mb=8192, ram_gb=64)
    assert out["afford_basis"] == "VRAM"


def test_a_small_machine_is_capped_and_says_the_tail_costs_more_calls() -> None:
    """Before 2026-08-10 the honest thing to say here was "the tail gets truncated,
    with disclosure". The ruling removed that trade, so the sentence has to change with
    it: a small window no longer costs COVERAGE, it costs CALLS."""
    out = C.recommend_num_ctx(p95_chars=200_000, script="latin", vram_mb=2048)
    assert out["recommended"] <= C.MAX_NUM_CTX
    assert "read in several parts" in out["reason"]
    assert "truncat" not in out["reason"], "a window no longer costs coverage"


def test_a_huge_machine_is_still_capped_by_the_heuristic_ceiling() -> None:
    """A bigger window is the operator's explicit choice, not something a rule of
    thumb hands out."""
    out = C.recommend_num_ctx(p95_chars=2_000_000, vram_mb=80_000)
    assert out["recommended"] <= C.MAX_NUM_CTX


def test_the_recommendation_states_that_it_is_an_estimate() -> None:
    out = C.recommend_num_ctx(p95_chars=8000, vram_mb=8192)
    assert "ESTIMATES" in out["caveat"] and "not a tokenizer" in out["caveat"]


# --------------------------------------------------------------------------- #
#  Truncation is GONE, not deprecated.
# --------------------------------------------------------------------------- #
def test_there_is_no_truncation_helper_left_to_reach_for() -> None:
    """``head_truncate`` cut an article to the budget and returned a disclosure saying
    so. The maintainer retired that trade on 2026-08-10 ("not acceptable ... otherwise
    it won't work"), and it was DELETED rather than left unused: with no helper to
    truncate with, "no sweep truncates" holds by construction instead of by everyone
    remembering. This guard is why re-adding it is a deliberate act."""
    assert not hasattr(C, "head_truncate")
    assert "head_truncate" not in C.__all__


# --------------------------------------------------------------------------- #
#  Chunking — now the ONLY path, for user-driven work and sweeps alike.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "One paragraph only.",
        "First para.\n\nSecond para.\n\nThird para that is quite a lot longer than the others.",
        "A. B! C? D. " * 200,
        "nopunctuationatallhere" * 400,
        "峰会在北京举行。" * 300,
        "Mixed.\n\n" + ("z" * 5000) + "\n\nTail.",
    ],
)
def test_chunking_covers_the_whole_text_exactly(text) -> None:
    """THE property the user-driven path rests on: a chunker that dropped a separator
    would lose content while looking like it had covered everything."""
    for budget in (50, 200, 1000):
        chunks = C.chunk_text(text, budget)
        assert "".join(chunks) == text, (budget, chunks[:3])
        assert all(len(c) <= budget for c in chunks), [len(c) for c in chunks]


def test_a_text_that_fits_is_one_chunk_so_the_single_call_path_is_unchanged() -> None:
    assert C.chunk_text("short enough", 1000) == ["short enough"]
    assert C.chunk_text("", 1000) == []


def test_chunks_prefer_paragraph_then_sentence_boundaries() -> None:
    """Cutting mid-sentence changes what a translator is asked to translate, so it is
    the last resort rather than the mechanism."""
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = C.chunk_text(text, 45)
    assert len(chunks) > 1
    # every chunk but the last ends at a sentence end (possibly with its space)
    for c in chunks[:-1]:
        assert c.rstrip().endswith((".", "!", "?")), c


def test_a_single_sentence_longer_than_the_budget_is_cut_but_never_dropped() -> None:
    text = "w" * 5000
    chunks = C.chunk_text(text, 1000)
    assert len(chunks) == 5 and "".join(chunks) == text


def test_a_word_count_can_be_converted_and_the_extra_estimate_is_stated() -> None:
    out = C.recommend_num_ctx(p95_words=1200, script="latin", vram_mb=8192)
    assert out["recommended"] is not None
    assert "characters per word" in out["method"]
    assert out["inputs"]["p95_words"] == 1200


def test_an_unsegmented_script_is_not_converted_from_words() -> None:
    """`word_count` for Chinese is one giant token; multiplying it by anything
    produces a confident wrong number."""
    assert C.chars_from_words(1200, "cjk") is None
    out = C.recommend_num_ctx(p95_words=1200, script="cjk", vram_mb=8192)
    assert out["recommended"] is None
    assert "unsegmented" in out["method"]
