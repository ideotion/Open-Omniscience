"""Tests for the offline country-polygons coarsening (the choropleth base map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.timemap.countries_geo import coarsen_admin0, iso2_of
from src.timemap.disputed_geo import APP_LOCALES, claim_index, coarsen_disputed

_ASSET = Path(__file__).resolve().parents[1] / "src" / "static" / "world_countries.json"
_DISPUTED = Path(__file__).resolve().parents[1] / "src" / "static" / "world_disputed.json"


def _square(cx, cy, half):
    return [
        [cx - half, cy - half], [cx + half, cy - half],
        [cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half],
    ]


def _feat(iso, geom, name="X", **extra):
    props = {"ISO_A2": iso, "NAME": name, **extra}
    return {"type": "Feature", "properties": props, "geometry": geom}


# ----------------------------- iso2_of ---------------------------------- #


def test_iso2_prefers_iso_a2_then_eh_fallback():
    assert iso2_of({"ISO_A2": "FR"}) == "fr"
    # Natural Earth stamps "-99" for some sovereigns; the real code lives in ISO_A2_EH.
    assert iso2_of({"ISO_A2": "-99", "ISO_A2_EH": "NO"}) == "no"
    assert iso2_of({"ISO_A2": "-99"}) is None
    assert iso2_of({"ISO_A2": "XX1"}) is None
    assert iso2_of({}) is None


# --------------------------- coarsen_admin0 ----------------------------- #


def test_keys_by_iso_and_rounds():
    gj = {"features": [_feat("DE", {"type": "Polygon",
          "coordinates": [[[10.123, 50.456], [12.0, 50.0], [12.0, 52.0], [10.0, 52.0], [10.123, 50.456]]]})]}
    out = coarsen_admin0(gj, precision=1, min_span=0.5)
    assert set(out["countries"]) == {"de"}
    de = out["countries"]["de"]
    assert de["name"] == "X" and len(de["rings"]) == 1
    assert de["rings"][0][0] == [10.1, 50.5]  # rounded to 1 dp
    assert out["precision"] == 1


def test_multipolygon_yields_multiple_rings_per_country():
    gj = {"features": [_feat("JP", {"type": "MultiPolygon", "coordinates": [
        [_square(135, 35, 4)], [_square(140, 40, 3)]]})]}
    out = coarsen_admin0(gj, precision=1, min_span=0.5)
    assert len(out["countries"]["jp"]["rings"]) == 2


def test_microstate_keeps_its_largest_ring_even_below_min_span():
    # A tiny island nation (span 0.4) must NOT vanish — every country with a ring renders.
    gj = {"features": [_feat("TV", {"type": "Polygon", "coordinates": [_square(179, -8, 0.2)]})]}
    out = coarsen_admin0(gj, precision=2, min_span=1.0)
    assert "tv" in out["countries"] and len(out["countries"]["tv"]["rings"]) == 1


def test_iso_eh_fallback_country_is_kept():
    gj = {"features": [_feat("-99", {"type": "Polygon", "coordinates": [_square(8, 60, 5)]},
                             name="Norway", ISO_A2_EH="NO")]}
    out = coarsen_admin0(gj, min_span=0.5)
    assert out["countries"]["no"]["name"] == "Norway"


def test_feature_without_iso_is_dropped():
    gj = {"features": [_feat("-99", {"type": "Polygon", "coordinates": [_square(0, -80, 10)]})]}
    assert coarsen_admin0(gj)["countries"] == {}


def test_empty_input_is_safe():
    assert coarsen_admin0({})["countries"] == {}
    assert coarsen_admin0({"features": []})["countries"] == {}


# ------------------------- the committed asset -------------------------- #


def test_bundled_asset_shape_and_coverage():
    """The generated world_countries.json covers the major countries and is honest
    about its shape (ISO-keyed, precision recorded). Microstates the source is too
    coarse to include are handled by the renderer's centroid fallback, not invented here.

    The scale moved 110m -> 50m on 2026-09-16 (ruling Q802): 175 -> 229 countries. The
    floor is raised to 200 in the same change, because a floor of 150 would have gone on
    passing if a later rebuild silently fell back to the coarser source -- which is the
    one regression this assertion exists to catch.
    """
    if not _ASSET.exists():
        return  # built once on a networked machine (like world_outline.json)
    data = json.loads(_ASSET.read_text(encoding="utf-8"))
    countries = data["countries"]
    assert len(countries) >= 200, f"only {len(countries)} countries -- did the build fall back to 110m?"
    assert data.get("precision") == 1
    assert "50m" in str(data.get("source", "")), f"unexpected source {data.get('source')!r}"
    # a spread of large countries across every inhabited continent must be present
    for iso in ("us", "br", "gb", "de", "fr", "ru", "cn", "in", "jp", "za", "ng", "au", "eg"):
        assert iso in countries, f"{iso} missing from the choropleth asset"
        assert countries[iso]["rings"] and len(countries[iso]["rings"][0]) >= 4


# --------------------- the contested-areas asset ------------------------ #
#
# Rulings Q826 and Q803 (2026-09-15): every disputed area is rendered CONTESTED showing
# BOTH claims, never a silent pick, with a worldview toggle so the differences between
# conventions can be seen. These guard the DATA half of that promise -- the rendering
# half lives in tests/test_map_projection.py and the Chromium click-through.


def test_disputed_transform_reads_claims_out_of_the_data():
    """The per-viewpoint fields are what make "both claims" derivable at all, so the
    transform must read them rather than take the feature's own assignment."""
    admin0 = {"features": [
        _feat("cn", {"type": "Polygon", "coordinates": [_square(80, 35, 2)]}, name="China",
              ADM0_A3="CHN", ISO_A3="CHN"),
        _feat("in", {"type": "Polygon", "coordinates": [_square(78, 22, 2)]}, name="India",
              ADM0_A3="IND", ISO_A3="IND"),
    ]}
    disputed = {"features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_square(79, 35, 1)]},
        "properties": {
            "BRK_NAME": "Aksai Chin", "TYPE": "Disputed", "ADM0_A3": "CHN",
            "ADM0_A3_IN": "IND", "ADM0_A3_CN": "CHN", "NAME_FR": "Aksai Chin",
        },
    }]}
    out = coarsen_disputed(disputed, index=claim_index(admin0, disputed))
    area = out["areas"][0]
    assert [c["a2"] for c in area["claims"]] == ["cn", "in"], "both claims, sorted, deduped"
    assert area["views"]["cn"] == "cn" and area["views"]["in"] == "in", "the views differ"
    assert area["views"]["iso"] == "cn", "an unstated viewpoint falls back to the base assignment"


def test_an_unresolvable_code_is_undetermined_never_a_fabricated_country():
    """Natural Earth's internal codes (B16, C02...) mean "this viewpoint assigns the area
    to no recognised state". That is an explicit refusal, and it must not be silently
    turned into a country or dropped into a gap."""
    admin0 = {"features": [_feat("il", {"type": "Polygon", "coordinates": [_square(35, 32, 1)]},
                                 name="Israel", ADM0_A3="ISR", ISO_A3="ISR")]}
    disputed = {"features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_square(35.8, 33, 0.3)]},
        "properties": {"BRK_NAME": "Golan Heights", "TYPE": "Indeterminate",
                       "ADM0_A3": "ISR", "ADM0_A3_FR": "B16"},
    }]}
    area = coarsen_disputed(disputed, index=claim_index(admin0, disputed))["areas"][0]
    assert area["views"]["fr"] is None, "an unresolvable code is undetermined"
    assert all(c["a2"] != "B16" and c["a3"] != "B16" or c["self"] for c in area["claims"]), (
        "an internal code must never be listed as a claimant country"
    )


def test_a_self_declared_entity_keeps_its_own_claim():
    """The trap this exists for: a breakaway's own claim carries no ISO alpha-2, so
    resolving claims from the alpha-3 fields alone lists ONLY the parent state -- a
    silent pick in the parent's favour, which is exactly what Q826 forbids."""
    admin0 = {"features": [_feat("ge", {"type": "Polygon", "coordinates": [_square(43, 42, 2)]},
                                 name="Georgia", ADM0_A3="GEO", ISO_A3="GEO")]}
    disputed = {"features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_square(41, 43, 0.5)]},
        "properties": {"BRK_NAME": "Abkhazia", "TYPE": "Breakaway", "ADM0_A3": "B35",
                       "BRK_A3": "B35", "ADM0_A3_ISO": "GEO", "FCLASS_RU": "Admin-0 country"},
    }]}
    area = coarsen_disputed(disputed, index=claim_index(admin0, disputed))["areas"][0]
    assert area["self_declared"] is True
    assert area["recognised_by"] == ["ru"]
    assert area["claims"][0]["self"] is True and area["claims"][0]["name"] == "Abkhazia"
    assert [c["a2"] for c in area["claims"][1:]] == ["ge"], "the parent state is still named"
    assert area["views"]["ru"] == "self", "a viewpoint that recognises it says so"
    assert area["views"]["iso"] == "ge"


def test_bundled_disputed_asset_names_every_claim():
    """The shipped asset. The headline property is that NO area is drawn with an empty
    claim list -- an area marked contested that names nobody would be the silent pick
    wearing a hatch."""
    if not _DISPUTED.exists():
        return  # built once on a networked machine
    data = json.loads(_DISPUTED.read_text(encoding="utf-8"))
    areas = data["areas"]
    assert len(areas) >= 25, f"only {len(areas)} contested areas"
    assert "50m" in str(data.get("source", ""))
    for a in areas:
        assert a["claims"], f"{a['name']} is drawn contested but names no claimant"
        assert a["rings"] and len(a["rings"][0]) >= 4, f"{a['name']} has no drawable ring"
        # Every claim is either a real country or the area's own claim to statehood.
        for c in a["claims"]:
            assert c["a2"] or c["self"], f"{a['name']}: a claim with neither a code nor selfhood"
    # The named disputes a reader will look for, with both sides present.
    by_name = {a["name"]: a for a in areas}
    for name, expected in {
        "Aksai Chin": {"cn", "in"}, "Crimea": {"ru", "ua"},
        "Jammu and Kashmir": {"in", "pk"}, "Golan Heights": {"il", "sy"},
    }.items():
        assert name in by_name, f"{name} is missing from the contested asset"
        got = {c["a2"] for c in by_name[name]["claims"] if c["a2"]}
        assert expected <= got, f"{name}: claims {sorted(got)} do not cover {sorted(expected)}"


def test_every_contested_area_is_named_in_all_twelve_locales():
    """The names travel as DATA from Natural Earth's own NAME_<lang> fields, so this is
    a coverage check on the SOURCE, not on a translation this app made. A gap is
    recorded as a gap -- the renderer falls back to the English name."""
    if not _DISPUTED.exists():
        return
    data = json.loads(_DISPUTED.read_text(encoding="utf-8"))
    missing = {a["name"]: sorted(set(APP_LOCALES) - set(a["names"])) for a in data["areas"]
               if set(APP_LOCALES) - set(a["names"])}
    # MEASURED 2026-09-16, not assumed: 24 of the 28 areas carry all twelve, and four
    # have gaps in Natural Earth itself. Pinned as the known gap rather than asserted
    # away, so a REGRESSION (a rebuild that loses names) reddens while the real hole
    # stays visible. The renderer falls back to the English name, which is why a gap
    # here is honest rather than broken.
    known = {
        "Donetsk People's Republic": ["hi"],
        "Junagadh and Manavadar": ["hi", "pt"],
        "Luhansk People's Republic": ["hi"],
        "North Borneo": ["bn", "es", "hi"],
    }
    assert missing == known, f"locale coverage moved: {missing}"
    # Every area is named in English at minimum, which is what the fallback needs.
    assert all(a["names"].get("en") or a["name"] for a in data["areas"])

