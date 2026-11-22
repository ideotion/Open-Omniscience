"""Row 319: an unread floor file no longer hides an unread law catalogue.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``floor_report`` carried ONE ``reason``. When the catalogue could not be read it held the catalogue's error, but a floor file
that listed no country replaced it with its own sentence, so the report, the read-back and the Living sources panel lost the
catalogue's error whenever both failed. The report now keeps it beside the floor's read state in ``catalog_reason`` (null when
the catalogue was read), the read-back prints it as its own line, and the panel says it under the floor's sentence
(``tests/living_sources_node_test.js``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from src.law.coverage import floor_report

ROOT = Path(__file__).resolve().parent.parent
CAT = "the law catalogue legal_sources.yml could not be read (YAMLError)"
EMPTY = {"countries": [], "languages": {}, "read": {"state": "absent"}}
ONE = {
    "as_of": "2026-01-01",
    "verification_status": "drafted",
    "invalid": [],
    "contested": [],
    "countries": ["fr"],
    "languages": {
        "fr": {"name": "fr", "source": "t", "countries": [{"cc": "fr", "basis": "official"}]}
    },
}


def _readback():
    spec = importlib.util.spec_from_file_location(
        "oo_law_coverage_readback_319", ROOT / "scripts" / "law_coverage_readback.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_both_unread_keeps_both_reasons():
    rep = floor_report([], None, EMPTY, reason=CAT)
    assert rep["floor"]["state"] == "absent" and rep["state"] == "unchecked"
    assert rep["catalog_reason"] == CAT, "the floor's sentence replaced the catalogue's error"
    assert "language_countries.yml" in rep["reason"], (
        "the floor's own reason is unchanged (the read-back prints it)"
    )


def test_the_catalogue_reason_is_null_when_the_catalogue_was_read():
    assert floor_report([], {"sources": []}, EMPTY)["catalog_reason"] is None
    assert floor_report([], {"sources": []}, ONE)["catalog_reason"] is None


def test_a_read_floor_with_an_unread_catalogue_carries_the_same_reason_in_both_fields():
    rep = floor_report([], None, ONE, reason=CAT)
    assert rep["reason"] == rep["catalog_reason"] == CAT


def test_an_unread_catalogue_with_no_reason_given_is_still_said():
    assert floor_report([], None, EMPTY)["catalog_reason"] == "the law catalogue could not be read"


def test_the_read_back_prints_the_catalogue_line_once(tmp_path):
    R = _readback()

    def text(floor):
        p = tmp_path / "oo-field-20261122-1100-p8000-law-coverage.json"
        p.write_text(
            json.dumps({"kind": "law-coverage", "data": {"floor": floor}}), encoding="utf-8"
        )
        return "\n".join(R.report(R.load(p)))

    both = text(floor_report([], None, EMPTY, reason=CAT))
    assert f"  catalogue not read either: {CAT}" in both, both
    only_catalogue = text(floor_report([], None, ONE, reason=CAT))
    assert "catalogue not read either" not in only_catalogue, "the same reason was printed twice"
    assert "catalogue not read either" not in text(floor_report([], {"sources": []}, EMPTY))


def test_the_route_keeps_both_when_both_fail(monkeypatch):
    from fastapi.testclient import TestClient

    import src.civic.coverage_floor as cf
    import src.law.catalog as catalog
    import src.monitoring.kpi as kpi
    from src.api.main import app

    def _unreadable():
        raise catalog.LawCatalogUnreadable(CAT)

    monkeypatch.setattr(catalog, "load_legal_catalog", _unreadable)
    monkeypatch.setattr(cf, "load_floor", lambda: dict(EMPTY))
    monkeypatch.setattr(kpi, "_write_record", lambda name, schema, rec: rec)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        r = client.get("/api/diagnostics/law-coverage")
    assert r.status_code == 200
    floor = r.json()["data"]["floor"]
    assert floor["floor"]["state"] == "absent" and floor["catalog_reason"] == CAT, floor


def test_a_read_floor_with_no_reason_given_never_says_either(tmp_path):
    """Opus read: with the floor read and no reason handed in, ``reason`` was None beside a default ``catalog_reason``, and the
    read-back printed "catalogue not read either" under "no reason given". Both now carry the one sentence."""
    rep = floor_report([], None, ONE)
    assert rep["reason"] == rep["catalog_reason"] == "the law catalogue could not be read"
    for state in ("absent", "unreadable"):
        empty = floor_report(
            [], None, {**EMPTY, "read": {"state": state, "error": "YAMLError"}}, reason=CAT
        )
        assert empty["floor"]["state"] == state and empty["catalog_reason"] == CAT
