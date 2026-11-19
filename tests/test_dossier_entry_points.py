"""The dossier's entry points and its rail-availability counter (0.8 row A, brief S08-01 S2/S3, row 178).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S3's acceptance: the counter is in the Diagnostics zip with method and n. The refusals pinned here: the
member never carries the item's id or label (the zip is a file the operator sends to someone else), a
rail with no rows is listed as a gap rather than dropped, a counter that cannot read a payload never
costs the operator their dossier, and the member stays inside the budget its slot row states.
S2's entry points (a keyword with a QID, an Explore search, a Lead card) are pinned in the shipped
sources and driven through the real functions by ``dossier_entry_node_test.js``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.api import diagnostics_slots as slots
from src.entities import dossier_diagnostics as DD
from tests.js_source_helper import function_source, read_static
from tests.test_dossier_seed import ZED, db, lanes, rings, seeded  # noqa: F401 - fixtures

COUNTRY_KEYS = ["news", "wikipedia", "law", "places", "map", "stats", "climate", "agenda", "elections"]


@pytest.fixture(autouse=True)
def _fresh_counter():
    DD.reset()
    yield
    DD.reset()


def _payload(rails, with_rows, *, country=True, not_joined=None):
    return {"qid": "Q90", "item": {"label": "Paris"}, "rails": [{"key": k} for k in rails],
            "availability": {"rails_with_rows": with_rows}, "country": {"iso2": "fr"} if country else None,
            "not_joined": not_joined if not_joined is not None else [{"key": "markets"}, {"key": "law_versions"}]}


def test_the_counter_names_gaps_tallies_every_rail_and_says_n_and_method():
    DD.record(_payload(COUNTRY_KEYS, COUNTRY_KEYS[:6]))
    DD.record(_payload(COUNTRY_KEYS[:5], ["news"], country=False,
                       not_joined=[*({"key": k, "code": "not-a-country"} for k in COUNTRY_KEYS[5:]), {"key": "markets"}]))
    out = DD.diagnostics_member()
    assert out["n"] == 2 and out["n_country"] == 1 and out["method"] == DD.METHOD and out["since"]
    assert out["rails"]["news"] == {"joined": 2, "with_rows": 2}
    assert out["rails"]["stats"] == {"joined": 1, "with_rows": 1}
    assert out["rails"]["map"] == {"joined": 2, "with_rows": 1}
    # a gap is a gap: the joined rails without rows are LISTED, never folded into a zero
    newest = out["recent"][0]
    assert newest["country"] is False and newest["with_rows"] == ["news"]
    assert newest["without_rows"] == ["wikipedia", "law", "places", "map"]
    assert "stats:not-a-country" in newest["not_joined"] and out["not_joined"]["markets"] == 2


def test_the_member_never_carries_the_items_id_or_label():
    DD.record(_payload(COUNTRY_KEYS, COUNTRY_KEYS))
    text = json.dumps(DD.diagnostics_member())
    assert "Q90" not in text and "Paris" not in text


def test_a_payload_the_counter_cannot_read_never_raises():
    DD.record(None)  # type: ignore[arg-type]
    DD.record({"rails": "nonsense", "availability": 3})
    assert DD.diagnostics_member()["n"] == 0
    assert DD.diagnostics_member("lots")["error"] == "ValueError"


def test_a_full_memory_fits_the_slot_budget_and_the_cut_is_oldest_first_and_named():
    row = next(s for s in slots.SLOTS if s.name == "dossier-rails.json")
    assert row.budget_bytes == DD.DEFAULT_MAX_BYTES and row.area == "interface"
    assert row.target == "src.entities.dossier_diagnostics:diagnostics_member"
    for i in range(DD.KEEP_RECENT + 5):
        DD.record(_payload(COUNTRY_KEYS, COUNTRY_KEYS[: 1 + i % 9]))
    whole = DD.diagnostics_member(10**6)
    assert whole["n"] == DD.KEEP_RECENT + 5 and len(whole["recent"]) == DD.KEEP_RECENT
    out = DD.diagnostics_member(row.budget_bytes)
    assert len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()) <= row.budget_bytes
    assert out["dropped_to_fit"] == DD.KEEP_RECENT - len(out["recent"]) and len(out["recent"]) >= 4
    assert out["recent"] == whole["recent"][: len(out["recent"])], "the newest are kept"
    assert out["n"] == whole["n"], "the tally covers every opening whatever the cut"


def test_the_slot_is_a_member_of_this_build():
    assert "dossier-rails.json" in {name for name, _fn in slots.members()}


def test_opening_a_dossier_through_the_route_counts_it(db, seeded, lanes):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import entities as E
    from src.database.session import get_db

    app = FastAPI()
    app.include_router(E.router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    d = c.get("/api/entities/dossier", params={"qid": ZED}).json()
    assert c.get("/api/entities/dossier", params={"qid": "Paris"}).status_code == 400
    out = DD.diagnostics_member()
    assert out["n"] == 1, "a refused id is not an opening"
    assert out["recent"][0]["with_rows"] == d["availability"]["rails_with_rows"]
    assert ZED not in json.dumps(out)
    # the Explore and Lead entry points resolve through the ring table, locally
    r = c.get("/api/entities/resolve", params={"term": "Zedport", "target_lang": "de"}).json()
    assert r["qid"] == ZED
    r = c.get("/api/entities/resolve", params={"term": "Mercury", "target_lang": "de"}).json()
    assert "qid" not in r and len(r["candidate_qids"]) == 2


def test_the_three_entry_points_are_wired_in_the_shipped_sources():
    corpus, analysis, home = read_static("app-corpus.js"), read_static("app-analysis.js"), read_static("app-home.js")
    assert "dossierButtonHtml(qid)" in function_source(corpus, "kwQidHtml"), "a keyword with a QID offers its dossier"
    assert "dossierSearchHint(" in analysis and "seq === _searchSeq" in analysis, "an Explore search names its item"
    assert "openDossierForTerm(" in home and "${dossierBtn}" in home, "a Lead card offers its dossier"
    assert "kwQidHtml(row, {noDossier: !!(opts && opts.inButton)})" in corpus, "never a button nested in a chip button"
    assert "const dossierBtn = (_dq.trim() &&" in home and "openDossierForTerm(${esc(JSON.stringify(_dq.trim()))})" in home, \
        "only the name a Lead's title quotes"
    on = read_static("oo-on.js")
    assert on.count('"openDossier"') == 2 and on.count('"openDossierForTerm"') == 2


def test_the_entry_points_run_through_the_real_functions():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "dossier_entry_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
