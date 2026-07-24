"""
Tests for the sitemap discovery channel (src/ingest/sitemap.py).

2026-07-24 throughput brief, C7. Fully faked HTTP (no network) via the same
_Resp/_Session pattern the rest of this suite uses for EthicalFetcher. Covers:
pure parsing (index + urlset, incl. a Google-News-namespaced urlset), robots-
declared sitemaps discovered, size bound honoured, the qualification trial
channel producing real extraction-validity evidence for a feedless candidate --
and the MANDATORY negative-space cases: a malformed/non-XML/empty body never
crashes, a billion-laughs entity-expansion attack is refused safely by
defusedxml, and a sitemap-index child on a DIFFERENT host is reported but never
followed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest import EthicalFetcher
from src.ingest.sitemap import (
    SitemapError,
    declared_sitemap_urls,
    default_sitemap_candidates,
    discover_sitemap_urls,
    parse_sitemap_xml,
    sitemap_trial_ingest,
    update_source_sitemap_url,
)


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/xml", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _Session:
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


def _fetcher(session, **kw):
    return EthicalFetcher(min_interval_s=0.0, session=session, **kw)


def _article_html(title, body_sentence):
    body = (body_sentence + " ") * 30
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-articles.xml</loc></sitemap>
</sitemapindex>"""

_URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc><lastmod>2026-07-20</lastmod></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>"""

_GOOGLE_NEWS_URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://example.com/news-1</loc>
    <news:news>
      <news:publication><news:name>Example</news:name><news:language>en</news:language></news:publication>
      <news:publication_date>2026-07-20</news:publication_date>
      <news:title>News 1</news:title>
    </news:news>
  </url>
</urlset>"""

_BILLION_LAUGHS_XML = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<urlset><url><loc>&lol2;</loc></url></urlset>
"""


# --------------------------------------------------------------------------- #
# Pure parsing.
# --------------------------------------------------------------------------- #


def test_parses_a_sitemap_index():
    result = parse_sitemap_xml(_INDEX_XML)
    assert result.kind == "index"
    assert result.sitemaps == ["https://example.com/sitemap-articles.xml"]
    assert result.urls == []


def test_parses_a_urlset():
    result = parse_sitemap_xml(_URLSET_XML)
    assert result.kind == "urlset"
    assert [e.loc for e in result.urls] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert result.urls[0].lastmod == "2026-07-20"
    assert result.urls[1].lastmod is None


def test_parses_a_google_news_sitemap_by_the_same_urlset_skeleton():
    """Google News sitemaps add namespaced <news:news> metadata but keep the
    SAME <urlset>/<url>/<loc> skeleton -- the localname match handles both
    uniformly without caring about the namespace URI."""
    result = parse_sitemap_xml(_GOOGLE_NEWS_URLSET_XML)
    assert result.kind == "urlset"
    assert [e.loc for e in result.urls] == ["https://example.com/news-1"]


# --------------------------------------------------------------------------- #
# NEGATIVE-SPACE (mandatory): malformed/empty/non-XML never crashes; a
# billion-laughs entity-expansion attack is refused safely by defusedxml.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "data",
    ["not xml at all", "<urlset><url><loc>", "<html><body>hi</body></html>", "", "   "],
)
def test_malformed_non_xml_and_wrong_root_bodies_raise_a_typed_error_never_crash(data):
    with pytest.raises(SitemapError):
        parse_sitemap_xml(data)


def test_a_billion_laughs_entity_expansion_attack_is_refused_safely():
    with pytest.raises(SitemapError):
        parse_sitemap_xml(_BILLION_LAUGHS_XML)


# --------------------------------------------------------------------------- #
# Robots-declared sitemaps.
# --------------------------------------------------------------------------- #


def test_declared_sitemaps_are_discovered_from_robots_txt():
    session = _Session()
    session.route(
        "https://example.com/robots.txt",
        text="User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap-articles.xml\n",
        content_type="text/plain",
    )
    fetcher = _fetcher(session)
    assert declared_sitemap_urls(fetcher, "example.com") == [
        "https://example.com/sitemap-articles.xml"
    ]


def test_no_declared_sitemaps_falls_back_to_conventional_candidates():
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    fetcher = _fetcher(session)
    assert declared_sitemap_urls(fetcher, "example.com") == []
    assert default_sitemap_candidates("example.com") == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap_index.xml",
    ]


def test_declared_sitemaps_returns_empty_never_a_guess_when_robots_disallows():
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=403, text="")
    fetcher = _fetcher(session)
    assert declared_sitemap_urls(fetcher, "example.com") == []


# --------------------------------------------------------------------------- #
# discover_sitemap_urls: the full orchestrator.
# --------------------------------------------------------------------------- #


def test_discovers_urls_via_a_declared_index_and_its_child_sitemap():
    session = _Session()
    session.route(
        "https://example.com/robots.txt",
        text="Sitemap: https://example.com/sitemap-index.xml\n",
        content_type="text/plain",
    )
    session.route("https://example.com/sitemap-index.xml", text=_INDEX_XML)
    session.route("https://example.com/sitemap-articles.xml", text=_URLSET_XML)
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com")
    assert report.urls == ["https://example.com/a", "https://example.com/b"]
    assert report.root_sitemap_url == "https://example.com/sitemap-index.xml"
    assert report.child_sitemaps_fetched == 2
    assert report.stopped_reason == "completed"
    assert report.errors == []


def test_falls_back_to_conventional_sitemap_xml_when_nothing_is_declared():
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=_URLSET_XML)
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com")
    assert report.root_sitemap_url == "https://example.com/sitemap.xml"
    assert report.urls == ["https://example.com/a", "https://example.com/b"]


# --------------------------------------------------------------------------- #
# NEGATIVE-SPACE (mandatory): an off-host child sitemap is reported, NEVER
# fetched. A malformed reachable sitemap degrades to an honest error, never a
# crash of the whole discovery run.
# --------------------------------------------------------------------------- #


def test_an_off_host_child_sitemap_is_reported_but_never_fetched():
    off_host_index = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-articles.xml</loc></sitemap>
  <sitemap><loc>https://evil.example/sitemap.xml</loc></sitemap>
</sitemapindex>"""
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=off_host_index)
    session.route(
        "https://example.com/sitemap-articles.xml", text=_URLSET_XML
    )
    # If the off-host sitemap were ever fetched, this route would answer it --
    # its presence lets the test PROVE non-fetch, not just assume it.
    session.route("https://evil.example/sitemap.xml", text=_URLSET_XML.replace("example.com", "evil.example"))
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com")
    assert report.skipped_off_host == ["https://evil.example/sitemap.xml"]
    assert "https://evil.example/sitemap.xml" not in session.fetched
    assert all(u.startswith("https://example.com/") for u in report.urls)


def test_a_malformed_reachable_sitemap_is_recorded_as_an_error_not_a_crash():
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text="not xml at all")
    # Nothing declared -> BOTH conventional candidates are tried (sitemap.xml,
    # then sitemap_index.xml, which 404s here) -- both degrade to a recorded
    # error, never a crash of the whole discovery run.
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com")
    assert report.urls == []
    assert report.root_sitemap_url is None
    assert len(report.errors) == 2
    assert "malformed sitemap XML" in report.errors[0]


# --------------------------------------------------------------------------- #
# Bounds: max_sitemaps / max_urls.
# --------------------------------------------------------------------------- #


def test_max_sitemaps_bounds_a_deeply_nested_index():
    huge_index = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
""" + "".join(
        f"  <sitemap><loc>https://example.com/child-{i}.xml</loc></sitemap>\n"
        for i in range(20)
    ) + "</sitemapindex>"
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=huge_index)
    for i in range(20):
        session.route(f"https://example.com/child-{i}.xml", text=_URLSET_XML)
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com", max_sitemaps=3)
    assert report.stopped_reason == "max_sitemaps"
    assert report.child_sitemaps_fetched <= 3


def test_max_urls_bounds_a_huge_urlset():
    big_urlset = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
""" + "".join(
        f"  <url><loc>https://example.com/page-{i}</loc></url>\n" for i in range(200)
    ) + "</urlset>"
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=big_urlset)
    fetcher = _fetcher(session)

    report = discover_sitemap_urls(fetcher, "example.com", max_urls=10)
    assert len(report.urls) == 10
    assert report.stopped_reason == "max_urls"


# --------------------------------------------------------------------------- #
# Size bound: EthicalFetcher's own max_bytes applies to a sitemap fetch exactly
# like any other -- discover_sitemap_urls degrades to an honest error rather
# than crashing on an oversized body.
# --------------------------------------------------------------------------- #


def test_an_oversized_sitemap_is_refused_by_the_fetchers_size_bound():
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text="x" * 5000)
    fetcher = _fetcher(session, max_bytes=100)  # far smaller than the body above

    report = discover_sitemap_urls(fetcher, "example.com")
    assert report.urls == []
    assert "sitemap.xml: response exceeds 100 bytes" in report.errors[0]


# --------------------------------------------------------------------------- #
# update_source_sitemap_url: consumer (c) -- populate/refresh SourceMetadata
# (a one-to-one side table, NOT a Source column -- src/monitoring/preflight.py's
# get-or-create pattern reused, per the module docstring).
# --------------------------------------------------------------------------- #


def test_update_source_sitemap_url_populates_and_refreshes(db, source):
    from src.database.models import SourceMetadata
    from src.ingest.sitemap import SitemapDiscoveryReport

    report = SitemapDiscoveryReport(
        source_host="example.com", root_sitemap_url="https://example.com/sitemap.xml"
    )
    assert update_source_sitemap_url(db, source, report) is True
    meta = db.query(SourceMetadata).filter_by(source_id=source.id).first()
    assert meta is not None and meta.sitemap_url == "https://example.com/sitemap.xml"

    # Unchanged on a second identical report -- no needless write.
    assert update_source_sitemap_url(db, source, report) is False

    # A moved sitemap DOES refresh (populate AND refresh, per the ruling).
    moved = SitemapDiscoveryReport(
        source_host="example.com", root_sitemap_url="https://example.com/new-sitemap.xml"
    )
    assert update_source_sitemap_url(db, source, moved) is True
    db.flush()
    db.refresh(meta)
    assert meta.sitemap_url == "https://example.com/new-sitemap.xml"


def test_update_source_sitemap_url_never_writes_when_nothing_was_confirmed(db, source):
    from src.database.models import SourceMetadata
    from src.ingest.sitemap import SitemapDiscoveryReport

    report = SitemapDiscoveryReport(source_host="example.com")  # no root found
    assert update_source_sitemap_url(db, source, report) is False
    assert db.query(SourceMetadata).filter_by(source_id=source.id).first() is None


# --------------------------------------------------------------------------- #
# The trial channel (consumer b): a FEEDLESS candidate now produces real
# extraction-validity evidence, exactly like an RSS-having one.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    s.add(Source(name="Example", domain="example.com", language="en", rss_url=None, enabled=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


def test_sitemap_trial_ingest_produces_evidence_for_a_feedless_candidate(db, source):
    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=_URLSET_XML)
    session.route(
        "https://example.com/a",
        text=_article_html("Article A", "real news content here"),
        content_type="text/html",
    )
    session.route(
        "https://example.com/b",
        text=_article_html("Article B", "more real news content"),
        content_type="text/html",
    )
    fetcher = _fetcher(session)

    result = sitemap_trial_ingest(db, source, fetcher, max_items=5)
    assert result["channel"] == "sitemap"
    assert result["discovered"] == 2
    assert result["attempted"] == 2
    assert result["tally"]["stored"] == 2

    from src.database.models import Article, SourceMetadata

    assert db.query(Article).filter_by(source_id=source.id).count() == 2
    # Consumer (c): the confirmed working sitemap is persisted onto SourceMetadata.
    meta = db.query(SourceMetadata).filter_by(source_id=source.id).first()
    assert meta is not None and meta.sitemap_url == "https://example.com/sitemap.xml"


def test_trial_fetch_dispatches_feedless_candidates_to_the_sitemap_channel(db, source):
    """End-to-end through src.catalog.qualification.trial_fetch itself (not the
    helper directly) -- the C5/C7 unblock: a feedless candidate now produces
    evidence via qualification's own entry point."""
    from src.catalog.qualification import trial_fetch

    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    session.route("https://example.com/sitemap.xml", text=_URLSET_XML)
    session.route(
        "https://example.com/a",
        text=_article_html("Article A", "real news content here"),
        content_type="text/html",
    )
    session.route(
        "https://example.com/b",
        text=_article_html("Article B", "more real news content"),
        content_type="text/html",
    )
    fetcher = _fetcher(session)

    result = trial_fetch(db, source, fetcher)
    assert result["channel"] == "sitemap"
    from src.database.models import Article

    assert db.query(Article).filter_by(source_id=source.id).count() == 2


def test_a_feedless_candidate_with_no_sitemap_either_still_produces_no_evidence_honestly(
    db, source
):
    """The narrowed (not closed) residual scope limit: neither rss_url nor a
    discoverable sitemap -> honestly zero evidence, never a crash, never a
    fabricated pass."""
    from src.catalog.qualification import trial_fetch

    session = _Session()
    session.route("https://example.com/robots.txt", status_code=404, text="")
    # No sitemap.xml route -> falls through to a 404 -> FetchFailed -> recorded.
    fetcher = _fetcher(session)

    result = trial_fetch(db, source, fetcher)
    assert result["discovered"] == 0
    assert result["attempted"] == 0
