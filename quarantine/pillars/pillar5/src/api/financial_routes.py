"""
Financial Routes

FastAPI endpoints for Pillar 5's financial intelligence system.
"""

import sys
from pathlib import Path

# Add pillar5 to path
pillar5_path = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(pillar5_path))

from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from pillar5.src.models import (
    SessionLocal,
    Exchange, ExchangeDB,
    FinancialInstrument, FinancialInstrumentDB,
    FinancialDataPoint, FinancialDataPointDB,
    InstrumentFundamentals, InstrumentFundamentalsDB,
    FinancialMetric, FinancialMetricDB,
    InstrumentKeyword, InstrumentKeywordDB,
    ArticleFinancialLink, ArticleFinancialLinkDB,
)

from pillar5.src.scraping import (
    ExchangeDiscovery,
    InstrumentDiscovery,
    OHLCScraper,
    FundamentalsScraper,
    KeywordExtractor,
)

from pillar5.src.services import (
    MetricCalculator,
    HybridCorrelationEngine,
)

# Create router
router = APIRouter(prefix="/api/v1/financial", tags=["Financial Intelligence"])


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Exchange Endpoints
# ============================================================================

@router.get("/exchanges", response_model=List[Dict[str, Any]])
async def list_exchanges(
    country: Optional[str] = None,
    exchange_type: Optional[str] = None,
    db: SessionLocal = Depends(get_db)
):
    """
    List all financial exchanges.
    
    Query parameters:
    - country: Filter by country code (e.g., 'US', 'GB')
    - exchange_type: Filter by type ('stock', 'commodity', 'crypto')
    """
    query = db.query(ExchangeDB)
    
    if country:
        query = query.filter(ExchangeDB.country == country.upper())
    
    exchanges = query.all()
    
    return [exchange.to_dataclass().to_dict() for exchange in exchanges]


@router.get("/exchanges/{exchange_id}", response_model=Dict[str, Any])
async def get_exchange(
    exchange_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get a specific exchange by ID."""
    exchange = db.query(ExchangeDB).filter(ExchangeDB.id == exchange_id.upper()).first()
    
    if not exchange:
        raise HTTPException(status_code=404, detail="Exchange not found")
    
    return exchange.to_dataclass().to_dict()


@router.post("/exchanges/discover", response_model=Dict[str, Any])
async def discover_exchanges():
    """
    Discover exchanges using the ExchangeDiscovery scraper.
    Returns statistics about discovered exchanges.
    """
    scraper = ExchangeDiscovery()
    stats = scraper.get_stats()
    
    # Save to database
    exchanges = scraper.get_all_exchanges()
    count = scraper.save_to_database(exchanges)
    
    return {
        "message": f"Discovered {len(exchanges)} exchanges, saved {count} to database",
        "stats": stats
    }


# ============================================================================
# Instrument Endpoints
# ============================================================================

@router.get("/instruments", response_model=List[Dict[str, Any]])
async def list_instruments(
    instrument_type: Optional[str] = None,
    exchange_id: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    is_active: Optional[bool] = True,
    limit: int = 100,
    offset: int = 0,
    db: SessionLocal = Depends(get_db)
):
    """
    List financial instruments.
    
    Query parameters:
    - instrument_type: Filter by type ('stock', 'etf', 'index', 'commodity', 'forex', 'crypto')
    - exchange_id: Filter by exchange ID
    - sector: Filter by sector
    - industry: Filter by industry
    - is_active: Filter by active status
    - limit: Maximum number of results
    - offset: Pagination offset
    """
    query = db.query(FinancialInstrumentDB)
    
    if instrument_type:
        query = query.filter(FinancialInstrumentDB.type == instrument_type.lower())
    
    if exchange_id:
        query = query.filter(FinancialInstrumentDB.exchange_id == exchange_id.upper())
    
    if sector:
        query = query.filter(FinancialInstrumentDB.sector.ilike(f"%{sector}%"))
    
    if industry:
        query = query.filter(FinancialInstrumentDB.industry.ilike(f"%{industry}%"))
    
    if is_active is not None:
        query = query.filter(FinancialInstrumentDB.is_active == is_active)
    
    instruments = query.limit(limit).offset(offset).all()
    
    return [instrument.to_dataclass().to_dict() for instrument in instruments]


@router.get("/instruments/{instrument_id}", response_model=Dict[str, Any])
async def get_instrument(
    instrument_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get a specific instrument by ID."""
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id.upper()).first()
    
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    return instrument.to_dataclass().to_dict()


@router.post("/instruments/discover", response_model=Dict[str, Any])
async def discover_instruments():
    """
    Discover instruments using the InstrumentDiscovery scraper.
    Returns statistics about discovered instruments.
    """
    scraper = InstrumentDiscovery()
    stats = scraper.get_stats()
    
    # Get all instruments
    instruments = scraper.get_all_instruments()
    count = scraper.save_to_database(instruments)
    
    return {
        "message": f"Discovered {len(instruments)} instruments, saved {count} to database",
        "stats": stats
    }


@router.post("/instruments/{instrument_id}/extract-keywords", response_model=Dict[str, Any])
async def extract_instrument_keywords(
    instrument_id: str,
    db: SessionLocal = Depends(get_db)
):
    """
    Extract keywords from an instrument's metadata.
    """
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    extractor = KeywordExtractor()
    keywords = extractor.extract_from_instrument(
        instrument_id=instrument.id,
        name=instrument.name or "",
        description=instrument.description,
        sector=instrument.sector,
        industry=instrument.industry
    )
    
    # Save to database
    count = extractor.save_to_database(keywords)
    
    return {
        "message": f"Extracted {len(keywords)} keywords, saved {count} to database",
        "keywords": [kw.to_dict() for kw in keywords]
    }


# ============================================================================
# OHLC Data Endpoints
# ============================================================================

@router.get("/ohlc/{instrument_id}", response_model=List[Dict[str, Any]])
async def get_ohlc_data(
    instrument_id: str,
    timeframe: str = "1mo",
    limit: int = 100,
    db: SessionLocal = Depends(get_db)
):
    """
    Get OHLC data for an instrument.
    
    Query parameters:
    - timeframe: Timeframe ('1d', '5d', '1mo', '3mo', '6mo', '1y', '5y', 'max')
    - limit: Maximum number of data points
    """
    scraper = OHLCScraper()
    
    # Get instrument to verify it exists
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Scrape OHLC data
    ohlc_data = scraper.get_ohlc_data(instrument.symbol or instrument.id, timeframe)
    
    # Save to database
    count = scraper.save_to_database(
        instrument_id=instrument.id,
        ohlc_data=ohlc_data,
        currency=instrument.base_currency or "USD",
        data_source="yahoo_finance"
    )
    
    # Return data
    return [
        {
            "timestamp": d.timestamp.isoformat(),
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume,
            "adjusted_close": d.adjusted_close
        }
        for d in ohlc_data[-limit:]
    ]


@router.get("/ohlc/{instrument_id}/latest", response_model=Dict[str, Any])
async def get_latest_ohlc(
    instrument_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get the latest OHLC data point for an instrument."""
    scraper = OHLCScraper()
    
    # Get instrument
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Get latest price
    latest = scraper.get_latest_price(instrument.symbol or instrument.id)
    
    if not latest:
        raise HTTPException(status_code=404, detail="No OHLC data available")
    
    return {
        "timestamp": latest.timestamp.isoformat(),
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "volume": latest.volume,
        "adjusted_close": latest.adjusted_close
    }


# ============================================================================
# Fundamentals Endpoints
# ============================================================================

@router.get("/fundamentals/{instrument_id}", response_model=Dict[str, Any])
async def get_fundamentals(
    instrument_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get fundamental data for an instrument."""
    scraper = FundamentalsScraper()
    
    # Get instrument
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Scrape fundamentals
    fundamentals = scraper.get_fundamentals(instrument.symbol or instrument.id, instrument.type)
    
    if not fundamentals:
        raise HTTPException(status_code=404, detail="No fundamentals data available")
    
    # Save to database
    count = scraper.save_to_database(fundamentals)
    
    return fundamentals.to_fundamentals().to_dict()


# ============================================================================
# Metrics Endpoints
# ============================================================================

@router.get("/metrics", response_model=List[Dict[str, Any]])
async def list_metrics():
    """List all available metric definitions."""
    calculator = MetricCalculator()
    metrics = calculator.get_all_metrics()
    
    return [metric.to_dict() for metric in metrics]


@router.get("/metrics/{instrument_id}", response_model=List[Dict[str, Any]])
async def get_instrument_metrics(
    instrument_id: str,
    timeframe: str = "1D",
    db: SessionLocal = Depends(get_db)
):
    """
    Get all calculated metrics for an instrument.
    
    Query parameters:
    - timeframe: Timeframe for metrics ('1D', '1W', '1M')
    """
    calculator = MetricCalculator()
    
    # Get instrument
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Get OHLC data
    ohlc_scraper = OHLCScraper()
    ohlc_data = ohlc_scraper.get_ohlc_data(instrument.symbol or instrument.id, "1mo")
    
    if not ohlc_data:
        raise HTTPException(status_code=404, detail="No OHLC data available for calculation")
    
    # Calculate metrics
    metrics = calculator.calculate_all_metrics(
        ohlc_data=ohlc_data,
        instrument_id=instrument.id,
        timestamp=datetime.utcnow(),
        timeframe=timeframe
    )
    
    # Save to database
    count = calculator.save_to_database(metrics)
    
    return [metric.to_dict() for metric in metrics]


@router.get("/metrics/{instrument_id}/{metric_name}", response_model=Dict[str, Any])
async def get_single_metric(
    instrument_id: str,
    metric_name: str,
    timeframe: str = "1D",
    db: SessionLocal = Depends(get_db)
):
    """Get a specific metric for an instrument."""
    calculator = MetricCalculator()
    
    # Get instrument
    instrument = db.query(FinancialInstrumentDB).filter(FinancialInstrumentDB.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Get OHLC data
    ohlc_scraper = OHLCScraper()
    ohlc_data = ohlc_scraper.get_ohlc_data(instrument.symbol or instrument.id, "1mo")
    
    if not ohlc_data:
        raise HTTPException(status_code=404, detail="No OHLC data available for calculation")
    
    # Calculate metric
    value = calculator.calculate_metric(metric_name, ohlc_data)
    
    if value is None:
        raise HTTPException(status_code=404, detail="Metric calculation failed")
    
    # Get metric definition
    metric_def = calculator.get_metric_definition(metric_name)
    
    return {
        "instrument_id": instrument_id,
        "metric_name": metric_name,
        "metric_group": metric_def.group.value if metric_def else "unknown",
        "value": value,
        "timestamp": datetime.utcnow().isoformat(),
        "timeframe": timeframe,
        "calculation_method": metric_def.formula if metric_def else "unknown"
    }


# ============================================================================
# Keyword Endpoints
# ============================================================================

@router.get("/keywords/{instrument_id}", response_model=List[Dict[str, Any]])
async def get_instrument_keywords(
    instrument_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get all keywords for an instrument."""
    keywords = db.query(InstrumentKeywordDB).filter(
        InstrumentKeywordDB.instrument_id == instrument_id
    ).all()
    
    return [kw.to_dataclass().to_dict() for kw in keywords]


# ============================================================================
# Correlation Endpoints
# ============================================================================

@router.post("/correlations", response_model=List[Dict[str, Any]])
async def calculate_correlations(
    article_id: str,
    article_text: str,
    article_timestamp: Optional[datetime] = None,
    min_score: float = 0.1,
    time_window_hours: float = 24.0,
    db: SessionLocal = Depends(get_db)
):
    """
    Calculate correlations between an article and financial instruments.
    
    Request body:
    - article_id: The article ID
    - article_text: The article text content
    - article_timestamp: Optional article timestamp (defaults to now)
    - min_score: Minimum correlation score to include (0-1)
    - time_window_hours: Time window for temporal correlation
    """
    engine = HybridCorrelationEngine()
    
    # Get all instruments
    instruments = db.query(FinancialInstrumentDB).all()
    
    # Calculate correlations
    results = engine.calculate_correlation(
        article_id=article_id,
        article_text=article_text,
        article_timestamp=article_timestamp or datetime.utcnow(),
        instruments=instruments,
        time_window_hours=time_window_hours,
        min_score=min_score
    )
    
    # Save to database
    count = engine.save_to_database(results)
    
    return [
        {
            "article_id": r.article_id,
            "instrument_id": r.instrument_id,
            "correlation_score": r.correlation_score,
            "correlation_type": r.correlation_type,
            "matched_keywords": r.matched_keywords,
            "matched_sector": r.matched_sector,
            "time_diff_hours": r.time_diff_hours,
            "direction": r.direction,
            "confidence": r.confidence,
            "is_significant": r.is_significant
        }
        for r in results
    ]


@router.get("/correlations/{article_id}", response_model=List[Dict[str, Any]])
async def get_article_correlations(
    article_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get all correlations for a specific article."""
    links = db.query(ArticleFinancialLinkDB).filter(
        ArticleFinancialLinkDB.article_id == article_id
    ).all()
    
    return [link.to_dataclass().to_dict() for link in links]


# ============================================================================
# Stats Endpoints
# ============================================================================

@router.get("/stats", response_model=Dict[str, Any])
async def get_stats():
    """Get statistics about the financial intelligence system."""
    from pillar5.src.scraping import ExchangeDiscovery, InstrumentDiscovery
    from pillar5.src.services import MetricCalculator, HybridCorrelationEngine
    
    exchange_discovery = ExchangeDiscovery()
    instrument_discovery = InstrumentDiscovery()
    metric_calculator = MetricCalculator()
    correlation_engine = HybridCorrelationEngine()
    
    return {
        "exchanges": exchange_discovery.get_stats(),
        "instruments": instrument_discovery.get_stats(),
        "metrics": metric_calculator.get_stats(),
        "correlations": correlation_engine.get_stats()
    }
