"""
Ingestion API: trigger ethical scraping of a source feed or a single URL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoints are synchronous (`def`) so they run in Starlette's threadpool: fetching
is blocking, rate-limited I/O and must not block the event loop. A single module
level EthicalFetcher is shared so per-host rate-limit / robots state persists
across requests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Source
from src.database.session import get_db
from src.ingest import EthicalFetcher  # noqa: F401 (kept for type/back-compat)
from src.ingest.email import (
    count_imported_newsletters,
    delete_imported_newsletters,
    fetch_imap,
    fetch_mailbox,
    ingest_emails,
)
from src.ingest.pipeline import ingest_source, ingest_url
from src.ingest.seed_sources import seed_default_sources
from src.jobs.background import BackgroundJob, register_job
from src.safety.fetcher import make_fetcher

router = APIRouter(prefix="/api", tags=["ingestion"])

# Shared fetcher: keeps robots cache + per-host rate-limit timers across requests.
_fetcher = make_fetcher()


def get_fetcher() -> EthicalFetcher:
    """Dependency returning the shared fetcher (overridable in tests)."""
    return _fetcher


class IngestUrlRequest(BaseModel):
    source_id: int
    url: str


class BatchIngestRequest(BaseModel):
    source_ids: list[int]


class IngestEmailRequest(BaseModel):
    host: str
    user: str
    password: str
    folder: str = "INBOX"
    limit: int = 50
    use_ssl: bool = True


def _get_source(db: Session, source_id: int) -> Source:
    source = db.query(Source).filter_by(id=source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source id {source_id} not found.")
    return source


@router.post("/sources/seed-defaults")
def seed_defaults_endpoint(db: Session = Depends(get_db)) -> dict:
    """Register the curated starter sources (idempotent; nothing is fetched)."""
    result = seed_default_sources(db)
    return {"seeded": result}


@router.post("/sources/{source_id}/ingest")
def ingest_source_endpoint(
    source_id: int,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Ingest a source's RSS/Atom feed through the ethical fetch path.

    Returns a tally of outcomes (stored / duplicate / blocked_robots / ...).
    """
    source = _get_source(db, source_id)
    if not source.rss_url:
        raise HTTPException(
            status_code=400,
            detail=f"Source '{source.name}' has no rss_url; use POST /api/ingest for single URLs.",
        )
    tally = ingest_source(db, source, fetcher=fetcher)
    return {"source_id": source_id, "source": source.name, "tally": tally}


@router.post("/sources/ingest-batch")
def ingest_batch_endpoint(
    req: BatchIngestRequest,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Fetch the RSS/Atom feeds of many sources in one run (the batch picker).

    Best-effort: each selected source is fetched through the same ethical path
    (robots fail-closed, rate-limited) and reported individually — one bad feed
    never aborts the batch. Bounded to 50 sources per call so a click can't kick
    off an unbounded crawl; sources without a feed are skipped with a clear status.
    Synchronous (runs in the threadpool); a queued/background variant is a future
    step for very large batches.
    """
    ids = list(dict.fromkeys(req.source_ids))[:50]  # de-dup, cap
    if not ids:
        raise HTTPException(status_code=400, detail="No source_ids provided.")
    results: list[dict] = []
    aggregate: dict[str, int] = {}
    ingested = 0
    for sid in ids:
        source = db.query(Source).filter_by(id=sid).first()
        if source is None:
            results.append({"source_id": sid, "status": "not_found"})
            continue
        if not source.rss_url:
            results.append({"source_id": sid, "source": source.name, "status": "no_feed"})
            continue
        try:
            tally = ingest_source(db, source, fetcher=fetcher)
            results.append(
                {"source_id": sid, "source": source.name, "status": "ok", "tally": tally}
            )
            ingested += 1
            for k, v in tally.items():
                if isinstance(v, int):
                    aggregate[k] = aggregate.get(k, 0) + v
        except Exception as exc:  # noqa: BLE001 - one bad feed must not abort the batch
            db.rollback()
            results.append(
                {"source_id": sid, "source": source.name, "status": "error", "detail": str(exc)}
            )
    return {"requested": len(ids), "ingested": ingested, "aggregate": aggregate, "results": results}


@router.post("/sources/{source_id}/ingest-email")
def ingest_email_endpoint(
    source_id: int,
    req: IngestEmailRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Fetch emails from an IMAP mailbox and fold them into the corpus.

    Credentials are used transiently (not stored). Emails become searchable
    Article rows under the given source. Single-user, loopback-only by design.
    """
    source = _get_source(db, source_id)
    try:
        raws = fetch_imap(
            req.host,
            req.user,
            req.password,
            folder=req.folder,
            limit=req.limit,
            use_ssl=req.use_ssl,
        )
    except RuntimeError as exc:  # the airplane-mode refusal (ruling #11 kill-switch gate)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    tally = ingest_emails(db, source, raws)
    return {"source_id": source_id, "source": source.name, "fetched": len(raws), "tally": tally}


# A single dedicated, FILTERABLE provenance bucket for locally-imported .eml
# newsletters (email-vs-web stays separable, like the DDG-discovered class). It is
# DISABLED so the scheduler never touches it — these articles arrive ONLY by explicit
# local file import, never the network. (Per-publisher eTLD+1 source resolution — the
# S2 design — is a deliberate follow-up; v1 never fuzzy-merges, the conservative call.)
_NEWSLETTER_DOMAIN = "newsletters.import.local"
_NEWSLETTER_NAME = "Imported newsletters (.eml)"

# Content-provenance S1: the ingest channel is an ASSERTED FACT (this path IS the
# newsletter channel), so stamp it — never the Source.source_type default "news",
# which mislabelled every imported newsletter as news. A newsletter is a CHANNEL,
# not a credibility judgement. Both the .eml and the mailbox paths are this channel.
_IMPORT_SOURCE_TYPE = "newsletter"


def _ensure_import_source(db: Session, *, domain: str, name: str) -> Source:
    """Get-or-create a local import source, stamping the newsletter provenance and
    self-healing any pre-existing row that still carries the mislabelled default
    (deterministic, idempotent, no migration)."""
    src = db.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(
            name=name, domain=domain, enabled=False, source_type=_IMPORT_SOURCE_TYPE
        )
        db.add(src)
        db.commit()
        db.refresh(src)
    elif src.source_type != _IMPORT_SOURCE_TYPE:
        src.source_type = _IMPORT_SOURCE_TYPE  # backfill a source created before S1
        db.commit()
        db.refresh(src)
    return src


def _get_newsletter_source(db: Session) -> Source:
    return _ensure_import_source(db, domain=_NEWSLETTER_DOMAIN, name=_NEWSLETTER_NAME)


@router.get("/newsletters/publisher-preview")
def newsletter_publisher_preview(db: Session = Depends(get_db)) -> dict:
    """Which publisher each imported newsletter WOULD be filed under.

    A PREVIEW, not an action: the 2026-06-15 ruling pairs silent auto-attach with
    an import UI that announces it and an undo for the automated attaches, so the
    attach is not wired until those exist. This endpoint runs the real resolver
    over the newsletters already in the corpus so the decision can be reviewed
    against evidence rather than described -- and so the resolver has a caller
    that is not a test.

    Loopback and read-only: no write, no network (the Public Suffix List is a
    vendored snapshot). A plain ``def`` so the DB work runs in the threadpool
    rather than freezing the single event loop.
    """
    from src.ingest.newsletter_source import resolution_preview

    return resolution_preview(db)


# Starlette's MultiPartParser defaults to max_files=1000, so a selection of ~1300
# .eml files returned HTTP 400 "Too many files" (maintainer field test 2026-06-20).
# We parse the form ourselves with a higher cap for this local, single-user upload.
# A TRULY huge set (20 GB+) is the server-side folder-import job's job; this upload
# path comfortably handles thousands.
_MAX_UPLOAD_FILES = 5000


@router.post("/newsletters/import")
async def import_newsletters(request: Request, db: Session = Depends(get_db)) -> dict:
    """Import local ``.eml`` newsletter files into the unified corpus, ANONYMISED at
    ingest. **ZERO network**: each file is parsed, de-tracked and stored locally —
    nothing is ever fetched (tracker pixels / wrapped links are NEVER followed, so an
    import can never confirm an open or a click). The recipient is never stored; the
    returned tally reports exactly what anonymisation stripped (recipient echoes
    redacted, tracker query-params removed, server-side tracker wrappers flagged) so
    the user sees it honestly. Local-only, single-user, loopback by design.

    The form is parsed with ``max_files`` raised above Starlette's 1000 default so a
    large selection no longer 400s; a truly huge set should use the folder import.
    """
    try:
        form = await request.form(max_files=_MAX_UPLOAD_FILES, max_fields=_MAX_UPLOAD_FILES + 100)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many files in one upload (cap {_MAX_UPLOAD_FILES}). For a very large "
                f"set, import from a folder instead. ({exc})"
            ),
        ) from exc
    from starlette.datastructures import UploadFile

    # isinstance rather than hasattr("filename"): the same set of objects (only
    # UploadFile has that attribute), and it narrows the UploadFile | str union
    # for the .read() below.
    files = [v for v in form.getlist("files") if isinstance(v, UploadFile)]
    raws: list[bytes] = []
    skipped_non_eml = 0
    for f in files:
        name = (getattr(f, "filename", "") or "").lower()
        if not name.endswith(".eml"):
            skipped_non_eml += 1
            continue
        try:
            raws.append(await f.read())
        except Exception:
            skipped_non_eml += 1
    # Heavy sync work (parse + anonymise + index_article per message) runs OFF the
    # event loop -- this is an async def handler, so without this a multi-thousand-
    # message import freezes the single-worker server for its whole duration (the
    # same async-def-doing-sync-work family already fixed for unlock/restore-preview/
    # /api/articles; the sibling upload_pdfs handler already does this correctly).
    #
    # S3.6 (2026-09-07) closed the two SMALL uses the 2026-07-17 fix left behind. They
    # are one row each, which is why they read as harmless -- but get-or-create COMMITS,
    # and a commit on the event loop waits for the single-writer gate like any other:
    # under a held gate (measured at 6,236 s of wait in the field) it blocks every
    # request in the process, from a one-row insert. The rollback is the same call on
    # the error path. The rule this slice ships is the simple one a guard can hold the
    # line on -- the session is NEVER touched on the loop -- not "only the big ones".
    from starlette.concurrency import run_in_threadpool

    source = await run_in_threadpool(_get_newsletter_source, db)
    try:
        tally = await run_in_threadpool(ingest_emails, db, source, raws)
    except Exception as exc:  # ingest_emails is total; never let storage escape as a raw 500
        await run_in_threadpool(db.rollback)
        raise HTTPException(
            status_code=500,
            detail=f"Newsletter import failed while storing: {exc}",
        ) from exc
    tally["skipped_non_eml"] = skipped_non_eml
    return {
        "source": source.name,
        "source_id": source.id,
        "received": len(files),
        "tally": tally,
    }


class RemoveNewslettersBody(BaseModel):
    confirm: bool = False


@router.get("/newsletters/imported-count")
def imported_newsletters_count(db: Session = Depends(get_db)) -> dict:
    """How many imported-newsletter articles the live corpus holds (drives the confirm
    preview + showing the maintenance button only when there is something to remove)."""
    return {"count": count_imported_newsletters(db)}


@router.post("/newsletters/remove-imported")
def remove_imported_newsletters(
    body: RemoveNewslettersBody, db: Session = Depends(get_db)
) -> dict:
    """Remove ALL imported-newsletter (.eml + mailbox) articles from the LIVE corpus.

    The "replace the faulty ones" loop: restore is additive-only, so excluding
    newsletters from a backup never purges the live corpus — this does. Deletes the
    newsletter-source articles AND every dependent row, leaving the (empty) source rows
    so a future clean re-import re-attaches. Reversible ONLY via a prior backup — the UI
    nudges "back up first" and requires an explicit confirm. Local-only, no network.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm:true is required")
    result = delete_imported_newsletters(db)
    return {"removed": True, **result}


# --------------------------------------------------------------------------- #
# Local PDF-document import (mirrors the .eml importer): bring your own PDFs into
# the corpus as Articles. ZERO network — each file is extracted + stored locally.
# A scanned / encrypted / mis-decoded PDF is SKIPPED with an honest reason and
# stores NOTHING (never a fabricated body). Dedup by content hash ⇒ idempotent.
# --------------------------------------------------------------------------- #
_MAX_PDF_UPLOAD_FILES = 2000
_MAX_PDF_BYTES = 200 * 1024 * 1024  # per-file bound so one huge upload can't OOM the worker


@router.post("/documents/pdf/upload")
async def upload_pdfs(request: Request, db: Session = Depends(get_db)) -> dict:
    """Import local PDF files into the unified corpus. ZERO network: each PDF is
    parsed and its text extracted locally (nothing is ever fetched). A scanned /
    encrypted / mis-decoded PDF is SKIPPED with an honest reason and stores NOTHING.
    Dedup is by content hash, so re-importing the same document is idempotent."""
    from starlette.concurrency import run_in_threadpool
    from starlette.datastructures import UploadFile

    from src.ingest.pdf import looks_like_pdf
    from src.ingest.pdf_import import ingest_pdf_blobs

    try:
        form = await request.form(
            max_files=_MAX_PDF_UPLOAD_FILES, max_fields=_MAX_PDF_UPLOAD_FILES + 100
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many files in one upload (cap {_MAX_PDF_UPLOAD_FILES}). For a very "
                f"large set, import from a folder instead. ({exc})"
            ),
        ) from exc
    blobs: list[tuple[str, bytes]] = []
    skipped_non_pdf = 0
    for f in form.getlist("files"):
        if not isinstance(f, UploadFile):
            continue
        name = f.filename or ""
        try:
            # Bounded read (cap+1): a file over the cap materialises only cap+1 bytes,
            # then is skipped — one huge upload can't balloon RAM on the single worker.
            data = await f.read(_MAX_PDF_BYTES + 1)
        except Exception:
            skipped_non_pdf += 1
            continue
        if len(data) > _MAX_PDF_BYTES:
            skipped_non_pdf += 1  # oversize — honest skip, never a crash
            continue
        if not name.lower().endswith(".pdf") and not looks_like_pdf(data):
            skipped_non_pdf += 1
            continue
        blobs.append((name, data))
    # Heavy sync work (extract + index_article per file) runs OFF the event loop so a
    # multi-PDF import never freezes the single-worker server.
    tally = await run_in_threadpool(ingest_pdf_blobs, db, blobs)
    tally["skipped_non_pdf"] = skipped_non_pdf
    return {"received": len(blobs) + skipped_non_pdf, "tally": tally}


@router.get("/documents/pdf/imported-count")
def imported_pdfs_count(db: Session = Depends(get_db)) -> dict:
    """How many imported-PDF articles the corpus holds (drives the UI)."""
    from src.ingest.pdf_import import count_imported_pdfs

    return {"count": count_imported_pdfs(db)}


class PdfFolderBody(BaseModel):
    folder: str


@router.post("/documents/pdf/import-folder")
def import_pdf_folder(body: PdfFolderBody, db: Session = Depends(get_db)) -> dict:
    """Import every PDF under a server-side folder path (bounded, best-effort).

    ZERO network (local disk read). Heavy work runs off the event loop. 400 on a
    folder that does not exist. A very large tree is the future folder-import JOB's
    job (pausable + task-manager-visible, the .eml pattern) — this bounded pass
    handles an operator-chosen directory now.

    S3.6: a plain ``def``, not ``async def`` + ``run_in_threadpool``. Its two siblings
    above MUST be async -- they await the upload stream -- but this one takes a JSON
    body, so it never needed the loop at all: the old shape started on the loop only to
    bounce straight back off it. Starlette runs a sync path operation in its threadpool,
    which is the same place the work ran before and one hop closer."""
    import os

    from src.ingest.pdf_import import ingest_pdf_directory

    folder = (body.folder or "").strip()
    if not folder or not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail=f"Not a folder: {folder!r}")
    tally = ingest_pdf_directory(db, folder)
    return {"folder": folder, "tally": tally}


# --------------------------------------------------------------------------- #
# Server-side .eml FOLDER import as a pausable, task-manager-visible job (§2.B):
# the 20 GB+ case the small-file upload can't handle. Zero network (local disk).
# --------------------------------------------------------------------------- #
class FolderImportBody(BaseModel):
    folder: str


@router.post("/newsletters/import-folder")
def start_folder_import(body: FolderImportBody) -> dict:
    """Start importing every ``.eml`` under a server-side folder path as a background
    job (pausable, visible in the task manager). 400 on a bad folder; 409 if one runs."""
    from src.ingest.import_job import get_import_manager

    try:
        return get_import_manager().start(body.folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/newsletters/import-folder/status")
def folder_import_status() -> dict:
    """Live state of the (single) folder-import job — for the UI + /api/jobs."""
    from src.ingest.import_job import get_import_manager

    return get_import_manager().status()


@router.post("/newsletters/import-folder/{action}")
def folder_import_action(action: str) -> dict:
    """Pause / resume / cancel the running folder import."""
    from src.ingest.import_job import get_import_manager

    mgr = get_import_manager()
    if action == "pause":
        mgr.pause()
    elif action == "resume":
        try:
            return mgr.resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif action == "cancel":
        mgr.cancel()
    else:
        raise HTTPException(status_code=404, detail=f"unknown action {action}")
    return mgr.status()


# A dedicated, FILTERABLE provenance bucket for LIVE mailbox (IMAP/POP3) imports —
# DISTINCT from the file-.eml bucket so live-vs-file provenance stays separable (the
# ledger's email-vs-web separability principle). DISABLED: the scheduler never touches
# it; mail arrives only by explicit, consented pull.
_MAILBOX_DOMAIN = "mailbox.import.local"
_MAILBOX_NAME = "Imported mailbox (IMAP/POP3)"


def _get_mailbox_source(db: Session) -> Source:
    # A pulled mailbox is the same newsletter CHANNEL (content-provenance S1);
    # stamp + self-heal so it is never mislabelled "news".
    return _ensure_import_source(db, domain=_MAILBOX_DOMAIN, name=_MAILBOX_NAME)


class MailboxFetchRequest(BaseModel):
    protocol: str = "imap"  # "imap" | "pop3"
    host: str
    user: str
    password: str
    port: int = 0  # 0 = protocol default (993/995 SSL, 143/110 plain)
    folder: str = "INBOX"  # IMAP only
    limit: int = 50
    use_ssl: bool = True


_MAILBOX_DISCLOSURE = (
    "Pulled live from your mailbox over TLS and anonymised at ingest: the "
    "recipient is never stored, no raw message is retained, tracking links are "
    "de-toxed and never followed. Your IP is visible to the mail provider (not "
    "via Tor). Stored under a disabled, filterable 'mailbox' source."
)


def _scrub(text: str, secret: str) -> str:
    """Never let the password reach a job status.

    ``BackgroundJob.status()`` does not expose the worker's kwargs, so the credential
    itself stays on the thread — but it DOES expose ``error``, and a mail library's
    exception is the server's own protocol chatter, which is one server bug away from
    echoing the line it was sent. ``/api/jobs`` is unauthenticated (loopback-only, and
    that is the boundary, not an excuse), so the message is scrubbed at the point it is
    captured rather than trusted not to contain it.
    """
    return text.replace(secret, "***") if secret else text


def _mailbox_pull_worker(
    ctx,
    *,
    protocol: str,
    host: str,
    user: str,
    password: str,
    port: int,
    folder: str,
    limit: int,
    use_ssl: bool,
) -> dict:
    """Fetch + anonymise-at-ingest, off the request thread. Opens its OWN session."""
    from src.database.session import session_scope

    kwargs: dict = {"limit": limit, "use_ssl": use_ssl}
    if port:
        kwargs["port"] = port
    if protocol == "imap":
        kwargs["folder"] = folder
    ctx.set_progress(detail=f"connecting to {host} over {protocol.upper()}")
    try:
        raws = fetch_mailbox(protocol, host, user, password, **kwargs)
    except Exception as exc:
        raise RuntimeError(_scrub(f"mailbox fetch failed: {exc}", password)) from None
    ctx.set_progress(done=0, total=len(raws), detail=f"anonymising {len(raws)} message(s)")
    with session_scope() as db:
        source = _get_mailbox_source(db)
        tally = ingest_emails(db, source, raws)
        out = {
            "source": source.name,
            "source_id": source.id,
            "protocol": protocol,
            "fetched": len(raws),
            "tally": tally,
            "disclosure": _MAILBOX_DISCLOSURE,
        }
    ctx.set_progress(done=len(raws), total=len(raws), detail="done")
    return out


# A live mailbox pull is a NETWORK fetch of up to `limit` messages followed by a full
# anonymise-and-store pass -- minutes of work that ran synchronously in the request
# handler, so it froze the app and was invisible to /api/jobs: the operator could not
# see it, and the task manager's Stop could not reach it. It is a DB writer, so it
# joins the writer-arbitration set.
#
# cancellable=False is the HONEST setting, not a shortcut: `fetch_mailbox` is one
# opaque imaplib/poplib call and `ingest_emails` loops internally without a ctx, so
# nothing here checks ctx.stopping. Advertising a Cancel button that cannot stop the
# work is the theater this module's own docstring rules out.
_MAILBOX_JOB = register_job(
    BackgroundJob("mailbox-pull", "Pulling newsletters from your mailbox", _mailbox_pull_worker,
                  is_writer=True)
)


@router.post("/newsletters/mailbox")
def import_mailbox(req: MailboxFetchRequest) -> dict:
    """Pull newsletters LIVE from a mailbox (IMAP/POP3), ANONYMISED at ingest (ruling #11).

    The maintainer reversed the local-.eml-only stance: this fetches messages directly so
    you do not have to export .eml files. Each message goes through the SAME anonymise-at-
    ingest core as the file import — the recipient is NEVER stored, no raw message is
    retained, and tracking links are de-toxed (pixels/wrapped links are NEVER followed, so
    a pull can never confirm an open/click). Credentials are used for this one fetch and
    NOT stored.

    NETWORK + HONESTY: this is a consented network action — it is REFUSED under airplane
    mode (409, no socket), named as the kill switch rather than reported as a mailbox
    problem. The connection egresses to your mail provider directly over TLS (like any
    email client), revealing your IP to that provider; it is NOT routed through Tor
    (IMAP/POP3 is not the HTTP guarded path). The tally reports exactly what anonymisation
    stripped, so you see it honestly.

    RUNS AS A BACKGROUND JOB. The network-free checks (protocol, host/user) still answer
    synchronously with a 422, and the airplane refusal still with a 409 before any socket;
    everything after that is polled from ``/newsletters/mailbox/status`` or watched in the
    task manager. A transport or auth failure is therefore a job ``error`` rather than the
    old inline 502 — the same trade the other background jobs already accepted, and the
    reason the pull no longer holds a threadpool token (and the single-writer gate) for
    its whole run.
    """
    from src.ingest import kill_switch_active

    proto = (req.protocol or "").strip().lower()
    if proto not in ("imap", "pop3"):
        raise HTTPException(
            status_code=422, detail=f"unknown mailbox protocol: {req.protocol!r} (use 'imap' or 'pop3')"
        )
    if not (req.host or "").strip() or not (req.user or "").strip():
        raise HTTPException(status_code=422, detail="host and user are required")
    if kill_switch_active():
        raise HTTPException(
            status_code=409, detail="network refused: airplane mode is engaged (kill switch)"
        )
    started = {
        "protocol": proto,
        "host": req.host.strip(),
        "user": req.user.strip(),
        "password": req.password,
        "port": req.port,
        "folder": req.folder,
        "limit": req.limit,
        "use_ssl": req.use_ssl,
    }
    try:
        return {"started": True, "job": _MAILBOX_JOB.start(**started), "disclosure": _MAILBOX_DISCLOSURE}
    except RuntimeError:
        return {"started": False, "job": _MAILBOX_JOB.status(), "disclosure": _MAILBOX_DISCLOSURE}


@router.get("/newsletters/mailbox/status")
def import_mailbox_status() -> dict:
    """Live status of the background mailbox pull (never carries the credential)."""
    return _MAILBOX_JOB.status()


@router.post("/ingest")
def ingest_url_endpoint(
    req: IngestUrlRequest,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Ingest a single article URL under the given source."""
    source = _get_source(db, req.source_id)
    outcome = ingest_url(db, source, req.url, fetcher=fetcher)
    return {
        "url": outcome.url,
        "result": outcome.result.value,
        "article_id": outcome.article_id,
        "detail": outcome.detail,
    }
