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


def track_document(session, fetcher, doc: LawDocument) -> dict:
    """Fetch one tracked legal document and record a baseline or a change. Honest status."""
    from src.ingest import FetchError

    now = datetime.now(UTC)
    doc.last_checked_at = now
    try:
        result = fetcher.fetch(doc.url)
    except FetchError as exc:
        doc.last_status = f"fetch error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - record, never crash the batch
        doc.last_status = f"error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}

    text = page_text(result.content)
    if len(text) < _MIN_TEXT:
        doc.last_status = "no usable text extracted"
        session.commit()
        return {"document_id": doc.id, "status": "empty"}

    h = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # First sighting → immutable baseline + a baseline revision (delta 0, not flagged).
    if doc.baseline_text is None:
        doc.baseline_text = text
        doc.baseline_hash = h
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "baseline captured"
        session.add(
            LawRevision(
                document_id=doc.id,
                observed_at=now,
                content_hash=h,
                size=len(text),
                delta_bytes=0,
                flagged=False,
            )
        )
        session.commit()
        return {"document_id": doc.id, "status": "baseline", "size": len(text)}

    if h == doc.last_hash:
        doc.last_status = "unchanged"
        session.commit()
        return {"document_id": doc.id, "status": "unchanged"}

    # A revision with this exact text was seen before → a revert to a known version.
    seen = session.query(LawRevision).filter_by(document_id=doc.id, content_hash=h).first()
    if seen is not None:
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "reverted to a previously-seen version"
        session.commit()
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
        flagged=flag.flagged,
        flag_reasons=flag.reasons_csv() if flag.flagged else None,
    )
    session.add(rev)
    doc.last_hash = h
    doc.last_size = len(text)
    doc.last_status = f"changed ({delta:+d} bytes vs baseline)"
    session.commit()
    return {
        "document_id": doc.id,
        "status": "changed",
        "delta_bytes": delta,
        "flagged": flag.flagged,
        "flag_reasons": flag.reasons,
    }


def track_watched(session, fetcher, *, limit_documents: int = 50) -> dict:
    """Track all watched legal documents, returning an aggregate tally."""
    from src.database.query import capped

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
            res = track_document(session, fetcher, doc)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law tracking: document %s failed", doc.id, exc_info=True)
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


def auto_track_due(session, fetcher, *, batch: int = 5, min_interval_hours: float = 24.0) -> dict:
    """Track a BOUNDED, freshness-gated batch of watched legal documents per collect pass
    (field test 2026-06-22, #18: the World-law tab was empty because law is only tracked
    in mode=="law", never in the default rss pass).

    Mirrors the calendar/markets auto-load: at most ``batch`` documents per call, chosen
    ROUND-ROBIN by least-recently-checked (never-checked first), and a document checked
    within ``min_interval_hours`` is skipped — so legal sites are polled politely over
    successive passes (per-host politeness + robots fail-closed + the kill switch all ride
    the shared fetcher; this only schedules the existing tracker). Best-effort + idempotent
    (track_document dedups by content hash); never raises for one bad document. Returns the
    same tally shape as track_watched plus ``due`` (how many were eligible)."""
    from datetime import timedelta

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
            res = track_document(session, fetcher, doc)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law auto-track: document %s failed", doc.id, exc_info=True)
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
