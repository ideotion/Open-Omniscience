# Pillar 5: Global Financial Intelligence - Updated Technical Specification

**Open Omniscience - Financial Data Analysis & Stock Fluctuation Intelligence**

**Version:** 2.0.0  
**Date:** 2026  
**Author:** Ideotion  
**Status:** Design Phase (Updated)  

---

## 📋 Executive Summary

This document **updates** the technical specification for Pillar 5 to implement a **comprehensive global financial intelligence system** that:

1. **Unifies all asset classes** (stocks, ETFs, indices, commodities, forex, crypto) in a single `financial_instruments` table with a `type` field.
2. **Scrapes sector classifications** and extracts **keywords** from company names, descriptions, and article text for hybrid linking.
3. **Pre-computes a comprehensive catalog of metrics** (grouped by theme) with definitions, formulas, and use cases, stored separately with full audit trails.
4. **Maintains backward compatibility** with existing Pillar 5 models while extending functionality.
5. **Keeps Pillar 5’s models separate** but in the **same central database** as articles.

**Key Principles:**
- **No APIs/authentication**: All data scraped from open web sources.
- **Ethical scraping**: Respects `robots.txt`, rate limits, and user-agent identification.
- **Centralized storage**: Financial data and articles share the same database.
- **Raw + processed separation**: Raw scraped data is immutable; processed/analyzed data is stored separately with source metadata.
- **Visualization-ready**: Pre-computed metrics are grouped by theme and designed for easy visualization.

---

## 🎯 Updated Objectives

### Primary Goals
1. **Unified Asset Coverage**: Support stocks, ETFs, indices, commodities, forex, and crypto in a single system.
2. **Comprehensive Data**: OHLC, fundamentals, and metadata for all instrument types.
3. **Smart Linking**: Hybrid correlation engine (temporal + keyword + sector + manual).
4. **Pre-Computed Metrics**: 50+ metrics grouped by theme (trend, momentum, volatility, volume, fundamental) with definitions and use cases.
5. **Centralized Storage**: All data in the same database as articles, with clear separation between raw and processed data.

### Secondary Goals
1. **Extensible Architecture**: Easy to add new asset classes, metrics, or data sources.
2. **User Customization**: Allow users to enable/disable metrics, adjust scraping priorities, and tweak rate limits.
3. **Visual Exploration**: Group metrics by theme for intuitive exploration in the GUI.
4. **Audit Trails**: Every pre-computed metric includes source, calculation method, and timestamp.

---

## 🏗️ Updated System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PILLAR 5: GLOBAL FINANCIAL INTELLIGENCE (v2.0)               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   SCRAPING      │    │   ANALYSIS       │    │    STORAGE       │       │
│  │   ENGINE        │    │   ENGINE        │    │    ENGINE        │       │
│  │                 │    │                 │    │                 │       │
│  │ • Exchange      │    │ • Fluctuation   │    │ • Time-Series   │       │
│  │   Discovery     │    │   Detection     │    │   Database      │       │
│  │ • Instrument    │    │ • Pattern       │    │ • Raw Data      │       │
│  │   Discovery     │    │   Recognition    │    │   Table         │       │
│  │ • OHLC Scraper  │    │ • Correlation   │    │ • Processed     │       │
│  │ • Fundamentals  │    │   Analysis      │    │   Data Table    │       │
│  │   Scraper       │    │ • Anomaly       │    │ • Metrics       │       │
│  │ • Sector/       │    │   Detection      │    │   Table         │       │
│  │   Keyword       │    │ • Metric        │    │ • Keywords      │       │
│  │   Extractor     │    │   Calculator    │    │   Table         │       │
│  │ • Scheduler     │    │                 │    │                 │       │
│  │ • Rate Limiter  │    │                 │    │                 │       │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘       │
│           │                    │                     │                    │
│           ▼                    ▼                     ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        CENTRAL DATABASE                              │   │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                  │   │
│  │  │   articles           │  │   financial_          │                  │   │
│  │  │   (existing)         │  │   instruments        │                  │   │
│  │  └─────────────────────┘  │   (unified)          │                  │   │
│  │  ┌─────────────────────┐  └──────────┬───────────┘                  │   │
│  │  │   financial_raw      │             │                              │   │
│  │  │   (OHLC time-series)│             ▼                              │   │
│  │  └─────────────────────┘  ┌─────────────────────────────────────┐  │   │
│  │                           │   financial_processed                 │  │   │
│  │                           │   (aggregated, normalized)             │  │   │
│  │                           └──────────────┬───────────────────────┘  │   │
│  │                                          │                           │   │
│  │                           ┌──────────────┴───────────────────────┐  │   │
│  │                           │   financial_metrics                    │  │   │
│  │                           │   (pre-computed, grouped by theme)     │  │   │
│  │                           └──────────────┬───────────────────────┘  │   │
│  │                                          │                           │   │
│  │                           ┌──────────────┴───────────────────────┐  │   │
│  │                           │   instrument_keywords                 │  │   │
│  │                           │   (NLP-extracted for linking)          │  │   │
│  │                           └──────────────┬───────────────────────┘  │   │
│  │                                          │                           │   │
│  │                           ┌──────────────┴───────────────────────┐  │   │
│  │                           │   article_financial_links             │  │   │
│  │                           │   (hybrid: temporal + keyword + sector)│  │   │
│  │                           └───────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐       │
│  │   API LAYER      │    │   CORRELATION    │    │   VISUALIZATION  │       │
│  │                 │    │   ENGINE         │    │   READY DATA     │       │
│  │ • REST Endpoints│    │                 │    │                 │       │
│  │ • Query Builder  │    │ • Temporal       │    │ • Themed Metrics │       │
│  │ • Cache Layer    │    │   Linking        │    │   (Trend, Momentum│       │
│  │                 │    │ • Keyword        │    │   Volatility, etc.)│       │
│  │                 │    │   Linking        │    │ • Time-Bucketed │       │
│  │                 │    │ • Sector         │    │ • Aggregated    │       │
│  │                 │    │   Linking        │    │                 │       │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Updated Data Model

### Core Entities (Updated)

#### 1. `FinancialInstrument` (Replaces `Company`)
**Purpose**: Unified table for all financial instruments (stocks, ETFs, indices, commodities, forex, crypto).

```python
@dataclass
class FinancialInstrument:
    """
    Unified model for all financial instruments.
    
    Attributes:
        id: Unique identifier (ISIN for stocks/ETFs, symbol for crypto/forex, or generated UUID)
        symbol: Trading symbol (e.g., "AAPL", "SPY", "BTC-USD", "EUR-USD", "XAU-USD")
        name: Full name (e.g., "Apple Inc.", "SPDR S&P 500 ETF", "Bitcoin")
        type: Instrument type (stock, etf, index, commodity, forex, crypto)
        exchange_id: Reference to exchange (if applicable; NULL for forex/crypto)
        sector: Industry sector (e.g., "Technology", "Energy"; NULL for non-stock types)
        industry: Specific industry (e.g., "Software", "Oil & Gas"; NULL for non-stock types)
        category: Sub-category (e.g., "Large Cap", "Small Cap", "Government Bond")
        base_currency: Base currency (e.g., "USD", "EUR")
        quote_currency: Quote currency (for forex/crypto; e.g., "USD" in "EUR-USD")
        description: Business/asset description
        founded_year: Year founded (for companies; NULL otherwise)
        headquarters: Headquarters location (for companies; NULL otherwise)
        website: Official website URL
        is_active: Whether the instrument is currently tradable
        last_updated: Last data update timestamp
        metadata: Additional instrument-specific info (e.g., contract size for commodities)
        created_at: When the instrument was added to the system
        updated_at: When the instrument was last updated
    """
    id: str
    symbol: str
    name: str
    type: str  # "stock", "etf", "index", "commodity", "forex", "crypto"
    exchange_id: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    category: Optional[str] = None
    base_currency: str = "USD"
    quote_currency: Optional[str] = None  # For forex/crypto pairs
    description: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    website: Optional[str] = None
    is_active: bool = True
    last_updated: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLAlchemy Model:**
```python
class FinancialInstrument(Base):
    __tablename__ = 'financial_instruments'
    
    id = Column(String(50), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False, index=True)  # stock, etf, index, commodity, forex, crypto
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    sector = Column(String(100), index=True)
    industry = Column(String(100), index=True)
    category = Column(String(100))
    base_currency = Column(String(3), default="USD")
    quote_currency = Column(String(3))  # For forex/crypto
    description = Column(Text)
    founded_year = Column(Integer)
    headquarters = Column(String(255))
    website = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime)
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_instrument_symbol_type', 'symbol', 'type', unique=True),
        Index('idx_instrument_type', 'type'),
        Index('idx_instrument_sector', 'sector'),
        Index('idx_instrument_industry', 'industry'),
        Index('idx_instrument_exchange', 'exchange_id'),
    )
```

---

#### 2. `FinancialDataPoint` (Updated)
**Purpose**: OHLC time-series data for all instrument types. **No changes needed** (already supports all instruments via `company_id` → `instrument_id`).

**Update:** Rename `company_id` to `instrument_id` in the model and all references.

```python
class FinancialDataPoint(Base):
    __tablename__ = 'financial_data_points'
    
    id = Column(String(36), primary_key=True)  # UUID
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)  # Updated
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(Float)  # Use Float for crypto/forex volumes
    currency = Column(String(3), default="USD")
    is_dividend_adjusted = Column(Boolean, default=False)
    data_source = Column(String(100))  # e.g., "yahoo_finance", "investing_com"
    metadata = Column(JSON)  # e.g., {"split_factor": 2.0, "dividend": 0.5}
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_data_point_instrument', 'instrument_id'),
        Index('idx_data_point_timestamp', 'timestamp'),
        Index('idx_data_point_instrument_timestamp', 'instrument_id', 'timestamp'),
    )
```

---

#### 3. `CompanyFundamentals` (Renamed to `InstrumentFundamentals`)
**Purpose**: Fundamentals for stocks/ETFs (P/E, market cap, etc.). **Extended to support all instrument types** where applicable.

```python
@dataclass
class InstrumentFundamentals:
    """
    Fundamentals for financial instruments (primarily stocks/ETFs).
    
    Attributes:
        id: UUID
        instrument_id: Reference to instrument
        date: Reporting date
        fiscal_period: Fiscal period (Q1, Annual, TTM)
        
        # Valuation (stocks/ETFs)
        market_cap: Market capitalization
        pe_ratio: Price-to-Earnings ratio
        peg_ratio: PE-to-Growth ratio
        pb_ratio: Price-to-Book ratio
        ps_ratio: Price-to-Sales ratio
        
        # Profitability (stocks/ETFs)
        eps: Earnings per share
        revenue: Revenue
        net_income: Net income
        profit_margin: Profit margin (decimal)
        
        # Dividends (stocks/ETFs)
        dividend_yield: Dividend yield (decimal)
        
        # Risk (stocks/ETFs)
        beta: Beta coefficient
        debt_to_equity: Debt-to-equity ratio
        current_ratio: Current ratio
        roe: Return on equity (decimal)
        roa: Return on assets (decimal)
        
        # Commodity-specific
        contract_size: Contract size (e.g., 100 troy oz for gold)
        tick_size: Minimum price movement
        
        # Crypto-specific
        max_supply: Maximum supply (for crypto)
        circulating_supply: Circulating supply
        
        # Metadata
        currency: Currency of values
        source: Data source
        created_at: When record was added
    """
    id: str
    instrument_id: str
    date: datetime
    fiscal_period: str = "TTM"
    
    # Valuation
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    
    # Profitability
    eps: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    profit_margin: Optional[float] = None
    
    # Dividends
    dividend_yield: Optional[float] = None
    
    # Risk
    beta: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    
    # Commodity-specific
    contract_size: Optional[float] = None
    tick_size: Optional[float] = None
    
    # Crypto-specific
    max_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    
    # Metadata
    currency: str = "USD"
    source: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```

---

#### 4. `FinancialMetric` (New)
**Purpose**: Pre-computed metrics for all instruments, stored separately with full audit trails.

```python
@dataclass
class FinancialMetric:
    """
    Pre-computed metric for a financial instrument.
    
    Attributes:
        id: UUID
        instrument_id: Reference to instrument
        metric_name: Name of the metric (e.g., "sma_20", "rsi_14")
        metric_group: Theme/group (e.g., "Trend", "Momentum", "Volatility")
        metric_value: Computed value
        timeframe: Timeframe for calculation (e.g., "1D", "1W", "1M")
        timestamp: Timestamp of the data point this metric is for
        calculation_method: Formula/method used (e.g., "Simple Moving Average")
        parameters: Parameters used (e.g., {"period": 20} for SMA(20))
        source: Source of the underlying data (e.g., "yahoo_finance")
        is_real_time: Whether this is a real-time or historical metric
        confidence: Confidence score (0-1) for the calculation
        created_at: When this metric was computed
        updated_at: When this metric was last updated
    """
    id: str
    instrument_id: str
    metric_name: str  # e.g., "sma_20", "rsi_14"
    metric_group: str  # e.g., "Trend", "Momentum", "Volatility", "Volume", "Fundamental"
    metric_value: float
    timeframe: str = "1D"  # 1D, 1W, 1M, 3M, 1Y, etc.
    timestamp: datetime
    calculation_method: str  # e.g., "Simple Moving Average"
    parameters: Dict[str, Any] = field(default_factory=dict)  # e.g., {"period": 20}
    source: Optional[str] = None
    is_real_time: bool = False
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLAlchemy Model:**
```python
class FinancialMetric(Base):
    __tablename__ = 'financial_metrics'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    metric_name = Column(String(50), nullable=False)
    metric_group = Column(String(50), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    timeframe = Column(String(10), default="1D", index=True)
    timestamp = Column(DateTime, nullable=False)
    calculation_method = Column(String(255), nullable=False)
    parameters = Column(JSON, default={})
    source = Column(String(100))
    is_real_time = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_metric_instrument', 'instrument_id'),
        Index('idx_metric_name', 'metric_name'),
        Index('idx_metric_group', 'metric_group'),
        Index('idx_metric_timestamp', 'timestamp'),
        Index('idx_metric_instrument_group', 'instrument_id', 'metric_group'),
    )
```

---

#### 5. `InstrumentKeyword` (New)
**Purpose**: NLP-extracted keywords for instruments, used for hybrid linking with articles.

```python
@dataclass
class InstrumentKeyword:
    """
    Keyword extracted from an instrument's name, description, or related text.
    
    Attributes:
        id: UUID
        instrument_id: Reference to instrument
        keyword: The extracted keyword (normalized, lowercase)
        source: Source of the keyword (e.g., "name", "description", "article")
        weight: Importance weight (0-1)
        language: Language of the keyword (e.g., "en")
        created_at: When the keyword was extracted
    """
    id: str
    instrument_id: str
    keyword: str
    source: str = "name"  # "name", "description", "article", "sector"
    weight: float = 1.0
    language: str = "en"
    created_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLAlchemy Model:**
```python
class InstrumentKeyword(Base):
    __tablename__ = 'instrument_keywords'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    keyword = Column(String(100), nullable=False, index=True)
    source = Column(String(20), default="name")
    weight = Column(Float, default=1.0)
    language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_keyword_instrument', 'instrument_id'),
        Index('idx_keyword_keyword', 'keyword'),
    )
```

---

#### 6. `ArticleFinancialLink` (Updated)
**Purpose**: Links articles to financial instruments with hybrid correlation (temporal + keyword + sector).

**Updates:**
- Add `sector` and `keyword` correlation types.
- Add `matched_keywords` field to store which keywords triggered the link.

```python
@dataclass
class ArticleFinancialLink:
    """
    Link between an article and a financial instrument.
    
    Attributes:
        id: UUID
        article_id: Reference to article
        instrument_id: Reference to instrument (replaces company_id)
        exchange_id: Reference to exchange (optional)
        
        # Correlation metadata
        correlation_score: Strength of correlation (0-1)
        correlation_type: Type (mention, event, sentiment, temporal, sector, keyword)
        time_diff_hours: Hours between article and financial event
        direction: Temporal direction (before, after, same_time)
        
        # Keyword matching (new)
        matched_keywords: List of keywords that matched
        matched_sector: Sector that matched (if correlation_type is "sector")
        
        # Sentiment analysis
        article_sentiment: Sentiment score from article (-1 to 1)
        financial_sentiment: Sentiment inferred from financial data (-1 to 1)
        
        # Analysis
        is_significant: Whether correlation is statistically significant
        confidence: Confidence in correlation (0-1)
        
        # Metadata
        created_at: When link was created
        updated_at: When link was last updated
    """
    id: str
    article_id: str
    instrument_id: Optional[str] = None  # Replaces company_id
    exchange_id: Optional[str] = None
    
    # Correlation metadata
    correlation_score: float = 0.0
    correlation_type: str = "mention"  # mention, event, sentiment, temporal, sector, keyword
    time_diff_hours: Optional[float] = None
    direction: str = "same_time"
    
    # Keyword matching (new)
    matched_keywords: List[str] = field(default_factory=list)
    matched_sector: Optional[str] = None
    
    # Sentiment analysis
    article_sentiment: Optional[float] = None
    financial_sentiment: Optional[float] = None
    
    # Analysis
    is_significant: bool = False
    confidence: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLAlchemy Model:**
```python
class ArticleFinancialLink(Base):
    __tablename__ = 'article_financial_links'
    
    id = Column(String(36), primary_key=True)
    article_id = Column(String(36), ForeignKey('articles.id'), nullable=False)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'))  # Updated
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    
    # Correlation metadata
    correlation_score = Column(Float, default=0.0)
    correlation_type = Column(String(20), default="mention")
    time_diff_hours = Column(Float)
    direction = Column(String(20), default="same_time")
    
    # Keyword matching (new)
    matched_keywords = Column(JSON, default=[])
    matched_sector = Column(String(100))
    
    # Sentiment analysis
    article_sentiment = Column(Float)
    financial_sentiment = Column(Float)
    
    # Analysis
    is_significant = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_link_article', 'article_id'),
        Index('idx_link_instrument', 'instrument_id'),
        Index('idx_link_correlation_type', 'correlation_type'),
        Index('idx_link_score', 'correlation_score'),
    )
```

---

## 📈 Pre-Computed Metrics Catalog

This section defines **50+ pre-computed metrics** grouped by theme, with:
- **Definition**: What the metric measures.
- **Formula**: How it’s calculated.
- **Use Case**: Why it’s useful for analysis.
- **Visualization**: Recommended chart type.
- **Parameters**: Configurable inputs (e.g., period for SMA).

---

### 📌 Metric Groups

| Group | Description | Example Metrics |
|-------|-------------|-----------------|
| **Trend** | Identify direction and strength of price movements | SMA, EMA, MACD, Bollinger Bands |
| **Momentum** | Measure speed of price changes | RSI, Stochastic Oscillator, ROC |
| **Volatility** | Measure price variability | ATR, Standard Deviation, Beta |
| **Volume** | Analyze trading activity | OBV, Volume Spike, Chaikin Money Flow |
| **Fundamental** | Company health metrics | P/E, P/B, Dividend Yield, ROE |
| **Statistical** | Statistical properties | Z-Score, Percentile, Correlation |
| **Pattern** | Chart patterns | Head & Shoulders, Double Top, Support/Resistance |

---

### 🔹 Group 1: Trend Metrics
**Purpose**: Identify the direction and strength of price trends.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **SMA (Simple Moving Average)** | Smooths price data to identify trends | `SMA = (P1 + P2 + ... + Pn) / n` | Identify trend direction, support/resistance | Line chart (overlaid on price) | `period` (e.g., 20, 50, 200) |
| **EMA (Exponential Moving Average)** | Weighted moving average (recent prices matter more) | `EMA = (P * k) + (EMA_prev * (1 - k))` where `k = 2/(n+1)` | Faster reaction to price changes than SMA | Line chart | `period` (e.g., 12, 26) |
| **MACD (Moving Average Convergence Divergence)** | Trend-following momentum indicator | `MACD = EMA(12) - EMA(26)`, `Signal = EMA(9) of MACD`, `Histogram = MACD - Signal` | Identify trend reversals, momentum shifts | Histogram + Line chart | `fast_period=12`, `slow_period=26`, `signal_period=9` |
| **Bollinger Bands** | Volatility bands around a moving average | `Upper = SMA + (k * σ)`, `Lower = SMA - (k * σ)` where `σ` = standard deviation | Identify overbought/oversold conditions | Band chart | `period=20`, `k=2` |
| **ADX (Average Directional Index)** | Measures trend strength (not direction) | `ADX = 100 * SMA(|+DI - -DI| / (+DI + -DI))` | Determine if a trend is strong or weak | Line chart | `period=14` |
| **Ichimoku Cloud** | Comprehensive trend indicator | `Conversion Line = (9P High + 9P Low)/2`, `Base Line = (26P High + 26P Low)/2`, `Cloud = Span A/B` | Identify support/resistance, trend direction | Cloud chart | `conversion_period=9`, `base_period=26`, `lagging_span=52` |
| **Parabolic SAR** | Time/price-based trailing stop | `SAR = Prior SAR + AF * (EP - Prior SAR)` where `AF` = acceleration factor | Identify potential reversals | Dots on price chart | `af_start=0.02`, `af_increment=0.02`, `af_max=0.2` |

---

### 🔹 Group 2: Momentum Metrics
**Purpose**: Measure the speed of price changes to identify overbought/oversold conditions.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **RSI (Relative Strength Index)** | Measures speed and change of price movements | `RSI = 100 - (100 / (1 + RS))` where `RS = Avg Gain / Avg Loss` | Identify overbought (>70) or oversold (<30) conditions | Line chart (0-100 scale) | `period=14` |
| **Stochastic Oscillator** | Compares closing price to price range | `%K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100`, `%D = SMA(%K)` | Identify overbought/oversold conditions | Line chart (0-100 scale) | `k_period=14`, `d_period=3`, `smooth_k=3` |
| **ROC (Rate of Change)** | Percentage change in price over a period | `ROC = (Current Price - Price n periods ago) / Price n periods ago * 100` | Measure momentum, identify divergences | Line chart | `period=12` |
| **CCI (Commodity Channel Index)** | Measures deviation from statistical mean | `CCI = (Typical Price - SMA) / (0.015 * Mean Deviation)` | Identify overbought/oversold conditions | Line chart | `period=20` |
| **Williams %R** | Momentum oscillator | `%R = (Highest High - Close) / (Highest High - Lowest Low) * -100` | Identify overbought/oversold conditions | Line chart (-100 to 0) | `period=14` |
| **Awesome Oscillator** | Measures market momentum | `AO = SMA(Median Price, 5) - SMA(Median Price, 34)` | Confirm trends, identify reversals | Histogram | `fast_period=5`, `slow_period=34` |

---

### 🔹 Group 3: Volatility Metrics
**Purpose**: Measure price variability to assess risk.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **ATR (Average True Range)** | Measures market volatility | `ATR = SMA(True Range)` where `True Range = max(High-Low, |High-Prev Close|, |Low-Prev Close|)` | Assess risk, set stop-loss levels | Line chart | `period=14` |
| **Standard Deviation** | Measures price dispersion | `σ = sqrt(Σ(Pi - μ)² / n)` where `μ` = mean price | Measure volatility, risk assessment | Line chart | `period=20` |
| **Beta** | Measures volatility relative to a benchmark | `β = Cov(Ri, Rm) / Var(Rm)` where `Ri` = instrument returns, `Rm` = market returns | Assess risk relative to market | Single value | `benchmark` (e.g., S&P 500) |
| **Historical Volatility** | Annualized standard deviation of returns | `HV = σ * sqrt(252)` (for daily data) | Measure long-term volatility | Line chart | `period=30`, `annualize=True` |
| **Donchian Channels** | Price range over a period | `Upper = Highest High (n)`, `Lower = Lowest Low (n)` | Identify breakouts, volatility | Band chart | `period=20` |
| **Keltner Channels** | Volatility-based bands | `Middle = EMA`, `Upper = EMA + (ATR * k)`, `Lower = EMA - (ATR * k)` | Identify overbought/oversold conditions | Band chart | `ema_period=20`, `atr_period=10`, `k=2` |

---

### 🔹 Group 4: Volume Metrics
**Purpose**: Analyze trading activity to confirm trends.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **OBV (On-Balance Volume)** | Cumulative volume based on price changes | `OBV = OBV_prev + Volume` (if Close > Close_prev) or `OBV = OBV_prev - Volume` (if Close < Close_prev) | Confirm trends, identify divergences | Line chart | None |
| **Volume Spike** | Unusual volume compared to average | `Spike = Volume / SMA(Volume, n)` | Identify unusual trading activity | Bar chart | `period=20`, `threshold=2.0` |
| **Chaikin Money Flow** | Measures money flow volume | `CMF = (Money Flow Multiplier * Volume) / Total Volume` where `Money Flow Multiplier = (Close - Low) - (High - Close) / (High - Low)` | Identify buying/selling pressure | Line chart | `period=20` |
| **Volume Weighted Average Price (VWAP)** | Average price weighted by volume | `VWAP = Σ(Price * Volume) / Σ(Volume)` | Identify fair value, institutional activity | Line chart | None |
| **Accumulation/Distribution Line** | Cumulative volume flow | `A/D = A/D_prev + ((Close - Low) - (High - Close)) / (High - Low) * Volume` | Identify accumulation/distribution | Line chart | None |
| **Money Flow Index (MFI)** | Measures money flow in/out of an asset | `MFI = 100 - (100 / (1 + MR))` where `MR = Positive Money Flow / Negative Money Flow` | Identify overbought/oversold conditions | Line chart (0-100) | `period=14` |

---

### 🔹 Group 5: Fundamental Metrics
**Purpose**: Assess company health (primarily for stocks/ETFs).

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **P/E Ratio (Trailing)** | Price relative to earnings | `P/E = Price / EPS` | Assess valuation | Bar chart (vs. peers) | None |
| **P/E Ratio (Forward)** | Price relative to projected earnings | `P/E = Price / Forward EPS` | Assess future valuation | Bar chart | None |
| **P/B Ratio** | Price relative to book value | `P/B = Price / Book Value per Share` | Assess valuation vs. assets | Bar chart | None |
| **P/S Ratio** | Price relative to revenue | `P/S = Price / Revenue per Share` | Assess valuation vs. sales | Bar chart | None |
| **Dividend Yield** | Annual dividend relative to price | `Yield = Annual Dividend / Price * 100` | Assess income potential | Bar chart | None |
| **ROE (Return on Equity)** | Profitability relative to equity | `ROE = Net Income / Shareholders' Equity` | Assess profitability efficiency | Bar chart | None |
| **ROA (Return on Assets)** | Profitability relative to assets | `ROA = Net Income / Total Assets` | Assess asset efficiency | Bar chart | None |
| **Debt-to-Equity** | Leverage ratio | `D/E = Total Debt / Shareholders' Equity` | Assess financial risk | Bar chart | None |
| **Current Ratio** | Liquidity ratio | `Current Ratio = Current Assets / Current Liabilities` | Assess short-term solvency | Bar chart | None |
| **Profit Margin** | Profitability per dollar of revenue | `Margin = Net Income / Revenue * 100` | Assess profitability | Bar chart | None |

---

### 🔹 Group 6: Statistical Metrics
**Purpose**: Statistical properties of price data.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **Z-Score** | Standard deviations from mean | `Z = (X - μ) / σ` | Identify outliers | Scatter plot | `period=20` |
| **Percentile Rank** | Percentage of values below a given value | `Percentile = (Number of Values Below X / Total Values) * 100` | Assess relative performance | Line chart | `period=100` |
| **Sharpe Ratio** | Risk-adjusted return | `Sharpe = (Rp - Rf) / σp` where `Rp` = portfolio return, `Rf` = risk-free rate | Assess risk-adjusted performance | Bar chart | `risk_free_rate=0.02` |
| **Sortino Ratio** | Risk-adjusted return (downside deviation) | `Sortino = (Rp - Rf) / σd` where `σd` = downside deviation | Assess risk-adjusted performance (focus on downside) | Bar chart | `risk_free_rate=0.02` |
| **Correlation** | Relationship between two instruments | `Corr(X,Y) = Cov(X,Y) / (σX * σY)` | Identify related instruments | Heatmap | `pair` (e.g., "AAPL,MSFT") |
| **Beta (vs. Benchmark)** | Volatility relative to benchmark | `β = Cov(Ri, Rm) / Var(Rm)` | Assess market risk | Single value | `benchmark` (e.g., "SPY") |

---

### 🔹 Group 7: Pattern Metrics
**Purpose**: Detect chart patterns for technical analysis.

| Metric | Definition | Detection Method | Use Case | Visualization | Parameters |
|--------|------------|-------------------|----------|---------------|-------------|
| **Head & Shoulders** | Reversal pattern with 3 peaks | Identify higher high (head) between two lower highs (shoulders) | Predict bearish reversal | Price chart overlay | `lookback=50` |
| **Double Top** | Reversal pattern with 2 peaks | Identify two peaks at similar price level | Predict bearish reversal | Price chart overlay | `lookback=30`, `tolerance=2%` |
| **Double Bottom** | Reversal pattern with 2 troughs | Identify two troughs at similar price level | Predict bullish reversal | Price chart overlay | `lookback=30`, `tolerance=2%` |
| **Triple Top** | Reversal pattern with 3 peaks | Identify three peaks at similar price level | Predict bearish reversal | Price chart overlay | `lookback=40`, `tolerance=2%` |
| **Triple Bottom** | Reversal pattern with 3 troughs | Identify three troughs at similar price level | Predict bullish reversal | Price chart overlay | `lookback=40`, `tolerance=2%` |
| **Support Level** | Price level where buying interest emerges | Identify price bounces at a specific level | Identify entry points | Horizontal line | `lookback=50`, `tolerance=1%` |
| **Resistance Level** | Price level where selling interest emerges | Identify price rejections at a specific level | Identify exit points | Horizontal line | `lookback=50`, `tolerance=1%` |
| **Trendline** | Line connecting price extremes | Linear regression or manual drawing | Identify trend direction | Line overlay | `min_points=2` |

---

### 🔹 Group 8: Custom/Composite Metrics
**Purpose**: User-defined or composite metrics.

| Metric | Definition | Formula | Use Case | Visualization | Parameters |
|--------|------------|---------|----------|---------------|-------------|
| **Golden Cross** | Bullish signal (short-term MA crosses above long-term MA) | `SMA(50) > SMA(200)` | Predict bullish trend | Price chart overlay | `short_period=50`, `long_period=200` |
| **Death Cross** | Bearish signal (short-term MA crosses below long-term MA) | `SMA(50) < SMA(200)` | Predict bearish trend | Price chart overlay | `short_period=50`, `long_period=200` |
| **Bullish Engulfing** | Reversal pattern (small bearish candle followed by large bullish candle) | `Close > Open` and `Close > Prior Open` and `Open < Prior Close` | Predict bullish reversal | Candlestick chart | None |
| **Bearish Engulfing** | Reversal pattern (small bullish candle followed by large bearish candle) | `Close < Open` and `Close < Prior Open` and `Open > Prior Close` | Predict bearish reversal | Candlestick chart | None |
| **Hammer** | Reversal pattern (small body, long lower wick) | `Body < Wick` and `Close > Open` | Predict bullish reversal | Candlestick chart | `body_ratio=0.3` |
| **Shooting Star** | Reversal pattern (small body, long upper wick) | `Body < Wick` and `Close < Open` | Predict bearish reversal | Candlestick chart | `body_ratio=0.3` |

---

## 🗃️ Database Schema Summary

### Tables Overview

| Table | Purpose | Key Fields | Relationships |
|-------|---------|------------|---------------|
| `financial_exchanges` | Exchange metadata | `id`, `name`, `country`, `currency`, `timezone` | One-to-many with `financial_instruments` |
| `financial_instruments` | Unified instrument data | `id`, `symbol`, `name`, `type`, `sector`, `industry` | One-to-many with `financial_data_points`, `financial_metrics`, `instrument_keywords` |
| `financial_data_points` | OHLC time-series | `id`, `instrument_id`, `timestamp`, `open`, `high`, `low`, `close`, `volume` | Many-to-one with `financial_instruments` |
| `instrument_fundamentals` | Fundamentals (P/E, market cap, etc.) | `id`, `instrument_id`, `date`, `pe_ratio`, `market_cap` | Many-to-one with `financial_instruments` |
| `financial_metrics` | Pre-computed metrics | `id`, `instrument_id`, `metric_name`, `metric_group`, `metric_value`, `timestamp`, `calculation_method` | Many-to-one with `financial_instruments` |
| `instrument_keywords` | NLP-extracted keywords | `id`, `instrument_id`, `keyword`, `source`, `weight` | Many-to-one with `financial_instruments` |
| `article_financial_links` | Article-instrument links | `id`, `article_id`, `instrument_id`, `correlation_type`, `matched_keywords`, `matched_sector` | Many-to-one with `articles` and `financial_instruments` |

---

## 🌐 Scraping Strategy

### Asset Class Coverage

| Asset Class | Priority | Target Sources | Data Types | Notes |
|-------------|----------|----------------|------------|-------|
| **Stocks** | 1 | Yahoo Finance, Google Finance, Investing.com, Exchange websites | OHLC, Fundamentals, Sector/Industry | Focus on Tier 1 exchanges first |
| **ETFs** | 1 | Yahoo Finance, ETF.com, Morningstar, Exchange websites | OHLC, Fundamentals, Holdings | Scrape top ETFs by AUM |
| **Indices** | 1 | Yahoo Finance, Investing.com, Exchange websites | OHLC, Components | S&P 500, NASDAQ, Dow Jones, etc. |
| **Commodities** | 2 | Investing.com, Kitco, LME, CME Group | OHLC, Contract Specs | Gold, Silver, Oil, etc. |
| **Forex** | 2 | OANDA, XE, Investing.com, Central Bank websites | OHLC, Cross Rates | Major pairs (EUR/USD, USD/JPY, etc.) |
| **Crypto** | 2 | CoinMarketCap, CoinGecko, Binance (public pages) | OHLC, Market Cap, Supply | Bitcoin, Ethereum, etc. |

---

### Scraping Workflow

1. **Discovery Phase** (Daily):
   - Scrape **exchange lists** (Wikipedia, WFE) to discover new exchanges.
   - Scrape **instrument lists** from each exchange (e.g., NASDAQ’s listed companies).
   - Classify instruments by `type` (stock, ETF, etc.) and populate `financial_instruments`.
   - Scrape **sector/industry** classifications from Yahoo Finance or exchange websites.

2. **OHLC Data Scraping** (Daily + On-Demand):
   - For each instrument, scrape **historical OHLC** from public sources (Yahoo Finance, Google Finance, Investing.com).
   - **Incremental updates**: Only fetch new data since the last scrape.
   - **Fallback logic**: If one source fails, try another.
   - **Normalization**: Convert all prices to a base currency (configurable) and adjust for splits/dividends.

3. **Fundamentals Scraping** (Weekly):
   - Scrape **key statistics** (P/E, market cap, etc.) from Yahoo Finance, Google Finance, or Morningstar.
   - Store in `instrument_fundamentals` with `date` and `source`.

4. **Keyword Extraction** (On Ingestion):
   - For each instrument, extract keywords from:
     - **Name** (e.g., "Apple Inc." → ["apple", "inc"]).
     - **Description** (e.g., "Tesla designs electric vehicles" → ["tesla", "electric", "vehicles"]).
     - **Sector/Industry** (e.g., "Technology" → ["tech", "technology"]).
   - Use **NLP libraries** (spaCy, NLTK) for:
     - Tokenization.
     - Stopword removal.
     - Lemmatization (e.g., "designing" → "design").
     - Noun phrase extraction.
   - Store in `instrument_keywords` with `source` and `weight`.

5. **Metric Calculation** (Scheduled):
   - Run **daily/weekly** to compute all metrics in the catalog.
   - Store results in `financial_metrics` with:
     - `metric_name`, `metric_group`, `metric_value`.
     - `calculation_method`, `parameters`, `source`.
   - **Incremental updates**: Only recompute metrics for new/updated data points.

---

### Rate Limiting and Ethics

- **Robots.txt Compliance**: Check `robots.txt` before scraping any domain. Respect `Disallow` directives.
- **Rate Limiting**:
  - Default: **1 request per 2 seconds per domain** (configurable).
  - User can override in `configs/scraping.yaml`.
  - **Exponential backoff** on failures (retry after 5s, 10s, 30s, etc.).
- **User-Agent**: Identify as `OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)`.
- **Caching**: Cache scraped pages for **24 hours** to avoid repeated requests.
- **Public Data Only**: Only scrape **publicly available** data (no paywalls, no authentication).
- **Respect Terms of Service**: Avoid domains that explicitly prohibit scraping (e.g., Bloomberg Terminal).

---

### Example Scraping Configuration (`configs/scraping.yaml`)

```yaml
# Global settings
user_agent: "OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)"
request_timeout: 30  # seconds
max_retries: 3
retry_delay: 5  # seconds (exponential backoff)

# Rate limiting (requests per minute per domain)
default_rate_limit: 30  # ~1 request every 2 seconds
rate_limits:
  yahoo.com: 60
  google.com: 60
  investing.com: 30
  coinmarketcap.com: 20
  kitco.com: 10

# Asset class priorities (1 = highest)
priorities:
  stock: 1
  etf: 1
  index: 1
  commodity: 2
  forex: 2
  crypto: 2

# Exchange tiers (1 = highest)
exchange_tiers:
  NYSE: 1
  NASDAQ: 1
  LSE: 1
  TSE: 1
  SSE: 1
  HKEX: 1
  Euronext: 1
  Deutsche Börse: 1
  TSX: 1
  ASX: 1
  BSE: 2
  NSE: 2
  # ... (50+ exchanges)

# Data sources (fallback order)
ohlc_sources:
  - yahoo_finance
  - google_finance
  - investing_com
  - exchange_website

fundamentals_sources:
  - yahoo_finance
  - google_finance
  - morningstar
  - marketwatch

# NLP settings
keyword_extraction:
  enabled: true
  min_keyword_length: 3
  max_keywords_per_instrument: 50
  stopwords_language: "en"
  use_lemmatization: true
  use_noun_phrases: true
```

---

## 🔍 Correlation Engine Updates

### Hybrid Linking Logic

The correlation engine will link articles to instruments using **4 methods**:

1. **Temporal Linking**:
   - Link articles published **±X hours** (configurable, default: 24h) of a **significant price move** (e.g., >5% change).
   - Calculate `time_diff_hours` and `direction` (before/after/same_time).
   - Score: Higher for closer temporal proximity.

2. **Keyword Linking**:
   - Extract keywords from **article text** (using same NLP pipeline as instruments).
   - Match against `instrument_keywords` table.
   - Score: Based on:
     - Number of matched keywords.
     - Weight of matched keywords.
     - Position in article (title > first paragraph > body).
   - Store matched keywords in `matched_keywords` field.

3. **Sector Linking**:
   - Extract **sector/industry** from article text (e.g., "tech", "automotive").
   - Match against `financial_instruments.sector` or `industry`.
   - Score: Higher for exact matches.
   - Store matched sector in `matched_sector` field.

4. **Mention Linking**:
   - Direct mention of **instrument name** or **symbol** in article.
   - Score: Highest for exact matches (e.g., "AAPL" or "Apple Inc.").

### Correlation Scoring

The final `correlation_score` (0-1) is computed as:

```
correlation_score = 
  (temporal_score * temporal_weight) +
  (keyword_score * keyword_weight) +
  (sector_score * sector_weight) +
  (mention_score * mention_weight)
```

Default weights (configurable):
- `mention_weight = 0.4` (highest priority)
- `keyword_weight = 0.3`
- `sector_weight = 0.2`
- `temporal_weight = 0.1`

### Example Workflow

1. **New Article Ingested**:
   - Extract keywords: ["tesla", "electric", "car", "elon musk", "stock"].
   - Extract sector: "Automotive".
   - Extract mentions: ["TSLA"].

2. **Link to Instruments**:
   - **Mention**: Direct match for `TSLA` → Tesla Inc. (`correlation_score += 0.4`).
   - **Keyword**: Matches for "tesla", "electric", "car" → Tesla Inc. (`correlation_score += 0.3`).
   - **Sector**: "Automotive" → All automotive stocks (`correlation_score += 0.2`).

3. **Temporal Check**:
   - If Tesla’s stock moved **10% today** and the article was published **1 hour ago**, add temporal score (`+0.1`).

4. **Final Score**:
   - Tesla Inc.: `0.4 (mention) + 0.3 (keyword) + 0.1 (temporal) = 0.8` → **Strong correlation**.
   - Ford (automotive sector): `0.2 (sector) = 0.2` → **Weak correlation**.

---

## 📊 API Layer Updates

### New Endpoints

#### Instruments
```
GET  /api/v1/financial/instruments              # List all instruments (filterable by type, sector, exchange)
GET  /api/v1/financial/instruments/{id}        # Get instrument details
GET  /api/v1/financial/instruments/{id}/ohlc   # Get OHLC data for instrument
GET  /api/v1/financial/instruments/{id}/fundamentals  # Get fundamentals
GET  /api/v1/financial/instruments/{id}/metrics      # Get pre-computed metrics
GET  /api/v1/financial/instruments/{id}/keywords     # Get extracted keywords
```

#### Metrics
```
GET  /api/v1/financial/metrics                  # List all metrics (filterable by group, instrument)
GET  /api/v1/financial/metrics/groups          # List all metric groups (Trend, Momentum, etc.)
GET  /api/v1/financial/metrics/{id}            # Get metric details
POST /api/v1/financial/metrics/calculate        # Trigger metric calculation for an instrument
```

#### Correlation
```
GET  /api/v1/financial/correlations/articles/{article_id}  # Get all links for an article
GET  /api/v1/financial/correlations/instruments/{instrument_id}  # Get all links for an instrument
POST /api/v1/financial/correlations/link          # Manually link an article to an instrument
DELETE /api/v1/financial/correlations/link/{id}    # Remove a link
```

#### Analysis
```
GET  /api/v1/financial/analysis/fluctuations    # Get fluctuation analysis
GET  /api/v1/financial/analysis/patterns        # Get pattern analysis
GET  /api/v1/financial/analysis/anomalies        # Get anomaly detection
GET  /api/v1/financial/analysis/correlations    # Get correlation analysis
```

---

## 🎨 Visualization-Ready Data

### Metric Grouping for GUI

The GUI will allow users to **explore metrics by group**:

1. **Trend Metrics**:
   - SMA (20, 50, 200)
   - EMA (12, 26)
   - MACD
   - Bollinger Bands
   - ADX

2. **Momentum Metrics**:
   - RSI (14)
   - Stochastic Oscillator
   - ROC
   - CCI
   - Williams %R

3. **Volatility Metrics**:
   - ATR (14)
   - Standard Deviation
   - Beta
   - Historical Volatility

4. **Volume Metrics**:
   - OBV
   - Volume Spike
   - Chaikin Money Flow
   - VWAP

5. **Fundamental Metrics**:
   - P/E Ratio
   - P/B Ratio
   - Dividend Yield
   - ROE
   - Debt-to-Equity

6. **Statistical Metrics**:
   - Z-Score
   - Sharpe Ratio
   - Correlation

### Example Dashboard Views

1. **Instrument Overview**:
   - Price chart with **SMA(20, 50, 200)** overlays.
   - **RSI(14)** and **MACD** below the price chart.
   - **Volume** bars with **OBV** overlay.
   - **Bollinger Bands** (optional).

2. **Metric Explorer**:
   - Dropdown to select **metric group** (Trend, Momentum, etc.).
   - Checkboxes to enable/disable **individual metrics**.
   - Slider to adjust **timeframe** (1D, 1W, 1M, etc.).
   - **Definition popup** on hover (shows formula and use case).

3. **Correlation View**:
   - Timeline of **article publications** and **price movements**.
   - **Keyword cloud** for matched terms.
   - **Sector heatmap** showing related instruments.

---

## 🚀 Updated Implementation Plan

### Phase 1: Database Migration (Week 1)
- [ ] Create new tables: `financial_instruments`, `financial_metrics`, `instrument_keywords`.
- [ ] Update existing tables: Rename `company_id` to `instrument_id` in `financial_data_points` and `article_financial_links`.
- [ ] Add new fields to `article_financial_links`: `matched_keywords`, `matched_sector`, `correlation_type` (enum).
- [ ] Write migration scripts (Alembic).
- [ ] Test backward compatibility with existing data.

### Phase 2: Unified Instrument Model (Week 2)
- [ ] Implement `FinancialInstrument` dataclass and SQLAlchemy model.
- [ ] Migrate existing `Company` data to `FinancialInstrument` (type = "stock").
- [ ] Add `type`, `sector`, `industry`, `base_currency`, `quote_currency` fields.
- [ ] Update all references from `company_id` to `instrument_id`.

### Phase 3: Scraping Enhancements (Weeks 3-4)
- [ ] Implement **instrument discovery** for ETFs, indices, commodities, forex, crypto.
- [ ] Enhance **sector/industry scraping** (Yahoo Finance, exchange websites).
- [ ] Add **fallback logic** for OHLC data (try multiple sources).
- [ ] Implement **incremental updates** (only fetch new data).
- [ ] Add **rate limiting** and **robots.txt compliance**.

### Phase 4: NLP Keyword Extraction (Week 5)
- [ ] Integrate **spaCy** or **NLTK** for keyword extraction.
- [ ] Implement **stopword removal** and **lemmatization**.
- [ ] Extract keywords from:
  - Instrument **names**.
  - Instrument **descriptions**.
  - **Sector/industry** labels.
- [ ] Store in `instrument_keywords` with `source` and `weight`.

### Phase 5: Metric Calculation Engine (Weeks 6-7)
- [ ] Implement **MetricCalculator** class.
- [ ] Add **all 50+ metrics** from the catalog.
- [ ] Group metrics by **theme** (Trend, Momentum, etc.).
- [ ] Store results in `financial_metrics` with:
  - `metric_name`, `metric_group`, `metric_value`.
  - `calculation_method`, `parameters`, `source`.
- [ ] Schedule **daily/weekly** metric updates.

### Phase 6: Correlation Engine Updates (Week 8)
- [ ] Implement **hybrid linking** (temporal + keyword + sector + mention).
- [ ] Update `ArticleFinancialLink` to support new correlation types.
- [ ] Add **scoring logic** for each linking method.
- [ ] Implement **keyword matching** between articles and instruments.

### Phase 7: API Layer Updates (Week 9)
- [ ] Add new endpoints for:
  - `financial_instruments` (CRUD).
  - `financial_metrics` (list, get, calculate).
  - `instrument_keywords` (list, get).
- [ ] Update existing endpoints to use `instrument_id` instead of `company_id`.
- [ ] Add **filtering** by `type`, `sector`, `metric_group`.

### Phase 8: GUI Integration (Weeks 10-11)
- [ ] Design **Metric Explorer** (grouped by theme).
- [ ] Add **definition popups** for metrics.
- [ ] Implement **Correlation View** (temporal + keyword + sector).
- [ ] Add **Instrument Overview Dashboard** (price + metrics).

### Phase 9: Testing & Optimization (Week 12)
- [ ] Write **unit tests** for:
  - Metric calculations.
  - Keyword extraction.
  - Correlation scoring.
- [ ] Test **scraping** for all asset classes.
- [ ] Optimize **database queries** (indexes, caching).
- [ ] Load test with **10,000+ instruments**.

---

## 📦 Dependencies

### Required (New)
```
spacy>=3.0.0          # NLP for keyword extraction
nltk>=3.8.0           # Alternative NLP library
pandas-ta>=0.3.0     # Technical analysis library
ta>=0.10.0           # Alternative TA library
scipy>=1.10.0        # Statistical functions
statsmodels>=0.14.0  # Statistical models
cachetools>=5.3.0    # Caching for scraped data
```

### Recommended (New)
```
textblob>=0.18.0      # Sentiment analysis
wordcloud>=1.9.0     # Keyword visualization
plotly>=5.0.0        # Interactive charts (for GUI)
```

---

## 🛡️ Ethical and Legal Considerations

1. **Robots.txt Compliance**: Always check and respect `robots.txt`.
2. **Rate Limiting**: Default to **1 request per 2 seconds per domain** (configurable).
3. **User-Agent Identification**: Clearly identify as `OpenOmniscience/2.0`.
4. **Public Data Only**: Only scrape **publicly available** data (no paywalls, no authentication).
5. **Caching**: Cache responses for **24 hours** to minimize requests.
6. **Error Handling**: Gracefully handle failures (retries, fallbacks, timeouts).
7. **Data Attribution**: Store `source` for all scraped/processed data.

---

## 📚 Glossary

| Term | Definition |
|------|------------|
| **OHLC** | Open, High, Low, Close price data for a given period. |
| **ETF** | Exchange-Traded Fund: A fund that tracks an index, sector, or asset class. |
| **Forex** | Foreign Exchange: Trading of currency pairs (e.g., EUR/USD). |
| **Crypto** | Cryptocurrency: Digital assets like Bitcoin, Ethereum. |
| **SMA** | Simple Moving Average: Average price over a period. |
| **EMA** | Exponential Moving Average: Weighted average (recent prices matter more). |
| **RSI** | Relative Strength Index: Momentum oscillator (0-100). |
| **ATR** | Average True Range: Volatility measure. |
| **OBV** | On-Balance Volume: Cumulative volume based on price changes. |
| **NLP** | Natural Language Processing: AI for text analysis. |
| **Lemmatization** | Reducing words to their base form (e.g., "running" → "run"). |

---

## 📜 License

This document and the associated code are licensed under the **GNU GPLv3 License**. See the [LICENSE](../../LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Data Providers**: Yahoo Finance, Google Finance, Investing.com, CoinMarketCap, CoinGecko, and others for providing public financial data.
- **Open-Source Libraries**: BeautifulSoup, Scrapy, pandas, numpy, spaCy, NLTK, TA-Lib, pandas-ta.
- **Contributors**: All contributors to the Open Omniscience project.

---

*© 2026 Ideotion. All rights reserved.*
*Built with ❤️ for investigative journalism and ethical financial analysis.*
