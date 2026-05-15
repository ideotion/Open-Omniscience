"""
Database models for Email Intelligence Module

Defines the SQLAlchemy models for storing email sources, messages, and attachments.
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

# Use the same base as the main application
try:
    from src.database.models import Base
except ImportError:
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
    Configuration for email/newsletter sources
    
    Represents a source from which emails or newsletters are retrieved.
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
    
    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    messages = relationship("EmailMessage", back_populates="source", cascade="all, delete-orphan")
    
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
    Stored email messages
    
    Represents an email or newsletter that has been retrieved and stored.
    """
    
    __tablename__ = "email_messages"
    
    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # Source reference
    source_id = Column(Integer, ForeignKey('email_sources.id'), nullable=True)
    source = relationship("EmailSource", back_populates="messages")
    
    # Email headers
    message_id = Column(String(255), index=True, nullable=True)  # Email Message-ID header
    thread_id = Column(String(255), index=True, nullable=True)  # Conversation thread
    in_reply_to = Column(String(255), nullable=True)  # Reference to parent message
    
    # Metadata
    from_address = Column(String(500), index=True, nullable=True)
    to_addresses = Column(ARRAY(String), default=[])
    cc_addresses = Column(ARRAY(String), default=[])
    bcc_addresses = Column(ARRAY(String), default=[])
    subject = Column(Text, index=True, nullable=True)
    date_sent = Column(DateTime, nullable=True)
    date_received = Column(DateTime, nullable=True)
    
    # Content
    plain_text = Column(Text, nullable=True)
    html_content = Column(Text, nullable=True)
    content_hash = Column(String(64), index=True, nullable=True)  # SHA-256 hash for duplicate detection
    
    # Content metadata
    content_type = Column(String(100), nullable=True)
    charset = Column(String(50), nullable=True)
    content_length = Column(Integer, nullable=True)
    
    # Analysis results
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


class EmailAttachment(Base):
    """
    Email attachments
    
    Represents files attached to email messages.
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
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<EmailAttachment(id={self.id}, filename='{self.filename}')>"


class EmailThread(Base):
    """
    Email conversation threads
    
    Groups related emails into conversation threads.
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
    Detailed analysis results for email messages
    
    Stores comprehensive analysis results that may be too large for the main message table.
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


# Indexes for better performance
class EmailSearchIndex(Base):
    """
    Search index for email content
    
    Provides full-text search capabilities for email content.
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
