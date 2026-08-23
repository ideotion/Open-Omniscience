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


# --------------------------------------------------------------------------- #
# Index pages ABOVE the body guard (source-quality export 2026-08-11)
# --------------------------------------------------------------------------- #


def test_index_page_classifier_sees_what_the_body_guard_hides():
    """The whole point: these URLs carry a SUBSTANTIAL body (they are pages of concatenated
    real teasers), so ``classify_non_article`` keeps them and every other detector is blind.
    Real specimens from the 2026-08-11 control set, with their measured word counts."""
    from src.ingest.non_article import classify_index_page, classify_non_article

    for url, wc in [
        ("https://lci.fr", 2287),
        ("https://www.dawn.com/business", 300),
        ("https://www.nzherald.co.nz/topic/united-states/", 766),
        ("https://www.levernews.com/tag/midterm-madness/", 106),
        ("https://vlast.kz/author/248/", 129),
        ("https://adamtooze.substack.com/sitemap/2026", 596),
        ("https://icilome.com/page/2/", 1667),
    ]:
        assert classify_non_article(url, text="x " * wc, word_count=wc) is None, (
            f"{url} is kept by the ingest gate — that is the gap being reported"
        )
        assert classify_index_page(url) is not None, url


def test_index_page_classifier_never_widens_the_non_article_set():
    """It reports the shapes ``classify_non_article`` ALREADY recognises and nothing else, so
    it cannot invent a new way to condemn an article. The real-article corpus below is the
    same negative space the ingest gate is held to."""
    from src.ingest.non_article import classify_index_page

    for url in [
        "https://www.sydsvenskan.se/varlden/uppgift-ukrainare-atalas-for-nord-stream-sabotage/",
        "https://www.irishexaminer.com/world/arid-41234567.html",
        "https://site.com/category/politics/us-supreme-court-upholds-birthright-citizenship",
        "https://eastmojo.com/sikkim/2026/07/23/sikkim-4-day-rescue-ends-in-samardung-tunnel/",
        "https://www.bleepingcomputer.com/news/artificial-intelligence/openai-relaxes-limits",
        "https://polarresearch.net/index.php/polar/article/view/5169",
    ]:
        assert classify_index_page(url) is None, url


@pytest.mark.parametrize("url,tier", [
    # TIER 1 — a real article is structurally impossible: nowhere to put a slug.
    ("https://lci.fr", 1),
    ("https://alaraby.co.uk", 1),
    ("https://icilome.com/page/2/", 1),
    ("https://news.com/tag/", 1),
    ("https://example.com/account/login", 1),
    ("https://calculatedriskblog.com/search", 1),
    ("https://adamtooze.substack.com/sitemap/2026", 1),
    # TIER 2 — a listing by convention, where an article COULD live.
    ("https://www.nzherald.co.nz/topic/united-states/", 2),
    ("https://www.levernews.com/tag/midterm-madness/", 2),
    ("https://vlast.kz/author/248/", 2),
    ("https://www.dawn.com/business", 2),
    ("https://site.com/print/some-real-story", 2),
    ("https://www.bleepingcomputer.com/download/qualys-browsercheck/", 2),
    ("https://www.bmv.com.mx/en/bmv/glossary", 2),
])
def test_index_page_tiers_split_by_structural_possibility(url, tier):
    """The tier is a review-effort split, not a confidence score. Tier 2 exists because a
    print view, a download page and a glossary entry front REAL body text even though the
    path is a utility word — putting them in Tier 1 would auto-act on real content."""
    from src.ingest.non_article import classify_index_page

    v = classify_index_page(url)
    assert v is not None, url
    assert v.tier == tier, f"{url} -> tier {v.tier}, expected {tier} ({v.reason})"


def test_the_ingest_drop_contract_is_untouched_by_the_index_page_addition():
    """The load-bearing guarantee of this slice: NOTHING about what ingest DROPS changed. A
    substantial body at a listing URL is still kept by ``classify_non_article`` — the new
    classifier is a separate, reporting-only reading that feeds a REVERSIBLE quarantine
    stamp. If a future change routes ``classify_index_page`` into the ingest drop path, this
    test is where that decision has to be made deliberately."""
    from src.ingest.non_article import classify_non_article

    for url in ("https://lci.fr", "https://www.dawn.com/business", "https://news.com/tag/x"):
        assert classify_non_article(url, text=ARTICLE_TEXT, word_count=240) is None, url
        # and a THIN body at the same URL is still dropped, exactly as before
        assert classify_non_article(url, text="Headline one. Headline two.", word_count=4)


def test_the_reported_index_page_rate_is_a_FLOOR_not_a_census():
    """``_SECTION_WORDS`` is a fixed vocabulary, so a section front named outside it is
    invisible to BOTH classifiers. ``hindustantimes.com/astrology`` (955 words of section
    blurb + listing, hand-read from the 2026-08-11 control) is the specimen: nothing here
    recognises it, and that is deliberate — widening the vocabulary to chase it would widen
    the set of shapes the project can condemn, which is the one thing this addition must not
    do. So any rate derived from these classifiers is a LOWER BOUND on the real listing
    population, and must be reported as one."""
    from src.ingest.non_article import classify_index_page, classify_non_article

    for url in ("https://www.hindustantimes.com/astrology",
                "https://example.com/horoscopes",
                "https://example.com/obituaries"):
        assert classify_non_article(url) is None, url
        assert classify_index_page(url) is None, url


# --------------------------------------------------------------------------- #
# A query-string item id vetoes the homepage / section-landing rules
# --------------------------------------------------------------------------- #
# Found by the 2026-08-23 criteria-calibration bundle (0.3 gate row 5): on a 5,010-article
# instance the ENTIRE drop path proposed four articles, all four Antiwar.com
# ``/news/?articleid=NNNN``, all four under the reason "section landing '/news'" — which is
# false of a URL that names one article. Their function-word densities were 0.28-0.37, i.e.
# prose. So the only quarantine this corpus's criteria proposed was 4/4 false positives.

@pytest.mark.parametrize("url", [
    "https://www.antiwar.com/news/?articleid=2504",   # the field specimens, verbatim
    "http://antiwar.com/news/?articleid=2637",
    "https://example.com/?p=12345",                   # WordPress default permalink
    "https://example.com/news/?story_id=443",
    "https://example.com/?nid=1234",
])
def test_a_query_string_item_id_is_not_a_section_landing_or_a_homepage(url):
    """The DIRECTION that matters: a false positive here quarantines a real article."""
    assert classify_non_article(url, text="A short real page body.", word_count=50) is None, url


@pytest.mark.parametrize("url,signal", [
    # The twin. Widening this veto until it swallows genuine listings would be the same
    # defect pointing the other way, so each of these must still fire.
    ("https://example.com/news/", "url_section"),        # a real section front
    ("https://example.com/", "url_homepage"),            # a real homepage
    ("https://example.com/news/?page=2", "url_section"), # pagination is not an item id
    ("https://example.com/news/?tag=gaza", "url_section"),
    ("https://example.com/news/?s=search+terms", "url_section"),
    ("https://example.com/news/?id=", "url_section"),    # blank value addresses nothing
    ("https://example.com/news/?id=latest", "url_section"),  # no digit -> not a record id
])
def test_the_veto_does_not_rescue_a_genuine_listing(url, signal):
    v = classify_non_article(url, text="Headline one. Headline two.", word_count=6)
    assert v is not None and v.signal == signal, url


def test_the_veto_is_scoped_to_the_two_rules_about_having_no_item_address():
    """Taxonomy and utility rules key on an explicit PATH segment, so an item id in the
    query must not rescue them — a `/tag/gaza` listing is a listing however it is decorated."""
    for url, signal in (("https://example.com/tag/gaza?id=9", "url_taxonomy"),
                        ("https://example.com/account/login?id=9", "url_utility")):
        v = classify_non_article(url, text="Headline one.", word_count=4)
        assert v is not None and v.signal == signal, url
