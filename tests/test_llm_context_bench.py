"""What a bigger context costs, and what it buys.

The guards here are mostly about the two halves not being confused with each other: a
configured setting is not a serving limit, a prompt size is not a window size, and a
coverage figure with no measured corpus behind it is the most misleading number the
report could carry.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time

from src.monitoring import llm_context as LC


class _Client:
    """Cost grows with the prompt, SUB-linearly — the real shape, because prompt
    tokens are processed in parallel. A client whose cost was flat would let a broken
    reading pass, and one whose cost was linear would hide the sub-linear branch."""

    def __init__(self, unit: float = 0.002, power: float = 0.6):
        self.unit, self.power = unit, power
        self.prompts: list[int] = []

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.prompts.append(len(prompt))
        time.sleep(self.unit * (len(prompt) / 2000) ** self.power)

        class R:
            text = "{}"
            eval_count = 8

        return R()


def test_the_reading_uses_run_levels_own_key():
    """THE ONE THAT MATTERS. An earlier cut read ``wall_p50_s``; ``_run_level``
    publishes ``call_wall_p50_s``. Nothing raised — every run just carried
    ``note: None``, a reading that silently said nothing instead of saying it could not
    read. A resolver over another module's payload must be tested against that module's
    REAL, CURRENT shape."""
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=3, client=_Client(), model="m", backend_name="ollama"
    )
    r = out["reading"]
    assert r["readable"] is True
    assert r["smallest"]["call_wall_p50_s"], "the key must be the one _run_level emits"
    assert r.get("latency_ratio"), "and the derived ratio must exist, not be a silent None"
    assert "x the prompt cost" in r["note"]


def test_the_end_to_end_reading_is_self_consistent():
    """What the timing harness CAN prove on any machine: it produced a reading, and the
    sentence agrees with the numbers beside it.

    IT CANNOT PROVE WHICH VERDICT. This asserted "Sub-linear" until the macOS runner
    returned 11.5x wall for 12x prompt against a fixture whose sleeps scale as sqrt(12)
    = 3.5x — so the measurement was dominated by something other than the fixture, and
    the guard failed against correct code.

    THE CLAIM I MADE WHEN FIXING ITS TWIN WAS WRONG, and this is the correction: I wrote
    that overhead "only ever pushes the ratio further under the bar — it cannot
    manufacture the verdict being asserted here." That holds for a FIXED addend, which
    compresses a ratio toward 1. It is false for overhead PROPORTIONAL to the input, and
    this harness has some: `_prompt_of(chars)` builds a prompt per call, so the O(n)
    work grows with the size being swept and inflates the wall ratio past the fixture's
    own. A slow shared runner makes that term dominate. Both directions of the verdict
    are therefore machine-dependent end to end, and both are pinned on the classifier
    directly instead."""
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=3, client=_Client(power=0.5), model="m", backend_name="ollama"
    )
    r = out["reading"]
    assert r["readable"] is True
    note = r["note"]
    assert ("Sub-linear" in note) or ("proportional" in note), "one verdict or the other"
    assert f"{r['size_ratio']:.0f}x the prompt" in note
    assert f"{r['latency_ratio']:.1f}x the wall" in note
    # And the sentence must match the rule it claims to apply, whichever way it went.
    assert ("Sub-linear" in note) == (r["latency_ratio"] < r["size_ratio"] * 0.8)


def test_a_proportional_cost_is_not_called_sub_linear():
    """The negative-space twin: a machine where cost DOES track length must not be told
    it is getting a bargain.

    TESTED AGAINST THE CLASSIFIER DIRECTLY, and that is the fix rather than a detail.
    Driving it through the timing harness measured the fixture's sleeps PLUS a fixed
    per-call overhead, and a fixed addend compresses a ratio toward 1: with the sleeps
    at 2 ms and 24 ms, an overhead of c makes the measured ratio (c+24)/(c+2), which
    falls under the 0.8x-span bar as soon as c is a few milliseconds. The macOS runner
    measured 4.8x where the fixture intends 12x — c was about 3.8 ms — so a PROPORTIONAL
    fixture read as sub-linear and the guard failed against correct code. The failure is
    guaranteed on a slow enough machine, so it was never a flake.

    The claim underneath is pure arithmetic over two published numbers, which is what
    this now asserts. The sub-linear direction keeps its end-to-end test above, where
    overhead only ever pushes the ratio further under the bar — it cannot manufacture
    the verdict being asserted there."""
    rows = [
        {"prompt_chars": 2000, "n": 3, "call_wall_p50_s": 0.010},
        {"prompt_chars": 24000, "n": 3, "call_wall_p50_s": 0.120},  # exactly 12x for 12x
    ]
    out = LC._reading(rows, {"tokens": None})
    assert out["latency_ratio"] == 12.0 and out["size_ratio"] == 12.0
    assert "Sub-linear" not in out["note"]
    assert "proportional" in out["note"]


def test_the_sub_linear_verdict_is_reachable_by_arithmetic_too():
    """Both branches pinned on the same exact footing, so the boundary is a decision
    and not an accident of whichever machine ran it."""
    rows = [
        {"prompt_chars": 2000, "n": 3, "call_wall_p50_s": 0.010},
        {"prompt_chars": 24000, "n": 3, "call_wall_p50_s": 0.040},  # 4x wall for 12x text
    ]
    out = LC._reading(rows, {"tokens": None})
    assert "Sub-linear" in out["note"]


def test_the_sentence_never_contradicts_the_number_published_beside_it():
    """The macOS lane's red (2026-08-11): the note printed "1.0x the wall time" while
    ``latency_ratio`` published 0.95, and the self-consistency test failed on a machine
    where nothing was wrong. Two roundings of one quantity -- the field was
    ``round(raw, 2)`` and the sentence formatted the RAW value -- so they disagreed
    whenever the raw ratio fell in a band like 0.9549: 0.95 published, "1.0" printed.

    THE FIXTURE IS THE POINT. Every other test here uses clean ratios (12x, 4x) that
    round identically either way, which is exactly why this survived: the band is
    narrow and nothing aimed at it. 0.9549 is chosen to sit inside it -- against the
    old code this asserts "0.9" is in a note that says "1.0"."""
    rows = [
        {"prompt_chars": 2000, "n": 3, "call_wall_p50_s": 1.0},
        {"prompt_chars": 24000, "n": 3, "call_wall_p50_s": 0.9549},
    ]
    out = LC._reading(rows, {"tokens": None})
    assert f"{out['latency_ratio']:.1f}x the wall" in out["note"], (
        f"note {out['note']!r} disagrees with latency_ratio={out['latency_ratio']}"
    )
    assert f"{out['size_ratio']:.0f}x the prompt" in out["note"], (
        "the size half rounds twice the same way -- fix it with its sibling, or it is "
        "the same trap waiting for whoever next asserts about it"
    )
    # ...and the verdict is decided on the SAME published numbers the reader compares.
    assert ("Sub-linear" in out["note"]) == (
        out["latency_ratio"] < out["size_ratio"] * 0.8
    )


def test_prompt_sizes_are_actually_swept():
    c = _Client()
    LC.run_context_bench(
        sizes=(2000, 8000), calls=2, client=c, model="m", backend_name="ollama"
    )
    # one warmup at the smallest size, then 2 calls at each of two sizes
    assert len(c.prompts) == 1 + 4
    assert max(c.prompts) > min(c.prompts) * 3, "the sweep must really vary the prompt"


def test_a_size_past_the_serving_limit_is_flagged_not_silently_attempted(monkeypatch):
    """The field's exact trap: the setting said 8192 while vLLM had computed 2048 from
    free VRAM. A row measured past the real limit measures what the backend did with an
    over-long prompt, not the model reading that much text, and must say so."""
    monkeypatch.setattr(
        LC, "_serving_limit_tokens", lambda _b: {"tokens": 1000, "source": "test"}
    )
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=2, client=_Client(), model="m", backend_name="vllm"
    )
    flagged = [r["prompt_chars"] for r in out["sizes"] if r["beyond_serving_limit"]]
    assert flagged == [24000], "2000 chars ~ 500 tokens fits; 24000 ~ 6000 does not"
    assert out["reading"]["beyond_serving_limit"] == [24000]
    assert "1000 tokens" in out["reading"]["limit_note"]


def test_the_serving_limit_is_asked_of_the_server_not_re_derived_here(monkeypatch):
    """ONE ANSWER to "what window is being served", and this is the guard that keeps it
    one. This module used to compute its own estimate from whatever VRAM was free at
    read time and label it "vLLM's computed max_model_len (derived from VRAM at start)"
    -- a source it did not have: nothing asked the server, so on a card whose free
    memory had moved it reported a number the server never used, and the bench could
    disagree with the sweeps about the very window it was measuring.

    Behavioural on purpose. A source grep for the old label would trip on the comment
    that explains why the label is gone, which is exactly what a future session needs
    to read before deciding the delegation was a mistake.
    """
    from src.ai_layer import coverage as COV

    called: list[str | None] = []

    def _fake(backend_name=None):
        called.append(backend_name)
        return {"tokens": 7777, "source": "the running vLLM server's own model card"}

    monkeypatch.setattr(COV, "serving_window_tokens", _fake)
    out = LC._serving_limit_tokens("vllm")
    assert called == ["vllm"], "the one resolver was not asked"
    assert out["tokens"] == 7777, "a locally re-derived estimate was reported instead"
    assert out["source"] == "the running vLLM server's own model card"


def test_a_serving_limit_that_cannot_be_read_never_claims_a_source(monkeypatch):
    """The negative-space twin. Degrading is fine; degrading while still naming the
    server as the source is the fabrication -- and it is the shape the old code had,
    since it printed that label whether or not anything was running."""
    from src.ai_layer import coverage as COV

    def _boom(backend_name=None):
        raise RuntimeError("no backend here")

    monkeypatch.setattr(COV, "serving_window_tokens", _boom)
    out = LC._serving_limit_tokens("vllm")
    assert out["tokens"] is None
    assert "could not be read" in out["source"]
    assert "model card" not in out["source"]


def test_coverage_without_a_measured_corpus_is_a_gap_not_a_guess():
    """The half the operator cannot eyeball. Inventing it from a guessed distribution
    would be the most misleading figure in the report."""
    cov = LC.corpus_coverage()
    assert cov["available"] is False
    assert "article-length diagnostic" in cov["reason"]

    cov2 = LC.corpus_coverage(report={"n": 5})
    assert cov2["available"] is True and cov2["report"] == {"n": 5}


def test_an_unreachable_backend_reports_no_figures():
    """A curve measured against a backend that is not there would be invented."""
    out = LC.run_context_bench(sizes=(2000,), calls=1)
    if out.get("available") is False:
        assert out.get("reason")
        assert "sizes" not in out, "no rows may be published for a run that did not happen"


def test_the_caveat_separates_prompt_size_from_window_size():
    """What was measured is the cost of a longer PROMPT. Raising max_model_len also
    enlarges the KV cache and takes concurrency away — a different measurement that
    needs a server restart per level, and the report must not be read as having made
    it."""
    out = LC.run_context_bench(
        sizes=(2000, 6000), calls=2, client=_Client(), model="m", backend_name="ollama"
    )
    assert "not what a larger configured WINDOW costs" in out["caveat"]
    assert out["concurrency"] == 1, "concurrency is fixed and stated, never swept here"
    assert "ESTIMATES" in out["method"], "token counts are estimates and say so"
