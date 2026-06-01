"""
Unit Tests for Pillar 5 API Endpoints

Tests for:
- Exchange endpoints
- Instrument endpoints
- OHLC endpoints
- Fundamentals endpoints
- Metrics endpoints
- Keywords endpoints
- Correlations endpoints
- Stats endpoints
"""

import pytest
import sys
import os
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Add pillar5 to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import after path is set
from pillar5.src.api.financial_routes import router as financial_router
from fastapi import FastAPI


# Create a test app
@pytest.fixture
def test_app():
    """Create a test FastAPI app with financial routes"""
    app = FastAPI()
    app.include_router(financial_router)
    return app


@pytest.fixture
def client(test_app):
    """Create a test client"""
    return TestClient(test_app)


class TestExchangeEndpoints:
    """Tests for exchange endpoints"""
    
    @patch('pillar5.src.api.financial_routes.Exchange')
    @patch('pillar5.src.api.financial_routes.ExchangeDB')
    def test_list_exchanges(self, mock_exchange_db, mock_exchange, client):
        """Test listing exchanges"""
        # Mock the database query
        mock_exchange_db.query.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/exchanges")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        assert "success" in response.json()
    
    @patch('pillar5.src.api.financial_routes.Exchange')
    @patch('pillar5.src.api.financial_routes.ExchangeDB')
    def test_get_exchange(self, mock_exchange_db, mock_exchange, client):
        """Test getting a specific exchange"""
        # Mock the database query
        mock_exchange.from_dict.return_value = MagicMock()
        
        response = client.get("/api/v1/financial/exchanges/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.ExchangeDiscovery')
    def test_discover_exchanges(self, mock_discovery, client):
        """Test discovering exchanges"""
        # Mock the discovery
        mock_instance = MagicMock()
        mock_instance.get_all_exchanges.return_value = []
        mock_discovery.return_value = mock_instance
        
        response = client.get("/api/v1/financial/exchanges/discover")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestInstrumentEndpoints:
    """Tests for instrument endpoints"""
    
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_list_instruments(self, mock_instrument_db, mock_instrument, client):
        """Test listing instruments"""
        # Mock the database query
        mock_instrument_db.query.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/instruments")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        assert "success" in response.json()
    
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_get_instrument(self, mock_instrument_db, mock_instrument, client):
        """Test getting a specific instrument"""
        # Mock the database query
        mock_instrument.from_dict.return_value = MagicMock()
        
        response = client.get("/api/v1/financial/instruments/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.InstrumentDiscovery')
    def test_discover_instruments(self, mock_discovery, client):
        """Test discovering instruments"""
        # Mock the discovery
        mock_instance = MagicMock()
        mock_instance.get_all_instruments.return_value = []
        mock_discovery.return_value = mock_instance
        
        response = client.get("/api/v1/financial/instruments/discover")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.KeywordExtractor')
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_extract_keywords(self, mock_instrument_db, mock_instrument, mock_extractor, client):
        """Test extracting keywords for an instrument"""
        # Mock the database query
        mock_instrument.from_dict.return_value = MagicMock()
        
        # Mock the extractor
        mock_instance = MagicMock()
        mock_instance.extract_keywords.return_value = []
        mock_extractor.return_value = mock_instance
        
        response = client.post("/api/v1/financial/instruments/1/extract-keywords")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestOHLCEndpoints:
    """Tests for OHLC endpoints"""
    
    @patch('pillar5.src.api.financial_routes.FinancialDataPoint')
    @patch('pillar5.src.api.financial_routes.FinancialDataPointDB')
    def test_get_ohlc(self, mock_data_point_db, mock_data_point, client):
        """Test getting OHLC data for an instrument"""
        # Mock the database query
        mock_data_point_db.query.return_value.filter.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/ohlc/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.FinancialDataPoint')
    @patch('pillar5.src.api.financial_routes.FinancialDataPointDB')
    def test_get_latest_ohlc(self, mock_data_point_db, mock_data_point, client):
        """Test getting latest OHLC data for an instrument"""
        # Mock the database query
        mock_data_point_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        
        response = client.get("/api/v1/financial/ohlc/1/latest")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestFundamentalsEndpoints:
    """Tests for fundamentals endpoints"""
    
    @patch('pillar5.src.api.financial_routes.InstrumentFundamentals')
    @patch('pillar5.src.api.financial_routes.InstrumentFundamentalsDB')
    def test_get_fundamentals(self, mock_fundamentals_db, mock_fundamentals, client):
        """Test getting fundamentals for an instrument"""
        # Mock the database query
        mock_fundamentals_db.query.return_value.filter.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/fundamentals/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestMetricsEndpoints:
    """Tests for metrics endpoints"""
    
    @patch('pillar5.src.api.financial_routes.FinancialMetric')
    @patch('pillar5.src.api.financial_routes.FinancialMetricDB')
    def test_list_metrics(self, mock_metric_db, mock_metric, client):
        """Test listing metrics"""
        # Mock the database query
        mock_metric_db.query.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/metrics")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        assert "success" in response.json()
    
    @patch('pillar5.src.api.financial_routes.FinancialMetric')
    @patch('pillar5.src.api.financial_routes.FinancialMetricDB')
    def test_get_metric(self, mock_metric_db, mock_metric, client):
        """Test getting a specific metric"""
        # Mock the database query
        mock_metric.from_dict.return_value = MagicMock()
        
        response = client.get("/api/v1/financial/metrics/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.MetricCalculator')
    @patch('pillar5.src.api.financial_routes.FinancialDataPoint')
    @patch('pillar5.src.api.financial_routes.FinancialDataPointDB')
    def test_get_all_metrics_for_instrument(self, mock_data_point_db, mock_data_point, mock_calculator, client):
        """Test getting all metrics for an instrument"""
        # Mock the database query
        mock_data_point_db.query.return_value.filter.return_value.all.return_value = []
        
        # Mock the calculator
        mock_instance = MagicMock()
        mock_instance.calculate_all_metrics.return_value = []
        mock_calculator.return_value = mock_instance
        
        response = client.get("/api/v1/financial/metrics/instrument/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestKeywordsEndpoints:
    """Tests for keywords endpoints"""
    
    @patch('pillar5.src.api.financial_routes.InstrumentKeyword')
    @patch('pillar5.src.api.financial_routes.InstrumentKeywordDB')
    def test_get_keywords_by_instrument(self, mock_keyword_db, mock_keyword, client):
        """Test getting keywords for an instrument"""
        # Mock the database query
        mock_keyword_db.query.return_value.filter.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/keywords/instrument/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestCorrelationsEndpoints:
    """Tests for correlations endpoints"""
    
    @patch('pillar5.src.api.financial_routes.HybridCorrelationEngine')
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_calculate_correlations(self, mock_instrument_db, mock_instrument, mock_engine, client):
        """Test calculating correlations for an article"""
        # Mock the database query
        mock_instrument_db.query.return_value.all.return_value = []
        
        # Mock the engine
        mock_instance = MagicMock()
        mock_instance.calculate_correlation.return_value = []
        mock_engine.return_value = mock_instance
        
        request_data = {
            "article_id": 1,
            "article_text": "Test article text"
        }
        
        response = client.post("/api/v1/financial/correlations/calculate", json=request_data)
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
    
    @patch('pillar5.src.api.financial_routes.ArticleFinancialLink')
    @patch('pillar5.src.api.financial_routes.ArticleFinancialLinkDB')
    def test_get_correlations_by_article(self, mock_link_db, mock_link, client):
        """Test getting correlations for an article"""
        # Mock the database query
        mock_link_db.query.return_value.filter.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/correlations/article/1")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestStatsEndpoints:
    """Tests for stats endpoints"""
    
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    @patch('pillar5.src.api.financial_routes.Exchange')
    @patch('pillar5.src.api.financial_routes.ExchangeDB')
    @patch('pillar5.src.api.financial_routes.FinancialMetric')
    @patch('pillar5.src.api.financial_routes.FinancialMetricDB')
    @patch('pillar5.src.api.financial_routes.ArticleFinancialLink')
    @patch('pillar5.src.api.financial_routes.ArticleFinancialLinkDB')
    def test_get_system_stats(self, mock_link_db, mock_link, mock_metric_db, mock_metric, 
                             mock_exchange_db, mock_exchange, mock_instrument_db, mock_instrument, client):
        """Test getting system statistics"""
        # Mock all database queries
        mock_instrument_db.query.return_value.count.return_value = 0
        mock_exchange_db.query.return_value.count.return_value = 0
        mock_metric_db.query.return_value.count.return_value = 0
        mock_link_db.query.return_value.count.return_value = 0
        
        response = client.get("/api/v1/financial/stats")
        
        assert response.status_code == 200
        assert isinstance(response.json(), dict)
        assert "success" in response.json()


class TestAPIResponseStructure:
    """Tests for API response structure"""
    
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_list_response_structure(self, mock_instrument_db, client):
        """Test that list responses have correct structure"""
        mock_instrument_db.query.return_value.all.return_value = []
        
        response = client.get("/api/v1/financial/instruments")
        
        data = response.json()
        
        assert "success" in data
        assert "data" in data
        assert "message" in data
        assert isinstance(data["data"], list)
    
    @patch('pillar5.src.api.financial_routes.FinancialInstrument')
    @patch('pillar5.src.api.financial_routes.FinancialInstrumentDB')
    def test_get_response_structure(self, mock_instrument_db, mock_instrument, client):
        """Test that get responses have correct structure"""
        mock_instrument.from_dict.return_value = MagicMock()
        
        response = client.get("/api/v1/financial/instruments/1")
        
        data = response.json()
        
        assert "success" in data
        assert "data" in data
        assert "message" in data
    
    def test_error_response_structure(self, client):
        """Test that error responses have correct structure"""
        # Try to get a non-existent endpoint
        response = client.get("/api/v1/financial/nonexistent")
        
        assert response.status_code == 404
        
        data = response.json()
        
        assert "success" in data
        assert data["success"] is False
        assert "error" in data
        assert "message" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
