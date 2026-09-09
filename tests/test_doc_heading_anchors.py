"""docs-anchors fix (2026-09-09 visual-audit pass, FIX_BRIEF.md).

The Help panel's table of contents links to slugs like
``#1-install--first-run`` (docs/USER_MANUAL.md's own hand-written TOC), but
``mdToHtml()`` in src/static/app-settings.js rendered every heading as bare
``<h[level]>...</h[level]>`` with no ``id`` -- measured live: 103+ headings in
the rendered panel, 0 addressable. Clicking a TOC link had nowhere to land (a
SEPARATE agent scopes the popstate side of this same defect -- the click no
longer ejecting the reader to Home; this test covers only "does the anchor
have a target").

This test EXTRACTS the real ``slugifyHeading``/``mdToHtml`` functions from the
shipped source and runs them through node (the established pattern --
tests/test_legal_markdown_render.py, tests/test_agenda_month_shift.py -- a
hand-reimplementation could silently drift from the real code). It proves,
against the REAL docs/USER_MANUAL.md:

  * every rendered heading gets a non-empty, UNIQUE id (the doc has real
    duplicate heading text -- four "API" headings, two "Intent" headings --
    so naive slugging without de-duplication would collide);
  * the anchor convention matches the doc's own reference link
    #1-install--first-run: a deleted punctuation character's two neighbouring
    spaces both survive as hyphens (never collapsed to one) -- verified
    against four independent hand-written anchors in the doc that all show
    the same double-hyphen shape for a deleted "&" or em dash;
  * a solid majority (>=80%) of the doc's own 50 in-page TOC links now
    resolve to a real heading id. The remainder are pre-existing, genuine
    authoring inconsistencies in the markdown itself (a shortened link that
    drops half the heading text, or a link hand-typed assuming the OTHER,
    collapsing convention) -- fixing those would mean editing the markdown,
    which is out of scope for this pass (FIX_BRIEF.md: "do not change the
    markdown"). This test pins the exact set so a future regression in
    EITHER direction is visible.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import arrow_const_source, function_source, read_static

_ROOT = Path(__file__).resolve().parents[1]
_APP_SETTINGS = _ROOT / "src" / "static" / "app-settings.js"
_APP_CORE = _ROOT / "src" / "static" / "app-core.js"
_USER_MANUAL = _ROOT / "docs" / "USER_MANUAL.md"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")

# The doc's own hand-written anchors that a correct slugifier MUST reproduce --
# each independently confirms "delete the punctuation char, keep both of its
# neighbouring spaces as separate hyphens" (never collapsed to one hyphen).
_REFERENCE_ANCHORS = {
    "1. Install & first run": "1-install--first-run",
    "3.0a Activity & the Task manager": "30a-activity--the-task-manager",
    "3.8 Evidence & custody": "38-evidence--custody",
    "5.5a Memory on a small machine — the one real ceiling":
        "55a-memory-on-a-small-machine--the-one-real-ceiling",
}


def _extract_esc() -> str:
    """The real ``esc`` arrow-const, lifted through the shared helper.

    This used to be ``src.index("const esc = (s) => (s == null")`` -- a hand-rolled
    anchor, which is what ``test_source_slicing_discipline`` counts. The helper had
    no shape for an EXPRESSION arrow (no braced body to match), so
    ``arrow_const_source`` was added there rather than the slice re-derived here.
    """
    return arrow_const_source(read_static("app-core.js"), "esc")


def _extract_settings_slice() -> str:
    """``slugifyHeading`` + ``mdToHtml`` as shipped, never reimplemented.

    Both come through ``function_source``, which balances the parameter list
    before brace-matching, so neither a default parameter nor a nested object
    literal can end the slice early -- and no sentinel is needed for "where does
    the next top-level function start", which is the guess that over-runs.
    """
    src = read_static("app-settings.js")
    return function_source(src, "slugifyHeading") + "\n" + function_source(src, "mdToHtml")


def _run(md_path: Path) -> dict:
    esc_fn = _extract_esc()
    settings_fn = _extract_settings_slice()
    harness = f"""
{esc_fn}
{settings_fn}
const fs = require('fs');
const md = fs.readFileSync({json.dumps(str(md_path))}, 'utf8');
const html = mdToHtml(md);
const ids = [...html.matchAll(/<h[1-6] id="([^"]*)"/g)].map(m => m[1]);
const links = [...md.matchAll(/\\]\\(#([a-z0-9-]+)\\)/g)].map(m => m[1]);
console.log(JSON.stringify({{ids, links}}));
"""
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def _run_slugify_only(heading: str) -> str:
    # Only slugifyHeading is needed here, so slice exactly that one function
    # through the helper rather than truncating the combined slice by hand.
    fn = function_source(read_static("app-settings.js"), "slugifyHeading")
    harness = f"""
{fn}
console.log(slugifyHeading({json.dumps(heading)}));
"""
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout.strip()


def test_headings_get_nonempty_unique_ids():
    result = _run(_USER_MANUAL)
    ids = result["ids"]
    assert len(ids) > 100, f"expected 100+ headings in USER_MANUAL.md, got {len(ids)}"
    assert all(i for i in ids), "every heading must get a NON-EMPTY id"
    assert len(ids) == len(set(ids)), (
        "heading ids must be UNIQUE -- USER_MANUAL.md has real duplicate heading "
        "text (four headings slug to 'api', two to 'intent') that a naive "
        "slugifier would collide on"
    )
    # the real duplicate-text case: four separate "API" headings must produce
    # four distinct ids, not one id reused three times.
    api_like = [i for i in ids if i == "api" or re.match(r"^api-\d+$", i)]
    assert len(api_like) == 4, f"expected 4 distinct api/api-N ids, got {api_like}"


@pytest.mark.parametrize("heading,expected", list(_REFERENCE_ANCHORS.items()))
def test_slug_matches_the_docs_own_reference_anchor(heading, expected):
    assert _run_slugify_only(heading) == expected


def test_most_of_the_docs_own_toc_links_now_resolve():
    result = _run(_USER_MANUAL)
    ids = set(result["ids"])
    links = result["links"]
    assert len(links) == 50, f"USER_MANUAL.md's own in-page link count changed ({len(links)}); re-verify this test's numbers"
    resolved = [link for link in links if link in ids]
    unresolved = sorted({link for link in links if link not in ids})
    # Pinned, not rounded up: these 9 unique targets are pre-existing markdown
    # authoring inconsistencies (shortened links, or links hand-typed assuming
    # the opposite/collapsing convention) that no single consistent slugifier
    # can satisfy alongside the reference anchors above -- see module docstring
    # and this session's verifiedHow notes.
    expected_unresolved = {
        "32-collect", "33-sources", "37-wikipedia",              # TOC shortens the heading (drops the "*(in Settings -> X)*" part)
        "31a-analysis-the-corpora-window",                          # hand-typed collapsing single-hyphen guess
        "the-home-briefing-intelligence-as-honest-cards",
        "source-integrity-anti-amplification",
        "shared-source-annotations-signed-portable-federated-by-trust",
        "insights-keyword-entity-analytics",
        "world-law-change-tracking-for-statutes-gazettes-ip",
    }
    assert unresolved == sorted(expected_unresolved), (
        f"unresolved anchor set changed: {unresolved}"
    )
    assert len(resolved) >= 40, f"only {len(resolved)}/50 links resolved"


def test_old_bare_heading_would_have_failed_this(monkeypatch):
    """Guards the regression this fix closes: a heading rendered WITHOUT an id
    attribute (the pre-fix behaviour) must be recognizable as broken by the
    same assertion the fixed code passes."""
    esc_fn = _extract_esc()
    old_style = f"""
{esc_fn}
function oldMdToHtmlHeading(text) {{
  const inline = (t) => esc(t);
  return `<h2>${{inline(text)}}</h2>`;
}}
console.log(oldMdToHtmlHeading("1. Install & first run"));
"""
    r = subprocess.run(["node", "-e", old_style], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert 'id="' not in r.stdout, "sanity check itself is wrong: old-style heading unexpectedly carries an id"
    # and the FIXED extraction, on the same heading, DOES carry the id:
    result = _run(_USER_MANUAL)
    assert "1-install--first-run" in result["ids"]
