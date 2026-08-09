"""The Background-AI coordinator (field impressions 2026-08-01, rulings 12-13).

Before this, each progressive sweep had its own toggle. Turning several on was
possible and quietly wrong: Ollama serves one generation at a time, so they simply
queued behind each other with no coordination. The master switch is therefore a
COORDINATOR -- one lane, enabled sweeps round-robin, each resuming from its own
persisted cursor.

The load-bearing property, and the reason these tests exist in this shape, is the
2026-07-24 exclusive-hold lesson: a pause honoured by only the main loop is
honest-sounding and incomplete, because every OTHER way of starting equivalent
work walks straight past it. So the tests below assert the hold is checked by
every background-AI entry point, not just by the coordinator.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.ai_layer import coordinator as C

_SRC = Path(__file__).resolve().parents[1] / "src"


class _Ctx:
    """A JobContext stand-in: cooperative stop + progress, nothing else."""

    def __init__(self, stop_after: int = 0) -> None:
        self._stop = False
        self.details: list[str] = []
        self.calls = 0
        self.stop_after = stop_after

    @property
    def stopping(self) -> bool:
        return self._stop

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail:
            self.details.append(detail)
            self.calls += 1
            if self.stop_after and self.calls >= self.stop_after:
                self._stop = True


class _Settings:
    def __init__(self, **flags) -> None:
        self.ai_sweep_keyword_triage = flags.get("keyword_triage", False)
        self.ai_sweep_source_tags = flags.get("source_tags", False)
        self.ai_sweep_perception_extract = flags.get("perception_extract", False)


@pytest.fixture(autouse=True)
def _clean_hold():
    """No test may leak a hold into the next one."""
    yield
    with C._hold_lock:
        C._hold_count = 0
        C._hold_reasons.clear()


# --------------------------------------------------------------------------- #
#  The hold itself.
# --------------------------------------------------------------------------- #
def test_the_hold_is_a_counter_so_overlapping_batches_cannot_release_each_other() -> None:
    """Two user batches can legitimately overlap; the first to finish must not
    release a hold the second still needs."""
    assert C.user_batch_active()["held"] is False
    with C.user_batch_hold("bulk translate"):
        assert C.user_batch_active()["held"] is True
        with C.user_batch_hold("manual sweep"):
            assert sorted(C.user_batch_active()["holders"]) == ["bulk translate", "manual sweep"]
        # inner released, outer still holds
        assert C.user_batch_active()["held"] is True
        assert C.user_batch_active()["holders"] == ["bulk translate"]
    assert C.user_batch_active()["held"] is False


def test_a_raising_batch_never_strands_the_lane_paused() -> None:
    """The hold is released in a `finally`: an aborted stream or a mid-run model
    outage must not leave background AI paused forever."""
    with pytest.raises(RuntimeError):
        with C.user_batch_hold("bulk summarize"):
            raise RuntimeError("the model went away")
    assert C.user_batch_active()["held"] is False


def test_the_hold_is_visible_across_threads() -> None:
    """The coordinator runs on its own thread; a hold taken by a request thread has
    to be seen there, or the pause is decorative."""
    seen: list[bool] = []
    started = threading.Event()

    def _reader():
        started.wait(2)
        seen.append(C.user_batch_active()["held"])

    t = threading.Thread(target=_reader)
    t.start()
    with C.user_batch_hold("bulk translate"):
        started.set()
        t.join(2)
    assert seen == [True]


# --------------------------------------------------------------------------- #
#  The lane.
# --------------------------------------------------------------------------- #
def test_only_enabled_sweeps_run_and_they_alternate(monkeypatch) -> None:
    order: list[str] = []

    def _spec():
        return [
            C.Member("a", "A", "ai_sweep_keyword_triage",
                     lambda ctx, model: order.append("a") or {}),
            C.Member("b", "B", "ai_sweep_source_tags",
                     lambda ctx, model: order.append("b") or {}),
            C.Member("c", "C", "ai_sweep_perception_extract",
                     lambda ctx, model: order.append("c") or {}),
        ]

    monkeypatch.setattr(C, "_member_specs", _spec)
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: "ollama")
    ctx = _Ctx(stop_after=2)
    out = C.run_coordinator(
        ctx, model="m", settings=_Settings(keyword_triage=True, perception_extract=True),
        sleep=lambda s: None,
    )
    assert set(out["members"]) == {"a", "c"}
    assert "b" not in order, "a sweep the operator disabled must never run"
    assert order.count("a") == order.count("c") >= 1, "enabled sweeps must alternate, not starve"


def test_no_enabled_sweep_is_an_honest_no_op_not_a_fake_run(monkeypatch) -> None:
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: "ollama")
    out = C.run_coordinator(_Ctx(), model="m", settings=_Settings(), sleep=lambda s: None)
    assert out["turns"] == 0 and out["members"] == []
    assert "nothing to run" in out["note"]


def test_the_lane_stands_down_while_a_user_batch_holds_the_model(monkeypatch) -> None:
    """THE ruling-13 property: user work preempts background work, and the pause is
    stated in the visible detail rather than looking like a stall."""
    ran: list[str] = []
    monkeypatch.setattr(C, "_member_specs", lambda: [
        C.Member("a", "A", "ai_sweep_keyword_triage", lambda ctx, model: ran.append("a") or {}),
    ])
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: "ollama")
    ctx = _Ctx(stop_after=2)
    with C.user_batch_hold("bulk translate"):
        out = C.run_coordinator(ctx, model="m", settings=_Settings(keyword_triage=True),
                                sleep=lambda s: None)
    assert ran == [], "no sweep may run while a user batch holds the model"
    assert out["paused_turns"] >= 1
    assert any("paused" in d and "bulk translate" in d for d in ctx.details), (
        "the pause must be visible, naming what holds the model"
    )


def test_a_member_that_raises_never_ends_the_lane(monkeypatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(C, "_member_specs", lambda: [
        C.Member("bad", "Bad", "ai_sweep_keyword_triage",
                 lambda ctx, model: (_ for _ in ()).throw(RuntimeError("boom"))),
        C.Member("good", "Good", "ai_sweep_source_tags",
                 lambda ctx, model: ran.append("good") or {}),
    ])
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: "ollama")
    out = C.run_coordinator(
        _Ctx(stop_after=1), model="m",
        settings=_Settings(keyword_triage=True, source_tags=True), sleep=lambda s: None,
    )
    assert ran == ["good"], "a sibling must still advance"
    assert "error" in out["per_member"]["bad"], "the failure is reported, not swallowed"


def test_a_complete_member_is_skipped_but_rechecked_rather_than_spun_on(monkeypatch) -> None:
    """A finished sweep costs nothing but stays ready to pick up newly-collected work."""
    calls: list[int] = []
    monkeypatch.setattr(C, "_member_specs", lambda: [
        C.Member("a", "A", "ai_sweep_keyword_triage",
                 lambda ctx, model: (calls.append(1), {"complete": True})[1]),
    ])
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: "ollama")
    ctx = _Ctx(stop_after=3)
    C.run_coordinator(ctx, model="m", settings=_Settings(keyword_triage=True), sleep=lambda s: None)
    assert any("up to date" in d for d in ctx.details), "a drained lane must idle honestly"
    assert len(calls) < ctx.calls, "a complete member must not be re-run every turn"


def test_ollama_is_serial_and_vllm_may_overlap(monkeypatch) -> None:
    monkeypatch.setattr(C, "_member_specs", lambda: [])
    assert C._turn_workers("ollama") == 1, "Ollama serves one generation at a time"
    assert C._turn_workers("vllm") >= 1


# --------------------------------------------------------------------------- #
#  EVERY entry point checks the SAME hold (the 2026-07-24 lesson).
# --------------------------------------------------------------------------- #
def test_every_background_ai_entry_point_checks_the_hold() -> None:
    """A pause that only stops the coordinator loop is silently incomplete. These are
    the other ways background AI work can start; each must consult user_batch_active."""
    checks = {
        "the langdetect scheduler ride-along": (
            _SRC / "api" / "ai.py", "advance_langdetect_auto_start"),
        "the custom-prompt auto-on-ingest hook": (
            _SRC / "ai_layer" / "auto.py", "run_auto_on_ingest"),
    }
    for what, (path, func) in checks.items():
        src = path.read_text(encoding="utf-8")
        body = src.split(f"def {func}(", 1)[1].split("\ndef ", 1)[0]
        assert "user_batch_active" in body, f"{what} must check the same hold"


def test_a_manual_sweep_run_takes_the_hold_for_its_whole_duration() -> None:
    """Ruling 13 names a manual sweep run as a user batch. Wrapping the WORKER (not
    the endpoint) is what makes the hold last the whole run rather than its start."""
    src = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    for worker in ("_keyword_triage_worker", "_source_tags_worker", "_perception_extract_worker"):
        body = src.split(f"def {worker}(", 1)[1].split("\ndef ", 1)[0]
        assert "user_batch_hold" in body, f"{worker} must hold while it runs"


def test_a_user_bulk_run_takes_the_hold_and_says_so() -> None:
    src = (_SRC / "api" / "llm.py").read_text(encoding="utf-8")
    assert "user_batch_hold(f\"bulk {op}\")" in src, "a bulk run is a user batch"
    assert '"pauses_background_ai": True' in src, (
        "the pause must be announced, not silent (ruling 13's visible notice)"
    )


# --------------------------------------------------------------------------- #
#  The hardware-aware default.
# --------------------------------------------------------------------------- #
def test_an_unreadable_hardware_verdict_defaults_off_and_says_why() -> None:
    """A machine we could not measure must not be volunteered for hours of
    background inference -- and must not have a verdict invented for it either."""
    def _broken():
        raise OSError("nope")

    out = C.coordinator_default_enabled(capability=_broken)
    assert out["default_on"] is False
    assert "not readable" in out["reason"]


def test_the_default_follows_the_same_practicality_predicate() -> None:
    assert C.coordinator_default_enabled(
        capability=lambda: {"practical": True, "reason": "GPU"})["default_on"] is True
    out = C.coordinator_default_enabled(
        capability=lambda: {"practical": False, "reason": "no dedicated GPU"})
    assert out["default_on"] is False and "GPU" in out["reason"]


# --------------------------------------------------------------------------- #
#  the lane's concurrency budget has to reach the calls
# --------------------------------------------------------------------------- #
def _budget_probe(monkeypatch, *, backend: str, budget: int, flags: dict) -> dict:
    """Run one turn and report the kwargs each member was actually called with."""
    seen: dict[str, dict] = {}

    def _mk(key: str, enabled_key: str, per_item: bool) -> "C.Member":
        def _run(ctx, model, **kw):
            seen[key] = dict(kw)
            return {}
        return C.Member(key, key, enabled_key, _run, per_item_concurrency=per_item)

    monkeypatch.setattr(C, "_member_specs", lambda: [
        _mk("triage", "ai_sweep_keyword_triage", False),
        _mk("tags", "ai_sweep_source_tags", False),
        _mk("perception", "ai_sweep_perception_extract", True),
    ])
    monkeypatch.setattr(C, "_resolve_backend_name", lambda: backend)
    monkeypatch.setattr(C, "_turn_workers", lambda _b: budget)
    C.run_coordinator(ctx=_Ctx(stop_after=1), model="m", settings=_Settings(**flags),
                      sleep=lambda _s: None)
    return seen


def test_the_lane_budget_reaches_the_member_that_calls_once_per_item(monkeypatch) -> None:
    """Field report 2026-08-09: "I see my GPU working only 20%".

    Turn-level overlap alone caps real concurrency at the number of enabled sweeps, and
    each member ran its own items SERIALLY because nothing passed max_workers and its
    default is 1 -- so OO_VLLM_CONCURRENCY, whose own docstring invites the operator to
    measure and override it, could not reach the loop that issues the calls."""
    seen = _budget_probe(
        monkeypatch, backend="vllm", budget=8,
        flags={"keyword_triage": True, "source_tags": True, "perception_extract": True},
    )
    # Three due members: the two batched ones spend one sequence each, so the per-item
    # member gets the remaining six and the lane's total matches the budget rather than
    # exceeding it and queueing behind the server's own --max-num-seqs.
    assert seen["perception"] == {"max_workers": 6}


def test_a_member_that_batches_its_items_is_never_handed_workers(monkeypatch) -> None:
    """Triage and source-tags already carry a whole batch in one call, so extra workers
    would be silently ignored -- and a silently-ignored argument is what later reads as
    a bug. They are not given one."""
    seen = _budget_probe(
        monkeypatch, backend="vllm", budget=8,
        flags={"keyword_triage": True, "source_tags": True, "perception_extract": True},
    )
    assert seen["triage"] == {} and seen["tags"] == {}


def test_ollama_stays_serial(monkeypatch) -> None:
    """The negative-space twin. Ollama is serial by this project's default posture, so
    the same wiring must not quietly start issuing concurrent calls to it."""
    seen = _budget_probe(
        monkeypatch, backend="ollama", budget=1,
        flags={"keyword_triage": True, "perception_extract": True},
    )
    assert seen["perception"] == {"max_workers": 1}


def test_the_per_item_member_alone_gets_the_whole_budget(monkeypatch) -> None:
    """With nothing else due there is nothing to reserve for."""
    seen = _budget_probe(
        monkeypatch, backend="vllm", budget=8, flags={"perception_extract": True},
    )
    assert seen["perception"] == {"max_workers": 8}


def test_the_shipped_perception_member_is_the_per_item_one() -> None:
    """The flag is only meaningful if the REAL registry carries it, and only on the
    member whose job actually accepts max_workers."""
    import inspect

    from src.ai_layer.perception_extract_job import run_progressive_perception_extract_job

    by_key = {m.key: m for m in C._member_specs()}
    assert by_key["perception_extract"].per_item_concurrency is True
    assert by_key["keyword_triage"].per_item_concurrency is False
    assert by_key["source_tags"].per_item_concurrency is False
    assert "max_workers" in inspect.signature(
        run_progressive_perception_extract_job
    ).parameters, "the member is marked per-item, so its job must take the argument"
