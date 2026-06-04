"""
Unit Tests for Pillar 5 Database Models

Tests for:
- FinancialInstrument (dataclass and SQLAlchemy)
- FinancialDataPoint (dataclass and SQLAlchemy)
- Exchange (dataclass and SQLAlchemy)
- FinancialMetric (dataclass and SQLAlchemy)
- InstrumentKeyword (dataclass and SQLAlchemy)
- ArticleFinancialLink (dataclass and SQLAlchemy)
- FinancialAnalysis (dataclass and SQLAlchemy)
- InstrumentFundamentals (dataclass and SQLAlchemy)
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal

# Add pillar5 to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pillar5.src.models.financial_instrument import FinancialInstrument, FinancialInstrumentDB
from pillar5.src.models.exchange import Exchange, ExchangeDB
from pillar5.src.models.financial_data import FinancialDataPoint, FinancialDataPointDB
from pillar5.src.models.financial_metric import FinancialMetric, FinancialMetricDB
from pillar5.src.models.instrument_keyword import InstrumentKeyword, InstrumentKeywordDB
from pillar5.src.models.correlation import ArticleFinancialLink, ArticleFinancialLinkDB, CorrelationType, ExtendedCorrelationType
from pillar5.src.models.analysis import FinancialAnalysis, FinancialAnalysisDB
from pillar5.src.models.fundamentals import InstrumentFundamentals, InstrumentFundamentalsDB


class TestFinancialInstrument:
    """Tests for FinancialInstrument model"""
    
    def test_create_financial_instrument(self):
        """Test creating a FinancialInstrument instance"""
        instrument = FinancialInstrument(
            id=1,
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=1,
            isin="US0378331005",
            cusip="037833100",
            figi="BBG000B9XRY4",
            sector="Technology",
            industry="Consumer Electronics",
            country="United States",
            currency="USD",
            description="Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories.",
            website="https://www.apple.com",
            founded_year=1976,
            employees=165000,
            headquarters="Cupertino, California",
            extra_metadata={"market_cap": 3e12, "pe_ratio": 28.5}
        )
        
        assert instrument.id == 1
        assert instrument.symbol == "AAPL"
        assert instrument.name == "Apple Inc."
        assert instrument.type == "stock"
        assert instrument.sector == "Technology"
        assert instrument.industry == "Consumer Electronics"
        assert instrument.country == "United States"
        assert instrument.currency == "USD"
        assert instrument.founded_year == 1976
        assert instrument.employees == 165000
    
    def test_financial_instrument_to_dict(self):
        """Test converting FinancialInstrument to dict"""
        instrument = FinancialInstrument(
            id=1,
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=1,
            sector="Technology"
        )
        
        data = instrument.to_dict()
        
        assert data["id"] == 1
        assert data["symbol"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["type"] == "stock"
        assert data["sector"] == "Technology"
    
    def test_financial_instrument_from_dict(self):
        """Test creating FinancialInstrument from dict"""
        data = {
            "id": 1,
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "type": "stock",
            "exchange_id": 1,
            "sector": "Technology",
            "industry": "Consumer Electronics"
        }
        
        instrument = FinancialInstrument.from_dict(data)
        
        assert instrument.id == 1
        assert instrument.symbol == "AAPL"
        assert instrument.name == "Apple Inc."
        assert instrument.type == "stock"
        assert instrument.sector == "Technology"
    
    def test_financial_instrument_backward_compatibility(self):
        """Test backward compatibility with company_id field"""
        # Test with old field name
        data = {
            "company_id": 1,
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "type": "stock"
        }
        
        instrument = FinancialInstrument.from_dict(data)
        
        # Should map company_id to id
        assert instrument.id == 1
        assert instrument.symbol == "AAPL"
    
    def test_financial_instrument_validation(self):
        """Test validation of FinancialInstrument fields"""
        # Valid types
        for instrument_type in ["stock", "etf", "index", "commodity", "forex", "crypto"]:
            instrument = FinancialInstrument(
                id=1,
                symbol="TEST",
                name="Test",
                type=instrument_type
            )
            assert instrument.type == instrument_type
        
        # Test with None values
        instrument = FinancialInstrument(
            id=1,
            symbol="TEST",
            name="Test",
            type="stock"
        )
        assert instrument.exchange_id is None
        assert instrument.sector is None


class TestExchange:
    """Tests for Exchange model"""
    
    def test_create_exchange(self):
        """Test creating an Exchange instance"""
        exchange = Exchange(
            id=1,
            code="NYSE",
            name="New York Stock Exchange",
            country="United States",
            city="New York",
            timezone="America/New_York",
            currency="USD",
            website="https://www.nyse.com",
            founded_year=1792,
            is_active=True,
            exchange_type="stock",
            trading_hours="09:30-16:00",
            extra_metadata={"volume_24h": 1e12}
        )
        
        assert exchange.id == 1
        assert exchange.code == "NYSE"
        assert exchange.name == "New York Stock Exchange"
        assert exchange.country == "United States"
        assert exchange.city == "New York"
        assert exchange.timezone == "America/New_York"
        assert exchange.currency == "USD"
        assert exchange.is_active is True
        assert exchange.exchange_type == "stock"
    
    def test_exchange_to_dict(self):
        """Test converting Exchange to dict"""
        exchange = Exchange(
            id=1,
            code="NYSE",
            name="New York Stock Exchange",
            country="United States"
        )
        
        data = exchange.to_dict()
        
        assert data["id"] == 1
        assert data["code"] == "NYSE"
        assert data["name"] == "New York Stock Exchange"
        assert data["country"] == "United States"
    
    def test_exchange_from_dict(self):
        """Test creating Exchange from dict"""
        data = {
            "id": 1,
            "code": "NYSE",
            "name": "New York Stock Exchange",
            "country": "United States",
            "city": "New York"
        }
        
        exchange = Exchange.from_dict(data)
        
        assert exchange.id == 1
        assert exchange.code == "NYSE"
        assert exchange.name == "New York Stock Exchange"
        assert exchange.country == "United States"


class TestFinancialDataPoint:
    """Tests for FinancialDataPoint model"""
    
    def test_create_financial_data_point(self):
        """Test creating a FinancialDataPoint instance"""
        now = datetime.utcnow()
        data_point = FinancialDataPoint(
            id=1,
            instrument_id=1,
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=148.0,
            close_price=152.5,
            volume=1000000,
            adjusted_close=152.3,
            timeframe="1d",
            source="yahoo",
            is_verified=True,
            extra_metadata={"dividends": 0.5, "splits": 0}
        )
        
        assert data_point.id == 1
        assert data_point.instrument_id == 1
        assert data_point.timestamp == now
        assert data_point.open_price == 150.0
        assert data_point.high_price == 155.0
        assert data_point.low_price == 148.0
        assert data_point.close_price == 152.5
        assert data_point.volume == 1000000
        assert data_point.timeframe == "1d"
        assert data_point.source == "yahoo"
    
    def test_financial_data_point_to_dict(self):
        """Test converting FinancialDataPoint to dict"""
        now = datetime.utcnow()
        data_point = FinancialDataPoint(
            id=1,
            instrument_id=1,
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=148.0,
            close_price=152.5,
            volume=1000000
        )
        
        data = data_point.to_dict()
        
        assert data["id"] == 1
        assert data["instrument_id"] == 1
        assert data["open_price"] == 150.0
        assert data["high_price"] == 155.0
        assert data["low_price"] == 148.0
        assert data["close_price"] == 152.5
    
    def test_financial_data_point_backward_compatibility(self):
        """Test backward compatibility with company_id field"""
        now = datetime.utcnow()
        data = {
            "id": 1,
            "company_id": 1,
            "timestamp": now.isoformat(),
            "open_price": 150.0,
            "close_price": 152.5
        }
        
        data_point = FinancialDataPoint.from_dict(data)
        
        # Should map company_id to instrument_id
        assert data_point.instrument_id == 1


class TestFinancialMetric:
    """Tests for FinancialMetric model"""
    
    def test_create_financial_metric(self):
        """Test creating a FinancialMetric instance"""
        now = datetime.utcnow()
        metric = FinancialMetric(
            id=1,
            instrument_id=1,
            name="SMA_20",
            group="Trend",
            value=150.5,
            timestamp=now,
            timeframe="1d",
            parameters={"period": 20},
            source="calculated",
            calculation_method="Simple Moving Average",
            description="20-day Simple Moving Average",
            formula="SUM(close, 20) / 20",
            use_case="Identify trend direction",
            visualization_type="line",
            is_active=True,
            extra_metadata={"version": "1.0"}
        )
        
        assert metric.id == 1
        assert metric.instrument_id == 1
        assert metric.name == "SMA_20"
        assert metric.group == "Trend"
        assert metric.value == 150.5
        assert metric.timeframe == "1d"
        assert metric.source == "calculated"
        assert metric.calculation_method == "Simple Moving Average"
    
    def test_financial_metric_to_dict(self):
        """Test converting FinancialMetric to dict"""
        now = datetime.utcnow()
        metric = FinancialMetric(
            id=1,
            instrument_id=1,
            name="SMA_20",
            group="Trend",
            value=150.5,
            timestamp=now
        )
        
        data = metric.to_dict()
        
        assert data["id"] == 1
        assert data["instrument_id"] == 1
        assert data["name"] == "SMA_20"
        assert data["group"] == "Trend"
        assert data["value"] == 150.5
    
    def test_financial_metric_from_dict(self):
        """Test creating FinancialMetric from dict"""
        now = datetime.utcnow()
        data = {
            "id": 1,
            "instrument_id": 1,
            "name": "SMA_20",
            "group": "Trend",
            "value": 150.5,
            "timestamp": now.isoformat(),
            "timeframe": "1d"
        }
        
        metric = FinancialMetric.from_dict(data)
        
        assert metric.id == 1
        assert metric.instrument_id == 1
        assert metric.name == "SMA_20"
        assert metric.group == "Trend"
        assert metric.value == 150.5


class TestInstrumentKeyword:
    """Tests for InstrumentKeyword model"""
    
    def test_create_instrument_keyword(self):
        """Test creating an InstrumentKeyword instance"""
        keyword = InstrumentKeyword(
            id=1,
            instrument_id=1,
            keyword="technology",
            weight=0.8,
            source="name",
            is_primary=True,
            category="sector",
            extra_metadata={"language": "en"}
        )
        
        assert keyword.id == 1
        assert keyword.instrument_id == 1
        assert keyword.keyword == "technology"
        assert keyword.weight == 0.8
        assert keyword.source == "name"
        assert keyword.is_primary is True
        assert keyword.category == "sector"
    
    def test_instrument_keyword_to_dict(self):
        """Test converting InstrumentKeyword to dict"""
        keyword = InstrumentKeyword(
            id=1,
            instrument_id=1,
            keyword="technology",
            weight=0.8,
            source="name"
        )
        
        data = keyword.to_dict()
        
        assert data["id"] == 1
        assert data["instrument_id"] == 1
        assert data["keyword"] == "technology"
        assert data["weight"] == 0.8
    
    def test_instrument_keyword_from_dict(self):
        """Test creating InstrumentKeyword from dict"""
        data = {
            "id": 1,
            "instrument_id": 1,
            "keyword": "technology",
            "weight": 0.8,
            "source": "name"
        }
        
        keyword = InstrumentKeyword.from_dict(data)
        
        assert keyword.id == 1
        assert keyword.instrument_id == 1
        assert keyword.keyword == "technology"
        assert keyword.weight == 0.8


class TestArticleFinancialLink:
    """Tests for ArticleFinancialLink model"""
    
    def test_create_article_financial_link(self):
        """Test creating an ArticleFinancialLink instance"""
        now = datetime.utcnow()
        link = ArticleFinancialLink(
            id=1,
            article_id=1,
            instrument_id=1,
            correlation_type=CorrelationType.HYBRID,
            correlation_score=0.85,
            mention_score=0.9,
            keyword_score=0.8,
            sector_score=0.7,
            temporal_score=0.6,
            matched_keywords=["technology", "apple"],
            matched_sectors=["Technology"],
            timestamp=now,
            is_active=True,
            extra_metadata={"confidence": "high"}
        )
        
        assert link.id == 1
        assert link.article_id == 1
        assert link.instrument_id == 1
        assert link.correlation_type == CorrelationType.HYBRID
        assert link.correlation_score == 0.85
        assert link.mention_score == 0.9
        assert link.keyword_score == 0.8
        assert link.sector_score == 0.7
        assert link.temporal_score == 0.6
        assert link.matched_keywords == ["technology", "apple"]
        assert link.matched_sectors == ["Technology"]
    
    def test_article_financial_link_to_dict(self):
        """Test converting ArticleFinancialLink to dict"""
        now = datetime.utcnow()
        link = ArticleFinancialLink(
            id=1,
            article_id=1,
            instrument_id=1,
            correlation_type=CorrelationType.HYBRID,
            correlation_score=0.85,
            matched_keywords=["technology", "apple"]
        )
        
        data = link.to_dict()
        
        assert data["id"] == 1
        assert data["article_id"] == 1
        assert data["instrument_id"] == 1
        assert data["correlation_type"] == "hybrid"
        assert data["correlation_score"] == 0.85
    
    def test_article_financial_link_from_dict(self):
        """Test creating ArticleFinancialLink from dict"""
        now = datetime.utcnow()
        data = {
            "id": 1,
            "article_id": 1,
            "instrument_id": 1,
            "correlation_type": "hybrid",
            "correlation_score": 0.85,
            "matched_keywords": ["technology", "apple"]
        }
        
        link = ArticleFinancialLink.from_dict(data)
        
        assert link.id == 1
        assert link.article_id == 1
        assert link.instrument_id == 1
        assert link.correlation_type == CorrelationType.HYBRID
        assert link.correlation_score == 0.85
    
    def test_article_financial_link_backward_compatibility(self):
        """Test backward compatibility with company_id field"""
        data = {
            "id": 1,
            "article_id": 1,
            "company_id": 1,
            "correlation_type": "hybrid",
            "correlation_score": 0.85
        }
        
        link = ArticleFinancialLink.from_dict(data)
        
        # Should map company_id to instrument_id
        assert link.instrument_id == 1


class TestFinancialAnalysis:
    """Tests for FinancialAnalysis model"""
    
    def test_create_financial_analysis(self):
        """Test creating a FinancialAnalysis instance"""
        now = datetime.utcnow()
        analysis = FinancialAnalysis(
            id=1,
            instrument_id=1,
            analysis_type="comprehensive",
            title="Apple Inc. Financial Analysis",
            summary="Strong financial performance with growth potential",
            content={"strengths": ["Strong cash flow"], "weaknesses": []},
            score=85.5,
            confidence=0.95,
            timestamp=now,
            created_by="system",
            status="completed",
            tags=["technology", "growth"],
            extra_metadata={"version": "1.0"}
        )
        
        assert analysis.id == 1
        assert analysis.instrument_id == 1
        assert analysis.analysis_type == "comprehensive"
        assert analysis.title == "Apple Inc. Financial Analysis"
        assert analysis.score == 85.5
        assert analysis.confidence == 0.95
        assert analysis.status == "completed"
    
    def test_financial_analysis_to_dict(self):
        """Test converting FinancialAnalysis to dict"""
        now = datetime.utcnow()
        analysis = FinancialAnalysis(
            id=1,
            instrument_id=1,
            analysis_type="comprehensive",
            title="Apple Inc. Financial Analysis",
            score=85.5
        )
        
        data = analysis.to_dict()
        
        assert data["id"] == 1
        assert data["instrument_id"] == 1
        assert data["analysis_type"] == "comprehensive"
        assert data["title"] == "Apple Inc. Financial Analysis"
        assert data["score"] == 85.5


class TestInstrumentFundamentals:
    """Tests for InstrumentFundamentals model"""
    
    def test_create_instrument_fundamentals(self):
        """Test creating an InstrumentFundamentals instance"""
        now = datetime.utcnow()
        fundamentals = InstrumentFundamentals(
            id=1,
            instrument_id=1,
            timestamp=now,
            timeframe="quarterly",
            market_cap=3e12,
            pe_ratio=28.5,
            pb_ratio=6.2,
            ps_ratio=8.1,
            peg_ratio=1.8,
            dividend_yield=0.005,
            payout_ratio=0.25,
            eps=4.5,
            revenue=394.33e9,
            net_income=96.87e9,
            ebitda=119.44e9,
            gross_margin=0.42,
            operating_margin=0.29,
            net_margin=0.25,
            roe=0.55,
            roa=0.18,
            roi=0.22,
            current_ratio=1.8,
            quick_ratio=1.5,
            debt_to_equity=0.5,
            total_debt=120e9,
            total_equity=240e9,
            free_cash_flow=80e9,
            operating_cash_flow=90e9,
            beta=1.2,
            volatility_1y=0.25,
            volatility_3y=0.22,
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            alpha=0.05,
            source="yahoo",
            is_verified=True,
            extra_metadata={"currency": "USD"}
        )
        
        assert fundamentals.id == 1
        assert fundamentals.instrument_id == 1
        assert fundamentals.market_cap == 3e12
        assert fundamentals.pe_ratio == 28.5
        assert fundamentals.dividend_yield == 0.005
        assert fundamentals.revenue == 394.33e9
        assert fundamentals.net_income == 96.87e9
    
    def test_instrument_fundamentals_to_dict(self):
        """Test converting InstrumentFundamentals to dict"""
        now = datetime.utcnow()
        fundamentals = InstrumentFundamentals(
            id=1,
            instrument_id=1,
            timestamp=now,
            market_cap=3e12,
            pe_ratio=28.5,
            eps=4.5
        )
        
        data = fundamentals.to_dict()
        
        assert data["id"] == 1
        assert data["instrument_id"] == 1
        assert data["market_cap"] == 3e12
        assert data["pe_ratio"] == 28.5
    
    def test_instrument_fundamentals_backward_compatibility(self):
        """Test backward compatibility with company_id field"""
        now = datetime.utcnow()
        data = {
            "id": 1,
            "company_id": 1,
            "timestamp": now.isoformat(),
            "market_cap": 3e12,
            "pe_ratio": 28.5
        }
        
        fundamentals = InstrumentFundamentals.from_dict(data)
        
        # Should map company_id to instrument_id
        assert fundamentals.instrument_id == 1


class TestSQLAlchemyModels:
    """Tests for SQLAlchemy model relationships and database operations"""
    
    @pytest.fixture
    def db_session(self):
        """Create a test database session"""
        from pillar5.src.models.base import Base, engine, SessionLocal
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)
    
    def test_financial_instrument_db_creation(self, db_session):
        """Test creating FinancialInstrumentDB record"""
        instrument = FinancialInstrumentDB(
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=1,
            sector="Technology",
            industry="Consumer Electronics"
        )
        
        db_session.add(instrument)
        db_session.commit()
        
        assert instrument.id is not None
        assert instrument.symbol == "AAPL"
        assert instrument.name == "Apple Inc."
    
    def test_exchange_db_creation(self, db_session):
        """Test creating ExchangeDB record"""
        exchange = ExchangeDB(
            code="NYSE",
            name="New York Stock Exchange",
            country="United States",
            city="New York"
        )
        
        db_session.add(exchange)
        db_session.commit()
        
        assert exchange.id is not None
        assert exchange.code == "NYSE"
        assert exchange.name == "New York Stock Exchange"
    
    def test_relationships(self, db_session):
        """Test relationships between models"""
        # Create exchange
        exchange = ExchangeDB(
            code="NYSE",
            name="New York Stock Exchange",
            country="United States"
        )
        db_session.add(exchange)
        db_session.commit()
        
        # Create instrument
        instrument = FinancialInstrumentDB(
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=exchange.id,
            sector="Technology"
        )
        db_session.add(instrument)
        db_session.commit()
        
        # Create data point
        data_point = FinancialDataPointDB(
            instrument_id=instrument.id,
            timestamp=datetime.utcnow(),
            open_price=150.0,
            high_price=155.0,
            low_price=148.0,
            close_price=152.5,
            volume=1000000,
            timeframe="1d"
        )
        db_session.add(data_point)
        db_session.commit()
        
        # Test relationships
        db_session.refresh(instrument)
        assert instrument.exchange_id == exchange.id
        assert len(instrument.data_points) == 1
        assert instrument.data_points[0].id == data_point.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
