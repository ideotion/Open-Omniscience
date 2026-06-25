"""
Revision-anomaly detector over StatFigure vintages (Group N, the reliable-memory kernel).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The project's deepest intention is reliable memory: digital data is editable by nature, and
History must not be silently rewritten. Official statistics ARE rewritten — every vintage is
a chance to move a previously-published figure. This module flags, RETROSPECTIVELY, when the
most recent vintage moved a PAST figure by an amount unusually large for that observation's
OWN revision history.

It is PURE and MODEL-FREE: it reads a list of :class:`~src.stats.sdmx.StatFigure` vintages
(several ``extracted_at`` observations of the same cell, as ``store.store_figures`` preserves
them) and a robust statistic — never a forecast, never a learned model, never the network.

HONESTY (the §7 non-negotiables + the manipulation-card doctrine, enforced in code):
  * RETROSPECTIVE ONLY — it compares the latest revision against the cell's EARLIER
    revisions; it never predicts a future value and the band never crosses the last
    observation (it has no band — it characterises what already happened);
  * NAME THE SHAPE, NEVER THE INTENT — it flags "an outlier-sized revision for this series",
    never a claim the change was wrong or deliberate; the innocent twin (a scheduled
    benchmark / methodology update, a late source, a correction) is stated in the caveat;
  * the signal carries its COMPONENTS (from/to value, the change, the cell's median ± MAD
    revision, the robust z) — NEVER a composite score;
  * a thin history or a perfectly-uniform revision spread degrades to SILENCE — with no
    robust scale we make no claim, rather than guess a tail.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from src.stats.sdmx import StatFigure

_MAD_TO_SIGMA = 1.4826  # consistency constant: MAD → σ for a normal distribution


@dataclass(frozen=True)
class RevisionAnomaly:
    """One observation whose most recent revision is an outlier vs its own history."""

    agency: str
    series_id: str
    ref_area: str
    time_period: str  # the PAST period whose published figure was revised
    from_value: float  # the previously-published value
    to_value: float  # the value the newest vintage published
    revised_at: str  # the extracted_at of the revising vintage
    abs_change: float  # |to - from| (magnitude is direction-agnostic; from/to show direction)
    rel_change: float | None  # abs_change / |from_value|, or None when from_value == 0
    n_prior_revisions: int  # how many earlier revisions characterise the baseline
    median_prior_abs: float  # the cell's typical revision magnitude
    mad_prior_abs: float  # the robust spread of its prior revisions
    robust_z: float  # (abs_change − median) / (1.4826 · MAD) — the anomaly measure

    def to_dict(self) -> dict:
        return {
            "agency": self.agency,
            "series_id": self.series_id,
            "ref_area": self.ref_area,
            "time_period": self.time_period,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "revised_at": self.revised_at,
            "abs_change": self.abs_change,
            "rel_change": round(self.rel_change, 6) if self.rel_change is not None else None,
            "n_prior_revisions": self.n_prior_revisions,
            "median_prior_abs": self.median_prior_abs,
            "mad_prior_abs": self.mad_prior_abs,
            "robust_z": round(self.robust_z, 4),
        }


_CAVEAT = (
    "A recent vintage moved this past official figure by an amount unusually large for this "
    "series' own revision history. Revisions are normal and usually legitimate — a scheduled "
    "benchmark or methodology update, a late-arriving source, or a correction can move a "
    "figure substantially. This names the shape (an outlier-sized revision for this series), "
    "never a claim the change was wrong or deliberate; read the producer's revision notes "
    "and judge."
)


def find_revision_anomalies(
    figures: list[StatFigure],
    *,
    min_prior_revisions: int = 4,
    z_min: float = 3.5,
    max_items: int = 50,
) -> dict:
    """Flag observations whose most recent revision is a robust outlier vs their own history.

    Groups the vintages by observation (agency · series · area · period); within each, orders
    them oldest → newest by ``extracted_at``, keeps the numeric values, and collapses a run of
    identical re-published values (a no-change re-fetch is not a revision). The magnitude of
    the LATEST revision is compared to the robust spread (median ± MAD) of the EARLIER
    revisions and flagged at ``robust_z >= z_min`` when at least ``min_prior_revisions`` earlier
    revisions exist and they show a non-zero spread (else: silence — no robust basis). Returns
    a plain dict; counts/magnitudes only, no score.
    """
    cells: dict[tuple[str, str, str, str], list[StatFigure]] = {}
    for f in figures:
        cells.setdefault((f.agency, f.series_id, f.ref_area, f.time_period), []).append(f)

    items: list[RevisionAnomaly] = []
    for (agency, series_id, ref_area, time_period), group in cells.items():
        ordered = sorted(group, key=lambda f: f.extracted_at)
        # The revision trail: numeric values only, consecutive duplicates collapsed.
        points: list[tuple[str, float]] = []
        for f in ordered:
            if f.value is None:
                continue  # a published gap breaks no chain — we revise between numbers
            if not points or points[-1][1] != f.value:
                points.append((f.extracted_at, f.value))
        if len(points) < 2:
            continue  # no revision at all

        changes = [abs(points[i][1] - points[i - 1][1]) for i in range(1, len(points))]
        latest_abs = changes[-1]
        prior = changes[:-1]
        if len(prior) < min_prior_revisions:
            continue  # too thin a history to characterise a tail

        med = median(prior)
        mad = median([abs(c - med) for c in prior])
        if mad <= 0:
            continue  # zero observed spread — no robust scale, stay silent
        robust_z = (latest_abs - med) / (_MAD_TO_SIGMA * mad)
        if robust_z < z_min:
            continue

        from_value = points[-2][1]
        to_value = points[-1][1]
        items.append(
            RevisionAnomaly(
                agency=agency,
                series_id=series_id,
                ref_area=ref_area,
                time_period=time_period,
                from_value=from_value,
                to_value=to_value,
                revised_at=points[-1][0],
                abs_change=latest_abs,
                rel_change=(latest_abs / abs(from_value)) if from_value != 0 else None,
                n_prior_revisions=len(prior),
                median_prior_abs=med,
                mad_prior_abs=mad,
                robust_z=robust_z,
            )
        )

    items.sort(key=lambda a: (a.robust_z, a.abs_change), reverse=True)
    items = items[:max_items]

    return {
        "anomalies": [a.to_dict() for a in items],
        "count": len(items),
        "min_prior_revisions": min_prior_revisions,
        "z_min": z_min,
        "method": (
            "Per observation (agency · series · area · period), compares the magnitude of the "
            "MOST RECENT revision (the change the newest vintage made to the previously-"
            "published value) against the robust spread (median ± MAD) of that observation's "
            f"own EARLIER revisions. Flags at robust z >= {z_min} with >= {min_prior_revisions} "
            "earlier revisions of non-zero spread (a thin or uniform history degrades to "
            "silence). Retrospective only — it never predicts a future value; magnitude is "
            "direction-agnostic (the from/to values show direction). Magnitudes only, no score."
        ),
        "caveat": _CAVEAT,
    }
