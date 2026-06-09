"""
Markets API: per-source price-extraction rules + structured price ingestion.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Powers the Markets tabs (financial / stock / rare-earth). A rule says exactly
where one instrument's price lives on one page; running a rule fetches it through
the ethical path and stores a real CommodityPrice (or records an explicit miss).
Charting + correlation reuse the existing /api/commodities endpoints, so no
number is shown without a real series behind it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import CommodityPrice, MarketExtractionRule, Source
from src.database.session import get_db
from src.ingest import EthicalFetcher  # noqa: F401 (kept for type/back-compat)
from src.safety.fetcher import make_fetcher

router = APIRouter(prefix="/api/markets", tags=["markets"])

VALID_CATEGORIES = ("financial", "stock", "commodity")

# Shared ethical fetcher (persists robots cache + per-host rate-limit state).
_fetcher = make_fetcher()


class RuleCreate(BaseModel):
    source_id: int
    symbol: str
    url: str
    selector: str
    category: str = "commodity"
    label: str | None = None
    attribute: str | None = None
    value_regex: str | None = None
    currency: str = "USD"
    unit: str = "kg"
    market: str | None = None
    enabled: bool = True


class RuleUpdate(BaseModel):
    symbol: str | None = None
    url: str | None = None
    selector: str | None = None
    category: str | None = None
    label: str | None = None
    attribute: str | None = None
    value_regex: str | None = None
    currency: str | None = None
    unit: str | None = None
    market: str | None = None
    enabled: bool | None = None


def _serialize(r: MarketExtractionRule) -> dict:
    return {
        "id": r.id,
        "source_id": r.source_id,
        "source_name": r.source.name if r.source else None,
        "category": r.category,
        "symbol": r.symbol,
        "label": r.label,
        "url": r.url,
        "selector": r.selector,
        "attribute": r.attribute,
        "value_regex": r.value_regex,
        "currency": r.currency,
        "unit": r.unit,
        "market": r.market,
        "enabled": r.enabled,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "last_status": r.last_status,
    }


def _get_rule(db: Session, rule_id: int) -> MarketExtractionRule:
    rule = db.query(MarketExtractionRule).filter_by(id=rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found.")
    return rule


def _validate_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown category {category!r}; use one of: {', '.join(VALID_CATEGORIES)}",
        )


@router.get("/rules")
def list_rules(category: str | None = None, db: Session = Depends(get_db)) -> dict:
    """List extraction rules, optionally filtered to one Markets category."""
    q = db.query(MarketExtractionRule)
    if category:
        _validate_category(category)
        q = q.filter_by(category=category)
    rules = q.order_by(MarketExtractionRule.category, MarketExtractionRule.symbol).all()
    return {"count": len(rules), "rules": [_serialize(r) for r in rules]}


@router.post("/rules")
def create_rule(payload: RuleCreate, db: Session = Depends(get_db)) -> dict:
    """Create a price-extraction rule for a source."""
    _validate_category(payload.category)
    if not db.query(Source.id).filter_by(id=payload.source_id).first():
        raise HTTPException(status_code=404, detail=f"Source {payload.source_id} not found.")
    if not payload.symbol.strip() or not payload.url.strip() or not payload.selector.strip():
        raise HTTPException(status_code=400, detail="symbol, url and selector are required.")
    rule = MarketExtractionRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    return _serialize(rule)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db)) -> dict:
    """Update fields of an existing rule (only provided fields change)."""
    rule = _get_rule(db, rule_id)
    data = payload.model_dump(exclude_unset=True)
    if "category" in data and data["category"] is not None:
        _validate_category(data["category"])
    for k, v in data.items():
        setattr(rule, k, v)
    db.commit()
    return _serialize(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a rule (stored price history is left intact)."""
    rule = _get_rule(db, rule_id)
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


@router.post("/rules/{rule_id}/run")
def run_rule_now(rule_id: int, db: Session = Depends(get_db)) -> dict:
    """Fetch the page once and apply the rule now (also serves as a 'test' action).

    Returns the structured outcome -- the extracted value on success, or the exact
    reason it did not match -- so an operator can tune a selector with feedback.
    """
    from src.markets.pipeline import run_rule

    rule = _get_rule(db, rule_id)
    outcome = run_rule(db, rule, fetcher=_fetcher)
    return outcome.to_dict()


@router.get("/overview")
def overview(category: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Per-symbol summary for the Markets tabs: latest stored point + rule + count.

    Combines configured rules with whatever price history exists for their symbols
    (the series itself is fetched from /api/commodities/{symbol}/prices).
    """
    if category:
        _validate_category(category)
    q = db.query(MarketExtractionRule)
    if category:
        q = q.filter_by(category=category)
    rules = q.order_by(MarketExtractionRule.symbol).all()

    items = []
    for r in rules:
        rows = (
            db.query(CommodityPrice)
            .filter_by(symbol=r.symbol)
            .order_by(CommodityPrice.observed_on.desc())
            .all()
        )
        latest = rows[0] if rows else None
        items.append(
            {
                **_serialize(r),
                "points": len(rows),
                "latest": {
                    "observed_on": latest.observed_on.isoformat(),
                    "price": latest.price,
                    "currency": latest.currency,
                    "unit": latest.unit,
                }
                if latest
                else None,
            }
        )
    return {"category": category, "count": len(items), "items": items}


# ----------------------------- CSV data feeds ------------------------------- #
# The trustworthy path to real price history: import an official, machine-readable
# CSV series (FRED / World Bank / EIA / a custom URL) straight into the store.


class CustomFeedImport(BaseModel):
    url: str
    symbol: str
    currency: str = "USD"
    unit: str = "t"
    market: str | None = None
    date_column: str | None = None
    value_column: str | None = None


def _symbol_point_count(db: Session, symbol: str) -> int:
    return db.query(CommodityPrice.id).filter_by(symbol=symbol).count()


@router.get("/feeds")
def list_feeds(category: str | None = None, db: Session = Depends(get_db)) -> dict:
    """List curated official CSV feeds and how many points each symbol already has.

    ``category='index'`` lists the world stock-index catalog; otherwise the
    commodity catalog (default, backward-compatible).
    """
    from src.markets.feed_catalog import feeds_for_category

    feeds = feeds_for_category(category)
    out = [{**f.to_dict(), "points": _symbol_point_count(db, f.symbol)} for f in feeds]
    return {"count": len(out), "feeds": out}


@router.post("/feeds/{key}/import")
def import_catalog_feed(key: str, db: Session = Depends(get_db)) -> dict:
    """Fetch and import one curated feed by key (e.g. 'copper', 'wti_crude')."""
    from src.markets.csv_feeds import import_feed
    from src.markets.feed_catalog import get_feed

    feed = get_feed(key)
    if feed is None:
        raise HTTPException(status_code=404, detail=f"Unknown feed {key!r}.")
    result = import_feed(
        db,
        url=feed.url,
        symbol=feed.symbol,
        fetcher=_fetcher,
        date_column=feed.date_column,
        value_column=feed.value_column,
        currency=feed.currency,
        unit=feed.unit,
        market=feed.market,
        source=f"feed:{feed.key}:{feed.url}",
    )
    if result.status != "imported":
        raise HTTPException(status_code=502, detail=result.to_dict())
    return result.to_dict()


@router.post("/feeds/import-all")
def import_all_feeds(category: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Import every curated feed (for one-click out-of-the-box market data).

    ``category='index'`` imports the world stock-index catalog; otherwise the
    commodity catalog (default, backward-compatible). Best-effort: each feed is
    attempted; failures are reported per-key rather than aborting the batch, so a
    single retired series doesn't block the rest.
    """
    from src.markets.csv_feeds import import_feed
    from src.markets.feed_catalog import feeds_for_category

    results, imported, failed = [], 0, 0
    for feed in feeds_for_category(category):
        try:
            r = import_feed(
                db,
                url=feed.url,
                symbol=feed.symbol,
                fetcher=_fetcher,
                date_column=feed.date_column,
                value_column=feed.value_column,
                currency=feed.currency,
                unit=feed.unit,
                market=feed.market,
                source=f"feed:{feed.key}:{feed.url}",
            )
            results.append({"key": feed.key, **r.to_dict()})
            if r.status == "imported":
                imported += r.imported
            else:
                failed += 1
        except Exception as exc:  # noqa: BLE001 - one feed must never 500 the whole batch
            db.rollback()
            failed += 1
            results.append(
                {
                    "key": feed.key,
                    "symbol": feed.symbol,
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "feeds": len(results),
        "points_imported": imported,
        "failed": failed,
        "results": results,
    }


@router.get("/series")
def list_series(db: Session = Depends(get_db)) -> dict:
    """Distinct stored price symbols with their latest point — drives the dashboard."""
    from sqlalchemy import func

    rows = (
        db.query(
            CommodityPrice.symbol,
            func.count(CommodityPrice.id),
            func.max(CommodityPrice.observed_on),
        )
        .group_by(CommodityPrice.symbol)
        .all()
    )
    out = []
    for symbol, n, _last in rows:
        latest = (
            db.query(CommodityPrice)
            .filter_by(symbol=symbol)
            .order_by(CommodityPrice.observed_on.desc())
            .first()
        )
        out.append(
            {
                "symbol": symbol,
                "points": int(n),
                "latest": {
                    "observed_on": latest.observed_on.isoformat(),
                    "price": latest.price,
                    "currency": latest.currency,
                    "unit": latest.unit,
                    "market": latest.market,
                }
                if latest
                else None,
            }
        )
    out.sort(key=lambda s: s["symbol"])
    return {"count": len(out), "series": out}


@router.get("/board")
def market_board(
    category: str = Query(
        "commodity", description="'index' for the stock-index board, else commodity"
    ),
    spark: int = Query(30, ge=2, le=180, description="How many recent points per sparkline"),
    db: Session = Depends(get_db),
) -> dict:
    """Curated board cards for a category, each with its latest value, day-over-day
    change and a recent sparkline — drives the Indices / Commodities dashboards.

    Every card is a *curated catalog entry* enriched with whatever real points are
    stored for its symbol. Entries with no data yet are returned with ``latest:
    null`` (so the comprehensive list shows before a first import); nothing is
    fabricated, and the change is a real day-over-day delta of stored points.
    """
    from src.markets.feed_catalog import feeds_for_category

    cards = []
    for f in feeds_for_category(category):
        pts = (
            db.query(CommodityPrice.observed_on, CommodityPrice.price)
            .filter_by(symbol=f.symbol)
            .order_by(CommodityPrice.observed_on.asc())
            .all()
        )
        latest = prev = None
        change = change_pct = None
        spark_pts: list[list] = []
        if pts:
            spark_pts = [[d.isoformat(), p] for (d, p) in pts[-spark:]]
            latest = {"observed_on": pts[-1][0].isoformat(), "price": pts[-1][1]}
            if len(pts) >= 2:
                prev = {"observed_on": pts[-2][0].isoformat(), "price": pts[-2][1]}
                if pts[-2][1]:
                    change = round(pts[-1][1] - pts[-2][1], 6)
                    change_pct = round((change / pts[-2][1]) * 100, 2)
        cards.append(
            {
                "key": f.key,
                "symbol": f.symbol,
                "name": f.name,
                "market": f.market,
                "currency": f.currency,
                "unit": f.unit,
                "url": f.url,
                "category": f.category,
                "points": len(pts),
                "latest": latest,
                "prev": prev,
                "change": change,
                "change_pct": change_pct,
                "spark": spark_pts,
            }
        )
    # Cards with data first (by name), empty catalog entries after.
    cards.sort(key=lambda c: (c["latest"] is None, (c["name"] or "").lower()))
    return {
        "category": category,
        "count": len(cards),
        "with_data": sum(1 for c in cards if c["latest"]),
        "note": "End-of-day values from official CSV sources; each card shows its as-of date and source. Not real-time.",
        "cards": cards,
    }


@router.post("/feeds/import-url")
def import_custom_feed(payload: CustomFeedImport, db: Session = Depends(get_db)) -> dict:
    """Import a price series from any CSV URL the user supplies (user-customizable).

    Defaults to column 0 = date and column 1 = value (the FRED convention); either
    can be named explicitly via date_column / value_column.
    """
    from src.markets.csv_feeds import import_feed

    if not payload.url.strip() or not payload.symbol.strip():
        raise HTTPException(status_code=400, detail="url and symbol are required.")
    result = import_feed(
        db,
        url=payload.url,
        symbol=payload.symbol,
        fetcher=_fetcher,
        date_column=payload.date_column,
        value_column=payload.value_column,
        currency=payload.currency,
        unit=payload.unit,
        market=payload.market,
    )
    if result.status != "imported":
        raise HTTPException(status_code=502, detail=result.to_dict())
    return result.to_dict()
