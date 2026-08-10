"""One button, every AI check on THIS machine, one report.

Maintainer ask 2026-08-09, after running four of them by hand: "Can you simplify all
AI related diagnostics into one single button to test everything at once?"

WHAT IT RUNS, in this order, because each step's failure explains the next one's:

1. FACTS -- which backend serves here, what the GPU is, which model is active, what
   context and concurrency it was started with. If this step says no backend is
   reachable, everything below it will fail for that one reason rather than four.
2. LATENCY -- one call per prompt shape the app actually sends.
3. THROUGHPUT -- the same shape at rising concurrency, with GPU utilisation sampled
   while it runs. This is the step that answers "why is my GPU at 25%".
4. PERCEPTION EVAL -- the live gate that decides which languages may store who/where/
   when extractions, run against the ACTIVE model over the real gold set.
5. SELF-TESTS -- the deterministic harness checks (parsers, canaries, echo-back).
   Seconds, no model needed, and they say whether a bad measurement above is the
   model's doing or the harness's.

WHAT IT DOES NOT RUN, and why saying so matters more than quietly omitting it: the
COMPARATIVE MODEL BENCH. That one loads every roster model in turn over a frozen input
set; it is resumable per model precisely because it runs for hours, and folding it in
here would turn a check into an afternoon. It keeps its own button, and this report
says where it is rather than leaving a reader to assume "everything" included it.

EVERY STEP IS GUARDED AND TIMED. A step that fails records why and the run continues,
because the most useful report from a half-broken machine is the one that says which
half. No step writes anything to the corpus; all of it is loopback inference, so it
works in airplane mode.

NO SCORE. The report ends in a `reading` block that states what was measured and what
follows from it -- a concurrency the curve supports, a language the gate refuses -- and
never a number standing for "how good is my AI".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable

_LOG = logging.getLogger("monitoring.ai_check")

AI_CHECK_SCHEMA = "oo-ai-check-1"

#: What a QUICK check leaves out, named so its absence is a statement rather than a
#: silence. In a DEEP run the bench is included and this list shrinks to the one thing
#: no machine can do for the operator — see :func:`not_run_here`.
SEPARATE_RUNS: tuple[dict, ...] = (
    {
        "name": "Comparative model bench",
        "where": "the same button, with 'every model' ticked",
        "why": (
            "It loads every roster model in turn over a frozen input set and is resumable "
            "per model because it runs for hours. A quick check is minutes, so the two are "
            "one button with a choice rather than two buttons."
        ),
    },
)

#: The human step. Anchor accuracy needs verdicts a PERSON graded: agreement between
#: models is not correctness, and a model grading its own answers measures nothing. So
#: the bench reports that one metric as unmeasured with its reason, rather than filling
#: it with something that looks like a number.
NEEDS_A_HUMAN: dict = {
    "name": "Anchor grading",
    "where": "Settings → Advanced → AI diagnostics → grade a sitting",
    "why": (
        "Triage anchor accuracy is measured against verdicts a person graded. Nothing here "
        "can supply those: two models agreeing is not either being right, and a model asked "
        "to grade itself measures nothing at all. Every other metric in this report is "
        "measured without you; this one is reported as unmeasured until a sitting exists."
    ),
}


def not_run_here(*, deep: bool, anchors_available: bool) -> list[dict]:
    """What this run did NOT cover, computed rather than hardcoded.

    A static list would keep claiming the bench was skipped in the very runs that
    include it, which is the kind of stale sentence that survives for months.
    """
    out: list[dict] = [] if deep else list(SEPARATE_RUNS)
    if not anchors_available:
        out.append(NEEDS_A_HUMAN)
    return out


def _step(name: str, fn: Callable[[], Any], *, monotonic=time.monotonic) -> dict:
    """Run one step, timed, and never let its failure end the run."""
    t0 = monotonic()
    try:
        out = fn()
        return {"step": name, "ok": True, "seconds": round(monotonic() - t0, 3), "report": out}
    except Exception as exc:  # noqa: BLE001 - a broken step is data, not a crash
        _LOG.warning("ai-check step %s failed: %s", name, exc)
        return {
            "step": name,
            "ok": False,
            "seconds": round(monotonic() - t0, 3),
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }


def _backend_line(facts: dict | None) -> dict:
    """Whether a model can be reached at all -- the fact every other step depends on.

    The model comes from ``active_model``, not from the backend block: those answer
    different questions (what this machine will SERVE with, versus who could serve a
    request right now), and reading one for the other is how a model id ends up beside
    the wrong backend's name.
    """
    f = (facts or {}).get("backend") or {}
    am = (facts or {}).get("active_model") or {}
    return {
        "backend": f.get("backend"),
        "serves_with": am.get("provisioning_backend"),
        "model": am.get("model"),
        "available": bool(f.get("available")),
        "reason": f.get("reason"),
    }


def _throughput_advice(throughput: dict | None) -> dict | None:
    """What the concurrency curve supports, in the operator's own terms.

    The measurement already knows this; it was buried in a downloadable file. A GPU
    sitting at a quarter of its capacity while the best measured level is at or above
    the server's configured limit is not a mystery, it is a setting.
    """
    if not throughput or not throughput.get("available"):
        return None
    reading = throughput.get("reading") or {}
    best = reading.get("best_concurrency")
    configured = throughput.get("configured_concurrency")
    if best is None or configured is None:
        return None
    line = {
        "best_measured_concurrency": best,
        "configured_concurrency": configured,
        "best_calls_per_hour": reading.get("best_calls_per_hour"),
        "speedup_over_serial": reading.get("speedup_over_serial"),
    }
    if best >= configured:
        line["action"] = (
            f"The best level measured ({best}) is at or above the running server's limit "
            f"({configured}), so the curve had not flattened when it ran out of room. "
            "Raising OO_VLLM_CONCURRENCY and RESTARTING the backend is what would let a "
            "higher level be measured."
        )
    else:
        line["action"] = (
            f"Throughput peaked at {best}, below the configured limit of {configured}, so "
            "more requests in flight would not have helped: the ceiling here is the model "
            "and the card, not the setting."
        )
    return line


def _gate_lines(perception: dict | None) -> dict | None:
    """Which languages the live gate clears, refuses, or never measured.

    Three states, never two: "never evaluated" is not "failed", and collapsing them
    would make an untested language look like a rejected one.
    """
    if not perception or perception.get("status") == "unavailable":
        return None
    try:
        from src.ai_layer.perception_extract import gate_languages_from_report
    except Exception:  # noqa: BLE001 - a core install has no gate to read
        return None
    try:
        gates = gate_languages_from_report(perception) or {}
    except Exception as exc:  # noqa: BLE001 - report the gap, never guess a verdict
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    cleared = sorted(k for k, v in gates.items() if v.get("active") is True)
    refused = sorted(k for k, v in gates.items() if v.get("active") is False)
    unmeasured = sorted(k for k, v in gates.items() if v.get("active") is None)
    return {
        "cleared": cleared,
        "refused": refused,
        "unmeasured": unmeasured,
        "note": (
            "'unmeasured' is not 'failed'. A language the harness never tested is refused "
            "for want of evidence, which is a different thing to fix than one that "
            "hallucinated its way past the floor."
        ),
    }


class _StepCtx:
    """Forwards a sub-run's own progress into the outer job's line, prefixed.

    The comparative bench reports "vllm · model · triage" as it goes, and that detail
    is the only thing that makes an hours-long step readable. Without this the button
    would sit on "bench" for the whole run, which is indistinguishable from a hang.
    """

    def __init__(self, outer, label: str) -> None:
        self._outer, self._label = outer, label

    @property
    def stopping(self) -> bool:
        return bool(self._outer is not None and getattr(self._outer, "stopping", False))

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if self._outer is None:
            return
        try:
            suffix = f" · {done}/{total}" if done is not None and total else ""
            self._outer.set_progress(detail=f"{self._label}{suffix} · {detail or ''}".strip(" ·"))
        except Exception:  # noqa: BLE001 - progress must never break the run
            pass


def ensure_frozen_batch(*, refresh: bool = False, db=None) -> dict:
    """Make sure the bench has its frozen inputs, building them from the corpus if not.

    Maintainer ask 2026-08-10: "I don't want to take care of freezing bench inputs."

    REUSE IS THE DEFAULT, and that is not laziness — it is the comparability rule. Every
    bench report records the digest of the batch it answered, and a resume whose digest
    moved is refused rather than blending two question sets. Rebuilding on every run
    would make each run incomparable with the last, which is the opposite of what a
    bench is for. ``refresh`` is the deliberate "ask new questions" switch.
    """
    from src.ai_layer.bench_batch import (
        BenchArtifactError,
        collect_frozen_inputs,
        load_frozen_batch,
        save_frozen_batch,
    )

    if not refresh:
        try:
            existing = load_frozen_batch()
            return {
                "built": False,
                "digest": existing.get("digest"),
                "built_at": existing.get("built_at"),
                "n_keywords": existing.get("n_keywords") or len(existing.get("keywords") or []),
                "n_sources": existing.get("n_sources") or len(existing.get("sources") or []),
                "reason": "reusing the existing frozen batch so this run is comparable with the last",
            }
        except BenchArtifactError:
            pass  # none yet — build one below

    owned = db is None
    if owned:
        from src.database.session import SessionLocal

        db = SessionLocal()
    try:
        payload = collect_frozen_inputs(db)
    finally:
        if owned:
            db.close()
    save_frozen_batch(payload)
    return {
        "built": True,
        "digest": payload.get("digest"),
        "built_at": payload.get("built_at"),
        "n_keywords": payload.get("n_keywords") or len(payload.get("keywords") or []),
        "n_sources": payload.get("n_sources") or len(payload.get("sources") or []),
        "reason": "no frozen batch existed, so one was sampled from this corpus",
    }


def _live_bench(ctx, *, models, repeats: int, refresh_batch: bool) -> dict:
    """Freeze the inputs if needed, then bench every runnable (model, backend) pair.

    ``allow_backend_switch`` is ON here and that is the whole point of the deep run: a
    vLLM server serves one model, so measuring several means restarting it between
    them, and on a single-GPU machine it means handing the card back and forth with
    Ollama. Left off, the run would silently cover one vLLM model out of however many
    are downloaded.
    """
    from src.ai_layer.bench_batch import load_anchors
    from src.ai_layer.model_bench import run_model_bench

    batch = ensure_frozen_batch(refresh=refresh_batch)
    anchors = load_anchors()
    report = run_model_bench(
        _StepCtx(ctx, "bench"),
        models=models,
        repeats=repeats,
        restart=refresh_batch,
        allow_backend_switch=True,
    )
    report["frozen_batch_step"] = batch
    report["anchors_available"] = bool(anchors and anchors.get("anchors"))
    return report


def _bench_lines(bench: dict | None) -> dict | None:
    """What the comparative bench covered, and what it could not.

    Deliberately NOT a summary of the numbers: those are per model, per task, per
    language, and flattening them into a headline is the composite this bench exists
    to refuse. This says which pairs ran, which were skipped and why, and where the
    same model was measured on both backends -- so the reader knows what the table
    contains before opening it.
    """
    if not bench:
        return None
    if bench.get("status") == "refused":
        return {"refused": bench.get("reason"), "detail": bench.get("detail")}
    skipped = bench.get("skipped") or []
    by_reason: dict[str, list[str]] = {}
    for s in skipped:
        label = s.get("model") or s.get("roster_key") or s.get("backend") or "?"
        by_reason.setdefault(str(s.get("reason") or "unknown"), []).append(
            f"{s.get('backend')}|{label}"
        )
    cross = bench.get("same_model_across_backends") or []
    return {
        "pairs_measured": bench.get("pairs_run") or [],
        "pairs_pending": bench.get("pairs_pending") or [],
        "skipped_by_reason": {k: sorted(v) for k, v in sorted(by_reason.items())},
        "same_model_on_both_backends": [row.get("roster_key") for row in cross],
        "frozen_batch": bench.get("frozen_batch_step"),
        "anchor_accuracy": (
            "measured against the graded sitting"
            if bench.get("anchors_available")
            else "unmeasured — no graded anchors exist; every other metric is measured"
        ),
        "note": (
            "No headline number: the bench reports each metric per model, backend, task "
            "and language, and a single figure over those would hide which one moved. "
            "Open the artifact for the table."
        ),
    }


def default_step_names(
    *, include_perception: bool = True, include_selftests: bool = True, deep: bool = False
) -> list[str]:
    """The steps a live run would take, in order — without taking them.

    A seam rather than a comment: it lets the ORDER be asserted (the bench last, because
    it is the step measured in hours and every cheap step above explains its failures)
    without a test driving real inference, which is how a check-composition test ends up
    touching the corpus and polluting whatever runs after it.
    """
    names = ["facts", "latency", "throughput"]
    if include_perception:
        names.append("perception_eval")
    if include_selftests:
        names.append("selftests")
    if deep:
        names.append("model_bench")
    return names


def run_ai_check(
    ctx=None,
    *,
    repeats: int = 2,
    levels: tuple[int, ...] | None = None,
    calls_per_level: int = 8,
    include_perception: bool = True,
    include_selftests: bool = True,
    deep: bool = False,
    bench_models: list[str] | None = None,
    bench_repeats: int = 2,
    refresh_batch: bool = False,
    steps: dict[str, Callable[[], Any]] | None = None,
) -> dict:
    """Run every AI check this machine can do, in one pass, and report each ALONE.

    ``ctx`` is the ``BackgroundJob`` context (progress + cancellation); ``steps`` is an
    injection seam so the sequencing and the degrade paths are testable without a model.
    """
    started = time.monotonic()

    def progress(done: int, total: int, detail: str) -> None:
        # ``set_progress``, keyword-only: that is JobContext's actual API. An earlier
        # cut called a ``progress`` method that does not exist, guarded by hasattr —
        # so it silently did nothing and the button reported no progress at all for
        # the whole run. A guarded call to a misremembered name is indistinguishable
        # from a job that has nothing to report.
        if ctx is None:
            return
        try:
            ctx.set_progress(done=done, total=total, detail=detail)
        except Exception:  # noqa: BLE001 - progress must never break the run
            pass

    def stopping() -> bool:
        return bool(ctx is not None and getattr(ctx, "stopping", False))

    plan: list[tuple[str, Callable[[], Any]]] = []
    if steps is not None:
        plan = list(steps.items())
    else:
        # ``model_bench`` is LAST, and deliberately so: it is the step measured in
        # hours, and every cheap step above explains its failures. A backend that is
        # unreachable should be visible in seconds, not after a bench has spent an
        # afternoon failing every pair for that one reason. The order lives in
        # ``default_step_names`` so it can be asserted without running anything.
        live: dict[str, Callable[[], Any]] = {
            "facts": _live_facts,
            "latency": lambda: _live_latency(repeats),
            "throughput": lambda: _live_throughput(levels, calls_per_level),
            "perception_eval": _live_perception,
            "selftests": _live_selftests,
            "model_bench": lambda: _live_bench(
                ctx, models=bench_models, repeats=bench_repeats, refresh_batch=refresh_batch
            ),
        }
        plan = [
            (name, live[name])
            for name in default_step_names(
                include_perception=include_perception,
                include_selftests=include_selftests,
                deep=deep,
            )
        ]

    results: dict[str, dict] = {}
    total = len(plan)
    for i, (name, fn) in enumerate(plan):
        if stopping():
            results[name] = {"step": name, "ok": False, "error": "cancelled"}
            break
        progress(i, total, name)
        results[name] = _step(name, fn)
    progress(total, total, "done")

    facts = (results.get("facts") or {}).get("report")
    throughput = (results.get("throughput") or {}).get("report")
    perception = (results.get("perception_eval") or {}).get("report")
    bench = (results.get("model_bench") or {}).get("report")

    failed = [k for k, v in results.items() if not v.get("ok")]
    return {
        "schema": AI_CHECK_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - started, 2),
        "deep": bool(deep),
        "steps": [results[k] for k, _ in plan if k in results],
        "reading": {
            "backend": _backend_line(facts),
            "throughput": _throughput_advice(throughput),
            "extraction_gate": _gate_lines(perception),
            "models": _bench_lines(bench),
            "steps_failed": failed,
        },
        "not_run_here": not_run_here(
            deep=bool(deep), anchors_available=bool((bench or {}).get("anchors_available"))
        ),
        "method": (
            "Each check runs once, in order, against the model this machine actually "
            "serves with, and reports its own numbers with its own method and caveats "
            "unchanged. A step that fails records why and the run continues, so a "
            "half-broken machine still produces a report that says which half. Every "
            "call is loopback inference: no egress, works in airplane mode."
        ),
        "caveat": (
            "Measured HERE, with THIS model, on synthetic prompts of representative size, "
            "on a machine that may be doing other work. There is no overall figure and no "
            "pass mark: each number answers its own question, and blending them would hide "
            "which one moved."
        ),
    }


# --------------------------------------------------------------------------- #
#  The live steps. Imported lazily so a core install can still import this module.
# --------------------------------------------------------------------------- #
def _live_facts() -> dict:
    from src.monitoring.ai_diagnostics import ai_diagnostics_report

    return ai_diagnostics_report()


def _live_latency(repeats: int) -> dict:
    from src.monitoring.llm_bench import run_llm_bench

    return run_llm_bench(repeats=repeats)


def _live_throughput(levels: tuple[int, ...] | None, calls_per_level: int) -> dict:
    from src.monitoring.llm_throughput import run_throughput_bench

    return run_throughput_bench(levels=levels, calls_per_level=calls_per_level)


def _live_perception() -> dict:
    from src.ai_layer.perception_job import run_and_persist_perception_eval

    return run_and_persist_perception_eval()


def _live_selftests() -> dict:
    """The deterministic harness checks: seconds, no model, no network."""
    from src.ai_layer.qualification_assist import run_qualification_assist_selftest
    from src.ai_layer.source_tags import run_source_tags_selftest
    from src.ai_layer.triage import run_triage_selftest
    from src.analytics.perception_eval import run_perception_eval_selftest

    out: dict[str, Any] = {}
    for name, fn in (
        ("keyword_triage", run_triage_selftest),
        ("source_tags", run_source_tags_selftest),
        ("qualification_assist", run_qualification_assist_selftest),
        ("perception_harness", run_perception_eval_selftest),
    ):
        try:
            rep = fn()
            # Each harness reports one overall boolean plus a dict of named boolean
            # checks. Summarise it -- but name the checks that FAILED, because
            # "3 of 16 failed" sends somebody reading a whole file to find which.
            checks = rep.get("checks")
            checks = checks if isinstance(checks, dict) else {}
            out[name] = {
                "passed": bool(rep.get("passed")),
                "checks": len(checks),
                "failed_checks": sorted(k for k, v in checks.items() if v is False),
            }
        except Exception as exc:  # noqa: BLE001 - one broken harness is not five
            out[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out


# --------------------------------------------------------------------------- #
#  Persistence. One dated artifact per run, in the same archive the AI sweeps use,
#  so "the file to attach to a bug report" is one place rather than five.
# --------------------------------------------------------------------------- #
def _dir():
    from src.paths import data_dir

    d = data_dir() / "triage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_and_persist_ai_check(ctx=None, **kwargs) -> dict:
    """``BackgroundJob`` worker: run the check and save it, dated.

    A failed WRITE must not lose the measurement -- the run took minutes and the report
    is already in hand, so a disk error is reported beside the results rather than
    thrown over them.
    """
    import json

    out = run_ai_check(ctx, **kwargs)
    try:
        path = _dir() / f"oo-ai-check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        out["path"] = str(path)
        out["filename"] = path.name
    except OSError as exc:
        out["persist_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def last_ai_check_report() -> dict:
    """The newest saved run, or an honest ``{available: false}``."""
    import json

    try:
        files = sorted(_dir().glob("oo-ai-check-*.json"))
    except OSError as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if not files:
        return {"available": False, "reason": "no AI check has been run on this machine yet"}
    newest = files[-1]
    try:
        out = json.loads(newest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a corrupt artifact is a fact, not a crash
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    out["available"] = True
    out["filename"] = newest.name
    return out


__all__ = [
    "AI_CHECK_SCHEMA",
    "NEEDS_A_HUMAN",
    "SEPARATE_RUNS",
    "default_step_names",
    "ensure_frozen_batch",
    "last_ai_check_report",
    "not_run_here",
    "run_ai_check",
    "run_and_persist_ai_check",
]
