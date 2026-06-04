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
Database Models for Open Omniscience

This module defines the SQLAlchemy models for the database,
supporting both SQLite (default) and PostgreSQL.
Includes tables for sources and articles, with relationships and indexes.

Author: Ideotion
"""

import os
from contextlib import contextmanager
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import declarative_base, relationship

# Engine, session lifecycle, and the FastAPI dependency live in session.py and
# have NO import-time side effects (no create_all, no monitoring thread). They are
# re-exported here because much existing code does
# `from src.database.models import get_session` etc.
from src.database.session import (  # noqa: E402
    Session,
    SessionLocal,
    close_session,
    dispose_engine,
    engine,
    get_db,
    get_session,
    init_db,
    session_scope,
)

# =============================================================================
# Compressed Text Type for SQLAlchemy
# =============================================================================

class CompressedText(TypeDecorator):
    """
    SQLAlchemy type decorator for storing compressed text.
    
    This type automatically compresses text data before storing it in the database
    and decompresses it when retrieving. This is particularly useful for large text
    fields like article content, where compression can significantly reduce storage
    requirements.
    
    Usage:
        class Article(Base):
            content = Column(CompressedText)
    """
    
    impl = LargeBinary
    cache_ok = True
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the CompressedText type.
        
        Args:
            *args: Positional arguments passed to TypeDecorator.
            **kwargs: Keyword arguments passed to TypeDecorator.
        """
        super().__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from src.utils.compression import database_compressor
        self.compressor = database_compressor
    
    def process_bind_param(self, value: str | bytes | None, dialect: Any) -> bytes | None:
        """
        Process the value before storing in the database.
        
        Args:
            value: The value to compress.
            dialect: The database dialect.
            
        Returns:
            Compressed value as bytes, or None.
        """
        if value is None:
            return None
        
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        
        # Compress the text
        return self.compressor.compress_text_for_storage(value)
    
    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        """
        Process the value after retrieving from the database.
        
        Args:
            value: The compressed value from the database.
            dialect: The database dialect.
            
        Returns:
            Decompressed value as string, or None.
        """
        if value is None:
            return None
        
        # Decompress the text
        return self.compressor.decompress_text_from_storage(value)
    
    def copy(self, *args: Any, **kwargs: Any) -> "CompressedText":
        """Create a copy of this type."""
        return CompressedText(*args, **kwargs)


# =============================================================================
# Compressed JSON Type for SQLAlchemy
# =============================================================================

class CompressedJSON(TypeDecorator):
    """
    SQLAlchemy type decorator for storing compressed JSON data.
    
    This type automatically serializes Python objects to JSON, compresses them,
    and stores them in the database. When retrieving, it decompresses and deserializes
    the JSON back to Python objects.
    
    Usage:
        class Article(Base):
            metadata = Column(CompressedJSON)
    """
    
    impl = LargeBinary
    cache_ok = True
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the CompressedJSON type."""
        super().__init__(*args, **kwargs)
        import json

        from src.utils.compression import database_compressor
        self.json = json
        self.compressor = database_compressor
    
    def process_bind_param(self, value: Any, dialect: Any) -> bytes | None:
        """
        Process the value before storing in the database.
        
        Args:
            value: The Python object to serialize and compress.
            dialect: The database dialect.
            
        Returns:
            Compressed JSON as bytes, or None.
        """
        if value is None:
            return None
        
        # Serialize to JSON
        json_str = self.json.dumps(value, ensure_ascii=False, default=str)
        
        # Compress the JSON string
        return self.compressor.compress_text_for_storage(json_str)
    
    def process_result_value(self, value: bytes | None, dialect: Any) -> Any:
        """
        Process the value after retrieving from the database.
        
        Args:
            value: The compressed JSON from the database.
            dialect: The database dialect.
            
        Returns:
            Deserialized Python object, or None.
        """
        if value is None:
            return None
        
        # Decompress the JSON string
        json_str = self.compressor.decompress_text_from_storage(value)
        
        # Deserialize from JSON
        return self.json.loads(json_str)
    
    def copy(self, *args: Any, **kwargs: Any) -> "CompressedJSON":
        """Create a copy of this type."""
        return CompressedJSON(*args, **kwargs)


# =============================================================================
# Database Configuration Utilities
# =============================================================================

# Base class for declarative models
Base = declarative_base()


# Association table for many-to-many relationship between Source and SourceGroup
source_group_association = Table(
    'source_group_association',
    Base.metadata,
    Column('source_id', Integer, ForeignKey('sources.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('source_groups.id'), primary_key=True),
    Column('added_at', DateTime, default=lambda: datetime.now(UTC)),
    # Indexes for performance
    Index('idx_source_group_source_id', 'source_id'),
    Index('idx_source_group_group_id', 'group_id'),
)


class SourceGroup(Base):
    """
    Represents a group of sources for organizational purposes.
    
    Groups allow users to categorize and manage sources in bulk.
    Sources can belong to multiple groups.
    
    Attributes:
        id: Primary key.
        name: Name of the group (e.g., "Technology News", "Financial Sources").
        description: Description of the group's purpose.
        color: Color code for UI display (e.g., "#FF5733").
        is_tag_based: Whether this group is automatically populated based on source tags.
        tag_pattern: Tag pattern for auto-population (e.g., "technology,tech").
        priority: Default priority for sources in this group.
        rate_limit_ms: Default rate limit for sources in this group.
        enabled: Whether sources in this group are enabled by default.
        created_at: Timestamp when the group was created.
        updated_at: Timestamp when the group was last updated.
        sources: Relationship to Source model (many-to-many).
    """
    __tablename__ = "source_groups"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    color = Column(String(20), default="#666666")
    is_tag_based = Column(Boolean, default=False)
    tag_pattern = Column(String(500))  # Comma-separated tags for auto-population
    priority = Column(Integer, default=2)
    rate_limit_ms = Column(Integer, default=2000)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Many-to-many relationship with sources
    sources = relationship(
        "Source",
        secondary=source_group_association,
        back_populates="groups",
        lazy='dynamic'
    )
    
    def __repr__(self):
        return f"<SourceGroup(name='{self.name}', id={self.id})>"


class SourceMetadata(Base):
    """
    Additional metadata for sources.
    
    This table stores extended information about sources that doesn't
    fit in the main Source table, such as geographic and language data,
    robots.txt information, and other metadata.
    
    Attributes:
        id: Primary key.
        source_id: Foreign key to Source (one-to-one relationship).
        language: Primary language of the source (e.g., "en", "fr", "en-US").
        country: Country code where the source is based (ISO 3166-1 alpha-2).
        region: Region or state (for country-specific sources).
        city: City where the source is based.
        timezone: Timezone of the source (e.g., "America/New_York").
        robots_txt_url: URL to the source's robots.txt file.
        robots_allowed: Whether scraping is allowed according to robots.txt.
        crawl_delay: Crawl delay specified in robots.txt (in seconds).
        sitemap_url: URL to the source's sitemap.xml.
        favicon_url: URL to the source's favicon.
        logo_url: URL to the source's logo.
        contact_email: Contact email for the source.
        social_twitter: Twitter handle of the source.
        social_facebook: Facebook page URL.
        social_linkedin: LinkedIn page URL.
        alexa_rank: Alexa rank of the domain (if available).
        last_checked: Timestamp when metadata was last verified.
        notes: Additional notes about the source.
        source: Relationship to Source model.
    """
    __tablename__ = "source_metadata"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, unique=True)
    
    # Geographic and language metadata
    language = Column(String(20))
    country = Column(String(2))
    region = Column(String(100))
    city = Column(String(100))
    timezone = Column(String(50))
    
    # Robots.txt and crawling metadata
    robots_txt_url = Column(String(500))
    robots_allowed = Column(Boolean, default=True)
    crawl_delay = Column(Integer)  # In seconds
    sitemap_url = Column(String(500))
    
    # Branding and contact
    favicon_url = Column(String(500))
    logo_url = Column(String(500))
    contact_email = Column(String(255))
    
    # Social media
    social_twitter = Column(String(255))
    social_facebook = Column(String(500))
    social_linkedin = Column(String(500))
    
    # Popularity and ranking
    alexa_rank = Column(Integer)
    
    # Timestamps and notes
    last_checked = Column(DateTime)
    notes = Column(Text)
    
    # Relationship to source
    source = relationship("Source", back_populates="source_metadata", uselist=False)
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_metadata_source_id', 'source_id', unique=True),
        Index('idx_metadata_country', 'country'),
        Index('idx_metadata_language', 'language'),
        Index('idx_metadata_robots_allowed', 'robots_allowed'),
    )
    
    def __repr__(self):
        return f"<SourceMetadata(source_id={self.source_id}, language='{self.language}', country='{self.country}')>"


class Source(Base):
    """
    Represents a news source.

    Attributes:
        id: Primary key.
        name: Name of the source (e.g., "BBC News").
        domain: Domain of the source (e.g., "bbc.com").
        rss_url: URL of the RSS feed, if available.
        rate_limit_ms: Delay between requests in milliseconds.
        enabled: Whether the source is active for scraping.
        priority: Priority level (1 = high, 3 = low).
        tags: Comma-separated list of tags.
        reliability_score: Reliability score (1-10, 10 = most reliable).
        language: Primary language of the source (ISO 639-1 code).
        region: Geographic region (e.g., "global", "europe", "asia").
        country: Country code (ISO 3166-1 alpha-2).
        source_type: Type of source (e.g., "news", "financial", "scientific").
        update_frequency: How often source updates (in minutes).
        cacheability: Whether responses can be cached.
        articles: Relationship to Article model.
    """
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)
    rss_url = Column(String(500))
    rate_limit_ms = Column(Integer, default=2000)
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=2)
    tags = Column(String(500))  # Comma-separated tags
    
    # Enhanced metadata fields
    reliability_score = Column(Integer, default=5)  # 1-10 scale
    language = Column(String(10), default="en")  # ISO 639-1 code
    region = Column(String(50), default="global")
    country = Column(String(2), default="US")  # ISO 3166-1 alpha-2
    source_type = Column(String(50), default="news")  # news, financial, scientific, etc.
    update_frequency = Column(Integer, default=60)  # minutes
    cacheability = Column(Boolean, default=True)

    # Relationship to articles
    articles = relationship("Article", back_populates="source", cascade="all, delete-orphan")
    
    # Many-to-many relationship with groups
    groups = relationship(
        "SourceGroup",
        secondary=source_group_association,
        back_populates="sources",
        lazy='dynamic'
    )
    
    # One-to-one relationship with metadata
    source_metadata = relationship("SourceMetadata", back_populates="source", uselist=False, cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_source_domain', 'domain', unique=True),
        Index('idx_source_enabled', 'enabled'),
        Index('idx_source_priority', 'priority'),
        Index('idx_source_reliability', 'reliability_score'),
        Index('idx_source_language', 'language'),
        Index('idx_source_region', 'region'),
        Index('idx_source_country', 'country'),
        Index('idx_source_type', 'source_type'),
    )
    
    def __repr__(self):
        return f"<Source(name='{self.name}', domain='{self.domain}')>"


class Article(Base):
    """
    Represents a scraped article.

    Attributes:
        id: Primary key.
        url: Original URL of the article.
        canonical_url: Canonicalized URL (for duplicate detection).
        source_id: Foreign key to Source.
        title: Title of the article.
        content: Full text content of the article.
        published_at: Publication date/time (ISO format).
        language: Language code (e.g., "en", "fr").
        hash: SHA-256 hash of the content (for duplicate detection).
        created_at: Timestamp when the article was ingested.
        region: Geographic region detected from content.
        country: Country code detected from content.
        author: Author of the article.
        source: Relationship to Source model.
    """
    __tablename__ = "articles"
    
    id = Column(Integer, primary_key=True)
    url = Column(String(1000), nullable=False)
    canonical_url = Column(String(1000), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String(500))
    content = Column(Text, nullable=False)
    # Compressed version of content for storage optimization
    compressed_content = Column(LargeBinary)
    published_at = Column(DateTime)
    language = Column(String(10))
    hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hash length is 64
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(UTC))
    
    # Enhanced metadata fields
    region = Column(String(50))  # Geographic region
    country = Column(String(2))  # ISO 3166-1 alpha-2 country code
    author = Column(String(255))  # Article author
    word_count = Column(Integer)  # Number of words in the article
    reading_time = Column(Integer)  # Estimated reading time in minutes
    
    # Content analysis fields
    sentiment_score = Column(Float)  # Sentiment analysis score (-1 to 1)
    sentiment_label = Column(String(20))  # Sentiment label (positive, negative, neutral)
    
    # Relationship to source
    source = relationship("Source", back_populates="articles")
    
    # Indexes for performance
    __table_args__ = (
        # Index for faster duplicate detection
        Index("idx_article_hash", "hash", unique=True),
        # Index for faster URL lookups
        Index("idx_article_canonical_url", "canonical_url"),
        # Index for faster source-based queries
        Index("idx_article_source_id", "source_id"),
        # Index for faster text search (on original content)
        Index("idx_article_content", "content"),
        # Index for faster language queries
        Index("idx_article_language", "language"),
        # Index for faster region queries
        Index("idx_article_region", "region"),
        # Index for faster country queries
        Index("idx_article_country", "country"),
        # Index for faster author queries
        Index("idx_article_author", "author"),
        # Index for faster date-based queries
        Index("idx_article_published_at", "published_at"),
        Index("idx_article_created_at", "created_at"),
        # Composite indexes for common query patterns
        Index("idx_article_source_published", "source_id", "published_at"),
        Index("idx_article_language_region", "language", "region"),
        Index("idx_article_country_language", "country", "language"),
        # Index for content length (word_count)
        Index("idx_article_word_count", "word_count"),
        # Index for sentiment analysis
        Index("idx_article_sentiment", "sentiment_score"),
    )
    
    @property
    def is_compressed(self) -> bool:
        """Check if content is stored in compressed format."""
        return self.compressed_content is not None
    
    def compress_content(self) -> None:
        """Compress the content and store in compressed_content field."""
        if self.content and not self.compressed_content:
            from src.utils.compression import database_compressor
            self.compressed_content = database_compressor.compress_text_for_storage(self.content)
    
    def decompress_content(self) -> str:
        """Decompress the content from compressed_content field."""
        if self.compressed_content:
            from src.utils.compression import database_compressor
            return database_compressor.decompress_text_from_storage(self.compressed_content)
        return self.content or ""
    
    def get_content(self) -> str:
        """Get the content, decompressing if necessary."""
        if self.compressed_content:
            return self.decompress_content()
        return self.content or ""
    
    def set_content(self, content: str) -> None:
        """Set the content, optionally compressing it."""
        self.content = content
        # Clear compressed content to force recompression
        self.compressed_content = None
    
    def __repr__(self):
        return f"<Article(title='{self.title[:50]}...', source='{self.source.name if self.source else 'Unknown'}')>"



# Keyword and Category Models for Keyword Extraction

# Association table for many-to-many relationship between Article and Keyword
article_keyword_association = Table(
    'article_keyword_association',
    Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id'), primary_key=True),
    Column('keyword_id', Integer, ForeignKey('keywords.id'), primary_key=True),
    Column('frequency', Integer, default=1),
    Column('position', Integer),
    Column('relevance_score', Float, default=0.0),
    Column('created_at', DateTime, default=lambda: datetime.now(UTC)),
    # Indexes for performance
    Index('idx_article_keyword_article_id', 'article_id'),
    Index('idx_article_keyword_keyword_id', 'keyword_id'),
)


class KeywordCategory(Base):
    """
    Represents a category for classifying keywords.
    
    Attributes:
        id: Primary key.
        name: Name of the category (e.g., "Politics", "Technology").
        description: Description of the category.
        parent_id: Foreign key to parent category (for hierarchical categories).
        color: Color code for UI display.
        is_active: Whether the category is active.
        created_at: Timestamp when the category was created.
        updated_at: Timestamp when the category was last updated.
        keywords: Relationship to Keyword model.
    """
    __tablename__ = "keyword_categories"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    parent_id = Column(Integer, ForeignKey("keyword_categories.id"))
    color = Column(String(20), default="#666666")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Self-referential relationship for hierarchical categories
    parent = relationship("KeywordCategory", remote_side=[id], back_populates="children")
    children = relationship("KeywordCategory", back_populates="parent")
    
    # One-to-many relationship with keywords
    keywords = relationship("Keyword", back_populates="category", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<KeywordCategory(name='{self.name}', id={self.id})>"


class Keyword(Base):
    """
    Represents a keyword extracted from articles.
    
    Attributes:
        id: Primary key.
        term: The keyword term (normalized).
        normalized_term: Fully normalized term (lowercase, stemmed, etc.).
        language: Language code (e.g., "en", "fr").
        frequency: Total frequency across all articles.
        category_id: Foreign key to KeywordCategory.
        is_ngram: Whether this is an n-gram (multi-word keyword).
        ngram_size: Size of n-gram (1 for unigram, 2 for bigram, etc.).
        is_entity: Whether this keyword is a named entity.
        entity_type: Type of entity (person, organization, location, etc.).
        relevance_score: Overall relevance score.
        created_at: Timestamp when the keyword was first extracted.
        updated_at: Timestamp when the keyword was last updated.
        category: Relationship to KeywordCategory model.
        articles: Relationship to Article model (many-to-many).
    """
    __tablename__ = "keywords"
    
    id = Column(Integer, primary_key=True)
    term = Column(String(255), nullable=False)
    normalized_term = Column(String(255), nullable=False)
    language = Column(String(10), default="en")
    frequency = Column(Integer, default=0)
    category_id = Column(Integer, ForeignKey("keyword_categories.id"))
    is_ngram = Column(Boolean, default=False)
    ngram_size = Column(Integer, default=1)
    is_entity = Column(Boolean, default=False)
    entity_type = Column(String(50))
    relevance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Relationships
    category = relationship("KeywordCategory", back_populates="keywords")
    articles = relationship(
        "Article",
        secondary=article_keyword_association,
        lazy='dynamic'
    )
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_keyword_term', 'term'),
        Index('idx_keyword_normalized_term', 'normalized_term'),
        Index('idx_keyword_language', 'language'),
        Index('idx_keyword_category_id', 'category_id'),
        Index('idx_keyword_frequency', 'frequency'),
        Index('idx_keyword_is_ngram', 'is_ngram'),
        Index('idx_keyword_is_entity', 'is_entity'),
    )
    
    def __repr__(self):
        return f"<Keyword(term='{self.term}', frequency={self.frequency})>"


class ArticleKeyword(Base):
    """
    Represents the relationship between an article and a keyword with additional metadata.
    
    This model stores information about how a keyword appears in a specific article,
    including frequency, position, and relevance score.
    
    Attributes:
        article_id: Foreign key to Article.
        keyword_id: Foreign key to Keyword.
        frequency: Number of times the keyword appears in the article.
        first_position: Position of first occurrence.
        last_position: Position of last occurrence.
        relevance_score: Relevance score for this keyword in this article.
        created_at: Timestamp when the relationship was created.
    """
    __tablename__ = "article_keywords"
    
    article_id = Column(Integer, ForeignKey('articles.id'), primary_key=True)
    keyword_id = Column(Integer, ForeignKey('keywords.id'), primary_key=True)
    frequency = Column(Integer, default=1)
    first_position = Column(Integer)
    last_position = Column(Integer)
    relevance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    
    def __repr__(self):
        return f"<ArticleKeyword(article_id={self.article_id}, keyword_id={self.keyword_id}, frequency={self.frequency})>"



# Link Tracking Models for Source/Link Tracking System

class LinkClassificationRule(Base):
    """
    Represents a rule for classifying links.
    
    Attributes:
        id: Primary key.
        rule_name: Name of the classification rule.
        pattern: URL pattern to match (regex).
        classification_type: Type of classification (source, reference, ad, social, navigation, other).
        priority: Priority of the rule (higher = applied first).
        is_active: Whether the rule is active.
        created_at: Timestamp when the rule was created.
        updated_at: Timestamp when the rule was last updated.
    """
    __tablename__ = "link_classification_rules"
    
    id = Column(Integer, primary_key=True)
    rule_name = Column(String(100), nullable=False, unique=True)
    pattern = Column(String(500), nullable=False)
    classification_type = Column(String(50), nullable=False)  # source, reference, ad, social, navigation, other
    priority = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_link_classification_rule_name', 'rule_name', unique=True),
        Index('idx_link_classification_type', 'classification_type'),
        Index('idx_link_classification_priority', 'priority'),
        Index('idx_link_classification_active', 'is_active'),
    )
    
    def __repr__(self):
        return f"<LinkClassificationRule(rule_name='{self.rule_name}', classification_type='{self.classification_type}')>"


class ExternalSource(Base):
    """
    Represents an external source (website, publication, etc.) that is referenced in articles.
    
    Attributes:
        id: Primary key.
        domain: Domain of the source (e.g., "nytimes.com").
        name: Name of the source (e.g., "The New York Times").
        url: Base URL of the source.
        source_type: Type of source (news, blog, academic, government, etc.).
        credibility_score: Credibility score (0-100).
        political_bias: Political bias score (-100 to 100, left to right).
        country: Country code (ISO 3166-1 alpha-2).
        language: Primary language code (ISO 639-1).
        description: Description of the source.
        founded_year: Year the source was founded.
        alexa_rank: Alexa rank of the domain.
        social_media_followers: Number of social media followers.
        is_verified: Whether the source has been verified.
        last_verified_at: Timestamp when the source was last verified.
        created_at: Timestamp when the source was first added.
        updated_at: Timestamp when the source was last updated.
        source_articles: Relationship to SourceArticle model.
        links: Relationship to ArticleLink model.
    """
    __tablename__ = "external_sources"
    
    id = Column(Integer, primary_key=True)
    domain = Column(String(255), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500))
    source_type = Column(String(50), default="unknown")  # news, blog, academic, government, social, etc.
    credibility_score = Column(Float, default=50.0)  # 0-100
    political_bias = Column(Float, default=0.0)  # -100 (left) to 100 (right)
    country = Column(String(2))
    language = Column(String(10), default="en")
    description = Column(Text)
    founded_year = Column(Integer)
    alexa_rank = Column(Integer)
    social_media_followers = Column(Integer)
    is_verified = Column(Boolean, default=False)
    last_verified_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Relationships
    source_articles = relationship("SourceArticle", back_populates="external_source", cascade="all, delete-orphan")
    links = relationship("ArticleLink", back_populates="external_source", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_external_source_domain', 'domain', unique=True),
        Index('idx_external_source_name', 'name'),
        Index('idx_external_source_type', 'source_type'),
        Index('idx_external_source_credibility', 'credibility_score'),
        Index('idx_external_source_country', 'country'),
        Index('idx_external_source_verified', 'is_verified'),
    )
    
    def __repr__(self):
        return f"<ExternalSource(name='{self.name}', domain='{self.domain}', credibility={self.credibility_score})>"


class SourceArticle(Base):
    """
    Represents an article from an external source that is referenced in our articles.
    
    Attributes:
        id: Primary key.
        source_id: Foreign key to ExternalSource.
        url: URL of the source article.
        title: Title of the source article.
        published_at: Publication date of the source article.
        author: Author of the source article.
        summary: Summary/description of the source article.
        content_hash: SHA-256 hash of the source article content.
        word_count: Number of words in the source article.
        sentiment_score: Sentiment score of the source article.
        is_accessible: Whether the source article is still accessible.
        last_accessed_at: Timestamp when the source article was last accessed.
        created_at: Timestamp when the source article was first added.
        updated_at: Timestamp when the source article was last updated.
        source: Relationship to ExternalSource model.
        article_links: Relationship to ArticleLink model.
    """
    __tablename__ = "source_articles"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("external_sources.id"), nullable=False)
    url = Column(String(1000), nullable=False)
    title = Column(String(500))
    published_at = Column(DateTime)
    author = Column(String(255))
    summary = Column(Text)
    content_hash = Column(String(64))  # SHA-256 hash
    word_count = Column(Integer)
    sentiment_score = Column(Float)
    is_accessible = Column(Boolean, default=True)
    last_accessed_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Relationships
    external_source = relationship("ExternalSource", back_populates="source_articles")
    article_links = relationship("ArticleLink", back_populates="source_article", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_source_article_source_id', 'source_id'),
        Index('idx_source_article_url', 'url', unique=True),
        Index('idx_source_article_published', 'published_at'),
        Index('idx_source_article_hash', 'content_hash', unique=True),
        Index('idx_source_article_accessible', 'is_accessible'),
    )
    
    def __repr__(self):
        return f"<SourceArticle(title='{self.title[:50] if self.title else 'Untitled'}...', source_id={self.source_id})>"


class ArticleLink(Base):
    """
    Represents a link found in an article, with classification and relationship tracking.
    
    Attributes:
        id: Primary key.
        article_id: Foreign key to Article.
        url: The URL of the link.
        normalized_url: Normalized URL (for duplicate detection).
        link_text: The text of the link (anchor text).
        position: Position of the link in the article (character offset).
        link_type: Type of link (internal, external, image, etc.).
        classification: Classification of the link (source, reference, ad, social, navigation, other).
        external_source_id: Foreign key to ExternalSource (if identified).
        source_article_id: Foreign key to SourceArticle (if the link points to a known article).
        is_followable: Whether the link should be followed for scraping.
        is_working: Whether the link is still working (not 404).
        last_checked_at: Timestamp when the link was last checked.
        redirect_url: Final URL after following redirects.
        http_status: HTTP status code of the link.
        created_at: Timestamp when the link was first extracted.
        updated_at: Timestamp when the link was last updated.
        article: Relationship to Article model.
        external_source: Relationship to ExternalSource model.
        source_article: Relationship to SourceArticle model.
    """
    __tablename__ = "article_links"
    
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    url = Column(String(1000), nullable=False)
    normalized_url = Column(String(1000), nullable=False)
    link_text = Column(String(500))
    position = Column(Integer)
    link_type = Column(String(50), default="external")  # internal, external, image, script, stylesheet, etc.
    classification = Column(String(50), default="other")  # source, reference, ad, social, navigation, other
    external_source_id = Column(Integer, ForeignKey("external_sources.id"))
    source_article_id = Column(Integer, ForeignKey("source_articles.id"))
    is_followable = Column(Boolean, default=True)
    is_working = Column(Boolean, default=True)
    last_checked_at = Column(DateTime)
    redirect_url = Column(String(1000))
    http_status = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Relationships
    article = relationship("Article", back_populates="links")
    external_source = relationship("ExternalSource", back_populates="links")
    source_article = relationship("SourceArticle", back_populates="article_links")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_article_link_article_id', 'article_id'),
        Index('idx_article_link_url', 'url'),
        Index('idx_article_link_normalized_url', 'normalized_url'),
        Index('idx_article_link_classification', 'classification'),
        Index('idx_article_link_source_id', 'external_source_id'),
        Index('idx_article_link_source_article_id', 'source_article_id'),
        Index('idx_article_link_working', 'is_working'),
        Index('idx_article_link_type', 'link_type'),
    )
    
    def __repr__(self):
        return f"<ArticleLink(url='{self.url[:50]}...', classification='{self.classification}', article_id={self.article_id})>"


class ArticleSourceRelationship(Base):
    """
    Represents the relationship between an article and its external sources.
    
    This table tracks which external sources are referenced in which articles,
    including temporal analysis (article date vs. source article date).
    
    Attributes:
        id: Primary key.
        article_id: Foreign key to Article.
        source_id: Foreign key to ExternalSource.
        source_article_id: Foreign key to SourceArticle (if specific article is identified).
        link_id: Foreign key to ArticleLink (the specific link that created this relationship).
        relationship_type: Type of relationship (citation, reference, source, etc.).
        time_delta_days: Difference in days between article publication and source publication.
        is_temporal_anomaly: Whether there's a temporal anomaly (article published before source).
        confidence_score: Confidence score of the relationship (0-1).
        notes: Additional notes about the relationship.
        created_at: Timestamp when the relationship was created.
        updated_at: Timestamp when the relationship was last updated.
        article: Relationship to Article model.
        external_source: Relationship to ExternalSource model.
        source_article: Relationship to SourceArticle model.
        link: Relationship to ArticleLink model.
    """
    __tablename__ = "article_source_relationships"
    
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("external_sources.id"), nullable=False)
    source_article_id = Column(Integer, ForeignKey("source_articles.id"))
    link_id = Column(Integer, ForeignKey("article_links.id"))
    relationship_type = Column(String(50), default="reference")  # citation, reference, source, mention, etc.
    time_delta_days = Column(Float)  # Can be negative if article published before source
    is_temporal_anomaly = Column(Boolean, default=False)
    confidence_score = Column(Float, default=0.0)  # 0-1
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Relationships
    article = relationship("Article")
    external_source = relationship("ExternalSource")
    source_article = relationship("SourceArticle")
    link = relationship("ArticleLink")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_article_source_rel_article_id', 'article_id'),
        Index('idx_article_source_rel_source_id', 'source_id'),
        Index('idx_article_source_rel_source_article_id', 'source_article_id'),
        Index('idx_article_source_rel_link_id', 'link_id'),
        Index('idx_article_source_rel_type', 'relationship_type'),
        Index('idx_article_source_rel_anomaly', 'is_temporal_anomaly'),
        Index('idx_article_source_rel_confidence', 'confidence_score'),
    )
    
    def __repr__(self):
        return f"<ArticleSourceRelationship(article_id={self.article_id}, source_id={self.source_id}, time_delta={self.time_delta_days} days)"


class SourceCredibilityRule(Base):
    """
    Represents a rule for calculating source credibility scores.
    
    Attributes:
        id: Primary key.
        rule_name: Name of the credibility rule.
        factor: Factor to apply (e.g., alexa_rank, social_followers, etc.).
        weight: Weight of this factor in the overall score (0-1).
        min_value: Minimum value for normalization.
        max_value: Maximum value for normalization.
        is_inverse: Whether higher values should decrease credibility (e.g., alexa rank).
        is_active: Whether the rule is active.
        created_at: Timestamp when the rule was created.
        updated_at: Timestamp when the rule was last updated.
    """
    __tablename__ = "source_credibility_rules"
    
    id = Column(Integer, primary_key=True)
    rule_name = Column(String(100), nullable=False, unique=True)
    factor = Column(String(50), nullable=False)  # alexa_rank, social_followers, age, verification_status, etc.
    weight = Column(Float, default=1.0)  # 0-1
    min_value = Column(Float, default=0.0)
    max_value = Column(Float, default=100.0)
    is_inverse = Column(Boolean, default=False)  # True for factors where higher = worse (e.g., alexa rank)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_credibility_rule_name', 'rule_name', unique=True),
        Index('idx_credibility_rule_factor', 'factor'),
        Index('idx_credibility_rule_active', 'is_active'),
    )
    
    def __repr__(self):
        return f"<SourceCredibilityRule(rule_name='{self.rule_name}', factor='{self.factor}', weight={self.weight})>"


# Add relationships to existing Article model
Article.links = relationship("ArticleLink", back_populates="article", cascade="all, delete-orphan")


class ArticleAnalysis(Base):
    """A derived analytic result for an article (LLM summary, translation, ...).

    Carries provenance so no number/text is ever shown without its origin
    (PRODUCT_SYNTHESIS §8): which model produced it, with which prompt version,
    and when. This is how LLM output is stored "with provenance".
    """

    __tablename__ = "article_analyses"

    id = Column(Integer, primary_key=True)
    article_id = Column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(50), nullable=False)  # summary | translation | entities | ...
    result = Column(Text, nullable=False)
    # provenance
    model = Column(String(100), nullable=False)
    prompt_version = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    article = relationship("Article", backref="analyses")

    def __repr__(self) -> str:
        return f"<ArticleAnalysis(article_id={self.article_id}, kind='{self.kind}', model='{self.model}')>"


class CommodityPrice(Base):
    """A single observed commodity price point (time series).

    Stored alongside articles in the unified DB so price movements can be
    correlated with news. ``currency`` and ``unit`` are recorded explicitly --
    prices are NOT silently mixed across currencies/units (see src/commodity/units.py
    for correct, tested unit conversion).
    """

    __tablename__ = "commodity_prices"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)  # e.g. "Nd", "Dy"
    market = Column(String(100), nullable=True)              # e.g. "china_spot", "USGS"
    observed_on = Column(Date, nullable=False, index=True)
    price = Column(Float, nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    unit = Column(String(16), nullable=False, default="kg")  # mass unit (kg, t, lb, ozt, ...)
    source = Column(String(255), nullable=True)              # provenance: where it came from
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_commodity_symbol_date", "symbol", "observed_on"),
    )

    def __repr__(self) -> str:
        return f"<CommodityPrice({self.symbol} {self.observed_on} {self.price} {self.currency}/{self.unit})>"



# Example usage
if __name__ == "__main__":
    # Test database connection and table creation
    init_db()
    session = get_session()
    
    # Check if tables exist
    from sqlalchemy.inspection import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tables in database: {tables}")
    
    session.close()
    print("Database setup complete. Tables created if they didn't exist.")
