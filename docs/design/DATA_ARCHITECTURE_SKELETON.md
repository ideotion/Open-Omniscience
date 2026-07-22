> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — K1 (`content_multihash`), K2 (`canon_version`), and K4 (the honesty envelope) are confirmed SHIPPED. K5 (WARC/BagIt archive), age/SLIP-39 archival encryption, TLS-chain/SCT/CT capture, C2PA verification, the Provenance-Tier UI, and tiered-retention cold storage all remain at zero code — correctly still deferred, exactly as this doc's own §7 states (not silently forgotten). See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Data Architecture & Durability Skeleton (architecture-of-record)

**Status:** decisions ratified in the 2026-06-19 design session · pre-0.1 (no installed
archive base — formats are free to change until 0.1 tags) · **design only, no code in this
document.**

This is the single architecture-of-record that ties together three workstreams the
project had been treating separately — **scalability**, **durability**, and **content
authentication** — and shows they are **one skeleton**. It is the artifact the
maintainer asked to "fix in time": the small set of decisions that are cheap to make
once, now, and ruinous to retrofit once corpora exist in the wild.

It is the product of two internet-research reviews (scaling 10×/100×/1000×; provable
source authentication & tamper-evidence) cross-checked against this codebase, plus the
maintainer's rulings. Where a recommendation is still gated on verification it is parked
in the **VERIFY** list (§8); the autonomous build brief lives at
`docs/archive/session-briefs/AUTONOMOUS_BUILD_BRIEF_DATA_ARCH.md`.

---

## 0. Governing principles (the reframes that organize everything)

1. **There are three separate security properties; never conflate them.**
   - **Confidentiality** (encryption) — "can a thief read it?" Protects the journalist's
     *unpublished work-in-progress*. Real but narrow; **not** the durability advantage.
   - **Integrity** — "has it changed since we captured it?" Achievable and largely
     already built (`src/custody`).
   - **Authenticity** — "did the source say X?" The goal; only partially achievable; we
     **never claim past the evidence we hold**.

2. **Performance must never depend on hiding data.** Decade-scale speed comes from
   *maintained counters + a derived columnar read-model*, with **every article fully
   present and searchable at all times.**

3. **Cross-time recall is sacred.** The app exists partly to surface ancient events
   beside recent ones ("does the story repeat itself"). No feature may bias toward recent
   data, default a user to a recent window, or make old data slower-to-reach or
   second-class.

4. **One canonical store; everything else is rebuildable.** The encrypted SQLite/SQLCipher
   operational DB is the source of truth. Off **one** stable export seam (A1) hang two
   *disposable, rebuildable* derived representations: a **columnar store for speed** and a
   **WARC/BagIt archive for permanence**. Both are keyed by the same content hash; both
   carry the honesty envelope. **One spine, not three.**

5. **Honesty by construction carries into every layer.** No composite scores. Every
   maintained or approximate number carries an **honesty envelope**
   `{value, basis: exact|estimated, as_of, method, n}` — `basis` is a *disclosure*, not a
   score. Degrade loudly; never fabricate a count, an IP, a location, or a provenance
   claim.

---

## 1. What is already built (verified in code — do NOT rebuild)

- `src/custody/log.py` — an **append-only, hash-chained, signed, offline-verifiable**
  event log (each entry commits the previous head). This *is* the "day-one federation
  seam" both reviews call for.
- The custody signer is already **Ed25519 + ML-DSA hybrid** → the post-quantum agility is
  shipped, not pending.
- `src/custody/timestamp.py` + `anchor.py` — **OpenTimestamps anchoring, opt-in**.
- The oo-backup-2 artifact already carries a **Merkle root over article hashes** + a
  signed manifest.
- `KeywordMention` already carries `observed_on` (date) + denormalised `country`/`city` +
  `created_at` — so the time/source key (A4) is largely present.

→ 4 of the 5 "irreversible seams" already exist. Lean on `src/custody`; do not reinvent it.

---

## 2. The skeleton to freeze in V0.1 (the irreversible decisions)

| # | Decision | Status vs code |
|---|----------|----------------|
| **K1** | **Self-describing content identifier** — add `Article.content_multihash` (algorithm named in-band, e.g. `sha2-256:…`) **alongside** the existing `Article.hash`. **Never reformat `Article.hash`** (unique, dedup-load-bearing). | Gap — additive, cheap |
| **K2** | **Stamp `Article.canon_version`** — which canonicalization produced `canonical_url`. | Gap — additive, cheap |
| **K3** | **Provenance Tier vocabulary** — a *descriptive* per-resource label, never a composite score; "signature failed" ≠ "absent"; universal "a compromised capture machine defeats this" caveat. | New (authentication workstream) |
| **K4** | **Honesty envelope on every maintained/approximate aggregate.** Mandatory because `KeywordMention` FKs are `ondelete=CASCADE`, so any rollup can drift — the envelope makes counters *honest* (estimated vs exact + reconcile). | New (schema shape) |
| **K5** | **Archival format = BagIt outer · WARC at *text fidelity with raw-byte slots reserved* · OAIS/PREMIS provenance (unknowns marked) · SHA-256 + Merkle + par2 · named/appendable signatures · opt-in multi-authority timestamps · gzip-in-WARC.** | New (durability workstream) |
| **K6** | **Encryption is a decoupled layer.** Operational store stays SQLCipher (no-recovery). Archival copy → thin removable `age` outer envelope. Derived columnar cache → encrypted under the **same** passphrase, or in-memory; **never plaintext on disk.** | New |
| **K7** | **Format versioning fails LOUD** — magic + semver + capability flags; an unknown/newer archive on an old app **refuses**, never partial-restores; `SPEC.md` bundled inside every archive. | New (contract) |

---

## 3. Scalability — staying fast for a decade on modest hardware

The diagnosed problem: whole-corpus `GROUP BY` in GIL-bound pure Python over an encrypted
row-store, whose cost grows linearly with total corpus size (the 132 s "Groups" freeze on
a 10k-article corpus). The fix makes work proportional to **new** data, not **total** data.

1. **Maintained counters** (`Keyword.mention_count` / `article_count`), updated on the
   single-writer index path; a background reconcile recomputes exact and the **K4 honesty
   envelope** discloses any interim `estimated` state. Kills the per-read whole-corpus scan
   for `top`/`supergroups`/`trending`. SQLite-only, no new dependency.

2. **Derived columnar read-model** behind a stable **A1 seam** (`src/analytics/readmodel.py`)
   — the heavy aggregations (`associations`, `graph`, `framing`, `supergroups`, `trending`,
   `map-coverage`) read from a columnar engine, turning ~minutes of Python `GROUP BY` into
   sub-second SQL. **Decision: persisted + encrypted DuckDB under the same passphrase**
   (incrementally maintained at index time; survives restarts so a decade-scale corpus is
   *not* reprocessed each session), with two safeguards:
   - **Empirical encryption gate** (runnable offline): create the store with a sentinel,
     prove the sentinel is absent from the raw file bytes, that it won't open without the
     key, and that it does with the key.
   - **Hard fallback:** if the gate fails or DuckDB can't be guaranteed fully offline
     (extension autoload disabled), fall back to **DuckDB in-memory** — never a plaintext
     file on disk. Worst case degrades to "rebuilt lazily per session," never to a leak.
   The derived store is a **disposable cache**: the canonical store stays the source of
   truth; a cold/missing derived store falls back to the live query (slower, never wrong);
   it is **excluded from backups** (rebuildable), with an optional "include to skip the
   post-restore rebuild" later (like the wiki-dumps/models inclusion).

3. **Tiered retention (DESIGNED, not built this session).** Default OFF. An optional
   constrained-hardware mode where **only raw article text** relocates to a **local**
   archive; the **search index, all mention/analytic/metadata rows, and provenance stay
   permanently hot**, so search, trends, maps, when/where/who, coordination — every
   analytic — are untouched. Opening/recomputing over a cold article becomes a transparent
   **local** archive read, never a failure. Reversible. **Performance does not depend on
   it** (counters + columnar store carry the speed); it is purely a disk-space escape hatch.
   Needs the K5 archive format first.

4. **Time-partitioning is ABANDONED** unless it can be proven to return byte-identical
   results with no recency bias (principle 3). Not load-bearing; not worth the risk.

---

## 4. Tracing & securing content (provenance + tamper-evidence)

**Tracing (provenance) — what every article carries:** the K1 multihash + K2
`canon_version`; capture-time evidence (URL, capture time, and anonymization-neutral
public corroboration — TLS certificate chain + SCTs, Certificate Transparency confirmation,
plus source-signed material — DKIM for email, C2PA for media — *when present*); the **K3
Tier label** stating exactly what the evidence proves; the existing append-only
hash-chained custody log recording every action on an item.

**Securing (tamper-evidence) — already built (§1):** content-addressing, Merkle root,
Ed25519 + ML-DSA signed manifests, opt-in OpenTimestamps existence-anchor, par2 bit-rot
recovery, and crypto agility (algorithms named in-band, signatures appendable → migrate to
SHA-3 / SLH-DSA in decades without invalidating old proofs).

**Capture posture (ratified ruling):** **default-anonymize + opt-in high fidelity.**
Anonymize/strip stays the default (web and email). A consented per-source "high-fidelity
preservation" mode retains raw bytes + byte-exact DKIM material only where opted in, with
the privacy cost stated. The anonymization-neutral public corroboration (TLS chain/SCTs,
headers, C2PA-when-present) is captured for everything.

**Source IP + offline geolocation (ratified, buildable):** capture the **server IP we
connected to** at fetch time (honest "unavailable" over Tor/SOCKS — the socket is the
proxy, not the server); geolocate **offline** against a dated, CC-licensed bundled
country-level DB plus an optional one-time-downloaded city-level DB; plot it on `ooMap` as
a **distinct "server location" layer** with caveats **visible by default** (CDN edge /
anycast, approximate, dated DB, unavailable over Tor, **never** proof of the source's true
origin). Investigative signal (many "independent" sources sharing one host/ASN) surfaced as
a **shape to investigate, never a verdict** — the network-layer cousin of the existing
coordination/source-laundering detection.

---

## 5. The provenance tiers (descriptive, never a grade)

Read as **orthogonal evidence types per resource**, not a ladder. One page can carry Tier-1
evidence (a signed image), a Tier-3 affidavit (over the whole capture), and Tier-4 status
(the unsigned text) at once. A *present-but-failed* signature is shown distinctly from an
*absent* one.

- **Source-signed (verified)** — DKIM/C2PA/etc. verifies. Proves a key controlled by the
  named domain signed it. Not authorship-as-truth; may become repudiable if the source
  later publishes its keys.
- **Source-signed (key unavailable)** — a signature is present but the public key was not
  archived and is no longer retrievable.
- **Signature failed** — present and does not verify; content may have been altered.
- **Notarized capture (future)** — a third party attests the server returned these bytes.
  Depends on trusting the notary. *Not load-bearing now (see §7).*
- **Provenance affidavit (this app)** — we captured these exact bytes from this URL at this
  time, unchanged, and a valid certificate for that domain existed then. Not proof the
  source authored it.
- **Captured bytes (integrity only)** — unchanged since hashed; nothing about origin/time.
- On every one: **a compromised capture machine at the moment of capture defeats this.**

---

## 6. Encryption stance (kept in its lane)

- **Operational store:** SQLCipher, **no-recovery** (unchanged — correct; its job is
  protecting unpublished work from a stolen laptop). The recovery debate was about the
  wrong property; encryption is *not* what makes an archive trustworthy.
- **Archival copy:** a thin, removable `age` outer envelope over standard formats (so a
  future reader needs fewer moving parts; LoC sustainability criteria treat encryption as a
  preservation *obstacle*, hence "outer + removable, not baked into the DB engine").
- **Derived columnar cache:** encrypted under the **same** passphrase via the one
  `connect()` factory (no second key surface, invisible to the user) — or in-memory; never
  plaintext on disk.

---

## 7. Explicitly deferred / routed elsewhere (honest scope)

- **TLS notarization (Tier 2):** *not yet load-bearing.* The mature open tool is TLS-1.2
  only, its bandwidth is unusable over Tor, and it **injects a live third party who learns
  you fetched domain D at time T** (deanonymization). Build the capture record so it can
  slot in later; make no current claim depend on it.
- **Witness federation / mutual cross-verification (the original blockchain intent):**
  needs other live participants → the **Open Commons Mirror** sister project, optional
  opt-in. This app stays single-machine + **anchoring-only** (OpenTimestamps gives ~90% of
  the value with one consented call, no cluster). The day-one seam (K1 + custody log +
  Merkle root) makes future federation possible **without re-archiving**.
- **Running our own chain:** rejected (circular trust; no gain over anchoring to an
  already-witnessed public chain).
- **WARC/BagIt archive, `age` envelope, SLIP-39, tiered-retention eviction, TLS chain/SCTs/
  CT capture, the Tier-vocabulary UI:** real workstreams, sequenced after the
  data-management slices.

---

## 8. Hard limits (stated, never exceeded)

A **compromised capture machine defeats everything** · a plain HTTPS fetch leaves **no
transferable proof** of what the server sent · we prove "these bytes were served under this
name at this time," **never** the source's truth or intent · even DKIM origin proof is
**durability-contingent** (the key-publishing deniability movement) · IP geolocation shows
**infrastructure** (often a CDN edge), not the publisher. "Name the shape, never the verdict."

---

## 9. VERIFY list (close on a networked machine before tagging 0.1)

1. **DuckDB encryption** — real AEAD, mature, and **fully offline** (extension autoload
   disablable). The empirical sentinel gate (§3) closes the basic question even offline;
   confirm the crypto backend (OpenSSL/mbedTLS AES) from DuckDB's own docs/source.
2. **DuckDB string-heavy speedup** — realized gain on short-string keyword data, not just
   numeric benchmarks.
3. **`age` / SLIP-39** exact versions + a recovery drill (durability workstream).
4. **TLSNotary TLS-1.3** status; **C2PA** offline trust-list mechanics; **OpenTimestamps**
   offline-verify procedure (archived Bitcoin header chain).
5. **Published-private-key DKIM** prevalence among large senders.
6. **IP geolocation DB** — exact license (DB-IP Lite CC BY 4.0 / IP2Location LITE
   CC BY-SA 4.0), file sizes (country bundleable; city download-on-demand), and fully
   offline lookup.
7. **Body-scrubbing policy** for the default (anonymized) path if raw bodies are ever
   retained under the opt-in high-fidelity mode.

---

## 10. The one coherent skeleton (summary)

```
                         CANONICAL (source of truth)
              SQLCipher / SQLite operational store, no-recovery
                                  │
                    A1 export seam (stable: K1 hash, K2 canon, capture metadata)
                ┌─────────────────┼──────────────────────────────┐
                ▼                                                 ▼
   DERIVED — SPEED                                     DERIVED — PERMANENCE
   columnar store (DuckDB,                             WARC + BagIt archive
   encrypted same key / in-mem)                        (text fidelity, raw slots reserved)
   maintained counters + K4 envelope                   PREMIS/OAIS · Merkle · par2 ·
   disposable, rebuildable                             named/appendable sigs · OTS anchor
                                                        + optional local cold tier (eviction)
                \___________________  both keyed by K1 content hash  ___________________/
                                 every action in the append-only custody log
```

Scalable, durable, and traceable **by construction** — one spine, not three systems.
