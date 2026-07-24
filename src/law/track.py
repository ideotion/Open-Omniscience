"""
Law change-tracking — baseline snapshot → per-change diff → honest flag.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the Wikipedia tracker (``src/wiki/track.py``) for arbitrary legal documents
fetched through the **ethical, robots-fail-closed** fetcher. The first successful fetch
is the immutable **baseline** ("the law as it stood on date X"); every later fetch whose
*normalised visible text* differs records a :class:`LawRevision` carrying the byte delta,
a capped unified **diff** against the baseline, and an honest large-change flag (reusing
the wiki flagging thresholds — mutualisation). Nothing is interpreted; a change is
*surfaced*, never judged. A fetch error degrades **loudly** (recorded status), never
fabricated.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from datetime import UTC, datetime

from src.database.models import LawDocument, LawRevision
from src.database.write import is_integrity_error
from src.wiki.flagging import flag_revision

_LOG = logging.getLogger(__name__)

_MIN_TEXT = 200  # below this we treat extraction as failed, not a real document
_MAX_DIFF_LINES = 4000  # cap stored diff size (bounded, like the crawler)
_WS_RE = re.compile(r"[ \t]+")


def page_text(html: str) -> str:
    """Normalised visible text of an HTML page — a stable basis for change detection.

    Strips script/style/nav/footer/header chrome and collapses whitespace, so a real
    amendment produces a diff while cosmetic re-rendering does not.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - bs4 is a core dependency
        return re.sub(r"<[^>]+>", " ", html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    lines = [_WS_RE.sub(" ", ln).strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _diff(baseline: str, new: str) -> str:
    """A capped unified diff of baseline → new (added/removed lines only)."""
    diff_lines = list(
        difflib.unified_diff(baseline.splitlines(), new.splitlines(), lineterm="", n=1)
    )
    changed = [ln for ln in diff_lines if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    return "\n".join(changed[:_MAX_DIFF_LINES])


def _document_text(result) -> tuple[str | None, str]:
    """The document's normalised visible text + an honest status.

    A PDF body (detected by the ``%PDF`` magic bytes or the content-type) is
    routed to the optional PDF extractor, which returns ``(None, reason)`` for a
    scanned / encrypted / mis-decoded file — degrade LOUDLY, never a fabricated
    body. Everything else is treated as HTML/text and reduced by ``page_text``.
    """
    raw = getattr(result, "raw_content", None)
    content_type = getattr(result, "content_type", "") or ""
    from src.ingest.pdf import looks_like_pdf

    if looks_like_pdf(raw, content_type=content_type):
        from src.ingest.pdf import extract_pdf_text

        return extract_pdf_text(raw)
    return page_text(result.content), "ok"


def _ingest_to_corpus(session, doc: LawDocument, extractor) -> None:
    """Ingest the document's newest text into the corpus (laws are Articles too).

    Best-effort by construction: the text + revision are ALREADY committed before
    this runs, so a corpus-sync failure must NEVER block or roll back tracking —
    it is rolled back locally and logged (the wiki-corpus pattern).
    """
    try:
        from src.law.corpus import sync_law_to_corpus

        sync_law_to_corpus(session, doc, extractor=extractor)
    except Exception:  # noqa: BLE001 - corpus ingest is best-effort, never blocks tracking
        session.rollback()
        _LOG.warning("law corpus ingest failed for doc %s", doc.id, exc_info=True)


def track_document(session, fetcher, doc: LawDocument, *, extractor=None) -> dict:
    """Fetch one tracked legal document and record a baseline or a change. Honest status.

    On a successful baseline / change / revert (and a first-time backfill on an
    unchanged poll) the document's NEWEST text is materialised on the document
    (``latest_text`` / ``latest_text_revid``) and, for a new version, stored in
    full on the :class:`LawRevision` (``full_text``) — the versioned-sources
    model (a law = an Article + a linked revision/audit trail). The text is then
    ingested into the corpus through the one ``index_article`` hook.
    """
    from src.ingest import FetchError

    now = datetime.now(UTC)
    doc.last_checked_at = now
    try:
        # require_html=False so an official-gazette PDF is not rejected up front;
        # keep_bytes so the PDF extractor sees the real bytes (the text decode
        # destroys them). Both are additive — a fetcher double without keep_bytes
        # simply won't set raw_content, and the HTML path is unchanged.
        result = fetcher.fetch(doc.url, require_html=False, keep_bytes=True)
    except FetchError as exc:
        doc.last_status = f"fetch error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - record, never crash the batch
        doc.last_status = f"error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}

    text, reason = _document_text(result)
    if not text or len(text) < _MIN_TEXT:
        # Degrade loudly: a scanned/encrypted/mis-decoded PDF (or too-short HTML)
        # records WHY and stores NO body — never a fabricated one.
        doc.last_status = reason if reason != "ok" else "no usable text extracted"
        session.commit()
        return {"document_id": doc.id, "status": "empty", "detail": doc.last_status}

    h = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # First sighting → immutable baseline + a baseline revision (delta 0, not flagged).
    if doc.baseline_text is None:
        doc.baseline_text = text
        doc.baseline_hash = h
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "baseline captured"
        doc.latest_text = text  # the CURRENT text, shown without replaying diffs
        rev = LawRevision(
            document_id=doc.id,
            observed_at=now,
            content_hash=h,
            size=len(text),
            delta_bytes=0,
            full_text=text,  # the exact baseline text, locally reconstructable
            flagged=False,
        )
        session.add(rev)
        try:
            session.flush()  # materialise rev.id so latest_text_revid can anchor it
            doc.latest_text_revid = rev.id
            session.commit()
        except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
            # Audit finding 2026-07-17: `except IntegrityError` (sqlalchemy.exc) never
            # matched on the encrypted (sqlcipher3) store, whose driver raises its OWN
            # unwrapped exception class -- the same cross-driver divergence already
            # fixed for is_locked_error/classify_restore_error/_is_integrity_error.
            # A genuinely unexpected failure must still surface, never be swallowed.
            if not is_integrity_error(exc):
                raise
            # This (document_id, content_hash) baseline revision already exists (a
            # concurrent pass or a re-process). IDEMPOTENT: roll back the poisoned
            # transaction so it can NEVER roll back the whole scrape pass, then cache
            # the baseline so the next pass takes the fast "unchanged" path.
            session.rollback()
            doc.baseline_text = text
            doc.baseline_hash = h
            doc.last_checked_at = now
            doc.last_hash = h
            doc.last_size = len(text)
            doc.last_status = "baseline already recorded"
            doc.latest_text = text
            existing = (
                session.query(LawRevision)
                .filter_by(document_id=doc.id, content_hash=h)
                .first()
            )
            if existing:  # keep any prior anchor rather than nulling it on a miss
                doc.latest_text_revid = existing.id
            session.commit()
            _ingest_to_corpus(session, doc, extractor)
            return {"document_id": doc.id, "status": "duplicate"}
        _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "baseline", "size": len(text)}

    if h == doc.last_hash:
        doc.last_status = "unchanged"
        # Backfill the materialised text for a document baselined before this
        # feature shipped, then ingest it once (idempotent: an unchanged corpus
        # hash re-index is skipped, so a steady-state poll adds no work).
        backfilled = doc.latest_text is None
        if backfilled:
            doc.latest_text = text
            doc.latest_text_revid = doc.latest_text_revid or (
                session.query(LawRevision.id)
                .filter_by(document_id=doc.id, content_hash=h)
                .order_by(LawRevision.id.asc())
                .limit(1)
                .scalar()
            )
        session.commit()
        if backfilled:
            _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "unchanged"}

    # A revision with this exact text was seen before → a revert to a known version.
    seen = session.query(LawRevision).filter_by(document_id=doc.id, content_hash=h).first()
    if seen is not None:
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "reverted to a previously-seen version"
        doc.latest_text = text
        doc.latest_text_revid = seen.id
        session.commit()
        _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "reverted"}

    # A genuine new version: record the change vs the immutable baseline.
    delta = len(text) - (len(doc.baseline_text or "") or doc.last_size or 0)
    flag = flag_revision(delta_bytes=delta)
    rev = LawRevision(
        document_id=doc.id,
        observed_at=now,
        content_hash=h,
        size=len(text),
        delta_bytes=delta,
        diff=_diff(doc.baseline_text or "", text),
        full_text=text,  # the exact new version, locally reconstructable
        flagged=flag.flagged,
        flag_reasons=flag.reasons_csv() if flag.flagged else None,
    )
    session.add(rev)
    doc.last_hash = h
    doc.last_size = len(text)
    doc.last_status = f"changed ({delta:+d} bytes vs baseline)"
    doc.latest_text = text
    try:
        session.flush()  # materialise rev.id so latest_text_revid can anchor it
        doc.latest_text_revid = rev.id
        session.commit()
    except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
        # Audit finding 2026-07-17: same cross-driver fix as the baseline-capture
        # branch above -- see its comment.
        if not is_integrity_error(exc):
            raise
        # This (document_id, content_hash) revision already exists — a concurrent pass or
        # a re-process. IDEMPOTENT: roll back so a duplicate can never poison and roll back
        # the whole scrape pass, then just advance the doc's last-seen state.
        session.rollback()
        doc.last_checked_at = now
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "version already recorded"
        doc.latest_text = text
        existing = (
            session.query(LawRevision)
            .filter_by(document_id=doc.id, content_hash=h)
            .first()
        )
        if existing:  # keep any prior anchor rather than nulling it on a miss
            doc.latest_text_revid = existing.id
        session.commit()
        _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "duplicate"}
    _ingest_to_corpus(session, doc, extractor)
    return {
        "document_id": doc.id,
        "status": "changed",
        "delta_bytes": delta,
        "flagged": flag.flagged,
        "flag_reasons": flag.reasons,
    }


def _batch_extractor(extractor):
    """Build the keyword extractor ONCE per batch (laws index like any article)."""
    if extractor is not None:
        return extractor
    from src.analytics.extract import BaselineExtractor

    return BaselineExtractor()


def track_watched(session, fetcher, *, limit_documents: int = 50, extractor=None) -> dict:
    """Track all watched legal documents, returning an aggregate tally."""
    from src.database.query import capped

    extractor = _batch_extractor(extractor)
    docs = capped(
        session.query(LawDocument).filter_by(watched=True).order_by(LawDocument.id.asc()),
        limit_documents,  # 0 = every watched document (no cap)
    ).all()
    tally = {
        "documents": 0,
        "baselines": 0,
        "changed": 0,
        "flagged": 0,
        "errors": 0,
        "unchanged": 0,
    }
    for doc in docs:
        try:
            res = track_document(session, fetcher, doc, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law tracking: document %s failed", doc.id, exc_info=True)
            session.rollback()  # clear a poisoned transaction so it can't roll back the batch
            tally["errors"] += 1
            continue
        tally["documents"] += 1
        status = res.get("status")
        if status == "baseline":
            tally["baselines"] += 1
        elif status == "changed":
            tally["changed"] += 1
            if res.get("flagged"):
                tally["flagged"] += 1
        elif status == "error":
            tally["errors"] += 1
        elif status == "unchanged":
            tally["unchanged"] += 1
    return tally


def adaptive_track_budget(
    watched_count: int, *, min_batch: int = 5, max_batch: int = 25, divisor: int = 20
) -> int:
    """The per-pass tracking budget, SCALED to the size of the watched-document set
    (2026-07-24 field-feedback Session A, item 3: "auto_track_due's batch=5/24h
    cannot baseline hundreds of docs -- make the per-pass budget adaptive").

    Bounded both ways: today's small watched set (~23 documents) still resolves to
    ``min_batch`` — the ORIGINAL hardcoded default, so nothing changes on a typical
    install — while a large one (once enumeration adapters register hundreds of
    documents per jurisdiction) climbs toward ``max_batch`` instead of crawling at
    5/pass forever, but a single pass never floods legal sites beyond that cap."""
    if watched_count <= 0:
        return min_batch
    return max(min_batch, min(max_batch, watched_count // max(1, divisor)))


def auto_track_due(
    session, fetcher, *, batch: int | None = None, min_interval_hours: float = 24.0, extractor=None
) -> dict:
    """Track a BOUNDED, freshness-gated batch of watched legal documents per collect pass
    (field test 2026-06-22, #18: the World-law tab was empty because law is only tracked
    in mode=="law", never in the default rss pass).

    Mirrors the calendar/markets auto-load: at most ``batch`` documents per call, chosen
    ROUND-ROBIN by least-recently-checked (never-checked first), and a document checked
    within ``min_interval_hours`` is skipped — so legal sites are polled politely over
    successive passes (per-host politeness + robots fail-closed + the kill switch all ride
    the shared fetcher; this only schedules the existing tracker). Best-effort + idempotent
    (track_document dedups by content hash); never raises for one bad document. Returns the
    same tally shape as track_watched plus ``due`` (how many were eligible).

    ``batch=None`` (the default) computes an ADAPTIVE budget from the total watched
    count via :func:`adaptive_track_budget` — pass an explicit int to keep the old
    fixed-batch behaviour (tests do, deliberately, for determinism)."""
    from datetime import timedelta

    extractor = _batch_extractor(extractor)
    if batch is None:
        watched_count = session.query(LawDocument).filter_by(watched=True).count()
        batch = adaptive_track_budget(watched_count)
    cutoff = datetime.now(UTC) - timedelta(hours=min_interval_hours)
    q = session.query(LawDocument).filter_by(watched=True).filter(
        # never-checked (NULL) OR stale beyond the interval
        (LawDocument.last_checked_at.is_(None)) | (LawDocument.last_checked_at < cutoff)
    )
    due_total = q.count()
    # least-recently-checked first; NULLs (never checked) sort first so a fresh corpus
    # builds its baselines before re-checking anything.
    docs = (
        q.order_by(LawDocument.last_checked_at.is_(None).desc(), LawDocument.last_checked_at.asc())
        .limit(max(0, batch))
        .all()
    )
    tally = {"documents": 0, "baselines": 0, "changed": 0, "flagged": 0,
             "errors": 0, "unchanged": 0, "due": due_total}
    for doc in docs:
        try:
            res = track_document(session, fetcher, doc, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law auto-track: document %s failed", doc.id, exc_info=True)
            session.rollback()  # clear a poisoned txn so one dup can't roll back the WHOLE pass
            tally["errors"] += 1
            continue
        tally["documents"] += 1
        status = res.get("status")
        if status == "baseline":
            tally["baselines"] += 1
        elif status == "changed":
            tally["changed"] += 1
            if res.get("flagged"):
                tally["flagged"] += 1
        elif status == "error":
            tally["errors"] += 1
        elif status == "unchanged":
            tally["unchanged"] += 1
    return tally
