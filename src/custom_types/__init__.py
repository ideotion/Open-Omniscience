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

from typing import Any, Dict, List, Optional, Set, Tuple, Union, TypedDict, TypeVar
from datetime import datetime
from pathlib import Path

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
    scan_config: Dict[str, Any]
    rss_url: Optional[URL]
    sitemap_url: Optional[URL]
    language: Optional[str]
    region: Optional[str]
    country: Optional[str]
    reliability_score: Optional[Score]

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
    scraper: Dict[str, Any]
    api: Dict[str, Any]
    llm: Dict[str, Any]
    logging: Dict[str, Any]

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
    published_at: Optional[Timestamp]
    retrieved_at: Timestamp
    source_domain: Domain
    source_name: str
    language: Optional[str]
    region: Optional[str]
    country: Optional[str]
    author: Optional[str]
    tags: List[str]
    metadata: Dict[str, Any]
    content_hash: ContentHash

class SourceData(TypedDict, total=False):
    """Source data structure."""
    id: SourceID
    domain: Domain
    name: str
    url: Optional[URL]
    rss_url: Optional[URL]
    enabled: bool
    rate_limit_ms: RateLimit
    reliability_score: Optional[Score]
    language: Optional[str]
    region: Optional[str]
    country: Optional[str]
    last_scraped: Optional[Timestamp]
    article_count: int

# =============================================================================
# HTTP and Web Types
# =============================================================================

class HTTPResponse(TypedDict, total=False):
    """HTTP response structure."""
    status_code: int
    content: bytes
    text: str
    headers: Dict[str, str]
    url: URL

class ScrapeResult(TypedDict, total=False):
    """Result of a scraping operation."""
    success: bool
    url: URL
    content: Optional[str]
    error: Optional[str]
    status_code: Optional[int]
    headers: Optional[Dict[str, str]]

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
    confidence: Optional[Confidence]

# =============================================================================
# Analysis Types
# =============================================================================

class AnalysisResult(TypedDict, total=False):
    """Result from analysis operations."""
    article_id: ArticleID
    analysis_type: str
    results: Dict[str, Any]
    score: Optional[Score]
    confidence: Optional[Confidence]
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
    enabled_sources: List[SourceID]

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
JSONData = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

# Type for configuration dictionaries
ConfigDict = Dict[str, Any]

# Type for metadata dictionaries
MetadataDict = Dict[str, Any]

# Type for error information
ErrorInfo = Dict[str, Any]

# Type for result with success/failure
Result = Tuple[bool, T]

# Type for paginated results
PaginatedResult = Dict[str, Union[List[T], int, bool]]

# =============================================================================
# Request/Response Types
# =============================================================================

class APIResponse(TypedDict, total=False):
    """Standard API response structure."""
    success: bool
    data: Optional[Any]
    error: Optional[str]
    message: Optional[str]
    count: Optional[int]
    page: Optional[int]
    total_pages: Optional[int]

class SearchRequest(TypedDict, total=False):
    """Search request structure."""
    query: str
    sources: Optional[List[SourceID]]
    date_from: Optional[ISODateString]
    date_to: Optional[ISODateString]
    language: Optional[str]
    region: Optional[str]
    limit: Optional[int]
    offset: Optional[int]
    sort_by: Optional[str]
    sort_order: Optional[str]

class SearchResponse(TypedDict, total=False):
    """Search response structure."""
    results: List[ArticleData]
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
    date_from: Optional[ISODateString]
    date_to: Optional[ISODateString]
    sources: Optional[List[SourceID]]
    fields: Optional[List[str]]
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
RateLimitConfig = Dict[str, Union[int, float, str]]

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
