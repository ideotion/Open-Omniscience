"""
Loader for the curated commodity CSV-feed catalog (configs/commodity_feeds.yml).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tiny, dependency-light reader. Entries are validated minimally (a feed needs a
key, a symbol and a url); malformed entries are skipped rather than crashing the
API, mirroring how the source catalog is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "commodity_feeds.yml"
INDEX_CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "index_feeds.yml"


@dataclass
class Feed:
    key: str
    name: str
    symbol: str
    url: str
    category: str = "commodity"
    currency: str = "USD"
    unit: str = "t"
    market: str | None = None
    date_column: str | None = None
    value_column: str | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "symbol": self.symbol,
            "url": self.url,
            "category": self.category,
            "currency": self.currency,
            "unit": self.unit,
            "market": self.market,
            "date_column": self.date_column,
            "value_column": self.value_column,
        }


def load_feeds(path: Path | None = None) -> list[Feed]:
    """Read and validate feed definitions from the YAML catalog."""
    path = path or CATALOG_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    feeds: list[Feed] = []
    for f in data.get("feeds", []):
        if not (isinstance(f, dict) and f.get("key") and f.get("symbol") and f.get("url")):
            continue
        feeds.append(
            Feed(
                key=str(f["key"]),
                name=str(f.get("name", f["key"])),
                symbol=str(f["symbol"]),
                url=str(f["url"]),
                category=str(f.get("category", "commodity")),
                currency=str(f.get("currency", "USD")),
                unit=str(f.get("unit", "t")),
                market=f.get("market"),
                date_column=f.get("date_column"),
                value_column=f.get("value_column"),
            )
        )
    return feeds


def load_index_feeds(path: Path | None = None) -> list[Feed]:
    """Curated world stock-market index feeds (configs/index_feeds.yml).

    Same shape as the commodity catalog, kept in a separate file so the Indices
    board and the Commodities board stay cleanly separated. Defaults differ: an
    index value is an index level (``unit='pts'``) and ``category='index'``.
    """
    path = path or INDEX_CATALOG_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    feeds: list[Feed] = []
    for f in data.get("feeds", []):
        if not (isinstance(f, dict) and f.get("key") and f.get("symbol") and f.get("url")):
            continue
        feeds.append(
            Feed(
                key=str(f["key"]),
                name=str(f.get("name", f["key"])),
                symbol=str(f["symbol"]),
                url=str(f["url"]),
                category=str(f.get("category", "index")),
                currency=str(f.get("currency", "USD")),
                unit=str(f.get("unit", "pts")),
                market=f.get("market"),
                date_column=f.get("date_column"),
                value_column=f.get("value_column"),
            )
        )
    return feeds


def feeds_for_category(category: str | None) -> list[Feed]:
    """The right catalog for a board/import: index feeds for 'index', else commodity."""
    return load_index_feeds() if category == "index" else load_feeds()


def get_feed(key: str, path: Path | None = None) -> Feed | None:
    return next((f for f in load_feeds(path) if f.key == key), None)


def get_index_feed(key: str, path: Path | None = None) -> Feed | None:
    return next((f for f in load_index_feeds(path) if f.key == key), None)
