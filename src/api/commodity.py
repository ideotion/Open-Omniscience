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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.commodity.correlation import correlate_price_with_news
from src.commodity.units import UnitError, convert_price
from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, CommodityPrice
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
        db.add(CommodityPrice(
            symbol=symbol, market=p.market, observed_on=p.observed_on,
            price=p.price, currency=p.currency, unit=p.unit, source=req.source,
        ))
    db.commit()
    return {"symbol": symbol, "imported": len(req.points)}


@router.get("/{symbol}/prices")
def list_prices(
    symbol: str,
    unit: str | None = Query(None, description="Convert all prices to this mass unit"),
    db: Session = Depends(get_db),
) -> dict:
    """List stored price points for a symbol, optionally normalized to one unit."""
    rows = (db.query(CommodityPrice).filter_by(symbol=symbol)
            .order_by(CommodityPrice.observed_on).all())
    out = []
    for r in rows:
        price, u = r.price, r.unit
        if unit and unit != r.unit:
            try:
                price = convert_price(r.price, r.unit, unit)
                u = unit
            except UnitError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        out.append({
            "observed_on": r.observed_on.isoformat(), "price": price,
            "currency": r.currency, "unit": u, "market": r.market,
        })
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

    q = db.query(Article.published_at).filter(Article.published_at.isnot(None))
    if query:
        try:
            ids = search_ids(db, query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        if not ids:
            article_dates = []
        else:
            rows = q.filter(Article.id.in_(ids)).all()
            article_dates = [r[0].date() for r in rows]
    else:
        article_dates = [r[0].date() for r in q.all()]

    result = correlate_price_with_news(price_points, article_dates, method=method)
    return {"symbol": symbol, "query": query, **result.to_dict()}
