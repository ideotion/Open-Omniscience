"""
Non-article ingest classifier (source-quality recall-gap fix).

The load-bearing tests are the NEGATIVE SPACE: a false positive DROPS A REAL ARTICLE, so the
"keeps a real article" cases matter more than the "catches a non-article" ones. Also pins the
recall-gap kinds the diagnostic surfaced (section pages, taxonomy listings, tool/wall pages), the
reversible env switch, and the store_fetched wiring (a distinct NON_ARTICLE outcome, never a
silent drop).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ingest.non_article import (
    classify_non_article,
    run_non_article_selftest,
    skip_non_articles_enabled,
)

ARTICLE_TEXT = "A full genuine article body with real sentences. " * 30


@pytest.mark.parametrize("url,signal", [
    ("https://deswater.com", "url_homepage"),
    ("https://deswater.com/", "url_homepage"),
    ("https://nano-magazine.com/news/tag/depression", "url_taxonomy"),
    ("https://site.com/category/politics", "url_taxonomy"),
    ("https://site.com/author/jane-doe", "url_taxonomy"),
    ("https://nano-magazine.com/events", "url_section"),
    ("https://www.irishexaminer.com/world/", "url_section"),
    ("https://www.bmv.com.mx/en/bmv/glossary", "url_utility"),
    ("https://lngjournal.com/index.php/downloads", "url_utility"),
    ("https://example.com/account/login", "url_utility"),
    ("https://example.com/blog/page/3", "url_pagination"),
])
def test_catches_non_article_urls_with_the_right_signal(url, signal):
    v = classify_non_article(url, text="short nav chrome")
    assert v is not None and v.signal == signal, f"{url} -> {v}"


def test_catches_consent_and_error_walls():
    assert classify_non_article("https://s.com/x", text="Please enable JavaScript to continue.",
                                word_count=6).signal == "boilerplate_wall"
    assert classify_non_article("https://s.com/x", text="404 Not Found. The page you requested…",
                                word_count=8).signal == "boilerplate_wall"


# --- THE NEGATIVE SPACE: real articles MUST be kept (a false positive = data loss) ---

@pytest.mark.parametrize("url", [
    "https://www.sydsvenskan.se/varlden/uppgift-ukrainare-atalas-for-nord-stream-sabotage/",
    "https://www.irishexaminer.com/world/arid-41234567.html",              # article UNDER /world/
    "https://site.com/category/politics/us-supreme-court-upholds-birthright-citizenship",  # under a category, long slug
    "https://blog.example.com/2026/07/13/a-genuine-long-form-investigation-into-x",
    "https://news.example.com/business/tech-giant-posts-record-quarter",
])
def test_keeps_real_articles(url):
    assert classify_non_article(url, text=ARTICLE_TEXT, word_count=240) is None, url


def test_keeps_a_long_article_that_merely_mentions_a_wall_phrase():
    # the word gate: a 900-word real article quoting "subscribe to continue" is NOT a wall
    text = "Long real article. " * 300 + " a banner said subscribe to continue."
    assert classify_non_article("https://s.com/news/real-slug", text=text, word_count=903) is None


@pytest.mark.parametrize("url", [
    "https://blog.example.com/business",              # bare section word — HIGH finding
    "https://site.com/economy",
    "https://about.example.com/about",
    "https://news.com/tag/gaza",                      # bare taxonomy value — HIGH finding
    "https://site.com/category/politics",
    "https://site.com/topic/climate-change",
    "https://site.com/2026/download",                 # utility word mid-path — HIGH finding
    "https://site.com/print",
])
def test_keeps_a_real_article_at_a_non_article_shaped_url_when_the_body_is_substantial(url):
    # THE skeptic HIGH fix: a real article that lives at a bare section / short taxonomy / utility
    # URL is KEPT, because its extracted body is substantial — the body, not the URL, decides.
    assert classify_non_article(url, text=ARTICLE_TEXT, word_count=240) is None, url


@pytest.mark.parametrize("url,signal", [
    ("https://blog.example.com/business", "url_section"),
    ("https://news.com/tag/gaza", "url_taxonomy"),
    ("https://site.com/category/politics", "url_taxonomy"),
])
def test_still_drops_the_same_urls_when_the_body_is_thin(url, signal):
    # the listing/section FRONT at the same URL — a thin extracted body — is still dropped
    v = classify_non_article(url, text="Headline one. Headline two. Headline three.", word_count=6)
    assert v is not None and v.signal == signal, f"{url} -> {v}"


def test_keeps_a_short_real_brief_that_quotes_a_wall_phrase():
    # skeptic MEDIUM: a 60-word real brief REPORTING on a 404 / paywall is kept (above the tiny
    # wall gate); only a chrome-tiny body dominated by the phrase is a wall.
    brief = ("The newspaper's site went down on Tuesday, greeting readers with a stark page not "
             "found error for several hours before engineers restored access to the archive. ") * 2
    assert classify_non_article("https://s.com/media/site-outage-tuesday", text=brief,
                                word_count=len(brief.split())) is None


def test_keeps_an_article_whose_slug_looks_like_a_section_word_but_has_more_path():
    # /world/... with a real slug is kept; only a BARE /world section landing is a non-article
    assert classify_non_article("https://s.com/technology/apple-unveils-new-chip", text=ARTICLE_TEXT,
                                word_count=200) is None


def test_env_switch_is_reversible(monkeypatch):
    monkeypatch.delenv("OO_SKIP_NON_ARTICLES", raising=False)
    assert skip_non_articles_enabled() is True  # default ON
    for off in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv("OO_SKIP_NON_ARTICLES", off)
        assert skip_non_articles_enabled() is False


def test_selftest_all_green():
    log = run_non_article_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


def test_no_score_field():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(run_non_article_selftest())


# --- wiring: store_fetched skips a non-article as a distinct, reversible outcome ---

def _fake_fetched(url):
    class F:
        content = "<html>nav</html>"
        final_url = url
        requested_url = url
    return F()


class _Doc:
    def __init__(self, text, title="t"):
        self.text = text
        self.title = title
        self.canonical_url = None
        self.published_at = None
        self.language = "en"
        self.author = None


def test_store_fetched_skips_a_non_article_and_the_switch_bypasses_it(monkeypatch):
    # store_fetched imports the crypto/ORM stack; skip cleanly in the bare sandbox (runs in CI).
    pipeline = pytest.importorskip("src.ingest.pipeline")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base, Source

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="X", domain="x.example")
    s.add(src)
    s.flush()

    # a taxonomy-listing URL -> non-article; extract returns a normal doc so only the URL decides.
    # The skip is an EARLY return (before dedup/store), so the outcome is a clean NON_ARTICLE.
    monkeypatch.setattr(pipeline, "extract_article", lambda content, url: _Doc("nav " * 20))
    monkeypatch.setenv("OO_SKIP_NON_ARTICLES", "1")
    out = pipeline.store_fetched(s, src, _fake_fetched("https://x.example/news/tag/politics"))
    assert out.result is pipeline.IngestResult.NON_ARTICLE
    assert out.result.value == "non_article"

    # with the switch OFF the classifier is not consulted at all (robust to store internals).
    import contextlib

    called: list[int] = []
    monkeypatch.setattr(pipeline, "classify_non_article", lambda *a, **k: called.append(1))
    monkeypatch.setenv("OO_SKIP_NON_ARTICLES", "0")
    # the minimal fake can't finish a real store; we only care the classifier wasn't consulted
    with contextlib.suppress(Exception):
        pipeline.store_fetched(s, src, _fake_fetched("https://x.example/news/tag/politics"))
    assert not called  # env off -> the non-article filter is bypassed
