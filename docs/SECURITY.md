# Security

## Model

Open Omniscience v0.4 targets a **single local user** on a **Qubes OS Debian AppVM**:

- Binds to **127.0.0.1 only** (loopback). It must never be exposed on a network
  interface; there is intentionally no authentication/RBAC for this deployment.
- **No telemetry. No data leaves the machine.** LLM inference is local (Ollama, HTTP).
- Outbound traffic happens **only during ingestion**, and only through the single
  ethical fetcher: robots.txt is honoured and **fail-closed** (if it can't be
  confirmed, the URL is not fetched), per-host rate-limited, identifying User-Agent.

## Data integrity / chain of custody

- Stored items carry provenance (source, original URL, canonical URL, content hash,
  fetch time).
- Evidence bundles are **Merkle-rooted (domain-separated) + Ed25519-signed**. Verify
  with `scripts/verify_evidence.py <bundle.json> [signer_public_key]` — pass the
  signer's key to prove *provenance*, not just integrity. Verification needs nothing
  but the bundle + key (no DB, no trust in this tool).

## Hardening already in place

- Parameterized DB access only (no string-built SQL on the live path); FTS5 `MATCH`
  is fully bound. `bleach` allowlist for any HTML; `bcrypt` required for hashing
  (no silent fallback). `sanitize_url` strips whitespace before scheme checks.

## Reporting a vulnerability

Open a GitHub issue (or email open-omniscience@ideotion.com) with steps to
reproduce. Because the app is loopback/single-user, the main risk surface is the
ethical-fetch path and the evidence-verification guarantees above.
