"""
Instrument Discovery Module

Discovers financial instruments (stocks, ETFs, indices, commodities, forex, crypto) from various sources.
"""

import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pillar5.src.scraping.base import EthicalScraper, ScraperConfig
from pillar5.src.scraping.exchange_discovery import ExchangeDiscovery
from pillar5.src.models import FinancialInstrument, FinancialInstrumentDB
from pillar5.src.models.financial_instrument import InstrumentType


@dataclass
class InstrumentInfo:
    """Information about a financial instrument."""
    id: str
    symbol: str
    name: str
    type: str  # stock, etf, index, commodity, forex, crypto
    exchange_id: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    category: Optional[str] = None
    base_currency: str = "USD"
    quote_currency: Optional[str] = None
    description: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    website: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_instrument(self) -> FinancialInstrument:
        """Convert to FinancialInstrument dataclass."""
        return FinancialInstrument(
            id=self.id,
            symbol=self.symbol,
            name=self.name,
            type=self.type,
            exchange_id=self.exchange_id,
            sector=self.sector,
            industry=self.industry,
            category=self.category,
            base_currency=self.base_currency,
            quote_currency=self.quote_currency,
            description=self.description,
            founded_year=self.founded_year,
            headquarters=self.headquarters,
            website=self.website,
            is_active=self.is_active,
            metadata=self.metadata,
        )


class InstrumentDiscovery(EthicalScraper):
    """
    Discovers financial instruments from various sources.
    
    Supports:
    - Stocks from major exchanges
    - ETFs
    - Indices
    - Commodities
    - Forex pairs
    - Cryptocurrencies
    """
    
    # Common stock symbols by exchange
    COMMON_STOCKS = {
        "NYSE": [
            {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics"},
            {"symbol": "MSFT", "name": "Microsoft Corporation", "sector": "Technology", "industry": "Software"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "sector": "Technology", "industry": "Internet"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary", "industry": "Internet Retail"},
            {"symbol": "META", "name": "Meta Platforms Inc.", "sector": "Technology", "industry": "Social Media"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary", "industry": "Automotive"},
            {"symbol": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors"},
            {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "sector": "Financial Services", "industry": "Banks"},
            {"symbol": "V", "name": "Visa Inc.", "sector": "Financial Services", "industry": "Payment Processing"},
            {"symbol": "WMT", "name": "Walmart Inc.", "sector": "Consumer Staples", "industry": "Retail"},
        ],
        "NASDAQ": [
            {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics"},
            {"symbol": "MSFT", "name": "Microsoft Corporation", "sector": "Technology", "industry": "Software"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "sector": "Technology", "industry": "Internet"},
            {"symbol": "META", "name": "Meta Platforms Inc.", "sector": "Technology", "industry": "Social Media"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary", "industry": "Internet Retail"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary", "industry": "Automotive"},
            {"symbol": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors"},
            {"symbol": "NFLX", "name": "Netflix Inc.", "sector": "Communication Services", "industry": "Entertainment"},
            {"symbol": "ADBE", "name": "Adobe Inc.", "sector": "Technology", "industry": "Software"},
            {"symbol": "INTC", "name": "Intel Corporation", "sector": "Technology", "industry": "Semiconductors"},
        ],
        "LSE": [
            {"symbol": "UBSG.L", "name": "UBS Group AG", "sector": "Financial Services", "industry": "Banks"},
            {"symbol": "HSBA.L", "name": "HSBC Holdings plc", "sector": "Financial Services", "industry": "Banks"},
            {"symbol": "BP.L", "name": "BP plc", "sector": "Energy", "industry": "Oil & Gas"},
            {"symbol": "SHEL.L", "name": "Shell plc", "sector": "Energy", "industry": "Oil & Gas"},
            {"symbol": "UU.L", "name": "United Utilities Group PLC", "sector": "Utilities", "industry": "Utilities"},
        ],
    }
    
    # Common ETFs
    COMMON_ETFS = [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "type": "etf", "exchange_id": "NYSE", "category": "Large Cap"},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust", "type": "etf", "exchange_id": "NASDAQ", "category": "Large Cap"},
        {"symbol": "DIA", "name": "SPDR Dow Jones Industrial Average ETF Trust", "type": "etf", "exchange_id": "NYSE", "category": "Large Cap"},
        {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "type": "etf", "exchange_id": "NYSE", "category": "Small Cap"},
        {"symbol": "EFA", "name": "iShares MSCI EAFE ETF", "type": "etf", "exchange_id": "NYSE", "category": "International"},
        {"symbol": "EEM", "name": "iShares MSCI Emerging Markets ETF", "type": "etf", "exchange_id": "NYSE", "category": "Emerging Markets"},
        {"symbol": "GLD", "name": "SPDR Gold Shares", "type": "etf", "exchange_id": "NYSE", "category": "Commodity"},
        {"symbol": "SLV", "name": "iShares Silver Trust", "type": "etf", "exchange_id": "NYSE", "category": "Commodity"},
        {"symbol": "USO", "name": "United States Oil Fund", "type": "etf", "exchange_id": "NYSE", "category": "Commodity"},
        {"symbol": "ARKK", "name": "ARK Innovation ETF", "type": "etf", "exchange_id": "NYSE", "category": "Thematic"},
    ]
    
    # Common indices
    COMMON_INDICES = [
        {"symbol": "^GSPC", "name": "S&P 500", "type": "index", "exchange_id": None, "base_currency": "USD"},
        {"symbol": "^DJI", "name": "Dow Jones Industrial Average", "type": "index", "exchange_id": None, "base_currency": "USD"},
        {"symbol": "^IXIC", "name": "NASDAQ Composite", "type": "index", "exchange_id": None, "base_currency": "USD"},
        {"symbol": "^RUT", "name": "Russell 2000", "type": "index", "exchange_id": None, "base_currency": "USD"},
        {"symbol": "^VIX", "name": "CBOE Volatility Index", "type": "index", "exchange_id": None, "base_currency": "USD"},
        {"symbol": "^FTSE", "name": "FTSE 100", "type": "index", "exchange_id": "LSE", "base_currency": "GBP"},
        {"symbol": "^N225", "name": "Nikkei 225", "type": "index", "exchange_id": "TSE", "base_currency": "JPY"},
        {"symbol": "^HSI", "name": "Hang Seng Index", "type": "index", "exchange_id": "HKEX", "base_currency": "HKD"},
        {"symbol": "^STRAITS", "name": "Strait Times Index", "type": "index", "exchange_id": "SGX", "base_currency": "SGD"},
        {"symbol": "^AXJO", "name": "S&P/ASX 200", "type": "index", "exchange_id": "ASX", "base_currency": "AUD"},
    ]
    
    # Common commodities
    COMMON_COMMODITIES = [
        {"symbol": "XAU=F", "name": "Gold", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "XAG=F", "name": "Silver", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "CL=F", "name": "Crude Oil (Light)", "type": "commodity", "base_currency": "USD", "category": "Energy"},
        {"symbol": "BRN=F", "name": "Crude Oil (Brent)", "type": "commodity", "base_currency": "USD", "category": "Energy"},
        {"symbol": "NG=F", "name": "Natural Gas", "type": "commodity", "base_currency": "USD", "category": "Energy"},
        {"symbol": "GC=F", "name": "Gold (COMEX)", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "SI=F", "name": "Silver (COMEX)", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "PL=F", "name": "Platinum", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "PA=F", "name": "Palladium", "type": "commodity", "base_currency": "USD", "category": "Precious Metals"},
        {"symbol": "C=F", "name": "Corn", "type": "commodity", "base_currency": "USD", "category": "Agriculture"},
        {"symbol": "S=F", "name": "Soybeans", "type": "commodity", "base_currency": "USD", "category": "Agriculture"},
        {"symbol": "W=F", "name": "Wheat", "type": "commodity", "base_currency": "USD", "category": "Agriculture"},
        {"symbol": "KC=F", "name": "Coffee", "type": "commodity", "base_currency": "USD", "category": "Soft Commodities"},
        {"symbol": "CT=F", "name": "Cotton", "type": "commodity", "base_currency": "USD", "category": "Soft Commodities"},
        {"symbol": "SB=F", "name": "Sugar", "type": "commodity", "base_currency": "USD", "category": "Soft Commodities"},
        {"symbol": "CC=F", "name": "Cocoa", "type": "commodity", "base_currency": "USD", "category": "Soft Commodities"},
    ]
    
    # Common forex pairs
    COMMON_FOREX = [
        {"symbol": "EUR-USD", "name": "Euro/US Dollar", "type": "forex", "base_currency": "EUR", "quote_currency": "USD"},
        {"symbol": "USD-JPY", "name": "US Dollar/Japanese Yen", "type": "forex", "base_currency": "USD", "quote_currency": "JPY"},
        {"symbol": "GBP-USD", "name": "British Pound/US Dollar", "type": "forex", "base_currency": "GBP", "quote_currency": "USD"},
        {"symbol": "USD-CAD", "name": "US Dollar/Canadian Dollar", "type": "forex", "base_currency": "USD", "quote_currency": "CAD"},
        {"symbol": "USD-CHF", "name": "US Dollar/Swiss Franc", "type": "forex", "base_currency": "USD", "quote_currency": "CHF"},
        {"symbol": "AUD-USD", "name": "Australian Dollar/US Dollar", "type": "forex", "base_currency": "AUD", "quote_currency": "USD"},
        {"symbol": "NZD-USD", "name": "New Zealand Dollar/US Dollar", "type": "forex", "base_currency": "NZD", "quote_currency": "USD"},
        {"symbol": "EUR-GBP", "name": "Euro/British Pound", "type": "forex", "base_currency": "EUR", "quote_currency": "GBP"},
        {"symbol": "EUR-JPY", "name": "Euro/Japanese Yen", "type": "forex", "base_currency": "EUR", "quote_currency": "JPY"},
        {"symbol": "USD-CNY", "name": "US Dollar/Chinese Yuan", "type": "forex", "base_currency": "USD", "quote_currency": "CNY"},
    ]
    
    # Common cryptocurrencies
    COMMON_CRYPTO = [
        {"symbol": "BTC-USD", "name": "Bitcoin", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "ETH-USD", "name": "Ethereum", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "BNB-USD", "name": "Binance Coin", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "SOL-USD", "name": "Solana", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "XRP-USD", "name": "XRP", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "ADA-USD", "name": "Cardano", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "DOGE-USD", "name": "Dogecoin", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "DOT-USD", "name": "Polkadot", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "AVAX-USD", "name": "Avalanche", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
        {"symbol": "MATIC-USD", "name": "Polygon", "type": "crypto", "base_currency": "USD", "quote_currency": "USD"},
    ]
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize InstrumentDiscovery."""
        super().__init__(config)
        self.exchange_discovery = ExchangeDiscovery(config)
        self._instruments_cache: Dict[str, List[InstrumentInfo]] = {}
    
    def get_instruments_by_type(self, instrument_type: str, exchange_id: Optional[str] = None) -> List[InstrumentInfo]:
        """
        Get instruments of a specific type.
        
        Args:
            instrument_type: Type of instrument ('stock', 'etf', 'index', 'commodity', 'forex', 'crypto')
            exchange_id: Optional exchange ID to filter by
            
        Returns:
            List of InstrumentInfo objects
        """
        cache_key = f"{instrument_type}:{exchange_id}"
        
        if cache_key in self._instruments_cache:
            return self._instruments_cache[cache_key]
        
        instruments = []
        
        if instrument_type == "stock":
            instruments = self._get_stocks(exchange_id)
        elif instrument_type == "etf":
            instruments = self._get_etfs(exchange_id)
        elif instrument_type == "index":
            instruments = self._get_indices()
        elif instrument_type == "commodity":
            instruments = self._get_commodities()
        elif instrument_type == "forex":
            instruments = self._get_forex()
        elif instrument_type == "crypto":
            instruments = self._get_crypto()
        
        self._instruments_cache[cache_key] = instruments
        return instruments
    
    def _get_stocks(self, exchange_id: Optional[str] = None) -> List[InstrumentInfo]:
        """Get stock instruments."""
        instruments = []
        
        if exchange_id:
            # Get stocks for specific exchange
            exchange_stocks = self.COMMON_STOCKS.get(exchange_id, [])
            for stock in exchange_stocks:
                instruments.append(InstrumentInfo(
                    id=stock["symbol"],
                    symbol=stock["symbol"],
                    name=stock["name"],
                    type="stock",
                    exchange_id=exchange_id,
                    sector=stock.get("sector"),
                    industry=stock.get("industry"),
                    base_currency=self._get_exchange_currency(exchange_id),
                ))
        else:
            # Get stocks from all exchanges
            for exchange_id_key, stocks in self.COMMON_STOCKS.items():
                for stock in stocks:
                    instruments.append(InstrumentInfo(
                        id=stock["symbol"],
                        symbol=stock["symbol"],
                        name=stock["name"],
                        type="stock",
                        exchange_id=exchange_id_key,
                        sector=stock.get("sector"),
                        industry=stock.get("industry"),
                        base_currency=self._get_exchange_currency(exchange_id_key),
                    ))
        
        return instruments
    
    def _get_etfs(self, exchange_id: Optional[str] = None) -> List[InstrumentInfo]:
        """Get ETF instruments."""
        instruments = []
        
        for etf in self.COMMON_ETFS:
            if exchange_id is None or etf.get("exchange_id") == exchange_id:
                instruments.append(InstrumentInfo(
                    id=etf["symbol"],
                    symbol=etf["symbol"],
                    name=etf["name"],
                    type="etf",
                    exchange_id=etf.get("exchange_id"),
                    category=etf.get("category"),
                    base_currency=self._get_exchange_currency(etf.get("exchange_id")),
                ))
        
        return instruments
    
    def _get_indices(self) -> List[InstrumentInfo]:
        """Get index instruments."""
        return [
            InstrumentInfo(
                id=index["symbol"],
                symbol=index["symbol"],
                name=index["name"],
                type="index",
                exchange_id=index.get("exchange_id"),
                base_currency=index.get("base_currency", "USD"),
            )
            for index in self.COMMON_INDICES
        ]
    
    def _get_commodities(self) -> List[InstrumentInfo]:
        """Get commodity instruments."""
        return [
            InstrumentInfo(
                id=commodity["symbol"],
                symbol=commodity["symbol"],
                name=commodity["name"],
                type="commodity",
                base_currency=commodity.get("base_currency", "USD"),
                category=commodity.get("category"),
            )
            for commodity in self.COMMON_COMMODITIES
        ]
    
    def _get_forex(self) -> List[InstrumentInfo]:
        """Get forex instruments."""
        return [
            InstrumentInfo(
                id=forex["symbol"],
                symbol=forex["symbol"],
                name=forex["name"],
                type="forex",
                base_currency=forex["base_currency"],
                quote_currency=forex["quote_currency"],
            )
            for forex in self.COMMON_FOREX
        ]
    
    def _get_crypto(self) -> List[InstrumentInfo]:
        """Get crypto instruments."""
        return [
            InstrumentInfo(
                id=crypto["symbol"],
                symbol=crypto["symbol"],
                name=crypto["name"],
                type="crypto",
                base_currency=crypto.get("base_currency", "USD"),
                quote_currency=crypto.get("quote_currency", "USD"),
            )
            for crypto in self.COMMON_CRYPTO
        ]
    
    def _get_exchange_currency(self, exchange_id: str) -> str:
        """Get the currency for an exchange."""
        exchange = self.exchange_discovery.get_exchange_by_id(exchange_id)
        if exchange:
            return exchange.currency
        return "USD"
    
    def get_instrument_by_symbol(self, symbol: str, instrument_type: Optional[str] = None) -> Optional[InstrumentInfo]:
        """
        Get instrument by symbol.
        
        Args:
            symbol: The instrument symbol (e.g., 'AAPL', 'BTC-USD')
            instrument_type: Optional type to narrow search
            
        Returns:
            InstrumentInfo or None if not found
        """
        # Search in all instrument types
        types_to_search = [instrument_type] if instrument_type else ["stock", "etf", "index", "commodity", "forex", "crypto"]
        
        for inst_type in types_to_search:
            instruments = self.get_instruments_by_type(inst_type)
            for instrument in instruments:
                if instrument.symbol.upper() == symbol.upper():
                    return instrument
        
        return None
    
    def scrape_instrument_list(self, exchange_id: str, instrument_type: str = "stock") -> List[InstrumentInfo]:
        """
        Scrape instrument list from a specific exchange.
        
        Args:
            exchange_id: The exchange ID
            instrument_type: Type of instruments to scrape
            
        Returns:
            List of InstrumentInfo objects
        """
        # For now, return predefined instruments
        # In the future, this will scrape from exchange websites
        return self.get_instruments_by_type(instrument_type, exchange_id)
    
    def scrape_instrument_details(self, symbol: str, instrument_type: str) -> Optional[InstrumentInfo]:
        """
        Scrape detailed information for a specific instrument.
        
        Args:
            symbol: The instrument symbol
            instrument_type: Type of instrument
            
        Returns:
            InstrumentInfo with detailed metadata or None if failed
        """
        # Get basic info from predefined lists
        instrument = self.get_instrument_by_symbol(symbol, instrument_type)
        if not instrument:
            return None
        
        # Try to scrape additional details from Yahoo Finance
        try:
            if instrument_type in ["stock", "etf", "index"]:
                url = f"https://finance.yahoo.com/quote/{symbol}"
                soup = self.get_soup(url)
                if soup:
                    # Extract description
                    description_elem = soup.find("p", class_="D(ib) Va(t)")
                    if description_elem:
                        instrument.description = description_elem.get_text(strip=True)
                    
                    # Extract sector/industry for stocks
                    if instrument_type == "stock":
                        sector_elem = soup.find("span", text="Sector")
                        if sector_elem:
                            sector_value = sector_elem.find_next("span")
                            if sector_value:
                                instrument.sector = sector_value.get_text(strip=True)
                        
                        industry_elem = soup.find("span", text="Industry")
                        if industry_elem:
                            industry_value = industry_elem.find_next("span")
                            if industry_value:
                                instrument.industry = industry_value.get_text(strip=True)
                    
                    # Update metadata
                    instrument.metadata["last_scraped"] = datetime.now().isoformat()
                    instrument.metadata["source"] = "Yahoo Finance"
        except Exception as e:
            print(f"Error scraping details for {symbol}: {e}")
        
        return instrument
    
    def save_to_database(self, instruments: List[InstrumentInfo]) -> int:
        """
        Save instruments to the database.
        
        Args:
            instruments: List of InstrumentInfo objects to save
            
        Returns:
            Number of instruments saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for instrument_info in instruments:
                # Check if already exists
                existing = db.query(FinancialInstrumentDB).filter_by(id=instrument_info.id).first()
                if existing:
                    # Update existing
                    for key, value in instrument_info.__dict__.items():
                        if not key.startswith('_') and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    # Create new
                    instrument_db = FinancialInstrumentDB.from_dataclass(instrument_info.to_instrument())
                    db.add(instrument_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_all_instruments(self) -> List[InstrumentInfo]:
        """
        Get all instruments across all types.
        
        Returns:
            List of all InstrumentInfo objects
        """
        all_instruments = []
        
        for instrument_type in ["stock", "etf", "index", "commodity", "forex", "crypto"]:
            all_instruments.extend(self.get_instruments_by_type(instrument_type))
        
        return all_instruments
    
    def get_stats(self) -> Dict[str, Any]:
        """Get instrument discovery statistics."""
        return {
            "total_instruments": len(self.get_all_instruments()),
            "stocks": len(self.get_instruments_by_type("stock")),
            "etfs": len(self.get_instruments_by_type("etf")),
            "indices": len(self.get_instruments_by_type("index")),
            "commodities": len(self.get_instruments_by_type("commodity")),
            "forex": len(self.get_instruments_by_type("forex")),
            "crypto": len(self.get_instruments_by_type("crypto")),
        }
