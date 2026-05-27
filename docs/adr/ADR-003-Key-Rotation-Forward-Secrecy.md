# ADR-003: Key Rotation and Forward Secrecy for Chain of Custody

## Status
✅ **Accepted**

## Context

The Chain of Custody (CoC) system in Open-Omniscience requires **long-term cryptographic security** to ensure:
1. **Non-repudiation**: Actors cannot deny performing actions.
2. **Integrity**: CoC entries cannot be tampered with.
3. **Forward secrecy**: Compromise of a key **does not affect past entries**.

### Key Compromise Threat

- **Private Key Leak**: If an attacker obtains the private key used for signing CoC entries, they can:
  - **Forge new entries** (impersonate the actor).
  - **Repudiate past actions** (if the key is revoked).
- **Impact on Open-Omniscience**:
  - **Without forward secrecy**: Compromise of the current key **invalidates all past signatures**.
  - **With forward secrecy**: Compromise of the current key **only affects future entries**.

### NIST Key Management Best Practices (SP 800-57)

NIST recommends:
- **Key rotation**: Rotate keys **periodically** (e.g., every 30–90 days).
- **Key revocation**: Revoke compromised keys **immediately**.
- **Key lifetime**: Limit key lifetime to **1 year** for signing keys.
- **Forward secrecy**: Use **ephemeral keys** or **key versioning** to limit exposure.

## Decision

**Implement automatic key rotation with forward secrecy for CoC signing keys.**

### Implementation Details

1. **KeyManager Class** (`src/blockchain/core/key_manager.py`):
   - Manages **Ed25519 + Dilithium3 hybrid key pairs**.
   - Supports **automatic key rotation** on a configurable schedule.
   - Maintains a **Key Revocation List (KRL)** for compromised keys.
   - Stores keys in **SQLite database** (encrypted at rest in future).

2. **Key Rotation Schedule**:
   - **Default**: Rotate every **30 days** (`rotation_interval=2592000`).
   - **Configurable**: Can be adjusted based on security requirements.
   - **Key lifetime**: Maximum **1 year** (`key_lifetime=31536000`).

3. **Key Versioning**:
   - Each key has a **unique version number** (incremented on rotation).
   - CoC entries store the **key_id** used for signing.
   - Verification uses the **key_id** to retrieve the correct key.

4. **Key Revocation List (KRL)**:
   - Tracks **compromised or revoked keys**.
   - Revoked keys **cannot be used for signing or verification**.
   - If the current key is revoked, **automatic rotation** occurs.

5. **Hardware-Backed Keys (Future)**:
   - Support for **YubiKey** and **TPM** for high-security deployments.
   - **Not implemented yet** (requires `python-yubikey` or `tpm2-python`).

### Forward Secrecy Guarantee

| Scenario | Without Key Rotation | With Key Rotation |
|----------|----------------------|-------------------|
| **Key compromise** | All past signatures **invalid** | Only future signatures **at risk** |
| **Key revocation** | All past entries **unverifiable** | Past entries **remain verifiable** |
| **Long-term trust** | **Broken** if key is compromised | **Preserved** for past entries |

**Key rotation ensures that:
- **Past CoC entries remain verifiable** even if the current key is compromised.
- **Future entries are protected** by the new key.
- **Damage is limited** to the time window between rotations.

## Consequences

### Positive
✅ **Forward secrecy**: Past entries remain secure even if the current key is compromised.
✅ **Automatic rotation**: No manual intervention required.
✅ **Key revocation**: Compromised keys can be revoked and will no longer be trusted.
✅ **Auditability**: Key versioning allows tracking which key was used for each entry.
✅ **NIST-compliant**: Follows NIST SP 800-57 best practices.

### Negative
❌ **Key management complexity**: Requires secure storage of old keys.
❌ **Database dependency**: Keys are stored in SQLite (requires backup).
❌ **Performance overhead**: Key rotation adds slight overhead (negligible for CoC).

### Mitigations
- **Key storage**: Keys are stored in **SQLite with optional encryption** (future).
- **Backup**: SQLite database can be **backed up** (see `integrity_monitor.py`).
- **Hardware security**: Future support for **YubiKey/TPM** (not implemented yet).

## Alternatives Considered

### 1. **No Key Rotation**
- **Rejected**: No forward secrecy; key compromise invalidates all past entries.

### 2. **Manual Key Rotation**
- **Rejected**: Requires manual intervention; error-prone.

### 3. **Ephemeral Keys (Per-Entry)**
- **Rejected**: Impractical for signatures (would require storing all keys).

### 4. **Hardware Security Module (HSM) Only**
- **Rejected**: Not all users have access to HSMs; software-based rotation is more accessible.

## References
- [NIST SP 800-57: Key Management Best Practices](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
- [RFC 5280: Internet X.509 Public Key Infrastructure Certificate and CRL Profile](https://datatracker.ietf.org/doc/html/rfc5280)
- [YubiKey Documentation](https://developers.yubico.com/)
- [TPM 2.0 Specification](https://trustedcomputinggroup.org/resource/tpm-library-specification/)

## Changelog
- **2025-XX-XX**: ADR created and accepted.
- **2025-XX-XX**: KeyManager implemented in `key_manager.py`.
- **2025-XX-XX**: CoC updated to use KeyManager for signing.
