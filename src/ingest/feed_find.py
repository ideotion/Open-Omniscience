"""
Finding a candidate's feed INSIDE its qualification trial (R773 (3), row 249).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every source world discovery adds comes from Wikidata with a domain and no ``rss_url``, so its trial could only try the
sitemap channel, and a site with no reachable sitemap produced no evidence and was offered again, pass after pass. The
trial now first reads the candidate's own home page and looks for the feed links that page names, the ``<link
rel="alternate" type="application/rss+xml">`` a site publishes so that readers can find its feed.

What this reaches, and nothing else (the world-discovery disclosure names the same, and
``tests/test_qualification_trial_disclosure_r773.py`` runs the real trial over a recording fetcher to hold it there):

* the home page, ``https://<domain>/``, through the ethical fetcher (robots.txt is the fetcher's own read, fail closed;
  per-host politeness; the SSRF guard; the transport and protected-mode rules of collection), a redirect off the
  site refused at the hop;
* the feed links that page names ON THE SAME SITE (the same host, ``www.`` ignored: the crawler's rule, so a subdomain is
  another site and a link carrying a user name or password is refused), at most
  ``TRIAL_FEED_LINKS_MAX`` of them. A feed link to another site is counted and never fetched: a candidate's trial reaches
  the candidate, and the disclosure says so;
* the articles such a feed lists ON THE SAME SITE, at most the trial's article count
  (``ingest_source(entry_site=...)``); an entry on another site is counted and never fetched. EVERY trial of a feed takes
  this filter (:func:`src.catalog.qualification.trial_fetch`), the second as much as the first: a trial judges THIS site;
* NO guessed feed addresses. Topic discovery probes nineteen common paths (R761); a trial runs unattended on every
  collection pass, so it reads only what the site itself publishes.

The trial does not grow the number of sites a pass contacts: it is the same candidate, inside the same per-pass budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from src.ingest import EthicalFetcher, FetchError
from src.monitoring.secret_scrub import record_text

#: At most this many of the page's own feed links are tried, in the order the page names them.
TRIAL_FEED_LINKS_MAX = 2

_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml")


class _FeedLinkParser(HTMLParser):
    """The ``href`` of every ``<link rel="alternate">`` whose ``type`` is a feed type, in document order."""

    def __init__(self, max_hrefs: int = 0) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self._seen: set[str] = set()
        self.max_hrefs = max_hrefs  # 0: no cap

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rels = a.get("rel", "").lower().split()
        if "alternate" in rels and a.get("type", "").strip().lower() in _FEED_TYPES and a.get("href", "").strip():
            href = a["href"].strip()
            if href not in self._seen and (not self.max_hrefs or len(self.hrefs) < self.max_hrefs):
                self._seen.add(href)
                self.hrefs.append(href)


#: At most this many feed links are read off one page: a page naming thousands of them (a hostile or broken page, up to the
#: fetcher's 10 MB) costs a bounded amount of work, and a real site names a handful.
PAGE_FEED_LINKS_READ_MAX = 50


def feed_links_in_page(html: str, page_url: str, *, max_links: int = PAGE_FEED_LINKS_READ_MAX) -> list[str]:
    """The absolute http(s) feed addresses ``html`` names, deduplicated, in document order (the first ``max_links``)."""
    p = _FeedLinkParser(max_links)
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # noqa: BLE001 - a page the parser cannot finish yields what it read so far
        pass
    out: list[str] = []
    seen: set[str] = set()
    for href in p.hrefs:
        try:
            url = urljoin(page_url, href)
            scheme = urlsplit(url).scheme
        except ValueError:
            continue
        if scheme in ("http", "https") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def same_site(url: str, domain: str) -> bool:
    """True when ``url`` is on the candidate's own site by the crawler's rule (:func:`src.ingest.crawl._off_site`): the same
    host, a leading ``www.`` ignored on both sides, any port, Unicode and punycode spellings one site. A subdomain is ANOTHER
    site (``gov.uk`` is not its ministries, ``wordpress.com`` not its blogs), and an address carrying a user name or a password
    is always off the site (R624). Fail closed: an address that cannot be read is off the site."""
    from src.ingest.crawl import _off_site, _registrable_host

    try:
        netloc = urlsplit(url).netloc
    except ValueError:
        return False
    base = _registrable_host(domain or "")
    return bool(base) and bool(netloc) and not _off_site(netloc, base)


@dataclass
class TrialFeedReport:
    page_url: str
    feeds: list[str] = field(default_factory=list)
    off_site: int = 0
    error: str | None = None


def find_trial_feed(fetcher: EthicalFetcher, domain: str) -> TrialFeedReport:
    """Read ``https://<domain>/`` and return the same-site feed links it names (at most ``TRIAL_FEED_LINKS_MAX``).

    A refusal or failure of the page (robots, airplane mode, an error answer) is reported in ``error`` and yields no
    feed; the caller then goes on to the sitemap channel, as before.
    """
    page = f"https://{domain}/"
    report = TrialFeedReport(page_url=page)
    from src.ingest.crawl import _kept_on_site, _registrable_host

    try:
        # a home page that redirects to another site is refused at the hop, as a sitemap's is (R629)
        resp = fetcher.fetch(page, require_html=True, redirect_scope=_kept_on_site(_registrable_host(domain)))
    except FetchError as exc:
        report.error = record_text(exc)[:200]
        return report
    base = resp.final_url or page
    for url in feed_links_in_page(resp.content, base):
        if not same_site(url, domain):
            report.off_site += 1
        elif len(report.feeds) < TRIAL_FEED_LINKS_MAX:
            report.feeds.append(url)
    return report


__all__ = ["PAGE_FEED_LINKS_READ_MAX", "TRIAL_FEED_LINKS_MAX", "TrialFeedReport", "feed_links_in_page", "find_trial_feed", "same_site"]
