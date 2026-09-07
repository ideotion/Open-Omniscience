"""
Wikipedia pages enter THE corpus — same aggregation as any other article.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's ruling (2026-06-12, the living-source mandate made
concrete): a watched Wikipedia page is an ARTICLE like any other — it joins
full-text search, the keyword aggregator and the When×Where×Who anchoring —
with ONE structural difference: it has versions. The text ingested here is
always the NEWEST version the tracker has fetched (``latest_text``, falling
back to the baseline when no edit has landed yet), and re-syncing after new
revisions re-indexes idempotently, so the analytics always describe the
version the user is shown.

Honesty notes:
  * the corpus row's content is wikitext reduced to plain text by a bounded
    lexical strip (templates/refs/markup removed, link labels kept) — stated
    in the per-edition source name, never passed off as the rendered page;
  * provenance: each edition gets ONE catalog source ("Wikipedia (en)",
    domain en.wikipedia.org) so wiki-derived rows are filterable forever;
  * version anchoring: the revision the stored TEXT came from is recorded on the
    ARTICLE (``Article.source_revision``), written in the same transaction as the
    content it describes, for BOTH the watched-page sync and the offline dump
    ingest. The page row keeps ``latest_text_revid`` (the tracker's current
    state, which can legitimately run ahead of the last successful index); the
    article's anchor is what an analytic result can name, because every analytic
    is recomputed from that exact text through the one ``index_article`` hook.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote, unquote

from sqlalchemy.orm import Session

from src.database.models import Article, Source, WikiPage, WikiRevision
from src.utils.markup_blocks import strip_one_block

_LOG = logging.getLogger(__name__)

# Editions whose code is also one of the app's analysis languages keep it as
# the article language; anything else stays NULL (never silently "en").
_KNOWN_LANGS = frozenset({
    "en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id",
    "nl", "sv", "it", "pl", "tr",
})


def wiki_article_url(wiki: str, title: str) -> str:
    w = (wiki or "en").strip().lower()
    return f"https://{w}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


#: Exactly the shape ``wiki_article_url`` builds. The inverse below must never
#: accept a URL this app did not mint, or a hostile ``canonical_url`` could name a
#: "wiki page" that is not one.
_WIKI_URL_RE = re.compile(r"^https://([a-z0-9-]+)\.wikipedia\.org/wiki/(.+)$")


def wiki_page_ref(canonical_url: str) -> tuple[str, str] | None:
    """The (wiki, title) a canonical wiki URL was built FROM, or ``None``.

    The exact inverse of :func:`wiki_article_url` and kept beside it, because two
    functions answering one question from different sources drift — here into
    disagreeing about which page an article is.

    IT VERIFIES BY ROUND TRIP rather than by a hand-written rule about which
    characters are legal. Re-minting the URL from the candidate pair and requiring
    it back byte-for-byte accepts EXACTLY what the forward function can produce, by
    construction: a title containing ``/`` (``A/B testing``, ``OS/2``) survives,
    because ``quote`` leaves the slash and re-minting reproduces it, while nothing
    this app never minted can pass. A hand-maintained character rule would have to
    be kept in step with ``quote``'s ``safe`` set forever, and the first draft of
    this function got exactly that wrong — it refused every slash-bearing title,
    which would have silently withheld the history link from real pages.

    THE RETURNED TITLE IS A DATABASE LOOKUP KEY, NEVER A PATH. A page could
    legitimately be titled ``../../etc`` and the round trip therefore accepts it,
    which is correct here (no ``WikiPage`` carries that title, so the lookup finds
    nothing) and would be a traversal the moment a caller joined it onto a
    directory. Any such caller must run it through the same guard the dump reader
    uses; this function does not make it path-safe and does not claim to.
    """
    m = _WIKI_URL_RE.match((canonical_url or "").strip())
    if not m:
        return None
    wiki, raw = m.group(1), m.group(2)
    title = unquote(raw).replace("_", " ")
    if not title.strip():
        return None
    if wiki_article_url(wiki, title) != canonical_url.strip():
        return None
    return wiki, title


#: The three DELIMITED BLOCKS this strip removes. They are NOT written as
#: ``OPEN.*?CLOSE`` regexes, and that is the whole point: an opener with no closer
#: makes the lazy ``.*?`` scan to end-of-document, fail, and RESTART from the next
#: opener, so K openers cost K*N. MEASURED on this very function at 400,000 chars:
#: 0.014 s well-formed against **13.440 s** for unclosed-``<ref>`` spam and
#: 12.295 s for unclosed-``{|`` -- a ~960x cliff turning only on whether the
#: closers happen to be there, reached by ordinary broken wikitext, on the path
#: EVERY watched-page sync and EVERY dump ingest runs through. The recorded
#: 2026-08-05 lesson names this shape and asks for it to be grepped rather than
#: waited for; it was still here in three patterns on 2026-09-07.
#: ``src.utils.markup_blocks.strip_blocks`` walks each opener forward once and
#: retires a family that can no longer close: 14.16 s -> 0.0030 s, byte-identical
#: over 20,000 randomised documents (tests/test_markup_blocks.py).
#:
#: **SIX OF THE PATTERNS BELOW STILL CARRY THE SAME CLASS AND ARE NOT FIXED HERE.**
#: They wear it differently -- ``OPEN[^X]*CLOSE``, where an opener with no closer
#: makes the character class consume to end-of-document and then backtrack
#: position by position -- and they are the EXPENSIVE half. Measured on this
#: function, 100,000 -> 400,000 chars of opener-only spam:
#:
#:   ``<[^>]+>``          0.154 s -> 2.381 s   (15.4x for a 4x input)
#:   ``<ref[^>/]*/>``     1.052 s -> 16.756 s  (15.9x)
#:   ``[[File|Image|…]]`` 1.749 s -> 28.035 s  (16.0x)
#:   ``[[target|label]]`` 1.614 s -> 26.388 s  (16.4x)
#:   ``[[target]]``       1.721 s -> 27.398 s  (15.9x)
#:   ``[url label]``      1.420 s -> 22.525 s  (15.9x)
#:   ``{{templates}}``    0.005 s -> 0.019 s   (4.1x -- LINEAR, because ``[^{}]*``
#:                                             cannot cross a brace)
#:
#: They are RECORDED rather than rushed: each CAPTURES and rewrites rather than
#: removing, so the scanner needs a replacement callback and every rewrite needs
#: its own byte-identical differential before it goes near the ingest path. The
#: numbers are here so the next session has them; the Open queue carries the
#: finding. Possessive quantifiers do NOT fix these either -- the cost is a scan
#: per start position, not backtracking depth.
_WIKI_BLOCKS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (re.compile(r"<!--"), re.compile(r"-->")),
    (re.compile(r"<ref[^>]*>", re.IGNORECASE), re.compile(r"</ref>", re.IGNORECASE)),
    (re.compile(r"\{\|"), re.compile(r"\|\}")),  # tables
)


def plain_from_wikitext(text: str, *, max_passes: int = 4) -> str:
    """Reduce wikitext to analyzable plain text (bounded lexical strip).

    Deliberately simple and stated: nested templates are peeled in a few
    passes, refs/comments/tables/files dropped, link labels kept. The goal is
    keyword/WWW-quality text, not rendering fidelity.

    Comment, ``<ref>`` and table BLOCKS go through the shared linear scanner
    rather than a lazy regex -- see ``_WIKI_BLOCKS`` for the measurement.
    """
    t = text or ""
    comment_open, comment_close = _WIKI_BLOCKS[0]
    t = strip_one_block(t, comment_open, comment_close)
    t = re.sub(r"<ref[^>/]*/>", " ", t)  # self-closing: not a block, no closer to find
    ref_open, ref_close = _WIKI_BLOCKS[1]
    t = strip_one_block(t, ref_open, ref_close)
    for _ in range(max_passes):  # peel nested {{templates}} inside-out
        t2 = re.sub(r"\{\{[^{}]*\}\}", " ", t)
        if t2 == t:
            break
        t = t2
    table_open, table_close = _WIKI_BLOCKS[2]
    t = strip_one_block(t, table_open, table_close)
    t = re.sub(r"\[\[(?:File|Image|Category)[^\]]*\]\]", " ", t, flags=re.I)
    t = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", t)  # [[target|label]] -> label
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)  # [[target]] -> target
    t = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", t)  # [url label] -> label
    t = re.sub(r"\[https?://\S+\]", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)  # residual html
    t = t.replace("'''", "").replace("''", "")
    t = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", t, flags=re.M)  # ==headings==
    return re.sub(r"[ \t]+", " ", t).strip()


def ensure_wiki_source(session: Session, wiki: str) -> Source:
    """ONE catalog source per edition — wiki-derived rows stay filterable."""
    w = (wiki or "en").strip().lower()
    domain = f"{w}.wikipedia.org"
    src = session.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(
            name=f"Wikipedia ({w})",
            domain=domain,
            rss_url=None,
            # channel-implied tags (provenance.CLASS_IMPLIED_TAGS) so tag-based
            # filters find wiki articles; the boot heal covers older rows.
            tags="wikipedia,encyclopedia",
        )
        session.add(src)
        session.flush()
    return src


def _page_text(page: WikiPage) -> tuple[str | None, int | None]:
    """The newest text we hold + the revid it corresponds to (honest pair)."""
    if page.latest_text:
        return page.latest_text, (page.latest_text_revid or page.last_revid)
    if page.baseline_text:
        return page.baseline_text, page.baseline_revid
    return None, None


def sync_page_to_corpus(session: Session, page: WikiPage, *, extractor=None) -> dict:
    """Upsert the page's NEWEST text as one corpus article and (re-)index it.

    Idempotent: keyed on the canonical wiki URL; unchanged content is skipped
    (hash compare), changed content replaces the row's text and re-runs the
    ONE ``index_article`` hook — keywords and When×Where×Who follow the
    latest version automatically.
    """
    if page.missing:
        return {"page": page.title, "status": "skipped-missing"}
    raw, revid = _page_text(page)
    if not raw:
        return {"page": page.title, "status": "skipped-no-text"}

    last_rev_ts = (
        session.query(WikiRevision.timestamp)
        .filter(WikiRevision.page_id == page.id, WikiRevision.timestamp.isnot(None))
        .order_by(WikiRevision.revid.desc())
        .limit(1)
        .scalar()
    )
    return upsert_wiki_corpus_article(
        session,
        wiki=page.wiki,
        title=page.title,
        plain=plain_from_wikitext(raw),
        published_at=last_rev_ts or page.last_checked_at,
        revid=revid,
        extractor=extractor,
    )


def upsert_wiki_corpus_article(
    session: Session,
    *,
    wiki: str,
    title: str,
    plain: str,
    published_at=None,
    revid: int | None = None,
    extractor=None,
) -> dict:
    """Upsert ONE wiki page's plain text as a corpus Article and index it.

    Keyed on the canonical wiki URL; idempotent on the content hash (unchanged
    content is skipped). Shared by the watched-page sync (live text) and the
    OFFLINE dump ingest (dump text) so both follow the exact same path through
    the single ``index_article`` hook (keywords + When×Where×Who).
    """
    if not plain:
        return {"page": title, "status": "skipped-empty-after-strip"}
    content_hash = hashlib.sha256(plain.encode()).hexdigest()
    url = wiki_article_url(wiki, title)

    # The version anchor travels WITH the text, in the same transaction, because it is
    # only meaningful beside it: `source_revision` claims "this is the revision `content`
    # came from", never "the analytics are current". A revid we were not given stays
    # NULL rather than becoming a guess.
    revision = str(revid) if revid is not None else None

    art = session.query(Article).filter(Article.canonical_url == url).first()
    created = False
    if art is None:
        src = ensure_wiki_source(session, wiki)
        art = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=title,
            content=plain,
            language=(wiki if wiki in _KNOWN_LANGS else None),
            hash=content_hash,
            published_at=published_at or datetime.now(UTC),
            source_revision=revision,
        )
        session.add(art)
        session.flush()
        created = True
    elif art.hash == content_hash:
        # Unchanged TEXT. The revision may still be newly known (an older row stored
        # before this column existed, or a dump ingest that first learned the revid), so
        # fill a NULL -- but never OVERWRITE a recorded one from an identical body: two
        # revisions producing byte-identical text are both true answers, and replacing
        # the recorded one would silently rewrite what a past analysis was anchored to.
        if revision and not art.source_revision:
            art.source_revision = revision
            session.commit()
        return {
            "page": title, "status": "unchanged", "article_id": art.id, "revid": revid,
            "source_revision": art.source_revision,
        }
    else:
        art.content = plain
        art.hash = content_hash
        art.title = title
        # New text, so the anchor is replaced -- including with NULL when this path did
        # not learn a revision, because keeping the previous revid beside different text
        # would be a fabricated version, which is worse than an honest absence.
        art.source_revision = revision
        if published_at:
            art.published_at = published_at
    session.commit()

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor)
    return {
        "page": title,
        "status": "created" if created else "updated",
        "article_id": art.id,
        "revid": revid,
        "source_revision": art.source_revision,
        "mentions": tally.get("mentions", 0),
    }


def sync_watched(session: Session, *, extractor=None, limit: int = 200) -> dict:
    """Sync every watched page that has text — the backfill for existing
    watchlists (new revisions sync automatically from the tracker)."""
    pages = (
        session.query(WikiPage)
        .filter(WikiPage.watched.is_(True))
        .limit(limit)
        .all()
    )
    out = {"pages": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for page in pages:
        try:
            res = sync_page_to_corpus(session, page, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad page must not abort the batch
            session.rollback()
            _LOG.warning("corpus sync failed for %s:%s", page.wiki, page.title, exc_info=True)
            out["skipped"] += 1
            continue
        out["pages"] += 1
        st = res.get("status", "")
        if st == "created":
            out["created"] += 1
        elif st == "updated":
            out["updated"] += 1
        elif st == "unchanged":
            out["unchanged"] += 1
        else:
            out["skipped"] += 1
    return out


def ingest_dump_page(
    session: Session, wiki: str, title: str, *, extractor=None, base_dir=None
) -> dict:
    """Ingest ONE page from a DOWNLOADED dump into the corpus (offline; no network).

    Reads the page's raw wikitext from the local multistream dump via
    ``dumpread.find_page``, strips it, and upserts it as a corpus Article through
    the SAME path watched-page sync uses (``upsert_wiki_corpus_article`` → the one
    ``index_article`` hook). The article is a snapshot as of the dump date; the
    canonical wiki URL keys it, so a later live sync of the same page updates the
    SAME row (no duplicate). Returns the upsert tally, or an honest skip reason
    (e.g. ``no-multistream-dump`` / ``title-not-in-index``) from the reader.
    """
    from src.wiki import dumpread

    res = dumpread.find_page(wiki, title, base_dir=base_dir)
    if not res.get("found"):
        return {"page": title, "status": res.get("reason") or "not-found",
                "found": False}
    published_at = None
    ts = res.get("rev_timestamp")
    if ts:
        try:
            published_at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            published_at = None
    revid = res.get("revid")
    return upsert_wiki_corpus_article(
        session,
        wiki=wiki,
        title=title,
        plain=plain_from_wikitext(res.get("wikitext") or ""),
        published_at=published_at,
        revid=int(revid) if revid and str(revid).isdigit() else None,
        extractor=extractor,
    )


def ingest_dump_pages(
    session: Session, wiki: str, titles: list[str], *, extractor=None, limit: int = 1000,
    base_dir=None,
) -> dict:
    """Ingest a BOUNDED list of titles from the downloaded dump (offline).

    The bound (``limit``) is deliberate: a full edition is millions of pages, so
    this slice ingests an explicit, operator-chosen set (e.g. a watch list or a
    curated top-N) rather than the whole dump in one pass. One bad page never
    aborts the batch. Returns per-title results + a tally.
    """
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    results: list[dict] = []
    for title in titles[: max(0, limit)]:
        try:
            res = ingest_dump_page(session, wiki, title, extractor=extractor, base_dir=base_dir)
        except Exception:  # noqa: BLE001 - one bad page must not abort the batch
            session.rollback()
            _LOG.warning("dump corpus ingest failed for %s:%s", wiki, title, exc_info=True)
            res = {"page": title, "status": "error"}
        st = res.get("status", "")
        counts[st if st in counts else "skipped"] += 1
        results.append(res)
    return {"wiki": wiki.lower(), "requested": len(titles), **counts, "results": results}
