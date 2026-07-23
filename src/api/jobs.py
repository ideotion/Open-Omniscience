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


# Human dump-kind labels (field test 2026-06-19 #36: the task manager showed the raw
# "en · pages-articles-multistream"). The seekable multistream variant is an internal
# detail — the user just wants "articles dump".
_DUMP_KIND_LABELS = {
    "pages-articles": "articles dump",
    "pages-articles-multistream": "articles dump",
    "pages-articles-multistream-index": "articles dump index",
}


def _dump_label(wiki: str, kind: str) -> str:
    """A human label like "English Wikipedia — articles dump" (never "en · pages-…")."""
    from src.wiki.languages import get_language

    lang = get_language(wiki)
    edition = lang.name if lang else (wiki or "?").upper()
    return f"{edition} Wikipedia — {_DUMP_KIND_LABELS.get(kind, kind)}"


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
                "label": _dump_label(e["wiki"], e["kind"]),
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


def _folder_backup_jobs() -> list[dict]:
    """The large-data 'copy to a folder/drive' backup/restore as a visible job (brief
    §2.A) — a FILE copy (no DB-writer contention), pausable + resumable. Aggregated
    live from the folder-backup manager; surfaces only while it is active."""
    from src.backup.folder_backup import get_folder_manager

    s = get_folder_manager().status()
    if s["state"] in ("idle", "done") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    p = s.get("progress") or {}
    prog = None
    if p.get("bytes_total"):
        done, total = int(p.get("bytes_copied") or 0), int(p["bytes_total"])
        prog = {"done": done, "total": total, "unit": "bytes",
                "percent": round(100 * done / total, 1) if total else 0.0}
    verb = "Restoring" if s.get("mode") == "restore" else "Backing up"
    actions = []
    if state == "running":
        actions = ["pause", "cancel"]
    elif state in ("paused", "failed"):
        actions = ["resume", "cancel"]
    return [
        {
            "id": "folder-backup",
            "kind": "folder-backup",
            "label": f"{verb} to {s.get('dest') or 'a folder'}",
            "state": state,
            "progress": prog,
            "error": s.get("error"),
            "actions": actions,
        }
    ]


def _volume_backup_jobs() -> list[dict]:
    """The large ENCRYPTED backup as a volume set + Reed-Solomon parity (field test
    2026-06-24) — a cancellable build, or a restore+merge. Surfaces while active; control
    lives in the Settings panel (visibility-only here for now)."""
    from src.backup.volume_job import get_volume_manager

    s = get_volume_manager().status()
    if s["state"] in ("idle", "done") and not s.get("running"):
        return []
    state = {"running": "running", "error": "failed"}.get(s["state"], s["state"])
    p = s.get("progress") or {}
    phase = p.get("phase") or ""
    vols = p.get("volumes_written")
    detail = phase + (f", {vols} volumes" if vols else "")
    verb = "Restoring" if s.get("mode") == "restore" else "Backing up (volumes + parity)"
    return [
        {
            "id": "volume-backup",
            "kind": "volume-backup",
            "label": f"{verb} — {detail}" if detail else verb,
            "state": state,
            "progress": None,
            "error": s.get("error"),
            "actions": [],
        }
    ]


def _import_jobs() -> list[dict]:
    """The server-side .eml folder import as a visible job (§2.B). It is a DB-WRITER
    (kind="import"), so it joins the arbitration set — collecting WHILE importing both
    write the corpus, serialised by the single-writer gate. Pausable + resumable."""
    from src.ingest.import_job import get_import_manager

    s = get_import_manager().status()
    if s["state"] in ("idle", "done") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    total = s.get("files_total") or 0
    prog = (
        {"done": s.get("files_done", 0), "total": total, "unit": "files", "percent": s.get("percent", 0.0)}
        if total
        else None
    )
    actions = ["pause", "cancel"] if state == "running" else (["resume", "cancel"] if state in ("paused", "failed") else [])
    folder = s.get("folder") or "a folder"
    return [
        {
            "id": "newsletter-import",
            "kind": "import",
            "label": f"Importing newsletters from {folder}",
            "state": state,
            "progress": prog,
            "eta_seconds": s.get("eta_seconds"),
            "error": s.get("error"),
            "actions": actions,
        }
    ]


def _reindex_jobs() -> list[dict]:
    """The whole-corpus re-index as a visible job (keyword-engine Phase 1.1). A DB-WRITER
    (kind="reindex"): it drives index_article, which takes the single-writer gate per
    article, so it joins the arbitration set — collecting WHILE re-indexing is serialised,
    never a silent collision. Pausable + resumable from the task manager; aggregated live
    from the manager (no shadow state). Zero network."""
    from src.analytics.reindex_job import get_reindex_manager

    s = get_reindex_manager().status()
    if s["state"] in ("idle", "done") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    total = s.get("articles_total") or 0
    prog = (
        {"done": s.get("articles_done", 0), "total": total, "unit": "articles", "percent": s.get("percent", 0.0)}
        if total
        else None
    )
    actions = ["pause", "cancel"] if state == "running" else (["resume", "cancel"] if state in ("paused", "failed") else [])
    label = "Re-indexing the corpus" + (" + pruning keywords" if s.get("prune_after") else "")
    return [
        {
            "id": "reindex",
            "kind": "reindex",
            "label": label,
            "state": state,
            "progress": prog,
            "eta_seconds": s.get("eta_seconds"),
            "error": s.get("error"),
            "actions": actions,
        }
    ]


def _quarantine_jobs() -> list[dict]:
    """The retroactive article-quarantine job as a visible job (S3.2, 2026-07-23
    field-feedback workflow). A DB-WRITER only when running in write=True mode (a
    dry-run detection pass touches nothing); joins the arbitration set either way for
    simplicity — local DB work, no network. Pausable + resumable; aggregated live from
    the manager (no shadow state)."""
    from src.analytics.quarantine_job import get_quarantine_manager

    s = get_quarantine_manager().status()
    if s["state"] in ("idle", "done") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    total = s.get("articles_total") or 0
    prog = (
        {"done": s.get("articles_done", 0), "total": total, "unit": "articles", "percent": s.get("percent", 0.0)}
        if total
        else None
    )
    actions = ["pause", "cancel"] if state == "running" else (["resume", "cancel"] if state in ("paused", "failed") else [])
    label = "Quarantining flagged non-article junk" if not s.get("dry_run") else "Scanning for non-article junk (dry-run)"
    return [
        {
            "id": "quarantine",
            "kind": "quarantine",
            "label": label,
            "state": state,
            "progress": prog,
            "eta_seconds": s.get("eta_seconds"),
            "error": s.get("error"),
            "actions": actions,
        }
    ]


def _model_pull_jobs() -> list[dict]:
    """Model downloads as visible jobs (§2.C1): one active pull, the rest queued.
    A NETWORK job (clearnet via the Ollama process) — NOT a DB writer. Ollama's pull
    is not resumable, so the only action is cancel."""
    from src.llm.pull_queue import get_pull_manager

    s = get_pull_manager().status()
    jobs: list[dict] = []
    a = s.get("active")
    if a:
        total = a.get("total")
        jobs.append(
            {
                "id": f"model-pull:{a['model']}",
                "kind": "model-pull",
                "label": f"Downloading model {a['model']}",
                "state": "running",
                "detail": a.get("status"),
                "progress": (
                    {"done": a.get("completed") or 0, "total": total, "unit": "bytes",
                     "percent": a.get("percent", 0.0)}
                    if total else None
                ),
                "actions": ["cancel"],
            }
        )
    for i, m in enumerate(s.get("queue", [])):
        jobs.append(
            {
                "id": f"model-pull:{m}",
                "kind": "model-pull",
                "label": f"Model {m}",
                "state": "queued",
                "queue_position": i + 1,
                "actions": ["cancel"],
            }
        )
    return jobs


@router.get("/history")
def jobs_history(limit: int = 20) -> dict:
    """Recent COMPLETED collection passes (the History tab) — newest first, with the
    owner's honest verdict (ok/error), mode, articles stored and duration. Reads the
    scheduler's own append-only run log; no shadow state."""
    from src.scheduler.runlog import recent_runs

    runs = recent_runs(limit=max(1, min(limit, 100)))
    return {"runs": runs, "count": len(runs)}


def _background_jobs() -> list[dict]:
    """The generic background jobs (field test 2026-07-08, Item 8 P1): the heavy button
    actions that used to run synchronously — governments load-standard, enrich-source-types,
    keyword-tags backfill — now run on a worker thread. Shown while RUNNING (or failed);
    the DB-writer ones join the arbitration set. Aggregated live from the registry, no
    shadow state."""
    from src.jobs.background import all_job_statuses

    jobs: list[dict] = []
    for s in all_job_statuses():
        if s["state"] not in ("running", "error"):
            continue  # idle/done/cancelled are not shown (mirrors the reindex/import helpers)
        state = "failed" if s["state"] == "error" else "running"
        # HONEST cancel affordance: only a cooperatively-cancellable worker (governments)
        # advertises Cancel — the opaque ones (enrich/backfill) can't be interrupted mid-pass,
        # so offering a button that does nothing would be theatre (skeptic D1).
        actions = ["cancel"] if (state == "running" and s.get("cancellable")) else []
        jobs.append(
            {
                "id": s["kind"],
                "kind": s["kind"],
                "label": s["label"],
                "state": state,
                "progress": s.get("progress"),
                "detail": s.get("detail"),
                "error": s.get("error"),
                "actions": actions,
            }
        )
    return jobs


# DB-writer job kinds that must arbitrate with each other + collection (they take the
# single-writer gate). The original three are kept as a LITERAL tuple (a repo invariant
# guards the exact string) and concatenated with the generic background writers, so a new
# writer kind is added in ONE place. The generic writers commit per unit, so they release
# the gate between units — but they still contend, so the UI's "queue / proceed / stop the
# other" ask fires.
_DB_WRITER_KINDS = ("collect", "import", "reindex", "quarantine") + (
    "governments",
    "enrich-source-types",
    "keyword-tags-backfill",
)


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
    jobs.extend(_folder_backup_jobs())
    jobs.extend(_volume_backup_jobs())
    jobs.extend(_import_jobs())
    jobs.extend(_reindex_jobs())
    jobs.extend(_quarantine_jobs())
    jobs.extend(_model_pull_jobs())
    jobs.extend(_background_jobs())
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
    db_writers = [j for j in running if j["kind"] in _DB_WRITER_KINDS]
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
    if job_id == "folder-backup":
        # Task-manager "cancel"/"pause" PAUSE the folder copy (resumable, like a dump);
        # a true abandon lives in the dedicated Settings → Data & backup controls.
        from src.backup.folder_backup import get_folder_manager

        get_folder_manager().pause()
        return {"cancelled": job_id, "detail": "folder backup paused (resumable from Settings → Data & backup)"}
    if job_id == "newsletter-import":
        from src.ingest.import_job import get_import_manager

        get_import_manager().pause()
        return {"cancelled": job_id, "detail": "newsletter import paused (resumable from Settings → Newsletters)"}
    if job_id == "reindex":
        # Task-manager "cancel"/"pause" PAUSE the re-index (resumable from a persisted
        # cursor); a full discard lives in the Settings → Insights re-index controls.
        from src.analytics.reindex_job import get_reindex_manager

        get_reindex_manager().pause()
        return {"cancelled": job_id, "detail": "re-index paused (resumable; it survives a restart)"}
    if job_id == "quarantine":
        # Task-manager "cancel"/"pause" PAUSE the quarantine job (resumable from its
        # persisted cursor, in the SAME write/dry-run mode it started in).
        from src.analytics.quarantine_job import get_quarantine_manager

        get_quarantine_manager().pause()
        return {"cancelled": job_id, "detail": "quarantine job paused (resumable; it survives a restart)"}
    if job_id.startswith("model-pull:"):
        # Ollama's pull is not resumable, so cancel ABORTS the download (queued or active).
        from src.llm.pull_queue import get_pull_manager

        get_pull_manager().cancel(job_id.split(":", 1)[1])
        return {"cancelled": job_id, "detail": "model download cancelled"}
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
    # Generic background jobs (governments / enrich-source-types / keyword-tags-backfill).
    # The id IS the kind. Only a cooperatively-cancellable worker actually stops early; the
    # opaque ones report honestly that they will finish the current bounded pass first.
    from src.jobs.background import get_job as _get_bg_job

    bg = _get_bg_job(job_id)
    if bg is not None:
        bg.cancel()
        detail = (
            f"{bg.label} — stopping at the next safe point"
            if bg.cancellable
            else f"{bg.label} — cannot be interrupted mid-pass; it will finish the current "
            "bounded pass, then stop (it will not repeat)"
        )
        return {"cancelled": job_id, "cancellable": bg.cancellable, "detail": detail}
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
    if job_id == "folder-backup":
        # Local disk copy — no network/airplane gate (the frontend's ensureOnline is a
        # no-op when offline); resume re-plans + skips already-copied files.
        from src.backup.folder_backup import get_folder_manager

        try:
            get_folder_manager().resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"resumed": job_id, "detail": "folder backup resumed"}
    if job_id == "newsletter-import":
        from src.ingest.import_job import get_import_manager

        try:
            get_import_manager().resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"resumed": job_id, "detail": "newsletter import resumed"}
    if job_id == "reindex":
        # Local DB work — no network/airplane gate; resume continues from the cursor.
        from src.analytics.reindex_job import get_reindex_manager

        try:
            get_reindex_manager().resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"resumed": job_id, "detail": "re-index resumed"}
    if job_id == "quarantine":
        # Local DB work — no network/airplane gate; resume continues from the cursor,
        # in the SAME write/dry-run mode the run started in (never a silent flip).
        from src.analytics.quarantine_job import get_quarantine_manager

        try:
            get_quarantine_manager().resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"resumed": job_id, "detail": "quarantine job resumed"}
    raise HTTPException(status_code=404, detail=f"unknown or unresumable job {job_id!r}")
