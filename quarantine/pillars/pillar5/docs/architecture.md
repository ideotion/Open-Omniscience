# Pillar 5 - Financial Intelligence Architecture

## Overview

Open-Omniscience Pillar 5 provides comprehensive financial data analysis capabilities, enabling the system to ingest, process, and analyze financial data from worldwide sources. This document describes the architecture, components, and data flow of Pillar 5.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Open-Omniscience Core                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   Pillar 1      │    │   Pillar 2      │    │   Pillar 3      │  │
│  │   Content       │    │   Analysis      │    │   Knowledge    │  │
│  │   Ingestion     │    │   Engine        │    │   Graph        │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    Pillar 5 - Financial Intelligence              │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                    Database Layer                          │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │  │  │
│  │  │  │  SQLAlchemy     │  │   Alembic       │  │   SQLite    │  │  │  │
│  │  │  │   Models        │  │  Migrations     │  │  PostgreSQL │  │  │  │
│  │  │  └─────────────────┘  └─────────────────┘  └─────────────┘  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                  │  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                    Scraping Layer                           │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │  │  │
│  │  │  │ Exchange         │  │ Instrument       │  │ OHLC        │  │  │  │
│  │  │  │ Discovery        │  │ Discovery       │  │ Scraper     │  │  │  │
│  │  │  └─────────────────┘  └─────────────────┘  └─────────────┘  │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │  │  │
│  │  │  │ Fundamentals     │  │ Keyword         │  │ Ethical     │  │  │  │
│  │  │  │ Scraper         │  │ Extractor       │  │ Scraper     │  │  │  │
│  │  │  └─────────────────┘  └─────────────────┘  └─────────────┘  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                  │  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                    Services Layer                           │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐                    │  │  │
│  │  │  │ Metric          │  │ Hybrid           │                    │  │  │
│  │  │  │ Calculator      │  │ Correlation      │                    │  │  │
│  │  │  │                 │  │ Engine           │                    │  │  │
│  │  │  └─────────────────┘  └─────────────────┘                    │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                  │  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                    API Layer                               │  │  │
│  │  │  ┌─────────────────────────────────────────────────────┐  │  │  │
│  │  │  │  FastAPI Endpoints:                                    │  │  │  │
│  │  │  │  - /api/v1/financial/exchanges                        │  │  │  │
│  │  │  │  - /api/v1/financial/instruments                       │  │  │  │
│  │  │  │  - /api/v1/financial/ohlc                             │  │  │  │
│  │  │  │  - /api/v1/financial/fundamentals                     │  │  │  │
│  │  │  │  - /api/v1/financial/metrics                          │  │  │  │
│  │  │  │  - /api/v1/financial/correlations                     │  │  │  │
│  │  │  └─────────────────────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                  │  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                    GUI Layer                               │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │  │  │
│  │  │  │ Financial        │  │ Metric          │  │ Correlation │  │  │  │
│  │  │  │ Dashboard        │  │ Explorer        │  │ View        │  │  │  │
│  │  │  └─────────────────┘  └─────────────────┘  └─────────────┘  │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐                    │  │  │
│  │  │  │ Instrument       │  │ Analytics       │                    │  │  │
│  │  │  │ Browser          │  │ Pane            │                    │  │  │
│  │  │  └─────────────────┘  └─────────────────┘                    │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   Pillar 6      │    │   Pillar 7      │    │   Pillar 8      │  │
│  │   (Future)      │    │   (Future)      │    │   (Future)      │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Database Layer

The database layer provides persistent storage for all financial data using SQLAlchemy ORM 2.0 with support for both SQLite (default) and PostgreSQL.

#### Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `financial_exchanges` | Stores exchange information | id, code, name, country, exchange_type |
| `financial_instruments` | Stores all financial instruments | id, symbol, name, type, exchange_id, sector, industry |
| `financial_data_points` | Stores OHLC data | id, instrument_id, timestamp, open, high, low, close, volume |
| `instrument_fundamentals` | Stores fundamental data | id, instrument_id, timestamp, market_cap, pe_ratio, etc. |
| `financial_metrics` | Stores pre-computed metrics | id, instrument_id, name, group, value, timestamp |
| `instrument_keywords` | Stores extracted keywords | id, instrument_id, keyword, weight, source, category |
| `article_financial_links` | Stores article-instrument correlations | id, article_id, instrument_id, correlation_score, type |
| `financial_analyses` | Stores analysis results | id, instrument_id, analysis_type, title, content, score |

#### Relationships

```
financial_exchanges
    │
    └── financial_instruments (exchange_id)
            │
            ├── financial_data_points (instrument_id)
            ├── instrument_fundamentals (instrument_id)
            ├── financial_metrics (instrument_id)
            ├── instrument_keywords (instrument_id)
            └── article_financial_links (instrument_id)
                    │
                    └── articles (article_id)

financial_instruments
    └── financial_analyses (instrument_id)
```

### 2. Scraping Layer

The scraping layer handles data collection from open web sources with ethical scraping practices.

#### Modules

- **ExchangeDiscovery**: Discovers and catalogs stock exchanges worldwide
  - 19 major exchanges (NYSE, NASDAQ, LSE, etc.)
  - 39 regional exchanges
  - 10 cryptocurrency exchanges

- **InstrumentDiscovery**: Discovers financial instruments across all asset classes
  - Stocks: Major companies from all exchanges
  - ETFs: Popular exchange-traded funds
  - Indices: Market indices (S&P 500, NASDAQ, etc.)
  - Commodities: Gold, silver, oil, agricultural products
  - Forex: Major currency pairs
  - Crypto: Major cryptocurrencies

- **OHLCScraper**: Scrapes Open-High-Low-Close data
  - Primary source: Yahoo Finance
  - Fallback source: Investing.com
  - Supported timeframes: 1m, 5m, 15m, 30m, 1h, 1d, 1w, 1m

- **FundamentalsScraper**: Scrapes fundamental data
  - Valuation metrics (P/E, P/B, P/S, etc.)
  - Profitability metrics (ROE, ROA, margins, etc.)
  - Risk metrics (beta, volatility, etc.)
  - Cash flow metrics

- **KeywordExtractor**: Extracts keywords from text
  - NLP-based keyword extraction
  - Sector and industry classification
  - Weighted keyword scoring

#### Ethical Scraping

All scraping follows ethical practices:
- Respects `robots.txt`
- Rate limiting: 1 request per 2 seconds per domain (configurable)
- User-Agent: `OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)`
- File-based caching with 24-hour expiration
- Automatic cache cleanup

### 3. Services Layer

The services layer provides business logic and calculations.

#### MetricCalculator

Calculates 80+ pre-computed metrics across 8 themes:

**Trend Metrics (10)**
- SMA (Simple Moving Average)
- EMA (Exponential Moving Average)
- WMA (Weighted Moving Average)
- DEMA (Double Exponential Moving Average)
- TEMA (Triple Exponential Moving Average)
- HMA (Hull Moving Average)
- MACD (Moving Average Convergence Divergence)
- ADX (Average Directional Index)
- Bollinger Bands (Upper, Lower)

**Momentum Metrics (8)**
- RSI (Relative Strength Index)
- Stochastic Oscillator
- MFI (Money Flow Index)
- CCI (Commodity Channel Index)
- ROC (Rate of Change)
- Momentum
- AO (Awesome Oscillator)
- KST (Know Sure Thing)

**Volatility Metrics (8)**
- ATR (Average True Range)
- Bollinger Band Width
- Bollinger %B
- Standard Deviation
- Variance
- Historical Volatility
- True Range
- Chandelier Exit

**Volume Metrics (8)**
- Volume SMA
- Volume EMA
- OBV (On-Balance Volume)
- CMF (Chaikin Money Flow)
- Force Index
- MFI Volume
- Volume ROC
- Volume Spike

**Fundamental Metrics (14)**
- P/E Ratio
- P/B Ratio
- P/S Ratio
- PEG Ratio
- Dividend Yield
- Payout Ratio
- EPS
- Revenue Growth
- Net Income Growth
- EBITDA Margin
- Gross Margin
- Operating Margin
- Net Margin
- ROE (Return on Equity)
- ROA (Return on Assets)

**Statistical Metrics (10)**
- Mean
- Median
- Mode
- Standard Deviation
- Variance
- Skewness
- Kurtosis
- Sharpe Ratio
- Sortino Ratio
- Alpha
- Beta

**Pattern Metrics (12)**
- Candlestick patterns (Hammer, Shooting Star, etc.)
- Chart patterns (Head & Shoulders, Double Top, etc.)
- Support/Resistance levels
- Trend lines
- Fibonacci retracements
- Pivot points

**Custom Metrics (10)**
- User-defined metrics
- Composite scores
- Custom formulas

#### HybridCorrelationEngine

Calculates correlations between articles and financial instruments using a hybrid scoring formula:

```
correlation_score = (mention * 0.4) + (keyword * 0.3) + (sector * 0.2) + (temporal * 0.1)
```

**Components:**
- **Mention Score**: Direct mentions of instrument name or symbol in article
- **Keyword Score**: Matches between article keywords and instrument keywords
- **Sector Score**: Matches between article sector references and instrument sector
- **Temporal Score**: Temporal relevance (recency of data, article timestamp)

**Features:**
- Multi-instrument correlation calculation
- Score breakdown by component
- Matched keywords and sectors tracking
- Configurable weights
- Batch processing

### 4. API Layer

RESTful API endpoints for accessing Pillar 5 functionality.

#### Base URL
```
/api/v1/financial
```

#### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/exchanges` | List all exchanges |
| GET | `/exchanges/{id}` | Get specific exchange |
| GET | `/exchanges/discover` | Discover new exchanges |
| GET | `/instruments` | List all instruments |
| GET | `/instruments/{id}` | Get specific instrument |
| GET | `/instruments/discover` | Discover new instruments |
| POST | `/instruments/{id}/extract-keywords` | Extract keywords for instrument |
| GET | `/ohlc/{instrument_id}` | Get OHLC data for instrument |
| GET | `/ohlc/{instrument_id}/latest` | Get latest OHLC data |
| GET | `/fundamentals/{instrument_id}` | Get fundamentals for instrument |
| GET | `/metrics` | List all metrics |
| GET | `/metrics/{id}` | Get specific metric |
| GET | `/metrics/instrument/{instrument_id}` | Get all metrics for instrument |
| GET | `/keywords/instrument/{instrument_id}` | Get keywords for instrument |
| POST | `/correlations/calculate` | Calculate correlations for article |
| GET | `/correlations/article/{article_id}` | Get correlations for article |
| GET | `/stats` | Get system statistics |

### 5. GUI Layer

Web-based user interface components for financial data exploration.

#### Components

- **FinancialDashboard**: Main dashboard with tab-based navigation
  - Integrates all Pillar 5 components
  - System statistics overview
  - Quick access to all features

- **InstrumentBrowser**: Browse and filter financial instruments
  - Filter by type, exchange, sector
  - Sort by various fields
  - Pagination for large datasets
  - Detailed instrument view

- **MetricExplorer**: Explore pre-computed metrics
  - Group by theme (Trend, Momentum, etc.)
  - Filter by instrument, timeframe
  - Interactive visualization
  - Metric details and definitions

- **CorrelationView**: View article-instrument correlations
  - Hybrid scoring breakdown
  - Matched keywords and sectors
  - Network visualization
  - Score filtering

## Data Flow

### 1. Data Ingestion Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Exchange        │────▶│  Instrument      │────▶│  OHLC           │
│  Discovery       │     │  Discovery       │     │  Scraper        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                        Database Storage                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ financial_       │  │ financial_       │  │ financial_data_  │  │
│  │ exchanges        │  │ instruments      │  │ points           │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2. Metric Calculation Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Database        │────▶│  Metric         │────▶│  Database        │
│  (OHLC Data)     │     │  Calculator      │     │  (Metrics)       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
       │                   │                   │
       │                   ▼                   │
       │            ┌─────────────────┐          │
       │            │  Pre-computed    │          │
       │            │  Metrics         │          │
       │            └─────────────────┘          │
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                        API Access                               │
└─────────────────────────────────────────────────────────────┘
```

### 3. Correlation Calculation Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Articles        │────▶│  Hybrid         │────▶│  Database        │
│  (from Pillar 1) │     │  Correlation     │     │  (Correlations)  │
└─────────────────┘     │  Engine          │     └─────────────────┘
                           └─────────────────┘
                                  │
                                  ▼
                           ┌─────────────────┐
                           │  Instrument      │
                           │  Data           │
                           └─────────────────┘
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| Database | SQLite (default), PostgreSQL |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Web Framework | FastAPI |
| Scraping | requests, beautifulsoup4, lxml |
| NLP | Custom keyword extraction |
| Metrics | numpy, math |
| Configuration | YAML |
| GUI | Vanilla JavaScript, Chart.js (optional) |

## Design Principles

1. **Separation of Concerns**: Each layer has distinct responsibilities
2. **Modularity**: Components can be used independently
3. **Extensibility**: Easy to add new metrics, scrapers, or features
4. **Backward Compatibility**: Supports existing Pillar 5 data
5. **Ethical Practices**: Respects website policies and rate limits
6. **Performance**: Efficient calculations and caching
7. **Visualization-Ready**: Data structured for easy visualization

## Directory Structure

```
pillar5/
├── configs/
│   └── scraping.yaml              # Scraping configuration
├── migrations/
│   ├── alembic.ini                # Alembic configuration
│   ├── env.py                     # Alembic environment
│   └── versions/
│       └── 001_initial_schema.py  # Database migrations
├── scripts/
│   └── migrate_company_to_instrument.py  # Migration script
├── src/
│   ├── __init__.py                # Package exports
│   ├── api/
│   │   ├── __init__.py            # API module exports
│   │   └── financial_routes.py     # FastAPI endpoints
│   ├── models/
│   │   ├── __init__.py            # Model exports
│   │   ├── base.py                # Base models and database setup
│   │   ├── analysis.py            # FinancialAnalysis model
│   │   ├── company.py             # Original Company model (reference)
│   │   ├── correlation.py         # ArticleFinancialLink model
│   │   ├── exchange.py            # Exchange model
│   │   ├── financial_data.py      # FinancialDataPoint model
│   │   ├── financial_instrument.py # FinancialInstrument model
│   │   ├── financial_metric.py    # FinancialMetric model
│   │   ├── fundamentals.py        # InstrumentFundamentals model
│   │   └── instrument_keyword.py  # InstrumentKeyword model
│   ├── scraping/
│   │   ├── __init__.py            # Scraper exports
│   │   ├── base.py                # EthicalScraper, RateLimiter, CacheManager
│   │   ├── exchange_discovery.py  # ExchangeDiscovery
│   │   ├── fundamentals_scraper.py # FundamentalsScraper
│   │   ├── instrument_discovery.py # InstrumentDiscovery
│   │   ├── keyword_extractor.py   # KeywordExtractor
│   │   └── ohlc_scraper.py         # OHLCScraper
│   └── services/
│       ├── __init__.py            # Service exports
│       ├── correlation_engine.py  # HybridCorrelationEngine
│       └── metric_calculator.py    # MetricCalculator
├── static/
│   └── js/
│       └── components/
│           └── financial/
│               ├── financial_dashboard.js  # Main dashboard
│               ├── metric_explorer.js      # Metric Explorer
│               ├── correlation_view.js      # Correlation View
│               ├── instrument_browser.js    # Instrument Browser
│               └── financial_styles.js       # CSS styles
├── tests/
│   ├── __init__.py                # Test exports
│   ├── test_models.py             # Model tests
│   ├── test_scraping.py           # Scraping tests
│   ├── test_services.py           # Service tests
│   └── test_api.py                # API tests
└── docs/
    ├── __init__.py                # Documentation exports
    ├── architecture.md             # Architecture documentation
    ├── api.md                     # API documentation
    ├── user_guide.md              # User guide
    └── deployment.md              # Deployment guide
```

## Integration with Open-Omniscience

Pillar 5 integrates with the broader Open-Omniscience system:

- **Pillar 1 (Content Ingestion)**: Provides articles for correlation analysis
- **Pillar 2 (Analysis Engine)**: Can use financial data for enhanced analysis
- **Pillar 3 (Knowledge Graph)**: Financial entities can be added to the knowledge graph
- **Pillar 5 (Financial Intelligence)**: This module
- **Future Pillars**: Can consume financial data and metrics

The integration is primarily through:
1. **Database**: All Pillar 5 models are in the same database as other pillars
2. **API**: Pillar 5 exposes RESTful endpoints for other pillars to consume
3. **Article Links**: `article_financial_links` table connects articles to instruments
