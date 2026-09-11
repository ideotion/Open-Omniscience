"""P3: what htmldate's last-resort date hunt costs, and what it INVENTS.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``trafilatura.extract_metadata`` defaults to ``extensive=True``, which turns on a
last-resort walk of every free-text segment through ``dateparser``'s locale search. It
was recorded in the queue as a SPEED item (434 ms per article). Measuring it turned the
item around: the speed is real and language-dependent, but the reason to bound it is that
on a page with no real publication date the last resort does not answer "unknown" -- it
answers with a copyright year, a sidebar entry, or a sentence out of the body, stored as
this article's publication date.

So the suite is mostly a TRUTH TABLE. The first half proves the bound costs nothing where
a real date exists; the second proves it stops a fabrication; and the third NAMES the
dates the bound genuinely loses, because a trade recorded only in the winning direction
is not a trade a later reader can re-judge.
"""

from __future__ import annotations

import pytest

from src.ingest.extract import extensive_date_search_enabled, extract_article

_BODY = (
    "<p>"
    + (
        "The committee published its assessment of the measure and the rapporteur set "
        "out the timetable for the next stage of the process. "
    )
    * 8
    + "</p>"
) * 3

_TRUE = "2026-03-04"


def _page(inner_head: str = "", inner_body: str = "") -> str:
    return (
        f"<html lang='en'><head><title>The committee assessment</title>{inner_head}</head>"
        f"<body><article><h1>The committee assessment</h1>{inner_body}{_BODY}</article>"
        f"</body></html>"
    )


def _date(html: str, monkeypatch, *, extensive: bool) -> str | None:
    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "1" if extensive else "0")
    doc = extract_article(html, url="https://example.org/a")
    assert doc is not None, "the body must still extract; only the DATE is in question"
    return doc.published_at.strftime("%Y-%m-%d") if doc.published_at else None


# --------------------------------------------------------------------------- #
#  1. Where a real date exists, the bound costs nothing.
# --------------------------------------------------------------------------- #

STRUCTURED = {
    "meta article:published_time": (
        "<meta property='article:published_time' content='2026-03-04T09:15:00Z'>",
        "",
    ),
    "json-ld datePublished": (
        "<script type='application/ld+json'>"
        '{"@context":"https://schema.org","@type":"NewsArticle",'
        '"datePublished":"2026-03-04T09:15:00Z"}</script>',
        "",
    ),
    "time[datetime]": ("", "<time datetime='2026-03-04T09:15:00Z'>4 March 2026</time>"),
    "span.date": ("", "<span class='date'>4 March 2026</span>"),
}


@pytest.mark.parametrize("name", sorted(STRUCTURED))
def test_a_structured_date_is_found_identically_with_the_bound(name, monkeypatch):
    """The four placements a real news page actually uses. If the bound changed ANY of
    these it would be a recall regression rather than a bounded search, and the whole
    argument for it would collapse."""
    head, body = STRUCTURED[name]
    html = _page(head, body)
    assert _date(html, monkeypatch, extensive=True) == _TRUE
    assert _date(html, monkeypatch, extensive=False) == _TRUE


# --------------------------------------------------------------------------- #
#  2. THE REASON. Where no real date exists, the unbounded search invents one.
# --------------------------------------------------------------------------- #

FABRICATIONS = {
    "a copyright footer": (
        "<footer>Copyright 2019 The Institute. All rights reserved.</footer>",
        "2019",
    ),
    "a sidebar of related articles": (
        "<aside><h3>Related</h3><ul><li>An earlier report, 12 January 2011</li>"
        "<li>The first consultation, 8 August 2014</li></ul></aside>",
        "2011",
    ),
    "a date mentioned in the body prose": (
        "<p>Officials met on 11 September 2001 and returned to the question later.</p>",
        "2001",
    ),
}


@pytest.mark.parametrize("name", sorted(FABRICATIONS))
def test_the_unbounded_search_returns_a_wrong_date_where_the_bound_returns_none(
    name, monkeypatch
):
    """None of these pages HAS a publication date. The unbounded search answers anyway,
    and the answer is wrong in a way nothing downstream can detect -- it lands in the
    timemap, the agenda and every trend as fact. ``None`` is the true answer, and one the
    app already renders honestly.

    The assertion is on the YEAR rather than the exact day: which wrong date is picked is
    htmldate's heuristic and may move between versions. That it picks one, from text that
    is not a publication date, is the property under test.
    """
    body, wrong_year = FABRICATIONS[name]
    html = _page("", body)

    unbounded = _date(html, monkeypatch, extensive=True)
    assert unbounded is not None, (
        "this test is only meaningful while the unbounded search still fabricates; "
        "if upstream stopped, the bound's case rests on speed alone and this suite "
        "should be re-argued rather than deleted"
    )
    assert unbounded.startswith(wrong_year)
    assert unbounded != _TRUE

    assert _date(html, monkeypatch, extensive=False) is None


# --------------------------------------------------------------------------- #
#  3. The other side of the trade, named rather than glossed.
# --------------------------------------------------------------------------- #

LOST = {
    "a.date (outside htmldate's fast element list)": (
        "<a class='date' href='/archive/2026/03/04'>4 March 2026</a>"
    ),
    "td.date (outside htmldate's fast element list)": (
        "<table><tr><td class='date'>4 March 2026</td></tr></table>"
    ),
    "a date only in free text": "<p>Published 4 March 2026 by the secretariat.</p>",
}


@pytest.mark.parametrize("name", sorted(LOST))
def test_the_bound_loses_these_real_dates_and_that_is_the_price(name, monkeypatch):
    """These are CORRECT dates the bounded path misses -- the cost of the ruling, pinned
    so it stays visible. Two come from the element-scan narrowing rather than the
    free-text resort (htmldate's fast list covers div/h2/h3/h4/li/p/span/time/ul, so an
    anchor or a table cell falls outside it), which is why the bound is a flag and not a
    deletion: OO_EXTENSIVE_DATE_SEARCH=1 buys them back, with the fabrications above
    attached.
    """
    html = _page("", LOST[name])
    assert _date(html, monkeypatch, extensive=True) == _TRUE
    assert _date(html, monkeypatch, extensive=False) is None


def test_the_flag_defaults_off_and_only_1_turns_it_on(monkeypatch):
    monkeypatch.delenv("OO_EXTENSIVE_DATE_SEARCH", raising=False)
    assert extensive_date_search_enabled() is False
    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "1")
    assert extensive_date_search_enabled() is True
    for off in ("0", "", "true", "yes"):
        monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", off)
        assert extensive_date_search_enabled() is False, (
            "an explicit allowlist, not truthiness: a typo must fail to the bounded "
            "path, which is the one that cannot fabricate"
        )


def test_the_flag_is_read_once_per_article_not_per_candidate_date(monkeypatch):
    """The P2 shape, guarded here before it can recur: a settings read that drifts into a
    per-candidate loop. htmldate evaluates many date expressions per page, so a read
    inside that path would multiply by the page's element count."""
    import src.ingest.extract as EX

    calls = [0]
    real = EX.extensive_date_search_enabled

    def counting():
        calls[0] += 1
        return real()

    monkeypatch.setattr(EX, "extensive_date_search_enabled", counting)
    html = _page("", "<span class='date'>4 March 2026</span><p>Also 12 January 2011.</p>")
    assert extract_article(html, url="https://example.org/a") is not None
    assert calls[0] == 1, f"read {calls[0]} times for one article"
