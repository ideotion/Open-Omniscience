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
    extract_pdf_text,
    looks_like_pdf,
    pdf_available,
)

_FIX = Path(__file__).parent / "fixtures" / "pdf"
_TEXT_PDF = _FIX / "text_statute.pdf"
_IMAGE_PDF = _FIX / "scanned_image.pdf"

needs_pypdf = pytest.mark.skipif(not pdf_available(), reason="pypdf ([pdf] extra) not installed")


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
