"""Boilerplate STRIP -- remove page chrome that is chrome BY DECLARATION.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (maintainer field report 2026-08-07, the law attachment). The stored
body of *Data Protection Act 2018 (consolidated)* opened with the site's own header:
``Skip to main content . Cymraeg . Search Legislation . Title: . Year: . All UK
Legislation (excluding originating from the EU) . UK Private and Personal Acts . ...``
-- the search form's ``<select>`` dropdown, ingested as prose. Every bogus extraction
downstream traced to it: ``Personal Acts`` and ``Data Protection`` as PEOPLE, ``PART``
as an ORGANIZATION, and ``Ireland (ie)`` inside a UK Act, from
``Acts of the Northern Ireland Assembly``.

THE ARCHITECTURAL GAP the report named: the ingest gates are BINARY. ``non_article``
and the prose gate answer "is this page an article?", and that page is ~80% genuine Act
text, so it is correctly KEPT -- and the chrome rides along. There was a REJECT stage
and no STRIP stage.

WHAT THIS IS NOT. It is not a density heuristic and it does not guess. Every element it
removes is one whose own markup DECLARES it to be chrome: a ``<select>`` is a form
control, a ``<nav>`` is navigation, ``role="banner"`` is an authored ARIA landmark. A
false positive here is data loss from a legal text, so the rule is: remove what the
document says is not prose, and leave everything else -- including anything that would
need a judgement call.

Text-shaped signals (function-word density, sentence punctuation) deliberately live
NEXT DOOR in :mod:`src.services.prose_gate`, where they answer a different question
(is the WHOLE body chrome?) with their own guards. Applying them per-block here was
considered and rejected: a nav line is 2-5 words, far below that module's ``_MIN_TOKENS``
floor, so the measure would be unmeasurable exactly where it was needed -- and a
short-unpunctuated-line rule would eat an Act's real section headings ("PART 1",
"Preliminary"). What escapes THIS module is recorded honestly in the report it returns,
not silently swept up by a weaker rule.

THE ONE CONDITIONAL RULE, and why it is measured rather than assumed. ``<form>`` is
almost always a search box, and dropping it also removes its heading ("Search
Legislation") -- but classic ASP.NET WebForms wraps the ENTIRE page body in one
``<form runat="server">``, and dropping that would delete the whole document. Measured
on both shapes: the wrapper holds 100.0% of the page's text, a real search box 15.8%.
So a form is removed only when its text is a small share of the document; above the bar
the element stays and only its CONTROLS go, which are never prose either way. The
failure mode is therefore bounded: misjudging a form can leave chrome, never remove an
Act.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Bumped whenever the element sets or the form rule below change, so a consumer that
#: caches extracted text can tell "the page changed" from "our reading of it changed".
#: The law tracker keys its one-time re-read on exactly this (see ``src.law.track``).
BOILERPLATE_STRIP_VERSION = "strip-1"

#: Chrome by SEMANTIC DECLARATION -- the element's own tag says it is not document
#: prose. ``script``/``style``/``noscript``/``svg`` are not text at all; the rest are
#: HTML's own words for navigation, page furniture and asides.
_STRUCTURAL = (
    "script", "style", "noscript", "svg",
    "nav", "header", "footer", "aside", "menu", "dialog", "template",
)

#: Form CONTROLS. A ``<select>``'s options, a ``<label>``, a submit ``<button>`` are
#: interface, never the document's own words -- this is the set that produced the
#: field report's fabricated people and the Irish place inside a UK Act. Removed
#: unconditionally, including inside a form the rule below decides to keep.
_FORM_CONTROLS = (
    "select", "option", "optgroup", "datalist",
    "label", "button", "input", "textarea",
)

#: Embedded objects. No document prose, and their fallback text is interface
#: ("Your browser does not support...").
_EMBEDS = ("iframe", "object", "embed", "canvas", "audio", "video")

#: ARIA landmarks. An AUTHORED declaration of the same thing the semantic tags say,
#: used by sites whose markup predates (or ignores) ``<nav>``/``<header>``/``<footer>``.
#: Deliberately NOT including ``aria-hidden``: it is used on decorative icons inside
#: real content as often as on chrome, so it is a judgement call, which this module
#: does not make.
_LANDMARK_ROLES = (
    "navigation", "banner", "contentinfo", "search",
    "dialog", "alertdialog", "menu", "menubar", "toolbar", "tablist",
)

#: A ``<form>`` holding more than this share of the page's text is a page WRAPPER, not
#: a control, and is kept. Measured: ASP.NET WebForms wrapper 100.0%, search box 15.8%
#: -- the bar sits between them with room on both sides rather than hugging either.
_FORM_WRAPPER_SHARE = 0.40


def strip_enabled() -> bool:
    """Reversible, like every other gate in the ingest path (``OO_STRIP_BOILERPLATE=0``)."""
    return os.getenv("OO_STRIP_BOILERPLATE", "1") != "0"


@dataclass
class StripReport:
    """What was removed, so the effect is measurable rather than asserted.

    No score: these are counts of elements removed, by the reason that removed them.
    """

    removed: dict[str, int] = field(default_factory=dict)
    chars_before: int = 0
    chars_after: int = 0
    forms_kept_as_wrapper: int = 0
    version: str = BOILERPLATE_STRIP_VERSION

    @property
    def chars_removed(self) -> int:
        return max(0, self.chars_before - self.chars_after)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "removed": dict(sorted(self.removed.items())),
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "chars_removed": self.chars_removed,
            "forms_kept_as_wrapper": self.forms_kept_as_wrapper,
            "method": "elements whose own markup declares them non-prose (semantic tags, "
            "form controls, embeds, ARIA landmarks); a <form> holding more than "
            f"{_FORM_WRAPPER_SHARE:.0%} of the page's text is kept as a page wrapper",
            "caveat": "Structural only -- chrome that carries no such declaration (a bare "
            "skip link, a language switch outside any landmark) is NOT removed and is not "
            "counted here.",
        }


def strip_boilerplate(soup) -> StripReport:
    """Remove declared-chrome elements from ``soup`` IN PLACE; return what went.

    Takes a parsed BeautifulSoup rather than markup so the caller keeps one parse --
    ``page_text`` already has the tree in hand, and re-parsing a large consolidated Act
    to strip it would double the cost of every poll.
    """
    report = StripReport()
    report.chars_before = len(soup.get_text(" ", strip=True))

    def drop(tag, reason: str) -> None:
        tag.decompose()
        report.removed[reason] = report.removed.get(reason, 0) + 1

    for name in _STRUCTURAL:
        for tag in soup.find_all(name):
            drop(tag, name)

    # Forms BEFORE controls: a removed wrapper takes its controls with it, and counting
    # the controls of a form we are about to remove would overstate what the control
    # rule contributes.
    whole = max(report.chars_before, 1)
    for tag in soup.find_all("form"):
        if tag.decomposed:  # already gone with an enclosing element
            continue
        share = len(tag.get_text(" ", strip=True)) / whole
        if share >= _FORM_WRAPPER_SHARE:
            # A page wrapper (ASP.NET WebForms). Keep it -- its controls still go below.
            report.forms_kept_as_wrapper += 1
            continue
        drop(tag, "form")

    for name in _FORM_CONTROLS + _EMBEDS:
        for tag in soup.find_all(name):
            drop(tag, name)

    for role in _LANDMARK_ROLES:
        for tag in soup.find_all(attrs={"role": role}):
            drop(tag, f"role={role}")

    report.chars_after = len(soup.get_text(" ", strip=True))
    return report


#: The element set as it stood BEFORE this module -- kept so a consumer can reproduce
#: its own previous reading of a page and tell an extractor change from a real content
#: change, instead of recording one as the other. See ``src.law.track.page_text``.
LEGACY_ELEMENTS = ("script", "style", "nav", "footer", "header", "noscript", "svg")


def strip_legacy(soup) -> None:
    """The pre-``strip-1`` reading: decompose only ``LEGACY_ELEMENTS``. IN PLACE."""
    for tag in soup(list(LEGACY_ELEMENTS)):
        tag.decompose()
