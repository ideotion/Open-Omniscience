"""The boilerplate STRIP stage, and the two ways it must refuse to over-reach.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer field report 2026-08-07: the stored body of *Data Protection Act 2018
(consolidated)* opened with the legislation.gov.uk search form -- ``Title:``, ``Year:``,
``All UK Legislation (excluding originating from the EU)``, ``UK Private and Personal
Acts`` -- and every bogus extraction traced to it (``Personal Acts`` as a PERSON,
``Ireland (ie)`` inside a UK Act from ``Acts of the Northern Ireland Assembly``).

The specimen below is the real page's SHAPE, reconstructed from the strings the report
quotes: the skip link and language switch outside any landmark, a search form whose
type filter is a ``<select>``, real Act prose, a footer. Verified against the shipped
extractor before the fix -- every quoted string leaked, in the reported order.

A false positive here deletes part of a legal text, so every should-remove assertion
below has a should-KEEP twin.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bs4", reason="bs4 is the parser this stage strips through")

from bs4 import BeautifulSoup  # noqa: E402

from src.law.track import page_text  # noqa: E402
from src.services.boilerplate import (  # noqa: E402
    BOILERPLATE_STRIP_VERSION,
    strip_boilerplate,
    strip_legacy,
)

# --------------------------------------------------------------------------- #
#  The specimen
# --------------------------------------------------------------------------- #

_CHROME = """
<div id="header">
  <a href="#content" class="skip">Skip to main content</a>
  <a href="/cy">Cymraeg</a>
  <nav id="primaryNav"><ul><li><a href="/browse">Browse Legislation</a></li></ul></nav>
  <form id="searchLegislation" action="/search">
    <h2>Search Legislation</h2>
    <label for="title">Title:</label><input id="title" name="title">
    <label for="year">Year:</label><input id="year" name="year">
    <label for="type">Type:</label>
    <select id="type" name="type">
      <option value="all">All UK Legislation (excluding originating from the EU)</option>
      <option value="ukppa">UK Private and Personal Acts</option>
      <option value="nia">Acts of the Northern Ireland Assembly</option>
    </select>
    <button type="submit">Search</button>
  </form>
</div>
"""

_ACT = """
<div id="content">
  <h1>Data Protection Act 2018</h1>
  <p>An Act to make provision for the regulation of the processing of information
  relating to individuals; and for connected purposes.</p>
  <h2>PART 1</h2>
  <h3>Preliminary</h3>
  <p>This Act makes provision about the processing of personal data. Most processing of
  personal data is subject to the GDPR.</p>
</div>
"""

_FOOTER = '<footer><ul><li><a href="/cookies">Cookies</a></li></ul></footer>'

SPECIMEN = f"<html><head><title>DPA 2018</title></head><body>{_CHROME}{_ACT}{_FOOTER}</body></html>"

#: The strings the field report quoted, each of which produced a downstream fabrication.
REPORTED_CHROME = (
    "Search Legislation",
    "Title:",
    "Year:",
    "All UK Legislation (excluding originating from the EU)",
    "UK Private and Personal Acts",
    "Acts of the Northern Ireland Assembly",
)

#: The Act's own words. Losing any of these is the failure this stage must not have.
ACT_PROSE = (
    "Data Protection Act 2018",
    "An Act to make provision",
    "PART 1",
    "Preliminary",
    "subject to the GDPR",
)


# --------------------------------------------------------------------------- #
#  Should remove
# --------------------------------------------------------------------------- #


def test_the_reported_chrome_is_gone_and_the_act_survives():
    out = page_text(SPECIMEN)
    for s in REPORTED_CHROME:
        assert s not in out, f"the field report's own specimen string survived: {s!r}"
    for s in ACT_PROSE:
        assert s in out, f"the strip removed the Act's own text: {s!r}"


def test_the_old_extractor_really_did_leak_all_of_it():
    """The negative control. Without it, the test above could pass because the
    specimen never contained the chrome in the first place."""
    before = page_text(SPECIMEN, legacy=True)
    for s in REPORTED_CHROME:
        assert s in before, f"specimen does not reproduce the defect for {s!r}"


def test_the_select_options_are_the_ones_that_fabricated_entities():
    """Named separately because these two are not just noise -- they are where
    ``Personal Acts`` became a PERSON and an Irish place appeared in a UK Act."""
    out = page_text(SPECIMEN)
    assert "Personal Acts" not in out
    assert "Northern Ireland" not in out


# --------------------------------------------------------------------------- #
#  Should NOT remove -- the twins
# --------------------------------------------------------------------------- #


def test_a_form_that_wraps_the_whole_page_is_kept():
    """ASP.NET WebForms wraps the entire body in one ``<form runat="server">``.
    Dropping ``<form>`` unconditionally would delete the document.

    Measured on these two shapes: the wrapper holds 100% of the page text, a real
    search box 15.8%.
    """
    wrapped = f'<html><body><form id="aspnetForm" runat="server">{_ACT}</form></body></html>'
    out = page_text(wrapped)
    for s in ACT_PROSE:
        assert s in out, f"a page-wrapping form must not take the document with it: {s!r}"


def test_a_wrapper_form_still_loses_its_controls():
    """Keeping the wrapper is not keeping its chrome: the controls are never prose,
    so they go either way."""
    wrapped = f'<html><body><form runat="server">{_CHROME}{_ACT}</form></body></html>'
    out = page_text(wrapped)
    assert "UK Private and Personal Acts" not in out
    assert "Title:" not in out
    for s in ACT_PROSE:
        assert s in out


def test_ordinary_document_structure_is_untouched():
    """Lists, tables, headings, block quotes and figure captions are how legislation
    is written. None of them declares itself chrome."""
    html = (
        "<html><body><article>"
        "<h1>Section 4</h1>"
        "<p>The following applies.</p>"
        "<ul><li>paragraph (a) of subsection (2)</li><li>Schedule 3</li></ul>"
        "<table><tr><td>Column 1</td><td>Column 2</td></tr></table>"
        "<blockquote>as the court held in that case</blockquote>"
        "<figure><figcaption>Table of amendments</figcaption></figure>"
        "</article></body></html>"
    )
    out = page_text(html)
    for s in ("Section 4", "paragraph (a) of subsection (2)", "Schedule 3",
              "Column 1", "as the court held", "Table of amendments"):
        assert s in out, f"ordinary document structure was removed: {s!r}"


def test_a_page_with_no_chrome_is_byte_identical_to_the_old_reading():
    """The blast radius. A source whose markup declares nothing must be unaffected --
    otherwise this change reaches every tracked document, not only the polluted ones.
    """
    html = f"<html><body>{_ACT}</body></html>"
    assert page_text(html) == page_text(html, legacy=True)


def test_the_strip_is_reversible():
    import os

    os.environ["OO_STRIP_BOILERPLATE"] = "0"
    try:
        assert page_text(SPECIMEN) == page_text(SPECIMEN, legacy=True)
    finally:
        del os.environ["OO_STRIP_BOILERPLATE"]


# --------------------------------------------------------------------------- #
#  The report
# --------------------------------------------------------------------------- #


def test_the_report_counts_what_went_and_states_what_it_cannot_reach():
    soup = BeautifulSoup(SPECIMEN, "html.parser")
    report = strip_boilerplate(soup)
    d = report.as_dict()

    assert d["version"] == BOILERPLATE_STRIP_VERSION
    assert d["chars_removed"] > 0 and d["chars_after"] < d["chars_before"]
    assert d["removed"]["nav"] == 1 and d["removed"]["footer"] == 1
    # The form went as ONE element, and its <select>/<label>/<button> are NOT counted
    # again on top -- they left inside it. Counting both would overstate what the
    # control rule contributes, which is the whole reason forms are handled first.
    assert d["removed"]["form"] == 1
    assert "select" not in d["removed"] and "label" not in d["removed"]
    # A count of elements removed, by reason -- no score/rating/grade anywhere.
    walk = repr(d).lower()
    for banned in ("score", "rating", "ranking"):
        assert banned not in walk, banned
    # ...and it says what it does NOT catch, rather than implying it caught everything.
    assert "not removed" in d["caveat"].lower()


def test_the_residue_is_declared_rather_than_quietly_left():
    """A skip link and a bare language switch carry no declaration of any kind, so
    this stage leaves them -- deliberately, since the alternative is a text heuristic
    that would also eat an Act's section headings.

    Pinned so the limit is a stated property, not something a reader has to discover.
    """
    out = page_text(SPECIMEN)
    assert "Skip to main content" in out and "Cymraeg" in out


def test_a_wrapper_form_is_reported_as_kept_not_silently_skipped():
    soup = BeautifulSoup(f'<html><body><form runat="server">{_ACT}</form></body></html>',
                         "html.parser")
    report = strip_boilerplate(soup)
    assert report.forms_kept_as_wrapper == 1
    assert "form" not in report.removed


# --------------------------------------------------------------------------- #
#  ARIA landmarks
# --------------------------------------------------------------------------- #


def test_authored_aria_landmarks_are_honoured():
    """Sites whose markup predates the semantic tags declare the same thing in ARIA."""
    html = (
        '<html><body><div role="banner">Site name Login</div>'
        '<div role="navigation">Home Browse Contact</div>'
        f"{_ACT}"
        '<div role="contentinfo">Open Government Licence</div></body></html>'
    )
    out = page_text(html)
    assert "Site name Login" not in out and "Home Browse Contact" not in out
    assert "Open Government Licence" not in out
    for s in ACT_PROSE:
        assert s in out


def test_aria_hidden_is_deliberately_not_a_signal():
    """It marks decorative icons inside real content as often as it marks chrome, so
    acting on it would be a judgement call -- which this module does not make."""
    html = f'<html><body><div aria-hidden="true">{_ACT}</div></body></html>'
    out = page_text(html)
    for s in ACT_PROSE:
        assert s in out


# --------------------------------------------------------------------------- #
#  The legacy reading, which the tracker uses to tell the two apart
# --------------------------------------------------------------------------- #


def test_the_legacy_reading_is_exactly_the_old_element_set():
    soup = BeautifulSoup(SPECIMEN, "html.parser")
    strip_legacy(soup)
    text = soup.get_text("\n")
    assert "Browse Legislation" not in text, "nav was in the old set"
    assert "Cookies" not in text, "footer was in the old set"
    assert "UK Private and Personal Acts" in text, "select was NOT in the old set"
