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
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime

import trafilatura
from dateutil import parser as date_parser
from trafilatura.settings import Document, set_date_params

from src.ingest import lock_stats
from src.monitoring.native_inflight import native_call


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


#: ONE extraction at a time, process-wide. The process aborted (SIGABRT, no Python traceback) inside
#: ``lxml.html.document_fromstring`` under the collector's pool of ~50 workers, about one boot in
#: seven (2026-10-14: ``lxml/html/__init__.py:740`` <- ``trafilatura/utils.py:345`` <-
#: ``extract_article``). Who called ``abort()`` and why is NOT established (``docs/ledger/OPEN_QUEUE.md``,
#: "THE lxml SIGABRT"): no lxml 5.2-6.1.3, libxml2 2.12-2.15 or trafilatura report names it, and the
#: one loose match (trafilatura #840, fixed in 2.1.0) is a release older than the one that aborted.
#: What is known is that every parse, tree walk and tree release of the app's article HTML
#: (trafilatura, and inside it lxml, htmldate and justext) happens inside this one function's call
#: tree, so a lock around it makes concurrent use of libxml2 by that extraction impossible, whatever
#: the fault was. NOT covered: a library that reaches libxml2 on its own, which the walk in
#: ``tests/test_extract_lock.py`` cannot see. feedparser asks for libxml2's SAX driver first
#: (``PREFERRED_XML_PARSERS``) and uses it wherever the libxml2 Python bindings import, in every
#: collector worker and outside this lock: a system or distro Python can have them, a pip venv has
#: not (OPEN_QUEUE, "THE lxml SIGABRT"). The lock covers the whole call, not only the parse: the
#: faulting frame may be where an earlier corruption surfaced. The trees die inside it on a return
#: (the result holds only text, so they go with the call's last local) and on a raise (the
#: traceback's frames are cleared and an AttributeError's object dropped before the lock is given
#: up, :func:`_release_frames`). An RLock, so a caller that nests extraction cannot deadlock itself.
#: COST, said so: one page that takes long (a 10 MiB nav-heavy page measured 85 s) now holds every
#: other extraction in the process, and nothing can time it out; the OPEN_QUEUE entry has the numbers
#: and what would change it.
_LXML_LOCK = threading.RLock()


def extract_article(html: str, *, url: str | None = None) -> ExtractedDoc | None:
    """Extract an article from raw HTML, or return ``None`` if there isn't one.

    ``url`` improves trafilatura's metadata resolution (e.g. canonical link). One extraction runs
    at a time in the process (:data:`_LXML_LOCK`), whatever the number of collect workers; how long
    each waited and held is counted per pass in :mod:`src.ingest.lock_stats`, and its live gauge is
    marked three times around the lock (``asking`` before it, ``holding`` and ``released`` inside the hold).
    """
    if not html or not html.strip():
        return None
    asked = lock_stats.now()
    got = released = None
    try:
        lock_stats.asking()
        with _LXML_LOCK:
            got = lock_stats.now()
            try:
                lock_stats.holding()
                # RC2's black box (src/monitoring/native_inflight.py): the next boot can say libxml2 was running when the
                # process aborted. Inside the lock, so a worker WAITING for it is not counted as in lxml; around the whole
                # call because the lock covers the parse, the walk and the release of the trees, and the faulting frame may
                # be any of them. Never raises, never swallows the body's exception.
                with native_call("lxml"):
                    return _extract_locked(html, url=url)
            except BaseException as exc:
                _release_frames(exc)
                raise
            finally:
                released = lock_stats.released()
    finally:
        # After the lock is given up, so the statistic adds nothing to a hold; numbers only, never the URL.
        lock_stats.record(asked=asked, got=got, released=released, html=html)


def _release_frames(exc: BaseException) -> None:
    """Free what a raising extraction's frames still hold, while the lock is still held.

    An exception carries its traceback, and the traceback keeps every frame it passed through
    alive WITH its locals: ``bare_extraction``'s parsed trees among them. Left alone they are
    freed when the caller drops the exception, which is after the lock is given up (a worker's
    ``except`` clause in ``runner.py``), while another worker may be inside a parse. Clearing the
    frames drops the locals and keeps the traceback's lines (a ``NameError``'s "Did you mean" hint loses the candidates that came
    from the frame's locals; those from globals and builtins remain).
    The chain is walked because the fallback's exception carries the primary's as ``__context__``.
    An ``AttributeError`` also holds the object it failed on (``obj``, set by the interpreter), so that is dropped too;
    the message is unchanged, but Python's "Did you mean" hint, which it computes from that object, is no longer computed from the real
    one: it is not offered for most names, and for a name starting with ``_`` it is computed from ``None``'s attributes.
    NOT covered: a tree held in an exception's ``args`` or in ``StopIteration.value`` (nothing in the extraction path
    puts one there; ``tests/test_extract_lock.py`` pins the two cases it does see).
    """
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        err = pending.pop()
        if err is None or id(err) in seen:
            continue
        seen.add(id(err))
        traceback.clear_frames(err.__traceback__)
        if isinstance(err, AttributeError):
            # The interpreter sets ``obj`` to the object whose lookup failed: on an lxml element that is the element, which keeps its whole document alive.
            err.obj = None
        pending += [err.__cause__, err.__context__]


def _extract_locked(html: str, *, url: str | None = None) -> ExtractedDoc | None:
    """The body of :func:`extract_article`; call it only with :data:`_LXML_LOCK` held."""
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
