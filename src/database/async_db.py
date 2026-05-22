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
Async Database Support for Open Omniscience

This module provides async database support using SQLAlchemy 2.0 async API.
It includes:
- Async engine and session factory
- Async versions of all database models
- Async query utilities
- Performance optimizations for async operations

Author: Ideotion
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Type, Union

from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    Text, 
    DateTime, 
    Boolean, 
    ForeignKey, 
    Float, 
    Index, 
    Table, 
    TypeDecorator, 
    LargeBinary,
    select, 
    func, 
    and_, 
    or_, 
    desc, 
    asc,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, 
    create_async_engine, 
    async_sessionmaker,
)
from sqlalchemy.orm import (
    declarative_base, 
    relationship, 
    sessionmaker,
)
from sqlalchemy.sql import Select

logger = logging.getLogger(__name__)


# =============================================================================
# Async Database Configuration
# =============================================================================

# Get database URL from environment or use SQLite
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
DATA_DIR = REPO_ROOT / "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Async database URL - replace sqlite with postgresql+asyncpg for production
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL", 
    f"sqlite+aiosqlite:///{DATA_DIR / 'open_omniscience_async.db'}"
)

# Async database configuration
ASYNC_DATABASE_CONFIG = {
    "sqlite": {
        "echo": False,
        "future": True,
        "connect_args": {
            "check_same_thread": False,
            "timeout": 30,
        },
    },
    "postgresql": {
        "echo": False,
        "future": True,
        "pool_size": 20,
        "max_overflow": 50,
        "pool_timeout": 30,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
    },
    "mysql": {
        "echo": False,
        "future": True,
        "pool_size": 20,
        "max_overflow": 50,
        "pool_timeout": 30,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    },
}


def get_async_database_config() -> Dict[str, Any]:
    """Get async database configuration based on URL."""
    config = ASYNC_DATABASE_CONFIG["sqlite"].copy()
    
    if ASYNC_DATABASE_URL.startswith("postgresql"):
        config.update(ASYNC_DATABASE_CONFIG["postgresql"])
    elif ASYNC_DATABASE_URL.startswith("mysql"):
        config.update(ASYNC_DATABASE_CONFIG["mysql"])
    
    return config


# Create async engine
async_engine = create_async_engine(
    ASYNC_DATABASE_URL, 
    **get_async_database_config()
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
)

# Base class for async models
AsyncBase = declarative_base()


# =============================================================================
# Async Compressed Types
# =============================================================================

class AsyncCompressedText(TypeDecorator):
    """Async version of CompressedText type."""
    impl = LargeBinary
    cache_ok = True
    
    def process_bind_param(self, value: Optional[Union[str, bytes]], dialect: Any) -> Optional[bytes]:
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        from src.utils.compression import database_compressor
        return database_compressor.compress_text_for_storage(value)
    
    def process_result_value(self, value: Optional[bytes], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        from src.utils.compression import database_compressor
        return database_compressor.decompress_text_from_storage(value)


class AsyncCompressedJSON(TypeDecorator):
    """Async version of CompressedJSON type."""
    impl = LargeBinary
    cache_ok = True
    
    def process_bind_param(self, value: Any, dialect: Any) -> Optional[bytes]:
        if value is None:
            return None
        import json
        from src.utils.compression import database_compressor
        json_str = json.dumps(value, ensure_ascii=False, default=str)
        return database_compressor.compress_text_for_storage(json_str)
    
    def process_result_value(self, value: Optional[bytes], dialect: Any) -> Any:
        if value is None:
            return None
        import json
        from src.utils.compression import database_compressor
        json_str = database_compressor.decompress_text_from_storage(value)
        return json.loads(json_str)


# =============================================================================
# Async Database Models
# =============================================================================

# Association table for many-to-many relationship between Source and SourceGroup
async_source_group_association = Table(
    'async_source_group_association',
    AsyncBase.metadata,
    Column('source_id', Integer, ForeignKey('async_sources.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('async_source_groups.id'), primary_key=True),
    Column('added_at', DateTime, default=lambda: datetime.now(timezone.utc)),
    Index('idx_async_source_group_source_id', 'source_id'),
    Index('idx_async_source_group_group_id', 'group_id'),
)


class AsyncSourceGroup(AsyncBase):
    """Async version of SourceGroup model."""
    __tablename__ = "async_source_groups"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    color = Column(String(20), default="#666666")
    is_tag_based = Column(Boolean, default=False)
    tag_pattern = Column(String(500))
    priority = Column(Integer, default=2)
    rate_limit_ms = Column(Integer, default=2000)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    sources = relationship(
        "AsyncSource",
        secondary=async_source_group_association,
        back_populates="groups",
        lazy='dynamic'
    )


class AsyncSourceMetadata(AsyncBase):
    """Async version of SourceMetadata model."""
    __tablename__ = "async_source_metadata"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("async_sources.id"), nullable=False, unique=True)
    
    language = Column(String(20))
    country = Column(String(2))
    region = Column(String(100))
    city = Column(String(100))
    timezone = Column(String(50))
    
    robots_txt_url = Column(String(500))
    robots_allowed = Column(Boolean, default=True)
    crawl_delay = Column(Integer)
    sitemap_url = Column(String(500))
    
    favicon_url = Column(String(500))
    logo_url = Column(String(500))
    contact_email = Column(String(255))
    
    social_twitter = Column(String(255))
    social_facebook = Column(String(500))
    social_linkedin = Column(String(500))
    
    alexa_rank = Column(Integer)
    last_checked = Column(DateTime)
    notes = Column(Text)
    
    source = relationship("AsyncSource", back_populates="source_metadata", uselist=False)
    
    __table_args__ = (
        Index('idx_async_metadata_source_id', 'source_id', unique=True),
        Index('idx_async_metadata_country', 'country'),
        Index('idx_async_metadata_language', 'language'),
    )


class AsyncSource(AsyncBase):
    """Async version of Source model."""
    __tablename__ = "async_sources"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)
    rss_url = Column(String(500))
    rate_limit_ms = Column(Integer, default=2000)
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=2)
    tags = Column(String(500))
    
    reliability_score = Column(Integer, default=5)
    language = Column(String(10), default="en")
    region = Column(String(50), default="global")
    country = Column(String(2), default="US")
    source_type = Column(String(50), default="news")
    update_frequency = Column(Integer, default=60)
    cacheability = Column(Boolean, default=True)
    
    articles = relationship("AsyncArticle", back_populates="source", cascade="all, delete-orphan")
    groups = relationship(
        "AsyncSourceGroup",
        secondary=async_source_group_association,
        back_populates="sources",
        lazy='dynamic'
    )
    source_metadata = relationship("AsyncSourceMetadata", back_populates="source", uselist=False, cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_async_source_domain', 'domain', unique=True),
        Index('idx_async_source_enabled', 'enabled'),
        Index('idx_async_source_priority', 'priority'),
        Index('idx_async_source_language', 'language'),
        Index('idx_async_source_region', 'region'),
        Index('idx_async_source_country', 'country'),
    )


class AsyncArticle(AsyncBase):
    """Async version of Article model."""
    __tablename__ = "async_articles"
    
    id = Column(Integer, primary_key=True)
    url = Column(String(1000), nullable=False)
    canonical_url = Column(String(1000), nullable=False)
    source_id = Column(Integer, ForeignKey("async_sources.id"), nullable=False)
    title = Column(String(500))
    content = Column(Text, nullable=False)
    compressed_content = Column(LargeBinary)
    published_at = Column(DateTime)
    language = Column(String(10))
    hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    
    region = Column(String(50))
    country = Column(String(2))
    author = Column(String(255))
    word_count = Column(Integer)
    reading_time = Column(Integer)
    
    sentiment_score = Column(Float)
    sentiment_label = Column(String(20))
    
    source = relationship("AsyncSource", back_populates="articles")
    
    __table_args__ = (
        Index("idx_async_article_hash", "hash", unique=True),
        Index("idx_async_article_canonical_url", "canonical_url"),
        Index("idx_async_article_source_id", "source_id"),
        Index("idx_async_article_content", "content"),
        Index("idx_async_article_language", "language"),
        Index("idx_async_article_region", "region"),
        Index("idx_async_article_country", "country"),
        Index("idx_async_article_author", "author"),
        Index("idx_async_article_published_at", "published_at"),
        Index("idx_async_article_created_at", "created_at"),
        Index("idx_async_article_source_published", "source_id", "published_at"),
        Index("idx_async_article_language_region", "language", "region"),
        Index("idx_async_article_word_count", "word_count"),
        Index("idx_async_article_sentiment", "sentiment_score"),
    )
    
    @property
    def is_compressed(self) -> bool:
        return self.compressed_content is not None
    
    def compress_content(self) -> None:
        if self.content and not self.compressed_content:
            from src.utils.compression import database_compressor
            self.compressed_content = database_compressor.compress_text_for_storage(self.content)
    
    def decompress_content(self) -> str:
        if self.compressed_content:
            from src.utils.compression import database_compressor
            return database_compressor.decompress_text_from_storage(self.compressed_content)
        return self.content or ""
    
    def get_content(self) -> str:
        if self.compressed_content:
            return self.decompress_content()
        return self.content or ""
    
    def set_content(self, content: str) -> None:
        self.content = content
        self.compressed_content = None


# =============================================================================
# Async Query Utilities
# =============================================================================

@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for async database sessions.
    
    Usage:
        async with get_async_session() as session:
            result = await session.execute(select(AsyncArticle))
            articles = result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    Transactional scope for async operations.
    
    Usage:
        async with async_session_scope() as session:
            # Do async database operations
            new_article = AsyncArticle(title="Test")
            session.add(new_article)
            await session.flush()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# =============================================================================
# Async CRUD Operations
# =============================================================================

class AsyncCRUD:
    """
    Async CRUD operations for database models.
    
    Provides common async CRUD operations with performance optimizations.
    """
    
    @staticmethod
    async def create(session: AsyncSession, obj: Any) -> Any:
        """Create a new record."""
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj
    
    @staticmethod
    async def get(
        session: AsyncSession, 
        model: Type, 
        id: int
    ) -> Optional[Any]:
        """Get a record by ID."""
        result = await session.execute(
            select(model).where(model.id == id)
        )
        return result.scalars().first()
    
    @staticmethod
    async def get_by_field(
        session: AsyncSession, 
        model: Type, 
        field: str, 
        value: Any
    ) -> Optional[Any]:
        """Get a record by field value."""
        result = await session.execute(
            select(model).where(getattr(model, field) == value)
        )
        return result.scalars().first()
    
    @staticmethod
    async def get_all(
        session: AsyncSession, 
        model: Type,
        limit: Optional[int] = None
    ) -> List[Any]:
        """Get all records."""
        query = select(model)
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_paginated(
        session: AsyncSession,
        model: Type,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        descending: bool = True
    ) -> Tuple[List[Any], int, int]:
        """
        Get paginated records.
        
        Returns:
            Tuple of (items, total_count, total_pages).
        """
        # Get total count
        count_result = await session.execute(
            select(func.count()).select_from(model)
        )
        total_count = count_result.scalar()
        
        # Calculate total pages
        total_pages = (total_count + page_size - 1) // page_size
        
        # Build query
        query = select(model)
        
        # Apply ordering
        if order_by and hasattr(model, order_by):
            column = getattr(model, order_by)
            if descending:
                query = query.order_by(desc(column))
            else:
                query = query.order_by(asc(column))
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        # Execute query
        result = await session.execute(query)
        items = result.scalars().all()
        
        return items, total_count, total_pages
    
    @staticmethod
    async def update(
        session: AsyncSession, 
        obj: Any
    ) -> Any:
        """Update a record."""
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj
    
    @staticmethod
    async def delete(
        session: AsyncSession, 
        obj: Any
    ) -> None:
        """Delete a record."""
        await session.delete(obj)
        await session.flush()
    
    @staticmethod
    async def delete_by_id(
        session: AsyncSession, 
        model: Type, 
        id: int
    ) -> bool:
        """Delete a record by ID."""
        obj = await AsyncCRUD.get(session, model, id)
        if obj:
            await session.delete(obj)
            await session.flush()
            return True
        return False
    
    @staticmethod
    async def search(
        session: AsyncSession,
        model: Type,
        search_term: str,
        search_fields: List[str],
        limit: int = 50
    ) -> List[Any]:
        """Search records by multiple fields."""
        conditions = []
        for field in search_fields:
            if hasattr(model, field):
                conditions.append(
                    getattr(model, field).ilike(f"%{search_term}%")
                )
        
        if not conditions:
            return []
        
        query = select(model).where(or_(*conditions)).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_by_hash(
        session: AsyncSession, 
        model: Type, 
        hash_value: str
    ) -> Optional[Any]:
        """Get a record by hash value (for duplicate detection)."""
        if hasattr(model, 'hash'):
            result = await session.execute(
                select(model).where(model.hash == hash_value)
            )
            return result.scalars().first()
        return None


# =============================================================================
# Async Query Builder
# =============================================================================

class AsyncQueryBuilder:
    """
    Builder for complex async queries with optimizations.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def build_article_query(
        self,
        source_id: Optional[int] = None,
        language: Optional[str] = None,
        region: Optional[str] = None,
        country: Optional[str] = None,
        published_after: Optional[datetime] = None,
        published_before: Optional[datetime] = None,
        search_term: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "published_at",
        descending: bool = True
    ) -> List[AsyncArticle]:
        """Build a complex article query."""
        query = select(AsyncArticle)
        
        # Apply filters
        if source_id is not None:
            query = query.where(AsyncArticle.source_id == source_id)
        
        if language is not None:
            query = query.where(AsyncArticle.language == language)
        
        if region is not None:
            query = query.where(AsyncArticle.region == region)
        
        if country is not None:
            query = query.where(AsyncArticle.country == country)
        
        if published_after is not None:
            query = query.where(AsyncArticle.published_at >= published_after)
        
        if published_before is not None:
            query = query.where(AsyncArticle.published_at <= published_before)
        
        if search_term is not None:
            query = query.where(
                or_(
                    AsyncArticle.title.ilike(f"%{search_term}%"),
                    AsyncArticle.content.ilike(f"%{search_term}%")
                )
            )
        
        # Apply ordering
        if order_by == "published_at":
            if descending:
                query = query.order_by(desc(AsyncArticle.published_at))
            else:
                query = query.order_by(asc(AsyncArticle.published_at))
        elif order_by == "created_at":
            if descending:
                query = query.order_by(desc(AsyncArticle.created_at))
            else:
                query = query.order_by(asc(AsyncArticle.created_at))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute query
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_article_count(
        self,
        source_id: Optional[int] = None,
        language: Optional[str] = None,
        region: Optional[str] = None,
        published_after: Optional[datetime] = None
    ) -> int:
        """Get count of articles matching criteria."""
        query = select(func.count()).select_from(AsyncArticle)
        
        if source_id is not None:
            query = query.where(AsyncArticle.source_id == source_id)
        
        if language is not None:
            query = query.where(AsyncArticle.language == language)
        
        if region is not None:
            query = query.where(AsyncArticle.region == region)
        
        if published_after is not None:
            query = query.where(AsyncArticle.published_at >= published_after)
        
        result = await self.session.execute(query)
        return result.scalar()
    
    async def get_recent_articles(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> List[AsyncArticle]:
        """Get articles published in the last N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = select(AsyncArticle)
        query = query.where(AsyncArticle.published_at >= cutoff)
        query = query.order_by(desc(AsyncArticle.published_at))
        query = query.limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()


# =============================================================================
# Async Batch Processing
# =============================================================================

class AsyncBatchProcessor:
    """
    Async batch processor for large datasets.
    """
    
    @staticmethod
    async def process_in_batches(
        items: List[Any],
        batch_size: int = 100,
        process_func: callable = None
    ) -> List[Any]:
        """Process items in async batches."""
        results = []
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            if process_func:
                result = await process_func(batch)
                results.append(result)
            else:
                results.append(batch)
        
        return results
    
    @staticmethod
    async def batch_create(
        session: AsyncSession,
        model: Type,
        data_list: List[Dict[str, Any]],
        batch_size: int = 100
    ) -> List[Any]:
        """Create multiple records in batches."""
        created_objects = []
        
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            batch_objects = [model(**data) for data in batch]
            
            session.add_all(batch_objects)
            await session.flush()
            
            # Refresh objects to get IDs
            for obj in batch_objects:
                await session.refresh(obj)
            
            created_objects.extend(batch_objects)
        
        return created_objects
    
    @staticmethod
    async def batch_update(
        session: AsyncSession,
        model: Type,
        filter_conditions: Dict[str, Any],
        update_data: Dict[str, Any],
        batch_size: int = 100
    ) -> int:
        """Update records in batches."""
        # For simplicity, we'll do a single update
        # In practice, for very large datasets, you'd need to batch
        
        query = select(model)
        for field, value in filter_conditions.items():
            if hasattr(model, field):
                query = query.where(getattr(model, field) == value)
        
        result = await session.execute(query)
        objects = result.scalars().all()
        
        for obj in objects:
            for field, value in update_data.items():
                if hasattr(obj, field):
                    setattr(obj, field, value)
        
        await session.flush()
        return len(objects)
    
    @staticmethod
    async def async_chunked_query(
        session: AsyncSession,
        query: Select,
        chunk_size: int = 100
    ) -> AsyncGenerator[List[Any], None]:
        """
        Execute a query in async chunks.
        
        Usage:
            async for chunk in AsyncBatchProcessor.async_chunked_query(session, query):
                process_chunk(chunk)
        """
        offset = 0
        
        while True:
            chunk_query = query.offset(offset).limit(chunk_size)
            result = await session.execute(chunk_query)
            items = result.scalars().all()
            
            if not items:
                break
            
            yield items
            offset += chunk_size


# =============================================================================
# Async Performance Utilities
# =============================================================================

class AsyncQueryOptimizer:
    """
    Async query optimizer with caching and performance monitoring.
    """
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, float] = {}
        self._cache_timeout = 300  # 5 minutes
    
    async def cached_query(
        self,
        session: AsyncSession,
        query: Select,
        cache_key: Optional[str] = None
    ) -> Any:
        """Execute a query with caching."""
        if cache_key is None:
            cache_key = str(query)
        
        # Check cache
        if cache_key in self._cache:
            if time.time() < self._cache_ttl.get(cache_key, 0):
                return self._cache[cache_key]
            else:
                # Cache expired
                del self._cache[cache_key]
                del self._cache_ttl[cache_key]
        
        # Execute query
        result = await session.execute(query)
        items = result.scalars().all()
        
        # Cache result
        self._cache[cache_key] = items
        self._cache_ttl[cache_key] = time.time() + self._cache_timeout
        
        return items
    
    async def with_timeout(
        self,
        coroutine: Any,
        timeout: float = 30.0
    ) -> Any:
        """Execute a coroutine with timeout."""
        try:
            return await asyncio.wait_for(coroutine, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Query timed out after {timeout} seconds")
            raise


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Async engine and session
    "async_engine",
    "AsyncSessionLocal",
    "AsyncBase",
    "get_async_session",
    "async_session_scope",
    # Async models
    "AsyncSourceGroup",
    "AsyncSourceMetadata",
    "AsyncSource",
    "AsyncArticle",
    # Async types
    "AsyncCompressedText",
    "AsyncCompressedJSON",
    # Async utilities
    "AsyncCRUD",
    "AsyncQueryBuilder",
    "AsyncBatchProcessor",
    "AsyncQueryOptimizer",
    # Configuration
    "ASYNC_DATABASE_URL",
    "get_async_database_config",
]
