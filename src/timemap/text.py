"""The text the when/where/who stores read from an article (R725).

An article kept compressed holds its text in ``compressed_content`` and leaves the ``content``
column empty. The date, place and entity stores read ``article.content`` directly, so for such an
article they found nothing: no dates, no places, no people, on every path (ingest, re-index,
import), while the keyword half read the decompressed text. ``Article.get_content()`` is the one
reading that answers for both kinds; this is the call every one of those stores makes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from typing import Any


def article_text(article: Any) -> str:
    """The article's text, decompressed when it is kept compressed; ``""`` when it has none.

    Falls back to the ``content`` attribute for an object without ``get_content`` (a test double),
    which is what every caller read before."""
    get = getattr(article, "get_content", None)
    if callable(get):
        return get() or ""
    return getattr(article, "content", None) or ""
