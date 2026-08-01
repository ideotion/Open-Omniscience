"""
The local-LLM latency bench — the measurement a time budget rests on.

A budget expressed as an article COUNT is meaningless without knowing what a call
costs on the operator's machine, and nothing in this repo recorded per-call latency.
These tests pin the arithmetic and, more importantly, the degrade paths: a bench that
invents a number when it cannot measure is worse than no bench.

No real model is involved anywhere here — a fake client with a fixed per-call sleep
drives the real code.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.monitoring.llm_bench import (
    _FakeClient,
    _prompt_of,
    _SHAPES_BY_ID,
    budget_translation,
    run_llm_bench,
    run_llm_bench_selftest,
)

_ONE = ("narration",)


def _run(**kw):
    kw.setdefault("repeats", 3)
    kw.setdefault("shapes", _ONE)
    kw.setdefault("model", "m")
    kw.setdefault("backend_name", "ollama")
    return run_llm_bench(**kw)


# -- the warmup ------------------------------------------------------------- #


def test_warmup_is_excluded_from_the_sample_but_still_reported():
    """Folding a cold call into a steady-state median overstates cost; hiding it
    entirely understates first-run wall time. So: excluded, and reported."""
    fake = _FakeClient(0.005)
    out = _run(client=fake, repeats=3)
    rep = out["shapes"][0]
    assert rep["n"] == 3
    assert fake.calls == 4, "one warmup + three timed calls"
    assert rep["warmup_wall_s"] is not None
    assert "Warmup excluded" in rep["note"]


# -- timing provenance ------------------------------------------------------ #


def test_backend_reported_timings_are_labelled_as_such():
    out = _run(client=_FakeClient(0.005, with_durations=True))
    assert out["shapes"][0]["timing_source"] == "backend-reported"
    assert out["shapes"][0]["backend_total_p50_s"] is not None


def test_wall_clock_is_labelled_when_the_backend_reports_no_durations():
    """vLLM's OpenAI-compatible response carries no durations. The two clocks are
    not interchangeable and must never be silently mixed."""
    out = _run(client=_FakeClient(0.005, with_durations=False), backend_name="vllm")
    rep = out["shapes"][0]
    assert rep["timing_source"] == "wall-clock"
    assert rep["backend_total_p50_s"] is None
    assert rep["wall_p50_s"] is not None


# -- degrade paths: the part that must never invent a number ---------------- #


def test_a_shape_whose_calls_all_failed_reports_no_figures():
    out = _run(client=_FakeClient(fail=True), repeats=2)
    rep = out["shapes"][0]
    assert rep["n"] == 0
    assert rep["failed_n"] == 2
    assert rep["wall_p50_s"] is None, "a percentile over zero samples would be invented"
    assert rep["errors"], "the failure reason is carried, not swallowed"


def test_an_unmeasurable_shape_gets_no_fabricated_capacity():
    out = _run(client=_FakeClient(fail=True), repeats=2)
    row = out["budget"]["rows"][0]
    assert row["per_hour"] is None
    assert "reason" in row


def test_no_backend_reports_unavailable_with_a_reason_and_no_numbers(monkeypatch):
    monkeypatch.setattr(
        "src.llm.backend.resolve_backend",
        lambda **_: {"available": False, "reason": "nothing reachable", "backend": "ollama"},
    )
    out = run_llm_bench(repeats=1)
    assert out["available"] is False
    assert out["reason"]
    assert "shapes" not in out, "no figures may accompany an unavailable backend"


def test_a_resolution_crash_degrades_instead_of_raising(monkeypatch):
    def _boom(**_):
        raise RuntimeError("detection exploded")

    monkeypatch.setattr("src.llm.backend.resolve_backend", _boom)
    out = run_llm_bench(repeats=1)
    assert out["available"] is False
    assert "detection exploded" in out["reason"]


def test_tokens_per_second_is_none_without_token_counts():
    """A rate divided by an assumed token count would be a fabricated throughput."""
    fake = _FakeClient(0.005)

    class _NoCounts(type(fake)):
        def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
            res = super().generate(prompt, model=model, system=system)
            res.eval_count = None
            return res

    out = _run(client=_NoCounts(0.005))
    assert out["shapes"][0]["output_tokens_per_s"] is None


# -- arithmetic ------------------------------------------------------------- #


def test_per_hour_follows_the_stated_formula():
    out = _run(client=_FakeClient(0.01))
    rep, row = out["shapes"][0], out["budget"]["rows"][0]
    expected = round((3600.0 / rep["wall_p50_s"]) * out["budget"]["concurrency_assumed"])
    assert row["per_hour"] == expected
    assert "3600 / wall_p50" in out["budget"]["method"]


def test_concurrency_multiplies_capacity_and_is_disclosed_as_an_upper_bound():
    reports = [{"shape": "x", "wall_p50_s": 2.0}]
    serial = budget_translation(reports, concurrency=1)["rows"][0]["per_hour"]
    eight = budget_translation(reports, concurrency=8)["rows"][0]["per_hour"]
    assert eight == serial * 8
    assert "UPPER bound" in budget_translation(reports, concurrency=8)["method"]


def test_budget_fits_scale_with_the_hours():
    out = _run(client=_FakeClient(0.01))
    fits = out["budget"]["rows"][0]["fits"]
    assert fits["3h"] == pytest.approx(fits["1h"] * 3, rel=0.01)
    assert fits["8h"] == pytest.approx(fits["1h"] * 8, rel=0.01)


# -- the shapes are the real ones ------------------------------------------- #


def test_synthesis_prompt_matches_the_apps_own_excerpt_budget():
    """_SYNTHESIS_BUDGET_CHARS in src/api/llm.py is 24_000 — measuring a toy prompt
    would produce a budget for work the app never does."""
    from src.api.llm import _SYNTHESIS_BUDGET_CHARS

    assert _SHAPES_BY_ID["synthesis"][2] == _SYNTHESIS_BUDGET_CHARS


def test_prompts_are_deterministic_and_the_requested_size():
    for chars in (800, 4_000, 24_000):
        a, b = _prompt_of(chars), _prompt_of(chars)
        assert a == b, "a bench prompt must be repeatable across runs"
        assert len(a) == chars


def test_every_shape_is_timed_when_none_are_filtered():
    out = run_llm_bench(repeats=1, client=_FakeClient(0.002), model="m", backend_name="ollama")
    assert [s["shape"] for s in out["shapes"]] == list(_SHAPES_BY_ID)


# -- payload shape ---------------------------------------------------------- #


def test_no_score_shaped_key_and_the_caveat_is_present():
    out = _run(client=_FakeClient(0.005))
    flat = json.dumps(out).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat
    assert out["method"] and out["caveat"]
    assert "this machine" in out["caveat"].lower()


def test_selftest_passes_is_registered_and_matches_the_loop_contract():
    out = run_llm_bench_selftest()
    assert out["failed_count"] == 0, [c for c in out["cases"] if not c["passed"]]
    assert isinstance(out["passed"], bool)

    from src.monitoring.recursive_loop import LOOP_SELFTESTS, _selftest_passed

    assert _selftest_passed(out) is True, "the loop could not read this selftest's verdict"
    assert any(
        mod == "src.monitoring.llm_bench" and fn == "run_llm_bench_selftest"
        for _, mod, fn in LOOP_SELFTESTS
    )


def test_the_endpoint_is_a_documented_bundle_exemption():
    """A GET diagnostic must be a bundle member or carry a stated exemption.

    This one needs a live model, so it cannot ride the bundle — the exemption is the
    honest option, and the ratchet requires it be written down.
    """
    from src.api.diagnostics import _DIAG_COVERAGE_EXEMPT

    assert "/llm-bench" in _DIAG_COVERAGE_EXEMPT
    assert "model" in _DIAG_COVERAGE_EXEMPT["/llm-bench"]
