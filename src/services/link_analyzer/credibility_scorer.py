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
Credibility Scorer Service for Open Omniscience

This module provides functionality for calculating credibility scores for external sources
based on various factors and rules.

Author: Open Omniscience Team
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
import logging
import numpy as np

# Configure logging
logger = logging.getLogger(__name__)


class CredibilityScorer:
    """
    Service for calculating credibility scores for external sources.
    
    This class provides methods to:
    - Calculate credibility scores based on multiple factors
    - Apply custom scoring rules
    - Update scores based on new information
    - Rank sources by credibility
    - Identify low-credibility sources
    """
    
    def __init__(self):
        """Initialize the CredibilityScorer."""
        # Default scoring rules
        self.scoring_rules = self._load_default_rules()
        
        # Factor weights
        self.factor_weights = {
            'alexa_rank': -0.1,  # Lower rank = higher credibility
            'social_media_followers': 0.05,  # More followers = higher credibility
            'age': 0.02,  # Older = higher credibility
            'verification_status': 0.2,  # Verified = higher credibility
            'political_bias': -0.1,  # More biased = lower credibility
            'source_type': 0.1,  # Some types are more credible
            'domain_authority': 0.15,  # Higher domain authority = higher credibility
            'citation_count': 0.1,  # More citations = higher credibility
            'link_quality': 0.1,  # Higher quality links = higher credibility
            'content_quality': 0.1  # Higher quality content = higher credibility
        }
        
        # Source type credibility scores (0-100)
        self.source_type_scores = {
            'news': 80,
            'academic': 90,
            'government': 85,
            'business': 75,
            'technology': 70,
            'blog': 60,
            'social': 50,
            'unknown': 50
        }
    
    def _load_default_rules(self) -> List[Dict[str, Any]]:
        """
        Load default credibility scoring rules.
        
        Returns:
            List of scoring rule dictionaries
        """
        return [
            {
                'rule_name': 'alexa_rank_rule',
                'factor': 'alexa_rank',
                'weight': -0.1,
                'min_value': 1,
                'max_value': 1000000,
                'is_inverse': True,
                'is_active': True,
                'description': 'Lower Alexa rank = higher credibility'
            },
            {
                'rule_name': 'social_followers_rule',
                'factor': 'social_media_followers',
                'weight': 0.05,
                'min_value': 0,
                'max_value': 10000000,
                'is_inverse': False,
                'is_active': True,
                'description': 'More social media followers = higher credibility'
            },
            {
                'rule_name': 'age_rule',
                'factor': 'age',
                'weight': 0.02,
                'min_value': 0,
                'max_value': 100,
                'is_inverse': False,
                'is_active': True,
                'description': 'Older sources = higher credibility'
            },
            {
                'rule_name': 'verification_rule',
                'factor': 'verification_status',
                'weight': 0.2,
                'min_value': 0,
                'max_value': 1,
                'is_inverse': False,
                'is_active': True,
                'description': 'Verified sources = higher credibility'
            },
            {
                'rule_name': 'bias_rule',
                'factor': 'political_bias',
                'weight': -0.1,
                'min_value': -100,
                'max_value': 100,
                'is_inverse': False,
                'is_active': True,
                'description': 'More political bias = lower credibility'
            },
            {
                'rule_name': 'source_type_rule',
                'factor': 'source_type',
                'weight': 0.1,
                'min_value': 0,
                'max_value': 100,
                'is_inverse': False,
                'is_active': True,
                'description': 'Different source types have different base credibility'
            }
        ]
    
    def calculate_score(self, source_info: Dict[str, Any]) -> float:
        """
        Calculate credibility score for a single source.
        
        Args:
            source_info: Source information dictionary
            
        Returns:
            Credibility score (0-100)
        """
        if not source_info:
            return 50.0  # Default score
        
        score = 0.0
        total_weight = 0.0
        
        # Apply each scoring rule
        for rule in self.scoring_rules:
            if not rule.get('is_active', True):
                continue
            
            factor = rule.get('factor')
            weight = rule.get('weight', 0)
            is_inverse = rule.get('is_inverse', False)
            
            # Get factor value from source info
            factor_value = self._get_factor_value(source_info, factor)
            
            if factor_value is None:
                continue
            
            # Normalize factor value
            min_val = rule.get('min_value', 0)
            max_val = rule.get('max_value', 100)
            
            if max_val > min_val:
                normalized_value = (factor_value - min_val) / (max_val - min_val)
            else:
                normalized_value = 0.5
            
            # Apply inverse if needed
            if is_inverse:
                normalized_value = 1 - normalized_value
            
            # Add to score
            score += normalized_value * abs(weight)
            total_weight += abs(weight)
        
        # Add base score based on source type
        source_type = source_info.get('source_type', 'unknown')
        base_score = self.source_type_scores.get(source_type, 50)
        score += base_score * 0.1  # 10% of total score
        total_weight += 0.1
        
        # Normalize to 0-100 range
        if total_weight > 0:
            score = (score / total_weight) * 100
        
        # Ensure score is within bounds
        score = max(0.0, min(100.0, score))
        
        return score
    
    def calculate_scores(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate credibility scores for multiple sources.
        
        Args:
            sources: List of source information dictionaries
            
        Returns:
            Dictionary containing scores for each source
        """
        results = {}
        
        for source in sources:
            source_id = source.get('id') or source.get('domain')
            if not source_id:
                continue
            
            score = self.calculate_score(source)
            results[source_id] = {
                'credibility_score': score,
                'source_info': source,
                'calculated_at': datetime.now(timezone.utc).isoformat()
            }
        
        return results
    
    def _get_factor_value(self, source_info: Dict[str, Any], factor: str) -> Optional[float]:
        """
        Get the value of a factor from source information.
        
        Args:
            source_info: Source information dictionary
            factor: Factor name
            
        Returns:
            Factor value as float, or None if not available
        """
        # Direct mapping
        factor_mappings = {
            'alexa_rank': 'alexa_rank',
            'social_media_followers': 'social_media_followers',
            'age': 'age',
            'verification_status': 'is_verified',
            'political_bias': 'political_bias',
            'source_type': 'source_type',
            'domain_authority': 'domain_authority',
            'citation_count': 'citation_count',
            'link_quality': 'link_quality',
            'content_quality': 'content_quality'
        }
        
        if factor in factor_mappings:
            key = factor_mappings[factor]
            value = source_info.get(key)
            
            if value is not None:
                # Convert to float
                if isinstance(value, bool):
                    return 1.0 if value else 0.0
                elif isinstance(value, str):
                    # Handle source_type specially
                    if factor == 'source_type':
                        return self.source_type_scores.get(value, 50)
                    try:
                        return float(value)
                    except ValueError:
                        return None
                else:
                    return float(value)
        
        # Calculate age from founded_year
        if factor == 'age':
            founded_year = source_info.get('founded_year')
            if founded_year:
                current_year = datetime.now().year
                return current_year - founded_year
        
        return None
    
    def update_source_score(self, source_id: str, new_info: Dict[str, Any]) -> Optional[float]:
        """
        Update the credibility score for a source with new information.
        
        Args:
            source_id: ID of the source to update
            new_info: New information to incorporate
            
        Returns:
            Updated credibility score, or None if source not found
        """
        # In a real implementation, this would update the database
        # For now, we'll just return the recalculated score
        
        # Get existing source info (in a real implementation, this would come from DB)
        source_info = new_info
        source_info['id'] = source_id
        
        # Calculate new score
        score = self.calculate_score(source_info)
        
        return score
    
    def rank_sources_by_credibility(self, sources: List[Dict[str, Any]], 
                                   limit: int = 10) -> List[Dict[str, Any]]:
        """
        Rank sources by credibility score.
        
        Args:
            sources: List of source information dictionaries
            limit: Maximum number of sources to return
            
        Returns:
            List of ranked source dictionaries
        """
        # Calculate scores
        scored_sources = []
        for source in sources:
            score = self.calculate_score(source)
            scored_sources.append({
                'source': source,
                'credibility_score': score
            })
        
        # Sort by score (descending)
        scored_sources.sort(key=lambda x: x['credibility_score'], reverse=True)
        
        # Return top N
        return scored_sources[:limit]
    
    def identify_low_credibility_sources(self, sources: List[Dict[str, Any]], 
                                        threshold: float = 60.0) -> List[Dict[str, Any]]:
        """
        Identify sources with low credibility scores.
        
        Args:
            sources: List of source information dictionaries
            threshold: Credibility score threshold (0-100)
            
        Returns:
            List of low-credibility source dictionaries
        """
        low_credibility = []
        
        for source in sources:
            score = self.calculate_score(source)
            if score < threshold:
                low_credibility.append({
                    'source': source,
                    'credibility_score': score
                })
        
        # Sort by score (ascending)
        low_credibility.sort(key=lambda x: x['credibility_score'])
        
        return low_credibility
    
    def get_credibility_distribution(self, sources: List[Dict[str, Any]], 
                                     bins: int = 10) -> Dict[str, Any]:
        """
        Get the distribution of credibility scores.
        
        Args:
            sources: List of source information dictionaries
            bins: Number of bins for histogram
            
        Returns:
            Dictionary containing credibility score distribution
        """
        if not sources:
            return {
                'scores': [],
                'mean': 0,
                'median': 0,
                'std': 0,
                'min': 0,
                'max': 0,
                'histogram': {}
            }
        
        # Calculate scores
        scores = [self.calculate_score(source) for source in sources]
        
        # Calculate statistics
        mean_score = float(np.mean(scores))
        median_score = float(np.median(scores))
        std_score = float(np.std(scores))
        min_score = float(min(scores))
        max_score = float(max(scores))
        
        # Create histogram
        hist, bin_edges = np.histogram(scores, bins=bins, range=(0, 100))
        histogram = {}
        for i in range(len(hist)):
            bin_start = bin_edges[i]
            bin_end = bin_edges[i + 1] if i + 1 < len(bin_edges) else 100
            histogram[f"{bin_start:.0f}-{bin_end:.0f}"] = int(hist[i])
        
        return {
            'scores': scores,
            'mean': mean_score,
            'median': median_score,
            'std': std_score,
            'min': min_score,
            'max': max_score,
            'histogram': histogram
        }
    
    def add_custom_rule(self, rule_name: str, factor: str, weight: float,
                       min_value: float = 0, max_value: float = 100,
                       is_inverse: bool = False, is_active: bool = True,
                       description: str = '') -> bool:
        """
        Add a custom scoring rule.
        
        Args:
            rule_name: Name of the rule
            factor: Factor to score on
            weight: Weight of the rule (positive or negative)
            min_value: Minimum value for normalization
            max_value: Maximum value for normalization
            is_inverse: Whether higher values should decrease score
            is_active: Whether the rule is active
            description: Description of the rule
            
        Returns:
            True if rule was added successfully
        """
        if not rule_name or not factor:
            logger.error("Rule name and factor are required")
            return False
        
        # Check for duplicate rule name
        for rule in self.scoring_rules:
            if rule.get('rule_name') == rule_name:
                logger.error(f"Rule with name '{rule_name}' already exists")
                return False
        
        # Add the rule
        new_rule = {
            'rule_name': rule_name,
            'factor': factor,
            'weight': weight,
            'min_value': min_value,
            'max_value': max_value,
            'is_inverse': is_inverse,
            'is_active': is_active,
            'description': description
        }
        
        self.scoring_rules.append(new_rule)
        return True
    
    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove a scoring rule.
        
        Args:
            rule_name: Name of the rule to remove
            
        Returns:
            True if rule was removed successfully
        """
        for i, rule in enumerate(self.scoring_rules):
            if rule.get('rule_name') == rule_name:
                self.scoring_rules.pop(i)
                return True
        
        logger.error(f"Rule with name '{rule_name}' not found")
        return False
    
    def enable_rule(self, rule_name: str, enable: bool = True) -> bool:
        """
        Enable or disable a scoring rule.
        
        Args:
            rule_name: Name of the rule
            enable: Whether to enable the rule
            
        Returns:
            True if rule was updated successfully
        """
        for rule in self.scoring_rules:
            if rule.get('rule_name') == rule_name:
                rule['is_active'] = enable
                return True
        
        logger.error(f"Rule with name '{rule_name}' not found")
        return False
    
    def get_rules(self) -> List[Dict[str, Any]]:
        """
        Get all scoring rules.
        
        Returns:
            List of all scoring rules
        """
        return [
            {
                'rule_name': rule.get('rule_name'),
                'factor': rule.get('factor'),
                'weight': rule.get('weight'),
                'min_value': rule.get('min_value'),
                'max_value': rule.get('max_value'),
                'is_inverse': rule.get('is_inverse'),
                'is_active': rule.get('is_active'),
                'description': rule.get('description')
            }
            for rule in self.scoring_rules
        ]
    
    def get_credibility_categories(self, score: float) -> str:
        """
        Categorize a credibility score.
        
        Args:
            score: Credibility score (0-100)
            
        Returns:
            Category string
        """
        if score >= 90:
            return 'Excellent'
        elif score >= 80:
            return 'Very High'
        elif score >= 70:
            return 'High'
        elif score >= 60:
            return 'Medium'
        elif score >= 50:
            return 'Moderate'
        elif score >= 40:
            return 'Low'
        elif score >= 30:
            return 'Very Low'
        else:
            return 'Poor'
    
    def get_source_type_scores(self) -> Dict[str, float]:
        """
        Get the base credibility scores for each source type.
        
        Returns:
            Dictionary of source types and their base scores
        """
        return self.source_type_scores.copy()
    
    def set_source_type_score(self, source_type: str, score: float) -> bool:
        """
        Set the base credibility score for a source type.
        
        Args:
            source_type: Type of source
            score: Base credibility score (0-100)
            
        Returns:
            True if score was set successfully
        """
        if not source_type:
            logger.error("Source type is required")
            return False
        
        if not 0 <= score <= 100:
            logger.error("Score must be between 0 and 100")
            return False
        
        self.source_type_scores[source_type] = score
        return True
    
    def get_factor_weights(self) -> Dict[str, float]:
        """
        Get the weights for each factor.
        
        Returns:
            Dictionary of factor weights
        """
        return self.factor_weights.copy()
    
    def set_factor_weight(self, factor: str, weight: float) -> bool:
        """
        Set the weight for a factor.
        
        Args:
            factor: Factor name
            weight: Weight value
            
        Returns:
            True if weight was set successfully
        """
        if not factor:
            logger.error("Factor is required")
            return False
        
        self.factor_weights[factor] = weight
        return True