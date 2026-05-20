"""
Database models for Email Intelligence Module

Defines the SQLAlchemy models for storing email sources, messages, and attachments.
This module integrates with the existing Article database architecture, treating
emails as articles with their own sources for seamless exploration and analysis.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid
import hashlib

from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, Float, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

from .exceptions import EmailConfigError

# Import the existing Base from the main database models
try:
    from src.database.models import Base, Source, Article, ArticleLink, ExternalSource, SourceArticle
except ImportError:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()


class EmailSourceType(str, Enum):
    """Types of email sources"""
    IMAP = "imap"
    POP3 = "pop3"
    API = "api"
    RSS = "rss"


class EmailSourceStatus(str, Enum):
    """Status of email sources"""
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"
    TESTING = "testing"


class EmailSource(Base):
    """
    Configuration for email/newsletter sources.
    
    This model extends the existing Source architecture to support email-based sources.
    Each email source can be linked to the existing Source model for unified management.
    
    Attributes:
        id: Primary key.
        name: Name of the email source.
        source_type: Type of email source (imap, pop3, api, rss).
        description: Description of the source.
        connection_config: Connection configuration (server, port, credentials).
        status: Current status of the source.
        enabled: Whether the source is active.
        is_secure: Whether to use SSL/TLS.
        folders: List of folders to monitor.
        fetch_since: Only fetch emails from this date onwards.
        max_emails_per_fetch: Maximum number of emails to fetch per retrieval.
        interval_minutes: Interval between fetches in minutes.
        last_checked: When the source was last checked.
        next_check: When the source should be checked next.
        error_count: Number of consecutive errors.
        last_error: Last error message.
        last_error_time: When the last error occurred.
        linked_source_id: ID of the linked Source in the main database (optional).
        created_at: When the email source was created.
        updated_at: When the email source was last updated.
    """
    
    __tablename__ = "email_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # Source information
    name = Column(String(255), nullable=False, index=True)
    source_type = Column(String(20), nullable=False, default=EmailSourceType.IMAP)
    description = Column(Text, nullable=True)
    
    # Connection configuration (encrypted sensitive data)
    connection_config = Column(JSON, nullable=False, default={})
    
    # Status and settings
    status = Column(String(20), default=EmailSourceStatus.ACTIVE)
    enabled = Column(Boolean, default=True)
    is_secure = Column(Boolean, default=True)  # Uses SSL/TLS
    
    # Retrieval settings
    folders = Column(ARRAY(String), default=[])
    fetch_since = Column(DateTime, nullable=True)
    max_emails_per_fetch = Column(Integer, default=50)
    
    # Scheduling
    interval_minutes = Column(Integer, default=60)
    last_checked = Column(DateTime, nullable=True)
    next_check = Column(DateTime, nullable=True)
    
    # Error tracking
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_error_time = Column(DateTime, nullable=True)
    
    # Integration with existing Source model
    linked_source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    linked_source = relationship("Source", backref="email_sources")
    
    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    messages = relationship("EmailMessage", back_populates="email_source", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<EmailSource(name='{self.name}', type='{self.source_type}', enabled={self.enabled})>"
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the connection configuration"""
        return self.connection_config or {}
    
    @config.setter
    def config(self, value: Dict[str, Any]):
        """Set the connection configuration"""
        self.connection_config = value or {}
    
    def get_server(self) -> Optional[str]:
        """Get the server address"""
        return self.config.get('server') or self.config.get('host')
    
    def get_port(self) -> int:
        """Get the port number"""
        port = self.config.get('port')
        if port:
            return int(port)
        # Default ports
        if self.source_type == EmailSourceType.IMAP:
            return 993 if self.is_secure else 143
        elif self.source_type == EmailSourceType.POP3:
            return 995 if self.is_secure else 110
        return 0
    
    def get_username(self) -> Optional[str]:
        """Get the username"""
        return self.config.get('username')
    
    def is_api_based(self) -> bool:
        """Check if this is an API-based source"""
        return self.source_type in [EmailSourceType.API, EmailSourceType.RSS]
    
    def create_linked_source(self) -> Optional["Source"]:
        """
        Create a linked Source in the main database for this email source.
        This allows emails to be treated as articles from a unified source.
        """
        try:
            from src.database.models import Source
            
            # Create a source that represents this email source
            source = Source(
                name=self.name,
                domain=f"email-{self.source_type}-{self.id}",  # Unique domain identifier
                rss_url=self.config.get('rss_url') if self.source_type == EmailSourceType.RSS else None,
                rate_limit_ms=60000,  # 1 minute rate limit for email sources
                enabled=self.enabled,
                priority=2,
                tags=f"email,{self.source_type}",
                reliability_score=7,  # Default reliability for email sources
                language="en",  # Default language
                region="global",
                country="US",
                source_type="email",
                update_frequency=self.interval_minutes,
                cacheability=False
            )
            
            return source
        except Exception as e:
            from .exceptions import EmailConfigError
            raise EmailConfigError(f"Failed to create linked source: {str(e)}")


class EmailMessageStatus(str, Enum):
    """Status of email messages"""
    NEW = "new"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"
    DELETED = "deleted"


class EmailMessage(Base):
    """
    Stored email messages.
    
    This model stores email messages and can be linked to the existing Article model
    for unified search, analysis, and exploration. Each email can optionally create
    a corresponding Article record for seamless integration.
    
    Attributes:
        id: Primary key (UUID).
        email_source_id: Foreign key to EmailSource.
        linked_article_id: ID of the linked Article in the main database.
        message_id: Email Message-ID header.
        thread_id: Conversation thread identifier.
        in_reply_to: Reference to parent message.
        from_address: Sender email address.
        to_addresses: List of recipient addresses.
        cc_addresses: List of CC addresses.
        bcc_addresses: List of BCC addresses.
        subject: Email subject (used as article title).
        date_sent: When the email was sent.
        date_received: When the email was received.
        plain_text: Plain text content.
        html_content: HTML content.
        content_hash: SHA-256 hash for duplicate detection.
        content_type: MIME content type.
        charset: Character encoding.
        content_length: Length of content in bytes.
        language: Detected language.
        sentiment_score: Sentiment analysis score.
        sentiment_label: Sentiment label (positive, negative, neutral).
        entities: Extracted entities.
        keywords: Extracted keywords.
        topics: Detected topics.
        is_spam: Whether the email is marked as spam.
        is_newsletter: Whether the email is a newsletter.
        importance: Importance score (0-10).
        status: Processing status.
        is_read: Whether the email has been read.
        is_starred: Whether the email is starred.
        is_processed: Whether the email has been processed.
        is_archived: Whether the email is archived.
        processing_error: Error message if processing failed.
        processing_attempts: Number of processing attempts.
        created_at: When the email was stored.
        updated_at: When the email was last updated.
        processed_at: When the email was processed.
    """
    
    __tablename__ = "email_messages"
    
    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # Source reference
    email_source_id = Column(Integer, ForeignKey('email_sources.id'), nullable=True)
    email_source = relationship("EmailSource", back_populates="messages")
    
    # Integration with existing Article model
    linked_article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, unique=True)
    linked_article = relationship("Article", back_populates="email_message", uselist=False)
    
    # Email headers
    message_id = Column(String(255), index=True, nullable=True)  # Email Message-ID header
    thread_id = Column(String(255), index=True, nullable=True)  # Conversation thread
    in_reply_to = Column(String(255), nullable=True)  # Reference to parent message
    
    # Metadata (compatible with Article model)
    from_address = Column(String(500), index=True, nullable=True)
    to_addresses = Column(ARRAY(String), default=[])
    cc_addresses = Column(ARRAY(String), default=[])
    bcc_addresses = Column(ARRAY(String), default=[])
    subject = Column(Text, index=True, nullable=True)  # This becomes the article title
    date_sent = Column(DateTime, nullable=True)  # This becomes published_at
    date_received = Column(DateTime, nullable=True)
    
    # Content (compatible with Article model)
    plain_text = Column(Text, nullable=True)  # This becomes article content
    html_content = Column(Text, nullable=True)
    content_hash = Column(String(64), index=True, nullable=True, unique=True)  # SHA-256 hash for duplicate detection
    
    # Content metadata
    content_type = Column(String(100), nullable=True)
    charset = Column(String(50), nullable=True)
    content_length = Column(Integer, nullable=True)
    
    # Analysis results (compatible with existing analysis)
    language = Column(String(10), nullable=True)
    sentiment_score = Column(Float, nullable=True)
    sentiment_label = Column(String(20), nullable=True)
    entities = Column(JSON, default=[])
    keywords = Column(ARRAY(String), default=[])
    topics = Column(ARRAY(String), default=[])
    
    # Classification
    is_spam = Column(Boolean, default=False)
    is_newsletter = Column(Boolean, default=False)
    importance = Column(Integer, default=0)  # 0-10 scale
    
    # Status
    status = Column(String(20), default=EmailMessageStatus.NEW)
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    is_processed = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    
    # Error tracking
    processing_error = Column(Text, nullable=True)
    processing_attempts = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime, nullable=True)
    
    # Relationships
    attachments = relationship("EmailAttachment", back_populates="email", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<EmailMessage(id='{self.id[:8]}...', subject='{self.subject[:30] if self.subject else 'No Subject'}')>"
    
    @property
    def all_recipients(self) -> List[str]:
        """Get all recipient addresses"""
        return (self.to_addresses or []) + (self.cc_addresses or []) + (self.bcc_addresses or [])
    
    def calculate_content_hash(self) -> str:
        """Calculate SHA-256 hash of the content"""
        content = f"{self.from_address}{self.subject}{self.plain_text or ''}{self.html_content or ''}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def mark_as_processed(self):
        """Mark the message as processed"""
        self.status = EmailMessageStatus.PROCESSED
        self.is_processed = True
        self.processed_at = datetime.utcnow()
    
    def mark_as_failed(self, error: str):
        """Mark the message as failed"""
        self.status = EmailMessageStatus.FAILED
        self.processing_error = error
        self.processing_attempts += 1
    
    def create_linked_article(self) -> Optional["Article"]:
        """
        Create a linked Article in the main database for this email.
        This allows emails to be treated as articles for unified search and analysis.
        """
        try:
            from src.database.models import Article
            from src.utils.url_utils import canonicalize_url
            
            # Generate a unique URL for this email
            # Format: email://<source_type>/<source_id>/<message_id>
            email_url = f"email://{self.email_source.source_type}/{self.email_source_id}/{self.id}"
            canonical_url = canonicalize_url(email_url)
            
            # Create the article
            article = Article(
                url=email_url,
                canonical_url=canonical_url,
                source_id=self.email_source.linked_source_id if self.email_source and self.email_source.linked_source_id else None,
                title=self.subject or "No Subject",
                content=self.plain_text or self.html_content or "",
                published_at=self.date_sent,
                language=self.language or "en",
                hash=self.content_hash or self.calculate_content_hash(),
                region="global",  # Can be updated based on analysis
                country="US",    # Can be updated based on analysis
                author=self.from_address,
            )
            
            return article
        except Exception as e:
            from .exceptions import EmailProcessingError
            raise EmailProcessingError(f"Failed to create linked article: {str(e)}")
    
    def to_article_data(self) -> Dict[str, Any]:
        """
        Convert email message to article-compatible data format.
        
        Returns:
            Dictionary with article-compatible data
        """
        return {
            'url': f"email://{self.email_source.source_type if self.email_source else 'unknown'}/{self.email_source_id}/{self.id}",
            'title': self.subject or "No Subject",
            'content': self.plain_text or self.html_content or "",
            'published_at': self.date_sent,
            'language': self.language or "en",
            'hash': self.content_hash or self.calculate_content_hash(),
            'author': self.from_address,
            'source_id': self.email_source.linked_source_id if self.email_source and self.email_source.linked_source_id else None,
            'region': "global",
            'country': "US",
            'keywords': self.keywords or [],
            'entities': self.entities or [],
            'sentiment_score': self.sentiment_score,
            'sentiment_label': self.sentiment_label,
        }


class EmailAttachment(Base):
    """
    Email attachments.
    
    Represents files attached to email messages. Attachments can be linked to
    the existing ExternalSource model if they reference external content.
    
    Attributes:
        id: Primary key.
        email_id: Foreign key to EmailMessage.
        filename: Original filename.
        original_filename: Original filename before any processing.
        content_type: MIME content type.
        file_size: Size in bytes.
        file_hash: SHA-256 hash of the file.
        storage_path: Path to the stored file.
        storage_type: Type of storage (filesystem, s3, etc.).
        extracted_text: Text extracted from the attachment.
        entities: Extracted entities from the attachment.
        keywords: Extracted keywords from the attachment.
        topics: Detected topics in the attachment.
        is_inline: Whether this is an inline attachment (image, etc.).
        is_signed: Whether the attachment is digitally signed.
        is_encrypted: Whether the attachment is encrypted.
        linked_source_article_id: ID of linked SourceArticle if this attachment references external content.
        created_at: When the attachment was stored.
        updated_at: When the attachment was last updated.
    """
    
    __tablename__ = "email_attachments"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # Email reference
    email_id = Column(String(36), ForeignKey('email_messages.id'), nullable=False)
    email = relationship("EmailMessage", back_populates="attachments")
    
    # File information
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=True)
    content_type = Column(String(200), nullable=True)
    file_size = Column(Integer, nullable=True)  # Size in bytes
    file_hash = Column(String(64), nullable=True)  # SHA-256 hash
    
    # Storage
    storage_path = Column(String(1000), nullable=True)  # Path to stored file
    storage_type = Column(String(20), default="filesystem")  # filesystem, s3, etc.
    
    # Extracted content
    extracted_text = Column(Text, nullable=True)  # Text extracted from document
    
    # Analysis results
    entities = Column(JSON, default=[])
    keywords = Column(ARRAY(String), default=[])
    topics = Column(ARRAY(String), default=[])
    
    # Metadata
    is_inline = Column(Boolean, default=False)  # Inline image/attachment
    is_signed = Column(Boolean, default=False)
    is_encrypted = Column(Boolean, default=False)
    
    # Integration with existing models
    linked_source_article_id = Column(Integer, ForeignKey("source_articles.id"), nullable=True)
    linked_source_article = relationship("SourceArticle", back_populates="email_attachments")
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<EmailAttachment(id={self.id}, filename='{self.filename}')>"
    
    def to_article_link_data(self) -> Optional[Dict[str, Any]]:
        """
        Convert attachment to article link data if it references external content.
        
        Returns:
            Dictionary with article link data, or None if not applicable
        """
        if not self.extracted_text:
            return None
        
        # Check if the extracted text contains URLs
        import re
        urls = re.findall(r'https?://[^\s]+', self.extracted_text)
        if not urls:
            return None
        
        return {
            'url': urls[0],  # Use the first URL found
            'link_text': self.filename,
            'link_type': 'reference',
            'classification': 'source',
        }


class EmailThread(Base):
    """
    Email conversation threads.
    
    Groups related emails into conversation threads for better organization
    and analysis of email conversations.
    
    Attributes:
        id: Primary key.
        thread_id: Unique thread identifier.
        subject: Thread subject.
        participants: List of participant email addresses.
        first_message_id: ID of the first message in the thread.
        last_message_id: ID of the last message in the thread.
        first_message_date: Date of the first message.
        last_message_date: Date of the last message.
        message_count: Number of messages in the thread.
        attachment_count: Number of attachments in the thread.
        is_archived: Whether the thread is archived.
        is_muted: Whether the thread is muted.
        created_at: When the thread was created.
        updated_at: When the thread was last updated.
    """
    
    __tablename__ = "email_threads"
    
    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String(255), unique=True, index=True, nullable=False)
    
    # Thread metadata
    subject = Column(Text, index=True, nullable=True)
    participants = Column(ARRAY(String), default=[])
    
    # First and last message info
    first_message_id = Column(String(36), nullable=True)
    last_message_id = Column(String(36), nullable=True)
    first_message_date = Column(DateTime, nullable=True)
    last_message_date = Column(DateTime, nullable=True)
    
    # Counts
    message_count = Column(Integer, default=0)
    attachment_count = Column(Integer, default=0)
    
    # Status
    is_archived = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<EmailThread(id='{self.id[:8]}...', subject='{self.subject[:30] if self.subject else 'No Subject'}')>"


class EmailAnalysisResult(Base):
    """
    Detailed analysis results for email messages.
    
    Stores comprehensive analysis results that may be too large for the main
    message table, including full text analysis and detailed entity extraction.
    
    Attributes:
        id: Primary key.
        email_id: Foreign key to EmailMessage.
        full_text: Full text for analysis.
        language_detection: Language detection results.
        sentiment_analysis: Sentiment analysis results.
        entity_analysis: Entity extraction results.
        keyword_analysis: Keyword extraction results.
        topic_analysis: Topic modeling results.
        network_analysis: Communication network analysis results.
        analysis_version: Version of the analysis algorithm.
        analysis_time: Time taken for analysis in seconds.
        created_at: When the analysis was performed.
        updated_at: When the analysis was last updated.
    """
    
    __tablename__ = "email_analysis_results"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String(36), ForeignKey('email_messages.id'), unique=True, nullable=False)
    
    # Analysis results
    full_text = Column(Text, nullable=True)  # Full text for analysis
    language_detection = Column(JSON, default={})
    sentiment_analysis = Column(JSON, default={})
    entity_analysis = Column(JSON, default={})
    keyword_analysis = Column(JSON, default={})
    topic_analysis = Column(JSON, default={})
    network_analysis = Column(JSON, default={})
    
    # Metadata
    analysis_version = Column(String(20), default="1.0")
    analysis_time = Column(Float, nullable=True)  # Time taken in seconds
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<EmailAnalysisResult(email_id='{self.email_id[:8]}...')>"


# Add relationship to Article model for email integration
# This allows articles to reference their email message if they were created from an email
Article.email_message = relationship("EmailMessage", back_populates="linked_article", uselist=False)

# Add relationship to SourceArticle model for email attachments
SourceArticle.email_attachments = relationship("EmailAttachment", back_populates="linked_source_article")


# Indexes for better performance
class EmailSearchIndex(Base):
    """
    Search index for email content.
    
    Provides full-text search capabilities for email content, integrated with
    the existing article search functionality.
    
    Attributes:
        id: Primary key.
        email_id: Foreign key to EmailMessage.
        subject: Email subject for search.
        from_address: Sender address for search.
        to_addresses: Recipient addresses for search.
        content: Full content for search.
        tokens: Tokenized content for search.
        created_at: When the index was created.
        updated_at: When the index was last updated.
    """
    
    __tablename__ = "email_search_index"
    
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String(36), ForeignKey('email_messages.id'), unique=True, nullable=False)
    
    # Searchable content
    subject = Column(Text, nullable=True)
    from_address = Column(String(500), nullable=True)
    to_addresses = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    
    # Tokens for search
    tokens = Column(ARRAY(String), default=[])
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Create all tables function
def create_tables():
    """Create all tables for the email intelligence module"""
    Base.metadata.create_all()


# Drop all tables function
def drop_tables():
    """Drop all tables for the email intelligence module"""
    Base.metadata.drop_all()
