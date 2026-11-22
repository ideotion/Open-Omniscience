"""Bad-item signals from the 8-instance field test (2026-11-14, report 5.1 and 5.2; row 65, and the WordPress default post of row 66).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.analytics.source_quality import _pre_label
from src.ingest.non_article import classify_index_page, classify_non_article
from tests._app_engine import app_sqlite_engine


@pytest.mark.parametrize("text", [
    "Allerede abonnent? Logg inn for å lese videre.",
    "Vain tilaajille. Tilaa nyt ja lue koko juttu.",
    "Cet article est réservé aux abonnés.",
    "Dieser Artikel ist nur für Abonnenten verfügbar.",
])
def test_paywall_walls_in_other_languages_are_labelled(text):
    assert any(x.startswith("boilerplate_phrase:") for x in _pre_label(text, word_count=200, external_links=0))


def test_404_is_a_number_not_a_substring():
    for prose in ("The bridge carried 2404 cars a day.", "Flight AF404 landed.", "It was founded in 404 AD.",
                  "Hij is al abonnee sinds 1990.", "Hän on ollut jo tilaaja vuosia."):
        assert _pre_label(prose, word_count=200, external_links=0) == [], prose
    assert _pre_label("Error 404: page gone", word_count=200, external_links=0)


def test_unsegmented_languages_get_no_word_count_signals():
    # A complete Chinese article has a tiny "word count"; that is not a short page.
    assert _pre_label("一篇完整的新闻报道。", word_count=3, external_links=1, language="zh") == []
    assert _pre_label("短い", word_count=2, external_links=0, language="ja-JP") == []
    assert _pre_label("short", word_count=2, external_links=0, language="en") == ["very_short:2"]


@pytest.mark.parametrize("url", [
    "https://24haubenin.info/?Benin-le-gouvernement-annonce-un-plan",
    "https://24haubenin.info/?Le-conseil-des-ministres-du-mercredi%C3%A9t%C3%A9",
])
def test_a_bare_query_slug_is_an_article_address(url):
    assert classify_non_article(url) is None and classify_index_page(url) is None


@pytest.mark.parametrize("url", [
    "https://24haubenin.info/", "https://x.example/?page=2", "https://x.example/?s=gaza-war-news",
    "https://x.example/?a-b", "https://x.example/?utm=a-b-c&x=1", "https://x.example/?utm_source-x-y-z",
    "https://x.example/?fbclid-IwAR0abc-def-ghi", "https://x.example/?amp-page-view-mode",
])
def test_a_homepage_with_a_query_stays_a_homepage(url):
    assert classify_non_article(url) is not None


@pytest.mark.parametrize(("text", "phrase"), [
    ("Welcome to WordPress. This is your first post. Edit or delete it, then start writing!",
     "this is your first post. edit or delete it"),
])
def test_field_test_walls(text, phrase):
    v = classify_non_article("https://x.example/a/b-c-d", text=text, word_count=len(text.split()))
    assert v is not None and v.signal == "boilerplate_wall" and phrase in v.reason


@pytest.mark.parametrize("text", [
    "This is your first posting abroad, the minister told the new envoy.",
    "Coach: this is your first post-season win and the city is celebrating.",
    "This is your first post office visit since the reform, residents were told.",
])
def test_a_short_real_brief_that_starts_like_the_wordpress_post_is_kept(text):
    assert classify_non_article("https://x.example/a/b-c-d", text=text, word_count=len(text.split())) is None


@pytest.mark.parametrize("lang", ["zh", "zh-Hans", "ZH-tw", "zh_TW", " zh", "ja-JP", "ja_JP", "th"])
def test_unsegmented_languages_in_any_spelling_skip_word_signals(lang):
    from src.analytics.source_quality import _word_signals_apply

    assert _word_signals_apply(lang) is False


@pytest.mark.parametrize("lang", [None, "", "en", "en-GB", "zu"])
def test_other_and_unknown_languages_keep_word_signals(lang):
    from src.analytics.source_quality import _word_signals_apply

    assert _word_signals_apply(lang) is True


@pytest.mark.parametrize("url", [
    "https://x.example/news/?sort-by-date-desc",
    "https://x.example/?preview-theme-dark-mode",
    "https://x.example/?mc-cid-abc-def",
])
def test_view_and_tracking_queries_do_not_veto_the_homepage_or_section_rules(url):
    from src.ingest.non_article import _has_item_identifier

    assert _has_item_identifier(url) is False


def test_a_slug_under_a_section_path_is_an_article_address():
    from src.ingest.non_article import _has_item_identifier

    assert _has_item_identifier("https://x.example/news/?minister-resigns-after-budget-vote") is True


def test_link_density_criterion_skips_unsegmented_languages():
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.analytics.source_quality import link_dense_article_ids
    from src.database.models import Article, ArticleLink, Base, Source

    engine = app_sqlite_engine(":memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="s", domain="s.example")
        s.add(src)
        s.commit()
        ids = {}
        for lang in ("zh", "en"):
            url = f"https://s.example/{lang}"
            a = Article(url=url, canonical_url=url, source_id=src.id, content="x", hash=lang, word_count=3,
                        language=lang, title=lang)
            s.add(a)
            s.commit()
            ids[lang] = int(a.id)
            s.add(ArticleLink(article_id=a.id, url="https://other.example/", normalized_url="https://other.example/",
                              link_type="external"))
        s.commit()
        assert link_dense_article_ids(s) == {ids["en"]}
        assert link_dense_article_ids(s, source_ids={int(src.id)}) == {ids["en"]}
