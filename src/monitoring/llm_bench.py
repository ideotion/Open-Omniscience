"""
Local-LLM per-call latency bench — the measurement a time budget has to rest on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Any feature that runs the local model over many articles needs an
operator setting for how much work to do, and the honest form of that setting is a
TIME BUDGET rather than an article count (a count means nothing without knowing what
a call costs on THIS machine). There was no recorded per-call latency anywhere in
this repo, so no budget could be anything but a guess.

The raw material was already captured and unused: ``GenerationResult`` passes
Ollama's own nanosecond timings through verbatim (``total_duration``,
``load_duration``, ``prompt_eval_duration``, ``eval_duration``) alongside the token
counts, with a comment naming them "the raw material for ... any honest throughput
measurement". This module is what exercises them.

WHAT IT MEASURES, AND WHY IT IS PER SHAPE. Latency is dominated by prompt length
(prompt eval) and output length (generation), so a single number is useless: a
1-3 sentence narration over a small fact bundle and a multi-paragraph synthesis over
a 24,000-character excerpt set differ by more than an order of magnitude on the same
model. The bench therefore times each SHAPE the app actually uses and reports them
separately. A budget derived from the wrong shape would be a fabricated capacity.

HONESTY RAILS.
  * No reachable backend => ``{"available": false, "reason": ...}``. Never numbers.
  * The WARMUP call is excluded from the statistics and reported separately, because
    it carries model load. Folding a cold call into a steady-state median would
    overstate cost; hiding it entirely would understate first-run wall time.
  * ``timing_source`` is stated per shape: Ollama reports its own durations, vLLM's
    OpenAI-compatible response carries none, so there the figures are wall-clock.
    They are not interchangeable and are never silently mixed.
  * Tokens/sec is emitted ONLY when the backend returned token counts; absent counts
    give ``None``, never a divided-by-assumption rate.
  * A call that fails is recorded with its error and excluded from the statistics,
    with the surviving ``n`` stated. A shape where every call failed reports no
    figures at all rather than a figure over zero samples.
  * ``n`` accompanies every percentile, and percentiles over very few samples say so.
  * No composite score, and no field name carrying a banned substring.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime
from typing import Any

from src.llm.ollama import bounded_error

SCHEMA = "oo-llm-bench-1"

_NS_PER_S = 1_000_000_000

# Deterministic filler: a fixed sentence repeated to a target size. Repeatable across
# runs and machines, and independent of the corpus, so two benches are comparable.
_FILLER = (
    "The committee published its findings on the regional water supply and the "
    "measures proposed for the coming year. "
)


def _prompt_of(chars: int) -> str:
    """A deterministic prompt of approximately ``chars`` characters."""
    if chars <= 0:
        return ""
    reps = (chars // len(_FILLER)) + 1
    return (_FILLER * reps)[:chars]


# The shapes the app actually runs, with the prompt sizes they actually use.
# `synthesis` mirrors _SYNTHESIS_BUDGET_CHARS (24_000) from src/api/llm.py.
#   (id, human name, prompt_chars, system prompt)
_SHAPES: tuple[tuple[str, str, int, str], ...] = (
    (
        "narration",
        "fact bundle -> 1-3 sentences",
        800,
        "Write two plain sentences summarising the facts given. Do not add facts.",
    ),
    (
        "perception",
        "one article -> who / where / when",
        4_000,
        "Reply with exactly three lines: WHO:, WHERE:, WHEN:. Use only the text given.",
    ),
    (
        "summary",
        "one article -> a paragraph",
        8_000,
        "Summarise the text in one short paragraph. Use only the text given.",
    ),
    (
        "synthesis",
        "many excerpts -> multi-paragraph",
        24_000,
        "Write a short synthesis of the excerpts. Use only the text given.",
    ),
)

_SHAPES_BY_ID = {s[0]: s for s in _SHAPES}


def _pct(values: list[float], q: float) -> float | None:
    """Percentile of a sample, or None when there is nothing to compute it from."""
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    ordered = sorted(values)
    # Nearest-rank: no interpolation between samples we did not observe.
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[idx], 3)


def _one_call(client, *, model: str, prompt: str, system: str) -> dict:
    """One timed generation. Returns a record; never raises."""
    started = time.perf_counter()
    try:
        # temperature 0 so repeated runs are as comparable as the backend allows.
        res = client.generate(prompt, model=model, system=system, options={"temperature": 0})
    except Exception as exc:  # noqa: BLE001 - a failed call is data, not a crash
        return {
            "ok": False,
            "wall_s": round(time.perf_counter() - started, 3),
            "error": bounded_error(exc, 200),
        }
    wall = time.perf_counter() - started
    rec: dict[str, Any] = {
        "ok": True,
        "wall_s": round(wall, 3),
        "prompt_tokens": getattr(res, "prompt_eval_count", None),
        "output_tokens": getattr(res, "eval_count", None),
    }
    # The backend's OWN timings, when it reports them (Ollama does; vLLM does not).
    for field in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
        ns = getattr(res, field, None)
        rec[field + "_s"] = round(ns / _NS_PER_S, 3) if isinstance(ns, int) else None
    return rec


def _shape_report(shape_id: str, name: str, calls: list[dict], warmup: dict) -> dict:
    """Reduce a shape's calls to honest figures. Excludes the warmup by construction."""
    ok = [c for c in calls if c.get("ok")]
    failed = [c for c in calls if not c.get("ok")]
    walls = [c["wall_s"] for c in ok]
    backend_totals = [c["total_duration_s"] for c in ok if c.get("total_duration_s") is not None]

    out_tokens = [c["output_tokens"] for c in ok if isinstance(c.get("output_tokens"), int)]
    tok_per_s: float | None = None
    if out_tokens and walls and len(out_tokens) == len(walls):
        per_call = [t / w for t, w in zip(out_tokens, walls, strict=False) if w > 0]
        tok_per_s = round(statistics.median(per_call), 1) if per_call else None

    timing_source = "backend-reported" if backend_totals else "wall-clock"
    p50 = _pct(walls, 0.50)
    return {
        "shape": shape_id,
        "name": name,
        "n": len(ok),
        "failed_n": len(failed),
        "errors": [c["error"] for c in failed][:5],
        "wall_p50_s": p50,
        "wall_p95_s": _pct(walls, 0.95),
        "backend_total_p50_s": _pct(backend_totals, 0.50),
        "timing_source": timing_source,
        "output_tokens_per_s": tok_per_s,
        "warmup_wall_s": warmup.get("wall_s"),
        "warmup_load_s": warmup.get("load_duration_s"),
        "calls_per_hour_serial": round(3600.0 / p50) if p50 else None,
        "note": (
            "Warmup excluded from these figures and reported separately — it carries model "
            "load, so folding it in would overstate steady-state cost and dropping it "
            "entirely would understate first-run wall time."
            + ("" if len(ok) >= 3 else " Very few samples: read as an order of magnitude.")
            + ("" if not failed else f" {len(failed)} call(s) failed and are excluded.")
        ),
    }


def run_llm_bench(
    *,
    repeats: int = 3,
    shapes: tuple[str, ...] | None = None,
    client=None,
    model: str | None = None,
    backend_name: str | None = None,
) -> dict:
    """Time the local model on each prompt shape the app actually uses.

    ``client``/``model``/``backend_name`` are injectable so the mechanism is testable
    without a running model; left None they resolve the live backend.
    """
    started = time.monotonic()
    resolved: dict = {}
    if client is None:
        try:
            from src.api.llm import active_model
            from src.llm.backend import get_client_with_name, resolve_backend

            resolved = resolve_backend()
            if not resolved.get("available"):
                return {
                    "schema": SCHEMA,
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "available": False,
                    "reason": (
                        resolved.get("reason")
                        or "no local LLM backend is reachable right now"
                    ),
                    "backend": resolved.get("backend"),
                    "note": (
                        "No figures are reported. A budget derived from an unreachable "
                        "backend would be invented."
                    ),
                }
            backend_name, client = get_client_with_name()
            model = model or active_model()
        except Exception as exc:  # noqa: BLE001 - resolution failure degrades, never raises
            return {
                "schema": SCHEMA,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "available": False,
                "reason": f"could not resolve a backend: {type(exc).__name__}: {exc}",
            }

    chosen = [s for s in _SHAPES if shapes is None or s[0] in shapes]
    reports = []
    for shape_id, name, chars, system in chosen:
        prompt = _prompt_of(chars)
        warmup = _one_call(client, model=model or "", prompt=prompt, system=system)
        calls = [
            _one_call(client, model=model or "", prompt=prompt, system=system)
            for _ in range(max(1, repeats))
        ]
        reports.append(_shape_report(shape_id, name, calls, warmup))

    concurrency = 1
    try:
        from src.llm.concurrency import concurrency_for

        concurrency = concurrency_for(backend_name or "ollama")
    except Exception:  # noqa: BLE001 - a missing ceiling is not a bench failure
        concurrency = 1

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "available": True,
        "backend": backend_name,
        "model": model,
        "repeats": max(1, repeats),
        "concurrency": concurrency,
        "elapsed_s": round(time.monotonic() - started, 2),
        "shapes": reports,
        "budget": budget_translation(reports, concurrency=concurrency),
        "method": (
            "Each shape is timed with a deterministic prompt of the size the app actually "
            "sends, at temperature 0, after one excluded warmup call. Percentiles are "
            "nearest-rank over the timed calls, with n stated. Ollama reports its own "
            "durations; vLLM's OpenAI-compatible response carries none, so those figures "
            "are wall-clock — the two are stated per shape and never mixed."
        ),
        "caveat": (
            "Measured on THIS machine, with THIS model, on synthetic prompts of "
            "representative size. Real prompts vary, and a machine under collection load "
            "is slower than an idle one, so treat these as the order of magnitude a budget "
            "should be built on rather than a guarantee."
        ),
    }


def budget_translation(shape_reports: list[dict], *, concurrency: int = 1) -> dict:
    """How many calls of each shape fit in a given wall-clock budget.

    This is the point of the bench: it turns "spend up to N hours" into a real number
    of articles for THIS machine, instead of an operator guessing a count.
    """
    hours = (1, 3, 8)
    rows = []
    for rep in shape_reports:
        p50 = rep.get("wall_p50_s")
        if not p50:
            rows.append({
                "shape": rep["shape"],
                "per_hour": None,
                "reason": "no timed call succeeded for this shape",
            })
            continue
        per_hour = (3600.0 / p50) * max(1, concurrency)
        rows.append({
            "shape": rep["shape"],
            "per_hour": round(per_hour),
            "fits": {f"{h}h": round(per_hour * h) for h in hours},
        })
    return {
        "concurrency_assumed": max(1, concurrency),
        "rows": rows,
        "method": (
            "calls_per_hour = 3600 / wall_p50 * concurrency. Concurrency is the backend's "
            "configured ceiling, so it is an UPPER bound: a saturated GPU or a serial "
            "Ollama will not reach it."
        ),
    }


# --------------------------------------------------------------------------- #
#  Selftest (recursive-loop harness)
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, wall_ns: int, out_tokens: int | None, with_durations: bool):
        self.model = "fake"
        self.text = "ok"
        self.prompt_eval_count = 100
        self.eval_count = out_tokens
        self.total_duration = wall_ns if with_durations else None
        self.load_duration = 0 if with_durations else None
        self.prompt_eval_duration = 0 if with_durations else None
        self.eval_duration = wall_ns if with_durations else None


class _FakeClient:
    """A client that sleeps a fixed time per call, so timings are predictable."""

    def __init__(self, seconds: float = 0.01, *, with_durations=True, fail=False):
        self.seconds, self.with_durations, self.fail = seconds, with_durations, fail
        self.calls = 0

    def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model unavailable")
        time.sleep(self.seconds)
        return _FakeResult(int(self.seconds * _NS_PER_S), 40, self.with_durations)


def run_llm_bench_selftest() -> dict:
    """Prove the bench's arithmetic and honesty rails without a real model."""
    cases: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        cases.append({"case": name, "passed": bool(ok), "detail": detail})

    one = ("narration",)

    # 1. The warmup is excluded from n.
    fake = _FakeClient(0.005)
    out = run_llm_bench(repeats=3, shapes=one, client=fake, model="m", backend_name="ollama")
    rep = out["shapes"][0]
    _check("warmup is excluded from the sample", rep["n"] == 3 and fake.calls == 4,
           f"n={rep['n']} calls={fake.calls}")

    # 2. The warmup is still reported, not hidden.
    _check("warmup is reported separately", rep.get("warmup_wall_s") is not None, str(rep))

    # 3. Backend-reported timings are labelled as such.
    _check("timing source is backend-reported when durations exist",
           rep["timing_source"] == "backend-reported", rep["timing_source"])

    # 4. Without durations it falls back to wall-clock and SAYS so.
    out2 = run_llm_bench(repeats=2, shapes=one, client=_FakeClient(0.005, with_durations=False),
                         model="m", backend_name="vllm")
    _check("timing source is wall-clock when the backend reports none",
           out2["shapes"][0]["timing_source"] == "wall-clock", out2["shapes"][0]["timing_source"])

    # 5. A shape where every call fails reports no figures rather than a zero.
    out3 = run_llm_bench(repeats=2, shapes=one, client=_FakeClient(fail=True),
                         model="m", backend_name="ollama")
    r3 = out3["shapes"][0]
    _check("an all-failed shape reports no percentile",
           r3["wall_p50_s"] is None and r3["n"] == 0 and r3["failed_n"] == 2, str(r3))

    # 6. ... and its budget row explains itself instead of showing 0.
    row = out3["budget"]["rows"][0]
    _check("an unmeasurable shape has no fabricated per_hour",
           row["per_hour"] is None and "reason" in row, str(row))

    # 7. The budget arithmetic is the stated formula.
    per_hour = out["budget"]["rows"][0]["per_hour"]
    expected = round((3600.0 / rep["wall_p50_s"]) * out["budget"]["concurrency_assumed"])
    _check("per_hour follows 3600 / p50 * concurrency", per_hour == expected,
           f"{per_hour} vs {expected}")

    # 8. Prompt sizes are the real ones the app sends.
    _check("synthesis prompt matches the app's excerpt budget",
           len(_prompt_of(_SHAPES_BY_ID["synthesis"][2])) == 24_000, "")

    # 9. No score-shaped key anywhere in the payload.
    import json

    flat = json.dumps(out).lower()
    _check("no score-shaped key in the payload",
           not any(f'"{b}"' in flat or f'_{b}"' in flat
                   for b in ("score", "ranking", "rating", "grade")), "")

    # SHAPE CONTRACT: recursive_loop._selftest_passed reads a top-level `passed` BOOL
    # (counts live under *_count), matching run_leads_selftest / run_skeleton_selftest.
    passed = all(c["passed"] for c in cases)
    return {
        "schema": "oo-llm-bench-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": cases,
        "total": len(cases),
        "passed": passed,
        "passed_count": sum(1 for c in cases if c["passed"]),
        "failed_count": sum(1 for c in cases if not c["passed"]),
        "method": (
            "A fake client with a fixed per-call sleep drives the real bench. Proves the "
            "arithmetic and the degrade paths only — it measures no real model."
        ),
    }
