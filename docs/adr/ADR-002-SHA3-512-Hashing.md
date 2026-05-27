# ADR-002: Use SHA-3-512 for Hashing in Chain of Custody

## Status
✅ **Accepted**

## Context

The Chain of Custody (CoC) system in Open-Omniscience requires **cryptographically secure hashing** to ensure:
1. **Integrity**: CoC entries cannot be tampered with.
2. **Non-repudiation**: Actors cannot deny performing actions.
3. **Long-term trust**: Hashes must remain secure for **50+ years** (legal requirements).

### Quantum Computing Threat to Hashing

- **Grover's Algorithm (1996)**: Reduces brute-force resistance of hash functions by **√2^N**.
  - **SHA-256**: 2^256 → **2^128** (still secure for now).
  - **SHA-3-512**: 2^512 → **2^256** (future-proof).
- **Impact on Open-Omniscience**:
  - Current **SHA-256 hashes** are **safe for now**, but may need upgrading in the future.
  - **SHA-3-512** provides **2^256 security against Grover's algorithm** (NIST-recommended for long-term use).

### NIST SHA-3 Standardization

NIST standardized **SHA-3 (Keccak)** in **FIPS 202 (2015)** as the next-generation hash function.

| Algorithm | Output Size | Security (Classical) | Security (Quantum) | Standard |
|-----------|-------------|---------------------|-------------------|----------|
| SHA-256 | 256 bits | 2^256 | **2^128** (Grover) | FIPS 180-4 |
| SHA-3-256 | 256 bits | 2^256 | **2^128** (Grover) | FIPS 202 |
| SHA-3-512 | **512 bits** | **2^512** | **2^256** (Grover) | FIPS 202 |

## Decision

**Use SHA-3-512 for all hashing in CoC entries.**

### Implementation Details

1. **HashAlgorithm Enum** (`src/blockchain/core/pqc.py`):
   - Supports **SHA-256, SHA-3-256, SHA-3-512, BLAKE2B, BLAKE2S**.
   - Default: **SHA-3-512** for new CoC entries.

2. **CoCEntry Updates** (`src/blockchain/core/coc.py`):
   - Added `hash_algorithm` field (default: `HashAlgorithm.SHA3_512`).
   - Updated `_compute_hash()` to use the configured algorithm.

3. **Backward Compatibility**:
   - Existing CoC entries with SHA-256 remain **valid and verifiable**.
   - New entries use **SHA-3-512 by default**.

### Why SHA-3-512?

| Algorithm | Pros | Cons |
|-----------|------|------|
| **SHA-256** | Fast, widely supported | 2^128 security against Grover's |
| **SHA-3-256** | NIST-standardized, sponge construction | 2^128 security against Grover's |
| **SHA-3-512** | **2^256 security against Grover's**, NIST-standardized | Slightly slower, larger output |

**SHA-3-512 provides the best long-term security** while being:
- **NIST-standardized** (FIPS 202).
- **Resistant to Grover's algorithm** (2^256 security).
- **Future-proof** for 50+ years.

## Consequences

### Positive
✅ **Quantum-resistant**: 2^256 security against Grover's algorithm.
✅ **NIST-compliant**: Uses FIPS 202-standardized algorithm.
✅ **Future-proof**: Secure for 50+ years.
✅ **Sponge construction**: Resistant to length-extension attacks.

### Negative
❌ **Slightly slower**: SHA-3-512 is ~2x slower than SHA-256.
❌ **Larger output**: 512-bit hash (vs. 256-bit for SHA-256).

### Mitigations
- **Performance**: Hashing is **not on the critical path** (CoC entries are created asynchronously).
- **Storage**: 512-bit hashes are **still small** (64 bytes vs. 32 bytes for SHA-256).

## Alternatives Considered

### 1. **SHA-256 Only**
- **Rejected**: Only 2^128 security against Grover's algorithm (may not be sufficient for 50+ years).

### 2. **SHA-3-256**
- **Rejected**: Same security as SHA-256 against Grover's (2^128).

### 3. **BLAKE3**
- **Rejected**: Not NIST-standardized (though very fast and secure).

### 4. **Wait for NIST Guidance**
- **Rejected**: NIST already recommends SHA-3 for long-term use.

## References
- [FIPS 202 (SHA-3)](https://csrc.nist.gov/publications/detail/fips/202/final)
- [NIST Hash Function Recommendations](https://csrc.nist.gov/projects/hash-functions)
- [Grover's Algorithm (1996)](https://en.wikipedia.org/wiki/Grover%27s_algorithm)
- [SHA-3 (Keccak) Website](https://keccak.team/)

## Changelog
- **2025-XX-XX**: ADR created and accepted.
- **2025-XX-XX**: SHA-3-512 implemented in `pqc.py`.
- **2025-XX-XX**: CoC updated to use SHA-3-512 by default.
