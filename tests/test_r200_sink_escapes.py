"""Four unescaped values reached HTML (audit 0.5.0, js-sinks F1 to F4, R200).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

None was reachable from the web: each value is stored locally (a draft card id, a commodity symbol,
a source tag) and only the operator, an import, a restore or a local process can plant it. They are
fixed because ``oo-on.js`` makes any HTML injection in the SPA a call to an allowed function.

An id or symbol written into a ``data-on-*`` argument goes through ``esc(JSON.stringify(x))``, not
``'${esc(x)}'``: the browser decodes the attribute before ``oo-on.js`` parses it, so an escaped
apostrophe comes back as an apostrophe and closes the string argument. The shape was checked in
Chromium (see the PR body); the assertions here pin it in the source.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import _function_span, read_static

_ROOT = Path(__file__).resolve().parent.parent


def _body(js: str, name: str) -> str:
    _, body_at, end = _function_span(js, name)
    return js[body_at:end]


def test_draft_item_card_id_is_escaped_at_all_three_sinks() -> None:
    body = _body(read_static("app-home.js"), "renderDraft")
    assert 'data-id="${esc(c.id)}"' in body
    assert "saveDraftItemNote(${esc(JSON.stringify(c.id))}, this.value)" in body
    assert "removeDraftItem(${esc(JSON.stringify(c.id))})" in body
    assert "${c.id}" not in body.replace("${esc(c.id)}", ""), "a card id is written into the draft markup unescaped"


def test_trend_chip_symbol_is_a_json_string_argument() -> None:
    js = read_static("app-analysis.js")
    assert "anTrendPick(${esc(JSON.stringify(sym))})" in js
    assert "anTrendPick('${sym}')" not in js


def test_transparency_tags_are_escaped_before_they_are_joined() -> None:
    js = read_static("app-home.js")
    assert "(tr.ownership_tags||[]).map(esc).join" in js
    assert "(tr.leaning_tags||[]).map(esc).join" in js
    assert "(tr.leaning_tags||[]).join" not in js


def test_reader_esc_escapes_quotes() -> None:
    js = read_static("reader.js")
    body = _body(js, "esc")
    assert '.replace(/"/g, "&quot;")' in body and ".replace(/'/g, \"&#39;\")" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_reader_esc_behaviour_in_node() -> None:
    result = subprocess.run(  # noqa: S603
        ["node", str(_ROOT / "tests" / "reader_esc_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
