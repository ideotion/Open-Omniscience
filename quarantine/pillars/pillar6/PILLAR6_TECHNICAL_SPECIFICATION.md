# Pillar 6: Rare Earth Market Intelligence - Technical Specification

**Open Omniscience - Rare Earth Elements Price Analysis & Market Intelligence**

**Version:** 1.0.0  
**Date:** 2026  
**Author:** Ideotion  
**Status:** Design Phase  

---

## 📋 Executive Summary

Pillar 6 implements a **comprehensive, global rare earth market intelligence system** that scrapes, analyzes, and correlates rare earth element (REE) market data from worldwide sources with news articles. This system enables investigative journalists to:

- Track rare earth element prices across all global markets
- Monitor supply chain dynamics and production volumes
- Identify correlations between REE price fluctuations and geopolitical/news events
- Analyze market trends and anomalies
- Visualize rare earth market data intuitively

**Key Principle:** All data is scraped from open web sources **without APIs, subscriptions, or authentication**. Data is centralized in the same database as articles for seamless cross-referencing.

---

## 🎯 Objectives

### Primary Goals
1. **Global Coverage**: Scrape data from all worldwide rare earth markets and producers
2. **Comprehensive Data**: Track all 17 rare earth elements with historical pricing
3. **Centralized Storage**: Unified database with articles and rare earth data
4. **Advanced Analysis**: Price fluctuation detection, trend analysis, anomaly detection
5. **Visualization Ready**: Time-series optimized, normalized for cross-element comparison
6. **User-Friendly**: Intuitive GUI access to all analysis capabilities

### Secondary Goals
1. **Real-Time Capabilities**: On-demand scraping with daily defaults
2. **Rate Limiting**: Respectful scraping with retries
3. **Robots.txt Compliance**: Ethical scraping practices
4. **Extensible Architecture**: Easy to add new data sources and analysis methods

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PILLAR 6: RARE EARTH MARKET INTELLIGENCE                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   SCRAPING      │    │   ANALYSIS       │    │    STORAGE       │       │
│  │   ENGINE        │    │   ENGINE        │    │    ENGINE        │       │
│  │                 │    │                 │    │                 │       │
│  │ • Market        │    │ • Fluctuation   │    │ • Time-Series   │       │
│  │   Discovery     │    │   Detection     │    │   Database      │       │
│  │ • Price Scraper │    │ • Trend         │    │ • Raw Data      │       │
│  │ • Production    │    │   Analysis      │    │   Table         │       │
│  │   Scraper       │    │ • Anomaly       │    │ • Processed     │       │
│  │ • Supply Chain  │    │   Detection      │    │   Data Table    │       │
│  │   Scraper       │    │ • Correlation   │    │ • Metadata      │       │
│  │ • Scheduler     │    │   Analysis      │    │   Index         │       │
│  │ • Rate Limiter  │    │ • Forecasting   │    │                 │       │
│  │                 │    │   Engine        │    │                 │       │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘       │
│           │                    │                     │                    │
│           ▼                    ▼                     ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        CENTRAL DATABASE                              │   │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                  │   │
│  │  │   articles           │  │   rare_earth_data    │                  │   │
│  │  │   (existing)         │  │   (new)              │                  │   │
│  │  └─────────────────────┘  └─────────────────────┘                  │   │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                  │   │
│  │  │   rare_earth_prices  │  │   rare_earth_        │                  │   │
│  │  │   (time-series)      │  │   production         │                  │   │
│  │  └─────────────────────┘  └─────────────────────┘                  │   │
│  │  ┌─────────────────────────────────────────────────────────────┐  │   │
│  │  │              article_rare_earth_links                         │  │   │
│  │  └─────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   API LAYER      │    │   CORRELATION    │    │   VISUALIZATION  │       │
│  │                 │    │   ENGINE         │    │   READY DATA     │       │
│  │ • REST Endpoints│    │                 │    │                 │       │
│  │ • Query Builder  │    │ • Article-REE   │    │ • Normalized    │       │
│  │ • Cache Layer    │    │   Linking       │    │   Metrics       │       │
│  │                 │    │ • Temporal       │    │ • Time-Bucketed │       │
│  │                 │    │   Analysis       │    │ • Aggregated    │       │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Data Model

### Core Entities

#### 1. RareEarthElement
```python
@dataclass
class RareEarthElement:
    """Metadata about a rare earth element."""
    id: str                    # Atomic symbol (e.g., "Nd", "Pr", "Dy")
    name: str                  # Full name (e.g., "Neodymium", "Praseodymium")
    atomic_number: int         # Atomic number
    category: str              # "Light" or "Heavy"
    symbol: str                # Chemical symbol
    description: str           # Description and uses
    is_critical: bool          # Whether this is a critical element
    common_uses: List[str]     # Common applications
    metadata: Dict[str, Any]    # Additional properties
```

#### 2. RareEarthMarket
```python
@dataclass
class RareEarthMarket:
    """Information about a rare earth market/exchange."""
    id: str                    # Unique identifier
    name: str                  # Market name (e.g., "China Spot Market", "LME")
    location: str              # Country/region
    currency: str              # Base currency (USD, CNY, EUR)
    market_type: str          # "spot", "futures", "wholesale", "retail"
    website: str               # Official website
    is_active: bool            # Currently operational
    reliability_score: float   # Data reliability (0-1)
    last_scraped: datetime     # Last successful scrape
    metadata: Dict[str, Any]    # Market-specific info
```

#### 3. RareEarthPrice (Time-Series)
```python
@dataclass
class RareEarthPrice:
    """Price data point for a rare earth element."""
    id: str                    # UUID
    element_id: str            # Reference to RareEarthElement
    market_id: str             # Reference to RareEarthMarket
    timestamp: datetime         # Date/time of price
    price: float               # Price per unit
    currency: str              # Currency (from market)
    unit: str                  # Unit (kg, tonne, lb, oz)
    purity: float              # Purity percentage (e.g., 99.0, 99.9)
    form: str                  # Form (oxide, metal, alloy, compound)
    price_type: str            # "spot", "futures", "ask", "bid", "average"
    source: str                # Data source
    is_verified: bool          # Whether price is verified
    confidence: float          # Confidence score (0-1)
    metadata: Dict[str, Any]    # Additional info (e.g., contract size)
```

#### 4. RareEarthProduction
```python
@dataclass
class RareEarthProduction:
    """Production data for rare earth elements."""
    id: str                    # UUID
    element_id: str            # Reference to RareEarthElement
    country: str               # ISO country code
    company: str               # Producing company (if known)
    date: datetime             # Reporting date
    production_volume: float  # Volume produced
    production_unit: str      # Unit (tonne, kg, etc.)
    capacity: float            # Production capacity
    capacity_unit: str         # Capacity unit
    utilization_rate: float    # Capacity utilization (0-1)
    source: str                # Data source
    metadata: Dict[str, Any]    # Additional info
```

#### 5. RareEarthInventory
```python
@dataclass
class RareEarthInventory:
    """Inventory/stockpile data for rare earth elements."""
    id: str                    # UUID
    element_id: str            # Reference to RareEarthElement
    holder: str                # Country, company, or entity holding inventory
    holder_type: str           # "country", "company", "exchange"
    date: datetime             # Reporting date
    inventory_volume: float    # Volume in inventory
    inventory_unit: str        # Unit (tonne, kg, etc.)
    change_pct: float          # Percentage change from previous
    source: str                # Data source
    metadata: Dict[str, Any]    # Additional info
```

#### 6. RareEarthAnalysis (Processed Data)
```python
@dataclass
class RareEarthAnalysis:
    """Analysis results for rare earth data."""
    id: str                    # UUID
    element_id: str            # Reference to RareEarthElement
    market_id: str             # Reference to RareEarthMarket (optional)
    analysis_type: str         # "fluctuation", "trend", "anomaly", "correlation", "forecast"
    analysis_date: datetime     # When analysis was performed
    time_period: str           # "1D", "7D", "30D", "90D", "1Y", "5Y", "MAX"
    
    # Analysis results
    results: Dict[str, Any]     # Type-specific results
    
    # Metadata
    confidence: float          # Analysis confidence score (0-1)
    severity: str              # "low", "medium", "high", "critical"
    related_articles: List[str] # IDs of related articles
    related_events: List[str]  # IDs of related events
    
    # For fluctuation analysis
    price_change_pct: float     # Percentage price change
    volume_change_pct: float   # Volume change (if applicable)
    volatility: float           # Volatility score
    
    # For trend analysis
    trend_direction: str       # "increasing", "decreasing", "stable"
    trend_strength: float      # Trend confidence (0-1)
    
    # For anomaly detection
    anomaly_type: str          # "price_spike", "volume_spike", "supply_shock", etc.
    anomaly_score: float       # Anomaly severity (0-1)
    
    # For correlation analysis
    correlation_score: float   # Correlation with news events
    correlated_article_ids: List[str]
    
    # For forecasting
    forecast_value: float      # Predicted future value
    forecast_period: str       # Forecast period (e.g., "30D")
    forecast_confidence: float # Forecast confidence (0-1)
```

#### 7. ArticleRareEarthLink (Correlation Table)
```python
@dataclass
class ArticleRareEarthLink:
    """Correlation between an article and rare earth data."""
    id: str                    # UUID
    article_id: str            # Reference to article
    element_id: str            # Reference to RareEarthElement
    market_id: str             # Reference to RareEarthMarket (optional)
    
    # Correlation metadata
    correlation_score: float   # Strength of correlation (0-1)
    correlation_type: str      # "mention", "event", "sentiment", "temporal", "statistical"
    
    # Temporal analysis
    time_diff_hours: float     # Hours between article and REE event
    direction: str             # "before", "after", "same_time"
    
    # Sentiment analysis
    article_sentiment: float   # Sentiment score from article (-1 to 1)
    market_sentiment: float    # Sentiment inferred from market data (-1 to 1)
    
    # Analysis
    is_significant: bool       # Whether correlation is statistically significant
    confidence: float          # Confidence in correlation (0-1)
    
    # Metadata
    created_at: datetime       # When link was created
    updated_at: datetime       # Last update
```

---

## 🗃️ Database Schema (SQLAlchemy)

```python
# SQLAlchemy Models for PostgreSQL/SQLite

class RareEarthElement(Base):
    __tablename__ = 'rare_earth_elements'
    
    id = Column(String(5), primary_key=True)  # Atomic symbol
    name = Column(String(50), nullable=False)
    atomic_number = Column(Integer, nullable=False)
    category = Column(String(20), nullable=False)  # 'Light' or 'Heavy'
    symbol = Column(String(5), nullable=False)
    description = Column(Text)
    is_critical = Column(Boolean, default=False)
    common_uses = Column(ARRAY(String))
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_element_category', 'category'),
        Index('idx_element_critical', 'is_critical'),
    )


class RareEarthMarket(Base):
    __tablename__ = 'rare_earth_markets'
    
    id = Column(String(10), primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(String(2), nullable=False)  # ISO country code
    currency = Column(String(3), nullable=False)
    market_type = Column(String(50))
    website = Column(String(500))
    is_active = Column(Boolean, default=True)
    reliability_score = Column(Float, default=0.8)
    last_scraped = Column(DateTime)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_market_location', 'location'),
        Index('idx_market_active', 'is_active'),
    )


class RareEarthPrice(Base):
    __tablename__ = 'rare_earth_prices'
    
    id = Column(String(36), primary_key=True)  # UUID
    element_id = Column(String(5), ForeignKey('rare_earth_elements.id'), nullable=False)
    market_id = Column(String(10), ForeignKey('rare_earth_markets.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    unit = Column(String(20), nullable=False)  # 'kg', 'tonne', 'lb', 'oz'
    purity = Column(Float)  # Percentage
    form = Column(String(50))  # 'oxide', 'metal', 'alloy'
    price_type = Column(String(20))  # 'spot', 'futures', 'ask', 'bid'
    source = Column(String(100))
    is_verified = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Time-series partitioning
    __table_args__ = (
        Index('idx_price_element_timestamp', 'element_id', 'timestamp'),
        Index('idx_price_market_timestamp', 'market_id', 'timestamp'),
        Index('idx_price_timestamp', 'timestamp'),
        Index('idx_price_element', 'element_id'),
    )


class RareEarthProduction(Base):
    __tablename__ = 'rare_earth_production'
    
    id = Column(String(36), primary_key=True)  # UUID
    element_id = Column(String(5), ForeignKey('rare_earth_elements.id'), nullable=False)
    country = Column(String(2), nullable=False)  # ISO country code
    company = Column(String(255))
    date = Column(DateTime, nullable=False)
    production_volume = Column(Float)
    production_unit = Column(String(20), nullable=False)
    capacity = Column(Float)
    capacity_unit = Column(String(20))
    utilization_rate = Column(Float)
    source = Column(String(100))
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_production_element_date', 'element_id', 'date'),
        Index('idx_production_country', 'country'),
        Index('idx_production_date', 'date'),
    )


class RareEarthInventory(Base):
    __tablename__ = 'rare_earth_inventory'
    
    id = Column(String(36), primary_key=True)  # UUID
    element_id = Column(String(5), ForeignKey('rare_earth_elements.id'), nullable=False)
    holder = Column(String(255), nullable=False)
    holder_type = Column(String(20), nullable=False)  # 'country', 'company', 'exchange'
    date = Column(DateTime, nullable=False)
    inventory_volume = Column(Float)
    inventory_unit = Column(String(20), nullable=False)
    change_pct = Column(Float)
    source = Column(String(100))
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_inventory_element_date', 'element_id', 'date'),
        Index('idx_inventory_holder', 'holder'),
        Index('idx_inventory_date', 'date'),
    )


class RareEarthAnalysis(Base):
    __tablename__ = 'rare_earth_analyses'
    
    id = Column(String(36), primary_key=True)  # UUID
    element_id = Column(String(5), ForeignKey('rare_earth_elements.id'))
    market_id = Column(String(10), ForeignKey('rare_earth_markets.id'))
    analysis_type = Column(String(50), nullable=False)
    analysis_date = Column(DateTime, default=datetime.utcnow)
    time_period = Column(String(20))
    
    # Results (JSON for flexibility)
    results = Column(JSON, nullable=False)
    
    # Analysis metadata
    confidence = Column(Float)
    severity = Column(String(20))
    
    # Correlations
    price_change_pct = Column(Float)
    volume_change_pct = Column(Float)
    volatility = Column(Float)
    trend_direction = Column(String(20))
    trend_strength = Column(Float)
    anomaly_type = Column(String(100))
    anomaly_score = Column(Float)
    correlation_score = Column(Float)
    
    # Relationships
    related_articles = Column(ARRAY(String))
    related_events = Column(ARRAY(String))
    
    # Forecasting
    forecast_value = Column(Float)
    forecast_period = Column(String(20))
    forecast_confidence = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_analysis_element', 'element_id'),
        Index('idx_analysis_type', 'analysis_type'),
        Index('idx_analysis_date', 'analysis_date'),
        Index('idx_analysis_severity', 'severity'),
    )


class ArticleRareEarthLink(Base):
    __tablename__ = 'article_rare_earth_links'
    
    id = Column(String(36), primary_key=True)  # UUID
    article_id = Column(String(36), ForeignKey('articles.id'))
    element_id = Column(String(5), ForeignKey('rare_earth_elements.id'))
    market_id = Column(String(10), ForeignKey('rare_earth_markets.id'))
    
    # Correlation metadata
    correlation_score = Column(Float)
    correlation_type = Column(String(50))
    time_diff_hours = Column(Float)
    direction = Column(String(20))
    
    # Sentiment
    article_sentiment = Column(Float)
    market_sentiment = Column(Float)
    
    # Analysis
    is_significant = Column(Boolean, default=False)
    confidence = Column(Float)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_article_ree_article', 'article_id'),
        Index('idx_article_ree_element', 'element_id'),
        Index('idx_article_ree_score', 'correlation_score'),
        Index('idx_article_ree_significant', 'is_significant'),
    )
```

---

## 🌍 Rare Earth Element Coverage

### All 17 Rare Earth Elements

#### Light Rare Earth Elements (LREE)
| Symbol | Name | Atomic # | Critical | Primary Uses |
|--------|------|----------|----------|--------------|
| La | Lanthanum | 57 | ❌ | Catalysts, glass, batteries |
| Ce | Cerium | 58 | ❌ | Catalysts, glass polishing, ceramics |
| Pr | Praseodymium | 59 | ✅ | Magnets (NdPr), alloys, coloring |
| Nd | Neodymium | 60 | ✅ | **Permanent magnets (NdFeB)**, lasers, hard drives |
| Pm | Promethium | 61 | ❌ | Nuclear batteries, luminous paints |
| Sm | Samarium | 62 | ✅ | Magnets (SmCo), catalysts, cancer treatment |
| Eu | Europium | 63 | ✅ | Phosphors (red), lasers, nuclear control |

#### Heavy Rare Earth Elements (HREE)
| Symbol | Name | Atomic # | Critical | Primary Uses |
|--------|------|----------|----------|--------------|
| Gd | Gadolinium | 64 | ✅ | MRI contrast, magnets, nuclear reactors |
| Tb | Terbium | 65 | ✅ | **Permanent magnets**, phosphors (green), lasers |
| Dy | Dysprosium | 66 | ✅ | **Permanent magnets (NdFeB)**, lasers, lighting |
| Ho | Holmium | 67 | ❌ | Magnets, lasers, nuclear control |
| Er | Erbium | 68 | ❌ | Fiber optics, lasers, coloring |
| Tm | Thulium | 69 | ❌ | Portable X-rays, lasers |
| Yb | Ytterbium | 70 | ❌ | Stress gauges, lasers, catalysts |
| Lu | Lutetium | 71 | ❌ | PET scans, catalysts, phosphors |
| Y | Yttrium | 39 | ✅ | Phosphors, ceramics, lasers, superconductors |
| Sc | Scandium | 21 | ✅ | Fuel cells, aerospace, lighting |

**Critical Elements (✅)**: Nd, Pr, Dy, Tb, Sm, Eu, Gd, Y, Sc (9 elements)
**Priority**: Focus on critical elements, especially Nd, Pr, Dy, Tb (magnet materials)

---

## 🔍 Scraping Strategy

### 1. Market Discovery
**Module:** `scraping.market_discovery`

```python
class MarketDiscovery:
    """Discovers and maintains list of rare earth markets."""
    
    def discover_markets(self) -> List[RareEarthMarket]:
        """Scrape and identify all global rare earth markets."""
        
    def get_market_metadata(self, market_id: str) -> RareEarthMarket:
        """Get detailed metadata for a specific market."""
        
    def update_market_list(self) -> None:
        """Periodically update the list of known markets."""
```

**Sources:**
- **Commodity Exchange Websites**: LME, SHFE, CME, ICE
- **Industry Publications**: Metal Bulletin, Platts, S&P Global
- **Government Sources**: USGS, China MIIT, EU reports
- **Company Reports**: Lynas, MP Materials, Rare Earths miners
- **News Websites**: Reuters, Bloomberg, Financial Times commodities sections
- **Research Institutions**: Rare earth research centers, universities

### 2. Price Data Scraping
**Module:** `scraping.price_scraper`

```python
class PriceScraper:
    """Scrapes price data for rare earth elements."""
    
    def scrape_current_prices(self, market_id: str) -> List[RareEarthPrice]:
        """Scrape current prices from a market."""
        
    def scrape_historical_prices(
        self, 
        element_id: str, 
        market_id: str,
        start_date: datetime, 
        end_date: datetime
    ) -> List[RareEarthPrice]:
        """Scrape historical prices for an element from a market."""
        
    def scrape_all_markets(self) -> List[RareEarthPrice]:
        """Scrape prices from all configured markets."""
```

**Sources by Market:**

#### Primary Sources (Direct Market Data)
- **China (Dominant Producer)**:
  - Baotou Rare Earth Products Exchange
  - China Rare Earth Information Network
  - Shanghai Metals Market (SMM)
  - Asian Metal
  - Mysteel
- **United States**:
  - MP Materials investor relations
  - USA Rare Earth
  - Texas Mineral Resources
- **Australia**:
  - Lynas Corporation reports
  - Northern Minerals
  - Arafura Resources
- **Europe**:
  - Less Common Metals (UK)
  - European Rare Earth Competency Network
- **Japan**:
  - Japan Oil, Gas and Metals National Corporation (JOGMEC)
  - Toyota Tsusho

#### Secondary Sources (Market Reports)
- **Metal Bulletin**: Weekly rare earth price assessments
- **Platts (S&P Global)**: Daily price assessments
- **Fastmarkets (formerly Metal Bulletin)**: Price data
- **Argus Media**: Rare earth market intelligence
- **Roskill**: Market analysis and forecasts
- **Adamas Intelligence**: Rare earth market research

#### News & Analysis Sources
- **Reuters**: Commodities section
- **Bloomberg**: Rare earth market coverage
- **Financial Times**: Commodities reporting
- **Mining.com**: Rare earth mining news
- **Investing News Network**: Rare earth investing
- **Kitco**: Precious metals (includes some REEs)

### 3. Production Data Scraping
**Module:** `scraping.production_scraper`

```python
class ProductionScraper:
    """Scrapes production data for rare earth elements."""
    
    def scrape_production_by_country(self, country: str) -> List[RareEarthProduction]:
        """Scrape production data for a specific country."""
        
    def scrape_production_by_company(self, company: str) -> List[RareEarthProduction]:
        """Scrape production data for a specific company."""
        
    def scrape_global_production(self) -> List[RareEarthProduction]:
        """Scrape global production data."""
```

**Sources:**
- **USGS Mineral Commodity Summaries**: Annual production statistics
- **China MIIT**: Chinese production quotas and data
- **Company Annual Reports**: Lynas, MP Materials, etc.
- **Industry Associations**: Rare earth industry associations
- **Government Statistical Agencies**: National statistics bureaus

### 4. Inventory & Stockpile Data
**Module:** `scraping.inventory_scraper`

```python
class InventoryScraper:
    """Scrapes inventory and stockpile data."""
    
    def scrape_strategic_stockpiles(self) -> List[RareEarthInventory]:
        """Scrape data on strategic stockpiles."""
        
    def scrape_exchange_inventory(self, exchange_id: str) -> List[RareEarthInventory]:
        """Scrape inventory data from exchanges."""
        
    def scrape_company_inventory(self, company: str) -> List[RareEarthInventory]:
        """Scrape inventory data from companies."""
```

**Sources:**
- **US Defense Logistics Agency**: Strategic stockpile reports
- **China State Reserve Bureau**: Stockpile information
- **Exchange Warehouse Reports**: LME, SHFE warehouse stocks
- **Company Filings**: Quarterly and annual reports

### 5. Scraping Configuration

```yaml
# configs/scraping.yaml
scraping:
  # Global settings
  user_agent: "OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"
  request_timeout: 30
  max_retries: 3
  retry_delay: 5
  respect_robots_txt: true
  
  # Rate limiting
  requests_per_minute: 60
  burst_requests: 10
  
  # Element priorities
  elements:
    critical: ["Nd", "Pr", "Dy", "Tb", "Sm", "Eu", "Gd", "Y", "Sc"]
    all: ["La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Y", "Sc"]
  
  # Market priorities
  markets:
    tier1:  # Primary markets
      - id: "china_spot"
        name: "China Spot Market"
        enabled: true
        priority: 1
        scrape_frequency: daily
        sources: ["smm", "asian_metal", "mysteel"]
        
      - id: "lme"
        name: "London Metal Exchange"
        enabled: true
        priority: 1
        scrape_frequency: daily
        sources: ["lme.com"]
        
      - id: "usgs"
        name: "USGS Mineral Commodity Summaries"
        enabled: true
        priority: 2
        scrape_frequency: monthly
        sources: ["usgs.gov"]
    
    tier2:  # Secondary markets
      - id: "mp_materials"
        name: "MP Materials"
        enabled: true
        priority: 2
        scrape_frequency: weekly
        sources: ["mpmaterials.com"]
        
      - id: "lynas"
        name: "Lynas Corporation"
        enabled: true
        priority: 2
        scrape_frequency: weekly
        sources: ["lynas.com"]
    
  # Data types
  data_types:
    prices:
      enabled: true
      lookback_days: 365
      granularity: daily
      
    production:
      enabled: true
      lookback_years: 10
      granularity: monthly
      
    inventory:
      enabled: true
      lookback_years: 5
      granularity: quarterly
```

---

## 📈 Analysis Engine

### 1. Fluctuation Detection
**Module:** `analysis.fluctuation_detector`

```python
class RareEarthFluctuationDetector:
    """Detects significant price fluctuations for rare earth elements."""
    
    def detect_fluctuations(
        self, 
        element_id: str, 
        time_period: str = "5D"
    ) -> List[RareEarthAnalysis]:
        """Detect price fluctuations for an element."""
        
    def calculate_volatility(
        self, 
        prices: List[RareEarthPrice]
    ) -> float:
        """Calculate historical volatility for a price series."""
        
    def identify_spikes_and_drops(
        self, 
        prices: List[RareEarthPrice],
        threshold_pct: float = 5.0
    ) -> List[RareEarthPrice]:
        """Identify significant price movements."""
        
    def detect_supply_shocks(self) -> List[RareEarthAnalysis]:
        """Detect potential supply shocks from production data."""
```

**Analysis Methods:**
- **Percentage Change**: Calculate % change over various periods (1D, 7D, 30D, etc.)
- **Volatility**: Historical volatility (standard deviation of returns)
- **Price Range**: Daily/weekly high-low range analysis
- **Volume Analysis**: Trading volume spikes (if available)
- **Supply-Demand Balance**: Compare production vs consumption
- **Inventory Changes**: Track stockpile/inventory changes

### 2. Trend Analysis
**Module:** `analysis.trend_analyzer`

```python
class RareEarthTrendAnalyzer:
    """Analyzes trends in rare earth element prices."""
    
    def analyze_trend(
        self, 
        element_id: str, 
        time_period: str = "90D"
    ) -> RareEarthAnalysis:
        """Analyze trend for an element."""
        
    def calculate_moving_averages(
        self, 
        prices: List[RareEarthPrice],
        periods: List[int] = [20, 50, 200]
    ) -> Dict[str, List[float]]:
        """Calculate moving averages for price series."""
        
    def detect_trend_reversals(
        self, 
        prices: List[RareEarthPrice]
    ) -> List[RareEarthAnalysis]:
        """Detect potential trend reversals."""
        
    def compare_elements(
        self, 
        element_ids: List[str],
        time_period: str = "1Y"
    ) -> Dict[str, RareEarthAnalysis]:
        """Compare trends across multiple elements."""
```

**Trend Types:**
- **Short-Term**: < 30 days
- **Medium-Term**: 30-180 days
- **Long-Term**: > 180 days

**Trend Directions:**
- **Strong Uptrend**: Price consistently rising with increasing volume
- **Uptrend**: Price generally rising
- **Sideways/Stable**: Price moving within a range
- **Downtrend**: Price generally falling
- **Strong Downtrend**: Price consistently falling with increasing volume

### 3. Anomaly Detection
**Module:** `analysis.anomaly_detector`

```python
class RareEarthAnomalyDetector:
    """Detects anomalies in rare earth market data."""
    
    def detect_anomalies(
        self, 
        element_id: str, 
        time_period: str = "30D"
    ) -> List[RareEarthAnalysis]:
        """Detect anomalies for an element."""
        
    def detect_price_anomalies(
        self, 
        prices: List[RareEarthPrice]
    ) -> List[RareEarthPrice]:
        """Detect unusual price movements."""
        
    def detect_production_anomalies(
        self, 
        production_data: List[RareEarthProduction]
    ) -> List[RareEarthProduction]:
        """Detect unusual production changes."""
        
    def detect_inventory_anomalies(
        self, 
        inventory_data: List[RareEarthInventory]
    ) -> List[RareEarthInventory]:
        """Detect unusual inventory changes."""
```

**Anomaly Types:**
- **Price Anomalies**: Price movements > 3 standard deviations from mean
- **Volume Anomalies**: Trading volume spikes without price movement
- **Production Anomalies**: Sudden production increases/decreases
- **Inventory Anomalies**: Unusual stockpile changes
- **Supply Chain Anomalies**: Disruptions in mining/processing
- **Geopolitical Anomalies**: Price movements correlated with political events

### 4. Correlation Engine
**Module:** `analysis.correlation_engine`

```python
class RareEarthCorrelationEngine:
    """Correlates rare earth data with news articles."""
    
    def correlate_with_articles(
        self, 
        element_id: str, 
        time_window: timedelta = timedelta(days=7)
    ) -> List[ArticleRareEarthLink]:
        """Find articles correlated with REE price movements."""
        
    def temporal_correlation(
        self, 
        price_event_time: datetime, 
        article_times: List[datetime]
    ) -> List[Tuple[datetime, float]]:
        """Calculate temporal correlation scores."""
        
    def sentiment_correlation(
        self, 
        price_data: List[RareEarthPrice],
        articles: List[Article]
    ) -> List[ArticleRareEarthLink]:
        """Correlate based on sentiment analysis."""
        
    def keyword_correlation(
        self, 
        element_id: str, 
        articles: List[Article]
    ) -> List[ArticleRareEarthLink]:
        """Correlate based on keyword matching."""
        
    def event_correlation(
        self, 
        element_id: str
    ) -> List[ArticleRareEarthLink]:
        """Correlate with known events (quotas, trade wars, etc.)."""
```

**Correlation Methods:**
- **Temporal Correlation**: Articles published near price events
- **Sentiment Correlation**: Article sentiment matches price movement direction
- **Keyword Correlation**: Articles mention element, company, or related terms
- **Event Correlation**: Articles about specific events (quotas, sanctions, etc.)
- **Statistical Correlation**: Mathematical correlation between news volume and price

### 5. Forecasting Engine
**Module:** `analysis.forecasting_engine`

```python
class RareEarthForecaster:
    """Forecasts future rare earth prices."""
    
    def forecast_price(
        self, 
        element_id: str, 
        forecast_period: str = "30D"
    ) -> RareEarthAnalysis:
        """Forecast future price for an element."""
        
    def train_model(
        self, 
        element_id: str,
        historical_data: List[RareEarthPrice]
    ) -> Any:
        """Train forecasting model for an element."""
        
    def evaluate_forecast(
        self, 
        forecast: RareEarthAnalysis,
        actual_data: List[RareEarthPrice]
    ) -> float:
        """Evaluate forecast accuracy."""
```

**Forecasting Methods:**
- **Moving Averages**: Simple, exponential, weighted
- **ARIMA**: AutoRegressive Integrated Moving Average
- **SARIMA**: Seasonal ARIMA
- **Prophet**: Facebook's forecasting tool
- **LSTM**: Long Short-Term Memory neural networks (if data available)
- **Ensemble Methods**: Combine multiple models

### 6. Normalization Engine
**Module:** `analysis.normalization_engine`

```python
class RareEarthNormalizer:
    """Normalizes rare earth data for cross-element comparison."""
    
    def normalize_price(
        self, 
        prices: List[RareEarthPrice],
        method: str = "percent"
    ) -> List[RareEarthPrice]:
        """Normalize price data."""
        
    def normalize_to_base_currency(
        self, 
        prices: List[RareEarthPrice],
        base_currency: str = "USD"
    ) -> List[RareEarthPrice]:
        """Convert all prices to a base currency."""
        
    def normalize_to_base_unit(
        self, 
        prices: List[RareEarthPrice],
        base_unit: str = "kg"
    ) -> List[RareEarthPrice]:
        """Convert all prices to a base unit."""
        
    def create_price_index(
        self, 
        element_ids: List[str],
        base_element: str = "Nd"
    ) -> Dict[str, List[float]]:
        """Create price index relative to a base element."""
```

**Normalization Methods:**
- **Percentage Normalization**: All prices relative to starting point (0-100%)
- **Z-Score Normalization**: Standardized scores
- **Min-Max Normalization**: Scale to 0-1 range
- **Currency Conversion**: Use historical FX rates
- **Unit Conversion**: Convert between kg, tonne, lb, oz
- **Price Index**: Create composite indices (e.g., "Critical REE Index")

---

## 💾 Storage Engine

### 1. Time-Series Storage
**Module:** `storage.time_series_storage`

```python
class RareEarthTimeSeriesStorage:
    """Optimized storage for time-series rare earth data."""
    
    def store_price(self, price: RareEarthPrice) -> None:
        """Store a single price data point."""
        
    def store_batch(self, prices: List[RareEarthPrice]) -> None:
        """Store multiple price data points efficiently."""
        
    def query_range(
        self, 
        element_id: str, 
        start: datetime, 
        end: datetime
    ) -> List[RareEarthPrice]:
        """Query price data points in a date range."""
        
    def query_aggregated(
        self, 
        element_id: str, 
        time_period: str
    ) -> RareEarthPrice:
        """Get aggregated data for a period."""
```

**Optimizations:**
- **Partitioning**: Data partitioned by element and date range
- **Indexing**: Multiple indexes for fast queries
- **Compression**: Historical data compression for efficiency
- **Caching**: Frequently accessed data cached in memory

### 2. Data Aggregation
**Module:** `storage.aggregation_engine`

```python
class RareEarthAggregationEngine:
    """Aggregates raw data into processed metrics."""
    
    def aggregate_daily(self, element_id: str) -> RareEarthPrice:
        """Aggregate to daily prices."""
        
    def aggregate_weekly(self, element_id: str) -> RareEarthPrice:
        """Aggregate to weekly prices."""
        
    def aggregate_monthly(self, element_id: str) -> RareEarthPrice:
        """Aggregate to monthly prices."""
        
    def create_composite_index(
        self, 
        element_ids: List[str],
        weights: Optional[Dict[str, float]] = None
    ) -> List[RareEarthPrice]:
        """Create weighted composite index from multiple elements."""
```

**Aggregation Levels:**
- **Tick Data**: Raw, unprocessed (if available)
- **Daily Data**: Daily prices (primary)
- **Weekly Data**: Weekly averages
- **Monthly Data**: Monthly averages
- **Quarterly Data**: Quarterly averages
- **Annual Data**: Annual averages

**Composite Indices:**
- **Critical REE Index**: Weighted average of critical elements
- **Light REE Index**: Average of light rare earths
- **Heavy REE Index**: Average of heavy rare earths
- **Magnet REE Index**: Nd, Pr, Dy, Tb (for permanent magnets)
- **All REE Index**: Average of all 17 elements

### 3. Data Retention Policy

```yaml
# configs/retention.yaml
retention:
  # Raw data
  tick_data: 7D      # Keep 7 days of tick data
  
  # Aggregated data
  daily_data: MAX    # Keep all daily data
  weekly_data: MAX   # Keep all weekly data
  monthly_data: MAX  # Keep all monthly data
  
  # Production data
  production_data: MAX  # Keep all production data
  
  # Inventory data
  inventory_data: MAX  # Keep all inventory data
  
  # Analysis results
  analysis_results: 365D  # Keep 1 year of analysis results
  
  # Cleanup
  cleanup_frequency: daily
  cleanup_time: "03:00"  # Run at 3 AM
```

---

## 🔌 API Layer

### REST API Endpoints

#### Element Endpoints
```
GET    /api/v1/rare_earth/elements              # List all rare earth elements
GET    /api/v1/rare_earth/elements/{id}        # Get element details
```

#### Market Endpoints
```
GET    /api/v1/rare_earth/markets              # List all markets
GET    /api/v1/rare_earth/markets/{id}        # Get market details
POST   /api/v1/rare_earth/markets/{id}/refresh  # Refresh market data
```

#### Price Endpoints
```
GET    /api/v1/rare_earth/prices               # Query price data
GET    /api/v1/rare_earth/prices/{id}         # Get specific price point
GET    /api/v1/rare_earth/elements/{id}/prices  # Get prices for an element
GET    /api/v1/rare_earth/markets/{id}/prices  # Get prices from a market
```

#### Production Endpoints
```
GET    /api/v1/rare_earth/production           # Query production data
GET    /api/v1/rare_earth/production/{id}     # Get specific production record
GET    /api/v1/rare_earth/elements/{id}/production  # Get production for an element
GET    /api/v1/rare_earth/countries/{code}/production  # Get production by country
```

#### Inventory Endpoints
```
GET    /api/v1/rare_earth/inventory            # Query inventory data
GET    /api/v1/rare_earth/inventory/{id}      # Get specific inventory record
```

#### Analysis Endpoints
```
GET    /api/v1/rare_earth/analysis/fluctuations  # Get fluctuation analysis
GET    /api/v1/rare_earth/analysis/trends      # Get trend analysis
GET    /api/v1/rare_earth/analysis/anomalies    # Get anomaly detection
GET    /api/v1/rare_earth/analysis/correlations # Get article correlations
GET    /api/v1/rare_earth/analysis/forecasts    # Get price forecasts
```

#### Correlation Endpoints
```
GET    /api/v1/rare_earth/correlations/articles  # Get all article-REE links
GET    /api/v1/rare_earth/correlations/{article_id}  # Get correlations for article
POST   /api/v1/rare_earth/correlations/analyze  # Analyze new correlations
```

#### Index Endpoints
```
GET    /api/v1/rare_earth/indices                # List all composite indices
GET    /api/v1/rare_earth/indices/{id}          # Get index details
GET    /api/v1/rare_earth/indices/critical      # Get Critical REE Index
GET    /api/v1/rare_earth/indices/magnet        # Get Magnet REE Index
```

### GraphQL API (Optional)
For complex queries across rare earth and article data.

---

## 🎨 GUI Integration

### Dashboard Components

#### 1. Rare Earth Overview Dashboard
- **Global Price Heatmap**: Visual representation of all elements
- **Top Movers**: Elements with largest % price changes
- **Critical Elements Focus**: Nd, Pr, Dy, Tb with special highlighting
- **Market Status**: Status of all tracked markets
- **Recent News**: Articles correlated with REE movements
- **Composite Indices**: Critical REE Index, Magnet REE Index, etc.

#### 2. Element Deep Dive
- **Price Chart**: Interactive price chart with technical indicators
- **Historical Data**: Full price history with zoom/pan
- **Production Data**: Mining and production statistics
- **Inventory Data**: Stockpile and warehouse levels
- **News Correlation**: Articles linked to this element
- **Analysis Results**: Fluctuations, trends, anomalies, forecasts
- **Comparisons**: Compare with other elements or indices

#### 3. Market Comparison
- **Cross-Market View**: Compare prices across different markets
- **Arbitrage Opportunities**: Identify price differences between markets
- **Market Share**: Production shares by country/company
- **Supply Chain**: Visualize mining to processing to end-use

#### 4. Correlation Explorer
- **Temporal View**: Timeline of articles and price movements
- **Sentiment Analysis**: Article sentiment vs. price direction
- **Keyword Cloud**: Most common terms in correlated articles
- **Event Timeline**: Major events and their impact on prices
- **Geopolitical Map**: Visualize geopolitical risks by region

#### 5. Advanced Analysis
- **Custom Queries**: Build complex rare earth queries
- **Pattern Scanner**: Scan for specific patterns across all elements
- **Anomaly Detector**: Find unusual market activity
- **Forecasting Tool**: Generate price forecasts
- **Portfolio Tracker**: Track custom element groups
- **Watchlists**: Save and monitor element groups

### GUI Technical Requirements

```javascript
// Example React component structure
class RareEarthDashboard extends React.Component {
  state = {
    selectedElement: 'Nd',
    selectedMarket: 'china_spot',
    timePeriod: '1Y',
    viewMode: 'chart', // 'chart', 'table', 'correlations', 'analysis'
  }
  
  render() {
    return (
      <div className="rare-earth-dashboard">
        <ElementSelector elements={this.props.elements} />
        <MarketSelector markets={this.props.markets} />
        <TimePeriodSelector />
        <ViewModeTabs />
        
        {this.state.viewMode === 'chart' && <PriceChart />}
        {this.state.viewMode === 'table' && <DataTable />}
        {this.state.viewMode === 'correlations' && <CorrelationView />}
        {this.state.viewMode === 'analysis' && <AnalysisPanel />}
        
        <NewsSidebar />
        <MarketStatusBar />
      </div>
    )
  }
}
```

---

## ⚙️ Scheduling System

### Scraping Schedule

```yaml
# configs/schedule.yaml
schedule:
  # Market discovery
  market_discovery:
    frequency: weekly
    day: monday
    time: "00:00"
    
  # Price data updates
  price_updates:
    frequency: daily
    time: "02:00"
    priority_markets: ["china_spot", "lme"]
    lookback_days: 1
    
  # Historical price backfill
  historical_backfill:
    frequency: weekly
    day: sunday
    time: "03:00"
    lookback_days: 30
    
  # Production data updates
  production_updates:
    frequency: monthly
    day: 1
    time: "04:00"
    lookback_months: 12
    
  # Inventory data updates
  inventory_updates:
    frequency: quarterly
    day: 1
    month: [1, 4, 7, 10]
    time: "05:00"
    
  # Analysis updates
  analysis_updates:
    frequency: hourly
    minute: 0
    
  # Correlation analysis
  correlation_analysis:
    frequency: hourly
    minute: 30
```

### On-Demand Scraping

```python
class OnDemandScraper:
    """Handles user-requested scraping."""
    
    def scrape_element(self, element_id: str) -> None:
        """Scrape all data for a specific element."""
        
    def scrape_market(self, market_id: str) -> None:
        """Scrape all data from a specific market."""
        
    def refresh_all(self) -> None:
        """Refresh all rare earth data."""
```

---

## 🛡️ Ethical & Legal Considerations

### Compliance
1. **Robots.txt**: Always respect robots.txt directives
2. **Rate Limiting**: Never exceed configured rate limits
3. **User-Agent**: Identify as OpenOmniscience bot
4. **Caching**: Cache responses to minimize requests
5. **Data Usage**: Only use publicly available data

### Data Privacy
1. **No Personal Data**: Avoid scraping personal/private information
2. **Public Data Only**: Only scrape data intended for public consumption
3. **No Authentication**: Never use credentials or bypass paywalls
4. **Attribution**: Maintain data source attribution

### Legal Disclaimer
```
This rare earth market data is provided for informational and journalistic purposes only.
It is not intended for trading, investment advice, or financial decision-making.
Users should verify data from official sources before making any decisions.
Open Omniscience is not responsible for the accuracy or completeness of this data.

Rare earth markets are highly specialized and prices can vary significantly based on:
- Purity levels
- Form (oxide, metal, alloy)
- Contract terms
- Market conditions
- Geopolitical factors

This data should be used as a starting point for investigation, not as definitive market data.
```

---

## 📦 Dependencies

### Python Packages
```
# Core
requests>=2.28.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pandas>=2.0.0
numpy>=1.24.0

# Database
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0  # PostgreSQL

# Scraping
scrapy>=2.8.0
selenium>=4.10.0  # For JavaScript-heavy sites
fake-useragent>=1.1.0

# Analysis
scipy>=1.10.0
statsmodels>=0.14.0
ta>=0.10.0  # Technical analysis library
pandas-ta>=0.3.0
scikit-learn>=1.3.0  # For forecasting

# Date/Time
pytz>=2023.0
python-dateutil>=2.8.0

# Caching
cachetools>=5.3.0

# Async
aiohttp>=3.8.0
asyncio-throttle>=1.0.2

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

### System Dependencies
- Python 3.10+
- PostgreSQL 14+ (recommended) or SQLite
- Redis (for caching and rate limiting)

---

## 🚀 Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Set up Pillar 6 directory structure
- [ ] Create database models
- [ ] Implement element and market discovery
- [ ] Set up storage engine
- [ ] Create basic API endpoints

### Phase 2: Core Scraping (Week 3-4)
- [ ] Implement price scraper for major markets
- [ ] Implement production data scraper
- [ ] Implement inventory data scraper
- [ ] Add rate limiting and retry logic
- [ ] Implement robots.txt compliance
- [ ] Set up scheduling system

### Phase 3: Analysis Engine (Week 5-6)
- [ ] Implement fluctuation detection
- [ ] Implement trend analysis
- [ ] Implement anomaly detection
- [ ] Implement normalization engine
- [ ] Implement aggregation engine

### Phase 4: Correlation Engine (Week 7-8)
- [ ] Implement temporal correlation
- [ ] Implement sentiment correlation
- [ ] Implement keyword correlation
- [ ] Implement event correlation
- [ ] Create article-REE linking

### Phase 5: Forecasting Engine (Week 9-10)
- [ ] Implement moving average forecasting
- [ ] Implement ARIMA forecasting
- [ ] Implement SARIMA forecasting
- [ ] Implement ensemble forecasting
- [ ] Create forecast evaluation

### Phase 6: GUI Integration (Week 11-12)
- [ ] Design dashboard components
- [ ] Implement rare earth overview dashboard
- [ ] Implement element deep dive
- [ ] Implement market comparison
- [ ] Implement correlation explorer
- [ ] Implement advanced analysis tools

### Phase 7: Testing & Optimization (Week 13-14)
- [ ] Write comprehensive tests
- [ ] Optimize scraping performance
- [ ] Optimize database queries
- [ ] Implement caching strategies
- [ ] Performance testing

### Phase 8: Documentation & Deployment (Week 15)
- [ ] Write user documentation
- [ ] Write developer documentation
- [ ] Create examples and tutorials
- [ ] Final integration testing
- [ ] Deployment preparation

---

## 📊 Success Metrics

### Coverage Metrics
- **Element Coverage**: All 17 rare earth elements
- **Market Coverage**: 10+ major markets worldwide
- **Data Coverage**: 90% of elements with price data
- **Historical Depth**: 10+ years of historical data for major elements

### Performance Metrics
- **Scraping Speed**: 50 elements/hour
- **Data Freshness**: < 24 hours for major markets
- **Query Performance**: < 100ms for common queries
- **Uptime**: 99.9% for scheduled scraping

### Quality Metrics
- **Data Accuracy**: > 90% match with official sources
- **Test Coverage**: > 80% code coverage
- **User Satisfaction**: > 4.5/5 in user surveys

---

## 📚 File Structure

```
pillar6/
├── README.md                          # Pillar 6 overview
├── PILLAR6_TECHNICAL_SPECIFICATION.md # This document
├── IMPLEMENTATION_PLAN.md             # Detailed implementation plan
│
├── src/
│   ├── __init__.py
│   │
│   ├── scraping/
│   │   ├── __init__.py
│   │   ├── market_discovery.py
│   │   ├── price_scraper.py
│   │   ├── production_scraper.py
│   │   ├── inventory_scraper.py
│   │   ├── scheduler.py
│   │   ├── rate_limiter.py
│   │   └── robots_txt.py
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── fluctuation_detector.py
│   │   ├── trend_analyzer.py
│   │   ├── anomaly_detector.py
│   │   ├── correlation_engine.py
│   │   ├── forecasting_engine.py
│   │   └── normalization_engine.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── time_series_storage.py
│   │   ├── aggregation_engine.py
│   │   └── retention_manager.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── element.py
│   │   ├── market.py
│   │   ├── price.py
│   │   ├── production.py
│   │   ├── inventory.py
│   │   ├── analysis.py
│   │   └── correlation.py
│   │
│   └── api/
│       ├── __init__.py
│       ├── routes.py
│       ├── schemas.py
│       └── query_builder.py
│
├── tests/
│   ├── __init__.py
│   ├── test_scraping.py
│   ├── test_analysis.py
│   ├── test_storage.py
│   └── test_api.py
│
├── configs/
│   ├── scraping.yaml
│   ├── schedule.yaml
│   ├── retention.yaml
│   └── elements.yaml
│
├── examples/
│   ├── basic_usage.py
│   ├── advanced_analysis.py
│   └── correlation_example.py
│
├── docs/
│   ├── USER_GUIDE.md
│   ├── DEVELOPER_GUIDE.md
│   └── API_DOCUMENTATION.md
│
└── scripts/
    ├── setup.py
    ├── backfill_data.py
    └── verify_data.py
```

---

## 🎯 Next Steps

1. **Review this specification** and provide feedback
2. **Approve the architecture** or request changes
3. **Prioritize features** based on importance
4. **Assign resources** for implementation
5. **Begin Phase 1** implementation

---

## 📞 Support & Contact

For questions about this specification:
- Open an issue on GitHub: https://github.com/ideotion/Open-Omniscience/issues
- Contact: open-omniscience@ideotion.com

---

**Document Status:** ✅ Complete  
**Review Required:** Yes  
**Approval Required:** Yes  

---

*© 2026 Ideotion. All rights reserved.*
*Licensed under GNU GPLv3*
