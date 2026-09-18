"""Q725's first-run wizard: two doors, one dialog, and every string keyed ×12.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q725 = a: "Edition choice (default: all twelve) + the storage budget (Q707) + the
plain statement of what the lane contacts", reachable from ``unlock.html`` AND
``#set-wikipedia``.

THE MOST IMPORTANT TEST IN THIS FILE IS THE TEMPLATE ONE, and it exists because of a
hole the gates cannot see. ``scripts/i18n_report.py`` excludes ``{`` from every one of
its character classes on purpose, so a ``tf()`` TEMPLATE literal registers neither as
a UI string nor as an unkeyed ``t()`` call — both gates report green while the
template renders English in eleven locales. That is one level past the defect this
slice already recorded (a toast string the painter-only extraction never saw); the
same shape, in a place no gate reaches. So the templates are extracted HERE, by name,
and checked against every locale file.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from tests.js_source_helper import function_source, read_static, strip_comments

_LOCALES = pathlib.Path("src/static/locales")
_INDEX = pathlib.Path("src/static/index.html")
_UNLOCK = pathlib.Path("src/static/unlock.html")

#: Every function that renders a string on this surface. NAMED, never derived by
#: scanning the file: the recorded defect is an extraction that read only some of the
#: renderers and reported the rest as fine.
_WIZARD_FUNCTIONS = (
    "_wizShare",
    "_wizRender",
    "_wizSelectAll",
    "_wizPaintHosts",
    "openWikiWizard",
    "saveWikiWizard",
    "loadWikiLaneSummary",
)


def _sources() -> str:
    return read_static("app-sources.js")


def _wizard_js() -> str:
    src = _sources()
    return "\n".join(function_source(src, name) for name in _WIZARD_FUNCTIONS)


def _locale(code: str) -> dict:
    return json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))


_ALL_LOCALES = ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id")


def _dialog() -> str:
    html = _INDEX.read_text(encoding="utf-8")
    start = html.index('<dialog id="wiki-wizard"')
    return html[start : html.index("</dialog>", start)]


# --------------------------------------------------------------------------- #
# It exists, and it is reachable BOTH ways the ruling asks for.
# --------------------------------------------------------------------------- #
def test_the_wizard_asks_Q725s_THREE_questions_and_no_others():
    dialog = _dialog()
    assert 'id="wiki-wizard-editions"' in dialog, "edition choice"
    assert 'id="wiki-wizard-budget"' in dialog, "the storage budget"
    assert 'id="wiki-wizard-hosts"' in dialog, "what the lane contacts"


def test_it_is_reachable_from_SETTINGS():
    html = _INDEX.read_text(encoding="utf-8")
    panel = html[html.index('id="set-wikipedia"') : html.index('id="set-agenda"')]
    assert 'id="wiki-wizard-open"' in panel, "the Settings door"


def test_it_is_reachable_from_the_FIRST_LAUNCH_flow():
    """unlock.html hands off rather than carrying a second copy: that page runs before
    the corpus is open, so it cannot read or write a lane setting at all."""
    unlock = _UNLOCK.read_text(encoding="utf-8")
    assert "/?wikiwizard=1" in unlock
    assert "waitReadyThenEnter(btn.id === \"btn-create\")" in unlock, (
        "only a FRESH corpus is sent to the wizard -- an operator who already "
        "answered must not be asked again on every launch"
    )
    boot = read_static("app-boot.js")
    assert 'get("wikiwizard")' in boot, "and the app opens it on that parameter"


def test_the_wizard_is_NOT_a_consent_surface():
    """Every call it makes is loopback. Gating a settings screen behind the network
    popup would teach an operator that choosing a setting costs a network decision."""
    js = _wizard_js()
    assert "ensureOnline" not in js, (
        "the wizard writes three settings over loopback; crossing online is the ONE "
        "popup's job and the lane starts there"
    )


def test_the_hosts_come_from_the_ONE_table_and_not_from_a_literal_in_the_markup():
    """Q1001: one source of truth. A second copy in the markup is a second thing to
    keep in step with docs/SECURITY.md -- and the copy nobody updates is the one an
    operator reads before deciding."""
    assert "OO_NET_LANES" in function_source(_sources(), "_wizPaintHosts")
    dialog = _dialog()
    for host in ("stream.wikimedia.org", "wikimedia.org", "wikipedia.org"):
        assert host not in dialog, f"{host} is hardcoded in the dialog markup"


def test_an_unreadable_host_list_says_so_rather_than_rendering_blank():
    body = function_source(_sources(), "_wizPaintHosts")
    assert "The host list could not be read." in body


# --------------------------------------------------------------------------- #
# The ruled defaults, and the refusals.
# --------------------------------------------------------------------------- #
def test_the_defaults_in_the_MARKUP_are_the_ruled_ones():
    dialog = _dialog()
    assert 'value="20"' in dialog, "Q707's published 20 GB"
    assert 'min="1"' in dialog and 'max="2000"' in dialog, "the wizard's own bounds"


def test_saving_with_NO_editions_is_refused_rather_than_silently_defaulted():
    body = function_source(_sources(), "saveWikiWizard")
    assert "_wizChosen.size" in body
    assert "Pick at least one edition" in body


def test_NOT_NOW_leaves_wizard_done_alone():
    """An operator who dismissed the screen has not been through it, and recording
    that they had would make the defaults look like a choice they made."""
    # COMMENTS STRIPPED FIRST. This file's own comment explains why "Not now" leaves
    # the flag alone, so a raw substring search finds the word in the explanation and
    # passes whatever the code does -- a guard satisfied by its own rationale.
    boot = strip_comments(read_static("app-boot.js"))
    start = boot.index('$("wiki-wizard-cancel")')
    cancel = boot[start : start + 600]
    assert "wiki_lane_wizard_done" not in cancel
    assert "wizard_done" not in cancel


def test_saving_records_that_the_operator_WENT_THROUGH_it():
    body = function_source(_sources(), "saveWikiWizard")
    assert "wiki_lane_wizard_done: true" in body, (
        "a different fact from 'the values differ from the defaults' -- the two would "
        "be indistinguishable if it were inferred"
    )


def test_the_share_line_is_an_ABSENCE_with_a_reason_when_it_cannot_be_computed():
    body = function_source(_sources(), "_wizShare")
    assert "Pick at least one edition and a budget to see the share." in body
    assert "toFixed" in body, "and a real division when it can"


def test_the_summary_never_reports_an_unmeasured_lane_as_ZERO_bytes():
    body = function_source(_sources(), "loadWikiLaneSummary")
    assert "not yet measured — this lane has not run" in body
    assert "b.measured" in body


# --------------------------------------------------------------------------- #
# The blind spot: tf() templates, invisible to BOTH i18n gates.
# --------------------------------------------------------------------------- #
def _template_literals() -> set[str]:
    """Every ``_wizTf`` template on this surface, by NAME rather than by scan."""
    js = _wizard_js()
    out: set[str] = set()
    for rx in (r'_wizTf\(\s*"((?:[^"\\]|\\.)+)"', r"_wizTf\(\s*'((?:[^'\\]|\\.)+)'"):
        out |= set(re.findall(rx, js))
    # Multi-line calls: the template may sit on its own line after the paren.
    out |= set(re.findall(r'_wizTf\(\s*\n\s*"((?:[^"\\]|\\.)+)"', js))
    return {s for s in out if len(s) > 2}


def test_the_extraction_actually_FINDS_the_templates():
    """A guard that extracts nothing passes every assertion below it. This is the
    positive control that makes the rest of this section mean something."""
    found = _template_literals()
    assert len(found) >= 4, f"expected the wizard's templates, found {found}"
    assert any("{n}" in s for s in found), found


@pytest.mark.parametrize("code", _ALL_LOCALES)
def test_every_template_has_a_key_in_every_locale(code):
    """The gates cannot see these: ``scripts/i18n_report.py`` excludes ``{`` from every
    character class, so a template registers neither as a UI string nor as an unkeyed
    t() call, and both gates report green while eleven locales render English."""
    locale = _locale(code)
    missing = sorted(s for s in _template_literals() if s not in locale)
    assert not missing, f"{code}.json is missing {missing}"


@pytest.mark.parametrize("code", _ALL_LOCALES)
def test_every_placeholder_survives_translation(code):
    """A dropped ``{n}`` is a sentence with a hole in it; a translated one never
    interpolates and renders the brace text to the operator."""
    locale = _locale(code)
    for template in _template_literals():
        value = locale.get(template)
        if value is None:
            continue  # the test above is the one that reports that
        wanted = set(re.findall(r"\{(\w+)\}", template))
        got = set(re.findall(r"\{(\w+)\}", value))
        assert wanted == got, f"{code}.json {template!r} -> {value!r}"


@pytest.mark.parametrize("code", _ALL_LOCALES)
def test_every_t9_string_on_this_surface_has_a_key_too(code):
    js = _wizard_js()
    literals = set(re.findall(r't9\(\s*"((?:[^"\\]|\\.)+)"', js))
    literals |= set(re.findall(r'OOI18N\.t : \(\(x\) => x\)\)\(\s*"((?:[^"\\]|\\.)+)"', js))
    locale = _locale(code)
    missing = sorted(s for s in literals if len(s) > 2 and s not in locale)
    assert not missing, f"{code}.json is missing {missing}"


# --------------------------------------------------------------------------- #
# Q726's disclosures, on the surface rather than in a doc.
# --------------------------------------------------------------------------- #
def test_the_ROBOTS_exemption_is_stated_on_the_Wikipedia_surface():
    """Q726 = a, worded the way src/safety/fetcher.py and src/stats/fetch.py word it
    for the statistics endpoints. VISIBLE, not only in a hover: it is a disclosure
    about what this app does to someone else's servers."""
    html = _INDEX.read_text(encoding="utf-8")
    raw = html[html.index('id="set-wikipedia"') : html.index('id="set-agenda"')]
    panel = " ".join(raw.split())
    assert "blanket-applying robots.txt" in panel
    assert "documented public API endpoints" in panel
    # The sentence is in a plain hint, not inside a [hidden] block or a <details>.
    at = panel.index("blanket-applying robots.txt")
    before = panel[max(0, at - 400) : at]
    assert "<details" not in before and "hidden" not in before, (
        "the disclosure must not be behind a disclosure widget"
    )


def test_the_LICENCE_is_stated_on_both_the_wizard_and_the_settings_surface():
    html = _INDEX.read_text(encoding="utf-8")
    panel = html[html.index('id="set-wikipedia"') : html.index('id="set-agenda"')]
    assert "CC BY-SA 4.0" in panel
    assert "CC BY-SA 4.0" in _dialog()


def test_the_wizard_says_the_budget_is_STORAGE_and_names_where_speed_lives():
    """Q1012: one rate authority. An operator who reads this as a speed limit would
    look for it in the wrong place and find a second control disagreeing with it."""
    # Whitespace normalised: the markup wraps these sentences across lines, and a
    # contiguous substring search would pass or fail on where the line happens to break.
    dialog = " ".join(_dialog().split())
    assert "not on how fast it is fetched" in dialog
    assert "collection-speed control in the top bar" in dialog
