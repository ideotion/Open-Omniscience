"""The Background-AI COORDINATOR (2026-08-01 field impressions, rulings 12-13).

Before this, each progressive sweep (keyword triage, source tags, perception
extraction) had its OWN toggle button, and langdetect had its own auto-start
setting. Turning several on at once was possible and quietly wrong: Ollama serves
ONE generation at a time by this project's default posture
(:mod:`src.llm.concurrency`), so independent sweeps simply queue behind each
other on the same model with no coordination and no shared view of progress.

So the master switch is a COORDINATOR, not a fan-out (ruling 12a): ONE background
lane that runs the ENABLED members ROUND-ROBIN, one bounded batch each per turn.
Every member already keeps a PERSISTED cursor, so interleaving is free — a member
resumes exactly where its last turn ended, and the coordinator holds no progress
state of its own that could disagree with the member's.

Backend-aware dispatch (ruling 12b): on vLLM, whose whole advantage is continuous
batching, member turns may run CONCURRENTLY up to ``concurrency_for("vllm")``; on
Ollama they run strictly serially. The backend is resolved through
:func:`src.llm.backend.resolve_backend` — never a hardcoded name.

That turn-level overlap is not the whole budget, and treating it as such is what a
field report of a GPU at 20% turned out to be (2026-08-09). Overlapping TURNS caps
real concurrency at the number of enabled sweeps — three — and each member then ran
its own items serially, because nothing passed ``max_workers`` and its default is 1.
So ``concurrency_for`` reached the scheduler and never the loop that issues the
calls. The budget is now SPENT: a member whose calls each carry a whole batch
(triage's 25 keywords, a page of source domains) costs one sequence, and the
per-item member — who/where/when, one call per article — gets the remainder, so the
lane's total in flight matches the same number the server's ``--max-num-seqs`` was
set from. What that number should BE is a measurement, not a guess:
``/api/diagnostics/llm-throughput`` sweeps it on the operator's own machine.

PREEMPTION (ruling 13): interactive one-off calls are never governed by this
toggle and never queue behind it. A user-initiated BATCH (bulk translate/
summarize, a manual sweep run) takes the EXCLUSIVE HOLD below, and the
coordinator stands down for its duration, cursors intact, then resumes on its
own. The 2026-07-24 exclusive-hold lesson is the reason the hold is a dedicated
flag rather than "the coordinator pauses itself": EVERY entry point that can
start background AI work must check the SAME hold, or the one that forgets
silently defeats the guarantee the others provide.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

_LOG = logging.getLogger(__name__)

#: One coordinator turn runs at most this many batches of a member, so no single
#: member can monopolise the lane while others wait.
BATCHES_PER_TURN = 1
#: Pause between turns when every member reports it has nothing left to do — the
#: lane idles cheaply instead of spinning on empty work.
IDLE_SLEEP_S = 30.0
#: Pause between turns while a user batch holds the model.
HELD_SLEEP_S = 2.0


# --------------------------------------------------------------------------- #
#  The exclusive hold: user work preempts background work.
# --------------------------------------------------------------------------- #
# A COUNTER, not a boolean: two user batches can legitimately overlap, and the
# second finishing must not release a hold the first still needs. Released in a
# `finally` by the context manager, so a raising batch cannot strand the lane.
_hold_lock = threading.Lock()
_hold_count = 0
_hold_reasons: list[str] = []


@contextmanager
def user_batch_hold(reason: str) -> Iterator[None]:
    """Claim the model for a user-initiated batch; the coordinator stands down.

    Wrap any batch a USER asked for (bulk summarize/translate, a manual sweep run).
    Interactive single calls do NOT need this — they are short, and making a reader
    wait behind a sweep is the very thing this exists to prevent.
    """
    global _hold_count
    with _hold_lock:
        _hold_count += 1
        _hold_reasons.append(reason)
    try:
        yield
    finally:
        with _hold_lock:
            _hold_count = max(0, _hold_count - 1)
            try:
                _hold_reasons.remove(reason)
            except ValueError:  # pragma: no cover - defensive
                pass


def user_batch_active() -> dict:
    """Is a user batch holding the model right now, and what for?

    EVERY background-AI entry point checks this — the coordinator loop, the
    langdetect ride-along, the custom-prompt auto-on-ingest hook and the manual
    sweep endpoints. A pause that only stops the main loop is honest-sounding and
    incomplete (the 2026-07-24 lesson).
    """
    with _hold_lock:
        return {"held": _hold_count > 0, "holders": list(_hold_reasons)}


# --------------------------------------------------------------------------- #
#  Members.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Member:
    """One coordinated sweep.

    ``run`` performs at most ``BATCHES_PER_TURN`` batches and returns the member's
    own status dict; ``enabled_key`` is the settings flag that includes it.
    ``complete`` is read from the member's OWN report — the coordinator never
    decides for a member that it has finished.
    """

    key: str
    label: str
    enabled_key: str
    run: Callable[..., dict]
    #: Does this member issue ONE model call PER ITEM, so that giving it more workers
    #: puts more sequences in flight? Triage and source-tags do not: each of their calls
    #: already carries a whole batch (25 keywords, a page of domains), so their
    #: concurrency lever would be running several BATCHES at once -- a different change,
    #: in their own batch loops. Only the per-item member can spend the lane's budget,
    #: and marking that here keeps the coordinator from handing workers to a member that
    #: would silently ignore them.
    per_item_concurrency: bool = False


def _member_specs() -> list[Member]:
    """The coordinated members, imported lazily so this module stays importable
    on a core install where the AI extras are absent."""

    def _triage(ctx, model: str) -> dict:
        from src.ai_layer.triage_job import run_progressive_triage_job

        return run_progressive_triage_job(ctx, model=model, max_batches=BATCHES_PER_TURN)

    def _source_tags(ctx, model: str) -> dict:
        from src.ai_layer.source_tags_job import run_progressive_source_tags_job

        return run_progressive_source_tags_job(ctx, model=model, max_batches=BATCHES_PER_TURN)

    def _perception(ctx, model: str, max_workers: int = 1) -> dict:
        from src.ai_layer.perception_extract_job import run_progressive_perception_extract_job

        return run_progressive_perception_extract_job(
            ctx, model=model, max_batches=BATCHES_PER_TURN, max_workers=max_workers
        )

    return [
        Member("keyword_triage", "Keyword triage", "ai_sweep_keyword_triage", _triage),
        Member("source_tags", "Source tags", "ai_sweep_source_tags", _source_tags),
        Member(
            "perception_extract",
            "When / where / who extraction",
            "ai_sweep_perception_extract",
            _perception,
            per_item_concurrency=True,
        ),
    ]


def enabled_members(settings: Any | None = None) -> list[Member]:
    """The members the operator has switched on. A member the operator disabled is
    simply not run — the coordinator never enables one on its own."""
    if settings is None:
        try:
            from src.config.app_settings import load_settings

            settings = load_settings()
        except Exception:  # noqa: BLE001 - settings are advisory; degrade to none
            return []
    return [m for m in _member_specs() if bool(getattr(settings, m.enabled_key, False))]


# --------------------------------------------------------------------------- #
#  The lane.
# --------------------------------------------------------------------------- #
def _resolve_backend_name() -> str:
    try:
        from src.llm.backend import resolve_backend

        return str((resolve_backend() or {}).get("backend") or "ollama")
    except Exception:  # noqa: BLE001 - an unknown backend is treated as the serial one
        return "ollama"


def _turn_workers(backend: str) -> int:
    """How many member turns may overlap. vLLM's continuous batching makes real
    concurrency worthwhile; Ollama is serial by this project's default posture."""
    try:
        from src.llm.concurrency import concurrency_for

        return max(1, int(concurrency_for(backend)))
    except Exception:  # noqa: BLE001
        return 1


def release_after_lane(backend: str) -> dict:
    """Give the GPU back now that the lane is finished.

    FIELD REPORT 2026-08-13, verbatim: *"how come the model doesn't automatically
    unload from vRAM when the AI related jobs are finished or stopped? ... we both want
    to avoid using too much SSD by loading and unloading before every request, but the
    unloading should be automatic when we stop the AI backend and/or when AI operations
    are stopped."*

    Both halves of that were true. Stopping a BACKEND already released (``/vllm/stop``
    stops the server, ``/ollama/stop`` calls ``release_vram``); stopping the WORK
    released nothing. The lane simply returned, and what it left behind differed by
    backend in a way an operator has no reason to expect: Ollama's own default drops
    residency after a few idle minutes, while vLLM holds the card for the lifetime of
    its server -- so a finished sweep kept several GB indefinitely.

    THE BOUNDARY IS THE POINT. This runs when the lane ENDS -- finished, cancelled, or
    crashed -- and never between turns or around a request, because loading a model per
    request is the thrash the maintainer explicitly does not want. A lane that has gone
    idle-but-ready also keeps the card: for vLLM a release is a server stop, and
    restarting one costs 60-90 seconds, so releasing on a transient idle would trade a
    memory saving for a stall on the next article collected.

    ``OO_LLM_AURELEASE`` is not the knob -- ``OO_LLM_AUTORELEASE=0`` is -- and
    ``conftest`` sets it session-wide for the same reason it sets ``OO_LLM_AUTOSTART``:
    a production path that ACTS must not act on a developer's own machine merely
    because a test drove the lane.
    """
    if os.getenv("OO_LLM_AUTORELEASE", "1").strip().lower() in ("0", "false", "no"):
        return {"released": False, "reason": "OO_LLM_AUTORELEASE=0"}
    # A user's own batch owns the model. Releasing under it would make their translate
    # reload from disk mid-run -- the exact cost this feature exists to avoid, paid by
    # the one person actually waiting.
    hold = user_batch_active()
    if hold.get("held"):
        return {"released": False, "reason": "a user batch is holding the model"}
    try:
        from src.llm.arbitration import release_backend

        return release_backend(backend)
    except Exception as exc:  # noqa: BLE001 - a release must never fail the run
        _LOG.warning("coordinator could not release %s", backend, exc_info=True)
        return {"released": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def run_coordinator(
    ctx,
    *,
    model: str,
    max_turns: int | None = None,
    settings=None,
    sleep=time.sleep,
) -> dict:
    """``BackgroundJob`` worker: run the enabled sweeps round-robin until cancelled.

    Each turn gives every enabled member one bounded batch. A member that reports
    ``complete`` is skipped on later turns (its cursor says there is nothing left);
    when EVERY member is complete the lane idles rather than spinning, so a finished
    sweep costs nothing but stays ready to pick up newly-collected work.

    ``max_turns`` bounds one call for tests and for a deliberately-bounded run.
    """
    backend = _resolve_backend_name()
    workers = _turn_workers(backend)
    members = enabled_members(settings)
    turns = 0
    per_member: dict[str, dict] = {}
    paused_turns = 0
    if not members:
        return {
            "backend": backend,
            "members": [],
            "turns": 0,
            "note": "No sweeps are enabled — the coordinator has nothing to run.",
        }

    done: set[str] = set()
    released: dict = {"released": False, "reason": "the lane did not reach its end"}
    try:
        while not ctx.stopping:
            if max_turns is not None and turns >= max_turns:
                    break
            hold = user_batch_active()
            if hold["held"]:
                # A user's own batch owns the model: stand down, keep every cursor,
                # and say so in the visible detail rather than looking stalled.
                paused_turns += 1
                ctx.set_progress(
                    done=turns,
                    detail=f"paused — {', '.join(hold['holders']) or 'a user batch'} is running",
                )
                sleep(HELD_SLEEP_S)
                continue
            due = [m for m in members if m.key not in done]
            if not due:
                ctx.set_progress(done=turns, detail="all enabled sweeps are up to date")
                sleep(IDLE_SLEEP_S)
                done.clear()          # re-check later: new articles/keywords may have arrived
                continue

            turns += 1

            # THE LANE'S BUDGET, SPENT RATHER THAN LEFT ON THE TABLE (field report
            # 2026-08-09: "I see my GPU working only 20%"). Turn-level overlap alone caps
            # real concurrency at the number of enabled sweeps -- three -- and each member
            # ran its own items serially, because nothing passed max_workers and its default
            # is 1. So OO_VLLM_CONCURRENCY, whose own docstring invites the operator to
            # measure and override it, could not reach the loop that issues the calls.
            #
            # The budget is `workers` sequences in flight, which is also what the server was
            # started with (--max-num-seqs comes from the same concurrency_for). A member
            # that batches its items spends exactly one; the per-item member gets whatever
            # remains, so the lane's total matches the budget instead of exceeding it and
            # queueing.
            batched = sum(1 for m in due if not m.per_item_concurrency)
            per_item_workers = max(1, workers - batched)

            # `_budget` is bound at definition rather than closed over: this function is
            # handed to a thread pool, and the enclosing name is rebound every turn.
            def _one(m: Member, _budget: int = per_item_workers) -> tuple[str, dict]:
                try:
                    kw = {"max_workers": _budget} if m.per_item_concurrency else {}
                    out = m.run(ctx, model=model, **kw) or {}
                except Exception as exc:  # noqa: BLE001 - one member must never end the lane
                    _LOG.warning("coordinator member %s failed", m.key, exc_info=True)
                    return m.key, {"error": f"{type(exc).__name__}: {exc}"[:200]}
                return m.key, out

            if workers > 1 and len(due) > 1:
                from src.llm.concurrency import run_concurrent

                slots = run_concurrent(due, _one, max_workers=min(workers, len(due)))
                # run_concurrent isolates per item: a raising slot carries ok=False and
                # must not be read as a result (its member simply did not advance).
                results = [s.value for s in slots if s.ok and s.value]
            else:
                results = [_one(m) for m in due]

            for key, out in results:
                per_member[key] = out
                if out.get("complete"):
                    done.add(key)
            ctx.set_progress(done=turns, detail=f"turn {turns} — {len(due)} sweep(s) advanced")
    finally:
        # IN A `finally`, so the three ways a lane ends all give the card back: it
        # finished its members, the operator cancelled it, or a member raised past the
        # per-member guard. A release that only ran on the clean path would be missing
        # from the two cases where an operator is most likely to be watching the GPU.
        released = release_after_lane(backend)

    return {
        "backend": backend,
        "concurrent_turns": workers,
        "members": [m.key for m in members],
        "turns": turns,
        "paused_turns": paused_turns,
        "per_member": per_member,
        # What was actually given back, named rather than assumed: "released" means a
        # dropped model residency on Ollama and a stopped server on vLLM, and an
        # operator reading this needs to know which.
        "gpu_released": released,
        "method": (
            "One background lane runs the ENABLED sweeps round-robin, one bounded batch "
            "each per turn, resuming from each sweep's own persisted cursor. A "
            "user-initiated batch takes an exclusive hold and the lane stands down for "
            "its duration, then resumes. Counts only — no score."
        ),
    }


def coordinator_default_enabled(capability=None) -> dict:
    """Should the master toggle default ON for this machine?

    Consults the SAME practicality predicate the langdetect ride-along already uses
    (:func:`src.llm.backend.inference_capability`; injectable for tests and for a
    core install where the backend module's own imports are absent), so an
    impractical machine is not
    quietly signed up for hours of saturated cores — and the override still reveals
    it, because this is a default, never a block. An unreadable verdict defaults OFF
    and says why: a machine we could not measure must not be volunteered.
    """
    probe = capability
    try:
        if probe is None:
            from src.llm.backend import inference_capability

            probe = inference_capability
        cap = probe() or {}
    except Exception as exc:  # noqa: BLE001
        return {"default_on": False, "reason": f"hardware not readable ({type(exc).__name__})"}
    practical = bool(cap.get("practical"))
    return {
        "default_on": practical,
        "reason": cap.get("reason") or ("practical" if practical else "not practical"),
        "overridden": bool(cap.get("overridden")),
    }


__all__ = [
    "BATCHES_PER_TURN",
    "Member",
    "coordinator_default_enabled",
    "enabled_members",
    "run_coordinator",
    "user_batch_active",
    "user_batch_hold",
]
