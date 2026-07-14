"""
Local PDF-document import (src/ingest/pdf_import.py) — bring-your-own PDFs become
first-class corpus Articles, mirroring the .eml importer.

Includes the mandatory negative-space lens: a scanned / non-PDF file is SKIPPED and
stores NOTHING (never a fabricated body); re-importing the same PDF is deduped
(never a second Article).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, KeywordMention, Source
from src.ingest.pdf import pdf_available
from src.ingest.pdf_import import (
    PDF_IMPORT_SOURCE_DOMAIN,
    count_imported_pdfs,
    ensure_pdf_import_source,
    ingest_pdf_blobs,
    ingest_pdf_bytes,
    ingest_pdf_directory,
)

_FIX = Path(__file__).parent / "fixtures" / "pdf"
_TEXT_PDF = (_FIX / "text_statute.pdf").read_bytes()
_IMAGE_PDF = (_FIX / "scanned_image.pdf").read_bytes()

needs_pypdf = pytest.mark.skipif(not pdf_available(), reason="pypdf ([pdf] extra) not installed")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------------------------------------------------------- #
#  The happy path — a real PDF becomes a first-class corpus article
# --------------------------------------------------------------------------- #
@needs_pypdf
def test_ingest_pdf_creates_article_under_import_source(db):
    res = ingest_pdf_bytes(db, filename="Human Rights Act.pdf", data=_TEXT_PDF)
    assert res["status"] == "imported"
    art = db.get(Article, res["article_id"])
    assert "liberty and security" in art.content
    assert art.title == "Human Rights Act"  # filename (sans .pdf) is the title
    assert art.language is None  # unknown — never guessed
    # A dedicated, filterable provenance class.
    src = db.get(Source, art.source_id)
    assert src.domain == PDF_IMPORT_SOURCE_DOMAIN and src.source_type == "document"
    assert src.enabled is False  # a provenance sink, never scraped
    # It flowed through the ONE index_article hook.
    assert db.query(KeywordMention).filter_by(article_id=art.id).count() > 0


@needs_pypdf
def test_pdf_text_matching_another_source_dedups_not_errors(db):
    """A PDF whose extracted text equals an EXISTING article from another source
    (globally-unique Article.hash) must dedup — a "duplicate" result, one row, never
    an error surfaced from the collision. (Reviewer MEDIUM finding, pinned.)"""
    import hashlib

    from src.ingest.pdf import extract_pdf_text

    text, _ = extract_pdf_text(_TEXT_PDF)
    h = hashlib.sha256(text.encode()).hexdigest()
    web = Source(name="Web", domain="news.example", source_type="news")
    db.add(web)
    db.flush()
    db.add(Article(url="https://news.example/a", canonical_url="https://news.example/a",
                   source_id=web.id, title="Web copy", content=text, hash=h,
                   published_at=datetime.now(UTC)))
    db.commit()
    res = ingest_pdf_bytes(db, filename="dup.pdf", data=_TEXT_PDF)
    assert res["status"] == "duplicate"  # deduped, never an error
    assert db.query(Article).count() == 1  # no second row


@needs_pypdf
def test_reimport_same_pdf_is_deduped(db):
    a = ingest_pdf_bytes(db, filename="a.pdf", data=_TEXT_PDF)
    b = ingest_pdf_bytes(db, filename="a-again.pdf", data=_TEXT_PDF)
    assert a["status"] == "imported" and b["status"] == "duplicate"
    assert b["article_id"] == a["article_id"]
    assert db.query(Article).count() == 1  # never a second row


@needs_pypdf
def test_batch_tally_and_directory(db, tmp_path):
    (tmp_path / "one.pdf").write_bytes(_TEXT_PDF)
    (tmp_path / "scan.pdf").write_bytes(_IMAGE_PDF)  # scanned → skipped
    (tmp_path / "note.txt").write_text("not a pdf")  # ignored (not *.pdf)
    out = ingest_pdf_directory(db, str(tmp_path))
    assert out["received"] == 2  # only the two *.pdf files
    assert out["imported"] == 1 and out["skipped"] == 1
    assert db.query(Article).count() == 1


@needs_pypdf
def test_count_imported_pdfs(db):
    assert count_imported_pdfs(db) == 0  # no source yet
    ingest_pdf_bytes(db, filename="x.pdf", data=_TEXT_PDF)
    assert count_imported_pdfs(db) == 1


def test_ensure_source_is_idempotent(db):
    a = ensure_pdf_import_source(db)
    b = ensure_pdf_import_source(db)
    assert a.id == b.id and a.domain == PDF_IMPORT_SOURCE_DOMAIN


def test_pdf_import_ui_is_wired():
    """Conservative frontend guard (browser-unverified per Q6a): the Settings panel
    + handlers + endpoint URL are present, so a rename can't silently orphan the UI."""
    root = Path(__file__).resolve().parents[1] / "src" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="pdf-files"' in html and 'onclick="importPdfs(this)"' in html
    assert 'onclick="importPdfFolder(this)"' in html
    assert "function importPdfs(" in js and "function importPdfFolder(" in js
    assert "/api/documents/pdf/upload" in js and "/api/documents/pdf/import-folder" in js


# --------------------------------------------------------------------------- #
#  Negative space — degrade loudly, never fabricate a body
# --------------------------------------------------------------------------- #
def test_non_pdf_is_skipped_stores_nothing(db):
    # Runs everywhere (no pypdf needed — a non-PDF is rejected before the extractor).
    res = ingest_pdf_bytes(db, filename="page.html", data=b"<html><body>hi</body></html>")
    assert res["status"] == "skipped" and res["reason"] == "not a pdf"
    assert db.query(Article).count() == 0


@needs_pypdf
def test_scanned_pdf_is_skipped_stores_nothing(db):
    res = ingest_pdf_bytes(db, filename="scan.pdf", data=_IMAGE_PDF)
    assert res["status"] == "skipped"
    assert "scanned" in res["reason"] or "no extractable text" in res["reason"]
    assert db.query(Article).count() == 0


@needs_pypdf
def test_scanned_pdf_imported_via_ocr_is_tagged(db, monkeypatch):
    """When OCR is available, a scanned PDF imports with method 'ocr' (lower-trust)
    and is counted in the ocr tally — so the UI can flag OCR-derived documents.
    (pypdfium2 renders the real fixture; the tesseract call is stubbed.)"""
    import importlib.util

    if importlib.util.find_spec("pypdfium2") is None:
        pytest.skip("pypdfium2 ([ocr] extra) not installed")
    import pytesseract

    scanned = (Path(__file__).parent / "fixtures" / "pdf" / "scanned_text.pdf").read_bytes()
    para = ("AN ACT to protect liberty and security of the person . Section one every "
            "person shall have the right to liberty and security under the law . Section "
            "two no one shall be deprived of liberty save in accordance with a procedure "
            "established by law across the whole realm and its territories now .")
    words = para.split()
    monkeypatch.setattr("src.ingest.pdf.ocr_available", lambda: True)
    monkeypatch.setattr(
        pytesseract, "image_to_data",
        lambda image, lang=None, output_type=None, **kw: {
            "block_num": [1] * len(words), "par_num": [1] * len(words),
            "line_num": [i // 8 + 1 for i in range(len(words))],
            "conf": [90] * len(words), "text": words,
        },
    )
    out = ingest_pdf_blobs(db, [("scan.pdf", scanned)])
    assert out["imported"] == 1 and out["ocr"] == 1
    assert out["results"][0]["method"] == "ocr"
    assert db.query(Article).filter(Article.content.contains("liberty")).count() == 1


def test_blobs_batch_never_aborts_on_one_bad_file(db):
    # A mix: a non-PDF (skipped) + a corrupt PDF (skipped) — neither crashes the batch,
    # and nothing is stored (all runs without pypdf too: no valid text is produced).
    out = ingest_pdf_blobs(
        db,
        [("a.html", b"<html>x</html>"), ("b.pdf", b"%PDF-1.4 broken")],
    )
    assert out["received"] == 2 and out["imported"] == 0 and out["skipped"] == 2
    assert db.query(Article).count() == 0


# --------------------------------------------------------------------------- #
#  Endpoint smoke (isolated data dir; TestClient)
# --------------------------------------------------------------------------- #
@needs_pypdf
def test_upload_endpoint_imports_a_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post(
            "/api/documents/pdf/upload",
            files={"files": ("statute.pdf", _TEXT_PDF, "application/pdf")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tally"]["imported"] == 1
        assert c.get("/api/documents/pdf/imported-count").json()["count"] == 1
        # A non-existent folder import degrades with a 400, never a 500.
        assert c.post("/api/documents/pdf/import-folder",
                      json={"folder": "/no/such/dir"}).status_code == 400
