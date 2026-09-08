"""
Layer B as a resumable background job (design record §14).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Narration used to run INLINE inside ``POST /api/bulletin/generate``.
That is fine for a bounded story cap and wrong for a long run: a request that
narrates dozens of stories against a local model is a multi-minute synchronous
handler, which is the whole-server-freeze family this codebase has already paid for
three times (restore preview, ``/api/articles``, the unlock path). A plain ``def``
handler still holds a threadpool token for its whole duration, so the freeze does
not go away by not being ``async``.

THE FOUR PROPERTIES §14 ASKS FOR, and what each one costs if it is missing:

* **A persisted cursor.** A multi-hour run must survive a restart. The cursor and
  the work already banked live in a small state file beside the editions, and each
  finished unit is written back into the edition record itself — so a killed run
  loses at most the unit in flight, never the hours behind it.
* **Task-manager visible.** It is a registered ``BackgroundJob``, so ``/api/jobs``
  enumerates it with no shadow state and the operator can watch and stop it.
* **Resumable, and the SAFE reading is the default.** ``start()`` CONTINUES a
  compatible paused run; discarding a day of work has to be asked for
  (``restart=True``). That is the recorded 24-hour-loss lesson: a default of "start
  over" is indistinguishable from resume at every layer above it.
* **Honest about outages rather than aborting to ``done``.** A transient model
  failure is retried with exponential backoff; only after
  ``_MAX_CONSECUTIVE_FAILURES`` in a row does the run give up, and it gives up by
  RAISING, so the job's state genuinely becomes ``error``. A run that stopped
  because the model went away must never read as a run that finished.

TWO THINGS THAT ARE DELIBERATELY REFUSALS RATHER THAN GUESSES:

* Resuming against a DIFFERENT edition than the paused one. Continuing would
  misreport what was narrated; starting over would discard it. The refusal names
  the paused edition, the cursor and the way out.
* Resuming when the edition's story list has CHANGED under the cursor. The cursor
  counts units in the record's own order, so a re-clustered edition would attach
  paragraphs to the wrong stories — a count-to-identity mapping is exactly the
  shape the recorded lesson says to check before trusting a positional resume.

NOT A WRITER in the database sense (``is_writer=False``): the only writes are the
edition JSON and this module's own cursor file. It reads the corpus for each
story's evidence, which is why it takes a session factory rather than a session —
a session held across hours of model calls is the autoflush/gate hazard the ledger
already records.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.jobs import progress_state as _progress_state

_LOG = logging.getLogger("bulletin.narration_job")

NARRATION_JOB_KIND = "bulletin-narration"
NARRATION_STATE_SCHEMA = "oo-bulletin-narration-progress-1"

_PROGRESS_FILENAME = "narration_progress_state.json"

#: How many consecutive model outages end the run. Same shape and the same reason
#: as the triage/perception sweeps: a hiccup is not a reason to stop a multi-hour
#: run, and ten in a row is not a hiccup.
_MAX_CONSECUTIVE_FAILURES = int(os.getenv("OO_BULLETIN_NARRATION_MAX_FAILURES", "10"))
_BACKOFF_BASE_S = float(os.getenv("OO_BULLETIN_NARRATION_BACKOFF_BASE_S", "5"))
_BACKOFF_CAP_S = float(os.getenv("OO_BULLETIN_NARRATION_BACKOFF_CAP_S", "60"))

#: The unit key for the introduction (D2). It is the LAST unit, because it
#: describes the document and the document is not finished until the stories are.
_INTRO_UNIT = "introduction"


def _sleep_interruptible(seconds: float, ctx, *, step: float = 0.5) -> None:
    """Sleep up to ``seconds``, checking ``ctx.stopping`` every ``step``.

    A cancel fired during a backoff wait is honoured promptly instead of blocking
    for the full delay — the operator pressed Stop, not Stop-in-a-minute.
    """
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        if ctx.stopping:
            return
        time.sleep(min(step, max(0.0, end - time.monotonic())))


def _state_path() -> Path:
    from src.bulletin.store import editions_dir

    d = editions_dir().parent
    d.mkdir(parents=True, exist_ok=True)
    return d / _PROGRESS_FILENAME


def load_progress_state(state_path: Path | None = None) -> dict:
    """The persisted cursor, or ``{}``.

    A missing or unreadable state file means "no run is paused", never an error: a
    corrupt cursor must not make the feature unusable, and the worst it costs is
    starting a run again.

    The generic read/write logic lives in ``src.jobs.progress_state``, shared with
    the other progressive job modules; only this module's default state PATH is
    module-specific.
    """
    return _progress_state.load_progress_state(state_path or _state_path())


def _save_progress_state(state: dict, path: Path) -> None:
    """Atomic write, so a crash mid-save never leaves a cursor that parses --
    see ``src.jobs.progress_state`` for the shared implementation."""
    _progress_state.save_progress_state(state, path)


def story_digest(stories: list[dict]) -> str:
    """A digest over the ORDERED story identities.

    The cursor counts units in the record's own order, so this is what makes a
    positional resume safe: if the stories were re-clustered under a paused run,
    unit 4 is no longer the story unit 4 was, and attaching paragraph 4 to it would
    file a model's sentences under an unrelated cluster. Identity only — the
    narration written back into each story is deliberately NOT part of it, or the
    job would invalidate its own cursor on its first write.
    """
    payload = [",".join(str(int(i)) for i in (s.get("article_ids") or [])) for s in stories]
    return hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()[:16]


def _unit_keys(stories: list[dict], *, introduction: bool) -> list[str]:
    keys = [",".join(str(int(i)) for i in (s.get("article_ids") or [])) for s in stories]
    if introduction:
        keys.append(_INTRO_UNIT)
    return keys


class NarrationScopeMismatch(RuntimeError):
    """A paused run exists and it is not the one being asked for.

    Its own class rather than a bare ``RuntimeError`` so the endpoint can answer
    409 with the cursor, the paused edition and the way out, instead of a 500 that
    reads like a crash.
    """

    def __init__(self, message: str, *, state: dict) -> None:
        super().__init__(message)
        self.state = state


def _fresh_state(filename: str, digest: str, params: dict, total: int) -> dict:
    return {
        "schema": NARRATION_STATE_SCHEMA,
        "filename": filename,
        "story_digest": digest,
        "cursor": 0,
        "total_units": total,
        # THE MODE IS PERSISTED WITH THE CURSOR. A resumable job with more than a
        # cursor — a target language, a model, a budget — needs its mode explicitly
        # re-supplied, or "just call start() again" silently resumes under whatever
        # the defaults happen to be. That is a recorded data-safety lesson from the
        # quarantine job, and here it would mean half a document in one language.
        "params": dict(params),
        "totals": {
            "units_done": 0,
            "narrated": 0,
            "fallback": 0,
            "sentences_kept": 0,
            "sentences_dropped": 0,
        },
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def run_bulletin_narration_job(
    ctx,
    *,
    filename: str,
    model: str | None = None,
    backend: str | None = None,
    language: str | None = None,
    story_budget_chars: int | None = None,
    max_stories: int | None = None,
    introduction: bool = True,
    restart: bool = False,
    max_units: int | None = None,
    session_factory=None,
    client=None,
    state_path: Path | None = None,
    gate: dict | None = None,
) -> dict:
    """``BackgroundJob`` worker: narrate one persisted edition, resumably.

    Each unit is one story, and the last unit is the introduction (§20 Q2, ruled
    narrated 2026-09-07). After every unit the paragraph is written back into the
    edition record and the cursor is saved, so the record on disk is always a
    consistent, readable document — a half-narrated edition is a real edition with
    fewer paragraphs, never a broken one.

    Returns a summary. Raises ``NarrationScopeMismatch`` when a paused run is for a
    different edition, and ``RuntimeError`` when the model has been unreachable for
    ``_MAX_CONSECUTIVE_FAILURES`` units in a row — raising rather than returning,
    so the job's own state becomes ``error`` and a dead backend can never present
    as a finished run.
    """
    from src.bulletin.edition import attach_narration
    from src.bulletin.introduction import deterministic_block, narrate_introduction
    from src.bulletin.narration import (
        DEFAULT_OPTIONS,
        DEFAULT_STORY_BUDGET_CHARS,
        NARRATION_PROMPT_VERSION,
        deterministic_paragraph,
        narrate_story,
    )
    from src.bulletin.store import read_edition, update_edition

    if gate is None:
        from src.bulletin.gate import bulletin_available

        gate = bulletin_available()

    # REFUSE ONCE, not per story. A gate that clears nothing means every unit would
    # be refused, and walking the whole edition to establish that costs a model
    # probe per story to learn the same fact again. The cursor is untouched, so the
    # moment the hardware verdict changes the very next call resumes this run.
    if not gate.get("narration_available"):
        reason = str(gate.get("narration_reason") or "this machine cannot narrate")
        ctx.set_progress(detail=reason)
        return {
            "state": "refused",
            "refused": True,
            "filename": filename,
            "reason": reason,
            "narration_caveat": gate.get("narration_caveat"),
        }

    edition = read_edition(filename)
    stories = list((edition.get("stories") or {}).get("stories") or [])
    if max_stories is not None:
        stories = stories[: int(max_stories)]
    digest = story_digest(stories)
    unit_keys = _unit_keys(stories, introduction=bool(introduction))
    total_units = len(unit_keys)

    path_state = state_path or _state_path()
    saved = {} if restart else load_progress_state(path_state)

    params: dict[str, Any] = {
        "model": model,
        "backend": backend,
        "language": language,
        "story_budget_chars": story_budget_chars,
        "max_stories": max_stories,
        "introduction": bool(introduction),
    }

    if saved and not saved.get("completed_at"):
        if saved.get("filename") != filename:
            raise NarrationScopeMismatch(
                f"a narration run is paused on {saved.get('filename')!r} at unit "
                f"{saved.get('cursor')} of {saved.get('total_units')}. Resume that one, "
                "or pass restart=true to discard it and narrate this edition instead — "
                "which throws away the paused run's work.",
                state=dict(saved),
            )
        if saved.get("story_digest") != digest:
            raise NarrationScopeMismatch(
                "the paused run's stories are not this edition's stories any more "
                f"(cursor {saved.get('cursor')} of {saved.get('total_units')}). The "
                "cursor counts units in the record's own order, so continuing would "
                "attach paragraphs to the wrong clusters. Pass restart=true to narrate "
                "this edition from the beginning.",
                state=dict(saved),
            )
        state = dict(saved)
        # The MODE is re-applied from the paused run, and an explicitly-supplied
        # value still wins — a resume that silently changed the target language
        # would leave one document written in two.
        stored = dict(state.get("params") or {})
        for key, value in params.items():
            if value is None or (key == "introduction" and stored.get(key) is not None):
                params[key] = stored.get(key, value)
        state["params"] = dict(params)
        state["total_units"] = total_units
        resumed_from = int(state.get("cursor") or 0)
    else:
        state = _fresh_state(filename, digest, params, total_units)
        resumed_from = 0

    cursor = int(state.get("cursor") or 0)
    totals = dict(state.get("totals") or {})
    for key in ("units_done", "narrated", "fallback", "sentences_kept", "sentences_dropped"):
        totals.setdefault(key, 0)

    budget = int(params.get("story_budget_chars") or DEFAULT_STORY_BUDGET_CHARS)
    # RESOLVED, not the argument: on a resume this is the paused run's language
    # unless one was named explicitly. Its own name so the two cannot be
    # confused further down, where using the argument would silently ignore
    # the mode the cursor carries.
    run_language: str | None = params.get("language") or None

    if session_factory is None:
        from src.database.session import session_scope

        session_factory = session_scope

    # The model id and its backend travel TOGETHER from here on. They are only
    # meaningful beside each other — a tag resolved against one backend and served
    # by another is the recorded "is not installed. Run: ollama pull <hf repo id>"
    # defect — so both are bound once, as plain strings, and neither is looked up
    # a second time further down.
    backend_name: str = str(params.get("backend") or "injected")
    model_name: str
    if client is None:
        try:
            from src.api.llm import active_model
            from src.llm.backend import get_client_with_name

            resolved_backend, client = get_client_with_name(
                backend=str(params["backend"]) if params.get("backend") else None
            )
            backend_name = str(resolved_backend)
            model_name = str(params.get("model") or active_model())
        except Exception as exc:  # noqa: BLE001 - no backend at all is a refusal, not a crash
            reason = f"no local model is available: {type(exc).__name__}: {exc}"
            ctx.set_progress(detail=reason)
            return {
                "state": "refused",
                "refused": True,
                "filename": filename,
                "reason": reason,
            }
    else:
        model_name = str(params.get("model") or "injected")

    ctx.set_progress(done=cursor, total=total_units, detail="starting…")

    paused_reason: str | None = None
    complete = False
    units_this_call = 0
    consecutive_failures = 0

    def _persist(block: dict, unit_key: str) -> None:
        """Write one finished unit into the edition record, atomically."""

        def _mutate(record: dict) -> None:
            if unit_key == _INTRO_UNIT:
                record["introduction"] = block
                return
            nar = record.setdefault("narration", {})
            nar.setdefault("layer", "B")
            paragraphs = nar.setdefault("paragraphs", [])
            key = tuple(block.get("article_ids") or [])
            # Replace rather than append: a retried unit must not leave two
            # paragraphs for one story, which would double-count `stories_narrated`
            # and hand the attach join an ambiguous key.
            for i, existing in enumerate(paragraphs):
                if tuple(existing.get("article_ids") or []) == key:
                    paragraphs[i] = block
                    break
            else:
                paragraphs.append(block)
            nar["stories_narrated"] = sum(1 for p in paragraphs if p.get("narrated"))
            nar["stories_shown"] = len(record.get("stories", {}).get("stories") or [])
            nar["stories_available"] = nar["stories_shown"]
            nar["model"] = model_name
            nar["backend"] = backend_name
            nar["prompt_version"] = NARRATION_PROMPT_VERSION
            nar["options"] = dict(DEFAULT_OPTIONS)
            nar["method"] = (
                "one constrained call per story over the opening text of that story's "
                "articles, run as a resumable background job; every sentence checked "
                "against that same text before it is kept, and a story whose sentences "
                "all fail falls back to a deterministic template"
            )
            nar["caveat"] = (
                "AI-derived — unreliable. These sentences were written by a local model "
                "and kept only because every figure and name in them appears in the "
                "articles it was shown. That check catches invented facts; it does NOT "
                "catch real facts arranged into a false claim. Remove this layer and the "
                "document is still complete."
            )
            # PARTIAL BY CONSTRUCTION while the run is in flight, and it says so.
            # Without this a killed run's record reads as an edition whose model
            # narrated four of nine stories and stopped having nothing to say.
            nar["run"] = {
                "job": NARRATION_JOB_KIND,
                "units_done": totals["units_done"],
                "units_total": total_units,
                "complete": totals["units_done"] >= total_units,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            attach_narration(record)

        update_edition(filename, _mutate)

    while True:
        if ctx.stopping:
            paused_reason = "cancelled — progress is saved; start it again to resume"
            break
        if cursor >= total_units:
            complete = True
            break
        if max_units is not None and units_this_call >= int(max_units):
            break  # the per-call budget is spent — a clean bounded end, not a pause

        unit_key = unit_keys[cursor]
        try:
            if unit_key == _INTRO_UNIT:
                block = narrate_introduction(
                    edition,
                    client=client,
                    model=model_name,
                    backend=backend_name,
                    language=run_language,
                )
            else:
                story = stories[cursor]
                with session_factory() as session:
                    from src.bulletin.stories import story_evidence

                    ev = story_evidence(
                        session, list(story.get("article_ids") or []), budget_chars=budget
                    )
                block = narrate_story(
                    story,
                    ev,
                    client=client,
                    model=model_name,
                    backend=backend_name,
                    language=run_language,
                )
        except Exception as exc:  # noqa: BLE001 - an evidence read can fail too
            _LOG.warning("bulletin: narration unit %s failed", cursor, exc_info=True)
            block = {
                "article_ids": list((stories[cursor].get("article_ids") or []))
                if unit_key != _INTRO_UNIT
                else [],
                "grounded_in_article_ids": [],
                "text": deterministic_paragraph(stories[cursor])
                if unit_key != _INTRO_UNIT
                else deterministic_block(edition, str(exc))["text"],
                "narrated": False,
                "fallback_reason": f"evidence unavailable: {type(exc).__name__}: {exc}",
                "sentences": [],
            }

        # AN OUTAGE IS NOT A UNIT. ``narrate_story`` never raises — it degrades to
        # the template with the reason — so a dead backend would otherwise write a
        # deterministic paragraph for every story and finish `complete`, which is
        # exactly the abort-to-done defect §14 names. The cursor is NOT advanced on
        # a model failure; the same unit is retried after a backoff.
        if _is_outage(block):
            consecutive_failures += 1
            state.update({"cursor": cursor, "totals": totals,
                          "updated_at": datetime.now(UTC).isoformat(timespec="seconds")})
            _save_progress_state(state, path_state)
            why, fix = _outage_words(block)
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                err = (
                    f"stopped after {consecutive_failures} consecutive local-model "
                    f"failures at unit {cursor + 1} of {total_units} "
                    f"({totals['narrated']} narrated so far): "
                    f"{block.get('fallback_reason') or ''}"
                )
                _LOG.warning("bulletin narration gave up: %s", err)
                # RAISE, never return: the outer BackgroundJob must reach
                # state=="error" rather than a benign-looking "done".
                raise RuntimeError(err)
            backoff = min(
                _BACKOFF_BASE_S * (2 ** (consecutive_failures - 1)), _BACKOFF_CAP_S
            )
            ctx.set_progress(
                done=cursor,
                total=total_units,
                detail=(
                    f"{why} — retrying in {backoff:.0f}s in case it comes back "
                    f"({consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})"
                    + (f" · {fix}" if fix else "")
                ),
            )
            _sleep_interruptible(backoff, ctx)
            continue  # the SAME unit; the cursor was never advanced

        consecutive_failures = 0
        totals["units_done"] += 1
        if block.get("narrated"):
            totals["narrated"] += 1
        else:
            totals["fallback"] += 1
        totals["sentences_kept"] += int(block.get("sentences_kept") or 0)
        totals["sentences_dropped"] += int(block.get("sentences_dropped") or 0)

        _persist(block, unit_key)
        cursor += 1
        units_this_call += 1
        state.update(
            {
                "cursor": cursor,
                "totals": totals,
                "total_units": total_units,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        _save_progress_state(state, path_state)
        ctx.set_progress(
            done=cursor,
            total=total_units,
            detail=f"unit {cursor} of {total_units} · {totals['narrated']} narrated",
        )

    if complete:
        state["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    state.update({"cursor": cursor, "totals": totals, "total_units": total_units})
    _save_progress_state(state, path_state)

    summary = {
        "state": "done" if complete else "paused",
        "filename": filename,
        "complete": complete,
        "cursor": cursor,
        "total_units": total_units,
        "resumed_from": resumed_from,
        "units_this_call": units_this_call,
        "totals": totals,
        "model": model_name,
        "backend": backend_name,
    }
    if paused_reason:
        summary["paused_reason"] = paused_reason
    return summary


#: Fallback reasons that mean THE BACKEND, as opposed to this story having no
#: usable text. Only the first kind is worth retrying: re-sending an identical
#: request to a working backend that had nothing to read produces the same answer,
#: so retrying it is a delay before the same result rather than resilience.
_OUTAGE_MARKERS = ("the model call failed", "the model returned nothing")


def _is_outage(block: dict) -> bool:
    if block.get("narrated"):
        return False
    reason = str(block.get("fallback_reason") or "")
    return any(marker in reason for marker in _OUTAGE_MARKERS)


def _outage_words(block: dict) -> tuple[str, str | None]:
    """The retry line's words — the resolver's, never a generic phrase over them.

    The recorded defect is a loop that holds the real exception and prints "local
    model hiccup" instead. Where the resolver has nothing to add, the block's own
    reason is what the operator reads.
    """
    fallback = str(block.get("fallback_reason") or "the local model did not answer")
    try:
        from src.llm.activation import recover_backend
        from src.llm.backend import outage_detail, outage_reason

        why = outage_reason()
        fix = recover_backend(why)
        return outage_detail(why, fallback, recovery=fix), (
            str(fix.get("detail")) if isinstance(fix, dict) and fix.get("detail") else None
        )
    except Exception:  # noqa: BLE001 - enrichment is a nicety; the reason is the fact
        return fallback, None


def last_narration_run() -> dict:
    """What the newest narration run is doing, or did — for the panel and the bundle.

    Reads the persisted cursor, which is the only durable account of a run: the
    ``BackgroundJob``'s own status is process-local and a restart erases it, which
    is precisely the shape §14 asks this job not to have.
    """
    state = load_progress_state()
    if not state:
        return {
            "schema": NARRATION_STATE_SCHEMA,
            "available": False,
            "note": "no narration run has been started on this machine yet",
        }
    cursor = int(state.get("cursor") or 0)
    total = int(state.get("total_units") or 0)
    return {
        "schema": NARRATION_STATE_SCHEMA,
        "available": True,
        "filename": state.get("filename"),
        "cursor": cursor,
        "total_units": total,
        "complete": bool(state.get("completed_at")),
        "completed_at": state.get("completed_at"),
        "started_at": state.get("started_at"),
        "updated_at": state.get("updated_at"),
        "totals": state.get("totals") or {},
        "params": state.get("params") or {},
        # An in-flight or abandoned run is NOT a finished one, and the absence of a
        # completion stamp is the evidence. Never write one to mark a run handled.
        "state": "done" if state.get("completed_at") else ("paused" if cursor else "started"),
    }


# The BackgroundJob itself is registered in ``src/api/bulletin.py``, beside the
# route that starts it — the house convention, and one registration site rather
# than two that can drift about whether a run is cancellable.


__all__ = [
    "NARRATION_JOB_KIND",
    "NarrationScopeMismatch",
    "last_narration_run",
    "load_progress_state",
    "run_bulletin_narration_job",
    "story_digest",
]
