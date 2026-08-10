"""Background sweeps read the WHOLE article (maintainer ruling, 2026-08-10).

*"We need to change that articles are truncated for background sweeps, it's not
acceptable. Background sweeps should process entire articles, otherwise it won't
work."*

The guard that matters is the first one: every character of a long article reaches the
model. Reverting any sweep to ``text[:budget]`` fails it immediately, which is the
whole point — the old code was honest ABOUT truncating (perception disclosed it) and
that honesty is exactly why nobody noticed the extraction was reading the opening of
every long article and nothing else.

The rest of the file is negative space: the tail must actually survive into the result
(coverage that is thrown away at the merge is not coverage), a cap must not restore the
head bias it was supposed to be innocent of, and an article that FITS must still be one
call so the common path is unchanged.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ai_layer import coverage as COV


@pytest.fixture(autouse=True)
def _no_cached_window():
    """The resolved window is process-cached for five minutes (the probe shells out to
    nvidia-smi). A test that set one machine's window must not describe the next."""
    COV.reset_window_cache()
    yield
    COV.reset_window_cache()


class _Client:
    """Records every prompt it is handed and replies with a per-call canned answer."""

    def __init__(self, replies=None):
        self.prompts: list[str] = []
        self.options: list[dict] = []
        self.systems: list[str] = []
        self._replies = list(replies or [])

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.prompts.append(prompt)
        self.options.append(dict(options or {}))
        self.systems.append(system or "")
        i = len(self.prompts) - 1
        text = self._replies[i] if i < len(self._replies) else (self._replies[-1] if self._replies else "")

        class R:
            pass

        r = R()
        r.text = text
        r.model = model
        return r


def _article(parts: int, per: int) -> str:
    """A long article made of numbered paragraphs, so a part can be identified."""
    return "\n\n".join(f"P{i} " + ("word " * (per // 5)) for i in range(parts))


# --------------------------------------------------------------------------- #
#  THE GUARANTEE.
# --------------------------------------------------------------------------- #
def test_every_character_of_a_long_article_reaches_the_model():
    """THE ONE THAT MATTERS. The parts the sweep sends must CONCATENATE BACK to the
    article — not "cover most of it", not "cover it with the separators dropped"."""
    from src.ai_layer.perception import llm_perception_extract

    text = _article(40, 500)
    c = _Client(["WHO: none\nWHERE: none\nWHEN: none"])
    llm_perception_extract(c, text, model="m", budget_chars=1000)

    assert len(c.prompts) > 1, "a 20k-character article at a 1k budget is not one call"
    assert "".join(c.prompts) == text, "the parts must BE the article, exactly"


def test_a_name_only_in_the_tail_survives_into_the_result():
    """Coverage thrown away at the merge is not coverage. Under the old head-cut this
    name was never seen; under a merge that only kept the first part's answer it would
    be seen and then discarded — both fail here."""
    from src.ai_layer.perception import llm_perception_extract

    text = _article(30, 500)
    replies = ["WHO: Early Person\nWHERE: none\nWHEN: none"] * 20
    replies[-1] = "WHO: Tail Person\nWHERE: Tail City\nWHEN: 2026-01-01"
    c = _Client(replies)
    out = llm_perception_extract(c, text, model="m", budget_chars=1000)

    assert "Tail Person" in out["who"], out["who"]
    assert "Early Person" in out["who"], "the head is not sacrificed to the tail either"
    assert out["where"] == ["Tail City"]
    assert out["coverage"]["parts"] == len(c.prompts)
    assert out["coverage"]["chars"] == len(text)
    assert out["coverage"]["complete"] is True


def test_the_same_name_in_every_part_is_reported_once():
    from src.ai_layer.perception import llm_perception_extract

    c = _Client(["WHO: Ada Lovelace\nWHERE: none\nWHEN: none"])
    out = llm_perception_extract(c, _article(20, 500), model="m", budget_chars=1000)
    assert out["who"] == ["Ada Lovelace"]


def test_an_article_that_fits_is_one_call_and_carries_no_multi_part_note():
    """The common path must be unchanged: same single prompt, same single call."""
    from src.ai_layer.perception import llm_perception_extract

    c = _Client(["WHO: A\nWHERE: B\nWHEN: 2026"])
    out = llm_perception_extract(c, "A short article about A in B.", model="m", budget_chars=6000)
    assert len(c.prompts) == 1
    assert c.prompts[0] == "A short article about A in B."
    assert out["coverage"]["parts"] == 1 and "note" not in out["coverage"]


def test_empty_text_costs_no_call_at_all():
    from src.ai_layer.perception import llm_perception_extract

    c = _Client(["WHO: invented"])
    out = llm_perception_extract(c, "", model="m", budget_chars=6000)
    assert c.prompts == [], "there is nothing to read, so there is nothing to ask"
    assert out["who"] == [] and out["coverage"]["parts"] == 0


# --------------------------------------------------------------------------- #
#  The keyword sweep, where the cap is the trap.
# --------------------------------------------------------------------------- #
def test_keyword_extraction_reads_the_whole_article():
    from src.ai_layer.extract import extract_terms

    text = _article(30, 500)
    c = _Client(["alpha"])
    extract_terms(c, "T", text, model="m", budget_chars=1000)
    # every prompt is "Article title: T\n\n<part>"; the parts must rebuild the article.
    # ``extract_terms`` strips surrounding whitespace first — that is tidying, not
    # truncation, and the comparison says which is which rather than papering over it.
    head = "Article title: T\n\n"
    assert all(p.startswith(head) for p in c.prompts)
    assert len(c.prompts) > 1
    assert "".join(p[len(head):] for p in c.prompts) == text.strip()


def test_the_term_cap_is_spread_across_parts_not_spent_on_the_opening():
    """The trap the round-robin merge exists for: concatenate-then-cut would fill
    ``max_terms`` from the first part or two and look exactly like full coverage."""
    from src.ai_layer.extract import extract_terms

    text = _article(30, 500)
    # every part offers five terms of its own
    replies = [f"p{i}a\np{i}b\np{i}c\np{i}d\np{i}e" for i in range(40)]
    c = _Client(replies)
    terms = extract_terms(c, "T", text, model="m", max_terms=10, budget_chars=1000)

    assert len(terms) == 10
    contributing = {t[: t.index("a") if "a" in t else 2] for t in terms}
    assert len(contributing) >= 5, (
        f"10 terms drawn from {len(c.prompts)} parts came from too few of them: {terms}"
    )


def test_a_zero_part_run_reports_a_real_zero():
    """A measured zero must stay zero on the way out. The counting side of this is
    defensive only — the batch gates empty content out before it can run — but the
    PRODUCING side is reachable and is what a reader would be misled by: `parts: 0`
    means no call was made, and any consumer defaulting a falsy value to 1 turns that
    into a call that never happened."""
    parts, cov = COV.split_for_sweep("", 4000)
    assert parts == [] and cov["parts"] == 0
    assert cov["chars"] == 0 and cov["complete"] is True


def test_merge_items_dedupes_case_insensitively_keeping_the_first_form():
    assert COV.merge_items([["Ada"], ["ADA"], ["ada", "Grace"]]) == ["Ada", "Grace"]


def test_merge_items_round_robins():
    """One from each part before any part contributes twice."""
    assert COV.merge_items([["a1", "a2"], ["b1", "b2"]]) == ["a1", "b1", "a2", "b2"]


# --------------------------------------------------------------------------- #
#  The label sweep: a stated aggregation, both directions.
# --------------------------------------------------------------------------- #
def test_a_page_whose_body_is_an_article_is_not_condemned_by_its_nav_header():
    """The failure mode this one had of its own: nav soup sits at the TOP, so a
    head-only judgement could answer "junk" about a page whose body it never saw."""
    from src.ai_layer.qualification_assist import classify_article_for_qualification

    c = _Client(["junk", "junk", "article", "junk"])
    v = classify_article_for_qualification(
        c, "T", _article(8, 500), model="m", budget_chars=1000
    )
    assert v == "article"
    assert len(c.prompts) > 1


def test_a_page_that_is_junk_all_the_way_down_stays_junk():
    """The negative-space twin. An "any part wins" rule that could never answer junk
    would be a gate that cannot fire."""
    from src.ai_layer.qualification_assist import classify_article_for_qualification

    c = _Client(["junk"])
    v = classify_article_for_qualification(
        c, "T", _article(8, 500), model="m", budget_chars=1000
    )
    assert v == "junk"


def test_no_parseable_verdict_anywhere_is_None_never_a_guess():
    from src.ai_layer.qualification_assist import classify_article_for_qualification

    c = _Client(["I cannot answer that"])
    assert classify_article_for_qualification(
        c, "T", _article(4, 500), model="m", budget_chars=1000
    ) is None


# --------------------------------------------------------------------------- #
#  The two-sided budget — the half that was missing.
# --------------------------------------------------------------------------- #
def test_the_smaller_of_the_two_windows_governs(monkeypatch):
    """The field trap, exactly: the operator's setting said 8192 while vLLM had
    computed 2048 from free VRAM. Sizing for 8192 would have produced ~26,600-character
    prompts against a window that accepts ~2,000 — every call failing on a machine
    where they currently succeed."""
    monkeypatch.setattr(COV, "_configured_tokens", lambda: 8192)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": 2048, "source": "test", "backend": "vllm"}
    )
    budget, basis = COV.sweep_text_budget("some latin text")
    assert basis["num_ctx"] == 2048
    assert basis["governing"] == "the backend's serving window"
    assert budget < 6000, budget


def test_the_configured_window_governs_when_the_backend_cannot_be_read(monkeypatch):
    """A MISSING reading is not a reading of zero. An unreadable backend window must
    leave the operator's own setting in charge, not collapse the budget."""
    monkeypatch.setattr(COV, "_configured_tokens", lambda: 8192)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": None, "source": "unreadable", "backend": None}
    )
    _budget, basis = COV.sweep_text_budget("some latin text")
    assert basis["num_ctx"] == 8192
    assert basis["governing"] == "the operator's configured window"


def test_with_neither_window_readable_the_budget_is_the_pre_existing_constant(monkeypatch):
    """A machine that can tell us nothing behaves exactly as it did before, rather than
    getting a budget guessed from nothing."""
    from src.ai_layer.context import LEGACY_TEXT_BUDGET_CHARS

    monkeypatch.setattr(COV, "_configured_tokens", lambda: None)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": None, "source": "x", "backend": None}
    )
    budget, basis = COV.sweep_text_budget("some latin text")
    assert budget == LEGACY_TEXT_BUDGET_CHARS
    assert basis["num_ctx"] is None
    assert "neither" in basis["governing"]


def test_the_window_is_sent_not_only_sized_for(monkeypatch):
    """Ollama serves each model's own default num_ctx unless told otherwise, so sizing
    a part for a configured window and not SENDING it re-truncates at the daemon — the
    same silence, one layer down."""
    from src.ai_layer.perception import llm_perception_extract

    monkeypatch.setattr(COV, "_configured_tokens", lambda: 8192)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": None, "source": "ollama", "backend": "ollama"}
    )
    c = _Client(["WHO: none\nWHERE: none\nWHEN: none"])
    llm_perception_extract(c, "short text", model="m")
    assert c.options[0].get("num_ctx") == 8192


def test_a_sweep_reserves_less_for_its_reply_than_a_prose_call_does(monkeypatch):
    """What makes the ruling affordable on a small window. A sweep's reply is bounded
    by its PARSER — three lines, or N terms of <=80 characters, or one word — not by a
    writer's inclination, so reserving a summary's worth of output tokens for it spends
    the window on nothing. On the field machine's 2,048-token vLLM window the prose
    reserve leaves 25% of it for text (11 calls to read a 22 KB article whole); the
    sweep reserve leaves 50% (6 calls). Same coverage, half the bill."""
    from src.ai_layer.context import (
        OUTPUT_RESERVE_TOKENS,
        SWEEP_OUTPUT_RESERVE_TOKENS,
        text_budget_chars,
    )

    assert SWEEP_OUTPUT_RESERVE_TOKENS < OUTPUT_RESERVE_TOKENS
    prose = text_budget_chars(2048, "latin")
    sweep = text_budget_chars(2048, "latin", output_reserve=SWEEP_OUTPUT_RESERVE_TOKENS)
    assert sweep > prose, (sweep, prose)

    # ...and the sweeps actually use it, rather than it being a constant nobody passes.
    monkeypatch.setattr(COV, "_configured_tokens", lambda: 2048)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": None, "source": "t", "backend": "ollama"}
    )
    budget, basis = COV.sweep_text_budget("latin text here")
    assert budget == sweep
    assert basis["output_reserve_tokens"] == SWEEP_OUTPUT_RESERVE_TOKENS


def test_the_prose_paths_keep_the_prose_reserve():
    """The negative-space twin: a summary really does need room to write, so the
    user-driven budget must be untouched by the sweep calibration."""
    import inspect

    from src.ai_layer.context import OUTPUT_RESERVE_TOKENS, text_budget_chars
    from src.api import llm as API

    sig = inspect.signature(text_budget_chars)
    assert sig.parameters["output_reserve"].default == OUTPUT_RESERVE_TOKENS
    body = inspect.getsource(API._user_text_budget)
    assert "output_reserve" not in body, "the user-driven path keeps the prose reserve"


def test_a_cjk_article_gets_a_smaller_char_budget_than_a_latin_one(monkeypatch):
    """A defect in the FIRST cut of this change, caught before it shipped: the batch
    resolved ONE budget and passed it to every article. A token buys ~4 Latin
    characters and ~1.2 CJK ones, so a Chinese article sized with a Latin article's
    ratio gets parts ~3x too big — they overflow the window and the SERVER truncates
    them, silently, which is the exact defect this module removes. The window is cached
    per batch; the ratio is per article."""
    monkeypatch.setattr(COV, "_configured_tokens", lambda: 8192)
    monkeypatch.setattr(
        COV, "_resolve_window", lambda _b: {"tokens": 8192, "source": "t", "backend": "vllm"}
    )
    latin, _ = COV.sweep_text_budget("the quick brown fox " * 200)
    cjk, basis = COV.sweep_text_budget("峰会在北京举行。" * 200)
    assert basis["script"] == "cjk"
    assert cjk < latin / 2, (cjk, latin)


def test_the_batch_callers_do_not_pin_one_budget_for_every_article():
    """The guard for the above at the call site. Passing ``budget_chars`` down from the
    batch would freeze the FIRST article's script onto all the others."""
    import inspect

    from src.ai_layer import jobs, perception_extract, qualification_assist

    for mod, fn in (
        (perception_extract, "extract_perception_batch"),
        (jobs, "extract_for_articles"),
        (qualification_assist, "propose_qualification_flags"),
    ):
        body = inspect.getsource(getattr(mod, fn))
        assert "budget_chars=budget" not in body, (
            f"{fn} pins one budget for the whole batch — the script varies per article"
        )


def test_an_explicit_budget_does_not_reach_for_the_backend(monkeypatch):
    """The batch callers resolve the window ONCE and pass it down; a per-article
    re-resolution would shell out to nvidia-smi per article and cost more than the
    truncation this replaces."""
    from src.ai_layer.perception import llm_perception_extract

    def _boom(_b):
        raise AssertionError("the window must not be resolved when a budget was given")

    monkeypatch.setattr(COV, "_resolve_window", _boom)
    c = _Client(["WHO: none\nWHERE: none\nWHEN: none"])
    llm_perception_extract(c, "short text", model="m", budget_chars=4000)
    assert len(c.prompts) == 1


def test_the_resolved_window_is_cached_so_a_batch_probes_once(monkeypatch):
    calls = {"n": 0}

    def _count(_b):
        calls["n"] += 1
        return {"tokens": 4096, "source": "test", "backend": "vllm"}

    monkeypatch.setattr(COV, "_resolve_window", _count)
    for _ in range(25):
        COV.serving_window_tokens("vllm")
    assert calls["n"] == 1
