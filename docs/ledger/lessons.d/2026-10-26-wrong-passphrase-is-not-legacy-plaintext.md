## 2026-10-26 — A failed authenticated decrypt means "not wrapped under THIS passphrase", never "plaintext": tell a legacy key by its length

**What was found.** `HybridSigner._load_or_create_mldsa` (audit A-018) treated any exception from `_unwrap` as proof that the key file was a legacy plaintext key from before the database had a passphrase. `_wrap` writes `salt || nonce || ciphertext+tag` with no magic prefix, so a GCM tag failure is exactly what a WRONG passphrase and an ALTERED file also produce; the still-wrapped blob was then split at the public-key length and used as a key pair, silently, with `key_protection` reporting «plaintext-0600».

**The rules.**
1. **A failed tag check proves one thing.** When a format has no marker, the fallback needs a second, independent test that only the legacy case passes. Here it is the length: a legacy plaintext key is exactly public key + secret key; a wrapped blob is 44 bytes longer; anything else is refused with fixed words that never quote the passphrase.
2. **Read the expected length from the library, not from a constant you cannot see.** `_mldsa_plain_len()` generates a throwaway pair (1.6 ms, only on the failure path) and measures it, so a pqcrypto size-constant rename cannot turn the check into a guess.
3. **The sibling path was already right.** The Ed25519 branch falls back only on `TypeError` (the PEM's own wrapped/plaintext marker) and re-raises a wrong passphrase; compare two loaders for the same key family before trusting either.
4. **Test with a stand-in for the library when the library is an extra.** The tests patch `signing._mldsa` and `PQC_AVAILABLE` with a fixed-size fake, so the refusal runs on a machine without pqcrypto; the real ML-DSA round trip stays in CI's PQC job.
