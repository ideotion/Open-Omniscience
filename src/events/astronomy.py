"""
Astronomy layer for the agenda: lunar phases by the standard Meeus algorithm.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A reliable LOCAL mathematical model (maintainer-ruled, field report #2):
full/new moons computed with the standard algorithm from Jean Meeus,
*Astronomical Algorithms* (2nd ed.), chapter 49 — the mean-phase series plus
the periodic and planetary corrections. Zero network, zero data files.

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
from math import floor, pi, sin

_METHOD = (
    "Meeus, Astronomical Algorithms (2nd ed.) ch. 49: mean lunar phase + "
    "periodic and planetary corrections; computed locally, no data files"
)
_ACCURACY = (
    "typically within ~2 minutes; times are TD (ΔT≈70 s vs UTC not applied — "
    "immaterial at agenda granularity, stated rather than hidden)"
)

_D2R = pi / 180.0


def _jde_phase(k: float) -> float:
    """JDE (TD) of the lunar phase for Meeus' k (integer = new moon,
    integer + 0.5 = full moon)."""
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

    is_full = abs(k - floor(k) - 0.5) < 1e-9
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

    # Planetary corrections (A1..A14) — needed for the ~minutes accuracy class.
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
    add = sum(coef * sin(angle * _D2R) for coef, angle in a)
    return jde + corr + add


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


def phases_for_year(year: int) -> dict:
    """All full and new moons of a calendar year (UTC), with method+accuracy."""
    out: dict = {"year": year, "full_moons": [], "new_moons": [], "method": _METHOD,
                 "accuracy": _ACCURACY}
    k0 = floor((year - 2000) * 12.3685) - 1
    for i in range(16):
        for offset, bucket in ((0.0, "new_moons"), (0.5, "full_moons")):
            k = k0 + i + offset
            dt = _jde_to_datetime(_jde_phase(k))
            if dt.year == year:
                out[bucket].append(
                    {
                        "date": dt.date().isoformat(),
                        "time_utc": dt.strftime("%H:%M"),
                        "phase": "full" if offset else "new",
                    }
                )
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
    out = {"year": year, "seasons": [], "method": _METHOD.replace("ch. 49", "ch. 27"),
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
