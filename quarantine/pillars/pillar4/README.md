# 🚨 Pillar 4: Real-Time Monitoring & Alerting System

**100% Open-Source, Offline-Capable Real-Time Surveillance System**

Pillar 4 provides comprehensive real-time monitoring and alerting capabilities for Open-Omniscience, enabling continuous surveillance of information sources and immediate detection of emerging threats, disinformation campaigns, and suspicious activities.

## 🎯 Overview

Pillar 4 extends the detection capabilities of Pillar 3 by adding **real-time monitoring** and **proactive alerting**. While Pillar 3 focuses on analyzing individual pieces of content, Pillar 4 provides:

- **Continuous Monitoring**: 24/7 surveillance of news sources, social media, APIs, and databases
- **Real-Time Anomaly Detection**: Immediate identification of unusual patterns and potential threats
- **Trend Analysis**: Detection of emerging narratives, topics, and coordinated campaigns
- **Automated Alerting**: Multi-channel notifications (email, webhooks, APIs, chat platforms)
- **Threat Intelligence**: Integration with open-source threat feeds for contextual enrichment
- **Adaptive Learning**: System that improves over time based on feedback and new data

All functionality works **100% offline** with no cloud dependencies, making it suitable for air-gapped environments and privacy-conscious applications.

## 📁 Project Structure

```
pillar4/
├── src/
│   ├── analysis/              # Advanced analysis modules
│   │   ├── anomaly_detector.py   # Real-time anomaly detection
│   │   ├── trend_analyzer.py     # Trend detection and analysis
│   │   ├── pattern_recognizer.py # Pattern recognition in data streams
│   │   └── threat_intel.py      # Threat intelligence integration
│   ├── monitoring/            # Core monitoring infrastructure
│   │   ├── stream_processor.py  # Async stream processing engine
│   │   ├── source_manager.py    # Source configuration and management
│   │   ├── scheduler.py         # Monitoring schedule management
│   │   └── health_monitor.py    # System health monitoring
│   ├── alerting/              # Alerting system
│   │   ├── alert_manager.py     # Alert lifecycle management
│   │   ├── notification_channels.py # Multi-channel notifications
│   │   ├── alert_rules.py       # Rule-based alert configuration
│   │   └── alert_escalation.py  # Alert escalation policies
│   ├── models/                # ML models for real-time analysis
│   │   └── ...
│   └── utils/                  # Utility functions
│       └── ...
├── tests/                     # Comprehensive test suite
│   └── ...
├── examples/                  # Usage examples
│   └── ...
├── configs/                  # Configuration files
│   ├── monitoring.yml         # Monitoring configuration
│   ├── alerts.yml             # Alert configuration
│   └── sources.yml            # Source configurations
├── data/                      # Runtime data
│   ├── cache/
│   ├── logs/
│   └── state/
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## 🚀 Quick Start

```bash
# Navigate to Pillar 4 directory
cd pillar4

# Install dependencies
pip install -r requirements.txt

# Run basic monitoring example
python examples/realtime_monitoring_demo.py

# Run tests
python -m pytest tests/ -v
```

## 📋 Features by Phase

### Phase 4.1: Real-Time Monitoring Infrastructure ✅

**Status:** Ready for Implementation

#### Core Components:

1. **Stream Processing Engine** (`stream_processor.py`)
   - Asynchronous stream processing with backpressure handling
   - Batch processing for high-volume streams
   - Stream recovery and checkpointing
   - Parallel processing pipelines
   - Support for multiple stream types (HTTP, WebSocket, RSS, etc.)

2. **Source Management** (`source_manager.py`)
   - Source configuration and validation
   - Source health monitoring and automatic failover
   - Source categorization and prioritization
   - Rate limiting and throttling per source
   - Source authentication and security

3. **Monitoring Scheduler** (`scheduler.py`)
   - Cron-based scheduling for periodic monitoring
   - Event-driven monitoring for real-time sources
   - Dynamic schedule adjustment based on source activity
   - Monitoring job queue management
   - Job retry and error handling

4. **System Health Monitoring** (`health_monitor.py`)
   - Resource usage monitoring (CPU, memory, disk, network)
   - Service health checks and heartbeats
   - Performance metrics collection
   - Self-healing capabilities
   - Alerting on system health issues

#### Example Usage:

```python
from pillar4.monitoring import StreamProcessor, SourceManager, Scheduler

# Initialize components
processor = StreamProcessor(max_concurrent_streams=10)
source_manager = SourceManager()
scheduler = Scheduler()

# Add a source
source_config = {
    "id": "news_source_1",
    "type": "rss",
    "url": "https://example.com/rss",
    "interval": 300,  # 5 minutes
    "priority": "high"
}
source_manager.add_source(source_config)

# Start monitoring
scheduler.add_job(source_id="news_source_1", interval=300)
scheduler.start()

# Process incoming data
async def process_item(item):
    # Your processing logic here
    print(f"Processing: {item['title']}")
    return await processor.process(item, process_item)
```

---

### Phase 4.2: Anomaly Detection & Trend Analysis 🔄

**Status:** Ready for Implementation

#### Core Components:

1. **Anomaly Detection** (`anomaly_detector.py`)
   - **Statistical Methods**: Z-score, IQR, moving averages, standard deviation
   - **Machine Learning**: Isolation Forest, One-Class SVM, Local Outlier Factor
   - **Temporal Analysis**: Sudden spikes, drops, pattern changes, seasonality
   - **Contextual Analysis**: Anomalies relative to historical context and similar sources
   - **Multi-dimensional**: Detect anomalies across multiple features simultaneously

2. **Trend Analysis** (`trend_analyzer.py`)
   - **Time Series Analysis**: Trend identification, seasonality detection, forecasting
   - **Emerging Narratives**: Detection of new topics and narratives
   - **Topic Modeling**: LDA, NMF, BERTopic for topic extraction and evolution
   - **Sentiment Trends**: Sentiment analysis over time
   - **Volume Analysis**: Content volume trends and anomalies

3. **Pattern Recognition** (`pattern_recognizer.py`)
   - **Repeating Patterns**: Detection of recurring content patterns
   - **Coordination Detection**: Multiple sources posting similar content simultaneously
   - **Campaign Fingerprinting**: Identify coordinated disinformation campaigns
   - **Behavioral Patterns**: Recognize typical behavior patterns of sources
   - **Temporal Patterns**: Identify patterns in timing and frequency

4. **Threat Intelligence Integration** (`threat_intel.py`)
   - **IOC Matching**: Match against known Indicators of Compromise
   - **Threat Actor Attribution**: Identify known threat actors
   - **Contextual Enrichment**: Add context from threat intelligence feeds
   - **Reputation Analysis**: Source reputation based on threat intelligence
   - **STIX/TAXII Support**: Standard threat intelligence formats

#### Example Usage:

```python
from pillar4.analysis import AnomalyDetector, TrendAnalyzer, PatternRecognizer

# Initialize analyzers
detector = AnomalyDetector()
trend_analyzer = TrendAnalyzer()
pattern_recognizer = PatternRecognizer()

# Detect anomalies in new data
data_point = {"value": 150, "timestamp": "2024-01-01T12:00:00Z"}
anomaly_score = detector.detect(data_point)
if anomaly_score > 0.9:
    print(f"High anomaly detected: {anomaly_score}")

# Analyze trends
historical_data = [...]  # List of data points
trends = trend_analyzer.analyze(historical_data)
for trend in trends:
    print(f"Trend: {trend['direction']}, Strength: {trend['strength']}")

# Recognize patterns
items = [...]  # List of content items
patterns = pattern_recognizer.find_patterns(items)
for pattern in patterns:
    print(f"Pattern: {pattern['type']}, Confidence: {pattern['confidence']}")
```

---

### Phase 4.3: Alerting System 📅

**Status:** Ready for Implementation

#### Core Components:

1. **Alert Management** (`alert_manager.py`)
   - Alert creation and deduplication
   - Alert lifecycle management (new, acknowledged, resolved, closed)
   - Alert prioritization (Critical, High, Medium, Low)
   - Alert correlation and grouping of related alerts
   - Alert history and audit trail

2. **Notification Channels** (`notification_channels.py`)
   - **Email**: SMTP-based email notifications with Jinja2 templating
   - **Webhooks**: HTTP POST notifications to external systems
   - **API**: REST API for alert retrieval and management
   - **Chat Platforms**: Slack, Discord, Microsoft Teams integration
   - **SMS**: SMS notifications via third-party gateways (Twilio, etc.)

3. **Alert Rules Engine** (`alert_rules.py`)
   - Rule-based alert configuration using YAML/JSON
   - Conditional alert triggering (IF-THIS-THEN-THAT logic)
   - Threshold-based alerts (value > X, rate > Y, etc.)
   - Multi-condition alerts (AND/OR logic)
   - Time-based alerts (alert if condition persists for N minutes)

4. **Alert Escalation** (`alert_escalation.py`)
   - Escalation policies based on severity and time
   - Multi-level escalation paths (Level 1 → Level 2 → Level 3)
   - Automatic escalation for unacknowledged alerts
   - Escalation history tracking
   - Custom escalation workflows

#### Example Usage:

```python
from pillar4.alerting import AlertManager, NotificationChannels, AlertRulesEngine

# Initialize alerting system
alert_manager = AlertManager()
channels = NotificationChannels()
rules_engine = AlertRulesEngine()

# Configure email channel
channels.add_email_channel(
    name="admin_email",
    smtp_server="smtp.example.com",
    port=587,
    username="user@example.com",
    password="password",
    from_addr="alerts@example.com",
    to_addrs=["admin@example.com"]
)

# Configure webhook channel
channels.add_webhook_channel(
    name="slack_webhook",
    url="https://hooks.slack.com/services/...",
    method="POST",
    headers={"Content-Type": "application/json"}
)

# Create alert rule
rule = {
    "name": "high_anomaly_rule",
    "condition": "anomaly_score > 0.9",
    "severity": "high",
    "channels": ["admin_email", "slack_webhook"],
    "escalation": {"after": "1h", "to": "manager_email"}
}
rules_engine.add_rule(rule)

# Trigger an alert
alert = alert_manager.create_alert(
    title="High Anomaly Detected",
    description="Anomaly score of 0.95 detected in news source",
    severity="high",
    source="news_source_1",
    metadata={"anomaly_score": 0.95, "timestamp": "2024-01-01T12:00:00Z"}
)

# Dispatch alert
alert_manager.dispatch_alert(alert)
```

---

### Phase 4.4: Adaptive Learning & Optimization 📅

**Status:** Ready for Implementation

#### Core Components:

1. **Feedback Integration**
   - User feedback collection on alerts (relevant/irrelevant, true/false positive)
   - False positive/negative tracking and analysis
   - Feedback-based model retraining and improvement
   - Feedback history and analytics

2. **Adaptive Thresholds**
   - Dynamic threshold adjustment based on feedback
   - Source-specific threshold tuning
   - Time-based threshold adaptation (different thresholds for different times)
   - Context-aware thresholding

3. **Performance Optimization**
   - Monitoring efficiency optimization
   - Resource usage optimization (CPU, memory, network)
   - Processing pipeline optimization
   - Caching strategies for frequently accessed data

4. **Continuous Learning**
   - Online learning for anomaly detection models
   - Trend model updates based on new data
   - Pattern recognition improvement over time
   - Model versioning and rollback capabilities

---

## 🎯 Key Features

### 1. Multi-Source Monitoring
Monitor various types of information sources:
- **Web Sources**: News websites, blogs, forums
- **Social Media**: Twitter/X, Facebook, Reddit, Telegram, Mastodon
- **RSS/Atom Feeds**: News feeds, blog feeds, podcast feeds
- **APIs**: REST APIs, GraphQL APIs, WebSocket APIs
- **Databases**: PostgreSQL, MySQL, MongoDB, SQLite
- **File Systems**: Local files, remote files (SFTP, S3-compatible)

### 2. Advanced Detection Capabilities
- **Real-time Anomaly Detection**: Immediate detection of unusual patterns
- **Trend Analysis**: Identification of emerging narratives and topics
- **Pattern Recognition**: Detection of coordinated campaigns and behaviors
- **Threat Intelligence**: Integration with open-source threat feeds
- **Contextual Analysis**: Understanding content in context
- **Multi-dimensional Analysis**: Analyze multiple features simultaneously

### 3. Flexible Alerting
- **Multiple Channels**: Email, webhooks, APIs, SMS, chat platforms
- **Customizable Rules**: Define what triggers alerts using YAML/JSON
- **Severity Levels**: Critical, High, Medium, Low
- **Escalation Policies**: Automatic escalation for unaddressed alerts
- **Deduplication**: Prevent alert spam from similar events
- **Rate Limiting**: Control alert frequency to prevent overload

### 4. Scalability & Reliability
- **Asynchronous Processing**: Non-blocking I/O operations
- **Rate Limiting**: Prevent overwhelming sources or being rate-limited
- **Retry Logic**: Automatic retry for failed operations
- **Circuit Breakers**: Prevent cascading failures
- **Load Shedding**: Graceful degradation under heavy load
- **Horizontal Scaling**: Add more monitoring instances
- **Vertical Scaling**: Increase resources per instance

### 5. Observability
- **Comprehensive Logging**: Structured logs for all operations
- **Metrics Collection**: Performance and usage metrics (Prometheus-compatible)
- **Health Checks**: System and service health monitoring
- **Alert Monitoring**: Monitor the alerting system itself
- **Audit Trails**: Complete history of all monitoring activities
- **Dashboards**: Visualization of monitoring status and metrics

---

## 📊 Performance Metrics

### Target Performance:
- **Throughput**: 10,000+ items/hour per monitoring instance
- **Latency**: < 1 second for alert generation after detection
- **Availability**: 99.9% uptime
- **False Positive Rate**: < 5%
- **False Negative Rate**: < 10%

### Resource Requirements:
- **CPU**: 2+ cores recommended
- **Memory**: 4GB+ recommended
- **Disk**: 10GB+ for logs and cache
- **Network**: 100Mbps+ for high-volume monitoring

---

## 🔧 Configuration

### Monitoring Configuration (`configs/monitoring.yml`):

```yaml
# Global settings
global:
  max_concurrent_streams: 10
  request_timeout: 30
  retry_attempts: 3
  retry_delay: 5
  user_agent: "OpenOmniscience-Monitor/1.0"

# Source configurations
sources:
  news_source_1:
    type: rss
    url: https://example.com/rss
    interval: 300  # seconds
    priority: high
    rate_limit: 10  # requests per minute
    
  twitter_source:
    type: twitter
    api_key: ${TWITTER_API_KEY}
    api_secret: ${TWITTER_API_SECRET}
    interval: 60
    priority: medium
    search_queries:
      - "disinformation"
      - "fake news"
      - "deepfake"

# Processing settings
processing:
  batch_size: 100
  flush_interval: 60  # seconds
  max_queue_size: 1000
```

### Alert Configuration (`configs/alerts.yml`):

```yaml
# Alert severity levels
severity_levels:
  critical:
    color: red
    sound: alarm
    notify_all: true
    
  high:
    color: orange
    sound: alert
    notify_all: false
    
  medium:
    color: yellow
    sound: notification
    notify_all: false
    
  low:
    color: blue
    sound: none
    notify_all: false

# Notification channels
channels:
  email:
    enabled: true
    smtp_server: smtp.example.com
    port: 587
    username: ${EMAIL_USERNAME}
    password: ${EMAIL_PASSWORD}
    from_addr: alerts@example.com
    to_addrs:
      - admin@example.com
      - security@example.com
    
  slack:
    enabled: true
    webhook_url: ${SLACK_WEBHOOK_URL}
    
  webhook:
    enabled: true
    url: https://api.example.com/webhook
    method: POST
    headers:
      Content-Type: application/json
      Authorization: Bearer ${WEBHOOK_TOKEN}

# Alert rules
rules:
  high_anomaly:
    condition: anomaly_score > 0.9
    severity: high
    channels: [email, slack]
    description: "High anomaly score detected"
    
  trend_detected:
    condition: trend_strength > 0.8
    severity: medium
    channels: [email]
    description: "Emerging trend detected"
    
  source_down:
    condition: source_health == "down"
    severity: critical
    channels: [email, slack, webhook]
    description: "Monitored source is down"
```

---

## 🛡️ Security Considerations

### Data Security:
- **Encryption**: All sensitive data encrypted at rest (AES-256) and in transit (TLS)
- **Access Control**: Role-based access control (RBAC) for monitoring data
- **Audit Logging**: Complete audit trail of all access and modifications
- **Data Retention**: Configurable retention policies with automatic purging
- **Secure Deletion**: Cryptographic shredding of deleted data

### Source Security:
- **Authentication**: Secure authentication with all monitored sources
- **Rate Limiting**: Prevent abuse of monitored sources and avoid being rate-limited
- **Input Validation**: Validate and sanitize all incoming data
- **Sandboxing**: Isolate processing of untrusted content in sandboxed environments
- **API Keys**: Secure storage and rotation of API keys and credentials

### Alert Security:
- **Encrypted Notifications**: Encrypt sensitive alert content in transit
- **Authentication**: Authenticate notification recipients
- **Integrity**: Digital signatures to ensure alert content cannot be tampered with
- **Non-Repudiation**: Cryptographic proof of alert delivery
- **Secure Channels**: Use encrypted channels for all notifications

---

## 📚 Dependencies

All dependencies are 100% FOSS and available via pip:

### Core Dependencies:
- Python 3.12+
- aiohttp - Async HTTP client
- requests - HTTP requests
- pydantic - Data validation
- APScheduler - Advanced scheduling
- feedparser - RSS/Atom feed parsing

### Data Processing:
- numpy - Numerical computing
- pandas - Data analysis
- scipy - Scientific computing
- statsmodels - Time series analysis

### Machine Learning:
- scikit-learn - ML algorithms
- river - Online machine learning
- gensim - Topic modeling

### Monitoring:
- prometheus-client - Metrics collection
- structlog - Structured logging

### Optional:
- redis - Alert queue management
- psycopg2 - PostgreSQL support
- stix2 - Threat intelligence standards

See `requirements.txt` for complete list with versions.

---

## 📖 Documentation

- **[PILLAR4_SUMMARY.md](PILLAR4_SUMMARY.md)** - Detailed implementation plan
- **examples/** - Usage examples and demos
- **tests/** - Comprehensive test suite

---

## 🆘 Support

- **GitHub Issues**: Report bugs and request features
- **Discussions**: Ask questions and share ideas
- **Documentation**: Check the docs first!
- **Email**: contact@ideotion.com

---

## 📅 Changelog

### Version 0.1.0 (Current)
- Initial Pillar 4 structure and documentation
- Directory structure created
- Requirements defined
- Module stubs created
- Comprehensive documentation added

---

**© 2026 Ideotion. All rights reserved.**

*Built with ❤️ for investigative journalism and ethical data analysis.*
