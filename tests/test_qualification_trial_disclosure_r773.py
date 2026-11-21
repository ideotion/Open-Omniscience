"""A candidate's trial reaches the candidate, and the world-discovery disclosure says exactly what it reaches (R773 (3); row 249).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every source world discovery adds comes with a domain and no feed, so its trial could only try the sitemap, and a
site with no reachable sitemap was offered again pass after pass. The trial now reads the candidate's home page for the
feed links it publishes first. What holds the disclosure and the fetching together, as R761 did for topic discovery:

- a run of the REAL ``trial_fetch`` over a recording fetcher reaches only the candidate's site, and there only its
  robots.txt (the fetcher's own read, named), its home page, the same-site feed links that page names (at most
  ``TRIAL_FEED_LINKS_MAX``), the same-site articles a feed lists, and otherwise its sitemap and the articles it lists;
- a feed link or a feed entry on another site is counted and never asked for, and no feed address is guessed;
- the consent table's discovery lane carries ``TRIAL_FEED_LINKS_MAX`` and the conventional sitemap paths exactly, the
  hover sentence renders them, ``docs/SECURITY.md`` names them, and the sentence is keyed and translated in all twelve
  locales.

Mutation-checked by hand: a third feed link allowed by the constant reddens the table check; dropping ``entry_site``
from the trial reddens the off-site entry run; a guessed ``/feed`` probe added to ``find_trial_feed`` reddens the
"nothing guessed" run; the hover sentence dropped from ``_laneHostTitle`` reddens the hover check.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog import qualification as q
from src.database.models import Base, Source
from src.ingest import FetchFailed, FetchResult, pipeline, sitemap
from src.ingest import feed_find as ff
from tests.js_source_helper import array_literal, function_body

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"

HOVER = (
    "then, to judge each candidate it found, on that candidate's own site only: its robots.txt, its home page, at "
    "most {n} feed links that page names, a few articles those feeds list, and otherwise its sitemap (the one its "
    "robots.txt names, or {paths}) and a few articles it lists. No link to another site is followed, but an article "
    "or feed address that redirects can lead to another site, whose robots.txt is read first."
)


def _result(url: str, content: str, ctype: str) -> FetchResult:
    return FetchResult(requested_url=url, final_url=url, status_code=200, content=content, content_type=ctype,
                       fetched_at=datetime.now(UTC))


def _rss(*links: str) -> str:
    items = "".join(f"<item><title>t</title><link>{u}</link></item>" for u in links)
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>x</title>{items}</channel></rss>"


class _Recorder:
    """A fetcher that logs every address asked for. ``robots`` logs the robots.txt read ``declared_sitemaps`` makes."""

    def __init__(self, pages: dict[str, tuple[str, str]]):
        self.pages = pages
        self.log: list[str] = []
        self.headers: dict[str, dict] = {}

    def declared_sitemaps(self, url: str) -> list[str]:
        self.log.append(url.rstrip("/") + "/robots.txt")
        return []

    def fetch(self, url: str, *, require_html: bool = True, extra_headers=None, **_kw) -> FetchResult:
        self.log.append(url)
        self.headers[url] = dict(extra_headers or {})
        if url not in self.pages:
            raise FetchFailed(f"404 for {url}")
        content, ctype = self.pages[url]
        return _result(url, content, ctype)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def articles(monkeypatch):
    """The article step is the fetch of the article's own address; the extraction behind it is not what is pinned."""

    def fake_ingest_url(session, source, url, *, fetcher, batch=None):
        try:
            fetcher.fetch(url)
        except FetchFailed as exc:
            return pipeline.IngestOutcome(url=url, result=pipeline.IngestResult.FETCH_FAILED, detail=str(exc))
        return pipeline.IngestOutcome(url=url, result=pipeline.IngestResult.STORED, article_id=1)

    monkeypatch.setattr(pipeline, "ingest_url", fake_ingest_url)
    monkeypatch.setattr(sitemap, "ingest_url", fake_ingest_url)


def _candidate(db, domain="cand.example") -> Source:
    s = Source(name=domain, domain=domain, status="unqualified", enabled=False)
    db.add(s)
    db.commit()
    return s


HOME = "https://cand.example/"
ARTICLE = ("<html><body><p>story</p></body></html>", "text/html")
PAGE = (
    "<html><head>"
    '<link rel="alternate" type="application/rss+xml" href="/feed-one.xml">'
    '<link rel="alternate" type="application/atom+xml" href="https://news.cand.example/two.atom">'
    '<link rel="alternate" type="application/rss+xml" href="/feed-three.xml">'
    '<link rel="alternate" type="application/rss+xml" href="/feed-four.xml">'
    '<link rel="alternate" type="application/rss+xml" href="https://feeds.elsewhere.test/x.rss">'
    "</head><body>home</body></html>",
    "text/html",
)


def test_a_found_feed_is_tried_and_only_its_same_site_entries_are_fetched(db, articles):
    src = _candidate(db)
    rec = _Recorder({
        HOME: PAGE,
        "https://cand.example/feed-one.xml": (_rss("https://cand.example/a1", "https://elsewhere.test/b",
                                                   "https://www.cand.example/a2"), "application/rss+xml"),
        "https://cand.example/a1": ARTICLE,
        "https://www.cand.example/a2": ARTICLE,
    })
    out = q.trial_fetch(db, src, rec, max_items=5)
    assert out["channel"] == "feed" and out["feed_found_on_page"] is True
    assert out["off_site_entries"] == 1 and out["entries"] == 2
    assert src.rss_url == "https://cand.example/feed-one.xml", "a feed that yields entries is kept"
    assert rec.log == [HOME, "https://cand.example/feed-one.xml", "https://cand.example/a1",
                       "https://www.cand.example/a2"]


def test_the_trial_reaches_only_what_the_disclosure_names(db, articles):
    """Neither found feed yields anything: both are put back and the sitemap runs. Every address asked for is on the
    candidate's site, and is the robots.txt, the home page, a same-site feed link (at most TRIAL_FEED_LINKS_MAX), a
    conventional sitemap address, or an article the sitemap lists."""
    src = _candidate(db)
    rec = _Recorder({
        HOME: PAGE,
        "https://cand.example/feed-one.xml": (_rss(), "application/rss+xml"),
        "https://cand.example/feed-three.xml": (_rss("https://elsewhere.test/only-off-site",
                                                     "https://news.cand.example/a-subdomain-is-another-site"),
                                                "application/rss+xml"),
        "https://cand.example/sitemap.xml": (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://cand.example/story-1</loc></url>"
            "<url><loc>https://elsewhere.test/not-ours</loc></url></urlset>",
            "application/xml",
        ),
    })
    out = q.trial_fetch(db, src, rec, max_items=5)
    assert out["channel"] == "sitemap"
    assert src.rss_url is None, "a feed that yielded nothing is put back"
    hosts = {urlsplit(u).hostname for u in rec.log}
    assert hosts <= {"cand.example"}, sorted(hosts)
    feeds = [u for u in rec.log if u.endswith((".xml", ".atom")) and "sitemap" not in u]
    assert feeds == ["https://cand.example/feed-one.xml", "https://cand.example/feed-three.xml"]
    assert len(feeds) <= ff.TRIAL_FEED_LINKS_MAX
    allowed_paths = {"/robots.txt", "/", "/feed-one.xml", "/feed-three.xml", "/story-1", *sitemap._CONVENTIONAL_PATHS}
    assert {urlsplit(u).path for u in rec.log} <= allowed_paths
    assert "https://cand.example/feed-four.xml" not in rec.log, "the third same-site link is past TRIAL_FEED_LINKS_MAX"


def test_a_page_with_no_feed_link_guesses_none(db, articles):
    src = _candidate(db)
    rec = _Recorder({HOME: ("<html><head></head><body>no feed</body></html>", "text/html")})
    q.trial_fetch(db, src, rec, max_items=5)
    feedish = [u for u in rec.log if urlsplit(u).path not in {"/", "/robots.txt", *sitemap._CONVENTIONAL_PATHS}]
    assert feedish == [], f"a feed address was guessed: {feedish}"


def test_a_feed_another_row_of_the_same_site_owns_is_left_to_it(db, articles):
    from src.database.feed_key import feed_key

    owner = Source(name="owner", domain="cand.example", rss_url="https://cand.example/feed-one.xml", enabled=True,
                   status="qualified")
    owner.feed_key = feed_key(owner.rss_url)
    db.add(owner)
    db.commit()
    src = Source(name="cand", domain="cand.example", feed_key=feed_key(None), status="unqualified", enabled=False)
    db.add(src)
    db.commit()
    rec = _Recorder({HOME: PAGE})
    q.trial_fetch(db, src, rec, max_items=5)
    assert "https://cand.example/feed-one.xml" not in rec.log
    assert src.rss_url is None


def test_feed_links_are_read_in_order_and_held_to_the_site():
    html = PAGE[0]
    links = ff.feed_links_in_page(html, HOME)
    assert links == ["https://cand.example/feed-one.xml", "https://news.cand.example/two.atom",
                     "https://cand.example/feed-three.xml", "https://cand.example/feed-four.xml",
                     "https://feeds.elsewhere.test/x.rss"]
    assert ff.same_site("https://www.cand.example/x", "cand.example")
    assert ff.same_site("https://cand.example:8443/x", "www.cand.example")
    # the crawler's rule (security read, row 249): a subdomain is ANOTHER site, as for sitemaps (R627) ...
    assert not ff.same_site("https://news.cand.example/x", "www.cand.example")
    assert not ff.same_site("https://news.cand.example/x", "cand.example")
    # ... a shared host's other tenants are other sites ...
    assert not ff.same_site("https://other.wordpress.com/feed", "cand.wordpress.com")
    # ... and an address carrying userinfo is refused whichever side of the @ names the site
    assert not ff.same_site("https://cand.example@evil.test/x", "cand.example")
    assert not ff.same_site("https://user@cand.example/x", "cand.example")
    assert not ff.same_site("https://cand.example.evil.test/x", "cand.example")
    assert not ff.same_site("https://notcand.example/x", "cand.example")
    assert not ff.same_site("http://[::1/x", "cand.example")
    rep = ff.find_trial_feed(_Recorder({HOME: PAGE}), "cand.example")
    assert rep.feeds == ["https://cand.example/feed-one.xml", "https://cand.example/feed-three.xml"]
    assert rep.off_site == 2 and rep.error is None


def test_a_refused_home_page_is_reported_and_yields_no_feed():
    rep = ff.find_trial_feed(_Recorder({}), "cand.example")
    assert rep.feeds == [] and rep.error and "404" in rep.error


def _lane() -> dict:
    lanes = json.loads(array_literal((STATIC / "net-hosts.js").read_text(encoding="utf-8"), "OO_NET_LANES"))
    (lane,) = [x for x in lanes if x["id"] == "discovery"]
    return lane


def test_the_consent_table_carries_the_trial_bounds_the_code_uses():
    lane = _lane()
    assert lane["candidateTrial"] is True
    assert lane["trialFeedLinks"] == ff.TRIAL_FEED_LINKS_MAX
    assert lane["sitemapPaths"] == list(sitemap._CONVENTIONAL_PATHS)
    assert lane["hosts"] == ["query.wikidata.org", "www.wikidata.org"], "the candidates are a class, not hosts"


def test_the_hover_says_it_before_the_click():
    core = (STATIC / "app-core.js").read_text(encoding="utf-8")
    title = function_body(core, "_laneHostTitle")
    assert "lane.candidateTrial" in title and "lane.trialFeedLinks" in title and "lane.sitemapPaths" in title
    assert 'tf("' + HOVER + '"' in title


def test_the_security_row_names_what_a_trial_fetches():
    text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    (row,) = [ln for ln in text.splitlines() if ln.startswith("| **Source discovery** |")]
    for needle in ("`/robots.txt`", "`https://<domain>/`", f"at most {ff.TRIAL_FEED_LINKS_MAX} feed links",
                   "`TRIAL_FEED_LINKS_MAX`", "no feed address is guessed", "`world_discovery_backlog_bound`",
                   "`world_discovery_country_backlog_bound`", *(f"`{p}`" for p in sitemap._CONVENTIONAL_PATHS)):
        assert needle in row, needle


@pytest.mark.parametrize("path", sorted((STATIC / "locales").glob("*.json")), ids=lambda p: p.stem)
def test_the_disclosure_sentence_is_keyed_and_translated(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert HOVER in d
    assert d[HOVER].count("{n}") == 1 and d[HOVER].count("{paths}") == 1
    assert "robots.txt" in d[HOVER]
    if path.stem != "en":
        assert d[HOVER] != HOVER, f"{path.stem} leaves the trial disclosure in English"


def test_a_later_trial_of_a_kept_feed_still_fetches_only_same_site_entries(db, articles):
    """Security read 1 (blocking): a feed one trial found and kept is the source's ``rss_url``, so the NEXT trial took
    the plain feed path and fetched every entry. Every trial judges this site, the second as much as the first."""
    src = _candidate(db)
    feed = "https://cand.example/feed-one.xml"
    rec = _Recorder({HOME: PAGE, feed: (_rss("https://cand.example/a1"), "application/rss+xml"),
                     "https://cand.example/a1": ARTICLE, "https://cand.example/a3": ARTICLE})
    q.trial_fetch(db, src, rec, max_items=5)
    assert src.rss_url == feed
    rec.pages[feed] = (_rss("https://cand.example/a3", "https://elsewhere.test/later", "https://news.cand.example/s"),
                       "application/rss+xml")
    rec.log.clear()
    out = q.trial_fetch(db, src, rec, max_items=5)
    assert rec.log == [feed, "https://cand.example/a3"], rec.log
    assert out["off_site_entries"] == 2


def test_a_feed_with_entries_but_nothing_to_judge_is_not_kept(db, articles):
    """Security read 2 (N4): entries that all fail to fetch are no evidence the feed serves the site; it is put back."""
    src = _candidate(db)
    rec = _Recorder({HOME: PAGE,
                     "https://cand.example/feed-one.xml": (_rss("https://cand.example/gone"), "application/rss+xml")})
    out = q.trial_fetch(db, src, rec, max_items=5)
    assert out.get("channel") == "sitemap"
    assert src.rss_url is None


def test_a_feed_not_kept_leaves_no_address_or_fetch_state_once_committed(db, articles):
    """Security read 2 (S1, S2): ``ingest_source`` commits its own bookkeeping, so a feed put back only in memory came
    back on the next commit; and the conditional-GET state of one feed tried was sent with the next. Read back after rolling
    back whatever was left uncommitted: nothing of a feed not kept is left, and no feed tried is asked with old validators."""
    from src.database.models import FeedFetchState

    src = _candidate(db)
    db.add(FeedFetchState(source_id=src.id, etag='"stale"', last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
                          consecutive_unchanged=4))
    db.commit()
    feed_one, feed_three = "https://cand.example/feed-one.xml", "https://cand.example/feed-three.xml"
    rec = _Recorder({HOME: PAGE, feed_one: (_rss(), "application/rss+xml"),
                     feed_three: (_rss(), "application/rss+xml")})
    q.trial_fetch(db, src, rec, max_items=5)
    assert rec.headers[feed_one] == {} and rec.headers[feed_three] == {}, rec.headers
    db.rollback()  # anything not committed is gone (an in-memory database shares one connection, so a second
    db.expire_all()  # session would see the uncommitted writes too)
    assert db.get(Source, src.id).rss_url is None
    assert db.get(FeedFetchState, src.id) is None


def test_a_feed_not_kept_is_put_back_even_when_the_trial_raises(db, articles, monkeypatch):
    src = _candidate(db)

    def boom(*_a, **_kw):
        raise RuntimeError("extraction exploded")

    monkeypatch.setattr(pipeline, "ingest_url", boom)
    rec = _Recorder({HOME: PAGE, "https://cand.example/a1": ARTICLE,
                     "https://cand.example/feed-one.xml": (_rss("https://cand.example/a1"), "application/rss+xml")})
    with pytest.raises(RuntimeError):
        q.trial_fetch(db, src, rec, max_items=5)
    db.rollback()
    db.expire_all()
    assert db.get(Source, src.id).rss_url is None


def test_a_page_full_of_feed_links_is_read_in_bounded_time():
    """Security read 1: the dedupe was quadratic, so a 10 MB home page of links took about 100 s. Reading stops at
    ``PAGE_FEED_LINKS_READ_MAX`` distinct links, and a repeated link is one set lookup."""
    import time

    many = "".join(f'<link rel="alternate" type="application/rss+xml" href="/f{i}.xml">' for i in range(20000))
    same = '<link rel="alternate" type="application/rss+xml" href="/same.xml">' * 20000
    start = time.perf_counter()
    links = ff.feed_links_in_page(f"<html><head>{many}</head></html>", HOME)
    repeated = ff.feed_links_in_page(f"<html><head>{same}</head></html>", HOME)
    assert time.perf_counter() - start < 5
    assert len(links) == ff.PAGE_FEED_LINKS_READ_MAX
    assert links[0] == "https://cand.example/f0.xml"
    assert repeated == ["https://cand.example/same.xml"]
