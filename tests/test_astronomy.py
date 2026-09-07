"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T11 — the agenda astronomy layer: Meeus ch.49 lunar phases, verified against
the book's own worked example (the gold reference) and published almanac
full-moon dates. Honest accuracy fields travel with every result.
"""

from __future__ import annotations

from math import floor

from src.events.astronomy import _jde_phase, phases_for_year


def test_meeus_worked_example_49a_new_moon_feb_1977():
    """Meeus, example 49.a: the new moon of 1977 February — JDE 2443192.65118.
    The book computes this exact value with the same series; we require
    agreement to 3e-4 day (~26 s)."""
    k = floor((1977.13 - 2000) * 12.3685)  # = -283 per the book
    assert k == -283
    jde = _jde_phase(float(k))
    assert abs(jde - 2443192.65118) < 0.0003, f"got {jde!r}"


def test_full_moons_2024_match_published_almanac_dates():
    """Published almanac full-moon dates (UTC), 2024 — computed dates must
    land within the same UTC day ±1 (the series is minutes-accurate; ±1 day
    guards timezone-of-publication edges, honestly)."""
    expected = {1: 25, 2: 24, 3: 25, 4: 23, 5: 23, 6: 22, 7: 21, 8: 19, 9: 18, 10: 17, 11: 15, 12: 15}
    got = phases_for_year(2024)["full_moons"]
    by_month = {}
    for fm in got:
        y, m, d = (int(x) for x in fm["date"].split("-"))
        by_month.setdefault(m, d)
    for month, day in expected.items():
        assert month in by_month, f"no full moon computed in 2024-{month:02d}"
        assert abs(by_month[month] - day) <= 1, (
            f"2024-{month:02d}: computed day {by_month[month]}, almanac {day}"
        )


def test_phase_listing_carries_method_and_accuracy():
    out = phases_for_year(2026)
    assert "Meeus" in out["method"]
    assert "ΔT" in out["accuracy"] or "TD" in out["accuracy"]
    assert 11 <= len(out["full_moons"]) <= 14
    assert all(f["phase"] == "full" for f in out["full_moons"])
    # Chronological and within the year.
    dates = [f["date"] for f in out["full_moons"]]
    assert dates == sorted(dates) and all(d.startswith("2026") for d in dates)


def test_meeus_worked_example_27a_june_solstice_1962():
    """Meeus, example 27.a: the June solstice of 1962 — JDE 2437837.39245.
    Agreement to 1e-4 day (~9 s) validates the polynomial + the 24-term table."""
    from src.events.astronomy import _jde_season

    jde = _jde_season(1962, "june_solstice")
    assert abs(jde - 2437837.39245) < 0.0001, f"got {jde!r}"


def test_seasons_2024_match_published_dates():
    """Published 2024 season dates (UTC): Mar 20, Jun 20, Sep 22, Dec 21."""
    from src.events.astronomy import seasons_for_year

    out = seasons_for_year(2024)
    got = {s["event"]: s["date"] for s in out["seasons"]}
    assert got["march_equinox"] == "2024-03-20"
    assert got["june_solstice"] == "2024-06-20"
    assert got["september_equinox"] == "2024-09-22"
    assert got["december_solstice"] == "2024-12-21"
    assert "hemispheres" in out["naming"], "hemisphere honesty must travel with the data"


def test_climate_endpoint_carries_provenance_and_verification_flag():
    import os
    os.environ.setdefault("OO_DB_PLAINTEXT", "1")
    os.environ.setdefault("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        body = c.get("/api/events/climate").json()
        assert body["source"].startswith("NOAA CPC")
        assert "pending" in body["verification_status"], (
            "drafted data must stay flagged until the clearnet check"
        )
        assert body["count"] >= 20
        ep9798 = next(e for e in body["el_nino_episodes"] if e["start"] == "1997-04")
        assert ep9798["intensity"] == "very strong"
        assert ep9798["length_months"] == 14
        astro = c.get("/api/events/astronomy?year=2026").json()
        assert len(astro["seasons"]) == 4
        assert "hemispheres" in astro["seasons_naming"]


def test_lunar_phase_series_is_honest_and_consistent():
    from src.events.astronomy import lunar_phase_series, phases_for_year

    out = lunar_phase_series("2024-01-01", "2024-03-31")
    assert len(out["days"]) == 91
    assert "never" in out["caveat"] and "causation" in out["caveat"]
    assert "approximation" in out["method"]
    by_date = {d["date"]: d for d in out["days"]}
    # Consistency with the verified phase engine: on a known full-moon date
    # (2024-01-25) the fraction must be near 1; on a new-moon date
    # (2024-02-09, per the same engine) near 0.
    fulls = {f["date"] for f in phases_for_year(2024)["full_moons"]}
    news = {n["date"] for n in phases_for_year(2024)["new_moons"]}
    assert "2024-01-25" in fulls
    assert by_date["2024-01-25"]["illuminated_fraction"] > 0.97
    nm = next(d for d in sorted(news) if d.startswith("2024-02"))
    assert by_date[nm]["illuminated_fraction"] < 0.03
    # Waxing/waning: a week AFTER a new moon is waxing; a week BEFORE is waning.
    from datetime import date as _d
    from datetime import timedelta as _td
    after = (_d.fromisoformat(nm) + _td(days=7)).isoformat()
    before = (_d.fromisoformat(nm) - _td(days=7)).isoformat()
    assert by_date[after]["waxing"] is True
    assert by_date[before]["waxing"] is False


# --------------------------------------------------------------------------- #
# Quarter phases (2026-09-07) — closing the accepted loss recorded when the
# redundant `monkeyness-moons` ICS feed was retired (ruling 2026-07-17).
#
# WHY AN ELONGATION CHECK AND NOT A QUOTED CONSTANT. The new/full series is
# pinned above against Meeus' own worked example 49.a, which is the gold
# reference. For the QUARTERS the risk is a mistranscribed coefficient, and a
# constant written from memory would be exactly the fabricated reference this
# project forbids. So the quarters are verified against an INDEPENDENT method:
# a principal phase is BY DEFINITION the instant the Moon's apparent longitude
# leads the Sun's by 0 / 90 / 180 / 270 degrees, and those longitudes come from
# different chapters (Meeus ch. 47 for the Moon, ch. 25 for the Sun) with no
# term in common with ch. 49.
#
# THE ANTI-VACUITY HALF IS WHAT MAKES IT EVIDENCE: the same checker is run over
# the new and full moons, whose times are already verified to ~26 s. Its error
# there is its OWN truncation noise, so the quarters are required to sit inside
# that same band rather than under a tolerance picked by hand.
#
# MEASURED (1900..2200, every 7th year, 13 lunations each; recorded so the next
# session does not re-derive them) -- worst elongation error, degrees:
#     shipped code       new/full 0.0217   quarters 0.0196   ratio 0.90
#     W sign flipped     new/full 0.0217   quarters 0.1106   ratio 5.09
#     -0.62801 -> -0.62  new/full 0.0217   quarters 0.1137   ratio 5.24
#     W term dropped     new/full 0.0217   quarters 0.0621   ratio 2.86
# The bars below (ratio <= 2.0, absolute <= 0.035 deg) fail all three mutants
# and clear the shipped code with ~2x margin on both sides. The W-dropped
# mutant is the tight one, which is why the ratio bar is 2.0 and not 3.0.
# --------------------------------------------------------------------------- #

import re
from math import pi, sin

from src.events.astronomy import _jde_phase as _jde  # noqa: E402  (grouped with the block it serves)

_D2R = pi / 180.0

# Meeus 47.A, the 59 leading periodic terms of the Moon's longitude:
# (coefficient in 1e-6 degrees, D, M, M', F).
_MOON_TERMS = (
    (6288774, 0, 0, 1, 0), (1274027, 2, 0, -1, 0), (658314, 2, 0, 0, 0),
    (213618, 0, 0, 2, 0), (-185116, 0, 1, 0, 0), (-114332, 0, 0, 0, 2),
    (58793, 2, 0, -2, 0), (57066, 2, -1, -1, 0), (53322, 2, 0, 1, 0),
    (45758, 2, -1, 0, 0), (-40923, 0, 1, -1, 0), (-34720, 1, 0, 0, 0),
    (-30383, 0, 1, 1, 0), (15327, 2, 0, 0, -2), (-12528, 0, 0, 1, 2),
    (10980, 0, 0, 1, -2), (10675, 4, 0, -1, 0), (10034, 0, 0, 3, 0),
    (8548, 4, 0, -2, 0), (-7888, 2, 1, -1, 0), (-6766, 2, 1, 0, 0),
    (-5163, 1, 0, -1, 0), (4987, 1, 1, 0, 0), (4036, 2, -1, 1, 0),
    (3994, 2, 0, 2, 0), (3861, 4, 0, 0, 0), (3665, 2, 0, -3, 0),
    (-2689, 0, 1, -2, 0), (-2602, 2, 0, -1, 2), (2390, 2, -1, -2, 0),
    (-2348, 1, 0, 1, 0), (2236, 2, -2, 0, 0), (-2120, 0, 1, 2, 0),
    (-2069, 0, 2, 0, 0), (2048, 2, -2, -1, 0), (-1773, 2, 0, 1, -2),
    (-1595, 2, 0, 0, 2), (1215, 4, -1, -1, 0), (-1110, 0, 0, 2, 2),
    (-892, 3, 0, -1, 0), (-810, 2, 1, 1, 0), (759, 4, -1, -2, 0),
    (-713, 0, 2, -1, 0), (-700, 2, 2, -1, 0), (691, 2, 1, -2, 0),
    (596, 2, -1, 0, -2), (549, 4, 0, 1, 0), (537, 0, 0, 4, 0),
    (520, 4, -1, 0, 0), (-487, 1, 0, -2, 0), (-399, 2, 1, 0, -2),
    (-381, 0, 0, 2, -2), (351, 1, 1, 1, 0), (-340, 3, 0, -2, 0),
    (330, 4, 0, -3, 0), (327, 2, -1, 2, 0), (-323, 0, 2, 1, 0),
    (299, 1, 1, -1, 0), (294, 2, 0, 3, 0),
)


def _sun_longitude(jde: float) -> float:
    """The Sun's geometric longitude (Meeus ch. 25, low accuracy ~0.01 deg)."""
    t = (jde - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) * _D2R
    c = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * sin(m)
        + (0.019993 - 0.000101 * t) * sin(2 * m)
        + 0.000289 * sin(3 * m)
    )
    return (l0 + c) % 360.0


def _moon_longitude(jde: float) -> float:
    """The Moon's geometric longitude (Meeus ch. 47, leading terms)."""
    t = (jde - 2451545.0) / 36525.0
    lp = (218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
          + t ** 3 / 538841.0 - t ** 4 / 65194000.0)
    d = (297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
         + t ** 3 / 545868.0 - t ** 4 / 113065000.0)
    m = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t + t ** 3 / 24490000.0
    mp = (134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
          + t ** 3 / 69699.0 - t ** 4 / 14712000.0)
    f = (93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
         - t ** 3 / 3526000.0 + t ** 4 / 863310000.0)
    e = 1.0 - 0.002516 * t - 0.0000074 * t * t
    total = 0.0
    for coef, cd, cm, cmp_, cf in _MOON_TERMS:
        total += coef * (e ** abs(cm)) * sin((cd * d + cm * m + cmp_ * mp + cf * f) * _D2R)
    return (lp + total / 1e6) % 360.0


def _elongation_error(jde: float, expected_deg: float) -> float:
    """How far the Moon-Sun elongation at ``jde`` is from ``expected_deg``.

    Nutation cancels (it shifts both longitudes by the same amount), so
    geometric longitudes are the right inputs for a DIFFERENCE.
    """
    got = (_moon_longitude(jde) - _sun_longitude(jde)) % 360.0
    return abs((got - expected_deg + 180.0) % 360.0 - 180.0)


_EXPECTED_ELONGATION = {0.0: 0.0, 0.25: 90.0, 0.5: 180.0, 0.75: 270.0}


def _worst_elongation_errors() -> tuple[float, float, int]:
    """(worst new/full error, worst quarter error, phases examined)."""
    worst_nf = worst_q = 0.0
    n = 0
    for year in range(1900, 2201, 7):
        k0 = int((year - 2000) * 12.3685)
        for i in range(13):
            for off, expected in _EXPECTED_ELONGATION.items():
                err = _elongation_error(_jde(k0 + i + off), expected)
                n += 1
                if off in (0.0, 0.5):
                    worst_nf = max(worst_nf, err)
                else:
                    worst_q = max(worst_q, err)
    return worst_nf, worst_q, n


def test_quarter_phases_land_at_90_and_270_degrees_of_elongation():
    """The independent check: quarters must sit in the SAME error band as the
    already-verified new and full moons, under a checker built from other
    chapters entirely."""
    worst_nf, worst_q, n = _worst_elongation_errors()
    # Anti-vacuity: the sweep really ran, and the checker is live — its error on
    # the VERIFIED new/full instants must itself be small, or a checker that
    # returned a constant would let anything through.
    assert n == len(range(1900, 2201, 7)) * 13 * 4, (
        f"the sweep examined {n} phases"
    )
    assert 0.0 < worst_nf < 0.03, (
        f"the independent checker is not behaving as calibrated: worst error "
        f"{worst_nf:.4f} deg on new/full instants that are verified to ~26 s"
    )
    assert worst_q <= 2.0 * worst_nf, (
        f"quarter instants sit outside the checker's own noise band: "
        f"quarters {worst_q:.4f} deg vs new/full {worst_nf:.4f} deg"
    )
    assert worst_q <= 0.035, f"worst quarter elongation error {worst_q:.4f} deg"


def test_the_four_phases_of_a_lunation_are_strictly_ordered():
    """new < first quarter < full < last quarter < next new, every lunation,
    with each gap near a quarter of a synodic month. A quarter series that
    computed the wrong phase would break the ORDER, not merely the minute."""
    for year in (1901, 1975, 2026, 2099, 2180):
        k0 = int((year - 2000) * 12.3685)
        for i in range(13):
            j = [_jde(k0 + i + off) for off in (0.0, 0.25, 0.5, 0.75)]
            j.append(_jde(k0 + i + 1.0))
            assert j == sorted(j), f"phases out of order at k={k0 + i}: {j}"
            for a, b in zip(j[:-1], j[1:], strict=True):
                gap = b - a
                # MEASURED, not reasoned: over 1900..2200 the real
                # quarter-lunation interval runs 6.583..8.240 d (the Moon's
                # orbit is elliptical, so the four arcs are unequal and the
                # inequality itself varies). A first draft guessed +-0.8 d of
                # syn/4 and failed against correct code at 8.210 d. The bound
                # below brackets the measured range with ~0.25 d of slack and
                # catches a gross error (a phase computed as the wrong one),
                # never a minute-scale one -- the elongation guard above is
                # what has that resolution.
                assert 6.3 < gap < 8.5, f"gap {gap:.3f} d at k={k0 + i}"


def test_phases_for_year_publishes_all_four_buckets():
    out = phases_for_year(2026)
    for bucket, name in (
        ("new_moons", "new"),
        ("first_quarters", "first_quarter"),
        ("full_moons", "full"),
        ("last_quarters", "last_quarter"),
    ):
        rows = out[bucket]
        assert 11 <= len(rows) <= 14, f"{bucket}: {len(rows)} entries"
        assert all(r["phase"] == name for r in rows), f"{bucket} carries a foreign phase"
        assert rows == sorted(rows, key=lambda r: (r["date"], r["time_utc"]))
        assert all(r["date"].startswith("2026-") for r in rows)


def test_every_year_gets_every_quarter_the_scan_window_is_wide_enough():
    """A phase falling in the first or last days of a year must not be lost to
    the k-scan window. Twelve is the floor for any bucket in any year."""
    for year in (1900, 1999, 2000, 2026, 2100, 2200):
        out = phases_for_year(year)
        for bucket in ("new_moons", "first_quarters", "full_moons", "last_quarters"):
            assert len(out[bucket]) >= 12, f"{year} {bucket}: {len(out[bucket])}"


def test_an_off_grid_k_is_refused_by_name_never_computed_as_a_new_moon():
    """Meeus' series are per-phase; k=3.1 names no phase, so it must raise
    rather than silently return the new-moon answer."""
    import pytest

    with pytest.raises(ValueError, match="multiple of 0.25"):
        _jde(3.1)


def test_the_astronomy_endpoint_publishes_the_four_buckets():
    """A payload field with no reader is a dead end; the reverse — a renderer
    reading a bucket the API never sends — is the same defect pointing the other
    way. Drive the real endpoint and check what it actually carries."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/events/astronomy?year=2026")
        assert r.status_code == 200
        d = r.json()
    for bucket in ("new_moons", "first_quarters", "full_moons", "last_quarters"):
        assert bucket in d and len(d[bucket]) >= 11, f"{bucket}: {d.get(bucket)!r}"
    assert "Meeus" in d["method"]


def test_the_agenda_renders_all_four_phases_and_labels_each_one():
    """The quarters are only recovered if the grid draws them. Both the loader
    and the label map are asserted against the SHIPPED source, sliced through
    js_source_helper (a hand-rolled slice is what the slicing ratchet exists to
    stop), with comments stripped so the guard cannot be satisfied by the
    sentence that explains it."""
    from tests.js_source_helper import array_literal, function_body, read_static, strip_comments

    js = strip_comments(read_static("app-agenda.js"))

    buckets = array_literal(js, "_MOON_BUCKETS")
    for bucket, kind in (
        ("new_moons", "new"),
        ("first_quarters", "first_quarter"),
        ("full_moons", "full"),
        ("last_quarters", "last_quarter"),
    ):
        assert f'"{bucket}"' in buckets, f"{bucket} is not drawn on the agenda grid"
        assert f'"{kind}"' in buckets, f"{kind} has no glyph mapping"
    # Four DISTINCT glyphs: a phase drawn with another phase's symbol is a
    # mislabelled measurement, not a cosmetic slip.
    glyphs = re.findall(r'"\\u\{([0-9A-Fa-f]+)\}"', buckets)
    assert len(glyphs) == 4 and len(set(glyphs)) == 4, f"glyphs: {glyphs}"

    label = function_body(js, "_moonLabel")
    for phrase in ("New moon", "First quarter moon", "Full moon", "Last quarter moon"):
        assert f'"{phrase}"' in label, f"{phrase!r} is not a label the grid can show"

    # Both grids must go through the ONE label map — a second, hand-written
    # ternary is how the month and week views come to disagree about a glyph.
    assert js.count("_moonLabel(moon.kind") == 2, (
        "both the month and the week grid must resolve the phase label through "
        "_moonLabel; found " + str(js.count("_moonLabel(moon.kind"))
    )


def test_every_phase_label_is_translated_in_all_twelve_locales():
    """Chrome ships x12 (informed consent is app-wide). A phase label present in
    en.json alone reddens the i18n gate; asserting it here names the locale."""
    import json
    from pathlib import Path

    locales = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12, f"expected 12 locale files, found {len(files)}"
    for f in files:
        d = json.loads(f.read_text("utf-8"))
        for phrase in ("New moon", "First quarter moon", "Full moon", "Last quarter moon"):
            assert d.get(phrase), f"{f.name} has no translation for {phrase!r}"
