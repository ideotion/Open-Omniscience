"""
Astronomy layer for the agenda: lunar phases by the standard Meeus algorithm.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A reliable LOCAL mathematical model (maintainer-ruled, field report #2):
the four principal lunar phases computed with the standard algorithm from Jean
Meeus, *Astronomical Algorithms* (2nd ed.), chapter 49 — the mean-phase series
plus the periodic and planetary corrections. Zero network, zero data files.

QUARTERS (2026-09-07). The 2026-07-17 ruling retired the `monkeyness-moons`
ICS feed as redundant and recorded ONE accepted loss: that feed carried the
first/last QUARTER phases, which this layer did not compute. It does now, by
the SAME ch. 49 method that was already verified for new/full — chapter 49
gives the quarters their own periodic series plus the ±W term (added at first
quarter, subtracted at last). This closes the loss without re-admitting a
method-unstated feed, which the scope fence forbids.


Honesty notes carried on every result:
  * Accuracy: the truncated series is typically good to ~1–2 minutes; we
    verify against the book's own worked example (49.a) to ≤ 30 s and
    against published almanac dates.
  * Times are TD (Terrestrial Dynamical Time). ΔT (TD−UTC, ≈ 70 s in the
    current era) is NOT applied — stated in the accuracy field rather than
    silently approximated; at day/minute granularity for an agenda this is
    immaterial, and we say so instead of hiding it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import cos, floor, pi, sin
from typing import Any

_METHOD = (
    "Meeus, Astronomical Algorithms (2nd ed.) ch. 49: mean lunar phase + "
    "periodic and planetary corrections; computed locally, no data files"
)
_ACCURACY = (
    "typically within ~2 minutes; times are TD (ΔT≈70 s vs UTC not applied — "
    "immaterial at agenda granularity, stated rather than hidden)"
)

_D2R = pi / 180.0


def _phase_of_k(k: float) -> str:
    """Which of the four principal phases Meeus' ``k`` names.

    The fractional part carries it: .0 new, .25 first quarter, .5 full,
    .75 last quarter. Written as an explicit lookup rather than a chain of
    float comparisons so a caller passing an off-grid k is REFUSED by name
    instead of silently computing a new moon (Meeus' series are per-phase;
    there is no honest answer for k = 3.1).
    """
    frac = round((k - floor(k)) * 4)
    if abs((k - floor(k)) * 4 - frac) > 1e-6 or frac == 4:
        raise ValueError(f"k must be a multiple of 0.25, got {k!r}")
    return ("new", "first_quarter", "full", "last_quarter")[frac]


def _jde_phase(k: float) -> float:
    """JDE (TD) of the lunar phase for Meeus' k (integer = new moon,
    integer + 0.25 = first quarter, + 0.5 = full moon, + 0.75 = last
    quarter)."""
    t = k / 1236.85
    t2, t3, t4 = t * t, t**3, t**4
    jde = (
        2451550.09766
        + 29.530588861 * k
        + 0.00015437 * t2
        - 0.000000150 * t3
        + 0.00000000073 * t4
    )
    e = 1.0 - 0.002516 * t - 0.0000074 * t2
    m = (2.5534 + 29.10535670 * k - 0.0000014 * t2 - 0.00000011 * t3) * _D2R
    mp = (
        201.5643 + 385.81693528 * k + 0.0107582 * t2 + 0.00001238 * t3 - 0.000000058 * t4
    ) * _D2R
    f = (
        160.7108 + 390.67050284 * k - 0.0016118 * t2 - 0.00000227 * t3 + 0.000000011 * t4
    ) * _D2R
    om = (124.7746 - 1.56375588 * k + 0.0020672 * t2 + 0.00000215 * t3) * _D2R

    phase = _phase_of_k(k)
    is_full = phase == "full"
    if phase in ("first_quarter", "last_quarter"):
        # Meeus ch. 49 gives the QUARTERS their own periodic series (not the
        # new/full series with different coefficients), plus the W term below.
        corr = (
            -0.62801 * sin(mp)
            + 0.17172 * e * sin(m)
            - 0.01183 * e * sin(mp + m)
            + 0.00862 * sin(2 * mp)
            + 0.00804 * sin(2 * f)
            + 0.00454 * e * sin(mp - m)
            + 0.00204 * e * e * sin(2 * m)
            - 0.00180 * sin(mp - 2 * f)
            - 0.00070 * sin(mp + 2 * f)
            - 0.00040 * sin(3 * mp)
            - 0.00034 * e * sin(2 * mp - m)
            + 0.00032 * e * sin(m + 2 * f)
            + 0.00032 * e * sin(m - 2 * f)
            - 0.00028 * e * e * sin(mp + 2 * m)
            + 0.00027 * e * sin(2 * mp + m)
            - 0.00017 * sin(om)
            - 0.00005 * sin(mp - m - 2 * f)
            + 0.00004 * sin(2 * mp + 2 * f)
            - 0.00004 * sin(mp + m + 2 * f)
            + 0.00004 * sin(mp - 2 * m)
            + 0.00003 * sin(mp + m - 2 * f)
            + 0.00003 * sin(3 * m)
            + 0.00002 * sin(2 * mp - 2 * f)
            + 0.00002 * sin(mp - m + 2 * f)
            - 0.00002 * sin(3 * mp + m)
        )
        # W: ADDED at first quarter, SUBTRACTED at last (Meeus 49). The sign is
        # the only thing distinguishing the two, and it is worth ~9 minutes, so
        # a flipped sign is a real error rather than a rounding one — the
        # elongation guard in tests/test_astronomy.py is what catches it.
        w = (
            0.00306
            - 0.00038 * e * cos(m)
            + 0.00026 * cos(mp)
            - 0.00002 * cos(mp - m)
            + 0.00002 * cos(mp + m)
            + 0.00002 * cos(2 * f)
        )
        corr += w if phase == "first_quarter" else -w
        return jde + corr + _planetary(k, t)

    if is_full:
        c1, c2, c3 = -0.40614, 0.17302, 0.01614
        c5, c6 = 0.00734, -0.00515
        c7 = 0.00209
    else:  # new moon
        c1, c2, c3 = -0.40720, 0.17241, 0.01608
        c5, c6 = 0.00739, -0.00514
        c7 = 0.00208
    corr = (
        c1 * sin(mp)
        + c2 * e * sin(m)
        + c3 * sin(2 * mp)
        + 0.01039 * sin(2 * f)
        + c5 * e * sin(mp - m)
        + c6 * e * sin(mp + m)
        + c7 * e * e * sin(2 * m)
        - 0.00111 * sin(mp - 2 * f)
        - 0.00057 * sin(mp + 2 * f)
        + 0.00056 * e * sin(2 * mp + m)
        - 0.00042 * sin(3 * mp)
        + 0.00042 * e * sin(m + 2 * f)
        + 0.00038 * e * sin(m - 2 * f)
        - 0.00024 * e * sin(2 * mp - m)
        - 0.00017 * sin(om)
        - 0.00007 * sin(mp + 2 * m)
        + 0.00004 * sin(2 * mp - 2 * f)
        + 0.00004 * sin(3 * m)
        + 0.00003 * sin(mp + m - 2 * f)
        + 0.00003 * sin(2 * mp + 2 * f)
        - 0.00003 * sin(mp + m + 2 * f)
        + 0.00003 * sin(mp - m + 2 * f)
        - 0.00002 * sin(mp - m - 2 * f)
        - 0.00002 * sin(3 * mp + m)
        + 0.00002 * sin(4 * mp)
    )
    # The full-moon series uses 0.01043 sin 2F (vs 0.01039 for new) — Meeus.
    if is_full:
        corr += (0.01043 - 0.01039) * sin(2 * f)

    return jde + corr + _planetary(k, t)


def _planetary(k: float, t: float) -> float:
    """The A1..A14 planetary corrections (Meeus ch. 49) — the same for ALL four
    phases, which is why they live here rather than being copied per branch."""
    t2k = t * t
    a = [
        (0.000325, 299.77 + 0.107408 * k - 0.009173 * t2k),
        (0.000165, 251.88 + 0.016321 * k),
        (0.000164, 251.83 + 26.651886 * k),
        (0.000126, 349.42 + 36.412478 * k),
        (0.000110, 84.66 + 18.206239 * k),
        (0.000062, 141.74 + 53.303771 * k),
        (0.000060, 207.14 + 2.453732 * k),
        (0.000056, 154.84 + 7.306860 * k),
        (0.000047, 34.52 + 27.261239 * k),
        (0.000042, 207.19 + 0.121824 * k),
        (0.000040, 291.34 + 1.844379 * k),
        (0.000037, 161.72 + 24.198154 * k),
        (0.000035, 239.56 + 25.513099 * k),
        (0.000023, 331.55 + 3.592518 * k),
    ]
    return sum(coef * sin(angle * _D2R) for coef, angle in a)


def _jde_to_datetime(jde: float) -> datetime:
    """JDE → naive-UTC datetime (TD; ΔT not applied — see module notes)."""
    j = jde + 0.5
    z = floor(j)
    fpart = j - z
    if z < 2299161:
        a_ = z
    else:
        alpha = floor((z - 1867216.25) / 36524.25)
        a_ = z + 1 + alpha - floor(alpha / 4)
    b = a_ + 1524
    c = floor((b - 122.1) / 365.25)
    d = floor(365.25 * c)
    e_ = floor((b - d) / 30.6001)
    day = b - d - floor(30.6001 * e_) + fpart
    month = e_ - 1 if e_ < 14 else e_ - 13
    year = c - 4716 if month > 2 else c - 4715
    day_int = int(day)
    frac = day - day_int
    return datetime(int(year), int(month), day_int, tzinfo=UTC) + timedelta(days=frac)


# The four principal phases: Meeus' k offset -> the payload bucket that carries
# it. Ordered by offset so a bucket can never be filed under another's phase name.
_PHASE_BUCKETS = (
    (0.0, "new_moons", "new"),
    (0.25, "first_quarters", "first_quarter"),
    (0.5, "full_moons", "full"),
    (0.75, "last_quarters", "last_quarter"),
)


def phases_for_year(year: int) -> dict:
    """The four principal lunar phases of a calendar year (UTC), with
    method+accuracy.

    Buckets: ``new_moons`` · ``first_quarters`` · ``full_moons`` ·
    ``last_quarters``. The quarters were an ACCEPTED LOSS when the redundant
    moons ICS feed was retired (ruling 2026-07-17) and are computed here by the
    same verified ch. 49 method — never re-imported from a method-unstated feed.
    """
    out: dict = {"year": year, "method": _METHOD, "accuracy": _ACCURACY}
    for _off, bucket, _name in _PHASE_BUCKETS:
        out[bucket] = []
    # Scan from one lunation BEFORE the year and run past its end, so a phase
    # falling in the first or last days of the year cannot be missed; the
    # year filter below is what decides membership, so a wider scan can only
    # ever find more of the same year and never duplicates a k.
    k0 = floor((year - 2000) * 12.3685) - 2
    for i in range(18):
        for offset, bucket, name in _PHASE_BUCKETS:
            k = k0 + i + offset
            dt = _jde_to_datetime(_jde_phase(k))
            if dt.year == year:
                out[bucket].append(
                    {
                        "date": dt.date().isoformat(),
                        "time_utc": dt.strftime("%H:%M"),
                        "phase": name,
                    }
                )
    for _off, bucket, _name in _PHASE_BUCKETS:
        out[bucket].sort(key=lambda p: (p["date"], p["time_utc"]))
    return out


# --------------------------------------------------------------------------- #
# Seasons: equinoxes & solstices (Meeus ch. 27, the higher-accuracy method).
# HEMISPHERE HONESTY (maintainer-ruled 2026-06-12): the events are named
# astronomically — "March equinox", "June solstice" — never "spring/summer",
# because the seasons are OPPOSITE across hemispheres and undefined at the
# equator. Hemisphere-specific season names are a display layer, not data.
# --------------------------------------------------------------------------- #

_SEASON_TERMS = (
    (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
    (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
    (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
    (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
    (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
)

_SEASON_POLY = {
    "march_equinox": (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
    "june_solstice": (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),
    "september_equinox": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
    "december_solstice": (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),
}


def _jde_season(year: int, which: str) -> float:
    from math import cos

    a0, a1, a2, a3, a4 = _SEASON_POLY[which]
    y = (year - 2000) / 1000.0
    jde0 = a0 + a1 * y + a2 * y * y + a3 * y**3 + a4 * y**4
    t = (jde0 - 2451545.0) / 36525.0
    w = (35999.373 * t - 2.47) * _D2R
    dlam = 1 + 0.0334 * cos(w) + 0.0007 * cos(2 * w)
    s = sum(a * cos((b + c * t) * _D2R) for a, b, c in _SEASON_TERMS)
    return jde0 + (0.00001 * s) / dlam


def seasons_for_year(year: int) -> dict:
    """The four season points of a year (UTC), hemisphere-neutrally named."""
    out: dict[str, Any] = {"year": year, "seasons": [], "method": _METHOD.replace("ch. 49", "ch. 27"),
           "accuracy": _ACCURACY,
           "naming": (
               "astronomical names only — 'June solstice', never 'summer "
               "solstice': seasons are opposite across hemispheres and "
               "undefined at the equator; hemisphere labels are display-side"
           )}
    for which in ("march_equinox", "june_solstice", "september_equinox", "december_solstice"):
        dt = _jde_to_datetime(_jde_season(year, which))
        out["seasons"].append(
            {"event": which, "date": dt.date().isoformat(), "time_utc": dt.strftime("%H:%M")}
        )
    return out


def lunar_phase_series(start: str, end: str) -> dict:
    """Daily lunar-phase series for correlation studies (maintainer concept
    2026-06-12: let users TEST moon-effect beliefs against their own data).

    Per day: synodic age (days since new moon), illuminated fraction by the
    age approximation, and the waxing/waning flag. METHOD HONESTY: the
    fraction uses (1 - cos(2π·age/29.53))/2 — the standard synodic-age
    approximation, within ~2% of the true illuminated fraction; exact values
    need the full solar/lunar position theory (Meeus ch. 48). Good enough
    for daily-granularity correlation, and the method note says exactly this.
    The SERIES asserts nothing about effects: it is one honest variable for
    the analysis tools, which carry their own correlation≠causation and
    multiple-comparisons caveats.
    """
    from datetime import date as _date
    from math import cos

    d0 = _date.fromisoformat(start)
    d1 = _date.fromisoformat(end)
    if d1 < d0:
        d0, d1 = d1, d0
    # New moons spanning the window (with margin), from the verified engine.
    k0 = floor((d0.year - 2000) * 12.3685) - 2
    k1 = floor((d1.year - 2000) * 12.3685) + 3
    new_moons = [_jde_to_datetime(_jde_phase(float(k))) for k in range(k0, k1 + 1)]
    days = []
    cur = d0
    syn = 29.530588861
    while cur <= d1:
        noon = datetime(cur.year, cur.month, cur.day, 12, tzinfo=UTC)
        prev = max((nm for nm in new_moons if nm <= noon), default=None)
        if prev is None:
            cur += timedelta(days=1)
            continue
        age = (noon - prev).total_seconds() / 86400.0
        frac = (1 - cos(2 * pi * age / syn)) / 2
        days.append(
            {
                "date": cur.isoformat(),
                "age_days": round(age, 2),
                "illuminated_fraction": round(frac, 3),
                "waxing": age <= syn / 2,
            }
        )
        cur += timedelta(days=1)
    return {
        "start": d0.isoformat(),
        "end": d1.isoformat(),
        "days": days,
        "method": (
            "synodic age from Meeus-computed new moons; illuminated fraction "
            "by the age approximation (1-cos(2π·age/29.53))/2, within ~2% of "
            "the true fraction — exact values need full position theory "
            "(Meeus ch. 48); waxing = first half of the synodic cycle"
        ),
        "caveat": (
            "a variable for correlation studies — co-occurrence is never "
            "causation, and screening many series against the moon WILL "
            "produce spurious hits without multiple-comparisons control"
        ),
    }
