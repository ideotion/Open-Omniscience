"""
Pillar 6 Storage Module

High-level storage interface for rare earth market data.
Provides CRUD operations and data access patterns.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Union
from contextlib import contextmanager
import logging

from src.database.models import Session
from .database import (
    RareEarthElementDB,
    RareEarthMarketDB,
    RareEarthPriceDB,
    RareEarthProductionDB,
    RareEarthInventoryDB,
    RareEarthAnalysisDB,
    ArticleRareEarthLinkDB,
    RareEarthPriceTimeSeriesDB,
)

# Configure logging
logger = logging.getLogger(__name__)


class RareEarthStorage:
    """
    High-level storage interface for Pillar 6 data.
    
    Provides CRUD operations, querying, and data management for
    rare earth market intelligence data.
    """
    
    def __init__(self):
        """Initialize the storage interface."""
        self.Session = Session
    
    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around database operations."""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()
    
    # =========================================================================
    # Rare Earth Element Operations
    # =========================================================================
    
    def get_element_by_symbol(self, symbol: str) -> Optional[RareEarthElementDB]:
        """Get a rare earth element by its chemical symbol."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).filter_by(symbol=symbol.upper()).first()
    
    def get_element_by_id(self, element_id: int) -> Optional[RareEarthElementDB]:
        """Get a rare earth element by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).filter_by(id=element_id).first()
    
    def get_element_by_name(self, name: str) -> Optional[RareEarthElementDB]:
        """Get a rare earth element by its name."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).filter_by(name=name).first()
    
    def get_all_elements(self) -> List[RareEarthElementDB]:
        """Get all rare earth elements."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).order_by(RareEarthElementDB.atomic_number).all()
    
    def get_elements_by_category(self, category: str) -> List[RareEarthElementDB]:
        """Get elements by category (light or heavy)."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).filter_by(category=category.lower()).all()
    
    def get_critical_elements(self) -> List[RareEarthElementDB]:
        """Get all critical rare earth elements."""
        with self.session_scope() as session:
            return session.query(RareEarthElementDB).filter_by(is_critical=True).all()
    
    def create_element(self, element_data: Dict[str, Any]) -> RareEarthElementDB:
        """Create a new rare earth element."""
        with self.session_scope() as session:
            element = RareEarthElementDB(**element_data)
            session.add(element)
            session.flush()
            return element
    
    def update_element(self, element_id: int, updates: Dict[str, Any]) -> Optional[RareEarthElementDB]:
        """Update an existing rare earth element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(id=element_id).first()
            if element:
                for key, value in updates.items():
                    setattr(element, key, value)
                element.updated_at = datetime.utcnow()
            return element
    
    # =========================================================================
    # Rare Earth Market Operations
    # =========================================================================
    
    def get_market_by_id(self, market_id: str) -> Optional[RareEarthMarketDB]:
        """Get a market by its market_id."""
        with self.session_scope() as session:
            return session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
    
    def get_market_by_db_id(self, db_id: int) -> Optional[RareEarthMarketDB]:
        """Get a market by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthMarketDB).filter_by(id=db_id).first()
    
    def get_all_markets(self) -> List[RareEarthMarketDB]:
        """Get all rare earth markets."""
        with self.session_scope() as session:
            return session.query(RareEarthMarketDB).order_by(RareEarthMarketDB.name).all()
    
    def get_active_markets(self) -> List[RareEarthMarketDB]:
        """Get all active markets."""
        with self.session_scope() as session:
            return session.query(RareEarthMarketDB).filter_by(is_active=True).all()
    
    def get_markets_by_region(self, region: str) -> List[RareEarthMarketDB]:
        """Get markets by geographic region."""
        with self.session_scope() as session:
            return session.query(RareEarthMarketDB).filter_by(region=region.lower()).all()
    
    def get_markets_by_element(self, symbol: str) -> List[RareEarthMarketDB]:
        """Get markets that support a specific element."""
        with self.session_scope() as session:
            # Filter markets where the element is in supported_elements
            return session.query(RareEarthMarketDB).filter(
                RareEarthMarketDB.supported_elements.contains([symbol.upper()])
            ).all()
    
    def create_market(self, market_data: Dict[str, Any]) -> RareEarthMarketDB:
        """Create a new rare earth market."""
        with self.session_scope() as session:
            market = RareEarthMarketDB(**market_data)
            session.add(market)
            session.flush()
            return market
    
    def update_market(self, market_id: str, updates: Dict[str, Any]) -> Optional[RareEarthMarketDB]:
        """Update an existing rare earth market."""
        with self.session_scope() as session:
            market = session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
            if market:
                for key, value in updates.items():
                    setattr(market, key, value)
                market.updated_at = datetime.utcnow()
            return market
    
    # =========================================================================
    # Price Data Operations
    # =========================================================================
    
    def create_price(self, price_data: Dict[str, Any]) -> RareEarthPriceDB:
        """Create a new price data point."""
        with self.session_scope() as session:
            price = RareEarthPriceDB(**price_data)
            session.add(price)
            session.flush()
            return price
    
    def get_price_by_id(self, price_id: int) -> Optional[RareEarthPriceDB]:
        """Get a price by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthPriceDB).filter_by(id=price_id).first()
    
    def get_prices_by_element(self, element_symbol: str, limit: int = 100) -> List[RareEarthPriceDB]:
        """Get price data for a specific element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if element:
                return session.query(RareEarthPriceDB).filter_by(element_id=element.id).order_by(
                    RareEarthPriceDB.timestamp.desc()
                ).limit(limit).all()
            return []
    
    def get_prices_by_market(self, market_id: str, limit: int = 100) -> List[RareEarthPriceDB]:
        """Get price data for a specific market."""
        with self.session_scope() as session:
            market = session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
            if market:
                return session.query(RareEarthPriceDB).filter_by(market_id=market.id).order_by(
                    RareEarthPriceDB.timestamp.desc()
                ).limit(limit).all()
            return []
    
    def get_prices_by_element_and_market(
        self, element_symbol: str, market_id: str, limit: int = 100
    ) -> List[RareEarthPriceDB]:
        """Get price data for a specific element and market."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            market = session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
            
            if element and market:
                return session.query(RareEarthPriceDB).filter_by(
                    element_id=element.id,
                    market_id=market.id
                ).order_by(RareEarthPriceDB.timestamp.desc()).limit(limit).all()
            return []
    
    def get_latest_price(self, element_symbol: str, market_id: str) -> Optional[RareEarthPriceDB]:
        """Get the latest price for an element and market."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            market = session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
            
            if element and market:
                return session.query(RareEarthPriceDB).filter_by(
                    element_id=element.id,
                    market_id=market.id
                ).order_by(RareEarthPriceDB.timestamp.desc()).first()
            return None
    
    def get_prices_in_date_range(
        self, 
        element_symbol: str, 
        start_date: date, 
        end_date: date,
        market_id: Optional[str] = None
    ) -> List[RareEarthPriceDB]:
        """Get price data within a date range."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if not element:
                return []
            
            query = session.query(RareEarthPriceDB).filter(
                RareEarthPriceDB.element_id == element.id,
                RareEarthPriceDB.date >= start_date,
                RareEarthPriceDB.date <= end_date
            )
            
            if market_id:
                market = session.query(RareEarthMarketDB).filter_by(market_id=market_id).first()
                if market:
                    query = query.filter_by(market_id=market.id)
            
            return query.order_by(RareEarthPriceDB.date).all()
    
    def get_price_history(
        self, 
        element_symbol: str, 
        days: int = 30,
        market_id: Optional[str] = None
    ) -> List[RareEarthPriceDB]:
        """Get price history for the last N days."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        return self.get_prices_in_date_range(element_symbol, start_date, end_date, market_id)
    
    # =========================================================================
    # Production Data Operations
    # =========================================================================
    
    def create_production(self, production_data: Dict[str, Any]) -> RareEarthProductionDB:
        """Create a new production data point."""
        with self.session_scope() as session:
            production = RareEarthProductionDB(**production_data)
            session.add(production)
            session.flush()
            return production
    
    def get_production_by_id(self, production_id: int) -> Optional[RareEarthProductionDB]:
        """Get production data by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthProductionDB).filter_by(id=production_id).first()
    
    def get_productions_by_element(self, element_symbol: str) -> List[RareEarthProductionDB]:
        """Get production data for a specific element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if element:
                return session.query(RareEarthProductionDB).filter_by(
                    element_id=element.id
                ).order_by(RareEarthProductionDB.year.desc()).all()
            return []
    
    def get_productions_by_country(self, country: str) -> List[RareEarthProductionDB]:
        """Get production data for a specific country."""
        with self.session_scope() as session:
            return session.query(RareEarthProductionDB).filter_by(
                country=country
            ).order_by(RareEarthProductionDB.year.desc()).all()
    
    def get_productions_by_company(self, company: str) -> List[RareEarthProductionDB]:
        """Get production data for a specific company."""
        with self.session_scope() as session:
            return session.query(RareEarthProductionDB).filter_by(
                company=company
            ).order_by(RareEarthProductionDB.year.desc()).all()
    
    def get_productions_by_year(self, year: int) -> List[RareEarthProductionDB]:
        """Get production data for a specific year."""
        with self.session_scope() as session:
            return session.query(RareEarthProductionDB).filter_by(
                year=year
            ).order_by(RareEarthProductionDB.country).all()
    
    # =========================================================================
    # Inventory Data Operations
    # =========================================================================
    
    def create_inventory(self, inventory_data: Dict[str, Any]) -> RareEarthInventoryDB:
        """Create a new inventory data point."""
        with self.session_scope() as session:
            inventory = RareEarthInventoryDB(**inventory_data)
            session.add(inventory)
            session.flush()
            return inventory
    
    def get_inventory_by_id(self, inventory_id: int) -> Optional[RareEarthInventoryDB]:
        """Get inventory data by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthInventoryDB).filter_by(id=inventory_id).first()
    
    def get_inventories_by_element(self, element_symbol: str) -> List[RareEarthInventoryDB]:
        """Get inventory data for a specific element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if element:
                return session.query(RareEarthInventoryDB).filter_by(
                    element_id=element.id
                ).order_by(RareEarthInventoryDB.year.desc()).all()
            return []
    
    def get_inventories_by_country(self, country: str) -> List[RareEarthInventoryDB]:
        """Get inventory data for a specific country."""
        with self.session_scope() as session:
            return session.query(RareEarthInventoryDB).filter_by(
                country=country
            ).order_by(RareEarthInventoryDB.year.desc()).all()
    
    def get_inventories_by_holder(self, holder: str) -> List[RareEarthInventoryDB]:
        """Get inventory data for a specific holder."""
        with self.session_scope() as session:
            return session.query(RareEarthInventoryDB).filter_by(
                holder=holder
            ).order_by(RareEarthInventoryDB.year.desc()).all()
    
    # =========================================================================
    # Analysis Operations
    # =========================================================================
    
    def create_analysis(self, analysis_data: Dict[str, Any]) -> RareEarthAnalysisDB:
        """Create a new analysis record."""
        with self.session_scope() as session:
            analysis = RareEarthAnalysisDB(**analysis_data)
            session.add(analysis)
            session.flush()
            return analysis
    
    def get_analysis_by_id(self, analysis_id: int) -> Optional[RareEarthAnalysisDB]:
        """Get analysis by its database ID."""
        with self.session_scope() as session:
            return session.query(RareEarthAnalysisDB).filter_by(id=analysis_id).first()
    
    def get_analyses_by_element(self, element_symbol: str) -> List[RareEarthAnalysisDB]:
        """Get analyses for a specific element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if element:
                return session.query(RareEarthAnalysisDB).filter_by(
                    element_id=element.id
                ).order_by(RareEarthAnalysisDB.created_at.desc()).all()
            return []
    
    def get_analyses_by_type(self, analysis_type: str) -> List[RareEarthAnalysisDB]:
        """Get analyses by type."""
        with self.session_scope() as session:
            return session.query(RareEarthAnalysisDB).filter_by(
                analysis_type=analysis_type
            ).order_by(RareEarthAnalysisDB.created_at.desc()).all()
    
    def get_recent_analyses(self, days: int = 7) -> List[RareEarthAnalysisDB]:
        """Get analyses from the last N days."""
        with self.session_scope() as session:
            cutoff = datetime.utcnow() - timedelta(days=days)
            return session.query(RareEarthAnalysisDB).filter(
                RareEarthAnalysisDB.created_at >= cutoff
            ).order_by(RareEarthAnalysisDB.created_at.desc()).all()
    
    # =========================================================================
    # Correlation Operations
    # =========================================================================
    
    def create_correlation(self, correlation_data: Dict[str, Any]) -> ArticleRareEarthLinkDB:
        """Create a new article-REE correlation link."""
        with self.session_scope() as session:
            correlation = ArticleRareEarthLinkDB(**correlation_data)
            session.add(correlation)
            session.flush()
            return correlation
    
    def get_correlation_by_id(self, correlation_id: int) -> Optional[ArticleRareEarthLinkDB]:
        """Get correlation by its database ID."""
        with self.session_scope() as session:
            return session.query(ArticleRareEarthLinkDB).filter_by(id=correlation_id).first()
    
    def get_correlations_by_article(self, article_id: int) -> List[ArticleRareEarthLinkDB]:
        """Get correlations for a specific article."""
        with self.session_scope() as session:
            return session.query(ArticleRareEarthLinkDB).filter_by(
                article_id=article_id
            ).order_by(ArticleRareEarthLinkDB.correlation_score.desc()).all()
    
    def get_correlations_by_element(self, element_symbol: str) -> List[ArticleRareEarthLinkDB]:
        """Get correlations for a specific element."""
        with self.session_scope() as session:
            element = session.query(RareEarthElementDB).filter_by(symbol=element_symbol.upper()).first()
            if element:
                return session.query(ArticleRareEarthLinkDB).filter_by(
                    element_id=element.id
                ).order_by(ArticleRareEarthLinkDB.correlation_score.desc()).all()
            return []
    
    def get_significant_correlations(self, min_score: float = 0.7) -> List[ArticleRareEarthLinkDB]:
        """Get correlations with a minimum correlation score."""
        with self.session_scope() as session:
            return session.query(ArticleRareEarthLinkDB).filter(
                ArticleRareEarthLinkDB.correlation_score >= min_score
            ).order_by(ArticleRareEarthLinkDB.correlation_score.desc()).all()
    
    def get_correlations_by_type(self, correlation_type: str) -> List[ArticleRareEarthLinkDB]:
        """Get correlations by type."""
        with self.session_scope() as session:
            return session.query(ArticleRareEarthLinkDB).filter_by(
                correlation_type=correlation_type
            ).order_by(ArticleRareEarthLinkDB.correlation_score.desc()).all()
    
    def get_correlations_in_date_range(
        self, start_date: date, end_date: date
    ) -> List[ArticleRareEarthLinkDB]:
        """Get correlations within a date range."""
        with self.session_scope() as session:
            return session.query(ArticleRareEarthLinkDB).filter(
                ArticleRareEarthLinkDB.date >= start_date,
                ArticleRareEarthLinkDB.date <= end_date
            ).order_by(ArticleRareEarthLinkDB.date.desc()).all()
    
    # =========================================================================
    # Time-Series Operations
    # =========================================================================
    
    def create_timeseries_price(self, ts_data: Dict[str, Any]) -> RareEarthPriceTimeSeriesDB:
        """Create a new time-series price data point."""
        with self.session_scope() as session:
            ts_price = RareEarthPriceTimeSeriesDB(**ts_data)
            session.add(ts_price)
            session.flush()
            return ts_price
    
    def get_timeseries_prices(
        self, 
        element_symbol: str, 
        market_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[RareEarthPriceTimeSeriesDB]:
        """Get time-series price data for an element and market."""
        with self.session_scope() as session:
            query = session.query(RareEarthPriceTimeSeriesDB).filter_by(
                element_symbol=element_symbol.upper(),
                market_id=market_id
            )
            
            if start_date:
                query = query.filter(RareEarthPriceTimeSeriesDB.timestamp >= start_date)
            if end_date:
                query = query.filter(RareEarthPriceTimeSeriesDB.timestamp <= end_date)
            
            return query.order_by(RareEarthPriceTimeSeriesDB.timestamp).limit(limit).all()
    
    def get_latest_timeseries_price(
        self, element_symbol: str, market_id: str
    ) -> Optional[RareEarthPriceTimeSeriesDB]:
        """Get the latest time-series price for an element and market."""
        with self.session_scope() as session:
            return session.query(RareEarthPriceTimeSeriesDB).filter_by(
                element_symbol=element_symbol.upper(),
                market_id=market_id
            ).order_by(RareEarthPriceTimeSeriesDB.timestamp.desc()).first()
    
    # =========================================================================
    # Bulk Operations
    # =========================================================================
    
    def bulk_create_prices(self, prices_data: List[Dict[str, Any]]) -> List[RareEarthPriceDB]:
        """Bulk create multiple price data points."""
        with self.session_scope() as session:
            prices = [RareEarthPriceDB(**data) for data in prices_data]
            session.bulk_save_objects(prices)
            session.flush()
            return prices
    
    def bulk_create_productions(self, productions_data: List[Dict[str, Any]]) -> List[RareEarthProductionDB]:
        """Bulk create multiple production data points."""
        with self.session_scope() as session:
            productions = [RareEarthProductionDB(**data) for data in productions_data]
            session.bulk_save_objects(productions)
            session.flush()
            return productions
    
    def bulk_create_inventories(self, inventories_data: List[Dict[str, Any]]) -> List[RareEarthInventoryDB]:
        """Bulk create multiple inventory data points."""
        with self.session_scope() as session:
            inventories = [RareEarthInventoryDB(**data) for data in inventories_data]
            session.bulk_save_objects(inventories)
            session.flush()
            return inventories
    
    # =========================================================================
    # Statistics and Aggregations
    # =========================================================================
    
    def get_price_statistics(
        self, 
        element_symbol: str, 
        market_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get price statistics for an element."""
        prices = self.get_price_history(element_symbol, days, market_id)
        
        if not prices:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "avg": None,
                "latest": None,
            }
        
        price_values = [p.price for p in prices]
        
        return {
            "count": len(prices),
            "min": min(price_values),
            "max": max(price_values),
            "avg": sum(price_values) / len(price_values),
            "latest": prices[0].price if prices else None,
            "volatility": self._calculate_volatility(price_values),
        }
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility (standard deviation)."""
        if len(prices) < 2:
            return 0.0
        
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return variance ** 0.5
    
    def get_production_statistics(
        self, 
        element_symbol: str, 
        country: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get production statistics for an element."""
        productions = self.get_productions_by_element(element_symbol)
        
        if country:
            productions = [p for p in productions if p.country == country]
        
        if not productions:
            return {
                "count": 0,
                "total_tonnes": 0,
                "avg_annual": 0,
            }
        
        total_tonnes = sum(p.tonnes for p in productions)
        
        # Calculate average annual production
        yearly = {}
        for p in productions:
            year = p.year
            yearly[year] = yearly.get(year, 0) + p.tonnes
        
        avg_annual = sum(yearly.values()) / len(yearly) if yearly else 0
        
        return {
            "count": len(productions),
            "total_tonnes": total_tonnes,
            "avg_annual_tonnes": avg_annual,
            "years": list(yearly.keys()),
        }
    
    def get_market_coverage(self) -> Dict[str, Any]:
        """Get statistics about market coverage."""
        with self.session_scope() as session:
            markets = session.query(RareEarthMarketDB).all()
            elements = session.query(RareEarthElementDB).all()
            prices = session.query(RareEarthPriceDB).all()
            
            return {
                "total_markets": len(markets),
                "active_markets": len([m for m in markets if m.is_active]),
                "total_elements": len(elements),
                "critical_elements": len([e for e in elements if e.is_critical]),
                "total_price_points": len(prices),
                "markets_by_region": self._count_by_attribute(markets, "region"),
                "markets_by_currency": self._count_by_attribute(markets, "currency"),
            }
    
    def _count_by_attribute(self, items: List[Any], attribute: str) -> Dict[str, int]:
        """Count items by a specific attribute."""
        counts = {}
        for item in items:
            value = getattr(item, attribute, None)
            if value:
                counts[value] = counts.get(value, 0) + 1
        return counts


# Singleton instance
storage = RareEarthStorage()


__all__ = [
    "RareEarthStorage",
    "storage",
]
