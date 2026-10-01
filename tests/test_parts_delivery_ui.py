"""The page's side of the 1 MB numbered files (2026-10-01): five to a click, manifest first.

The behaviour is driven in node (``parts_delivery_node_test.js``) against functions extracted from
the shipped module. This half is the driver the node-suite ratchet requires, plus what belongs on
this side: the buttons exist and call the routine with the mode that picks the URL, the bar's
elements exist, nothing is wired with an inline handler (the CSP has no 'unsafe-inline'), and every
string the delivery introduces is keyed in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"

#: Every English string the delivery can put on screen (keys, with their {placeholders}). Keyed
#: here rather than trusted to the i18n ratchets, which are MAXIMA.
_STRINGS = [
    "All diagnostics (1 MB files)",
    "All diagnostics, again (last build, 1 MB files)",
    "All keywords (1 MB files)",
    "Keyword log (1 MB files)",
    "Last keyword files, again",
    "Building the numbered keyword files… a large corpus takes minutes; the app stays usable.",
    "Looking for the last keyword files…",
    "No keyword files are kept on this machine yet — build them with one of the keyword buttons.",
    "Ready — preparing the numbered files…",
    "Save all the rest",
    "Save the next 5",
    "Start at part number",
    "Your browser may ask once to allow several downloads: allow them.",
    "Save all {n} files",
    "Save the first {n}",
    "Save the last {n}",
    "Save the next {n}",
    "Saved {done} of {n} files.",
    "All {n} files saved. Send them all together: the manifest lists every file with its size and checksum.",
    "{n} files of at most 1 MB each are ready: the manifest and {parts} numbered parts.",
    "Could not build the keyword files: {why}",
]


def test_delivery_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "parts_delivery_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_delivery_string_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s[:48]!r}")
            elif not str(data[s]).strip():
                missing.append(f"{path.name}: {s[:48]!r} is EMPTY")
            elif sorted(re.findall(r"\{\w+\}", s)) != sorted(re.findall(r"\{\w+\}", data[s])):
                missing.append(f"{path.name}: {s[:48]!r} lost or invented a placeholder")
    assert not missing, "\n".join(missing)


def test_the_buttons_and_the_bar_exist_and_use_no_inline_handlers() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    for call in (
        "downloadKeywordParts(this, 'default')",
        "downloadKeywordParts(this, 'all')",
        "downloadKeywordParts(this, 'again')",
        "downloadDiagnosticsVolumes(this)",
        "runAllDiagnostics(this)",
        "partsSaveNext()",
        "partsSaveRest()",
    ):
        assert f'data-on-click="{call}"' in html, call
    for ident in ("parts-bar", "parts-status", "parts-next", "parts-rest", "parts-from", "parts-from-wrap"):
        assert f'id="{ident}"' in html, ident
    bar = html[html.index('id="parts-bar"'): html.index('id="parts-from"')]
    assert not re.search(r"\son(click|input|change)=", bar), "the CSP has no 'unsafe-inline'"
    # The names the page calls are registered with the dispatcher.
    on = (_STATIC / "oo-on.js").read_text(encoding="utf-8")
    for name in ("downloadKeywordParts", "partsSaveNext", "partsSaveRest"):
        assert f'"{name}"' in on, name


def test_hidden_wins_on_the_bar_and_the_part_number_box() -> None:
    """`label { display:block }` and `.row` are author rules, and an author `display` beats the
    browser's `[hidden]`: the Chromium walk of 2026-10-01 saw the "Start at part number" box on a
    page that had built nothing. Reading attributes, as the other tests here do, cannot see that,
    so the stylesheet must carry the two rules that make `hidden` win."""
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    for ident in ("#parts-bar", "#parts-from-wrap"):
        assert re.search(re.escape(ident) + r"\[hidden\][^{}]*\{[^}]*display:\s*none", css), ident


def test_the_page_never_opens_one_big_download_for_the_bundle_or_the_keyword_log() -> None:
    js = (_STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    assert 'window.open("/api/diagnostics/all-job/download"' not in js
    assert "format=zip" not in js
    # five to a click is a named constant, and the reason is written beside it
    assert "const _PARTS_PER_CLICK = 5;" in js
    assert "take FIVE files per message" in js
