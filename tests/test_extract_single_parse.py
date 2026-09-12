"""The double parse, retired -- and the two things that made it worth a differential.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``extract_article`` called ``trafilatura.extract`` and then ``trafilatura.extract_metadata``
on the same HTML string, and each of those calls ``load_html``: every article was parsed
twice. ``bare_extraction(with_metadata=True)`` does the metadata pass and the body pass off
ONE tree, metadata first, before the body extraction prunes it.

The change was deferred twice as "a correctness risk for ~1 ms" and it earns its tests in
two places a diff does not show:

  * ``Extractor`` defaults ``date_params`` to ``set_date_params(extensive_search=True)``,
    and ``extract_metadata`` prefers a supplied ``date_config`` over its own ``extensive``
    argument -- so a switch that omitted ``date_extraction_params`` would silently restore
    the unbounded date hunt P3 removed, with nothing in the diff to see it in;
  * ``bare_extraction`` folds metadata and body into one call, so a metadata fault that
    used to cost the metadata now costs the ARTICLE. The contract says ``None`` means
    "no article here", never "the byline parser threw".

Equivalence itself is proven by differential rather than by these tests: 12,600 cases
(7 page shapes x 5 head shapes x 10 body shapes x 6 languages x 3 URL forms x both date
modes) comparing every field of the shipped function against the previous two-call
implementation -- ZERO differences. The harness discriminates: dropping
``date_extraction_params`` produces 894 differences, dropping ``with_metadata`` 7,380,
and flipping ``include_tables`` 720.
"""

from __future__ import annotations

import pytest
import trafilatura
import trafilatura.core
import trafilatura.metadata

from src.ingest.extract import extract_article

_BODY = (
    "<p>"
    + (
        "The committee published its assessment of the measure and the rapporteur set "
        "out the timetable for the next stage of the process. "
    )
    * 8
    + "</p>"
) * 3


def _page(head: str = "", body_extra: str = "") -> str:
    return (
        f"<html lang='en'><head><title>The committee assessment</title>{head}</head>"
        f"<body><article><h1>The committee assessment</h1>{body_extra}{_BODY}</article>"
        f"</body></html>"
    )


_DATED = _page("<meta property='article:published_time' content='2026-03-04T09:15:00Z'>")


@pytest.fixture()
def parses(monkeypatch):
    """Count REAL HTML parses, not calls.

    ``load_html`` is the one place trafilatura turns a string into a tree, and both
    ``core`` and ``metadata`` hold the same function object -- so patching the name in
    each module sees every parse either path makes. If upstream renames it this fixture
    fails loudly, which is the correct direction: the whole reason one call is safe is a
    fact about how that call parses, and that fact would need re-checking.
    """
    from lxml.html import HtmlElement

    seen: list[int] = []
    real = trafilatura.core.load_html

    def counting(htmlobject, *a, **kw):
        # ``load_html`` is CALLED more than once per article even now: ``bare_extraction``
        # parses the string, then hands the TREE to ``extract_metadata``, which calls
        # ``load_html`` again and gets it straight back. Counting calls would therefore
        # report two parses for one, and a test asserting 1 would be asserting something
        # false about working code. Count the calls that actually build a tree.
        if not isinstance(htmlobject, HtmlElement):
            seen.append(1)
        return real(htmlobject, *a, **kw)

    monkeypatch.setattr(trafilatura.core, "load_html", counting)
    monkeypatch.setattr(trafilatura.metadata, "load_html", counting)
    return seen


@pytest.fixture()
def calls(monkeypatch):
    """Which public entry points were used, so the fallback can be told from the normal path."""
    log: list[str] = []
    for name in ("bare_extraction", "extract", "extract_metadata"):
        real = getattr(trafilatura, name)

        def spy(*a, _n=name, _r=real, **kw):
            log.append(_n)
            return _r(*a, **kw)

        monkeypatch.setattr(trafilatura, name, spy)
    return log


# --------------------------------------------------------------------------- #
#  The change itself.
# --------------------------------------------------------------------------- #


def test_an_article_is_parsed_once(parses, calls):
    doc = extract_article(_DATED, url="https://example.org/a")
    assert doc is not None and doc.title and doc.published_at is not None
    assert len(parses) == 1, f"the page was parsed {len(parses)} times"
    assert calls == ["bare_extraction"], calls


def test_a_legitimate_no_article_does_not_pay_a_second_parse(parses, calls, monkeypatch):
    """The fallback must fire on a FAULT, never on a verdict.

    ``bare_extraction`` returns None for every rejection it makes -- no tree, body too
    short, wrong language, duplicate. Re-extracting on those would parse every non-article
    page in a crawl twice, which is the cost this change removes, paid back on the most
    common page there is.
    """
    monkeypatch.setattr(trafilatura, "bare_extraction", lambda *a, **kw: None)
    assert extract_article(_DATED, url="https://example.org/a") is None
    assert "extract" not in calls, f"the fallback ran on a legitimate None: {calls}"
    assert len(parses) == 0


def test_a_short_body_is_still_rejected(parses):
    short = (
        "<html lang='en'><head><title>A title</title></head><body><article>"
        "<h1>A headline</h1><p>Too short to be an article.</p></article></body></html>"
    )
    assert extract_article(short, url="https://example.org/a") is None


def test_empty_html_never_reaches_the_parser(parses, calls):
    for empty in ("", "   ", "\n\t"):
        assert extract_article(empty, url="https://example.org/a") is None
    assert parses == [] and calls == []


# --------------------------------------------------------------------------- #
#  THE REGRESSION THE DIFF CANNOT SHOW: the date bound must survive the switch.
# --------------------------------------------------------------------------- #


def test_the_date_bound_survives_the_single_parse(monkeypatch):
    """``Extractor`` defaults ``date_params`` to the EXTENSIVE search, and a supplied
    ``date_config`` beats the ``extensive`` argument -- so omitting
    ``date_extraction_params`` would restore the unbounded hunt P3 removed and no
    signature would change. Pinned on the case that made P3 an honesty item: a page whose
    only date-like text is a copyright footer, where the unbounded search answers 2019 and
    the bound answers None.
    """
    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "0")
    html = _page("", "<footer>Copyright 2019 The Institute. All rights reserved.</footer>")
    doc = extract_article(html, url="https://example.org/a")
    assert doc is not None
    assert doc.published_at is None, (
        "the unbounded date search is back: it invented a publication date from a "
        "copyright footer, which is what P3 removed"
    )

    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "1")
    restored = extract_article(html, url="https://example.org/a")
    assert restored is not None and restored.published_at is not None, (
        "...and the flag must still restore it, or the test above would pass on a "
        "tree where the date search had simply stopped working"
    )
    assert restored.published_at.year == 2019


def test_the_flag_is_read_once_per_article(monkeypatch):
    import src.ingest.extract as EX

    calls = [0]
    real = EX.extensive_date_search_enabled

    def counting():
        calls[0] += 1
        return real()

    monkeypatch.setattr(EX, "extensive_date_search_enabled", counting)
    assert extract_article(_DATED, url="https://example.org/a") is not None
    assert calls[0] == 1, f"read {calls[0]} times for one article"


# --------------------------------------------------------------------------- #
#  THE REFUSAL: a metadata fault must not cost the article.
# --------------------------------------------------------------------------- #


def test_a_fault_falls_back_and_keeps_the_body(calls, monkeypatch):
    """Folding the two calls into one put the BODY behind the metadata pass.
    ``bare_extraction`` catches only TypeError/ValueError, so anything else escaping it
    would have returned None for a page that plainly has an article."""
    def _boom(*_a, **_kw):
        raise AttributeError("a byline parser threw")

    monkeypatch.setattr(trafilatura, "bare_extraction", _boom)
    doc = extract_article(_DATED, url="https://example.org/a")
    assert doc is not None, "a metadata fault cost the whole article"
    assert len(doc.text) > 200
    # The raising stub REPLACED the spy, so `bare_extraction` cannot appear in the log.
    # What the log proves is the thing under test: the two-call rescue path ran.
    assert calls == ["extract", "extract_metadata"], calls


def test_the_fallback_survives_a_metadata_fault_of_its_own(monkeypatch):
    """The rescue path's own rescue: the body is returned with the metadata absent,
    which is the behaviour that existed before the parse was shared."""
    def _boom_bare(*_a, **_kw):
        raise AttributeError("a byline parser threw")

    def _boom_meta(*_a, **_kw):
        raise AttributeError("and again on the second attempt")

    monkeypatch.setattr(trafilatura, "bare_extraction", _boom_bare)
    monkeypatch.setattr(trafilatura, "extract_metadata", _boom_meta)
    doc = extract_article(_DATED, url="https://example.org/a")
    assert doc is not None and len(doc.text) > 200
    assert doc.title is None and doc.published_at is None and doc.author is None


def test_the_fallback_still_honours_the_date_bound(monkeypatch):
    """A rescue path that quietly used different settings would be a second, divergent
    extractor -- the shape this project calls two surfaces disagreeing about one fact."""
    def _boom(*_a, **_kw):
        raise AttributeError("a byline parser threw")

    monkeypatch.setattr(trafilatura, "bare_extraction", _boom)
    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "0")
    html = _page("", "<footer>Copyright 2019 The Institute. All rights reserved.</footer>")
    doc = extract_article(html, url="https://example.org/a")
    assert doc is not None and doc.published_at is None


def test_a_dict_return_lands_on_the_fallback_rather_than_an_attribute_error(monkeypatch):
    """``bare_extraction`` is typed ``Document | dict | None`` because of a deprecated
    ``as_dict`` parameter this call never passes, so today the dict arm is unreachable.
    It is narrowed rather than ``cast`` away because the two differ exactly when it
    matters: a cast asserts the union out of existence and would turn an upstream change
    into an ``AttributeError`` on a live collect pass, where the narrowing lands on the
    path that still works.

    This test is what keeps that from being an unfalsifiable guard -- the failure mode
    this project removed once already, when two guards survived every mutation.
    """
    monkeypatch.setattr(
        trafilatura, "bare_extraction", lambda *a, **kw: {"text": "a dict, somehow"}
    )
    doc = extract_article(_DATED, url="https://example.org/a")
    assert doc is not None, "a dict return cost the article"
    assert len(doc.text) > 200
    assert doc.published_at is not None, "the fallback lost the metadata too"


# --------------------------------------------------------------------------- #
#  Output equivalence, spot-checked here and proven by the differential.
# --------------------------------------------------------------------------- #


def test_every_field_still_comes_back():
    html = _page(
        "<meta property='article:published_time' content='2026-03-04T09:15:00Z'>"
        "<meta name='author' content='Jane Reporter'>"
        "<link rel='canonical' href='https://canonical.example/a'>"
    )
    doc = extract_article(html, url="https://example.org/a")
    assert doc is not None
    assert doc.title == "The committee assessment"
    assert doc.author == "Jane Reporter"
    assert doc.canonical_url == "https://canonical.example/a"
    assert doc.published_at is not None and doc.published_at.year == 2026
    assert "rapporteur" in doc.text
