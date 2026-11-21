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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.search_filters import AdvancedSearch, advanced_search_params
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

router = APIRouter(prefix="/api/medical", tags=["medical"])


def _fetch_worker(ctx, *, files: int, mode: str | None = None) -> dict:
    from src.medical.fetch import run_fetch
    from src.safety import transport_watch as tw

    def _progress(done: int, total: int, detail: str) -> None:
        ctx.set_progress(done=done, total=total, detail=detail)

    # R768/R772: the run is bound to the transport of the consented click, not to the one in force when its first request goes out
    # after the corpus scan: a change in between stops it, named, before anything is sent.
    with tw.run(tw.for_launch(mode if mode is not None else tw.mode_now())):
        result = run_fetch(files, progress=_progress, stopping=lambda: ctx.stopping)
    if result.get("listed") is not None:  # a run stopped before any request is no fetch, and is not recorded
        _record_for_k13(result)
    return result


def _nlm_name(name: str) -> str | None:
    """NLM's file name, rebuilt from its two sequence numbers, or None for anything that is not one."""
    from src.medical.store import FILE_NAME

    m = FILE_NAME.fullmatch(name or "")
    return f"pubmed{int(m.group(1)):02d}n{int(m.group(2)):04d}.xml.gz" if m else None


def _record_for_k13(result: dict) -> None:
    """K13's medical block (R751(a)): counts and NLM's public file name, never an id the corpus cites."""
    from datetime import UTC, datetime

    try:
        from src.medical import store as M
        from src.monitoring.kpi import _MEDICAL_COUNTS, record_medical_fetch
        from src.versioned import store

        with store.lane_session(M.LANE) as s:
            held = M.summary(s)
        newest = held["last_file"]
        raw_cov = result.get("coverage")
        cov = raw_cov if isinstance(raw_cov, dict) else {}
        record_medical_fetch({
            "fetched_at": datetime.now(UTC).isoformat(),
            "listed": int(result.get("listed") or 0),
            "remaining": int(result.get("remaining") or 0),
            "applied": len(result.get("applied") or []),
            # Whether the run stopped at a failure, never its text: the failure carries scrubbed
            # exception words, and nothing derived from them belongs in a plaintext record.
            "failed": result.get("failed") is not None,
            "stopped": bool(result.get("stopped")),
            # Keys from the record's own constant list, never the keys of the dict handed in.
            "coverage": {k: int(cov[k]) for k in _MEDICAL_COUNTS if isinstance(cov.get(k), int)},
            # Counts and a name rebuilt from NLM's own sequence numbers: nothing read here is copied whole.
            "papers": int(held["papers"]),
            "by_class": {c: int(held["by_class"].get(c, 0)) for c in ("journal", "preprint", "retracted")},
            "last_file": _nlm_name(newest["name"]) if newest else None,
        })
    except Exception:  # noqa: BLE001 - a diagnostic that cannot be written never fails the fetch it describes
        return


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
        from src.safety.transport_watch import mode_now

        return {"started": True, "job": _FETCH_JOB.start(files=files, mode=mode_now())}
    except RuntimeError:
        # Already running: the live status, not an error, so a double click is harmless.
        return {"started": False, "job": _FETCH_JOB.status()}


@router.get("/fetch/status")
def medical_fetch_status() -> dict:
    """Live status of the PubMed fetch job (state, progress, result, error)."""
    return _FETCH_JOB.status()


#: How many cited ids a single answer may look up, and how many articles it reads the links of.
_PAPERS_ARTICLE_CAP = 900


@router.get("/corpus-papers")
def medical_corpus_papers(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    expand: bool = True,
    ui_lang: str | None = None,
    sense: Annotated[list[str] | None, Query()] = None,
    literal_cap: bool = True,
    cap: int = Query(_PAPERS_ARTICLE_CAP, ge=1, le=_PAPERS_ARTICLE_CAP),
    adv: AdvancedSearch = Depends(advanced_search_params),
    db: Session = Depends(get_db),
) -> dict:
    """The kept PubMed records the analysed articles cite, BESIDE the news, never blended into it (S07-01 S1).

    Local only: the articles' own outbound links are read from ``corpus.db`` and matched against
    ``medical.db``; nothing is requested and nothing is written (a lane never fetched answers with
    every cited id counted as not found yet, and no file is created). Each paper carries its
    provenance class and the notices its record links to; an id with no kept record is COUNTED,
    never listed and never called missing from PubMed (R750)."""
    from sqlalchemy import or_, select

    from src.api.insights import _resolve_corpus
    from src.database.models import ArticleLink
    from src.medical import store as M
    from src.medical.fetch import _LINK_HINTS, GAP, cited_ids
    from src.versioned import store

    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, cap=cap, expand=expand, ui_lang=ui_lang, sense=sense,
        literal_cap=-1 if literal_cap else None, adv=adv,
    )
    urls: dict[int, list[str]] = {}
    if ids:
        hint = or_(*[ArticleLink.url.ilike(h) for h in _LINK_HINTS])
        for aid, url in db.execute(
            select(ArticleLink.article_id, ArticleLink.url).where(ArticleLink.article_id.in_(ids), hint)
        ).all():
            if url:
                urls.setdefault(int(aid), []).append(url)
    cited = {aid: w for aid, us in urls.items() if len(w := cited_ids(us))}
    if store.lane_path(M.LANE).exists():
        with store.lane_session(M.LANE) as s:
            found = M.papers_cited_by(s, cited)
            last = M.summary(s)["last_file"]
    else:
        n = sum(len(set().union(*(w._set(k) for w in cited.values()))) for k in M.WANTED_KINDS)
        found = {"papers": [], "cited": n, "found": 0, "not_found": n}  # never fetched: every cited id is not found YET
        last = None
    return {
        **found,
        "n_articles": len(ids),
        "articles_citing": len(cited),
        "total_matched": total,
        "capped": total > len(ids),
        "last_file": last,
        "gap": GAP,
        "method": (
            "The outbound links of the analysed articles are read for PubMed, PMC and DOI addresses, and each id "
            "is looked up in this install's medical.db. Nothing is requested from the network. A paper is shown "
            "with the provenance class its PubMed record states; peer review is the journal's claim, not checked here."
        ),
    }
