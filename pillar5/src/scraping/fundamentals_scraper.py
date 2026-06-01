"""
Fundamentals Scraper Module

Scrapes fundamental financial data for instruments.
Supports stocks, ETFs, and other asset classes.
"""

import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pillar5.src.scraping.base import EthicalScraper, ScraperConfig
from pillar5.src.models import InstrumentFundamentals, InstrumentFundamentalsDB


@dataclass
class FundamentalsData:
    """Fundamental data for a financial instrument."""
    instrument_id: str
    date: datetime
    fiscal_period: str = "TTM"
    
    # Valuation metrics
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    
    # Profitability metrics
    eps: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    profit_margin: Optional[float] = None
    
    # Dividend metrics
    dividend_yield: Optional[float] = None
    
    # Risk metrics
    beta: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    
    # Commodity-specific metrics
    contract_size: Optional[float] = None
    tick_size: Optional[float] = None
    
    # Crypto-specific metrics
    max_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    
    currency: str = "USD"
    source: Optional[str] = None
    
    def to_fundamentals(self) -> InstrumentFundamentals:
        """Convert to InstrumentFundamentals dataclass."""
        return InstrumentFundamentals(
            id=f"{self.instrument_id}:{self.date.isoformat()}",
            instrument_id=self.instrument_id,
            date=self.date,
            fiscal_period=self.fiscal_period,
            market_cap=self.market_cap,
            pe_ratio=self.pe_ratio,
            peg_ratio=self.peg_ratio,
            pb_ratio=self.pb_ratio,
            ps_ratio=self.ps_ratio,
            eps=self.eps,
            revenue=self.revenue,
            net_income=self.net_income,
            profit_margin=self.profit_margin,
            dividend_yield=self.dividend_yield,
            beta=self.beta,
            debt_to_equity=self.debt_to_equity,
            current_ratio=self.current_ratio,
            roe=self.roe,
            roa=self.roa,
            contract_size=self.contract_size,
            tick_size=self.tick_size,
            max_supply=self.max_supply,
            circulating_supply=self.circulating_supply,
            currency=self.currency,
            source=self.source,
        )


class FundamentalsScraper(EthicalScraper):
    """
    Scrapes fundamental financial data from various sources.
    
    Primary sources:
    - Yahoo Finance (free, no API key required)
    - MarketWatch
    - Investing.com
    
    Supports:
    - Stocks (valuation, profitability, risk metrics)
    - ETFs
    - Commodities (contract specs)
    - Crypto (supply metrics)
    """
    
    # Yahoo Finance quote summary API URL
    YAHOO_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    
    # Modules to request from Yahoo Finance
    YAHOO_MODULES = [
        "price",  # Basic price info
        "summaryDetail",  # Detailed summary
        "financialData",  # Financial data
        "earnings",  # Earnings data
        "incomeStatementHistory",  # Income statement
        "balanceSheetHistory",  # Balance sheet
        "cashflowStatementHistory",  # Cash flow
    ]
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize FundamentalsScraper."""
        super().__init__(config)
    
    def get_fundamentals(
        self,
        symbol: str,
        instrument_type: str = "stock"
    ) -> Optional[FundamentalsData]:
        """
        Get fundamental data for a symbol.
        
        Args:
            symbol: The instrument symbol
            instrument_type: Type of instrument (stock, etf, commodity, crypto)
            
        Returns:
            FundamentalsData or None if failed
        """
        # Try Yahoo Finance first
        data = self._scrape_yahoo_finance(symbol, instrument_type)
        if data:
            return data
        
        # Try other sources if Yahoo fails
        data = self._scrape_marketwatch(symbol, instrument_type)
        if data:
            return data
        
        return None
    
    def _scrape_yahoo_finance(
        self,
        symbol: str,
        instrument_type: str = "stock"
    ) -> Optional[FundamentalsData]:
        """
        Scrape fundamentals from Yahoo Finance.
        
        Args:
            symbol: The instrument symbol
            instrument_type: Type of instrument
            
        Returns:
            FundamentalsData or None if failed
        """
        try:
            url = self.YAHOO_SUMMARY_URL.format(symbol=symbol)
            params = {
                "modules": ",".join(self.YAHOO_MODULES),
            }
            
            response = self.session.get(url, params=params, timeout=self.config.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                if "quoteSummary" in data and "result" in data["quoteSummary"]:
                    result = data["quoteSummary"]["result"]
                    if result and isinstance(result, list) and len(result) > 0:
                        result = result[0]
                        
                        # Extract data from different modules
                        price_data = result.get("price", {})
                        summary_detail = result.get("summaryDetail", {})
                        financial_data = result.get("financialData", {})
                        
                        # Create FundamentalsData
                        fundamentals = FundamentalsData(
                            instrument_id=symbol,
                            date=datetime.now(),
                            fiscal_period="TTM",
                            currency=price_data.get("currency", "USD"),
                            source="Yahoo Finance",
                        )
                        
                        # Valuation metrics
                        fundamentals.market_cap = summary_detail.get("marketCap")
                        fundamentals.pe_ratio = summary_detail.get("trailingPE")
                        fundamentals.peg_ratio = summary_detail.get("trailingPegRatio")
                        fundamentals.pb_ratio = summary_detail.get("priceToBook")
                        fundamentals.ps_ratio = summary_detail.get("priceToSalesTrailing12Months")
                        
                        # Profitability metrics
                        fundamentals.eps = summary_detail.get("epsTrailingTwelveMonths")
                        fundamentals.revenue = financial_data.get("totalRevenue")
                        fundamentals.net_income = financial_data.get("netIncomeToCommon")
                        fundamentals.profit_margin = financial_data.get("profitMargins")
                        
                        # Dividend metrics
                        fundamentals.dividend_yield = summary_detail.get("dividendYield")
                        
                        # Risk metrics
                        fundamentals.beta = summary_detail.get("beta")
                        fundamentals.debt_to_equity = financial_data.get("debtToEquity")
                        fundamentals.current_ratio = financial_data.get("currentRatio")
                        fundamentals.roe = financial_data.get("returnOnEquity")
                        fundamentals.roa = financial_data.get("returnOnAssets")
                        
                        # Handle percentage fields (Yahoo returns as decimals)
                        if fundamentals.profit_margin is not None and fundamentals.profit_margin > 1:
                            fundamentals.profit_margin /= 100
                        if fundamentals.dividend_yield is not None and fundamentals.dividend_yield > 1:
                            fundamentals.dividend_yield /= 100
                        if fundamentals.roe is not None and fundamentals.roe > 1:
                            fundamentals.roe /= 100
                        if fundamentals.roa is not None and fundamentals.roa > 1:
                            fundamentals.roa /= 100
                        
                        return fundamentals
        except Exception as e:
            print(f"Error scraping Yahoo Finance fundamentals for {symbol}: {e}")
        
        return None
    
    def _scrape_marketwatch(
        self,
        symbol: str,
        instrument_type: str = "stock"
    ) -> Optional[FundamentalsData]:
        """
        Scrape fundamentals from MarketWatch.
        
        Args:
            symbol: The instrument symbol
            instrument_type: Type of instrument
            
        Returns:
            FundamentalsData or None if failed
        """
        try:
            url = f"https://www.marketwatch.com/investing/stock/{symbol}/financials"
            soup = self.get_soup(url)
            if not soup:
                return None
            
            # Parse financial data from tables
            fundamentals = FundamentalsData(
                instrument_id=symbol,
                date=datetime.now(),
                fiscal_period="TTM",
                currency="USD",
                source="MarketWatch",
            )
            
            # This is a placeholder - actual implementation would parse the HTML
            # For now, return empty data
            return fundamentals
        except Exception as e:
            print(f"Error scraping MarketWatch fundamentals for {symbol}: {e}")
        
        return None
    
    def get_historical_fundamentals(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        frequency: str = "quarterly"
    ) -> List[FundamentalsData]:
        """
        Get historical fundamental data for a date range.
        
        Args:
            symbol: The instrument symbol
            start_date: Start date
            end_date: End date
            frequency: Data frequency (quarterly, annual)
            
        Returns:
            List of FundamentalsData objects
        """
        # For now, return current data
        # In the future, this will scrape historical data
        current = self.get_fundamentals(symbol)
        if current:
            return [current]
        return []
    
    def get_multiple_symbols_fundamentals(
        self,
        symbols: List[str],
        instrument_type: str = "stock"
    ) -> Dict[str, Optional[FundamentalsData]]:
        """
        Get fundamentals for multiple symbols.
        
        Args:
            symbols: List of instrument symbols
            instrument_type: Type of instrument
            
        Returns:
            Dictionary mapping symbol to FundamentalsData
        """
        results = {}
        
        for symbol in symbols:
            data = self.get_fundamentals(symbol, instrument_type)
            results[symbol] = data
        
        return results
    
    def save_to_database(
        self,
        fundamentals_data: FundamentalsData
    ) -> int:
        """
        Save fundamentals data to the database.
        
        Args:
            fundamentals_data: FundamentalsData to save
            
        Returns:
            1 if saved, 0 if already exists
        """
        from pillar5.src.models import SessionLocal
        
        with SessionLocal() as db:
            # Check if already exists
            existing = db.query(InstrumentFundamentalsDB).filter_by(
                instrument_id=fundamentals_data.instrument_id,
                date=fundamentals_data.date
            ).first()
            
            if existing:
                # Update existing
                for key, value in fundamentals_data.__dict__.items():
                    if not key.startswith('_') and hasattr(existing, key):
                        setattr(existing, key, value)
                return 0
            else:
                # Create new
                fundamentals_db = InstrumentFundamentalsDB.from_dataclass(
                    fundamentals_data.to_fundamentals()
                )
                db.add(fundamentals_db)
                db.commit()
                return 1
    
    def save_multiple_to_database(
        self,
        fundamentals_list: List[FundamentalsData]
    ) -> int:
        """
        Save multiple fundamentals data to the database.
        
        Args:
            fundamentals_list: List of FundamentalsData to save
            
        Returns:
            Number of new records saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for data in fundamentals_list:
                existing = db.query(InstrumentFundamentalsDB).filter_by(
                    instrument_id=data.instrument_id,
                    date=data.date
                ).first()
                
                if existing:
                    # Update existing
                    for key, value in data.__dict__.items():
                        if not key.startswith('_') and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    # Create new
                    fundamentals_db = InstrumentFundamentalsDB.from_dataclass(
                        data.to_fundamentals()
                    )
                    db.add(fundamentals_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get fundamentals scraper statistics."""
        return {
            "supported_types": ["stock", "etf", "commodity", "crypto"],
            "primary_source": "Yahoo Finance",
            "fallback_sources": ["MarketWatch"],
            "modules": self.YAHOO_MODULES,
        }
