"""
Commodity (rare-earth) market intelligence API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Stores commodity price time-series in the unified DB and correlates price
movement with news volume using a REAL statistical test (see
src/commodity/correlation.py) -- never a fabricated p-value.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.commodity.correlation import correlate_price_with_counts
from src.commodity.csv_import import parse_price_csv
from src.commodity.units import UnitError, convert_price
from src.database.fts import SearchQueryError, search_ids
from src.database.models import CommodityPrice
from src.database.session import get_db

router = APIRouter(prefix="/api/commodities", tags=["commodities"])


class PricePoint(BaseModel):
    observed_on: date
    price: float
    currency: str = "USD"
    unit: str = "kg"
    market: str | None = None


class ImportPricesRequest(BaseModel):
    points: list[PricePoint]
    source: str | None = None


@router.post("/{symbol}/prices")
def import_prices(symbol: str, req: ImportPricesRequest, db: Session = Depends(get_db)) -> dict:
    """Import price points for a commodity symbol (e.g. 'Nd')."""
    if not req.points:
        raise HTTPException(status_code=400, detail="No price points supplied.")
    for p in req.points:
        db.add(
            CommodityPrice(
                symbol=symbol,
                market=p.market,
                observed_on=p.observed_on,
                price=p.price,
                currency=p.currency,
                unit=p.unit,
                source=req.source,
            )
        )
    db.commit()
    return {"symbol": symbol, "imported": len(req.points)}


@router.post("/{symbol}/prices/import-csv")
async def import_prices_csv(symbol: str, file: UploadFile, db: Session = Depends(get_db)) -> dict:
    """Bulk-import price points for a symbol from an uploaded CSV.

    Required columns: a date column (date/observed_on/day) and a price column
    (price/value/close). Optional: currency, unit, market. Malformed rows are
    reported rather than silently dropped.
    """
    raw = await file.read()
    parsed = parse_price_csv(raw.decode("utf-8", errors="replace"))
    if not parsed.points and parsed.errors:
        raise HTTPException(status_code=400, detail="; ".join(parsed.errors[:5]))
    for p in parsed.points:
        db.add(
            CommodityPrice(
                symbol=symbol,
                market=p.get("market"),
                observed_on=p["observed_on"],
                price=p["price"],
                currency=p.get("currency", "USD"),
                unit=p.get("unit", "kg"),
                source=f"csv:{file.filename}",
            )
        )
    db.commit()
    return {
        "symbol": symbol,
        "imported": len(parsed.points),
        "skipped": len(parsed.errors),
        "errors": parsed.errors[:20],
    }


@router.get("/{symbol}/prices")
def list_prices(
    symbol: str,
    unit: str | None = Query(None, description="Convert all prices to this mass unit"),
    db: Session = Depends(get_db),
) -> dict:
    """List stored price points for a symbol, optionally normalized to one unit."""
    # Column tuples, NOT full ORM objects: a long-history series (e.g. a daily
    # FRED index since 1971 ≈ 13k points) was materialising thousands of ORM
    # entities per chart load — the slowest reads in the 2026-06-17 perf report
    # (N225 6.6s, NASDAQCOM 5.3s). Selecting only the 5 needed columns skips the
    # ORM instrumentation overhead (same technique that took insights_map
    # ~550→215ms). Uses the (symbol, observed_on) composite index for filter+sort.
    rows = (
        db.query(
            CommodityPrice.observed_on,
            CommodityPrice.price,
            CommodityPrice.unit,
            CommodityPrice.currency,
            CommodityPrice.market,
        )
        .filter_by(symbol=symbol)
        .order_by(CommodityPrice.observed_on)
        .all()
    )
    out = []
    for observed_on, price, u, currency, market in rows:
        if unit and unit != u:
            try:
                price = convert_price(price, u, unit)
                u = unit
            except UnitError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        out.append(
            {
                "observed_on": observed_on.isoformat(),
                "price": price,
                "currency": currency,
                "unit": u,
                "market": market,
            }
        )
    return {"symbol": symbol, "count": len(out), "prices": out}


@router.get("/{symbol}/correlation")
def correlation(
    symbol: str,
    query: str | None = Query(None, description="Boolean FTS query selecting relevant articles"),
    method: str = Query("pearson", pattern="^(pearson|spearman)$"),
    db: Session = Depends(get_db),
) -> dict:
    """Correlate daily price change for ``symbol`` with daily article volume.

    If ``query`` is given, only matching articles count toward news volume;
    otherwise all articles with a publish date are used.
    """
    price_rows = db.query(CommodityPrice).filter_by(symbol=symbol).all()
    if not price_rows:
        raise HTTPException(status_code=404, detail=f"No prices stored for {symbol!r}.")
    price_points = [(r.observed_on, r.price) for r in price_rows]

    # Grouped in SQL (S9): the per-day article COUNT via an index-only scan of
    # idx_article_published_at, fed straight into the count-input correlation entry point —
    # O(days) rows instead of materialising one published_at per matching article.
    # substr(published_at, 1, 10) == Python datetime.date() on the stored ISO string, so the
    # counts (and every coefficient/p-value) are byte-identical to the prior per-row loop.
    base = (
        "SELECT substr(published_at, 1, 10) AS d, COUNT(*) AS c FROM articles"
        " WHERE published_at IS NOT NULL"
    )
    if query:
        try:
            ids = search_ids(db, query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        if not ids:
            article_counts: dict[date, int] = {}
        else:
            marks = ",".join(str(int(i)) for i in ids)
            article_counts = {
                date.fromisoformat(d): int(c)
                for d, c in db.execute(
                    text(  # nosec B608 - marks is a joined list of int()-cast ids from search_ids, never input
                        f"{base} AND id IN ({marks}) GROUP BY substr(published_at, 1, 10)"
                    )
                )
            }
    else:
        article_counts = {
            date.fromisoformat(d): int(c)
            for d, c in db.execute(text(f"{base} GROUP BY substr(published_at, 1, 10)"))
        }

    result = correlate_price_with_counts(price_points, article_counts, method=method)
    return {"symbol": symbol, "query": query, **result.to_dict()}
