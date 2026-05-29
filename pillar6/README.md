# Pillar 6: Rare Earth Market Intelligence

**Open Omniscience - Rare Earth Elements Price Analysis & Market Intelligence**

---

## 📌 Overview

Pillar 6 implements a **comprehensive global rare earth market intelligence system** that scrapes, analyzes, and correlates rare earth element (REE) market data from worldwide sources with news articles. This enables investigative journalists to:

- Track rare earth element prices across all global markets
- Monitor supply chain dynamics and production volumes
- Identify correlations between REE price fluctuations and geopolitical/news events
- Analyze market trends and anomalies
- Visualize rare earth market data intuitively

**Key Principle:** All data is scraped from open web sources **without APIs, subscriptions, or authentication**. Data is centralized in the same database as articles for seamless cross-referencing.

---

## 🎯 Features

### 🌍 Global Market Coverage
- **10+ major markets** worldwide (China, US, Australia, Japan, Europe, etc.)
- **All 17 rare earth elements** tracked with comprehensive metadata
- **Tiered priority system** for efficient scraping
- **Automatic discovery** of new markets and data sources

### 📊 Comprehensive Data
- **Price Data**: Spot prices, historical prices, futures (where available)
- **Production Data**: Mining production by country and company
- **Inventory Data**: Strategic stockpiles and exchange warehouses
- **Historical Records**: 10+ years of historical data for major elements
- **Real-Time Updates**: Daily scraping with on-demand refresh

### 🔍 Advanced Analysis
- **Fluctuation Detection**: Identify significant price movements
- **Trend Analysis**: Detect short-term, medium-term, and long-term trends
- **Anomaly Detection**: Find unusual market activity (price spikes, supply shocks)
- **Correlation Engine**: Link REE movements to news articles
- **Forecasting**: Predict future prices using multiple models
- **Normalization**: Cross-element comparison capabilities

### 💾 Centralized Storage
- **Unified Database**: Rare earth data stored alongside articles
- **Time-Series Optimized**: Efficient storage for historical data
- **Raw + Processed**: Separate tables for raw scraped data and analyzed results
- **Smart Retention**: Configurable data retention policies

### 🎨 Intuitive GUI
- **Rare Earth Overview Dashboard**: Global price heatmap, top movers, market status
- **Element Deep Dive**: Interactive charts, production data, news correlations
- **Market Comparison**: Cross-market view, arbitrage opportunities
- **Correlation Explorer**: Temporal and sentiment-based article linking
- **Advanced Analysis**: Custom queries, forecasting, watchlists

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              PILLAR 6: RARE EARTH MARKET INTELLIGENCE               │
├─────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │  SCRAPING   │    │  ANALYSIS   │    │      STORAGE          │  │
│  │   ENGINE    │    │   ENGINE    │    │      ENGINE          │  │
│  └──────┬──────┘    └──────┬──────┘    └──────────┬───────────┘  │
│         │                  │                     │                │
│         ▼                  ▼                     ▼                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    CENTRAL DATABASE                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │   │
│  │  │  articles   │  │  rare_earth_ │  │  rare_earth_      │  │   │
│  │  │             │  │  prices     │  │  production      │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │   │
│  │  ┌─────────────────────────────────────────────────────┐│   │
│  │  │              article_rare_earth_links                   ││   │
│  │  └─────────────────────────────────────────────────────┘│   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │    API      │    │ CORRELATION  │    │  VISUALIZATION   │  │
│  │   LAYER    │    │   ENGINE     │    │     READY        │  │
│  └─────────────┘    └─────────────┘    └─────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📦 Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 14+ (recommended) or SQLite
- Redis (for caching and rate limiting)

### Installation

```bash
# Navigate to Pillar 6 directory
cd pillar6

# Install dependencies
pip install -r requirements.txt

# Set up database (PostgreSQL example)
createdb open_omniscience_rare_earth
psql open_omniscience_rare_earth < schema.sql

# Or use SQLite (for development)
python scripts/setup_database.py

# Run initial data scrape
python scripts/initial_scrape.py
```

### Configuration

Edit `configs/scraping.yaml` to configure:
- Scraping behavior
- Rate limits
- Market priorities
- Data sources

---

## 🚀 Usage Examples

### Basic Usage

```python
from pillar6.src.scraping import MarketScraper, PriceScraper
from pillar6.src.storage import RareEarthStorage

# Initialize components
market_scraper = MarketScraper()
price_scraper = PriceScraper()
storage = RareEarthStorage()

# Scrape market data
markets = market_scraper.discover_markets()
storage.store_markets(markets)

# Scrape price data for an element
prices = price_scraper.scrape_historical_prices("Nd", "china_spot", start_date, end_date)
storage.store_prices(prices)

# Query data
from pillar6.src.models import RareEarthPrice
prices = RareEarthPrice.query.filter_by(element_id="Nd").all()
```

### Advanced Analysis

```python
from pillar6.src.analysis import FluctuationDetector, CorrelationEngine

# Detect price fluctuations
detector = FluctuationDetector()
fluctuations = detector.detect_fluctuations("Nd", time_period="5D")

# Find correlated articles
correlation_engine = CorrelationEngine()
correlations = correlation_engine.correlate_with_articles("Nd")

# Get analysis results
for analysis in fluctuations:
    print(f"Price change: {analysis.price_change_pct}%")
    print(f"Volatility: {analysis.volatility}")
    print(f"Related articles: {analysis.related_articles}")
```

### GUI Integration

```javascript
// React component example
import { RareEarthDashboard } from './components/RareEarthDashboard';

function App() {
  return (
    <div className="app">
      <RareEarthDashboard 
        element="Nd" 
        onElementSelect={(element) => console.log(element)} 
      />
    </div>
  );
}
```

---

## 📊 Database Schema

### Core Tables

1. **rare_earth_elements** - Metadata about all 17 rare earth elements
2. **rare_earth_markets** - Information about markets/exchanges
3. **rare_earth_prices** - Time-series price data
4. **rare_earth_production** - Production data by country/company
5. **rare_earth_inventory** - Inventory/stockpile data
6. **rare_earth_analyses** - Analysis results
7. **article_rare_earth_links** - Article-REE correlations

See [PILLAR6_TECHNICAL_SPECIFICATION.md](PILLAR6_TECHNICAL_SPECIFICATION.md) for detailed schema.

---

## 🔌 API Endpoints

### REST API

#### Elements
```
GET  /api/v1/rare_earth/elements              # List all rare earth elements
GET  /api/v1/rare_earth/elements/{id}        # Get element details
```

#### Markets
```
GET  /api/v1/rare_earth/markets              # List all markets
GET  /api/v1/rare_earth/markets/{id}        # Get market details
POST /api/v1/rare_earth/markets/{id}/refresh  # Refresh market data
```

#### Prices
```
GET  /api/v1/rare_earth/prices               # Query price data
GET  /api/v1/rare_earth/prices/{id}         # Get specific price point
GET  /api/v1/rare_earth/elements/{id}/prices  # Get prices for an element
```

#### Analysis
```
GET  /api/v1/rare_earth/analysis/fluctuations  # Fluctuation analysis
GET  /api/v1/rare_earth/analysis/trends      # Trend analysis
GET  /api/v1/rare_earth/analysis/anomalies    # Anomaly detection
GET  /api/v1/rare_earth/analysis/correlations  # Article correlations
GET  /api/v1/rare_earth/analysis/forecasts    # Price forecasts
```

#### Correlations
```
GET  /api/v1/rare_earth/correlations/articles  # All article links
GET  /api/v1/rare_earth/correlations/{article_id}  # Links for article
```

---

## 📁 Project Structure

```
pillar6/
├── README.md                          # This file
├── PILLAR6_TECHNICAL_SPECIFICATION.md # Technical specification
├── IMPLEMENTATION_PLAN.md             # Implementation roadmap
│
├── src/
│   ├── __init__.py
│   │
│   ├── scraping/                      # Web scraping modules
│   │   ├── market_discovery.py
│   │   ├── price_scraper.py
│   │   ├── production_scraper.py
│   │   ├── inventory_scraper.py
│   │   ├── scheduler.py
│   │   ├── rate_limiter.py
│   │   └── robots_txt.py
│   │
│   ├── analysis/                      # Analysis modules
│   │   ├── fluctuation_detector.py
│   │   ├── trend_analyzer.py
│   │   ├── anomaly_detector.py
│   │   ├── correlation_engine.py
│   │   ├── forecasting_engine.py
│   │   └── normalization_engine.py
│   │
│   ├── storage/                       # Storage modules
│   │   ├── time_series_storage.py
│   │   ├── aggregation_engine.py
│   │   └── retention_manager.py
│   │
│   ├── models/                       # Data models
│   │   ├── element.py
│   │   ├── market.py
│   │   ├── price.py
│   │   ├── production.py
│   │   ├── inventory.py
│   │   ├── analysis.py
│   │   └── correlation.py
│   │
│   └── api/                          # API layer
│       ├── routes.py
│       ├── schemas.py
│       └── query_builder.py
│
├── tests/                           # Test suite
├── configs/                        # Configuration files
├── examples/                       # Usage examples
├── docs/                           # Documentation
└── scripts/                        # Utility scripts
```

---

## 🛡️ Ethical Scraping

Pillar 6 follows ethical scraping practices:

- ✅ **Respects robots.txt** - Never scrapes disallowed pages
- ✅ **Rate Limited** - Configurable requests per minute
- ✅ **User-Agent Identification** - Identifies as OpenOmniscience bot
- ✅ **Caching** - Minimizes repeated requests
- ✅ **Public Data Only** - Only scrapes publicly available information
- ✅ **No Authentication** - Never uses credentials or bypasses paywalls

---

## 🌍 Market Coverage

### Tier 1: Primary Markets (Priority 1)
- **China Spot Market** (Baotou, Ganzhou) - Dominant global producer
- **London Metal Exchange (LME)** - Major commodities exchange
- **Shanghai Futures Exchange (SHFE)** - Chinese futures market
- **USGS Mineral Commodity Summaries** - US government data
- **Metal Bulletin / Fastmarkets** - Industry price assessments
- **Platts (S&P Global)** - Commodity price reporting

### Tier 2: Producer Markets (Priority 2)
- **MP Materials** (USA) - Mountain Pass mine
- **Lynas Corporation** (Australia/Malaysia) - Major producer
- **Northern Minerals** (Australia) - Browns Range project
- **Arafura Resources** (Australia) - Nolans project
- **Less Common Metals** (UK) - Processing
- **Toyota Tsusho** (Japan) - Trading

### Tier 3: Regional Markets (Priority 3)
- **India Rare Earths Limited**
- **Vietnam Rare Earth**
- **Russia Rare Earth**
- **Brazil Rare Earth**
- **Greenland Rare Earth** (Kvanefjeld, Kringlerne)

**Total Target: 10+ markets, all 17 elements**

---

## 🎨 GUI Features

### Rare Earth Overview Dashboard
- Global price heatmap for all 17 elements
- Top movers (gainers/losers)
- Critical elements focus (Nd, Pr, Dy, Tb)
- Market status overview
- Recent correlated news
- Composite indices (Critical REE, Magnet REE, etc.)

### Element Deep Dive
- Interactive price chart with technical indicators
- Historical data with zoom/pan
- Production data by country/company
- Inventory/stockpile levels
- News correlation timeline
- Analysis results (fluctuations, trends, anomalies, forecasts)
- Comparisons with other elements

### Market Comparison
- Cross-market price comparison
- Arbitrage opportunities
- Market share by country/company
- Supply chain visualization

### Correlation Explorer
- Temporal view of articles and price movements
- Sentiment analysis
- Keyword cloud
- Event timeline
- Geopolitical risk map

### Advanced Analysis
- Custom query builder
- Pattern scanner
- Anomaly detector
- Forecasting tool
- Portfolio tracker
- Watchlists

---

## 📦 Dependencies

### Required
```
requests>=2.28.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pandas>=2.0.0
numpy>=1.24.0
sqlalchemy>=2.0.0
```

### Recommended
```
scrapy>=2.8.0
selenium>=4.10.0
scipy>=1.10.0
statsmodels>=0.14.0
ta>=0.10.0
pandas-ta>=0.3.0
scikit-learn>=1.3.0
cachetools>=5.3.0
aiohttp>=3.8.0
```

See [requirements.txt](requirements.txt) for complete list.

---

## 🚀 Implementation Status

- [x] Technical specification complete
- [x] Architecture designed
- [x] Database schema defined
- [x] API endpoints designed
- [x] GUI components designed
- [ ] Phase 1: Foundation (0%)
- [ ] Phase 2: Core Scraping (0%)
- [ ] Phase 3: Analysis Engine (0%)
- [ ] Phase 4: Correlation Engine (0%)
- [ ] Phase 5: Forecasting Engine (0%)
- [ ] Phase 6: GUI Integration (0%)
- [ ] Phase 7: Testing & Optimization (0%)
- [ ] Phase 8: Documentation & Deployment (0%)

**Overall Progress: 0% (Design Complete, Implementation Pending)**

---

## 📚 Documentation

- [Technical Specification](PILLAR6_TECHNICAL_SPECIFICATION.md) - Detailed technical design
- [Implementation Plan](IMPLEMENTATION_PLAN.md) - Development roadmap
- [User Guide](docs/USER_GUIDE.md) - Usage instructions
- [Developer Guide](docs/DEVELOPER_GUIDE.md) - Development guidelines
- [API Documentation](docs/API_DOCUMENTATION.md) - API reference

---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience/pillar6

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/
```

---

## 📜 License

This project is licensed under the **GNU GPLv3 License** - see the [LICENSE](../../LICENSE) file for details.

---

## 🙏 Acknowledgments

- Data providers (USGS, Metal Bulletin, Fastmarkets, Platts)
- Open-source scraping libraries (BeautifulSoup, Scrapy)
- Analysis libraries (pandas, numpy, scipy, statsmodels)
- All contributors to the Open Omniscience project

---

## 📞 Support

- **GitHub Issues**: https://github.com/ideotion/Open-Omniscience/issues
- **Documentation**: Check the docs first!
- **Email**: open-omniscience@ideotion.com

---

*© 2026 Ideotion. All rights reserved.*
*Built with ❤️ for investigative journalism and ethical rare earth market analysis.*
