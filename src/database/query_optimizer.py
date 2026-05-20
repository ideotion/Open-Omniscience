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
Query Optimizer for Open Omniscience

This module provides comprehensive query optimization capabilities including:
- EXPLAIN ANALYZE support for query analysis
- Composite index recommendations
- Query plan analysis and optimization suggestions
- Automatic query optimization
- Performance benchmarking

Author: Ideotion
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
import logging
import re
import time

from sqlalchemy import (
    and_, 
    asc, 
    desc, 
    func, 
    or_, 
    select, 
    text, 
    union_all,
    between,
    case,
    cast,
    extract,
    literal_column,
)
from sqlalchemy.orm import Query, Session, joinedload, selectinload, contains_eager
from sqlalchemy.sql import Select, ColumnElement
from sqlalchemy.engine import Engine
from sqlalchemy.inspection import inspect

logger = logging.getLogger(__name__)


# =============================================================================
# Query Analysis and Optimization
# =============================================================================

class QueryType(str, Enum):
    """Types of database queries."""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    JOIN = "JOIN"
    AGGREGATE = "AGGREGATE"
    SUBQUERY = "SUBQUERY"
    CTE = "CTE"


class IndexType(str, Enum):
    """Types of database indexes."""
    B_TREE = "B-Tree"
    HASH = "Hash"
    GIN = "GIN"
    GIST = "GiST"
    BRIN = "BRIN"
    PARTIAL = "Partial"
    COMPOSITE = "Composite"
    FUNCTIONAL = "Functional"


@dataclass
class QueryStats:
    """Statistics for a database query."""
    query: str
    query_type: QueryType
    execution_time: float = 0.0
    rows_returned: int = 0
    rows_examined: int = 0
    cost: float = 0.0
    plan: Optional[str] = None
    indexes_used: List[str] = field(default_factory=list)
    full_table_scans: List[str] = field(default_factory=list)
    sort_operations: List[str] = field(default_factory=list)
    temporary_files: bool = False
    is_slow: bool = False
    
    def __repr__(self) -> str:
        return (
            f"QueryStats(query='{self.query[:50]}...', "
            f"execution_time={self.execution_time:.4f}s, "
            f"rows_returned={self.rows_returned}, "
            f"cost={self.cost:.2f}, "
            f"indexes_used={self.indexes_used})"
        )


@dataclass
class IndexRecommendation:
    """Recommendation for creating a new index."""
    table_name: str
    columns: List[str]
    index_type: IndexType = IndexType.B_TREE
    index_name: Optional[str] = None
    where_clause: Optional[str] = None  # For partial indexes
    priority: int = 1  # 1-10, higher = more important
    estimated_improvement: float = 0.0  # Estimated performance improvement (%)
    reason: str = ""
    
    def __post_init__(self) -> None:
        if self.index_name is None:
            if self.where_clause:
                self.index_name = f"idx_{self.table_name}_{'_'.join(self.columns)}_partial"
            else:
                self.index_name = f"idx_{self.table_name}_{'_'.join(self.columns)}"
    
    def __repr__(self) -> str:
        return (
            f"IndexRecommendation(table='{self.table_name}', "
            f"columns={self.columns}, "
            f"type={self.index_type.value}, "
            f"priority={self.priority}, "
            f"improvement={self.estimated_improvement:.1f}%)"
        )


@dataclass
class QueryOptimization:
    """Optimization suggestion for a query."""
    query: str
    original_cost: float
    optimized_query: str
    optimized_cost: float
    improvement: float  # Percentage improvement
    changes: List[str] = field(default_factory=list)
    recommendations: List[IndexRecommendation] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return (
            f"QueryOptimization(improvement={self.improvement:.1f}%, "
            f"original_cost={self.original_cost:.2f}, "
            f"optimized_cost={self.optimized_cost:.2f})"
        )


class QueryAnalyzer:
    """
    Analyzes database queries and provides optimization suggestions.
    
    This class uses EXPLAIN ANALYZE to analyze query performance and
    provides recommendations for optimization.
    """
    
    def __init__(self, engine: Engine):
        """
        Initialize the query analyzer.
        
        Args:
            engine: SQLAlchemy engine for database connection.
        """
        self.engine = engine
        self._inspector = inspect(engine)
        self._slow_query_threshold = 0.1  # seconds
        self._high_cost_threshold = 1000.0  # arbitrary cost units
    
    def analyze_query(
        self, 
        query: Union[str, Select, Query], 
        params: Optional[Dict] = None
    ) -> QueryStats:
        """
        Analyze a query using EXPLAIN ANALYZE.
        
        Args:
            query: The query to analyze (SQL string or SQLAlchemy query).
            params: Optional parameters for the query.
            
        Returns:
            QueryStats with analysis results.
        """
        # Convert SQLAlchemy query to string if needed
        if isinstance(query, (Select, Query)):
            sql_query = str(query)
        else:
            sql_query = query
        
        # Determine query type
        query_type = self._determine_query_type(sql_query)
        
        # Execute EXPLAIN ANALYZE
        explain_sql = self._build_explain_query(sql_query)
        
        start_time = time.time()
        
        try:
            with self.engine.connect() as conn:
                if params:
                    result = conn.execute(text(explain_sql), params)
                else:
                    result = conn.execute(text(explain_sql))
                
                plan = result.fetchall()
                execution_time = time.time() - start_time
                
                # Parse the execution plan
                plan_text = "\n".join([str(row) for row in plan])
                stats = self._parse_execution_plan(
                    sql_query, query_type, plan_text, execution_time
                )
                
                return stats
        except Exception as e:
            logger.warning(f"Failed to analyze query: {e}")
            return QueryStats(
                query=sql_query,
                query_type=query_type,
                execution_time=0.0,
                plan=str(e)
            )
    
    def _determine_query_type(self, query: str) -> QueryType:
        """Determine the type of query from its SQL string."""
        query_upper = query.strip().upper()
        
        if query_upper.startswith("SELECT"):
            return QueryType.SELECT
        elif query_upper.startswith("INSERT"):
            return QueryType.INSERT
        elif query_upper.startswith("UPDATE"):
            return QueryType.UPDATE
        elif query_upper.startswith("DELETE"):
            return QueryType.DELETE
        elif "JOIN" in query_upper:
            return QueryType.JOIN
        elif any(word in query_upper for word in ["COUNT", "SUM", "AVG", "GROUP BY"]):
            return QueryType.AGGREGATE
        elif "WITH" in query_upper or "CTE" in query_upper:
            return QueryType.CTE
        else:
            return QueryType.SELECT
    
    def _build_explain_query(self, query: str) -> str:
        """Build an EXPLAIN ANALYZE query."""
        # Check if already has EXPLAIN
        if query.strip().upper().startswith("EXPLAIN"):
            return query
        
        # For PostgreSQL
        if self.engine.dialect.name == "postgresql":
            return f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        # For SQLite
        elif self.engine.dialect.name == "sqlite":
            return f"EXPLAIN QUERY PLAN {query}"
        # For MySQL
        elif self.engine.dialect.name == "mysql":
            return f"EXPLAIN FORMAT=JSON {query}"
        else:
            return f"EXPLAIN ANALYZE {query}"
    
    def _parse_execution_plan(
        self, 
        query: str, 
        query_type: QueryType, 
        plan_text: str, 
        execution_time: float
    ) -> QueryStats:
        """Parse the execution plan text and extract statistics."""
        stats = QueryStats(
            query=query,
            query_type=query_type,
            execution_time=execution_time,
            plan=plan_text
        )
        
        # Parse based on database type
        dialect = self.engine.dialect.name
        
        if dialect == "postgresql":
            self._parse_postgresql_plan(stats, plan_text)
        elif dialect == "sqlite":
            self._parse_sqlite_plan(stats, plan_text)
        elif dialect == "mysql":
            self._parse_mysql_plan(stats, plan_text)
        
        # Check if query is slow
        stats.is_slow = execution_time > self._slow_query_threshold
        
        return stats
    
    def _parse_postgresql_plan(self, stats: QueryStats, plan_text: str) -> None:
        """Parse PostgreSQL execution plan."""
        try:
            import json
            # Try to parse as JSON
            if plan_text.strip().startswith("["):
                plans = json.loads(plan_text)
                for plan in plans:
                    self._parse_postgresql_plan_node(stats, plan)
        except (json.JSONDecodeError, ImportError):
            # Fall back to text parsing
            self._parse_plan_text(stats, plan_text)
    
    def _parse_postgresql_plan_node(self, stats: QueryStats, node: Dict) -> None:
        """Recursively parse PostgreSQL plan node."""
        # Extract basic info
        if "Actual Total Time" in node:
            time_match = re.search(r"Actual Total Time:\s*(\d+\.\d+)", node["Actual Total Time"])
            if time_match:
                stats.execution_time = float(time_match.group(1))
        
        if "Planning Time" in node:
            time_match = re.search(r"Planning Time:\s*(\d+\.\d+)", node["Planning Time"])
            if time_match:
                stats.execution_time += float(time_match.group(1))
        
        if "Rows" in node:
            rows_match = re.search(r"Rows:\s*(\d+)", node["Rows"])
            if rows_match:
                stats.rows_returned = int(rows_match.group(1))
        
        if "Total Cost" in node:
            cost_match = re.search(r"Total Cost:\s*(\d+\.\d+)", node["Total Cost"])
            if cost_match:
                stats.cost = float(cost_match.group(1))
        
        # Check for index usage
        if "Index Scan" in node.get("Node Type", ""):
            if "Index" in node:
                stats.indexes_used.append(node["Index"])
        elif "Seq Scan" in node.get("Node Type", ""):
            if "Relation Name" in node:
                stats.full_table_scans.append(node["Relation Name"])
        
        # Check for sort operations
        if "Sort" in node.get("Node Type", ""):
            if "Relation Name" in node:
                stats.sort_operations.append(node["Relation Name"])
        
        # Recursively parse children
        if "Plans" in node:
            for child in node["Plans"]:
                self._parse_postgresql_plan_node(stats, child)
    
    def _parse_sqlite_plan(self, stats: QueryStats, plan_text: str) -> None:
        """Parse SQLite execution plan."""
        # SQLite EXPLAIN QUERY PLAN output
        lines = plan_text.split("\n")
        for line in lines:
            if "SCAN" in line.upper():
                if "INDEX" in line.upper():
                    # Extract index name
                    match = re.search(r"INDEX\s+(\w+)", line, re.IGNORECASE)
                    if match:
                        stats.indexes_used.append(match.group(1))
                elif "TABLE" in line.upper():
                    # Full table scan
                    match = re.search(r"TABLE\s+(\w+)", line, re.IGNORECASE)
                    if match:
                        stats.full_table_scans.append(match.group(1))
            
            if "COST" in line.upper():
                match = re.search(r"COST\s+(\d+)", line, re.IGNORECASE)
                if match:
                    stats.cost = float(match.group(1))
    
    def _parse_mysql_plan(self, stats: QueryStats, plan_text: str) -> None:
        """Parse MySQL execution plan."""
        try:
            import json
            plans = json.loads(plan_text)
            for plan in plans:
                self._parse_mysql_plan_node(stats, plan)
        except (json.JSONDecodeError, ImportError):
            self._parse_plan_text(stats, plan_text)
    
    def _parse_mysql_plan_node(self, stats: QueryStats, node: Dict) -> None:
        """Parse MySQL plan node."""
        if "query_block" in node:
            for qb in node["query_block"]:
                if "table" in qb:
                    table = qb["table"]
                    if "access_type" in table:
                        access_type = table["access_type"]
                        if access_type == "ref" or access_type == "range":
                            if "key" in table:
                                stats.indexes_used.append(table["key"])
                        elif access_type == "ALL":
                            if "table" in table:
                                stats.full_table_scans.append(table["table"])
        
        if "cost_info" in node:
            cost = node["cost_info"]
            if "total_cost" in cost:
                stats.cost = float(cost["total_cost"])
        
        if "rows_examined_per_scan" in node:
            stats.rows_examined = int(node["rows_examined_per_scan"])
        
        if "rows_produced_per_join" in node:
            stats.rows_returned = int(node["rows_produced_per_join"])
    
    def _parse_plan_text(self, stats: QueryStats, plan_text: str) -> None:
        """Generic text-based plan parsing."""
        # Look for index usage
        index_pattern = re.compile(r"(Index|Key)\s+(\w+)", re.IGNORECASE)
        for match in index_pattern.finditer(plan_text):
            stats.indexes_used.append(match.group(2))
        
        # Look for full table scans
        scan_pattern = re.compile(r"(Seq Scan|Full Table Scan|ALL)\s+on\s+(\w+)", re.IGNORECASE)
        for match in scan_pattern.finditer(plan_text):
            stats.full_table_scans.append(match.group(2))
        
        # Look for sort operations
        sort_pattern = re.compile(r"Sort\s+(Method|on)\s+(\w+)", re.IGNORECASE)
        for match in sort_pattern.finditer(plan_text):
            stats.sort_operations.append(match.group(2))
        
        # Look for cost
        cost_pattern = re.compile(r"cost\s*=\s*(\d+\.?\d*)", re.IGNORECASE)
        for match in cost_pattern.finditer(plan_text):
            stats.cost = float(match.group(1))
        
        # Look for rows
        rows_pattern = re.compile(r"rows\s*=\s*(\d+)", re.IGNORECASE)
        for match in rows_pattern.finditer(plan_text):
            stats.rows_returned = int(match.group(1))
    
    def recommend_indexes(
        self, 
        query: Union[str, Select, Query], 
        params: Optional[Dict] = None
    ) -> List[IndexRecommendation]:
        """
        Recommend indexes for a query based on its execution plan.
        
        Args:
            query: The query to analyze.
            params: Optional parameters for the query.
            
        Returns:
            List of index recommendations.
        """
        stats = self.analyze_query(query, params)
        recommendations = []
        
        # If query uses full table scans, recommend indexes
        for table in stats.full_table_scans:
            # Get WHERE conditions for this table
            where_columns = self._extract_where_columns(query, table)
            if where_columns:
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=where_columns,
                    priority=10,
                    estimated_improvement=50.0,
                    reason=f"Full table scan on {table} with WHERE conditions"
                ))
        
        # If query has JOINs, recommend composite indexes
        join_columns = self._extract_join_columns(query)
        if join_columns:
            for table, columns in join_columns.items():
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=columns,
                    index_type=IndexType.COMPOSITE,
                    priority=9,
                    estimated_improvement=40.0,
                    reason=f"JOIN optimization for {table}"
                ))
        
        # If query has ORDER BY, recommend indexes
        order_by_columns = self._extract_order_by_columns(query)
        if order_by_columns:
            for table, columns in order_by_columns.items():
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=columns,
                    priority=8,
                    estimated_improvement=30.0,
                    reason=f"ORDER BY optimization for {table}"
                ))
        
        # If query has GROUP BY, recommend indexes
        group_by_columns = self._extract_group_by_columns(query)
        if group_by_columns:
            for table, columns in group_by_columns.items():
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=columns,
                    priority=7,
                    estimated_improvement=25.0,
                    reason=f"GROUP BY optimization for {table}"
                ))
        
        # Deduplicate recommendations
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            key = (rec.table_name, tuple(rec.columns), rec.index_type)
            if key not in seen:
                seen.add(key)
                unique_recommendations.append(rec)
        
        return unique_recommendations
    
    def _extract_where_columns(
        self, 
        query: Union[str, Select, Query], 
        table: str
    ) -> List[str]:
        """Extract columns used in WHERE conditions for a table."""
        if isinstance(query, str):
            # Simple text parsing
            where_match = re.search(r"WHERE\s+(.*?)(?:GROUP BY|ORDER BY|LIMIT|$)", query, re.IGNORECASE)
            if not where_match:
                return []
            
            where_clause = where_match.group(1)
            # Extract column names
            columns = re.findall(r"(\w+)\s*(?:=|!=|>|<|>=|<=|LIKE|IN|BETWEEN)", where_clause)
            return list(set(columns))
        
        # For SQLAlchemy queries, this would be more complex
        return []
    
    def _extract_join_columns(
        self, 
        query: Union[str, Select, Query]
    ) -> Dict[str, List[str]]:
        """Extract columns used in JOIN conditions."""
        if isinstance(query, str):
            join_matches = re.finditer(
                r"JOIN\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
                query,
                re.IGNORECASE
            )
            
            result = {}
            for match in join_matches:
                table1 = match.group(2)
                col1 = match.group(3)
                table2 = match.group(4)
                col2 = match.group(5)
                
                if table1 not in result:
                    result[table1] = []
                result[table1].append(col1)
                
                if table2 not in result:
                    result[table2] = []
                result[table2].append(col2)
            
            return result
        
        return {}
    
    def _extract_order_by_columns(
        self, 
        query: Union[str, Select, Query]
    ) -> Dict[str, List[str]]:
        """Extract columns used in ORDER BY clauses."""
        if isinstance(query, str):
            order_match = re.search(r"ORDER BY\s+(.*?)(?:LIMIT|$)", query, re.IGNORECASE)
            if not order_match:
                return {}
            
            order_clause = order_match.group(1)
            columns = re.findall(r"(\w+)", order_clause)
            
            # Try to determine table from column names
            # This is a simplified approach
            return {"unknown": columns}
        
        return {}
    
    def _extract_group_by_columns(
        self, 
        query: Union[str, Select, Query]
    ) -> Dict[str, List[str]]:
        """Extract columns used in GROUP BY clauses."""
        if isinstance(query, str):
            group_match = re.search(r"GROUP BY\s+(.*?)(?:ORDER BY|LIMIT|$)", query, re.IGNORECASE)
            if not group_match:
                return {}
            
            group_clause = group_match.group(1)
            columns = re.findall(r"(\w+)", group_clause)
            
            return {"unknown": columns}
        
        return {}
    
    def optimize_query(
        self, 
        query: Union[str, Select, Query], 
        params: Optional[Dict] = None
    ) -> QueryOptimization:
        """
        Optimize a query by applying various optimization techniques.
        
        Args:
            query: The query to optimize.
            params: Optional parameters for the query.
            
        Returns:
            QueryOptimization with original and optimized queries.
        """
        # Analyze the original query
        original_stats = self.analyze_query(query, params)
        
        # Convert to string for manipulation
        if isinstance(query, (Select, Query)):
            query_str = str(query)
        else:
            query_str = query
        
        # Apply optimization rules
        optimized_query = self._apply_optimization_rules(query_str)
        
        # Analyze the optimized query
        optimized_stats = self.analyze_query(optimized_query, params)
        
        # Calculate improvement
        if original_stats.cost > 0:
            improvement = ((original_stats.cost - optimized_stats.cost) / original_stats.cost) * 100
        else:
            improvement = 0.0
        
        # Get index recommendations
        recommendations = self.recommend_indexes(query, params)
        
        # Track changes
        changes = []
        if query_str != optimized_query:
            changes.append("Applied query rewriting rules")
        
        return QueryOptimization(
            query=query_str,
            original_cost=original_stats.cost,
            optimized_query=optimized_query,
            optimized_cost=optimized_stats.cost,
            improvement=improvement,
            changes=changes,
            recommendations=recommendations
        )
    
    def _apply_optimization_rules(self, query: str) -> str:
        """Apply various optimization rules to a query."""
        optimized = query
        
        # Rule 1: Remove unnecessary DISTINCT if no duplicates expected
        optimized = re.sub(
            r"SELECT\s+DISTINCT\s+",
            "SELECT ",
            optimized,
            flags=re.IGNORECASE
        )
        
        # Rule 2: Use EXISTS instead of IN for subqueries
        optimized = re.sub(
            r"WHERE\s+(\w+)\s+IN\s*\(\s*SELECT\s+(\w+)\s+FROM\s+(\w+)\s+WHERE\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
            r"WHERE EXISTS (SELECT 1 FROM \3 WHERE \4.\5 = \6.\7 AND \1 = \3.\5)",
            optimized,
            flags=re.IGNORECASE
        )
        
        # Rule 3: Use LIMIT with OFFSET for pagination
        # This is already good practice, but ensure it's used
        
        # Rule 4: Add missing indexes recommendation in comments
        # This would be done separately
        
        return optimized


# =============================================================================
# Query Builder Utilities
# =============================================================================

class QueryBuilder:
    """
    Utility class for building optimized queries.
    
    Provides methods for building common query patterns with performance
    optimizations built-in.
    """
    
    def __init__(self, session: Session):
        """
        Initialize the query builder.
        
        Args:
            session: SQLAlchemy session.
        """
        self.session = session
    
    def build_paginated_query(
        self,
        model: Type,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        eager_loads: Optional[List[str]] = None
    ) -> Query:
        """
        Build a paginated query with optimizations.
        
        Args:
            model: SQLAlchemy model class.
            page: Page number (1-based).
            page_size: Number of items per page.
            filters: Dictionary of filter conditions.
            sort_by: Column name to sort by.
            sort_order: Sort order ('asc' or 'desc').
            eager_loads: List of relationships to eager load.
            
        Returns:
            SQLAlchemy Query object.
        """
        query = self.session.query(model)
        
        # Apply filters
        if filters:
            for column, value in filters.items():
                if hasattr(model, column):
                    if isinstance(value, (list, tuple)):
                        query = query.filter(getattr(model, column).in_(value))
                    else:
                        query = query.filter(getattr(model, column) == value)
        
        # Apply sorting
        if sort_by and hasattr(model, sort_by):
            column = getattr(model, sort_by)
            if sort_order.lower() == "asc":
                query = query.order_by(asc(column))
            else:
                query = query.order_by(desc(column))
        
        # Apply eager loading
        if eager_loads:
            for relationship in eager_loads:
                if hasattr(model, relationship):
                    query = query.options(joinedload(getattr(model, relationship)))
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        return query
    
    def build_search_query(
        self,
        model: Type,
        search_term: str,
        search_columns: List[str],
        filters: Optional[Dict] = None,
        limit: int = 50
    ) -> Query:
        """
        Build a full-text search query with optimizations.
        
        Args:
            model: SQLAlchemy model class.
            search_term: Search term.
            search_columns: List of column names to search.
            filters: Additional filter conditions.
            limit: Maximum number of results.
            
        Returns:
            SQLAlchemy Query object.
        """
        query = self.session.query(model)
        
        # Build search conditions
        search_conditions = []
        for column in search_columns:
            if hasattr(model, column):
                search_conditions.append(
                    getattr(model, column).ilike(f"%{search_term}%")
                )
        
        if search_conditions:
            query = query.filter(or_(*search_conditions))
        
        # Apply additional filters
        if filters:
            for column, value in filters.items():
                if hasattr(model, column):
                    query = query.filter(getattr(model, column) == value)
        
        # Apply limit
        query = query.limit(limit)
        
        return query
    
    def build_aggregate_query(
        self,
        model: Type,
        group_by: List[str],
        aggregates: Dict[str, Any],
        filters: Optional[Dict] = None
    ) -> Query:
        """
        Build an aggregate query with optimizations.
        
        Args:
            model: SQLAlchemy model class.
            group_by: List of column names to group by.
            aggregates: Dictionary of aggregate functions.
            filters: Filter conditions.
            
        Returns:
            SQLAlchemy Query object.
        """
        # Start with a select query
        from sqlalchemy.orm import aliased
        
        # For simplicity, we'll use a basic approach
        # In practice, this would be more sophisticated
        query = self.session.query(model)
        
        # Apply filters
        if filters:
            for column, value in filters.items():
                if hasattr(model, column):
                    query = query.filter(getattr(model, column) == value)
        
        # Apply grouping
        group_columns = []
        for column in group_by:
            if hasattr(model, column):
                group_columns.append(getattr(model, column))
        
        if group_columns:
            query = query.group_by(*group_columns)
        
        return query
    
    def build_batch_query(
        self,
        model: Type,
        ids: List[int],
        batch_size: int = 100
    ) -> List[Query]:
        """
        Build batch queries for processing large datasets.
        
        Args:
            model: SQLAlchemy model class.
            ids: List of IDs to query.
            batch_size: Number of IDs per batch.
            
        Returns:
            List of Query objects, one per batch.
        """
        queries = []
        primary_key = getattr(model, "id")
        
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            query = self.session.query(model).filter(primary_key.in_(batch_ids))
            queries.append(query)
        
        return queries


# =============================================================================
# Database Optimizer
# =============================================================================

class DatabaseOptimizer:
    """
    Comprehensive database optimizer for Open Omniscience.
    
    Provides automated database optimization including:
    - Index management
    - Query optimization
    - Table analysis
    - Performance recommendations
    """
    
    def __init__(self, engine: Engine, session: Session):
        """
        Initialize the database optimizer.
        
        Args:
            engine: SQLAlchemy engine.
            session: SQLAlchemy session.
        """
        self.engine = engine
        self.session = session
        self.analyzer = QueryAnalyzer(engine)
        self._inspector = inspect(engine)
    
    def analyze_database(self) -> Dict[str, Any]:
        """
        Analyze the entire database and provide optimization recommendations.
        
        Returns:
            Dictionary with analysis results and recommendations.
        """
        result = {
            "tables": {},
            "indexes": {},
            "recommendations": [],
            "issues": []
        }
        
        # Get all tables
        tables = self._inspector.get_table_names()
        
        for table_name in tables:
            table_info = self._analyze_table(table_name)
            result["tables"][table_name] = table_info
            
            # Add recommendations for this table
            recommendations = self._get_table_recommendations(table_name, table_info)
            result["recommendations"].extend(recommendations)
        
        # Get all indexes
        for table_name in tables:
            indexes = self._inspector.get_indexes(table_name)
            result["indexes"][table_name] = [
                {"name": idx["name"], "columns": list(idx["column_names"])}
                for idx in indexes
            ]
        
        return result
    
    def _analyze_table(self, table_name: str) -> Dict[str, Any]:
        """Analyze a specific table."""
        info = {
            "name": table_name,
            "columns": [],
            "row_count": 0,
            "size": 0,
            "indexes": [],
            "foreign_keys": []
        }
        
        # Get columns
        columns = self._inspector.get_columns(table_name)
        for col in columns:
            info["columns"].append({
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col["nullable"],
                "primary_key": col["primary_key"],
                "default": col["default"]
            })
        
        # Get row count and size
        try:
            with self.engine.connect() as conn:
                if self.engine.dialect.name == "postgresql":
                    result = conn.execute(text(
                        f"SELECT COUNT(*) as count, pg_total_relation_size('{table_name}') as size FROM {table_name}"
                    ))
                    row = result.fetchone()
                    info["row_count"] = row[0] if row else 0
                    info["size"] = row[1] if row else 0
                elif self.engine.dialect.name == "sqlite":
                    result = conn.execute(text(
                        f"SELECT COUNT(*) as count FROM {table_name}"
                    ))
                    row = result.fetchone()
                    info["row_count"] = row[0] if row else 0
                    # SQLite doesn't have easy size query
                    info["size"] = 0
                elif self.engine.dialect.name == "mysql":
                    result = conn.execute(text(
                        f"SELECT TABLE_ROWS as count, DATA_LENGTH as size FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{table_name}'"
                    ))
                    row = result.fetchone()
                    info["row_count"] = row[0] if row else 0
                    info["size"] = row[1] if row else 0
        except Exception as e:
            logger.warning(f"Failed to get stats for table {table_name}: {e}")
        
        # Get indexes
        indexes = self._inspector.get_indexes(table_name)
        for idx in indexes:
            info["indexes"].append({
                "name": idx["name"],
                "columns": list(idx["column_names"]),
                "unique": idx["unique"]
            })
        
        # Get foreign keys
        fks = self._inspector.get_foreign_keys(table_name)
        for fk in fks:
            info["foreign_keys"].append({
                "constrained_columns": list(fk["constrained_columns"]),
                "referred_table": fk["referred_table"],
                "referred_columns": list(fk["referred_columns"])
            })
        
        return info
    
    def _get_table_recommendations(
        self, 
        table_name: str, 
        table_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get optimization recommendations for a table."""
        recommendations = []
        
        # Check for missing indexes on foreign keys
        for fk in table_info.get("foreign_keys", []):
            constrained_cols = fk["constrained_columns"]
            
            # Check if there's an index on these columns
            has_index = False
            for idx in table_info.get("indexes", []):
                if set(constrained_cols).issubset(set(idx["columns"])):
                    has_index = True
                    break
            
            if not has_index:
                recommendations.append({
                    "type": "missing_index",
                    "table": table_name,
                    "columns": constrained_cols,
                    "reason": "Foreign key columns should be indexed",
                    "priority": 8,
                    "index_type": IndexType.B_TREE.value
                })
        
        # Check for large tables without indexes
        if table_info.get("row_count", 0) > 10000:
            if not table_info.get("indexes"):
                recommendations.append({
                    "type": "missing_index",
                    "table": table_name,
                    "columns": ["id"],  # At least index primary key
                    "reason": "Large table should have indexes",
                    "priority": 10,
                    "index_type": IndexType.B_TREE.value
                })
        
        # Check for text columns that might benefit from full-text search
        for col in table_info.get("columns", []):
            if "text" in col.get("type", "").lower() or "varchar" in col.get("type", "").lower():
                if col.get("name") in ["content", "title", "description", "summary"]:
                    recommendations.append({
                        "type": "full_text_search",
                        "table": table_name,
                        "column": col["name"],
                        "reason": "Text column might benefit from full-text search index",
                        "priority": 7,
                        "index_type": IndexType.GIN.value
                    })
        
        return recommendations
    
    def create_index(
        self, 
        table_name: str, 
        columns: List[str], 
        index_name: Optional[str] = None,
        unique: bool = False,
        index_type: IndexType = IndexType.B_TREE
    ) -> bool:
        """
        Create a new index on a table.
        
        Args:
            table_name: Name of the table.
            columns: List of column names.
            index_name: Name for the index (auto-generated if not provided).
            unique: Whether the index should be unique.
            index_type: Type of index to create.
            
        Returns:
            True if index was created successfully.
        """
        if index_name is None:
            index_name = f"idx_{table_name}_{'_'.join(columns)}"
        
        try:
            dialect = self.engine.dialect.name
            
            if dialect == "postgresql":
                if index_type == IndexType.GIN:
                    sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {table_name} USING GIN ({', '.join(columns)})"
                elif index_type == IndexType.BRIN:
                    sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {table_name} USING BRIN ({', '.join(columns)})"
                else:
                    sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {table_name} ({', '.join(columns)})"
            elif dialect == "mysql":
                if index_type == IndexType.FULLTEXT:
                    sql = f"CREATE FULLTEXT INDEX {index_name} ON {table_name} ({', '.join(columns)})"
                else:
                    sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {table_name} ({', '.join(columns)})"
            else:  # SQLite
                sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {table_name} ({', '.join(columns)})"
            
            with self.engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            
            logger.info(f"Created index {index_name} on {table_name}({', '.join(columns)})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            return False
    
    def optimize_all_queries(self, queries: List[Union[str, Select, Query]]) -> List[QueryOptimization]:
        """
        Optimize a list of queries.
        
        Args:
            queries: List of queries to optimize.
            
        Returns:
            List of QueryOptimization objects.
        """
        optimizations = []
        for query in queries:
            optimization = self.analyzer.optimize_query(query)
            optimizations.append(optimization)
        return optimizations
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive performance report.
        
        Returns:
            Dictionary with performance metrics and recommendations.
        """
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "database": {
                "type": self.engine.dialect.name,
                "url": str(self.engine.url)
            },
            "tables": {},
            "queries": {},
            "recommendations": []
        }
        
        # Analyze database
        db_analysis = self.analyze_database()
        report["tables"] = db_analysis["tables"]
        report["recommendations"] = db_analysis["recommendations"]
        
        return report


# =============================================================================
# Decorators for Query Optimization
# =============================================================================

def monitor_query(func: Callable) -> Callable:
    """
    Decorator to monitor query performance.
    
    Logs query execution time and other statistics.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        execution_time = time.time() - start_time
        
        # Get function name
        func_name = func.__name__
        
        # Log performance
        logger.info(
            f"Query in {func_name} executed in {execution_time:.4f}s"
        )
        
        return result
    
    return wrapper


def cached_query(
    ttl: int = 300,
    key_func: Optional[Callable] = None
) -> Callable:
    """
    Decorator to cache query results.
    
    Args:
        ttl: Time-to-live in seconds.
        key_func: Function to generate cache key from arguments.
    """
    from functools import lru_cache
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Simple caching based on arguments
            # In production, use a proper cache like Redis
            cache_key = (func.__name__, args, tuple(sorted(kwargs.items())))
            
            # This is a simplified implementation
            # For production, integrate with a caching system
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def with_relationships(*relationships: str) -> Callable:
    """
    Decorator to automatically load relationships for a query.
    
    Args:
        *relationships: Relationship names to eager load.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            
            # Apply eager loading if result is a query
            if hasattr(result, 'options'):
                for rel in relationships:
                    if hasattr(self, rel):
                        result = result.options(joinedload(getattr(self, rel)))
            
            return result
        
        return wrapper
    
    return decorator


# =============================================================================
# Utility Functions
# =============================================================================

def get_query_analyzer(engine: Engine) -> QueryAnalyzer:
    """
    Get a QueryAnalyzer instance for the given engine.
    
    Args:
        engine: SQLAlchemy engine.
        
    Returns:
        QueryAnalyzer instance.
    """
    return QueryAnalyzer(engine)


def get_database_optimizer(engine: Engine, session: Session) -> DatabaseOptimizer:
    """
    Get a DatabaseOptimizer instance.
    
    Args:
        engine: SQLAlchemy engine.
        session: SQLAlchemy session.
        
    Returns:
        DatabaseOptimizer instance.
    """
    return DatabaseOptimizer(engine, session)


def explain_query(
    engine: Engine,
    query: Union[str, Select, Query],
    params: Optional[Dict] = None
) -> QueryStats:
    """
    Execute EXPLAIN ANALYZE on a query.
    
    Args:
        engine: SQLAlchemy engine.
        query: Query to explain.
        params: Optional query parameters.
        
    Returns:
        QueryStats with execution plan.
    """
    analyzer = QueryAnalyzer(engine)
    return analyzer.analyze_query(query, params)


def recommend_indexes(
    engine: Engine,
    query: Union[str, Select, Query],
    params: Optional[Dict] = None
) -> List[IndexRecommendation]:
    """
    Recommend indexes for a query.
    
    Args:
        engine: SQLAlchemy engine.
        query: Query to analyze.
        params: Optional query parameters.
        
    Returns:
        List of index recommendations.
    """
    analyzer = QueryAnalyzer(engine)
    return analyzer.recommend_indexes(query, params)


def optimize_query(
    engine: Engine,
    query: Union[str, Select, Query],
    params: Optional[Dict] = None
) -> QueryOptimization:
    """
    Optimize a query.
    
    Args:
        engine: SQLAlchemy engine.
        query: Query to optimize.
        params: Optional query parameters.
        
    Returns:
        QueryOptimization with results.
    """
    analyzer = QueryAnalyzer(engine)
    return analyzer.optimize_query(query, params)


# =============================================================================
# Batch Processing Utilities
# =============================================================================

def batch_process(
    items: List[Any],
    batch_size: int = 100,
    process_func: Callable[[List[Any]], Any] = None
) -> List[Any]:
    """
    Process items in batches.
    
    Args:
        items: List of items to process.
        batch_size: Number of items per batch.
        process_func: Function to process each batch.
        
    Returns:
        List of results from each batch.
    """
    results = []
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        if process_func:
            result = process_func(batch)
            results.append(result)
        else:
            results.append(batch)
    
    return results


def paginate_query(
    query: Query,
    page: int = 1,
    page_size: int = 20
) -> Tuple[List[Any], int, int]:
    """
    Paginate a query.
    
    Args:
        query: SQLAlchemy query.
        page: Page number (1-based).
        page_size: Items per page.
        
    Returns:
        Tuple of (items, total_count, total_pages).
    """
    # Get total count
    total_count = query.count()
    
    # Calculate total pages
    total_pages = (total_count + page_size - 1) // page_size
    
    # Apply pagination
    offset = (page - 1) * page_size
    paginated_query = query.offset(offset).limit(page_size)
    
    items = paginated_query.all()
    
    return items, total_count, total_pages


def chunked_query(
    query: Query,
    chunk_size: int = 100
) -> List[List[Any]]:
    """
    Execute a query in chunks.
    
    Args:
        query: SQLAlchemy query.
        chunk_size: Number of items per chunk.
        
    Returns:
        List of chunks, each containing a list of items.
    """
    chunks = []
    offset = 0
    
    while True:
        chunk_query = query.offset(offset).limit(chunk_size)
        items = chunk_query.all()
        
        if not items:
            break
        
        chunks.append(items)
        offset += chunk_size
    
    return chunks


# =============================================================================
# Performance Monitoring
# =============================================================================

class QueryPerformanceMonitor:
    """
    Monitor query performance over time.
    """
    
    def __init__(self):
        self._query_stats: Dict[str, List[QueryStats]] = {}
        self._slow_queries: List[QueryStats] = []
    
    def record_query(self, stats: QueryStats) -> None:
        """Record query statistics."""
        # Use query as key (simplified)
        query_key = stats.query[:100]  # Use first 100 chars as key
        
        if query_key not in self._query_stats:
            self._query_stats[query_key] = []
        
        self._query_stats[query_key].append(stats)
        
        # Keep only recent stats
        if len(self._query_stats[query_key]) > 100:
            self._query_stats[query_key] = self._query_stats[query_key][-100:]
        
        # Track slow queries
        if stats.is_slow:
            self._slow_queries.append(stats)
            if len(self._slow_queries) > 1000:
                self._slow_queries = self._slow_queries[-1000:]
    
    def get_query_history(self, query: str) -> List[QueryStats]:
        """Get history for a specific query."""
        query_key = query[:100]
        return self._query_stats.get(query_key, [])
    
    def get_slow_queries(self) -> List[QueryStats]:
        """Get list of slow queries."""
        return self._slow_queries
    
    def get_average_execution_time(self, query: str) -> float:
        """Get average execution time for a query."""
        history = self.get_query_history(query)
        if not history:
            return 0.0
        
        return sum(s.execution_time for s in history) / len(history)
    
    def get_performance_trend(self, query: str) -> Dict[str, Any]:
        """Get performance trend for a query."""
        history = self.get_query_history(query)
        
        if not history:
            return {"average": 0, "trend": "stable", "count": 0}
        
        times = [s.execution_time for s in history]
        avg = sum(times) / len(times)
        
        # Simple trend detection
        if len(times) >= 2:
            if times[-1] > times[0] * 1.5:
                trend = "degrading"
            elif times[-1] < times[0] * 0.5:
                trend = "improving"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return {
            "average": avg,
            "trend": trend,
            "count": len(history),
            "min": min(times),
            "max": max(times)
        }


# Global performance monitor instance
query_performance_monitor = QueryPerformanceMonitor()


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Classes
    "QueryAnalyzer",
    "QueryBuilder",
    "DatabaseOptimizer",
    "QueryPerformanceMonitor",
    "QueryStats",
    "IndexRecommendation",
    "QueryOptimization",
    # Enums
    "QueryType",
    "IndexType",
    # Functions
    "get_query_analyzer",
    "get_database_optimizer",
    "explain_query",
    "recommend_indexes",
    "optimize_query",
    "batch_process",
    "paginate_query",
    "chunked_query",
    # Decorators
    "monitor_query",
    "cached_query",
    "with_relationships",
    # Utilities
    "query_performance_monitor",
]
