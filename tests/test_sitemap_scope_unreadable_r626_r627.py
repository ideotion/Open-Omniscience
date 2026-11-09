"""
One unreadable link or sitemap loc no longer ends a source's crawl (R626); a sitemap's page locs are held to the source's host (R627).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R626. ``urllib.parse`` raises a bare ``ValueError`` on an href or a loc such as ``http://[::1`` (an unclosed IPv6 bracket), a
bracketed host that is no address, or a netloc NFKC would change. ``src.ingest.crawl._harvest_links`` let it out, which ended the
whole crawl of the source; ``discover_sitemap_urls`` let it out of a child sitemap's (or a robots-declared sitemap's) host check,
which ended the whole discovery; and a page loc was handed on unread, so the caller's ``ingest_url`` raised it and the walk of
the rest of the sitemap's pages ended. Each is now skipped and counted: ``CrawlReport.skipped_unreadable`` (also in its
``to_dict``) and ``SitemapDiscoveryReport.skipped_unreadable``, each a count of distinct links or locs.

R627. A urlset's page locs were never host-checked (only child sitemaps were), so a sitemap could make the app fetch pages on
other sites and store them as the source's. They are held by the child sitemaps' own rule, ``_registrable_host(...) !=
base_host`` (host after the last ``@``, lower-cased, without its port or a leading ``www.``), and listed in
``skipped_off_host`` through ``failure_url`` (no userinfo kept). The rule is the host, not the registrable domain: a subdomain
such as ``edition.good.example`` under the source ``good.example`` is off the host, as it already was for a child sitemap and
for the crawl's links (tested below as the stated effect). A loc carrying a userinfo for the source's own host is not pinned
here either way: R630 (folded into R624) drops it.

Driven through the real ``crawl_source``, ``discover_sitemap_urls``, ``sitemap_trial_ingest`` and the housekeeping lane's crawl
rung, with a real ``EthicalFetcher`` over an injected session that answers in memory (as tests/test_crawl_scope_userinfo_r624.py
does); nothing leaves the process. Every planted off-site page has a route, so a fetch of it is SEEN, never assumed. The
credentials are fakes.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED
from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher
from src.ingest.crawl import CrawlConfig, _registrable_host, crawl_source
from src.ingest.fetch_verdict import failure_url
from src.ingest.sitemap import discover_sitemap_urls, sitemap_trial_ingest
from src.utils.url_utils import canonicalize_url

_EVIL = "evil.example"


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _Session:
    """Answers in memory: a routed URL (matched as written) gets its page, anything else a 404 (robots: allow-all)."""

    def __init__(self):
        self.headers = {}
        self._routes: dict[str, _Resp] = {}
        self.fetched: list[str] = []

    def route(self, url, **kwargs):
        self._routes[url] = _Resp(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        self.fetched.append(url)
        if url in self._routes:
            return self._routes[url]
        return _Resp(status_code=404, text="not found", url=url)


def _fetcher(session):
    return EthicalFetcher(min_interval_s=0.0, session=session)


def _hosts(session) -> set[str | None]:
    return {urlsplit(u).hostname for u in session.fetched}


def _page(title, body_sentence, links=()):
    body = (body_sentence + " ") * 30
    anchors = "".join(f'<a href="{href}">{txt}</a>' for href, txt in links)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p>{anchors}</article></body></html>"
    )


def _article(title):
    return _page(title, f"A real article body about {title}, long enough to be stored.")


def _urlset(*locs: str) -> str:
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
        + "</urlset>"
    )


def _index(*children: str) -> str:
    return (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
        + "</sitemapindex>"
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good", domain="good.example", language="en", rss_url=None, enabled=True, status=STATUS_QUALIFIED))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


# Each of these makes urljoin/urldefrag/urlparse raise a bare ValueError.
_UNREADABLE = [
    "http://[::1",  # an unclosed IPv6 bracket (the ruling's example)
    "https://[::1/x",
    "https://good.example]/x",  # a stray closing bracket
    "https://[foo]/x",  # a bracketed host that is no address
    "//[::1",  # scheme-relative
    "https://a＃b/x",  # FULLWIDTH NUMBER SIGN: NFKC would make it a "#"
    "https://u[@good.example/x",  # a bracket in the userinfo: urlsplit refuses the whole netloc
]

_OWN_A = "https://good.example/own-a"
_OWN_B = "https://good.example/own-b"


def test_every_unreadable_case_is_one_urllib_refuses():
    # the premise of the cases below: if urllib.parse ever reads one of them, its tests prove nothing
    from urllib.parse import urljoin

    for bad in _UNREADABLE:
        with pytest.raises(ValueError):
            urljoin("https://good.example/", bad)


# --------------------------------------------------------------------------- #
# R626 in the crawl.
# --------------------------------------------------------------------------- #


def _crawl(db, source, home_links, *, extra_routes=(), max_depth=1):
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route("https://good.example", text=_page("Home", "x", links=[(h, "link") for h in home_links]))
    sess.route(_OWN_A, text=_article("own a"))
    sess.route(_OWN_B, text=_article("own b"))
    for url, kwargs in extra_routes:
        sess.route(url, **kwargs)
    report = crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=max_depth, max_pages=50))
    return sess, report


@pytest.mark.parametrize("bad", _UNREADABLE)
def test_crawl_skips_an_unreadable_link_counts_it_and_crawls_the_rest(db, source, bad):
    sess, report = _crawl(db, source, [_OWN_A, bad, _OWN_B])
    assert _OWN_A in sess.fetched and _OWN_B in sess.fetched  # the link AFTER the bad one too
    assert report.tally["stored"] == 2
    assert report.skipped_unreadable == 1
    assert report.stopped_reason == "completed"
    assert report.to_dict()["skipped_unreadable"] == 1


def test_crawl_counts_each_unreadable_link_once_however_often_it_appears(db, source):
    bad1, bad2 = "http://[::1", "https://[foo]/x"
    own_a_page = _page("Own A", "A real article body about own a, long enough to be stored.", links=[(bad1, "again"), (_OWN_B, "b")])
    sess, report = _crawl(
        db, source, [bad1, bad1, _OWN_A, bad2], extra_routes=[(_OWN_A, {"text": own_a_page})], max_depth=2
    )
    assert _OWN_A in sess.fetched and _OWN_B in sess.fetched  # reached through the page that repeats bad1
    assert report.tally["stored"] == 2
    assert report.skipped_unreadable == 2  # bad1 (three times, on two pages) and bad2


def test_crawl_counts_an_unreadable_link_on_a_page_that_is_no_article(db, source):
    # the harvest reads every fetched page, stored or not: the home page here is too short to be an article
    sess, report = _crawl(db, source, ["http://[::1"])
    assert report.pages_fetched == 1
    assert report.skipped_unreadable == 1


def test_control_a_bracket_in_a_relative_link_is_a_path_and_is_followed(db, source):
    # urljoin reads "[::1" without "//" as a path on the page's own host: readable, so never counted
    target = "https://good.example/[::1"
    sess, report = _crawl(db, source, ["[::1"], extra_routes=[(target, {"text": _article("bracket path")})])
    assert target in sess.fetched
    assert report.tally["stored"] == 1


def test_control_a_port_out_of_range_never_ends_the_crawl_and_is_never_requested(db, source):
    # urlparse reads it (only .port raises, and _registrable_host catches that); the fetcher refuses it before any request
    bad_port = "https://good.example:99999/x"
    sess, report = _crawl(db, source, [_OWN_A, bad_port, _OWN_B], extra_routes=[(bad_port, {"text": _article("port")})])
    assert bad_port not in sess.fetched
    assert _OWN_A in sess.fetched and _OWN_B in sess.fetched
    assert report.tally["stored"] == 2
    assert report.tally["fetch_failed"] == 1


def test_control_a_page_of_readable_links_is_crawled_as_before(db, source):
    sess, report = _crawl(db, source, [_OWN_A, f"https://{_EVIL}/x", _OWN_B])
    assert report.tally["stored"] == 2
    assert _EVIL not in _hosts(sess)
    assert report.stopped_reason == "completed"


@pytest.mark.parametrize("bad", [*_UNREADABLE, "https://good.example:99999/x", "https://good.example:abc/x", "http://", ""])
def test_control_the_helpers_a_link_passes_through_never_raise(bad):
    # _registrable_host and canonicalize_url are read per link and per loc; neither raises on a link urllib cannot read
    netloc = bad.split("//", 1)[-1].split("/", 1)[0]
    _registrable_host(netloc)
    assert canonicalize_url(bad) is not None


# --------------------------------------------------------------------------- #
# R626 in the sitemap discovery.
# --------------------------------------------------------------------------- #


def _discover(*, sitemap=None, robots=None, routes=(), host="good.example", max_urls=500):
    sess = _Session()
    if robots is None:
        sess.route(f"https://{host}/robots.txt", status_code=404, text="")  # declares nothing: the conventional paths
    else:
        sess.route(f"https://{host}/robots.txt", text=robots, content_type="text/plain")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    if sitemap is not None:
        sess.route(f"https://{host}/sitemap.xml", text=sitemap, content_type="text/xml")
    for url, body in routes:
        sess.route(url, text=body, content_type="text/xml" if url.endswith(".xml") else "text/html")
    return sess, discover_sitemap_urls(_fetcher(sess), host, max_urls=max_urls)


@pytest.mark.parametrize("bad", _UNREADABLE)
def test_an_unreadable_page_loc_is_skipped_and_counted(bad):
    _sess, report = _discover(sitemap=_urlset(_OWN_A, bad, _OWN_B))
    assert report.urls == [_OWN_A, _OWN_B]
    assert report.skipped_unreadable == 1
    assert bad not in report.skipped_off_host
    assert not any(bad in e for e in report.errors)  # (the second conventional path's 404 is the only error)


@pytest.mark.parametrize("bad", _UNREADABLE)
def test_an_unreadable_child_sitemap_is_skipped_and_counted_and_the_next_child_followed(bad):
    child = "https://good.example/sitemap-own.xml"
    sess, report = _discover(sitemap=_index(bad, child), routes=[(child, _urlset(_OWN_A))])
    assert child in sess.fetched
    assert report.urls == [_OWN_A]
    assert report.skipped_unreadable == 1
    assert report.child_sitemaps_fetched == 2  # the index and its readable child
    assert report.stopped_reason == "completed"


def test_an_unreadable_sitemap_declared_in_robots_is_skipped_and_counted():
    declared = "https://good.example/sitemap-declared.xml"
    robots = f"User-agent: *\nAllow: /\nSitemap: http://[::1\nSitemap: {declared}\n"
    sess, report = _discover(robots=robots, routes=[(declared, _urlset(_OWN_A))])
    assert declared in sess.fetched
    assert report.urls == [_OWN_A]
    assert report.skipped_unreadable == 1


def test_the_same_unreadable_loc_is_counted_once():
    child = "https://good.example/sitemap-own.xml"
    bad_child, bad_page = "http://[::1", "https://[foo]/x"
    _sess, report = _discover(
        sitemap=_index(bad_child, bad_child, child), routes=[(child, _urlset(bad_page, _OWN_A, bad_page))]
    )
    assert report.urls == [_OWN_A]
    assert report.skipped_unreadable == 2


# --------------------------------------------------------------------------- #
# R627: page locs held to the source's host by the child sitemaps' rule.
# --------------------------------------------------------------------------- #

_OFF_HOST = [
    f"https://{_EVIL}/planted",
    "https://good.example.evil.example/planted",  # the source's name as a label of another host
    "https://evilgood.example/planted",
    "https://good.example:x@evil.example/planted",  # text before the last @ (R624): the host is evil.example
    "https://[2001:db8::1]/planted",
]


@pytest.mark.parametrize("off", _OFF_HOST)
def test_an_off_host_page_loc_is_skipped_and_listed(off):
    _sess, report = _discover(sitemap=_urlset(_OWN_A, off, _OWN_B))
    assert report.urls == [_OWN_A, _OWN_B]
    assert report.skipped_off_host == [failure_url(off)]
    assert report.skipped_unreadable == 0


def test_the_same_off_host_page_loc_is_listed_once():
    off = f"https://{_EVIL}/planted"
    _sess, report = _discover(sitemap=_urlset(off, _OWN_A, off))
    assert report.urls == [_OWN_A]
    assert report.skipped_off_host == [failure_url(off)]


def test_a_subdomain_page_loc_is_off_the_host_by_the_same_rule_as_a_child_sitemap():
    # The stated effect of "same rule": host minus www., not the registrable domain. A child sitemap on the subdomain was
    # already skipped; a page on it now is too.
    sub_page = "https://edition.good.example/a"
    sub_child = "https://edition.good.example/sitemap.xml"
    _sess, report = _discover(sitemap=_index(sub_child, "https://good.example/sitemap-own.xml"),
                              routes=[("https://good.example/sitemap-own.xml", _urlset(_OWN_A, sub_page))])
    assert report.urls == [_OWN_A]
    assert report.skipped_off_host == [sub_child, sub_page]


def test_an_idn_source_written_in_its_unicode_form_does_not_match_its_punycode_locs():
    # A stated effect of "same rule" (_registrable_host compares the host as written, lower-cased, never IDNA-encoded): the
    # three catalogue sources with a Unicode domain lose any page loc their sitemap writes in punycode, as their punycode child
    # sitemaps and crawl links already were.
    from src.ingest.sitemap import _off_host

    base = _registrable_host("b\u00fccher.example")
    assert _off_host("https://b\u00fccher.example/a", base) is False
    assert _off_host("https://xn--bcher-kva.example/a", base) is True


def test_a_page_loc_without_a_host_is_off_the_host_by_the_same_rule():
    # a relative loc (the protocol asks for absolute ones) names no host; the fetcher refused it anyway, now it is not handed on
    _sess, report = _discover(sitemap=_urlset("/relative/a", _OWN_A))
    assert report.urls == [_OWN_A]
    assert report.skipped_off_host == ["/relative/a"]


@pytest.mark.parametrize(
    "kept",
    [
        "https://www.good.example/a",
        "https://GOOD.Example/b",
        "https://WWW.Good.Example/c",
        "https://good.example:443/d",
        "https://good.example:8443/e",  # same-site, not same-origin: the port is not compared
        "http://good.example/g",
        "https://good.example/@name",  # an @ in the path or query is no userinfo (R630 reads the netloc's)
        "https://good.example/h?by=a@b.example",
    ],
)
def test_control_the_source_host_however_spelled_is_kept(kept):
    _sess, report = _discover(sitemap=_urlset(kept))
    assert report.urls == [kept]
    assert report.skipped_off_host == []


def test_control_a_www_source_keeps_its_pages_on_the_bare_host_and_on_www():
    locs = ("https://good.example/a", "https://www.good.example/b")
    _sess, report = _discover(sitemap=_urlset(*locs), host="www.good.example")
    assert report.urls == list(locs)
    assert report.skipped_off_host == []


def test_control_a_port_out_of_range_loc_is_kept_for_the_fetcher_to_refuse():
    # urlparse reads it, so it is neither unreadable nor off the host; the fetcher refuses it before any request (below)
    _sess, report = _discover(sitemap=_urlset("https://good.example:99999/x", _OWN_A))
    assert report.urls == ["https://good.example:99999/x", _OWN_A]


def test_control_an_off_host_child_sitemap_is_still_listed_and_never_fetched():
    child = f"https://{_EVIL}/sitemap.xml"
    sess, report = _discover(sitemap=_index(child), routes=[(child, _urlset(f"https://{_EVIL}/x"))])
    assert report.skipped_off_host == [child]
    assert child not in sess.fetched


# --------------------------------------------------------------------------- #
# The callers that walk the sitemap's pages: the qualification trial and the crawl rung.
# --------------------------------------------------------------------------- #


def _trial_session(*locs, extra=()):
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_urlset(*locs), content_type="text/xml")
    sess.route(_OWN_A, text=_article("own a"))
    sess.route(_OWN_B, text=_article("own b"))
    for url in extra:
        sess.route(url, text=_article("planted"))
    return sess


def test_trial_walks_past_an_unreadable_page_loc(db, source):
    sess = _trial_session(_OWN_A, "http://[::1", _OWN_B)
    result = sitemap_trial_ingest(db, source, _fetcher(sess), max_items=10)
    assert result["discovered"] == 2
    assert result["attempted"] == 2
    assert result["tally"]["stored"] == 2


def test_trial_never_fetches_an_off_host_page_loc(db, source):
    planted = f"https://{_EVIL}/planted"
    sess = _trial_session(_OWN_A, planted, extra=[planted])
    result = sitemap_trial_ingest(db, source, _fetcher(sess), max_items=10)
    assert planted not in sess.fetched
    assert _EVIL not in _hosts(sess)  # not even its robots.txt
    assert result["discovered"] == 1
    assert db.query(Article).count() == 1  # nothing of evil.example is stored as good.example's


def test_control_trial_walks_past_a_port_out_of_range_loc_without_requesting_it(db, source):
    bad_port = "https://good.example:99999/x"
    sess = _trial_session(bad_port, _OWN_A, extra=[bad_port])
    result = sitemap_trial_ingest(db, source, _fetcher(sess), max_items=10)
    assert bad_port not in sess.fetched
    assert result["attempted"] == 2
    assert result["tally"]["stored"] == 1
    assert result["tally"]["fetch_failed"] == 1


def test_crawl_rung_walks_past_an_unreadable_loc_and_never_fetches_an_off_host_one(db, source):
    from src.scheduler.runner import _lane_step_crawl
    from src.scheduler.settings import SchedulerSettings

    planted = f"https://{_EVIL}/planted"
    sess = _trial_session(_OWN_A, "http://[::1", _OWN_B, planted, extra=[planted])
    result = _lane_step_crawl(db, _fetcher(sess), SchedulerSettings(crawl_per_pass=1))
    assert result["sources_crawled"] == 1  # before: the ValueError failed the source, and its walk ended at the bad loc
    assert result["sitemap_urls_ingested"] == 2
    assert planted not in sess.fetched
    assert db.query(Article).count() == 2


# --- The fetcher itself: a feed item's unreadable link (R626, the build's read) -------------------------------------------------
# ``ingest_source`` hands each feed entry's link to ``ingest_url``, which calls ``EthicalFetcher.fetch``; its own ``urlparse``
# raised the bare ValueError, which ended the source's whole feed pass. It is now the fetcher's FetchFailed for an unsupported or
# malformed URL, which ``ingest_url`` already records as that item's failure.


def _rss(*links: str) -> str:
    items = "".join(f"<item><title>t{i}</title><link>{link}</link></item>" for i, link in enumerate(links))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Good</title>{items}</channel></rss>'


@pytest.mark.parametrize("bad", _UNREADABLE)
def test_the_fetcher_refuses_an_unreadable_url_as_malformed_and_requests_nothing(bad):
    from src.ingest import FetchFailed

    sess = _Session()
    with pytest.raises(FetchFailed) as caught:
        _fetcher(sess).fetch(bad)
    assert str(caught.value).startswith("unsupported or malformed URL: ")
    assert sess.fetched == []


def test_one_unreadable_feed_item_link_no_longer_ends_the_feed_pass(db, source):
    from src.ingest.pipeline import ingest_source

    good_a, good_b = "https://good.example/a", "https://good.example/b"
    source.rss_url = "https://good.example/feed.xml"
    db.commit()
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(source.rss_url, text=_rss(good_a, "http://[::1", good_b), content_type="application/rss+xml")
    sess.route(good_a, text=_article("A"))
    sess.route(good_b, text=_article("B"))
    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["entries"] == 3
    assert good_a in sess.fetched and good_b in sess.fetched  # the item after the bad one is still walked
    assert db.query(Article).count() == 2


def test_control_a_readable_malformed_url_is_still_refused_the_same_way():
    from src.ingest import FetchFailed

    sess = _Session()
    with pytest.raises(FetchFailed) as caught:
        _fetcher(sess).fetch("ftp://good.example/x")
    assert str(caught.value).startswith("unsupported or malformed URL: ")
    assert sess.fetched == []
