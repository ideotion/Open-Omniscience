"""
Jobs API: ONE honest view over every background/network task + arbitration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

T9 (maintainer repeat ×2): every network task is a VISIBLE JOB. This module
deliberately keeps NO state of its own — it AGGREGATES the real owning
systems (the scheduler, the wiki-dump manager, the fetcher's live activity)
so the view can never disagree with reality, and routes actions back to the
owners (stop = the scheduler's own stop; reorder = the dump queue's own
order). The 'database is locked' class of collisions is what the arbitration
choices prevent: a new heavy task while one runs ASKS — queue / proceed /
stop the other — never a silent pile-up.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _dl_actions(state: str) -> list[str]:
    """Honest action set per download state, shared by the dump + OSM jobs.

    A 'cancel' on an already-paused download would re-call the owner's pause()
    and fail (it is not queued and has no live stop event), so paused/failed
    offer RESUME instead — permanent removal stays in the owning Settings tab
    (Wikipedia / Offline map), as the pause/cancel detail messages already say.
    """
    if state == "running":
        return ["pause", "cancel"]
    if state == "queued":
        return ["reorder", "cancel"]
    if state in ("paused", "failed"):
        return ["resume"]
    return []


def _dump_jobs() -> list[dict]:
    from src.wiki.dumps import get_manager

    mgr = get_manager()
    order = mgr.queue_order()
    jobs = []
    for e in mgr.list():
        state = {
            "downloading": "running",
            "queued": "queued",
            "paused": "paused",
            "done": "done",
            "error": "failed",
        }.get(e["status"], e["status"])
        jobs.append(
            {
                "id": f"dump:{e['key']}",
                "kind": "wiki-dump",
                "label": f"{e['wiki']} · {e['kind']}",
                "state": state,
                "queue_position": (order.index(e["key"]) + 1) if e["key"] in order else None,
                "progress": {
                    "done": e["downloaded_bytes"],
                    "total": e["total_bytes"] or None,
                    "unit": "bytes",
                    "percent": e["percent"],
                },
                "error": e.get("error"),
                "actions": _dl_actions(state),
            }
        )
    return jobs


def _osm_jobs() -> list[dict]:
    """OSM offline-map region downloads as visible jobs (Group M), mirroring the
    wiki-dump aggregation: a FILE download (no DB-writer contention), parallel up
    to capacity with a reorderable queue. Aggregated live from the OSM download
    manager — no shadow state."""
    from src.geo.osm_downloads import get_manager

    mgr = get_manager()
    order = mgr.queue_order()
    jobs = []
    for e in mgr.list():
        state = {
            "downloading": "running",
            "queued": "queued",
            "paused": "paused",
            "done": "done",
            "error": "failed",
        }.get(e["status"], e["status"])
        jobs.append(
            {
                "id": f"osm:{e['key']}",
                "kind": "osm-map",
                "label": e.get("name") or e["code"],
                "state": state,
                "queue_position": (order.index(e["key"]) + 1) if e["key"] in order else None,
                "progress": {
                    "done": e["downloaded_bytes"],
                    "total": e["total_bytes"] or None,
                    "unit": "bytes",
                    "percent": e["percent"],
                },
                "error": e.get("error"),
                "actions": _dl_actions(state),
            }
        )
    return jobs


def _collect_job() -> dict | None:
    from src.scheduler.runner import get_scheduler

    st = get_scheduler().status()
    if not (st.get("running") or st.get("active")):
        return None
    # Honest phase label so the user understands WHAT the pass is doing (the
    # task-manager's whole point — maintainer 2026-06-18). Articles are collected
    # FIRST; the post-scrape housekeeping (markets/calendars/preflight checks) is a
    # named phase so a lingering market fetch reads as "finishing", not a stall.
    _PHASE_LABELS = {
        "collecting": "collection pass — collecting articles",
        "background": "collection pass — background tasks (markets · calendars · checks)",
        "briefing": "collection pass — building the briefing",
    }
    if st.get("active"):
        label = _PHASE_LABELS.get(st.get("phase") or "", "collection pass")
    else:
        label = "collection loop (idle)"
    return {
        "id": "collect:current",
        "kind": "collect",
        "label": label,
        "phase": st.get("phase"),
        "state": "running" if st.get("active") else "scheduled",
        "next_run": st.get("next_run"),
        "progress": None,  # the detailed panel reads /api/scheduler/activity
        "actions": ["stop"],
    }


def _live_fetch() -> dict | None:
    from src.monitoring.activity import activity_monitor

    snap = activity_monitor.snapshot()
    cur = snap.get("current_fetch")
    if not cur:
        return None
    from urllib.parse import urlparse

    host = ""
    try:
        host = urlparse(cur).hostname or ""
    except Exception:  # noqa: BLE001 - display aid only
        host = ""
    return {
        "id": "fetch:current",
        "kind": "fetch",
        # DOMAIN only (ruled): never the full URL in the manager view.
        "label": host or "fetch in flight",
        "state": "running",
        "actions": [],
    }


def _task_jobs() -> list[dict]:
    """Background LLM/analysis tasks that registered themselves (src.monitoring.tasks).

    Read-only visibility — the answer to "is an LLM translating? are keywords being
    extracted?". Each carries only the owner's real facts (label/detail and an
    optional done/total it published), never a fabricated percentage. No actions:
    these are short, in-request operations the user did not queue."""
    from src.monitoring.tasks import snapshot

    out: list[dict] = []
    for t in snapshot():
        prog = None
        if t.get("total"):
            done = int(t.get("done") or 0)
            total = int(t["total"])
            prog = {"done": done, "total": total, "percent": round(100 * done / total) if total else 0}
        out.append(
            {
                "id": f"task:{t['token']}",
                "kind": t.get("kind") or "task",
                "label": t.get("label") or "background task",
                "detail": t.get("detail"),
                "state": "running",
                "elapsed_s": t.get("elapsed_s"),
                "progress": prog,
                "actions": [],
            }
        )
    return out


@router.get("/history")
def jobs_history(limit: int = 20) -> dict:
    """Recent COMPLETED collection passes (the History tab) — newest first, with the
    owner's honest verdict (ok/error), mode, articles stored and duration. Reads the
    scheduler's own append-only run log; no shadow state."""
    from src.scheduler.runlog import recent_runs

    runs = recent_runs(limit=max(1, min(limit, 100)))
    return {"runs": runs, "count": len(runs)}


@router.get("")
def list_jobs() -> dict:
    """Every visible job, aggregated LIVE from the owning systems (no shadow
    state): the collection loop/pass, each wiki-dump and OSM-region download with
    its real queue position, the fetch currently on the wire (domain only), and
    any background LLM/analysis task that registered itself (the Windows-Task-
    Manager "what is actually happening" view — maintainer 2026-06-18)."""
    jobs: list[dict] = []
    j = _collect_job()
    if j:
        jobs.append(j)
    jobs.extend(_dump_jobs())
    jobs.extend(_osm_jobs())
    jobs.extend(_task_jobs())
    f = _live_fetch()
    if f:
        jobs.append(f)
    running = [j for j in jobs if j["state"] == "running"]
    # PARALLEL ACROSS KINDS (maintainer-amended 2026-06-12): collecting
    # articles WHILE a Wikipedia dump downloads is by design — a dump writes
    # to a FILE, collection writes to the DATABASE; they share neither the
    # writer lock nor (usually) hosts. The arbitration ASK therefore fires
    # only for DB-WRITER collisions (collect/import kinds); bulk downloads
    # keep their own single-download, reorderable queue among themselves.
    db_writers = [j for j in running if j["kind"] in ("collect", "import")]
    return {
        "jobs": jobs,
        "running": len(running),
        "queued": len([j for j in jobs if j["state"] == "queued"]),
        "network_busy": bool(running),
        "db_writers_busy": bool(db_writers),
        "busy_with": [f"{j['kind']}: {j['label']}" for j in db_writers],
        "running_with": [f"{j['kind']}: {j['label']}" for j in running],
        "method": (
            "Aggregated live from the scheduler, the dump manager and the "
            "fetcher's own activity monitor — no shadow state, so this view "
            "cannot disagree with reality."
        ),
    }


class ReorderBody(BaseModel):
    keys: list[str]


@router.post("/dumps/reorder")
def reorder_dumps(body: ReorderBody) -> dict:
    """Reorder the QUEUED dump downloads (the fr-before-en acceptance case)."""
    from src.wiki.dumps import get_manager

    return {"queue_order": get_manager().reorder(body.keys)}


@router.post("/osm/reorder")
def reorder_osm(body: ReorderBody) -> dict:
    """Reorder the QUEUED OSM region downloads (same prioritisation as dumps)."""
    from src.geo.osm_downloads import get_manager

    return {"queue_order": get_manager().reorder(body.keys)}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Cancel/stop a job via its OWNING system, honestly named per kind."""
    if job_id.startswith("dump:"):
        from src.wiki.dumps import get_manager

        key = job_id.split(":", 1)[1]
        mgr = get_manager()
        ok = mgr.pause(key)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown dump {key!r}")
        return {"cancelled": job_id, "detail": "download paused (resumable; delete it in Settings → Wikipedia)"}
    if job_id.startswith("osm:"):
        from src.geo.osm_downloads import get_manager as get_osm_manager

        key = job_id.split(":", 1)[1]
        ok = get_osm_manager().pause(key)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown OSM download {key!r}")
        return {"cancelled": job_id, "detail": "download paused (resumable; delete it in Settings → Offline map)"}
    if job_id == "collect:current":
        from src.ingest import activate_kill_switch, kill_switch_active
        from src.scheduler.runner import get_scheduler

        # The Stop-button semantics exactly (§0.5): refuse every further fetch
        # FIRST, then stop the loop — and SAY so (informed consent: stopping
        # collection takes the app offline; the airplane toggle will show it).
        activate_kill_switch()
        stopped = get_scheduler().stop()
        return {
            "cancelled": job_id,
            "stopped": stopped,
            "online": not kill_switch_active(),
            "detail": "collection stopped; the network kill switch is now engaged",
        }
    raise HTTPException(status_code=404, detail=f"unknown or uncancellable job {job_id!r}")


@router.post("/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    """Resume a PAUSED/failed download via its OWNING system (start() continues
    the partial file from where it stopped). The frontend gates this through the
    ONE network-consent popup first (invariant #14) — a resume re-opens a fetch;
    the download path itself still refuses while the kill switch is engaged."""
    if job_id.startswith("dump:"):
        from src.wiki.dumps import get_manager

        key = job_id.split(":", 1)[1]
        if get_manager().resume(key) is None:
            raise HTTPException(status_code=404, detail=f"unknown dump {key!r}")
        return {"resumed": job_id, "detail": "download resumed"}
    if job_id.startswith("osm:"):
        from src.geo.osm_downloads import get_manager as get_osm_manager

        key = job_id.split(":", 1)[1]
        if get_osm_manager().resume(key) is None:
            raise HTTPException(status_code=404, detail=f"unknown OSM download {key!r}")
        return {"resumed": job_id, "detail": "download resumed"}
    raise HTTPException(status_code=404, detail=f"unknown or unresumable job {job_id!r}")
