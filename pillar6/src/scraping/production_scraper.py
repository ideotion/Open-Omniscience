"""
Pillar 6 Production Scraper

Scrapes rare earth production data from various sources.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
import logging
import re

from bs4 import BeautifulSoup
from .base_scraper import RareEarthScraper, ScraperConfig, DEFAULT_CONFIG
from ..models import RareEarthProduction, ProductionType, ProductionUnit
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class ProductionScraper(RareEarthScraper):
    """
    Scraper for rare earth production data.
    
    Scrapes production information from various sources including:
    - USGS Mineral Commodity Summaries
    - Company annual reports
    - Government publications
    - Industry reports
    """
    
    # Production data sources
    PRODUCTION_SOURCES = {
        "usgs": {
            "url": "https://www.usgs.gov/centers/national-minerals-information-center/rare-earths-statistics-and-information",
            "name": "USGS Mineral Commodity Summaries",
            "description": "US Geological Survey rare earth production statistics",
            "update_frequency": "annual",
            "data_format": "table",
        },
        "usgs_mcs": {
            "url": "https://pubs.usgs.gov/periodicals/mcs2023/mcs2023.pdf",
            "name": "USGS Mineral Commodity Summaries 2023",
            "description": "Annual USGS report with production data",
            "update_frequency": "annual",
            "data_format": "pdf",
        },
        "lynas": {
            "url": "https://www.lynascorp.com/investors/annual-reports",
            "name": "Lynas Corporation",
            "description": "Lynas annual reports with production data",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "mp_materials": {
            "url": "https://www.mpmaterials.com/investors/financial-information/",
            "name": "MP Materials",
            "description": "MP Materials investor presentations with production data",
            "update_frequency": "quarterly",
            "data_format": "html",
        },
        "northern_minerals": {
            "url": "https://www.northernminerals.com.au/investors/annual-reports/",
            "name": "Northern Minerals",
            "description": "Northern Minerals annual reports",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "rainbow_rare_earths": {
            "url": "https://www.rainbowrareearths.com/investors/reports-and-presentations/",
            "name": "Rainbow Rare Earths",
            "description": "Rainbow Rare Earths reports",
            "update_frequency": "annual",
            "data_format": "html",
        },
        "china_ministry": {
            "url": "http://www.miit.gov.cn/n1146295/n1146352/index.html",
            "name": "China Ministry of Industry and Information Technology",
            "description": "Chinese government production statistics",
            "update_frequency": "monthly",
            "data_format": "html",
        },
        "baotou_group": {
            "url": "http://www.baotougroup.com.cn/english/",
            "name": "Baotou Iron and Steel Group",
            "description": "China's largest rare earth producer",
            "update_frequency": "annual",
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
        "ndpr": "Nd",  # Neodymium-Praseodymium
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
        "brazil": "Brazil",
        "russia": "Russia",
        "russian federation": "Russia",
        "india": "India",
        "vietnam": "Vietnam",
        "burma": "Myanmar",
        "myanmar": "Myanmar",
        "thailand": "Thailand",
    }
    
    # Company mappings
    COMPANY_MAPPINGS = {
        "lynas": "Lynas Corporation",
        "mp materials": "MP Materials",
        "mountain pass": "MP Materials",
        "baotou": "Baotou Iron and Steel Group",
        "northern minerals": "Northern Minerals",
        "rainbow": "Rainbow Rare Earths",
        "chinalco": "Chinalco",
        "aluminum corporation of china": "Chinalco",
    }
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        name: str = "ProductionScraper",
        sources: Optional[List[str]] = None,
    ):
        """
        Initialize the production scraper.
        
        Args:
            config: Scraper configuration
            name: Name of the scraper
            sources: List of sources to scrape (None = all)
        """
        super().__init__(config, name)
        self.sources = sources or list(self.PRODUCTION_SOURCES.keys())
    
    def get_data_sources(self) -> List[str]:
        """Get the list of data sources for this scraper."""
        return list(self.PRODUCTION_SOURCES.keys())
    
    def scrape(self, **kwargs) -> List[RareEarthProduction]:
        """
        Scrape production data from all configured sources.
        
        Args:
            **kwargs: Additional arguments
                - sources: List of specific sources to scrape
                - years: List of specific years to scrape
                - countries: List of specific countries to filter by
                - companies: List of specific companies to filter by
                
        Returns:
            List of RareEarthProduction objects
        """
        sources = kwargs.get("sources", self.sources)
        years = kwargs.get("years", None)
        countries = kwargs.get("countries", None)
        companies = kwargs.get("companies", None)
        
        all_productions = []
        
        for source_id in sources:
            if source_id not in self.PRODUCTION_SOURCES:
                logger.warning(f"Unknown source: {source_id}")
                continue
            
            try:
                source_productions = self.scrape_source(source_id, years, countries, companies)
                all_productions.extend(source_productions)
                logger.info(f"Scraped {len(source_productions)} production data points from {source_id}")
            except Exception as e:
                logger.error(f"Failed to scrape {source_id}: {e}")
        
        return all_productions
    
    def scrape_source(
        self,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        companies: Optional[List[str]] = None,
    ) -> List[RareEarthProduction]:
        """
        Scrape production data from a specific source.
        
        Args:
            source_id: Source identifier
            years: Optional list of years to filter by
            countries: Optional list of countries to filter by
            companies: Optional list of companies to filter by
            
        Returns:
            List of RareEarthProduction objects
        """
        source_info = self.PRODUCTION_SOURCES.get(source_id)
        if not source_info:
            return []
        
        url = source_info["url"]
        data_format = source_info.get("data_format", "html")
        
        if data_format == "pdf":
            return self._scrape_pdf(url, source_id, years, countries, companies)
        else:
            return self._scrape_html(url, source_id, years, countries, companies)
    
    def _scrape_html(
        self,
        url: str,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        companies: Optional[List[str]] = None,
    ) -> List[RareEarthProduction]:
        """Scrape production data from HTML pages."""
        soup = self.get_soup(url)
        
        if not soup:
            logger.warning(f"Failed to fetch page for {source_id}")
            return []
        
        # Try to find production tables
        productions = []
        
        # Look for tables with production data
        tables = soup.find_all("table")
        for table in tables:
            table_productions = self._parse_production_table(
                table, source_id, years, countries, companies
            )
            productions.extend(table_productions)
        
        # If no tables found, try to parse text
        if not productions:
            productions = self._parse_production_text(soup, source_id, years, countries, companies)
        
        return productions
    
    def _scrape_pdf(
        self,
        url: str,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        companies: Optional[List[str]] = None,
    ) -> List[RareEarthProduction]:
        """Scrape production data from PDF files."""
        # For PDF scraping, we would use a library like PyPDF2 or pdfplumber
        # This is a placeholder implementation
        logger.warning(f"PDF scraping not yet implemented for {source_id}")
        return []
    
    def _parse_production_table(
        self,
        table: BeautifulSoup,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        companies: Optional[List[str]] = None,
    ) -> List[RareEarthProduction]:
        """Parse a production table."""
        productions = []
        
        # Get table headers
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [th.get_text().strip().lower() for th in header_row.find_all(["th", "td"])]
        
        # Parse each row
        rows = table.find_all("tr")[1:]  # Skip header row
        for row in rows:
            try:
                production_data = self._parse_production_row(
                    row, headers, source_id
                )
                if production_data:
                    # Apply filters
                    if years and production_data["year"] not in years:
                        continue
                    if countries and production_data["country"] not in countries:
                        continue
                    if companies and production_data.get("company") not in companies:
                        continue
                    
                    # Create RareEarthProduction object
                    production = RareEarthProduction(
                        element_symbol=production_data["element_symbol"],
                        country=production_data["country"],
                        amount=production_data["amount"],
                        production_type=ProductionType(production_data.get("production_type", "total")),
                        production_unit=ProductionUnit(production_data.get("production_unit", "tonnes")),
                        year=production_data["year"],
                        quarter=production_data.get("quarter"),
                        month=production_data.get("month"),
                        date=production_data.get("date"),
                        company=production_data.get("company"),
                        source=source_id,
                        source_url=self.PRODUCTION_SOURCES[source_id]["url"],
                        is_estimated=production_data.get("is_estimated", True),
                        confidence=production_data.get("confidence", 0.8),
                        notes=f"Scraped from {source_id}",
                    )
                    productions.append(production)
                    
            except Exception as e:
                logger.debug(f"Failed to parse production row: {e}")
                continue
        
        return productions
    
    def _parse_production_row(
        self,
        row: BeautifulSoup,
        headers: List[str],
        source_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Parse a single production row from a table."""
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
            country = "Global"  # Default to global if not specified
        
        # Extract amount
        amount = self._extract_amount(row_data)
        if amount is None:
            return None
        
        # Extract year
        year = self._extract_year(row_data)
        if year is None:
            year = datetime.now().year
        
        # Extract company if available
        company = self._extract_company(row_data)
        
        # Extract production type
        production_type = self._extract_production_type(row_data)
        
        # Extract unit
        production_unit = self._extract_unit(row_data)
        
        return {
            "element_symbol": element_symbol,
            "country": country,
            "amount": amount,
            "year": year,
            "company": company,
            "production_type": production_type,
            "production_unit": production_unit,
            "is_estimated": True,
            "confidence": 0.8,
        }
    
    def _parse_production_text(
        self,
        soup: BeautifulSoup,
        source_id: str,
        years: Optional[List[int]] = None,
        countries: Optional[List[str]] = None,
        companies: Optional[List[str]] = None,
    ) -> List[RareEarthProduction]:
        """Parse production data from text content."""
        # This is a placeholder for text-based parsing
        # In practice, this would use NLP or pattern matching
        logger.warning(f"Text-based production parsing not yet implemented for {source_id}")
        return []
    
    def _extract_element(self, row_data: Dict[str, str]) -> Optional[str]:
        """Extract element symbol from row data."""
        # Check common column names
        element_keys = ["element", "commodity", "metal", "rare earth", "ree"]
        
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
        country_keys = ["country", "region", "location", "nation"]
        
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
    
    def _extract_company(self, row_data: Dict[str, str]) -> Optional[str]:
        """Extract company from row data."""
        company_keys = ["company", "producer", "firm", "organization"]
        
        for key in company_keys:
            if key in row_data:
                company_text = row_data[key].lower()
                company = self._map_company(company_text)
                if company:
                    return company
        
        return None
    
    def _extract_amount(self, row_data: Dict[str, str]) -> Optional[float]:
        """Extract production amount from row data."""
        amount_keys = ["production", "amount", "quantity", "volume", "output", "tonnes", "tons"]
        
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
        year_keys = ["year", "date", "period"]
        
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
    
    def _extract_production_type(self, row_data: Dict[str, str]) -> str:
        """Extract production type from row data."""
        type_keys = ["type", "category", "classification"]
        
        for key in type_keys:
            if key in row_data:
                type_text = row_data[key].lower()
                if "mine" in type_text:
                    return "mine"
                elif "refined" in type_text or "oxide" in type_text:
                    return "refined"
                elif "processed" in type_text:
                    return "processed"
                elif "recycled" in type_text:
                    return "recycled"
        
        return "total"
    
    def _extract_unit(self, row_data: Dict[str, str]) -> str:
        """Extract production unit from row data."""
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
        
        # Return capitalized version
        return name.title()
    
    def _map_company(self, name: str) -> Optional[str]:
        """Map a company name to its standard form."""
        name = name.lower().strip()
        
        if name in self.COMPANY_MAPPINGS:
            return self.COMPANY_MAPPINGS[name]
        
        for company_name, standard in self.COMPANY_MAPPINGS.items():
            if company_name in name or name in company_name:
                return standard
        
        return None
    
    def _parse_amount(self, text: str) -> Optional[float]:
        """Parse an amount string into a float."""
        # Remove commas, currency symbols, and other non-numeric characters
        text = text.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
        
        # Try to extract numbers
        numbers = re.findall(r"\d+\.?\d*", text)
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                return None
        
        return None
    
    def _parse_year(self, text: str) -> Optional[int]:
        """Parse a year from text."""
        # Look for 4-digit numbers
        years = re.findall(r"\b(19|20)\d{2}\b", text)
        if years:
            try:
                return int(years[0])
            except ValueError:
                return None
        
        return None
    
    def scrape_and_store(self, **kwargs) -> int:
        """
        Scrape production data and store in the database.
        
        Args:
            **kwargs: Arguments passed to scrape()
            
        Returns:
            Number of production data points stored
        """
        productions = self.scrape(**kwargs)
        
        stored_count = 0
        for production in productions:
            try:
                # Convert dataclass to dict for storage
                production_data = production.to_dict()
                # Remove computed fields
                production_data.pop("production_id", None)
                production_data.pop("hash", None)
                production_data.pop("tonnes", None)
                production_data.pop("display_amount", None)
                production_data.pop("period", None)
                
                # Get element ID
                element = storage.get_element_by_symbol(production.element_symbol)
                if element:
                    production_data["element_id"] = element.id
                    
                    # Store in database
                    storage.create_production(production_data)
                    stored_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to store production for {production.element_symbol}: {e}")
                continue
        
        return stored_count


class USGSProductionScraper(ProductionScraper):
    """Specialized scraper for USGS production data."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "USGSProductionScraper", ["usgs", "usgs_mcs"])
    
    def scrape(self, **kwargs) -> List[RareEarthProduction]:
        """Scrape production data from USGS sources."""
        return self.scrape_source("usgs")


class LynasProductionScraper(ProductionScraper):
    """Specialized scraper for Lynas Corporation production data."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config, "LynasProductionScraper", ["lynas"])
    
    def scrape(self, **kwargs) -> List[RareEarthProduction]:
        """Scrape production data from Lynas Corporation."""
        return self.scrape_source("lynas")


# Export everything
__all__ = [
    "ProductionScraper",
    "USGSProductionScraper",
    "LynasProductionScraper",
]
