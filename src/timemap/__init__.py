"""Temporal map — space-time signals on one zoomable world map + time slider.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A journalist works on two axes at once: *where* and *when*. This package
normalises every locatable, datable signal — curated historical anchors, the
recurring events agenda, live geophysical hazards, and (later) geocoded corpus
articles — into one shape ``{lat, lon, t, ...}`` so they can share a map and a
single time axis that runs from antiquity to the near future.

Honest by construction: only signals that have *both* a coordinate and a date
appear. A signal with no coordinate is not silently dropped onto (0, 0); it is
simply absent — and the UI says so. ``t`` is a fractional year (e.g. 79.81,
2001.69) so the slider can span two millennia without fighting JavaScript's
shaky parsing of pre-1000 dates.
"""

from __future__ import annotations

from datetime import date


def year_float(d: date) -> float:
    """A continuous, sortable position on the time axis: year + fraction-of-year.

    79.81 ≈ late 79 CE, 2001.69 ≈ 11 Sep 2001. Monotonic within a year and across
    years, which is all the slider needs (it is not a precise duration measure).
    """
    jan1 = date(d.year, 1, 1)
    days_in_year = (date(d.year, 12, 31) - jan1).days + 1
    return d.year + (d - jan1).days / days_in_year
