"""
Exchange Discovery Module

Discovers and scrapes information about stock exchanges worldwide.
Supports 50+ exchanges across all major markets.
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pillar5.src.scraping.base import EthicalScraper, ScraperConfig
from pillar5.src.models import Exchange, ExchangeDB


@dataclass
class ExchangeInfo:
    """Information about a stock exchange."""
    id: str
    name: str
    country: str
    currency: str
    timezone: str
    website: Optional[str] = None
    trading_hours: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_exchange(self) -> Exchange:
        """Convert to Exchange dataclass."""
        return Exchange(
            id=self.id,
            name=self.name,
            country=self.country,
            currency=self.currency,
            timezone=self.timezone,
            website=self.website,
            trading_hours=self.trading_hours,
            is_active=self.is_active,
            metadata=self.metadata,
        )


class ExchangeDiscovery(EthicalScraper):
    """
    Discovers stock exchanges and their metadata.
    
    Supports:
    - Major exchanges (NYSE, NASDAQ, LSE, TSE, HKEX, etc.)
    - Regional exchanges
    - Commodity exchanges
    - Crypto exchanges
    """
    
    # Pre-defined list of major exchanges with their metadata
    MAJOR_EXCHANGES = [
        {
            "id": "NYSE",
            "name": "New York Stock Exchange",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "website": "https://www.nyse.com",
            "trading_hours": "09:30-16:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1792,
                "market_cap": "30T+",
            }
        },
        {
            "id": "NASDAQ",
            "name": "NASDAQ",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "website": "https://www.nasdaq.com",
            "trading_hours": "09:30-16:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1971,
                "market_cap": "20T+",
            }
        },
        {
            "id": "LSE",
            "name": "London Stock Exchange",
            "country": "GB",
            "currency": "GBP",
            "timezone": "Europe/London",
            "website": "https://www.londonstockexchange.com",
            "trading_hours": "08:00-16:30",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1801,
                "market_cap": "3T+",
            }
        },
        {
            "id": "TSE",
            "name": "Tokyo Stock Exchange",
            "country": "JP",
            "currency": "JPY",
            "timezone": "Asia/Tokyo",
            "website": "https://www.tse.or.jp",
            "trading_hours": "09:00-15:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1878,
                "market_cap": "6T+",
            }
        },
        {
            "id": "HKEX",
            "name": "Hong Kong Stock Exchange",
            "country": "HK",
            "currency": "HKD",
            "timezone": "Asia/Hong_Kong",
            "website": "https://www.hkex.com.hk",
            "trading_hours": "09:30-16:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1891,
                "market_cap": "5T+",
            }
        },
        {
            "id": "SGX",
            "name": "Singapore Exchange",
            "country": "SG",
            "currency": "SGD",
            "timezone": "Asia/Singapore",
            "website": "https://www.sgx.com",
            "trading_hours": "09:00-17:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1999,
                "market_cap": "1T+",
            }
        },
        {
            "id": "ASX",
            "name": "Australian Securities Exchange",
            "country": "AU",
            "currency": "AUD",
            "timezone": "Australia/Sydney",
            "website": "https://www.asx.com.au",
            "trading_hours": "10:00-16:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1987,
                "market_cap": "2T+",
            }
        },
        {
            "id": "TSX",
            "name": "Toronto Stock Exchange",
            "country": "CA",
            "currency": "CAD",
            "timezone": "America/Toronto",
            "website": "https://www.tsx.com",
            "trading_hours": "09:30-16:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1861,
                "market_cap": "3T+",
            }
        },
        {
            "id": "FWB",
            "name": "Frankfurt Stock Exchange",
            "country": "DE",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
            "website": "https://www.boerse-frankfurt.de",
            "trading_hours": "09:00-17:30",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1585,
                "market_cap": "2T+",
            }
        },
        {
            "id": "EURONEXT",
            "name": "Euronext",
            "country": "EU",
            "currency": "EUR",
            "timezone": "Europe/Paris",
            "website": "https://www.euronext.com",
            "trading_hours": "09:00-17:30",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 2000,
                "market_cap": "4T+",
            }
        },
        {
            "id": "BSE",
            "name": "Bombay Stock Exchange",
            "country": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "website": "https://www.bseindia.com",
            "trading_hours": "09:15-15:30",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1875,
                "market_cap": "3T+",
            }
        },
        {
            "id": "NSE",
            "name": "National Stock Exchange of India",
            "country": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "website": "https://www.nseindia.com",
            "trading_hours": "09:15-15:30",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1992,
                "market_cap": "3T+",
            }
        },
        {
            "id": "SSE",
            "name": "Shanghai Stock Exchange",
            "country": "CN",
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
            "website": "https://www.sse.com.cn",
            "trading_hours": "09:30-15:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1990,
                "market_cap": "7T+",
            }
        },
        {
            "id": "SZSE",
            "name": "Shenzhen Stock Exchange",
            "country": "CN",
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
            "website": "https://www.szse.cn",
            "trading_hours": "09:30-15:00",
            "metadata": {
                "type": "stock",
                "tier": "1",
                "founded": 1990,
                "market_cap": "4T+",
            }
        },
        {
            "id": "CME",
            "name": "Chicago Mercantile Exchange",
            "country": "US",
            "currency": "USD",
            "timezone": "America/Chicago",
            "website": "https://www.cmegroup.com",
            "trading_hours": "24/5",
            "metadata": {
                "type": "commodity",
                "tier": "1",
                "founded": 1898,
            }
        },
        {
            "id": "ICE",
            "name": "Intercontinental Exchange",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "website": "https://www.theice.com",
            "trading_hours": "24/5",
            "metadata": {
                "type": "commodity",
                "tier": "1",
                "founded": 2000,
            }
        },
        {
            "id": "LME",
            "name": "London Metal Exchange",
            "country": "GB",
            "currency": "USD",
            "timezone": "Europe/London",
            "website": "https://www.lme.com",
            "trading_hours": "01:00-19:00",
            "metadata": {
                "type": "commodity",
                "tier": "1",
                "founded": 1877,
            }
        },
        {
            "id": "COMEX",
            "name": "COMEX",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "website": "https://www.cmegroup.com/trading/metals/",
            "trading_hours": "24/5",
            "metadata": {
                "type": "commodity",
                "tier": "1",
                "founded": 1933,
            }
        },
        {
            "id": "NYMEX",
            "name": "New York Mercantile Exchange",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "website": "https://www.cmegroup.com/trading/energy/",
            "trading_hours": "24/5",
            "metadata": {
                "type": "commodity",
                "tier": "1",
                "founded": 1872,
            }
        },
    ]
    
    # Regional exchanges
    REGIONAL_EXCHANGES = [
        {"id": "B3", "name": "B3 (Brasil Bolsa Balcão)", "country": "BR", "currency": "BRL", "timezone": "America/Sao_Paulo", "website": "https://www.b3.com.br"},
        {"id": "BMV", "name": "Mexican Stock Exchange", "country": "MX", "currency": "MXN", "timezone": "America/Mexico_City", "website": "https://www.bmv.com.mx"},
        {"id": "BCBA", "name": "Buenos Aires Stock Exchange", "country": "AR", "currency": "ARS", "timezone": "America/Argentina/Buenos_Aires", "website": "https://www.bcba.sba.com.ar"},
        {"id": "BVL", "name": "Lima Stock Exchange", "country": "PE", "currency": "PEN", "timezone": "America/Lima", "website": "https://www.bvl.com.pe"},
        {"id": "BCS", "name": "Santiago Stock Exchange", "country": "CL", "currency": "CLP", "timezone": "America/Santiago", "website": "https://www.bolsadesantiago.com"},
        {"id": "BCV", "name": "Caracas Stock Exchange", "country": "VE", "currency": "VES", "timezone": "America/Caracas", "website": "https://www.bcv.org.ve"},
        {"id": "JSE", "name": "Johannesburg Stock Exchange", "country": "ZA", "currency": "ZAR", "timezone": "Africa/Johannesburg", "website": "https://www.jse.co.za"},
        {"id": "NSE_ZA", "name": "Nigerian Stock Exchange", "country": "NG", "currency": "NGN", "timezone": "Africa/Lagos", "website": "https://www.nse.com.ng"},
        {"id": "EGX", "name": "Egyptian Exchange", "country": "EG", "currency": "EGP", "timezone": "Africa/Cairo", "website": "https://www.egx.com.eg"},
        {"id": "TADAWUL", "name": "Saudi Stock Exchange", "country": "SA", "currency": "SAR", "timezone": "Asia/Riyadh", "website": "https://www.tadawul.com.sa"},
        {"id": "DFM", "name": "Dubai Financial Market", "country": "AE", "currency": "AED", "timezone": "Asia/Dubai", "website": "https://www.dfm.ae"},
        {"id": "QSE", "name": "Qatar Stock Exchange", "country": "QA", "currency": "QAR", "timezone": "Asia/Qatar", "website": "https://www.qe.com.qa"},
        {"id": "KSE", "name": "Korea Exchange", "country": "KR", "currency": "KRW", "timezone": "Asia/Seoul", "website": "https://www.krx.co.kr"},
        {"id": "TWSE", "name": "Taiwan Stock Exchange", "country": "TW", "currency": "TWD", "timezone": "Asia/Taipei", "website": "https://www.twse.com.tw"},
        {"id": "IDX", "name": "Indonesia Stock Exchange", "country": "ID", "currency": "IDR", "timezone": "Asia/Jakarta", "website": "https://www.idx.co.id"},
        {"id": "SET", "name": "Stock Exchange of Thailand", "country": "TH", "currency": "THB", "timezone": "Asia/Bangkok", "website": "https://www.set.or.th"},
        {"id": "VNM", "name": "Hochiminh Stock Exchange", "country": "VN", "currency": "VND", "timezone": "Asia/Ho_Chi_Minh", "website": "https://www.hsx.vn"},
        {"id": "PSE", "name": "Philippine Stock Exchange", "country": "PH", "currency": "PHP", "timezone": "Asia/Manila", "website": "https://www.pse.com.ph"},
        {"id": "KLSE", "name": "Bursa Malaysia", "country": "MY", "currency": "MYR", "timezone": "Asia/Kuala_Lumpur", "website": "https://www.bursamalaysia.com"},
        {"id": "NZX", "name": "New Zealand Exchange", "country": "NZ", "currency": "NZD", "timezone": "Pacific/Auckland", "website": "https://www.nzx.com"},
        {"id": "OMX", "name": "Nasdaq Nordic", "country": "SE", "currency": "SEK", "timezone": "Europe/Stockholm", "website": "https://www.nasdaqomxnordic.com"},
        {"id": "HEL", "name": "Helsinki Stock Exchange", "country": "FI", "currency": "EUR", "timezone": "Europe/Helsinki", "website": "https://www.nasdaqhelsinki.com"},
        {"id": "OSL", "name": "Oslo Stock Exchange", "country": "NO", "currency": "NOK", "timezone": "Europe/Oslo", "website": "https://www.oslobors.no"},
        {"id": "CPH", "name": "Nasdaq Copenhagen", "country": "DK", "currency": "DKK", "timezone": "Europe/Copenhagen", "website": "https://www.nasdaqcopenhagen.com"},
        {"id": "IST", "name": "Istanbul Stock Exchange", "country": "TR", "currency": "TRY", "timezone": "Europe/Istanbul", "website": "https://www.borsaistanbul.com"},
        {"id": "TASE", "name": "Tel Aviv Stock Exchange", "country": "IL", "currency": "ILS", "timezone": "Asia/Jerusalem", "website": "https://www.tase.co.il"},
        {"id": "MOEX", "name": "Moscow Exchange", "country": "RU", "currency": "RUB", "timezone": "Europe/Moscow", "website": "https://www.moex.com"},
        {"id": "WSE", "name": "Warsaw Stock Exchange", "country": "PL", "currency": "PLN", "timezone": "Europe/Warsaw", "website": "https://www.gpw.pl"},
        {"id": "BUD", "name": "Budapest Stock Exchange", "country": "HU", "currency": "HUF", "timezone": "Europe/Budapest", "website": "https://www.bse.hu"},
        {"id": "PRA", "name": "Prague Stock Exchange", "country": "CZ", "currency": "CZK", "timezone": "Europe/Prague", "website": "https://www.pse.cz"},
        {"id": "LBX", "name": "Ljubljana Stock Exchange", "country": "SI", "currency": "EUR", "timezone": "Europe/Ljubljana", "website": "https://www.ljse.si"},
        {"id": "ZAG", "name": "Zagreb Stock Exchange", "country": "HR", "currency": "HRK", "timezone": "Europe/Zagreb", "website": "https://www.zse.hr"},
        {"id": "BEY", "name": "Beirut Stock Exchange", "country": "LB", "currency": "LBP", "timezone": "Asia/Beirut", "website": "https://www.bse.com.lb"},
        {"id": "AMM", "name": "Amman Stock Exchange", "country": "JO", "currency": "JOD", "timezone": "Asia/Amman", "website": "https://www.ase.com.jo"},
        {"id": "KUW", "name": "Boursa Kuwait", "country": "KW", "currency": "KWD", "timezone": "Asia/Kuwait", "website": "https://www.boursakuwait.com.kw"},
        {"id": "MUS", "name": "Stock Exchange of Mauritius", "country": "MU", "currency": "MUR", "timezone": "Indian/Mauritius", "website": "https://www.stockexchangeofmauritius.com"},
        {"id": "CSE", "name": "Colombo Stock Exchange", "country": "LK", "currency": "LKR", "timezone": "Asia/Colombo", "website": "https://www.cse.lk"},
        {"id": "DHA", "name": "Dhaka Stock Exchange", "country": "BD", "currency": "BDT", "timezone": "Asia/Dhaka", "website": "https://www.dsebd.org"},
        {"id": "KAR", "name": "Karachi Stock Exchange", "country": "PK", "currency": "PKR", "timezone": "Asia/Karachi", "website": "https://www.psx.com.pk"},
    ]
    
    # Crypto exchanges
    CRYPTO_EXCHANGES = [
        {"id": "BINANCE", "name": "Binance", "country": "CY", "currency": "USD", "timezone": "UTC", "website": "https://www.binance.com", "metadata": {"type": "crypto"}},
        {"id": "COINBASE", "name": "Coinbase", "country": "US", "currency": "USD", "timezone": "UTC", "website": "https://www.coinbase.com", "metadata": {"type": "crypto"}},
        {"id": "KRAKEN", "name": "Kraken", "country": "US", "currency": "USD", "timezone": "UTC", "website": "https://www.kraken.com", "metadata": {"type": "crypto"}},
        {"id": "FTX", "name": "FTX", "country": "AG", "currency": "USD", "timezone": "UTC", "website": "https://ftx.com", "metadata": {"type": "crypto"}},
        {"id": "BYBIT", "name": "Bybit", "country": "SC", "currency": "USD", "timezone": "UTC", "website": "https://www.bybit.com", "metadata": {"type": "crypto"}},
        {"id": "OKX", "name": "OKX", "country": "SC", "currency": "USD", "timezone": "UTC", "website": "https://www.okx.com", "metadata": {"type": "crypto"}},
        {"id": "HUOBI", "name": "Huobi", "country": "SC", "currency": "USD", "timezone": "UTC", "website": "https://www.huobi.com", "metadata": {"type": "crypto"}},
        {"id": "BITFINEX", "name": "Bitfinex", "country": "BM", "currency": "USD", "timezone": "UTC", "website": "https://www.bitfinex.com", "metadata": {"type": "crypto"}},
        {"id": "BITSTAMP", "name": "Bitstamp", "country": "GB", "currency": "USD", "timezone": "UTC", "website": "https://www.bitstamp.net", "metadata": {"type": "crypto"}},
        {"id": "GEMINI", "name": "Gemini", "country": "US", "currency": "USD", "timezone": "UTC", "website": "https://www.gemini.com", "metadata": {"type": "crypto"}},
    ]
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize ExchangeDiscovery."""
        super().__init__(config)
        self._exchanges_cache: Optional[List[ExchangeInfo]] = None
    
    def get_all_exchanges(self, include_crypto: bool = True) -> List[ExchangeInfo]:
        """
        Get all known exchanges.
        
        Args:
            include_crypto: Whether to include cryptocurrency exchanges
            
        Returns:
            List of ExchangeInfo objects
        """
        if self._exchanges_cache is not None:
            return self._exchanges_cache
        
        exchanges = []
        
        # Add major exchanges
        for exchange_data in self.MAJOR_EXCHANGES:
            exchanges.append(ExchangeInfo(**exchange_data))
        
        # Add regional exchanges
        for exchange_data in self.REGIONAL_EXCHANGES:
            exchanges.append(ExchangeInfo(**exchange_data))
        
        # Add crypto exchanges if requested
        if include_crypto:
            for exchange_data in self.CRYPTO_EXCHANGES:
                exchanges.append(ExchangeInfo(**exchange_data))
        
        self._exchanges_cache = exchanges
        return exchanges
    
    def get_exchange_by_id(self, exchange_id: str) -> Optional[ExchangeInfo]:
        """
        Get exchange by ID.
        
        Args:
            exchange_id: The exchange ID (e.g., 'NYSE', 'NASDAQ')
            
        Returns:
            ExchangeInfo or None if not found
        """
        for exchange in self.get_all_exchanges():
            if exchange.id.upper() == exchange_id.upper():
                return exchange
        return None
    
    def get_exchanges_by_country(self, country: str) -> List[ExchangeInfo]:
        """
        Get all exchanges in a specific country.
        
        Args:
            country: Two-letter country code (e.g., 'US', 'GB')
            
        Returns:
            List of ExchangeInfo objects
        """
        return [
            exchange for exchange in self.get_all_exchanges()
            if exchange.country.upper() == country.upper()
        ]
    
    def get_exchanges_by_type(self, exchange_type: str) -> List[ExchangeInfo]:
        """
        Get all exchanges of a specific type.
        
        Args:
            exchange_type: Type of exchange ('stock', 'commodity', 'crypto')
            
        Returns:
            List of ExchangeInfo objects
        """
        return [
            exchange for exchange in self.get_all_exchanges()
            if exchange.metadata.get('type', 'stock').lower() == exchange_type.lower()
        ]
    
    def scrape_exchange_list(self, source: str = "nasdaq") -> List[ExchangeInfo]:
        """
        Scrape exchange list from a specific source.
        
        Args:
            source: The source to scrape from ('nasdaq', 'wikipedia', etc.)
            
        Returns:
            List of ExchangeInfo objects
        """
        # For now, return the predefined list
        # In the future, this can be enhanced to scrape from various sources
        return self.get_all_exchanges()
    
    def update_exchange_metadata(self, exchange_id: str) -> Optional[ExchangeInfo]:
        """
        Update metadata for a specific exchange by scraping its website.
        
        Args:
            exchange_id: The exchange ID
            
        Returns:
            Updated ExchangeInfo or None if failed
        """
        exchange = self.get_exchange_by_id(exchange_id)
        if not exchange or not exchange.website:
            return None
        
        try:
            soup = self.get_soup(exchange.website)
            if soup:
                # Extract additional metadata from the website
                # This is a placeholder - actual implementation would parse the website
                metadata = exchange.metadata.copy()
                metadata['last_scraped'] = datetime.now().isoformat()
                
                return ExchangeInfo(
                    id=exchange.id,
                    name=exchange.name,
                    country=exchange.country,
                    currency=exchange.currency,
                    timezone=exchange.timezone,
                    website=exchange.website,
                    trading_hours=exchange.trading_hours,
                    is_active=exchange.is_active,
                    metadata=metadata,
                )
        except Exception as e:
            print(f"Error updating metadata for {exchange_id}: {e}")
            return None
        
        return exchange
    
    def save_to_database(self, exchanges: List[ExchangeInfo]) -> int:
        """
        Save exchanges to the database.
        
        Args:
            exchanges: List of ExchangeInfo objects to save
            
        Returns:
            Number of exchanges saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for exchange_info in exchanges:
                # Check if already exists
                existing = db.query(ExchangeDB).filter_by(id=exchange_info.id).first()
                if existing:
                    # Update existing
                    for key, value in exchange_info.__dict__.items():
                        if not key.startswith('_') and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    # Create new
                    exchange_db = ExchangeDB.from_dataclass(exchange_info.to_exchange())
                    db.add(exchange_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get exchange discovery statistics."""
        return {
            "total_exchanges": len(self.get_all_exchanges()),
            "major_exchanges": len(self.MAJOR_EXCHANGES),
            "regional_exchanges": len(self.REGIONAL_EXCHANGES),
            "crypto_exchanges": len(self.CRYPTO_EXCHANGES),
            "countries": len(set(e.country for e in self.get_all_exchanges())),
        }
