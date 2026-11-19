"""The medical lane's routes: what is kept (local), and the one click that fetches PubMed update files (S07-01; R745, R750).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE route egresses, and it is the only one gated: ``POST /api/medical/fetch`` reads NLM's update
directory and the files it names (``src/medical/fetch.py``). It refuses with a 409 that NAMES
airplane mode (invariant #14e's corollary) and with a 400 unless the caller says ``consent: true``:
the UI passes the ONE network consent first, and a caller that never opened the UI meets the same
refusal (invariant #14f). The status route reads ``medical.db`` alone and makes no request, so it
is not gated; it carries the disclosure and the gap (R750) so the UI shows them before any click.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.jobs.background import BackgroundJob, register_job

router = APIRouter(prefix="/api/medical", tags=["medical"])


def _fetch_worker(ctx, *, files: int) -> dict:
    from src.medical.fetch import run_fetch

    def _progress(done: int, total: int, detail: str) -> None:
        ctx.set_progress(done=done, total=total, detail=detail)

    return run_fetch(files, progress=_progress, stopping=lambda: ctx.stopping)


#: A WRITER (it commits to ``medical.db``), and CANCELLABLE honestly: the worker reads
#: ``ctx.stopping`` before each file and during the corpus scan, so Cancel ends the run at the next
#: file boundary. The file under way finishes or fails whole; a half-applied file never exists.
_FETCH_JOB = register_job(
    BackgroundJob(
        "medical-fetch", "Fetching PubMed update files", _fetch_worker, is_writer=True, cancellable=True
    )
)


class _FetchBody(BaseModel):
    consent: bool = False
    files: int | None = None


@router.get("/status")
def medical_status() -> dict:
    """What the lane holds and how many cited papers it found. Local only: no request leaves the machine."""
    from src.medical import store as M
    from src.medical.fetch import DEFAULT_FILES, DISCLOSURE, GAP, MAX_FILES, PUBMED_HOST
    from src.versioned import store

    if store.lane_path(M.LANE).exists():
        store.create_lane(M.LANE)  # idempotent: a table a newer version added exists before it is read
        with store.lane_session(M.LANE) as s:
            out = M.summary(s)
            cov = M.coverage(s)
    else:
        # Nothing fetched yet: say so with zeros rather than create a file on a read.
        out = {"papers": 0, "by_class": {"journal": 0, "preprint": 0, "retracted": 0}, "withdrawn": 0,
               "wanted_named": 0, "last_file": None}
        cov = dict.fromkeys(("cited", "cited_found", "cited_not_found", "named", "named_found", "named_not_found"), 0)
    return {
        **out,
        "coverage": cov,
        "host": PUBMED_HOST,
        "disclosure": DISCLOSURE,
        "gap": GAP,
        "default_files": DEFAULT_FILES,
        "max_files": MAX_FILES,
        "method": "Read from this install's medical.db; nothing is requested from the network.",
    }


@router.post("/fetch")
def medical_fetch(body: _FetchBody | None = None) -> dict:
    """Read NLM's update directory and apply the next unapplied files (EGRESSES)."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED
    from src.medical.fetch import DEFAULT_FILES, MAX_FILES

    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if body is None or not body.consent:
        raise HTTPException(
            status_code=400, detail="consent required: this sends requests to ftp.ncbi.nlm.nih.gov"
        )
    files = DEFAULT_FILES if body.files is None else max(1, min(int(body.files), MAX_FILES))
    try:
        return {"started": True, "job": _FETCH_JOB.start(files=files)}
    except RuntimeError:
        # Already running: the live status, not an error, so a double click is harmless.
        return {"started": False, "job": _FETCH_JOB.status()}


@router.get("/fetch/status")
def medical_fetch_status() -> dict:
    """Live status of the PubMed fetch job (state, progress, result, error)."""
    return _FETCH_JOB.status()
