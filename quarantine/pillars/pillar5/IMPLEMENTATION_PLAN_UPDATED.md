# Pillar 5: Updated Implementation Plan

**Global Financial Intelligence - Detailed Implementation Roadmap (v2.0)**

---

## 📋 Overview

This document **updates** the implementation plan for Pillar 5 to reflect the new requirements:

1. **Unified `financial_instruments` table** (replacing `Company`) with support for **stocks, ETFs, indices, commodities, forex, and crypto**.
2. **Sector/keyword extraction** from company names, descriptions, and articles for **hybrid linking**.
3. **Pre-computed metrics catalog** (80+ metrics grouped by theme) with definitions, formulas, and use cases.
4. **Separate but centralized storage** (Pillar 5 models in the same DB as articles).

**Key Changes from Original Plan:**
- Added **Phase 0: Database Migration** (to handle schema changes).
- Added **Phase 4: NLP Keyword Extraction** (for hybrid linking).
- Added **Phase 5: Metric Calculation Engine** (for pre-computed metrics).
- Updated **Phase 6: Correlation Engine** to include **sector/keyword linking**.
- Updated **Phase 7: API Layer** to support new endpoints for instruments, metrics, and keywords.
- Added **Phase 8: GUI Integration** for metric exploration and correlation views.

---

## 🎯 Implementation Phases (Updated)

### Phase 0: Database Migration (Week 1)
**Objective**: Migrate existing Pillar 5 database schema to support new requirements without breaking existing functionality.

#### Tasks:
- [ ] **Create new tables**:
  - `financial_instruments` (replaces `financial_companies`).
  - `financial_metrics` (new).
  - `instrument_keywords` (new).
- [ ] **Update existing tables**:
  - Rename `company_id` to `instrument_id` in:
    - `financial_data_points`.
    - `article_financial_links`.
    - `company_fundamentals` (rename to `instrument_fundamentals`).
  - Add new fields to `article_financial_links`:
    - `matched_keywords` (JSON array).
    - `matched_sector` (string).
    - Update `correlation_type` enum to include `sector` and `keyword`.
- [ ] **Write Alembic migrations**:
  - Create migration scripts for all schema changes.
  - Test **backward compatibility** with existing data.
- [ ] **Update models**:
  - Add SQLAlchemy models for new tables.
  - Update dataclasses for new fields.
- [ ] **Test migrations**:
  - Run migrations on a **backup of the database**.
  - Verify all existing queries still work.

**Deliverables:**
- Alembic migration scripts (`pillar5/migrations/`).
- Updated SQLAlchemy models (`pillar5/src/models/`).
- Backward-compatible database schema.

---

### Phase 1: Unified Instrument Model (Week 2)
**Objective**: Implement the `FinancialInstrument` model to replace `Company` and support all asset classes.

#### Tasks:
- [ ] **Implement `FinancialInstrument` dataclass**:
  - Fields: `id`, `symbol`, `name`, `type`, `exchange_id`, `sector`, `industry`, `category`, `base_currency`, `quote_currency`, `description`, `founded_year`, `headquarters`, `website`, `is_active`, `last_updated`, `metadata`.
  - Validation: Ensure `type` is one of `stock`, `etf`, `index`, `commodity`, `forex`, `crypto`.
- [ ] **Implement SQLAlchemy model**:
  - Table name: `financial_instruments`.
  - Indexes: `symbol + type` (unique), `type`, `sector`, `industry`, `exchange_id`.
- [ ] **Migrate existing `Company` data**:
  - Copy all `Company` records to `FinancialInstrument` with `type = "stock"`.
  - Map `Company.id` → `FinancialInstrument.id`.
  - Preserve all relationships (e.g., `financial_data_points.company_id` → `instrument_id`).
- [ ] **Update all references**:
  - Replace `company_id` with `instrument_id` in:
    - `FinancialDataPoint`.
    - `InstrumentFundamentals` (renamed from `CompanyFundamentals`).
    - `ArticleFinancialLink`.
    - All API endpoints, services, and scrapers.
- [ ] **Add asset class support**:
  - Extend `InstrumentFundamentals` to support **commodity-specific** (contract size, tick size) and **crypto-specific** (max supply, circulating supply) fields.

**Deliverables:**
- `FinancialInstrument` dataclass and SQLAlchemy model.
- Data migration script (`scripts/migrate_company_to_instrument.py`).
- Updated references across the codebase.

---

### Phase 2: Core Scraping (Weeks 3-4)
**Objective**: Implement scraping for all asset classes (stocks, ETFs, indices, commodities, forex, crypto).

#### Week 3: Exchange & Instrument Discovery
- [ ] **Enhance `ExchangeDiscovery`**:
  - Scrape **50+ exchanges** (Tier 1: NYSE, NASDAQ, LSE, TSE, etc.).
  - Add **exchange metadata** (country, currency, timezone, trading hours).
- [ ] **Implement `InstrumentDiscovery`**:
  - Scrape **instrument lists** from each exchange.
  - Classify instruments by `type`:
    - **Stocks**: Listed companies (e.g., AAPL, MSFT).
    - **ETFs**: Exchange-traded funds (e.g., SPY, QQQ).
    - **Indices**: Market indices (e.g., S&P 500, NASDAQ 100).
    - **Commodities**: Gold, Silver, Oil, etc. (e.g., XAU-USD, CL-USD).
    - **Forex**: Currency pairs (e.g., EUR-USD, USD-JPY).
    - **Crypto**: Cryptocurrencies (e.g., BTC-USD, ETH-USD).
  - Store in `financial_instruments` with `exchange_id` (NULL for forex/crypto).
- [ ] **Scrape sector/industry classifications**:
  - Use **Yahoo Finance**, **Google Finance**, or exchange websites.
  - Populate `sector` and `industry` fields for stocks/ETFs.
- [ ] **Implement rate limiting**:
  - Default: **1 request per 2 seconds per domain** (configurable in `configs/scraping.yaml`).
  - **Exponential backoff** on failures.
- [ ] **Add robots.txt compliance**:
  - Check `robots.txt` before scraping any domain.
  - Respect `Disallow` directives.

#### Week 4: OHLC Data Scraping
- [ ] **Implement `OHLCScraper`**:
  - Scrape **historical OHLC** from:
    - **Yahoo Finance** (primary).
    - **Google Finance** (fallback).
    - **Investing.com** (fallback).
    - **Exchange websites** (fallback).
  - Support **all asset classes** (stocks, ETFs, indices, commodities, forex, crypto).
- [ ] **Handle different data formats**:
  - **Timezones**: Convert all timestamps to UTC.
  - **Currencies**: Store in `base_currency`/`quote_currency` fields.
  - **Volume**: Use `Float` for crypto/forex (where volume is not in shares).
- [ ] **Implement incremental updates**:
  - Only fetch **new data** since the last scrape.
  - Store `last_scraped` timestamp for each instrument.
- [ ] **Add fallback logic**:
  - If one source fails, try the next in the priority list.
- [ ] **Normalize data**:
  - Adjust for **splits** and **dividends** (for stocks).
  - Convert all prices to a **base currency** (configurable, default: USD).

**Deliverables:**
- `ExchangeDiscovery` and `InstrumentDiscovery` classes.
- `OHLCScraper` class with fallback support.
- Sector/industry scraping for all instruments.
- Rate limiting and robots.txt compliance.

---

### Phase 3: Fundamentals & Storage (Week 5)
**Objective**: Implement fundamentals scraping and time-series storage.

- [ ] **Implement `FundamentalsScraper`**:
  - Scrape **key statistics** from:
    - **Yahoo Finance** (Key Statistics, Financials).
    - **Google Finance** (fallback).
    - **Morningstar** (fallback).
    - **MarketWatch** (fallback).
  - Support **stocks/ETFs** (P/E, market cap, revenue, etc.).
  - Support **commodities** (contract size, tick size).
  - Support **crypto** (max supply, circulating supply).
- [ ] **Store in `instrument_fundamentals`**:
  - Include `date`, `fiscal_period`, and `source`.
- [ ] **Implement `TimeSeriesStorage`**:
  - Optimized **bulk insert** for OHLC data.
  - **Date range queries** (e.g., get all data for an instrument between two dates).
  - **Aggregation queries** (daily, weekly, monthly).
- [ ] **Implement `RetentionManager`**:
  - Configurable **data retention policies** (e.g., keep 10 years of daily data).
  - **Archive old data** to a separate table or file.

**Deliverables:**
- `FundamentalsScraper` class.
- `TimeSeriesStorage` and `RetentionManager` classes.
- Fundamentals data for all instruments.

---

### Phase 4: NLP Keyword Extraction (Week 6)
**Objective**: Extract keywords from instrument names, descriptions, and sectors for hybrid linking.

- [ ] **Integrate NLP library**:
  - Use **spaCy** (preferred) or **NLTK** for keyword extraction.
  - Install language model (e.g., `en_core_web_sm` for English).
- [ ] **Implement `KeywordExtractor` class**:
  - **Tokenization**: Split text into words/tokens.
  - **Stopword removal**: Remove common words (e.g., "the", "and", "of").
  - **Lemmatization**: Reduce words to base form (e.g., "designing" → "design").
  - **Noun phrase extraction**: Extract multi-word phrases (e.g., "electric vehicle").
- [ ] **Extract keywords from**:
  - **Instrument names** (e.g., "Apple Inc." → ["apple", "inc"]).
  - **Descriptions** (e.g., "Tesla designs electric vehicles" → ["tesla", "electric", "vehicle", "design"]).
  - **Sector/industry labels** (e.g., "Technology" → ["tech", "technology"]).
- [ ] **Store in `instrument_keywords`**:
  - Fields: `instrument_id`, `keyword`, `source` ("name", "description", "sector"), `weight`, `language`.
  - Normalize keywords (lowercase, no special characters).
- [ ] **Add configuration**:
  - `min_keyword_length` (default: 3).
  - `max_keywords_per_instrument` (default: 50).
  - `stopwords_language` (default: "en").

**Deliverables:**
- `KeywordExtractor` class.
- `instrument_keywords` table populated for all instruments.
- NLP configuration in `configs/scraping.yaml`.

---

### Phase 5: Metric Calculation Engine (Weeks 7-8)
**Objective**: Implement pre-computed metrics (80+ grouped by theme) with full audit trails.

#### Week 7: Metric Calculator
- [ ] **Implement `MetricCalculator` class**:
  - **Fetch data**: Retrieve OHLC/volume from `financial_data_points`.
  - **Validate inputs**: Ensure sufficient data points for each metric’s `period`.
  - **Compute metrics**: Use formulas from the [Pre-Computed Metrics Catalog](docs/PRE_COMPUTED_METRICS_CATALOG.md).
  - **Store results**: Save to `financial_metrics` with:
    - `instrument_id`, `metric_name`, `metric_group`, `metric_value`.
    - `timeframe`, `timestamp`, `calculation_method`, `parameters`.
    - `source`, `is_real_time`, `confidence`.
- [ ] **Implement all 80+ metrics**:
  - **Trend**: SMA, EMA, MACD, Bollinger Bands, ADX, Ichimoku Cloud, Parabolic SAR, Linear Regression, Donchian Channels, Keltner Channels.
  - **Momentum**: RSI, Stochastic Oscillator, ROC, CCI, Williams %R, Awesome Oscillator, Ultimate Oscillator, Momentum.
  - **Volatility**: ATR, Standard Deviation, Beta, Historical Volatility, ATR%, Volatility Ratio.
  - **Volume**: OBV, Volume Spike, Chaikin Money Flow, VWAP, Accumulation/Distribution Line, MFI, Volume Weighted MACD, Ease of Movement.
  - **Fundamental**: P/E (Trailing/Forward), P/B, P/S, Dividend Yield, ROE, ROA, Debt-to-Equity, Current Ratio, Profit Margin, PEG Ratio, Free Cash Flow Yield.
  - **Statistical**: Z-Score, Percentile Rank, Sharpe Ratio, Sortino Ratio, Correlation, Beta, Alpha, R-Squared, VaR, CVaR.
  - **Pattern**: Head & Shoulders, Inverse Head & Shoulders, Double Top/Bottom, Triple Top/Bottom, Support/Resistance Levels, Trendline, Channel, Gap.
  - **Custom**: Golden Cross, Death Cross, Bullish/Bearish Engulfing, Hammer, Shooting Star, Morning/Evening Star, Three White Soldiers, Three Black Crows.
- [ ] **Group metrics by theme**:
  - Use `metric_group` field to categorize (e.g., "Trend", "Momentum").

#### Week 8: Scheduling and Optimization
- [ ] **Implement scheduling**:
  - **Daily**: Compute Trend, Momentum, Volatility, Volume, Statistical metrics.
  - **Weekly**: Compute Fundamental metrics.
  - **On-Demand**: API endpoint to trigger calculation for specific instruments.
- [ ] **Optimize performance**:
  - **Incremental updates**: Only recompute metrics for instruments with new data.
  - **Batch processing**: Compute metrics for multiple instruments in parallel.
  - **Caching**: Cache intermediate results (e.g., SMA values for multiple periods).
- [ ] **Add error handling**:
  - Log failures and skip invalid calculations.
  - Retry failed calculations with exponential backoff.

**Deliverables:**
- `MetricCalculator` class with all 80+ metrics.
- `financial_metrics` table populated for all instruments.
- Scheduled metric updates (daily/weekly).
- On-demand metric calculation API endpoint.

---

### Phase 6: Correlation Engine Updates (Week 9)
**Objective**: Implement hybrid linking (temporal + keyword + sector + mention) between articles and instruments.

- [ ] **Implement `HybridCorrelationEngine`**:
  - **Temporal Linking**:
    - Link articles published **±X hours** (configurable, default: 24h) of a **significant price move** (e.g., >5% change).
    - Calculate `time_diff_hours` and `direction` (before/after/same_time).
  - **Keyword Linking**:
    - Extract keywords from **article text** (using `KeywordExtractor`).
    - Match against `instrument_keywords` table.
    - Score based on:
      - Number of matched keywords.
      - Weight of matched keywords.
      - Position in article (title > first paragraph > body).
    - Store matched keywords in `matched_keywords` field.
  - **Sector Linking**:
    - Extract **sector/industry** from article text (e.g., "tech", "automotive").
    - Match against `financial_instruments.sector` or `industry`.
    - Store matched sector in `matched_sector` field.
  - **Mention Linking**:
    - Direct mention of **instrument name** or **symbol** in article.
    - Highest priority (weight = 0.4).
- [ ] **Implement scoring**:
  - `correlation_score = (temporal_score * temporal_weight) + (keyword_score * keyword_weight) + (sector_score * sector_weight) + (mention_score * mention_weight)`.
  - Default weights:
    - `mention_weight = 0.4`
    - `keyword_weight = 0.3`
    - `sector_weight = 0.2`
    - `temporal_weight = 0.1`
  - Configurable in `configs/correlation.yaml`.
- [ ] **Store links in `article_financial_links`**:
  - Fields: `article_id`, `instrument_id`, `correlation_score`, `correlation_type`, `matched_keywords`, `matched_sector`, `time_diff_hours`, `direction`.
- [ ] **Implement significance filtering**:
  - Only store links with `correlation_score > threshold` (default: 0.3).
  - Mark high-confidence links as `is_significant = True`.

**Deliverables:**
- `HybridCorrelationEngine` class.
- Updated `article_financial_links` table with hybrid linking data.
- Correlation scoring configuration.

---

### Phase 7: API Layer Updates (Week 10)
**Objective**: Add new endpoints for instruments, metrics, and keywords.

- [ ] **Implement new endpoints**:
  - **Instruments**:
    - `GET /api/v1/financial/instruments` (list all, filterable by `type`, `sector`, `exchange`).
    - `GET /api/v1/financial/instruments/{id}` (get details).
    - `GET /api/v1/financial/instruments/{id}/ohlc` (get OHLC data).
    - `GET /api/v1/financial/instruments/{id}/fundamentals` (get fundamentals).
    - `GET /api/v1/financial/instruments/{id}/metrics` (get pre-computed metrics).
    - `GET /api/v1/financial/instruments/{id}/keywords` (get extracted keywords).
  - **Metrics**:
    - `GET /api/v1/financial/metrics` (list all, filterable by `group`, `instrument`).
    - `GET /api/v1/financial/metrics/groups` (list all metric groups).
    - `GET /api/v1/financial/metrics/{id}` (get metric details).
    - `POST /api/v1/financial/metrics/calculate` (trigger calculation for an instrument).
  - **Correlation**:
    - `GET /api/v1/financial/correlations/articles/{article_id}` (get all links for an article).
    - `GET /api/v1/financial/correlations/instruments/{instrument_id}` (get all links for an instrument).
    - `POST /api/v1/financial/correlations/link` (manually link an article to an instrument).
    - `DELETE /api/v1/financial/correlations/link/{id}` (remove a link).
  - **Analysis**:
    - `GET /api/v1/financial/analysis/fluctuations` (get fluctuation analysis).
    - `GET /api/v1/financial/analysis/patterns` (get pattern analysis).
    - `GET /api/v1/financial/analysis/anomalies` (get anomaly detection).
    - `GET /api/v1/financial/analysis/correlations` (get correlation analysis).
- [ ] **Update existing endpoints**:
  - Replace `company_id` with `instrument_id` in all responses.
  - Add filtering by `type`, `sector`, `metric_group`.
- [ ] **Add caching**:
  - Cache frequent queries (e.g., instrument details, metrics).
  - Use `cachetools` or Redis for caching.

**Deliverables:**
- New API endpoints for instruments, metrics, and keywords.
- Updated existing endpoints.
- API caching for performance.

---

### Phase 8: GUI Integration (Weeks 11-12)
**Objective**: Design and implement GUI components for metric exploration and correlation views.

#### Week 11: Metric Explorer
- [ ] **Design `MetricExplorer` component**:
  - Dropdown to select **metric group** (Trend, Momentum, etc.).
  - Dropdown to select **individual metric** (e.g., SMA, RSI).
  - Slider to adjust **timeframe** (1D, 1W, 1M, etc.).
  - **Definition popup** on hover (shows formula and use case).
- [ ] **Implement interactive charts**:
  - **Trend metrics**: Line chart (e.g., SMA overlay on price).
  - **Momentum metrics**: Line chart or histogram (e.g., RSI below price).
  - **Volatility metrics**: Line chart or band chart (e.g., Bollinger Bands).
  - **Volume metrics**: Bar chart or line chart (e.g., OBV overlay on volume).
- [ ] **Add comparison features**:
  - Compare multiple metrics on the same chart.
  - Compare metrics across instruments.

#### Week 12: Correlation View
- [ ] **Design `CorrelationView` component**:
  - Display **article text** and **matched keywords/sector**.
  - Show **linked instruments** with correlation scores and types.
  - **Timeline** of article publications and price movements.
- [ ] **Implement keyword cloud**:
  - Visualize **matched keywords** with size proportional to weight.
- [ ] **Implement sector heatmap**:
  - Show **sector performance** for linked instruments.
- [ ] **Add filtering**:
  - Filter by `correlation_type` (mention, keyword, sector, temporal).
  - Filter by `correlation_score` (e.g., show only strong links).

**Deliverables:**
- `MetricExplorer` and `CorrelationView` React components.
- Interactive charts for all metric groups.
- Keyword cloud and sector heatmap visualizations.

---

### Phase 9: Testing & Optimization (Week 13)
**Objective**: Ensure reliability, performance, and scalability.

- [ ] **Write unit tests**:
  - **Models**: Test validation, serialization, and relationships.
  - **Scraping**: Test rate limiting, fallback logic, and data normalization.
  - **Metrics**: Test all 80+ metric calculations for correctness.
  - **Correlation**: Test scoring logic for all linking methods.
  - **API**: Test all endpoints for correct responses.
- [ ] **Write integration tests**:
  - Test **end-to-end workflows** (e.g., scrape → store → analyze → link).
  - Test **hybrid correlation** with real articles and instruments.
- [ ] **Optimize database queries**:
  - Add **indexes** for frequently queried fields.
  - Optimize **time-series queries** (e.g., date range filters).
  - Use **connection pooling** for high concurrency.
- [ ] **Load test**:
  - Test with **10,000+ instruments** and **1M+ data points**.
  - Measure **scraping speed**, **metric calculation speed**, and **API response times**.
- [ ] **Profile performance**:
  - Identify **bottlenecks** in scraping, metric calculation, or correlation.
  - Optimize slow operations.

**Deliverables:**
- Comprehensive test suite (`pillar5/tests/`).
- Optimized database schema and queries.
- Performance benchmarks and profiling results.

---

### Phase 10: Documentation & Deployment (Week 14)
**Objective**: Finalize documentation and prepare for deployment.

- [ ] **Update documentation**:
  - **README.md**: Update with new features and usage examples.
  - **API Documentation**: Document all new endpoints.
  - **Developer Guide**: Add sections for metric calculation and correlation.
  - **User Guide**: Add GUI usage instructions.
- [ ] **Create deployment scripts**:
  - **Dockerfile**: For containerized deployment.
  - **docker-compose.yml**: For multi-service deployment (e.g., PostgreSQL + Redis).
  - **Installation scripts**: For manual deployment.
- [ ] **Add configuration templates**:
  - `configs/scraping.yaml` (default scraping settings).
  - `configs/correlation.yaml` (default correlation settings).
  - `configs/database.yaml` (database connection settings).
- [ ] **Create example scripts**:
  - `examples/scrape_instruments.py`: Scrape and store instruments.
  - `examples/calculate_metrics.py`: Calculate and store metrics.
  - `examples/link_articles.py`: Link articles to instruments.
- [ ] **Deploy to staging**:
  - Test in a **staging environment** with real data.
  - Fix any issues before production deployment.

**Deliverables:**
- Updated documentation (`pillar5/docs/`).
- Deployment scripts (`pillar5/package/`).
- Configuration templates (`pillar5/configs/`).
- Example scripts (`pillar5/examples/`).

---

## 📅 Timeline Summary

| Phase | Duration | Focus Area | Key Deliverables |
|-------|----------|------------|------------------|
| 0 | Week 1 | Database Migration | Alembic migrations, updated models |
| 1 | Week 2 | Unified Instrument Model | `FinancialInstrument`, data migration |
| 2 | Weeks 3-4 | Core Scraping | `ExchangeDiscovery`, `InstrumentDiscovery`, `OHLCScraper` |
| 3 | Week 5 | Fundamentals & Storage | `FundamentalsScraper`, `TimeSeriesStorage`, `RetentionManager` |
| 4 | Week 6 | NLP Keyword Extraction | `KeywordExtractor`, `instrument_keywords` table |
| 5 | Weeks 7-8 | Metric Calculation Engine | `MetricCalculator`, `financial_metrics` table |
| 6 | Week 9 | Correlation Engine Updates | `HybridCorrelationEngine`, updated `article_financial_links` |
| 7 | Week 10 | API Layer Updates | New endpoints for instruments, metrics, keywords |
| 8 | Weeks 11-12 | GUI Integration | `MetricExplorer`, `CorrelationView` components |
| 9 | Week 13 | Testing & Optimization | Test suite, performance optimizations |
| 10 | Week 14 | Documentation & Deployment | Docs, deployment scripts, examples |

**Total Duration**: **14 weeks** (vs. 12 weeks in original plan).

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
alembic>=1.11.0      # Database migrations
```

### Recommended (New)
```
textblob>=0.18.0      # Sentiment analysis
wordcloud>=1.9.0     # Keyword visualization
plotly>=5.0.0        # Interactive charts (for GUI)
fastapi>=0.95.0      # API layer (if not already included)
uvicorn>=0.21.0     # ASGI server for FastAPI
```

---

## 🛡️ Risk Mitigation

| Risk | Mitigation Strategy | Owner |
|------|---------------------|-------|
| **Schema migration breaks existing data** | Test migrations on a backup database first. | Dev Team |
| **Scraping blocked by rate limits** | Implement exponential backoff and fallback sources. | Dev Team |
| **NLP library performance issues** | Benchmark spaCy vs. NLTK; use lightweight models. | Dev Team |
| **Metric calculation errors** | Add validation and error handling; log failures. | Dev Team |
| **Database performance bottlenecks** | Optimize queries, add indexes, use connection pooling. | Dev Team |
| **API rate limiting** | Implement caching and pagination for API endpoints. | Dev Team |
| **GUI performance with large datasets** | Implement lazy loading and pagination. | Frontend Team |

---

## 📊 Success Criteria

| Metric | Target |
|--------|--------|
| **Database Migration** | 100% of existing data migrated without loss. |
| **Instrument Coverage** | 50+ exchanges, 10,000+ instruments. |
| **OHLC Data** | 90% of instruments have at least 1 year of historical data. |
| **Fundamentals Coverage** | 80% of stocks/ETFs have fundamentals data. |
| **Keyword Extraction** | 95% of instruments have at least 5 keywords. |
| **Metric Calculation** | 100% of 80+ metrics implemented and tested. |
| **Correlation Links** | 70% of articles linked to at least 1 instrument. |
| **API Response Time** | < 500ms for 95% of requests. |
| **GUI Performance** | < 2s load time for dashboards with 10,000+ instruments. |
| **Test Coverage** | > 80% code coverage. |

---

## 📚 References

1. [Pillar 5 Updated Technical Specification](PILLAR5_UPDATED_TECHNICAL_SPECIFICATION.md)
2. [Pre-Computed Metrics Catalog](docs/PRE_COMPUTED_METRICS_CATALOG.md)
3. [Original Implementation Plan](IMPLEMENTATION_PLAN.md)

---

## 🙏 Acknowledgments

- **Contributors**: All contributors to the Open Omniscience project.
- **Open-Source Libraries**: BeautifulSoup, Scrapy, pandas, numpy, spaCy, NLTK, TA-Lib, pandas-ta, FastAPI.

---

*© 2026 Ideotion. All rights reserved.*
*Built with ❤️ for investigative journalism and ethical financial analysis.*
