"""Accessibility regression guards for the static shell (``src/static/index.html``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fix pass 2026-09-09, acting on the live axe-core / keyboard-walk findings in
``docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`` (findings ``home-heading-hierarchy``,
``insights-axe-heading-landmark``, ``home-nav-label-badge-concat``, and the search
time-range-slider ``aria-valid-attr-value`` finding). These are static-markup-only
checks (no browser) so they run in every environment; the fixes were additionally
verified live with Playwright + axe-core against port 8011 (see the fix report).

Scope note: two of the audit's a11y findings turned out, on inspection, to live in
JS-rendered markup this file cannot reach (``.ov-fam`` heading levels are built by
``app-home.js``; the time-range slider's ARIA value attributes are built by
``app-markets.js``) -- they are intentionally NOT covered here; see the fix report's
``notFixed`` for the exact follow-up each needs.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_INDEX = _ROOT / "src" / "static" / "index.html"


def _html() -> str:
    return _INDEX.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) page-has-heading-one: the document had zero <h1>/role=heading[level=1]
# anywhere, on all 8 audited surfaces (a persistent-chrome SPA, so one fix
# covers all of them). The brand mark now carries the one page-level heading.
# ---------------------------------------------------------------------------
def test_brand_mark_is_the_page_level_heading():
    html = _html()
    brand = html.split('class="brand"', 1)[1][:2200]
    assert re.search(r'role="heading"\s+aria-level="1"', brand), (
        "the brand block must carry the ONE page-level heading "
        '(role="heading" aria-level="1"), or axe\'s page-has-heading-one fires '
        "on every surface again"
    )
    # It must still be the visible "Open Omniscience" brand text, not a new,
    # separate element -- this is a level added to the EXISTING mark, not a
    # second identity for the page.
    heading_el = re.search(r'<b role="heading" aria-level="1">([^<]*)</b>', brand)
    assert heading_el and heading_el.group(1).strip() == "Open Omniscience", (
        "the heading role must sit on the existing brand-name element, unchanged text"
    )
    # Regression guard for the invariant #4 pinned assertion (test_repo_invariants.py):
    # the version span must still be inside the same brand block.
    assert 'id="version"' in brand


def test_only_one_page_level_heading():
    """A second <h1> (or role=heading level 1) anywhere would be just as wrong
    as zero -- exactly one is the contract."""
    html = _html()
    h1_tags = re.findall(r"<h1[\s>]", html)
    aria_level_1 = re.findall(r'role="heading"\s+aria-level="1"', html)
    assert len(h1_tags) == 0, "no literal <h1> tag was introduced (the aria-level route was chosen so the visual CSS in app.css, out of this file's ownership, needs no change)"
    assert len(aria_level_1) == 1, f"expected exactly one level-1 heading, found {len(aria_level_1)}"


# ---------------------------------------------------------------------------
# (c) The Commodities nav item's "adv" badge concatenated into its accessible
# name with no separator ("Commoditiesadv"). Fixed with a literal whitespace
# text node between the two <span>s -- accname computation joins descendant
# text verbatim and does not synthesise a space of its own.
# ---------------------------------------------------------------------------
def test_commodities_badge_has_accessible_name_separator():
    html = _html()
    m = re.search(
        r'<button class="nav-item adv" data-tab="markets">.*?</button>', html, re.S
    )
    assert m, "the Commodities nav item must exist"
    nav_html = m.group(0)
    assert "<span>Commodities</span>" in nav_html and 'class="badge">adv</span>' in nav_html
    # The old, broken markup butted the two spans together with zero whitespace
    # between them -- assert that specific run-on is gone, and a separating
    # space is present instead.
    assert "<span>Commodities</span><span class=\"badge\">adv</span>" not in nav_html, (
        "the two spans must not be adjacent with no separating text node "
        "(that is exactly what accname-concatenates into \"Commoditiesadv\")"
    )
    assert re.search(r"<span>Commodities</span>\s+<span class=\"badge\">adv</span>", nav_html), (
        "expected a whitespace text node between the label and badge spans"
    )
    # The visual badge itself (class, text, position) must be untouched.
    assert 'class="badge">adv</span>' in nav_html


# ---------------------------------------------------------------------------
# (e) axe `region`: the shared #subtab-strip wrapper (every relocated facet
# subtab nav lands here at runtime, per app-shell.js's _relocateSubtabs) had
# no landmark role, and the tablist role the ooSubtabs() helper stamps onto
# the relocated <nav> at runtime overrides its implicit navigation landmark
# -- so those tab buttons ended up contained by no landmark whatsoever, on
# every one of insights / settings / law / agenda / indices / library /
# timemap (axe's `region` rule fires on the descendant content, not just a
# generic "somewhere on the page" check).
# ---------------------------------------------------------------------------
def test_subtab_strip_is_a_landmark():
    html = _html()
    m = re.search(r'<div id="subtab-strip"[^>]*>', html)
    assert m, "#subtab-strip must exist (also pinned by test_repo_invariants.py)"
    tag = m.group(0)
    assert 'role="navigation"' in tag, "#subtab-strip needs a landmark role so relocated tablist content isn't landmark-orphaned"
    assert re.search(r'aria-label="[^"]+"', tag), "a navigation landmark needs an accessible name"
    # Must stay distinct from the sidebar's own nav landmark label ("Primary"),
    # or two navigation landmarks would share one name.
    label = re.search(r'aria-label="([^"]+)"', tag).group(1)
    assert label != "Primary"
    # Untouched: still hidden by default (shown only when a tab has facet subtabs).
    assert "hidden" in tag


# ---------------------------------------------------------------------------
# (f) Insights' "How outlets frame this (VADER tone)" / "In context" headings
# rendered over permanently-empty divs until a term is explored -- a real
# heading with no content and no empty state on first load (and every load
# where the visitor has not searched a term yet). The content genuinely is
# absent at that point, so the fix is an honest empty state, not hiding the
# heading (exploreTerm() in app-corpus.js overwrites this innerHTML the
# moment a term resolves).
# ---------------------------------------------------------------------------
def test_insights_framing_and_context_have_default_empty_state():
    html = _html()
    framing = re.search(r'<div id="ins-framing">(.*?)</div>\s*<h2', html, re.S)
    context = re.search(r'<div id="ins-context">(.*?)</div>', html, re.S)
    assert framing and framing.group(1).strip(), (
        "#ins-framing must not be a bare empty div -- the heading above it "
        "would render with nothing beneath it and no empty state"
    )
    assert context and context.group(1).strip(), (
        "#ins-context must not be a bare empty div, for the same reason"
    )
    assert 'class="muted"' in framing.group(1), "the placeholder should read as a hint, like every other honest empty state in this file"
    assert 'class="muted"' in context.group(1)


def test_insights_headings_immediately_precede_their_now_nonempty_hosts():
    """Anchor the two headings themselves are still present and in the same
    order, so a future edit can't silently detach the empty state from the
    heading it explains."""
    html = _html()
    idx_heading1 = html.index("How outlets frame this")
    idx_framing = html.index('id="ins-framing"')
    idx_heading2 = html.index("In context</h2>")
    idx_context = html.index('id="ins-context"')
    assert idx_heading1 < idx_framing < idx_heading2 < idx_context
