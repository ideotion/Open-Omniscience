"""
Duplicate Detector for Email Intelligence

Handles detection of duplicate emails to prevent processing the same content multiple times.
"""

from typing import Optional, List
import logging

from sqlalchemy.orm import Session

from ..models import EmailMessage
from ..exceptions import DuplicateEmailError

logger = logging.getLogger(__name__)


class DuplicateDetector:
    """
    Detects duplicate emails based on content hashing.
    
    This class handles:
    - Checking for existing emails with the same content hash
    - Managing a cache of recently seen hashes for performance
    - Providing statistics on duplicate detection
    """
    
    def __init__(self, session: Optional[Session] = None):
        """
        Initialize the duplicate detector.
        
        Args:
            session: SQLAlchemy session (optional)
        """
        self.session = session
        self._hash_cache = set()  # In-memory cache of recently seen hashes
        self._max_cache_size = 10000  # Maximum size of the in-memory cache
    
    def is_duplicate(self, content_hash: str) -> bool:
        """
        Check if an email with the given content hash already exists.
        
        Args:
            content_hash: SHA-256 hash of the email content
            
        Returns:
            bool: True if the email is a duplicate
        """
        try:
            # First check in-memory cache
            if content_hash in self._hash_cache:
                return True
            
            # Then check database
            if self.session:
                existing = self.session.query(EmailMessage).filter_by(
                    content_hash=content_hash
                ).first()
                
                if existing:
                    # Add to cache for future checks
                    self._hash_cache.add(content_hash)
                    self._manage_cache_size()
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check for duplicate: {str(e)}")
            return False
    
    def check_and_add(self, content_hash: str) -> bool:
        """
        Check if an email is a duplicate and add its hash to the cache.
        
        Args:
            content_hash: SHA-256 hash of the email content
            
        Returns:
            bool: True if the email is a duplicate
        """
        is_dup = self.is_duplicate(content_hash)
        
        # Add to cache regardless of whether it's a duplicate
        # This prevents the same email from being processed multiple times in a batch
        self._hash_cache.add(content_hash)
        self._manage_cache_size()
        
        return is_dup
    
    def _manage_cache_size(self):
        """Manage the size of the in-memory hash cache"""
        if len(self._hash_cache) > self._max_cache_size:
            # Remove half of the cache entries
            cache_list = list(self._hash_cache)
            self._hash_cache = set(cache_list[self._max_cache_size // 2:])
            logger.debug(f"Trimmed hash cache from {len(cache_list)} to {len(self._hash_cache)} entries")
    
    def get_duplicate_statistics(self) -> dict:
        """
        Get statistics about duplicate detection.
        
        Returns:
            Dictionary with duplicate detection statistics
        """
        try:
            if not self.session:
                return {
                    'cache_size': len(self._hash_cache),
                    'database_checks': 0,
                    'duplicates_found': 0
                }
            
            # Count total emails
            total_emails = self.session.query(EmailMessage).count()
            
            # Count unique content hashes
            unique_hashes = self.session.query(EmailMessage.content_hash).distinct().count()
            
            # Calculate duplicate rate
            duplicate_rate = ((total_emails - unique_hashes) / total_emails * 100) if total_emails > 0 else 0
            
            return {
                'total_emails': total_emails,
                'unique_hashes': unique_hashes,
                'duplicate_rate_percent': round(duplicate_rate, 2),
                'cache_size': len(self._hash_cache),
                'max_cache_size': self._max_cache_size
            }
            
        except Exception as e:
            logger.error(f"Failed to get duplicate statistics: {str(e)}")
            return {}
    
    def clear_cache(self):
        """Clear the in-memory hash cache"""
        self._hash_cache.clear()
        logger.debug("Cleared hash cache")
    
    def add_to_cache(self, content_hash: str):
        """
        Add a content hash to the cache.
        
        Args:
            content_hash: SHA-256 hash to add to cache
        """
        self._hash_cache.add(content_hash)
        self._manage_cache_size()
