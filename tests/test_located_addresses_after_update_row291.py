"""Row 291: located infobox addresses are resolved again after a daily OpenStreetMap update.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The located-address scan memoizes each answer under a signature of the OSM countries it can ask. That signature was the extract's
date alone, and a daily apply changes the objects without a new cut (and rebuilds the index in the same run), so after an update
every memoized address kept the object it had matched before it, including an object the update deleted. The signature is now the
basis ``index_state`` itself compares (``country_basis``: the cut plus the daily file applied), so the two cannot disagree.

End to end, with no stand-in for the OSM side: a stamped synthetic extract is cut into a real lane, the real geocoder answers, and a
real change file deleting the matched object is applied through ``update_country``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.osm import apply as A
from src.osm import ingest
from src.versioned.store import create_lane, lane_session
from src.wiki import located as L
from tests import _osm_lane_helpers
from tests.test_osm_apply import Mirror, _extract, _osc

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parents[1]

#: The fixture's one address object (way 13, "1 Fixture Road"), deleted by the next daily file.
DELETE_WAY_13 = _osc(
    '<delete><way id="13" version="99" timestamp="2025-01-11T03:00:00Z"/></delete>'
)


def _public(q, limit=5, facts=False):
    """The real geocoder, with the answer tagged as OSM would tag a museum (way 13 is a plain building in the fixture)."""
    from src.osm.places import geocode

    out = geocode(q, limit=limit, facts=facts)
    for r in out["results"]:
        r["facts"] = {**r.get("facts", {}), "tourism": "museum"}
    return out


def _page(s):
    from src.versioned.models import VersionedEntity, VersionedRevision

    text = "{{Infobox museum|address=1 Fixture Road, Fixtureville, Fixture Land}}"
    e = VersionedEntity(external_id="en:#1", language="en", title="Fixture Building")
    s.add(e)
    s.flush()
    s.add(
        VersionedRevision(
            entity_id=e.id, revision_ref="101", content_hash="h1", content=text, byte_size=len(text)
        )
    )
    s.commit()


def test_an_address_is_resolved_again_after_a_daily_file_deletes_its_object(osm_lane_dir):
    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    L.reset()
    create_lane("wiki")
    try:
        with lane_session("wiki") as s:
            _page(s)
            before = L.located_report(s, budget=5.0, geocoder=_public)
            sig_before, _boxes = L._osm_scope()
            rep = A.update_country(
                "ZZ",
                Mirror(101, {101: DELETE_WAY_13}),
                workdir=osm_lane_dir / "w",
                kill_switch=lambda: False,
            )
            assert rep.outcome in ("current", "applied"), rep.outcome
            sig_after, _boxes = L._osm_scope()
            # The SAME scan state, as a running app holds it between two reads of the map.
            after = L.located_report(s, budget=5.0, geocoder=_public)
    finally:
        L.reset()
    [pt] = before["points"]
    assert pt["osm_object"] == "way/13" and pt["osm_data_date"]["updates"] == "none"
    assert sig_after != sig_before, (
        "a daily file changed the objects and the signature did not move"
    )
    assert after["points"] == [], "the address stayed placed at an object the update deleted"
    assert after["per_edition"]["en"].get("located", 0) == 0


def test_the_signature_is_the_basis_the_index_compares(osm_lane_dir):
    """One reading for both: the scope signature carries ``country_basis``, the string ``index_state`` matches the index against."""
    import json

    from src.osm.lane_models import OsmCountry, country_basis
    from src.osm.places import index_state
    from src.versioned import store

    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    sig, _boxes = L._osm_scope()
    with store.lane_session("osm") as s:
        basis = country_basis(s.query(OsmCountry).filter_by(alpha3="ZZZ").one())
    assert json.loads(sig) == [["ZZZ", basis]]
    assert [c["basis"] for c in index_state()] == [basis]


def test_a_located_answer_carries_the_data_date_from_the_one_reading(osm_lane_dir):
    from src.osm.lane_models import OsmCountry, country_data_date
    from src.versioned import store

    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    A.update_country(
        "ZZ", Mirror(101, {101: _osc("")}), workdir=osm_lane_dir / "w", kill_switch=lambda: False
    )
    answer = L.resolve("1 Fixture Road, Fixtureville", _public)
    with store.lane_session("osm") as s:
        want = country_data_date(s.query(OsmCountry).filter_by(alpha3="ZZZ").one())
    assert (
        answer["status"] == "located"
        and answer["osm_data_date"] == want
        and want["updates"] == "dated"
    )


def test_the_hover_runs_as_real_code_under_node():
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "located_address_data_date_row291_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0 and "all assertions passed" in out.stdout, out.stdout + out.stderr
