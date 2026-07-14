"""
PDF text extraction — HONEST about failure.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Shared by the world-law tracker (many official gazettes publish legislation as
PDFs) and the local PDF-document importer. PDF extraction is unreliable BY
NATURE: a scanned/image PDF carries no text layer, and some PDFs decode to
mojibake. The maintainer's ruling (2026-07-14): try it, but never fabricate a
body. So this module extracts text ONLY when it looks like real prose, and
otherwise returns an honest reason (recorded as the caller's status) so the
failure degrades LOUDLY — never a garbage keyword-poisoning body in the corpus.

It is an OPTIONAL seam: ``pypdf`` ships in the ``[pdf]`` pip extra. A core install
has no extractor, so ``extract_pdf_text`` returns ``(None, "…not installed…")``
and the caller records "no usable text" — never a crash. (Mirrors the
segmentation / analysis optional-seam convention.)
"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import re
from contextlib import suppress

_LOG = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"
# Real document prose is overwhelmingly letters + spaces. A scanned/image PDF
# yields little or no text, and a mis-decoded (mojibake) extraction is mostly
# symbols/control chars. Both must degrade to "no text" — never a fabricated body.
_MIN_CHARS = 200  # matches the law tracker's _MIN_TEXT extraction floor
_MIN_ALPHA_RATIO = 0.55  # of the non-space chars, at least this fraction must be letters
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def pdf_available() -> bool:
    """True if the optional PDF extractor (``pypdf``, the ``[pdf]`` extra) is present.

    A LIGHTWEIGHT importability probe (``find_spec`` only) — it never imports
    pypdf, so a mere availability/status check stays cheap (the segmenter-probe
    convention).
    """
    return importlib.util.find_spec("pypdf") is not None


def looks_like_pdf(data: bytes | None, *, content_type: str = "") -> bool:
    """True if the bytes are a PDF (``%PDF-`` magic) OR the server declared one.

    The magic is authoritative (some servers mislabel the content-type); the
    content-type is only a fallback hint when we have no bytes.
    """
    if data and _PDF_MAGIC in data[:1024]:
        return True
    return "application/pdf" in (content_type or "").lower()


def _looks_like_real_text(text: str) -> bool:
    """The mis-extraction guard: real prose is majority letters.

    A scanned page (empty text) or a mojibake decode (mostly symbols / control
    chars) fails this, so we never store garbage as a document body.
    """
    stripped = text.strip()
    if len(stripped) < _MIN_CHARS:
        return False
    non_space = [c for c in stripped if not c.isspace()]
    if not non_space:
        return False
    alpha = sum(1 for c in non_space if c.isalpha())
    return (alpha / len(non_space)) >= _MIN_ALPHA_RATIO


def extract_pdf_text(
    data: bytes | None, *, min_chars: int = _MIN_CHARS, ocr: bool = False
) -> tuple[str | None, str]:
    """Extract a PDF's visible text, returning ``(text, "ok")`` or ``(None, reason)``.

    Reads the born-digital TEXT LAYER first (exact, instant, never hallucinated).
    When that yields nothing (a scanned/image PDF) AND ``ocr`` is set AND the
    optional OCR fallback is available (the ``[ocr]`` extra + the tesseract
    binary), it falls back to OCR — returning ``(text, "ocr")`` so the caller can
    label the LOWER-TRUST provenance (OCR can mis-read; it is never the
    text-layer's exactness).

    ``reason`` is recorded as the caller's status so every failure mode degrades
    loudly and NEVER stores a fabricated body:
      * not a PDF / empty response;
      * no extractor installed (core install);
      * encrypted / corrupt / unsupported file;
      * a scanned or image-only PDF (no text layer) or a mis-decoded one that
        yields little or no real prose (OCR-off, or OCR unavailable / low
        confidence).
    """
    if not data:
        return None, "empty response"
    if not looks_like_pdf(data):
        return None, "not a pdf"
    if not pdf_available():
        return None, "pdf extractor not installed (install the [pdf] extra)"

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            unlocked = False
            try:
                # many public gazettes have no user password (empty-password decrypt)
                unlocked = bool(reader.decrypt(""))
            except Exception:  # noqa: BLE001 - undecryptable → honest gap
                unlocked = False
            if not unlocked:
                return None, "encrypted pdf (password required)"
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                continue
    except Exception as exc:  # noqa: BLE001 - corrupt / unsupported → honest gap, never a crash
        _LOG.debug("pdf extraction failed: %s", exc)
        return None, f"pdf extraction failed: {type(exc).__name__}"

    text = _WS_RE.sub(" ", "\n".join(parts))
    text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
    if len(text.strip()) < min_chars or not _looks_like_real_text(text):
        # No usable text layer (a scanned PDF). Fall back to OCR only when asked
        # and available — otherwise stay honest about the scan.
        if ocr and ocr_available():
            return ocr_pdf(data, min_chars=min_chars)
        return None, "no extractable text (likely a scanned/image pdf)"
    return text, "ok"


# --------------------------------------------------------------------------- #
# OCR fallback for SCANNED / image-only PDFs (optional [ocr] extra).
#
# pypdf reads the text LAYER of a born-digital PDF; a scan has none. When the
# [ocr] extra (pytesseract + pypdfium2 + Pillow) AND the tesseract system binary
# are present, we render each page and OCR it. HONESTY: OCR is a LOWER-TRUST
# class — it can mis-read characters and, on complex multi-column / table
# layouts, MIS-ORDER text — so (a) the result is tagged "ocr" (never the
# authoritative text; the original PDF is always linked), (b) reading order
# RESPECTS tesseract's block/paragraph segmentation so cleanly-separated columns
# are not fused into run-on lines, and (c) a mean-confidence floor rejects a poor
# scan rather than storing a confident-looking wrong body.
# --------------------------------------------------------------------------- #

_OCR_SCALE = 3.0  # ~216 DPI render — enough for body text, bounded for memory


def _ocr_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def ocr_available() -> bool:
    """True if the OCR fallback ([ocr] extra + the tesseract binary) is usable.

    ``OO_PDF_OCR=0`` force-disables it. A lightweight probe — importability
    (``find_spec``) + a ``tesseract`` binary on PATH — so it never imports the
    heavy libs merely to answer (the segmenter-probe convention). pytesseract
    shells out to the tesseract binary, so its presence is required, not just the
    Python wrappers.
    """
    if os.getenv("OO_PDF_OCR", "1") == "0":
        return False
    if not all(importlib.util.find_spec(m) for m in ("pytesseract", "pypdfium2", "PIL")):
        return False
    import shutil

    return shutil.which("tesseract") is not None


def _reconstruct_ocr_text(data: dict) -> tuple[str, float]:
    """Rebuild reading order from tesseract's ``image_to_data`` result, RESPECTING
    its block / paragraph / line segmentation — so a multi-column layout is not
    flattened into left-right-fused lines. Returns ``(text, mean_confidence)``.

    Words are emitted in tesseract's order; a NEW LINE starts on a line change and
    a BLANK LINE on a paragraph/block change. So when tesseract segments the
    columns into separate blocks (the common clean case) each column stays a
    contiguous run — never interleaved with the next column. Mean per-word
    confidence (ignoring tesseract's ``-1`` non-text markers) is the honesty
    signal a poor/complex scan is caught by.
    """
    texts = list(data.get("text") or [])
    n = len(texts)

    def _col(name: str) -> list:
        v = list(data.get(name) or [])
        return v + [0] * (n - len(v))

    block, par, line, conf = _col("block_num"), _col("par_num"), _col("line_num"), _col("conf")
    parts: list[str] = []
    confs: list[float] = []
    prev: tuple | None = None
    for i in range(n):
        try:
            c = float(conf[i])
        except (TypeError, ValueError):
            c = -1.0
        if c >= 0:
            confs.append(c)
        word = (texts[i] or "").strip()
        if not word:
            continue
        cur = (block[i], par[i], line[i])
        if prev is not None:
            if cur[:2] != prev[:2]:
                parts.append("\n\n")  # new paragraph / block (e.g. the next column)
            elif cur[2] != prev[2]:
                parts.append("\n")  # new line within the same block
            else:
                parts.append(" ")  # same line
        parts.append(word)
        prev = cur
    text = re.sub(r"[ \t]+", " ", "".join(parts))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    mean_conf = (sum(confs) / len(confs)) if confs else 0.0
    return text, mean_conf


def ocr_pdf(
    data: bytes | None, *, min_chars: int = _MIN_CHARS, lang: str | None = None,
    max_pages: int | None = None,
) -> tuple[str | None, str]:
    """OCR a scanned PDF, returning ``(text, "ocr")`` or ``(None, reason)``.

    Renders each page (pypdfium2) and OCRs it (tesseract), reconstructing reading
    order per :func:`_reconstruct_ocr_text` (column-respecting) and rejecting a
    scan whose mean confidence is below the floor (``OO_PDF_OCR_MIN_CONF``,
    default 50) — an honest gap beats a confident wrong body. Bounded to
    ``OO_PDF_OCR_MAX_PAGES`` (default 50) pages since OCR is slow.
    """
    if not data:
        return None, "empty response"
    if not looks_like_pdf(data):
        return None, "not a pdf"
    if not ocr_available():
        return None, "ocr not available (install the [ocr] extra + the tesseract binary)"
    lang = lang or (os.getenv("OO_PDF_OCR_LANG", "") or "eng")
    max_pages = max_pages or int(_ocr_env("OO_PDF_OCR_MAX_PAGES", 50.0))
    min_conf = _ocr_env("OO_PDF_OCR_MIN_CONF", 50.0)
    try:
        import pypdfium2 as pdfium
        import pytesseract
        from pytesseract import Output
    except Exception as exc:  # noqa: BLE001 - optional seam, never a crash
        return None, f"ocr import failed: {type(exc).__name__}"

    page_texts: list[str] = []
    page_confs: list[float] = []
    try:
        pdf = pdfium.PdfDocument(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - corrupt/unsupported → honest gap
        _LOG.debug("ocr render open failed: %s", exc)
        return None, f"ocr failed to open pdf: {type(exc).__name__}"
    try:
        pages = min(len(pdf), max(1, max_pages))
        for pno in range(pages):
            try:
                bitmap = pdf[pno].render(scale=_OCR_SCALE)
                image = bitmap.to_pil()
                tdata = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
                ptext, pconf = _reconstruct_ocr_text(tdata)
                if ptext:
                    page_texts.append(ptext)
                    page_confs.append(pconf)
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                continue
    finally:
        with suppress(Exception):
            pdf.close()

    text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(t for t in page_texts if t)).strip()
    mean_conf = (sum(page_confs) / len(page_confs)) if page_confs else 0.0
    if len(text) < min_chars or not _looks_like_real_text(text):
        return None, "no extractable text (blank or unreadable scan)"
    if mean_conf < min_conf:
        return None, f"low-confidence OCR ({mean_conf:.0f}%) — likely a complex layout or poor scan"
    return text, "ocr"
