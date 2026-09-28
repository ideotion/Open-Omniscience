"""The Help reader's list items survive being wrapped across source lines.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-09-26 click-through J8: ``mdToHtml()`` (src/static/app-settings.js) took a list item
to be exactly ONE source line, so every wrapped bullet in the shipped docs ended where its
first line did and the rest rendered as a stray paragraph outside the list -- the manual's
"Exports are never scheduled" bullet stopped at "and none is". The same function also
matched a code-fence placeholder only when it was unindented, so a fence inside a list item
(ARCHITECTURE.md's migration commands) rendered as a literal "F0" and its code was lost.

The real functions are lifted from the shipped source and run under node, never
reimplemented (the pattern of tests/test_doc_heading_anchors.py).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import arrow_const_source, function_source, read_static

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

_DOCS = Path(__file__).resolve().parent.parent / "docs"


def _render(md: str) -> str:
    fns = "\n".join(
        (
            arrow_const_source(read_static("app-core.js"), "esc"),
            function_source(read_static("app-settings.js"), "slugifyHeading"),
            function_source(read_static("app-settings.js"), "mdToHtml"),
        )
    )
    # The document goes in on stdin: the whole manual is too long for an argv string.
    harness = fns + "\nprocess.stdout.write(mdToHtml(require('fs').readFileSync(0, 'utf8')));\n"
    r = subprocess.run(
        ["node", "-e", harness], input=md, capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def test_a_wrapped_item_stays_one_item():
    md = "- first line\n  goes on here\n  - nested item\n    wraps too\n  Back at the outer indent.\n"
    html = _render(md)
    assert "<li>first line goes on here</li><li>nested item wraps too</li></ul>" in html, html
    # A line back at the marker's own indent is not the item's: it ends the list.
    assert "<p>  Back at the outer indent.</p>" in html, html


def test_a_blank_line_or_a_new_marker_still_ends_an_item():
    html = _render("- one\n- two\n\nAfter.\n")
    assert "<ul><li>one</li><li>two</li></ul>" in html and "<p>After.</p>" in html, html


def test_the_manuals_never_scheduled_bullet_renders_whole():
    html = _render((_DOCS / "USER_MANUAL.md").read_text(encoding="utf-8"))
    start = html.index("Exports are never scheduled.")
    item = html[start : html.index("</li>", start)]
    assert "and none is planned — an export is a <strong>deliberate act</strong>" in item, item
    assert item.endswith("at a moment you chose."), item
    assert "<p>    planned" not in html


def test_a_fence_inside_a_list_item_keeps_its_code():
    html = _render("- Upgrade:\n  ```bash\n  make migrate\n  ```\n- Next\n")
    assert "<pre" in html and "make migrate" in html, html
    assert "F0" not in html, html
