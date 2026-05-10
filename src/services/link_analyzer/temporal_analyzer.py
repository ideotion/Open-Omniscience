"""
Temporal Analyzer Service for Open Omniscience

This module provides functionality for analyzing temporal patterns in article-source
relationships, including time delta calculations, anomaly detection, and trend analysis.

Author: Open Omniscience Team
"""

import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any, Tuple
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
import logging
import numpy as np
from scipy import stats

# Configure logging
logger = logging.getLogger(__name__)


class TemporalAnalyzer:
    """
    Service for analyzing temporal patterns in article-source relationships.
    
    This class provides methods to:
    - Analyze time deltas between articles and sources
    - Detect temporal anomalies
    - Calculate temporal statistics
    - Identify trends over time
    - Generate temporal visualizations
    """
    
    def __init__(self):
        """Initialize the TemporalAnalyzer."""
        # Time delta categories
        self.time_delta_categories = {
            'article_before_source_1week+': (-float('inf'), -7),
            'article_before_source_1-7days': (-7, -1),
            'article_before_source_1day': (-1, 0),
            'same_day': (0, 1),
            'article_after_source_1-7days': (1, 7),
            'article_after_source_1-4weeks': (7, 30),
            'article_after_source_1month+': (30, float('inf'))
        }
    
    def analyze_temporal_patterns(self, article_id: int, relationships: List[Dict[str, Any]],
                                article_published_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze temporal patterns for an article's source relationships.
        
        Args:
            article_id: ID of the article
            relationships: List of relationship dictionaries
            article_published_at: Publication date of the article
            
        Returns:
            Dictionary containing temporal analysis results
        """
        if not relationships:
            return {
                'article_id': article_id,
                'total_relationships': 0,
                'temporal_anomalies': 0,
                'avg_time_delta_days': 0,
                'median_time_delta_days': 0,
                'std_time_delta_days': 0,
                'time_delta_distribution': {},
                'source_types': {},
                'earliest_source_date': None,
                'latest_source_date': None
            }
        
        # Parse article date
        article_date = self._parse_date(article_published_at) if article_published_at else None
        
        temporal_anomalies = 0
        time_deltas = []
        source_types = {}
        time_delta_distribution = {}
        source_dates = []
        
        for rel in relationships:
            # Count source types
            source_type = rel.get('source_type', 'unknown')
            source_types[source_type] = source_types.get(source_type, 0) + 1
            
            # Analyze temporal information
            time_delta = rel.get('time_delta_days')
            if time_delta is not None:
                time_deltas.append(time_delta)
                
                # Categorize time delta
                category = self._categorize_time_delta(time_delta)
                time_delta_distribution[category] = time_delta_distribution.get(category, 0) + 1
            
            # Count temporal anomalies
            if rel.get('is_temporal_anomaly', False):
                temporal_anomalies += 1
            
            # Collect source dates for additional analysis
            if article_date and time_delta is not None:
                source_date = article_date - timedelta(days=time_delta)
                source_dates.append(source_date)
        
        # Calculate statistics
        stats_dict = self._calculate_temporal_statistics(time_deltas)
        
        # Find earliest and latest source dates
        earliest_source_date = min(source_dates) if source_dates else None
        latest_source_date = max(source_dates) if source_dates else None
        
        result = {
            'article_id': article_id,
            'total_relationships': len(relationships),
            'temporal_anomalies': temporal_anomalies,
            'time_delta_distribution': time_delta_distribution,
            'source_types': source_types
        }
        
        result.update(stats_dict)
        
        if earliest_source_date:
            result['earliest_source_date'] = earliest_source_date.isoformat()
        if latest_source_date:
            result['latest_source_date'] = latest_source_date.isoformat()
        
        return result
    
    def analyze_temporal_trends(self, articles_data: List[Dict[str, Any]], 
                               time_range: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
        """
        Analyze temporal trends across multiple articles.
        
        Args:
            articles_data: List of article data with relationships
            time_range: Optional time range (start_date, end_date)
            
        Returns:
            Dictionary containing temporal trend analysis
        """
        if not articles_data:
            return {
                'total_articles': 0,
                'total_relationships': 0,
                'avg_relationships_per_article': 0,
                'temporal_anomaly_rate': 0,
                'time_delta_trends': {},
                'source_type_trends': {}
            }
        
        total_articles = 0
        total_relationships = 0
        temporal_anomalies = 0
        time_deltas_by_period = {}
        source_types_by_period = {}
        
        # Group by time periods (e.g., by month)
        for article_data in articles_data:
            article_date_str = article_data.get('published_at')
            if not article_date_str:
                continue
            
            article_date = self._parse_date(article_date_str)
            if not article_date:
                continue
            
            # Apply time range filter
            if time_range:
                start_date = self._parse_date(time_range[0])
                end_date = self._parse_date(time_range[1])
                if start_date and article_date < start_date:
                    continue
                if end_date and article_date > end_date:
                    continue
            
            # Get period key (e.g., '2024-01' for January 2024)
            period_key = article_date.strftime('%Y-%m')
            
            relationships = article_data.get('relationships', [])
            total_articles += 1
            total_relationships += len(relationships)
            
            # Count temporal anomalies
            anomalies_in_article = sum(1 for rel in relationships if rel.get('is_temporal_anomaly', False))
            temporal_anomalies += anomalies_in_article
            
            # Collect time deltas
            time_deltas = [rel.get('time_delta_days') for rel in relationships if rel.get('time_delta_days') is not None]
            if time_deltas:
                if period_key not in time_deltas_by_period:
                    time_deltas_by_period[period_key] = []
                time_deltas_by_period[period_key].extend(time_deltas)
            
            # Collect source types
            source_types = [rel.get('source_type', 'unknown') for rel in relationships]
            if period_key not in source_types_by_period:
                source_types_by_period[period_key] = []
            source_types_by_period[period_key].extend(source_types)
        
        # Calculate trends
        time_delta_trends = {}
        for period, deltas in time_deltas_by_period.items():
            if deltas:
                time_delta_trends[period] = {
                    'avg': np.mean(deltas),
                    'median': np.median(deltas),
                    'std': np.std(deltas),
                    'count': len(deltas)
                }
        
        source_type_trends = {}
        for period, types in source_types_by_period.items():
            if types:
                type_counts = {}
                for t in types:
                    type_counts[t] = type_counts.get(t, 0) + 1
                source_type_trends[period] = type_counts
        
        # Calculate rates
        avg_relationships_per_article = total_relationships / total_articles if total_articles > 0 else 0
        temporal_anomaly_rate = temporal_anomalies / total_relationships if total_relationships > 0 else 0
        
        return {
            'total_articles': total_articles,
            'total_relationships': total_relationships,
            'avg_relationships_per_article': avg_relationships_per_article,
            'temporal_anomaly_rate': temporal_anomaly_rate,
            'time_delta_trends': time_delta_trends,
            'source_type_trends': source_type_trends
        }
    
    def detect_temporal_anomalies(self, relationships: List[Dict[str, Any]], 
                                 threshold_days: float = 0.0) -> List[Dict[str, Any]]:
        """
        Detect temporal anomalies in relationships.
        
        Args:
            relationships: List of relationship dictionaries
            threshold_days: Time delta threshold for anomaly detection (negative values)
            
        Returns:
            List of relationships with temporal anomalies
        """
        anomalies = []
        
        for rel in relationships:
            time_delta = rel.get('time_delta_days')
            if time_delta is not None and time_delta < threshold_days:
                # Add anomaly severity
                rel_copy = rel.copy()
                rel_copy['anomaly_severity'] = self._calculate_anomaly_severity(time_delta)
                anomalies.append(rel_copy)
        
        return anomalies
    
    def _calculate_anomaly_severity(self, time_delta_days: float) -> str:
        """
        Calculate severity of a temporal anomaly.
        
        Args:
            time_delta_days: Time delta in days (negative for anomalies)
            
        Returns:
            Severity string (low, medium, high, critical)
        """
        # More negative = more severe
        abs_delta = abs(time_delta_days)
        
        if abs_delta < 1:
            return 'low'
        elif abs_delta < 7:
            return 'medium'
        elif abs_delta < 30:
            return 'high'
        else:
            return 'critical'
    
    def _categorize_time_delta(self, time_delta_days: float) -> str:
        """
        Categorize a time delta into predefined categories.
        
        Args:
            time_delta_days: Time delta in days
            
        Returns:
            Category string
        """
        for category, (min_val, max_val) in self.time_delta_categories.items():
            if min_val <= time_delta_days < max_val:
                return category
        
        return 'unknown'
    
    def _calculate_temporal_statistics(self, time_deltas: List[float]) -> Dict[str, Any]:
        """
        Calculate statistics for a list of time deltas.
        
        Args:
            time_deltas: List of time delta values in days
            
        Returns:
            Dictionary containing statistical measures
        """
        if not time_deltas:
            return {
                'avg_time_delta_days': 0,
                'median_time_delta_days': 0,
                'std_time_delta_days': 0,
                'min_time_delta_days': 0,
                'max_time_delta_days': 0,
                'time_delta_range': 0
            }
        
        try:
            avg = np.mean(time_deltas)
            median = np.median(time_deltas)
            std = np.std(time_deltas)
            min_val = min(time_deltas)
            max_val = max(time_deltas)
            range_val = max_val - min_val
            
            return {
                'avg_time_delta_days': float(avg),
                'median_time_delta_days': float(median),
                'std_time_delta_days': float(std),
                'min_time_delta_days': float(min_val),
                'max_time_delta_days': float(max_val),
                'time_delta_range': float(range_val)
            }
        except Exception as e:
            logger.warning(f"Error calculating temporal statistics: {e}")
            return {
                'avg_time_delta_days': 0,
                'median_time_delta_days': 0,
                'std_time_delta_days': 0,
                'min_time_delta_days': 0,
                'max_time_delta_days': 0,
                'time_delta_range': 0
            }
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.
        
        Args:
            date_str: Date string in various formats
            
        Returns:
            Datetime object, or None if parsing failed
        """
        if not date_str:
            return None
        
        try:
            # Try ISO format first
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            
            # Try parsing with dateutil
            dt = date_parser.parse(date_str)
            
            # If no timezone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            return dt
            
        except Exception as e:
            logger.warning(f"Error parsing date {date_str}: {e}")
            return None
    
    def calculate_correlation(self, time_series1: List[float], time_series2: List[float]) -> float:
        """
        Calculate correlation between two time series.
        
        Args:
            time_series1: First time series
            time_series2: Second time series
            
        Returns:
            Correlation coefficient (-1.0 to 1.0)
        """
        if not time_series1 or not time_series2 or len(time_series1) != len(time_series2):
            return 0.0
        
        try:
            correlation, _ = stats.pearsonr(time_series1, time_series2)
            return float(correlation)
        except Exception as e:
            logger.warning(f"Error calculating correlation: {e}")
            return 0.0
    
    def identify_temporal_clusters(self, relationships: List[Dict[str, Any]], 
                                  threshold_days: float = 7.0) -> List[Dict[str, Any]]:
        """
        Identify temporal clusters of source references.
        
        Args:
            relationships: List of relationship dictionaries
            threshold_days: Maximum time delta difference for clustering
            
        Returns:
            List of temporal clusters
        """
        if not relationships:
            return []
        
        # Extract time deltas
        time_deltas = [rel.get('time_delta_days') for rel in relationships if rel.get('time_delta_days') is not None]
        if not time_deltas:
            return []
        
        # Sort time deltas
        time_deltas.sort()
        
        # Create clusters
        clusters = []
        current_cluster = [time_deltas[0]]
        
        for i in range(1, len(time_deltas)):
            if time_deltas[i] - current_cluster[-1] <= threshold_days:
                current_cluster.append(time_deltas[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [time_deltas[i]]
        
        clusters.append(current_cluster)
        
        # Convert clusters to result format
        result_clusters = []
        for i, cluster in enumerate(clusters):
            result_clusters.append({
                'cluster_id': i + 1,
                'time_deltas': cluster,
                'size': len(cluster),
                'avg_time_delta': float(np.mean(cluster)),
                'median_time_delta': float(np.median(cluster)),
                'min_time_delta': float(min(cluster)),
                'max_time_delta': float(max(cluster))
            })
        
        return result_clusters
    
    def generate_temporal_report(self, articles_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a comprehensive temporal analysis report.
        
        Args:
            articles_data: List of article data with relationships
            
        Returns:
            Dictionary containing comprehensive temporal analysis
        """
        report = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'summary': {},
            'detailed_analysis': {},
            'recommendations': []
        }
        
        # Generate summary statistics
        report['summary'] = self.analyze_temporal_trends(articles_data)
        
        # Add detailed analysis
        report['detailed_analysis'] = {
            'by_article': [],
            'anomalies': [],
            'clusters': []
        }
        
        # Analyze each article
        for article_data in articles_data:
            article_id = article_data.get('id')
            relationships = article_data.get('relationships', [])
            published_at = article_data.get('published_at')
            
            article_analysis = self.analyze_temporal_patterns(
                article_id, relationships, published_at
            )
            report['detailed_analysis']['by_article'].append(article_analysis)
            
            # Find anomalies
            anomalies = self.detect_temporal_anomalies(relationships)
            if anomalies:
                report['detailed_analysis']['anomalies'].extend(anomalies)
            
            # Find clusters
            clusters = self.identify_temporal_clusters(relationships)
            if clusters:
                report['detailed_analysis']['clusters'].extend(clusters)
        
        # Generate recommendations
        summary = report['summary']
        if summary.get('temporal_anomaly_rate', 0) > 0.1:
            report['recommendations'].append(
                f"High temporal anomaly rate ({summary['temporal_anomaly_rate']:.1%}). "
                "Review articles with anomalies for accuracy."
            )
        
        if summary.get('avg_relationships_per_article', 0) < 2:
            report['recommendations'].append(
                "Low average number of source relationships per article. "
                "Consider adding more source references."
            )
        
        return report