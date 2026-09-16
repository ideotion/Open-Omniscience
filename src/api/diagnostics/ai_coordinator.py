"""
The AI coordinator job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 6303-6459 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.jobs.background import BackgroundJob, register_job

from ._base import router


# --------------------------------------------------------------------------- #
#  THE BACKGROUND-AI COORDINATOR (2026-08-01 field impressions, rulings 12-13)
#
#  One master switch instead of three independent sweep toggles that would
#  silently queue behind each other on a backend that serves one generation at a
#  time. The lane runs the ENABLED sweeps round-robin, each resuming from its own
#  persisted cursor, and stands down while a user-initiated batch holds the model.
# --------------------------------------------------------------------------- #
def _ai_coordinator_worker(ctx, **kwargs) -> dict:
    from src.ai_layer.coordinator import run_coordinator

    return run_coordinator(ctx, **kwargs)


_AI_COORDINATOR_JOB = register_job(
    BackgroundJob(
        "ai-coordinator", "Background AI (coordinated sweeps)", _ai_coordinator_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/ai-coordinator/run")
def ai_coordinator_run() -> JSONResponse:
    """Start the coordinated background-AI lane (the master toggle's ON action).

    Runs every sweep the operator has ENABLED in Settings, round-robin, one bounded
    batch each per turn, through whichever backend ``resolve_backend`` selects. Each
    sweep keeps its OWN persisted cursor, so this never re-does finished work and a
    cancel loses nothing. Loopback inference is airplane-safe, so this runs offline.

    Refuses (409) when no sweep is enabled -- an empty lane that reported "running"
    would be a fabricated capability. Re-calling while it runs returns the live
    status with ``started:false`` rather than erroring.

    STARTS THE BACKEND FIRST (2026-08-04 field report: "Starting the local AI
    produces 'local model hiccup'"). Nothing in this chain ever started a backend:
    the lane came up, probed, found no server, and spent its whole retry budget on a
    condition retrying cannot change. Now it asks ``activation`` to bring one up.

    The refusal is deliberately narrow, because the recorded lesson is that a health
    probe must NOT decide a retry -- a model reload, a restart and a busy server all
    answer alike, so ending a sweep on a probe would destroy the transient-retry
    guarantee. That lesson is about ENDING a run. Here we are STARTING one, and the
    two conditions are different in kind:

      * a STRUCTURAL blocker (no backend installed; weights not downloaded) is a
        filesystem fact, it will not change while the lane retries, and it is
        actionable -- so 409 with the reason, in words;
      * a backend that is starting (vLLM loading its engine for tens of seconds)
        gets the lane started anyway, which is exactly what the backoff is for.
    """
    from src.ai_layer.coordinator import enabled_members
    from src.api.llm import active_model
    from src.llm.activation import ensure_running

    members = enabled_members()
    if not members:
        raise HTTPException(
            status_code=409,
            detail="No background sweeps are enabled — switch at least one on in Settings → AI.",
        )
    act = ensure_running()
    if not (act.get("ready") or act.get("started")):
        detail = str(
            act.get("detail")
            or "No local AI backend could be started, so there is nothing to sweep with."
        )
        # The server's OWN first words, inline, when a vLLM start died on launch. A path
        # to a log file is an instruction to go and find the answer; the answer itself
        # is what turns "vLLM doesn't seem to start" into a fixable fact. Kept a STRING
        # rather than a structured field because this is a `detail=` a button renders,
        # and the frontend's error helper renders a dict as "[object Object]".
        head = str(act.get("server_log_head") or "").strip()
        if head:
            detail = f"{detail}\n\n--- the server's own first output ---\n{head}"
        raise HTTPException(status_code=409, detail=detail)

    # A backend that is UP with NOTHING TO SERVE fails every batch, and it is a likely
    # state right after a fresh install: the model store moved into the app's own
    # folder (2026-08-04 ask), so a reinstall can leave a perfectly healthy daemon
    # pointed at an empty directory. ``outage_reason()`` has nothing to say about it --
    # the backend IS reachable -- which is exactly how this reached the operator as
    # "local model hiccup", ten times over.
    #
    # Only when the probe SUCCEEDS and comes back empty. A probe that raises is not a
    # "no": refusing on an unreadable answer would be its own fabrication, and the
    # retry budget is the right instrument for a momentarily unhappy server.
    if act.get("ready"):
        try:
            from src.llm.backend import get_client

            installed = list(get_client().list_installed() or [])
        except Exception:  # noqa: BLE001 - an unreadable probe never refuses
            installed = None
        if installed is not None and not installed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{act.get('backend')} is running but no model is downloaded yet, so "
                    "there is nothing to sweep with. Download one in Settings → AI "
                    "(retrying cannot make a model appear)."
                ),
            )
    try:
        # The backend `ensure_running` ACTUALLY brought up -- not a second, independent
        # resolution. Those two can differ (a fallback, or vLLM dying between the calls),
        # and when they do the sweep is handed the other backend's identifier: the field
        # saw an HF repo id sent to Ollama, which then correctly said it had no such
        # model while the right one was installed all along.
        st = _AI_COORDINATOR_JOB.start(model=active_model(act.get("backend")))
        st["started"] = True
    except RuntimeError:
        st = _AI_COORDINATOR_JOB.status()
        st["started"] = False
    st["members"] = [m.key for m in members]
    # What it took to get a backend serving, so the UI can say "starting vLLM on
    # <model> — the engine takes a moment" instead of a bare spinner. `ready:false`
    # here is the honest still-loading case, not a failure.
    st["activation"] = {
        "backend": act.get("backend"),
        "started": bool(act.get("started")),
        "ready": bool(act.get("ready")),
        "detail": act.get("detail"),
        # Present only when the preferred backend failed and another one took over --
        # so a GPU machine quietly serving from Ollama can still say why.
        "fell_back_from": act.get("fell_back_from"),
    }
    return JSONResponse(st)


@router.get("/ai-coordinator/status")
def ai_coordinator_status() -> JSONResponse:
    """Live status of the coordinated lane: state, turns taken, which sweeps are
    included, whether a user batch is currently holding the model, and what the
    hardware verdict says the master toggle's default should be. Counts only."""
    from src.ai_layer.coordinator import (
        coordinator_default_enabled,
        enabled_members,
        user_batch_active,
    )

    st = _AI_COORDINATOR_JOB.status()
    st["members"] = [{"key": m.key, "label": m.label} for m in enabled_members()]
    st["user_batch"] = user_batch_active()
    st["hardware_default"] = coordinator_default_enabled()
    return JSONResponse(st)


@router.post("/ai-coordinator/cancel")
def ai_coordinator_cancel() -> JSONResponse:
    """Stop the lane at its next safe point. Every sweep's cursor persists, so
    switching back on resumes rather than restarting."""
    _AI_COORDINATOR_JOB.cancel()
    return JSONResponse(_AI_COORDINATOR_JOB.status())
