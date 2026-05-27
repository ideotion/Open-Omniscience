# ADR-001: Use Hybrid Signatures (Ed25519 + Dilithium3) for Chain of Custody

## Status
✅ **Accepted**

## Context

The Chain of Custody (CoC) system in Open-Omniscience requires **cryptographically secure signatures** to ensure:
1. **Non-repudiation**: Actors cannot deny performing actions.
2. **Integrity**: CoC entries cannot be tampered with.
3. **Long-term trust**: Signatures must remain valid for **50+ years** (legal requirements).

### Quantum Computing Threat

- **Shor's Algorithm (1994)**: Can break **ECDSA, RSA, and Ed25519** on a **Cryptographically Relevant Quantum Computer (CRQC)**.
  - Estimated timeline: **2030–2050** (NIST PQC Standardization Project).
  - **Harvest-Now-Decrypt-Later (HNDL)**: Adversaries can store encrypted data today and decrypt it later when quantum computers are available.
- **Impact on Open-Omniscience**: 
  - Current **Ed25519 signatures** in CoC are **vulnerable to Shor's algorithm**.
  - **SHA-256 hashes** are **safe against Grover's algorithm** for now (2^128 security), but may need upgrading in the future.

### NIST Post-Quantum Cryptography (PQC) Standardization

NIST selected **CRYSTALS-Dilithium** as the **primary PQC signature algorithm** in 2024 ([NIST PQC Standardization](https://csrc.nist.gov/projects/post-quantum-cryptography/round-4-submissions)).

| Algorithm | Type | Security (Classical) | Security (Quantum) | Signature Size |
|-----------|------|---------------------|-------------------|----------------|
| Ed25519 | ECC | 128-bit | **Broken (Shor)** | 64 bytes |
| Dilithium3 | Lattice | 128-bit | **128-bit** | ~2.5 KB |

## Decision

**Use hybrid signatures (Ed25519 + Dilithium3) for all CoC entries.**

### Implementation Details

1. **HybridSignature Dataclass** (`src/blockchain/core/pqc.py`):
   - Contains **both Ed25519 and Dilithium3 signatures**.
   - **Backward compatible**: If Dilithium3 is unavailable, falls back to Ed25519.
   - **Forward compatible**: If Ed25519 is broken by quantum computing, Dilithium3 remains secure.

2. **HybridKeyPair Dataclass** (`src/blockchain/core/pqc.py`):
   - Stores **both Ed25519 and Dilithium3 key pairs**.
   - Supports **PEM format for Ed25519** and **raw bytes for Dilithium3**.

3. **Signing Process**:
   - Compute **SHA-3-512 hash** of the CoC entry (resistant to Grover's algorithm).
   - Sign the hash with **both Ed25519 and Dilithium3**.
   - Store both signatures in the `HybridSignature`.

4. **Verification Process**:
   - Verify **at least one signature** (Ed25519 or Dilithium3).
   - If both are present, both are verified (but only one needs to pass).

### Why Hybrid?

| Approach | Pros | Cons |
|----------|------|------|
| **Ed25519 Only** | Fast, small signatures | Vulnerable to quantum computing |
| **Dilithium3 Only** | Quantum-resistant | Large signatures, not widely supported yet |
| **Hybrid (Ed25519 + Dilithium3)** | **Backward + forward compatible**, quantum-resistant | Larger signatures (~2.5KB) |

**Hybrid signatures provide the best balance** between:
- **Backward compatibility** (existing systems can verify Ed25519).
- **Forward security** (Dilithium3 resists Shor's algorithm).
- **Practicality** (works today, future-proof for tomorrow).

## Consequences

### Positive
✅ **Quantum-resistant**: Dilithium3 signatures cannot be broken by Shor's algorithm.
✅ **Backward compatible**: Existing Ed25519 verifiers continue to work.
✅ **Future-proof**: Ready for post-quantum world.
✅ **NIST-compliant**: Uses NIST-standardized algorithms.

### Negative
❌ **Larger signatures**: ~2.5KB per CoC entry (vs. 64B for Ed25519).
❌ **Slightly slower**: Dilithium3 signing/verification is slower than Ed25519.
❌ **Dependency on `pqcrypto`**: Requires `pqcrypto` library for Dilithium3.

### Mitigations
- **Storage**: 2.5KB per entry is **acceptable for CoC** (stored in SQLite, not on-chain).
- **Performance**: Signing is **not on the critical path** (CoC entries are created asynchronously).
- **Fallback**: If `pqcrypto` is unavailable, **Ed25519-only mode** is used (graceful degradation).

## Alternatives Considered

### 1. **Pure Dilithium3**
- **Rejected**: Not backward compatible, large signatures.

### 2. **Pure Ed25519**
- **Rejected**: Vulnerable to quantum computing.

### 3. **SHA-3 Only (No Signatures)**
- **Rejected**: No non-repudiation (anyone can create a CoC entry).

### 4. **Wait for NIST Finalization**
- **Rejected**: NIST has already standardized Dilithium (2024).

## References
- [NIST PQC Standardization Project](https://csrc.nist.gov/projects/post-quantum-cryptography)
- [CRYSTALS-Dilithium](https://pq-crystals.org/dilithium/)
- [RFC 8032 (Ed25519)](https://datatracker.ietf.org/doc/html/rfc8032)
- [FIPS 202 (SHA-3)](https://csrc.nist.gov/publications/detail/fips/202/final)
- [Shor's Algorithm (1994)](https://en.wikipedia.org/wiki/Shor%27s_algorithm)
- [Grover's Algorithm (1996)](https://en.wikipedia.org/wiki/Grover%27s_algorithm)

## Changelog
- **2025-XX-XX**: ADR created and accepted.
- **2025-XX-XX**: Hybrid signatures implemented in `pqc.py`.
- **2025-XX-XX**: CoC updated to use hybrid signatures.
