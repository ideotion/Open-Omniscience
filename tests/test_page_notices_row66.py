"""The ingest door's row-66 rules (field report 2026-11-14 sections 5.2 and 7): error dumps, JavaScript and
Flash notices, leading menu runs, code titles, long homepages and feed pages, and the app banner's button.

Each rule is tested on its specimen shape AND on the negative space: a real sentence that merely mentions
PHP, JavaScript or Flash, a short byline block, a headline about JavaScript, an article whose address
carries a query string. A false positive changes or hides a real article.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ingest.furniture import strip_furniture
from src.ingest.non_article import classify_non_article
from src.ingest.page_notices import (
    NAV_RUN_MIN_LINES,
    is_code_title,
    notice_kind,
    strip_leading_nav,
    strip_notices,
)

PROSE = (
    "Kommunfullmäktige beslutade på måndagskvällen att skolan ska renoveras under nästa år. "
    "Beslutet fattades efter en lång debatt där flera ledamöter lyfte frågan om kostnaderna. "
    "Renoveringen beräknas ta ett år och eleverna flyttas under tiden till tillfälliga lokaler."
)
DRUPAL = (
    "Deprecated function: Return type of Drupal\\Core\\Controller\\ControllerResolver::getArguments() "
    "should either be compatible with ... in include() (line 123 of "
    "/var/www/html/core/lib/Drupal/Core/Controller/ControllerResolver.php)."
)
PHP_PLAIN = "Warning: Undefined array key \"title\" in /var/www/html/wp-content/themes/x/single.php on line 42"
FRAME = "#0 /var/www/html/core/lib/Drupal/Core/DrupalKernel.php(705): Drupal\\Core\\Kernel->handle()"
FLASH = ("To play the media you will need to either update your browser to a recent version or update your "
         "Flash plugin.")


@pytest.mark.parametrize("line,kind", [
    (DRUPAL, "php_error"),
    (PHP_PLAIN, "php_error"),
    (FRAME, "php_error"),
    ("LessWrong requires JavaScript to run.", "js_required"),
    ("You need to enable JavaScript to run this app.", "js_required"),
    ("Update Required", "flash_required"),
    (FLASH, "flash_required"),
])
def test_each_specimen_line_is_named(line, kind):
    assert notice_kind(line) == kind


@pytest.mark.parametrize("line", [
    "The company rewrote its site in PHP last year, the developers said in a warning to users.",
    "Warning: the bridge will be closed on Monday for repairs.",
    "Deprecated: the old ticket machines will be removed by March.",
    "A short line saying JavaScript is fun",
    " ".join(["Regulators said browsers that require JavaScript"] + ["and"] * 30) + " was the topic.",
    "Adobe announced in 2017 that it would stop supporting the Flash player by the end of 2020, "
    "ending more than two decades in which the plugin shaped how video and games reached the web, "
    "and leaving many archives to update or lose their old interactive works.",
    "The camera's flash went off.",
    # the Opus read's specimens: news sentences that carry a notice's words
    "Firefox 140 lets users browse without JavaScript on any site.",
    "The exploit works even when JavaScript is disabled, researchers said.",
    "Adobe ended support for Flash Player in 2020, and users no longer need to install it.",
    "The agency's site requires JavaScript to run, critics said.",
])
def test_a_sentence_that_mentions_them_is_kept(line):
    assert notice_kind(line) is None


def test_stripping_notices_keeps_the_article_around_them_byte_for_byte():
    text = f"{DRUPAL}\n{DRUPAL}\n{PROSE}\n\nSecond paragraph stays."
    out, removed = strip_notices(text)
    assert out == f"{PROSE}\n\nSecond paragraph stays."
    assert removed == {"php_error": 2}
    assert strip_notices(PROSE) == (PROSE, {})
    # a notice at the bottom goes too
    assert strip_notices(f"{PROSE}\nLessWrong requires JavaScript to run.") == (PROSE, {"js_required": 1})


def test_a_notice_quoted_inside_an_article_stays():
    # a PHP tutorial shows the warning it explains: mid-body, so it is the article's text
    text = f"{PROSE}\n{PHP_PLAIN}\n{PROSE}"
    assert strip_notices(text) == (text, {})


def test_a_leading_menu_run_goes_and_a_byline_block_stays():
    menu = "\n".join(["Hem", "Nyheter", "Sport", "Kultur", "Ekonomi", "Debatt", "Väder", "Logga in"])
    out, n = strip_leading_nav(f"{menu}\n{PROSE}", keep_min_chars=200)
    assert out == PROSE and n == NAV_RUN_MIN_LINES
    byline = "Av Anna Svensson\nFoto Lehtikuva\nUppdaterad"
    assert strip_leading_nav(f"{byline}\n{PROSE}", keep_min_chars=200) == (f"{byline}\n{PROSE}", 0)
    # a date line is data and breaks the run, so a short run before it is never taken
    dated = "\n".join(["Hem", "Nyheter", "Sport", "16.11.2026", "Kultur", "Ekonomi", "Debatt", "Väder", "Logga in"])
    assert strip_leading_nav(f"{dated}\n{PROSE}", keep_min_chars=200)[1] == 0
    # never makes a stub: when too little would remain, nothing goes
    assert strip_leading_nav(f"{menu}\nKort text.", keep_min_chars=200)[1] == 0
    # a body that is only short lines is a menu page, judged elsewhere, not trimmed here
    assert strip_leading_nav(menu, keep_min_chars=0)[1] == 0


@pytest.mark.parametrize("lead", [
    # CJK sentences end in their own full stop or carry a clause comma
    "\n".join(["今天上午，市政府召开新闻发布会。"] * 9),
    # a CJK line without its stop is still longer than a menu entry
    "\n".join(["市政府召开新闻发布会宣布新政策"] * 9),
    # a poem at the top of a culture article: its lines run longer than a menu entry
    "\n".join(["the river keeps its counsel", "under the winter bridge", "and the gulls wheel south",
                "past the empty harbour", "where the boats lie still", "and nobody comes home",
                "before the lamps are lit", "on the long quay road", "and the night comes down"]),
])
def test_a_leading_run_of_real_lines_is_not_a_menu(lead):
    assert strip_leading_nav(f"{lead}\n{PROSE}", keep_min_chars=200)[1] == 0


@pytest.mark.parametrize("title,code", [
    ("function(){var a=document.createElement('script');a.src='x.js';}", True),
    ("window.dataLayer = window.dataLayer || []; function gtag(){dataLayer.push(arguments);}", True),
    ("var _paq = window._paq = window._paq || [];", True),
    ("Why JavaScript frameworks keep changing (and what to do about it)", False),
    ("Function and form: a review of (re)designs; part 2", False),
    ("Return of the king: the series finale (2003)", False),
    ("JavaScript's => arrow functions (and why () {} matter)", False),
    (None, False),
])
def test_a_code_title_is_told_from_a_headline(title, code):
    assert is_code_title(title) is code


def test_the_banner_button_goes_only_right_after_its_banner():
    banner = ("För att din app ska fortsätta fungera som det är tänkt behöver du uppdatera till nyaste versionen. "
              "Klicka på knappen för att uppdatera!")
    assert strip_furniture(f"{PROSE}\n{banner}\nUppdatera nu!") == (f"{PROSE}\n", 2)
    assert strip_furniture(f"{PROSE}\n\n{banner}\n\nUppdatera nu!")[1] == 2
    # on its own, or after ordinary text, the line is not furniture
    assert strip_furniture(f"Uppdatera nu!\n{PROSE}") == (f"Uppdatera nu!\n{PROSE}", 0)
    assert strip_furniture(f"{PROSE}\nUppdatera nu!")[1] == 0


LONG = PROSE + " " + PROSE + " " + PROSE + " " + PROSE


@pytest.mark.parametrize("url,signal", [
    ("https://thediplomat.com/", "url_homepage"),
    ("https://vietnamnews.vn", "url_homepage"),
    ("https://www.rnz.co.nz/rss", "url_utility"),
    ("https://example.com/feed/", "url_utility"),
])
def test_the_door_refuses_a_long_homepage_or_feed_page(url, signal):
    verdict = classify_non_article(url, text=LONG, door=True)
    assert verdict is not None and verdict.signal == signal
    # stored articles are judged as before: the retroactive scans never pass door
    assert classify_non_article(url, text=LONG) is None
    assert classify_non_article(url, word_count=400) is None


@pytest.mark.parametrize("url", [
    "https://24haubenin.info/?Le-gouvernement-annonce-un-nouveau-plan",  # an article addressed by its query (row 65)
    "https://site.com/?p=12345",
    "https://site.com/news/rss-feeds-explained",
    "https://site.com/2026/11/16/feed-the-world-campaign",
    "https://site.com/rss/2026/an-article-under-a-feed-folder",
    "https://x.com/#/story/12",  # a single-page site addresses its story in the fragment
])
def test_the_door_rule_spares_an_addressed_article(url):
    assert classify_non_article(url, text=LONG, door=True) is None


# ----------------------------------------------------------------------------------------------- the door itself
def _fetched(url: str, html: str):
    return SimpleNamespace(
        content=html, final_url=url, requested_url=url, server_ip=None, server_ip_reason=None,
        fetched_at=None,
    )


def _store(monkeypatch, url: str, *, title: str | None, text: str):
    from src.ingest import pipeline
    from src.ingest.extract import ExtractedDoc

    doc = ExtractedDoc(title=title, text=text, published_at=None, language="sv", author=None, canonical_url=None)
    monkeypatch.setattr(pipeline, "extract_article", lambda html, url=None: doc)
    staged: list = []
    batch = SimpleNamespace(has_hash=lambda h: False, stage=lambda *a: staged.append(a))
    monkeypatch.setattr(pipeline, "_exists", lambda *a, **k: False)
    source = SimpleNamespace(id=1, domain="example.com", language="sv")
    out = pipeline.store_fetched(None, source, _fetched(url, "<html></html>"), batch=batch)
    return out, doc, staged


def test_a_page_that_was_only_an_error_dump_is_a_counted_non_article(monkeypatch):
    from src.ingest.pipeline import IngestResult

    out, _, staged = _store(monkeypatch, "https://polonia1.tv/wiadomosci/x", title="Polonia1",
                            text="\n".join([DRUPAL] * 6 + ["Polonia1"]))
    assert out.result is IngestResult.NON_ARTICLE and "php_error x6" in out.detail and not staged


def test_an_article_under_an_error_dump_is_kept_without_the_dump(monkeypatch):
    from src.ingest.pipeline import IngestResult

    out, doc, staged = _store(monkeypatch, "https://polonia1.tv/wiadomosci/x", title="Tytuł",
                              text=f"{DRUPAL}\n{DRUPAL}\n{LONG}")
    assert out.result is IngestResult.STAGED and doc.text == LONG and staged


def test_a_short_brief_that_carries_a_notice_line_is_kept_whole(monkeypatch):
    from src.ingest.pipeline import IngestResult

    brief = PROSE[:190]
    text = f"{brief}\nLessWrong requires JavaScript to run."
    out, doc, staged = _store(monkeypatch, "https://example.com/news/brief", title="Brief", text=text)
    assert out.result is IngestResult.STAGED and doc.text == text and staged


def test_a_code_title_is_stored_as_no_title(monkeypatch):
    from src.ingest.pipeline import IngestResult

    out, doc, _ = _store(monkeypatch, "https://www.ajol.info/index.php/x/article/view/1",
                         title="var _paq = window._paq = window._paq || [];", text=LONG)
    assert out.result is IngestResult.STAGED and doc.title is None


def test_the_door_refuses_a_long_homepage(monkeypatch):
    from src.ingest.pipeline import IngestResult

    out, _, staged = _store(monkeypatch, "https://thediplomat.com/", title="The Diplomat", text=LONG)
    assert out.result is IngestResult.NON_ARTICLE and not staged


def test_every_new_rule_is_off_with_the_non_article_switch_off(monkeypatch):
    from src.ingest.pipeline import IngestResult

    monkeypatch.setenv("OO_SKIP_NON_ARTICLES", "0")
    text = "\n".join([DRUPAL] * 6 + ["Polonia1"])
    out, doc, _ = _store(monkeypatch, "https://thediplomat.com/", title="var a = 1; f(); g();", text=text)
    assert out.result is IngestResult.STAGED and doc.text == text
