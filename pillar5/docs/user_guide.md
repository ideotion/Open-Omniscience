# Pillar 5 - Financial Intelligence User Guide

## Overview

Welcome to Open-Omniscience Pillar 5 - Financial Intelligence! This guide will help you understand and use the comprehensive financial data analysis capabilities provided by Pillar 5.

## Quick Start

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- SQLite (included with Python) or PostgreSQL
- Modern web browser (for GUI components)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ideotion/Open-Omniscience.git
   cd Open-Omniscience
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Pillar 5 specific dependencies:**
   ```bash
   cd pillar5
   pip install -r requirements.txt
   ```

4. **Set up the database:**
   ```bash
   cd pillar5
   # Initialize Alembic
   alembic upgrade head
   ```

5. **Populate with sample data:**
   ```bash
   python scripts/migrate_company_to_instrument.py
   ```

6. **Start the application:**
   ```bash
   # From the main Open-Omniscience directory
   uvicorn main:app --reload
   ```

7. **Access the application:**
   Open your browser and navigate to `http://localhost:8000`

## Using Pillar 5

### Web Interface

Pillar 5 provides a comprehensive web-based interface for financial data analysis.

#### Financial Dashboard

The main dashboard provides:
- Overview of system statistics
- Quick access to all features
- Tab-based navigation between different components

**Access:** Navigate to the Pillar 5 section in your Open-Omniscience interface.

#### Instrument Browser

Browse and filter financial instruments across all asset classes.

**Features:**
- Filter by type (stock, ETF, index, commodity, forex, crypto)
- Filter by exchange, sector, or industry
- Sort by various fields (symbol, name, price, volume, etc.)
- Pagination for large datasets
- Detailed instrument view with fundamentals

**How to use:**
1. Click on "Instruments" tab in the dashboard
2. Use the filters on the left to narrow down your search
3. Click on any instrument to view detailed information
4. Use the search box to find specific instruments

#### Metric Explorer

Explore pre-computed financial metrics grouped by theme.

**Features:**
- Browse metrics by theme (Trend, Momentum, Volatility, Volume, etc.)
- Filter by instrument or timeframe
- View metric definitions, formulas, and use cases
- Interactive visualization of metric values

**How to use:**
1. Click on "Metrics" tab in the dashboard
2. Select a metric group from the sidebar
3. Click on a metric to view its details
4. Use the visualization panel to see historical values

#### Correlation View

View and analyze correlations between articles and financial instruments.

**Features:**
- Calculate correlations for any article
- View correlation scores with breakdown by component
- See matched keywords and sectors
- Network visualization of correlations
- Filter by score threshold or correlation type

**How to use:**
1. Click on "Correlations" tab in the dashboard
2. Select an article from the dropdown
3. Click "Load Article" to calculate correlations
4. Use the score slider to filter results
5. Click on correlation cards to see detailed breakdown

### API Usage

Pillar 5 provides a comprehensive RESTful API for programmatic access.

#### Base URL
```
http://localhost:8000/api/v1/financial
```

#### Common API Examples

**List all instruments:**
```bash
curl -X GET "http://localhost:8000/api/v1/financial/instruments"
```

**Get OHLC data for an instrument:**
```bash
curl -X GET "http://localhost:8000/api/v1/financial/ohlc/1?timeframe=1d&limit=30"
```

**Calculate correlations for an article:**
```bash
curl -X POST "http://localhost:8000/api/v1/financial/correlations/calculate" \
  -H "Content-Type: application/json" \
  -d '{
    "article_id": 1,
    "article_text": "Apple stock is rising due to strong earnings in the technology sector."
  }'
```

**Get all metrics for an instrument:**
```bash
curl -X GET "http://localhost:8000/api/v1/financial/metrics/instrument/1"
```

For more API examples, see the [API Documentation](api.md).

## Asset Classes

Pillar 5 supports all major asset classes:

### Stocks
Equity securities representing ownership in a corporation.

**Examples:**
- AAPL (Apple Inc.)
- MSFT (Microsoft Corporation)
- GOOGL (Alphabet Inc.)
- AMZN (Amazon.com Inc.)
- TSLA (Tesla Inc.)

### ETFs (Exchange-Traded Funds)
Investment funds traded on stock exchanges.

**Examples:**
- SPY (SPDR S&P 500 ETF)
- QQQ (Invesco QQQ Trust)
- VTI (Vanguard Total Stock Market ETF)
- VXUS (Vanguard Total International Stock ETF)
- GLD (SPDR Gold Shares)

### Indices
Market indices representing the performance of a group of stocks.

**Examples:**
- S&P 500
- NASDAQ Composite
- Dow Jones Industrial Average
- FTSE 100
- Nikkei 225

### Commodities
Raw materials or primary agricultural products.

**Examples:**
- Gold (XAU)
- Silver (XAG)
- Crude Oil (CL)
- Natural Gas (NG)
- Wheat (ZW)

### Forex (Foreign Exchange)
Currency pairs for foreign exchange trading.

**Examples:**
- EUR/USD (Euro/US Dollar)
- USD/JPY (US Dollar/Japanese Yen)
- GBP/USD (British Pound/US Dollar)
- USD/CHF (US Dollar/Swiss Franc)
- AUD/USD (Australian Dollar/US Dollar)

### Cryptocurrencies
Digital or virtual currencies using cryptography.

**Examples:**
- BTC/USD (Bitcoin)
- ETH/USD (Ethereum)
- BNB/USD (Binance Coin)
- SOL/USD (Solana)
- XRP/USD (Ripple)

## Metric Groups

Pillar 5 organizes 80+ pre-computed metrics into 8 groups for easy exploration:

### 1. Trend Metrics
Identify and analyze market trends.

**Key Metrics:**
- **SMA (Simple Moving Average)**: Average price over a specified period
- **EMA (Exponential Moving Average)**: Weighted average giving more weight to recent prices
- **MACD (Moving Average Convergence Divergence)**: Trend-following momentum indicator
- **ADX (Average Directional Index)**: Measures trend strength
- **Bollinger Bands**: Volatility bands placed above and below a moving average

**Use Cases:**
- Identify trend direction
- Determine trend strength
- Spot potential reversals
- Set stop-loss levels

### 2. Momentum Metrics
Measure the rate of price changes.

**Key Metrics:**
- **RSI (Relative Strength Index)**: Measures speed and change of price movements (0-100)
- **Stochastic Oscillator**: Compares closing price to price range over a period
- **MFI (Money Flow Index)**: Volume-weighted RSI
- **CCI (Commodity Channel Index)**: Identifies cyclical trends
- **ROC (Rate of Change)**: Percentage change in price over a period

**Use Cases:**
- Identify overbought/oversold conditions
- Spot divergences
- Confirm trend strength
- Generate buy/sell signals

### 3. Volatility Metrics
Measure price fluctuations.

**Key Metrics:**
- **ATR (Average True Range)**: Measures market volatility
- **Bollinger Band Width**: Distance between upper and lower bands
- **Standard Deviation**: Statistical measure of price dispersion
- **Historical Volatility**: Annualized standard deviation of returns

**Use Cases:**
- Assess risk
- Set position sizes
- Determine stop-loss levels
- Identify breakout opportunities

### 4. Volume Metrics
Analyze trading volume patterns.

**Key Metrics:**
- **OBV (On-Balance Volume)**: Cumulative volume indicator
- **CMF (Chaikin Money Flow)**: Volume-weighted accumulation/distribution
- **Force Index**: Combines price and volume
- **Volume ROC**: Rate of change of volume

**Use Cases:**
- Confirm price trends
- Identify accumulation/distribution
- Spot volume spikes
- Predict price movements

### 5. Fundamental Metrics
Analyze financial health and valuation.

**Key Metrics:**
- **P/E Ratio**: Price to earnings ratio
- **P/B Ratio**: Price to book value ratio
- **Dividend Yield**: Annual dividend per share divided by price
- **ROE (Return on Equity)**: Net income divided by shareholders' equity
- **Debt to Equity**: Total debt divided by total equity

**Use Cases:**
- Value investing
- Financial health assessment
- Growth potential analysis
- Risk evaluation

### 6. Statistical Metrics
Advanced statistical analysis.

**Key Metrics:**
- **Sharpe Ratio**: Risk-adjusted return
- **Sortino Ratio**: Downside risk-adjusted return
- **Alpha**: Excess return relative to benchmark
- **Beta**: Volatility relative to market
- **Skewness**: Asymmetry of returns distribution
- **Kurtosis**: "Tailedness" of returns distribution

**Use Cases:**
- Risk-adjusted performance analysis
- Portfolio optimization
- Benchmark comparison
- Distribution analysis

### 7. Pattern Metrics
Identify chart and candlestick patterns.

**Key Metrics:**
- **Candlestick Patterns**: Hammer, Shooting Star, Doji, etc.
- **Chart Patterns**: Head & Shoulders, Double Top, etc.
- **Support/Resistance**: Price levels where trends tend to reverse
- **Pivot Points**: Intraday support and resistance levels

**Use Cases:**
- Pattern recognition
- Price target identification
- Entry/exit signals
- Risk management

### 8. Custom Metrics
User-defined and composite metrics.

**Features:**
- Create custom formulas
- Combine multiple metrics
- Define custom parameters
- Save for future use

**Use Cases:**
- Proprietary indicators
- Composite scores
- Custom strategies
- Backtesting

## Correlation Analysis

Pillar 5's hybrid correlation engine links articles to financial instruments using a multi-factor scoring system.

### Correlation Formula

```
correlation_score = (mention * 0.4) + (keyword * 0.3) + (sector * 0.2) + (temporal * 0.1)
```

### Components

1. **Mention Score (40%)**
   - Direct mentions of instrument name or symbol in the article
   - Higher weight for exact matches
   - Case-insensitive matching

2. **Keyword Score (30%)**
   - Matches between article keywords and instrument keywords
   - Weighted by keyword importance
   - Considers synonyms and related terms

3. **Sector Score (20%)**
   - Matches between article sector references and instrument sector
   - Considers industry and sub-sector classifications
   - Weighted by sector specificity

4. **Temporal Score (10%)**
   - Temporal relevance based on article timestamp
   - Recency of instrument data
   - Market hours consideration

### Using Correlations

1. **Article Analysis**: Understand which financial instruments are most relevant to an article
2. **Portfolio Impact**: Assess how news might affect your portfolio
3. **Trend Identification**: Identify emerging trends from news patterns
4. **Risk Management**: Monitor correlations to anticipate market movements

### Correlation Score Interpretation

| Score Range | Interpretation |
|-------------|----------------|
| 0.8 - 1.0 | Strong correlation |
| 0.6 - 0.8 | Moderate correlation |
| 0.4 - 0.6 | Weak correlation |
| 0.2 - 0.4 | Very weak correlation |
| 0.0 - 0.2 | No significant correlation |

## Ethical Scraping

Pillar 5 follows ethical scraping practices:

### Rate Limiting
- Default: 1 request per 2 seconds per domain
- Configurable per domain in `configs/scraping.yaml`

### Caching
- File-based caching with 24-hour expiration
- Automatic cache cleanup
- Cache directory: `.cache/pillar5/`

### User-Agent
All requests include a descriptive User-Agent:
```
OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)
```

### Respect for robots.txt
- Checks `robots.txt` before scraping
- Respects crawl-delay directives
- Honors disallow rules

## Configuration

### Scraping Configuration

Edit `pillar5/configs/scraping.yaml`:

```yaml
# Rate limiting
rate_limits:
  default: 2.0  # seconds between requests
  yahoo.com: 2.5
  investing.com: 3.0
  nasdaq.com: 2.0

# Caching
cache:
  enabled: true
  expiration: 86400  # 24 hours in seconds
  directory: .cache/pillar5
  cleanup_interval: 3600  # 1 hour in seconds

# User agent
user_agent: "OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)"

# Timeout
timeout: 30  # seconds

# Retry settings
max_retries: 3
retry_delay: 1.0

# Primary sources
primary_sources:
  ohlc: yahoo
  fundamentals: yahoo
  exchanges: internal
  instruments: internal

# Fallback sources
fallback_sources:
  ohlc: [investing.com, alpha_vantage]
  fundamentals: [investing.com]
```

### Database Configuration

Edit `pillar5/src/models/base.py`:

```python
# SQLite (default)
SQLALCHEMY_DATABASE_URL = "sqlite:///./open_omniscience.db"

# PostgreSQL
# SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost/open_omniscience"
```

## Troubleshooting

### Common Issues

**1. Database connection errors**
- Ensure SQLite file exists and is writable
- For PostgreSQL, verify connection credentials
- Check that the database server is running

**2. Scraping failures**
- Check internet connection
- Verify rate limits are not being exceeded
- Check if target website is accessible
- Review `robots.txt` for the target domain

**3. API endpoint not found**
- Verify the endpoint URL is correct
- Check that the FastAPI application is running
- Ensure Pillar 5 routes are properly included

**4. Missing dependencies**
- Run `pip install -r requirements.txt`
- Check for version conflicts
- Verify all required packages are installed

### Debug Mode

Enable debug mode for more detailed error messages:

```python
# In main.py or wherever you create the FastAPI app
app = FastAPI(debug=True)
```

### Logs

Check application logs for detailed error information:
- Console output when running with `uvicorn`
- FastAPI logs
- Scraping logs (if enabled)

## Best Practices

### Data Management

1. **Regular Updates**: Schedule regular updates for OHLC and fundamentals data
2. **Data Retention**: Consider archiving old data to save space
3. **Backup**: Regularly backup your database
4. **Validation**: Validate data before use

### Performance

1. **Caching**: Enable caching for frequently accessed data
2. **Batch Processing**: Process data in batches for efficiency
3. **Indexing**: Ensure database indexes are properly configured
4. **Pagination**: Use pagination for large datasets

### Security

1. **API Protection**: Consider adding rate limiting to API endpoints
2. **Data Validation**: Validate all inputs and outputs
3. **Error Handling**: Implement proper error handling
4. **Logging**: Log important events and errors

## Advanced Usage

### Custom Metrics

Create custom metrics by extending the `MetricCalculator` class:

```python
from pillar5.src.services.metric_calculator import MetricCalculator, MetricDefinition, MetricGroup

class CustomMetricCalculator(MetricCalculator):
    def __init__(self):
        super().__init__()
        # Add custom metric definitions
        self.METRIC_DEFINITIONS['MY_CUSTOM_METRIC'] = MetricDefinition(
            name='MY_CUSTOM_METRIC',
            group=MetricGroup.CUSTOM,
            display_name='My Custom Metric',
            description='A custom metric I created',
            formula='Custom formula',
            use_case='Custom use case',
            visualization_type='line',
            parameters={'param1': 10}
        )
    
    def calculate_custom_metric(self, ohlc_data, **kwargs):
        # Implement your custom calculation
        return custom_value

# Register the custom metric
calculator = CustomMetricCalculator()
```

### Custom Scrapers

Create custom scrapers by extending the `EthicalScraper` class:

```python
from pillar5.src.scraping.base import EthicalScraper

class CustomScraper(EthicalScraper):
    def __init__(self):
        super().__init__(
            base_url='https://custom-source.com',
            rate_limit=2.0,
            user_agent='MyCustomScraper/1.0'
        )
    
    def scrape_data(self, symbol):
        # Implement custom scraping logic
        url = f'{self.base_url}/{symbol}'
        html = self.fetch(url)
        # Parse and extract data
        return extracted_data
```

### Batch Processing

Process multiple instruments efficiently:

```python
from pillar5.src.scraping.ohlc_scraper import OHLCScraper
from pillar5.src.services.metric_calculator import MetricCalculator

# Initialize scrapers and calculators
scraper = OHLCScraper()
calculator = MetricCalculator()

# List of instrument symbols
symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']

# Process each instrument
for symbol in symbols:
    # Get OHLC data
    ohlc_data = scraper.get_ohlc_data(symbol, timeframe='1d', limit=50)
    
    # Calculate metrics
    metrics = calculator.calculate_all_metrics(ohlc_data, symbol, '1d')
    
    # Store or process metrics
    process_metrics(symbol, metrics)
```

## Integration with Other Pillars

### Pillar 1 (Content Ingestion)

Use financial correlations to enhance article analysis:

```python
from pillar5.src.services.correlation_engine import HybridCorrelationEngine

# Get article from Pillar 1
article = pillar1.get_article(article_id)

# Calculate correlations with financial instruments
engine = HybridCorrelationEngine()
correlations = engine.calculate_correlation(
    article_id=article.id,
    article_text=article.content,
    instruments=all_instruments
)

# Store correlations for future reference
pillar5.store_correlations(correlations)
```

### Pillar 2 (Analysis Engine)

Use financial data in analysis:

```python
from pillar5.src.models.financial_instrument import FinancialInstrumentDB
from pillar5.src.models.financial_metric import FinancialMetricDB

# Get instrument data
instrument = FinancialInstrumentDB.query.filter_by(symbol='AAPL').first()

# Get latest metrics
metrics = FinancialMetricDB.query.filter_by(instrument_id=instrument.id).all()

# Use in Pillar 2 analysis
pillar2.analyze_with_financial_data(article, instrument, metrics)
```

### Pillar 3 (Knowledge Graph)

Add financial entities to the knowledge graph:

```python
from pillar5.src.models.financial_instrument import FinancialInstrumentDB

# Get all instruments
instruments = FinancialInstrumentDB.query.all()

# Add to knowledge graph
for instrument in instruments:
    pillar3.add_entity(
        entity_type='financial_instrument',
        name=instrument.name,
        symbol=instrument.symbol,
        properties={
            'type': instrument.type,
            'sector': instrument.sector,
            'industry': instrument.industry,
            'exchange': instrument.exchange.code
        }
    )
```

## Contributing

### Reporting Issues

1. Check existing issues on GitHub
2. Create a new issue with:
   - Clear description
   - Steps to reproduce
   - Expected vs. actual behavior
   - Screenshots (if applicable)
   - Logs (if applicable)

### Code Contributions

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Update documentation
6. Submit a pull request

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
pip install -r requirements-dev.txt

# Install in development mode
pip install -e .

# Run tests
pytest tests/ -v

# Start the application
uvicorn main:app --reload
```

## License

Pillar 5 is part of Open-Omniscience and is licensed under the same terms as the main project. See the main repository for license details.

## Support

For support and questions:
- GitHub Issues: https://github.com/ideotion/Open-Omniscience/issues
- Documentation: https://github.com/ideotion/Open-Omniscience/tree/main/pillar5/docs
- Community: Join the Open-Omniscience community

## Changelog

See the main Open-Omniscience repository for release notes and changelog.
