"""
Email Processing Pipeline

Handles the processing of retrieved emails, including:
- Content parsing and cleaning
- Attachment extraction
- Duplicate detection
- Integration with article database
- Analysis coordination
"""

from .pipeline import EmailProcessingPipeline
from .parser import EmailParser
from .cleaner import EmailCleaner
from .attachment_handler import AttachmentHandler
from .duplicate_detector import DuplicateDetector
from .article_integrator import ArticleIntegrator

__all__ = [
    'EmailProcessingPipeline',
    'EmailParser',
    'EmailCleaner',
    'AttachmentHandler',
    'DuplicateDetector',
    'ArticleIntegrator',
]
