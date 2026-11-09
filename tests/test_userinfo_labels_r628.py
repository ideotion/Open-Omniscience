"""
A URL's userinfo out of four labels and keys: the link domain, the feed key, the canonical URL and the preflight host (R628).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R621 took the userinfo (``alice:hunter2@``) out of the fetcher's keys and the logs and left four places that read a URL's netloc
whole. Each is read here as the fetcher reads a host: what follows the LAST ``@``, as ``urllib.parse`` reads it.

1. ``src/services/link_analyzer/extractor.py``: a link's ``domain`` label (which the social, ad and tracking checks search) kept
   the userinfo, and internal against external compared two whole netlocs, so a link to the page's own host written with a
   userinfo, a port or ``www.`` read as external and was stored as an outbound ArticleLink, credentials and all.
2. ``src/database/feed_key.py``: the feed identity kept the userinfo, so a feed written with and without credentials was two
   sources. CONTINUITY: a key stored before R628 is read as its feed's key today (``read_feed_key``) by the add and import lookups.
3. ``src/utils/url_utils.py``: the canonical URL kept the userinfo, so the crawl's dedup fetched one page twice and the
   credentials reached the stored canonical_url. ``CANON_VERSION`` moves to url-v2 (its own rule). CONTINUITY: an article stored
   under url-v1's form is still found by the pre-fetch dedup (``url_v1_canonical``), so it is not fetched again.
4. ``src/monitoring/feed_preflight.py``: a report's host field (and the robots read built from it) carried the userinfo.

Driven through the real paths where one exists (``crawl_source`` and ``ingest_url`` with a real EthicalFetcher over an in-memory
session, ``_maybe_index_links``, ``SourceManager.create_source``, ``upsert_sources``, ``merge_corpus``, ``run_feed_preflight``);
nothing leaves the process. The credentials are fakes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.feed_key import feed_key
from src.database.models import Article, ArticleLink, Base, Source
from src.ingest import EthicalFetcher
from src.ingest.crawl import CrawlConfig, _registrable_host, crawl_source
from src.ingest.pipeline import IngestResult, _maybe_index_links, ingest_url
from src.services.link_analyzer.extractor import LinkExtractor
from src.utils import url_utils

_USER, _NEEDLE = "alice", "hunter2"
_CRED = f"{_USER}:{_NEEDLE}@"


def _clean(value: object) -> None:
    assert _NEEDLE not in str(value) and f"{_USER}:" not in str(value), value


# --------------------------------------------------------------------------- #
# Shared in-memory fetch harness (as tests/test_crawl_scope_userinfo_r624.py).
# --------------------------------------------------------------------------- #


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


def _page(title, body_sentence, links=()):
    body = (body_sentence + " ") * 30
    anchors = "".join(f'<a href="{href}">{txt}</a>' for href, txt in links)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p>{anchors}</article></body></html>"
    )


def _pages(sess) -> list[str]:
    """Every request that was not a robots read."""
    return [u for u in sess.fetched if not u.endswith("/robots.txt")]


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


# --------------------------------------------------------------------------- #
# 1. The link extractor
# --------------------------------------------------------------------------- #

_BASE = "https://a.example/story"


def _links(html, base=_BASE):
    return {link["url"]: link for link in LinkExtractor().extract_links(html, base_url=base)}


def _anchor(href):
    return f'<html><body><a href="{href}">t</a></body></html>'


@pytest.mark.parametrize("href", [f"https://{_CRED}b.example/x", f"https://{_CRED}b.example:8443/x"])
def test_a_links_domain_label_carries_no_userinfo(href):
    link = _links(_anchor(href))[href]
    _clean(link["domain"])
    assert link["domain"] in ("b.example", "b.example:8443")
    assert link["url"] == href  # the link itself is data handed back, kept as written


def test_the_regex_fallback_label_carries_no_userinfo():
    href = f"https://{_CRED}b.example/x"
    (link,) = LinkExtractor()._extract_links_with_regex(f"<a href='{href}'>t</a>", _BASE, None)
    assert link["domain"] == "b.example"


def test_control_a_plain_links_label_is_its_host_as_before():
    assert _links(_anchor("https://B.example:8443/x"))["https://B.example:8443/x"]["domain"] == "b.example:8443"


@pytest.mark.parametrize(
    "href, wrong",
    [
        ("https://twitter.com:x@news.example/a", "social"),  # the userinfo named a social site; the host is a news site
        ("https://doubleclick.net@news.example/a", "tracking"),
        ("https://adnxs.com:pw@news.example/a", "ad"),
    ],
)
def test_text_before_the_at_cannot_steer_the_label(href, wrong):
    assert _links(_anchor(href))[href]["link_type"] == "external" != wrong


@pytest.mark.parametrize(
    "href, label",
    [
        ("https://twitter.com/a", "social"),
        (f"https://{_CRED}twitter.com/a", "social"),  # the host is what is labelled, credentials or not
        ("https://stats.doubleclick.net/a", "tracking"),
    ],
)
def test_control_the_host_itself_still_labels_the_link(href, label):
    assert _links(_anchor(href))[href]["link_type"] == label


@pytest.mark.parametrize(
    "href",
    [
        f"https://{_CRED}a.example/x",  # the page's own host, written with a userinfo
        "https://a.example:8443/x",  # with a port
        "https://www.a.example/x",  # with www.
        f"https://{_CRED}WWW.A.example:443/x",
    ],
)
def test_a_same_host_link_spelled_otherwise_is_internal(href):
    assert _links(_anchor(href))[href]["link_type"] == "internal"


def test_a_credentialed_base_url_reads_its_own_host_as_internal():
    assert _links(_anchor("https://a.example/x"), base=f"https://{_CRED}a.example/")["https://a.example/x"]["link_type"] == "internal"


def test_control_no_host_after_the_at_is_no_site_even_against_a_base_with_none():
    # two empty hosts are not one site: a link with nothing after its @ is external, as two unequal netlocs were before
    x = LinkExtractor()
    parsed = SimpleNamespace(netloc="bob@", path="/x", scheme="https")
    assert x._determine_link_type("https://bob@/x", parsed, "a", "alice@") == "external"


@pytest.mark.parametrize("href", ["https://a.example/x", "https://A.EXAMPLE/x", "/x"])
def test_control_the_same_host_written_plainly_is_internal_as_before(href):
    links = _links(_anchor(href))
    assert next(iter(links.values()))["link_type"] == "internal"


@pytest.mark.parametrize(
    "href",
    [
        "https://b.example/x",
        "https://a.example@b.example/x",  # the userinfo names the page's host; the link goes to b.example
        "https://a.example:x@b.example/x",
        "https://a.example.b.example/x",
        "https://b.example/a.example",
    ],
)
def test_control_another_host_stays_external(href):
    assert _links(_anchor(href))[href]["link_type"] == "external"


@pytest.mark.parametrize(
    "netloc",
    [
        "good.example", "GOOD.Example", "www.good.example", "good.example:443", "good.example:8443", "news.example.",
        "u:p@good.example", "u:p@www.good.example:8443", "good.example:x@evil.example", "a:b@good.example:c@evil.example",
        "[2001:db8::1]:8080", "u:p@[2001:DB8::1]", "u[x@good.example", "good.example@evil.example", "",
        "u@GOOD.example:7]", "www.GOOD.example:7]",  # unreadable: both come back as written after the @
    ],
)
def test_the_extractors_site_is_the_crawls_registrable_host(netloc):
    """``_site`` is written in the extractor so that it does not load src.ingest (R621); the reading is the crawl's (R624)."""
    from src.services.link_analyzer.extractor import _site

    assert _site(netloc) == _registrable_host(netloc)


def _article(db, source):
    a = Article(title="t", url="https://a.example/story", canonical_url="https://a.example/story", source_id=source.id,
                content="c", hash="h" * 64)
    db.add(a)
    db.commit()
    return a


def test_ingest_stores_no_same_host_link_and_keeps_the_outbound_one(db, source):
    html = (
        f'<html><body><a href="https://{_CRED}a.example/own">own</a><a href="https://a.example:8443/port">port</a>'
        '<a href="https://www.a.example/www">www</a><a href="https://b.example/out">out</a></body></html>'
    )
    article = _article(db, source)
    _maybe_index_links(db, article, html, "https://a.example/story")
    assert [(r.url, r.link_type) for r in db.query(ArticleLink)] == [("https://b.example/out", "external")]


# --------------------------------------------------------------------------- #
# 2. The feed key
# --------------------------------------------------------------------------- #

_FEED = "https://a.example/feed"


@pytest.mark.parametrize(
    "spelled",
    [
        f"https://{_CRED}a.example/feed",
        f"http://{_CRED}A.example/feed/",
        f"{_CRED}a.example/feed",  # no scheme
        "https://alice@a.example/feed",
        f"https://x:y@{_CRED}a.example/feed",  # the LAST @
    ],
)
def test_the_feed_key_has_no_userinfo_and_is_the_plain_feeds(spelled):
    _clean(feed_key(spelled))
    assert feed_key(spelled) == feed_key(_FEED) == "f:a.example/feed"


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://a.example/@bob/feed", "https://a.example/feed"),  # an @ in the path is part of the feed
        ("https://a.example/feed?u=alice@x", "https://a.example/feed"),  # and in the query
        (f"https://{_CRED}a.example/feed", f"https://{_CRED}b.example/feed"),  # another host
        (f"https://{_CRED}a.example:8443/feed", "https://a.example/feed"),  # another port
    ],
)
def test_control_what_names_another_feed_still_does(a, b):
    assert feed_key(a) != feed_key(b)


def test_control_an_at_in_the_path_stays_in_the_key():
    assert feed_key("https://a.example/@bob/feed") == "f:a.example/@bob/feed"


_LEGACY = f"f:{_CRED}a.example/feed"  # the key a build before R628 stored for the credentialed feed


@pytest.mark.parametrize(
    "stored, rss_url, read",
    [
        (_LEGACY, f"https://{_CRED}a.example/feed", "f:a.example/feed"),
        ("f:a.example/feed", f"https://{_CRED}a.example/feed", "f:a.example/feed"),
        ("f:a.example/@bob/feed", "https://a.example/@bob/feed", "f:a.example/@bob/feed"),
        ("f:a.example/old", "https://a.example/new", "f:a.example/old"),  # no "@": read as stored, as before
        ("", None, ""),
        (None, None, ""),
    ],
)
def test_a_stored_key_is_read_as_its_feeds_key_today(stored, rss_url, read):
    from src.database.feed_key import read_feed_key

    assert read_feed_key(stored, rss_url) == read


@pytest.fixture()
def store():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _legacy_row(s, rss_url=f"https://{_CRED}a.example/feed", *, name="A", domain="a.example"):
    """A row as a build before R628 left it: the key computed with the userinfo kept."""
    row = Source(name=name, domain=domain, rss_url=rss_url)
    s.add(row)
    s.commit()
    legacy = "f:" + rss_url.split("://", 1)[1].lower()
    s.execute(text("UPDATE sources SET feed_key = :k WHERE id = :i"), {"k": legacy, "i": row.id})
    s.commit()
    s.expire_all()
    assert s.get(Source, row.id).feed_key == legacy
    return row.id


def _sibling(s, rss_url="https://a.example/other", domain="a.example"):
    s.add(Source(name="sibling", domain=domain, rss_url=rss_url))
    s.commit()


def test_adding_a_feed_already_held_with_credentials_is_not_a_second_source(store):
    from src.database.source_manager import SourceManager

    SourceManager(store).create_source("A", "a.example", rss_url=f"https://{_CRED}a.example/feed")
    got = SourceManager(store).create_source("A plain", "a.example", rss_url=_FEED)
    assert store.query(Source).count() == 1 and got.rss_url == f"https://{_CRED}a.example/feed"
    _clean(got.feed_key)


def _add_again(store, again):
    from src.database.source_lookup import source_for_feed
    from src.database.source_manager import SourceManager

    sid = _legacy_row(store)
    _sibling(store)
    assert source_for_feed(store, "a.example", again).id == sid
    SourceManager(store).create_source("A again", "a.example", rss_url=again)
    assert store.query(Source).count() == 2  # the legacy row and its sibling: no third row


def test_continuity_a_key_stored_before_r628_is_still_found_when_the_same_url_is_added_again(store):
    # the same credentialed URL matched its stored key before R628; without read_feed_key it would not any more
    _add_again(store, f"https://{_CRED}a.example/feed")


@pytest.mark.parametrize("again", [_FEED, "https://bob:other@a.example/feed"])
def test_the_same_feed_with_other_credentials_or_none_is_the_legacy_rows_source(store, again):
    _add_again(store, again)


def test_control_a_new_feed_of_the_domain_is_still_a_new_source(store):
    from src.database.source_lookup import source_for_feed

    _legacy_row(store)
    assert source_for_feed(store, "a.example", "https://a.example/another") is None
    assert source_for_feed(store, "b.example", _FEED) is None


def _sheet(*feeds, domain="a.example"):
    from src.catalog.csv_io import parse_sources_csv, write_csv

    rows = [{"name": f"A {i}", "domain": domain, "rss_url": f} for i, f in enumerate(feeds)]
    parsed, errors = parse_sources_csv(write_csv(rows))
    assert errors == []
    return parsed


def test_continuity_a_csv_import_edits_the_legacy_row_instead_of_adding_a_sibling(store):
    from src.catalog.csv_io import upsert_sources

    sid = _legacy_row(store)
    _sibling(store)
    res = upsert_sources(store, _sheet(f"https://{_CRED}a.example/feed", "https://a.example/third"))
    assert res["errors"] == [] and (res["created"], res["updated"]) == (1, 1)
    assert store.query(Source).count() == 3
    assert store.get(Source, sid).name == "A 0"  # the record landed on the legacy row


def test_continuity_a_yaml_import_edits_the_legacy_row_instead_of_adding_a_sibling(store, tmp_path):
    import yaml

    from src.database.source_manager import SourceManager

    sid = _legacy_row(store)
    _sibling(store)
    doc = {"sources": [
        {"name": "A yaml", "domain": "a.example", "rss_url": f"https://{_CRED}a.example/feed"},
        {"name": "A third", "domain": "a.example", "rss_url": "https://a.example/third"},
    ]}
    path = tmp_path / "sources.yml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    SourceManager(store).import_sources_from_yaml(str(path))
    assert store.query(Source).count() == 3
    assert store.get(Source, sid).name == "A yaml"


def test_an_orm_write_heals_a_legacy_key(store):
    sid = _legacy_row(store)
    row = store.get(Source, sid)
    row.enabled = False
    store.commit()
    store.expire_all()
    assert store.get(Source, sid).feed_key == "f:a.example/feed"


def _merge_corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_a_restore_reads_a_credentialed_feed_as_the_plain_one_it_holds(tmp_path):
    """Through the real ``merge_corpus``, on a domain with two feeds (where only the exact key matches): the incoming feed
    written with credentials is the local plain one, not a third source."""
    from src.backup.merge import merge_corpus

    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    with _merge_corpus(staged)() as s:
        s.add_all([Source(name="in A", domain="a.example", rss_url=f"https://{_CRED}a.example/feed"),
                   Source(name="in B", domain="a.example", rss_url="https://a.example/other")])
        s.commit()
    with _merge_corpus(working)() as s:
        s.add_all([Source(name="A", domain="a.example", rss_url=_FEED),
                   Source(name="B", domain="a.example", rss_url="https://a.example/other")])
        s.commit()
    merge_corpus(staged, working, {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
                                   "alembic_rev": "head", "manifest": None})
    con = sqlite3.connect(working)
    try:
        rows = sorted(con.execute("SELECT domain, feed_key FROM sources").fetchall())
    finally:
        con.close()
    assert rows == [("a.example", "f:a.example/feed"), ("a.example", "f:a.example/other")]


# --------------------------------------------------------------------------- #
# 3. The canonical URL
# --------------------------------------------------------------------------- #


def test_the_canonical_key_dedupes_the_credentialed_and_plain_forms_of_one_url():
    """Plan's required test (R628): one page, one canonical key."""
    assert url_utils.canonicalize_url(f"https://{_CRED}a.example/x") == url_utils.canonicalize_url("https://a.example/x")


@pytest.mark.parametrize(
    "url, canonical",
    [
        (f"https://{_CRED}a.example/x", "https://a.example/x"),
        (f"http://{_CRED}WWW.A.example:443/x/?utm_source=n&b=2#f", "https://a.example/x?b=2"),
        ("https://alice@a.example/x", "https://a.example/x"),
        (f"https://x:y@{_CRED}a.example/x", "https://a.example/x"),  # the LAST @
    ],
)
def test_a_canonical_url_carries_no_userinfo(url, canonical):
    assert url_utils.canonicalize_url(url) == canonical


@pytest.mark.parametrize(
    "url, canonical",
    [
        ("https://a.example/x", "https://a.example/x"),
        ("http://WWW.A.example:443/x/?utm_source=n&b=2#f", "https://a.example/x?b=2"),
        ("https://a.example/@bob?u=a@b", "https://a.example/@bob?u=a@b"),  # an @ outside the authority stays
        ("https://a.example:8443/x", "https://a.example:8443/x"),
    ],
)
def test_control_a_plain_url_canonicalises_as_before(url, canonical):
    assert url_utils.canonicalize_url(url) == canonical


def test_the_domain_and_base_readers_carry_no_userinfo():
    assert url_utils.get_domain_from_url(f"https://{_CRED}www.a.example/x") == "a.example"
    assert url_utils.get_base_url(f"https://{_CRED}a.example:443/x") == "https://a.example"


def test_control_the_domain_and_base_readers_of_a_plain_url():
    assert url_utils.get_domain_from_url("https://www.a.example/x") == "a.example"
    assert url_utils.get_base_url("https://a.example:443/x") == "https://a.example"


def test_the_canonicalisation_stamp_moved_and_a_new_article_carries_it(db, source):
    """``CANON_VERSION``'s own rule: bump it whenever canonicalize_url changes its rules. The self-heal backfill of rows that
    predate the column still writes url-v1, as the Alembic revision does (tests/test_article_identity_seams.py)."""
    assert url_utils.CANON_VERSION == "url-v2"
    a = Article(title="t", url="https://good.example/a", canonical_url="https://good.example/a", source_id=source.id,
                content="c", hash="b" * 64)
    db.add(a)
    db.commit()
    assert a.canon_version == "url-v2"


@pytest.mark.parametrize(
    "url, v1",
    [
        (f"https://{_CRED}a.example/x", f"https://{_CRED}a.example/x"),
        (f"http://{_CRED}WWW.A.example:443/x/", f"https://{_CRED}www.a.example/x"),  # url-v1 left www. behind a userinfo
        ("https://a.example/x", None),
        ("https://a.example/@bob", None),
        ("http://[::1/x", None),
        ("", None),
    ],
)
def test_url_v1_canonical_gives_back_the_form_a_build_before_r628_stored(url, v1):
    assert url_utils.url_v1_canonical(url) == v1


def _crawl_two_spellings(db, source, first, second, *, start="https://good.example/", same_domain_only=False):
    """A start page linking to ``first`` and ``second``, off the site's own check by default (``same_domain_only=False``). Since
    R630 a harvested link holding a userinfo is never followed or stored whatever the scope, so the two spellings of one page
    meet in the crawl only through the start URL (the credentialed start below)."""
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route(start, text=_page("Home", "x", links=[(first, "a"), (second, "b")]))
    for url in (first, second):
        sess.route(url, text=_page("Page X", "A real article body, long enough to be stored."))
    report = crawl_source(db, source, fetcher=_fetcher(sess),
                          config=CrawlConfig(max_depth=1, max_pages=50, same_domain_only=same_domain_only), start_url=start)
    return sess, report


@pytest.mark.parametrize(
    "first, second, fetched",
    [
        (f"https://{_CRED}good.example/x", "https://good.example/x", "https://good.example/x"),
        ("https://good.example/x", f"https://{_CRED}good.example/x", "https://good.example/x"),
        (f"https://{_CRED}good.example/x", "https://bob:other@good.example/x", None),
    ],
)
def test_the_crawl_fetches_one_page_written_with_and_without_credentials_once(db, source, first, second, fetched):
    """R630 with R628: the credentialed spelling is never followed, so the page is fetched at most once, as its plain link."""
    sess, report = _crawl_two_spellings(db, source, first, second)
    assert _pages(sess) == ["https://good.example/"] + ([fetched] if fetched else [])
    assert report.tally["stored"] == (1 if fetched else 0)
    assert all(a.canonical_url == "https://good.example/x" and a.url == fetched for a in db.query(Article))


def test_a_crawl_kept_to_one_site_from_a_credentialed_start_does_not_fetch_the_start_page_again(db, source):
    """The crawl's real mode (``same_domain_only``, what the scheduler runs): the start URL written with a login is queued under
    its canonical form, so the page's plain link back to itself is the same page, not a second fetch without credentials."""
    start = f"https://{_CRED}good.example/x"
    sess, report = _crawl_two_spellings(db, source, "https://good.example/x", "https://good.example/y", start=start,
                                        same_domain_only=True)
    assert _pages(sess) == [start, "https://good.example/y"]
    assert all(_NEEDLE not in a.canonical_url for a in db.query(Article))


def test_control_the_crawl_fetches_two_pages_once_each(db, source):
    sess, report = _crawl_two_spellings(db, source, "https://good.example/x", "https://good.example/y")
    assert _pages(sess) == ["https://good.example/", "https://good.example/x", "https://good.example/y"]


def test_control_a_crawl_kept_to_one_site_still_never_follows_a_credentialed_link(db, source):
    """R624's fold, unchanged: a link holding an ``@`` stays off the site, whatever its canonical form."""
    sess, report = _crawl_two_spellings(db, source, f"https://{_CRED}good.example/x", "https://good.example/y",
                                        same_domain_only=True)
    assert _pages(sess) == ["https://good.example/", "https://good.example/y"]


def _store(db, source, canonical):
    db.add(Article(title="stored", url=canonical, canonical_url=canonical, source_id=source.id, content="c", hash="s" * 64))
    db.commit()


def test_ingest_skips_a_credentialed_url_whose_plain_page_is_stored(db, source):
    _store(db, source, "https://good.example/x")
    sess = _Session()
    outcome = ingest_url(db, source, f"https://{_CRED}good.example/x", fetcher=_fetcher(sess))
    assert outcome.result is IngestResult.DUPLICATE
    assert sess.fetched == []


@pytest.mark.parametrize("again", [f"https://{_CRED}good.example/x", f"https://{_CRED}good.example/x?utm_source=feed"])
def test_continuity_an_article_stored_under_url_v1_is_not_fetched_again(db, source, again):
    _store(db, source, f"https://{_CRED}good.example/x")  # the canonical_url a build before R628 stored
    sess = _Session()
    outcome = ingest_url(db, source, again, fetcher=_fetcher(sess))
    assert outcome.result is IngestResult.DUPLICATE
    assert sess.fetched == []


def test_continuity_the_crawl_does_not_queue_a_page_stored_under_url_v1(db, source):
    _store(db, source, f"https://{_CRED}good.example/x")
    sess, report = _crawl_two_spellings(db, source, f"https://{_CRED}good.example/x", "https://good.example/y")
    # since R630 the credentialed link is dropped before the dedup is asked; this pins the outcome, R630's tests the reason
    assert _pages(sess) == ["https://good.example/", "https://good.example/y"]


def test_control_ingest_fetches_a_url_nothing_stored_names(db, source):
    _store(db, source, f"https://{_CRED}good.example/x")
    sess = _Session()
    sess.route("https://good.example/robots.txt", status_code=404, text="")
    sess.route("https://good.example/z", text=_page("Z", "A real article body, long enough to be stored."))
    outcome = ingest_url(db, source, "https://good.example/z", fetcher=_fetcher(sess))
    assert outcome.result is IngestResult.STORED
    assert _pages(sess) == ["https://good.example/z"]


# --------------------------------------------------------------------------- #
# 4. The feed preflight's report
# --------------------------------------------------------------------------- #


class _PreflightSession:
    def __init__(self):
        self.fetched: list[str] = []

    def get(self, url, **kw):
        self.fetched.append(url)
        return SimpleNamespace(status_code=404, text="")


class _PreflightFetcher:
    timeout = 5
    user_agent = "OpenOmniscienceBot/test"

    def __init__(self):
        self.session = _PreflightSession()
        self.fetched: list[str] = []

    def fetch(self, url, *, require_html=True):
        self.fetched.append(url)
        return SimpleNamespace(content="date,value\n2026-01-01,1\n")

    def _guard_target(self, host):
        return None

    def _guarded_redirect_get(self, url, **kw):
        return self.session.get(url), url


@pytest.fixture()
def catalogue(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    import src.events.feeds as event_feeds
    import src.markets.feed_catalog as feed_catalog

    def _set(market_urls=(), calendar_urls=()):
        feeds = [SimpleNamespace(key=f"m{i}", url=u) for i, u in enumerate(market_urls)]
        monkeypatch.setattr(feed_catalog, "load_feeds", lambda: feeds)
        monkeypatch.setattr(feed_catalog, "load_index_feeds", list)
        families = [{"key": "fam", "feeds": [{"id": f"c{i}", "url": u} for i, u in enumerate(calendar_urls)]}]
        monkeypatch.setattr(event_feeds, "load_families", lambda: families)

    return _set


def test_the_preflight_host_field_carries_no_userinfo(catalogue):
    from src.monitoring import feed_preflight as fpf

    catalogue([f"https://{_CRED}Markets.example/data.csv"], [f"https://{_CRED}cal.example:443/x.ics"])
    market, calendar = fpf._feed_targets()
    assert [t["host"] for t in market + calendar] == ["markets.example", "cal.example"]


def test_control_the_preflight_host_field_of_a_plain_url(catalogue):
    from src.monitoring import feed_preflight as fpf

    catalogue(["https://markets.example/data.csv"], ["http://cal.example:8080/x.ics"])
    market, calendar = fpf._feed_targets()
    assert [t["host"] for t in market + calendar] == ["markets.example", "cal.example:8080"]


def test_the_preflight_report_and_its_robots_read_carry_no_userinfo(catalogue):
    from src.monitoring import feed_preflight as fpf

    catalogue([f"https://{_CRED}markets.example/data.csv"])
    fetcher = _PreflightFetcher()
    summary = fpf.run_feed_preflight(fetcher, sample_per_provider=1)
    assert summary["complete"] is True and summary["hosts"] == 1
    assert fetcher.session.fetched == ["https://markets.example/robots.txt"]  # no credentials sent with the robots read
    hosts = [r["host"] for r in fpf.recent_results()]
    assert hosts == ["markets.example", "markets.example"]
    assert fetcher.fetched == [f"https://{_CRED}markets.example/data.csv"]  # the sample itself is fetched as given (R621)


# --------------------------------------------------------------------------- #
# Import cost: nothing new loads src.ingest.
# --------------------------------------------------------------------------- #


def test_the_touched_modules_still_import_without_src_ingest():
    import subprocess
    import sys

    code = (
        f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "import src.utils.url_utils, src.services.link_analyzer.extractor, src.database.feed_key, src.database.source_lookup\n"
        "print('src.ingest' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=Path(__file__).resolve().parents[1])
    assert out.stdout.strip().splitlines()[-1] == "False", out.stdout + out.stderr


@pytest.mark.parametrize("netloc", ["[::1", "u@[::1", "@", "", "a@b@", f"{_CRED}[::1"])
def test_the_extractors_site_never_raises_and_an_empty_host_is_no_site(netloc):
    from src.services.link_analyzer.extractor import _site

    site = _site(netloc)
    assert isinstance(site, str)
    _clean(site)


def test_an_unreadable_credentialed_link_is_dropped_without_raising():
    html = f'<a href="https://{_CRED}[::1/x">bad</a><a href="https://b.example/ok">ok</a>'
    links = LinkExtractor().extract_links(html, base_url=_BASE)
    assert [link["url"] for link in links if link["normalized_url"]] == ["https://b.example/ok"]
    for link in links:
        _clean(link["domain"])
