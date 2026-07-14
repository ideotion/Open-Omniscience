"""
PDF text extraction (src/ingest/pdf.py), with an HONEST testing strategy for the
maintainer's concern ("maybe it won't work; text could be mis-extracted").

Three layers so a green run is never vacuous:
  1. REAL extraction against committed fixture PDFs (a text statute + a scanned /
     image-only PDF), skip-guarded on the optional pypdf ([pdf] extra) so they run
     for real in CI and skip on a core install;
  2. the DEGRADE + mis-extraction GUARD paths (not-a-pdf, corrupt, empty, extractor
     absent, symbol-garbage) — these run EVERYWHERE, including a core install;
  3. detection (magic bytes + content-type).

The fixtures are committed bytes (generated once with reportlab), so CI needs no
PDF-generator dependency — only pypdf (the runtime extractor) via [pdf].

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.pdf import (
    _looks_like_real_text,
    _reconstruct_ocr_text,
    extract_pdf_text,
    looks_like_pdf,
    ocr_available,
    ocr_pdf,
    pdf_available,
)

_FIX = Path(__file__).parent / "fixtures" / "pdf"
_TEXT_PDF = _FIX / "text_statute.pdf"
_IMAGE_PDF = _FIX / "scanned_image.pdf"
_SCANNED_TEXT_PDF = _FIX / "scanned_text.pdf"  # a picture of text (no text layer)


def _has_render() -> bool:
    import importlib.util

    return importlib.util.find_spec("pypdfium2") is not None and pdf_available()


needs_pypdf = pytest.mark.skipif(not pdf_available(), reason="pypdf ([pdf] extra) not installed")
needs_render = pytest.mark.skipif(not _has_render(), reason="pypdfium2 ([ocr] extra) not installed")
needs_ocr = pytest.mark.skipif(not ocr_available(), reason="OCR ([ocr] extra + tesseract) unavailable")


# --------------------------------------------------------------------------- #
#  Layer 1 — real extraction against fixture PDFs (CI, skip on core install)
# --------------------------------------------------------------------------- #
@needs_pypdf
def test_text_pdf_extracts_prose():
    text, reason = extract_pdf_text(_TEXT_PDF.read_bytes())
    assert reason == "ok"
    assert text and "liberty and security" in text
    assert len(text) >= 200


@needs_pypdf
def test_scanned_image_pdf_yields_no_text_not_garbage():
    # An image-only PDF has no text layer — extraction must return None + a reason,
    # NEVER a fabricated body (the maintainer's mis-extraction concern).
    text, reason = extract_pdf_text(_IMAGE_PDF.read_bytes())
    assert text is None
    assert "scanned" in reason or "no extractable text" in reason


@needs_pypdf
def test_corrupt_pdf_degrades_loudly():
    text, reason = extract_pdf_text(b"%PDF-1.4 this is not a real pdf body at all")
    assert text is None and reason.startswith("pdf extraction failed")


# --------------------------------------------------------------------------- #
#  Layer 2 — degrade + mis-extraction guard (run EVERYWHERE, incl. core install)
# --------------------------------------------------------------------------- #
def test_not_a_pdf_is_rejected():
    assert extract_pdf_text(b"<html><body>a web page</body></html>") == (None, "not a pdf")


def test_empty_response():
    assert extract_pdf_text(b"") == (None, "empty response")
    assert extract_pdf_text(None) == (None, "empty response")


def test_detects_pdf_by_magic_and_by_content_type():
    assert looks_like_pdf(b"%PDF-1.7\n...") is True
    assert looks_like_pdf(b"<html>", content_type="application/pdf") is True
    assert looks_like_pdf(b"<html>", content_type="text/html") is False
    assert looks_like_pdf(None) is False


def test_missing_extractor_degrades_gracefully(monkeypatch):
    # A core install (no pypdf) must record an honest reason, never crash.
    monkeypatch.setattr("src.ingest.pdf.pdf_available", lambda: False)
    text, reason = extract_pdf_text(b"%PDF-1.5\nsome bytes")
    assert text is None and "not installed" in reason


def test_mis_extraction_guard_rejects_symbol_garbage():
    # Real prose is majority letters; a mojibake decode is mostly symbols -> rejected,
    # so garbage can never be stored as a document body even if some PDF extracts to it.
    assert _looks_like_real_text("▢●□◆■ �� " * 80) is False  # mostly symbols -> rejected
    assert _looks_like_real_text("1234567 89.0 %$#@ " * 30) is False  # digits/symbols, not prose
    assert _looks_like_real_text("short") is False  # below the min-chars floor
    assert _looks_like_real_text("the law of the land shall be enforced " * 20) is True


# --------------------------------------------------------------------------- #
#  OCR fallback — column handling, degrade, confidence floor (mostly stubbed)
# --------------------------------------------------------------------------- #
def _tsv(blocks):
    """Build a tesseract image_to_data DICT from [(block,par,line,word,conf), ...]."""
    keys = ("block_num", "par_num", "line_num", "text", "conf")
    cols = list(zip(*blocks, strict=True)) if blocks else ([],) * 5
    return dict(zip(keys, cols, strict=True))


def test_reconstruct_respects_columns_and_never_fuses_them():
    """The multi-column concern: tesseract segments columns into separate BLOCKS;
    reconstruction must keep each column CONTIGUOUS, never interleave left+right on
    a shared line. Here block 1 = left column, block 2 = right — same line numbers."""
    data = _tsv([
        (1, 1, 1, "Left", 95), (1, 1, 1, "one", 95),
        (1, 1, 2, "Left", 95), (1, 1, 2, "two", 95),
        (2, 1, 1, "Right", 95), (2, 1, 1, "one", 95),
        (2, 1, 2, "Right", 95), (2, 1, 2, "two", 95),
    ])
    text, conf = _reconstruct_ocr_text(data)
    assert "Left one\nLeft two" in text and "Right one\nRight two" in text
    assert text.index("Left") < text.index("Right")  # left column before right
    assert "Right" not in text.split("Left two")[0]  # never fused onto a shared line
    assert conf == 95.0


def test_reconstruct_three_columns_stay_ordered():
    data = _tsv([
        (1, 1, 1, "colA", 90), (2, 1, 1, "colB", 90), (3, 1, 1, "colC", 90),
    ])
    text, _ = _reconstruct_ocr_text(data)
    assert text.index("colA") < text.index("colB") < text.index("colC")
    assert text == "colA\n\ncolB\n\ncolC"  # each column its own block, in order


def test_ocr_available_is_off_without_the_binary_or_env(monkeypatch):
    monkeypatch.setenv("OO_PDF_OCR", "0")
    assert ocr_available() is False


@needs_pypdf
def test_scanned_pdf_degrades_honestly_when_ocr_unavailable(monkeypatch):
    # ocr requested but unavailable -> the honest scan skip, never a crash.
    # (@needs_pypdf: without the [pdf] extra the extractor refuses BEFORE the scanned
    # path, with reason "pdf extractor not installed" — the Core-only lane proved it.)
    monkeypatch.setattr("src.ingest.pdf.ocr_available", lambda: False)
    text, reason = extract_pdf_text(_IMAGE_PDF.read_bytes(), ocr=True)
    assert text is None and "scanned" in reason


@needs_render
def test_ocr_pipeline_end_to_end_stubbed(monkeypatch):
    """Render the real scanned fixture (pypdfium2) but STUB the tesseract call, so the
    whole pipeline (render -> reconstruct -> guard) runs without the binary."""
    import pytesseract

    para = ("AN ACT to protect the liberty and security of the person . Section one "
            "Every person shall have the right to liberty and security . Section two "
            "No one shall be deprived of liberty save in accordance with law .")
    words = para.split()
    monkeypatch.setattr("src.ingest.pdf.ocr_available", lambda: True)
    monkeypatch.setattr(
        pytesseract, "image_to_data",
        lambda image, lang=None, output_type=None, **kw: _tsv(
            [(1, 1, i // 8 + 1, w, 90) for i, w in enumerate(words)]
        ),
    )
    text, reason = extract_pdf_text(_SCANNED_TEXT_PDF.read_bytes(), ocr=True)
    assert reason == "ocr"  # lower-trust provenance, not "ok"
    assert text and "liberty and security" in text


@needs_render
def test_low_confidence_ocr_is_rejected(monkeypatch):
    """A poor/complex scan (low mean confidence) is rejected, not stored as a
    confident-looking wrong body — the honesty floor."""
    import pytesseract

    para = ("garbled text that tesseract was unsure about across the whole page line "
            "after line of low confidence recognition from a bad scan repeated here so "
            "the page is long enough to pass the prose length floor and reach the "
            "confidence gate which should then reject this poor scan honestly now .")
    words = para.split()
    monkeypatch.setattr("src.ingest.pdf.ocr_available", lambda: True)
    monkeypatch.setattr(
        pytesseract, "image_to_data",
        lambda image, lang=None, output_type=None, **kw: _tsv(
            [(1, 1, i // 8 + 1, w, 20) for i, w in enumerate(words)]  # conf 20 = poor
        ),
    )
    text, reason = ocr_pdf(_SCANNED_TEXT_PDF.read_bytes())
    assert text is None and "low-confidence" in reason


@needs_pypdf
def test_born_digital_pdf_never_ocrs_even_when_ocr_on():
    # A PDF with a real text layer uses it exactly — OCR never runs (reason "ok").
    text, reason = extract_pdf_text(_TEXT_PDF.read_bytes(), ocr=True)
    assert reason == "ok" and text and "liberty and security" in text


@needs_ocr
def test_real_tesseract_reads_a_scanned_pdf():
    """CI only (needs the tesseract binary): the real OCR round-trip on the scanned
    fixture returns lower-trust text."""
    text, reason = extract_pdf_text(_SCANNED_TEXT_PDF.read_bytes(), ocr=True)
    assert reason == "ocr"
    assert text and "liberty" in text.lower()
