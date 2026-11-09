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


# --- R631: a Unicode host and its punycode are one site, either way round; a host that cannot be encoded is off ---------------
# Before, the comparison read the host as written, so the three catalogue sources with a Unicode domain (공유.net, åa.no,
# севернаяправда.рф) lost every punycode child sitemap, page loc and crawl link, and a source written in punycode lost the
# Unicode ones. Both sides are now the form requests connects to (idna, UTS 46); a host that cannot be encoded fails closed.

_U, _A = "b\u00fccher.example", "xn--bcher-kva.example"


@pytest.mark.parametrize(("base", "other"), [(_U, _A), (_A, _U), ("\u00e5a.no", "xn--a-1fa.no"), ("xn--a-1fa.no", "\u00e5a.no")])
def test_a_unicode_host_and_its_punycode_are_one_site_either_way_round(base, other):
    from src.ingest.sitemap import _off_host

    site = _registrable_host(base)
    assert _off_host(f"https://{other}/a", site) is False
    assert _off_host(f"https://www.{other}/a", site) is False
    assert _off_host(f"https://{other.upper() if other.isascii() else other}/a", site) is False
    assert _off_host("https://evil.example/a", site) is True


@pytest.mark.parametrize(("base", "loc"), [(_U, f"https://{_A}/own"), (_A, f"https://{_U}/own")])
def test_a_sitemap_keeps_the_page_locs_its_source_writes_in_the_other_form(base, loc):
    _sess, report = _discover(host=base, sitemap=_urlset(loc, f"https://{_EVIL}/planted"))
    assert report.urls == [loc]
    assert report.skipped_off_host == [f"https://{_EVIL}/planted"]


@pytest.mark.parametrize(("base", "child"), [(_U, f"https://{_A}/sitemap-a.xml"), (_A, f"https://{_U}/sitemap-a.xml")])
def test_a_sitemap_index_follows_a_child_written_in_the_other_form(base, child):
    sess, report = _discover(host=base, sitemap=_index(child), routes=[(child, _urlset(f"https://{base}/own"))])
    assert child in sess.fetched
    assert report.urls == [f"https://{base}/own"]


@pytest.fixture()
def idn_db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


@pytest.mark.parametrize(("domain", "link_host"), [(_U, _A), (_A, _U)])
def test_a_crawl_kept_to_one_site_follows_its_own_links_in_the_other_form(idn_db, domain, link_host):
    idn_db.add(Source(name="IDN", domain=domain, language="de", rss_url=None, enabled=True, status=STATUS_QUALIFIED))
    idn_db.commit()
    src = idn_db.query(Source).one()
    link = f"https://{link_host}/eigen"
    sess = _Session()
    sess.route(f"https://{domain}/robots.txt", status_code=404, text="")
    sess.route(f"https://{link_host}/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    sess.route(f"https://{domain}", text=_page("Home", "x", links=[(link, "own"), (f"https://{_EVIL}/x", "evil")]))
    sess.route(link, text=_article("Eigen"))
    sess.route(f"https://{_EVIL}/x", text=_article("Evil"))
    crawl_source(idn_db, src, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=True))
    assert link in sess.fetched
    assert f"https://{_EVIL}/x" not in sess.fetched


_UNENCODABLE = [
    "a\u00e9" + "x" * 70 + ".example",  # a label over 63 once encoded
    "\u00e9..example",  # an empty label
    "\u00e9" * 300 + ".example",  # longer than any host name
    ("\u00e9" * 60 + ".") * 170000 + "example",  # 10 MB of short labels
]


@pytest.mark.parametrize("bad", _UNENCODABLE)
def test_a_host_that_cannot_be_encoded_is_off_the_site_never_a_crash(bad):
    from src.ingest.crawl import _off_site, _site_key

    assert _site_key(bad) is None
    assert _off_site(bad, "good.example") is True
    assert _off_site("good.example", bad) is True  # a site that cannot be encoded matches nothing
    assert _off_site(bad, bad) is True  # not even its own text: fail closed


def test_a_crawl_skips_a_link_whose_host_cannot_be_encoded_and_walks_the_rest(db, source):
    bad = "https://a\u00e9" + "x" * 70 + ".example/p"
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example", text=_page("Home", "x", links=[(bad, "bad"), (_OWN_A, "a")]))
    sess.route(_OWN_A, text=_article("A"))
    crawl_source(db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=True))
    assert _OWN_A in sess.fetched
    assert bad not in sess.fetched


def test_the_key_is_uts_46():
    # UTS 46 keeps ß (xn--zca, not the IDNA 2003 "ss") and maps a fullwidth letter to its ASCII one. This is the key's own
    # encoding, not the connection's: see the next test.
    from src.ingest.crawl import _off_site

    assert _off_site("xn--zca.example", "\u00df.example") is False
    assert _off_site("ss.example", "\u00df.example") is True
    assert _off_site("\uff42\u00fccher.example", _U) is False


# Names where UTS 46 and urllib3 (the encoding the connection is named by, IDNA 2008 label by label) part ways, or urllib3 refuses.
_KEY_AND_CONNECTION_DIFFER = [
    "\u03a3\u03a3.example",  # ΣΣ: urllib.parse lowers it to σσ (xn--4xaa), urllib3 each label to σς (xn--3xab)
    "\u0391\u03a3.\u0392\u0393",  # ΑΣ.ΒΓ
    "\uff47\uff4f\uff4f\uff44.example",  # fullwidth: UTS 46 maps it to good.example, urllib3 refuses it
    "\uff42\u00fccher.example",
    "\ufb01le.example",  # the fi ligature
    "\u017ftrasse.example",  # long s
    "a\u00ad\u00fc.example",  # a soft hyphen
]


def test_wherever_the_key_and_the_connection_name_a_host_differently_the_fetcher_refuses_it_before_any_request():
    # The independent read of R626 (S3): on the urllib3 the app pins, urllib3 encodes a non-ASCII host before requests' own
    # UTS 46 path is reached, so the key is not the connection's name for every host. It is safe because R622's parser check
    # refuses each name where the two differ, before any request: held here over a fixed and a seeded sample of hosts.
    import random

    from urllib3.util import parse_url

    from src.ingest import BlockedTarget, FetchError
    from src.ingest.crawl import _site_key

    rng = random.Random(626)
    pool = [*"abcxz09-", "\u00e9", "\u00df", "\u1e9e", "\u03c2", "\u03c3", "\u03a3", "\u0131", "\u0130", "\u212a",
            "\u00c5", "\u200d", "\u200c", "\u00ad", "\u034f", "\u0301", "\u0308", "\uff41", "\uff21", "\u0430",
            "\u0435", "\u05d0", "\u0627", "\u0661", "\u0e01", "\u4e00", "\uac00", "\u2160", "\u24d0", "\u1d43",
            "\ufb01", "\u017f", "\u0345", "\u1e9b", "\u2060"]
    hosts = {*_KEY_AND_CONNECTION_DIFFER, _U, "\u00e5a.no", "\u0444\u0430\u00df.de", "stra\u00dfe.de"}
    for _ in range(3000):
        hosts.add("".join(rng.choice(pool) for _ in range(rng.randint(1, 10))) + rng.choice([".example", ".de", ".gr"]))
    differ = refused = 0
    for host in sorted(hosts):
        url = f"https://{host}/x"
        try:
            ours = urlsplit(url).hostname
        except ValueError:
            continue  # unreadable: R626's own path, refused by the fetcher's first urlparse
        if not ours or ours.isascii():
            continue
        try:
            theirs: str | None = (parse_url(url).host or "").lower()
        except Exception:  # noqa: BLE001 - urllib3 refuses the name: requests would never connect to it
            theirs = None
        if _site_key(ours) is not None and _site_key(ours) == theirs:
            continue
        differ += 1
        with pytest.raises(BlockedTarget):
            _fetcher(_Session())._refuse_parser_mismatch(url)
        refused += 1
    assert refused == differ
    assert differ >= 500  # the sample is not vacuous (ΣΣ.example and the fullwidth names among them)
    for host in _KEY_AND_CONNECTION_DIFFER:  # and through the fetch itself: nothing requested
        sess = _Session()
        with pytest.raises(FetchError):
            _fetcher(sess).fetch(f"https://{host}/x")
        assert sess.fetched == []


def test_control_ascii_hosts_are_compared_as_before():
    from src.ingest.crawl import _site_key

    assert _site_key("good.example") == "good.example"
    assert _site_key("xn--bcher-kva.example") == "xn--bcher-kva.example"
    assert _site_key("") == ""


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


# --------------------------------------------------------------------------- #
# The independent read of R626: a backfill list saved before the fix (S1), the skip lists bounded (S2), the refusal's words (S4).
# --------------------------------------------------------------------------- #


def test_a_backfill_list_saved_before_r627_never_fetches_its_off_host_or_unreadable_locs(db, source, tmp_path):
    import json

    from src.ingest.archive_backfill import advance_backfill, load_state

    planted, credentialed = f"https://{_EVIL}/planted-bf", "https://u:p@good.example/x"
    sp = tmp_path / "backfill.json"
    sp.write_text(json.dumps({"active": {
        "source_id": source.id, "urls": [_OWN_A, planted, "http://[::1", credentialed, _OWN_B],
        "cursor": 0, "full_history": False, "tally": {},
    }}), "utf-8")
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(f"https://{_EVIL}/robots.txt", status_code=404, text="")
    for url in (_OWN_A, _OWN_B):
        sess.route(url, text=_article(url))
    sess.route(planted, text=_article("planted"))
    sess.route(credentialed, text=_article("credentialed"))
    out = advance_backfill(db, _fetcher(sess), per_pass=10, state_path=sp)
    assert planted not in sess.fetched and _EVIL not in _hosts(sess)  # before: fetched and stored as good.example's
    assert credentialed not in sess.fetched
    assert sess.fetched.count(_OWN_A) == 1 and sess.fetched.count(_OWN_B) == 1
    assert out["tally"] == {"stored": 2, "skipped_off_host": 2, "skipped_unreadable": 1}
    assert out["done"] is True and out["cursor"] == 5
    assert db.query(Article).count() == 2
    assert "p@" not in json.dumps(load_state(sp))  # nothing new written with the login (the old list is gone with "active")


def test_control_a_backfill_list_of_own_pages_is_walked_as_before(db, source, tmp_path):
    import json

    from src.ingest.archive_backfill import advance_backfill

    own = ["https://good.example/a", "https://www.good.example/b", "https://GOOD.example:8443/c"]
    sp = tmp_path / "backfill.json"
    sp.write_text(json.dumps({"active": {"source_id": source.id, "urls": own, "cursor": 0, "full_history": False, "tally": {}}}),
                  "utf-8")
    calls: list[str] = []

    def _ingest(session, src, url, *, fetcher):
        from src.ingest.pipeline import IngestOutcome, IngestResult

        calls.append(url)
        return IngestOutcome(url=url, result=IngestResult.STORED, article_id=None, detail=None)

    out = advance_backfill(db, object(), per_pass=10, state_path=sp, ingest_fn=_ingest)
    assert calls == own
    assert out["tally"] == {"stored": 3}


def test_a_discovery_lists_the_first_hundred_off_host_locs_and_counts_them_all():
    from src.ingest.sitemap import SKIPPED_OFF_HOST_KEPT

    off = [f"https://{_EVIL}/p{i}?k=u:p@x" for i in range(150)]
    child = f"https://{_EVIL}/sitemap.xml"
    _sess, report = _discover(sitemap=_index(child, "https://good.example/own.xml"),
                              routes=[("https://good.example/own.xml", _urlset(*off, _OWN_A))])
    assert report.urls == [_OWN_A]
    assert SKIPPED_OFF_HOST_KEPT == 100
    assert report.skipped_off_host == [child, *(failure_url(u) for u in off[:99])]
    assert report.skipped_off_host_count == 151  # the child and every page loc
    assert report.stopped_reason == "completed"


def test_a_discovery_stops_once_it_has_skipped_four_times_max_urls_page_locs():
    off = [f"https://{_EVIL}/p{i}" for i in range(20)]
    _sess, report = _discover(sitemap=_urlset(*off, _OWN_A), max_urls=5)
    assert report.urls == []
    assert report.skipped_off_host_count == 20
    assert report.stopped_reason == "max_skipped"
    # unreadable locs count toward the same bound
    _sess, report = _discover(sitemap=_urlset(*off[:10], *(f"https://[p{i}]/x" for i in range(10)), _OWN_A), max_urls=5)
    assert report.urls == [] and report.skipped_unreadable == 10
    assert report.stopped_reason == "max_skipped"


def test_control_a_discovery_under_the_skip_bound_keeps_the_page_after_its_skipped_locs():
    off = [f"https://{_EVIL}/p{i}" for i in range(19)]
    _sess, report = _discover(sitemap=_urlset(*off, _OWN_A), max_urls=5)
    assert report.urls == [_OWN_A]
    assert report.stopped_reason == "completed"


def test_the_skip_bound_also_stops_before_the_next_child_sitemap():
    off = [f"https://{_EVIL}/p{i}" for i in range(20)]
    first, second = "https://good.example/one.xml", "https://good.example/two.xml"
    sess, report = _discover(sitemap=_index(first, second), routes=[(first, _urlset(*off)), (second, _urlset(_OWN_A))],
                             max_urls=5)
    assert second not in sess.fetched
    assert report.stopped_reason == "max_skipped"


def test_only_kept_page_locs_count_toward_max_urls():
    off = [f"https://{_EVIL}/p{i}" for i in range(3)]
    own = ["https://good.example/a", "https://good.example/b", "https://good.example/c"]
    _sess, report = _discover(sitemap=_urlset(*off, *own), max_urls=2)
    assert report.urls == own[:2]
    assert report.stopped_reason == "max_urls"


def test_the_fetcher_refusal_of_an_unreadable_url_keeps_its_password_out_and_chains_nothing():
    from src.ingest import FetchFailed

    sess = _Session()
    with pytest.raises(FetchFailed) as caught:
        _fetcher(sess).fetch("https://u:hunter2@[::1/x")
    assert "hunter2" not in str(caught.value)
    assert str(caught.value) == f"unsupported or malformed URL: {failure_url('https://u:hunter2@[::1/x')!r}"
    assert caught.value.__cause__ is None and caught.value.__context__ is None  # no ValueError carried along
    assert sess.fetched == []


def test_a_feed_item_link_that_is_unreadable_and_credentialed_stores_no_password(db, source, caplog):
    from src.ingest.pipeline import ingest_url

    caplog.set_level("DEBUG")
    sess = _Session()
    outcome = ingest_url(db, source, "https://u:hunter2@[::1/x", fetcher=_fetcher(sess))
    assert outcome.result.value == "fetch_failed"
    assert "hunter2" not in (outcome.detail or "")  # the stored failure (outcome.url is the URL as handed in, never stored)
    assert "hunter2" not in caplog.text
    assert sess.fetched == []
