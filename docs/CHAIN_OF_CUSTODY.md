# Chain of Custody (CoC) for Open-Omniscience

> **Legal-Grade Audit Trail for Investigative Journalism**

The **Chain of Custody (CoC)** module provides **tamper-evident, cryptographically signed, and legally admissible** tracking of all actions performed on articles in the Open-Omniscience system. This ensures that **evidence can be verified in court**, **audited by third parties**, and **trusted by intelligence agencies and journalists**.

---

## 📋 Table of Contents

1. [Overview](#-overview)
2. [Features](#-features)
3. [Architecture](#-architecture)
4. [Quick Start](#-quick-start)
5. [Configuration](#-configuration)
6. [API Reference](#-api-reference)
7. [Integration Guide](#-integration-guide)
8. [Legal Compliance](#-legal-compliance)
9. [Security Considerations](#-security-considerations)
10. [Best Practices](#-best-practices)
11. [Troubleshooting](#-troubleshooting)

---

## 📖 Overview

### What is Chain of Custody?

**Chain of Custody (CoC)** is a **chronological documentation** of the **seizure, custody, control, transfer, analysis, and disposition** of evidence. In the context of Open-Omniscience, it tracks:

- **Who** performed an action (e.g., journalist, editor, system)
- **What** action was performed (e.g., ingest, modify, verify, anchor)
- **When** the action occurred (with **RFC 3161 timestamps** for legal admissibility)
- **Why** the action was performed (via metadata)
- **Proof** that the data was not tampered with (via **cryptographic hashes and signatures**)

### Why is CoC Important?

| **Use Case** | **Why CoC Matters** |
|--------------|---------------------|
| **Legal Proceedings** | Courts require **unbroken chain of custody** to admit digital evidence (e.g., war crimes, corruption). |
| **Investigative Journalism** | Proves that **leaked documents** were not altered after receipt. |
| **Intelligence Agencies** | Ensures **data integrity** across classified and unclassified systems. |
| **Whistleblower Protection** | Provides **non-repudiation** for sources and journalists. |
| **Audit & Compliance** | Meets **GDPR, FOIA, and eDiscovery** requirements. |
| **Disinformation Defense** | Proves **authenticity** of evidence in an era of deepfakes and manipulation. |

---

## ✨ Features

### Core Capabilities

| **Feature** | **Description** | **Legal Benefit** |
|-------------|----------------|-------------------|
| **Cryptographic Chaining** | Each CoC entry includes the **hash of the previous entry**, creating an unbreakable chain. | Prevents **tampering, deletion, or insertion** of entries. |
| **Digital Signatures (Ed25519)** | All entries are **signed** with a private key to prove **authorship and non-repudiation**. | Proves **who performed the action** in court. |
| **RFC 3161 Timestamps** | Uses **Trusted Timestamp Authority (TSA)** to prove **when** an action occurred. | Provides **legally admissible timestamps** (e.g., DigiCert, Sectigo). |
| **Offline-First** | Works **without internet** (fallback to local timestamps). | Enables **air-gapped and field operations**. |
| **Exportable Reports** | Generate **PDF and JSON** reports for legal proceedings. | **Court-admissible** evidence format. |
| **Redaction Support** | **Redact sensitive metadata** (e.g., journalist names) in exported reports. | Protects **sources and whistleblowers**. |
| **Tamper Detection** | Automatically detects **modified, deleted, or forged** entries. | **Self-auditing** for integrity. |

### Supported Actions

The CoC tracks the following **action types** (via `CoCAction` enum):

| **Action** | **Description** | **When Logged** |
|------------|----------------|-----------------|
| `INGEST` | Article ingested into the system | When `_add_to_blockchain()` is called in `main_pipeline.py` |
| `MODIFY` | Article metadata or content updated | Manually or via API |
| `ACCESS` | Article accessed (read/exported) | Manually or via API |
| `DELETE` | Article deleted (secure wipe) | Manually or via API |
| `VERIFY` | Article verified (hash check) | Manually or via API |
| `ANCHOR` | Article anchored to blockchain | When `anchor_current_block()` is called in `AnchorService` |
| `RESTORE` | Article restored from backup | Manually or via API |
| `EXPORT` | Article exported (e.g., to PDF/JSON) | Manually or via API |
| `REDACT` | Sensitive data redacted from article | Manually or via API |
| `SIGN` | Article signed (e.g., by journalist/editor) | Manually or via API |

---

## 🏗️ Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Open-Omniscience System                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────┐  │
│  │ main_pipeline│───▶│ ChainOfCustody   │───▶│ RFC 3161 TSA             │  │
│  │ (ingestion)  │    │ Logger           │    │ (timestamping)           │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────┘  │
│          │                     │                     │                     │
│          ▼                     ▼                     ▼                     │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────┐  │
│  │ IngestedData│    │ CoCEntry         │    │ TSA Token               │  │
│  │ (article)   │    │ (signed + chained)│    │ (timestamp proof)       │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                        CoC Storage (SQLite)                            │  │
│  │  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────┐  │  │
│  │  │ coc_entries  │    │ Signatures       │    │ Timestamps           │  │  │
│  │  │ (JSON)       │    │ (Ed25519)        │    │ (RFC 3161)          │  │  │
│  │  └─────────────┘    └─────────────────┘    └─────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                        Export & Verification                            │  │
│  │  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────┐  │  │
│  │  │ PDF Report   │    │ JSON Report      │    │ CoC Verifier        │  │  │
│  │  │ (human)      │    │ (machine)        │    │ (API + CLI)         │  │  │
│  │  └─────────────┘    └─────────────────┘    └─────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Ingestion** (`main_pipeline.py`)
   - Article is ingested → `_add_to_blockchain()` is called
   - CoC logs `INGEST` action with **content_hash, metadata_hash, source_hash**
   - Article is added to **LocalHashChain**

2. **Anchoring** (`anchor_service.py`)
   - Block is anchored to external blockchain (Ethereum, Arweave, etc.)
   - CoC logs `ANCHOR` action for **each article in the block**
   - Includes **transaction_hash, merkle_root, provider** in metadata

3. **Manual Actions** (API or CLI)
   - Users can log **MODIFY, ACCESS, DELETE, VERIFY, etc.** via API
   - Each action is **signed, timestamped, and chained**

4. **Verification**
   - **Hash chain**: Each entry's `previous_entry_hash` matches the previous entry
   - **Signatures**: Each entry's `actor_signature` is verified with the public key
   - **Timestamps**: Each TSA token is verified against the original data
   - **Entry hashes**: Each `entry_hash` matches the recomputed hash

---

## 🚀 Quick Start

### 1. Initialize the CoC Logger

```python
from src.blockchain.core.coc import initialize_coc_logger, get_coc_logger

# Initialize with signing and TSA (recommended for production)
initialize_coc_logger(
    db_path="data/coc.db",
    private_key=open("keys/private_key.pem", "rb").read(),  # Ed25519 private key
    tsa_url="http://timestamp.digicert.com",  # RFC 3161 TSA
    enable_signing=True,
    enable_tsa=True,
)

# Get the global logger
coc_logger = get_coc_logger()
```

### 2. Log an Action

```python
from src.blockchain.core.coc import CoCAction

# Log an ingestion action
entry = coc_logger.log_action(
    article_id="article_123",
    article_hash="abc123...",  # SHA-256 of article content
    action=CoCAction.INGEST,
    actor_id="journalist_1",
    metadata={"source": "leaked_document.pdf", "classification": "confidential"},
)

print(f"Logged entry: {entry.entry_id}")
print(f"Entry hash: {entry.entry_hash}")
print(f"Signature: {entry.actor_signature.hex()}")
```

### 3. Generate a Report

```python
# Generate a CoC report for an article
report = coc_logger.generate_report(
    article_id="article_123",
    redact_actor_ids=True,  # Hide journalist names
    redact_metadata=True,   # Hide sensitive metadata
)

# Export as JSON
report.to_json()

# Export as PDF
report.to_pdf("coc_report.pdf")
```

### 4. Verify the Chain of Custody

```python
# Verify the integrity of the CoC for an article
is_valid, errors = coc_logger.verify_coc("article_123")

if is_valid:
    print("✅ Chain of Custody is valid!")
else:
    print(f"❌ Chain of Custody is invalid: {errors}")
```

---

## ⚙️ Configuration

### Settings in `configs/blockchain.yml`

```yaml
# Chain of Custody Configuration
chain_of_custody:
  enabled: true
  db_path: "data/coc.db"
  
  # Digital Signing (Ed25519)
  signing:
    enabled: true
    private_key_path: "keys/coc_private_key.pem"  # Path to PEM-encoded Ed25519 private key
    
  # Timestamp Authority (RFC 3161)
  tsa:
    enabled: true
    url: "http://timestamp.digicert.com"  # Public TSA URL
    timeout: 10  # Request timeout in seconds
    retry_attempts: 3
    
  # Offline Mode (fallback if TSA is unavailable)
  offline:
    enabled: true
    use_local_timestamps: true
```

### Generating Ed25519 Keys

```bash
# Generate a new Ed25519 key pair
openssl genpkey -algorithm ed25519 -out coc_private_key.pem

# Extract the public key
openssl pkey -in coc_private_key.pem -pubout -out coc_public_key.pem
```

Or with Python:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

# Generate a new key pair
private_key = Ed25519PrivateKey.generate()

# Save private key (PEM format)
private_key_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
with open("coc_private_key.pem", "wb") as f:
    f.write(private_key_bytes)

# Save public key (PEM format)
public_key_bytes = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
with open("coc_public_key.pem", "wb") as f:
    f.write(public_key_bytes)
```

---

## 📡 API Reference

### Base URL

```
http://localhost:8000/api/blockchain/coc
```

### Endpoints

#### **GET `/coc/{article_id}`**

Get the **Chain of Custody report** for an article.

**Query Parameters:**
- `redact_actor_ids` (bool): Redact actor IDs in the report (default: `false`)
- `redact_metadata` (bool): Redact metadata in the report (default: `false`)

**Response:** `CoCReport` (JSON)

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123?redact_actor_ids=true"
```

---

#### **GET `/coc/{article_id}/verify`**

Verify the **integrity of the Chain of Custody** for an article.

**Response:**
```json
{
  "article_id": "article_123",
  "is_valid": true,
  "errors": []
}
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/verify"
```

---

#### **GET `/coc/{article_id}/export/json`**

Export the **CoC report as JSON** (machine-readable).

**Query Parameters:**
- `redact_actor_ids` (bool): Redact actor IDs (default: `false`)
- `redact_metadata` (bool): Redact metadata (default: `false`)

**Response:** JSON file download

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/export/json" -o coc_report.json
```

---

#### **GET `/coc/{article_id}/entries`**

Get **all CoC entries** for an article.

**Response:** List of `CoCEntry` objects (JSON)

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/entries"
```

---

#### **GET `/coc/articles`**

Get a **list of all article IDs** with CoC entries.

**Response:** `List[str]`

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/articles"
```

---

#### **GET `/coc/stats`**

Get **statistics** about the CoC database.

**Response:**
```json
{
  "total_entries": 150,
  "total_articles": 50,
  "tsa_entries": 140,
  "signed_entries": 150,
  "db_path": "data/coc.db",
  "enable_signing": true,
  "enable_tsa": true
}
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/stats"
```

---

#### **POST `/coc/{article_id}/log`**

**Manually log a CoC action** for an article.

**Query Parameters:**
- `action` (str, required): Action to log (e.g., `modify`, `access`, `verify`)
- `article_hash` (str, required): SHA-256 hash of the article content
- `actor_id` (str, optional): ID of the actor performing the action

**Request Body (JSON):**
```json
{
  "metadata": {"key": "value"}
}
```

**Response:**
```json
{
  "status": "success",
  "entry": {
    "entry_id": "uuid",
    "article_id": "article_123",
    "action": "modify",
    "timestamp": "2024-01-01T12:00:00+00:00",
    "entry_hash": "abc123...",
    "actor_id": "user_1",
    "metadata": {"key": "value"}
  }
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/api/blockchain/coc/article_123/log?action=modify&article_hash=abc123" \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"reason": "corrected typo"}}'
```

---

## 🔗 Integration Guide

### With `main_pipeline.py`

CoC is **automatically integrated** with the main pipeline. When an article is ingested via `_add_to_blockchain()`, a `CoCAction.INGEST` entry is logged:

```python
# In main_pipeline.py
from src.blockchain.core.coc import get_coc_logger, CoCAction

coc_logger = get_coc_logger()
coc_entry = coc_logger.log_action(
    article_id=article_id,
    article_hash=content_hash,
    action=CoCAction.INGEST,
    actor_id="pipeline",
    metadata={"url": ingested_data.url, "source_type": ingested_data.source_type}
)
```

### With `anchor_service.py`

CoC is **automatically integrated** with the anchor service. When a block is anchored via `anchor_current_block()`, a `CoCAction.ANCHOR` entry is logged for each article in the block:

```python
# In anchor_service.py
from src.blockchain.core.coc import get_coc_logger, CoCAction

coc_logger = get_coc_logger()
coc_logger.log_action(
    article_id=article_id,
    article_hash=article_hashes['content_hash'],
    action=CoCAction.ANCHOR,
    actor_id=f"anchor_service:{provider_name}",
    metadata={
        'block_height': block.block_height,
        'provider': provider_name,
        'transaction_hash': transaction_hash,
        'merkle_root': block.merkle_root
    }
)
```

### Manual Integration

You can manually log CoC actions anywhere in your code:

```python
from src.blockchain.core.coc import get_coc_logger, CoCAction

coc_logger = get_coc_logger()

# Log a modification
coc_logger.log_action(
    article_id="article_123",
    article_hash="new_hash_after_modification",
    action=CoCAction.MODIFY,
    actor_id="editor_1",
    metadata={"changes": ["fixed typo", "updated title"]}
)

# Log an access
coc_logger.log_action(
    article_id="article_123",
    article_hash="abc123",
    action=CoCAction.ACCESS,
    actor_id="investigator_1",
    metadata={"purpose": "fact-checking"}
)
```

---

## ⚖️ Legal Compliance

### RFC 3161 Timestamp Authority (TSA)

**RFC 3161** is the **international standard** for **trusted timestamps**. Open-Omniscience uses RFC 3161 to provide **legally admissible proof** of when actions occurred.

#### Supported TSAs

| **Provider** | **URL** | **Status** |
|--------------|---------|------------|
| DigiCert | `http://timestamp.digicert.com` | ✅ Recommended |
| Sectigo | `http://timestamp.sectigo.com` | ✅ Supported |
| GlobalSign | `http://timestamp.globalsign.com` | ✅ Supported |
| D-Trust | `http://zeitstempel.d-trust.net` | ✅ Supported |

#### Why RFC 3161?

- **Legally binding**: Recognized by **courts worldwide** (e.g., US, EU, UK)
- **Non-repudiation**: Proves **when** data existed (not just when it was logged)
- **Long-term validity**: Timestamps remain valid **even if the TSA key is compromised**
- **Standardized**: Used by **Adobe, Microsoft, Java, and Linux**

### Chain of Custody in Court

To use CoC reports in **legal proceedings**:

1. **Generate a PDF report** (human-readable):
   ```python
   report = coc_logger.generate_report(article_id)
   report.to_pdf("coc_report.pdf")
   ```

2. **Generate a JSON report** (machine-verifiable):
   ```python
   report.to_json()
   ```

3. **Include in evidence**:
   - **PDF**: For judges and juries
   - **JSON**: For opposing counsel to verify
   - **Raw database**: For forensic analysis

4. **Verify in court**:
   - **Hash chain**: Prove no entries were modified/deleted
   - **Signatures**: Prove who performed each action
   - **Timestamps**: Prove when each action occurred

### GDPR Compliance

CoC supports **GDPR compliance** via:

- **Redaction**: Hide **actor IDs** and **metadata** in exported reports
- **Data minimization**: Only store **what is necessary** for verification
- **Right to erasure**: **Pseudonymize** data instead of deleting (to preserve CoC)

Example:
```python
# Export with redaction
report = coc_logger.generate_report(
    article_id,
    redact_actor_ids=True,  # Hide journalist names
    redact_metadata=True,   # Hide sensitive metadata
)
```

---

## 🔒 Security Considerations

### Key Management

- **Private keys** should be stored in **hardware security modules (HSMs)** or **encrypted files**
- **Never commit private keys** to version control
- **Rotate keys periodically** (e.g., every 90 days)
- **Use Ed25519** (faster and more secure than RSA for signing)

### Tamper Detection

CoC detects tampering via:

1. **Hash chain**: Each entry includes `previous_entry_hash`
   - If an entry is **modified**, its hash changes, breaking the chain
   - If an entry is **deleted**, the next entry's `previous_entry_hash` becomes invalid
   - If an entry is **inserted**, the chain is broken

2. **Digital signatures**: Each entry is signed with a private key
   - If an entry is **modified**, its signature becomes invalid
   - If a **new key** is used, old entries remain verifiable

3. **TSA timestamps**: Each entry can include a **trusted timestamp**
   - Proves **when** the entry was created
   - **Cannot be backdated** (TSA signs the hash + timestamp)

### Offline Mode

- If **TSA is unavailable**, CoC falls back to **local timestamps**
- If **signing is disabled**, CoC still logs entries (but without signatures)
- **All features work offline** (SQLite-based storage)

---

## 🎯 Best Practices

### For Journalists

1. **Always enable signing and TSA** for maximum legal defensibility
2. **Log all actions** (ingest, modify, verify, export)
3. **Use unique actor IDs** (e.g., journalist email or username)
4. **Include metadata** (e.g., source, purpose, classification)
5. **Export reports regularly** (PDF + JSON) for backup

### For Developers

1. **Use the singleton pattern** (`get_coc_logger()`) for global access
2. **Handle exceptions gracefully** (CoC should not break the main workflow)
3. **Log errors** if CoC logging fails (but continue execution)
4. **Test tamper detection** (verify that `verify_coc()` catches modifications)
5. **Benchmark performance** (CoC logging should add <100ms per action)

### For System Administrators

1. **Backup the CoC database** (`coc.db`) regularly
2. **Secure the private key** (use HSM or encrypted storage)
3. **Monitor TSA availability** (fallback to local timestamps if offline)
4. **Rotate keys periodically** (e.g., every 90 days)
5. **Audit CoC logs** for suspicious activity

---

## 🐛 Troubleshooting

### Common Issues

| **Issue** | **Cause** | **Solution** |
|-----------|-----------|--------------|
| `CoCError: CoC logger not initialized` | Forgot to call `initialize_coc_logger()` | Call `initialize_coc_logger()` before using CoC |
| `TSARequestError: TSA request failed` | TSA server is down or unreachable | Check network, use fallback to local timestamps |
| `CoCSignatureError: Signing requires 'cryptography' library` | Missing `cryptography` dependency | `pip install cryptography` |
| `CoCVerificationError: Entry hash mismatch` | Database was tampered with | Investigate security breach |
| `PDF generation failed` | Missing `pdfkit` or `wkhtmltopdf` | `pip install pdfkit` and install `wkhtmltopdf` |

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now CoC operations will log debug info
coc_logger = get_coc_logger()
entry = coc_logger.log_action(...)
```

### Testing CoC Integrity

```python
# Verify all CoC entries for all articles
coc_logger = get_coc_logger()
articles = coc_logger.get_all_articles()

for article_id in articles:
    is_valid, errors = coc_logger.verify_coc(article_id)
    if not is_valid:
        print(f"❌ Article {article_id} has CoC errors: {errors}")
    else:
        print(f"✅ Article {article_id} CoC is valid")
```

---

## 📚 Further Reading

- [RFC 3161: Internet X.509 PKI Time-Stamp Protocol](https://tools.ietf.org/html/rfc3161)
- [Ed25519: Elliptic Curve Signatures](https://ed25519.cr.yp.to/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [Python `cryptography` Library](https://cryptography.io/en/latest/)
- [Chain of Custody in Digital Forensics](https://en.wikipedia.org/wiki/Chain_of_custody#Digital_evidence)

---

## 📄 License

This documentation is part of **Open-Omniscience** and is licensed under the **GNU GPLv3**.

© 2026 Ideotion. All rights reserved.
