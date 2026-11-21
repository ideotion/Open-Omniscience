"""Row 229: links inside a line of text are underlined, not set apart by colour alone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

axe-core's link-in-text-block (WCAG 1.4.1) found two surfaces on the a11y sweep: the Time map's
OpenStreetMap credit (Ink and 11 of 13 themes) and Home's "Most recent" titles (20 nodes). The
hover convention's ``a.oo-tip-target { text-decoration: none }`` comes later in app.css than
``a.ext-link`` at the same specificity, so every TITLED link lost the underline, including the
evidence links ``extLink()`` gives the ext-link class for exactly this reason. A later rule with
higher specificity restores it; these checks pin the order, the selectors and the call sites.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_RESTORE = "a.ext-link, a.ext-link.oo-tip-target, .home-recent-row > a, .home-recent-row > a.oo-tip-target {"


def _css() -> str:
    return (_STATIC / "app.css").read_text(encoding="utf-8")


def test_restore_rule_comes_after_the_tip_rule_that_removes_the_underline():
    css = _css()
    strip = css.index("select.oo-tip-target, a.oo-tip-target,")
    assert css.count(_RESTORE) == 1, "the row 229 rule must exist exactly once"
    restore = css.index(_RESTORE)
    assert restore > strip, "a rule placed before the tip rule loses the cascade again"
    body = css[restore: css.index("}", restore)]
    assert "text-decoration-line: underline" in body and "text-decoration-style: solid" in body


def test_osm_and_dbip_credits_carry_the_underlined_class():
    js = (_STATIC / "app-map.js").read_text(encoding="utf-8")
    for href in ("https://www.openstreetmap.org/copyright", "https://db-ip.com"):
        n = js.count(f'href="{href}"')
        assert n and js.count(f'<a class="ext-link" href="{href}"') == n, href


def test_home_recent_rows_still_render_their_title_as_a_direct_child_link():
    js = (_STATIC / "app-home.js").read_text(encoding="utf-8")
    assert js.count('<div class="home-recent-row"><a href=') >= 2, \
        "the > a selector relies on the title link being the row's direct child"
