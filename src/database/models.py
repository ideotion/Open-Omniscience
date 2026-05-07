"""
Database Models for Open Omniscience

This module defines the SQLAlchemy models for the database,
supporting both SQLite (default) and PostgreSQL.
Includes tables for sources and articles, with relationships and indexes.

Author: Ideotion
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, create_engine, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
from pathlib import Path

# Ensure the data directory exists
os.makedirs("../../data", exist_ok=True)

# Database URL: Default to SQLite, but can be overridden for PostgreSQL
# To use PostgreSQL, set DATABASE_URL to:
# postgres://username:password@localhost:5432/open_omniscience
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///../../data/open_omniscience.db")

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL, echo=False)

# Session factory
Session = sessionmaker(bind=engine)

# Base class for declarative models
Base = declarative_base()


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