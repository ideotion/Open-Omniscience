# Pillar 5: Global Financial Intelligence - Technical Specification

**Open Omniscience - Financial Data Analysis & Stock Fluctuation Intelligence**

**Version:** 1.0.0  
**Date:** 2026  
**Author:** Ideotion  
**Status:** Design Phase  

---

## 📋 Executive Summary

Pillar 5 implements a **comprehensive, global financial intelligence system** that scrapes, analyzes, and correlates financial data from worldwide stock exchanges with news articles. This system enables investigative journalists to:

- Track stock price fluctuations across all global exchanges
- Identify correlations between financial movements and news events
- Analyze company fundamentals and market capitalizations
- Detect anomalies and patterns in financial data
- Visualize financial trends intuitively

**Key Principle:** All data is scraped from open web sources without APIs, subscriptions, or authentication. Data is centralized in the same database as articles for cross-referencing.

---

## 🎯 Objectives

### Primary Goals
1. **Global Coverage**: Scrape data from all worldwide stock exchanges
2. **Comprehensive Data**: OHLC, fundamentals, historical records
3. **Centralized Storage**: Unified database with articles and financial data
4. **Advanced Analysis**: Fluctuation detection, pattern recognition, correlation analysis
5. **Visualization Ready**: Time-series optimized, normalized for cross-exchange comparison
6. **User-Friendly**: Intuitive GUI access to all analysis capabilities

### Secondary Goals
1. **Real-Time Capabilities**: On-demand scraping with daily defaults
2. **Rate Limiting**: Respectful scraping with retries
3. **Robots.txt Compliance**: Ethical scraping practices
4. **Extensible Architecture**: Easy to add new exchanges and analysis methods

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PILLAR 5: FINANCIAL INTELLIGENCE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   SCRAPING      │    │   ANALYSIS       │    │    STORAGE       │       │
│  │   ENGINE        │    │   ENGINE        │    │    ENGINE        │       │
│  │                 │    │                 │    │                 │       │
│  │ • Exchange      │    │ • Fluctuation   │    │ • Time-Series   │       │
│  │   Discovery     │    │   Detection     │    │   Database      │       │
│  │ • OHLC Scraper  │    │ • Pattern       │    │ • Raw Data      │       │
│  │ • Fundamentals  │    │   Recognition    │    │   Table         │       │
│  │   Scraper       │    │ • Correlation   │    │ • Processed     │       │
│  │ • Scheduler     │    │   Analysis      │    │   Data Table    │       │
│  │ • Rate Limiter  │    │ • Anomaly       │    │ • Metadata      │       │
│  │                 │    │   Detection      │    │   Index         │       │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘       │
│           │                    │                     │                    │
│           ▼                    ▼                     ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        CENTRAL DATABASE                              │   │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                  │   │
│  │  │   articles           │  │   financial_data      │                  │   │
│  │  │   (existing)         │  │   (new)              │                  │   │
│  │  └─────────────────────┘  └─────────────────────┘                  │   │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                  │   │
│  │  │   financial_raw      │  │   financial_processed│                  │   │
│  │  │   (time-series)      │  │   (aggregated)        │                  │   │
│  │  └─────────────────────┘  └─────────────────────┘                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   API LAYER      │    │   CORRELATION    │    │   VISUALIZATION  │       │
│  │                 │    │   ENGINE         │    │   READY DATA     │       │
│  │ • REST Endpoints│    │                 │    │                 │       │
│  │ • Query Builder  │    │ • Article-Finance│    │ • Normalized    │       │
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

#### 1. Exchange
```python
@dataclass
class Exchange:
    id: str                    # Unique identifier (e.g., "NYSE", "NASDAQ")
    name: str                  # Full name (e.g., "New York Stock Exchange")
    country: str               # ISO country code
    currency: str              # Base currency (USD, EUR, JPY, etc.)
    timezone: str              # Timezone identifier
    website: str               # Official website URL
    trading_hours: str         # Trading hours in ISO format
    is_active: bool            # Currently operational
    last_scraped: datetime     # Last successful scrape
    metadata: Dict[str, Any]    # Additional exchange-specific info
```

#### 2. Company
```python
@dataclass
class Company:
    id: str                    # Unique identifier (ISIN, ticker, or generated)
    ticker: str                # Stock ticker symbol
    exchange_id: str           # Reference to exchange
    name: str                  # Company name
    sector: str                # Industry sector
    industry: str              # Specific industry
    founded_year: int          # Year founded
    headquarters: str          # Headquarters location
    website: str               # Company website
    description: str           # Business description
    is_active: bool            # Currently listed
    last_updated: datetime     # Last data update
```

#### 3. FinancialDataPoint (Time-Series)
```python
@dataclass
class FinancialDataPoint:
    id: str                    # UUID
    company_id: str            # Reference to company
    timestamp: datetime         # Date/time of data point
    open: float                # Opening price
    high: float                # Highest price
    low: float                 # Lowest price
    close: float               # Closing price
    adjusted_close: float      # Adjusted closing price
    volume: int                # Trading volume
    currency: str              # Currency (from exchange)
    is_dividend_adjusted: bool # Dividend adjustment flag
    data_source: str           # Source of this data point
    metadata: Dict[str, Any]    # Additional info (e.g., "split_factor")
```

#### 4. CompanyFundamentals
```python
@dataclass
class CompanyFundamentals:
    id: str                    # UUID
    company_id: str            # Reference to company
    date: datetime             # Reporting date
    market_cap: float          # Market capitalization
    pe_ratio: float            # Price-to-Earnings ratio
    peg_ratio: float           # PE-to-Growth ratio
    pb_ratio: float            # Price-to-Book ratio
    ps_ratio: float            # Price-to-Sales ratio
    dividend_yield: float      # Dividend yield
    beta: float                # Beta coefficient
    eps: float                 # Earnings per share
    revenue: float             # Revenue
    net_income: float          # Net income
    profit_margin: float       # Profit margin
    debt_to_equity: float      # Debt-to-equity ratio
    current_ratio: float       # Current ratio
    roe: float                 # Return on equity
    roa: float                 # Return on assets
    currency: str              # Currency
    fiscal_period: str         # Quarterly, Annual, TTM
    source: str                # Data source
```

#### 5. FinancialAnalysis (Processed Data)
```python
@dataclass
class FinancialAnalysis:
    id: str                    # UUID
    company_id: str            # Reference to company
    analysis_type: str         # "fluctuation", "pattern", "anomaly", "correlation"
    analysis_date: datetime     # When analysis was performed
    time_period: str           # "1D", "5D", "1M", "3M", "1Y", "5Y", "MAX"
    
    # Analysis results
    results: Dict[str, Any]     # Type-specific results
    
    # Metadata
    confidence: float          # Analysis confidence score (0-1)
    severity: str              # "low", "medium", "high", "critical"
    related_articles: List[str] # IDs of related articles
    related_events: List[str]  # IDs of related financial events
    
    # For fluctuation analysis
    price_change_pct: float     # Percentage change
    volume_change_pct: float   # Volume change
    volatility: float           # Volatility score
    
    # For pattern analysis
    pattern_type: str          # "head_and_shoulders", "double_top", etc.
    pattern_strength: float    # Pattern confidence
    
    # For correlation analysis
    correlation_score: float   # Correlation with news events
    correlated_article_ids: List[str]
```

#### 6. ArticleFinancialLink (Correlation Table)
```python
@dataclass
class ArticleFinancialLink:
    id: str                    # UUID
    article_id: str            # Reference to article
    company_id: str            # Reference to company
    exchange_id: str           # Reference to exchange
    
    # Correlation metadata
    correlation_score: float   # Strength of correlation (0-1)
    correlation_type: str      # "mention", "event", "sentiment", "temporal"
    
    # Temporal analysis
    time_diff_hours: float     # Hours between article and financial event
    direction: str             # "before", "after", "same_time"
    
    # Sentiment analysis
    article_sentiment: float   # Sentiment score from article
    financial_sentiment: float # Sentiment inferred from financial data
    
    # Analysis
    is_significant: bool       # Whether correlation is statistically significant
    confidence: float          # Confidence in correlation
    
    # Metadata
    created_at: datetime       # When link was created
    updated_at: datetime       # Last update
```

---

## 🗃️ Database Schema (SQLAlchemy)

```python
# SQLAlchemy Models for PostgreSQL/SQLite

class Exchange(Base):
    __tablename__ = 'financial_exchanges'
    
    id = Column(String(10), primary_key=True)
    name = Column(String(255), nullable=False)
    country = Column(String(2), nullable=False)
    currency = Column(String(3), nullable=False)
    timezone = Column(String(50), nullable=False)
    website = Column(String(500))
    trading_hours = Column(String(100))
    is_active = Column(Boolean, default=True)
    last_scraped = Column(DateTime)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Company(Base):
    __tablename__ = 'financial_companies'
    
    id = Column(String(50), primary_key=True)  # ISIN or generated UUID
    ticker = Column(String(20), nullable=False, index=True)
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    name = Column(String(255), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    founded_year = Column(Integer)
    headquarters = Column(String(255))
    website = Column(String(500))
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes for fast lookups
    __table_args__ = (
        Index('idx_company_ticker_exchange', 'ticker', 'exchange_id', unique=True),
        Index('idx_company_sector', 'sector'),
        Index('idx_company_industry', 'industry'),
    )


class FinancialDataPoint(Base):
    __tablename__ = 'financial_data_points'
    
    id = Column(String(36), primary_key=True)  # UUID
    company_id = Column(String(50), ForeignKey('financial_companies.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(BigInteger)
    currency = Column(String(3))
    is_dividend_adjusted = Column(Boolean, default=False)
    data_source = Column(String(100))
    metadata = Column(JSON)
    
    # Time-series partitioning
    __table_args__ = (
        Index('idx_financial_company_timestamp', 'company_id', 'timestamp'),
        Index('idx_financial_timestamp', 'timestamp'),
    )


class CompanyFundamentals(Base):
    __tablename__ = 'financial_fundamentals'
    
    id = Column(String(36), primary_key=True)  # UUID
    company_id = Column(String(50), ForeignKey('financial_companies.id'), nullable=False)
    date = Column(DateTime, nullable=False)
    fiscal_period = Column(String(20))
    
    # Valuation metrics
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    peg_ratio = Column(Float)
    pb_ratio = Column(Float)
    ps_ratio = Column(Float)
    
    # Profitability metrics
    eps = Column(Float)
    revenue = Column(Float)
    net_income = Column(Float)
    profit_margin = Column(Float)
    
    # Dividend metrics
    dividend_yield = Column(Float)
    
    # Risk metrics
    beta = Column(Float)
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    
    # Metadata
    currency = Column(String(3))
    source = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_fundamentals_company_date', 'company_id', 'date'),
        Index('idx_fundamentals_date', 'date'),
    )


class FinancialAnalysis(Base):
    __tablename__ = 'financial_analyses'
    
    id = Column(String(36), primary_key=True)  # UUID
    company_id = Column(String(50), ForeignKey('financial_companies.id'))
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
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
    pattern_type = Column(String(100))
    pattern_strength = Column(Float)
    correlation_score = Column(Float)
    
    # Relationships
    related_articles = Column(ARRAY(String))
    related_events = Column(ARRAY(String))
    
    __table_args__ = (
        Index('idx_analysis_company', 'company_id'),
        Index('idx_analysis_type', 'analysis_type'),
        Index('idx_analysis_date', 'analysis_date'),
        Index('idx_analysis_severity', 'severity'),
    )


class ArticleFinancialLink(Base):
    __tablename__ = 'article_financial_links'
    
    id = Column(String(36), primary_key=True)  # UUID
    article_id = Column(String(36), ForeignKey('articles.id'))
    company_id = Column(String(50), ForeignKey('financial_companies.id'))
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    
    # Correlation metadata
    correlation_score = Column(Float)
    correlation_type = Column(String(50))
    time_diff_hours = Column(Float)
    direction = Column(String(20))
    
    # Sentiment
    article_sentiment = Column(Float)
    financial_sentiment = Column(Float)
    
    # Analysis
    is_significant = Column(Boolean, default=False)
    confidence = Column(Float)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_article_financial_article', 'article_id'),
        Index('idx_article_financial_company', 'company_id'),
        Index('idx_article_financial_score', 'correlation_score'),
        Index('idx_article_financial_significant', 'is_significant'),
    )
```

---

## 🌍 Exchange Coverage

### Tier 1: Major Global Exchanges (Priority)
| Exchange | ID | Country | Currency | Priority |
|----------|-----|---------|----------|----------|
| NYSE | NYSE | USA | USD | 1 |
| NASDAQ | NASDAQ | USA | USD | 1 |
| London Stock Exchange | LSE | UK | GBP | 1 |
| Tokyo Stock Exchange | TSE | Japan | JPY | 1 |
| Shanghai Stock Exchange | SSE | China | CNY | 1 |
| Shenzhen Stock Exchange | SZSE | China | CNY | 1 |
| Hong Kong Stock Exchange | HKEX | Hong Kong | HKD | 1 |
| Euronext | ENXT | EU | EUR | 1 |
| Deutsche Börse | DB | Germany | EUR | 1 |
| Toronto Stock Exchange | TSX | Canada | CAD | 1 |
| Australian Securities Exchange | ASX | Australia | AUD | 1 |
| Bombay Stock Exchange | BSE | India | INR | 1 |
| National Stock Exchange of India | NSE | India | INR | 1 |
| São Paulo Stock Exchange | B3 | Brazil | BRL | 1 |

### Tier 2: Regional Exchanges
| Exchange | ID | Country | Currency | Priority |
|----------|-----|---------|----------|----------|
| Swiss Exchange | SIX | Switzerland | CHF | 2 |
| Stockholm Stock Exchange | OMX | Sweden | SEK | 2 |
| Oslo Stock Exchange | OSE | Norway | NOK | 2 |
| Singapore Exchange | SGX | Singapore | SGD | 2 |
| Korea Exchange | KRX | South Korea | KRW | 2 |
| Taiwan Stock Exchange | TWSE | Taiwan | TWD | 2 |
| Mexico Stock Exchange | BMV | Mexico | MXN | 2 |
| Johannesburg Stock Exchange | JSE | South Africa | ZAR | 2 |

### Tier 3: Emerging Markets
| Exchange | ID | Country | Currency | Priority |
|----------|-----|---------|----------|----------|
| Moscow Exchange | MOEX | Russia | RUB | 3 |
| Istanbul Stock Exchange | BIST | Turkey | TRY | 3 |
| Saudi Stock Exchange | TADAWUL | Saudi Arabia | SAR | 3 |
| Dubai Financial Market | DFM | UAE | AED | 3 |
| Qatar Stock Exchange | QSE | Qatar | QAR | 3 |
| Egyptian Exchange | EGX | Egypt | EGP | 3 |
| Nigeria Stock Exchange | NSE | Nigeria | NGN | 3 |

---

## 🔍 Scraping Strategy

### 1. Exchange Discovery
**Module:** `scraping.exchange_discovery`

```python
class ExchangeDiscovery:
    """Discovers and maintains list of global stock exchanges."""
    
    def discover_exchanges(self) -> List[Exchange]:
        """Scrape and identify all global stock exchanges."""
        
    def get_exchange_metadata(self, exchange_id: str) -> Exchange:
        """Get detailed metadata for a specific exchange."""
        
    def update_exchange_list(self) -> None:
        """Periodically update the list of known exchanges."""
```

**Sources:**
- Wikipedia: List of stock exchanges
- World Federation of Exchanges (WFE)
- Exchange websites (about pages)
- Financial news websites

### 2. Company Discovery
**Module:** `scraping.company_discovery`

```python
class CompanyDiscovery:
    """Discovers companies listed on each exchange."""
    
    def discover_companies(self, exchange_id: str) -> List[Company]:
        """Scrape all companies listed on an exchange."""
        
    def get_company_details(self, company_id: str) -> Company:
        """Get detailed information about a company."""
        
    def update_company_list(self, exchange_id: str) -> None:
        """Update the list of companies for an exchange."""
```

**Sources per Exchange:**
- NYSE/NASDAQ: Official company lists, Yahoo Finance, MarketWatch
- LSE: London Stock Exchange website, Investegate
- TSE: Tokyo Stock Exchange listings
- SSE/SZSE: Official exchange websites, Sina Finance
- HKEX: Hong Kong Exchanges website
- Euronext: Euronext listings
- Others: Official exchange websites, financial portals

### 3. OHLC Data Scraping
**Module:** `scraping.ohlc_scraper`

```python
class OHLCScraper:
    """Scrapes historical OHLC data for companies."""
    
    def scrape_historical_data(
        self, 
        company_id: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[FinancialDataPoint]:
        """Scrape OHLC data for a date range."""
        
    def scrape_current_data(self, company_id: str) -> FinancialDataPoint:
        """Scrape latest available data point."""
        
    def scrape_intraday_data(
        self, 
        company_id: str, 
        date: datetime
    ) -> List[FinancialDataPoint]:
        """Scrape intraday data (if available)."""
```

**Sources:**
- Yahoo Finance (no API, scrape HTML)
- Google Finance
- Investing.com
- MarketWatch
- Bloomberg (limited)
- Exchange-specific historical data pages

### 4. Fundamentals Scraping
**Module:** `scraping.fundamentals_scraper`

```python
class FundamentalsScraper:
    """Scrapes company fundamentals data."""
    
    def scrape_fundamentals(
        self, 
        company_id: str, 
        fiscal_period: str = "TTM"
    ) -> CompanyFundamentals:
        """Scrape fundamentals for a company."""
        
    def scrape_all_fundamentals(self, company_id: str) -> List[CompanyFundamentals]:
        """Scrape all available historical fundamentals."""
```

**Sources:**
- Yahoo Finance (Key Statistics, Financials tabs)
- Google Finance (Financials section)
- Investing.com (Company Financials)
- MarketWatch (Financials)
- Morningstar (free tier)
- Exchange filings (10-K, 10-Q, annual reports)

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
  
  # Exchange-specific settings
  exchanges:
    NYSE:
      enabled: true
      priority: 1
      scrape_frequency: daily
      company_list_url: "https://www.nyse.com/listings_directory/stock"
      
    NASDAQ:
      enabled: true
      priority: 1
      scrape_frequency: daily
      company_list_url: "https://www.nasdaq.com/market-activity/stocks/screener"
      
    # ... other exchanges
  
  # Data sources
  sources:
    yahoo_finance:
      enabled: true
      base_url: "https://finance.yahoo.com"
      
    google_finance:
      enabled: true
      base_url: "https://www.google.com/finance"
      
    investing_com:
      enabled: true
      base_url: "https://www.investing.com"
```

---

## 📈 Analysis Engine

### 1. Fluctuation Detection
**Module:** `analysis.fluctuation_detector`

```python
class FluctuationDetector:
    """Detects significant price fluctuations."""
    
    def detect_fluctuations(
        self, 
        company_id: str, 
        time_period: str = "5D"
    ) -> List[FinancialAnalysis]:
        """Detect price fluctuations for a company."""
        
    def calculate_volatility(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> float:
        """Calculate historical volatility."""
        
    def identify_spikes_and_drops(
        self, 
        data_points: List[FinancialDataPoint],
        threshold_pct: float = 5.0
    ) -> List[FinancialDataPoint]:
        """Identify significant price movements."""
```

**Analysis Methods:**
- **Percentage Change**: Calculate % change over various periods
- **Volatility**: Historical volatility (standard deviation of returns)
- **Volume Analysis**: Unusual volume spikes
- **Gap Detection**: Price gaps between sessions
- **Circuit Breaker Events**: Detect exchange circuit breaker triggers

### 2. Pattern Recognition
**Module:** `analysis.pattern_recognizer`

```python
class FinancialPatternRecognizer:
    """Recognizes chart patterns in financial data."""
    
    def recognize_patterns(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> List[FinancialAnalysis]:
        """Recognize chart patterns."""
        
    def detect_head_and_shoulders(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> Optional[FinancialAnalysis]:
        """Detect head and shoulders pattern."""
        
    def detect_double_top(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> Optional[FinancialAnalysis]:
        """Detect double top pattern."""
        
    def detect_double_bottom(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> Optional[FinancialAnalysis]:
        """Detect double bottom pattern."""
```

**Patterns to Detect:**
- Head and Shoulders (Bearish)
- Inverse Head and Shoulders (Bullish)
- Double Top (Bearish)
- Double Bottom (Bullish)
- Triple Top/Bottom
- Rising/Falling Wedge
- Ascending/Descending Triangle
- Symmetrical Triangle
- Flag and Pennant
- Cup and Handle
- Rounding Bottom/Top
- Gap Patterns

### 3. Anomaly Detection
**Module:** `analysis.anomaly_detector`

```python
class FinancialAnomalyDetector:
    """Detects anomalies in financial data."""
    
    def detect_anomalies(
        self, 
        company_id: str, 
        time_period: str = "30D"
    ) -> List[FinancialAnalysis]:
        """Detect anomalies for a company."""
        
    def detect_volume_anomalies(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> List[FinancialDataPoint]:
        """Detect unusual trading volumes."""
        
    def detect_price_anomalies(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> List[FinancialDataPoint]:
        """Detect unusual price movements."""
```

**Anomaly Types:**
- **Volume Anomalies**: Volume > 3x average, volume spikes without news
- **Price Anomalies**: Price movements > 3 standard deviations
- **Liquidity Anomalies**: Unusual bid-ask spreads
- **Temporal Anomalies**: Trading outside normal hours
- **Fundamental Anomalies**: Sudden changes in fundamentals

### 4. Correlation Engine
**Module:** `analysis.correlation_engine`

```python
class FinancialCorrelationEngine:
    """Correlates financial data with news articles."""
    
    def correlate_with_articles(
        self, 
        company_id: str, 
        time_window: timedelta = timedelta(days=7)
    ) -> List[ArticleFinancialLink]:
        """Find articles correlated with financial movements."""
        
    def temporal_correlation(
        self, 
        financial_event_time: datetime, 
        article_times: List[datetime]
    ) -> List[Tuple[datetime, float]]:
        """Calculate temporal correlation scores."""
        
    def sentiment_correlation(
        self, 
        financial_data: List[FinancialDataPoint],
        articles: List[Article]
    ) -> List[ArticleFinancialLink]:
        """Correlate based on sentiment analysis."""
        
    def keyword_correlation(
        self, 
        company_id: str, 
        articles: List[Article]
    ) -> List[ArticleFinancialLink]:
        """Correlate based on keyword matching."""
```

**Correlation Methods:**
- **Temporal Correlation**: Articles published near financial events
- **Sentiment Correlation**: Article sentiment matches price movement direction
- **Keyword Correlation**: Articles mention company, sector, or related terms
- **Event Correlation**: Articles about specific events (earnings, mergers, etc.)
- **Statistical Correlation**: Mathematical correlation between news volume and price

### 5. Normalization Engine
**Module:** `analysis.normalization_engine`

```python
class FinancialNormalizer:
    """Normalizes financial data for cross-exchange comparison."""
    
    def normalize_price(
        self, 
        data_points: List[FinancialDataPoint],
        method: str = "percent"
    ) -> List[FinancialDataPoint]:
        """Normalize price data."""
        
    def normalize_volume(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> List[FinancialDataPoint]:
        """Normalize volume data."""
        
    def normalize_to_base_currency(
        self, 
        data_points: List[FinancialDataPoint],
        base_currency: str = "USD"
    ) -> List[FinancialDataPoint]:
        """Convert all prices to a base currency."""
```

**Normalization Methods:**
- **Percentage Normalization**: All prices relative to starting point (0-100%)
- **Z-Score Normalization**: Standardized scores
- **Min-Max Normalization**: Scale to 0-1 range
- **Currency Conversion**: Use historical FX rates
- **Volume Normalization**: Average volume = 1.0

---

## 💾 Storage Engine

### 1. Time-Series Storage
**Module:** `storage.time_series_storage`

```python
class TimeSeriesStorage:
    """Optimized storage for time-series financial data."""
    
    def store_data_point(self, data_point: FinancialDataPoint) -> None:
        """Store a single data point."""
        
    def store_batch(self, data_points: List[FinancialDataPoint]) -> None:
        """Store multiple data points efficiently."""
        
    def query_range(
        self, 
        company_id: str, 
        start: datetime, 
        end: datetime
    ) -> List[FinancialDataPoint]:
        """Query data points in a date range."""
        
    def query_aggregated(
        self, 
        company_id: str, 
        time_period: str
    ) -> FinancialDataPoint:
        """Get aggregated data for a period."""
```

**Optimizations:**
- **Partitioning**: Data partitioned by company and date range
- **Indexing**: Multiple indexes for fast queries
- **Compression**: Historical data compression for efficiency
- **Caching**: Frequently accessed data cached in memory

### 2. Data Aggregation
**Module:** `storage.aggregation_engine`

```python
class AggregationEngine:
    """Aggregates raw data into processed metrics."""
    
    def aggregate_daily(self, company_id: str) -> FinancialDataPoint:
        """Aggregate to daily OHLC."""
        
    def aggregate_weekly(self, company_id: str) -> FinancialDataPoint:
        """Aggregate to weekly OHLC."""
        
    def aggregate_monthly(self, company_id: str) -> FinancialDataPoint:
        """Aggregate to monthly OHLC."""
        
    def calculate_moving_averages(
        self, 
        data_points: List[FinancialDataPoint],
        periods: List[int] = [20, 50, 200]
    ) -> Dict[str, List[float]]:
        """Calculate moving averages."""
        
    def calculate_technical_indicators(
        self, 
        data_points: List[FinancialDataPoint]
    ) -> Dict[str, List[float]]:
        """Calculate RSI, MACD, Bollinger Bands, etc."""
```

**Aggregation Levels:**
- **Tick Data**: Raw, unprocessed (if available)
- **Minute Data**: 1-minute intervals
- **Hourly Data**: Hourly OHLC
- **Daily Data**: Daily OHLC (primary)
- **Weekly Data**: Weekly OHLC
- **Monthly Data**: Monthly OHLC
- **Quarterly Data**: Quarterly fundamentals
- **Annual Data**: Annual fundamentals

### 3. Data Retention Policy

```yaml
# configs/retention.yaml
retention:
  # Raw data
  tick_data: 7D      # Keep 7 days of tick data
  minute_data: 30D   # Keep 30 days of minute data
  hourly_data: 90D   # Keep 90 days of hourly data
  
  # Aggregated data
  daily_data: MAX    # Keep all daily data
  weekly_data: MAX   # Keep all weekly data
  monthly_data: MAX  # Keep all monthly data
  
  # Fundamentals
  fundamentals: MAX  # Keep all fundamentals data
  
  # Analysis results
  analysis_results: 365D  # Keep 1 year of analysis results
  
  # Cleanup
  cleanup_frequency: daily
  cleanup_time: "02:00"  # Run at 2 AM
```

---

## 🔌 API Layer

### REST API Endpoints

#### Exchange Endpoints
```
GET    /api/v1/financial/exchanges              # List all exchanges
GET    /api/v1/financial/exchanges/{id}       # Get exchange details
POST   /api/v1/financial/exchanges/{id}/refresh  # Refresh exchange data
```

#### Company Endpoints
```
GET    /api/v1/financial/companies             # List companies (with filters)
GET    /api/v1/financial/companies/{id}        # Get company details
GET    /api/v1/financial/companies/{id}/ohlc   # Get OHLC data
GET    /api/v1/financial/companies/{id}/fundamentals  # Get fundamentals
POST   /api/v1/financial/companies/{id}/refresh  # Refresh company data
```

#### Data Endpoints
```
GET    /api/v1/financial/data/ohlc              # Query OHLC data
GET    /api/v1/financial/data/fundamentals      # Query fundamentals
GET    /api/v1/financial/data/aggregated        # Get aggregated data
```

#### Analysis Endpoints
```
GET    /api/v1/financial/analysis/fluctuations  # Get fluctuation analysis
GET    /api/v1/financial/analysis/patterns     # Get pattern analysis
GET    /api/v1/financial/analysis/anomalies     # Get anomaly detection
GET    /api/v1/financial/analysis/correlations  # Get article correlations
```

#### Correlation Endpoints
```
GET    /api/v1/financial/correlations/articles  # Get article-finance links
GET    /api/v1/financial/correlations/{article_id}  # Get correlations for article
POST   /api/v1/financial/correlations/analyze  # Analyze new correlations
```

### GraphQL API (Optional)
For complex queries across financial and article data.

---

## 🎨 GUI Integration

### Dashboard Components

#### 1. Financial Overview Dashboard
- **Global Market Heatmap**: Visual representation of all exchanges
- **Top Movers**: Companies with largest % changes
- **Volume Leaders**: Most actively traded companies
- **Sector Performance**: Performance by sector/industry
- **Recent News**: Articles correlated with financial movements

#### 2. Company Deep Dive
- **Price Chart**: Interactive OHLC chart with technical indicators
- **Fundamentals Table**: Key metrics and ratios
- **News Correlation**: Articles linked to this company
- **Pattern Detection**: Detected chart patterns
- **Anomaly Alerts**: Recent anomalies
- **Historical Comparison**: Compare with sector/industry peers

#### 3. Correlation Explorer
- **Temporal View**: Timeline of articles and price movements
- **Sentiment Analysis**: Article sentiment vs. price direction
- **Keyword Cloud**: Most common terms in correlated articles
- **Event Timeline**: Major events and their impact

#### 4. Advanced Analysis
- **Custom Queries**: Build complex financial queries
- **Pattern Scanner**: Scan for specific patterns across all companies
- **Anomaly Detector**: Find unusual activity
- **Portfolio Tracker**: Track custom portfolios
- **Watchlists**: Save and monitor company groups

### GUI Technical Requirements

```javascript
// Example React component structure
class FinancialDashboard extends React.Component {
  state = {
    selectedExchange: 'NYSE',
    selectedCompany: null,
    timePeriod: '1M',
    viewMode: 'chart', // 'chart', 'table', 'correlations'
  }
  
  render() {
    return (
      <div className="financial-dashboard">
        <ExchangeSelector />
        <CompanySearch />
        <TimePeriodSelector />
        <ViewModeTabs />
        
        {this.state.viewMode === 'chart' && <PriceChart />}
        {this.state.viewMode === 'table' && <DataTable />}
        {this.state.viewMode === 'correlations' && <CorrelationView />}
        
        <NewsSidebar />
        <AnalysisPanel />
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
  # Exchange discovery
  exchange_discovery:
    frequency: weekly
    day: monday
    time: "00:00"
    
  # Company list updates
  company_updates:
    frequency: daily
    time: "01:00"
    priority_exchanges: ["NYSE", "NASDAQ", "LSE", "TSE"]
    
  # OHLC data updates
  ohlc_updates:
    frequency: daily
    time: "02:00"
    lookback_days: 1
    
  # Historical data backfill
  historical_backfill:
    frequency: weekly
    day: sunday
    time: "03:00"
    lookback_days: 30
    
  # Fundamentals updates
  fundamentals_updates:
    frequency: weekly
    day: saturday
    time: "04:00"
    
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
    
    def scrape_company(self, company_id: str) -> None:
        """Scrape all data for a specific company."""
        
    def scrape_exchange(self, exchange_id: str) -> None:
        """Scrape all companies on an exchange."""
        
    def refresh_all(self) -> None:
        """Refresh all financial data."""
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
This financial data is provided for informational and journalistic purposes only.
It is not intended for trading, investment advice, or financial decision-making.
Users should verify data from official sources before making any decisions.
Open Omniscience is not responsible for the accuracy or completeness of this data.
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
- [ ] Set up Pillar 5 directory structure
- [ ] Create database models
- [ ] Implement exchange discovery
- [ ] Implement basic company discovery
- [ ] Set up storage engine
- [ ] Create basic API endpoints

### Phase 2: Core Scraping (Week 3-4)
- [ ] Implement OHLC scraper for major exchanges
- [ ] Implement fundamentals scraper
- [ ] Add rate limiting and retry logic
- [ ] Implement robots.txt compliance
- [ ] Set up scheduling system

### Phase 3: Analysis Engine (Week 5-6)
- [ ] Implement fluctuation detection
- [ ] Implement pattern recognition
- [ ] Implement anomaly detection
- [ ] Implement normalization engine
- [ ] Implement aggregation engine

### Phase 4: Correlation Engine (Week 7-8)
- [ ] Implement temporal correlation
- [ ] Implement sentiment correlation
- [ ] Implement keyword correlation
- [ ] Implement statistical correlation
- [ ] Create article-finance linking

### Phase 5: GUI Integration (Week 9-10)
- [ ] Design dashboard components
- [ ] Implement financial overview dashboard
- [ ] Implement company deep dive
- [ ] Implement correlation explorer
- [ ] Implement advanced analysis tools

### Phase 6: Testing & Optimization (Week 11-12)
- [ ] Write comprehensive tests
- [ ] Optimize scraping performance
- [ ] Optimize database queries
- [ ] Implement caching strategies
- [ ] Performance testing

### Phase 7: Documentation & Deployment (Week 13)
- [ ] Write user documentation
- [ ] Write developer documentation
- [ ] Create examples and tutorials
- [ ] Final integration testing
- [ ] Deployment preparation

---

## 📊 Success Metrics

### Coverage Metrics
- **Exchange Coverage**: 50+ exchanges worldwide
- **Company Coverage**: 10,000+ companies
- **Data Coverage**: 90% of companies with OHLC data
- **Fundamentals Coverage**: 70% of companies with fundamentals

### Performance Metrics
- **Scraping Speed**: 100 companies/hour
- **Data Freshness**: < 24 hours for major exchanges
- **Query Performance**: < 100ms for common queries
- **Uptime**: 99.9% for scheduled scraping

### Quality Metrics
- **Data Accuracy**: > 95% match with official sources
- **Test Coverage**: > 80% code coverage
- **User Satisfaction**: > 4.5/5 in user surveys

---

## 📚 File Structure

```
pillar5/
├── README.md                          # Pillar 5 overview
├── PILLAR5_TECHNICAL_SPECIFICATION.md # This document
├── IMPLEMENTATION_PLAN.md             # Detailed implementation plan
│
├── src/
│   ├── __init__.py
│   │
│   ├── scraping/
│   │   ├── __init__.py
│   │   ├── exchange_discovery.py
│   │   ├── company_discovery.py
│   │   ├── ohlc_scraper.py
│   │   ├── fundamentals_scraper.py
│   │   ├── scheduler.py
│   │   ├── rate_limiter.py
│   │   └── robots_txt.py
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── fluctuation_detector.py
│   │   ├── pattern_recognizer.py
│   │   ├── anomaly_detector.py
│   │   ├── correlation_engine.py
│   │   ├── normalization_engine.py
│   │   └── technical_indicators.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── time_series_storage.py
│   │   ├── aggregation_engine.py
│   │   └── retention_manager.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── exchange.py
│   │   ├── company.py
│   │   ├── financial_data.py
│   │   ├── fundamentals.py
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
│   └── exchanges.yaml
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
