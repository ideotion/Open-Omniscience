# Blockchain API Reference

**Open Omniscience - Per-Article Blockchain Verification API**

---

## 📖 Overview

The Open Omniscience Blockchain API provides REST endpoints for:

- Per-article verification
- Merkle proof generation
- Blockchain anchoring
- Chain integrity verification

**Base URL**: `http://localhost:8000/api/blockchain`

---

## 📡 Authentication

**No authentication required** for blockchain API endpoints. The blockchain module is designed for public verification.

---

## 🔌 Endpoints

### 📊 Status

#### Get Blockchain Service Status

```
GET /api/blockchain/status
```

**Description**: Get the current status and configuration of the blockchain service.

**Response**: `200 OK`

```json
{
  "status": "running",
  "enabled": true,
  "local_chain": {
    "enabled": true,
    "db_path": "data/blockchain/local_hash_chain.db",
    "articles_per_block": 100,
    "time_per_block": 86400
  },
  "anchoring": {
    "enabled": true,
    "providers": ["local"]
  },
  "statistics": {
    "total_blocks": 5,
    "total_articles": 427,
    "latest_block_height": 5
  }
}
```

---

### 🔍 Article Verification

#### Verify Article (GET)

```
GET /api/blockchain/verify?article_id={article_id}[&expected_content_hash={hash}][&expected_metadata_hash={hash}][&expected_source_hash={hash}]
```

**Description**: Verify a single article. Can optionally provide expected hashes for comparison.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | string | Yes | The article identifier to verify |
| `expected_content_hash` | string | No | Expected content hash for verification |
| `expected_metadata_hash` | string | No | Expected metadata hash for verification |
| `expected_source_hash` | string | No | Expected source hash for verification |

**Response**: `200 OK`

```json
{
  "article_id": "article_123",
  "verified": true,
  "local_verification": {
    "article_exists": true,
    "content_hash_match": true,
    "metadata_hash_match": true,
    "source_hash_match": true,
    "merkle_proof_valid": true,
    "block_chain_intact": true
  },
  "blockchain_verifications": {
    "local": {
      "verified": true,
      "provider": "local"
    }
  },
  "merkle_proof": [
    {
      "hash": "a1b2c3...",
      "is_right_sibling": true
    },
    {
      "hash": "d4e5f6...",
      "is_right_sibling": false
    }
  ],
  "block_height": 5,
  "position": 42,
  "warnings": []
}
```

**Response**: `404 Not Found` (if article not found)

```json
{
  "detail": "Article article_999 not found in hash chain"
}
```

#### Verify Article (POST)

```
POST /api/blockchain/verify
Content-Type: application/json
```

**Description**: Verify a single article using POST request body.

**Request Body**:

```json
{
  "article_id": "article_123",
  "expected_content_hash": "a1b2c3...",
  "expected_metadata_hash": "d4e5f6...",
  "expected_source_hash": "g7h8i9..."
}
```

**Response**: `200 OK` (same as GET)

---

### 📜 Article Data

#### Get Article Hashes

```
GET /api/blockchain/articles/{article_id}/hashes
```

**Description**: Get the three hashes for a specific article.

**Path Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | string | Yes | The article identifier |

**Response**: `200 OK`

```json
{
  "article_id": "article_123",
  "content_hash": "a1b2c3d4e5f6...",
  "metadata_hash": "g7h8i9j0k1l2...",
  "source_hash": "m3n4o5p6q7r8...",
  "block_height": 5,
  "position": 42,
  "timestamp": 1716800000
}
```

**Response**: `404 Not Found`

```json
{
  "detail": "Article article_999 not found"
}
```

#### Get Article Merkle Proof

```
GET /api/blockchain/articles/{article_id}/proof
```

**Description**: Get the Merkle proof for an article. This provides all data needed for third-party verification.

**Path Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | string | Yes | The article identifier |

**Response**: `200 OK`

```json
{
  "article_id": "article_123",
  "content_hash": "a1b2c3d4e5f6...",
  "metadata_hash": "g7h8i9j0k1l2...",
  "source_hash": "m3n4o5p6q7r8...",
  "block_height": 5,
  "position": 42,
  "timestamp": 1716800000,
  "merkle_proof": [
    {
      "hash": "sibling1_hash...",
      "is_right_sibling": true
    },
    {
      "hash": "sibling2_hash...",
      "is_right_sibling": false
    }
  ],
  "merkle_root": "block_5_merkle_root...",
  "block_hash": "block_5_hash...",
  "previous_block_hash": "block_4_hash..."
}
```

**Use Case**: This endpoint provides all data needed for a third party to independently verify the article using the Merkle proof and block hashes.

**Response**: `404 Not Found`

```json
{
  "detail": "Article article_999 not found"
}
```

#### Verify Article with Proof (POST)

```
POST /api/blockchain/articles/{article_id}/verify-with-proof
Content-Type: application/json
```

**Description**: Verify an article using a provided Merkle proof. This allows decentralized verification without accessing the local database.

**Path Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | string | Yes | The article identifier |

**Request Body**:

```json
{
  "content_hash": "a1b2c3d4e5f6...",
  "metadata_hash": "g7h8i9j0k1l2...",
  "source_hash": "m3n4o5p6q7r8...",
  "merkle_proof": [
    {
      "hash": "sibling1_hash...",
      "is_right_sibling": true
    },
    {
      "hash": "sibling2_hash...",
      "is_right_sibling": false
    }
  ],
  "merkle_root": "block_5_merkle_root..."
}
```

**Response**: `200 OK`

```json
{
  "verified": true
}
```

**Response**: `400 Bad Request`

```json
{
  "detail": "Missing required fields in request body"
}
```

---

### 📦 Blocks

#### Get All Blocks

```
GET /api/blockchain/blocks?limit={limit}
```

**Description**: Get information about all blocks in the chain.

**Query Parameters**:

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `limit` | integer | No | Maximum number of blocks to return | None (all) |

**Response**: `200 OK`

```json
[
  {
    "block_height": 0,
    "previous_hash": "0000...000",
    "merkle_root": "genesis_merkle_root...",
    "timestamp": 1716700000,
    "article_count": 0,
    "articles": [],
    "block_hash": "genesis_block_hash..."
  },
  {
    "block_height": 1,
    "previous_hash": "genesis_block_hash...",
    "merkle_root": "block_1_merkle_root...",
    "timestamp": 1716710000,
    "article_count": 100,
    "articles": ["article_1", "article_2", ...],
    "block_hash": "block_1_hash..."
  }
]
```

#### Get Specific Block

```
GET /api/blockchain/blocks?block_height={block_height}
```

**Description**: Get information about a specific block.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `block_height` | integer | Yes | The block height to retrieve |

**Response**: `200 OK`

```json
{
  "block_height": 5,
  "previous_hash": "block_4_hash...",
  "merkle_root": "block_5_merkle_root...",
  "timestamp": 1716800000,
  "article_count": 47,
  "articles": ["article_401", "article_402", ...],
  "block_hash": "block_5_hash..."
}
```

**Response**: `404 Not Found`

```json
{
  "detail": "Block 999 not found"
}
```

---

### ⚓ Anchors

#### Get All Anchors

```
GET /api/blockchain/anchors?block_height={block_height}&provider={provider}
```

**Description**: Get all blockchain anchors, optionally filtered by block height or provider.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `block_height` | integer | No | Filter by block height |
| `provider` | string | No | Filter by provider name (local, ethereum, ipfs, arweave) |

**Response**: `200 OK`

```json
[
  {
    "transaction_hash": "local_tx_123...",
    "merkle_root": "block_5_merkle_root...",
    "block_height": 5,
    "article_count": 100,
    "timestamp": 1716800000,
    "metadata": {
      "block_hash": "block_5_hash...",
      "previous_block_hash": "block_4_hash..."
    },
    "provider": "local"
  },
  {
    "transaction_hash": "0xabc123...",
    "merkle_root": "block_5_merkle_root...",
    "block_height": 5,
    "article_count": 100,
    "timestamp": 1716800001,
    "metadata_cid": "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco",
    "block_number": 12345678,
    "provider": "ethereum"
  }
]
```

---

### 🔗 Anchoring

#### Anchor Current Block

```
POST /api/blockchain/anchor-current-block
```

**Description**: Manually trigger anchoring of the current block's Merkle root to all configured blockchain providers.

**Response**: `200 OK`

```json
{
  "local": {
    "success": true,
    "transaction_hash": "local_tx_123...",
    "block_height": 5,
    "merkle_root": "block_5_merkle_root..."
  },
  "ethereum": {
    "success": false,
    "error": "Ethereum provider not initialized"
  }
}
```

**Response**: `400 Bad Request` (if anchoring is disabled)

```json
{
  "detail": "Anchoring is disabled"
}
```

---

### 🔄 Chain Integrity

#### Verify Chain Integrity

```
GET /api/blockchain/chain-integrity?max_height={max_height}
```

**Description**: Verify the integrity of the entire block chain by checking that each block's `previous_hash` matches the previous block's `block_hash`.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_height` | integer | No | Maximum block height to verify (None for all) |

**Response**: `200 OK`

```json
{
  "valid": true,
  "max_height_checked": 5
}
```

---

## 📝 Examples

### Example 1: Basic Article Verification

```bash
# Verify an article
curl "http://localhost:8000/api/blockchain/verify?article_id=article_123"

# Response
{
  "article_id": "article_123",
  "verified": true,
  "local_verification": {
    "article_exists": true,
    "content_hash_match": true,
    "metadata_hash_match": true,
    "source_hash_match": true,
    "merkle_proof_valid": true,
    "block_chain_intact": true
  },
  "block_height": 5,
  "position": 42
}
```

### Example 2: Get Merkle Proof for Third-Party Verification

```bash
# Get verification data
curl "http://localhost:8000/api/blockchain/articles/article_123/proof"

# Response (provide this to third party for verification)
{
  "article_id": "article_123",
  "content_hash": "a1b2c3...",
  "metadata_hash": "d4e5f6...",
  "source_hash": "g7h8i9...",
  "block_height": 5,
  "position": 42,
  "merkle_proof": [...],
  "merkle_root": "block_5_root...",
  "block_hash": "block_5_hash...",
  "previous_block_hash": "block_4_hash..."
}
```

### Example 3: Third-Party Verification

```bash
# Third party verifies using the proof data
curl -X POST "http://localhost:8000/api/blockchain/articles/article_123/verify-with-proof" \
  -H "Content-Type: application/json" \
  -d '{
    "content_hash": "a1b2c3...",
    "metadata_hash": "d4e5f6...",
    "source_hash": "g7h8i9...",
    "merkle_proof": [...],
    "merkle_root": "block_5_root..."
  }'

# Response
{
  "verified": true
}
```

### Example 4: Check Service Status

```bash
curl "http://localhost:8000/api/blockchain/status"

# Response
{
  "status": "running",
  "enabled": true,
  "statistics": {
    "total_blocks": 5,
    "total_articles": 427,
    "latest_block_height": 5
  }
}
```

### Example 5: List All Blocks

```bash
curl "http://localhost:8000/api/blockchain/blocks?limit=3"

# Response
[
  {
    "block_height": 0,
    "article_count": 0,
    "timestamp": 1716700000
  },
  {
    "block_height": 1,
    "article_count": 100,
    "timestamp": 1716710000
  },
  {
    "block_height": 2,
    "article_count": 100,
    "timestamp": 1716720000
  }
]
```

---

## 🚀 Integration Examples

### Python Example

```python
import requests
import hashlib
import json

# Configuration
BASE_URL = "http://localhost:8000/api/blockchain"

# Verify an article
def verify_article(article_id):
    response = requests.get(f"{BASE_URL}/verify", params={"article_id": article_id})
    return response.json()

# Get Merkle proof for third-party verification
def get_verification_data(article_id):
    response = requests.get(f"{BASE_URL}/articles/{article_id}/proof")
    return response.json()

# Verify using provided proof
def verify_with_proof(article_id, proof_data):
    response = requests.post(
        f"{BASE_URL}/articles/{article_id}/verify-with-proof",
        json=proof_data
    )
    return response.json()

# Example usage
article_id = "article_123"

# 1. Verify the article
result = verify_article(article_id)
print(f"Verified: {result['verified']}")

# 2. Get verification data for third-party verification
verification_data = get_verification_data(article_id)

# 3. Third party can verify using the proof
third_party_result = verify_with_proof(article_id, verification_data)
print(f"Third-party verification: {third_party_result['verified']}")
```

### JavaScript Example

```javascript
const BASE_URL = "http://localhost:8000/api/blockchain";

// Verify an article
async function verifyArticle(articleId) {
    const response = await fetch(`${BASE_URL}/verify?article_id=${articleId}`);
    return await response.json();
}

// Get Merkle proof
async function getProof(articleId) {
    const response = await fetch(`${BASE_URL}/articles/${articleId}/proof`);
    return await response.json();
}

// Example usage
(async () => {
    const articleId = "article_123";
    
    // Verify article
    const result = await verifyArticle(articleId);
    console.log(`Verified: ${result.verified}`);
    
    // Get proof for third-party verification
    const proof = await getProof(articleId);
    console.log(`Proof:`, proof);
})();
```

---

## 📊 Response Codes

| Code | Description | Example |
|------|-------------|---------|
| 200 | Success | Article verified, data retrieved |
| 400 | Bad Request | Missing parameters, invalid data |
| 404 | Not Found | Article/block not found |
| 500 | Internal Server Error | Database error, provider failure |

---

## 🔒 Security

- **No Authentication**: Blockchain verification is designed to be public
- **Read-Only**: Most endpoints are read-only (GET)
- **Write Operations**: Only `POST /api/blockchain/anchor-current-block` modifies data
- **Input Validation**: All inputs are validated
- **Error Handling**: Errors return appropriate HTTP status codes

---

## 📈 Rate Limiting

Currently, no rate limiting is implemented. For production use, consider:

- Adding rate limiting to prevent abuse
- Caching frequent queries
- Implementing API keys for write operations

---

## 🤝 Versioning

The blockchain API follows the same versioning as Open Omniscience. Currently:

- **API Version**: 1.0.0
- **Open Omniscience Version**: 0.03

---

## 🔐 Chain of Custody (CoC) Endpoints

The **Chain of Custody (CoC)** endpoints provide **legally admissible audit trails** for all actions performed on articles. These endpoints complement the blockchain verification system by adding **human-readable, tamper-evident logs** with **cryptographic proofs**.

**Base URL**: `http://localhost:8000/api/blockchain/coc`

### 📋 Get Chain of Custody Report

#### Get CoC Report for an Article

```
GET /api/blockchain/coc/{article_id}
```

**Description**: Retrieve the **complete Chain of Custody report** for an article, including all actions, timestamps, signatures, and cryptographic proofs.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `redact_actor_ids` | bool | No | `false` | Redact actor IDs in the report (for privacy) |
| `redact_metadata` | bool | No | `false` | Redact metadata in the report (for privacy) |

**Response**: `200 OK`

```json
{
  "report_id": "uuid",
  "generated_at": "2024-01-01T12:00:00+00:00",
  "generated_by": "Open-Omniscience CoC Logger",
  "article": {
    "id": "article_123",
    "hash": "abc123...",
    "metadata": {}
  },
  "chain_of_custody": [
    {
      "entry_id": "uuid",
      "article_id": "article_123",
      "article_hash": "abc123...",
      "action": "ingest",
      "timestamp": "2024-01-01T10:00:00+00:00",
      "tsa_timestamp": "2024-01-01T10:00:01+00:00",
      "actor_id": "journalist_1",
      "entry_hash": "def456...",
      "previous_entry_hash": null,
      "metadata": {"source": "leaked_document.pdf"}
    },
    {
      "entry_id": "uuid",
      "article_id": "article_123",
      "article_hash": "abc123...",
      "action": "verify",
      "timestamp": "2024-01-01T11:00:00+00:00",
      "tsa_timestamp": "2024-01-01T11:00:01+00:00",
      "actor_id": "editor_1",
      "entry_hash": "ghi789...",
      "previous_entry_hash": "def456...",
      "metadata": {}
    }
  ],
  "verification": {
    "is_verified": true,
    "errors": []
  }
}
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123?redact_actor_ids=true"
```

---

### ✅ Verify Chain of Custody

#### Verify CoC Integrity

```
GET /api/blockchain/coc/{article_id}/verify
```

**Description**: Verify the **integrity of the Chain of Custody** for an article. Checks hash chain, signatures, TSA tokens, and entry hashes.

**Response**: `200 OK`

```json
{
  "article_id": "article_123",
  "is_valid": true,
  "errors": []
}
```

**Error Response**: `200 OK` (but `is_valid: false`)

```json
{
  "article_id": "article_123",
  "is_valid": false,
  "errors": [
    "Entry uuid: Entry hash mismatch",
    "Entry uuid: Previous hash mismatch"
  ]
}
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/verify"
```

---

### 📥 Export CoC Report

#### Export as JSON

```
GET /api/blockchain/coc/{article_id}/export/json
```

**Description**: Export the **CoC report as JSON** (machine-readable format for automated processing).

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `redact_actor_ids` | bool | No | `false` | Redact actor IDs in the report |
| `redact_metadata` | bool | No | `false` | Redact metadata in the report |

**Response**: `200 OK` (JSON file download)

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/export/json?redact_actor_ids=true" \
  -o coc_report.json
```

---

### 📋 Get CoC Entries

#### Get All Entries for an Article

```
GET /api/blockchain/coc/{article_id}/entries
```

**Description**: Retrieve **all Chain of Custody entries** for an article, ordered by timestamp.

**Response**: `200 OK`

```json
[
  {
    "entry_id": "uuid",
    "article_id": "article_123",
    "article_hash": "abc123...",
    "action": "ingest",
    "timestamp": "2024-01-01T10:00:00+00:00",
    "tsa_timestamp": "2024-01-01T10:00:01+00:00",
    "actor_id": "journalist_1",
    "entry_hash": "def456...",
    "previous_entry_hash": null,
    "metadata": {"source": "leaked_document.pdf"}
  },
  {
    "entry_id": "uuid",
    "article_id": "article_123",
    "article_hash": "abc123...",
    "action": "verify",
    "timestamp": "2024-01-01T11:00:00+00:00",
    "tsa_timestamp": "2024-01-01T11:00:01+00:00",
    "actor_id": "editor_1",
    "entry_hash": "ghi789...",
    "previous_entry_hash": "def456...",
    "metadata": {}
  }
]
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/article_123/entries"
```

---

### 📊 List All Articles with CoC

#### Get All Article IDs

```
GET /api/blockchain/coc/articles
```

**Description**: Retrieve a **list of all article IDs** that have Chain of Custody entries.

**Response**: `200 OK`

```json
[
  "article_1",
  "article_2",
  "article_123"
]
```

**Example:**
```bash
curl "http://localhost:8000/api/blockchain/coc/articles"
```

---

### 📈 Get CoC Statistics

#### Get Database Statistics

```
GET /api/blockchain/coc/stats
```

**Description**: Retrieve **statistics** about the Chain of Custody database.

**Response**: `200 OK`

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

### ✍️ Log a CoC Action

#### Manually Log an Action

```
POST /api/blockchain/coc/{article_id}/log
```

**Description**: **Manually log a Chain of Custody action** for an article. Useful for custom workflows or external systems.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | str | Yes | Action to log (e.g., `modify`, `access`, `verify`) |
| `article_hash` | str | Yes | SHA-256 hash of the article content |
| `actor_id` | str | No | ID of the actor performing the action |

**Request Body (JSON):**
```json
{
  "metadata": {
    "key": "value",
    "reason": "corrected typo"
  }
}
```

**Response**: `200 OK`

```json
{
  "status": "success",
  "entry": {
    "entry_id": "uuid",
    "article_id": "article_123",
    "article_hash": "abc123...",
    "action": "modify",
    "timestamp": "2024-01-01T12:00:00+00:00",
    "entry_hash": "def456...",
    "actor_id": "user_1",
    "metadata": {"reason": "corrected typo"}
  }
}
```

**Error Response**: `400 Bad Request`

```json
{
  "detail": "Invalid action: invalid_action. Must be one of: ['ingest', 'modify', 'access', 'delete', 'verify', 'anchor', 'restore', 'export', 'redact', 'sign']"
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/api/blockchain/coc/article_123/log?action=modify&article_hash=abc123" \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"reason": "corrected typo"}}'
```

---

## 📊 CoC Action Types

The following **action types** are supported (via `CoCAction` enum):

| Action | Description | When to Use |
|--------|-------------|-------------|
| `ingest` | Article ingested into the system | Automatically logged by `main_pipeline.py` |
| `modify` | Article metadata or content updated | Log when editing an article |
| `access` | Article accessed (read/exported) | Log when viewing or exporting |
| `delete` | Article deleted (secure wipe) | Log when removing an article |
| `verify` | Article verified (hash check) | Log when manually verifying |
| `anchor` | Article anchored to blockchain | Automatically logged by `anchor_service.py` |
| `restore` | Article restored from backup | Log when recovering data |
| `export` | Article exported (e.g., to PDF/JSON) | Log when exporting |
| `redact` | Sensitive data redacted from article | Log when redacting PII |
| `sign` | Article signed (e.g., by journalist/editor) | Log when adding a signature |

---

## 📚 See Also

- [Blockchain Architecture Documentation](BLOCKCHAIN_ARCHITECTURE.md)
- [Blockchain Setup Guide](BLOCKCHAIN_SETUP.md)
- [Chain of Custody Detailed Guide](CHAIN_OF_CUSTODY.md)
- [Main API Documentation](../API_DOCUMENTATION.md)

---

## 📜 License

This API and documentation are licensed under **GNU GPLv3**. See [LICENSE](../../LICENSE) for details.
