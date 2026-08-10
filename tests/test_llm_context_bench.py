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
    reading pass, and one whose cost was linear would hide the sub-linear branch.

    ``overhead`` is a FIXED per-call cost, and it is the whole reason this parameter
    exists: a real runner adds one, and it lands on both arms equally in absolute terms,
    so it compresses a RATIO. macOS CI adds ~2–3 ms per call while Linux adds
    essentially none (Linux measures the intended 12.00x exactly, every run), which is
    why the small arm's sleep has to dominate it — see
    test_a_fixed_per_call_overhead_does_not_turn_proportional_into_sub_linear.
    """

    def __init__(self, unit: float = 0.002, power: float = 0.6, overhead: float = 0.0):
        self.unit, self.power, self.overhead = unit, power, overhead
        self.prompts: list[int] = []

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.prompts.append(len(prompt))
        time.sleep(self.overhead + self.unit * (len(prompt) / 2000) ** self.power)

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


def test_a_sublinear_cost_is_named_as_such():
    """The finding an operator acts on: a longer article is usually much cheaper than
    its length, which is the argument for a bigger window."""
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=3, client=_Client(power=0.5), model="m", backend_name="ollama"
    )
    assert "Sub-linear" in out["reading"]["note"]


#: The proportional arm's per-call sleep. NOT a tuning knob to nudge when this goes red:
#: the verdict fires "Sub-linear" below ratio 9.6 (span 12 x 0.8), and a fixed per-call
#: overhead C makes a truly-proportional fixture measure (24u + C)/(2u + C) instead of 12,
#: so the sleep has to dominate C. MEASURED, macOS CI at the old unit of 0.002 (2 ms):
#: 6.8x and 5.6x on two runs of the identical commit — both below 9.6, i.e. a red lane on
#: every PR, not a flake. Solving for C gives 1.8–2.8 ms, and simulating that exact
#: overhead on Linux reproduces 6.50x and 5.40x. At 50 ms the same simulation holds the
#: ratio at 11.38x with 3 ms of overhead and 10.17x with a punitive 10 ms — margin to
#: spare against the weakest platform observed, which is the side to calibrate on.
_PROPORTIONAL_UNIT = 0.05


def test_a_proportional_cost_is_not_called_sub_linear():
    """The negative-space twin: a machine where cost DOES track length must not be told
    it is getting a bargain."""
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=3,
        client=_Client(unit=_PROPORTIONAL_UNIT, power=1.0),
        model="m", backend_name="ollama",
    )
    assert "Sub-linear" not in out["reading"]["note"]


def test_a_fixed_per_call_overhead_does_not_turn_proportional_into_sub_linear():
    """The platform property, pinned where the platform cannot show it.

    The test above passed on Linux and failed on macOS for months' worth of runs' reasons
    that had nothing to do with the code under test: Linux adds no measurable per-call
    cost, so it measures 12.00x exactly and cannot observe the defect at all. Injecting
    the overhead explicitly is what lets every platform check the thing macOS was the only
    one to see — and it is a real assertion about the reading, not about the fixture,
    because a machine that is genuinely proportional must never be told it is getting a
    bargain just because each call carries a constant cost.
    """
    out = LC.run_context_bench(
        sizes=(2000, 24000), calls=3,
        client=_Client(unit=_PROPORTIONAL_UNIT, power=1.0, overhead=0.003),
        model="m", backend_name="ollama",
    )
    r = out["reading"]
    assert "Sub-linear" not in r["note"], (
        "a fixed per-call overhead compressed a proportional ratio past the sub-linear "
        f"threshold — ratio {r.get('latency_ratio')}, note {r['note']!r}"
    )
    assert "Roughly proportional" in r["note"]
    assert "proportional" in out["reading"]["note"]


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
