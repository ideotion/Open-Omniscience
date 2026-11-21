"""Row 267 (0.6 gate row C): the law coverage report the Field data button saves, and the script that reads it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The file is ``/api/diagnostics/law-coverage`` in its export envelope, the Diagnostics zip's ``law-coverage.json``. The script must
print every floor country with its state, the twelve-language tally and zh on its own line; never turn an absent figure into a
0; and print codes, states, counts and dates only: no source address, host, title or document.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from src.civic.coverage_floor import load_floor

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "law_coverage_readback.py"
PART = 200 * 1000  # the Field data button's piece size (app-diagnostics.js FIELD_PART_BYTES)


def _script():
    spec = importlib.util.spec_from_file_location("oo_law_coverage_readback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


@pytest.fixture(scope="module")
def route_bytes() -> bytes:
    """The route's answer on this test install: the shipped catalogue and the 140-country floor."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1") as client:
        r = client.get("/api/diagnostics/law-coverage?download=1")
    assert r.status_code == 200
    return r.content


def _write(tmp_path: Path, data: bytes, name: str = "oo-field-20261121-1600-p8000-law-coverage.json") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _reasons_only() -> dict:
    """A report with reasons and no figures, built by the report's OWN functions on their unread branches: the floor file
    could not be read (an empty floor), the catalogue could not be read, the enumeration not looked up. No world block and no
    document count: those are always figures, so they are absent here and must say so."""
    from src.law.coverage import floor_report

    floor = floor_report([], None, {"countries": [], "languages": {}}, reason="the law catalogue could not be parsed")
    return {
        "kind": "law-coverage",
        "data": {
            "catalog": {"readable": False, "error": "the law catalogue could not be parsed"},
            "floor": floor,
            "enumeration": {"state": "unchecked", "reason": "the law catalogue could not be parsed"},
        },
    }


def test_the_file_fits_one_piece_and_carries_no_document_or_address_the_readback_would_print(route_bytes, tmp_path):
    assert len(route_bytes) < PART, f"the 140-country report should fit one piece ({len(route_bytes):,} bytes)"
    text = "\n".join(R.report(R.load(_write(tmp_path, route_bytes))))
    for leak in ("http", "/", "@", ".org", ".gov", ".int", "europa"):
        assert leak not in text.replace("n/a", ""), f"{leak!r} reached the read-back"
    assert "not in the report's own words" not in text, "every value the report writes is printed"


def test_every_floor_country_is_printed_once_with_its_state_and_the_twelve_language_tally(route_bytes, tmp_path):
    doc = R.load(_write(tmp_path, route_bytes))
    lines = R.report(doc)
    text = "\n".join(lines)
    floor = load_floor()
    assert f"floor: {len(floor['countries'])} countries" in text
    state_lines = [ln for ln in lines if re.match(r"  (tracked|verified but not yet tracked|unverified|no eligible source): ", ln)]
    assert len(state_lines) == 4
    printed = [cc for ln in state_lines if "(" in ln for cc in ln.split("(", 1)[1].rstrip(")").split(", ")]
    assert sorted(printed) == sorted(floor["countries"]), "every floor country once, never dropped, never twice"
    tally = [ln for ln in lines if re.match(r"    [a-z]{2}: ", ln)]
    assert {ln.split(":")[0].strip() for ln in tally} == set(floor["languages"]), "one line per language of the floor"
    assert re.search(r"  zh \(its own line\): floor countries tracked \d+.*; named by the seed row beyond the floor: hk ", text)
    assert "order within a state: by code (no population table has been placed (an operator step))" in text
    assert re.search(r"many-country sources under int: \d+ listed, \d+ verified", text)


def test_a_report_with_only_reasons_prints_every_reason_and_no_figure(tmp_path):
    """Row 267's fixture with reasons and no figures: nothing in, nothing out but the reasons."""
    text = "\n".join(R.report(R.load(_write(tmp_path, json.dumps(_reasons_only()).encode()))))
    assert "catalogue: could not be read (the law catalogue could not be parsed)" in text
    # row 279: the floor's read state is named rather than "no country listed"
    assert ("floor: empty: the language-to-country list was read and lists no country, so no floor country was counted, "
            "floor file undated (its verification is not stated)") in text
    assert "  not checked: the floor file (language_countries.yml) is absent, unreadable or lists no country" in text
    assert "off the floor (world): absent from this file" in text
    assert "official counts in the catalogue: not read: the law catalogue could not be parsed" in text
    assert "documents tracked: not recorded in this file" in text
    figures = [ln for ln in text.splitlines() if re.search(r"\d", ln)]
    assert figures == [], f"a figure was printed for a report that holds none: {figures}"


def test_an_unreadable_catalogue_reads_not_looked_up_never_the_zeros_the_report_writes(tmp_path, monkeypatch):
    """The real route with the catalogue unreadable: the tracked side is still measured, every other state was never looked up."""
    from fastapi.testclient import TestClient

    import src.law.catalog as catalog
    from src.api.main import app

    def _unreadable():
        raise catalog.LawCatalogUnreadable("the law catalogue could not be parsed")

    monkeypatch.setattr(catalog, "load_legal_catalog", _unreadable)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = client.get("/api/diagnostics/law-coverage?download=1").content
    lines = R.report(R.load(_write(tmp_path, body)))
    text = "\n".join(lines)
    assert re.search(r"  tracked: \d+", text) and re.search(r"  unchecked \(the catalogue could not be read\): \d+", text)
    assert "  verified but not yet tracked, unverified, no eligible source: not looked up (" in text
    tally = [ln for ln in lines if re.match(r"    [a-z]{2}: ", ln)]
    assert tally and all("not looked up" in ln and "unverified 0" not in ln and "no eligible source 0" not in ln for ln in tally)
    assert "no eligible source, research to do" not in text and "no eligible source 0" not in text
    assert "official counts in the catalogue: not read: " in text


def test_a_state_list_or_tally_the_file_lacks_says_so_never_0():
    floor = {"state": "checked", "countries": 2, "as_of": "2026-01-01", "verification_status": "drafted",
             "by_state": {"tracked": ["fr"]}, "languages": [{"language": "fr", "official": ["fr"], "states": {"tracked": 1}}],
             "order": {"by": "population", "source": "UN WPP 2024", "as_of": "2024-07-11", "missing": ["xk"]}}
    text = "\n".join(R.floor_lines(floor))
    assert "  tracked: 1 (fr)" in text and "  unverified: not listed in this file" in text
    assert "    fr: official 1 · tracked 1 · documents not recorded" in text
    assert "order within a state: by population reached, from UN WPP 2024 dated 2024-07-11; not in the table, so listed by code after the rest: xk" in text
    assert "zh: not in this file" in text and "many-country sources: not recorded in this file" in text


def test_a_piece_set_is_joined_and_a_missing_piece_is_named_never_guessed(route_bytes, tmp_path):
    cut = len(route_bytes) // 2
    p1 = _write(tmp_path, route_bytes[:cut], "oo-field-x-law-coverage-part-001-of-002.json")
    p2 = _write(tmp_path, route_bytes[cut:], "oo-field-x-law-coverage-part-002-of-002.json")
    assert R.load(p2)["floor"]["state"] == "checked"
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)


def test_the_report_is_read_out_of_a_diagnostics_zip_and_another_export_is_refused(route_bytes, tmp_path):
    z = tmp_path / "oo-diagnostics.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("law-coverage.json", route_bytes)
    assert "floor: " in "\n".join(R.report(R.load(z)))
    other = _write(tmp_path, json.dumps({"kind": "law-ingest", "data": {}}).encode(), "other.json")
    with pytest.raises(ValueError, match="another kind"):
        R.load(other)


def test_malformed_shapes_are_said_never_a_crash_and_free_text_is_not_printed():
    doc = {"documents": "3", "catalog": [], "floor": {"state": "checked", "countries": True, "by_state": {"tracked": ["../x", "fr"]},
           "languages": ["x", {"language": "https://x.org", "states": "y"}], "zh_beyond_floor": {"hk": "nope"},
           "many_country_sources": {"int": {"treaties.un.org": True, "a": "yes"}}, "unplaced_documents": {"tl": "6"},
           "non_law_documents": {"see https://x.org": 1}, "verification_status": "see https://x.org/a?b=c",
           "order": {"by": "population", "source": "data.worldbank.org", "as_of": "2024-07-11"}},
           "world": "x", "enumeration": []}
    text = "\n".join(R.report(doc))
    assert "x.org" not in text and "treaties.un.org" not in text and "../x" not in text and "worldbank" not in text
    assert "documents tracked: not recorded in this file" in text and "floor: country count not recorded" in text
    assert "  tracked: 2 (?, fr)" in text and "    ?: no country listed · states not recorded" in text
    assert "hk ?" in text and "many-country sources under int: 2 listed, 1 verified" in text
    assert "documents that state no country: tl —" in text
    assert R._code("us-ca") == "us-ca", "a subdivision code is printed as written, not as ?"


def test_the_script_runs_stdlib_only_and_its_json_carries_no_host(route_bytes, tmp_path):
    f = _write(tmp_path, route_bytes)
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0].startswith("read at ") and "floor: " in out.stdout
    js = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f), "--json"], capture_output=True, text=True, timeout=60, check=False)
    assert js.returncode == 0 and "by_state" in js.stdout
    for leak in ("many_country_sources", "treaties.un.org", "configs/", "method", "caveat", "http"):
        assert leak not in js.stdout, f"{leak!r} reached --json"
    bad = _write(tmp_path, b"not json", "bad.json")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(bad)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 2 and "not a JSON file" in out.stderr
