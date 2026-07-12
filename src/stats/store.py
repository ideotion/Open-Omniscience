"""Durable storage + honest comparison for official statistics (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This persists the value objects produced by ``src.stats.sdmx`` / ``src.stats.fetch``
(``StatFigure``) into the durable ``stat_figures`` table, and reads them back for the
analysis surfaces. It is network-free: the caller fetches; this only stores + queries.

HONESTY (the Group N ruling, enforced in code, not just prose):
  * VINTAGES are first-class — a re-fetch at a later ``extracted_at`` is a NEW row,
    never an overwrite (``store_figures`` is idempotent per vintage, additive across
    vintages). A revision is preserved as evidence, like law/wiki versioning.
  * a published gap is stored as ``value=None`` (degrade loudly, never a fabricated 0)
    and is never dropped — ``store_figures`` counts gaps separately so the caller can
    say so.
  * TRIANGULATION puts producers SIDE BY SIDE and NEVER averages them; it flags
    incomparable denominators (different ``unit`` / ``adjustment`` SA-NSA /
    ``base_year``) instead of silently combining. Cross-agency series EQUIVALENCE is
    NOT inferred (that would fabricate a mapping) — triangulation compares the SAME
    ``series_id`` as reported by one or more producers; the caller asserts which series
    are comparable.
  * NO composite score / ranking / verdict anywhere — only observed values + trail.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.catalog.countries import to_iso2
from src.database.models import StatFigure as StatFigureRow
from src.stats.revision import find_revision_anomalies
from src.stats.sdmx import StatFigure
from src.stats.series import _parse_period, to_chart_series


def store_figures(session: Session, figures: Iterable[StatFigure]) -> dict:
    """Persist parsed ``StatFigure`` value objects, idempotent per vintage.

    A row already present at the SAME vintage (agency, series_id, ref_area,
    time_period, extracted_at) is skipped — re-storing the same fetch is a no-op. A
    DIFFERENT vintage of the same observation is a new row (revisions preserved). The
    caller owns the transaction (the single-writer gate serialises the flush); we do
    NOT commit here. Returns a tally: ``{stored, duplicate, gaps}`` (``gaps`` =
    stored rows whose published value was a gap, ``value=None`` — reported, not hidden).
    """
    stored = duplicate = gaps = 0
    for fig in figures:
        exists = session.execute(
            select(StatFigureRow.id).where(
                StatFigureRow.agency == fig.agency,
                StatFigureRow.series_id == fig.series_id,
                StatFigureRow.ref_area == fig.ref_area,
                StatFigureRow.time_period == fig.time_period,
                StatFigureRow.extracted_at == fig.extracted_at,
            ).limit(1)
        ).first()
        if exists:
            duplicate += 1
            continue
        session.add(
            StatFigureRow(
                agency=fig.agency,
                series_id=fig.series_id,
                ref_area=fig.ref_area,
                time_period=fig.time_period,
                value=fig.value,
                unit=fig.unit,
                methodology_ref=fig.methodology_ref,
                adjustment=fig.adjustment,
                base_year=fig.base_year,
                extracted_at=fig.extracted_at,
            )
        )
        stored += 1
        if fig.value is None:
            gaps += 1
    session.flush()
    return {"stored": stored, "duplicate": duplicate, "gaps": gaps}


def _row_dict(r: StatFigureRow) -> dict:
    return {
        "agency": r.agency,
        "series_id": r.series_id,
        "ref_area": r.ref_area,
        "time_period": r.time_period,
        "value": r.value,
        "unit": r.unit,
        "methodology_ref": r.methodology_ref,
        "adjustment": r.adjustment,
        "base_year": r.base_year,
        "extracted_at": r.extracted_at,
    }


def _latest_vintage(rows: list[StatFigureRow]) -> dict[tuple, StatFigureRow]:
    """Keep only the latest ``extracted_at`` per (agency, series, area, period).

    ISO-8601 strings sort lexicographically in time order, so ``max`` on the string is
    the latest vintage — no parsing needed.
    """
    best: dict[tuple, StatFigureRow] = {}
    for r in rows:
        key = (r.agency, r.series_id, r.ref_area, r.time_period)
        cur = best.get(key)
        if cur is None or r.extracted_at > cur.extracted_at:
            best[key] = r
    return best


def list_figures(
    session: Session,
    *,
    agency: str | None = None,
    series_id: str | None = None,
    ref_area: str | None = None,
    latest_vintage_only: bool = True,
    limit: int = 500,
) -> dict:
    """A filterable read over stored figures (the analysis-window/registered view).

    Filters are exact-match (case-insensitive for agency/area). ``latest_vintage_only``
    (default) collapses to the most recent vintage per observation; pass ``False`` to
    see every vintage (the revision history). Counts only, never a score; the
    ``method``/``caveat`` travel with the result.
    """
    q = select(StatFigureRow)
    if agency:
        q = q.where(StatFigureRow.agency == agency.strip().lower())
    if series_id:
        q = q.where(StatFigureRow.series_id == series_id.strip())
    if ref_area:
        q = q.where(StatFigureRow.ref_area == ref_area.strip().upper())
    rows = list(session.execute(q).scalars())
    if latest_vintage_only:
        rows = list(_latest_vintage(rows).values())
    # Stable, useful ordering: area, then period descending (newest period first).
    rows.sort(key=lambda r: (r.ref_area, r.time_period), reverse=False)
    total = len(rows)
    rows = rows[: max(0, int(limit))]
    return {
        "count": total,
        "shown": len(rows),
        "figures": [_row_dict(r) for r in rows],
        "method": "Stored official-statistics observations; latest vintage per series unless history requested.",
        "caveat": (
            "Each figure is a STANCED producer's published value (never a credibility "
            "score). A None value is a published gap, not zero. Producers are shown, "
            "never averaged."
        ),
    }


def minerals_supply_summary(session: Session, *, limit: int = 4000) -> dict:
    """USGS Mineral Commodity Summaries SUPPLY figures grouped by commodity → measure.

    The honest home for rare earths and other minerals that have NO free spot-price source
    (the B12 ruling): SUPPLY data — mine production, reserves, net-import-reliance — never
    market prices. Reads the ``us-usgs`` figures (latest vintage per observation) and groups
    them for a board; a ``None`` value is a published gap, kept. Degrades LOUDLY when no
    figures are stored yet (``available: false`` + a reason pointing at the operator fetch),
    so an empty board never looks like "no supply" — it looks like "not fetched yet". No
    score, producers never averaged.
    """
    data = list_figures(
        session, agency="us-usgs", latest_vintage_only=True, limit=limit
    )
    commodities: dict[str, dict] = {}
    for f in data["figures"]:
        commodity, _, measure = str(f["series_id"]).partition(":")
        c = commodities.setdefault(
            commodity, {"commodity": commodity, "measures": {}}
        )
        c["measures"].setdefault(measure, []).append(
            {
                "ref_area": f["ref_area"],
                "time_period": f["time_period"],
                "value": f["value"],
                "unit": f["unit"],
            }
        )
    out = sorted(commodities.values(), key=lambda x: x["commodity"])
    return {
        "available": bool(out),
        "commodities": out,
        "method": (
            "USGS Mineral Commodity Summaries — annual supply statistics, latest vintage "
            "per observation, grouped by commodity and measure."
        ),
        "caveat": (
            "SUPPLY data — production, reserves, net-import-reliance. NOT market prices: "
            "no free rare-earth spot-price source exists and none is fabricated here. A "
            "None value is a published gap. Producers are shown, never averaged."
        ),
        "reason": (
            None
            if out
            else "No USGS supply figures stored yet — run the USGS MCS fetch (operator step)."
        ),
    }


def vintages_for(
    session: Session, *, agency: str, series_id: str, ref_area: str, time_period: str
) -> dict:
    """Every stored VINTAGE of one observation, oldest → newest (the revision trail).

    Statistics get revised; each revision is evidence. This returns the full list so a
    surface can show how a producer's figure for a period changed over time — never
    collapsing them, never picking a "true" one.
    """
    rows = list(
        session.execute(
            select(StatFigureRow).where(
                StatFigureRow.agency == agency.strip().lower(),
                StatFigureRow.series_id == series_id.strip(),
                StatFigureRow.ref_area == ref_area.strip().upper(),
                StatFigureRow.time_period == time_period.strip(),
            )
        ).scalars()
    )
    rows.sort(key=lambda r: r.extracted_at)
    return {
        "agency": agency.strip().lower(),
        "series_id": series_id.strip(),
        "ref_area": ref_area.strip().upper(),
        "time_period": time_period.strip(),
        "count": len(rows),
        "vintages": [
            {"extracted_at": r.extracted_at, "value": r.value, "unit": r.unit,
             "adjustment": r.adjustment, "base_year": r.base_year}
            for r in rows
        ],
        "caveat": "Revisions are preserved as evidence; no vintage is treated as the single truth.",
    }


def revision_anomalies(
    session: Session,
    *,
    agency: str | None = None,
    series_id: str | None = None,
    ref_area: str | None = None,
    min_prior_revisions: int = 4,
    z_min: float = 3.5,
    max_items: int = 50,
) -> dict:
    """Flag observations whose MOST RECENT vintage revised a past figure unusually far.

    Loads the FULL vintage trail (every ``extracted_at`` for the matching figures — never
    latest-only, the revision history is the whole point) and runs the pure, model-free
    :func:`~src.stats.revision.find_revision_anomalies` over it. The reliable-memory check:
    History must not be silently rewritten. Retrospective only; magnitudes only, no score.
    """
    q = select(StatFigureRow)
    if agency:
        q = q.where(StatFigureRow.agency == agency.strip().lower())
    if series_id:
        q = q.where(StatFigureRow.series_id == series_id.strip())
    if ref_area:
        q = q.where(StatFigureRow.ref_area == ref_area.strip().upper())
    figures = [StatFigure(**_row_dict(r)) for r in session.execute(q).scalars()]
    return find_revision_anomalies(
        figures,
        min_prior_revisions=min_prior_revisions,
        z_min=z_min,
        max_items=max_items,
    )


def chart_series(
    session: Session, *, series_id: str, ref_area: str, agency: str | None = None
) -> dict:
    """An honest, comparability-segmented time series for ONE (series_id, ref_area) — the
    feed for a stat chart. Loads the matching stored figures (every vintage; the adapter
    keeps the latest per period), adapts them to StatFigures, and runs the pure
    :func:`~src.stats.series.to_chart_series`: a new line SEGMENT at every unit / base-year /
    SA-NSA change (never joined across a break), a published gap kept as ``None`` (the chart
    breaks the line, never interpolates), unparseable periods surfaced. Counts only, no score.

    Optionally scope by ``agency`` — omit it only when a single producer publishes this
    series for this area, since interleaving producers would mix their vintages (use the
    /triangulate endpoint to compare producers side by side instead).
    """
    sid = series_id.strip()
    area = ref_area.strip().upper()
    q = select(StatFigureRow).where(
        StatFigureRow.series_id == sid, StatFigureRow.ref_area == area
    )
    if agency:
        q = q.where(StatFigureRow.agency == agency.strip().lower())
    figures = [StatFigure(**_row_dict(r)) for r in session.execute(q).scalars()]
    return to_chart_series(figures, ref_area=area, series_id=sid)


def _period_key(label: str) -> float:
    """A period label → a sortable decimal-year (unparseable → -inf, sorts oldest)."""
    pos = _parse_period(label)[0]
    return pos if pos is not None else float("-inf")


def _area_more_recent(a: StatFigureRow, b: StatFigureRow) -> bool:
    """Is figure ``a`` the one to show for its area over ``b``? Later period wins; a tie
    on period falls back to the later vintage. Deterministic, no fabricated ordering."""
    ka, kb = _period_key(a.time_period), _period_key(b.time_period)
    if ka != kb:
        return ka > kb
    return a.extracted_at > b.extracted_at


def map_figures(
    session: Session,
    *,
    series_id: str,
    agency: str | None = None,
    time_period: str | None = None,
    limit: int = 2000,
) -> dict:
    """Latest-vintage figures for ONE series across all areas — the CHOROPLETH feed.

    Returns ONE cell per ``ref_area`` (the area's latest period, or ``time_period`` if
    pinned), each carrying the producer's published value + its comparability fields
    (unit / base_year / adjustment). The frontend ``ooViz.choroplethData`` applies the
    honesty gate over these cells: an area on a DIFFERENT (unit, base-year, seasonal-
    adjustment) basis is shown as no-data (NEVER recoloured to one scale), a missing
    value is no-data (never zero), and a LEVEL indicator is shown as proportional
    symbols, not colour.

    A map is SINGLE-PRODUCER per series: when several agencies report this series and no
    ``agency`` is pinned, the most recent VINTAGE is shown per area and ``multi_producer``
    is flagged so the caller can pin an agency — the map NEVER averages producers and
    never elects a 'true' one silently. ``periods`` / ``agencies`` are returned so a
    surface can offer a period / producer selector. Counts only, NO score.
    """
    sid = series_id.strip()
    q = select(StatFigureRow).where(StatFigureRow.series_id == sid)
    if agency:
        q = q.where(StatFigureRow.agency == agency.strip().lower())
    if time_period:
        q = q.where(StatFigureRow.time_period == time_period.strip())
    rows = list(_latest_vintage(list(session.execute(q).scalars())).values())

    agencies = sorted({r.agency for r in rows})
    periods = sorted({r.time_period for r in rows}, key=lambda p: (_period_key(p), p), reverse=True)

    # One cell per area: the latest period (tie → latest vintage).
    best: dict[str, StatFigureRow] = {}
    for r in rows:
        cur = best.get(r.ref_area)
        if cur is None or _area_more_recent(r, cur):
            best[r.ref_area] = r
    # Each cell carries an ``iso2`` (lowercase alpha-2) so a map renderer can key on it
    # WITHOUT a frontend ISO bridge — the producer's ref_area (often alpha-3 for WB/OWID)
    # is converted; a non-country aggregate (WLD/EUU/…) → None, which the map drops
    # honestly (never plotted as if it were a country).
    cells = []
    for r in best.values():
        cell = _row_dict(r)
        cell["iso2"] = to_iso2(r.ref_area)
        cells.append(cell)
    cells.sort(key=lambda c: c["ref_area"])
    total = len(cells)
    cells = cells[: max(0, int(limit))]
    return {
        "series_id": sid,
        "agency": agency.strip().lower() if agency else None,
        "time_period": time_period.strip() if time_period else None,
        "cells": cells,
        "count": total,
        "shown": len(cells),
        "periods": periods,
        "agencies": agencies,
        "multi_producer": agency is None and len(agencies) > 1,
        "method": (
            "Latest-vintage figure per area for one series (the area's latest period "
            "unless a period is pinned). The map's comparability gate (frontend) shows "
            "areas on a different basis as no-data; a level is shown as proportional symbols."
        ),
        "caveat": (
            "Each cell is a producer's published value, never a score. Areas on a "
            "different unit / base year / seasonal adjustment are shown as no-data on the "
            "map (never recoloured to one scale); a None value is a published gap, not "
            "zero. When several producers report this series, pin an agency — the map "
            "never averages producers."
        ),
    }


# --------------------------------------------------------------------------- #
# Triangulation — side by side, NEVER averaged.
# --------------------------------------------------------------------------- #
def _comparability(figs: list[dict]) -> dict:
    """Flag whether figures shown together share a comparable denominator.

    Compares the distinct (unit, adjustment, base_year) tuples among the producers in
    one (area, period) cell. >1 distinct tuple ⇒ NOT directly comparable, with the
    differing dimension(s) named. We NEVER reconcile or average — we surface the
    mismatch so the reader does not compare incomparable numbers.
    """
    units = {f["unit"] for f in figs if f["value"] is not None}
    adjustments = {f["adjustment"] for f in figs if f["value"] is not None}
    base_years = {f["base_year"] for f in figs if f["value"] is not None}
    reasons: list[str] = []
    if len(units) > 1:
        reasons.append("unit")
    if len(adjustments) > 1:
        reasons.append("seasonal_adjustment")
    if len(base_years) > 1:
        reasons.append("base_year")
    return {
        "comparable": not reasons,
        "differs_on": reasons,
        # When a comparability field is unstated (None) across producers we cannot
        # confirm comparability — say so rather than assume it.
        "unstated": sorted(
            dim for dim, vals in (
                ("unit", units), ("seasonal_adjustment", adjustments), ("base_year", base_years)
            ) if None in vals
        ),
    }


def triangulate(
    session: Session,
    *,
    series_id: str,
    ref_area: str | None = None,
    time_period: str | None = None,
    agencies: list[str] | None = None,
) -> dict:
    """Show the SAME ``series_id`` as reported by one or more producers, side by side.

    Groups the latest-vintage figures by (ref_area, time_period); within each cell the
    producers are listed side by side with a comparability verdict (do they share unit /
    seasonal-adjustment / base year?). Producers are NEVER averaged or reconciled — the
    reader compares (or declines to) with the mismatch named.

    Cross-AGENCY series equivalence is intentionally NOT inferred (World Bank's
    ``NY.GDP.MKTP.CD`` and Eurostat's ``nama_10_gdp`` are not auto-equated — that would
    fabricate a mapping). This compares the literal same ``series_id`` value; pass
    ``agencies`` to restrict which producers are included.
    """
    q = select(StatFigureRow).where(StatFigureRow.series_id == series_id.strip())
    if ref_area:
        q = q.where(StatFigureRow.ref_area == ref_area.strip().upper())
    if time_period:
        q = q.where(StatFigureRow.time_period == time_period.strip())
    if agencies:
        q = q.where(StatFigureRow.agency.in_([a.strip().lower() for a in agencies]))
    rows = list(_latest_vintage(list(session.execute(q).scalars())).values())

    cells: dict[tuple, list[dict]] = {}
    for r in rows:
        cells.setdefault((r.ref_area, r.time_period), []).append(_row_dict(r))

    out = []
    for (area, period), figs in sorted(cells.items()):
        figs.sort(key=lambda f: f["agency"])
        out.append({
            "ref_area": area,
            "time_period": period,
            "producers": figs,
            "n_producers": len({f["agency"] for f in figs}),
            "comparability": _comparability(figs),
        })
    return {
        "series_id": series_id.strip(),
        "cells": out,
        "count": len(out),
        "method": (
            "Latest vintage of the literal series_id, grouped by area+period; producers "
            "side by side. Same series_id only — cross-agency equivalence is not inferred."
        ),
        "caveat": (
            "Producers are shown SIDE BY SIDE, never averaged. A cell flagged not "
            "comparable mixes units / seasonal adjustment / base years — do not compare "
            "those numbers directly. No score, no 'true' producer."
        ),
    }
