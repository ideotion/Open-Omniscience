"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Common Type Definitions for Open Omniscience

This module provides type aliases and custom types used throughout the application
to improve type safety and code clarity.

Author: Ideotion
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict, TypeVar, Union

# Type variable for generic types
T = TypeVar('T')
from enum import Enum

import requests

# =============================================================================
# Common Type Aliases
# =============================================================================

# Path and File Types
RepoPath = Path
FilePath = Path
DirectoryPath = Path

# String Types
URL = str
Domain = str
Email = str
ContentHash = str
ArticleID = str
SourceID = str

# Numeric Types
RateLimit = int  # in milliseconds
Score = float
Confidence = float  # 0.0 to 1.0

# Date/Time Types
Timestamp = datetime
ISODateString = str

# =============================================================================
# Configuration Types
# =============================================================================

class SourceConfig(TypedDict, total=False):
    """Configuration for a news source."""
    name: str
    domain: Domain
    url: URL
    enabled: bool
    rate_limit_ms: RateLimit
    scan_config: dict[str, Any]
    rss_url: URL | None
    sitemap_url: URL | None
    language: str | None
    region: str | None
    country: str | None
    reliability_score: Score | None

class DatabaseConfig(TypedDict, total=False):
    """Database configuration."""
    url: str
    echo: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int

class AppConfig(TypedDict, total=False):
    """Application configuration."""
    database: DatabaseConfig
    scraper: dict[str, Any]
    api: dict[str, Any]
    llm: dict[str, Any]
    logging: dict[str, Any]

# =============================================================================
# Data Model Types
# =============================================================================

class ArticleData(TypedDict, total=False):
    """Article data structure."""
    id: ArticleID
    url: URL
    canonical_url: URL
    title: str
    content: str
    published_at: Timestamp | None
    retrieved_at: Timestamp
    source_domain: Domain
    source_name: str
    language: str | None
    region: str | None
    country: str | None
    author: str | None
    tags: list[str]
    metadata: dict[str, Any]
    content_hash: ContentHash

class SourceData(TypedDict, total=False):
    """Source data structure."""
    id: SourceID
    domain: Domain
    name: str
    url: URL | None
    rss_url: URL | None
    enabled: bool
    rate_limit_ms: RateLimit
    reliability_score: Score | None
    language: str | None
    region: str | None
    country: str | None
    last_scraped: Timestamp | None
    article_count: int

# =============================================================================
# HTTP and Web Types
# =============================================================================

class HTTPResponse(TypedDict, total=False):
    """HTTP response structure."""
    status_code: int
    content: bytes
    text: str
    headers: dict[str, str]
    url: URL

class ScrapeResult(TypedDict, total=False):
    """Result of a scraping operation."""
    success: bool
    url: URL
    content: str | None
    error: str | None
    status_code: int | None
    headers: dict[str, str] | None

# =============================================================================
# LLM Types
# =============================================================================

class LLMConfig(TypedDict, total=False):
    """LLM configuration."""
    model_name: str
    base_url: URL
    temperature: float
    max_tokens: int
    timeout: int
    auto_download: bool

class LLMResult(TypedDict, total=False):
    """Result from LLM processing."""
    model: str
    prompt: str
    response: str
    tokens_used: int
    processing_time: float
    confidence: Confidence | None

# =============================================================================
# Analysis Types
# =============================================================================

class AnalysisResult(TypedDict, total=False):
    """Result from analysis operations."""
    article_id: ArticleID
    analysis_type: str
    results: dict[str, Any]
    score: Score | None
    confidence: Confidence | None
    processed_at: Timestamp

class SimilarityResult(TypedDict, total=False):
    """Result from similarity analysis."""
    article_id_1: ArticleID
    article_id_2: ArticleID
    similarity_score: Score
    method: str
    processed_at: Timestamp

# =============================================================================
# Pipeline Types
# =============================================================================

class PipelineConfig(TypedDict, total=False):
    """Pipeline configuration."""
    max_workers: int
    batch_size: int
    retry_attempts: int
    timeout: int
    enabled_sources: list[SourceID]

class PipelineStatus(str, Enum):
    """Status of a pipeline operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# =============================================================================
# Utility Types
# =============================================================================

# Type for JSON-compatible data
JSONData = Union[dict[str, Any], list[Any], str, int, float, bool, None]

# Type for configuration dictionaries
ConfigDict = dict[str, Any]

# Type for metadata dictionaries
MetadataDict = dict[str, Any]

# Type for error information
ErrorInfo = dict[str, Any]

# Type for result with success/failure
Result = tuple[bool, T]

# Type for paginated results
PaginatedResult = dict[str, list[T] | int | bool]

# =============================================================================
# Request/Response Types
# =============================================================================

class APIResponse(TypedDict, total=False):
    """Standard API response structure."""
    success: bool
    data: Any | None
    error: str | None
    message: str | None
    count: int | None
    page: int | None
    total_pages: int | None

class SearchRequest(TypedDict, total=False):
    """Search request structure."""
    query: str
    sources: list[SourceID] | None
    date_from: ISODateString | None
    date_to: ISODateString | None
    language: str | None
    region: str | None
    limit: int | None
    offset: int | None
    sort_by: str | None
    sort_order: str | None

class SearchResponse(TypedDict, total=False):
    """Search response structure."""
    results: list[ArticleData]
    total: int
    limit: int
    offset: int
    query: str

# =============================================================================
# Export Types
# =============================================================================

class ExportFormat(str, Enum):
    """Export format options."""
    JSON = "json"
    CSV = "csv"
    XML = "xml"
    HTML = "html"

class ExportRequest(TypedDict, total=False):
    """Export request structure."""
    format: ExportFormat
    date_from: ISODateString | None
    date_to: ISODateString | None
    sources: list[SourceID] | None
    fields: list[str] | None
    include_metadata: bool

# =============================================================================
# Custom Types for Specific Use Cases
# =============================================================================

# Type for URL canonicalization
CanonicalURL = str

# Type for content hashing
ContentHash = str

# Type for domain normalization
NormalizedDomain = str

# Type for article deduplication
DeduplicationKey = str

# Type for rate limiting
RateLimitConfig = dict[str, int | float | str]

# Type for caching
CacheKey = str
CacheValue = Any
CacheTTL = int  # Time to live in seconds

# =============================================================================
# Type Variables for Generic Usage
# =============================================================================

from typing import TypeVar

T = TypeVar('T')
U = TypeVar('U')
V = TypeVar('V')

# =============================================================================
# Helper Functions for Type Checking
# =============================================================================

def is_valid_url(url: str) -> bool:
    """Check if a string is a valid URL."""
    from urllib.parse import urlparse
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def is_valid_domain(domain: str) -> bool:
    """Check if a string is a valid domain."""
    if not domain:
        return False
    # Basic domain validation
    return all(c.isalnum() or c in ('-', '.', '_') for c in domain)

def is_valid_email(email: str) -> bool:
    """Check if a string is a valid email."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

__all__ = [
    # Type aliases
    'RepoPath', 'FilePath', 'DirectoryPath',
    'URL', 'Domain', 'Email', 'ContentHash', 'ArticleID', 'SourceID',
    'RateLimit', 'Score', 'Confidence',
    'Timestamp', 'ISODateString',
    
    # Configuration types
    'SourceConfig', 'DatabaseConfig', 'AppConfig',
    
    # Data model types
    'ArticleData', 'SourceData',
    
    # HTTP and Web types
    'HTTPResponse', 'ScrapeResult',
    
    # LLM types
    'LLMConfig', 'LLMResult',
    
    # Analysis types
    'AnalysisResult', 'SimilarityResult',
    
    # Pipeline types
    'PipelineConfig', 'PipelineStatus',
    
    # Utility types
    'JSONData', 'ConfigDict', 'MetadataDict', 'ErrorInfo',
    'Result', 'PaginatedResult',
    
    # Request/Response types
    'APIResponse', 'SearchRequest', 'SearchResponse',
    
    # Export types
    'ExportFormat', 'ExportRequest',
    
    # Custom types
    'CanonicalURL', 'NormalizedDomain', 'DeduplicationKey',
    'RateLimitConfig', 'CacheKey', 'CacheValue', 'CacheTTL',
    
    # Type variables
    'T', 'U', 'V',
    
    # Helper functions
    'is_valid_url', 'is_valid_domain', 'is_valid_email',
]
