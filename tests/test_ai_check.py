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
    """A BackgroundJob stand-in: records progress, can ask for a stop."""

    def __init__(self, stop_after: int | None = None):
        self.calls: list[tuple[int, int, str]] = []
        self._stop_after = stop_after
        self.stopping = False

    def progress(self, done: int, total: int, detail: str) -> None:
        self.calls.append((done, total, detail))
        if self._stop_after is not None and done >= self._stop_after:
            self.stopping = True


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
