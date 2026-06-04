# Pillar 5: Global Financial Intelligence

**Open Omniscience - Financial Data Analysis & Stock Fluctuation Intelligence**

---

## 📌 Overview

Pillar 5 implements a **comprehensive global financial intelligence system** that scrapes, analyzes, and correlates financial data from worldwide stock exchanges with news articles. This enables investigative journalists to:

- Track stock price fluctuations across all global exchanges
- Identify correlations between financial movements and news events
- Analyze company fundamentals and market capitalizations
- Detect anomalies and patterns in financial data
- Visualize financial trends intuitively

**Key Principle:** All data is scraped from open web sources **without APIs, subscriptions, or authentication**. Data is centralized in the same database as articles for seamless cross-referencing.

---

## 🎯 Features

### 🌍 Global Exchange Coverage
- **50+ exchanges** worldwide across all continents
- **Tiered priority system** for efficient scraping
- **Automatic discovery** of new exchanges and companies

### 📊 Comprehensive Data
- **OHLC Data**: Open, High, Low, Close prices with volume
- **Historical Records**: Full historical data for all companies
- **Company Fundamentals**: P/E ratios, market cap, revenue, profitability metrics
- **Real-Time Updates**: Daily scraping with on-demand refresh

### 🔍 Advanced Analysis
- **Fluctuation Detection**: Identify significant price movements
- **Pattern Recognition**: Detect chart patterns (head & shoulders, double tops, etc.)
- **Anomaly Detection**: Find unusual trading activity
- **Correlation Engine**: Link financial movements to news articles
- **Normalization**: Cross-exchange comparison capabilities

### 💾 Centralized Storage
- **Unified Database**: Financial data stored alongside articles
- **Time-Series Optimized**: Efficient storage for historical data
- **Raw + Processed**: Separate tables for raw scraped data and analyzed results
- **Smart Retention**: Configurable data retention policies

### 🎨 Intuitive GUI
- **Financial Overview Dashboard**: Global market heatmap, top movers, volume leaders
- **Company Deep Dive**: Interactive charts, fundamentals, news correlations
- **Correlation Explorer**: Temporal and sentiment-based article linking
- **Advanced Analysis**: Pattern scanning, anomaly detection, custom queries

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PILLAR 5: FINANCIAL INTELLIGENCE                    │
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
│  │  │  articles   │  │  financial_  │  │  financial_        │  │   │
│  │  │             │  │  data_points │  │  fundamentals      │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │   │
│  │  ┌─────────────────────────────────────────────────────┐│   │
│  │  │              article_financial_links                   ││   │
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
# Navigate to Pillar 5 directory
cd pillar5

# Install dependencies
pip install -r requirements.txt

# Set up database (PostgreSQL example)
createdb open_omniscience_financial
psql open_omniscience_financial < schema.sql

# Or use SQLite (for development)
python scripts/setup_database.py

# Run initial data scrape
python scripts/initial_scrape.py
```

### Configuration

Edit `configs/scraping.yaml` to configure:
- Scraping behavior
- Rate limits
- Exchange priorities
- Data sources

---

## 🚀 Usage Examples

### Basic Usage

```python
from pillar5.src.scraping import CompanyScraper
from pillar5.src.storage import FinancialStorage

# Initialize components
scraper = CompanyScraper()
storage = FinancialStorage()

# Scrape data for a company
company_data = scraper.scrape_company("AAPL", "NASDAQ")
storage.store_company_data(company_data)

# Query data
from pillar5.src.models import Company
companies = Company.query.filter_by(exchange_id="NASDAQ").all()
```

### Advanced Analysis

```python
from pillar5.src.analysis import FluctuationDetector, CorrelationEngine

# Detect price fluctuations
detector = FluctuationDetector()
fluctuations = detector.detect_fluctuations("AAPL", time_period="5D")

# Find correlated articles
correlation_engine = CorrelationEngine()
correlations = correlation_engine.correlate_with_articles("AAPL")

# Get analysis results
for analysis in fluctuations:
    print(f"Price change: {analysis.price_change_pct}%")
    print(f"Volatility: {analysis.volatility}")
    print(f"Related articles: {analysis.related_articles}")
```

### GUI Integration

```javascript
// React component example
import { FinancialDashboard } from './components/FinancialDashboard';

function App() {
  return (
    <div className="app">
      <FinancialDashboard 
        exchange="NASDAQ" 
        onCompanySelect={(company) => console.log(company)} 
      />
    </div>
  );
}
```

---

## 📊 Database Schema

### Core Tables

1. **financial_exchanges** - Stock exchange metadata
2. **financial_companies** - Company information
3. **financial_data_points** - OHLC time-series data
4. **financial_fundamentals** - Company fundamentals
5. **financial_analyses** - Analysis results
6. **article_financial_links** - Article-finance correlations

See [PILLAR5_TECHNICAL_SPECIFICATION.md](PILLAR5_TECHNICAL_SPECIFICATION.md) for detailed schema.

---

## 🔌 API Endpoints

### REST API

#### Exchanges
```
GET  /api/v1/financial/exchanges              # List all exchanges
GET  /api/v1/financial/exchanges/{id}       # Get exchange details
POST /api/v1/financial/exchanges/{id}/refresh  # Refresh exchange data
```

#### Companies
```
GET  /api/v1/financial/companies             # List companies
GET  /api/v1/financial/companies/{id}        # Get company details
GET  /api/v1/financial/companies/{id}/ohlc   # Get OHLC data
GET  /api/v1/financial/companies/{id}/fundamentals  # Get fundamentals
```

#### Analysis
```
GET  /api/v1/financial/analysis/fluctuations  # Fluctuation analysis
GET  /api/v1/financial/analysis/patterns     # Pattern recognition
GET  /api/v1/financial/analysis/anomalies     # Anomaly detection
GET  /api/v1/financial/analysis/correlations  # Article correlations
```

#### Correlations
```
GET  /api/v1/financial/correlations/articles  # All article links
GET  /api/v1/financial/correlations/{article_id}  # Links for article
```

---

## 📁 Project Structure

```
pillar5/
├── README.md                          # This file
├── PILLAR5_TECHNICAL_SPECIFICATION.md # Technical specification
├── IMPLEMENTATION_PLAN.md             # Implementation roadmap
│
├── src/
│   ├── scraping/                      # Web scraping modules
│   │   ├── exchange_discovery.py
│   │   ├── company_discovery.py
│   │   ├── ohlc_scraper.py
│   │   ├── fundamentals_scraper.py
│   │   ├── scheduler.py
│   │   ├── rate_limiter.py
│   │   └── robots_txt.py
│   │
│   ├── analysis/                      # Analysis modules
│   │   ├── fluctuation_detector.py
│   │   ├── pattern_recognizer.py
│   │   ├── anomaly_detector.py
│   │   ├── correlation_engine.py
│   │   ├── normalization_engine.py
│   │   └── technical_indicators.py
│   │
│   ├── storage/                       # Storage modules
│   │   ├── time_series_storage.py
│   │   ├── aggregation_engine.py
│   │   └── retention_manager.py
│   │
│   ├── models/                       # Data models
│   │   ├── exchange.py
│   │   ├── company.py
│   │   ├── financial_data.py
│   │   ├── fundamentals.py
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

Pillar 5 follows ethical scraping practices:

- ✅ **Respects robots.txt** - Never scrapes disallowed pages
- ✅ **Rate Limited** - Configurable requests per minute
- ✅ **User-Agent Identification** - Identifies as OpenOmniscience bot
- ✅ **Caching** - Minimizes repeated requests
- ✅ **Public Data Only** - Only scrapes publicly available information
- ✅ **No Authentication** - Never uses credentials or bypasses paywalls

---

## 📊 Exchange Coverage

### Tier 1: Major Global Exchanges (Priority 1)
- NYSE, NASDAQ (USA)
- London Stock Exchange (UK)
- Tokyo Stock Exchange (Japan)
- Shanghai, Shenzhen (China)
- Hong Kong Stock Exchange
- Euronext (Europe)
- Deutsche Börse (Germany)
- Toronto Stock Exchange (Canada)
- Australian Securities Exchange
- Bombay, National Stock Exchange (India)
- São Paulo Stock Exchange (Brazil)

### Tier 2: Regional Exchanges (Priority 2)
- Swiss Exchange
- Stockholm, Oslo
- Singapore Exchange
- Korea Exchange
- Taiwan Stock Exchange
- Mexico Stock Exchange
- Johannesburg Stock Exchange

### Tier 3: Emerging Markets (Priority 3)
- Moscow Exchange
- Istanbul Stock Exchange
- Saudi Stock Exchange
- Dubai Financial Market
- Qatar Stock Exchange
- Egyptian Exchange
- Nigeria Stock Exchange

**Total Target: 50+ exchanges, 10,000+ companies**

---

## 🎨 GUI Features

### Financial Overview Dashboard
- Global market heatmap
- Top movers (gainers/losers)
- Volume leaders
- Sector performance
- Recent correlated news

### Company Deep Dive
- Interactive OHLC charts
- Technical indicators
- Fundamentals table
- News correlation timeline
- Pattern detection alerts
- Anomaly alerts

### Correlation Explorer
- Temporal view of articles and price movements
- Sentiment analysis
- Keyword cloud
- Event timeline

### Advanced Analysis
- Custom query builder
- Pattern scanner
- Anomaly detector
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
- [ ] Phase 5: GUI Integration (0%)
- [ ] Phase 6: Testing & Optimization (0%)
- [ ] Phase 7: Documentation & Deployment (0%)

**Overall Progress: 0% (Design Complete, Implementation Pending)**

---

## 📚 Documentation

- [Technical Specification](PILLAR5_TECHNICAL_SPECIFICATION.md) - Detailed technical design
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
cd Open-Omniscience/pillar5

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

- Financial data providers (Yahoo Finance, Google Finance, Investing.com)
- Open-source scraping libraries (BeautifulSoup, Scrapy)
- Technical analysis libraries (TA-Lib, pandas-ta)
- All contributors to the Open Omniscience project

---

## 📞 Support

- **GitHub Issues**: https://github.com/ideotion/Open-Omniscience/issues
- **Documentation**: Check the docs first!
- **Email**: open-omniscience@ideotion.com

---

*© 2026 Ideotion. All rights reserved.*
*Built with ❤️ for investigative journalism and ethical financial analysis.*
