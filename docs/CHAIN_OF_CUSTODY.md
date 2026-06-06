# Chain of Custody

Open Omniscience makes a deliberately *narrow and honest* evidentiary claim:

> **This corpus contained _this_ item, with _this_ content, recorded at _this_
> time, and the record has not been altered since — and here is cryptographic
> proof you can check yourself, offline, without trusting this tool.**

That is genuinely useful for an investigative journalist: it defends against
"you fabricated this," "you back‑dated this," or "you quietly edited it after the
fact," and it lets you show you reported something *before* a source page was
changed or deleted. It is **not** a whistleblower submission system (like
SecureDrop), and a "source" in this tool is a *news outlet*, not a confidential
human source. Keep that scope in mind when reasoning about protection.

This document describes the real mechanisms (`src/custody/`, `src/reporting/`) and
is explicit about what each one does and does **not** prove.

---

## The three properties, and how we get each one honestly

| Property | Mechanism | What it proves | What it does **not** prove |
|---|---|---|---|
| **Integrity** | Ed25519 (+ optional ML‑DSA) signatures over a canonical serialization; Merkle root over all provenance fields | The bytes have not changed since signing; everything is covered, not just the content | — |
| **Provenance** | **Pinning** the signer's known public key | The record was signed by *that* signer | Anything, if you don't pin a key — a valid signature alone only means "signed by the key embedded in the bundle" |
| **Time** | `local` (self‑asserted) **or** OpenTimestamps (Bitcoin‑anchored) | Local: a time the tool asserts. OTS: the content existed *no later than* a Bitcoin block | Local time proves nothing to a third party; OTS proves a *ceiling* on time, not the exact moment |

We refuse to fake any of these. If a real third‑party timestamp can't be obtained
(offline, or the library isn't installed) the code raises rather than inventing a
time — the failure mode the project's charter forbids (PRODUCT_SYNTHESIS §3.7).

---

## Components

### 1. Signed evidence bundles — `src/reporting/evidence.py`
A point‑in‑time export of selected articles, each with its provenance and a content
hash, bound by a **domain‑separated Merkle root** and an **Ed25519 signature**.
Verify offline with `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Exposed at `POST /api/reports/evidence` and `/api/reports/evidence/verify`.

### 2. Hybrid signatures — `src/custody/signing.py`
Combines **Ed25519** (fast, classical) with **ML‑DSA** (FIPS 204, post‑quantum,
the standardised successor to CRYSTALS‑Dilithium). Two rules make this honest:

- **Honest labels.** A signature is labelled `hybrid` only when an ML‑DSA key was
  actually used. Without the `pqc` extra installed, signing produces an `ed25519`
  signature and says so — it never claims quantum resistance it didn't produce.
- **Hybrid means AND.** A `hybrid` signature verifies only if **both** components
  verify. A verifier that lacks the post‑quantum library cannot check the ML‑DSA
  half and therefore **fails loudly** — it never silently passes on the classical
  half alone. (A scheme that accepts *either* signature is worthless once the
  classical one is broken.)

Private keys are encrypted at rest with AES‑256‑GCM under a scrypt‑derived key
when `OO_KEY_PASSPHRASE` is set; otherwise they are written `0600` in the clear
and the protection level is reported truthfully as `plaintext-0600`.

### 3. Custody log — `src/custody/log.py`
An **append‑only** SQLite ledger. Each action (`ingest`, `access`, `export`,
`redact`, …) becomes an entry that is **hash‑chained** to its predecessor,
**signed**, and **timestamped**. `verify()` re‑checks sequence order, chain links,
per‑entry hashes, signatures, and timestamp digests. Exports verify offline:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Opt‑in auto‑logging on ingest: set `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). It is **off by default** — an explicit evidentiary
choice with a small per‑article signing cost, not silent always‑on behaviour.
It is fail‑open: a custody error never breaks ingestion.

### 4. Anchoring — `src/custody/anchor.py`
Publishes a Merkle root to an external witness so its existence time doesn't rest
on your own clock or key:

- **`local`** (default, offline): records the root in a local anchor book. Proves
  only that *this tool* stored it — internal audit, not third‑party proof.
- **`opentimestamps`** (network): anchors an opaque hash into Bitcoin. No wallet,
  no fee, independently verifiable. Falls back to an explicit *unavailable* error
  when offline — never a fake receipt.
- **`ethereum` / `ipfs` / `arweave`**: declared but **not implemented**. They
  refuse with a clear error rather than shipping as stubs whose `verify()` always
  returns false.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

### 5. Settings — `src/custody/settings.py` (GUI‑configurable)
Custody behaviour is operator‑controlled at runtime, not just via env/YAML.
Preferences persist to `custody_settings.json` under the data dir and are edited
from the **Chain of custody** panel in the web UI (or the REST API):

- **`pqc_enabled`** — request hybrid Ed25519 + ML‑DSA signing.
- **`anchoring_mode`** — `local` (default) or `opentimestamps`.
- **`auto_log_on_ingest`** — append a signed entry on every successful ingest
  (defaults to the legacy `OO_CUSTODY_ON_INGEST` flag until a preference is saved).
- **`default_actor`** — optional actor label for auto‑logged entries.

**Honesty invariant.** A toggle is a *request*, not a guarantee. The API and GUI
always surface the **effective** state (preference **AND** library availability):
if PQC is enabled but `pqcrypto` is not installed, the signer stays Ed25519‑only
and the UI says so — it never shows a green "hybrid" light it cannot back up. Same
for OpenTimestamps without the `timestamping` extra.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

A typical "maximum proof" workflow:

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

## ⚠️ Privacy: anchoring can deanonymise you

Anchoring to a **public** blockchain is **permanent publication** of a hash and a
timestamp. The hash itself reveals nothing about the content, but the *act* of
submitting reveals your IP and timing to the calendar/RPC operators, and a funded
on‑chain wallet creates a money trail. For anyone who needs anonymity:

- Prefer **local + OpenTimestamps** over public‑chain wallets.
- Route OpenTimestamps submissions through **Tor** (e.g. `HTTPS_PROXY`).
- Or skip external anchoring entirely and rely on local timestamps + signing.

Confidentiality and public‑chain anchoring are in tension. The default
configuration (offline local provider, self‑asserted local time) leaks nothing.

---

## What we deliberately did **not** build

- **No fake RFC‑3161 TSA.** Returning `datetime.now()` and calling it a "trusted
  timestamp" is theatre. Use OpenTimestamps (real) or local (honestly labelled).
- **No OR‑semantics hybrid signatures.** See "Hybrid means AND" above.
- **No always‑on background integrity daemon, no unencrypted key store advertised
  as "encrypted."** Keys say how they're protected; verification is on demand.

## Threat model in one paragraph

The tool runs as a **single local user, loopback‑only, on Qubes** (see
`docs/SECURITY.md`). The custody system defends the *integrity and provenance of
your own evidence trail* against later tampering and against "you made this up"
challenges. It does not, and cannot, protect a human source's identity by itself,
and naive public‑chain anchoring can actively *harm* anonymity — so anchoring is
opt‑in, defaults to offline, and ships with the warning above.
