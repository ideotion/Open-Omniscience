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

import os
from dataclasses import dataclass
from datetime import datetime

import trafilatura
from dateutil import parser as date_parser
from trafilatura.settings import Document, set_date_params


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


def extensive_date_search_enabled() -> bool:
    """Is htmldate's last-resort free-text date hunt enabled? (OO_EXTENSIVE_DATE_SEARCH; off)

    P3 (2026-09-11). ``trafilatura.extract_metadata`` defaults ``extensive=True``, which
    switches TWO things on inside ``htmldate.find_date``: the element scan widens from a
    sensible element list to ``.//*``, and -- the expensive half -- a LAST RESORT walks
    every free-text segment of the page through ``dateparser``'s locale search.

    MEASURED on this tree (`collect_throughput_bench.py dates`), and the reason the
    default is OFF is not the speed:

    * Every STRUCTURED placement is unaffected: ``article:published_time``, JSON-LD
      ``datePublished``, ``<time datetime>`` and ``<span class="date">`` return the same
      date at the same cost with the flag either way. Nothing is traded there.
    * When the page has NO real publication date, the last resort does not return
      "unknown" -- it returns SOMETHING. A copyright footer became ``2019-01-01``, a
      sidebar of related articles became ``2011-01-12``, and a filler sentence in the body
      became ``2001-09-11``. Those are wrong publication dates, stored as this article's
      date, and they propagate into the timemap, the agenda and every trend. The bounded
      path returns ``None``, which is the true answer and one the app already renders
      honestly.
    * The cost is LANGUAGE-DEPENDENT, which matters for a collector that reads 12
      languages: ``custom_parse`` handles English shapes without ``dateparser``, so an
      English page pays little. A Spanish or Russian page carrying ~150 distinct textual
      dates measured 216 ms / 206 ms against 7 ms bounded -- ~30x, and the same order as
      the 434 ms recorded in the field profile, which this reproduces only once the page
      is non-English.

    WHAT IS ACTUALLY LOST, stated rather than glossed: a date that appears ONLY in an
    element outside htmldate's fast list (``<a class="date">``, ``<td class="date">``) or
    ONLY in free text. Those are real, correct dates the bounded path misses, and they are
    why this is a flag rather than a deletion -- ``OO_EXTENSIVE_DATE_SEARCH=1`` restores
    the old behaviour whole, with the fabrication risk above attached to it.
    """
    return os.getenv("OO_EXTENSIVE_DATE_SEARCH", "0") == "1"


def extract_article(html: str, *, url: str | None = None) -> ExtractedDoc | None:
    """Extract an article from raw HTML, or return ``None`` if there isn't one.

    ``url`` improves trafilatura's metadata resolution (e.g. canonical link).
    """
    if not html or not html.strip():
        return None

    # ONE parse, not two. ``extract`` and ``extract_metadata`` each called ``load_html``
    # on the same string, so every article was parsed twice; ``bare_extraction`` does the
    # metadata pass and the body pass off a single tree, in that order -- metadata first,
    # before the body extraction prunes it -- which is why sharing the parse is safe here
    # and would NOT have been safe by handing our own tree to the two public calls.
    #
    # ``date_extraction_params`` is not optional. ``Extractor`` defaults it to
    # ``set_date_params(extensive_search=True)``, and ``extract_metadata`` prefers a
    # supplied ``date_config`` over its own ``extensive`` argument -- so a switch to
    # ``bare_extraction`` that left this out would silently restore the unbounded date
    # hunt P3 removed, with no test failing and no line in the diff to see it in. The
    # flag is read ONCE per article, never per candidate date expression (the P2 shape).
    try:
        doc = trafilatura.bare_extraction(
            html,
            url=url,
            favor_recall=False,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            with_metadata=True,
            date_extraction_params=set_date_params(extensive_date_search_enabled()),
        )
    except Exception:
        # A RAISE is a fault, not a verdict. ``bare_extraction`` RETURNS None for every
        # legitimate rejection it makes (no tree, too short, wrong language, duplicate)
        # and catches only TypeError/ValueError internally, so anything else escaping it
        # came from the metadata pass -- which, folded into one call, would now take the
        # article BODY with it. That is a worse failure than the one this saves: the
        # contract says None means "no article here", never "the byline parser threw".
        # So a fault falls back to the previous two-call path, which survives a metadata
        # fault with the body intact. It costs a second parse on a page that was already
        # exceptional, and never on the normal path -- a legitimate None returns straight
        # away rather than re-extracting every non-article page in a crawl.
        return _extract_resiliently(html, url=url)

    if doc is None:
        return None
    if not isinstance(doc, Document):
        # ``bare_extraction`` is typed ``Document | dict | None`` because of a DEPRECATED
        # ``as_dict`` parameter this call never passes, so today this branch cannot be
        # reached -- and it is a narrowing rather than a ``cast`` because the two differ
        # exactly when it matters. A cast asserts the union away and would turn an
        # upstream change into an AttributeError on a live collect pass; this lands on
        # the path that still works. The test that forces it is what keeps it from being
        # an unfalsifiable guard.
        return _extract_resiliently(html, url=url)
    text = doc.text
    if not text or len(text.strip()) < _MIN_BODY_CHARS:
        return None

    title = author = language = canonical = None
    published_at: datetime | None = None
    meta = doc
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


def _extract_resiliently(html: str, *, url: str | None = None) -> ExtractedDoc | None:
    """The two-parse path, kept for the case the one-parse path cannot serve.

    This is what ``extract_article`` did before the parse was shared, unchanged: the body
    comes from its own call, and a metadata fault costs the metadata rather than the
    article. It is reached only when ``bare_extraction`` RAISES -- never on a legitimate
    ``None`` -- so the double parse is paid on an exceptional page and nowhere else.
    """
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
        meta = trafilatura.extract_metadata(
            html, default_url=url, extensive=extensive_date_search_enabled()
        )
    except Exception:
        meta = None
    if meta is not None:
        title = _clean(meta.title)
        author = _clean(meta.author)
        canonical = _clean(getattr(meta, "url", None))
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
