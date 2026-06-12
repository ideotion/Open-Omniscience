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
  * version anchoring slice 1: the synced revid is recorded on the page row
    (``latest_text_revid``); per-mention revid anchoring is the next slice.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy.orm import Session

from src.database.models import Article, Source, WikiPage, WikiRevision

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


def plain_from_wikitext(text: str, *, max_passes: int = 4) -> str:
    """Reduce wikitext to analyzable plain text (bounded lexical strip).

    Deliberately simple and stated: nested templates are peeled in a few
    passes, refs/comments/tables/files dropped, link labels kept. The goal is
    keyword/WWW-quality text, not rendering fidelity.
    """
    t = text or ""
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", " ", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", " ", t, flags=re.S | re.I)
    for _ in range(max_passes):  # peel nested {{templates}} inside-out
        t2 = re.sub(r"\{\{[^{}]*\}\}", " ", t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\{\|.*?\|\}", " ", t, flags=re.S)  # tables
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

    plain = plain_from_wikitext(raw)
    if not plain:
        return {"page": page.title, "status": "skipped-empty-after-strip"}
    content_hash = hashlib.sha256(plain.encode()).hexdigest()
    url = wiki_article_url(page.wiki, page.title)

    last_rev_ts = (
        session.query(WikiRevision.timestamp)
        .filter(WikiRevision.page_id == page.id, WikiRevision.timestamp.isnot(None))
        .order_by(WikiRevision.revid.desc())
        .limit(1)
        .scalar()
    )

    art = session.query(Article).filter(Article.canonical_url == url).first()
    created = False
    if art is None:
        src = ensure_wiki_source(session, page.wiki)
        art = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=page.title,
            content=plain,
            language=(page.wiki if page.wiki in _KNOWN_LANGS else None),
            hash=content_hash,
            published_at=last_rev_ts or page.last_checked_at or datetime.now(UTC),
        )
        session.add(art)
        session.flush()
        created = True
    elif art.hash == content_hash:
        return {"page": page.title, "status": "unchanged", "article_id": art.id,
                "revid": revid}
    else:
        art.content = plain
        art.hash = content_hash
        art.title = page.title
        if last_rev_ts:
            art.published_at = last_rev_ts
    session.commit()

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor)
    return {
        "page": page.title,
        "status": "created" if created else "updated",
        "article_id": art.id,
        "revid": revid,
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
