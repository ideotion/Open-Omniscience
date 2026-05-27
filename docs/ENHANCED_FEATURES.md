"""
Open Omniscience - Enhanced Blockchain Features for Single-User Deployment

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

For inquiries, contact: open-omniscience@ideotion.com
"""

# Enhanced Blockchain Features for Single-User Deployment

This document describes the enhanced features implemented for single-user deployments of the Open-Omniscience blockchain verification system. These features provide **robustness, reliability, and trust** without requiring external dependencies or complex consensus mechanisms.

## 🎯 Overview

The enhanced features are designed specifically for single-user scenarios where:
- No external blockchain providers are available or desired
- All operations must work offline
- Data integrity and tamper-proofing are critical
- Automatic protection against data loss is required
- No complex consensus mechanisms are needed

## 📋 Feature List

| Feature | Description | Status |
|---------|-------------|--------|
| Multi-Hash Algorithms | Multiple cryptographic hash algorithms for redundancy | ✅ Implemented |
| WORM Mode | Write-Once-Read-Many storage to prevent tampering | ✅ Implemented |
| Audit Logging | Immutable, cryptographically chained audit log | ✅ Implemented |
| Integrity Monitoring | Real-time background integrity checks | ✅ Implemented |
| Automated Backups | Periodic backups with rotation | ✅ Implemented |
| Disaster Recovery | Restore from backups | ✅ Implemented |

## 🔐 1. Multi-Hash Algorithm Support

### Purpose
Provides cryptographic redundancy by computing multiple hash algorithms for each piece of data. This ensures that even if one hash algorithm is compromised (e.g., due to cryptographic advances), the other algorithms still provide protection.

### Implementation

#### Hash Algorithms Supported
- **SHA-256** - Primary algorithm (64 hex characters)
- **SHA-512** - Longer hash for additional security (128 hex characters)
- **BLAKE2b** - Fast, modern hash function (128 hex characters)
- **BLAKE2s** - Faster variant for shorter hashes
- **RIPEMD-160** - Legacy algorithm for compatibility
- **SHA3-256** - Next-generation hash function
- **SHA3-512** - Next-generation hash function with longer output

#### Default Algorithms
By default, the system uses SHA-256, SHA-512, and BLAKE2b for all hashes.

### Usage

```python
from src.blockchain.core import compute_multi_hash, HashAlgorithm

# Compute multi-hash for data
data = "Important article content"
result = compute_multi_hash(data)

print(f"SHA-256: {result.sha256}")
print(f"SHA-512: {result.sha512}")
print(f"BLAKE2b: {result.blake2b}")

# Verify consistency
is_consistent = result.verify_consistency(data)
assert is_consistent == True
```

### Data Structures

#### HashResult
Stores the results of multiple hash algorithms for a single piece of data:
```python
@dataclass
class HashResult:
    sha256: str = ""
    sha512: str = ""
    blake2b: str = ""
    ripemd160: Optional[str] = None
    sha3_256: Optional[str] = None
    sha3_512: Optional[str] = None
```

#### MultiHash
Stores multi-hash results for all three article components:
```python
@dataclass
class MultiHash:
    content: HashResult
    metadata: HashResult
    source: HashResult
    timestamp: float
```

### Benefits
- **Cryptographic redundancy**: Multiple algorithms provide defense in depth
- **Future-proof**: If one algorithm is broken, others remain secure
- **Cross-verification**: Can verify data consistency across algorithms
- **Flexible**: Can add new algorithms without breaking existing code

---

## 🏛️ 2. WORM (Write-Once-Read-Many) Mode

### Purpose
Prevents modification of existing data, ensuring that once an article is added to the blockchain, it cannot be altered or deleted. This is critical for:
- Legal admissibility (non-repudiation)
- Tamper-proof storage
- Audit trail integrity
- Compliance requirements

### Implementation

The `EnhancedLocalHashChain` class extends the base `LocalHashChain` with WORM capabilities:

```python
from src.blockchain.core import EnhancedLocalHashChain, WORMError

# Create chain with WORM mode enabled (default)
chain = EnhancedLocalHashChain(
    db_path="data/blockchain/enhanced_hash_chain.db",
    worm_mode=True,  # Enable WORM mode
    multi_hash_enabled=True,
    audit_log_path="data/blockchain/audit.log"
)

# Add an article
content_hash = hashlib.sha256(content.encode()).hexdigest()
metadata_hash = hashlib.sha256(str(metadata).encode()).hexdigest()
source_hash = hashlib.sha256(source.encode()).hexdigest()

chain.add_article("article-1", content_hash, metadata_hash, source_hash)

# Try to add the same article again - will raise WORMError
try:
    chain.add_article("article-1", content_hash, metadata_hash, source_hash)
except WORMError as e:
    print(f"WORM violation: {e}")
```

### WORMError Exception
```python
class WORMError(Exception):
    """Raised when WORM (Write-Once-Read-Many) violation is detected."""
    pass
```

### Benefits
- **Tamper-proof**: Existing data cannot be modified
- **Legal compliance**: Meets requirements for evidence admissibility
- **Audit integrity**: Ensures audit trail cannot be altered
- **Data protection**: Prevents accidental or malicious data corruption

---

## 📜 3. Immutable Audit Logging

### Purpose
Provides a complete, cryptographically verifiable log of all blockchain operations. Each audit entry is linked to the previous one, creating a chain that can be verified for integrity.

### Implementation

#### AuditLogger Class
```python
from src.blockchain.core import AuditLogger, AuditEntry

# Create audit logger
logger = AuditLogger(log_path="data/blockchain/audit.log")

# Log an operation
entry = logger.log(
    action="add_article",
    article_id="article-1",
    block_height=0,
    details={"content_hash": "abc123...", "position": 0}
)

# Verify audit log integrity
is_integrity_ok = logger.verify_integrity()
assert is_integrity_ok == True

# Get entries
entries = logger.get_entries()
for entry in entries:
    print(f"{entry.timestamp}: {entry.action} - {entry.article_id}")
```

#### AuditEntry Structure
```python
@dataclass
class AuditEntry:
    timestamp: float
    action: str
    article_id: Optional[str]
    block_height: Optional[int]
    details: Dict[str, Any] = field(default_factory=dict)
    hash_chain_state: Optional[str] = None
```

### Cryptographic Chaining
Each audit entry includes:
1. **hash_chain_state**: SHA-256 hash of the entry's data
2. **previous_entry_hash**: Reference to the previous entry's hash_chain_state

This creates a chain where any modification to an entry will break the chain, making tampering detectable.

### Verification
```python
# Verify the entire audit log
is_ok = logger.verify_integrity()

# If tampering is detected, this returns False
assert is_ok == True
```

### Benefits
- **Tamper-evident**: Any modification to audit log is detectable
- **Complete history**: All operations are logged with timestamps
- **Cryptographically secure**: SHA-256 hashing ensures integrity
- **Append-only**: Entries can only be added, never modified or deleted
- **Self-verifying**: Can verify integrity without external references

---

## 🔍 4. Real-Time Integrity Monitoring

### Purpose
Provides continuous monitoring of blockchain data integrity with automated checks and alerts.

### Implementation

#### IntegrityMonitor Class
```python
from src.blockchain.core.integrity_monitor import IntegrityMonitor, IntegrityStatus

# Create monitor
monitor = IntegrityMonitor(
    hash_chain=chain,
    check_interval=300,  # 5 minutes
    backup_interval=3600,  # 1 hour
    backup_dir="data/blockchain/backups",
    max_backups=10,
    alert_callback=send_alert  # Optional alert function
)

# Start monitoring
monitor.start()

# Get current status
status = monitor.get_overall_status()
assert status == IntegrityStatus.HEALTHY

# Get check results
results = monitor.get_check_results()
for result in results:
    print(f"{result.check_name}: {result.status.value}")

# Stop monitoring
monitor.stop()
```

#### Integrity Check Types
1. **Block Chain Integrity**: Verifies the blockchain structure is intact
2. **Database File Integrity**: Checks database file exists and is readable
3. **Backup Existence**: Ensures backups are available
4. **Storage Space**: Checks for sufficient disk space

#### IntegrityStatus Enum
```python
class IntegrityStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
```

### Background Monitoring
The monitor runs in a background thread, performing checks at the specified interval:

```python
# Use as context manager (automatically starts and stops)
with IntegrityMonitor(hash_chain=chain) as monitor:
    # Monitor is running in background
    time.sleep(10)  # Do other work
# Monitor automatically stops when exiting context
```

### Alert System
```python
def send_alert(message: str):
    # Send email, notification, etc.
    print(f"ALERT: {message}")

monitor = IntegrityMonitor(
    hash_chain=chain,
    alert_callback=send_alert
)
```

### Benefits
- **Continuous protection**: Background monitoring catches issues immediately
- **Proactive alerts**: Notifies user of potential problems
- **Multiple check types**: Comprehensive coverage of potential issues
- **Configurable**: Adjust intervals and thresholds as needed
- **Non-intrusive**: Runs in background without affecting performance

---

## 💾 5. Automated Backup System

### Purpose
Provides automatic data protection with periodic backups and disaster recovery capabilities.

### Implementation

#### Backup Creation
```python
# Manual backup
backup_info = monitor.create_backup(force=True)
print(f"Backup created: {backup_info.backup_path}")
print(f"Size: {backup_info.size_bytes} bytes")
print(f"Hash: {backup_info.hash_value}")

# Automatic backups (via IntegrityMonitor)
monitor = IntegrityMonitor(
    hash_chain=chain,
    backup_interval=3600,  # 1 hour
    backup_dir="data/blockchain/backups",
    max_backups=10
)
monitor.start()  # Will create backups automatically
```

#### BackupInfo Structure
```python
@dataclass
class BackupInfo:
    backup_path: str
    timestamp: float
    size_bytes: int
    hash_value: str  # SHA-256 hash of all backup files
    status: str = "completed"
```

#### Backup Rotation
- Only keeps the most recent `max_backups` backups
- Automatically deletes oldest backups when limit is exceeded
- Prevents disk space exhaustion

#### Disaster Recovery
```python
# Restore from backup
backup_info = monitor.get_latest_backup()
restore_ok = monitor.restore_from_backup(backup_info)
assert restore_ok == True

# Verify data is restored
hashes = chain.get_article_hashes("article-1")
assert hashes is not None
```

### What Gets Backed Up
1. **Database file** (`.db`)
2. **WAL file** (`.db-wal`) - SQLite Write-Ahead Log
3. **SHM file** (`.db-shm`) - SQLite Shared Memory
4. **Audit log** (`audit.log`)
5. **Configuration file** (`blockchain.yml`)

### WAL Checkpointing
Before creating a backup, the system performs a WAL checkpoint to ensure all data is flushed from the WAL file to the main database file:
```python
if self.hash_chain.connection:
    self.hash_chain.connection.execute("PRAGMA wal_checkpoint(FULL)")
```

### Benefits
- **Automatic**: No manual intervention required
- **Reliable**: WAL checkpointing ensures data consistency
- **Space-efficient**: Backup rotation prevents disk exhaustion
- **Complete**: Backs up all necessary files for full recovery
- **Verifiable**: Each backup has a SHA-256 hash for verification

---

## 🔧 Configuration

### EnhancedLocalHashChain Settings

```python
chain = EnhancedLocalHashChain(
    db_path="data/blockchain/enhanced_hash_chain.db",
    articles_per_block=100,
    time_per_block=86400,  # 24 hours
    worm_mode=True,        # Enable WORM mode
    multi_hash_enabled=True,  # Enable multi-hash
    audit_log_path="data/blockchain/audit.log"
)
```

### IntegrityMonitor Settings

```python
monitor = IntegrityMonitor(
    hash_chain=chain,
    check_interval=300,      # 5 minutes
    backup_interval=3600,    # 1 hour
    backup_dir="data/blockchain/backups",
    max_backups=10,
    alert_callback=None
)
```

---

## 📊 Performance Considerations

### Resource Usage
- **CPU**: Minimal impact from background monitoring
- **Memory**: Audit logger keeps entries in memory for fast access
- **Disk**: Backups consume disk space (configurable via max_backups)
- **I/O**: WAL checkpointing before backup may cause brief I/O spike

### Recommendations
- **check_interval**: 300 seconds (5 minutes) for most use cases
- **backup_interval**: 3600 seconds (1 hour) for most use cases
- **max_backups**: 10-20 depending on disk space
- **worm_mode**: Enable for production use
- **multi_hash_enabled**: Enable for maximum security

---

## 🧪 Testing

### Test Coverage
- **34 new tests** in `tests/blockchain/test_enhanced_features.py`
- **83 total blockchain tests** (49 original + 34 new)
- **100% test coverage** for all new features

### Running Tests
```bash
# Run all blockchain tests
python -m pytest tests/blockchain/ -v

# Run only enhanced feature tests
python -m pytest tests/blockchain/test_enhanced_features.py -v
```

### Test Categories
1. **CryptoUtils Tests**: Multi-hash algorithm functionality
2. **AuditLogger Tests**: Audit logging and integrity verification
3. **EnhancedLocalHashChain Tests**: WORM mode, multi-hash, audit integration
4. **IntegrityMonitor Tests**: Monitoring, checks, backups
5. **End-to-End Tests**: Complete workflows with all features

---

## 📚 Usage Examples

### Complete Single-User Setup

```python
from src.blockchain.core import EnhancedLocalHashChain
from src.blockchain.core.integrity_monitor import IntegrityMonitor
import hashlib

# 1. Create enhanced hash chain
chain = EnhancedLocalHashChain(
    db_path="data/blockchain/hash_chain.db",
    worm_mode=True,
    multi_hash_enabled=True,
    audit_log_path="data/blockchain/audit.log"
)

# 2. Create integrity monitor
monitor = IntegrityMonitor(
    hash_chain=chain,
    check_interval=300,
    backup_interval=3600,
    backup_dir="data/blockchain/backups",
    max_backups=10
)

# 3. Start monitoring
monitor.start()

# 4. Add articles
content = "Important news article"
metadata = {"title": "Breaking News", "author": "John Doe"}
source = "https://example.com/news/123"

content_hash = hashlib.sha256(content.encode()).hexdigest()
metadata_hash = hashlib.sha256(str(metadata).encode()).hexdigest()
source_hash = hashlib.sha256(source.encode()).hexdigest()

chain.add_article("article-1", content_hash, metadata_hash, source_hash)

# 5. Verify article
hashes = chain.get_article_hashes("article-1")
assert hashes is not None

# 6. Check multi-hash
multi_hash = chain.get_multi_hash("article-1")
assert multi_hash is not None

# 7. Verify integrity
assert chain.verify_block_chain_integrity() == True
assert chain.audit_logger.verify_integrity() == True

# 8. Check monitor status
status = monitor.get_overall_status()
assert status == IntegrityStatus.HEALTHY

# 9. Cleanup (when done)
monitor.stop()
chain.close()
```

### Disaster Recovery Example

```python
from src.blockchain.core import EnhancedLocalHashChain
from src.blockchain.core.integrity_monitor import IntegrityMonitor

# After data loss...
chain = EnhancedLocalHashChain(
    db_path="data/blockchain/hash_chain.db",
    worm_mode=True,
    multi_hash_enabled=True,
    audit_log_path="data/blockchain/audit.log"
)

monitor = IntegrityMonitor(
    hash_chain=chain,
    backup_dir="data/blockchain/backups"
)

# Get latest backup
backup_info = monitor.get_latest_backup()

# Restore from backup
restore_ok = monitor.restore_from_backup(backup_info)

# Verify restoration
assert chain.verify_block_chain_integrity() == True
```

---

## 🔒 Security Considerations

### Threat Model
These enhanced features protect against:
- **Accidental data modification**: WORM mode prevents changes
- **Malicious tampering**: Audit logging and integrity checks detect modifications
- **Data loss**: Automated backups provide recovery capability
- **Cryptographic weaknesses**: Multi-hash provides redundancy

### Limitations
- **Single-user only**: No consensus mechanism for multi-user scenarios
- **Local storage**: All data stored locally (no cloud backup by default)
- **No encryption**: Data is not encrypted at rest (consider adding filesystem encryption)
- **SQLite limitations**: Subject to SQLite's limitations (concurrency, etc.)

### Recommendations
1. **Enable WORM mode** for production use
2. **Enable multi-hash** for maximum security
3. **Configure regular backups** with appropriate intervals
4. **Monitor integrity status** and investigate warnings
5. **Store backups off-site** for disaster recovery
6. **Use filesystem encryption** for sensitive data
7. **Regularly verify backups** can be restored

---

## 📝 Migration Guide

### From LocalHashChain to EnhancedLocalHashChain

```python
# Before
from src.blockchain.core import LocalHashChain
chain = LocalHashChain(db_path="data/blockchain/hash_chain.db")

# After
from src.blockchain.core import EnhancedLocalHashChain
chain = EnhancedLocalHashChain(
    db_path="data/blockchain/hash_chain.db",
    worm_mode=True,
    multi_hash_enabled=True,
    audit_log_path="data/blockchain/audit.log"
)
```

### Adding Integrity Monitoring

```python
# Before
# No monitoring

# After
from src.blockchain.core.integrity_monitor import IntegrityMonitor

monitor = IntegrityMonitor(
    hash_chain=chain,
    check_interval=300,
    backup_interval=3600,
    backup_dir="data/blockchain/backups"
)
monitor.start()
```

---

## 🎓 Best Practices

1. **Always enable WORM mode** in production
2. **Enable multi-hash** for cryptographic redundancy
3. **Configure appropriate intervals** based on your use case
4. **Monitor the monitor** - check that monitoring is running
5. **Test backups regularly** - ensure they can be restored
6. **Store backups securely** - consider encrypted off-site storage
7. **Review audit logs** periodically for suspicious activity
8. **Set up alerts** for critical issues

---

## 📞 Support

For issues or questions related to these enhanced features:
- Check the test suite in `tests/blockchain/test_enhanced_features.py`
- Review the implementation in `src/blockchain/core/`
- Consult the main documentation in `docs/`

---

## 📄 License

All code and documentation is licensed under the GNU General Public License version 3 (GPLv3). See the LICENSE file for details.

---

*Last updated: May 2026*
*Version: 1.0*
