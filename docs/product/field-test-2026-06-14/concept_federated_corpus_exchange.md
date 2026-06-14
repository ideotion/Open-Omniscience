# Concept memo — Federated Corpus Exchange + Automatic Fixity & Provenance

Developed at maintainer request (2026-06-14). Grounds in already-shipped
DB-reliability work; this is a CONCEPT to seed a design doc, not an implementation spec.

## The four asks
1. Two journalists (different parts of the world) merge ENTIRE databases without
   losing trust in their own.
2. Aggregation survives long-term app updates → a reliable structure that "won't
   change over time".
3. Automatic DB integrity tools to verify no tampering — like verifying Linux ISO
   checksums/signatures. Completely automatic.
4. Robust, durable, reliable, long-term, performative, open-source, ethical.

## What ALREADY EXISTS (reuse, don't reinvent)
- oo-backup-2 artifact: one signed zip; manifest = per-member SHA-256 + Merkle root
  over article hashes + explicit exclusions; keys only inside encrypted artifacts;
  legacy artifacts accepted forever.
- v2 ADDITIVE merge engine: preview=commit on a disposable copy; ~28 tables merged on
  natural keys with FK remap; bit-level article dedup; conflicts keep LOCAL + report
  both (never averaged); custody chains imported verified-not-trusted, original seqs
  preserved, never spliced, transitive propagation; atomic swap + keep-3 snapshots;
  torture suite 10/10 (SIGKILL-safe, floods idempotent).
- RESTORE-IS-ADDITIVE ruling: restore never replaces; always additive + dedup.
- Reliable-memory pillar (designed, sister-project-leaning): content addressing, signed
  manifests, RFC-6962 transparency logs (inclusion + consistency proofs),
  OpenTimestamps-style anchoring (no tokens), LOCKSS replication, fixity audits,
  VINTAGES never overwrites.

⇒ The foundation for asks 1 + 3 largely EXISTS. This concept ELEVATES it into a
federated-exchange workflow + automatic-fixity UX + a durability contract.

## Pillar A — Trust-preserving federated merge (ask 1)
- Every merged record carries an immutable, signed ORIGIN ATTRIBUTION (which
  corpus/identity contributed it). After merge you can always SEE and FILTER
  mine / theirs / both. Your own records' trust status is NEVER mutated by an import.
- The other party's data is "verified-not-trusted": a signature verifies AUTHENTICITY
  OF ORIGIN + INTEGRITY, not veracity (provenance ≠ veracity, stated). This is already
  the custody model — generalize it to all merged data.
- Additive, CRDT-like semantics: merges are idempotent + order-independent (re-merging
  changes nothing — already a torture property), so N journalists can pairwise-merge in
  any order and converge. Conflicts keep both values with both attributions.
- Each journalist signs their contribution with their own offline key; the manifest
  records the signer.
- MULTI-ATTESTATION on dedup (maintainer 2026-06-14): identical data is NOT duplicated
  (shipped bit-for-bit dedup) — but instead of discarding the duplicate, ATTACH an
  ATTESTATION to the kept record: "signed corpus X (signer fingerprint, import date)
  independently held this exact content hash." Dedup becomes a CORROBORATION counter
  ("independently attested by K signed corpora") + a tamper-evidence multiplier (altering
  one copy is exposed by the others' matching hashes). HONESTY CAVEAT (anti-false-
  triangulation): record WHICH source each corpus got it from; two corpora sharing one
  upstream origin = ONE source in two hats — attestation counts as corroboration only when
  the collection paths are independent (surface shared-origin structure like the Links
  tab); never auto-inflate into "more true."
- CHANGES-ONLY storage on difference (maintainer 2026-06-14): when corpora DIFFER, store
  only the changes, not full copies — achieved by CONTENT-ADDRESSED storage (each unique
  version stored once; identical content across corpora costs zero extra + gains an
  attestation; a differing version is a new content hash = the "change", attributed and
  surfaced as a vintage per Item 8). Reconciles with the wiki reconstructability lesson:
  store each version whole-but-deduped rather than naive textual diffs that can't be
  reconstructed.

## Pillar B — Durable, schema-stable INTERCHANGE format (ask 2 — with an honest reframe)
- HONEST REFRAME: an internal schema literally frozen forever is impossible (new
  features need schema growth). The durable thing is a STABLE, SELF-DESCRIBING,
  VERSIONED ARCHIVE/EXCHANGE format decoupled from the volatile internal SQL schema.
  oo-backup-2 is the seed.
- Principles: self-describing manifest (declares its own format version + what is/isn't
  carried); FORWARD-COMPATIBLE readers (unknown fields preserved on round-trip, never
  dropped — a newer peer's extra data survives an older app); CONTENT-ADDRESSED record
  identity (stable across schema churn); "legacy accepted forever" becomes a hard
  COMPATIBILITY CONTRACT with a conformance test in CI.
- The internal DB is rebuildable from the archive at any schema version (migrations
  apply on a staged copy — already the pattern). Consider publishing the format as an
  OPEN SPEC so it outlives the app (reliable-memory ethos).

## Pillar C — Automatic fixity & tamper-evidence (ask 3, "like ISO verification")
The ISO analogy = checksum + GPG signature from a trusted key, verified before trust.
Make it AUTOMATIC + continuous:
- On import, the app AUTO-verifies every member hash + the Merkle root + the producer's
  SIGNATURE, and shows a plain verdict (✓ authentic & intact / ✗ tampered / ⚠ unsigned).
  No manual checksumming.
- Peer keyring (TOFU): pin peers' public keys (like known_hosts); known signers
  auto-verify. Fingerprint compare for first contact; never a CA.
- Continuous FIXITY AUDIT: incremental background re-hash of stored content vs the
  manifest detects bit rot / at-rest tampering; loud verdict (audit-07 fixity tool).
  Automatic.
- Append-only TRANSPARENCY LOG of imports/merges/exports (hash-chained, RFC-6962
  inclusion + consistency proofs) = the Item-8 audit trail; a third party can later
  verify custody.
- OPTIONAL consented existence-anchoring (OpenTimestamps-style, no tokens): proves the
  corpus existed in this state before time T. Network ⇒ one consent popup + visible
  job; off by default.

## Pillar D — Performance, ethics, open-source
- Performative: verification is hash-based (cheap, streamable, parallel); metadata
  separated from blobs (codec-drag lesson); fixity incremental + off the write path;
  merge already runs on a disposable copy; verification reads use a snapshot.
- Ethical: no fabricated security (signature ≠ truth, said plainly); user always sees
  mine/theirs/both + can split; NO central authority (federation, not a server —
  matches "never host users' data"); offline-first; user corpora never touch the Open
  Commons Mirror.
- Open-source: format spec + verification tools documented + reproducible
  (reproducibility is the defense).

## Pillar E — the Difference Explorer (Settings → Database management)
A dedicated tool to EXPLORE, ANALYZE, and ACT UPON database differences (maintainer
2026-06-14). Rare-case ⇒ lives in Settings → Database management (invariant #8; reuses
the T6 restore-preview area; preview=commit on a disposable copy, the preview cannot lie).
- EXPLORE: classify records across two/N corpora — only-mine · only-theirs · identical
  (attested) · present-but-DIFFERING (vintages/conflicts).
- ANALYZE: per-difference detail — provenance + signer + dates, keyword-impact delta
  (Item 8), independence assessment (shared-origin vs independent).
- ACT: accept-theirs (ADD) · keep-mine · keep-BOTH (default) · mark-for-investigation ·
  split. RESTORE-IS-ADDITIVE holds: actions never silently replace/delete your data;
  keep-both is the safe default; any removal is explicit + reversible via the keep-3
  snapshots.
- Shares the Item-8 change/provenance substrate + Item-9 manifest/merge engine.

## Honest gaps / decisions to settle (before build)
1. Per-journalist IDENTITY/KEY model + UX for non-cryptographers (generate / back up /
   exchange / pin peers) — ties to the Custody-tab UX rename. The hardest UX problem.
2. Ask 2 cannot mean a literally frozen schema — confirm the reframe (stable
   interchange format + content-addressed identity) is what's wanted.
3. Scope split: local fixity + signed-manifest auto-verify clearly belong in THIS app
   for v0.1; public-chain anchoring + witness cosigning may be Open-Commons-Mirror
   scope. Decide the v0.1 line.
4. Out-of-band key verification between strangers (fingerprint compare now; optional
   web-of-trust later, never a CA).
5. Conflict UX at journalist scale: keep-both-with-attribution can grow; needs a
   reviewable conflict view (cf. Item 8 changes tab).

## Relationship to other items
- Item 8 (transversal change-tracking/audit) shares the transparency-log + provenance
  substrate — design together.
- Reliable-memory pillar / Open Commons Mirror — this is the LOCAL, peer-to-peer half
  of the same math; the mirror is the server-scale half. User corpora stay local.

## Maintainer rulings (2026-06-14, round 1)
- **Q2:** PROCEED — a scraped DB must survive app version upgrades (migrations + this
  forward-compatible interchange format + content-addressed identity).
- **Q3:** FOCUS the tamper-evidence stack on signed-manifest auto-verify + **public-chain
  anchoring** (OpenTimestamps-style) + **witness cosigning**; **defer local fixity** (the
  background re-hash audit) to later. (Honest: witness cosigning needs peers/a federation;
  anchoring needs consented network.)
- **Q4 (keys/identity):** GOAL = automatic, no-PII, background, pseudonymous "journalist"
  anchor. RECOMMENDATION: do NOT derive the key from passphrase+timestamp; reuse the app's
  existing RANDOM hybrid signing keypair (Ed25519 + ML-DSA), public **fingerprint** = the
  pseudonymous identity, DB-creation timestamp = identity metadata, private key encrypted
  under the passphrase. (Awaiting nod.)
- **Q7:** the artifact + retrieval must cover BOTH Wikipedia dumps AND OpenStreetMap (OSM
  PBF), checksum-deduped.
- **Q8 (external-drive key location):** PENDING — signing keys travel-with-data vs on-host.

### Round 2 (2026-06-14)
- **Q4 CONFIRMED:** use the existing RANDOM hybrid signing key (no passphrase derivation).
  Collision is impossible by entropy (~256-bit) even if two users share a passphrase; the
  timestamp is identity metadata, not a uniqueness device.
- **Q5 = B:** build the FULL transversal audit/version substrate NOW — it is the shared base for
  federation/fixity (Item 9/21), translation derivations (14), and OSM versioning (22).
- **Q8 PROVISIONAL:** keys travel WITH the data, ENCRYPTED under the passphrase; finalize via a
  SEPARATE threat-model + cybersecurity audit.
- **Q3 SHARING MODEL (important):** PHYSICAL artifact hand-off only — NO user-to-user network
  connection. Signed-manifest verify + witness cosigning are OFFLINE (cosignatures ride
  physically-circulating artifacts, accumulating as recipients verify). Public-chain anchoring is
  the ONLY networked piece and is NOT user-to-user networking — it's an OPTIONAL, consented ping
  to a public timestamp notary.
- **Q3 anchoring RESOLVED (round 3):** public-chain anchoring is ON by default + a Settings toggle
  to disable; RESPECTS airplane mode (no call while offline; only when online via the ensureOnline
  consent); routed through the guarded fetcher (kill switch/proxy/Tor); sends ONLY the manifest
  hash root (no content); on Tails rides Tor.
