"""
Wikipedia tracking orchestrator: baseline + store new revisions as deltas.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

On first sight of a watched page we store ONE compressed full-text baseline and
record its current revid; thereafter we only store *new* revisions as diffs +
signed byte deltas + honest flags (+ optional ORES). Re-polling stores nothing
for unchanged pages, so cosmetic-edit redundancy is avoided by construction.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from src.database.models import WikiPage, WikiRevision
from src.wiki.flagging import flag_revision
from src.wiki.mediawiki import diff_summary

_LOG = logging.getLogger(__name__)
_BURST_WINDOW = timedelta(hours=24)


def ensure_page(
    session: Session, wiki: str, title: str, *, category: str | None = None
) -> WikiPage:
    """Get or create a watched page row for (wiki, title)."""
    wiki = (wiki or "en").strip().lower()
    title = title.strip()
    page = session.query(WikiPage).filter_by(wiki=wiki, title=title).first()
    if page is None:
        page = WikiPage(wiki=wiki, title=title, category=category, watched=True)
        session.add(page)
        session.commit()
    return page


def _burst_count(new_revs: list[dict], rev: dict) -> int:
    ts = rev.get("timestamp")
    if not isinstance(ts, datetime):
        return 0
    return sum(
        1
        for r in new_revs
        if isinstance(r.get("timestamp"), datetime) and abs(r["timestamp"] - ts) <= _BURST_WINDOW
    )


def update_page(
    session: Session,
    client,
    page: WikiPage,
    *,
    ores_client=None,
    max_new: int = 50,
    fetch_diffs: bool = True,
) -> dict:
    """Fetch and store new revisions for one page. Returns a small tally."""
    now = datetime.now(UTC)

    # First contact: store a single baseline snapshot and start tracking from here.
    if page.baseline_revid is None:
        cur = client.fetch_current_text(page.wiki, page.title)
        if cur.get("missing"):
            # A typo / renamed / deleted page must be SAID, not silently pending
            # forever (live test 2026-06-10). The flag drives a loud UI badge.
            page.missing = True
            page.last_checked_at = now
            session.commit()
            return {"page": page.title, "new": 0, "flagged": 0, "missing": True}
        if cur.get("revid"):
            page.missing = False
            page.baseline_revid = cur["revid"]
            page.baseline_text = cur.get("text") or ""
            page.last_revid = cur["revid"]
            page.pageid = cur.get("pageid")
            # The article's real Wikipedia categories — for classification when
            # the watchlist grows large. Best-effort: never blocks the baseline.
            try:
                cats = client.fetch_categories(page.wiki, page.title)
                if cats:
                    page.wiki_categories = json.dumps(cats[:50], ensure_ascii=False)
            except Exception:  # noqa: BLE001
                _LOG.warning("category fetch failed for %s", page.title, exc_info=True)
        page.last_checked_at = now
        session.commit()
        return {"page": page.title, "new": 0, "flagged": 0, "baseline": True}

    revs = client.fetch_revisions(page.wiki, page.title, limit=max_new)
    last = page.last_revid or 0
    new = sorted((r for r in revs if (r.get("revid") or 0) > last), key=lambda r: r["revid"])
    size_by_revid = {r["revid"]: r.get("size") for r in revs if r.get("revid")}

    # Per-revision FULL TEXT (maintainer-agreed 2026-06-12): one batched call
    # for all new revids — exact versions become locally materializable. A
    # fetch failure stores the revisions without text (honest partial, said
    # in the row by its NULL) rather than dropping them.
    texts_by_revid: dict[int, str] = {}
    if new:
        try:
            texts_by_revid = client.fetch_revision_texts(
                page.wiki, [r["revid"] for r in new]
            )
        except Exception:  # noqa: BLE001 - text enrichment must not drop revisions
            _LOG.warning("revision-text fetch failed for %s", page.title, exc_info=True)

    stored = flagged = 0
    for r in new:
        parent = r.get("parent_revid")
        parent_size = size_by_revid.get(parent)
        delta = (
            (r["size"] - parent_size)
            if (r.get("size") is not None and parent_size is not None)
            else None
        )

        diff_text = None
        if fetch_diffs and parent:
            try:
                d = client.fetch_compare(page.wiki, parent, r["revid"])
                diff_text = diff_summary(d.get("added", ""), d.get("removed", ""))
                if delta is None:
                    delta = d.get("added_bytes", 0) - d.get("removed_bytes", 0)
            except Exception:  # noqa: BLE001 - a missing diff must not drop the revision
                _LOG.warning("compare failed for %s rev %s", page.title, r["revid"], exc_info=True)

        ores_d = ores_g = ores_prov = None
        if ores_client:
            try:
                sc = ores_client.score(page.wiki, [r["revid"]]).get(r["revid"])
            except Exception:  # noqa: BLE001 - ORES is optional and MUST fail-open (it's often down/deprecated)
                _LOG.warning(
                    "ORES scoring failed for %s rev %s", page.title, r["revid"], exc_info=True
                )
                sc = None
            if sc:
                ores_d, ores_g, ores_prov = (
                    sc.get("damaging"),
                    sc.get("goodfaith"),
                    sc.get("provenance"),
                )

        fr = flag_revision(
            delta_bytes=delta,
            tags=r.get("tags"),
            editor_anon=r.get("editor_anon", False),
            minor=r.get("minor", False),
            ores_damaging=ores_d,
            burst_count=_burst_count(new, r),
        )
        session.add(
            WikiRevision(
                page_id=page.id,
                revid=r["revid"],
                parent_revid=parent,
                timestamp=r.get("timestamp"),
                editor=r.get("editor"),
                editor_anon=r.get("editor_anon", False),
                comment=r.get("comment"),
                size=r.get("size"),
                delta_bytes=delta,
                tags=",".join(r.get("tags") or []),
                minor=r.get("minor", False),
                bot=r.get("bot", False),
                diff=diff_text,
                full_text=texts_by_revid.get(r["revid"]),
                ores_damaging=ores_d,
                ores_goodfaith=ores_g,
                ores_provenance=ores_prov,
                flagged=fr.flagged,
                flag_reasons=fr.reasons_csv(),
            )
        )
        stored += 1
        flagged += 1 if fr.flagged else 0
        page.last_revid = max(page.last_revid or 0, r["revid"])

    # Edits landed -> refresh the LATEST full text (maintainer-ruled
    # 2026-06-12: the article shown is always the newest version; the revid it
    # corresponds to travels with it). One extra fetch per CHANGED page only;
    # a failure keeps the previous text — honest staleness, never a crash.
    if stored:
        newest = max((r["revid"] for r in new), default=None)
        if newest is not None and newest in texts_by_revid:
            page.latest_text = texts_by_revid[newest]
            page.latest_text_revid = newest
        else:
            try:
                cur = client.fetch_current_text(page.wiki, page.title)
                if cur.get("revid") and cur.get("text"):
                    page.latest_text = cur["text"]
                    page.latest_text_revid = cur["revid"]
            except Exception:  # noqa: BLE001 - latest-text refresh must not drop the revisions
                _LOG.warning("latest-text refresh failed for %s", page.title, exc_info=True)

    page.last_checked_at = now
    session.commit()
    return {"page": page.title, "new": stored, "flagged": flagged, "baseline": False}


def track_watched(
    session: Session, client, *, ores_client=None, limit_pages: int = 50, max_new: int = 50
) -> dict:
    """Update all watched pages. Returns an aggregated tally."""
    from src.database.query import capped

    pages = capped(
        session.query(WikiPage)
        .filter_by(watched=True)
        .order_by(WikiPage.last_checked_at.is_(None).desc(), WikiPage.last_checked_at.asc()),
        limit_pages,  # 0 = every watched page (no cap)
    ).all()
    total_new = total_flagged = pages_done = 0
    for page in pages:
        try:
            res = update_page(session, client, page, ores_client=ores_client, max_new=max_new)
            total_new += res["new"]
            total_flagged += res["flagged"]
            pages_done += 1
            # The living-source bridge: changed pages re-enter the corpus with
            # their newest text (keywords + When x Where x Who follow). A sync
            # failure never blocks tracking.
            if res.get("new") or res.get("baseline"):
                try:
                    from src.wiki.corpus import sync_page_to_corpus

                    sync_page_to_corpus(session, page)
                except Exception:  # noqa: BLE001
                    session.rollback()
                    _LOG.warning("corpus sync failed for %s", page.title, exc_info=True)
        except Exception:  # noqa: BLE001 - one bad page must not abort the batch
            session.rollback()
            _LOG.warning("wiki tracking failed for %s:%s", page.wiki, page.title, exc_info=True)
    return {"pages": pages_done, "new_revisions": total_new, "flagged": total_flagged}
