"""
Article content extraction from HTML.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Uses trafilatura (robust boilerplate removal + metadata) instead of the old
generic-CSS-selector approach that silently produced "No Title / No Content".

Contract (PRODUCT_SYNTHESIS §3.7 "Transparency over graceful failure"): if a real
article body cannot be extracted, this returns ``None`` so the caller records an
explicit extraction failure -- it never fabricates a placeholder article.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import trafilatura
from dateutil import parser as date_parser


@dataclass
class ExtractedDoc:
    """A successfully extracted article."""

    title: str | None
    text: str
    published_at: datetime | None
    language: str | None
    author: str | None
    canonical_url: str | None


# Minimum number of characters of body text for a page to count as an article.
# Below this we treat extraction as failed rather than store a stub.
_MIN_BODY_CHARS = 200


def extract_article(html: str, *, url: str | None = None) -> ExtractedDoc | None:
    """Extract an article from raw HTML, or return ``None`` if there isn't one.

    ``url`` improves trafilatura's metadata resolution (e.g. canonical link).
    """
    if not html or not html.strip():
        return None

    text = trafilatura.extract(
        html,
        url=url,
        favor_recall=False,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    if not text or len(text.strip()) < _MIN_BODY_CHARS:
        return None

    title = author = language = canonical = None
    published_at: datetime | None = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        meta = None
    if meta is not None:
        title = _clean(meta.title)
        author = _clean(meta.author)
        canonical = _clean(getattr(meta, "url", None))
        # trafilatura exposes language only when its detector is enabled; guard it.
        language = _clean(getattr(meta, "language", None))
        published_at = _parse_date(getattr(meta, "date", None))

    return ExtractedDoc(
        title=title,
        text=text.strip(),
        published_at=published_at,
        language=language,
        author=author,
        canonical_url=canonical,
    )


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value or None


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
