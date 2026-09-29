"""The curated columns, the families and the blob: no tag lost, the ceiling stated (Q810, Q1140).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import random
import sqlite3

import pytest

from src.osm import tags as T
from src.osm.lane_models import table_width


def _random_tags(rng: random.Random) -> dict[str, str]:
    pool = list(T.SCALAR_KEYS) + ["name:fr", "name:", "contact:phone", "payment:cash", "disused:shop",
                                  "addr:floor", "Name", "name_fr", "t_name", "weird key", "k:v:w", "", "id"]
    out = {}
    for _ in range(rng.randint(0, 25)):
        out[rng.choice(pool)] = rng.choice(["", "x", "é", "a;b", "0", " "])
    return out


@pytest.mark.parametrize("extended", [True, False])
def test_split_then_join_loses_no_tag_and_invents_none(extended):
    rng = random.Random(1)
    for _ in range(2000):
        tags = _random_tags(rng)
        s, f, b = T.split_tags(tags, extended=extended)
        assert T.join_tags(s, f, b) == tags
        # Each tag lands in exactly one place.
        placed = len(s) + sum(len(v) for v in f.values()) + len(b)
        assert placed == len(tags)


def test_Q810s_list_is_carried_verbatim_and_the_extension_only_adds():
    q810 = set(T._scalar_keys(extended=False))
    for k in T.Q810_KEYS:
        if k.endswith(":*"):
            prefix = k[:-1]
            assert prefix in T.FAMILIES or prefix == "addr:", k
        else:
            assert k in q810, k
    assert q810 <= set(T.SCALAR_KEYS)
    assert len(T.SCALAR_KEYS) > len(q810)


def test_the_extension_shrinks_the_blob_on_a_real_shaped_object():
    road = {"highway": "residential", "name": "X", "surface": "asphalt", "maxspeed": "30", "lanes": "2", "oneway": "yes"}
    assert T.blob_bytes(road, extended=True) < T.blob_bytes(road, extended=False)
    assert T.blob_bytes(road, extended=True) == 0


def test_column_names_are_unique_and_never_collide_with_a_structural_column():
    cols = [T.column_name(k) for k in T.SCALAR_KEYS]
    assert len(cols) == len(set(cols))
    assert all(c.startswith("t_") for c in cols)


def test_the_table_stays_far_below_both_databases_column_ceilings():
    """The Q1140 note. SQLite's ceiling is MEASURED here; PostgreSQL's 1,600 is from memory."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE ok (" + ", ".join(f"c{i}" for i in range(2000)) + ")")
        with pytest.raises(sqlite3.OperationalError, match="too many columns"):
            con.execute("CREATE TABLE no (" + ", ".join(f"c{i}" for i in range(2001)) + ")")
    finally:
        con.close()
    assert table_width() <= 400, "widening osm_objects past 400 columns is an argued change"


@pytest.mark.parametrize(
    ("tags", "is_way", "expected"),
    [
        ({}, False, None),
        ({"highway": "traffic_signals"}, False, None),
        ({"highway": "residential"}, True, "road"),
        ({"building": "yes"}, True, "building"),
        ({"building": "yes", "shop": "bakery"}, True, "poi"),
        ({"place": "village"}, False, "place"),
        ({"boundary": "administrative", "admin_level": "4"}, False, "admin"),
        ({"natural": "tree"}, False, None),
        ({"natural": "peak", "wikidata": "Q1"}, False, "poi"),
        # R78 (answer 16 = c): land use, water and power lines are kept too.
        ({"power": "line"}, True, "power"),
        ({"power": "substation"}, False, "power"),
        ({"power": "tower"}, False, None),
        ({"power": "generator", "generator:source": "solar"}, True, None),
        ({"waterway": "river", "name": "X"}, True, "water"),
        ({"natural": "water", "water": "lake"}, True, "water"),
        ({"natural": "wetland"}, True, "water"),
        ({"natural": "coastline"}, True, None),
        ({"landuse": "farmland"}, True, "landuse"),
        ({"landuse": "reservoir", "water": "reservoir"}, True, "water"),
        ({"building": "yes", "landuse": "residential"}, True, "building"),
    ],
)
def test_classify_keeps_the_eight_kinds_and_nothing_else(tags, is_way, expected):
    assert T.classify(tags, is_way=is_way)[0] == expected


def test_notable_is_q817s_rule():
    assert T.classify({"place": "town"}, is_way=False)[3] is True
    assert T.classify({"boundary": "administrative"}, is_way=False)[3] is True
    assert T.classify({"amenity": "cafe"}, is_way=False)[3] is False
    assert T.classify({"amenity": "cafe", "wikipedia": "en:X"}, is_way=False)[3] is True
