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

import functools
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _dl_actions(state: str) -> list[str]:
    """Honest action set per download state, shared by the dump + OSM jobs.

    A 'cancel' on an already-paused download would re-call the owner's pause()
    and fail (it is not queued and has no live stop event), so paused/failed
    offer RESUME instead — permanent removal stays in the owning Settings tab
    (Wikipedia / OpenStreetMap), as the pause/cancel detail messages already say.
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


# A LABEL THAT CARRIES A VALUE, KEYED (click-through B17, T11). "Importing {x}",
# "Downloading model {m}", a dump's edition: the English `label` has the value welded in,
# so no key can ever match it and every locale showed English. Such a job also carries
# `label_i18n` -- the frame, which is the UI locale key -- and `label_vars`, the values,
# and the task managers (app-core.js `_jobLabel`, taskmanager.html `jobLabel`) write the
# frame in the UI language. The conventions they share: a number is formatted there; a
# var named `language` is a language CODE, written as its name in the UI language; a var
# that is itself ``{"i18n": key, "vars": {...}}`` is a keyed phrase, written in the UI
# language by the same rules (click-through B19: "Large data", a backup phase, "3 volumes");
# any other value is data and shown as given. `label` itself is unchanged: it is the API's
# answer, the arbitration line (`busy_with`) and what an older page prints. A job's
# `detail` line travels the same way (`detail_i18n` / `detail_vars`).
_DUMP_KIND_FRAMES = {
    "articles dump": "{language} Wikipedia — articles dump",
    "articles dump index": "{language} Wikipedia — articles dump index",
}


def _label_frame(frame: str, **values) -> dict:
    """The ``label_i18n`` / ``label_vars`` pair for a label carrying values."""
    return {"label_i18n": frame, "label_vars": values}


def _keyed(key: str, **values) -> dict:
    """A frame VALUE that is itself a keyed phrase (see the conventions above)."""
    return {"i18n": key, "vars": values} if values else {"i18n": key}


def _count_phrase(n: int, one: str, many: str) -> dict:
    """A count and its noun as ONE keyed phrase, the frame chosen by the count."""
    return _keyed(one if n == 1 else many, n=n)


def _detail_frame(src: dict) -> dict:
    """The ``detail_i18n`` / ``detail_vars`` pair a producer published, passed on as is."""
    if not src.get("detail_i18n"):
        return {}
    return {"detail_i18n": src["detail_i18n"], "detail_vars": dict(src.get("detail_vars") or {})}


def _dump_label_frame(wiki: str, kind: str) -> dict:
    """The keyed twin of `_dump_label`: the edition goes as its CODE, so each page names
    the language in its own UI language (the English name is what `label` says)."""
    human = _DUMP_KIND_LABELS.get(kind, kind)
    frame = _DUMP_KIND_FRAMES.get(human)
    if frame is None:   # a kind this table does not know: the frame carries it as data
        return _label_frame("{language} Wikipedia — {kind}", language=wiki or "?", kind=human)
    return _label_frame(frame, language=wiki or "?")


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
                **_dump_label_frame(e["wiki"], e["kind"]),
                "state": state,
                "queue_position": (order.index(e["key"]) + 1) if e["key"] in order else None,
                "progress": {
                    "done": e["downloaded_bytes"],
                    "total": e["total_bytes"] or None,
                    "unit": "bytes",
                    "percent": e["percent"],
                },
                # PERF-09: the OWNER's own bytes-over-time, measured in the
                # download loop. Always present as a block; `measured` is False
                # with a REASON when there is nothing to report, because a
                # `bytes_per_s` of 0 reads as "stalled" and that is a different
                # fact from "not measured yet". The ETA rides inside it and only
                # when a real rate AND a real Content-Length both exist.
                "rate": e.get("rate") or {"measured": False, "reason": "not reported"},
                "eta_seconds": (e.get("rate") or {}).get("eta_seconds"),
                "error": e.get("error"),
                # Who paused it (airplane / operator / restart), only while paused.
                "paused_by": e.get("paused_by"),
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
                # PERF-09: the OWNER's own bytes-over-time, measured in the
                # download loop. Always present as a block; `measured` is False
                # with a REASON when there is nothing to report, because a
                # `bytes_per_s` of 0 reads as "stalled" and that is a different
                # fact from "not measured yet". The ETA rides inside it and only
                # when a real rate AND a real Content-Length both exist.
                "rate": e.get("rate") or {"measured": False, "reason": "not reported"},
                "eta_seconds": (e.get("rate") or {}).get("eta_seconds"),
                "error": e.get("error"),
                # Who paused it (airplane / operator / restart), only while paused.
                "paused_by": e.get("paused_by"),
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
            # A COUNT, and it says so: with no unit the in-app window read the progress as
            # bytes (the shipped default for a unit-less row), so "Summarizing 12
            # article(s)" drew "3 B / 12 B" (click-through B17, T5).
            prog = {"done": done, "total": total, "unit": "items",
                    "percent": round(100 * done / total) if total else 0}
        # A task that registered its label as a frame (src.monitoring.tasks) passes it on.
        frame = _label_frame(t["label_i18n"], **(t.get("label_vars") or {})) if t.get("label_i18n") else {}
        out.append(
            {
                "id": f"task:{t['token']}",
                "kind": t.get("kind") or "task",
                "label": t.get("label") or "background task",
                **frame,
                "detail": t.get("detail"),
                **_detail_frame(t),
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
    dest = s.get("dest")
    # With no destination the label is a fixed sentence, and fixed sentences are keys.
    frame = (
        _label_frame("Restoring to {dest}" if s.get("mode") == "restore" else "Backing up to {dest}", dest=dest)
        if dest else {}
    )
    return [
        {
            "id": "folder-backup",
            "kind": "folder-backup",
            "label": f"{verb} to {dest or 'a folder'}",
            **frame,
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
            **_volume_label_frame(verb, s.get("mode"), phase, vols),
            "state": state,
            "progress": None,
            "error": s.get("error"),
            "actions": [],
        }
    ]


# The volume engine's phase CODES, named as the backup dialog names them (app-backup.js
# `_uxVolPhase`, whose keys these are): the English label prints the code ("parity"), which
# no locale can match (click-through B19, Q2). A phase the dialog does not name either --
# the sub-second post-commit housekeeping stages -- is left out of the keyed label rather
# than shown as a code; the English `label` still carries it.
_VOLUME_BACKUP_PHASES = {
    "starting": "Preparing…", "building": "Building encrypted volumes…",
    "volumes": "Writing encrypted volumes…", "parity": "Writing parity…",
    "verifying": "Verifying volumes…", "done": "Done.",
}
_VOLUME_RESTORE_PHASES = {
    "verifying": "Verifying volumes…", "reassembling": "Reassembling the archive…",
    "merging": "Merging (additive)…", "reindexing": "Re-indexing merged articles…",
    "done": "Done.", "verify": "Verifying the merge…",
    "snapshot_working_copy": "Snapshotting your corpus…",
    "pre_restore_snapshot": "Snapshotting your corpus…", "swap": "Committing…",
}


def _volume_label_frame(verb: str, mode, phase: str, vols) -> dict:
    """The keyed twin of the volume job's label: the verb and the phase as keyed phrases,
    the volume count as a count with its noun."""
    table = _VOLUME_BACKUP_PHASES if mode == "backup" else _VOLUME_RESTORE_PHASES
    named = table.get(phase)
    values: dict = {"verb": _keyed(verb)}
    if named:
        values["phase"] = _keyed(named)
    if vols:
        values["volumes"] = _count_phrase(int(vols), "{n} volume", "{n} volumes")
    shape = tuple(k for k in ("phase", "volumes") if k in values)
    if not shape:   # the verb alone is a fixed sentence: its own key
        return _label_frame(verb)
    frame = {
        ("phase", "volumes"): "{verb} — {phase}, {volumes}",
        ("phase",): "{verb} — {phase}",
        ("volumes",): "{verb} — {volumes}",
    }[shape]
    return _label_frame(frame, **values)


# The words the Import dialog sends as the label of an item that has no file name of its
# own (app-backup.js: t("Large data"), t("Newsletters"), t("Corpus backup")). The page
# sends them in ITS language at the moment of the click, so the queue holds "Données
# volumineuses" or "Large data" alike, and "Importing {label}" printed that word in
# whichever language it was queued in (click-through B19, Q1). Recognised here in any of
# the twelve, it goes out as the KEY and each page writes it in its own; any other label
# (a file name, an API caller's own words) is data and stays as given.
_IMPORT_ITEM_WORDS = ("Large data", "Newsletters", "Corpus backup")


@functools.lru_cache(maxsize=1)
def _import_item_word_index() -> dict[str, str]:
    idx = {k: k for k in _IMPORT_ITEM_WORDS}
    for f in sorted((Path(__file__).resolve().parents[1] / "static" / "locales").glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k in _IMPORT_ITEM_WORDS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                idx.setdefault(v, k)
    return idx


def _import_queue_jobs() -> list[dict]:
    """The whole IMPORT RUN as one visible job (2026-07-29, remark 2 + ruling 13).

    Distinct from the per-item jobs below it: those show what is running right now
    (a volume restore, a folder copy), while this shows the RUN they belong to --
    "3 of 6 imported" -- which is the thing the maintainer could not see at all when
    six backups shared one anonymous bar. kind="import" so it arbitrates with
    collection like every other DB writer.

    Its only action is CANCEL, and honestly so: an import run has no pause. Before a
    backup's atomic swap a stop is a complete abort; after it, that backup stands and
    only the remaining work stops. Offering "pause" would imply a resume that does
    not exist -- the passphrase is never stored, so a run cannot be picked back up."""
    from src.backup.import_queue import get_import_queue

    s = get_import_queue().status()
    if s.get("state") != "running":
        return []
    total = int(s.get("items_total") or 0)
    done = int(s.get("items_done") or 0)
    cur = s.get("current") or {}
    label = cur.get("label") or ""
    # A RUN DOES NOT END WITH ITS LAST ITEM (field report 2026-08-11). After the last
    # item the queue merges the search index inside the same exclusive window, with no
    # item in flight -- so `current` is None while `items_done == items_total`, and the
    # row read "Importing" at 100%: a job simultaneously claiming to be finished and to
    # be working. The item count is a real measurement and stays; what was wrong was the
    # NAME, which now says which of the two it is. A fixed string, so the DOM walker can
    # translate it (an f-string with the item label in it cannot be an exact key).
    s_done = int(s.get("stages_done") or 0)
    s_total = int(s.get("stages_total") or 0)
    tail = str(((s.get("live") or {}).get("progress") or s.get("live") or {}).get("phase") or "")
    # The item's own label comes from the import queue (src/backup/import_queue.py) and is
    # data here: the frame carries it as a value.
    word = _import_item_word_index().get(label)
    frame = _label_frame("Importing {label}", label=_keyed(word) if word else label) if label else {}
    if label:
        job_label = f"Importing {label}"
    elif tail:
        job_label = "Finishing the import"
    else:
        job_label = "Importing"
    return [
        {
            "id": "import-queue",
            "kind": "import",
            "label": job_label,
            **frame,
            "state": "running",
            # STAGES, not items: the run's last stage is the search-index merge, and with
            # every item done the item count reads 100% while that stage is still holding
            # the machine. The status publishes both; the BAR takes the one that counts
            # the work actually left.
            "progress": (
                {"done": s_done, "total": s_total, "unit": "stages",
                 "percent": round(100.0 * s_done / s_total, 1)}
                if s_total else None
            ),
            # The item count stays available beside it -- it is a real measurement and
            # the honest answer to "how many backups went in".
            "items_done": done,
            "items_total": total,
            # No ETA: the items are different kinds of work over different units, so
            # extrapolating one from the others would be a fabricated number.
            "eta_seconds": None,
            "error": None,
            "actions": ["cancel"],
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
    label = f"Importing newsletters from {folder}"
    # Same reading as the re-index row below, worded for a row that is ITSELF an import:
    # "paused for an import" would read as a contradiction here, and the thing it is
    # waiting for is specifically a corpus import (a restore/merge holding the window).
    parked = bool(s.get("parked_for_exclusive"))
    if parked:
        label = "Paused for a corpus import — " + label[0].lower() + label[1:]
    # With no folder the label is a fixed sentence, and fixed sentences are keys.
    frame = (
        _label_frame(
            "Paused for a corpus import — importing newsletters from {folder}" if parked
            else "Importing newsletters from {folder}",
            folder=s["folder"],
        )
        if s.get("folder") else {}
    )
    return [
        {
            "id": "newsletter-import",
            "kind": "import",
            "label": label,
            **frame,
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
    # A PARKED JOB IS RUNNING AND MAKING NO PROGRESS ON PURPOSE. The manager publishes
    # `parked_for_exclusive` for exactly this row -- its own comment says "without this
    # the task manager shows 'running' with a frozen counter, which is exactly the
    # signature of the stall this yielding was added to avoid" -- and this row never read
    # it, so a deliberate pause and a hang looked identical. Say which one it is.
    if s.get("parked_for_exclusive"):
        label = "Paused for an import — " + label[0].lower() + label[1:]
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


def _keyword_fold_jobs() -> list[dict]:
    """The keyword fold job (Q416 = a) as a visible job: a DB-WRITER (kind
    "keyword-fold") that re-keys keywords written before lemmatisation, then re-derives
    each keyword's language. Pausable + resumable; aggregated live from the manager (no
    shadow state). Zero network. ``error`` is the manager's CODE, never exception text."""
    from src.analytics.keyword_fold import get_fold_manager

    s = get_fold_manager().status()
    if s["state"] in ("idle", "done", "cancelled") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    total = s.get("keywords_total") or 0
    prog = (
        {"done": s.get("keywords_done", 0), "total": total, "unit": "keywords", "percent": s.get("percent", 0.0)}
        if total
        else None
    )
    actions = ["pause", "cancel"] if state == "running" else (["resume", "cancel"] if state in ("paused", "failed") else [])
    label = (
        "Setting each keyword's language from its mentions"
        if s.get("phase") == "language"
        else "Folding keyword forms into their base form"
    )
    if s.get("parked_for_exclusive"):
        label = "Paused for an import — " + label[0].lower() + label[1:]
    return [
        {
            "id": "keyword-fold",
            "kind": "keyword-fold",
            "label": label,
            "state": state,
            "progress": prog,
            "eta_seconds": s.get("eta_seconds"),
            "error": s.get("error"),
            "actions": actions,
        }
    ]


def _search_reindex_jobs() -> list[dict]:
    """The search re-index (S04-07 S8) as a visible job: a DB-WRITER (kind
    "search-reindex") that re-indexes articles indexed before Arabic folding and CJK
    segmentation. Pausable + resumable; aggregated live from the manager (no shadow
    state). Zero network. ``error`` is the manager's CODE, never exception text."""
    from src.database.fts_reindex import get_search_reindex_manager

    s = get_search_reindex_manager().status()
    if s["state"] in ("idle", "done", "cancelled") and not s.get("running"):
        return []
    state = {"running": "running", "paused": "paused", "error": "failed"}.get(s["state"], s["state"])
    total = s.get("articles_total") or 0
    prog = (
        {"done": s.get("articles_checked", 0), "total": total, "unit": "articles", "percent": s.get("percent", 0.0)}
        if total
        else None
    )
    actions = ["pause", "cancel"] if state == "running" else (["resume", "cancel"] if state in ("paused", "failed") else [])
    label = "Re-indexing search for Arabic, Chinese and Japanese"
    if s.get("parked_for_exclusive"):
        label = "Paused for an import — re-indexing search for Arabic, Chinese and Japanese"
    return [
        {
            "id": "search-reindex",
            "kind": "search-reindex",
            "label": label,
            "state": state,
            "progress": prog,
            "eta_seconds": None,
            "error": s.get("error"),
            "actions": actions,
        }
    ]


#: The walk's pause reasons as the task manager's detail line, keyed x12 (``detail_i18n``).
#: The SAME sentences, and so the same keys, the Living sources view draws for the same
#: tokens (``app-living.js:_LIVING_WALK_WHY``): one cause, one wording, in both places.
_WALK_WHY = {
    "network_off": "Airplane mode is on.",
    "transport_unavailable": "Protected mode has no usable proxy, and the walk never goes direct.",
    "storage_budget_spent": "The lane's storage budget is spent.",
}
_WALK_ALL_WAITING = "Every edition is waiting out a refusal from the wiki."


def _wiki_walk_jobs() -> list[dict]:
    """The Wikipedia ``allpages`` walk as a visible job (Q701 = c; S05-06's S2).

    A NETWORK job, not a DB writer in the arbitration sense: it writes the lane's own file,
    never ``corpus.db``, so it takes no part in the single-writer ask. Shown while THIS
    process's walker is walking, paused or waiting; nothing when it is off, finished, or no
    lane is running here. COUNTS ONLY, and no progress bar: the only total is the edition's
    own article count, which counts a slightly different set than the walk lists, so a bar
    against it could read past 100% -- and no ETA, because a rate measured over one hour of
    a multi-day walk is not a promise about the rest.
    """
    from src.wiki.service import lane_service_status

    live = (lane_service_status() or {}).get("walk") or {}
    state = live.get("state")
    if state not in ("walking", "paused", "waiting"):
        return []
    seen = None
    try:
        from src.versioned.store import lane_path, lane_session
        from src.wiki.walk import walk_coverage

        if lane_path("wiki").is_file():
            with lane_session("wiki") as lane:
                cov = walk_coverage(lane)
            if cov.get("measured"):
                seen = int(cov.get("pages_seen") or 0)
    except Exception:  # noqa: BLE001 - the row still shows without its count
        seen = None
    reason = live.get("reason")
    why = _WALK_WHY.get(reason or "")
    job: dict = {
        "id": "wiki-walk",
        "kind": "wiki-walk",
        "state": "running" if state == "walking" else "paused",
        "progress": None,
        "eta_seconds": None,
        "actions": [],
    }
    if seen is None:
        job["label"] = "Wikipedia page walk"
    else:
        job["label"] = f"Wikipedia page walk — {seen} page{'' if seen == 1 else 's'} seen"
        job.update(
            _label_frame(
                "Wikipedia page walk — {pages}",
                pages=_count_phrase(seen, "{n} page seen", "{n} pages seen"),
            )
        )
    line = why or (_WALK_ALL_WAITING if state == "waiting" else None)
    if line:
        job.update({"detail": line, "detail_i18n": line, "detail_vars": {}})
    return [job]


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
                **_label_frame("Downloading model {model}", model=a["model"]),
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
                **_label_frame("Model {model}", model=m),
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


@router.get("/ledger")
def jobs_ledger(limit: int = 200) -> dict:
    """The Activity Ledger (S05-09 S5): one entry per action the app took on its own,
    newest first, in the fixed shape (what happened, why, touched, caveat, budget,
    reversible, undo). Reads the append-only file the scheduler writes; counts only."""
    from src.monitoring import activity_ledger as al

    entries = al.read_entries(limit=max(1, min(limit, 1000)))
    return {
        "entries": entries,
        "count": len(entries),
        "categories": list(al.CATEGORIES),
        "reserved": sorted(al.RESERVED_CATEGORIES),
    }


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
                **_detail_frame(s),
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
    "mailbox-pull",
    "keyword-fold",
    "search-reindex",
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
    jobs.extend(_import_queue_jobs())
    jobs.extend(_import_jobs())
    jobs.extend(_reindex_jobs())
    jobs.extend(_quarantine_jobs())
    jobs.extend(_keyword_fold_jobs())
    jobs.extend(_search_reindex_jobs())
    jobs.extend(_wiki_walk_jobs())
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
        return {"cancelled": job_id, "detail": "download paused (resumable; delete it in Settings → OpenStreetMap)"}
    if job_id == "folder-backup":
        # Task-manager "cancel"/"pause" PAUSE the folder copy (resumable, like a dump);
        # a true abandon lives in the dedicated Settings → Data & backup controls.
        from src.backup.folder_backup import get_folder_manager

        get_folder_manager().pause()
        return {"cancelled": job_id, "detail": "folder backup paused (resumable from Settings → Data & backup)"}
    if job_id == "import-queue":
        # Stop, never pause: see _import_queue_jobs for why an import run has no resume.
        from src.backup.import_queue import get_import_queue

        get_import_queue().stop()
        return {
            "cancelled": job_id,
            "detail": (
                "import stopped — a backup not yet swapped in is abandoned completely "
                "(your corpus is untouched); one already merged stays merged and its "
                "re-index resumes later"
            ),
        }
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
    if job_id == "keyword-fold":
        # Task-manager "cancel"/"pause" PAUSE a RUNNING fold (resumable from its persisted
        # cursor; every committed page stays committed, and a re-run finds nothing left to
        # move). On a fold that is already stopped, pausing again would do nothing while the
        # row offers "cancel", so there it CANCELS: the saved cursor is dropped and the row
        # leaves the task manager. Nothing already folded is undone.
        from src.analytics.keyword_fold import get_fold_manager

        fmgr = get_fold_manager()
        if fmgr.status().get("state") in ("paused", "error"):
            fmgr.cancel()
            return {
                "cancelled": job_id,
                "detail": "keyword fold cancelled (what it already folded stays folded; folding again starts a new pass)",
            }
        fmgr.pause()
        return {"cancelled": job_id, "detail": "keyword fold paused (resumable; it survives a restart)"}
    if job_id == "search-reindex":
        # Task-manager "cancel"/"pause" PAUSE the search re-index (resumable from its
        # persisted cursor; every committed step stays committed).
        from src.database.fts_reindex import get_search_reindex_manager

        get_search_reindex_manager().pause()
        return {"cancelled": job_id, "detail": "search re-index paused (resumable; it survives a restart)"}
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
    if job_id == "keyword-fold":
        # Local DB work — no network/airplane gate; resume continues from the cursor.
        from src.analytics.keyword_fold import FoldRefused, get_fold_manager, refusal_code

        mgr = get_fold_manager()
        try:
            mgr.resume()
        except FoldRefused:
            # The code is re-derived from the manager's state, never read off the
            # exception: nothing an exception carries reaches a response.
            raise HTTPException(status_code=409, detail={"code": refusal_code(mgr)}) from None
        return {"resumed": job_id, "detail": "keyword fold resumed"}
    if job_id == "search-reindex":
        # Local DB work — no network/airplane gate; resume continues from the cursor.
        from src.database.fts_reindex import (
            SearchReindexRefused,
            get_search_reindex_manager,
        )
        from src.database.fts_reindex import refusal_code as search_refusal_code

        smgr = get_search_reindex_manager()
        try:
            smgr.resume()
        except SearchReindexRefused:
            raise HTTPException(status_code=409, detail={"code": search_refusal_code(smgr)}) from None
        return {"resumed": job_id, "detail": "search re-index resumed"}
    raise HTTPException(status_code=404, detail=f"unknown or unresumable job {job_id!r}")
