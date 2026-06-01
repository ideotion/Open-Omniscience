"""
OHLC Scraper Module

Scrapes Open, High, Low, Close data for financial instruments.
Supports multiple data sources with fallback.
"""

import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pillar5.src.scraping.base import EthicalScraper, ScraperConfig
from pillar5.src.models import FinancialDataPoint, FinancialDataPointDB


@dataclass
class OHLCData:
    """OHLC data for a single period."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted_close: Optional[float] = None
    
    def to_data_point(self, instrument_id: str, currency: str = "USD", data_source: str = "yahoo_finance") -> FinancialDataPoint:
        """Convert to FinancialDataPoint dataclass."""
        return FinancialDataPoint(
            id=f"{instrument_id}:{self.timestamp.isoformat()}",
            instrument_id=instrument_id,
            timestamp=self.timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            currency=currency,
            adjusted_close=self.adjusted_close,
            data_source=data_source,
        )


class OHLCScraper(EthicalScraper):
    """
    Scrapes OHLC data from various sources.
    
    Primary sources:
    - Yahoo Finance (free, no API key required)
    - Investing.com
    - MarketWatch
    
    Supports:
    - Daily, weekly, monthly data
    - Historical data (up to available history)
    - Multiple timeframes
    """
    
    # Yahoo Finance chart API URL
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    
    # Timeframe mappings
    TIMEFRAME_MAP = {
        "1d": {"interval": "1m", "range": "1d"},
        "5d": {"interval": "5m", "range": "5d"},
        "1mo": {"interval": "1d", "range": "1mo"},
        "3mo": {"interval": "1d", "range": "3mo"},
        "6mo": {"interval": "1d", "range": "6mo"},
        "1y": {"interval": "1d", "range": "1y"},
        "5y": {"interval": "1wk", "range": "5y"},
        "max": {"interval": "1mo", "range": "max"},
    }
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize OHLCScraper."""
        super().__init__(config)
    
    def get_ohlc_data(
        self,
        symbol: str,
        timeframe: str = "1mo",
        interval: Optional[str] = None
    ) -> List[OHLCData]:
        """
        Get OHLC data for a symbol.
        
        Args:
            symbol: The instrument symbol (e.g., 'AAPL', 'BTC-USD')
            timeframe: The timeframe (1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max)
            interval: Optional interval override
            
        Returns:
            List of OHLCData objects
        """
        # Try Yahoo Finance first
        data = self._scrape_yahoo_finance(symbol, timeframe, interval)
        if data:
            return data
        
        # Try other sources if Yahoo fails
        data = self._scrape_investing_com(symbol, timeframe)
        if data:
            return data
        
        return []
    
    def _scrape_yahoo_finance(
        self,
        symbol: str,
        timeframe: str = "1mo",
        interval: Optional[str] = None
    ) -> List[OHLCData]:
        """
        Scrape OHLC data from Yahoo Finance.
        
        Args:
            symbol: The instrument symbol
            timeframe: The timeframe
            interval: Optional interval override
            
        Returns:
            List of OHLCData objects or empty list if failed
        """
        try:
            # Get timeframe parameters
            tf_params = self.TIMEFRAME_MAP.get(timeframe, self.TIMEFRAME_MAP["1mo"])
            if interval:
                tf_params["interval"] = interval
            
            # Build URL with parameters
            url = self.YAHOO_CHART_URL.format(symbol=symbol)
            params = {
                "interval": tf_params["interval"],
                "range": tf_params["range"],
                "includePrePost": "false",
            }
            
            # Fetch data
            response = self.session.get(url, params=params, timeout=self.config.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                # Parse the response
                if "chart" in data and "result" in data["chart"]:
                    result = data["chart"]["result"]
                    if result and isinstance(result, list) and len(result) > 0:
                        result = result[0]
                        
                        if "indicators" in result and "quote" in result["indicators"]:
                            quotes = result["indicators"]["quote"]
                            if quotes and isinstance(quotes, list) and len(quotes) > 0:
                                quotes = quotes[0]
                                
                                timestamps = result.get("timestamp", [])
                                opens = quotes.get("open", [])
                                highs = quotes.get("high", [])
                                lows = quotes.get("low", [])
                                closes = quotes.get("close", [])
                                volumes = quotes.get("volume", [])
                                adjusted_closes = quotes.get("adjustedclose", [])
                                
                                ohlc_data = []
                                for i in range(len(timestamps)):
                                    try:
                                        timestamp = datetime.fromtimestamp(timestamps[i])
                                        ohlc = OHLCData(
                                            timestamp=timestamp,
                                            open=opens[i] if i < len(opens) and opens[i] is not None else 0,
                                            high=highs[i] if i < len(highs) and highs[i] is not None else 0,
                                            low=lows[i] if i < len(lows) and lows[i] is not None else 0,
                                            close=closes[i] if i < len(closes) and closes[i] is not None else 0,
                                            volume=volumes[i] if i < len(volumes) and volumes[i] is not None else 0,
                                            adjusted_close=adjusted_closes[i] if i < len(adjusted_closes) and adjusted_closes[i] is not None else None,
                                        )
                                        ohlc_data.append(ohlc)
                                    except (IndexError, TypeError, ValueError):
                                        continue
                                
                                return ohlc_data
        except Exception as e:
            print(f"Error scraping Yahoo Finance for {symbol}: {e}")
        
        return []
    
    def _scrape_investing_com(
        self,
        symbol: str,
        timeframe: str = "1mo"
    ) -> List[OHLCData]:
        """
        Scrape OHLC data from Investing.com.
        
        Args:
            symbol: The instrument symbol
            timeframe: The timeframe
            
        Returns:
            List of OHLCData objects or empty list if failed
        """
        try:
            # Investing.com uses different URLs for different instrument types
            if symbol.endswith("-USD") or symbol.endswith("-USDT"):
                # Crypto
                url = f"https://www.investing.com/crypto/{symbol.replace('-', '/')}-historical-data"
            elif "=" in symbol:
                # Forex or commodity
                base, quote = symbol.split("=")
                url = f"https://www.investing.com/currencies/{base}-{quote}-historical-data"
            else:
                # Stock
                url = f"https://www.investing.com/equities/{symbol}-historical-data"
            
            soup = self.get_soup(url)
            if not soup:
                return []
            
            # Parse the historical data table
            table = soup.find("table", class_="genTbl closedTbl historicalTbl")
            if not table:
                return []
            
            ohlc_data = []
            rows = table.find_all("tr")[1:]  # Skip header row
            
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 7:
                    try:
                        date_str = cols[0].get_text(strip=True)
                        timestamp = datetime.strptime(date_str, "%b %d, %Y")
                        
                        open_price = float(cols[1].get_text(strip=True).replace(",", ""))
                        high = float(cols[2].get_text(strip=True).replace(",", ""))
                        low = float(cols[3].get_text(strip=True).replace(",", ""))
                        close = float(cols[4].get_text(strip=True).replace(",", ""))
                        volume = float(cols[6].get_text(strip=True).replace(",", "")) if cols[6].get_text(strip=True) else 0
                        
                        ohlc = OHLCData(
                            timestamp=timestamp,
                            open=open_price,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume,
                        )
                        ohlc_data.append(ohlc)
                    except (ValueError, IndexError):
                        continue
            
            return ohlc_data
        except Exception as e:
            print(f"Error scraping Investing.com for {symbol}: {e}")
        
        return []
    
    def get_latest_price(self, symbol: str) -> Optional[OHLCData]:
        """
        Get the latest OHLC data point for a symbol.
        
        Args:
            symbol: The instrument symbol
            
        Returns:
            Latest OHLCData or None if failed
        """
        data = self.get_ohlc_data(symbol, timeframe="1d")
        if data:
            return data[-1]  # Return the most recent
        return None
    
    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d"
    ) -> List[OHLCData]:
        """
        Get historical OHLC data for a date range.
        
        Args:
            symbol: The instrument symbol
            start_date: Start date
            end_date: End date
            interval: Data interval (1d, 1wk, 1mo)
            
        Returns:
            List of OHLCData objects
        """
        # Calculate approximate timeframe
        days_diff = (end_date - start_date).days
        
        if days_diff <= 1:
            timeframe = "1d"
        elif days_diff <= 5:
            timeframe = "5d"
        elif days_diff <= 30:
            timeframe = "1mo"
        elif days_diff <= 90:
            timeframe = "3mo"
        elif days_diff <= 180:
            timeframe = "6mo"
        elif days_diff <= 365:
            timeframe = "1y"
        elif days_diff <= 1825:
            timeframe = "5y"
        else:
            timeframe = "max"
        
        data = self.get_ohlc_data(symbol, timeframe, interval)
        
        # Filter by date range
        filtered_data = [
            d for d in data
            if start_date <= d.timestamp <= end_date
        ]
        
        return filtered_data
    
    def get_multiple_symbols_data(
        self,
        symbols: List[str],
        timeframe: str = "1d"
    ) -> Dict[str, List[OHLCData]]:
        """
        Get OHLC data for multiple symbols.
        
        Args:
            symbols: List of instrument symbols
            timeframe: The timeframe
            
        Returns:
            Dictionary mapping symbol to list of OHLCData
        """
        results = {}
        
        for symbol in symbols:
            data = self.get_ohlc_data(symbol, timeframe)
            if data:
                results[symbol] = data
        
        return results
    
    def save_to_database(
        self,
        instrument_id: str,
        ohlc_data: List[OHLCData],
        currency: str = "USD",
        data_source: str = "yahoo_finance"
    ) -> int:
        """
        Save OHLC data to the database.
        
        Args:
            instrument_id: The instrument ID
            ohlc_data: List of OHLCData objects
            currency: The currency
            data_source: The data source
            
        Returns:
            Number of data points saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for data_point in ohlc_data:
                # Check if already exists
                existing = db.query(FinancialDataPointDB).filter_by(
                    instrument_id=instrument_id,
                    timestamp=data_point.timestamp
                ).first()
                
                if existing:
                    # Update existing
                    existing.open = data_point.open
                    existing.high = data_point.high
                    existing.low = data_point.low
                    existing.close = data_point.close
                    existing.volume = data_point.volume
                    existing.adjusted_close = data_point.adjusted_close
                else:
                    # Create new
                    data_point_db = FinancialDataPointDB.from_dataclass(
                        data_point.to_data_point(instrument_id, currency, data_source)
                    )
                    db.add(data_point_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get OHLC scraper statistics."""
        return {
            "supported_timeframes": list(self.TIMEFRAME_MAP.keys()),
            "primary_source": "Yahoo Finance",
            "fallback_sources": ["Investing.com"],
        }
