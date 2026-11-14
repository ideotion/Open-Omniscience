"""The ONE "Field data" button (maintainer, 2026-11-09).

«Simplify the field test button, I want just a single button to push on, updated as instances move
on, that will help you have field based information. For now, let's start with sources and articles.
one single button, one or several files are downloaded and I take care of sending them back to you.
Remove all information around this, no need.»

So: one button beside Diagnostics, no list, no counts, no explanatory block; what it saves is the
FIELD_DATA_EXPORTS list in app-diagnostics.js (sources and articles first), every entry a loopback,
read-only export that already exists and scrubs what it writes.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import array_literal, function_body, object_literal

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")


def _at(html: str, needle: str) -> int:
    m = re.search(re.escape(needle), html)
    assert m, needle
    return m.start()


def test_one_button_and_a_status_line_and_nothing_else_around_it():
    html = _html()
    assert html.count('id="field-data-btn"') == 1
    assert 'data-on-click="downloadFieldData(this)"' in html
    # the row is the button and its status line: no hint, no list, no count
    row = re.search(r'<div class="row"[^>]*>\s*(<button[^>]*id="field-data-btn".*?)</div>', html, re.S)
    assert row, "the Field data row"
    assert re.findall(r"<(\w+)[ >]", row.group(1)) == ["button", "span"], row.group(1)
    assert 'id="field-data-status"' in row.group(1)
    # it sits in the Diagnostics section, after the parts bar (only the bar's own buttons go above it)
    diag = _at(html, 'data-adv="diagnostics"')
    end = diag + re.search(r"\n    </details>", html[diag:]).start()
    assert diag < _at(html, 'id="parts-bar"') < _at(html, 'id="field-data-btn"') < end


def test_the_field_checks_panel_and_the_two_temp_buttons_are_gone():
    html = _html()
    for gone in ('data-adv="fieldchecks"', 'id="field-checks-box"', 'id="fc-open-link"', 'id="fc-count"',
                 'id="source-samples-btn"', "ooOpenUrl('/api/diagnostics/source-quality?download=1')"):
        assert gone not in html, gone
    js = _js()
    for gone in ("fieldChecksLoad", "_fcRun", "_fcPaintCount", "downloadSourceSamples", "#source-samples-btn"):
        assert gone not in js, gone
    shell = (STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert "fieldChecks" not in shell and "fieldchecks" not in object_literal(shell, "_ADV_LOADERS")
    assert "_fcPaintCount" not in (STATIC / "app-boot.js").read_text(encoding="utf-8")


def test_sources_and_articles_come_first_and_every_export_is_a_loopback_read():
    js = _js()
    exports = array_literal(js, "FIELD_DATA_EXPORTS")
    urls = re.findall(r'url: "([^"]+)"', exports)
    # Sources and articles first (2026-11-09); the cards file joined them on 2026-11-14 (Lane X).
    assert urls == [
        "/api/diagnostics/source-quality?download=1",
        "/api/diagnostics/source-samples?after=",
        "/api/diagnostics/field-cards",
    ]
    # same-origin paths only: nothing the button saves goes online
    assert all(u.startswith("/api/") for u in urls)
    # the cards export reads article text, so it is a POST (R694)
    assert 'method: "POST", url: "/api/diagnostics/field-cards"' in exports
    run = function_body(js, "downloadFieldData")
    assert "fetch(ex.url, ex.method ? {method: ex.method} : undefined)" in run and "fetch(ex.url + after)" in run
    assert "ensureOnline(" not in run
    # a cursor that does not advance ends the walk; the button is given back whatever happens
    assert "!(Number(nxt) > after)" in run
    assert "finally" in run and "btn.disabled = false" in run


def test_every_saved_file_is_cut_to_an_uploadable_size():
    """2026-11-14: «create smaller files» -- about half the parts would not upload. Both kinds of export go through
    one saver that cuts anything over FIELD_PART_BYTES into numbered pieces, and the server's sample cap matches it."""
    js = _js()
    m = re.search(r"const FIELD_PART_BYTES = (\d+) \* 1000;", js)
    assert m and int(m.group(1)) * 1000 <= 500_000
    run = function_body(js, "downloadFieldData")
    assert run.count("await _fieldSaveParts(await r.blob()") == 2 and "_fieldSave(await r.blob()" not in run
    saver = function_body(js, "_fieldSaveParts")
    assert "blob.slice(" in saver and "-part-" in saver and "-of-" in saver
    # one piece at a time (a tight loop of downloads loses some), numbers padded to the width of the count
    assert "await pause()" in saver and "String(n).length" in saver
    from src.api.diagnostics.source_samples import SAMPLE_ZIP_MAX_BYTES
    assert int(m.group(1)) * 1000 == SAMPLE_ZIP_MAX_BYTES


def test_the_button_is_wired_through_the_one_dispatcher():
    on = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    table = object_literal(on, "EVENT_ACTION_NAMES")
    click_row = re.search(r"click:\s*\[(.*?)\]", table, re.S)
    assert click_row and '"downloadFieldData"' in click_row.group(1)
