"""One button, every AI check, one report — and each step still reported alone.

Maintainer 2026-08-09: "Can you simplify all AI related diagnostics into one single
button to test everything at once?"

The steps are injected so the SEQUENCING and the DEGRADE paths are testable without a
model: what this file pins is that a failing step does not take the run down with it,
that the reading is derived from what was measured rather than asserted, and that the
one thing this check deliberately does NOT run is named rather than quietly omitted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import src.monitoring.ai_check as AC


class _Ctx:
    """A JobContext stand-in: records progress, can ask for a stop.

    THE SIGNATURE IS THE POINT, and it was wrong here before. This double carried a
    ``progress(done, total, detail)`` method, the real ``JobContext`` has a
    keyword-only ``set_progress``, and the code under test called the double's name
    behind a ``hasattr`` guard — so the check reported NO progress for its whole run
    on a real job while this test happily asserted that it did. A double that
    describes a class which does not exist proves nothing about the one that does;
    ``test_the_context_double_matches_the_real_job_context`` below pins the two
    together so it cannot drift again.
    """

    def __init__(self, stop_after: int | None = None):
        self.calls: list[tuple[int | None, int | None, str | None]] = []
        self._stop_after = stop_after
        self.stopping = False

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.calls.append((done, total, detail))
        if self._stop_after is not None and done is not None and done >= self._stop_after:
            self.stopping = True


def test_the_context_double_matches_the_real_job_context() -> None:
    """The double above must be callable exactly as the real context is."""
    import inspect

    from src.jobs.background import JobContext

    real = inspect.signature(JobContext.set_progress)
    fake = inspect.signature(_Ctx.set_progress)
    assert list(real.parameters) == list(fake.parameters), (
        "the double drifted from JobContext — the last time it did, a progress call "
        "that could never fire shipped behind a hasattr guard"
    )
    for name, param in real.parameters.items():
        if name == "self":
            continue
        assert fake.parameters[name].kind == param.kind, name


def _steps(**overrides):
    base = {
        "facts": lambda: {"backend": {"backend": "vllm", "available": True}},
        "latency": lambda: {"available": True},
        "throughput": lambda: {"available": True},
    }
    base.update(overrides)
    return base


def test_a_failing_step_records_why_and_the_run_continues() -> None:
    """The most useful report from a half-broken machine says which half.

    A step that raised used to be the whole run; here it becomes one row with its
    exception, and the steps after it still measure.
    """
    def boom():
        raise RuntimeError("nvidia-smi hung")

    out = AC.run_ai_check(steps=_steps(latency=boom))
    by = {s["step"]: s for s in out["steps"]}
    assert by["latency"]["ok"] is False
    assert "nvidia-smi hung" in by["latency"]["error"]
    assert by["facts"]["ok"] and by["throughput"]["ok"], "a later step stopped measuring"
    assert out["reading"]["steps_failed"] == ["latency"]


def test_every_step_carries_its_own_time() -> None:
    out = AC.run_ai_check(steps=_steps())
    assert all(isinstance(s["seconds"], float) for s in out["steps"])


def test_the_report_names_what_it_did_not_run() -> None:
    """Silence about the comparative bench would make "everything" a false claim."""
    out = AC.run_ai_check(steps=_steps())
    names = [n["name"] for n in out["not_run_here"]]
    assert any("bench" in n.lower() for n in names), names
    for entry in out["not_run_here"]:
        assert entry["why"] and entry["where"], entry


def test_no_composite_anywhere_in_the_payload() -> None:
    """Five measurements of different things; a blend would hide which one moved."""
    banned = ("score", "ranking", "rating", "grade", "winner")
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(AC.run_ai_check(steps=_steps()))


def test_a_cancel_stops_at_a_step_boundary_and_keeps_what_ran() -> None:
    ctx = _Ctx(stop_after=1)
    out = AC.run_ai_check(ctx, steps=_steps())
    by = {s["step"]: s for s in out["steps"]}
    assert by["facts"]["ok"] is True, "the completed step was discarded"
    assert any(s.get("error") == "cancelled" for s in out["steps"])


def test_progress_is_reported_per_step() -> None:
    ctx = _Ctx()
    AC.run_ai_check(ctx, steps=_steps())
    assert ctx.calls, "nothing reported progress"
    assert ctx.calls[-1][0] == ctx.calls[-1][1], "the final call did not report completion"


# --------------------------------------------------------------------------- #
#  The reading. Derived from measurements, never asserted.
# --------------------------------------------------------------------------- #
def _throughput(best: int, configured: int) -> dict:
    return {
        "available": True,
        "configured_concurrency": configured,
        "reading": {"best_concurrency": best, "best_calls_per_hour": 5697, "speedup_over_serial": 4.57},
    }


def test_a_curve_that_ran_out_of_room_says_the_setting_is_the_lever() -> None:
    """The field question, answered in the UI instead of in a downloaded file.

    "GPU compute did not exceed 50% and was averaging 25%" with the best measured level
    at or above the server's own limit is not a mystery; it is a setting that takes a
    restart to change.
    """
    out = AC.run_ai_check(steps=_steps(throughput=lambda: _throughput(best=8, configured=4)))
    line = out["reading"]["throughput"]
    assert line["best_measured_concurrency"] == 8 and line["configured_concurrency"] == 4
    assert "OO_VLLM_CONCURRENCY" in line["action"] and "RESTART" in line["action"].upper()


def test_a_curve_that_peaked_below_the_limit_says_the_opposite() -> None:
    """The negative-space twin.

    A fix that always told people to raise the setting would be advice, not a reading.
    When throughput peaked BELOW the configured limit, more requests in flight is
    exactly what would not help.
    """
    out = AC.run_ai_check(steps=_steps(throughput=lambda: _throughput(best=2, configured=8)))
    line = out["reading"]["throughput"]
    assert "OO_VLLM_CONCURRENCY" not in line["action"]
    assert "would not have helped" in line["action"]


def test_no_throughput_measurement_yields_no_advice() -> None:
    """An unmeasured curve produces silence, never a default recommendation."""
    out = AC.run_ai_check(steps=_steps(throughput=lambda: {"available": False}))
    assert out["reading"]["throughput"] is None


def test_the_backend_line_reads_the_model_from_active_model_not_the_router() -> None:
    """Two different questions: what this machine SERVES with, and who could serve now.

    Reading one for the other is how a model id ends up printed beside the wrong
    backend's name.
    """
    facts = {
        "backend": {"backend": "ollama", "available": False, "reason": "nothing reachable"},
        "active_model": {"provisioning_backend": "vllm", "model": "org/Repo-3B"},
    }
    out = AC.run_ai_check(steps=_steps(facts=lambda: facts))
    line = out["reading"]["backend"]
    assert line["serves_with"] == "vllm" and line["model"] == "org/Repo-3B"
    assert line["available"] is False and line["reason"] == "nothing reachable"


def test_the_selftest_step_names_the_checks_that_failed() -> None:
    """"3 of 16 failed" sends somebody reading a whole file to find which three."""
    out = AC._live_selftests()
    for name, rep in out.items():
        assert "error" in rep or set(rep) == {"passed", "checks", "failed_checks"}, (name, rep)
        if "error" not in rep:
            assert rep["passed"] is (rep["failed_checks"] == [])


# --------------------------------------------------------------------------- #
#  The deep run: every model, one button (maintainer ask 2026-08-10, item 3)
# --------------------------------------------------------------------------- #
def test_the_bench_runs_last_so_a_dead_backend_shows_in_seconds() -> None:
    """It is the step measured in hours, and every cheap step above explains its
    failures. A backend that is unreachable must be visible before an afternoon has
    been spent failing every pair for that one reason.

    Asserted against the PLAN, not a live run: driving the real steps here would send
    inference at the corpus and pollute whatever test runs next."""
    assert AC.default_step_names(deep=True)[-1] == "model_bench"
    assert "model_bench" not in AC.default_step_names(deep=False)
    assert AC.default_step_names()[0] == "facts", "the fact that explains the rest comes first"

    out = AC.run_ai_check(deep=True, steps={"model_bench": lambda: {"pairs_run": []}})
    assert out["deep"] is True


def test_a_quick_run_names_the_bench_it_skipped() -> None:
    out = AC.run_ai_check(steps=_steps())
    names = [n["name"] for n in out["not_run_here"]]
    assert any("bench" in n.lower() for n in names), names


def test_a_deep_run_no_longer_claims_the_bench_was_skipped() -> None:
    """THE STALE-SENTENCE GUARD. A hardcoded list would keep saying "not run here"
    in the very runs that include it."""
    out = AC.run_ai_check(
        deep=True,
        steps={"model_bench": lambda: {"pairs_run": ["ollama|a"], "anchors_available": True}},
    )
    assert [n["name"] for n in out["not_run_here"]] == []


def test_the_one_thing_no_machine_can_do_is_named_when_it_is_missing() -> None:
    """Anchor accuracy needs a human's verdicts. Nothing may fill it in, and the
    report must say which metric is unmeasured rather than quietly omitting it."""
    out = AC.run_ai_check(
        deep=True,
        steps={"model_bench": lambda: {"pairs_run": [], "anchors_available": False}},
    )
    entry = next(n for n in out["not_run_here"] if "nchor" in n["name"])
    assert "grading" in entry["why"].lower() or "graded" in entry["why"].lower()
    assert "agreeing is not" in entry["why"], "why a model cannot supply them"
    assert out["reading"]["models"]["anchor_accuracy"].startswith("unmeasured")


def test_the_bench_reading_says_what_is_in_the_table_not_a_headline_number() -> None:
    """Per model, per task, per language — a single figure over those is the composite
    the bench exists to refuse."""
    line = AC._bench_lines(
        {
            "pairs_run": ["ollama|a:1", "vllm|org/A"],
            "pairs_pending": [],
            "skipped": [
                {"backend": "vllm", "model": "org/B", "reason": "not-installed"},
                {"backend": "vllm", "model": "org/C", "reason": "not-installed"},
                {"backend": "ollama", "model": "z:1", "reason": "not-installed"},
            ],
            "same_model_across_backends": [{"model_key": "ministral-3-3b-instruct-2512"}],
            "anchors_available": True,
        }
    )
    assert line["pairs_measured"] == ["ollama|a:1", "vllm|org/A"]
    assert line["skipped_by_reason"]["not-installed"] == ["ollama|z:1", "vllm|org/B", "vllm|org/C"]
    assert line["same_model_on_both_backends"] == ["ministral-3-3b-instruct-2512"]
    for key in line:
        assert "overall" not in key and "total" not in key, key


def test_a_refused_resume_is_surfaced_rather_than_read_as_an_empty_run() -> None:
    line = AC._bench_lines({"status": "refused", "reason": "frozen-batch-changed", "detail": "d"})
    assert line["refused"] == "frozen-batch-changed"


def test_the_frozen_batch_is_reused_so_two_runs_stay_comparable(monkeypatch) -> None:
    """Rebuilding per run would make every run incomparable with the last, which is
    the opposite of what a bench is for."""
    built: list[str] = []
    monkeypatch.setattr(
        "src.ai_layer.bench_batch.load_frozen_batch",
        lambda **_kw: {"digest": "abc", "built_at": "2026-08-01", "keywords": [1, 2]},
    )
    monkeypatch.setattr(
        "src.ai_layer.bench_batch.collect_frozen_inputs",
        lambda *_a, **_kw: built.append("built") or {"digest": "new"},
    )

    out = AC.ensure_frozen_batch()

    assert built == [], "an existing batch must not be resampled"
    assert out["built"] is False and out["digest"] == "abc"
    assert "comparable" in out["reason"]


def test_a_missing_batch_is_built_from_the_corpus_without_asking(monkeypatch) -> None:
    """Maintainer ask: "I don't want to take care of freezing bench inputs.\""""
    from src.ai_layer.bench_batch import BenchArtifactError

    saved: list[dict] = []
    monkeypatch.setattr(
        "src.ai_layer.bench_batch.load_frozen_batch",
        lambda **_kw: (_ for _ in ()).throw(BenchArtifactError("none yet")),
    )
    monkeypatch.setattr(
        "src.ai_layer.bench_batch.collect_frozen_inputs",
        lambda *_a, **_kw: {"digest": "fresh", "keywords": [1], "sources": []},
    )
    monkeypatch.setattr(
        "src.ai_layer.bench_batch.save_frozen_batch", lambda p, **_kw: saved.append(p) or "/tmp/b"
    )

    out = AC.ensure_frozen_batch(db=object())

    assert out["built"] is True and out["digest"] == "fresh"
    assert saved, "a built batch must be persisted, or the next run rebuilds it"


def test_a_sub_runs_progress_reaches_the_outer_job() -> None:
    """The bench reports "vllm · model · triage" as it goes, and that detail is the
    only thing that makes an hours-long step readable. Without it the button sits on
    one word for the whole run, which is indistinguishable from a hang."""
    ctx = _Ctx()
    inner = AC._StepCtx(ctx, "bench")
    inner.set_progress(done=2, total=7, detail="vllm · org/A · triage")
    assert ctx.calls, "nothing forwarded"
    detail = ctx.calls[-1][2]
    assert "bench" in detail and "2/7" in detail and "triage" in detail


def test_a_cancel_reaches_the_sub_run() -> None:
    """An hours-long step that cannot be stopped is worse than no stop button."""
    ctx = _Ctx()
    inner = AC._StepCtx(ctx, "bench")
    assert inner.stopping is False
    ctx.stopping = True
    assert inner.stopping is True


def test_the_endpoint_forwards_every_field_the_worker_accepts() -> None:
    """A body field the worker does not take is a control that silently does nothing.

    The recorded shape of this failure: a request carries a flag, the job starts, and
    the run behaves as though the flag were never sent — with a 200 either way.
    """
    import inspect

    from src.api.diagnostics import AiCheckRunBody

    accepted = set(inspect.signature(AC.run_ai_check).parameters)
    for field in ("deep", "refresh_batch"):
        assert field in AiCheckRunBody.model_fields, f"{field} left the endpoint"
        assert field in accepted, f"{field} is sent but {AC.run_ai_check.__name__} ignores it"
    # BOTH DIRECTIONS, because the named list above only catches one of them. The
    # 2026-08-12 one-model ruling left `bench_models` and `download_missing` on this body
    # after the worker stopped accepting them -- a control the API still advertised and
    # that could no longer do anything, which is precisely the failure this test is
    # named for, surviving inside the test meant to prevent it.
    for field in AiCheckRunBody.model_fields:
        if field == "levels":
            continue  # parsed into `levels` tuple by the endpoint, not forwarded raw
        assert field in accepted, (
            f"the endpoint advertises {field!r} but run_ai_check does not take it: a "
            "request carrying it would get a 200 and change nothing"
        )
    assert AiCheckRunBody().deep is False, (
        "the slow run must be opt-in — a default-on deep check would turn one click "
        "into tens of minutes"
    )


def test_the_deep_run_manages_NOTHING(monkeypatch) -> None:
    """THE INVERSION, ruled 2026-08-12: "the app has failed to manage both ollama and
    vllm, so I'll do the managing myself."

    This used to assert the opposite -- that the deep run turned backend switching ON,
    because with a roster of models a vLLM server serving one of them would otherwise
    cover one pair out of many. With one model there is nothing to switch BETWEEN, and a
    run that rearranges the machine measures its own management. It now goes through
    run_default_model_bench, which measures whatever is serving and starts, stops and
    hands over nothing."""
    seen: dict = {}
    monkeypatch.setattr(AC, "ensure_frozen_batch", lambda **kw: {"built": False, "digest": "d"})
    monkeypatch.setattr("src.ai_layer.bench_batch.load_anchors", lambda **_kw: None)
    monkeypatch.setattr(
        "src.ai_layer.model_bench.run_default_model_bench",
        lambda ctx, **kw: seen.update(kw) or {"pairs_run": []},
    )

    out = AC._live_bench(None, repeats=2, refresh_batch=False)

    assert "allow_backend_switch" not in seen, "nothing may ask the bench to restart a server"
    assert "models" not in seen, "there is no roster to pass"
    assert seen["restart"] is False, "a reused batch resumes; it does not start over"
    assert out["frozen_batch_step"]["digest"] == "d"
    assert out["anchors_available"] is False


def test_refreshing_the_inputs_restarts_the_bench(monkeypatch) -> None:
    """New questions mean the earlier answers are answers to something else; resuming
    across them would put two question sets in one table."""
    seen: dict = {}
    monkeypatch.setattr(AC, "ensure_frozen_batch", lambda **kw: {"built": True, "digest": "new"})
    monkeypatch.setattr("src.ai_layer.bench_batch.load_anchors", lambda **_kw: None)
    monkeypatch.setattr(
        "src.ai_layer.model_bench.run_default_model_bench",
        lambda ctx, **kw: seen.update(kw) or {},
    )

    AC._live_bench(None, repeats=1, refresh_batch=True)

    assert seen["restart"] is True


def test_the_bench_holds_the_lane_while_it_measures(monkeypatch) -> None:
    """Correctness, not politeness -- and STILL correctness now that the bench restarts
    nothing: a background sweep running against the same server competes for the card
    this bench is trying to measure, so its numbers would be about the contention rather
    than the model. Every background-AI entry point already checks this hold."""
    from src.ai_layer.coordinator import user_batch_active

    seen: list[dict] = []
    monkeypatch.setattr(AC, "ensure_frozen_batch", lambda **_kw: {"digest": "d"})
    monkeypatch.setattr("src.ai_layer.bench_batch.load_anchors", lambda **_kw: None)
    monkeypatch.setattr(
        "src.ai_layer.model_bench.run_default_model_bench",
        lambda _ctx, **_kw: seen.append(user_batch_active()) or {},
    )

    assert user_batch_active()["held"] is False, "nothing should be holding it beforehand"
    AC._live_bench(None, repeats=1, refresh_batch=False)

    assert seen[0]["held"] is True, "the lane was not held while the bench ran"
    assert any("bench" in h for h in seen[0]["holders"])
    assert user_batch_active()["held"] is False, "the hold outlived the run"


def test_a_raising_bench_still_releases_the_lane(monkeypatch) -> None:
    """A stranded hold would leave background AI paused until the app restarts."""
    from src.ai_layer.coordinator import user_batch_active

    monkeypatch.setattr(AC, "ensure_frozen_batch", lambda **_kw: {"digest": "d"})
    monkeypatch.setattr("src.ai_layer.bench_batch.load_anchors", lambda **_kw: None)
    monkeypatch.setattr(
        "src.ai_layer.model_bench.run_default_model_bench",
        lambda _ctx, **_kw: (_ for _ in ()).throw(RuntimeError("no backend")),
    )

    try:
        AC._live_bench(None, repeats=1, refresh_batch=False)
    except RuntimeError:
        pass
    assert user_batch_active()["held"] is False


# --------------------------------------------------------------------------- #
#  provisioning (2026-08-10): survey first, download only when asked
# --------------------------------------------------------------------------- #
def test_a_deep_run_never_downloads_unless_asked():
    """Tens of gigabytes must not be inferred from a click on 'run the benchmark'."""
    calls: list[str] = []
    steps = {
        "provision": lambda: {"to_fetch": [{"backend": "vllm", "model": "x"}], "models": []},
        "model_bench": lambda: calls.append("bench") or {"results": {}},
    }
    AC.run_ai_check(steps=steps, deep=True)
    assert calls == ["bench"], "the injected plan runs as given; no fetch is implied"


def test_context_is_measured_in_every_run_not_only_the_deep_one():
    """The question "what does a longer article cost me" does not need an afternoon —
    it is minutes, so it belongs in the ordinary check beside latency and throughput."""
    for deep in (False, True):
        names = AC.default_step_names(deep=deep)
        assert "context" in names
        assert names.index("context") > names.index("throughput"), (
            "after throughput: both sweep the same client, and the cheap ones come first"
        )


# --------------------------------------------------------------------------- #
#  the extraction gate, at BOTH levels (2026-09-05 field defect 4)
#
#  The 09-04 check on the maintainer's machine rendered "cleared: 13, refused: 0,
#  unmeasured: 0" while the very same gate refused `hi`'s `who` for inventing people
#  (hallucination 1.0) and `fr`'s `who` for recovering nothing (recall 0.0) -- two
#  refusals, of the two different kinds the floors exist to catch, and eleven of the
#  thirteen "cleared" languages cleared on `where` ALONE. The run was correct
#  throughout; `_gate_lines` read only the language-level rollup and the distinction
#  died at the render boundary. `_gate_lines` had NO test at all before this.
#
#  Every guard below has its negative-space twin, because an over-eager renderer that
#  invents a refusal is exactly as dishonest as one that hides a real one.
# --------------------------------------------------------------------------- #
def _harness(by_language: dict) -> dict:
    """The live-eval ENVELOPE `_gate_lines` is handed: metadata wrapping the S6.5
    harness's own report one level in. Built in the shape the real
    ``run_perception_eval_against_model`` writes, since reading it at the wrong level
    is a defect this module has shipped before."""
    return {"status": "ok", "model": "m", "report": {"n_cases": 4, "by_language": by_language}}


def _metrics(*, hallucination=None, recall=None, n_gold=0, n_pred=0) -> dict:
    return {
        "hallucination_rate": hallucination,
        "recall": recall,
        "n_gold": n_gold,
        "n_pred": n_pred,
    }


def test_a_field_refused_inside_a_cleared_language_is_published() -> None:
    """THE FIELD DEFECT. `hi` rolls up active because `where` cleared; `who` was
    refused for invention. Reporting only the rollup tells the reader the model
    invents nothing anywhere."""
    out = AC._gate_lines(_harness({
        "hi": {
            "n_cases": 1,
            "who": _metrics(hallucination=1.0, n_pred=2),
            "where": _metrics(recall=1.0, n_gold=1),
        },
    }))
    assert out["cleared"] == ["hi"], "the language rollup keeps its own meaning"
    assert out["refused"] == [], "and it is still not refused AT THE LANGUAGE LEVEL"
    assert [(r["language"], r["field"]) for r in out["refused_fields"]] == [("hi", "who")]
    assert "hallucination" in out["refused_fields"][0]["reason"], (
        "the reason names WHICH floor it hit -- invention and silence are different failures"
    )
    assert out["by_field"]["who"]["refused"] == ["hi"]
    assert out["by_field"]["where"]["cleared"] == ["hi"]


def test_the_two_kinds_of_refusal_are_both_reported_and_told_apart() -> None:
    """Invention (hallucination above the floor) and silence (recall at zero) are the
    two floors; the field export carried one of each and neither reached the reader."""
    out = AC._gate_lines(_harness({
        "hi": {"n_cases": 1, "who": _metrics(hallucination=1.0, n_pred=2),
               "where": _metrics(recall=1.0, n_gold=1)},
        "fr": {"n_cases": 1, "who": _metrics(recall=0.0, n_gold=1),
               "where": _metrics(recall=1.0, n_gold=1)},
    }))
    reasons = {r["language"]: r["reason"] for r in out["refused_fields"]}
    assert set(reasons) == {"hi", "fr"}
    assert "hallucination" in reasons["hi"]
    assert "recall" in reasons["fr"] and "recovered nothing" in reasons["fr"]


def test_a_gate_with_nothing_refused_reports_no_refusals() -> None:
    """The negative-space twin: an over-eager renderer inventing a refusal would be
    exactly as dishonest as one hiding it."""
    out = AC._gate_lines(_harness({
        "en": {"n_cases": 2, "who": _metrics(hallucination=0.0, recall=1.0, n_gold=2, n_pred=2),
               "where": _metrics(recall=1.0, n_gold=2), "when": _metrics(recall=1.0, n_gold=2)},
    }))
    assert out["refused_fields"] == []
    assert out["partly_cleared"] == [], "cleared for all three is not 'partly cleared'"
    assert out["field_counts"] == {"cleared": 3, "refused": 0, "unmeasured": 0, "total": 3}


def test_a_language_cleared_on_one_field_says_which_fields_it_was_not() -> None:
    """Eleven of the thirteen "cleared" languages in the field report cleared on
    `where` alone. "Cleared" over-reads badly without this."""
    out = AC._gate_lines(_harness({
        "zh": {"n_cases": 1, "where": _metrics(recall=1.0, n_gold=1)},
    }))
    assert out["cleared"] == ["zh"]
    assert out["partly_cleared"] == [{"language": "zh", "not_cleared": ["who", "when"]}]
    assert out["by_field"]["who"]["unmeasured"] == ["zh"]


def test_a_language_refused_outright_is_not_called_partly_cleared() -> None:
    """A language that cleared NOTHING belongs in `refused`, and calling it "cleared for
    some fields only" would be a fabricated partial pass. The guard on `partly_cleared`
    is what keeps the two apart, and only a fully-refused language can discriminate it."""
    out = AC._gate_lines(_harness({
        "ar": {"n_cases": 1, "who": _metrics(hallucination=1.0, n_pred=1),
               "where": _metrics(recall=0.0, n_gold=1)},
    }))
    assert out["refused"] == ["ar"], "no field cleared, so the language is refused"
    assert out["cleared"] == []
    assert out["partly_cleared"] == [], "nothing was cleared, so nothing is PARTLY cleared"
    assert len(out["refused_fields"]) == 2, "both refusals are still named"


def test_an_unmeasured_field_is_never_counted_as_a_refusal() -> None:
    """Three states, one level down: "never evaluated" is not "failed" for a FIELD
    either, and a report that blended them would send the operator to fix a model
    that was simply never asked."""
    out = AC._gate_lines(_harness({
        "ja": {"n_cases": 1, "where": _metrics(recall=1.0, n_gold=1)},
    }))
    assert out["refused_fields"] == []
    assert out["field_counts"]["unmeasured"] == 2
    assert out["field_counts"]["refused"] == 0


def test_the_counts_carry_their_own_denominator() -> None:
    """A count of refusals with no total cannot be read: 2 refused out of 39 verdicts
    and 2 out of 4 are different machines."""
    out = AC._gate_lines(_harness({
        "en": {"n_cases": 1, "who": _metrics(hallucination=0.0, recall=1.0, n_gold=1, n_pred=1),
               "where": _metrics(recall=1.0, n_gold=1), "when": _metrics(recall=1.0, n_gold=1)},
        "hi": {"n_cases": 1, "who": _metrics(hallucination=1.0, n_pred=2),
               "where": _metrics(recall=1.0, n_gold=1)},
    }))
    c = out["field_counts"]
    assert c["total"] == c["cleared"] + c["refused"] + c["unmeasured"] == 6
    assert (c["cleared"], c["refused"], c["unmeasured"]) == (4, 1, 1)


def test_the_note_says_cleared_does_not_mean_cleared_for_everything() -> None:
    """The headline list is the thing that over-read; the note is what stops it."""
    out = AC._gate_lines(_harness({"en": {"n_cases": 1, "where": _metrics(recall=1.0, n_gold=1)}}))
    assert "at least one field" in out["note"].lower()


def test_a_report_predating_per_field_verdicts_is_named_not_counted_as_a_gap(monkeypatch) -> None:
    """A SCHEMA gap is not a MEASUREMENT gap. Reporting an old report's languages as
    "unmeasured for every field" would claim a harness result that was never absent."""
    import src.ai_layer.perception_extract as PE

    def _legacy(_report):
        return {"en": {"active": True, "reason": "cleared", "checks": ["x"]}}

    monkeypatch.setattr(PE, "gate_languages_from_report", _legacy)
    out = AC._gate_lines(_harness({"en": {}}))
    assert out["cleared"] == ["en"]
    assert out["field_counts"]["unmeasured"] == 0, "no field was measured OR left unmeasured"
    assert out["no_field_verdicts"]["languages"] == ["en"]
    assert "before per-field gating existed" in out["no_field_verdicts"]["reason"]


def test_an_empty_fields_dict_is_an_absence_of_verdicts_not_three_unmeasured_ones(
    monkeypatch,
) -> None:
    """``{}`` and a missing key are the same absence, and neither is a measurement.

    Counting an empty ``fields`` as "unmeasured for who, where and when" would publish
    three gaps the harness never left -- the same fabrication the legacy branch exists
    to avoid, reached by a shape one character away from it."""
    import src.ai_layer.perception_extract as PE

    monkeypatch.setattr(
        PE,
        "gate_languages_from_report",
        lambda _r: {"en": {"active": True, "reason": "c", "checks": ["x"], "fields": {}}},
    )
    out = AC._gate_lines(_harness({"en": {}}))
    assert out["field_counts"]["total"] == 0, "no verdicts is not three unmeasured ones"
    assert out["no_field_verdicts"]["languages"] == ["en"]


def test_the_field_order_follows_the_extractor_not_a_copy_of_it() -> None:
    """Lockstep: a field added to the sweep must not need a second edit here to become
    visible, and one it does not have must never be invented."""
    from src.ai_layer.perception_extract import _FIELDS

    out = AC._gate_lines(_harness({
        "en": {"n_cases": 1, "where": _metrics(recall=1.0, n_gold=1)},
    }))
    assert list(out["by_field"]) == list(_FIELDS)


def test_a_field_the_gate_carries_beyond_the_known_order_is_appended_not_dropped() -> None:
    """The report may never be SHORTER than the evidence it was handed."""
    assert AC._field_order(["where", "who", "why"]) == ["who", "where", "why"]


def test_no_gate_at_all_is_still_no_line() -> None:
    """A core install has no gate to read; an unavailable eval has no verdict. Neither
    is a refusal."""
    assert AC._gate_lines(None) is None
    assert AC._gate_lines({"status": "unavailable"}) is None


def test_a_raising_gate_reports_the_gap_rather_than_guessing_a_verdict() -> None:
    out = AC._gate_lines({"status": "ok", "report": "not-a-dict"})
    assert "error" in out and "refused_fields" not in out
