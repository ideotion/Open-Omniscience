"""Row 273: a world-events catalogue that was not read never reads as "every floor country missing".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The curated catalogue (``configs/world_events.yml``) is read once, with a state: ``present``, ``absent`` (no file),
``empty`` (read, holds no events) or ``unreadable`` (the error named by its class, never the path). Before this row an
absent or empty file was read as a catalogue with no events, so the elections floor said 0 covered and every floor
country "missing", and an unparsable one raised out of every caller. Now the floor's counts, the tier report and K13
give ``None`` beside the state, the events endpoints carry it, the Agenda says it in one line, and the read-back
script prints it. Absent, empty and unreadable stay three different facts.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "elections_readback.py"

#: Each case: the file's content (None = no file) and the state it must read as.
CASES = {
    "absent": (None, {"state": "absent"}),
    "empty": ("", {"state": "empty"}),
    "comments only": ("# nothing yet\n", {"state": "empty"}),
    "no events": ("events: []\n", {"state": "empty"}),
    "unparsable": ("events: [\n  - {title: a\n", {"state": "unreadable", "error": "ParserError"}),
    "not a mapping": ("- a\n- b\n", {"state": "unreadable", "error": "not a mapping (list)"}),
    "events not a list": ("events: 3\n", {"state": "unreadable", "error": "events is not a list (int)"}),
    "no usable row": ("events: [1, x, {title: t}]\n", {"state": "unreadable", "error": "no usable event row (3 refused)"}),
    "bad utf-8": (b"events:\n  - title: \xff\xfe\n", {"state": "unreadable", "error": "UnicodeDecodeError"}),
}


def _script():
    spec = importlib.util.spec_from_file_location("oo_elections_readback_r273", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


@pytest.fixture()
def catalogue(tmp_path, monkeypatch):
    """Point the curated catalogue (and the snapshot, absent) at tmp_path; the test writes the file through the
    returned function."""
    from src.civic import calendar_report
    from src.events import catalog

    monkeypatch.setattr(calendar_report, "SNAPSHOT_PATH", tmp_path / "absent-snapshot.json")
    path = tmp_path / "world_events.yml"
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)

    def write(body: str | bytes | None) -> Path:
        if isinstance(body, bytes):
            path.write_bytes(body)
        elif body is not None:
            path.write_text(body, encoding="utf-8")
        catalog.load_events.cache_clear()
        return path

    catalog.load_events.cache_clear()
    try:
        yield write
    finally:
        catalog.load_events.cache_clear()


def _list_events() -> dict:
    from src.api.events import list_events

    return list_events(category=None, calendar=None, country=None, tag=None, dedup=True)


# --- the read state ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", list(CASES))
def test_the_catalogue_reads_with_its_state_and_never_raises(catalogue, case, tmp_path):
    from src.events import catalog

    body, want = CASES[case]
    catalogue(body)
    assert catalog.catalogue_state() == want
    assert catalog.load_events() == [] and catalog.load_curated_events() == []
    _events, _snap, cat = catalog.layered_read()
    assert cat == want
    # the error is named by its class (or a shape fact), never with the path or the parser's position text
    assert str(tmp_path) not in json.dumps(cat) and "line" not in json.dumps(cat)


def test_the_shipped_catalogue_is_present():
    from src.events import catalog

    catalog.load_events.cache_clear()
    assert catalog.catalogue_state() == {"state": "present"}
    assert catalog.layered_read()[2] == {"state": "present"}
    assert len(catalog.layered_events()) == 2, "layered_events keeps its (events, snapshot) shape for its callers"


def test_a_state_copy_cannot_change_the_cached_read(catalogue):
    from src.events import catalog

    catalogue(None)
    catalog.catalogue_state()["state"] = "present"
    catalog.layered_read()[2]["state"] = "present"
    assert catalog.catalogue_state() == {"state": "absent"} and catalog.layered_read()[2] == {"state": "absent"}


# --- the floor, the tier report and K13 ----------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["absent", "empty", "unparsable", "no usable row"])
def test_the_floor_gives_none_beside_the_state_never_zero_or_missing(catalogue, case):
    from src.api.diagnostics.system import elections_coverage_floor
    from src.civic.coverage_floor import floor_coverage, load_floor

    body, want = CASES[case]
    catalogue(body)
    n = len(load_floor()["countries"])
    for doc in (elections_coverage_floor(), floor_coverage()):
        assert doc["catalogue"] == want
        assert doc["floor_countries"] == n, "the denominator is known whatever the catalogue"
        for key in ("covered", "only_passed_projection", "present_but_dateless", "missing"):
            assert doc[key] is None and doc[f"{key}_n"] is None, key
        assert doc["covered_outside_floor"] is None
    rep = elections_coverage_floor()["tier_report"]
    assert rep == {"floor_countries": n, "counts": None, "countries": None, "catalogue": want}


def test_the_present_catalogue_still_counts(catalogue):
    from src.api.diagnostics.system import elections_coverage_floor

    catalogue("events:\n  - {title: Vote, official_url: 'https://example.invalid/v', category: civic,"
              " country: FR, tags: [election], month: 5, day: 1}\n")
    doc = elections_coverage_floor()
    assert doc["catalogue"] == {"state": "present"}
    assert isinstance(doc["missing_n"], int) and doc["missing_n"] == doc["floor_countries"] - doc["covered_n"] - \
        doc["only_passed_projection_n"] - doc["present_but_dateless_n"]
    assert isinstance(doc["tier_report"]["counts"], dict)


@pytest.mark.parametrize("case", ["absent", "empty", "unparsable"])
def test_k13_gives_none_and_says_the_catalogue_was_not_read(catalogue, case):
    from src.monitoring.kpi import _elections_block

    body, want = CASES[case]
    catalogue(body)
    block = _elections_block()
    assert block["catalogue_state"] == want["state"]
    for key in ("covered", "only_passed_projection", "present_but_dateless", "missing"):
        assert block[key] is None, key
    assert f"(state: {want['state']})" in block["catalogue_reason"]
    (frame,) = block["catalogue_reason_i18n"]
    assert frame["v"] == {"state": want["state"]}


def test_k13_has_no_catalogue_reason_when_the_catalogue_is_present():
    from src.events import catalog
    from src.monitoring.kpi import _elections_block

    catalog.load_events.cache_clear()
    block = _elections_block()
    assert block["catalogue_state"] == "present" and "catalogue_reason" not in block


def test_the_k13_reason_is_a_locale_key_in_every_language():
    from src.monitoring import kpi

    m = re.search(r'_fr\("(the curated events catalogue[^"]*)"\s*"([^"]*)"', (ROOT / "src/monitoring/kpi.py").read_text("utf-8"))
    assert m, "the K13 catalogue reason template moved"
    key = m.group(1) + m.group(2)
    assert kpi  # the module the template lives in
    for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
        data = json.loads(loc.read_text("utf-8"))
        assert key in data and "{state}" in data[key], loc.name


# --- the events endpoints and the Agenda ----------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["absent", "empty", "unparsable"])
def test_the_events_endpoints_carry_the_state_and_do_not_crash(catalogue, case):
    from src.events import catalog

    body, want = CASES[case]
    catalogue(body)
    ev = _list_events()
    assert ev["catalogue"] == want and ev["events"] == [] and ev["count"] == 0
    assert catalog.facets()["catalogue"] == want


def test_the_agenda_says_the_state_in_one_line_in_every_language():
    from tests.js_source_helper import function_body

    js = (ROOT / "src/static/app-agenda.js").read_text("utf-8")
    assert "AG.catalogue = ev.catalogue" in js and "agCatalogueLine(AG.catalogue)" in js
    assert "agCatalogueLine(floor.catalogue)" in js
    lines = re.findall(r'return T\("([^"]+)"\);', function_body(js, "agCatalogueLine"))
    assert len(lines) == 3 and len(set(lines)) == 3, "absent, empty and unreadable are said apart"
    for line in lines:
        assert len(line) <= 90, "one short line"
        for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
            assert json.loads(loc.read_text("utf-8")).get(line), f"{line!r} has no {loc.name} text"


# --- the read-back ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("case", "want"), [
    ("absent", "catalogue: absent: no curated events catalogue on that machine"),
    ("empty", "catalogue: empty: the curated events catalogue was read and holds no events"),
    ("unparsable", "catalogue: unreadable (ParserError): the curated events catalogue could not be read"),
])
def test_the_readback_prints_the_catalogue_state_and_no_count(catalogue, tmp_path, case, want):
    from src.api.diagnostics.system import elections_coverage_floor

    catalogue(CASES[case][0])
    out = tmp_path / "oo-field-20261121-1400-p8000-elections-floor.json"
    out.write_text(json.dumps(elections_coverage_floor()), encoding="utf-8")
    lines = R.report(R.load(out))
    text = "\n".join(lines)
    assert lines[0].startswith(want), text
    assert "states: not counted (see the catalogue line)" in text
    assert "tier report: not counted (see the catalogue line)" in text
    assert not re.search(r"\bmissing\b|not a count", text), "a count that was not taken was printed"
    assert str(tmp_path) not in text


def test_the_bundle_member_holds_the_state(catalogue):
    from src.api.diagnostics.bundle import _elections_floor_member

    catalogue("")
    doc = _elections_floor_member()
    assert doc["catalogue"] == {"state": "empty"} and doc["missing_n"] is None and "cut" not in doc


def test_a_file_from_before_row_273_still_prints_its_counts():
    doc = {"floor_countries": 2, "covered_n": 1, "only_passed_projection_n": 0, "present_but_dateless_n": 0,
           "missing_n": 1, "covered_outside_floor": [], "tier_report": {"counts": {"scheduled": 1, "missing": 1}}}
    text = "\n".join(R.report(doc))
    assert "1 covered" in text and "1 missing" in text and "catalogue:" not in text
