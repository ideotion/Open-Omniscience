# Open-Omniscience API Documentation

> 📚 **Looking for other documentation?** See the [Unified Documentation Index](../DOCUMENTATION.md) for all Open-Omniscience documentation.

**Version:** 2.0  
**Last Updated:** 2025-05-12  
**Author:** Open-Omniscience Team  
**License:** Open Source (MIT)

---

## 📖 Table of Contents

1. [Introduction](#1-introduction)
2. [Authentication](#2-authentication)
3. [Base URL](#3-base-url)
4. [API Endpoints](#4-api-endpoints)
   - [Health & Status](#health--status)
   - [Articles](#articles)
   - [Sources](#sources)
   - [Keywords](#keywords)
   - [Link Analysis](#link-analysis)
   - [LLM Integration](#llm-integration)
5. [Request/Response Examples](#5-requestresponse-examples)
6. [Error Handling](#6-error-handling)
7. [Rate Limiting](#7-rate-limiting)
8. [Pagination](#8-pagination)
9. [Filtering & Search](#9-filtering--search)
10. [Visual Examples](#10-visual-examples)
11. [Postman Collection](#11-postman-collection)
12. [cURL Examples](#12-curl-examples)

---

## 1. Introduction

The Open-Omniscience API provides a comprehensive interface for interacting with the global intelligence platform. This documentation covers all available endpoints, their parameters, request/response formats, and examples.

### 🎯 API Features

- **RESTful Design**: Follows REST conventions
- **JSON Format**: All requests and responses use JSON
- **OpenAPI Support**: Auto-generated OpenAPI/Swagger documentation
- **Rate Limiting**: Built-in rate limiting for API protection
- **CORS Support**: Cross-origin resource sharing enabled
- **Error Handling**: Consistent error responses

### 📊 API Overview

| Category | Endpoints | Description |
|----------|-----------|-------------|
| Health | 3 | Service health checks |
| Articles | 2 | Article search and export |
| Sources | 15+ | Source management |
| Keywords | 8 | Keyword extraction and analysis |
| Link Analysis | 12 | Link classification and analysis |
| LLM | 8 | Large language model integration |

**Total Endpoints:** 50+

---

## 2. Authentication

**⚠️ IMPORTANT:** The API currently does not require authentication by default. For production deployments, you MUST implement authentication.

### 2.1 Authentication Methods

#### Method A: JWT Authentication (Recommended)

**Endpoint:** `POST /token`

**Request:**
```json
{
  "username": "your_username",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Usage:**
```bash
# Get token
curl -X POST "https://yourdomain.com/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=your_username&password=your_password"

# Use token
curl -X GET "https://yourdomain.com/api/articles" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### Method B: API Key Authentication

**Header:** `X-API-Key: your_api_key`

**Usage:**
```bash
curl -X GET "https://yourdomain.com/api/articles" \
  -H "X-API-Key: your_api_key"
```

### 2.2 Authentication Setup

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md#6-authentication-setup) for implementation details.

---

## 3. Base URL

### Development
```
http://localhost:8000
```

### Production
```
https://yourdomain.com
```

### API Base Path
```
/api
```

---

## 4. API Endpoints

---

## 🏥 Health & Status

### GET /api/llm/health

**Description:** Check the health of the LLM service

**Parameters:** None

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-05-12T12:00:00Z",
  "version": "0.03",
  "services": {
    "database": "healthy",
    "llm": "degraded"  // Degraded if Ollama not installed
  }
}
```

**Status Codes:**
- `200 OK`: Service is healthy
- `503 Service Unavailable`: Service is down

---

### GET /api/llm/models

**Description:** List available LLM models

**Parameters:** None

**Response:**
```json
{
  "models": [
    {
      "name": "llama3",
      "size": "8B",
      "download_url": "https://ollama.ai/library/llama3",
      "downloaded": false
    },
    {
      "name": "mistral",
      "size": "7B",
      "download_url": "https://ollama.ai/library/mistral",
      "downloaded": false
    }
  ],
  "total": 2,
  "downloaded_count": 0
}
```

---

### GET /api/llm/capabilities

**Description:** Get LLM service capabilities

**Parameters:** None

**Response:**
```json
{
  "capabilities": [
    "text_generation",
    "text_analysis",
    "translation",
    "summarization",
    "chat"
  ],
  "llm_installed": false,
  "ollama_version": null
}
```

---

## 📰 Articles

### GET /api/articles

**Description:** Search and list articles

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | No | null | Search query |
| `source` | string | No | null | Filter by source |
| `limit` | integer | No | 100 | Maximum results |
| `offset` | integer | No | 0 | Pagination offset |
| `published_after` | string | No | null | Filter by publish date (ISO format) |
| `published_before` | string | No | null | Filter by publish date (ISO format) |

**Response:**
```json
{
  "articles": [
    {
      "id": 1,
      "url": "https://example.com/article1",
      "canonical_url": "https://example.com/article1",
      "title": "Example Article",
      "content": "This is the content of the article...",
      "hash": "a1b2c3d4e5f6...",
      "published_at": "2025-05-12T10:00:00Z",
      "created_at": "2025-05-12T10:00:00Z",
      "language": "en",
      "region": "global",
      "country": "US",
      "author": "John Doe",
      "source": {
        "id": 1,
        "name": "Example News",
        "domain": "example.com"
      }
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/articles/export

**Description:** Export articles in various formats

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `format` | string | No | "csv" | Export format (csv, json, xml) |
| `query` | string | No | null | Search query |
| `source` | string | No | null | Filter by source |
| `limit` | integer | No | 1000 | Maximum results |

**Response:**
- For `format=csv`: CSV file download
- For `format=json`: JSON array of articles
- For `format=xml`: XML file download

**Example Response (JSON):**
```json
[
  {
    "id": 1,
    "url": "https://example.com/article1",
    "title": "Example Article",
    "content": "This is the content...",
    "published_at": "2025-05-12T10:00:00Z"
  }
]
```

---

## 📡 Sources

### GET /api/sources

**Description:** List all configured sources

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `enabled` | boolean | No | null | Filter by enabled status |
| `priority` | integer | No | null | Filter by priority |
| `tags` | string | No | null | Filter by tags (comma-separated) |
| `limit` | integer | No | 100 | Maximum results |
| `offset` | integer | No | 0 | Pagination offset |

**Response:**
```json
{
  "sources": [
    {
      "id": 1,
      "name": "BBC News",
      "domain": "bbc.com",
      "rss_url": "https://feeds.bbci.co.uk/news/rss.xml",
      "rate_limit_ms": 2000,
      "enabled": true,
      "priority": 1,
      "tags": "news,uk,international",
      "reliability_score": 9,
      "language": "en",
      "region": "global",
      "country": "GB",
      "source_type": "news",
      "update_frequency": 30,
      "cacheability": true,
      "created_at": "2025-05-12T08:00:00Z",
      "updated_at": "2025-05-12T08:00:00Z"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/sources/{source_id}

**Description:** Get details of a specific source

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_id` | integer | Yes | Source ID |

**Response:**
```json
{
  "id": 1,
  "name": "BBC News",
  "domain": "bbc.com",
  "rss_url": "https://feeds.bbci.co.uk/news/rss.xml",
  "rate_limit_ms": 2000,
  "enabled": true,
  "priority": 1,
  "tags": "news,uk,international",
  "reliability_score": 9,
  "language": "en",
  "region": "global",
  "country": "GB",
  "source_type": "news",
  "update_frequency": 30,
  "cacheability": true,
  "article_count": 42,
  "last_scraped_at": "2025-05-12T11:00:00Z",
  "created_at": "2025-05-12T08:00:00Z",
  "updated_at": "2025-05-12T08:00:00Z"
}
```

---

### POST /api/sources

**Description:** Create a new source

**Request Body:**
```json
{
  "name": "New Source",
  "domain": "newsource.com",
  "rss_url": "https://newsource.com/rss.xml",
  "rate_limit_ms": 2000,
  "enabled": true,
  "priority": 2,
  "tags": "news,technology",
  "reliability_score": 7,
  "language": "en",
  "region": "global",
  "country": "US",
  "source_type": "news",
  "update_frequency": 60,
  "cacheability": true
}
```

**Response:**
```json
{
  "id": 2,
  "name": "New Source",
  "domain": "newsource.com",
  "rss_url": "https://newsource.com/rss.xml",
  "rate_limit_ms": 2000,
  "enabled": true,
  "priority": 2,
  "tags": "news,technology",
  "reliability_score": 7,
  "language": "en",
  "region": "global",
  "country": "US",
  "source_type": "news",
  "update_frequency": 60,
  "cacheability": true,
  "created_at": "2025-05-12T12:00:00Z",
  "updated_at": "2025-05-12T12:00:00Z"
}
```

---

### PUT /api/sources/{source_id}

**Description:** Update an existing source

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_id` | integer | Yes | Source ID |

**Request Body:**
```json
{
  "name": "Updated Source",
  "domain": "updatedsource.com",
  "priority": 1,
  "enabled": true
}
```

**Response:**
```json
{
  "id": 1,
  "name": "Updated Source",
  "domain": "updatedsource.com",
  "rss_url": "https://updatedsource.com/rss.xml",
  "rate_limit_ms": 2000,
  "enabled": true,
  "priority": 1,
  "tags": "news,technology",
  "reliability_score": 7,
  "language": "en",
  "region": "global",
  "country": "US",
  "source_type": "news",
  "update_frequency": 60,
  "cacheability": true,
  "created_at": "2025-05-12T08:00:00Z",
  "updated_at": "2025-05-12T12:30:00Z"
}
```

---

### DELETE /api/sources/{source_id}

**Description:** Delete a source

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_id` | integer | Yes | Source ID |

**Response:**
```json
{
  "message": "Source deleted successfully",
  "id": 1
}
```

---

## 🔑 Keywords

### GET /api/keywords/extract

**Description:** Extract keywords from text

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `text` | string | Yes | - | Text to extract keywords from |
| `language` | string | No | "en" | Language code |
| `limit` | integer | No | 10 | Maximum keywords to return |

**Response:**
```json
{
  "keywords": [
    {
      "term": "artificial intelligence",
      "normalized_term": "artificial intelligence",
      "relevance_score": 0.95,
      "frequency": 5,
      "is_entity": true,
      "entity_type": "technology"
    },
    {
      "term": "machine learning",
      "normalized_term": "machine learning",
      "relevance_score": 0.92,
      "frequency": 4,
      "is_entity": true,
      "entity_type": "technology"
    }
  ],
  "total": 2,
  "language": "en"
}
```

---

### GET /api/keywords/categories

**Description:** List all keyword categories

**Parameters:** None

**Response:**
```json
{
  "categories": [
    {
      "id": 1,
      "name": "Technology",
      "description": "Technology-related keywords",
      "color": "#2563eb",
      "is_active": true,
      "keyword_count": 42
    },
    {
      "id": 2,
      "name": "Politics",
      "description": "Politics-related keywords",
      "color": "#7c3aed",
      "is_active": true,
      "keyword_count": 35
    }
  ],
  "total": 2
}
```

---

### GET /api/keywords/categorize

**Description:** Categorize a list of keywords

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `keywords` | string | Yes | Comma-separated list of keywords |

**Response:**
```json
{
  "categorization": {
    "artificial intelligence": ["Technology", "Science"],
    "machine learning": ["Technology", "Science"],
    "politics": ["Politics", "Government"]
  }
}
```

---

### GET /api/keywords/top

**Description:** Get top keywords by frequency

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 10 | Number of top keywords |
| `category` | string | No | null | Filter by category |
| `period` | string | No | "7d" | Time period (1d, 7d, 30d, all) |

**Response:**
```json
{
  "keywords": [
    {
      "term": "artificial intelligence",
      "frequency": 156,
      "rank": 1,
      "category": "Technology"
    },
    {
      "term": "machine learning",
      "frequency": 142,
      "rank": 2,
      "category": "Technology"
    }
  ],
  "total": 2,
  "period": "7d"
}
```

---

## 🔗 Link Analysis

### GET /api/link-analysis/health

**Description:** Check link analysis service health

**Parameters:** None

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-05-12T12:00:00Z",
  "services": {
    "link_classifier": "healthy",
    "source_identifier": "healthy",
    "anomaly_detector": "healthy"
  }
}
```

---

### POST /api/link-analysis/extract-links

**Description:** Extract links from text or URL

**Request Body:**
```json
{
  "text": "Check out this article at https://example.com and also visit https://another.com",
  "url": null
}
```

**Response:**
```json
{
  "links": [
    {
      "url": "https://example.com",
      "domain": "example.com",
      "classification": "source",
      "confidence": 0.95,
      "is_internal": false
    },
    {
      "url": "https://another.com",
      "domain": "another.com",
      "classification": "source",
      "confidence": 0.92,
      "is_internal": false
    }
  ],
  "total": 2,
  "internal_count": 0,
  "external_count": 2
}
```

---

### POST /api/link-analysis/classify-links

**Description:** Classify a list of links

**Request Body:**
```json
{
  "links": [
    "https://example.com",
    "https://twitter.com/user",
    "https://facebook.com/page"
  ]
}
```

**Response:**
```json
{
  "classifications": [
    {
      "url": "https://example.com",
      "classification": "source",
      "confidence": 0.95,
      "reason": "News website"
    },
    {
      "url": "https://twitter.com/user",
      "classification": "social",
      "confidence": 0.98,
      "reason": "Twitter profile"
    },
    {
      "url": "https://facebook.com/page",
      "classification": "social",
      "confidence": 0.98,
      "reason": "Facebook page"
    }
  ]
}
```

---

## 🤖 LLM Integration

### POST /api/llm/generate

**Description:** Generate text using LLM

**Request Body:**
```json
{
  "prompt": "Explain artificial intelligence in simple terms",
  "model": "llama3",
  "temperature": 0.7,
  "max_tokens": 512,
  "stream": false
}
```

**Response:**
```json
{
  "generated_text": "Artificial Intelligence (AI) is the simulation of human intelligence...",
  "model": "llama3",
  "tokens_generated": 45,
  "generation_time": 2.5,
  "finish_reason": "stop"
}
```

**Note:** Requires Ollama to be installed and running.

---

### POST /api/llm/chat

**Description:** Chat with LLM

**Request Body:**
```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "What is AI?"
    }
  ],
  "model": "llama3",
  "temperature": 0.7,
  "max_tokens": 512
}
```

**Response:**
```json
{
  "response": "Artificial Intelligence, or AI, refers to the simulation of human intelligence...",
  "model": "llama3",
  "tokens_generated": 38,
  "generation_time": 2.1
}
```

---

### POST /api/llm/analyze

**Description:** Analyze text using LLM

**Request Body:**
```json
{
  "text": "This is a sample text to analyze. It contains some information about AI.",
  "analysis_type": "summary",
  "model": "llama3"
}
```

**Analysis Types:**
- `summary`: Summarize the text
- `sentiment`: Analyze sentiment
- `entities`: Extract entities
- `keywords`: Extract keywords
- `classification`: Classify text

**Response:**
```json
{
  "analysis_type": "summary",
  "result": "This text discusses artificial intelligence and provides a brief overview.",
  "model": "llama3",
  "confidence": 0.92
}
```

---

## 5. Request/Response Examples

### Example 1: Search Articles

**Request:**
```bash
curl -X GET "https://yourdomain.com/api/articles?query=artificial intelligence&limit=5"
```

**Response:**
```json
{
  "articles": [
    {
      "id": 1,
      "url": "https://example.com/ai-overview",
      "title": "Artificial Intelligence: A Comprehensive Overview",
      "content": "AI is transforming industries...",
      "hash": "a1b2c3d4e5f6...",
      "published_at": "2025-05-10T08:00:00Z",
      "source": {
        "id": 1,
        "name": "Tech News"
      }
    }
  ],
  "total": 1,
  "limit": 5,
  "offset": 0
}
```

---

### Example 2: Create Source

**Request:**
```bash
curl -X POST "https://yourdomain.com/api/sources" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TechCrunch",
    "domain": "techcrunch.com",
    "rss_url": "https://techcrunch.com/feed/",
    "priority": 1,
    "enabled": true
  }'
```

**Response:**
```json
{
  "id": 2,
  "name": "TechCrunch",
  "domain": "techcrunch.com",
  "rss_url": "https://techcrunch.com/feed/",
  "rate_limit_ms": 2000,
  "enabled": true,
  "priority": 1,
  "tags": null,
  "reliability_score": 5,
  "language": "en",
  "region": "global",
  "country": "US",
  "source_type": "news",
  "update_frequency": 60,
  "cacheability": true,
  "created_at": "2025-05-12T12:00:00Z",
  "updated_at": "2025-05-12T12:00:00Z"
}
```

---

### Example 3: Extract Keywords

**Request:**
```bash
curl -X GET "https://yourdomain.com/api/keywords/extract?text=Artificial intelligence and machine learning are transforming industries&limit=3"
```

**Response:**
```json
{
  "keywords": [
    {
      "term": "artificial intelligence",
      "normalized_term": "artificial intelligence",
      "relevance_score": 0.95,
      "frequency": 1,
      "is_entity": true,
      "entity_type": "technology"
    },
    {
      "term": "machine learning",
      "normalized_term": "machine learning",
      "relevance_score": 0.92,
      "frequency": 1,
      "is_entity": true,
      "entity_type": "technology"
    },
    {
      "term": "transforming industries",
      "normalized_term": "transforming industries",
      "relevance_score": 0.85,
      "frequency": 1,
      "is_entity": false,
      "entity_type": null
    }
  ],
  "total": 3,
  "language": "en"
}
```

---

## 6. Error Handling

### Error Response Format

All error responses follow this format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {
      "field": "specific error details"
    }
  },
  "status": HTTP_STATUS_CODE,
  "timestamp": "2025-05-12T12:00:00Z"
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request validation failed |
| `UNAUTHORIZED` | 401 | Authentication required |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Internal server error |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

### Example Error Responses

#### 400 Bad Request (Validation Error)

**Request:**
```bash
curl -X POST "https://yourdomain.com/api/sources" \
  -H "Content-Type: application/json" \
  -d '{"name": ""}'
```

**Response:**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "details": {
      "name": "This field is required"
    }
  },
  "status": 400,
  "timestamp": "2025-05-12T12:00:00Z"
}
```

---

#### 404 Not Found

**Request:**
```bash
curl -X GET "https://yourdomain.com/api/sources/9999"
```

**Response:**
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Source with ID 9999 not found",
    "details": {}
  },
  "status": 404,
  "timestamp": "2025-05-12T12:00:00Z"
}
```

---

#### 429 Too Many Requests

**Request:**
```bash
# Make too many requests in a short time
for i in {1..101}; do curl -X GET "https://yourdomain.com/api/articles"; done
```

**Response:**
```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Please try again later.",
    "details": {
      "limit": "100/minute",
      "retry_after": 60
    }
  },
  "status": 429,
  "timestamp": "2025-05-12T12:00:00Z"
}
```

---

## 7. Rate Limiting

### Configuration

Rate limiting is configured via environment variables:

```bash
# In .env file
RATE_LIMIT=100/minute
```

### Rate Limit Headers

All responses include rate limit information:

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 30
```

### Rate Limit Types

| Endpoint | Rate Limit | Description |
|----------|------------|-------------|
| `/api/*` | 100/minute | General API endpoints |
| `/api/llm/*` | 10/minute | LLM endpoints (resource-intensive) |
| `/metrics` | 60/minute | Monitoring endpoint |

---

## 8. Pagination

### Pagination Parameters

Most list endpoints support pagination:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 100 | Maximum results per page |
| `offset` | integer | No | 0 | Offset from first result |

### Pagination Response

```json
{
  "items": [...],
  "total": 1000,
  "limit": 100,
  "offset": 0,
  "pages": 10,
  "current_page": 1
}
```

### Pagination Example

**Request:**
```bash
# Get first page
curl -X GET "https://yourdomain.com/api/sources?limit=10&offset=0"

# Get second page
curl -X GET "https://yourdomain.com/api/sources?limit=10&offset=10"
```

---

## 9. Filtering & Search

### Filtering

Most endpoints support filtering:

**Example:**
```bash
# Filter sources by enabled status
curl -X GET "https://yourdomain.com/api/sources?enabled=true"

# Filter sources by priority
curl -X GET "https://yourdomain.com/api/sources?priority=1"

# Filter sources by tags
curl -X GET "https://yourdomain.com/api/sources?tags=news,technology"
```

### Search

Search endpoints support various query parameters:

**Example:**
```bash
# Search articles
curl -X GET "https://yourdomain.com/api/articles?query=artificial intelligence"

# Search with date range
curl -X GET "https://yourdomain.com/api/articles?query=AI&published_after=2025-01-01&published_before=2025-05-12"

# Full-text search
curl -X GET "https://yourdomain.com/api/sources/search?q=news"
```

### Advanced Search

Use special operators for advanced searches:

| Operator | Example | Description |
|----------|---------|-------------|
| `AND` | `AI AND machine` | Both terms must match |
| `OR` | `AI OR machine` | Either term must match |
| `NOT` | `AI NOT robot` | Exclude term |
| `""` | `"machine learning"` | Exact phrase |
| `*` | `learn*` | Wildcard |

**Example:**
```bash
curl -X GET "https://yourdomain.com/api/articles?query=AI AND (machine OR deep) NOT robot"
```

---

## 10. Visual Examples

### 📸 Screenshot Guidance

While we cannot include actual screenshots in this text-based documentation, here are descriptions of what you should see and how to capture them.

#### How to Capture API Responses

**Using cURL with Output to File:**
```bash
# Save response to file
curl -X GET "https://yourdomain.com/api/sources" -o api_response.json

# Format JSON output
curl -X GET "https://yourdomain.com/api/sources" | jq '.' > formatted_response.json
```

**Using Browser Developer Tools:**
1. Open browser developer tools (F12)
2. Go to Network tab
3. Make API request
4. Right-click on request → Copy → Copy as cURL
5. Or screenshot the response

#### Expected API Response Screens

##### 1. Successful API Response

**Description:** JSON response from API

**What to Capture:**
- Browser showing JSON response
- Or terminal output from cURL

**Example Command:**
```bash
curl -X GET "https://yourdomain.com/api/sources?limit=5" | jq '.'
```

**Screenshot Suggestion:** Capture the formatted JSON output.

##### 2. API Documentation (Swagger UI)

**Description:** Interactive API documentation

**URL:** `https://yourdomain.com/docs`

**What to Capture:**
- Swagger UI showing all endpoints
- Try it out button and response

**Screenshot Suggestion:** Capture the Swagger UI with an endpoint expanded.

##### 3. API Response in Browser

**Description:** Raw JSON response in browser

**URL:** `https://yourdomain.com/api/sources`

**What to Capture:**
- Browser window showing JSON
- Or use a JSON viewer extension

**Screenshot Suggestion:** Capture the browser window with JSON formatted.

##### 4. Postman Collection

**Description:** API collection in Postman

**What to Capture:**
- Postman showing request/response
- Collection folder structure

**Screenshot Suggestion:** Capture Postman with a request and response visible.

### 🎨 Visual Documentation Template

When creating visual documentation, use this template:

```markdown
### [Endpoint Name]

**Method:** GET/POST/PUT/DELETE
**URL:** `/api/endpoint`

**Screenshot:**
![Description of API response](path/to/screenshot.png)

**Caption:** Example response from the [endpoint] showing [description].

**Request:**
```bash
curl command here
```

**Response:**
```json
{
  "example": "response"
}
```

**Notes:**
- Additional information about the endpoint
- Common use cases
- Error scenarios
```

### 📐 Architecture Diagram

```mermaid
graph TD
    A[Client] -->|Request| B[Nginx]
    B -->|Proxy| C[API Service]
    C -->|Query| D[PostgreSQL]
    C -->|Cache| E[Redis]
    C -->|LLM| F[Ollama]
    G[Prometheus] -->|Scrape| C
    H[Grafana] -->|Query| G
    
    style A fill:#f9f,stroke:#333
    style B fill:#bbf,stroke:#333
    style C fill:#9f9,stroke:#333
    style D fill:#f96,stroke:#333
    style E fill:#f66,stroke:#333
    style F fill:#69f,stroke:#333
    style G fill:#fc6,stroke:#333
    style H fill:#cf6,stroke:#333
```

This diagram shows the complete architecture with color-coded components.

---

## 11. Postman Collection

### Import Postman Collection

1. Download or create a Postman collection
2. Import the JSON file into Postman
3. Configure environment variables

### Sample Postman Collection Structure

```json
{
  "info": {
    "_postman_id": "unique-id",
    "name": "Open-Omniscience API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Health",
      "item": [
        {
          "name": "Health Check",
          "request": {
            "method": "GET",
            "header": [],
            "url": {
              "raw": "{{base_url}}/api/llm/health",
              "host": ["{{base_url}}"],
              "path": ["api", "llm", "health"]
            }
          }
        }
      ]
    },
    {
      "name": "Articles",
      "item": [
        {
          "name": "List Articles",
          "request": {
            "method": "GET",
            "header": [],
            "url": {
              "raw": "{{base_url}}/api/articles?query={{query}}&limit={{limit}}",
              "host": ["{{base_url}}"],
              "path": ["api", "articles"],
              "query": [
                {"key": "query", "value": "{{query}}"},
                {"key": "limit", "value": "{{limit}}"}
              ]
            }
          }
        }
      ]
    }
  ],
  "variable": [
    {
      "key": "base_url",
      "value": "http://localhost:8000",
      "type": "default"
    },
    {
      "key": "query",
      "value": "test",
      "type": "default"
    },
    {
      "key": "limit",
      "value": "10",
      "type": "default"
    }
  ]
}
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `base_url` | API base URL | `https://yourdomain.com` |
| `api_key` | API key (if used) | `your_api_key` |
| `username` | Username (if used) | `admin` |
| `password` | Password (if used) | `password` |

---

## 12. cURL Examples

### Health Check

```bash
# Simple health check
curl -I https://yourdomain.com/api/llm/health

# With verbose output
curl -v https://yourdomain.com/api/llm/health

# Save response to file
curl -o health.json https://yourdomain.com/api/llm/health
```

---

### Articles

```bash
# List all articles
curl -X GET "https://yourdomain.com/api/articles"

# Search articles
curl -X GET "https://yourdomain.com/api/articles?query=AI"

# Search with pagination
curl -X GET "https://yourdomain.com/api/articles?query=AI&limit=10&offset=0"

# Export articles as JSON
curl -X GET "https://yourdomain.com/api/articles/export?format=json" -o articles.json
```

---

### Sources

```bash
# List all sources
curl -X GET "https://yourdomain.com/api/sources"

# Get specific source
curl -X GET "https://yourdomain.com/api/sources/1"

# Create source
curl -X POST "https://yourdomain.com/api/sources" \
  -H "Content-Type: application/json" \
  -d '{"name": "New Source", "domain": "new.com", "priority": 1}'

# Update source
curl -X PUT "https://yourdomain.com/api/sources/1" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated Source"}'

# Delete source
curl -X DELETE "https://yourdomain.com/api/sources/1"
```

---

### Keywords

```bash
# Extract keywords
curl -X GET "https://yourdomain.com/api/keywords/extract?text=Sample text here"

# Get top keywords
curl -X GET "https://yourdomain.com/api/keywords/top?limit=5"

# Categorize keywords
curl -X GET "https://yourdomain.com/api/keywords/categorize?keywords=AI,ML,tech"
```

---

### Link Analysis

```bash
# Extract links
curl -X POST "https://yourdomain.com/api/link-analysis/extract-links" \
  -H "Content-Type: application/json" \
  -d '{"text": "Visit https://example.com for more info"}'

# Classify links
curl -X POST "https://yourdomain.com/api/link-analysis/classify-links" \
  -H "Content-Type: application/json" \
  -d '{"links": ["https://example.com", "https://twitter.com"]}'
```

---

### LLM

```bash
# Generate text
curl -X POST "https://yourdomain.com/api/llm/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain AI", "model": "llama3"}'

# Chat
curl -X POST "https://yourdomain.com/api/llm/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is AI?"}]}'

# Analyze text
curl -X POST "https://yourdomain.com/api/llm/analyze" \
  -H "Content-Type: application/json" \
  -d '{"text": "Sample text", "analysis_type": "summary"}'
```

---

## 📚 Additional Resources

### Official Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OpenAPI Specification](https://spec.openapis.org/oas/v3.0.3)
- [JSON:API Specification](https://jsonapi.org/)

### API Testing Tools
- [Postman](https://www.postman.com/)
- [Insomnia](https://insomnia.rest/)
- [cURL](https://curl.se/)
- [httpie](https://httpie.io/)

### API Design Resources
- [REST API Tutorial](https://www.restapitutorial.com/)
- [API Design Best Practices](https://github.com/goldbergyoni/nodebestpractices#1-project-structure-practices)
- [OpenAPI Tools](https://openapi.tools/)

---

## 🔒 Security Notes

### API Security Best Practices

1. **Always use HTTPS** in production
2. **Implement authentication** (JWT, API keys, or OAuth2)
3. **Validate all inputs** on the server side
4. **Use rate limiting** to prevent abuse
5. **Sanitize outputs** to prevent XSS
6. **Use parameterized queries** to prevent SQL injection
7. **Keep secrets secure** (never in code or version control)

### Security Headers

The API includes the following security headers:

```http
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self';
```

---

## 📄 License

This API documentation is licensed under the **MIT License**, the same as the Open-Omniscience project itself.

---

## 🙏 Contributing

If you find issues with this API documentation or have suggestions for improvements:

1. Open an issue on [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)
2. Submit a pull request with your improvements
3. Join the discussion on [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions)

---

**Documentation Version:** 2.0  
**Last Updated:** 2025-05-12  
**Maintainer:** Open-Omniscience Team
