"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 201 (S08-02 S2, "the method on hover ×12"): the KPI panel's method hover read English in every language, because each
method was an English f-string with its figures welded in, which no locale key can match. A method (and a K13 block's
reason) is now a list of keyed FRAMES beside its English, and the English is BUILT from them.

What is pinned here, and why each is not a grep:
  * every template ``kpi.py`` can emit is a key in all twelve locales with the same placeholders -- scanned from the
    module's own AST, so a new ``_fr("...")`` with no key fails here, not in a browser walk; the words a ``tr`` var may
    carry, K8's status tally, every not-measurable reason, every measure's name and target and the snapshot caveat too;
  * no frame call hides its template behind a computed string the scan cannot read;
  * no frame is written as a dict literal the scan would not see (every frame goes through ``_fr``);
  * across snapshots over recorded files (K2 with samples, K5-K8, and the law, OSM and wiki records with unknown counts),
    every frame emitted is one the scan found, every hole has its data, and a ``tr`` var holds a number or one of the
    keyed words -- never a stray English phrase. (The English rebuilding from its frames is by construction; that it is
    the same English as before row 201 is what the existing tests/test_kpi*.py method assertions pin.)
The UI that renders the frames is proven in tests/kpi_panel_node_test.js.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.monitoring import kpi
from tests.locale_forms import load_locale

_ROOT = Path(__file__).resolve().parents[1]
_KPI = _ROOT / "src" / "monitoring" / "kpi.py"
_LOCALES = _ROOT / "src" / "static" / "locales"
_LANGS = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")
_HOLE = re.compile(r"\{(\w+)\}")


def _strs(node: ast.AST) -> list[str] | None:
    """The template strings a frame call's first argument can be, or None when it is not a literal the scan can read."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        a, b = _strs(node.body), _strs(node.orelse)
        return None if a is None or b is None else a + b
    return None


def _frame_calls() -> tuple[set[str], list[str]]:
    templates: set[str] = set()
    unreadable: list[str] = []
    src = _KPI.read_text("utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_fr" and node.args:
            found = _strs(node.args[0])
            if found is None:
                unreadable.append(ast.get_source_segment(src, node.args[0]) or "?")
            else:
                templates.update(found)
    return templates, unreadable


def _all_keys() -> set[str]:
    templates, _ = _frame_calls()
    keys = set(templates) | set(kpi.TR_WORDS)
    for table in kpi.FRAME_TABLES:
        for first, then in table.values():
            keys |= {first, then}
    for spec in kpi._SPECS:
        keys |= {spec["name"], spec["target"]} | ({spec["nm"]} if spec.get("nm") else set())
    keys.add(kpi.kpi_snapshot()["caveat"])
    return keys


@pytest.fixture(scope="module")
def locales() -> dict[str, dict[str, str]]:
    return {lang: load_locale(_LOCALES / f"{lang}.json") for lang in _LANGS}


def test_every_frame_call_names_its_template_as_a_literal():
    # The four table lookups, whose rows are scanned through kpi.FRAME_TABLES, and the not-measurable reasons, scanned
    # through kpi._SPECS; anything else computed would be a key the scan cannot see.
    _, unreadable = _frame_calls()
    assert sorted(unreadable) == sorted([
        "_K2_KINDS[key][1 if i else 0]", "pair[1 if unknown else 0]", "pair[1 if unknown else 0]",
        "_K8_TALLY.get(st, _K8_TALLY[None])[1 if i else 0]", 'spec["nm"]',
    ]), unreadable


def test_no_frame_is_written_as_a_dict_literal():
    tree = ast.parse(_KPI.read_text("utf-8"))
    literal = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Dict)
               and any(isinstance(k, ast.Constant) and k.value == "t" for k in node.keys)]
    # The one dict with a "t" key is _fr's own return value.
    assert len(literal) == 1, f"a frame written by hand at line(s) {literal}: build it with _fr so the scan sees it"


def test_every_template_name_target_and_word_is_keyed_in_every_language(locales):
    keys = _all_keys()
    assert len(keys) > 60, "the scan found too little: was _fr renamed?"
    for key in sorted(keys):
        holes = sorted(_HOLE.findall(key))
        for lang, table in locales.items():
            assert key in table, f"not keyed in {lang}.json: {key!r}"
            assert sorted(_HOLE.findall(table[key])) == holes, f"{lang} changes the placeholders of {key!r}"
        # Arabic and Chinese share no script with English, so an identical value is an untranslated one.
        if re.search(r"[A-Za-z]{4,}", _HOLE.sub("", key)):
            for lang in ("ar", "zh"):
                assert locales[lang][key] != key or key == "OpenStreetMap", f"{lang} left English: {key!r}"


def _frames_in(obj, out: list[tuple[str, list[dict]]], key: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("_i18n") and isinstance(v, list):
                out.append((k[: -len("_i18n")], v))
                assert obj.get(k[: -len("_i18n")]) == kpi.frames_text(v), f"{k}: the English drifted from its frames"
            else:
                _frames_in(v, out, k)
    elif isinstance(obj, list):
        for v in obj:
            _frames_in(v, out, key)


def test_every_emitted_frame_is_scanned_and_rebuilds_its_english(tmp_path, monkeypatch):
    """Snapshots over recorded files: what reaches the UI is only scanned keys."""
    from src.monitoring import latency

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    scanned = _all_keys()
    seen: list[tuple[str, list[dict]]] = []
    _frames_in(kpi.kpi_snapshot(), seen)
    # A recorded keyword run, date run, source audit, law, OSM (with unknowns) and wiki (with unknowns) record.
    kpi.record_translation_coverage({"translation_coverage": {"pct": 12.5, "top_n": 200, "in_a_ring": 25, "rings_total": 9}})
    kpi.record_keyword_generic_terms({"generic_terms": {"candidate_terms": 42, "top_per_language": 20, "by_language": {"en": []}}})
    kpi.record_date_coverage({"corpus": {"scanned": 1500, "articles_total": 9000, "articles_with_extracted_dates": 774,
                                         "coverage_pct": 51.6, "articles_with_datelike_text_but_no_extraction": 410}},
                             {"scan": kpi.DATES_STANDARD_SCAN})
    kpi.record_source_audit_status({"sources_audited": 40, "min_articles": 5, "status_counts": [
        {"status": "healthy", "n": 31}, {"status": "watch", "n": 5}, {"status": "degraded", "n": 3},
        {"status": "failing", "n": 1}]}, allowlisted=2)
    kpi.record_law_coverage({"documents": 12, "baselined": 10, "jurisdictions": [], "floor": {}})
    kpi.record_osm_lane([{"status": "complete", "diffs_recorded": None, "gaps_total": None}])
    kpi.record_wiki_coverage([{"has_run": True, "pages_seen": None, "full_text": {"hot_pages_with_text": 3}}], True)
    _frames_in(kpi.kpi_snapshot(), seen)
    # K2 with samples: the worst route, its slowest call before an unlock finished, and the split by kind.
    monkeypatch.setattr(latency, "summary", lambda: {
        "snappy_bar": {"bar_ms": 500.0, "breaching": 2, "interactive_routes": 9, "breaching_low_n": 1, "min_n": 20,
                       "breaching_first_call_only": 1, "breaching_single_call": 1},
        "routes": [{"route": "GET /api/articles", "p95_ms": 900.0, "window_n": 3, "snappy": "low-n",
                    "slowest": {"ms": 1200.0, "status": 200, "started_after_unlock_s": -2.0, "ended_at": "2026-11-20"}}],
        "unlock": {"count": 1}})
    _frames_in(kpi.kpi_snapshot(), seen)
    k2 = [t for field, frames in seen for t in (fr["t"] for fr in frames) if "interactive routes are over the bar" in t]
    assert k2, "the K2 split was never emitted, so this test did not reach it"
    assert {field for field, _ in seen} >= {"method", "reason"}
    for field, frames in seen:
        for fr in frames:
            assert fr["t"] in scanned, f"{field}: an emitted template the scan did not find: {fr['t']!r}"
            assert set(_HOLE.findall(fr["t"])) <= set(fr["v"]), f"a hole with no data: {fr!r}"
            for name in fr.get("tr", []):
                value = fr["v"][name]
                assert value in kpi.TR_WORDS or re.fullmatch(r"\d+", value), f"a tr var carries {value!r}"
