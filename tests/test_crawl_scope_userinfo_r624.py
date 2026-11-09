"""
A crawl or a sitemap index kept to one site reads a link's host the way the fetcher does: after the LAST ``@`` (R624).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src.ingest.crawl._registrable_host`` cut the netloc at its first ``:`` BEFORE taking the userinfo out, so the link
``https://good.example:x@evil.example/page`` read as ``good.example``: the crawl's same-domain check (``crawl_source``) and the
sitemap's off-host check (``discover_sitemap_urls``) both followed it to evil.example. Robots, the SSRF guard and politeness still
applied to evil.example, so no safety check was skipped, but a crawl kept to one site left its stated scope, and evil.example's
page was stored as an article of good.example. The host is now the fetcher's host key's (``src.ingest._host_netloc``, R621).

Driven through the real ``crawl_source`` and ``discover_sitemap_urls`` with a real ``EthicalFetcher`` over an injected session
that answers in memory, as tests/test_crawl.py and tests/test_sitemap.py do; nothing leaves the process. Every planted
evil.example URL has a route, so a follow is SEEN (the request is recorded and answered), never assumed. The credentials are fakes.

The cases:
- the bug: text before the ``@`` that holds a ``:`` (``good.example:x@``, ``good.example:443@``, ``www.good.example:x@``, an
  empty password); and IPv6, which the same cut read as ``[`` and its first group;
- variants that were never the bug and must stay off the site: ``good.example@``, ``u:p@evil.example``, a backslash either side
  of the ``@`` (the fetcher refuses a backslash in the authority, R622), ``%40`` for the ``@`` (a host of its own to both readers;
  the fetcher refuses a percent-encoded host), and a port that hides a ``%40`` (unreadable to urllib3, refused by the fetcher);
- a real userinfo for the SAME host (``u:p@good.example``), which the old cut read as the host ``u`` and refused: followed now;
- controls, unchanged from before: the same site however it is spelled (capitals, the default port, another port, ``www.``, a
  relative link, IPv6 capitals), and a plain host read as it was.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher, _host_netloc
from src.ingest.crawl import CrawlConfig, _off_site, _registrable_host, crawl_source
from src.ingest.fetch_verdict import failure_url
from src.ingest.sitemap import discover_sitemap_urls

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
    """The host of every request the fetcher made, as urllib.parse reads it."""
    return {urlsplit(u).hostname for u in session.fetched}


def _page(title, body_sentence, links=()):
    body = (body_sentence + " ") * 30
    anchors = "".join(f'<a href="{href}">{txt}</a>' for href, txt in links)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p>{anchors}</article></body></html>"
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good", domain="good.example", language="en"))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


# Text before the ``@`` holding a ``:`` -- the old cut read each of these as good.example.
_BUG = [
    "https://good.example:x@evil.example/page",
    "https://good.example:443@evil.example/page",
    "https://www.good.example:x@evil.example/page",
    "https://GOOD.example:x@evil.example/page",
    "https://good.example:@evil.example/page",
]
# Never the bug, and off the site to the old cut too: they must stay so.
_STAYS_OFF = [
    "https://good.example@evil.example/page",
    "https://u:p@evil.example/page",
    "https://good.example\\@evil.example/page",  # urlparse: evil.example (urllib3: good.example); off the site either way
    "https://good.example%40evil.example/page",  # %40 is not an @: one percent-encoded host, refused by the fetcher
]
# urlparse reads good.example, so these are on the site; the fetcher refuses each before any request is made.
_FETCHER_REFUSES = [
    "https://evil.example\\@good.example/page",  # urllib3 connects to evil.example: refused as a backslash in the authority (R622)
    "https://good.example:x%40evil.example/page",  # the port is not a number: urllib3 cannot parse it, refused
]
# The same site, spelled otherwise: followed.
_SAME_SITE = [
    "https://GOOD.Example/x",
    "https://good.example:443/x",
    "https://good.example:8443/x",  # same-site, not same-origin: the port is not compared
    "https://www.good.example/x",
    "/x",
]
# A userinfo for the SAME host. The old cut read it as the host ``u`` and refused it; the host key reads good.example, but a
# netloc holding an ``@`` stays OFF the site (the independent read's S1): following it would send the userinfo as a login and
# store it in the article and canonical URLs, so it is refused as before, now for that reason.
_SAME_HOST_USERINFO = [
    "https://u:p@good.example/x",
    "https://u@good.example/x",
    "https://u:p@www.good.example/x",
]


# --------------------------------------------------------------------------- #
# The helper itself.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "netloc, host",
    [
        ("good.example:x@evil.example", "evil.example"),
        ("good.example:443@evil.example", "evil.example"),
        ("www.good.example:x@evil.example", "evil.example"),
        ("a:b@good.example:c@evil.example", "evil.example"),  # the LAST @
        ("u:p@good.example", "good.example"),
        ("u:p@www.good.example:8443", "good.example"),
        ("[2001:db8::1]:8080", "2001:db8::1"),
        ("u:p@[2001:DB8::1]", "2001:db8::1"),
        ("u[x@good.example", "good.example"),  # urlsplit refuses this whole netloc (a lone bracket); the host key reads past it
        # off the site to the old cut as well, but read as something else (the whole string, or "u")
        ("good.example@evil.example", "evil.example"),
        ("u:p@evil.example", "evil.example"),
    ],
)
def test_the_host_follows_the_last_at_as_urllib_reads_it(netloc, host):
    assert _registrable_host(netloc) == host


@pytest.mark.parametrize(
    "netloc, host",
    [
        ("good.example", "good.example"),
        ("GOOD.Example", "good.example"),
        ("www.good.example", "good.example"),
        ("good.example:443", "good.example"),
        ("good.example:8443", "good.example"),
        ("news.example.", "news.example."),  # a trailing dot stays, as in the host key
    ],
)
def test_control_a_plain_host_reads_as_before(netloc, host):
    assert _registrable_host(netloc) == host


def test_a_netloc_urllib_cannot_read_again_never_raises_and_names_no_site():
    # urlsplit refuses a lone bracket after the @; the key comes back as written, and must not raise out of the crawl
    assert _registrable_host("u@good.example]") not in ("", "good.example")
    assert _registrable_host("u@GOOD.example:7]") == "GOOD.example:7]"  # exactly as written: never lower-cased or cut to a site
    assert _registrable_host("") == ""  # no host at all: no site, and no exception


@pytest.mark.parametrize("netloc", ["u:p@good.example", "u@good.example", "u:p@www.good.example:8443", "@good.example"])
def test_a_netloc_holding_an_at_is_off_the_site_even_when_its_host_is_the_site(netloc):
    assert _registrable_host(netloc) == "good.example"  # the host is read right
    assert _off_site(netloc, "good.example")  # and the link is still not the site's to follow


@pytest.mark.parametrize("netloc", ["good.example", "GOOD.example:443", "www.good.example:8443"])
def test_control_a_plain_netloc_of_the_site_is_on_it(netloc):
    assert not _off_site(netloc, "good.example")


@pytest.mark.parametrize("netloc, scheme", [("good.example:0", "https"), ("good.example:0", "http"), ("good.example:00", ""), ("good.example:0", "")])
def test_port_zero_is_the_default_port_in_the_host_key(netloc, scheme):
    # requests drops ``:0`` and connects to the scheme's default, so the key must not make it a host of its own
    assert _host_netloc(netloc, scheme) == "good.example"


# --------------------------------------------------------------------------- #
# The real crawl.
# --------------------------------------------------------------------------- #


def _crawl(db, source, link, *, start_url=None):
    sess = _Session()
    start = start_url or "https://good.example"
    start_host = urlsplit(start).netloc
    sess.route(f"https://{start_host}/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route(start, text=_page("Home", "x", links=[(link, "the link")]))  # too short to be an article
    target = link if "://" in link else f"https://{start_host}{link}"
    sess.route(target, text=_page("Planted", "A real article body, long enough to be stored."))
    report = crawl_source(
        db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50), start_url=start_url
    )
    return sess, report, target


@pytest.mark.parametrize("link", _BUG)
def test_crawl_does_not_follow_a_link_that_only_looks_like_the_site(db, source, link):
    sess, _report, target = _crawl(db, source, link)
    assert target not in sess.fetched
    assert _EVIL not in _hosts(sess)  # not even its robots.txt
    assert db.query(Article).count() == 0  # nothing of evil.example is stored as good.example's


@pytest.mark.parametrize("link", _STAYS_OFF + _FETCHER_REFUSES)
def test_crawl_never_requests_the_variants(db, source, link):
    sess, _report, target = _crawl(db, source, link)
    assert target not in sess.fetched
    assert _EVIL not in _hosts(sess)
    assert db.query(Article).count() == 0


@pytest.mark.parametrize("link", _SAME_SITE)
def test_control_crawl_follows_the_same_site_however_it_is_spelled(db, source, link):
    sess, report, target = _crawl(db, source, link)
    assert target in sess.fetched
    assert report.tally["stored"] == 1
    assert _EVIL not in _hosts(sess)


@pytest.mark.parametrize("link", _SAME_HOST_USERINFO)
def test_crawl_never_follows_a_link_that_carries_a_userinfo_for_the_same_host(db, source, link):
    sess, _report, target = _crawl(db, source, link)
    assert target not in sess.fetched  # the userinfo is never sent to the site as a login
    assert db.query(Article).count() == 0
    assert not [u for u in sess.fetched if "@" in u]


def test_crawl_keeps_two_ipv6_hosts_apart(db, source):
    # the old cut read both as "[2001"
    sess, _report, target = _crawl(db, source, "https://[2001:db8::2]/x", start_url="https://[2001:db8::1]/")
    assert target not in sess.fetched
    assert db.query(Article).count() == 0


def test_control_crawl_follows_the_same_ipv6_host(db, source):
    sess, report, target = _crawl(db, source, "https://[2001:DB8::1]/y", start_url="https://[2001:db8::1]/")
    assert target in sess.fetched
    assert report.tally["stored"] == 1


def test_crawl_from_a_credentialed_start_stays_on_its_host(db, source):
    # the start's own userinfo named the site "u" before: every genuine link was off it, and "u:..." links were on it
    start = "https://u:p@good.example/"
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    links = [("https://good.example/a", "a"), ("https://u:z@evil.example/b", "b"), ("https://u:q@good.example/c", "c")]
    sess.route(start, text=_page("Home", "x", links=links))
    sess.route("https://good.example/a", text=_page("A", "A real article body, long enough to be stored."))
    sess.route("https://u:z@evil.example/b", text=_page("B", "A real article body, long enough to be stored."))
    sess.route("https://u:q@good.example/c", text=_page("C", "A real article body, long enough to be stored."))
    crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50), start_url=start)
    assert "https://good.example/a" in sess.fetched  # the start's own host is still read through the key
    assert _EVIL not in _hosts(sess)
    assert "https://u:q@good.example/c" not in sess.fetched  # a harvested link's userinfo is never followed


# --------------------------------------------------------------------------- #
# The real sitemap discovery.
# --------------------------------------------------------------------------- #


def _index(child: str) -> str:
    return (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{child}</loc></sitemap></sitemapindex>"
    )


def _urlset(loc: str) -> str:
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{loc}</loc></url></urlset>"
    )


_PLANTED = f"https://{_EVIL}/planted-article"
_OWN = "https://good.example/own-article"


def _discover(child_page: str):
    child = child_page.replace("/page", "/sitemap-child.xml").replace("/x", "/sitemap-child.xml")
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")  # declares nothing: the conventional paths
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_index(child), content_type="text/xml")
    planted = _URLSET_EVIL if _EVIL in (urlsplit(child).hostname or "") else _URLSET_OWN
    sess.route(child, text=planted, content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    return sess, report, child


_URLSET_EVIL = _urlset(_PLANTED)
_URLSET_OWN = _urlset(_OWN)


@pytest.mark.parametrize("link", _BUG)
def test_sitemap_does_not_follow_a_child_that_only_looks_like_the_site(link):
    sess, report, child = _discover(link)
    assert failure_url(child) in report.skipped_off_host  # written masked (R621)
    assert child not in sess.fetched
    assert _EVIL not in _hosts(sess)
    assert _PLANTED not in report.urls


@pytest.mark.parametrize("link", _STAYS_OFF + _FETCHER_REFUSES)
def test_sitemap_never_requests_the_variants(link):
    sess, report, child = _discover(link)
    assert child not in sess.fetched
    assert _EVIL not in _hosts(sess)
    assert report.urls == []
    # reported either way: as off the site, or as the fetcher's refusal
    shown = failure_url(child)
    assert shown in report.skipped_off_host or any(e.startswith(shown) for e in report.errors)


@pytest.mark.parametrize("link", [u for u in _SAME_SITE if "://" in u])
def test_control_sitemap_follows_a_child_on_the_same_site(link):
    sess, report, child = _discover(link)
    assert child in sess.fetched
    assert child not in report.skipped_off_host
    assert report.urls == [_OWN]


@pytest.mark.parametrize("link", _SAME_HOST_USERINFO)
def test_sitemap_never_follows_a_child_that_carries_a_userinfo_for_the_same_host(link):
    sess, report, child = _discover(link)
    assert child not in sess.fetched
    assert failure_url(child) in report.skipped_off_host and "p@" not in " ".join(report.skipped_off_host)
    assert report.urls == []


def test_a_credentialed_sitemap_declared_in_robots_is_never_fetched_saved_or_written():
    # the independent read's measured case: robots.txt declares a sitemap with a login in it
    declared = "https://bot:s3cret-FAKE@good.example/sitemap.xml"
    sess = _Session()
    sess.route("https://good.example/robots.txt", text=f"User-agent: *\nAllow: /\nSitemap: {declared}\n", content_type="text/plain")
    sess.route(declared, text=_URLSET_OWN, content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    assert declared not in sess.fetched
    assert report.root_sitemap_url is None  # nothing for update_source_sitemap_url to save
    assert "s3cret" not in repr(report)
    assert failure_url(declared) in report.skipped_off_host


def test_a_www_source_domain_reads_its_children_on_the_bare_host_as_its_own():
    # the base host goes through the same www. strip as each child
    sess = _Session()
    sess.route("https://www.good.example/robots.txt", status_code=404, text="")
    sess.route("https://www.good.example/sitemap.xml", text=_index("https://good.example/sitemap-child.xml"), content_type="text/xml")
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap-child.xml", text=_URLSET_OWN, content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "www.good.example")
    assert "https://good.example/sitemap-child.xml" in sess.fetched
    assert report.urls == [_OWN]


# --------------------------------------------------------------------------- #
# R630: a link or a sitemap page address carrying a userinfo is never followed or stored, whatever the crawl's scope.
# --------------------------------------------------------------------------- #

_CREDENTIALED = ["https://u:p@good.example/x", "https://u@good.example/x", "https://u:p@evil.example/x", "https://@good.example/x"]


@pytest.mark.parametrize("link", _CREDENTIALED)
def test_an_open_scope_crawl_never_follows_a_link_that_carries_a_userinfo(db, source, link):
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route("https://good.example", text=_page("Home", "x", links=[(link, "the link")]))
    sess.route(link, text=_page("Planted", "A real article body, long enough to be stored."))
    crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=False))
    assert link not in sess.fetched
    assert not [u for u in sess.fetched if "@" in u]
    assert db.query(Article).count() == 0


def test_control_an_open_scope_crawl_still_follows_a_plain_off_site_link(db, source):
    link = f"https://{_EVIL}/x"
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route("https://good.example", text=_page("Home", "x", links=[(link, "the link")]))
    sess.route(link, text=_page("Planted", "A real article body, long enough to be stored."))
    crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=False))
    assert link in sess.fetched  # an open-scope crawl's behaviour is otherwise unchanged


_CREDENTIALED_LOCS = [
    "https://u:p@good.example/own-article",
    "https://u@good.example/own-article",
    "https://@good.example/own-article",  # an empty userinfo
    "https://good.example:x@evil.example/own-article",  # R624's own form
    "https://u:p@evil.example/own-article",
]


@pytest.mark.parametrize("loc", _CREDENTIALED_LOCS)
def test_a_sitemap_page_address_that_carries_a_userinfo_is_never_kept(loc):
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_urlset(loc), content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    assert report.urls == []
    assert failure_url(loc) in report.skipped_off_host
    assert "u:p" not in repr(report)


def test_control_a_plain_sitemap_page_address_is_kept():
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_URLSET_OWN, content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    assert report.urls == [_OWN]


@pytest.mark.parametrize("loc", _CREDENTIALED_LOCS)
def test_a_credentialed_page_address_in_a_child_urlset_is_never_kept(loc):
    # the same rule one level down: an index's child urlset (the independent read of R630, S3)
    child = "https://good.example/sitemap-child.xml"
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_index(child), content_type="text/xml")
    sess.route(child, text=_urlset(loc), content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    assert child in sess.fetched  # the child itself was read
    assert report.urls == []
    assert failure_url(loc) in report.skipped_off_host
    assert not [u for u in sess.fetched if "@" in u]


_AT_OUTSIDE_THE_AUTHORITY = ["https://good.example/@alice/post-1", "https://good.example/a?to=a@b.example", "https://good.example/a@b"]


@pytest.mark.parametrize("same_domain_only", [True, False])
@pytest.mark.parametrize("link", _AT_OUTSIDE_THE_AUTHORITY)
def test_control_an_at_sign_outside_the_authority_is_followed_in_both_scopes(db, source, link, same_domain_only):
    # R630 reads the netloc's @ only: a handle in a path or an address in a query is no userinfo
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example", text=_page("Home", "x", links=[(link, "the link")]))
    sess.route(link, text=_page("Own", "A real article body, long enough to be stored."))
    crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=same_domain_only))
    assert link in sess.fetched


@pytest.mark.parametrize("loc", _AT_OUTSIDE_THE_AUTHORITY)
def test_control_a_page_address_with_an_at_sign_outside_the_authority_is_kept(loc):
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/sitemap.xml", text=_urlset(loc), content_type="text/xml")
    report = discover_sitemap_urls(_fetcher(sess), "good.example")
    assert report.urls == [loc]
    assert report.skipped_off_host == []
