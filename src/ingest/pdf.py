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
import re

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
    data: bytes | None, *, min_chars: int = _MIN_CHARS
) -> tuple[str | None, str]:
    """Extract a PDF's visible text, returning ``(text, "ok")`` or ``(None, reason)``.

    ``reason`` is recorded as the caller's status so every failure mode degrades
    loudly and NEVER stores a fabricated body:
      * not a PDF / empty response;
      * no extractor installed (core install);
      * encrypted / corrupt / unsupported file;
      * a scanned or image-only PDF (no text layer) or a mis-decoded one that
        yields little or no real prose (the maintainer-flagged case).
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
        return None, "no extractable text (likely a scanned/image pdf)"
    return text, "ok"
