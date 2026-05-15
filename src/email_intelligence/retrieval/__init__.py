"""
Email Retrieval Module

Handles fetching emails from various sources (IMAP, POP3, APIs, RSS).
"""

from .imap_client import IMAPClient
from .pop3_client import POP3Client
from .api_client import APIClient
from .rss_client import RSSClient
from .scheduler import EmailScheduler

__all__ = [
    'IMAPClient',
    'POP3Client', 
    'APIClient',
    'RSSClient',
    'EmailScheduler',
]
