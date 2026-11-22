"""Row 326: data is never translated, and the AI activity feed and the custody table speak the reader's language.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

1. The page translates a text node whose whole text equals a locale key. Row 322 added the bare keys "junk", "content"
   and "unsure", so a corpus keyword "content" would have shown as "contenu": the app altering the user's data on
   screen. The verdicts now use labelled keys ("Verdict: junk"), and the walker leaves anything inside an element marked
   translate="no" alone, which the feed's keyword and anchor-grading term cells now carry.
2. The AI activity feed printed raw counter names, kind tokens, units and an English coordinator note; one counter is
   a nested object and printed "[object Object]".
3. The custody entries table printed the word "opentimestamps" where an unconfirmed proof has no time yet.

tests/raw_values_row326_node_test.js runs the real i18n.js over the real French file, and the real helpers; this file
keeps the client's maps equal to the names the server writes, and the words x12.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, object_literal

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
LOCALES = sorted((STATIC / "locales").glob("*.json"))


def _node() -> list[str]:
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "raw_values_row326_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[-1] == "raw values row 326: all checks passed"
    return json.loads(lines[-2])


def _locale(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8"))


def _js_map_keys(js: str, name: str) -> set[str]:
    body = object_literal(js, name)
    return set(re.findall(r'[{,]\s*"?([\w-]+)"?\s*:', body))


def test_every_word_the_maps_use_is_a_key_in_all_twelve_locales():
    keys = _node()
    assert len(keys) >= 25, keys
    assert len(LOCALES) == 12
    for f in LOCALES:
        loc = _locale(f)
        for k in keys + [
            "Custody entries: {n}",
            "≈ Titles in search results",
            "Source tags",
            "Who / where / when",
            "Language detection",
        ]:
            assert loc.get(k), (f.stem, k)


def test_the_bare_verdict_words_are_not_keys_in_any_locale():
    for f in LOCALES:
        loc = _locale(f)
        for k in ("junk", "content", "unsure"):
            assert k not in loc, (f.stem, k, "a keyword with this text would be shown translated")


def test_the_walker_leaves_translate_no_alone_for_text_and_attributes():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "p.closest('[data-i18n-dyn],[translate=\"no\"]')" in function_body(js, "doText")
    assert "el.closest('[data-i18n-dyn],[translate=\"no\"]')" in function_body(js, "doAttrs")


def test_the_feed_marks_its_keywords_and_the_grading_terms_as_data():
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    feed = function_body(js, "loadAiActivity")
    assert '<span translate="no">${esc(x.term || x.domain || "")}</span>' in feed
    assert '<span class="pill" translate="no">${esc(x.term || "")}</span>' in feed
    assert '<span style="min-width:170px" translate="no">${esc(a.term)}</span>' in function_body(
        js, "_mbRenderAnchors"
    )


def _is_counter(v: ast.expr | None) -> bool:
    if isinstance(v, ast.Constant):
        return isinstance(v.value, int) and not isinstance(v.value, bool)
    if isinstance(v, ast.Dict):
        return all(_is_counter(x) for x in v.values)
    return False


def _dict_keys_with(path: Path, anchor: str) -> set[str]:
    """String keys of every ZEROED counter dict in a module that names ``anchor`` -- the totals a sweep job starts
    from. Every value is a number literal (or a dict of them: field_gated); a result record that merely mentions the
    counter carries other values and is not one."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and node.values and all(_is_counter(v) for v in node.values):
            ks = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if anchor in ks:
                out |= ks
    assert out, (path.name, anchor)
    return out


def _bump_keys(path: Path) -> set[str]:
    """The translation sweeps start from an empty totals dict and fill it through ``_bump(totals, "<key>")``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_bump"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }
    assert len(out) >= 8, out
    return out


def test_every_counter_the_sweeps_write_is_worded():
    ai = ROOT / "src" / "ai_layer"
    written = (
        _dict_keys_with(ai / "triage_job.py", "keywords_in")
        | _dict_keys_with(ai / "source_tags_job.py", "sources_in")
        | _dict_keys_with(ai / "perception_extract_job.py", "skipped_existing")
    )
    written |= _bump_keys(ai / "translation_sweep.py")
    # perception's defaults nest field_gated's own who/where/when, which are words of their own map
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    worded = _js_map_keys(js, "_AI_TOTALS_WORDS")
    assert written <= worded, sorted(written - worded)
    assert _js_map_keys(js, "_AI_FIELD_WORDS") == {"who", "where", "when"}


def test_every_stored_kind_is_worded():
    from src.ai_layer.activity import AI_KINDS

    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    assert set(AI_KINDS) == _js_map_keys(js, "_AI_KIND_WORDS")


def test_every_sweep_label_and_unit_is_a_key(tmp_path):
    from src.ai_layer.activity import recent_activity

    sweeps = recent_activity(directory=tmp_path)["sweeps"]
    assert len(sweeps) >= 6
    for f in LOCALES:
        loc = _locale(f)
        for s in sweeps:
            assert loc.get(s["label"]), (f.stem, s["label"])
            assert loc.get(s["unit"]), (f.stem, s["unit"])


def test_the_coordinator_note_is_worded_by_its_code_and_the_english_matches():
    from src.ai_layer.activity import _coordinator_view

    view = _coordinator_view()
    assert view["note_code"] == "lane-runs-members-directly"
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    assert f'const _AI_COORDINATOR_IDLE_NOTE = "{view["note"]}";' in js, (
        "the client's English drifted from the server's"
    )
    assert 'c.note_code === "lane-runs-members-directly"' in function_body(js, "_aiCoordinatorNote")
