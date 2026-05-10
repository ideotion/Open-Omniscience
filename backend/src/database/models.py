"""
Database Models for Open-Omniscience
SQLite-compatible models with JSON serialization for complex fields
"""
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, CheckConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .session import Base
import uuid
import json


def generate_uuid():
    """Generate a UUID string"""
    return str(uuid.uuid4())


class Article(Base):
    """Represents an article"""
    __tablename__ = "articles"

    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, index=True)
    content = Column(Text)
    content_html = Column(Text)
    summary = Column(Text)
    url = Column(String, unique=True, index=True)
    source_url = Column(String)
    source_domain = Column(String, index=True)
    author = Column(String)
    published_at = Column(DateTime, index=True)
    category = Column(String, index=True)
    language = Column(String, default="en")
    country = Column(String)
    sentiment = Column(String)
    word_count = Column(Integer)
    reading_time = Column(Integer)
    extra_metadata = Column(Text)  # JSON serialized (renamed from metadata)
    is_duplicate = Column(Boolean, default=False)
    duplicate_of = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    keywords = relationship("KeywordAppearance", back_populates="article")
    source_references = relationship("ArticleSourceReference", back_populates="article")

    def get_extra_metadata(self):
        """Get extra_metadata as dictionary"""
        if self.extra_metadata:
            return json.loads(self.extra_metadata)
        return {}

    def set_extra_metadata(self, data):
        """Set extra_metadata from dictionary"""
        self.extra_metadata = json.dumps(data)


class Keyword(Base):
    """Represents a keyword"""
    __tablename__ = "keywords"

    id = Column(String, primary_key=True, default=generate_uuid)
    text = Column(String, index=True)
    normalized_text = Column(String, index=True)
    category = Column(String, index=True)
    language = Column(String, default="en")
    is_stopword = Column(Boolean, default=False)
    stem = Column(String)
    lemma = Column(String)
    pos_tag = Column(String)
    sentiment_score = Column(Float)
    first_seen = Column(DateTime, index=True)
    last_seen = Column(DateTime, index=True)
    total_appearances = Column(Integer, default=0)
    article_count = Column(Integer, default=0)
    avg_relevance = Column(Float, default=0.0)
    trending_score = Column(Float, default=0.0)
    last_analysis_date = Column(DateTime)

    appearances = relationship("KeywordAppearance", back_populates="keyword")


class KeywordAppearance(Base):
    """Tracks keyword appearances in articles"""
    __tablename__ = "keyword_appearances"

    id = Column(String, primary_key=True, default=generate_uuid)
    keyword_id = Column(String, ForeignKey("keywords.id"), index=True)
    article_id = Column(String, ForeignKey("articles.id"), index=True)
    position = Column(Integer)
    count = Column(Integer, default=1)
    relevance_score = Column(Float)
    is_in_title = Column(Boolean, default=False)
    is_in_lead = Column(Boolean, default=False)
    is_quoted = Column(Boolean, default=False)
    sentiment = Column(String)
    created_at = Column(DateTime, server_default=func.now())

    keyword = relationship("Keyword", back_populates="appearances")
    article = relationship("Article", back_populates="keywords")


class Source(Base):
    """Represents an external source/link"""
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=generate_uuid)
    url = Column(String, unique=True, index=True)
    domain = Column(String, index=True)
    subdomain = Column(String)
    title = Column(String)
    description = Column(Text)
    favicon = Column(String)
    is_news = Column(Boolean, default=False)
    is_commercial = Column(Boolean, default=False)
    is_social = Column(Boolean, default=False)
    is_valid = Column(Boolean, default=True)
    first_seen = Column(DateTime, index=True)
    last_seen = Column(DateTime, index=True)
    last_scraped = Column(DateTime)
    scrape_count = Column(Integer, default=0)
    status_code = Column(Integer)
    content_type = Column(String)
    language = Column(String)
    country = Column(String)
    trust_score = Column(Float, default=0.0)
    category = Column(String)
    last_stats_update = Column(DateTime)

    article_references = relationship("ArticleSourceReference", back_populates="source")


class ArticleSourceReference(Base):
    """Links articles to their referenced sources"""
    __tablename__ = "article_source_references"

    id = Column(String, primary_key=True, default=generate_uuid)
    article_id = Column(String, ForeignKey("articles.id"), index=True)
    source_id = Column(String, ForeignKey("sources.id"), index=True)
    reference_url = Column(String)
    reference_text = Column(String)
    position = Column(Integer)
    context = Column(Text)
    is_direct_quote = Column(Boolean, default=False)
    reference_type = Column(String)
    created_at = Column(DateTime, server_default=func.now())

    article = relationship("Article", back_populates="source_references")
    source = relationship("Source", back_populates="article_references")


class SourceSourceReference(Base):
    """Tracks links between sources (citation network)"""
    __tablename__ = "source_source_references"

    id = Column(String, primary_key=True, default=generate_uuid)
    source_id = Column(String, ForeignKey("sources.id"), index=True)
    referenced_source_id = Column(String, ForeignKey("sources.id"), index=True)
    reference_url = Column(String)
    reference_text = Column(String)
    discovered_at = Column(DateTime, server_default=func.now())

    source = relationship("Source", foreign_keys=[source_id])
    referenced_source = relationship("Source", foreign_keys=[referenced_source_id])


class ArticleSimilarity(Base):
    """Stores similarity scores between articles"""
    __tablename__ = "article_similarities"

    id = Column(String, primary_key=True, default=generate_uuid)
    article_id_1 = Column(String, ForeignKey("articles.id"), index=True)
    article_id_2 = Column(String, ForeignKey("articles.id"), index=True)
    similarity_score = Column(Float)
    similarity_type = Column(String)
    common_keywords = Column(Integer)
    common_sources = Column(Integer)
    keyword_overlap = Column(Float)
    source_overlap = Column(Float)
    temporal_distance = Column(Float)
    is_duplicate = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint('article_id_1 < article_id_2', name='check_article_order'),
    )


class ScrapeJob(Base):
    """Tracks source scraping jobs"""
    __tablename__ = "scrape_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    source_id = Column(String, ForeignKey("sources.id"), index=True)
    status = Column(String)
    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)
    bytes_scraped = Column(Integer)
    links_found = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    source = relationship("Source")


class DashboardWidget(Base):
    """Customizable dashboard widgets"""
    __tablename__ = "dashboard_widgets"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, index=True)
    widget_type = Column(String)
    title = Column(String)
    config = Column(Text)
    position = Column(Text)
    is_active = Column(Boolean, default=True)
    refresh_interval = Column(Integer)
    last_refresh = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    def get_config(self):
        if self.config:
            return json.loads(self.config)
        return {}

    def set_config(self, data):
        self.config = json.dumps(data)

    def get_position(self):
        if self.position:
            return json.loads(self.position)
        return {"x": 0, "y": 0, "w": 4, "h": 3}

    def set_position(self, data):
        self.position = json.dumps(data)
