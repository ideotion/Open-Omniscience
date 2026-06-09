"""
Import official commodity price series from a CSV feed URL into the store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the *trustworthy* way to get a real price series: pull a machine-readable
CSV published by an official/statistical source (e.g. FRED, which redistributes
the World Bank "Pink Sheet" commodity series and EIA energy series as clean CSV),
through the same ethical fetch path, and store it as ``CommodityPrice`` points
with explicit provenance. No scraping fragility, no guessed numbers: every point
is a value that actually appeared in the downloaded file on a parseable date.

Design notes:
  * The parser is positional-with-optional-mapping, so it handles FRED's two header
    conventions (``DATE`` and ``observation_date``) and arbitrary user CSVs: by
    default column 0 is the date and column 1 the value; either can be named
    explicitly. FRED's missing-value marker ``.`` (and blanks/NA) are skipped, not
    parsed as zero.
  * Import is idempotent per ``(symbol, market, observed_on)`` so re-importing a
    feed updates the series without piling up duplicate points.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from dateutil import parser as date_parser
from sqlalchemy.orm import Session

from src.database.models import CommodityPrice
from src.ingest import EthicalFetcher, FetchError
from src.markets.extract import parse_number

# Values that mean "no observation" in common official feeds (FRED uses ".").
_MISSING = {"", ".", "na", "n/a", "null", "nan"}


@dataclass
class ParsedSeries:
    points: list[tuple[date, float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _col_index(header: list[str], name: str | None, default: int) -> int:
    """Resolve a column to an index: explicit name (case-insensitive) or a default."""
    if not name:
        return default
    lowered = [h.strip().lower() for h in header]
    target = name.strip().lower()
    if target in lowered:
        return lowered.index(target)
    raise ValueError(f"column {name!r} not found in header {header!r}")


def parse_series_csv(
    text: str,
    *,
    date_column: str | None = None,
    value_column: str | None = None,
) -> ParsedSeries:
    """Parse a date+value time-series CSV. Columns default to 0 (date) and 1 (value)."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r]
    if not rows:
        return ParsedSeries(errors=["empty file"])
    header = rows[0]
    try:
        di = _col_index(header, date_column, 0)
        vi = _col_index(header, value_column, 1 if len(header) > 1 else 0)
    except ValueError as exc:
        return ParsedSeries(errors=[str(exc)])

    points: list[tuple[date, float]] = []
    errors: list[str] = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= max(di, vi):
            continue
        raw_date, raw_val = row[di].strip(), row[vi].strip()
        if raw_val.lower() in _MISSING:
            continue  # genuine missing observation -> skip, never store 0
        value = parse_number(raw_val)
        if value is None:
            errors.append(f"row {i}: unparseable value {raw_val!r}")
            continue
        try:
            observed = date_parser.parse(raw_date).date()
        except (ValueError, OverflowError, TypeError):
            errors.append(f"row {i}: unparseable date {raw_date!r}")
            continue
        points.append((observed, value))
    return ParsedSeries(points=points, errors=errors)


def import_points(
    session: Session,
    *,
    symbol: str,
    points: list[tuple[date, float]],
    currency: str = "USD",
    unit: str = "t",
    market: str | None = None,
    source: str | None = None,
) -> dict:
    """Insert price points, skipping any that already exist for the same day.

    Idempotent on ``(symbol, market, observed_on)``: re-running an import adds only
    genuinely new dates rather than duplicating the series.
    """
    existing = {
        d
        for (d,) in session.query(CommodityPrice.observed_on)
        .filter_by(symbol=symbol, market=market)
        .all()
    }
    imported = 0
    for observed, value in points:
        if observed in existing:
            continue
        existing.add(observed)
        session.add(
            CommodityPrice(
                symbol=symbol,
                market=market,
                observed_on=observed,
                price=value,
                currency=currency,
                unit=unit,
                source=source,
            )
        )
        imported += 1
    session.commit()
    return {
        "symbol": symbol,
        "imported": imported,
        "skipped_existing": len(points) - imported,
        "received": len(points),
    }


@dataclass
class FeedImportResult:
    symbol: str
    status: str  # imported | fetch_failed | parse_failed
    imported: int = 0
    skipped_existing: int = 0
    received: int = 0
    parse_errors: int = 0
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "imported": self.imported,
            "skipped_existing": self.skipped_existing,
            "received": self.received,
            "parse_errors": self.parse_errors,
            "detail": self.detail,
        }


def import_feed(
    session: Session,
    *,
    url: str,
    symbol: str,
    fetcher: EthicalFetcher,
    date_column: str | None = None,
    value_column: str | None = None,
    currency: str = "USD",
    unit: str = "t",
    market: str | None = None,
    source: str | None = None,
) -> FeedImportResult:
    """Fetch a CSV feed URL ethically and import it as a price series for ``symbol``.

    Never raises for a feed-level problem: a network error (reset/timeout/SSL/DNS),
    a robots block, or a malformed file is returned as a failed ``FeedImportResult``
    so a single bad feed can't 500 a batch import. Only ``FetchError`` was caught
    before, which let raw network exceptions escape and crash the whole run.
    """
    try:
        fetched = fetcher.fetch(url, require_html=False)
    except FetchError as exc:
        return FeedImportResult(symbol, "fetch_failed", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - any fetch failure is a feed problem, not a crash
        return FeedImportResult(symbol, "fetch_failed", detail=f"{type(exc).__name__}: {exc}")

    try:
        parsed = parse_series_csv(
            fetched.content, date_column=date_column, value_column=value_column
        )
    except Exception as exc:  # noqa: BLE001 - a malformed feed must not abort the batch
        return FeedImportResult(symbol, "parse_failed", detail=f"{type(exc).__name__}: {exc}")
    if not parsed.points:
        return FeedImportResult(
            symbol,
            "parse_failed",
            parse_errors=len(parsed.errors),
            detail="; ".join(parsed.errors[:3]) or "no usable rows in feed",
        )

    try:
        res = import_points(
            session,
            symbol=symbol,
            points=parsed.points,
            currency=currency,
            unit=unit,
            market=market,
            source=source or f"csv-feed:{fetched.final_url}",
        )
    except Exception as exc:  # noqa: BLE001 - keep the session usable for the rest of the batch
        session.rollback()
        return FeedImportResult(
            symbol, "parse_failed", detail=f"store error: {type(exc).__name__}: {exc}"
        )
    return FeedImportResult(
        symbol,
        "imported",
        imported=res["imported"],
        skipped_existing=res["skipped_existing"],
        received=res["received"],
        parse_errors=len(parsed.errors),
    )
