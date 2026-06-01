# Pillar 5 - Financial Intelligence API Documentation

## Overview

The Pillar 5 API provides RESTful endpoints for accessing financial data, metrics, and correlation analysis. All endpoints are prefixed with `/api/v1/financial` and return JSON responses.

## Base URL

```
/api/v1/financial
```

## Authentication

Currently, no authentication is required for Pillar 5 endpoints. All data is publicly accessible.

## Response Format

All successful responses follow this structure:

```json
{
  "success": true,
  "data": { ... },
  "message": "Success message"
}
```

Error responses follow this structure:

```json
{
  "success": false,
  "error": "Error type",
  "message": "Error description",
  "details": { ... }
}
```

## Rate Limiting

API endpoints may be rate limited to prevent abuse. Current limits:
- 100 requests per minute per IP address
- 1000 requests per hour per IP address

Rate limit headers:
- `X-RateLimit-Limit`: Total requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Time when limit resets (UTC timestamp)

## Endpoints

### Exchange Endpoints

#### List All Exchanges

**Endpoint:** `GET /exchanges`

**Description:** Retrieve a list of all financial exchanges.

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `exchange_type` | string | Filter by exchange type (stock, forex, crypto, commodity) | No | All types |
| `country` | string | Filter by country | No | All countries |
| `is_active` | boolean | Filter by active status | No | true |
| `limit` | integer | Maximum number of results | No | 100 |
| `offset` | integer | Pagination offset | No | 0 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "code": "NYSE",
      "name": "New York Stock Exchange",
      "country": "United States",
      "city": "New York",
      "timezone": "America/New_York",
      "currency": "USD",
      "website": "https://www.nyse.com",
      "founded_year": 1792,
      "is_active": true,
      "exchange_type": "stock",
      "trading_hours": "09:30-16:00",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    },
    ...
  ],
  "message": "Exchanges retrieved successfully",
  "total": 68,
  "limit": 100,
  "offset": 0
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/exchanges?exchange_type=stock&country=United%20States"
```

#### Get Specific Exchange

**Endpoint:** `GET /exchanges/{exchange_id}`

**Description:** Retrieve details for a specific exchange.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `exchange_id` | integer | Exchange ID | Yes |

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "code": "NYSE",
    "name": "New York Stock Exchange",
    "country": "United States",
    "city": "New York",
    "timezone": "America/New_York",
    "currency": "USD",
    "website": "https://www.nyse.com",
    "founded_year": 1792,
    "is_active": true,
    "exchange_type": "stock",
    "trading_hours": "09:30-16:00",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "message": "Exchange retrieved successfully"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/exchanges/1"
```

#### Discover Exchanges

**Endpoint:** `GET /exchanges/discover`

**Description:** Discover new exchanges from open web sources.

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `force_refresh` | boolean | Force refresh from web sources | No | false |

**Response:**

```json
{
  "success": true,
  "data": {
    "discovered": 5,
    "new_exchanges": [
      {
        "code": "NEW_EXCHANGE",
        "name": "New Exchange Name",
        "country": "Country",
        "exchange_type": "stock"
      },
      ...
    ],
    "existing_exchanges": 68
  },
  "message": "Exchange discovery completed"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/exchanges/discover?force_refresh=true"
```

---

### Instrument Endpoints

#### List All Instruments

**Endpoint:** `GET /instruments`

**Description:** Retrieve a list of all financial instruments.

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `type` | string | Filter by instrument type (stock, etf, index, commodity, forex, crypto) | No | All types |
| `exchange_id` | integer | Filter by exchange ID | No | All exchanges |
| `sector` | string | Filter by sector | No | All sectors |
| `industry` | string | Filter by industry | No | All industries |
| `country` | string | Filter by country | No | All countries |
| `limit` | integer | Maximum number of results | No | 100 |
| `offset` | integer | Pagination offset | No | 0 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "type": "stock",
      "exchange_id": 1,
      "isin": "US0378331005",
      "cusip": "037833100",
      "figi": "BBG000B9XRY4",
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "country": "United States",
      "currency": "USD",
      "description": "Apple Inc. designs, manufactures, and markets...",
      "website": "https://www.apple.com",
      "founded_year": 1976,
      "employees": 165000,
      "headquarters": "Cupertino, California",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    },
    ...
  ],
  "message": "Instruments retrieved successfully",
  "total": 81,
  "limit": 100,
  "offset": 0
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/instruments?type=stock&sector=Technology"
```

#### Get Specific Instrument

**Endpoint:** `GET /instruments/{instrument_id}`

**Description:** Retrieve details for a specific instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "type": "stock",
    "exchange_id": 1,
    "isin": "US0378331005",
    "cusip": "037833100",
    "figi": "BBG000B9XRY4",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "United States",
    "currency": "USD",
    "description": "Apple Inc. designs, manufactures, and markets...",
    "website": "https://www.apple.com",
    "founded_year": 1976,
    "employees": 165000,
    "headquarters": "Cupertino, California",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "message": "Instrument retrieved successfully"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/instruments/1"
```

#### Discover Instruments

**Endpoint:** `GET /instruments/discover`

**Description:** Discover new instruments from open web sources.

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `type` | string | Filter by instrument type | No | All types |
| `exchange_id` | integer | Filter by exchange ID | No | All exchanges |
| `force_refresh` | boolean | Force refresh from web sources | No | false |

**Response:**

```json
{
  "success": true,
  "data": {
    "discovered": 10,
    "new_instruments": [
      {
        "symbol": "NEW_SYMBOL",
        "name": "New Instrument Name",
        "type": "stock",
        "exchange_id": 1
      },
      ...
    ],
    "existing_instruments": 81
  },
  "message": "Instrument discovery completed"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/instruments/discover?type=stock&force_refresh=true"
```

#### Extract Keywords for Instrument

**Endpoint:** `POST /instruments/{instrument_id}/extract-keywords`

**Description:** Extract keywords from an instrument's name, description, and other metadata.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Request Body:**

```json
{
  "text": "Additional text to analyze",
  "force_refresh": false
}
```

**Response:**

```json
{
  "success": true,
  "data": {
    "instrument_id": 1,
    "keywords": [
      {
        "keyword": "technology",
        "weight": 0.8,
        "source": "name",
        "is_primary": true,
        "category": "sector"
      },
      {
        "keyword": "apple",
        "weight": 0.9,
        "source": "name",
        "is_primary": true,
        "category": "company"
      },
      ...
    ],
    "sectors": ["Technology"],
    "industries": ["Consumer Electronics"]
  },
  "message": "Keywords extracted successfully"
}
```

**Example:**

```bash
curl -X POST "http://localhost:8000/api/v1/financial/instruments/1/extract-keywords" \
  -H "Content-Type: application/json" \
  -d '{"text": "Apple is a leading technology company"}'
```

---

### OHLC Endpoints

#### Get OHLC Data

**Endpoint:** `GET /ohlc/{instrument_id}`

**Description:** Retrieve historical OHLC (Open-High-Low-Close) data for an instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `timeframe` | string | Timeframe (1m, 5m, 15m, 30m, 1h, 1d, 1w, 1m) | No | 1d |
| `start_date` | string | Start date (YYYY-MM-DD) | No | 30 days ago |
| `end_date` | string | End date (YYYY-MM-DD) | No | Today |
| `limit` | integer | Maximum number of results | No | 100 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "instrument_id": 1,
      "timestamp": "2024-01-01T00:00:00Z",
      "open_price": 150.0,
      "high_price": 155.0,
      "low_price": 148.0,
      "close_price": 152.5,
      "adjusted_close": 152.3,
      "volume": 1000000,
      "timeframe": "1d",
      "source": "yahoo",
      "is_verified": true,
      "created_at": "2024-01-01T00:00:00Z"
    },
    ...
  ],
  "message": "OHLC data retrieved successfully",
  "total": 30,
  "instrument": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc."
  }
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/ohlc/1?timeframe=1d&start_date=2024-01-01&end_date=2024-01-31"
```

#### Get Latest OHLC Data

**Endpoint:** `GET /ohlc/{instrument_id}/latest`

**Description:** Retrieve the most recent OHLC data point for an instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `timeframe` | string | Timeframe (1m, 5m, 15m, 30m, 1h, 1d, 1w, 1m) | No | 1d |

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "instrument_id": 1,
    "timestamp": "2024-01-31T00:00:00Z",
    "open_price": 150.0,
    "high_price": 155.0,
    "low_price": 148.0,
    "close_price": 152.5,
    "adjusted_close": 152.3,
    "volume": 1000000,
    "timeframe": "1d",
    "source": "yahoo",
    "is_verified": true,
    "created_at": "2024-01-31T00:00:00Z"
  },
  "message": "Latest OHLC data retrieved successfully",
  "instrument": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc."
  }
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/ohlc/1/latest"
```

---

### Fundamentals Endpoints

#### Get Fundamentals

**Endpoint:** `GET /fundamentals/{instrument_id}`

**Description:** Retrieve fundamental data for an instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `timeframe` | string | Timeframe (quarterly, annual) | No | quarterly |

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "instrument_id": 1,
    "timestamp": "2024-01-01T00:00:00Z",
    "timeframe": "quarterly",
    "market_cap": 3000000000000,
    "pe_ratio": 28.5,
    "pb_ratio": 6.2,
    "ps_ratio": 8.1,
    "peg_ratio": 1.8,
    "dividend_yield": 0.005,
    "payout_ratio": 0.25,
    "eps": 4.5,
    "revenue": 394330000000,
    "net_income": 96870000000,
    "ebitda": 119440000000,
    "gross_margin": 0.42,
    "operating_margin": 0.29,
    "net_margin": 0.25,
    "roe": 0.55,
    "roa": 0.18,
    "roi": 0.22,
    "current_ratio": 1.8,
    "quick_ratio": 1.5,
    "debt_to_equity": 0.5,
    "total_debt": 120000000000,
    "total_equity": 240000000000,
    "free_cash_flow": 80000000000,
    "operating_cash_flow": 90000000000,
    "beta": 1.2,
    "volatility_1y": 0.25,
    "volatility_3y": 0.22,
    "sharpe_ratio": 1.5,
    "sortino_ratio": 2.0,
    "alpha": 0.05,
    "source": "yahoo",
    "is_verified": true,
    "created_at": "2024-01-01T00:00:00Z"
  },
  "message": "Fundamentals retrieved successfully",
  "instrument": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc."
  }
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/fundamentals/1"
```

---

### Metrics Endpoints

#### List All Metrics

**Endpoint:** `GET /metrics`

**Description:** Retrieve a list of all pre-computed metrics.

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `instrument_id` | integer | Filter by instrument ID | No | All instruments |
| `group` | string | Filter by metric group (Trend, Momentum, Volatility, Volume, Fundamental, Statistical, Pattern, Custom) | No | All groups |
| `timeframe` | string | Filter by timeframe | No | All timeframes |
| `limit` | integer | Maximum number of results | No | 100 |
| `offset` | integer | Pagination offset | No | 0 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "instrument_id": 1,
      "name": "SMA_20",
      "group": "Trend",
      "value": 150.5,
      "timestamp": "2024-01-01T00:00:00Z",
      "timeframe": "1d",
      "parameters": {"period": 20},
      "source": "calculated",
      "calculation_method": "Simple Moving Average",
      "description": "20-day Simple Moving Average",
      "formula": "SUM(close, 20) / 20",
      "use_case": "Identify trend direction",
      "visualization_type": "line",
      "is_active": true,
      "created_at": "2024-01-01T00:00:00Z"
    },
    ...
  ],
  "message": "Metrics retrieved successfully",
  "total": 80,
  "limit": 100,
  "offset": 0
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/metrics?group=Trend&instrument_id=1"
```

#### Get Specific Metric

**Endpoint:** `GET /metrics/{metric_id}`

**Description:** Retrieve details for a specific metric.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `metric_id` | integer | Metric ID | Yes |

**Response:**

```json
{
  "success": true,
  "data": {
    "id": 1,
    "instrument_id": 1,
    "name": "SMA_20",
    "group": "Trend",
    "value": 150.5,
    "timestamp": "2024-01-01T00:00:00Z",
    "timeframe": "1d",
    "parameters": {"period": 20},
    "source": "calculated",
    "calculation_method": "Simple Moving Average",
    "description": "20-day Simple Moving Average",
    "formula": "SUM(close, 20) / 20",
    "use_case": "Identify trend direction",
    "visualization_type": "line",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z"
  },
  "message": "Metric retrieved successfully"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/metrics/1"
```

#### Get All Metrics for Instrument

**Endpoint:** `GET /metrics/instrument/{instrument_id}`

**Description:** Retrieve all pre-computed metrics for a specific instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `timeframe` | string | Filter by timeframe | No | All timeframes |
| `group` | string | Filter by metric group | No | All groups |
| `recalculate` | boolean | Force recalculation | No | false |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "instrument_id": 1,
      "name": "SMA_20",
      "group": "Trend",
      "value": 150.5,
      "timestamp": "2024-01-01T00:00:00Z",
      "timeframe": "1d",
      "parameters": {"period": 20},
      "source": "calculated",
      "calculation_method": "Simple Moving Average",
      "description": "20-day Simple Moving Average",
      "formula": "SUM(close, 20) / 20",
      "use_case": "Identify trend direction",
      "visualization_type": "line",
      "is_active": true
    },
    ...
  ],
  "message": "Metrics retrieved successfully",
  "total": 80,
  "instrument": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc."
  }
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/metrics/instrument/1"
```

---

### Keywords Endpoints

#### Get Keywords by Instrument

**Endpoint:** `GET /keywords/instrument/{instrument_id}`

**Description:** Retrieve all keywords extracted for a specific instrument.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `instrument_id` | integer | Instrument ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `category` | string | Filter by keyword category (sector, industry, company) | No | All categories |
| `source` | string | Filter by keyword source (name, description, article) | No | All sources |
| `limit` | integer | Maximum number of results | No | 100 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "instrument_id": 1,
      "keyword": "technology",
      "weight": 0.8,
      "source": "name",
      "is_primary": true,
      "category": "sector",
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "id": 2,
      "instrument_id": 1,
      "keyword": "apple",
      "weight": 0.9,
      "source": "name",
      "is_primary": true,
      "category": "company",
      "created_at": "2024-01-01T00:00:00Z"
    },
    ...
  ],
  "message": "Keywords retrieved successfully",
  "total": 10,
  "instrument": {
    "id": 1,
    "symbol": "AAPL",
    "name": "Apple Inc."
  }
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/keywords/instrument/1"
```

---

### Correlations Endpoints

#### Calculate Correlations

**Endpoint:** `POST /correlations/calculate`

**Description:** Calculate correlations between an article and financial instruments.

**Request Body:**

```json
{
  "article_id": 1,
  "article_text": "Apple Inc. stock is performing well in the technology sector. The company reported strong earnings.",
  "instrument_ids": [1, 2, 3],
  "min_score": 0.1,
  "limit": 10
}
```

**Response:**

```json
{
  "success": true,
  "data": {
    "article_id": 1,
    "correlations": [
      {
        "article_id": 1,
        "instrument_id": 1,
        "correlation_score": 0.85,
        "correlation_type": "hybrid",
        "mention_score": 0.9,
        "keyword_score": 0.8,
        "sector_score": 0.7,
        "temporal_score": 0.6,
        "matched_keywords": ["apple", "technology"],
        "matched_sectors": ["Technology"],
        "timestamp": "2024-01-01T00:00:00Z",
        "is_active": true
      },
      ...
    ],
    "total": 3,
    "average_score": 0.75,
    "highest_score": 0.85
  },
  "message": "Correlations calculated successfully"
}
```

**Example:**

```bash
curl -X POST "http://localhost:8000/api/v1/financial/correlations/calculate" \
  -H "Content-Type: application/json" \
  -d '{
    "article_id": 1,
    "article_text": "Apple Inc. stock is performing well in the technology sector.",
    "min_score": 0.1
  }'
```

#### Get Correlations by Article

**Endpoint:** `GET /correlations/article/{article_id}`

**Description:** Retrieve all correlations for a specific article.

**Path Parameters:**

| Parameter | Type | Description | Required |
|-----------|------|-------------|----------|
| `article_id` | integer | Article ID | Yes |

**Query Parameters:**

| Parameter | Type | Description | Required | Default |
|-----------|------|-------------|----------|---------|
| `min_score` | float | Minimum correlation score | No | 0.0 |
| `correlation_type` | string | Filter by correlation type (hybrid, mention, keyword, sector, temporal) | No | All types |
| `limit` | integer | Maximum number of results | No | 100 |

**Response:**

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "article_id": 1,
      "instrument_id": 1,
      "correlation_score": 0.85,
      "correlation_type": "hybrid",
      "mention_score": 0.9,
      "keyword_score": 0.8,
      "sector_score": 0.7,
      "temporal_score": 0.6,
      "matched_keywords": ["apple", "technology"],
      "matched_sectors": ["Technology"],
      "timestamp": "2024-01-01T00:00:00Z",
      "is_active": true,
      "instrument": {
        "id": 1,
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "type": "stock"
      }
    },
    ...
  ],
  "message": "Correlations retrieved successfully",
  "total": 5,
  "article_id": 1
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/correlations/article/1?min_score=0.5"
```

---

### Stats Endpoints

#### Get System Statistics

**Endpoint:** `GET /stats`

**Description:** Retrieve system-wide statistics for Pillar 5.

**Response:**

```json
{
  "success": true,
  "data": {
    "total_exchanges": 68,
    "total_instruments": 81,
    "total_metrics": 80,
    "total_correlations": 150,
    "total_ohlc_data_points": 10000,
    "total_fundamentals": 81,
    "total_keywords": 500,
    "total_analyses": 10,
    "last_updated": "2024-01-01T00:00:00Z",
    "database_size": "10.5 MB",
    "cache_hit_rate": 0.85,
    "average_response_time": 0.15
  },
  "message": "Statistics retrieved successfully"
}
```

**Example:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/stats"
```

---

## Error Codes

| Code | Description | Solution |
|------|-------------|----------|
| 400 | Bad Request | Check request parameters and body |
| 404 | Not Found | Resource does not exist |
| 422 | Validation Error | Check request body validation errors |
| 429 | Too Many Requests | Wait and retry |
| 500 | Internal Server Error | Check server logs |
| 503 | Service Unavailable | Service is temporarily unavailable |

## API Examples

### Python Example

```python
import requests

# Base URL
BASE_URL = "http://localhost:8000/api/v1/financial"

# List all instruments
response = requests.get(f"{BASE_URL}/instruments")
if response.status_code == 200:
    instruments = response.json()["data"]
    for instrument in instruments:
        print(f"{instrument['symbol']}: {instrument['name']}")

# Get OHLC data for AAPL
response = requests.get(f"{BASE_URL}/ohlc/1?timeframe=1d&limit=30")
if response.status_code == 200:
    ohlc_data = response.json()["data"]
    for data_point in ohlc_data:
        print(f"{data_point['timestamp']}: {data_point['close_price']}")

# Calculate correlations
request_data = {
    "article_id": 1,
    "article_text": "Apple stock is rising due to strong earnings in the technology sector."
}
response = requests.post(f"{BASE_URL}/correlations/calculate", json=request_data)
if response.status_code == 200:
    correlations = response.json()["data"]["correlations"]
    for correlation in correlations:
        print(f"{correlation['instrument_id']}: {correlation['correlation_score']}")
```

### JavaScript Example

```javascript
// Base URL
const BASE_URL = "http://localhost:8000/api/v1/financial";

// List all instruments
async function listInstruments() {
    const response = await fetch(`${BASE_URL}/instruments`);
    const data = await response.json();
    if (data.success) {
        data.data.forEach(instrument => {
            console.log(`${instrument.symbol}: ${instrument.name}`);
        });
    }
}

// Get OHLC data for AAPL
async function getOHLC(instrumentId) {
    const response = await fetch(`${BASE_URL}/ohlc/${instrumentId}?timeframe=1d&limit=30`);
    const data = await response.json();
    if (data.success) {
        data.data.forEach(dataPoint => {
            console.log(`${dataPoint.timestamp}: ${dataPoint.close_price}`);
        });
    }
}

// Calculate correlations
async function calculateCorrelations(articleId, articleText) {
    const response = await fetch(`${BASE_URL}/correlations/calculate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            article_id: articleId,
            article_text: articleText
        })
    });
    const data = await response.json();
    if (data.success) {
        data.data.correlations.forEach(correlation => {
            console.log(`${correlation.instrument_id}: ${correlation.correlation_score}`);
        });
    }
}
```

## WebSocket Events (Future)

Pillar 5 will support WebSocket events for real-time updates:

| Event | Description | Data |
|-------|-------------|------|
| `financial:new_instrument` | New instrument discovered | Instrument data |
| `financial:new_ohlc` | New OHLC data available | OHLC data |
| `financial:new_metric` | New metric calculated | Metric data |
| `financial:new_correlation` | New correlation calculated | Correlation data |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-01-01 | Initial release |
