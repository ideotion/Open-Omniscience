"""
Database Models for Open Omniscience

This module defines the SQLAlchemy models for the database,
supporting both SQLite (default) and PostgreSQL.
Includes tables for sources and articles, with relationships and indexes.

Author: Ideotion
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, create_engine, Index, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
from pathlib import Path

# Get the absolute path to the repository root
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()

# Ensure the data directory exists
DATA_DIR = REPO_ROOT / "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Database URL: Default to SQLite, but can be overridden for PostgreSQL
# To use PostgreSQL, set DATABASE_URL to:
# postgresql://user:password@localhost:5432/open_omniscience
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'open_omniscience.db'}")

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL, echo=False)

# Session factory
Session = sessionmaker(bind=engine)

# Base class for declarative models
Base = declarative_base()


# Association table for many-to-many relationship between Source and SourceGroup
source_group_association = Table(
    'source_group_association',
    Base.metadata,
    Column('source_id', Integer, ForeignKey('sources.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('source_groups.id'), primary_key=True),
    Column('added_at', DateTime, default=datetime.utcnow),
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
        source: Relationship to Source model.
    """
    __tablename__ = "articles"
    
    id = Column(Integer, primary_key=True)
    url = Column(String(1000), nullable=False)
    canonical_url = Column(String(1000), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String(500))
    content = Column(Text, nullable=False)
    published_at = Column(DateTime)
    language = Column(String(10))
    hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hash length is 64
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
        # Index for faster text search
        Index("idx_article_content", "content"),
    )
    
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
    Column('created_at', DateTime, default=datetime.utcnow),
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<ArticleKeyword(article_id={self.article_id}, keyword_id={self.keyword_id}, frequency={self.frequency})>"



# Create all tables in the database
Base.metadata.create_all(engine)

# Utility function to get a new database session
def get_session():
    """Return a new database session."""
    return Session()


# Example usage
if __name__ == "__main__":
    # Test database connection and table creation
    session = get_session()
    
    # Check if tables exist
    from sqlalchemy.inspection import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tables in database: {tables}")
    
    session.close()
    print("Database setup complete. Tables created if they didn't exist.")
