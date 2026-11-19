"""The dossier's signed-evidence export (brief S08-01 S2; 0.8 gate row A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What the export promises, on the dossier seed's own fixture rows (tests/test_dossier_seed.py):

* it is the evidence bundle the app already signs: the joined articles are the items under the
  Merkle root, the dossier rides in ``manifest.dossier``, and ``verify_bundle`` passes unchanged;
* the signature covers the dossier: a changed byte in it fails the verification, as a changed
  item fails the root;
* the dossier block is what the page shows (a lens, invariant #31), with the rails it carries and
  the ones it does not, and the licence lines that APPLY, each with its signal (Q1008 = a; OSM's
  credit and the ODbL share-alike line under Q823 = a);
* a dossier larger than the page's id bound says how much the file holds;
* no key in the block is a score (no composite, the non-negotiable);
* a bundle with no dossier is unchanged, and no test opens a socket.
"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database.session import get_db
from src.reporting import dossier_evidence as DE
from src.reporting import evidence as ev
from tests.test_dossier_seed import ZED, ZED_PLACE, db, lanes, rings, seeded  # noqa: F401 - fixtures

FORBIDDEN_KEY_PARTS = ("score", "rating", "ranking", "grade")


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    p = tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(ev, "_default_key_path", lambda: p)
    return p


@pytest.fixture
def client(db, key_path):  # noqa: F811 - the imported fixture
    from src.api import reporting as R

    app = FastAPI()
    app.include_router(R.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def test_the_dossier_is_signed_as_the_evidence_bundle_and_verifies(client, seeded, lanes):  # noqa: F811
    r = client.post("/api/reports/evidence", json={"dossier_qid": ZED.lower(), "lang": "en", "case_name": "Zedport"})
    assert r.status_code == 200, r.text
    bundle = r.json()
    m = bundle["manifest"]
    assert m["bundle_version"] == ev.BUNDLE_VERSION and m["case_name"] == "Zedport"
    assert sorted(it["id"] for it in m["items"]) == sorted([seeded["a1"], seeded["a2"], seeded["a3"]])
    d = m["dossier"]
    assert d["qid"] == ZED
    assert d["rails_carried"] == ["news", "wikipedia", "law", "places", "map"]
    assert d["rails_not_carried"] == ["stats", "climate", "agenda", "elections", "markets", "law_versions"]
    assert (d["articles_total"], d["articles_in_bundle"], d["articles_bounded"]) == (3, 3, False)
    places = next(x for x in d["rails"] if x["key"] == "places")["places"]
    assert [p["id"] for p in places] == [ZED_PLACE]
    assert d["method"] and d["caveat"] and d["export_note"]
    assert ev.verify_bundle(bundle)[0] is True
    # The JSON the browser saves verifies too (the file, not only the dict).
    assert ev.verify_bundle(json.loads(json.dumps(bundle)))[0] is True
    pinned = client.post("/api/reports/evidence/verify", json={"bundle": bundle, "trusted_public_key": bundle["public_key"]})
    assert pinned.json()["verified"] is True


def test_the_signature_covers_the_dossier_block_and_the_items(client, seeded, lanes):  # noqa: F811
    bundle = client.post("/api/reports/evidence", json={"dossier_qid": ZED}).json()

    edited = copy.deepcopy(bundle)
    edited["manifest"]["dossier"]["articles_total"] += 1
    ok, reason = ev.verify_bundle(edited)
    assert ok is False and "signature" in reason

    renamed = copy.deepcopy(bundle)
    renamed["manifest"]["dossier"]["rails"][3]["places"][0]["name"] = "Elsewhere"
    assert ev.verify_bundle(renamed)[0] is False

    dropped = copy.deepcopy(bundle)
    del dropped["manifest"]["dossier"]
    assert ev.verify_bundle(dropped)[0] is False, "removing the dossier is a change to the signed manifest"

    item = copy.deepcopy(bundle)
    item["manifest"]["items"][0]["title"] = "changed"
    ok, reason = ev.verify_bundle(item)
    assert ok is False and "merkle" in reason


def test_the_licence_lines_are_the_ones_that_apply_each_with_its_signal(db, seeded, lanes):  # noqa: F811
    sel = DE.dossier_selection(db, ZED, "en")
    lines = {a["key"]: a for a in sel.block["attribution"]}
    # Wikipedia: an article from a *.wikipedia.org source is in the bundle.
    assert "domain:fr.wikipedia.org" in lines["wikipedia"]["because"]
    # Law: a legal source contributed.
    assert "law" in lines
    # OpenStreetMap: the Places carry OSM ids, so OSM's credit and the ODbL line apply (Q823 = a).
    assert "table:places" in lines["openstreetmap"]["because"]
    assert "ODbL" in lines["openstreetmap"]["text"] or "Open Database" in lines["openstreetmap"]["text"]
    # Nothing on this machine is DB-IP or Open-Meteo derived, so no such line is claimed.
    assert "db_ip" not in lines and "open_meteo" not in lines


def test_an_item_with_nothing_on_this_machine_claims_no_licence_and_still_exports(client, rings, lanes):  # noqa: F811
    r = client.post("/api/reports/evidence", json={"dossier_qid": "Q999999555"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["manifest"]["item_count"] == 0 and b["manifest"]["merkle_root"] is None
    assert b["manifest"]["dossier"]["attribution"] == []
    assert ev.verify_bundle(b)[0] is True
    plan = client.post("/api/reports/evidence/plan", json={"dossier_qid": "Q999999555"}).json()
    assert plan["articles"] == 0 and plan["dossier"]["articles_in_bundle"] == 0


def test_a_dossier_larger_than_the_page_bound_says_how_much_the_file_holds(db, seeded, lanes, monkeypatch):  # noqa: F811
    from src.entities import dossier as DO

    monkeypatch.setattr(DO, "IDS_FOR_ANALYSIS", 2)
    sel = DE.dossier_selection(db, ZED, "en")
    assert (sel.block["articles_total"], sel.block["articles_in_bundle"], sel.block["articles_bounded"]) == (3, 2, True)
    assert len(sel.article_ids) == 2


def test_the_plan_lists_the_dossier_part_before_anything_is_written(client, seeded, lanes, key_path):  # noqa: F811
    plan = client.post("/api/reports/evidence/plan", json={"dossier_qid": ZED, "lang": "en"}).json()
    assert plan["articles"] == 3 and plan["sources"] == 3
    d = plan["dossier"]
    assert d["qid"] == ZED and d["rails_carried"][0] == "news" and d["rails_not_carried"]
    assert {a["key"] for a in d["attribution"]} >= {"wikipedia", "openstreetmap"}
    assert not key_path.exists(), "the review creates no key"


def test_a_bad_qid_is_refused_and_a_plain_bundle_is_unchanged(client, seeded, lanes):  # noqa: F811
    assert client.post("/api/reports/evidence", json={"dossier_qid": "Paris"}).status_code == 400
    assert client.post("/api/reports/evidence/plan", json={"dossier_qid": "Q"}).status_code == 400
    plain = client.post("/api/reports/evidence", json={"article_ids": [seeded["a1"]]}).json()
    assert "dossier" not in plain["manifest"]
    assert set(plain["manifest"]) == {"bundle_version", "case_name", "generated_at", "item_count", "merkle_root", "items"}
    assert "dossier" not in client.post("/api/reports/evidence/plan", json={"article_ids": [seeded["a1"]]}).json()


def test_no_key_in_the_dossier_block_is_a_score(db, seeded, lanes):  # noqa: F811
    keys = _keys(DE.dossier_selection(db, ZED, "en").block)
    # "degraded" contains "grade": the walk looks at whole words of a key, split on "_".
    bad = {k for k in keys if any(part in FORBIDDEN_KEY_PARTS for part in k.lower().split("_"))}
    assert not bad, bad


def test_the_module_imports_nothing_socket_capable():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(DE.__file__).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {x.split(".")[0] for x in names} & {"socket", "requests", "httpx", "urllib", "http"}


def test_the_dossier_page_offers_the_export_through_the_one_review():
    from tests.js_source_helper import read_static

    js = read_static("app-dossier.js")
    assert 'class="secondary dossier-evidence"' in js and 't("Export signed evidence")' in js
    # The button opens the same review as every other evidence export: nothing is written before it.
    assert "openEvidenceReview({dossier_qid: d.qid" in js
    assert "/api/reports/evidence" not in js, "the dossier page never posts the export itself"
    ev_js = read_static("app-evidence.js")
    assert "evidenceDossierHtml(plan, t, tf)" in ev_js


# ---- the 2026-11-19 correctness and security reads ------------------------------------------ #

def _osm_object(lat, lon):
    from src.osm.lane_models import osm_objects_table as T
    from src.osm.tags import column_name
    from src.versioned.store import create_lane, lane_session

    create_lane("osm")
    with lane_session("osm") as lane:
        lane.execute(T.insert().values(osm_type="n", osm_id=9000000001, country_alpha3="ZZZ", kind="place",
                                       lat=lat, lon=lon, **{column_name("wikidata"): ZED, column_name("name"): "Zedport"}))


def test_a_whole_degree_coordinate_survives_the_browsers_save_and_still_verifies(client, seeded, lanes):  # noqa: F811
    import shutil
    import subprocess

    _osm_object(52.0, 0.0)
    bundle = client.post("/api/reports/evidence", json={"dossier_qid": ZED}).json()
    obj = next(r for r in bundle["manifest"]["dossier"]["rails"] if r["key"] == "map")["lane"]["objects"][0]
    assert (obj["lat"], obj["lon"]) == ("52.0", "0.0"), "coordinates are decimal text, never a JSON number"
    assert ev.verify_bundle(bundle)[0] is True
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    # What app-evidence.js does when it saves: JSON.stringify(bundle, null, 2) of the parsed answer.
    saved = subprocess.run([node, "-e", "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>"
                            "process.stdout.write(JSON.stringify(JSON.parse(s),null,2)))"],
                           input=json.dumps(bundle), capture_output=True, text=True, check=True).stdout
    ok, reason = ev.verify_bundle(json.loads(saved))
    assert ok is True, reason


def test_no_float_is_left_anywhere_in_the_block(db, seeded, lanes):  # noqa: F811
    _osm_object(48.85661, 2.3522)

    def floats(o):
        if isinstance(o, float):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from floats(v)
        elif isinstance(o, list):
            for v in o:
                yield from floats(v)

    assert list(floats(DE.dossier_selection(db, ZED, "en").block)) == []


def test_the_file_names_wikipedia_pages_but_not_which_ones_this_install_follows(db, seeded, lanes, monkeypatch):  # noqa: F811
    from src.entities import places

    monkeypatch.setattr(places, "wiki_pages_for_qid", lambda qid, limit=24: {"available": True, "pages": [
        {"edition": "frwiki", "title": "Zedport", "external_id": "frwiki:p1", "followed": True},
        {"edition": "enwiki", "title": "Zedport", "external_id": "enwiki:p2", "followed": False}]})
    sel = DE.dossier_selection(db, ZED, "en")
    pages = next(r for r in sel.block["rails"] if r["key"] == "wikipedia")["lane"]["pages"]
    assert [p["title"] for p in pages] == ["Zedport", "Zedport"]
    assert all(set(p) == set(DE.WIKI_PAGE_FIELDS) for p in pages)
    assert "followed" not in json.dumps(sel.block)


def test_the_language_and_the_selection_are_refused_when_they_are_not_one_thing(client, seeded, lanes):  # noqa: F811
    assert client.post("/api/reports/evidence", json={"dossier_qid": ZED, "lang": "x" * 500}).status_code == 422
    assert client.post("/api/reports/evidence", json={"dossier_qid": ZED, "lang": "../en"}).status_code == 422
    assert client.post("/api/reports/evidence", json={"dossier_qid": ZED, "lang": "pt-BR"}).status_code == 200
    both = client.post("/api/reports/evidence", json={"dossier_qid": ZED, "article_ids": [seeded["a1"]]})
    assert both.status_code == 400
    assert client.post("/api/reports/evidence/plan", json={"dossier_qid": ZED, "query": "zedport"}).status_code == 400
