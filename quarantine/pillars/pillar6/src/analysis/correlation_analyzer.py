"""
Pillar 6 Correlation Analyzer

Analyzes correlations between articles and rare earth market data.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import logging
import numpy as np
import pandas as pd

from .base_analyzer import RareEarthAnalyzer, AnalyzerConfig, DEFAULT_ANALYZER_CONFIG
from ..models import (
    RareEarthPrice,
    RareEarthAnalysis,
    ArticleRareEarthLink,
    CorrelationType,
    CorrelationStrength,
    Sentiment,
    AnalysisType,
    Severity,
    Direction,
)
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class CorrelationAnalyzer(RareEarthAnalyzer):
    """
    Analyzer for correlations between articles and rare earth data.
    
    Performs correlation analysis to identify relationships between
    news articles and rare earth market movements.
    """
    
    def __init__(
        self,
        config: Optional[AnalyzerConfig] = None,
        name: str = "CorrelationAnalyzer",
    ):
        """
        Initialize the correlation analyzer.
        
        Args:
            config: Analyzer configuration
            name: Name of the analyzer
        """
        super().__init__(config, name)
    
    def get_analysis_type(self) -> AnalysisType:
        """Get the type of analysis performed."""
        return AnalysisType.CORRELATION
    
    def analyze(
        self,
        element_symbol: str,
        **kwargs
    ) -> Optional[RareEarthAnalysis]:
        """
        Analyze correlations between articles and rare earth data.
        
        Args:
            element_symbol: Element symbol to analyze
            **kwargs: Additional parameters
                - days: Number of days of history (default: 30)
                - correlation_type: Specific correlation type
                - min_sentiment: Minimum sentiment score
                
        Returns:
            Correlation analysis results or None on failure
        """
        days = kwargs.get("days", 30)
        correlation_type = kwargs.get("correlation_type", CorrelationType.PRICE_NEWS)
        min_sentiment = kwargs.get("min_sentiment", None)
        
        # Get price data
        prices = self.get_price_data(element_symbol, days=days)
        
        if not self._check_min_data(prices):
            logger.warning(f"Insufficient price data for correlation analysis: {element_symbol}")
            return None
        
        # Get articles for this element (from main database)
        # This would query the main articles table
        articles = self._get_articles_for_element(element_symbol, days)
        
        if not articles:
            logger.warning(f"No articles found for element: {element_symbol}")
            return None
        
        # Determine dates
        start_date = prices[-1].date if prices else date.today()
        end_date = prices[0].date if prices else date.today()
        
        # Perform correlation analysis
        return self.analyze_correlations(
            element_symbol, prices, articles, correlation_type, start_date, end_date
        )
    
    def _get_articles_for_element(self, element_symbol: str, days: int) -> List[Any]:
        """
        Get articles related to a specific element.
        
        This would query the main articles database for articles
        that mention the element or related keywords.
        """
        # For now, return a placeholder
        # In practice, this would query the main database
        from src.database.models import Session, Article
        
        session = Session()
        try:
            # Query articles that might be related to this element
            # This is a simplified version - in practice, you'd have
            # a more sophisticated content analysis
            end_date = date.today()
            start_date = end_date - timedelta(days=days)
            
            articles = session.query(Article).filter(
                Article.published_at >= datetime(start_date.year, start_date.month, start_date.day),
                Article.published_at <= datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
            ).all()
            
            # Filter by content (simple keyword matching for now)
            element = storage.get_element_by_symbol(element_symbol)
            if element:
                keywords = [element.name.lower(), element_symbol.lower()]
                filtered_articles = []
                for article in articles:
                    content_lower = article.content.lower() if article.content else ""
                    title_lower = article.title.lower() if article.title else ""
                    if any(kw in content_lower or kw in title_lower for kw in keywords):
                        filtered_articles.append(article)
                return filtered_articles
            
            return articles
            
        except Exception as e:
            logger.error(f"Failed to get articles for {element_symbol}: {e}")
            return []
        finally:
            session.close()
    
    def analyze_correlations(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        articles: List[Any],
        correlation_type: CorrelationType,
        start_date: date,
        end_date: date,
    ) -> Optional[RareEarthAnalysis]:
        """
        Analyze correlations between articles and price data.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            articles: List of articles
            correlation_type: Type of correlation to analyze
            start_date: Start date of analysis period
            end_date: End date of analysis period
            
        Returns:
            Correlation analysis results
        """
        # Create correlation links
        correlations = self._create_correlation_links(
            element_symbol, prices, articles, correlation_type
        )
        
        if not correlations:
            return None
        
        # Calculate correlation statistics
        stats = self._calculate_correlation_stats(correlations)
        
        # Determine severity based on correlation strength
        avg_score = stats["avg_correlation_score"]
        severity_score = min(avg_score, 1.0)
        severity = self.config.get_severity(severity_score)
        
        # Determine direction based on average sentiment
        avg_sentiment = stats["avg_sentiment_score"]
        if avg_sentiment > 0.1:
            direction = Direction.UP
        elif avg_sentiment < -0.1:
            direction = Direction.DOWN
        else:
            direction = Direction.STABLE
        
        # Generate insights
        insights = self._generate_correlation_insights(
            element_symbol, correlations, stats
        )
        
        # Generate recommendations
        recommendations = self._generate_correlation_recommendations(
            element_symbol, correlations, stats
        )
        
        # Create results
        results = {
            "total_correlations": len(correlations),
            "significant_correlations": stats["significant_count"],
            "avg_correlation_score": stats["avg_correlation_score"],
            "avg_sentiment_score": stats["avg_sentiment_score"],
            "sentiment_distribution": stats["sentiment_distribution"],
            "correlation_by_type": stats["correlation_by_type"],
            "time_lag_distribution": stats["time_lag_distribution"],
        }
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=element_symbol,
            analysis_type=AnalysisType.CORRELATION,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=severity,
            confidence=0.8,
            direction=direction,
            magnitude=abs(avg_sentiment),
            insights=insights,
            recommendations=recommendations,
        )
        
        # Store correlations in database
        self._store_correlations(correlations)
        
        return analysis
    
    def _create_correlation_links(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        articles: List[Any],
        correlation_type: CorrelationType,
    ) -> List[ArticleRareEarthLink]:
        """
        Create correlation links between articles and price data.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            articles: List of articles
            correlation_type: Type of correlation
            
        Returns:
            List of ArticleRareEarthLink objects
        """
        correlations = []
        
        for article in articles:
            # Calculate correlation with price data
            correlation = self._calculate_article_correlation(
                article, prices, element_symbol, correlation_type
            )
            
            if correlation:
                correlations.append(correlation)
        
        return correlations
    
    def _calculate_article_correlation(
        self,
        article: Any,
        prices: List[RareEarthPrice],
        element_symbol: str,
        correlation_type: CorrelationType,
    ) -> Optional[ArticleRareEarthLink]:
        """
        Calculate correlation between an article and price data.
        
        Args:
            article: Article object
            prices: List of price data points
            element_symbol: Element symbol
            correlation_type: Type of correlation
            
        Returns:
            ArticleRareEarthLink object or None
        """
        # Get article date
        article_date = article.published_at.date() if article.published_at else date.today()
        
        # Find price closest to article date
        closest_price = self._find_closest_price(prices, article_date)
        
        if not closest_price:
            return None
        
        # Calculate time lag
        time_lag = (article_date - closest_price.date).days
        
        # Analyze article sentiment
        sentiment_score, sentiment = self._analyze_sentiment(article)
        
        # Calculate correlation score (simplified for now)
        # In practice, this would use more sophisticated analysis
        correlation_score = self._calculate_correlation_score(
            article, closest_price, time_lag, sentiment_score
        )
        
        # Determine correlation strength
        correlation_strength = self._get_correlation_strength(correlation_score)
        
        # Extract keywords and entities from article
        keywords = self._extract_keywords(article)
        entities = self._extract_entities(article)
        
        # Calculate price change around article date
        price_change_pct = self._calculate_price_change_around_date(
            prices, article_date, days_before=1, days_after=1
        )
        
        # Create correlation link
        correlation = ArticleRareEarthLink(
            article_id=article.id,
            element_symbol=element_symbol,
            correlation_type=correlation_type,
            correlation_score=correlation_score,
            correlation_strength=correlation_strength,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            date=article_date,
            time_lag_days=time_lag,
            price_change_pct=price_change_pct,
            keywords=keywords,
            entities=entities,
            confidence=0.8,
            insights=f"Article published {abs(time_lag)} days {'before' if time_lag < 0 else 'after'} price data",
            is_significant=correlation_score > 0.7,
            p_value=1.0 - correlation_score,  # Simplified p-value
            metadata={
                "article_title": article.title or "",
                "article_url": article.url or "",
                "price": closest_price.price,
                "price_date": closest_price.date.isoformat(),
            },
        )
        
        return correlation
    
    def _find_closest_price(
        self,
        prices: List[RareEarthPrice],
        target_date: date,
    ) -> Optional[RareEarthPrice]:
        """Find the price data point closest to a target date."""
        if not prices:
            return None
        
        # Sort prices by date distance
        prices_sorted = sorted(
            prices,
            key=lambda p: abs((p.date - target_date).days)
        )
        
        return prices_sorted[0]
    
    def _analyze_sentiment(self, article: Any) -> tuple:
        """
        Analyze the sentiment of an article.
        
        Args:
            article: Article object
            
        Returns:
            Tuple of (sentiment_score, sentiment_label)
        """
        # Use article's sentiment if available
        if hasattr(article, 'sentiment_score') and article.sentiment_score is not None:
            return article.sentiment_score, Sentiment.NEUTRAL
        
        # Simple sentiment analysis based on content
        content = (article.content or "").lower()
        title = (article.title or "").lower()
        text = f"{title} {content}"
        
        # Count positive and negative words
        positive_words = ["increase", "rise", "up", "growth", "positive", "bullish", "higher", "strong"]
        negative_words = ["decrease", "fall", "down", "drop", "negative", "bearish", "lower", "weak"]
        
        positive_count = sum(word in text for word in positive_words)
        negative_count = sum(word in text for word in negative_words)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0, Sentiment.NEUTRAL
        
        sentiment_score = (positive_count - negative_count) / total
        
        if sentiment_score > 0.1:
            sentiment = Sentiment.POSITIVE
        elif sentiment_score < -0.1:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = Sentiment.NEUTRAL
        
        return sentiment_score, sentiment
    
    def _calculate_correlation_score(
        self,
        article: Any,
        price: RareEarthPrice,
        time_lag: int,
        sentiment_score: float,
    ) -> float:
        """
        Calculate a correlation score between an article and price data.
        
        This is a simplified version - in practice, you'd use more
        sophisticated statistical methods.
        
        Args:
            article: Article object
            price: Price data point
            time_lag: Days between article and price
            sentiment_score: Article sentiment score
            
        Returns:
            Correlation score (0-1)
        """
        # Base score from sentiment
        sentiment_score_abs = abs(sentiment_score)
        
        # Time lag factor (closer is better)
        time_lag_factor = max(0, 1 - abs(time_lag) / 7)  # 7-day window
        
        # Content relevance factor
        content_factor = self._calculate_content_relevance(article, price.element_symbol)
        
        # Combine factors
        correlation_score = (
            sentiment_score_abs * 0.4 +
            time_lag_factor * 0.3 +
            content_factor * 0.3
        )
        
        return min(max(correlation_score, 0), 1)
    
    def _calculate_content_relevance(self, article: Any, element_symbol: str) -> float:
        """
        Calculate how relevant an article is to a specific element.
        
        Args:
            article: Article object
            element_symbol: Element symbol
            
        Returns:
            Relevance score (0-1)
        """
        element = storage.get_element_by_symbol(element_symbol)
        if not element:
            return 0.5
        
        content = (article.content or "").lower()
        title = (article.title or "").lower()
        text = f"{title} {content}"
        
        # Check for element name and symbol
        name_matches = element.name.lower() in text
        symbol_matches = element_symbol.lower() in text
        
        # Check for related terms
        related_terms = ["rare earth", "ree", "mineral", "metal", "price", "market"]
        term_matches = sum(term in text for term in related_terms)
        
        # Calculate score
        score = 0.0
        if name_matches:
            score += 0.4
        if symbol_matches:
            score += 0.3
        score += min(term_matches * 0.1, 0.3)
        
        return min(score, 1.0)
    
    def _get_correlation_strength(self, score: float) -> CorrelationStrength:
        """Get correlation strength from a score."""
        if score >= 0.8:
            return CorrelationStrength.VERY_STRONG
        elif score >= 0.6:
            return CorrelationStrength.STRONG
        elif score >= 0.4:
            return CorrelationStrength.MODERATE
        elif score >= 0.2:
            return CorrelationStrength.WEAK
        else:
            return CorrelationStrength.NONE
    
    def _extract_keywords(self, article: Any) -> List[str]:
        """Extract keywords from an article."""
        # Simple keyword extraction
        content = (article.content or "").lower()
        title = (article.title or "").lower()
        text = f"{title} {content}"
        
        # Common rare earth and market keywords
        keywords = [
            "rare earth", "ree", "neodymium", "dysprosium", "praseodymium",
            "cerium", "lanthanum", "samarium", "europium", "gadolinium",
            "terbium", "holmium", "erbium", "thulium", "ytterbium",
            "lutetium", "scandium", "yttrium", "price", "market",
            "production", "inventory", "stockpile", "demand", "supply",
            "china", "us", "australia", "malaysia", "mining", "refining"
        ]
        
        # Find matching keywords
        matched_keywords = [kw for kw in keywords if kw in text]
        
        return matched_keywords
    
    def _extract_entities(self, article: Any) -> List[str]:
        """Extract entities (companies, countries, etc.) from an article."""
        # Simple entity extraction
        content = (article.content or "")
        title = (article.title or "")
        text = f"{title} {content}"
        
        # Common entities
        companies = [
            "Lynas", "MP Materials", "Baotou", "Chinalco",
            "Northern Minerals", "Rainbow Rare Earths"
        ]
        countries = [
            "China", "United States", "Australia", "Malaysia",
            "Brazil", "Russia", "India", "Vietnam"
        ]
        
        entities = []
        
        # Check for companies
        for company in companies:
            if company.lower() in text.lower():
                entities.append(company)
        
        # Check for countries
        for country in countries:
            if country.lower() in text.lower():
                entities.append(country)
        
        return entities
    
    def _calculate_price_change_around_date(
        self,
        prices: List[RareEarthPrice],
        target_date: date,
        days_before: int = 1,
        days_after: int = 1,
    ) -> Optional[float]:
        """
        Calculate price change around a specific date.
        
        Args:
            prices: List of price data points
            target_date: Target date
            days_before: Number of days before target
            days_after: Number of days after target
            
        Returns:
            Percentage price change or None
        """
        # Find price before and after target date
        price_before = None
        price_after = None
        
        for price in prices:
            if (target_date - price.date).days <= days_before and (target_date - price.date).days >= 0:
                price_before = price
            if (price.date - target_date).days <= days_after and (price.date - target_date).days >= 0:
                price_after = price
        
        if price_before and price_after:
            change = (price_after.price - price_before.price) / price_before.price * 100
            return change
        
        return None
    
    def _calculate_correlation_stats(
        self,
        correlations: List[ArticleRareEarthLink],
    ) -> Dict[str, Any]:
        """Calculate statistics for a list of correlations."""
        if not correlations:
            return {
                "avg_correlation_score": 0,
                "avg_sentiment_score": 0,
                "significant_count": 0,
                "sentiment_distribution": {},
                "correlation_by_type": {},
                "time_lag_distribution": {},
            }
        
        # Calculate averages
        avg_correlation = sum(c.correlation_score for c in correlations) / len(correlations)
        avg_sentiment = sum(c.sentiment_score for c in correlations) / len(correlations)
        
        # Count significant correlations
        significant_count = sum(1 for c in correlations if c.is_significant)
        
        # Sentiment distribution
        sentiment_dist = {}
        for sentiment in [Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL, Sentiment.MIXED]:
            count = sum(1 for c in correlations if c.sentiment == sentiment)
            sentiment_dist[sentiment.value] = count
        
        # Correlation by type
        type_dist = {}
        for c in correlations:
            type_dist[c.correlation_type.value] = type_dist.get(c.correlation_type.value, 0) + 1
        
        # Time lag distribution
        lag_dist = {}
        for c in correlations:
            lag_bucket = f"{c.time_lag_days // 7 * 7}-{(c.time_lag_days // 7 + 1) * 7} days"
            lag_dist[lag_bucket] = lag_dist.get(lag_bucket, 0) + 1
        
        return {
            "avg_correlation_score": avg_correlation,
            "avg_sentiment_score": avg_sentiment,
            "significant_count": significant_count,
            "sentiment_distribution": sentiment_dist,
            "correlation_by_type": type_dist,
            "time_lag_distribution": lag_dist,
        }
    
    def _generate_correlation_insights(
        self,
        element_symbol: str,
        correlations: List[ArticleRareEarthLink],
        stats: Dict[str, Any],
    ) -> str:
        """Generate insights for correlation analysis."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        insights = []
        insights.append(f"Found {len(correlations)} articles correlated with {element_name} price data.")
        
        if stats["significant_count"] > 0:
            insights.append(f"{stats['significant_count']} correlations are statistically significant.")
        
        avg_score = stats["avg_correlation_score"]
        if avg_score > 0.5:
            insights.append(f"Average correlation score of {avg_score:.2f} indicates strong relationships.")
        elif avg_score > 0.3:
            insights.append(f"Average correlation score of {avg_score:.2f} indicates moderate relationships.")
        else:
            insights.append(f"Average correlation score of {avg_score:.2f} indicates weak relationships.")
        
        avg_sentiment = stats["avg_sentiment_score"]
        if avg_sentiment > 0.1:
            insights.append("Overall sentiment is positive, which may indicate bullish market conditions.")
        elif avg_sentiment < -0.1:
            insights.append("Overall sentiment is negative, which may indicate bearish market conditions.")
        else:
            insights.append("Overall sentiment is neutral.")
        
        return " ".join(insights)
    
    def _generate_correlation_recommendations(
        self,
        element_symbol: str,
        correlations: List[ArticleRareEarthLink],
        stats: Dict[str, Any],
    ) -> List[str]:
        """Generate recommendations for correlation analysis."""
        recommendations = []
        
        if stats["significant_count"] > 0:
            recommendations.append(f"Monitor news articles for {element_symbol} to anticipate market movements.")
            recommendations.append(f"Use article sentiment as an early indicator for {element_symbol} price changes.")
        
        if stats["avg_correlation_score"] > 0.5:
            recommendations.append(f"Develop trading strategies based on news sentiment for {element_symbol}.")
        
        return recommendations
    
    def _store_correlations(self, correlations: List[ArticleRareEarthLink]) -> int:
        """Store correlation links in the database."""
        stored_count = 0
        
        for correlation in correlations:
            try:
                # Convert to dict for storage
                correlation_data = correlation.to_dict()
                # Remove computed fields
                correlation_data.pop("link_id", None)
                correlation_data.pop("hash", None)
                correlation_data.pop("strength_level", None)
                correlation_data.pop("sentiment_label", None)
                correlation_data.pop("significance_score", None)
                correlation_data.pop("summary", None)
                
                # Get element ID
                element = storage.get_element_by_symbol(correlation.element_symbol)
                if element:
                    correlation_data["element_id"] = element.id
                    
                    # Store in database
                    storage.create_correlation(correlation_data)
                    stored_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to store correlation: {e}")
                continue
        
        return stored_count


class NewsPriceCorrelationAnalyzer(CorrelationAnalyzer):
    """Specialized analyzer for news-price correlations."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "NewsPriceCorrelationAnalyzer")
    
    def get_analysis_type(self) -> AnalysisType:
        return AnalysisType.CORRELATION
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Analyze news-price correlations."""
        kwargs["correlation_type"] = CorrelationType.PRICE_NEWS
        return super().analyze(element_symbol, **kwargs)


# Export everything
__all__ = [
    "CorrelationAnalyzer",
    "NewsPriceCorrelationAnalyzer",
]
