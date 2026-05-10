"""
Temporal Analyzer for Open-Omniscience
Analyzes temporal relationships between articles and sources
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dateutil import parser as date_parser


class TemporalAnalyzer:
    """
    Analyzes dates and temporal relationships in articles.
    """
    
    def __init__(self):
        """Initialize the temporal analyzer."""
        pass
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.
        
        Args:
            date_str: Date string in various formats
            
        Returns:
            datetime object or None if parsing fails
        """
        if not date_str:
            return None
        
        try:
            return date_parser.parse(date_str)
        except Exception:
            return None
    
    def calculate_time_difference(self, date1: datetime, date2: datetime) -> Dict[str, float]:
        """
        Calculate time difference between two dates.
        
        Args:
            date1: First date
            date2: Second date
            
        Returns:
            Dictionary with time differences in various units
        """
        if date1 > date2:
            date1, date2 = date2, date1
        
        delta = date2 - date1
        
        return {
            'seconds': delta.total_seconds(),
            'minutes': delta.total_seconds() / 60,
            'hours': delta.total_seconds() / 3600,
            'days': delta.days,
            'weeks': delta.days / 7,
            'months': delta.days / 30,
            'years': delta.days / 365,
        }
    
    def analyze_article_timeline(self, articles: List[Dict]) -> Dict:
        """
        Analyze timeline of articles.
        
        Args:
            articles: List of article dictionaries with 'published_date' field
            
        Returns:
            Dictionary with timeline analysis
        """
        if not articles:
            return {}
        
        # Parse dates
        dates = []
        for article in articles:
            date_str = article.get('published_date')
            if date_str:
                date = self.parse_date(date_str)
                if date:
                    dates.append(date)
        
        if not dates:
            return {}
        
        # Sort dates
        dates.sort()
        
        # Calculate statistics
        first_date = dates[0]
        last_date = dates[-1]
        total_articles = len(dates)
        
        # Calculate time span
        time_span = self.calculate_time_difference(first_date, last_date)
        
        # Calculate average interval
        if total_articles > 1:
            intervals = []
            for i in range(1, len(dates)):
                diff = (dates[i] - dates[i-1]).total_seconds()
                intervals.append(diff)
            avg_interval = sum(intervals) / len(intervals)
        else:
            avg_interval = 0
        
        return {
            'first_article_date': first_date.isoformat(),
            'last_article_date': last_date.isoformat(),
            'total_articles': total_articles,
            'time_span_days': time_span['days'],
            'average_interval_seconds': avg_interval,
            'average_interval_days': avg_interval / 86400 if avg_interval > 0 else 0,
        }
    
    def compare_article_source_dates(self, article_date: str, source_date: str) -> Dict:
        """
        Compare article publication date with source date.
        
        Args:
            article_date: Article publication date string
            source_date: Source publication date string
            
        Returns:
            Dictionary with comparison results
        """
        article_dt = self.parse_date(article_date)
        source_dt = self.parse_date(source_date)
        
        if not article_dt or not source_dt:
            return {'error': 'Could not parse dates'}
        
        # Calculate difference
        diff = self.calculate_time_difference(article_dt, source_dt)
        
        # Determine relationship
        if article_dt < source_dt:
            relationship = 'article_before_source'
            time_lag = diff['days']
        elif article_dt > source_dt:
            relationship = 'article_after_source'
            time_lag = diff['days']
        else:
            relationship = 'same_day'
            time_lag = 0
        
        return {
            'article_date': article_dt.isoformat(),
            'source_date': source_dt.isoformat(),
            'relationship': relationship,
            'days_difference': diff['days'],
            'time_lag_days': time_lag,
        }
    
    def detect_temporal_patterns(self, articles: List[Dict]) -> Dict:
        """
        Detect temporal patterns in article publication.
        
        Args:
            articles: List of article dictionaries
            
        Returns:
            Dictionary with detected patterns
        """
        if not articles:
            return {}
        
        # Group by date (day)
        date_counts = {}
        for article in articles:
            date_str = article.get('published_date')
            if date_str:
                date = self.parse_date(date_str)
                if date:
                    date_key = date.strftime('%Y-%m-%d')
                    date_counts[date_key] = date_counts.get(date_key, 0) + 1
        
        # Find peak days
        if date_counts:
            max_count = max(date_counts.values())
            peak_days = [day for day, count in date_counts.items() if count == max_count]
        else:
            peak_days = []
        
        # Calculate average articles per day
        if date_counts:
            avg_per_day = sum(date_counts.values()) / len(date_counts)
        else:
            avg_per_day = 0
        
        return {
            'total_days': len(date_counts),
            'total_articles': sum(date_counts.values()) if date_counts else 0,
            'average_articles_per_day': avg_per_day,
            'peak_days': peak_days,
            'max_articles_in_day': max(date_counts.values()) if date_counts else 0,
        }


# Global instance
temporal_analyzer = TemporalAnalyzer()
