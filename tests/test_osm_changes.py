"""``.osc`` parsed in pure Python and Q813's tag-level change rows -- the MODEL only (S05-04 S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest

from src.osm.changes import change_rows, parse_osc, tag_changes

OSC = b"""<?xml version="1.0" encoding="UTF-8"?>
<osmChange version="0.6" generator="synthetic">
  <create>
    <node id="30" version="1" timestamp="2025-01-02T00:00:00Z" lat="0.15" lon="0.16">
      <tag k="amenity" v="bench"/>
    </node>
  </create>
  <modify>
    <node id="5" version="4" timestamp="2025-01-03T00:00:00Z" lat="0.15" lon="0.15">
      <tag k="amenity" v="cafe"/>
      <tag k="opening_hours" v="Mo-Su 07:00-19:00"/>
      <tag k="website" v=""/>
    </node>
    <way id="12" version="4" timestamp="2025-01-03T00:00:00Z"><nd ref="20"/><nd ref="21"/></way>
  </modify>
  <delete>
    <node id="7" version="4" timestamp="2025-01-04T00:00:00Z"/>
  </delete>
</osmChange>
"""


def test_every_object_is_read_with_its_action_version_and_timestamp():
    got = list(parse_osc(io.BytesIO(OSC)))
    assert [(c.action, c.osm_type, c.osm_id, c.version) for c in got] == [
        ("create", "n", 30, 1), ("modify", "n", 5, 4), ("modify", "w", 12, 4), ("delete", "n", 7, 4),
    ]
    assert got[1].timestamp == datetime(2025, 1, 3, tzinfo=UTC)
    assert got[1].tags["website"] == "", "an empty value was dropped"
    assert got[2].tags == {}


def test_tag_changes_name_added_removed_and_modified_keys():
    old = {"amenity": "cafe", "opening_hours": "Mo-Fr 08:00-18:00", "website": "https://x", "email": "a"}
    new = {"amenity": "cafe", "opening_hours": "Mo-Su 07:00-19:00", "website": "", "phone": "1"}
    assert [(c.key, c.change) for c in tag_changes(old, new)] == [
        ("email", "removed"), ("opening_hours", "modified"), ("phone", "added"), ("website", "modified"),
    ]
    assert [c.change for c in tag_changes(None, {"a": "1"})] == ["added"]
    assert [c.change for c in tag_changes({"a": "1"}, None)] == ["removed"]
    assert tag_changes(old, old) == []


def test_change_rows_carry_the_diffs_timestamp_and_the_objects_version_and_are_not_saved():
    when = datetime(2025, 1, 3, tzinfo=UTC)
    rows = change_rows("n", 5, {"a": "1"}, {"a": "2"}, diff_timestamp=when, version=4)
    assert len(rows) == 1
    r = rows[0]
    assert (r.key, r.change, r.old_value, r.new_value, r.diff_timestamp, r.object_version) == ("a", "modified", "1", "2", when, 4)
    assert r.id is None, "the model is defined, the apply is 0.6"


def test_an_entity_expansion_bomb_is_refused_as_a_parse_error():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>
<osmChange><create><node id="1"><tag k="x" v="&b;"/></node></create></osmChange>"""
    with pytest.raises(Exception) as exc:
        list(parse_osc(io.BytesIO(bomb)))
    assert "Entities" in type(exc.value).__name__ or "entit" in str(exc.value).lower()
