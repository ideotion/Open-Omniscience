"""
Parse commodity price points from CSV.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Most public commodity data is distributed as CSV, so this gives a practical bulk
path into the price time-series (the JSON endpoint stays for programmatic use).
Header names are matched flexibly; malformed rows are reported, not silently
dropped (PRODUCT_SYNTHESIS §3.7).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from dateutil import parser as date_parser

# Accepted header aliases (lowercased) -> canonical field.
_ALIASES = {
    "observed_on": "observed_on",
    "date": "observed_on",
    "day": "observed_on",
    "price": "price",
    "value": "price",
    "close": "price",
    "currency": "currency",
    "ccy": "currency",
    "unit": "unit",
    "uom": "unit",
    "market": "market",
    "exchange": "market",
    "source_market": "market",
}


@dataclass
class ParsedPrices:
    points: list[dict]
    errors: list[str] = field(default_factory=list)


def parse_price_csv(text: str) -> ParsedPrices:
    """Parse CSV text into price-point dicts. Requires `date` and `price` columns."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return ParsedPrices([], ["empty file or missing header row"])

    # Map the actual headers to canonical names.
    colmap = {}
    for raw in reader.fieldnames:
        key = (raw or "").strip().lower()
        if key in _ALIASES:
            colmap[raw] = _ALIASES[key]
    canon = set(colmap.values())
    if "observed_on" not in canon or "price" not in canon:
        return ParsedPrices([], ["CSV must have a date column and a price column"])

    points: list[dict] = []
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        rec = {
            colmap[k]: (v.strip() if isinstance(v, str) else v)
            for k, v in row.items()
            if k in colmap
        }
        try:
            observed = date_parser.parse(rec["observed_on"]).date()
            price = float(rec["price"])
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f"row {i}: {exc}")
            continue
        point: dict = {"observed_on": observed, "price": price}
        if rec.get("currency"):
            point["currency"] = rec["currency"]
        if rec.get("unit"):
            point["unit"] = rec["unit"]
        if rec.get("market"):
            point["market"] = rec["market"]
        points.append(point)
    return ParsedPrices(points, errors)
