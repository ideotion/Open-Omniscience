# Email & Newsletter Intelligence Implementation Plan

## 📧 Overview

This document outlines the implementation plan for extending Open-Omniscience to support **email retrieval, archive, and analysis** capabilities. This feature will enable the platform to process both **public and private newsletter intelligence**, significantly enhancing its investigative journalism capabilities.

## 🎯 Objectives

1. **Email Retrieval**: Fetch emails from various sources (IMAP, POP3, API-based newsletters)
2. **Archive Management**: Store and organize email/newsletter data efficiently
3. **Content Analysis**: Extract insights, entities, and patterns from email content
4. **Integration**: Seamlessly integrate with existing Open-Omniscience infrastructure
5. **Privacy & Security**: Ensure ethical handling of private communications

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Email & Newsletter Module                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Retrieval   │  │  Processing  │  │    Analysis         │  │
│  │  Layer      │──▶│  Pipeline    │──▶│    Engine           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                          │                          │
         ▼                          ▼                          ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Email Sources   │  │  Database        │  │  Existing        │
│  - IMAP/POP3     │  │  - Metadata      │  │  Analysis        │
│  - Newsletter APIs│  │  - Content       │  │  - NLP           │
│  - RSS-to-Email  │  │  - Attachments   │  │  - Entity        │
│  - Forwarded     │  │  - Index         │  │  - Link          │
└─────────────────┘  └─────────────────┘  │  │  Analysis        │
                                              └─────────────────┘
```

---

## 📁 Directory Structure

```
src/
├── email_intelligence/
│   ├── __init__.py
│   ├── config.py              # Configuration for email sources
│   ├── models.py              # Database models for emails/newsletters
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── imap_client.py      # IMAP email retrieval
│   │   ├── pop3_client.py      # POP3 email retrieval
│   │   ├── api_client.py       # Newsletter API clients (Substack, etc.)
│   │   ├── rss_to_email.py     # Convert RSS feeds to email format
│   │   └── scheduler.py        # Scheduled retrieval
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── parser.py           # Email content parsing (HTML, plain text)
│   │   ├── cleaner.py          # Clean and normalize content
│   │   ├── attachment_handler.py # Handle attachments
│   │   └── pipeline.py         # Processing workflow
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── metadata_extractor.py # Extract sender, subject, dates, etc.
│   │   ├── content_analyzer.py  # Analyze email content
│   │   ├── entity_extractor.py  # Extract entities (people, orgs, locations)
│   │   ├── sentiment_analyzer.py # Sentiment analysis
│   │   └── network_analyzer.py  # Analyze communication networks
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # Database storage operations
│   │   ├── filesystem.py       # Filesystem storage for attachments
│   │   └── search_index.py      # Search indexing
│   └── api/
│       ├── __init__.py
│       ├── routes.py           # API endpoints for email management
│       └── schemas.py          # Pydantic schemas
├── services/
│   └── email_service.py        # Main email service integration
configs/
└── email_sources.yaml         # Configuration for email sources
```

---

## 🔧 Core Components

### 1. Email Retrieval Layer

#### IMAP/POP3 Client
- **Purpose**: Connect to email servers and fetch messages
- **Features**:
  - SSL/TLS support
  - Incremental fetching (only new emails)
  - Folder/subscription management
  - Error handling and retry logic
  - Rate limiting

#### Newsletter API Clients
- **Supported Services**:
  - Substack (via RSS or API)
  - Mailchimp
  - ConvertKit
  - Revue
  - Ghost
  - Custom RSS feeds

#### Scheduler
- **Purpose**: Manage when and how often to check for new emails
- **Features**:
  - Configurable intervals per source
  - Priority-based scheduling
  - Timezone-aware
  - Manual trigger capability

### 2. Processing Pipeline

#### Email Parser
- **Input**: Raw email (MIME format)
- **Output**: Structured data
- **Processing**:
  - Extract headers (From, To, Subject, Date, etc.)
  - Parse HTML and plain text content
  - Handle multipart messages
  - Extract attachments
  - Normalize encoding

#### Content Cleaner
- **Purpose**: Prepare content for analysis
- **Features**:
  - Remove boilerplate (signatures, disclaimers)
  - Strip HTML (optional)
  - Normalize whitespace
  - Detect and handle forwarded messages
  - Extract quoted text

#### Attachment Handler
- **Supported Types**:
  - PDF documents
  - Office files (DOCX, XLSX, PPTX)
  - Images (JPEG, PNG, GIF)
  - Archives (ZIP, RAR)
- **Processing**:
  - Text extraction from documents
  - OCR for images
  - Virus scanning (optional)
  - Secure storage

### 3. Analysis Engine

#### Metadata Extractor
- **Extracts**:
  - Sender/recipient information
  - Timestamps (sent, received, read)
  - Email headers analysis
  - Thread/conversation tracking
  - Domain analysis

#### Content Analyzer
- **Features**:
  - Keyword extraction
  - Topic modeling
  - Language detection
  - Text summarization
  - Duplicate detection

#### Entity Extractor
- **Extracts**:
  - People (names, email addresses)
  - Organizations
  - Locations
  - Dates and times
  - URLs and domains
  - Phone numbers

#### Network Analyzer
- **Analyzes**:
  - Communication patterns
  - Reply chains
  - CC/BCC relationships
  - Domain connections
  - Temporal patterns

### 4. Storage Layer

#### Database Models
```python
class EmailSource(Base):
    # Configuration for email/newsletter sources
    id: int
    name: str
    source_type: str  # imap, pop3, api, rss
    connection_config: dict  # Server, port, credentials (encrypted)
    enabled: bool
    last_checked: datetime
    next_check: datetime
    error_count: int

class EmailMessage(Base):
    # Stored email messages
    id: str  # Message-ID or UUID
    source_id: int
    message_id: str  # Email Message-ID header
    thread_id: str  # Conversation thread
    in_reply_to: str  # Reference to parent message
    
    # Metadata
    from_address: str
    to_addresses: list
    cc_addresses: list
    bcc_addresses: list
    subject: str
    date_sent: datetime
    date_received: datetime
    
    # Content
    plain_text: str
    html_content: str
    content_hash: str  # For duplicate detection
    
    # Analysis
    language: str
    sentiment_score: float
    entities: list
    topics: list
    
    # Status
    is_read: bool
    is_processed: bool
    is_archived: bool
    
    # Timestamps
    created_at: datetime
    updated_at: datetime

class EmailAttachment(Base):
    # Email attachments
    id: int
    email_id: str
    filename: str
    content_type: str
    file_size: int
    file_hash: str
    storage_path: str
    extracted_text: str  # Text extracted from document
    
    # Analysis
    entities: list
    topics: list
```

#### Filesystem Storage
- **Attachments**: Stored in `data/attachments/` with organized directory structure
- **Raw Emails**: Optional raw email storage for audit
- **Index**: Search index for fast retrieval

---

## 🔐 Security & Privacy Considerations

### Data Protection
1. **Encryption**:
   - Database encryption for sensitive fields
   - TLS for all email retrieval
   - Encrypted storage of credentials

2. **Access Control**:
   - Role-based access to email sources
   - Audit logging for all access
   - Data retention policies

3. **Privacy Compliance**:
   - GDPR compliance for EU data
   - Right to be forgotten implementation
   - Data minimization principles

### Ethical Guidelines
1. **Consent**: Only process emails with proper authorization
2. **Transparency**: Clear documentation of what data is collected
3. **Purpose Limitation**: Use data only for intended investigative purposes
4. **Data Minimization**: Collect only necessary data
5. **Retention**: Implement automatic data deletion policies

---

## 📋 Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Create directory structure
- [ ] Implement configuration system
- [ ] Create database models
- [ ] Set up basic API endpoints
- [ ] Implement IMAP client
- [ ] Create email parser

### Phase 2: Core Retrieval (Week 3-4)
- [ ] POP3 client implementation
- [ ] Newsletter API integrations (Substack, Mailchimp)
- [ ] RSS-to-email converter
- [ ] Scheduler implementation
- [ ] Error handling and retry logic

### Phase 3: Processing Pipeline (Week 5-6)
- [ ] Content cleaning and normalization
- [ ] Attachment handling
- [ ] Duplicate detection
- [ ] Processing workflow orchestration
- [ ] Performance optimization

### Phase 4: Analysis Engine (Week 7-8)
- [ ] Metadata extraction
- [ ] Content analysis
- [ ] Entity extraction
- [ ] Network analysis
- [ ] Integration with existing analysis modules

### Phase 5: Integration & Testing (Week 9-10)
- [ ] Web interface integration
- [ ] Search functionality
- [ ] User management integration
- [ ] Comprehensive testing
- [ ] Documentation

---

## 🛠️ Technical Requirements

### Dependencies
```
# Email protocols
imaplib (built-in)
poplib (built-in)
smtplib (built-in)

# Email parsing
email (built-in)
beautifulsoup4
html2text

# API clients
requests
httpx

# Document processing
pdfminer.six
python-docx
openpyxl
pillow
pytesseract (for OCR)

# Analysis
spacy
nltk
textblob

# Storage
sqlalchemy
alembic
```

### Configuration
```yaml
# configs/email_sources.yaml
email_sources:
  - name: "Personal Gmail"
    type: imap
    enabled: true
    config:
      server: imap.gmail.com
      port: 993
      username: "user@gmail.com"
      password: "${EMAIL_PASSWORD}"  # From environment
      ssl: true
      folders:
        - INBOX
        - Newsletters
      fetch_since: "2024-01-01"
      interval_minutes: 60

  - name: "Substack Newsletter"
    type: substack
    enabled: true
    config:
      publication: "the-investigator"
      api_key: "${SUBSTACK_API_KEY}"
      interval_hours: 24

  - name: "Company Mailchimp"
    type: mailchimp
    enabled: true
    config:
      list_id: "abc123"
      api_key: "${MAILCHIMP_API_KEY}"
      interval_hours: 12
```

---

## 📊 API Endpoints

```
# Email Sources Management
POST   /api/email/sources              # Create new email source
GET    /api/email/sources              # List all email sources
GET    /api/email/sources/{id}         # Get specific source
PUT    /api/email/sources/{id}         # Update source
DELETE /api/email/sources/{id}         # Delete source
POST   /api/email/sources/{id}/test    # Test connection

# Email Messages
GET    /api/email/messages             # List messages (with filters)
GET    /api/email/messages/{id}        # Get specific message
GET    /api/email/messages/{id}/raw    # Get raw email
POST   /api/email/messages/{id}/reprocess # Reprocess message
DELETE /api/email/messages/{id}        # Delete message

# Email Analysis
GET    /api/email/messages/{id}/analysis # Get analysis results
GET    /api/email/analysis/entities     # Search entities across emails
GET    /api/email/analysis/network     # Get communication network

# Attachments
GET    /api/email/attachments          # List attachments
GET    /api/email/attachments/{id}     # Get attachment metadata
GET    /api/email/attachments/{id}/download # Download attachment

# Scheduler
GET    /api/email/scheduler/status     # Get scheduler status
POST   /api/email/scheduler/run        # Manually trigger retrieval
POST   /api/email/scheduler/pause      # Pause scheduler
POST   /api/email/scheduler/resume     # Resume scheduler
```

---

## 🎨 Web Interface Integration

### New Pages
1. **Email Sources Management**
   - Add/edit/delete email sources
   - Connection testing
   - Status monitoring

2. **Email Inbox**
   - List of retrieved emails
   - Search and filtering
   - Bulk operations

3. **Email Detail View**
   - Full email content display
   - Attachment preview/download
   - Analysis results visualization

4. **Analysis Dashboard**
   - Email statistics
   - Entity extraction results
   - Communication network visualization
   - Trend analysis

### Existing Pages Enhancements
1. **Search**: Include email content in global search
2. **Source Management**: Add email sources alongside web sources
3. **Reports**: Include email-based intelligence in reports

---

## 🧪 Testing Strategy

### Unit Tests
- Email parsing (various formats)
- Content cleaning
- Entity extraction
- API client functionality

### Integration Tests
- End-to-end email retrieval
- Processing pipeline
- Database operations
- API endpoints

### Manual Testing
- Various email providers (Gmail, Outlook, etc.)
- Different newsletter services
- Edge cases (large attachments, malformed emails)
- Performance testing with large volumes

---

## 📚 Documentation Requirements

1. **User Guide**: How to set up and use email intelligence
2. **Administrator Guide**: Configuration and management
3. **Developer Guide**: Architecture and extension points
4. **API Documentation**: Complete API reference
5. **Security Guide**: Best practices for secure usage

---

## 🚀 Next Steps

1. **Review this plan** and provide feedback
2. **Prioritize features** based on immediate needs
3. **Assign team members** to different components
4. **Set up development environment** for the new branch
5. **Begin implementation** with Phase 1

---

## 📞 Support & Resources

- **Questions**: Open issues in the repository
- **Discussions**: Use GitHub Discussions for architecture questions
- **Documentation**: Update as implementation progresses
- **Examples**: Create example configurations and usage patterns

---

*Last Updated: $(date)*
*Status: Planning Phase*
