# Blockchain Verification Architecture

**Open Omniscience - Per-Article Blockchain Verification System**

---

## 📖 Overview

The Open Omniscience blockchain verification system provides **cryptographic proof of data authenticity and integrity** for all ingested content. This document describes the architecture, components, and design decisions behind the system.

### 🎯 Purpose

The blockchain verification system enables:

1. **Legal Admissibility**: Cryptographic proof that data has not been tampered with
2. **Decentralized Verification**: Third parties can verify article authenticity without trusting the central system
3. **Data Integrity**: Detection of any unauthorized modifications to ingested content
4. **Audit Trail**: Complete chain of custody for all articles

### 🔗 Key Concepts

| Concept | Description |
|---------|-------------|
| **Article Hashes** | Three SHA-256 hashes per article: content, metadata, source |
| **Local Hash Chain** | SQLite database storing article hashes and block information |
| **Block** | Group of articles (default: 100 articles or 24 hours) |
| **Merkle Root** | Cryptographic hash representing all articles in a block |
| **Merkle Proof** | Cryptographic proof that an article is included in a block |
| **Blockchain Anchoring** | Storing block Merkle roots on public blockchains |

---

## 🏗️ System Architecture

### 📊 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OPEN OMNISCIENCE SYSTEM                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │
│  │   Pillar 1:     │    │   Pillar 2:     │    │   Pillar 3:     │          │
│  │   Ingestion     │    │   Processing    │    │   Analytics     │          │
│  │                 │    │                 │    │                 │          │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘          │
│           │                     │                     │                   │
│           └─────────────────────┼─────────────────────┘                   │
│                             │                                         │
│                             ▼                                         │
│                  ┌──────────────────────┐                              │
│                  │   BLOCKCHAIN MODULE  │                              │
│                  │                      │                              │
│                  │  ┌────────────────┐  │                              │
│                  │  │ Local Hash     │  │                              │
│                  │  │ Chain (SQLite) │  │                              │
│                  │  └────────┬───────┘  │                              │
│                  │           │          │                              │
│                  │  ┌────────▼───────┐  │                              │
│                  │  │  Blockchain    │  │                              │
│                  │  │  Providers     │  │                              │
│                  │  │                │  │                              │
│                  │  │ - Local        │  │                              │
│                  │  │ - Ethereum     │  │                              │
│                  │  │ - IPFS         │  │                              │
│                  │  │ - Arweave      │  │                              │
│                  │  └────────────────┘  │                              │
│                  └──────────────────────┘                              │
│                            │                                         │
│                            ▼                                         │
│                  ┌──────────────────────┐                              │
│                  │   Pillar 4: Legal    │                              │
│                  │   Admissibility      │                              │
│                  └──────────────────────┘                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 🔄 Data Flow

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Article │────▶│ Compute     │────▶│ Store in    │────▶│ Create      │
│ Content │     │ 3 Hashes    │     │ Local Hash  │     │ Blocks      │
└─────────┘     └──────────────┘     │ Chain       │     └──────────────┘
                                          └──────┬───────┘
                                               │
                    ┌──────────────────────┬──────────────────────┐
                    │                          │                      │
                    ▼                          ▼                      ▼
            ┌──────────────┐          ┌──────────────┐      ┌──────────────┐
            │ Verify       │          │ Generate     │      │ (Optional)   │
            │ Article      │          │ Merkle Proof │      │ Anchor to    │
            │ (Local)      │          │              │      │ Public       │
            └──────────────┘          └──────────────┘      │ Blockchain   │
                                                        └──────────────┘
```

---

## 📦 Component Details

### 1. Local Hash Chain

**File**: `src/blockchain/core/hash_chain.py`

The local hash chain is the **core component** that stores all article hashes and enables per-article verification.

#### 🗃️ Database Schema

```sql
-- Blocks table: Stores block headers
CREATE TABLE blocks (
    block_height INTEGER PRIMARY KEY,
    previous_hash TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    article_count INTEGER NOT NULL,
    block_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

-- Block-articles mapping: Maps articles to blocks
CREATE TABLE block_articles (
    block_height INTEGER NOT NULL,
    article_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (block_height, article_id),
    FOREIGN KEY (block_height) REFERENCES blocks(block_height) ON DELETE CASCADE
);

-- Article hashes: Stores the 3 hashes for each article
CREATE TABLE article_hashes (
    article_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    metadata_hash TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    block_height INTEGER,
    position INTEGER,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (block_height) REFERENCES blocks(block_height) ON DELETE SET NULL
);
```

#### 🏗️ Classes

##### LocalBlock

Represents a block in the hash chain:

```python
@dataclass
class LocalBlock:
    block_height: int          # Block number (0 = genesis)
    previous_hash: str        # Hash of previous block
    merkle_root: str          # Merkle root of all articles
    timestamp: int            # Unix timestamp
    article_count: int        # Number of articles
    articles: List[str]       # List of article IDs
    block_hash: str           # Computed block hash
```

##### LocalHashChain

Manages the SQLite database and provides:

- `add_article(article_id, content_hash, metadata_hash, source_hash)`
- `get_article_hashes(article_id)`
- `get_article_block(article_id)`
- `get_merkle_proof(article_id)`
- `verify_article_with_proof(article_id, content_hash, metadata_hash, source_hash, merkle_proof, merkle_root)`
- `verify_block_chain_integrity()`

#### 🔢 Block Creation Rules

A new block is created when:

1. **Article Count**: Current block reaches `articles_per_block` (default: 100)
2. **Time Elapsed**: Current block is older than `time_per_block` (default: 24 hours)

#### 🌲 Merkle Tree

Each block contains a **Merkle tree** of all article content hashes:

```
        Merkle Root
           /    \
      Hash 0-1  Hash 2-3
       /  \      /  \
   Hash0 Hash1 Hash2 Hash3
   (Article content hashes)
```

The Merkle root provides a **single hash** that represents all articles in the block.

### 2. Anchor Service

**File**: `src/blockchain/core/anchor_service.py`

The anchor service manages:

- Per-article verification
- Blockchain anchoring (optional)
- Merkle proof generation

#### 🎯 Main Methods

##### add_article()

Adds an article to the local hash chain:

```python
def add_article(self, article_id, content_hash, metadata_hash, source_hash):
    # Adds article to current block (or creates new block)
    # Returns article info with block assignment
```

##### verify_article()

Verifies a single article:

```python
def verify_article(self, article_id, 
                  expected_content_hash=None,
                  expected_metadata_hash=None,
                  expected_source_hash=None):
    # Returns VerificationResult with:
    # - verified: bool
    # - local_verification: dict
    # - blockchain_verifications: dict
    # - merkle_proof: list
    # - block_height: int
    # - position: int
    # - warnings: list
```

##### get_article_verification_data()

Returns all data needed for third-party verification:

```python
def get_article_verification_data(self, article_id):
    # Returns dict with:
    # - article_id
    # - content_hash, metadata_hash, source_hash
    # - block_height, position, timestamp
    # - merkle_proof
    # - merkle_root
    # - block_hash, previous_block_hash
```

##### anchor_current_block()

Anchors the current block's Merkle root to configured blockchains:

```python
def anchor_current_block(self):
    # Returns dict with anchoring results for each provider
```

### 3. Blockchain Providers

**Directory**: `src/blockchain/providers/`

Providers implement the `BaseBlockchainProvider` interface:

```python
class BaseBlockchainProvider(ABC):
    @abstractmethod
    def anchor_hash(self, merkle_root: str, metadata: dict) -> str:
        """Anchor a Merkle root to the blockchain."""
        pass
    
    @abstractmethod
    def verify_anchor(self, merkle_root: str, block_height: int = None) -> bool:
        """Verify that a Merkle root was anchored."""
        pass
    
    @abstractmethod
    def get_anchor_data(self, transaction_hash: str) -> dict:
        """Retrieve anchored data by transaction hash."""
        pass
    
    @abstractmethod
    def get_all_anchors(self) -> list:
        """Get all anchors stored by this provider."""
        pass
```

#### 📚 Available Providers

| Provider | Description | Requirements | Status |
|----------|-------------|--------------|--------|
| **Local** | SQLite-based offline anchoring | None | ✅ Complete |
| **Ethereum** | Smart contract anchoring | web3.py, Ethereum node | ✅ Complete |
| **IPFS** | Decentralized storage | ipfshttpclient, IPFS node | ✅ Complete |
| **Arweave** | Permanent storage | arweave-python, wallet | ✅ Complete |

##### Local Provider

Stores anchors in a SQLite database:

```python
class LocalProvider(BaseBlockchainProvider):
    def anchor_hash(self, merkle_root, metadata):
        # Stores anchor in local SQLite database
        # Returns transaction hash (SHA-256 of anchor data)
        
    def verify_anchor(self, merkle_root, block_height=None):
        # Checks if Merkle root exists in local database
```

##### Ethereum Provider

Anchors to Ethereum smart contract:

```python
class EthereumProvider(BaseBlockchainProvider):
    def __init__(self, contract_address, rpc_url, private_key):
        # Connects to Ethereum node
        
    def anchor_hash(self, merkle_root, metadata):
        # Submits transaction to smart contract
        # Returns transaction hash
```

Smart Contract: `contracts/OpenOmniscienceAnchor.sol`

##### IPFS Provider

Stores anchors on IPFS:

```python
class IPFSProvider(BaseBlockchainProvider):
    def __init__(self, host, port, use_https):
        # Connects to IPFS node
        
    def anchor_hash(self, merkle_root, metadata):
        # Creates JSON file with anchor data
        # Adds to IPFS
        # Returns CID (Content Identifier)
```

##### Arweave Provider

Stores anchors on Arweave:

```python
class ArweaveProvider(BaseBlockchainProvider):
    def __init__(self, wallet_path, wallet_key, arweave_url):
        # Loads wallet and connects to Arweave
        
    def anchor_hash(self, merkle_root, metadata):
        # Creates and submits transaction
        # Returns transaction ID
```

### 4. API Routes

**File**: `src/api/routes/blockchain.py`

FastAPI endpoints for blockchain verification:

| Method | Endpoint | Description | Response |
|--------|----------|-------------|----------|
| GET | `/api/blockchain/status` | Service status | Status dict |
| GET | `/api/blockchain/verify` | Verify article | VerificationResult |
| POST | `/api/blockchain/verify` | Verify with POST | VerificationResult |
| GET | `/api/blockchain/articles/{article_id}/proof` | Get Merkle proof | Proof dict |
| GET | `/api/blockchain/articles/{article_id}/hashes` | Get hashes | Hashes dict |
| GET | `/api/blockchain/blocks` | List blocks | List[Block] |
| GET | `/api/blockchain/anchors` | List anchors | List[Anchor] |
| POST | `/api/blockchain/anchor-current-block` | Anchor block | Result dict |
| GET | `/api/blockchain/chain-integrity` | Verify chain | Integrity result |

### 5. Configuration

**File**: `configs/blockchain.yml`

```yaml
blockchain:
  enabled: true
  local_chain:
    enabled: true
    db_path: "data/blockchain/local_hash_chain.db"
    articles_per_block: 100
    time_per_block: 86400
  anchoring:
    enabled: true
    interval: 86400
    providers:
      - local
      # - ethereum
      # - ipfs
      # - arweave
    ethereum:
      contract_address: "0x..."
      rpc_url: "http://localhost:8545"
      gas_limit: 200000
      gas_price: 20000000000
    ipfs:
      host: "localhost"
      port: 5001
      use_https: false
    arweave:
      wallet_path: "~/.arweave/wallet.json"
      arweave_url: "https://arweave.net"
```

---

## 🔐 Cryptographic Details

### 🔢 Hashing Algorithm

All hashes use **SHA-256**:

```python
import hashlib

def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

### 📝 Article Hashes

Each article has **three hashes**:

1. **content_hash**: SHA-256 of the article content (raw bytes)
2. **metadata_hash**: SHA-256 of the article metadata (JSON string)
3. **source_hash**: SHA-256 of `source_url + timestamp`

### 🌲 Merkle Tree Construction

The Merkle tree is built from article content hashes:

```python
from src.crypto.merkle_tree import MerkleTree, compute_merkle_root

# For a block with articles
article_hashes = [article1_content_hash, article2_content_hash, ...]
merkle_root = compute_merkle_root(article_hashes)

# For verification
tree = MerkleTree(article_hashes)
proof = tree.get_proof(article_position)
is_valid = tree.verify_proof(article_hash, proof, merkle_root)
```

### 🔗 Block Hash

Each block has a hash computed from its header:

```python
@dataclass
class LocalBlock:
    block_height: int
    previous_hash: str
    merkle_root: str
    timestamp: int
    article_count: int
    articles: List[str]
    block_hash: str = field(init=False)
    
    def __post_init__(self):
        data = {
            'block_height': self.block_height,
            'previous_hash': self.previous_hash,
            'merkle_root': self.merkle_root,
            'timestamp': self.timestamp,
            'article_count': self.article_count,
            'articles': sorted(self.articles)
        }
        self.block_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
```

### 🔄 Chain Integrity

The block chain is verified by checking that each block's `previous_hash` matches the previous block's `block_hash`:

```python
def verify_block_chain_integrity(self):
    for height in range(1, max_height + 1):
        current_block = self.get_block(height)
        previous_block = self.get_block(height - 1)
        
        if current_block.previous_hash != previous_block.block_hash:
            return False
    
    return True
```

---

## 📊 Per-Article Verification Process

### 🔍 Verification Steps

1. **Retrieve Article Hashes**
   ```python
   article_info = hash_chain.get_article_hashes(article_id)
   # Returns: content_hash, metadata_hash, source_hash, block_height, position
   ```

2. **Get Block Information**
   ```python
   block = hash_chain.get_block(article_info['block_height'])
   # Returns: block with merkle_root
   ```

3. **Generate Merkle Proof**
   ```python
   proof_data = hash_chain.get_merkle_proof(article_id)
   # Returns: merkle_proof (list of sibling hashes), merkle_root
   ```

4. **Verify Merkle Proof**
   ```python
   is_valid = hash_chain.verify_article_with_proof(
       article_id,
       content_hash,
       metadata_hash,
       source_hash,
       proof_data['merkle_proof'],
       proof_data['merkle_root']
   )
   ```

5. **Verify Block Chain Integrity**
   ```python
   chain_intact = hash_chain.verify_block_chain_integrity()
   ```

6. **(Optional) Verify Blockchain Anchoring**
   ```python
   for provider in providers:
       is_anchored = provider.verify_anchor(block.merkle_root, block.block_height)
   ```

### 📋 Verification Result

```python
@dataclass
class VerificationResult:
    article_id: str
    verified: bool
    local_verification: Dict[str, bool]  # content_hash_match, metadata_hash_match, etc.
    blockchain_verifications: Dict[str, Dict[str, Any]]  # Per-provider results
    merkle_proof: Optional[List[Dict[str, Any]]]
    block_height: Optional[int]
    position: Optional[int]
    warnings: List[str]
```

---

## 🎯 Design Decisions

### ❓ Why Per-Article Verification?

**Problem**: Storing each article on a public blockchain is expensive and impractical.

**Solution**: Use Merkle trees to enable per-article verification while only storing block Merkle roots on-chain.

**Benefit**: 
- Individual articles can be verified
- Blockchain costs are minimized (per-batch, not per-article)
- Offline verification is possible via local hash chain

### ❓ Why Three Hashes Per Article?

| Hash | Purpose | What It Protects |
|------|---------|------------------|
| content_hash | Article content | Content integrity |
| metadata_hash | Article metadata | Metadata integrity |
| source_hash | Source URL + timestamp | Source authenticity |

**Benefit**: Comprehensive protection against:
- Content tampering
- Metadata modification
- Source spoofing

### ❓ Why SQLite for Local Hash Chain?

**Alternatives Considered**:
- LevelDB: More complex, less portable
- RocksDB: Requires C++ dependencies
- JSON files: No indexing, slow queries
- PostgreSQL: Overkill for this use case

**SQLite Chosen Because**:
- ✅ Zero configuration
- ✅ Single file (portable)
- ✅ ACID compliant
- ✅ Built into Python
- ✅ Fast for read-heavy workloads

### ❓ Why Multiple Blockchain Providers?

**Benefits**:
- **Flexibility**: Users can choose their preferred blockchain
- **Redundancy**: Anchor to multiple blockchains for resilience
- **Cost Optimization**: Use cheaper options (Arweave) for archival
- **Decentralization**: Different trust assumptions for different providers

### ❓ Why Not Store Articles Directly on Blockchain?

**Reasons**:
1. **Cost**: Storing even small articles on Ethereum costs significant gas fees
2. **Scalability**: Blockchains have limited throughput
3. **Privacy**: Article content may contain sensitive information
4. **Practicality**: Most blockchains have size limits per transaction

**Solution**: Store only cryptographic hashes on-chain, keep articles in the local database.

---

## 🔒 Security Considerations

### ✅ Security Features

1. **Cryptographic Hashing**: All hashes use SHA-256 (NIST-approved)
2. **Merkle Trees**: Tamper-evident data structure
3. **Chain Linking**: Each block references the previous block
4. **No Content on Chain**: Only hashes are stored on public blockchains
5. **FOSS Components**: All code is open source and auditable

### ⚠️ Threat Model

| Threat | Mitigation |
|--------|------------|
| Local database tampering | Merkle proofs detect tampering |
| Blockchain provider compromise | Multiple providers can be used |
| Hash collisions | SHA-256 is collision-resistant |
| Replay attacks | Timestamps and block heights prevent replay |
| Denial of Service | Local verification doesn't require network |

### 🛡️ Privacy Protection

**What's Stored Where**:

| Data | Local Hash Chain | Public Blockchain |
|------|------------------|-------------------|
| Article content | ❌ No | ❌ No |
| Article metadata | ❌ No | ❌ No |
| Source URL | ❌ No | ❌ No |
| content_hash | ✅ Yes | ❌ No |
| metadata_hash | ✅ Yes | ❌ No |
| source_hash | ✅ Yes | ❌ No |
| Merkle root | ✅ Yes | ✅ Yes |
| Block hash | ✅ Yes | ❌ No |

**Privacy Guarantee**: No article content, metadata, or source information is ever stored on public blockchains. Only cryptographic hashes are stored.

---

## 📈 Performance Considerations

### 📊 Benchmarks (Estimated)

| Operation | Time Complexity | Notes |
|-----------|-----------------|-------|
| Add article | O(1) | Amortized, occasional block creation |
| Verify article | O(log n) | Merkle proof verification |
| Get Merkle proof | O(log n) | Tree traversal |
| Verify chain integrity | O(n) | Linear in number of blocks |
| Anchor to Ethereum | ~15 sec | Depends on gas price |
| Anchor to IPFS | ~1 sec | Depends on node performance |
| Anchor to Arweave | ~10 sec | Depends on network |

### 💾 Storage Requirements

| Component | Size per Article | Notes |
|-----------|------------------|-------|
| content_hash | 32 bytes | SHA-256 hash |
| metadata_hash | 32 bytes | SHA-256 hash |
| source_hash | 32 bytes | SHA-256 hash |
| article_id | ~20 bytes | Variable length |
| Block overhead | ~200 bytes | Per block, not per article |
| **Total per article** | **~120 bytes** | In local hash chain |

For 1 million articles: ~120 MB in SQLite database

### 🔄 Scalability

- **Articles per block**: Configurable (default: 100)
- **Blocks**: Unlimited (only limited by storage)
- **Merkle tree depth**: log₂(articles_per_block) ≈ 7 levels for 100 articles
- **Proof size**: ~32 bytes × tree_depth ≈ 224 bytes per proof

---

## 🚀 Deployment

### 📋 Prerequisites

#### Local Provider (Required)
- Python 3.8+
- SQLite (built into Python)

#### Ethereum Provider (Optional)
- `pip install web3`
- Ethereum node (local or remote)
- ETH for gas fees
- Smart contract deployed

#### IPFS Provider (Optional)
- `pip install ipfshttpclient`
- IPFS node running

#### Arweave Provider (Optional)
- `pip install arweave-python`
- Arweave wallet
- AR for transaction fees

### 🛠️ Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure blockchain**:
   ```bash
   # Edit configs/blockchain.yml
   vi configs/blockchain.yml
   ```

3. **Deploy smart contract (Ethereum only)**:
   ```bash
   # Compile and deploy OpenOmniscienceAnchor.sol
   # Update contract_address in configs/blockchain.yml
   ```

4. **Start Open Omniscience**:
   ```bash
   python -m src.api.main
   ```

### 🔌 Integration with Existing Pipeline

The blockchain module is **automatically integrated** with the main pipeline:

```python
# In src/main_pipeline.py

def _add_to_blockchain(self, ingested_data: IngestedData) -> None:
    # Automatically called during ingestion
    # Computes 3 hashes and adds to blockchain
    pass
```

No additional configuration is needed for basic usage.

---

## 📚 References

- [Merkle Tree Wikipedia](https://en.wikipedia.org/wiki/Merkle_tree)
- [SHA-256 Wikipedia](https://en.wikipedia.org/wiki/SHA-2)
- [Ethereum Smart Contracts](https://ethereum.org/en/developers/docs/smart-contracts/)
- [IPFS Documentation](https://docs.ipfs.tech/)
- [Arweave Documentation](https://docs.arweave.org/)

---

## 📝 Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-05-27 | Initial implementation |

---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📜 License

This documentation and the blockchain verification system are licensed under **GNU GPLv3**. See [LICENSE](LICENSE) for details.
