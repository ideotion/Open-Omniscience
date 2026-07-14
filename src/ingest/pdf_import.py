"""
Local PDF-document import — bring your own PDFs into the corpus as Articles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the ``.eml`` newsletter importer: a LOCAL, ZERO-NETWORK file import. Each
PDF's visible text is extracted (``src/ingest/pdf.py`` — honest about
scanned / encrypted / mis-decoded files) and stored as ONE corpus Article,
flowing through the single ``index_article`` hook so an imported PDF gets keywords
and When×Where×Who exactly like any scraped article.

Honesty by construction:
  * provenance: imported PDFs get ONE dedicated, filterable source ("Imported
    PDFs", synthetic ``pdf.import.local`` domain, ``source_type="document"``) —
    the app's non-web-provenance convention (cf. ``mailbox.import.local`` / the
    per-jurisdiction law sources), so they are a distinct provenance class the user
    can see and exclude;
  * a scanned / encrypted / mis-decoded PDF (or a non-PDF) is SKIPPED with a
    per-file reason and stores NOTHING — never a fabricated body (the same
    mis-extraction guarantee the extractor enforces);
  * dedup is by the extracted text's sha256, so re-importing the same document is
    idempotent (it never creates a second Article);
  * language stays NULL (unknown) — the deduced-language pass fills
    ``detected_language`` at index time; we never guess it.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import Article, Source

_LOG = logging.getLogger(__name__)

PDF_IMPORT_SOURCE_DOMAIN = "pdf.import.local"
PDF_IMPORT_SOURCE_NAME = "Imported PDFs"
_MIN_TEXT = 200  # a PDF that extracts less than this is treated as no usable text


def ensure_pdf_import_source(session: Session) -> Source:
    """ONE catalog source for imported PDFs — a filterable provenance class."""
    src = session.query(Source).filter_by(domain=PDF_IMPORT_SOURCE_DOMAIN).first()
    if src is None:
        src = Source(
            name=PDF_IMPORT_SOURCE_NAME,
            domain=PDF_IMPORT_SOURCE_DOMAIN,
            rss_url=None,
            enabled=False,  # a provenance sink, never scraped
            source_type="document",
        )
        session.add(src)
        session.flush()
    return src


def _clean_title(filename: str) -> str:
    base = os.path.basename((filename or "").strip())
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    return (base.strip() or "Imported PDF")[:500]


def ingest_pdf_bytes(
    session: Session,
    *,
    filename: str,
    data: bytes,
    extractor=None,
    source: Source | None = None,
) -> dict:
    """Extract ONE PDF's text and store it as a corpus Article. Honest per-file result.

    Returns ``{status: imported|duplicate|skipped, ...}``. A scanned / encrypted /
    mis-decoded PDF (or a non-PDF) is SKIPPED with a reason and stores NOTHING.
    """
    from src.ingest.pdf import extract_pdf_text

    # OCR-fallback ON: a born-digital PDF uses its exact text layer; a SCANNED one
    # falls back to OCR when the [ocr] extra + tesseract are present (else an honest
    # skip). reason == "ocr" flags the LOWER-TRUST, OCR-derived provenance.
    text, reason = extract_pdf_text(data, ocr=True)
    if not text or len(text) < _MIN_TEXT:
        return {
            "status": "skipped",
            "filename": filename,
            "reason": reason if reason != "ok" else "no usable text",
        }
    method = "ocr" if reason == "ocr" else "text"

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    # Dedup by content hash (Article.hash is unique) — re-importing is idempotent.
    existing = session.query(Article).filter_by(hash=content_hash).first()
    if existing is not None:
        return {"status": "duplicate", "filename": filename, "article_id": existing.id}

    if source is None:
        source = ensure_pdf_import_source(session)
    # A stable, unique canonical url derived from the content (no real web url exists).
    url = f"{PDF_IMPORT_SOURCE_DOMAIN}/{content_hash}"
    art = Article(
        url=url,
        canonical_url=url,
        source_id=source.id,
        title=_clean_title(filename),
        content=text,
        language=None,  # unknown — the deduced-language pass fills detected_language
        hash=content_hash,
        published_at=datetime.now(UTC),  # import date (parity with the .eml pipeline)
    )
    session.add(art)
    try:
        session.commit()
    except IntegrityError:
        # Article.hash is globally unique — a race or same-batch collision means the
        # identical document is already in the corpus. Dedup, never surface as an error.
        session.rollback()
        dup = session.query(Article).filter_by(hash=content_hash).first()
        return {
            "status": "duplicate",
            "filename": filename,
            "article_id": dup.id if dup else None,
        }

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor)
    return {
        "status": "imported",
        "filename": filename,
        "article_id": art.id,
        "method": method,  # "text" (exact layer) or "ocr" (lower-trust, may mis-read)
        "mentions": tally.get("mentions", 0),
    }


def _empty_tally() -> dict:
    return {
        "received": 0,
        "imported": 0,
        "ocr": 0,  # of the imported, how many came via OCR (lower-trust, may mis-read)
        "duplicate": 0,
        "skipped": 0,
        "results": [],
    }


def _tally_one(tally: dict, res: dict) -> None:
    tally[res["status"]] = tally.get(res["status"], 0) + 1
    if res.get("method") == "ocr":
        tally["ocr"] = tally.get("ocr", 0) + 1
    tally["results"].append(res)


def ingest_pdf_blobs(session: Session, blobs, *, extractor=None, source=None) -> dict:
    """Import a list of ``(filename, bytes)`` PDF blobs. Best-effort per blob —
    one bad file never aborts the batch; each file gets an honest result."""
    if source is None:
        source = ensure_pdf_import_source(session)
    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    tally = _empty_tally()
    for filename, data in blobs:
        tally["received"] += 1
        try:
            res = ingest_pdf_bytes(
                session, filename=filename, data=data, extractor=extractor, source=source
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the batch
            session.rollback()
            _LOG.warning("pdf import failed for %s", filename, exc_info=True)
            res = {"status": "skipped", "filename": filename, "reason": f"error: {exc}"}
        _tally_one(tally, res)
    return tally


def ingest_pdf_files(session: Session, paths, *, extractor=None, source=None) -> dict:
    """Import a list of PDF file paths from disk (reads each, then delegates)."""
    if source is None:
        source = ensure_pdf_import_source(session)
    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    tally = _empty_tally()
    for path in paths:
        filename = os.path.basename(str(path))
        tally["received"] += 1
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            res = ingest_pdf_bytes(
                session, filename=filename, data=data, extractor=extractor, source=source
            )
        except Exception as exc:  # noqa: BLE001 - a read error is one file's problem only
            session.rollback()
            _LOG.warning("pdf import failed reading %s", path, exc_info=True)
            res = {"status": "skipped", "filename": filename, "reason": f"read error: {exc}"}
        _tally_one(tally, res)
    return tally


def find_pdf_files(folder: str, *, recursive: bool = True, limit: int = 10000) -> list[str]:
    """List (bounded) ``*.pdf`` files under a server-side folder path.

    The bound is deliberate (a huge tree is the server-side folder-import job's
    job, a future slice); this collects an explicit, operator-chosen set.
    """
    out: list[str] = []
    if not os.path.isdir(folder):
        return out
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if name.lower().endswith(".pdf"):
                    out.append(os.path.join(root, name))
                    if len(out) >= limit:
                        return out
    else:
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if name.lower().endswith(".pdf") and os.path.isfile(p):
                out.append(p)
                if len(out) >= limit:
                    return out
    return out


def ingest_pdf_directory(
    session: Session, folder: str, *, extractor=None, recursive: bool = True, limit: int = 10000
) -> dict:
    """Import every ``*.pdf`` under a server-side folder path (bounded, best-effort)."""
    paths = find_pdf_files(folder, recursive=recursive, limit=limit)
    return ingest_pdf_files(session, paths, extractor=extractor)


def count_imported_pdfs(session: Session) -> int:
    """How many imported-PDF articles the corpus holds (drives the UI count)."""
    src = session.query(Source).filter_by(domain=PDF_IMPORT_SOURCE_DOMAIN).first()
    if src is None:
        return 0
    return session.query(Article).filter_by(source_id=src.id).count()
