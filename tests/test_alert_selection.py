"""The alert DISPLAY layer (field impressions 2026-08-01, rulings 1-3).

The maintainer's report: "there has been a 6.8 magnitude earthquake in japan recently,
but this information is distilled amongst other less relevant, smaller earthquakes".

Why it happened, and what these tests pin: every USGS quake is tiered "info" (correct --
the provider declared no urgency, and a magnitude must never be promoted into one), and
the tier was then rendered in raw snapshot order with no cap. So the fix is ORDERING and
a DISPLAY floor over provider-declared facts, never a change to the tier. The tests below
assert BOTH directions: the big event surfaces, AND the tiering, the recall and the
storage-level 1:1 records are untouched.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from src.analytics.alerts import (
    DEFAULT_MIN_MAGNITUDE,
    _hazard_tier,
    _order_key,
    _same_event,
    group_same_events,
    is_major,
    quake_band,
)


def _quake(rid, mag, band, lat, lon, when, source="usgs", type_="earthquake"):
    return {
        "source": source, "id": rid, "type": type_, "severity": band, "magnitude": mag,
        "lat": lat, "lon": lon, "time": when, "article_id": None, "place": "somewhere",
    }


# --------------------------------------------------------------------------- #
#  The reported defect.
# --------------------------------------------------------------------------- #
def test_the_biggest_quake_sorts_first_among_smaller_ones() -> None:
    """The exact report: a M6.8 must not sit wherever the feed happened to put it."""
    recs = [
        _quake("a", 4.5, "moderate", 10.0, 10.0, "2026-08-01T10:00:00Z"),
        _quake("b", 6.8, "strong", 35.0, 139.0, "2026-08-01T09:00:00Z"),
        _quake("c", 4.9, "moderate", 20.0, 20.0, "2026-08-01T11:00:00Z"),
    ]
    ordered = sorted(group_same_events(recs), key=_order_key)
    assert ordered[0]["magnitude"] == 6.8


def test_a_provider_red_alert_outranks_a_larger_magnitude() -> None:
    """Ordering leads with the PROVIDER's own declared level: an orange/red GDACS
    alert is a statement about the event, a magnitude is only a measurement of size."""
    gdacs_red = {
        "source": "gdacs", "id": "r", "type": "flood", "severity": "urgent",
        "magnitude": None, "lat": 1.0, "lon": 1.0, "time": "2026-08-01T09:00:00Z",
    }
    big_quake = _quake("q", 7.4, "major", 50.0, 50.0, "2026-08-01T09:00:00Z")
    ordered = sorted([big_quake, gdacs_red], key=_order_key)
    assert ordered[0]["severity"] == "urgent"


# --------------------------------------------------------------------------- #
#  The floor is a DISPLAY floor -- and the honesty rule it must not break.
# --------------------------------------------------------------------------- #
def test_the_display_floor_uses_provider_declared_facts_only() -> None:
    assert is_major(_quake("a", 6.8, "strong", 0, 0, None)) is True
    assert is_major(_quake("b", 7.5, "major", 0, 0, None)) is True
    assert is_major(_quake("c", 4.5, "moderate", 0, 0, None)) is False
    # a provider level clears the floor whatever the magnitude (GDACS carries none)
    assert is_major({"severity": "urgent", "magnitude": None}) is True
    assert is_major({"severity": "watch", "magnitude": None}) is True
    assert is_major({"severity": "info", "magnitude": None}) is False


def test_the_floor_is_configurable_and_the_band_agrees_with_the_number() -> None:
    small = _quake("s", 5.2, "moderate", 0, 0, None)
    assert is_major(small) is False
    assert is_major(small, min_magnitude=5.0) is True
    assert DEFAULT_MIN_MAGNITUDE == 6.0  # the USGS "strong" band's own lower bound


def test_a_magnitude_is_never_promoted_into_an_urgency_tier() -> None:
    """THE honesty rule of this whole layer. A display floor must not become a tier:
    a M9 quake with no provider alert stays 'info', exactly as before."""
    assert _hazard_tier("major") == "info"
    assert _hazard_tier("strong") == "info"
    assert _hazard_tier("urgent") == "urgent"   # provider-declared only
    assert _hazard_tier(None) == "info"


def test_a_band_is_read_only_from_a_non_provider_severity() -> None:
    assert quake_band({"severity": "strong"}) == "strong"
    assert quake_band({"severity": "urgent"}) is None    # that is a GDACS level, not a band
    assert quake_band({"severity": "unknown"}) is None   # an absent measurement, not a band
    assert quake_band({}) is None


# --------------------------------------------------------------------------- #
#  Grouping -- and its NEGATIVE space (what must NOT group).
# --------------------------------------------------------------------------- #
def test_one_event_reported_by_two_providers_groups_once_naming_both() -> None:
    usgs = _quake("u", 6.8, "strong", 35.00, 139.00, "2026-08-01T09:00:00Z")
    usgs["article_id"] = 11
    gdacs = _quake("g", None, "watch", 35.10, 139.05, "2026-08-01T10:00:00Z", source="gdacs")
    gdacs["article_id"] = 12
    out = group_same_events([usgs, gdacs])
    assert len(out) == 1
    assert out[0]["grouped"] is True
    assert out[0]["providers"] == ["usgs", "gdacs"]
    assert out[0]["magnitude"] == 6.8              # the only provider that measured one
    assert out[0]["severity"] == "watch"           # the strongest provider level of the group
    assert sorted(out[0]["article_ids"]) == [11, 12]   # no article is lost


def test_different_types_never_group() -> None:
    a = _quake("a", 6.8, "strong", 35.0, 139.0, "2026-08-01T09:00:00Z")
    b = _quake("b", None, "watch", 35.0, 139.0, "2026-08-01T09:10:00Z", source="gdacs",
               type_="flood")
    assert _same_event(a, b) is False
    assert len(group_same_events([a, b])) == 2


def test_events_far_apart_in_space_never_group() -> None:
    a = _quake("a", 6.8, "strong", 35.0, 139.0, "2026-08-01T09:00:00Z")
    b = _quake("b", 6.7, "strong", 36.0, 139.0, "2026-08-01T09:10:00Z", source="gdacs")
    assert _same_event(a, b) is False


def test_events_far_apart_in_time_never_group() -> None:
    a = _quake("a", 6.8, "strong", 35.0, 139.0, "2026-08-01T09:00:00Z")
    b = _quake("b", 6.7, "strong", 35.0, 139.0, "2026-08-01T14:00:00Z", source="gdacs")
    assert _same_event(a, b) is False


def test_missing_coordinates_or_times_never_group() -> None:
    """An absent measurement is not a match. Grouping on a guess would merge two
    genuinely different events and hide one of them."""
    a = _quake("a", 6.8, "strong", None, None, "2026-08-01T09:00:00Z")
    b = _quake("b", 6.7, "strong", None, None, "2026-08-01T09:10:00Z", source="gdacs")
    assert _same_event(a, b) is False
    c = _quake("c", 6.8, "strong", 35.0, 139.0, None)
    d = _quake("d", 6.7, "strong", 35.0, 139.0, None, source="gdacs")
    assert _same_event(c, d) is False


def test_grouping_never_mutates_the_input_records() -> None:
    """Display-layer only: the stored snapshot records stay 1:1 per provider event."""
    usgs = _quake("u", 6.8, "strong", 35.0, 139.0, "2026-08-01T09:00:00Z")
    gdacs = _quake("g", None, "watch", 35.05, 139.02, "2026-08-01T09:30:00Z", source="gdacs")
    before = [dict(usgs), dict(gdacs)]
    group_same_events([usgs, gdacs])
    assert [usgs, gdacs] == before


def test_an_ungroupable_record_still_carries_the_display_fields() -> None:
    lone = _quake("l", 4.2, "minor", 1.0, 1.0, "2026-08-01T09:00:00Z")
    out = group_same_events([lone])
    assert out[0]["grouped"] is False and out[0]["providers"] == ["usgs"]


def test_a_record_without_a_magnitude_is_not_ranked_as_if_it_had_one() -> None:
    """An absence must not read as a low value: at the same provider level, a
    measured event sorts ahead of an unmeasured one rather than behind a zero."""
    measured = _quake("m", 4.0, "minor", 0, 0, "2026-08-01T09:00:00Z")
    unmeasured = _quake("u", None, "unknown", 0, 0, "2026-08-01T09:00:00Z")
    assert sorted([unmeasured, measured], key=_order_key)[0]["id"] == "m"
