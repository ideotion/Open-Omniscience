"""Row 289: the catalogue balance targets file is read with a state, and a bad one never breaks the coverage view.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``configs/catalog_targets.yml`` sets each region's floor and the concentration guards of Settings' coverage panel. Before
this row ``load_targets`` caught only OSError: an unparsable file raised ParserError and a list raised AttributeError out
of ``GET /api/database/coverage`` (and ``scripts/catalog_coverage_report.py``), ``min_sources: lots`` raised ValueError,
and an absent file read like "no target set". Now the read has a state, a bad value is refused per row with a token, and
the panel and the script say the state in one line.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parent.parent

CASES = {
    "absent": (None, {"state": "absent"}),
    "empty": ("", {"state": "empty"}),
    "comments only": ("# nothing\n", {"state": "empty"}),
    "no target": ("regions: {}\nconcentration: {}\n", {"state": "empty"}),
    "unparsable": ("regions: [\n", {"state": "unreadable", "error": "ParserError"}),
    "not a mapping": ("- a\n", {"state": "unreadable", "error": "not a mapping (list)"}),
    "bad utf-8": (b"regions:\n  Africa: \xff\n", {"state": "unreadable", "error": "UnicodeDecodeError"}),
    "only refused values": ("regions: {Africa: {min_sources: lots}}\nconcentration: {max_country_share_pct: 400}\n",
                            {"state": "unreadable", "error": "no usable target (2 refused)"}),
    "regions a list": ("regions: [1]\n", {"state": "unreadable", "error": "no usable target (1 refused)"}),
    "a misspelt key": ("regions: {Europe: {min_source: 5}}\n", {"state": "unreadable", "error": "no usable target (1 refused)"}),
}

UNREAD = [c for c, (_, want) in CASES.items() if want["state"] != "present"]


def _write(path: Path, body: str | bytes | None) -> Path:
    if isinstance(body, bytes):
        path.write_bytes(body)
    elif body is not None:
        path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize("case", list(CASES))
def test_the_targets_read_with_their_state_and_never_raise(tmp_path, case):
    from src.catalog.coverage import load_targets, regional_report

    body, want = CASES[case]
    targets = load_targets(_write(tmp_path / "catalog_targets.yml", body))
    assert targets["read"] == want
    assert targets["regions"] == {} and targets["concentration"] == {}
    assert str(tmp_path) not in json.dumps(targets)
    rep = regional_report({"fr": 3, "us": 9}, targets=targets, total_sources=20)
    assert rep["targets"] == want
    assert all(r["sources_met"] is None and r["countries_met"] is None for r in rep["regions"])
    assert rep["top_country"]["max_share_pct"] is None and rep["min_located_share_pct"] is None
    europe = next(r for r in rep["regions"] if r["region"] == "Europe")
    assert europe["sources"] == 3, "the actual counts stay; only the comparisons are withheld"


def test_the_shipped_targets_are_present():
    from src.catalog.coverage import load_targets

    targets = load_targets()
    assert targets["read"] == {"state": "present"} and targets["refused"] == []
    assert targets["regions"]["Africa"] == {"min_sources": 200, "min_countries": 50}
    assert targets["concentration"] == {"max_country_share_pct": 12, "min_located_share_pct": 70}


def test_a_bad_value_is_refused_by_row_and_the_good_ones_still_compare(tmp_path):
    from src.catalog.coverage import load_targets, regional_report

    path = _write(tmp_path / "t.yml", (
        "regions:\n"
        "  Europe: {min_sources: lots, min_countries: 2}\n"
        "  Africa: {min_sources: -1, min_countries: true}\n"
        "  Atlantis: {min_sources: 3}\n"
        "  Asia: 7\n"
        "  Oceania: {min_sources: 2.0, min_soruces: 9}\n"
        "concentration: {max_country_share_pct: 50, min_located_share_pct: '70', max_share: 3}\n"))
    targets = load_targets(path)
    assert targets["read"] == {"state": "present"}
    assert targets["regions"] == {"Europe": {"min_countries": 2}, "Oceania": {"min_sources": 2}}
    assert targets["concentration"] == {"max_country_share_pct": 50}
    assert targets["refused"] == [
        {"region": "Europe", "key": "min_sources", "refused": "not_a_whole_number"},
        {"region": "Africa", "key": "min_sources", "refused": "not_a_whole_number"},
        {"region": "Africa", "key": "min_countries", "refused": "not_a_whole_number"},
        {"region": "Atlantis", "key": None, "refused": "not_a_region"},
        {"region": "Asia", "key": None, "refused": "not_a_mapping"},
        {"region": "Oceania", "key": "min_soruces", "refused": "unknown_key"},
        {"region": None, "key": "max_share", "refused": "unknown_key"},
        {"region": None, "key": "min_located_share_pct", "refused": "not_a_percentage"},
    ]
    rep = regional_report({"fr": 3, "de": 1}, targets=targets, total_sources=4)
    europe = next(r for r in rep["regions"] if r["region"] == "Europe")
    assert europe["sources_met"] is None and europe["countries_met"] is True
    africa = next(r for r in rep["regions"] if r["region"] == "Africa")
    assert africa["sources_met"] is None, "a refused floor is never coerced to 0 and then met"
    assert len(rep["targets_refused"]) == 8


def test_a_hand_built_targets_dict_is_cleaned_the_same_way():
    from src.catalog.coverage import regional_report

    rep = regional_report({"fr": 3}, targets={"regions": {"Europe": {"min_sources": "lots"}}})
    assert rep["targets"] == {"state": "unreadable", "error": "no usable target (1 refused)"}
    rep = regional_report({"fr": 3}, targets={"regions": {"Europe": {"min_sources": 2}}})
    assert rep["targets"] == {"state": "present"} and rep["targets_refused"] == []
    rep = regional_report({"fr": 3}, targets={"regions": {}, "read": {"state": "present"}})
    assert rep["targets_refused"] == [], "a read block without a refused list never raises"


def test_the_targets_are_read_on_every_call_so_a_fixed_file_is_seen(tmp_path):
    from src.catalog.coverage import load_targets

    path = _write(tmp_path / "t.yml", "regions: [\n")
    assert load_targets(path)["read"]["state"] == "unreadable"
    path.write_text("regions: {Europe: {min_sources: 1}}\n", encoding="utf-8")
    assert load_targets(path)["read"] == {"state": "present"}


@pytest.fixture
def db(tmp_path):
    from src.database.models import Article, Base, Source

    eng = app_sqlite_engine(tmp_path / "coverage.db")  # row 285: the app's pragmas, never a bare engine
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__])
    with Session(eng) as s:
        s.add(Source(id=1, name="S1", domain="s1.example", country="FR", enabled=True, status="qualified"))
        s.commit()
        yield s
    eng.dispose()


@pytest.mark.parametrize("case", ["absent", "unparsable", "not a mapping", "only refused values", "a misspelt key"])
def test_the_coverage_route_answers_with_the_state_and_recomputes_after_its_own_ttl(db, tmp_path, monkeypatch, case):
    from src.api import database, served_cache
    from src.api.database import country_coverage
    from src.catalog import coverage

    body, want = CASES[case]
    path = _write(tmp_path / "catalog_targets.yml", body)
    monkeypatch.setattr(coverage, "_TARGETS_PATH", path)
    served_cache.invalidate("db:coverage")
    try:
        reg = country_coverage(db)["regional"]
        assert reg["targets"] == want
        assert next(r for r in reg["regions"] if r["region"] == "Europe")["sources"] == 1
        # A fixed file is not a database write, so the change probe cannot see it and a verified entry would only be
        # re-stamped. This entry carries its own TTL instead: once that ends, the next read starts a recompute even when
        # the probe still vouches for the payload.
        entry = served_cache._CACHE["db:coverage"]
        assert entry["ttl_s"] == database._CACHE_TTL_S
        kicked: list[str] = []
        monkeypatch.setattr(served_cache, "change_probe", lambda: 7)  # nothing written since: the probe vouches
        entry["probe"] = 7
        monkeypatch.setattr(served_cache, "_kick_background_refresh", lambda key, compute: kicked.append(key))
        entry["checked_at"] -= database._CACHE_TTL_S + 1
        country_coverage(db)
        assert kicked == ["db:coverage"]
        path.write_text("regions: {Europe: {min_sources: 1}}\n", encoding="utf-8")
        served_cache.invalidate("db:coverage")
        reg = country_coverage(db)["regional"]
        assert reg["targets"] == {"state": "present"}
        assert next(r for r in reg["regions"] if r["region"] == "Europe")["sources_met"] is True
        assert served_cache._CACHE["db:coverage"]["ttl_s"] is None, "a whole read keeps the route's usual cache"
    finally:
        served_cache.invalidate("db:coverage")


def _load_script():
    spec = importlib.util.spec_from_file_location("oo_catalog_coverage_report_r289",
                                                  ROOT / "scripts/catalog_coverage_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("case", ["absent", "empty", "unparsable"])
def test_the_script_names_the_state(tmp_path, case):
    from src.catalog.coverage import load_targets, regional_report

    body, want = CASES[case]
    reg = regional_report({"fr": 1}, targets=load_targets(_write(tmp_path / "t.yml", body)), total_sources=1)
    (line,) = _load_script().targets_lines(reg)
    assert line.startswith(f"Targets (configs/catalog_targets.yml): {want['state']}")
    assert line.endswith("so no region is compared with a floor")


def test_the_script_says_nothing_for_read_targets_and_lists_refusals():
    from src.catalog.coverage import regional_report

    script = _load_script()
    assert script.targets_lines(regional_report({"fr": 1}, targets={"regions": {"Europe": {"min_sources": 1}}})) == []
    lines = script.targets_lines(regional_report({"fr": 1}, targets={
        "regions": {"Europe": {"min_sources": 1}, "Asia": {"min_sources": "x"}}}))
    assert lines == ["Targets refused (1): Asia.min_sources not_a_whole_number"]


def test_the_panel_draws_the_state_line_in_every_language():
    from tests.js_source_helper import function_body

    js = (ROOT / "src/static/app-sources.js").read_text("utf-8")
    body = function_body(js, "covTargetsLine")
    keys = [ln.split('t("', 1)[1].rsplit('")', 1)[0] for ln in body.splitlines() if 'return t("' in ln]
    keys += [ln.split('tf("', 1)[1].split('", {', 1)[0] for ln in body.splitlines() if 'return tf("' in ln]
    assert len(set(keys)) == 4
    assert body.index("refused.length) return") < body.index('st === "unreadable"'), "every value refused is said as such"
    assert "covTargetsLine(reg, t, tf)" in function_body(js, "renderCoverageRegions")
    for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
        data = json.loads(loc.read_text("utf-8"))
        for key in keys:
            assert data.get(key), f"{key!r} has no {loc.name} text"
            if "{n}" in key:
                assert "{n}" in data[key], f"{loc.name} drops {{n}}"
