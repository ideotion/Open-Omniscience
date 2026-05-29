"""
Pillar 6 Inventory Scraper

Scrapes rare earth inventory/stockpile data from various sources.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
import logging
import re

from bs4 import BeautifulSoup
from .base_scraper import RareEarthScraper, ScraperConfig, DEFAULT_CONFIG
from ..models import RareEarthInventory, InventoryType, InventoryUnit
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class InventoryScraper(RareEarthScraper):
    """
    Scraper for rare earth inventory/stockpile data.
    
    Scrapes inventory information from various sources including:
    - US Defense Logistics Agency (DLA)
    - US Department of Defense
    - Company reports
    - Industry publications
    """
    
    # Inventory data sources
    INVENTORY_SOURCES = {
        "dla": {
            "url": "https://www.dla.mil/About-DLA/Organization/Strategic-Materials/",
            "name": "US Defense Logistics Agency",
            "description": "US government strategic stockpile information",
            "update_frequency": "quarterly",
            "data_format": "html",
        },
        "dod_stockpile": {
            "url": "https://www.acquisition.gov/dfars/national-defense-stockpile",
            "name": "US National Defense Stockpile",
            "description": "US national defense stockpile reports",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "usgs_stockpile": {
            "url": "https://www.usgs.gov/centers/national-minerals-information-center/stockpile-reports",
            "name": "USGS Stockpile Reports",
            "description": "USGS reports on strategic stockpiles",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "china_reserve": {
            "url": "http://www.saemc.org.cn/",
            "name": "China State Administration for Emergency Management",
            "description": "Chinese strategic reserve information",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "lynas_inventory": {
            "url": "https://www.lynascorp.com/investors/annual-reports",
            "name": "Lynas Corporation Inventory",
            "description": "Lynas inventory data from annual reports",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "mp_materials_inventory": {
            "url": "https://www.mpmaterials.com/investors/financial-information/",
            "name": "MP Materials Inventory",
            "description": "MP Materials inventory data",
            "update_frequency": "quarterly",
            "data_format": "html",
        },
    }
    
    # Element name mappings
    ELEMENT_MAPPINGS = {
        "scandium": "Sc",
        "yttrium": "Y",
        "lanthanum": "La",
        "cerium": "Ce",
        "praseodymium": "Pr",
        "neodymium": "Nd",
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
        "ndpr": "Nd",
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
    
    # Country mappings
    COUNTRY_MAPPINGS = {
        "china": "China",
        "chinese": "China",
        "prc": "China",
        "united states": "United States",
        "usa": "United States",
        "us": "United States",
        "australia": "Australia",
        "malaysia": "Malaysia",
    }
    
    # Holder mappings
    HOLDER_MAPPINGS = {
        "dla": "US Defense Logistics Agency",
        "dod": "US Department of Defense",
        "us government": "US Government",
        "national defense stockpile": "US National Defense Stockpile",
        "lynas": "Lynas Corporation",
        "mp materials": "MP Materials",
        "mountain pass": "MP Materials",
        "china": "Chinese Government",
        "chinese government": "Chinese Government",
    }
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        name: str = "InventoryScraper",
        sources: Optional[List[str]] = None,
    ):
        """
        Initialize the inventory scraper.
        
        Args:
            config: Scraper configuration
            name: Name of the scraper
            sources: List of sources to scrape (None = all)
        """
        super().__init__(config, name)
        self.sources = sources or list(self.INVENTORY_SOURCES.keys())
    
    def get_data_sources(self) -> List[str]:
        """Get the list of data sources for this scraper."""
        return list(self.INVENTORY_SOURCES.keys())
    
    def scrape(self, **kwargs) -> List[RareEarthInventory]:
        """
        Scrape inventory data from all configured sources.
        
        Args:
            **kwargs: Additional arguments
                - sources: List of specific sources to scrape
                - years: List of specific years to scrape
                - countries: List of specific countries to filter by
                - holders: List of specific holders to filter by
                
        Returns:
            List of RareEarthInventory objects
        """
        sources = kwargs.get("sources", self.sources)
        years = kwargs.get("years", None)
        countries = kwargs.get("countries", None)
        holders = kwargs.get("holders", None)
        
        all_inventories = []
        
        for source_id in sources:
            if source_id not in self.INVENTORY_SOURCES:
                logger.warning(f"Unknown source: {source_id}")
                continue
            
            try:
                source_inventories = self.scrape_source(source_id, years, countries, holders)
                all_inventories.extend(source_inventories)
                logger.info(f"Scraped {len(source_inventories)} inventory data points from {source_id}")
            except Exception as e:
                logger.error(f"Failed to scrape {source_id}: {e}")
        
        return all_inventories
    
    def scrape_source(
        self,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        holders: Optional[List[str]] = None,
    ) -> List[RareEarthInventory]:
        """
        Scrape inventory data from a specific source.
        
        Args:
            source_id: Source identifier
            years: Optional list of years to filter by
            countries: Optional list of countries to filter by
            holders: Optional list of holders to filter by
            
        Returns:
            List of RareEarthInventory objects
        """
        source_info = self.INVENTORY_SOURCES.get(source_id)
        if not source_info:
            return []
        
        url = source_info["url"]
        data_format = source_info.get("data_format", "html")
        
        if data_format == "pdf":
            return self._scrape_pdf(url, source_id, years, countries, holders)
        else:
            return self._scrape_html(url, source_id, years, countries, holders)
    
    def _scrape_html(
        self,
        url: str,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        holders: Optional[List[str]] = None,
    ) -> List[RareEarthInventory]:
        """Scrape inventory data from HTML pages."""
        soup = self.get_soup(url)
        
        if not soup:
            logger.warning(f"Failed to fetch page for {source_id}")
            return []
        
        # Try to find inventory tables
        inventories = []
        
        # Look for tables with inventory data
        tables = soup.find_all("table")
        for table in tables:
            table_inventories = self._parse_inventory_table(
                table, source_id, years, countries, holders
            )
            inventories.extend(table_inventories)
        
        # If no tables found, try to parse text
        if not inventories:
            inventories = self._parse_inventory_text(soup, source_id, years, countries, holders)
        
        return inventories
    
    def _scrape_pdf(
        self,
        url: str,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        holders: Optional[List[str]] = None,
    ) -> List[RareEarthInventory]:
        """Scrape inventory data from PDF files."""
        # For PDF scraping, we would use a library like PyPDF2 or pdfplumber
        logger.warning(f"PDF scraping not yet implemented for {source_id}")
        return []
    
    def _parse_inventory_table(
        self,
        table: BeautifulSoup,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        holders: Optional[List[str]] = None,
    ) -> List[RareEarthInventory]:
        """Parse an inventory table."""
        inventories = []
        
        # Get table headers
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [th.get_text().strip().lower() for th in header_row.find_all(["th", "td"])]
        
        # Parse each row
        rows = table.find_all("tr")[1:]  # Skip header row
        for row in rows:
            try:
                inventory_data = self._parse_inventory_row(
                    row, headers, source_id
                )
                if inventory_data:
                    # Apply filters
                    if years and inventory_data["year"] not in years:
                        continue
                    if countries and inventory_data["country"] not in countries:
                        continue
                    if holders and inventory_data.get("holder") not in holders:
                        continue
                    
                    # Create RareEarthInventory object
                    inventory = RareEarthInventory(
                        element_symbol=inventory_data["element_symbol"],
                        country=inventory_data["country"],
                        amount=inventory_data["amount"],
                        inventory_type=InventoryType(inventory_data.get("inventory_type", "stockpile")),
                        inventory_unit=InventoryUnit(inventory_data.get("inventory_unit", "tonnes")),
                        year=inventory_data["year"],
                        date=inventory_data.get("date"),
                        holder=inventory_data.get("holder"),
                        source=source_id,
                        source_url=self.INVENTORY_SOURCES[source_id]["url"],
                        is_estimated=inventory_data.get("is_estimated", True),
                        confidence=inventory_data.get("confidence", 0.8),
                        notes=f"Scraped from {source_id}",
                    )
                    inventories.append(inventory)
                    
            except Exception as e:
                logger.debug(f"Failed to parse inventory row: {e}")
                continue
        
        return inventories
    
    def _parse_inventory_row(
        self,
        row: BeautifulSoup,
        headers: List[str],
        source_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Parse a single inventory row from a table."""
        cells = row.find_all(["td", "th"])
        if not cells:
            return None
        
        # Create dictionary from cells and headers
        row_data = {}
        for i, cell in enumerate(cells):
            header = headers[i] if i < len(headers) else f"column_{i}"
            row_data[header] = cell.get_text().strip()
        
        # Try to extract element
        element_symbol = self._extract_element(row_data)
        if not element_symbol:
            return None
        
        # Extract country
        country = self._extract_country(row_data)
        if not country:
            country = "Global"
        
        # Extract amount
        amount = self._extract_amount(row_data)
        if amount is None:
            return None
        
        # Extract year
        year = self._extract_year(row_data)
        if year is None:
            year = datetime.now().year
        
        # Extract holder if available
        holder = self._extract_holder(row_data)
        
        # Extract inventory type
        inventory_type = self._extract_inventory_type(row_data)
        
        # Extract unit
        inventory_unit = self._extract_unit(row_data)
        
        return {
            "element_symbol": element_symbol,
            "country": country,
            "amount": amount,
            "year": year,
            "holder": holder,
            "inventory_type": inventory_type,
            "inventory_unit": inventory_unit,
            "is_estimated": True,
            "confidence": 0.8,
        }
    
    def _parse_inventory_text(
        self,
        soup: BeautifulSoup,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        holders: Optional[List[str]] = None,
    ) -> List[RareEarthInventory]:
        """Parse inventory data from text content."""
        # This is a placeholder for text-based parsing
        logger.warning(f"Text-based inventory parsing not yet implemented for {source_id}")
        return []
    
    def _extract_element(self, row_data: Dict[str, str]) -> Optional[str]:
        """Extract element symbol from row data."""
        element_keys = ["element", "commodity", "metal", "rare earth", "ree", "material"]
        
        for key in element_keys:
            if key in row_data:
                element_text = row_data[key].lower()
                element_symbol = self._map_element_name(element_text)
                if element_symbol:
                    return element_symbol
        
        # Try to find element in any column
        for value in row_data.values():
            element_symbol = self._map_element_name(value.lower())
            if element_symbol:
                return element_symbol
        
        return None
    
    def _extract_country(self, row_data: Dict[str, str]) -> Optional[str]:
        """Extract country from row data."""
        country_keys = ["country", "region", "location", "nation", "state"]
        
        for key in country_keys:
            if key in row_data:
                country_text = row_data[key].lower()
                country = self._map_country(country_text)
                if country:
                    return country
        
        # Try to find country in any column
        for value in row_data.values():
            country = self._map_country(value.lower())
            if country:
                return country
        
        return None
    
    def _extract_holder(self, row_data: Dict[str, str]) -> Optional[str]:
        """Extract holder from row data."""
        holder_keys = ["holder", "owner", "organization", "agency", "company"]
        
        for key in holder_keys:
            if key in row_data:
                holder_text = row_data[key].lower()
                holder = self._map_holder(holder_text)
                if holder:
                    return holder
        
        return None
    
    def _extract_amount(self, row_data: Dict[str, str]) -> Optional[float]:
        """Extract inventory amount from row data."""
        amount_keys = ["inventory", "amount", "quantity", "volume", "stock", "stockpile", "reserve", "tonnes", "tons"]
        
        for key in amount_keys:
            if key in row_data:
                amount_text = row_data[key]
                amount = self._parse_amount(amount_text)
                if amount is not None:
                    return amount
        
        # Try to find amount in any column
        for value in row_data.values():
            amount = self._parse_amount(value)
            if amount is not None:
                return amount
        
        return None
    
    def _extract_year(self, row_data: Dict[str, str]) -> Optional[int]:
        """Extract year from row data."""
        year_keys = ["year", "date", "period", "as of"]
        
        for key in year_keys:
            if key in row_data:
                year = self._parse_year(row_data[key])
                if year is not None:
                    return year
        
        # Try to find year in any column
        for value in row_data.values():
            year = self._parse_year(value)
            if year is not None:
                return year
        
        return None
    
    def _extract_inventory_type(self, row_data: Dict[str, str]) -> str:
        """Extract inventory type from row data."""
        type_keys = ["type", "category", "classification", "kind"]
        
        for key in type_keys:
            if key in row_data:
                type_text = row_data[key].lower()
                if "strategic" in type_text or "stockpile" in type_text:
                    return "strategic_reserve"
                elif "commercial" in type_text:
                    return "commercial"
                elif "government" in type_text:
                    return "government"
                elif "military" in type_text:
                    return "military"
                elif "industrial" in type_text:
                    return "industrial"
        
        return "stockpile"
    
    def _extract_unit(self, row_data: Dict[str, str]) -> str:
        """Extract inventory unit from row data."""
        unit_keys = ["unit", "units"]
        
        for key in unit_keys:
            if key in row_data:
                unit_text = row_data[key].lower()
                if "tonne" in unit_text or "ton" in unit_text:
                    return "tonnes"
                elif "kg" in unit_text:
                    return "kg"
                elif "gram" in unit_text:
                    return "grams"
        
        return "tonnes"
    
    def _map_element_name(self, name: str) -> Optional[str]:
        """Map an element name to its chemical symbol."""
        name = name.lower().strip()
        
        if name in self.ELEMENT_MAPPINGS:
            return self.ELEMENT_MAPPINGS[name]
        
        for element_name, symbol in self.ELEMENT_MAPPINGS.items():
            if element_name in name or name in element_name:
                return symbol
        
        if len(name) <= 3 and name.upper() in self.ELEMENT_MAPPINGS.values():
            return name.upper()
        
        return None
    
    def _map_country(self, name: str) -> Optional[str]:
        """Map a country name to its standard form."""
        name = name.lower().strip()
        
        if name in self.COUNTRY_MAPPINGS:
            return self.COUNTRY_MAPPINGS[name]
        
        for country_name, standard in self.COUNTRY_MAPPINGS.items():
            if country_name in name or name in country_name:
                return standard
        
        return name.title()
    
    def _map_holder(self, name: str) -> Optional[str]:
        """Map a holder name to its standard form."""
        name = name.lower().strip()
        
        if name in self.HOLDER_MAPPINGS:
            return self.HOLDER_MAPPINGS[name]
        
        for holder_name, standard in self.HOLDER_MAPPINGS.items():
            if holder_name in name or name in holder_name:
                return standard
        
        return None
    
    def _parse_amount(self, text: str) -> Optional[float]:
        """Parse an amount string into a float."""
        text = text.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
        
        numbers = re.findall(r"\d+\.?\d*", text)
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                return None
        
        return None
    
    def _parse_year(self, text: str) -> Optional[int]:
        """Parse a year from text."""
        years = re.findall(r"\b(19|20)\d{2}\b", text)
        if years:
            try:
                return int(years[0])
            except ValueError:
                return None
        
        return None
    
    def scrape_and_store(self, **kwargs) -> int:
        """
        Scrape inventory data and store in the database.
        
        Args:
            **kwargs: Arguments passed to scrape()
            
        Returns:
            Number of inventory data points stored
        """
        inventories = self.scrape(**kwargs)
        
        stored_count = 0
        for inventory in inventories:
            try:
                # Convert dataclass to dict for storage
                inventory_data = inventory.to_dict()
                # Remove computed fields
                inventory_data.pop("inventory_id", None)
                inventory_data.pop("hash", None)
                inventory_data.pop("tonnes", None)
                inventory_data.pop("display_amount", None)
                inventory_data.pop("period", None)
                
                # Get element ID
                element = storage.get_element_by_symbol(inventory.element_symbol)
                if element:
                    inventory_data["element_id"] = element.id
                    
                    # Store in database
                    storage.create_inventory(inventory_data)
                    stored_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to store inventory for {inventory.element_symbol}: {e}")
                continue
        
        return stored_count


class DLAScraper(InventoryScraper):
    """Specialized scraper for DLA inventory data."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "DLAScraper", ["dla"])
    
    def scrape(self, **kwargs) -> List[RareEarthInventory]:
        """Scrape inventory data from DLA."""
        return self.scrape_source("dla")


class USGSInventoryScraper(InventoryScraper):
    """Specialized scraper for USGS inventory data."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "USGSInventoryScraper", ["usgs_stockpile"])
    
    def scrape(self, **kwargs) -> List[RareEarthInventory]:
        """Scrape inventory data from USGS."""
        return self.scrape_source("usgs_stockpile")


# Export everything
__all__ = [
    "InventoryScraper",
    "DLAScraper",
    "USGSInventoryScraper",
]
