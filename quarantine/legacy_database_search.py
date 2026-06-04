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
Full-Text Search Optimization for Open Omniscience

This module provides comprehensive full-text search capabilities including:
- PostgreSQL full-text search integration
- SQLite FTS5 virtual tables
- Search query optimization
- Result ranking and relevance scoring
- Search index management
- Advanced search features (fuzzy, phrase, proximity)

Author: Ideotion
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type, Union
import logging
import re

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
    text,
    case,
    cast,
)
from sqlalchemy.orm import Session, Query, joinedload
from sqlalchemy.sql import Select
from sqlalchemy.engine import Engine
from sqlalchemy.inspection import inspect

logger = logging.getLogger(__name__)


# =============================================================================
# Search Configuration
# =============================================================================

class SearchBackend(str, Enum):
    """Supported search backends."""
    SQLITE_FTS5 = "sqlite_fts5"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ELASTICSEARCH = "elasticsearch"
    WHOOSH = "whoosh"


@dataclass
class SearchConfig:
    """Configuration for search functionality."""
    backend: SearchBackend = SearchBackend.SQLITE_FTS5
    enabled: bool = True
    default_language: str = "english"
    min_word_length: int = 3
    max_word_length: int = 50
    enable_stemming: bool = True
    enable_fuzzy_search: bool = True
    fuzzy_distance: int = 2
    enable_phrase_search: bool = True
    enable_proximity_search: bool = True
    result_limit: int = 100
    snippet_length: int = 200
    highlight_tag: str = "em"
    
    # PostgreSQL specific
    postgres_weight_columns: Dict[str, float] = field(default_factory=lambda: {
        "title": 1.0,
        "content": 0.5,
        "author": 0.8,
        "tags": 1.2,
    })
    
    # Performance
    cache_enabled: bool = True
    cache_ttl: int = 300  # seconds
    
    @classmethod
    def from_env(cls) -> "SearchConfig":
        """Create config from environment variables."""
        import os
        
        backend_str = os.getenv("SEARCH_BACKEND", "sqlite_fts5")
        try:
            backend = SearchBackend(backend_str)
        except ValueError:
            backend = SearchBackend.SQLITE_FTS5
        
        return cls(
            backend=backend,
            enabled=os.getenv("SEARCH_ENABLED", "true").lower() == "true",
            default_language=os.getenv("SEARCH_LANGUAGE", "english"),
            min_word_length=int(os.getenv("SEARCH_MIN_WORD_LENGTH", "3")),
            max_word_length=int(os.getenv("SEARCH_MAX_WORD_LENGTH", "50")),
            enable_stemming=os.getenv("SEARCH_ENABLE_STEMMING", "true").lower() == "true",
            enable_fuzzy_search=os.getenv("SEARCH_ENABLE_FUZZY", "true").lower() == "true",
            fuzzy_distance=int(os.getenv("SEARCH_FUZZY_DISTANCE", "2")),
            result_limit=int(os.getenv("SEARCH_RESULT_LIMIT", "100")),
            cache_enabled=os.getenv("SEARCH_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl=int(os.getenv("SEARCH_CACHE_TTL", "300")),
        )


# Global search configuration
search_config = SearchConfig.from_env()


# =============================================================================
# Search Result Types
# =============================================================================

@dataclass
class SearchResult:
    """A single search result."""
    id: int
    model: str
    title: str
    url: Optional[str] = None
    content: Optional[str] = None
    score: float = 0.0
    snippet: Optional[str] = None
    highlighted: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        return f"SearchResult(id={self.id}, title='{self.title[:50]}', score={self.score:.4f})"


@dataclass
class SearchResults:
    """Collection of search results."""
    query: str
    results: List[SearchResult] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 1
    execution_time: float = 0.0
    facets: Dict[str, Dict[str, int]] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return (
            f"SearchResults(query='{self.query[:30]}', "
            f"total={self.total}, "
            f"execution_time={self.execution_time:.4f}s)"
        )


@dataclass
class SearchFacet:
    """A single facet for faceted search."""
    field: str
    value: str
    count: int
    
    def __repr__(self) -> str:
        return f"SearchFacet(field='{self.field}', value='{self.value}', count={self.count})"


# =============================================================================
# Search Index Management
# =============================================================================

class SearchIndexManager:
    """
    Manages search indexes for different backends.
    """
    
    def __init__(self, engine: Engine):
        """
        Initialize the search index manager.
        
        Args:
            engine: SQLAlchemy engine.
        """
        self.engine = engine
        self._inspector = inspect(engine)
        self._dialect = engine.dialect.name
    
    def get_backend(self) -> SearchBackend:
        """Get the appropriate search backend for this database."""
        if self._dialect == "postgresql":
            return SearchBackend.POSTGRESQL
        elif self._dialect == "mysql":
            return SearchBackend.MYSQL
        elif self._dialect == "sqlite":
            return SearchBackend.SQLITE_FTS5
        else:
            return SearchBackend.SQLITE_FTS5
    
    def create_indexes(self) -> bool:
        """Create necessary search indexes."""
        backend = self.get_backend()
        
        if backend == SearchBackend.POSTGRESQL:
            return self._create_postgresql_indexes()
        elif backend == SearchBackend.SQLITE_FTS5:
            return self._create_sqlite_indexes()
        elif backend == SearchBackend.MYSQL:
            return self._create_mysql_indexes()
        
        return False
    
    def _create_postgresql_indexes(self) -> bool:
        """Create PostgreSQL full-text search indexes."""
        try:
            with self.engine.connect() as conn:
                # Create GIN indexes for full-text search
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_articles_search_title 
                    ON articles USING GIN (to_tsvector('english', title))
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_articles_search_content 
                    ON articles USING GIN (to_tsvector('english', content))
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_articles_search_author 
                    ON articles USING GIN (to_tsvector('english', author))
                """))
                
                # Create weighted search index
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_articles_search_weighted 
                    ON articles USING GIN (
                        setweight(to_tsvector('english', title), 'A') ||
                        setweight(to_tsvector('english', content), 'B') ||
                        setweight(to_tsvector('english', author), 'C')
                    )
                """))
                
                conn.commit()
                logger.info("Created PostgreSQL full-text search indexes")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL indexes: {e}")
            return False
    
    def _create_sqlite_indexes(self) -> bool:
        """Create SQLite FTS5 virtual tables."""
        try:
            with self.engine.connect() as conn:
                # Create FTS5 virtual table for articles
                conn.execute(text("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts 
                    USING fts5(
                        id, 
                        title, 
                        content, 
                        author, 
                        tags,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                """))
                
                # Create triggers to keep FTS table in sync
                conn.execute(text("""
                    CREATE TRIGGER IF NOT EXISTS articles_fts_insert 
                    AFTER INSERT ON articles 
                    BEGIN 
                        INSERT INTO articles_fts 
                        VALUES (new.id, new.title, new.content, new.author, new.tags);
                    END
                """))
                
                conn.execute(text("""
                    CREATE TRIGGER IF NOT EXISTS articles_fts_update 
                    AFTER UPDATE ON articles 
                    BEGIN 
                        UPDATE articles_fts 
                        SET title = new.title, 
                            content = new.content, 
                            author = new.author, 
                            tags = new.tags 
                        WHERE id = new.id;
                    END
                """))
                
                conn.execute(text("""
                    CREATE TRIGGER IF NOT EXISTS articles_fts_delete 
                    AFTER DELETE ON articles 
                    BEGIN 
                        DELETE FROM articles_fts WHERE id = old.id;
                    END
                """))
                
                conn.commit()
                logger.info("Created SQLite FTS5 virtual tables")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create SQLite FTS5 tables: {e}")
            return False
    
    def _create_mysql_indexes(self) -> bool:
        """Create MySQL full-text indexes."""
        try:
            with self.engine.connect() as conn:
                # Create full-text index
                conn.execute(text("""
                    ALTER TABLE articles 
                    ADD FULLTEXT INDEX idx_articles_fulltext 
                    (title, content, author, tags)
                """))
                
                conn.commit()
                logger.info("Created MySQL full-text indexes")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create MySQL indexes: {e}")
            return False
    
    def sync_indexes(self) -> bool:
        """Synchronize search indexes with database."""
        backend = self.get_backend()
        
        if backend == SearchBackend.SQLITE_FTS5:
            return self._sync_sqlite_indexes()
        
        # For other backends, indexes are updated automatically
        return True
    
    def _sync_sqlite_indexes(self) -> bool:
        """Rebuild SQLite FTS5 tables."""
        try:
            with self.engine.connect() as conn:
                # Rebuild FTS table
                conn.execute(text("""
                    INSERT OR REPLACE INTO articles_fts 
                    SELECT id, title, content, author, tags FROM articles
                """))
                
                conn.commit()
                logger.info("Rebuilt SQLite FTS5 tables")
                return True
                
        except Exception as e:
            logger.error(f"Failed to rebuild SQLite FTS5 tables: {e}")
            return False
    
    def drop_indexes(self) -> bool:
        """Drop all search indexes."""
        backend = self.get_backend()
        
        if backend == SearchBackend.POSTGRESQL:
            return self._drop_postgresql_indexes()
        elif backend == SearchBackend.SQLITE_FTS5:
            return self._drop_sqlite_indexes()
        elif backend == SearchBackend.MYSQL:
            return self._drop_mysql_indexes()
        
        return False
    
    def _drop_postgresql_indexes(self) -> bool:
        """Drop PostgreSQL full-text search indexes."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("DROP INDEX IF EXISTS idx_articles_search_title"))
                conn.execute(text("DROP INDEX IF EXISTS idx_articles_search_content"))
                conn.execute(text("DROP INDEX IF EXISTS idx_articles_search_author"))
                conn.execute(text("DROP INDEX IF EXISTS idx_articles_search_weighted"))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to drop PostgreSQL indexes: {e}")
            return False
    
    def _drop_sqlite_indexes(self) -> bool:
        """Drop SQLite FTS5 tables."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS articles_fts"))
                conn.execute(text("DROP TRIGGER IF EXISTS articles_fts_insert"))
                conn.execute(text("DROP TRIGGER IF EXISTS articles_fts_update"))
                conn.execute(text("DROP TRIGGER IF EXISTS articles_fts_delete"))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to drop SQLite FTS5 tables: {e}")
            return False
    
    def _drop_mysql_indexes(self) -> bool:
        """Drop MySQL full-text indexes."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE articles DROP INDEX idx_articles_fulltext
                """))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to drop MySQL indexes: {e}")
            return False


# =============================================================================
# Search Query Builder
# =============================================================================

class SearchQueryBuilder:
    """
    Builds optimized search queries for different backends.
    """
    
    def __init__(self, session: Session, config: Optional[SearchConfig] = None):
        """
        Initialize the search query builder.
        
        Args:
            session: SQLAlchemy session.
            config: Search configuration.
        """
        self.session = session
        self.config = config or search_config
        self._dialect = session.bind.dialect.name
    
    def build_search_query(
        self,
        query: str,
        model: Optional[Type] = None,
        fields: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: Optional[str] = None,
        descending: bool = True
    ) -> Query:
        """
        Build a search query.
        
        Args:
            query: Search query string.
            model: SQLAlchemy model to search.
            fields: List of fields to search.
            filters: Additional filter conditions.
            limit: Maximum number of results.
            offset: Offset for pagination.
            order_by: Field to order by.
            descending: Whether to sort in descending order.
            
        Returns:
            SQLAlchemy Query object.
        """
        if model is None:
            from src.database.models import Article
            model = Article
        
        if fields is None:
            fields = ["title", "content", "author", "tags"]
        
        if limit is None:
            limit = self.config.result_limit
        
        # Build base query
        if self._dialect == "postgresql":
            return self._build_postgresql_query(
                query, model, fields, filters, limit, offset, order_by, descending
            )
        elif self._dialect == "sqlite":
            return self._build_sqlite_query(
                query, model, fields, filters, limit, offset, order_by, descending
            )
        elif self._dialect == "mysql":
            return self._build_mysql_query(
                query, model, fields, filters, limit, offset, order_by, descending
            )
        else:
            # Fallback to simple LIKE query
            return self._build_simple_query(
                query, model, fields, filters, limit, offset, order_by, descending
            )
    
    def _build_postgresql_query(
        self,
        query: str,
        model: Type,
        fields: List[str],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int,
        order_by: Optional[str],
        descending: bool
    ) -> Query:
        """Build a PostgreSQL full-text search query."""
        from sqlalchemy import func as sql_func
        
        # Build search vector
        search_vector = None
        weights = self.config.postgres_weight_columns
        
        for field in fields:
            if hasattr(model, field):
                column = getattr(model, field)
                weight = weights.get(field, 0.5)
                
                if search_vector is None:
                    search_vector = sql_func.setweight(
                        sql_func.to_tsvector(self.config.default_language, column),
                        'A' if weight >= 1.0 else 'B' if weight >= 0.7 else 'C'
                    )
                else:
                    search_vector = search_vector or sql_func.setweight(
                        sql_func.to_tsvector(self.config.default_language, column),
                        'A' if weight >= 1.0 else 'B' if weight >= 0.7 else 'C'
                    )
        
        if search_vector is None:
            return self.session.query(model).limit(0)
        
        # Build query
        ts_query = sql_func.plainto_tsquery(self.config.default_language, query)
        
        # Create the search condition
        search_condition = search_vector.op('@@')(ts_query)
        
        # Start with select
        q = self.session.query(model)
        
        # Apply search condition
        q = q.filter(search_condition)
        
        # Apply additional filters
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, (list, tuple)):
                        q = q.filter(column.in_(value))
                    else:
                        q = q.filter(column == value)
        
        # Apply ordering
        if order_by and hasattr(model, order_by):
            column = getattr(model, order_by)
            if descending:
                q = q.order_by(desc(column))
            else:
                q = q.order_by(asc(column))
        else:
            # Default ordering by relevance (ts_rank)
            q = q.order_by(
                desc(sql_func.ts_rank(
                    search_vector,
                    ts_query
                ))
            )
        
        # Apply pagination
        q = q.offset(offset).limit(limit)
        
        return q
    
    def _build_sqlite_query(
        self,
        query: str,
        model: Type,
        fields: List[str],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int,
        order_by: Optional[str],
        descending: bool
    ) -> Query:
        """Build a SQLite FTS5 search query."""
        # For SQLite, we need to join with the FTS5 table
        from sqlalchemy import Table, MetaData
        
        metadata = MetaData()
        fts_table = Table('articles_fts', metadata, autoload_with=self.session.bind)
        
        # Build the FTS5 query
        fts_query = query
        
        # Create the join condition
        q = self.session.query(model).join(
            fts_table,
            model.id == fts_table.c.id
        )
        
        # Apply FTS5 search
        q = q.filter(fts_table.c.match(fts_query))
        
        # Apply additional filters
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, (list, tuple)):
                        q = q.filter(column.in_(value))
                    else:
                        q = q.filter(column == value)
        
        # Apply ordering
        if order_by and hasattr(model, order_by):
            column = getattr(model, order_by)
            if descending:
                q = q.order_by(desc(column))
            else:
                q = q.order_by(asc(column))
        else:
            # Default ordering by rank (if available)
            if hasattr(fts_table.c, 'rank'):
                q = q.order_by(desc(fts_table.c.rank))
        
        # Apply pagination
        q = q.offset(offset).limit(limit)
        
        return q
    
    def _build_mysql_query(
        self,
        query: str,
        model: Type,
        fields: List[str],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int,
        order_by: Optional[str],
        descending: bool
    ) -> Query:
        """Build a MySQL full-text search query."""
        from sqlalchemy import func as sql_func
        
        # Build the MATCH...AGAINST query
        match_columns = []
        for field in fields:
            if hasattr(model, field):
                match_columns.append(getattr(model, field))
        
        if not match_columns:
            return self.session.query(model).limit(0)
        
        # Create the MATCH...AGAINST condition
        search_condition = sql_func.match(*match_columns).against(query, modifier='IN NATURAL LANGUAGE MODE')
        
        # Start with select
        q = self.session.query(model)
        
        # Apply search condition
        q = q.filter(search_condition)
        
        # Apply additional filters
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, (list, tuple)):
                        q = q.filter(column.in_(value))
                    else:
                        q = q.filter(column == value)
        
        # Apply ordering
        if order_by and hasattr(model, order_by):
            column = getattr(model, order_by)
            if descending:
                q = q.order_by(desc(column))
            else:
                q = q.order_by(asc(column))
        
        # Apply pagination
        q = q.offset(offset).limit(limit)
        
        return q
    
    def _build_simple_query(
        self,
        query: str,
        model: Type,
        fields: List[str],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int,
        order_by: Optional[str],
        descending: bool
    ) -> Query:
        """Build a simple LIKE-based search query (fallback)."""
        # Build OR conditions for each field
        conditions = []
        for field in fields:
            if hasattr(model, field):
                column = getattr(model, field)
                conditions.append(column.ilike(f"%{query}%"))
        
        if not conditions:
            return self.session.query(model).limit(0)
        
        # Start with select
        q = self.session.query(model)
        
        # Apply search conditions
        q = q.filter(or_(*conditions))
        
        # Apply additional filters
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, (list, tuple)):
                        q = q.filter(column.in_(value))
                    else:
                        q = q.filter(column == value)
        
        # Apply ordering
        if order_by and hasattr(model, order_by):
            column = getattr(model, order_by)
            if descending:
                q = q.order_by(desc(column))
            else:
                q = q.order_by(asc(column))
        
        # Apply pagination
        q = q.offset(offset).limit(limit)
        
        return q
    
    def build_faceted_search(
        self,
        query: str,
        model: Optional[Type] = None,
        fields: Optional[List[str]] = None,
        facet_fields: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> Tuple[Query, List[Query]]:
        """
        Build a faceted search query.
        
        Args:
            query: Search query string.
            model: SQLAlchemy model to search.
            fields: List of fields to search.
            facet_fields: List of fields to create facets for.
            filters: Additional filter conditions.
            limit: Maximum number of results.
            
        Returns:
            Tuple of (main query, list of facet queries).
        """
        if model is None:
            from src.database.models import Article
            model = Article
        
        if fields is None:
            fields = ["title", "content", "author", "tags"]
        
        if facet_fields is None:
            facet_fields = ["language", "region", "country", "source_id"]
        
        if limit is None:
            limit = self.config.result_limit
        
        # Build main query
        main_query = self.build_search_query(
            query, model, fields, filters, limit
        )
        
        # Build facet queries
        facet_queries = []
        for facet_field in facet_fields:
            if hasattr(model, facet_field):
                facet_query = self._build_facet_query(
                    model, facet_field, query, fields, filters
                )
                facet_queries.append(facet_query)
        
        return main_query, facet_queries
    
    def _build_facet_query(
        self,
        model: Type,
        facet_field: str,
        query: str,
        fields: List[str],
        filters: Optional[Dict[str, Any]]
    ) -> Query:
        """Build a query for a single facet."""
        from sqlalchemy import func as sql_func
        
        # Get the facet column
        facet_column = getattr(model, facet_field)
        
        # Build search conditions
        search_conditions = []
        for field in fields:
            if hasattr(model, field):
                column = getattr(model, field)
                search_conditions.append(column.ilike(f"%{query}%"))
        
        # Start with select
        q = self.session.query(facet_column, sql_func.count().label('count'))
        
        # Apply search conditions
        if search_conditions:
            q = q.filter(or_(*search_conditions))
        
        # Apply additional filters (excluding the facet field itself)
        if filters:
            for field, value in filters.items():
                if field != facet_field and hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, (list, tuple)):
                        q = q.filter(column.in_(value))
                    else:
                        q = q.filter(column == value)
        
        # Group by facet field
        q = q.group_by(facet_column)
        
        return q


# =============================================================================
# Search Service
# =============================================================================

class SearchService:
    """
    High-level search service with advanced features.
    """
    
    def __init__(
        self, 
        session: Session, 
        config: Optional[SearchConfig] = None
    ):
        """
        Initialize the search service.
        
        Args:
            session: SQLAlchemy session.
            config: Search configuration.
        """
        self.session = session
        self.config = config or search_config
        self.query_builder = SearchQueryBuilder(session, self.config)
        self._cache: Dict[str, SearchResults] = {}
        self._cache_ttl: Dict[str, float] = {}
    
    def search(
        self,
        query: str,
        model: Optional[Type] = None,
        fields: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        descending: bool = True,
        include_facets: bool = False,
        facet_fields: Optional[List[str]] = None
    ) -> SearchResults:
        """
        Execute a search query.
        
        Args:
            query: Search query string.
            model: SQLAlchemy model to search.
            fields: List of fields to search.
            filters: Additional filter conditions.
            page: Page number for pagination.
            page_size: Number of items per page.
            order_by: Field to order by.
            descending: Whether to sort in descending order.
            include_facets: Whether to include faceted search results.
            facet_fields: List of fields to create facets for.
            
        Returns:
            SearchResults object.
        """
        import time
        start_time = time.time()
        
        # Check cache
        cache_key = self._generate_cache_key(
            query, model, fields, filters, page, page_size, order_by, descending
        )
        
        if self.config.cache_enabled and cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() < self._cache_ttl.get(cache_key, 0):
                # Update execution time
                cached.execution_time = time.time() - start_time
                return cached
        
        # Build and execute main query
        offset = (page - 1) * page_size
        
        if include_facets:
            main_query, facet_queries = self.query_builder.build_faceted_search(
                query, model, fields, facet_fields, filters, page_size
            )
            
            # Execute main query
            main_results = main_query.offset(offset).limit(page_size).all()
            
            # Execute facet queries
            facets = {}
            for facet_query in facet_queries:
                facet_results = facet_query.all()
                for row in facet_results:
                    field_name = row[0].__name__ if hasattr(row[0], '__name__') else str(row[0])
                    if field_name not in facets:
                        facets[field_name] = {}
                    facets[field_name][str(row[0])] = row[1]
        else:
            main_query = self.query_builder.build_search_query(
                query, model, fields, filters, page_size, offset, order_by, descending
            )
            main_results = main_query.all()
            facets = {}
        
        # Get total count
        count_query = self.query_builder.build_search_query(
            query, model, fields, filters, None, 0, None, False
        )
        total = len(count_query.all())
        
        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size
        
        # Convert results to SearchResult objects
        results = []
        for row in main_results:
            obj = row[0] if isinstance(row, tuple) else row
            result = self._convert_to_search_result(obj)
            results.append(result)
        
        # Generate snippets and highlighting
        for result in results:
            result.snippet = self._generate_snippet(result.content or "", query)
            result.highlighted = self._highlight_text(result.content or "", query)
        
        # Create SearchResults object
        search_results = SearchResults(
            query=query,
            results=results,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            execution_time=time.time() - start_time,
            facets=facets
        )
        
        # Cache results
        if self.config.cache_enabled:
            self._cache[cache_key] = search_results
            self._cache_ttl[cache_key] = time.time() + self.config.cache_ttl
        
        return search_results
    
    def _generate_cache_key(
        self,
        query: str,
        model: Optional[Type],
        fields: Optional[List[str]],
        filters: Optional[Dict[str, Any]],
        page: int,
        page_size: int,
        order_by: Optional[str],
        descending: bool
    ) -> str:
        """Generate a cache key for the search query."""
        parts = [
            query,
            str(model) if model else "",
            str(fields) if fields else "",
            str(filters) if filters else "",
            str(page),
            str(page_size),
            order_by or "",
            str(descending)
        ]
        return "|".join(parts)
    
    def _convert_to_search_result(self, obj: Any) -> SearchResult:
        """Convert a database object to a SearchResult."""
        title = getattr(obj, 'title', '') or ''
        url = getattr(obj, 'url', None)
        content = getattr(obj, 'content', None)
        
        # Try to get a score if available
        score = 0.0
        if hasattr(obj, '_rank'):
            score = float(obj._rank) if obj._rank else 0.0
        
        # Get metadata
        metadata = {}
        for attr in ['id', 'source_id', 'published_at', 'language', 'region', 'country']:
            if hasattr(obj, attr):
                value = getattr(obj, attr)
                if value is not None:
                    metadata[attr] = str(value)
        
        return SearchResult(
            id=getattr(obj, 'id', 0),
            model=obj.__class__.__name__,
            title=title[:200],  # Limit title length
            url=url,
            content=content[:1000] if content else None,  # Limit content length
            score=score,
            metadata=metadata
        )
    
    def _generate_snippet(self, text: str, query: str) -> Optional[str]:
        """Generate a text snippet with query terms highlighted."""
        if not text or not query:
            return None
        
        # Simple snippet generation - find first occurrence of query terms
        query_terms = re.split(r'\s+', query)
        text_lower = text.lower()
        
        # Find positions of query terms
        positions = []
        for term in query_terms:
            if term:
                pos = text_lower.find(term.lower())
                if pos >= 0:
                    positions.append(pos)
        
        if not positions:
            # No matches found, return first part of text
            return text[:self.config.snippet_length]
        
        # Find the earliest position
        start_pos = min(positions)
        
        # Adjust start position to get context
        start_pos = max(0, start_pos - 20)
        end_pos = min(len(text), start_pos + self.config.snippet_length)
        
        snippet = text[start_pos:end_pos]
        
        # Add ellipsis if truncated
        if start_pos > 0:
            snippet = "..." + snippet
        if end_pos < len(text):
            snippet = snippet + "..."
        
        return snippet
    
    def _highlight_text(self, text: str, query: str) -> Optional[str]:
        """Highlight query terms in text."""
        if not text or not query:
            return None
        
        query_terms = re.split(r'\s+', query)
        highlighted = text
        
        for term in query_terms:
            if term:
                # Case-insensitive replacement
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                highlighted = pattern.sub(
                    f"<{self.config.highlight_tag}>\\g<0></{self.config.highlight_tag}>",
                    highlighted
                )
        
        return highlighted
    
    def suggest(
        self,
        query: str,
        model: Optional[Type] = None,
        field: str = "title",
        limit: int = 10
    ) -> List[str]:
        """
        Get search suggestions (autocomplete).
        
        Args:
            query: Partial query string.
            model: SQLAlchemy model to search.
            field: Field to get suggestions from.
            limit: Maximum number of suggestions.
            
        Returns:
            List of suggestion strings.
        """
        if model is None:
            from src.database.models import Article
            model = Article
        
        if not hasattr(model, field):
            return []
        
        column = getattr(model, field)
        
        # Build query
        q = self.session.query(column)
        
        # Filter by partial match
        q = q.filter(column.ilike(f"{query}%"))
        
        # Group and count
        from sqlalchemy import func as sql_func
        q = q.group_by(column).order_by(sql_func.count(column).desc())
        
        # Limit results
        q = q.limit(limit)
        
        # Execute and return results
        results = q.all()
        return [str(row[0]) for row in results if row[0]]
    
    def advanced_search(
        self,
        query: str,
        model: Optional[Type] = None,
        fields: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        search_type: str = "standard",
        fuzzy: bool = False,
        phrase: bool = False,
        proximity_distance: Optional[int] = None,
        page: int = 1,
        page_size: int = 20
    ) -> SearchResults:
        """
        Execute an advanced search with special search types.
        
        Args:
            query: Search query string.
            model: SQLAlchemy model to search.
            fields: List of fields to search.
            filters: Additional filter conditions.
            search_type: Type of search ('standard', 'fuzzy', 'phrase', 'proximity').
            fuzzy: Whether to use fuzzy search.
            phrase: Whether to search for exact phrase.
            proximity_distance: Maximum distance between terms for proximity search.
            page: Page number for pagination.
            page_size: Number of items per page.
            
        Returns:
            SearchResults object.
        """
        # Modify query based on search type
        modified_query = query
        
        if phrase:
            modified_query = f'"{query}"'
        elif fuzzy and self.config.enable_fuzzy_search:
            modified_query = f"{query}:*"
        elif proximity_distance:
            # PostgreSQL proximity search syntax
            modified_query = f"{query} <{proximity_distance}>"
        
        return self.search(
            modified_query,
            model=model,
            fields=fields,
            filters=filters,
            page=page,
            page_size=page_size
        )
    
    def clear_cache(self) -> None:
        """Clear the search cache."""
        self._cache.clear()
        self._cache_ttl.clear()


# =============================================================================
# Search Index Models (for dedicated search tables)
# =============================================================================

class SearchIndexBase:
    """Base class for search index models."""
    pass


# =============================================================================
# Utility Functions
# =============================================================================

def get_search_service(session: Session) -> SearchService:
    """
    Get a SearchService instance.
    
    Args:
        session: SQLAlchemy session.
        
    Returns:
        SearchService instance.
    """
    return SearchService(session)


def get_search_query_builder(session: Session) -> SearchQueryBuilder:
    """
    Get a SearchQueryBuilder instance.
    
    Args:
        session: SQLAlchemy session.
        
    Returns:
        SearchQueryBuilder instance.
    """
    return SearchQueryBuilder(session)


def get_search_index_manager(engine: Engine) -> SearchIndexManager:
    """
    Get a SearchIndexManager instance.
    
    Args:
        engine: SQLAlchemy engine.
        
    Returns:
        SearchIndexManager instance.
    """
    return SearchIndexManager(engine)


def create_search_indexes(engine: Engine) -> bool:
    """
    Create search indexes for the database.
    
    Args:
        engine: SQLAlchemy engine.
        
    Returns:
        True if indexes were created successfully.
    """
    manager = SearchIndexManager(engine)
    return manager.create_indexes()


def sync_search_indexes(engine: Engine) -> bool:
    """
    Synchronize search indexes with the database.
    
    Args:
        engine: SQLAlchemy engine.
        
    Returns:
        True if synchronization was successful.
    """
    manager = SearchIndexManager(engine)
    return manager.sync_indexes()


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Configuration
    "SearchConfig",
    "search_config",
    "SearchBackend",
    # Result types
    "SearchResult",
    "SearchResults",
    "SearchFacet",
    # Services
    "SearchService",
    "SearchQueryBuilder",
    "SearchIndexManager",
    # Utility functions
    "get_search_service",
    "get_search_query_builder",
    "get_search_index_manager",
    "create_search_indexes",
    "sync_search_indexes",
]
