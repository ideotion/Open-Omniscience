"""
Pillar 6 Price Scraper

Scrapes rare earth price data from various market sources.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
import logging
import re

from bs4 import BeautifulSoup
from .base_scraper import RareEarthScraper, ScraperConfig, DEFAULT_CONFIG
from ..models import RareEarthPrice, PriceType, PriceUnit, PurityGrade
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class PriceScraper(RareEarthScraper):
    """
    Scraper for rare earth price data.
    
    Scrapes price information from various market sources including:
    - Metal Pages
    - Fastmarkets
    - Argus Media
    - Asian Metal
    - Shanghai Metal Market
    - Baotou Rare Earth Exchange
    - USGS
    - Roskill
    """
    
    # Market-specific selectors and parsers
    MARKET_PARSERS = {
        "metal_pages": {
            "url": "https://www.metal-pages.com/metalprices/rare-earth/",
            "selectors": {
                "price_table": "table.price-table",
                "price_row": "tr",
                "element": "td:nth-child(1)",
                "price": "td:nth-child(2)",
                "unit": "td:nth-child(3)",
                "currency": "td:nth-child(4)",
                "date": "td:nth-child(5)",
            },
        },
        "fastmarkets": {
            "url": "https://www.fastmarkets.com/rare-earth-prices",
            "selectors": {
                "price_table": "table.data-table",
                "price_row": "tr",
                "element": "td:nth-child(1)",
                "price": "td:nth-child(2)",
                "unit": "td:nth-child(3)",
                "currency": "td:nth-child(4)",
            },
        },
        "argus_media": {
            "url": "https://www.argusmedia.com/en/rare-earths",
            "selectors": {
                "price_table": "table.argus-table",
                "price_row": "tr",
                "element": "td:nth-child(1)",
                "price": "td:nth-child(2)",
            },
        },
        "asian_metal": {
            "url": "https://www.asianmetal.com/rare-earth-prices",
            "selectors": {
                "price_table": "table.price-table",
                "price_row": "tr",
                "element": "td:nth-child(1)",
                "price": "td:nth-child(2)",
                "unit": "td:nth-child(3)",
            },
        },
        "shanghai": {
            "url": "https://www.smm.cn/data/price",
            "selectors": {
                "price_table": "table.price-table",
                "price_row": "tr",
            },
        },
        "baotou": {
            "url": "https://www.cxre.com/price",
            "selectors": {
                "price_table": "table.price-table",
                "price_row": "tr",
            },
        },
    }
    
    # Element name mappings (common names to symbols)
    ELEMENT_MAPPINGS = {
        "scandium": "Sc",
        "yttrium": "Y",
        "lanthanum": "La",
        "cerium": "Ce",
        "praseodymium": "Pr",
        "neodymium": "Nd",
        "promethium": "Pm",
        "samarium": "Sm",
        "europium": "Eu",
        "gadolinium": "Gd",
        "terbium": "Tb",
        "dysprosium": "Dy",
        "holmium": "Ho",
        "erbium": "Er",
        "thulium": "Tm",
        "ytterbium": "Yb",
        "lutetium": "Lu",
        "nd": "Nd",
        "pr": "Pr",
        "sm": "Sm",
        "eu": "Eu",
        "gd": "Gd",
        "tb": "Tb",
        "dy": "Dy",
        "ho": "Ho",
        "er": "Er",
        "tm": "Tm",
        "yb": "Yb",
        "lu": "Lu",
    }
    
    # Unit mappings
    UNIT_MAPPINGS = {
        "usd/kg": ("USD", "per_kg"),
        "usd/kg": ("USD", "per_kg"),
        "usd per kg": ("USD", "per_kg"),
        "usd/ton": ("USD", "per_ton"),
        "usd per ton": ("USD", "per_ton"),
        "cny/kg": ("CNY", "per_kg"),
        "cny per kg": ("CNY", "per_kg"),
        "eur/kg": ("EUR", "per_kg"),
        "eur per kg": ("EUR", "per_kg"),
        "us$/kg": ("USD", "per_kg"),
        "us$/ton": ("USD", "per_ton"),
        "$/kg": ("USD", "per_kg"),
        "$/ton": ("USD", "per_ton"),
    }
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        name: str = "PriceScraper",
        markets: Optional[List[str]] = None,
    ):
        """
        Initialize the price scraper.
        
        Args:
            config: Scraper configuration
            name: Name of the scraper
            markets: List of markets to scrape (None = all)
        """
        super().__init__(config, name)
        self.markets = markets or list(self.MARKET_PARSERS.keys())
    
    def get_data_sources(self) -> List[str]:
        """Get the list of data sources for this scraper."""
        return [
            f"https://www.metal-pages.com/metalprices/rare-earth/",
            f"https://www.fastmarkets.com/rare-earth-prices",
            f"https://www.argusmedia.com/en/rare-earths",
            f"https://www.asianmetal.com/rare-earth-prices",
            f"https://www.smm.cn/data/price",
            f"https://www.cxre.com/price",
        ]
    
    def scrape(self, **kwargs) -> List[RareEarthPrice]:
        """
        Scrape price data from all configured markets.
        
        Args:
            **kwargs: Additional arguments
                - markets: List of specific markets to scrape
                - elements: List of specific elements to look for
                - days: Number of days of history to scrape
                
        Returns:
            List of RareEarthPrice objects
        """
        markets = kwargs.get("markets", self.markets)
        elements = kwargs.get("elements", None)
        
        all_prices = []
        
        for market_id in markets:
            if market_id not in self.MARKET_PARSERS:
                logger.warning(f"Unknown market: {market_id}")
                continue
            
            try:
                market_prices = self.scrape_market(market_id, elements)
                all_prices.extend(market_prices)
                logger.info(f"Scraped {len(market_prices)} prices from {market_id}")
            except Exception as e:
                logger.error(f"Failed to scrape {market_id}: {e}")
        
        return all_prices
    
    def scrape_market(
        self, 
        market_id: str, 
        elements: Optional[List[str]] = None
    ) -> List[RareEarthPrice]:
        """
        Scrape price data from a specific market.
        
        Args:
            market_id: Market identifier
            elements: Optional list of element symbols to filter by
            
        Returns:
            List of RareEarthPrice objects
        """
        market_info = self.MARKET_PARSERS.get(market_id)
        if not market_info:
            return []
        
        url = market_info["url"]
        soup = self.get_soup(url)
        
        if not soup:
            logger.warning(f"Failed to fetch page for {market_id}")
            return []
        
        # Parse prices based on market-specific selectors
        prices = []
        selectors = market_info["selectors"]
        
        # Find the price table
        price_table = soup.select_one(selectors["price_table"])
        if not price_table:
            logger.warning(f"Price table not found for {market_id}")
            return []
        
        # Parse each row
        rows = price_table.select(selectors["price_row"])
        for row in rows:
            try:
                price_data = self._parse_price_row(row, selectors, market_id)
                if price_data:
                    # Filter by elements if specified
                    if elements and price_data["element_symbol"] not in elements:
                        continue
                    
                    # Create RareEarthPrice object
                    price = RareEarthPrice(
                        element_symbol=price_data["element_symbol"],
                        market_id=market_id,
                        price=price_data["price"],
                        currency=price_data["currency"],
                        price_type=PriceType.SPOT,
                        price_unit=PriceUnit(price_data["price_unit"]),
                        purity_grade=PurityGrade.COMMERCIAL,
                        date=price_data.get("date", date.today()),
                        timestamp=datetime.utcnow(),
                        source_url=url,
                        is_verified=False,
                        confidence=0.8,
                        notes=f"Scraped from {market_id}",
                    )
                    prices.append(price)
                    
            except Exception as e:
                logger.debug(f"Failed to parse row in {market_id}: {e}")
                continue
        
        return prices
    
    def _parse_price_row(
        self, 
        row: BeautifulSoup, 
        selectors: Dict[str, str],
        market_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a single price row from a market table.
        
        Args:
            row: BeautifulSoup row element
            selectors: Market-specific CSS selectors
            market_id: Market identifier
            
        Returns:
            Dictionary with parsed price data or None
        """
        # Extract cells
        cells = row.find_all("td")
        if not cells:
            return None
        
        # Try to extract element name
        element_cell = row.select_one(selectors.get("element", "td:nth-child(1)"))
        if not element_cell:
            return None
        
        element_text = element_cell.get_text().strip().lower()
        
        # Map element name to symbol
        element_symbol = self._map_element_name(element_text)
        if not element_symbol:
            return None
        
        # Extract price
        price_cell = row.select_one(selectors.get("price", "td:nth-child(2)"))
        if not price_cell:
            return None
        
        price_text = price_cell.get_text().strip()
        price = self._parse_price(price_text)
        if price is None:
            return None
        
        # Extract currency and unit
        currency = "USD"
        price_unit = "per_kg"
        
        # Try to extract from specific columns
        unit_cell = row.select_one(selectors.get("unit", "td:nth-child(3)"))
        if unit_cell:
            unit_text = unit_cell.get_text().strip().lower()
            currency, price_unit = self._parse_currency_unit(unit_text)
        
        currency_cell = row.select_one(selectors.get("currency", "td:nth-child(4)"))
        if currency_cell:
            currency_text = currency_cell.get_text().strip().upper()
            if currency_text in ["USD", "CNY", "EUR", "GBP"]:
                currency = currency_text
        
        # Extract date if available
        date_cell = row.select_one(selectors.get("date", "td:nth-child(5)"))
        scraped_date = date.today()
        if date_cell:
            date_text = date_cell.get_text().strip()
            scraped_date = self._parse_date(date_text)
        
        return {
            "element_symbol": element_symbol,
            "price": price,
            "currency": currency,
            "price_unit": price_unit,
            "date": scraped_date,
        }
    
    def _map_element_name(self, name: str) -> Optional[str]:
        """
        Map an element name to its chemical symbol.
        
        Args:
            name: Element name or partial name
            
        Returns:
            Chemical symbol or None
        """
        name = name.lower().strip()
        
        # Direct match
        if name in self.ELEMENT_MAPPINGS:
            return self.ELEMENT_MAPPINGS[name]
        
        # Try to find partial matches
        for element_name, symbol in self.ELEMENT_MAPPINGS.items():
            if element_name in name or name in element_name:
                return symbol
        
        # Try to match symbol directly
        if len(name) <= 3 and name.upper() in self.ELEMENT_MAPPINGS.values():
            return name.upper()
        
        return None
    
    def _parse_price(self, price_text: str) -> Optional[float]:
        """
        Parse a price string into a float.
        
        Args:
            price_text: Price string (e.g., "123.45", "$123.45", "123,450")
            
        Returns:
            Price as float or None
        """
        # Remove currency symbols and commas
        price_text = price_text.replace("$", "").replace(",", "").replace("€", "").replace("£", "").strip()
        
        # Try to parse as float
        try:
            return float(price_text)
        except ValueError:
            return None
    
    def _parse_currency_unit(self, text: str) -> tuple:
        """
        Parse currency and unit from text.
        
        Args:
            text: Text containing currency and unit (e.g., "USD/kg", "CNY per ton")
            
        Returns:
            Tuple of (currency, unit)
        """
        text = text.lower().strip()
        
        # Check for known patterns
        for pattern, (currency, unit) in self.UNIT_MAPPINGS.items():
            if pattern in text:
                return currency, unit
        
        # Default to USD per kg
        return "USD", "per_kg"
    
    def _parse_date(self, date_text: str) -> date:
        """
        Parse a date string into a date object.
        
        Args:
            date_text: Date string in various formats
            
        Returns:
            date object
        """
        from dateutil.parser import parse
        
        try:
            dt = parse(date_text)
            return dt.date()
        except Exception:
            return date.today()
    
    def scrape_and_store(self, **kwargs) -> int:
        """
        Scrape price data and store in the database.
        
        Args:
            **kwargs: Arguments passed to scrape()
            
        Returns:
            Number of prices stored
        """
        prices = self.scrape(**kwargs)
        
        stored_count = 0
        for price in prices:
            try:
                # Convert dataclass to dict for storage
                price_data = price.to_dict()
                # Remove computed fields
                price_data.pop("price_id", None)
                price_data.pop("hash", None)
                price_data.pop("price_per_kg", None)
                price_data.pop("normalized_price", None)
                price_data.pop("display_price", None)
                
                # Get element and market IDs
                element = storage.get_element_by_symbol(price.element_symbol)
                market = storage.get_market_by_id(price.market_id)
                
                if element and market:
                    price_data["element_id"] = element.id
                    price_data["market_id"] = market.id
                    
                    # Store in database
                    storage.create_price(price_data)
                    stored_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to store price for {price.element_symbol}: {e}")
                continue
        
        return stored_count
    
    def scrape_single_market(self, market_id: str) -> List[RareEarthPrice]:
        """
        Scrape prices from a single market.
        
        Args:
            market_id: Market identifier
            
        Returns:
            List of RareEarthPrice objects
        """
        return self.scrape_market(market_id)


class MetalPagesScraper(PriceScraper):
    """Specialized scraper for Metal Pages."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "MetalPagesScraper", ["metal_pages"])
    
    def scrape(self, **kwargs) -> List[RareEarthPrice]:
        """Scrape prices from Metal Pages."""
        return self.scrape_market("metal_pages")


class FastmarketsScraper(PriceScraper):
    """Specialized scraper for Fastmarkets."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "FastmarketsScraper", ["fastmarkets"])
    
    def scrape(self, **kwargs) -> List[RareEarthPrice]:
        """Scrape prices from Fastmarkets."""
        return self.scrape_market("fastmarkets")


class ArgusMediaScraper(PriceScraper):
    """Specialized scraper for Argus Media."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "ArgusMediaScraper", ["argus_media"])
    
    def scrape(self, **kwargs) -> List[RareEarthPrice]:
        """Scrape prices from Argus Media."""
        return self.scrape_market("argus_media")


# Export everything
__all__ = [
    "PriceScraper",
    "MetalPagesScraper",
    "FastmarketsScraper",
    "ArgusMediaScraper",
]
