"""Row 279: a language floor that was not read never reads as an empty floor.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``configs/language_countries.yml`` is the denominator of the elections floor, of the law coverage report and the OSM
picker's per-language suggestions. It is read once, with a state: ``present``, ``absent`` (no file), ``empty`` (read, no
usable country) or ``unreadable`` (the error named by its class, never the path). Before this row an absent or empty
file gave "0 floor countries, 0 missing", which reads as complete, and an unparsable one raised out of the elections
route, K13, the law report and the picker. Now each says the state and gives None for every floor figure.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CASES = {
    "absent": (None, {"state": "absent"}),
    "empty": ("", {"state": "empty"}),
    "comments only": ("# nothing\n", {"state": "empty"}),
    "no usable row": ("languages: {en: {countries: 3}}\n", {"state": "empty"}),
    "only invalid codes": ("languages: {en: {countries: [{cc: zz, basis: official}]}}\n",
                           {"state": "unreadable", "error": "no usable country row (1 refused)"}),
    "unparsable": ("languages: [\n", {"state": "unreadable", "error": "ParserError"}),
    "not a mapping": ("- a\n", {"state": "unreadable", "error": "not a mapping (list)"}),
    "languages not a mapping": ("languages: 4\n", {"state": "unreadable", "error": "languages is not a mapping (int)"}),
    "bad utf-8": (b"languages:\n  en: \xff\n", {"state": "unreadable", "error": "UnicodeDecodeError"}),
}

UNREAD = ["absent", "empty", "unparsable"]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def floor_file(tmp_path, monkeypatch):
    """Point the floor at tmp_path (and the snapshot at an absent file); the test writes it through the returned
    function."""
    from src.civic import calendar_report
    from src.civic import coverage_floor as cf
    from src.events import catalog

    monkeypatch.setattr(calendar_report, "SNAPSHOT_PATH", tmp_path / "absent-snapshot.json")
    path = tmp_path / "language_countries.yml"
    monkeypatch.setattr(cf, "FLOOR_PATH", path)

    def write(body: str | bytes | None) -> Path:
        if isinstance(body, bytes):
            path.write_bytes(body)
        elif body is not None:
            path.write_text(body, encoding="utf-8")
        cf.load_floor.cache_clear()
        catalog.load_events.cache_clear()
        return path

    cf.load_floor.cache_clear()
    try:
        yield write
    finally:
        cf.load_floor.cache_clear()
        catalog.load_events.cache_clear()


@pytest.mark.parametrize("case", list(CASES))
def test_the_floor_reads_with_its_state_and_never_raises(floor_file, tmp_path, case):
    from src.civic import coverage_floor as cf

    body, want = CASES[case]
    floor_file(body)
    floor = cf.load_floor()
    assert cf.floor_state() == want and floor["read"] == want
    assert floor["countries"] == [] and cf.floor_countries() == set()
    assert str(tmp_path) not in json.dumps(want) and "line" not in json.dumps(want)


def test_the_shipped_floor_is_present():
    from src.civic import coverage_floor as cf

    cf.load_floor.cache_clear()
    assert cf.floor_state() == {"state": "present"} and len(cf.load_floor()["countries"]) > 100


def test_clearing_load_floor_clears_the_file_read_too(floor_file):
    from src.civic import coverage_floor as cf

    path = floor_file(None)
    assert cf.floor_state()["state"] == "absent"
    path.write_text("languages: {en: {countries: [{cc: gb, basis: official}]}}\n", encoding="utf-8")
    cf.load_floor.cache_clear()
    assert cf.floor_state() == {"state": "present"} and cf.load_floor()["countries"] == ["gb"]


def test_a_hand_built_floor_without_a_read_block_is_judged_by_its_countries():
    from src.civic.coverage_floor import floor_state

    assert floor_state({"countries": ["fr"]}) == {"state": "present"}
    assert floor_state({"countries": []}) == {"state": "empty"}


@pytest.mark.parametrize("case", UNREAD)
def test_the_elections_floor_gives_none_with_the_state_never_zero(floor_file, case):
    from src.api.diagnostics.system import elections_coverage_floor
    from src.civic.coverage_floor import floor_coverage

    body, want = CASES[case]
    floor_file(body)
    for doc in (elections_coverage_floor(), floor_coverage()):
        assert doc["floor"] == want and doc["floor_countries"] is None
        for key in ("covered", "only_passed_projection", "present_but_dateless", "missing"):
            assert doc[key] is None and doc[f"{key}_n"] is None, key
    rep = elections_coverage_floor()["tier_report"]
    assert rep["floor_countries"] is None and rep["counts"] is None and rep["countries"] is None
    assert rep["floor"] == want


@pytest.mark.parametrize("case", UNREAD)
def test_k13_says_the_floor_was_not_read(floor_file, case):
    from src.monitoring.kpi import _elections_block

    body, want = CASES[case]
    floor_file(body)
    block = _elections_block()
    assert block["floor_state"] == want["state"] and block["floor_countries"] is None and block["missing"] is None
    assert f"(state: {want['state']})" in block["floor_reason"]
    (frame,) = block["floor_reason_i18n"]
    assert frame["v"] == {"state": want["state"]}


def test_k13_has_no_floor_reason_when_the_floor_is_present():
    from src.civic import coverage_floor as cf
    from src.monitoring.kpi import _elections_block

    cf.load_floor.cache_clear()
    block = _elections_block()
    assert block["floor_state"] == "present" and "floor_reason" not in block


@pytest.mark.parametrize("case", UNREAD)
def test_the_law_reports_name_the_floor_state(floor_file, case):
    from src.law.coverage import floor_report, world_report

    body, want = CASES[case]
    floor_file(body)
    rep = floor_report([], {})
    assert rep["state"] == "unchecked" and rep["floor"] == want and rep["countries"] is None
    world = world_report([], {})
    assert world["floor"] == want and "floor_note" in world
    assert world["floor_countries_excluded"] is None, "nothing was set aside: unknown, never 0"
    readback = _load("oo_law_coverage_readback_r279", "scripts/law_coverage_readback.py")
    floor_text = "\n".join(readback.floor_lines(rep))
    assert floor_text.startswith(f"floor: {want['state']}: ") and "so no floor country was counted" in floor_text
    assert "no country listed" not in floor_text and " 0 " not in floor_text
    world_text = "\n".join(readback.world_lines(world))
    assert f"the floor was not read ({want['state']}: " in world_text and "every country is listed here" in world_text
    assert readback.json_floor({"floor": rep})["floor_read"].startswith(want["state"])


def test_the_law_reports_say_present_for_the_shipped_floor():
    from src.civic import coverage_floor as cf
    from src.law.coverage import floor_report, world_report

    cf.load_floor.cache_clear()
    assert floor_report([], {})["floor"] == {"state": "present"}
    assert world_report([], {})["floor"] == {"state": "present"}


@pytest.mark.parametrize("case", UNREAD)
def test_the_osm_picker_carries_the_state_and_does_not_crash(floor_file, case):
    from src.osm.picker import picker_state

    body, want = CASES[case]
    floor_file(body)
    state = picker_state("en")
    assert state["suggested"] == [] and state["suggested_floor"] == want


def test_the_picker_and_the_agenda_say_the_state_in_one_line_in_every_language():
    from tests.js_source_helper import function_body

    lines = {}
    for rel, name, call in (("src/static/app-map.js", "osmFloorLine", "osmFloorLine(p.suggested_floor, t)"),
                            ("src/static/app-agenda.js", "agFloorLine", "agFloorLine(floor.floor, T)")):
        js = (ROOT / rel).read_text("utf-8")
        assert call in js, rel
        lines[name] = [ln.split('t("', 1)[1].rsplit('")', 1)[0] for ln in function_body(js, name).splitlines()
                       if 'return t("' in ln]
    assert lines["osmFloorLine"] == lines["agFloorLine"] and len(set(lines["osmFloorLine"])) == 3
    for line in lines["osmFloorLine"]:
        for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
            assert json.loads(loc.read_text("utf-8")).get(line), f"{line!r} has no {loc.name} text"


def test_the_task_manager_draws_the_k13_floor_reason():
    from tests.js_source_helper import function_body

    body = function_body((ROOT / "src/static/app-library.js").read_text("utf-8"), "_kpiBlockHtml")
    assert "kpiFramesText(b.floor_reason_i18n, b.floor_reason, h)" in body and "floorReason ?" in body


@pytest.mark.parametrize("case", UNREAD)
def test_the_readback_and_the_coverage_report_say_the_floor_was_not_read(floor_file, tmp_path, case):
    from src.api.diagnostics.system import elections_coverage_floor

    body, want = CASES[case]
    floor_file(body)
    readback = _load("oo_elections_readback_r279", "scripts/elections_readback.py")
    out = tmp_path / "oo-field-x-elections-floor.json"
    out.write_text(json.dumps(elections_coverage_floor()), encoding="utf-8")
    text = "\n".join(readback.report(readback.load(out)))
    assert f"floor: {want['state']}" in text and "so no floor figure was counted" in text
    assert "tier report: not counted (see the floor line)" in text
    assert "0 countries" not in text and " missing" not in text
    report = _load("oo_elections_coverage_report_r279", "scripts/elections_coverage_report.py").build_report(date.today())
    assert f"- Language floor (configs/language_countries.yml): {want['state']}" in report
    assert "- Floor:" not in report and "| State |" not in report


def test_the_coverage_report_keeps_the_catalogue_line_when_neither_was_read(floor_file, monkeypatch, tmp_path):
    from src.events import catalog

    floor_file(None)
    monkeypatch.setattr(catalog, "CATALOG_PATH", tmp_path / "no-catalogue.yml")
    catalog.load_events.cache_clear()
    report = _load("oo_elections_coverage_report_r279b", "scripts/elections_coverage_report.py").build_report(date.today())
    assert "- Language floor (configs/language_countries.yml): absent" in report
    assert "- Curated catalogue: absent." in report


def test_a_file_of_only_refused_rows_is_not_said_to_list_no_country(floor_file):
    from src.civic import coverage_floor as cf

    floor_file("languages: {en: {countries: [{cc: zz, basis: official}, {cc: gb, basis: maybe}]}}\n")
    assert cf.floor_state() == {"state": "unreadable", "error": "no usable country row (2 refused)"}
    assert len(cf.load_floor()["invalid"]) == 2
