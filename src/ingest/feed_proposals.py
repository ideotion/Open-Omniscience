"""Feed addresses PROPOSED for feed-less sources, found without a request of their own (row 463, R852).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

About 650 catalogue rows have no feed address, and a feed-less source is not read by the regular passes (#2418,
catalogue.md section 2). Two offline ways to propose one, and nothing else:

* ``crawl_page``: when the crawl supplement fetches a feed-less outlet's START PAGE for its own walk, the page it already
  holds in memory is read for ``<link rel="alternate">`` feed links (:func:`src.ingest.feed_find.feed_links_in_page`).
  No request is made for it: no retry, no second page, no redirect followed to find a feed, and nothing of the page is
  stored. Labelled "found on a page the crawl already read".
* ``same_domain``: another source of this install on the EXACT same host (``www.`` ignored; a subdomain is another site,
  so an edition in another language is never proposed) already has a feed. Labelled "same domain, not verified", with
  that source named.

A proposal is never an ``rss_url`` change. The address is not fetched, probed or validated until the operator accepts it
with a click (:func:`accept`), which sets the source's ``rss_url``; the next collection then reads it like any feed, under
the consent and transport in force, through the one fetcher and its full address guard. Nothing here accepts in bulk or
on a schedule.

The page is untrusted input. Before a proposal is recorded the address must be http(s), carry no user name or password,
be at most :data:`URL_MAX_CHARS` long, and name a host that is not an internal one by its WRITING alone
(:func:`address_refusal`): an IP literal in a private, loopback, link-local or reserved range, ``localhost``, a
single-label name or an ``.local``/``.internal``/``.localhost`` name. The name is NOT resolved here, because a lookup is
itself a request; the fetcher's own guard resolves and checks it again when the accepted feed is first read. At most
:data:`MAX_PER_PAGE` proposals per page.

THIS MODULE MAKES NO REQUEST. It imports no fetcher and no network library, and ``tests/test_feed_proposals.py`` pins
that by reading this file's own syntax tree.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.database.models import FeedProposal, Source

#: At most this many proposals are recorded from one page (R852 (3); Plan may adjust).
MAX_PER_PAGE = 3
#: A longer address is not recorded (the column holds 500).
URL_MAX_CHARS = 500

ORIGIN_CRAWL_PAGE = "crawl_page"
ORIGIN_SAME_DOMAIN = "same_domain"

_INTERNAL_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")


def _host(url: str) -> str | None:
    try:
        return (urlsplit(url).hostname or "").rstrip(".").lower() or None
    except ValueError:
        return None


def _site(host: str | None) -> str:
    h = (host or "").strip().lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def address_refusal(url: str) -> str | None:
    """Why ``url`` may not be recorded or accepted as a proposal, or ``None``. Reads the writing only; never resolves."""
    from src.ingest import _carries_userinfo, _unsafe_url_text

    if not isinstance(url, str) or not url or len(url) > URL_MAX_CHARS:
        return "length"
    if _unsafe_url_text(url):
        return "unsafe_text"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unreadable"
    if parts.scheme not in ("http", "https"):
        return "scheme"
    if _carries_userinfo(url):
        return "userinfo"
    host = _host(url)
    if not host:
        return "no_host"
    try:
        from src.ingest.ssrf_guard import is_blocked_ip

        if is_blocked_ip(ipaddress.ip_address(host.strip("[]"))):
            return "internal_address"
        return None  # a public IP literal
    except ValueError:
        pass
    if host == "localhost" or "." not in host or host.endswith(_INTERNAL_SUFFIXES):
        return "internal_name"
    return None


def _known(session: Session, source_id: int) -> set[str]:
    """Every address already proposed for this source, whatever its status: a dismissed one is never proposed again."""
    return {u for (u,) in session.execute(select(FeedProposal.url).where(FeedProposal.source_id == source_id)).all()}


def links_from_page(source: Source, html: str, page_url: str) -> list[str]:
    """Up to :data:`MAX_PER_PAGE` feed links named on ``html``, the start page the crawl already fetched for ``source``,
    each passing :func:`address_refusal`. Only for a source with no feed. Pure: no database write and no request, so the
    crawl can call it between two fetches without staging a row (the fetcher hands a connection back only for a session
    with nothing pending). Never raises."""
    try:
        if getattr(source, "rss_url", None) or not html:
            return []
        from src.ingest.feed_find import feed_links_in_page

        out: list[str] = []
        for url in feed_links_in_page(html, page_url):
            if len(out) >= MAX_PER_PAGE:
                break
            if url not in out and address_refusal(url) is None:
                out.append(url)
        return out
    except Exception:  # noqa: BLE001 - a proposal is a by-product: it never fails the crawl
        return []


def record_links(session: Session, source_id: int, urls: list[str]) -> int:
    """Record ``urls`` (from :func:`links_from_page`) as ``crawl_page`` proposals for ``source_id``, skipping any address
    already proposed for it whatever its status. Checked again here, capped again here. Returns how many were added; the
    caller commits. Never raises."""
    try:
        src = session.get(Source, source_id)
        if src is None or src.rss_url:
            return 0
        known = _known(session, source_id)
        added = 0
        for url in urls[:MAX_PER_PAGE]:
            if url in known or address_refusal(url) is not None:
                continue
            session.add(FeedProposal(source_id=source_id, url=url, host=_host(url) or "", origin=ORIGIN_CRAWL_PAGE,
                                     status="proposed"))
            known.add(url)
            added += 1
        return added
    except Exception:  # noqa: BLE001 - a proposal is a by-product: it never fails the crawl
        return 0


def record_same_domain(session: Session) -> int:
    """Propose, for every feed-less source, the feed of another source on the exact same host (``www.`` ignored).
    Database only. Returns how many were recorded."""
    fed: dict[str, tuple[int, str]] = {}
    for sid, domain, rss in session.execute(
        select(Source.id, Source.domain, Source.rss_url).where(Source.rss_url.isnot(None)).order_by(Source.id)
    ).all():
        key = _site(domain)
        if key and rss and key not in fed:
            fed[key] = (int(sid), str(rss))
    if not fed:
        return 0
    known = {(int(s), str(u)) for s, u in session.execute(select(FeedProposal.source_id, FeedProposal.url)).all()}
    added = 0
    for sid, domain in session.execute(select(Source.id, Source.domain).where(or_(Source.rss_url.is_(None), Source.rss_url == ""))).all():
        hit = fed.get(_site(domain))
        if hit is None or hit[0] == sid:
            continue
        sibling, url = hit
        if address_refusal(url) is not None or (int(sid), url) in known:
            continue
        known.add((int(sid), url))
        session.add(FeedProposal(source_id=int(sid), url=url, host=_host(url) or "", origin=ORIGIN_SAME_DOMAIN,
                                 sibling_source_id=sibling, status="proposed"))
        added += 1
    return added


def counts(session: Session) -> dict[str, int]:
    """Proposals by status: counted apart from sources and from discovery candidates (R773)."""
    out = {"proposed": 0, "accepted": 0, "dismissed": 0}
    for status, n in session.execute(select(FeedProposal.status, func.count()).group_by(FeedProposal.status)).all():
        out[str(status)] = int(n)
    return out


@dataclass(frozen=True)
class Refusal:
    """A proposal that cannot be decided as asked; ``code`` is the HTTP status the API answers with. Returned, never
    raised, so no caller turns an exception into a served record."""

    code: int
    message: str


def _decidable(session: Session, proposal_id: int) -> FeedProposal | Refusal:
    p = session.get(FeedProposal, proposal_id)
    if p is None:
        return Refusal(404, "proposal not found")
    if p.status != "proposed":
        return Refusal(409, f"proposal is already {p.status}")
    return p


def accept(session: Session, proposal_id: int) -> FeedProposal | Refusal:
    """The operator's click: set the source's ``rss_url`` to the proposed address. ONE proposal; nothing is fetched here.
    The address is checked again first, and a source that has a feed by now is left as it is."""
    p = _decidable(session, proposal_id)
    if isinstance(p, Refusal):
        return p
    src = session.get(Source, p.source_id)
    if src is None:
        return Refusal(404, "source not found")
    if src.rss_url:
        return Refusal(409, "this source already has a feed address")
    if address_refusal(p.url) is not None:
        return Refusal(422, "the proposed address is not one the app will fetch")
    src.rss_url = p.url
    p.status = "accepted"
    p.decided_at = datetime.now(UTC)
    return p


def dismiss(session: Session, proposal_id: int) -> FeedProposal | Refusal:
    """Dismiss ONE proposal; it is remembered, so the same address is never proposed again for that source."""
    p = _decidable(session, proposal_id)
    if isinstance(p, Refusal):
        return p
    p.status = "dismissed"
    p.decided_at = datetime.now(UTC)
    return p
