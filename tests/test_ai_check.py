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
            "same_model_across_backends": [{"roster_key": "qwen35-0-8b"}],
            "anchors_available": True,
        }
    )
    assert line["pairs_measured"] == ["ollama|a:1", "vllm|org/A"]
    assert line["skipped_by_reason"]["not-installed"] == ["ollama|z:1", "vllm|org/B", "vllm|org/C"]
    assert line["same_model_on_both_backends"] == ["qwen35-0-8b"]
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
    for field in ("deep", "bench_models", "refresh_batch"):
        assert field in AiCheckRunBody.model_fields, f"{field} left the endpoint"
        assert field in accepted, f"{field} is sent but {AC.run_ai_check.__name__} ignores it"
    assert AiCheckRunBody().deep is False, (
        "the hours-long run must be opt-in — a default-on deep check would turn one "
        "click into an afternoon"
    )


def test_the_deep_run_turns_backend_switching_ON(monkeypatch) -> None:
    """THE LOAD-BEARING FLAG for the whole ask. Left off, a vLLM server serves the one
    model it was started with, so the run would silently cover ONE model out of however
    many are downloaded — and report it as though that were the roster."""
    seen: dict = {}
    monkeypatch.setattr(AC, "ensure_frozen_batch", lambda **kw: {"built": False, "digest": "d"})
    monkeypatch.setattr("src.ai_layer.bench_batch.load_anchors", lambda **_kw: None)
    monkeypatch.setattr(
        "src.ai_layer.model_bench.run_model_bench",
        lambda ctx, **kw: seen.update(kw) or {"pairs_run": []},
    )

    out = AC._live_bench(None, models=None, repeats=2, refresh_batch=False)

    assert seen["allow_backend_switch"] is True
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
        "src.ai_layer.model_bench.run_model_bench",
        lambda ctx, **kw: seen.update(kw) or {},
    )

    AC._live_bench(None, models=None, repeats=1, refresh_batch=True)

    assert seen["restart"] is True
