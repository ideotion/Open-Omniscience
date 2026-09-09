"""Shell routing + palette fixes (2026-09-08 visual audit, fix pass).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two defects, one file (``src/static/app-shell.js``):

(a) hash-anchor-ejects-to-home (P1). Help renders 50 visible in-page table-of-contents
    anchors against 103 headings, none of which carry an ``id``. Clicking one changes
    ``location.hash``; the ``popstate`` handler used to call ``showTab`` unconditionally,
    which found no ``#tab-<anchor>`` element, fell back to Home, and rewrote the URL --
    ejecting the reader from whatever they were reading. The fix (``_hashIsTab`` +
    the named ``_onPopStateRoute``) only routes through ``showTab`` when the hash
    plausibly names a real tab.

(b) The command palette's "Pages" group was built from the static ``NAV`` array, which
    had drifted from the rendered sidebar (Feed and Observatory -- the two largest
    surfaces by control count -- were on the sidebar but not in ``NAV``, so they were
    unreachable from the palette). The fix (``_navPages``) keeps NAV's curated labels
    but appends anything the LIVE sidebar (``#navGroups .nav-item[data-tab]``) renders
    that NAV does not already name, so a future sidebar addition can't repeat the gap
    silently.

These are BEHAVIOURAL tests, not source greps: the exact functions are sliced out of
the real file with ``tests.js_source_helper`` (brace-matched, not re-typed) and driven
under ``node`` with a minimal fake DOM. Run directly against the pre-fix file, the
node harnesses below fail: ``_hashIsTab``/``_onPopStateRoute``/``_navPages`` do not
exist yet (the source-slicer raises), and the old ``palCommands`` reaches Feed/
Observatory only through this test's fake sidebar becoming impossible to satisfy from
``NAV`` alone. Both were confirmed to fail against a checked-out copy of the pre-fix
file (see ``verifiedHow`` in this session's report) before being confirmed green here.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, function_source, read_static

_ROOT = Path(__file__).resolve().parents[1]


def _shell_src() -> str:
    return read_static("app-shell.js")


def _run_node(script: str) -> str:
    """Write ``script`` to a scratch file and run it under node, returning stdout.

    A real temp file rather than ``node -e`` (or ``node --check``): the harness is
    long enough that quoting it onto a command line is its own hazard, and a file
    gives a useful path in a failure's stack trace.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "harness.js"
        p.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(p)], capture_output=True, text=True, timeout=60, cwd=str(_ROOT)
        )
        assert proc.returncode == 0, (
            f"node harness failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        return proc.stdout


def _sidebar_items() -> list[tuple[str, str]]:
    """The real ``(data-tab, visible label)`` pairs rendered in the sidebar.

    Parsed straight out of ``index.html`` (never hand-listed) so this test tracks the
    ACTUAL sidebar rather than a snapshot of it -- the exact drift that caused (b).
    """
    html = read_static("index.html")
    start = html.index('id="navGroups"')
    end = html.index("</nav>", start)
    block = html[start:end]
    items: list[tuple[str, str]] = []
    for _classes, tab_id, inner in re.findall(
        r'<button class="([^"]*)" data-tab="([a-z0-9_-]+)"[^>]*>(.*?)</button>', block, re.S
    ):
        label = None
        for cls, text in re.findall(r'<span(?: class="([^"]*)")?>([^<]*)</span>', inner):
            if cls != "badge":
                label = text
                break
        items.append((tab_id, label or tab_id))
    assert items, "the sidebar markup shape changed -- update the parser, not the test"
    return items


# --------------------------------------------------------------------------------- #
# (a) hash-anchor-ejects-to-home
# --------------------------------------------------------------------------------- #


def test_popstate_is_wired_to_a_named_guarded_function() -> None:
    """Source guard: the tab-routing popstate listener must be named (so it can be
    driven directly by the node harness below) and the sibling dialog-closing
    listener (imp-ghost-modal-after-back) must remain a SEPARATE, unconditional
    listener -- that one must keep firing on every Back/Forward, tab-hash or not."""
    src = _shell_src()
    assert 'window.addEventListener("popstate", _onPopStateRoute);' in src
    assert src.count('window.addEventListener("popstate"') == 2, (
        "expected exactly two popstate listeners: the tab router and the "
        "imp-ghost-modal-after-back dialog closer"
    )
    dialog_listener = src.split('window.addEventListener("popstate", _onPopStateRoute);', 1)[1]
    assert 'd.dispatchEvent(new Event("cancel"' in dialog_listener, (
        "the dialog-closing popstate listener must still be present and unconditional"
    )


def test_hash_guard_and_route_behaviour_under_node() -> None:
    """Drive the REAL sliced functions: an unknown hash (an in-page anchor) must not
    call showTab at all; a real tab hash (incl. the legacy redirect names showTab
    itself handles) must still call it, so Back/Forward keeps working."""
    src = _shell_src()
    m = re.search(r"const _LEGACY_TAB_HASHES = new Set\(\[[^\]]*\]\);", src)
    assert m, "_LEGACY_TAB_HASHES not found -- was the guard renamed?"
    legacy_line = m.group(0)
    hash_is_tab_src = function_source(src, "_hashIsTab")
    onpop_src = function_source(src, "_onPopStateRoute")

    script = f"""
"use strict";
const assert = require("assert");

{legacy_line}
{hash_is_tab_src}
{onpop_src}

// A fake DOM: only these ids exist as real ".tab-page" elements.
const REAL_TABS = new Set(["home", "help", "search", "settings"]);
global.document = {{
  getElementById: (id) => {{
    const name = id.replace(/^tab-/, "");
    return REAL_TABS.has(name) ? {{}} : null;
  }},
}};

// _hashIsTab: the unit the routing decision is made from.
assert.strictEqual(_hashIsTab("home"), true, "a real tab must be recognised");
assert.strictEqual(_hashIsTab("help"), true, "Help itself must be recognised");
assert.strictEqual(_hashIsTab("wiki"), true, "the legacy wiki->settings redirect must still route");
assert.strictEqual(_hashIsTab("ingest"), true, "the legacy ingest->settings redirect must still route");
assert.strictEqual(
  _hashIsTab("1-install--first-run"), false,
  "a Help table-of-contents anchor (measured: no matching tab-* element) must NOT be treated as a tab"
);
assert.strictEqual(_hashIsTab("some-article-heading"), false, "an arbitrary in-page anchor must not be a tab");

// _onPopStateRoute: the exact function `addEventListener("popstate", ...)` holds.
let calls;
global.showTab = (name, push) => calls.push([name, push]);

calls = [];
global.location = {{ hash: "#1-install--first-run" }};
_onPopStateRoute();
assert.deepStrictEqual(calls, [], "clicking a Help TOC anchor must NOT eject the reader to another tab");

calls = [];
global.location = {{ hash: "#help" }};
_onPopStateRoute();
assert.deepStrictEqual(calls, [["help", false]], "Back/Forward to a real tab must still call showTab(name, false)");

calls = [];
global.location = {{ hash: "" }};
_onPopStateRoute();
assert.deepStrictEqual(calls, [["home", false]], "an empty hash must still default to Home");

console.log("hash-guard node harness: all assertions passed");
"""
    out = _run_node(script)
    assert "all assertions passed" in out


def test_hash_guard_fails_to_slice_from_the_pre_fix_shape() -> None:
    """Documents the FAIL side of the fail/pass pair required by the fix brief: the
    node harness above depends on ``_hashIsTab``/``_onPopStateRoute`` existing as
    named functions. Simulate the pre-fix source (the two-line inline arrow this
    replaced) and confirm the slicer -- and therefore the whole behavioural test --
    cannot find them, i.e. it fails loudly rather than passing vacuously."""
    from tests.js_source_helper import function_source as _fs

    pre_fix_src = (
        'window.addEventListener("popstate", () =>\n'
        '  showTab((location.hash || "#home").slice(1), false));\n'
    )
    with pytest.raises(AssertionError):
        _fs(pre_fix_src, "_onPopStateRoute")
    with pytest.raises(AssertionError):
        _fs(pre_fix_src, "_hashIsTab")


# --------------------------------------------------------------------------------- #
# (b) palette Pages omitting sidebar surfaces
# --------------------------------------------------------------------------------- #


def test_every_sidebar_tab_is_reachable_from_the_palette() -> None:
    """The literal drift guard the brief asks for: every ``#navGroups
    .nav-item[data-tab]`` must appear among ``_navPages()``'s output, driven under
    node against the REAL sidebar markup (parsed from index.html, not hand-listed)
    so a future sidebar addition without a matching NAV/derivation update fails
    this test instead of shipping unreachable."""
    src = _shell_src()
    nav_pages_src = function_source(src, "_navPages")
    m = re.search(r"const NAV = \[.*?\n    \];", src, re.S)
    assert m, "NAV array not found -- was it renamed?"
    nav_src = m.group(0)

    sidebar = _sidebar_items()
    sidebar_json = json.dumps([{"id": tab_id, "label": label} for tab_id, label in sidebar])

    script = f"""
"use strict";
const assert = require("assert");

{nav_src}
{nav_pages_src}

const SIDEBAR = {sidebar_json};
global.document = {{
  querySelectorAll: (sel) => {{
    assert.strictEqual(sel, "#navGroups .nav-item[data-tab]", "must query the LIVE sidebar, not a copy");
    return SIDEBAR.map((it) => ({{
      dataset: {{ tab: it.id }},
      querySelector: (s) => ({{ textContent: it.label }}),
    }}));
  }},
}};

const pages = _navPages();
const ids = pages.map((p) => p.id);
for (const it of SIDEBAR) {{
  assert.ok(ids.includes(it.id), "sidebar tab '" + it.id + "' is missing from the palette's page list");
}}
// The two concretely-reported gaps, named explicitly so a regression here is unambiguous.
assert.ok(ids.includes("feed"), "Feed must be reachable from the command palette");
assert.ok(ids.includes("observatory"), "Observatory must be reachable from the command palette");
// No duplicates: a tab present in both NAV and the sidebar must appear exactly once.
assert.strictEqual(new Set(ids).size, ids.length, "a tab must not be listed twice in the palette");

console.log("navPages node harness: all assertions passed");
"""
    out = _run_node(script)
    assert "all assertions passed" in out


def test_nav_pages_is_actually_wired_into_the_palette() -> None:
    """Source guard against the mechanism silently reverting to the flat `NAV.map`
    this replaced (which is exactly what let the sidebar drift in the first place).

    Uses the shared brace-matched slicer (never a hand-rolled index/split pair) --
    tests/test_source_slicing_discipline.py ratchets exactly that hazard.
    """
    src = _shell_src()
    palette_fn = function_body(src, "palCommands")
    assert "_navPages()" in palette_fn, "palCommands must build Pages from _navPages(), not NAV directly"
    assert '#navGroups .nav-item[data-tab]' in src, "the derivation must scan the live sidebar"


def test_feed_and_observatory_have_curated_nav_labels() -> None:
    """Belt-and-braces: Feed and Observatory (both already reachable via the
    DOM-derived safety net above) also get a proper curated NAV row, so their
    palette entry carries a real grouping label rather than a bare fallback."""
    src = _shell_src()
    m = re.search(r"const NAV = \[(.*?)\n    \];", src, re.S)
    assert m
    nav_body = m.group(1)
    assert '{id:"feed",' in nav_body.replace(" ", "") or '{id:"feed"' in nav_body
    assert '{id:"observatory",' in nav_body.replace(" ", "") or '{id:"observatory"' in nav_body


# --------------------------------------------------------------------------------- #
# (c) the palette teaching the keyboard shortcuts it already knows about
# --------------------------------------------------------------------------------- #


def test_palette_offers_a_route_to_the_shortcuts_panel() -> None:
    """§4c, in scope but explicitly NOT a default-shortcut change: the palette gained
    a discovery action pointing at Settings -> General, where all five actions from
    ``_kbActions()`` are listed and rebindable (``#kb-panel`` / ``loadShortcuts``).
    Reuses the two existing, already-×12 English strings "Keyboard shortcuts" and
    "System" -- verified against src/static/locales/en.json so this introduces no
    string that needs a new translation."""
    src = _shell_src()
    assert '{grp:"Actions", label:"Keyboard shortcuts"' in src
    assert 'select("general")' in src

    locale = json.loads(
        (_ROOT / "src" / "static" / "locales" / "en.json").read_text(encoding="utf-8")
    )
    assert "Keyboard shortcuts" in locale, "reused string must already be a translated key"
    assert "System" in locale, "reused string must already be a translated key"


def test_node_files_are_syntactically_valid() -> None:
    """A cheap belt-and-braces check independent of the behavioural harnesses above:
    the owned file must still parse under node."""
    proc = subprocess.run(
        ["node", "--check", str(_ROOT / "src" / "static" / "app-shell.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
