"""
Email Retrieval Module

Handles fetching emails from various sources (IMAP, POP3, APIs, RSS).

Note: Some modules may not be available in all environments.
      Lazy imports are used for optional dependencies.
"""

# Import IMAP client (always available)
from .imap_client import IMAPClient

# Try to import optional clients
try:
    from .pop3_client import POP3Client
except ImportError:
    POP3Client = None

try:
    from .api_client import APIClient
except ImportError:
    APIClient = None

try:
    from .rss_client import RSSClient
except ImportError:
    RSSClient = None

try:
    from .scheduler import EmailScheduler
except ImportError:
    EmailScheduler = None

__all__ = [
    'IMAPClient',
    'POP3Client', 
    'APIClient',
    'RSSClient',
    'EmailScheduler',
]
