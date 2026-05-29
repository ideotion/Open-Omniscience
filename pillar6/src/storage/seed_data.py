"""
Pillar 6 Seed Data

Functions to seed the database with default rare earth elements and markets.
"""

from datetime import datetime
from src.database.models import Session
from .database import (
    RareEarthElementDB,
    RareEarthMarketDB,
)


def seed_rare_earth_elements():
    """
    Seed the database with all 17 rare earth elements.
    
    Returns the list of created elements.
    """
    session = Session()
    
    # Check if elements already exist
    existing_count = session.query(RareEarthElementDB).count()
    if existing_count > 0:
        print(f"Found {existing_count} existing rare earth elements. Skipping seed.")
        session.close()
        return []
    
    elements_data = [
        {
            "symbol": "Sc",
            "name": "Scandium",
            "atomic_number": 21,
            "category": "light",
            "element_type": "scandium",
            "atomic_weight": 44.955908,
            "melting_point": 1541,
            "boiling_point": 2836,
            "density": 2.985,
            "discovery_year": 1879,
            "common_uses": ["aluminum alloys", "fuel cells", "aerospace"],
            "is_critical": True,
            "aliases": ["Scandium"],
        },
        {
            "symbol": "Y",
            "name": "Yttrium",
            "atomic_number": 39,
            "category": "light",
            "element_type": "yttrium",
            "atomic_weight": 88.905842,
            "melting_point": 1522,
            "boiling_point": 3345,
            "density": 4.469,
            "discovery_year": 1794,
            "common_uses": ["phosphors", "ceramics", "lasers", "superconductors"],
            "is_critical": True,
            "aliases": ["Yttrium"],
        },
        {
            "symbol": "La",
            "name": "Lanthanum",
            "atomic_number": 57,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 138.90547,
            "melting_point": 920,
            "boiling_point": 3464,
            "density": 6.145,
            "discovery_year": 1839,
            "common_uses": ["batteries", "camera lenses", "catalysts"],
            "is_critical": True,
            "aliases": ["Lanthanum"],
        },
        {
            "symbol": "Ce",
            "name": "Cerium",
            "atomic_number": 58,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 140.116,
            "melting_point": 795,
            "boiling_point": 3443,
            "density": 6.77,
            "discovery_year": 1803,
            "common_uses": ["catalysts", "glass polishing", "alloying agent"],
            "is_critical": True,
            "aliases": ["Cerium"],
        },
        {
            "symbol": "Pr",
            "name": "Praseodymium",
            "atomic_number": 59,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 140.90766,
            "melting_point": 935,
            "boiling_point": 3520,
            "density": 6.773,
            "discovery_year": 1885,
            "common_uses": ["magnets", "alloying agent", "glass coloring"],
            "is_critical": True,
            "aliases": ["Praseodymium"],
        },
        {
            "symbol": "Nd",
            "name": "Neodymium",
            "atomic_number": 60,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 144.242,
            "melting_point": 1024,
            "boiling_point": 3074,
            "density": 7.007,
            "discovery_year": 1885,
            "common_uses": ["permanent magnets", "lasers", "glass coloring"],
            "is_critical": True,
            "aliases": ["Neodymium"],
        },
        {
            "symbol": "Pm",
            "name": "Promethium",
            "atomic_number": 61,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 145,
            "melting_point": 1042,
            "boiling_point": 3000,
            "density": 7.26,
            "discovery_year": 1945,
            "common_uses": ["nuclear batteries", "luminous paint"],
            "is_critical": False,
            "aliases": ["Promethium"],
        },
        {
            "symbol": "Sm",
            "name": "Samarium",
            "atomic_number": 62,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 150.36,
            "melting_point": 1072,
            "boiling_point": 1794,
            "density": 7.52,
            "discovery_year": 1879,
            "common_uses": ["magnets", "catalysts", "cancer treatment"],
            "is_critical": True,
            "aliases": ["Samarium"],
        },
        {
            "symbol": "Eu",
            "name": "Europium",
            "atomic_number": 63,
            "category": "light",
            "element_type": "lanthanide",
            "atomic_weight": 151.964,
            "melting_point": 822,
            "boiling_point": 1529,
            "density": 5.244,
            "discovery_year": 1901,
            "common_uses": ["phosphors", "TV screens", "fluorescent lamps"],
            "is_critical": True,
            "aliases": ["Europium"],
        },
        {
            "symbol": "Gd",
            "name": "Gadolinium",
            "atomic_number": 64,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 157.25,
            "melting_point": 1313,
            "boiling_point": 3273,
            "density": 7.90,
            "discovery_year": 1880,
            "common_uses": ["MRI contrast agent", "neutron absorber", "memory devices"],
            "is_critical": True,
            "aliases": ["Gadolinium"],
        },
        {
            "symbol": "Tb",
            "name": "Terbium",
            "atomic_number": 65,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 158.92535,
            "melting_point": 1356,
            "boiling_point": 3230,
            "density": 8.229,
            "discovery_year": 1843,
            "common_uses": ["phosphors", "magnets", "sonar systems"],
            "is_critical": True,
            "aliases": ["Terbium"],
        },
        {
            "symbol": "Dy",
            "name": "Dysprosium",
            "atomic_number": 66,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 162.500,
            "melting_point": 1412,
            "boiling_point": 2567,
            "density": 8.54,
            "discovery_year": 1886,
            "common_uses": ["magnets", "lasers", "nuclear reactors"],
            "is_critical": True,
            "aliases": ["Dysprosium"],
        },
        {
            "symbol": "Ho",
            "name": "Holmium",
            "atomic_number": 67,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 164.93033,
            "melting_point": 1474,
            "boiling_point": 2700,
            "density": 8.795,
            "discovery_year": 1878,
            "common_uses": ["magnets", "lasers", "nuclear control rods"],
            "is_critical": True,
            "aliases": ["Holmium"],
        },
        {
            "symbol": "Er",
            "name": "Erbium",
            "atomic_number": 68,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 167.259,
            "melting_point": 1529,
            "boiling_point": 2868,
            "density": 9.066,
            "discovery_year": 1843,
            "common_uses": ["fiber optics", "lasers", "metallurgy"],
            "is_critical": True,
            "aliases": ["Erbium"],
        },
        {
            "symbol": "Tm",
            "name": "Thulium",
            "atomic_number": 69,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 168.93422,
            "melting_point": 1545,
            "boiling_point": 1950,
            "density": 9.32,
            "discovery_year": 1879,
            "common_uses": ["portable X-rays", "lasers", "nuclear reactors"],
            "is_critical": False,
            "aliases": ["Thulium"],
        },
        {
            "symbol": "Yb",
            "name": "Ytterbium",
            "atomic_number": 70,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 173.054,
            "melting_point": 819,
            "boiling_point": 1196,
            "density": 6.90,
            "discovery_year": 1878,
            "common_uses": ["stress gauges", "alloying agent", "catalysts"],
            "is_critical": False,
            "aliases": ["Ytterbium"],
        },
        {
            "symbol": "Lu",
            "name": "Lutetium",
            "atomic_number": 71,
            "category": "heavy",
            "element_type": "lanthanide",
            "atomic_weight": 174.9668,
            "melting_point": 1663,
            "boiling_point": 3402,
            "density": 9.84,
            "discovery_year": 1907,
            "common_uses": ["catalysts", "PET scans", "refining"],
            "is_critical": False,
            "aliases": ["Lutetium"],
        },
    ]
    
    elements = []
    for data in elements_data:
        element = RareEarthElementDB(
            symbol=data["symbol"],
            name=data["name"],
            atomic_number=data["atomic_number"],
            category=data["category"],
            element_type=data["element_type"],
            atomic_weight=data["atomic_weight"],
            melting_point=data["melting_point"],
            boiling_point=data["boiling_point"],
            density=data["density"],
            discovery_year=data["discovery_year"],
            common_uses=data["common_uses"],
            is_critical=data["is_critical"],
            aliases=data["aliases"],
        )
        session.add(element)
        elements.append(element)
    
    session.commit()
    print(f"Seeded {len(elements)} rare earth elements.")
    session.close()
    
    return elements


def seed_rare_earth_markets():
    """
    Seed the database with major rare earth markets.
    
    Returns the list of created markets.
    """
    session = Session()
    
    # Check if markets already exist
    existing_count = session.query(RareEarthMarketDB).count()
    if existing_count > 0:
        print(f"Found {existing_count} existing rare earth markets. Skipping seed.")
        session.close()
        return []
    
    markets_data = [
        {
            "market_id": "baotou",
            "name": "Baotou Rare Earth Exchange",
            "market_type": "spot",
            "region": "china",
            "currency": "CNY",
            "description": "China's primary rare earth trading hub",
            "website": "https://www.cxre.com",
            "is_active": True,
            "data_sources": [
                "https://www.cxre.com",
                "https://www.rex.com.cn",
            ],
            "supported_elements": ["Sc", "Y", "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"],
            "update_frequency": "daily",
        },
        {
            "market_id": "shanghai",
            "name": "Shanghai Metal Market",
            "market_type": "spot",
            "region": "china",
            "currency": "CNY",
            "description": "Major metal market with rare earth price reporting",
            "website": "https://www.smm.cn",
            "is_active": True,
            "data_sources": [
                "https://www.smm.cn",
                "https://news.smm.cn",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
            "update_frequency": "daily",
        },
        {
            "market_id": "metal_pages",
            "name": "Metal Pages",
            "market_type": "spot",
            "region": "global",
            "currency": "USD",
            "description": "International metal pricing and news",
            "website": "https://www.metal-pages.com",
            "is_active": True,
            "data_sources": [
                "https://www.metal-pages.com",
                "https://www.metal-pages.com/metalprices/rare-earth/",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Er"],
            "update_frequency": "daily",
        },
        {
            "market_id": "argus_media",
            "name": "Argus Media",
            "market_type": "spot",
            "region": "global",
            "currency": "USD",
            "description": "Commodity price reporting agency",
            "website": "https://www.argusmedia.com",
            "is_active": True,
            "data_sources": [
                "https://www.argusmedia.com",
                "https://www.argusmedia.com/en/rare-earths",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
            "update_frequency": "daily",
        },
        {
            "market_id": "fastmarkets",
            "name": "Fastmarkets (formerly Metal Bulletin)",
            "market_type": "spot",
            "region": "global",
            "currency": "USD",
            "description": "Commodity price reporting and intelligence",
            "website": "https://www.fastmarkets.com",
            "is_active": True,
            "data_sources": [
                "https://www.fastmarkets.com",
                "https://www.fastmarkets.com/rare-earth-prices",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
            "update_frequency": "daily",
        },
        {
            "market_id": "asian_metal",
            "name": "Asian Metal",
            "market_type": "spot",
            "region": "asia",
            "currency": "USD",
            "description": "Asian metal market prices and news",
            "website": "https://www.asianmetal.com",
            "is_active": True,
            "data_sources": [
                "https://www.asianmetal.com",
                "https://www.asianmetal.com/rare-earth-prices",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
            "update_frequency": "daily",
        },
        {
            "market_id": "roskill",
            "name": "Roskill",
            "market_type": "spot",
            "region": "global",
            "currency": "USD",
            "description": "Commodity research and price data",
            "website": "https://roskill.com",
            "is_active": True,
            "data_sources": [
                "https://roskill.com",
                "https://roskill.com/market-research/rare-earths/",
            ],
            "supported_elements": ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er"],
            "update_frequency": "weekly",
        },
        {
            "market_id": "usgs",
            "name": "USGS Mineral Commodity Summaries",
            "market_type": "spot",
            "region": "north_america",
            "currency": "USD",
            "description": "US Geological Survey rare earth statistics",
            "website": "https://www.usgs.gov",
            "is_active": True,
            "data_sources": [
                "https://www.usgs.gov/centers/national-minerals-information-center/rare-earths-statistics-and-information",
                "https://pubs.usgs.gov/periodicals/mcs2023/mcs2023.pdf",
            ],
            "supported_elements": ["Sc", "Y", "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"],
            "update_frequency": "annual",
        },
    ]
    
    markets = []
    for data in markets_data:
        market = RareEarthMarketDB(
            market_id=data["market_id"],
            name=data["name"],
            market_type=data["market_type"],
            region=data["region"],
            currency=data["currency"],
            description=data["description"],
            website=data["website"],
            is_active=data["is_active"],
            data_sources=data["data_sources"],
            supported_elements=data["supported_elements"],
            update_frequency=data["update_frequency"],
        )
        session.add(market)
        markets.append(market)
    
    session.commit()
    print(f"Seeded {len(markets)} rare earth markets.")
    session.close()
    
    return markets


def seed_all():
    """Seed all default data."""
    print("Seeding Pillar 6 default data...")
    elements = seed_rare_earth_elements()
    markets = seed_rare_earth_markets()
    print(f"Seeding complete: {len(elements)} elements, {len(markets)} markets.")
    return elements, markets


if __name__ == "__main__":
    seed_all()
