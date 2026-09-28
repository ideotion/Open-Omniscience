"""Three layout defects from the 2026-09-26 delegated click-through, pinned at the source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each was measured in Chromium (the numbers are in the comments beside the fixes); these pin
the property that made each one happen, so it cannot quietly come back:

* U4 -- Help scrolled sideways by 406 px at 375 px: ``.doc-layout``'s ``1fr`` track has
  an ``auto`` minimum, so one unbreakable ``<pre>`` line widened the column past the
  viewport. ``minmax(0,1fr)`` lets the pre's own ``overflow-x:auto`` do the scrolling.
* P9 -- Settings -> Wikipedia scrolled sideways by 29 px at 375 px: the "Build index ·
  Cancel build · Clear index" group was ``flex:0 0 auto`` (never shrinks, never wraps), and
  so was the "Search titles · Read locally" pair (6 px in French once the trio was fixed).
* U7 -- the newsletter source rows read "BBC News1": they reuse ``.vr`` markup whose only
  rules are scoped to the task manager, so name and count ran together.
"""

from __future__ import annotations

import re

from tests.js_source_helper import css_rule, read_static


def test_the_help_layouts_text_column_can_shrink_below_its_content():
    css = read_static("app.css")
    assert "minmax(0,1fr)" in css_rule(css, ".doc-layout").replace(" ", "")
    narrow = re.findall(r"\.doc-layout\s*\{\s*grid-template-columns:([^;}]*)", css)
    assert narrow, "the phone-width .doc-layout rule is gone"
    for cols in narrow:
        assert "1fr" not in cols.replace("minmax(0,1fr)", "").replace(" ", ""), cols
    # ...and the long unbroken tokens inside the column (inline <code> API paths) wrap
    # rather than sticking out of it.
    assert "overflow-wrap:break-word" in css_rule(css, ".prose").replace(" ", "")


def test_the_dump_button_groups_wrap_instead_of_widening_the_row():
    """Both multi-button groups of the panel: the index trio (en, 29 px) and the
    "Search titles · Read locally" pair (fr, 6 px -- measured after the trio was fixed)."""
    html = read_static("index.html")
    for first in ("dumpFtsBuild", "dumpSearchTitles"):
        m = re.search(
            r'<div style="([^"]*)">\s*<button class="secondary" data-on-click="' + first + r'\(\)">', html
        )
        assert m, f"the {first} button group moved"
        style = m.group(1).replace(" ", "")
        assert "flex-wrap:wrap" in style and "flex:00auto" not in style, (first, style)
    for field in ("dumpfts-q", "dumpread-title"):
        q = re.search(r'<div style="([^"]*)">\s*<label for="' + field + '">', html)
        assert q and re.search(r"flex:2 1 \d+px", q.group(1)), f"{field} needs a real basis"


def test_the_newsletter_source_rows_keep_name_and_count_apart():
    rule = css_rule(read_static("app.css"), "#nl-attach-body .vr").replace(" ", "")
    assert "display:flex" in rule and "justify-content:space-between" in rule, rule
    assert "gap:" in rule, rule
