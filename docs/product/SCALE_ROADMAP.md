# Scale & Stability Roadmap — consolidated 2026-07-09

**THE MANDATE (maintainer, 2026-07-09, verbatim intent):** a live test grew the corpus to
**~100–130 GB in 4–5 days**; the app must therefore be designed to handle **5 TB databases**
with proper indexing, staying **snappy** — "snappiness / responsiveness is quite important,
otherwise it will slow or block user adoption, and this app is useless if it is not used."
**Resolving the large-database hiccups is THE priority: at 100 GB+ we cannot even back the
corpus up (the backup tool crashes the app), so we cannot test import either.**

This doc consolidates every open item from: the field-test ledgers
(`docs/product/field-test-2026-06-14/`, `-2026-06-15/`, `-2026-07-08/`), the CLAUDE.md Open
queue, the wave-1→8 parallel-session audits, and the 2026-07-09 field event (4-day run,
app self-stopped, backup crash, slow unlock). CLAUDE.md remains the ruling ledger; this is
the working priority list. Update rows here as items close.

**The 2026-07-09 field event (root-cause PENDING the diagnostics zip the maintainer is
exporting):** 4+ day continuous run → app stopped on its own hours before the maintainer
returned → DB ~130 GB → backup tool crashes the app → app reinstalled with the preserved
data folder → unlock very slow. First data questions for the logs: what stopped the app
(OOM death-spiral?); the `-wal` file size before unlock (WAL-replay hypothesis); what is
IN the 130 GB (per-table composition); where the backup died (plaintext-snapshot decrypt /
RAM / disk).

---

## P0 — DATA SAFETY AT SCALE (blockers; ATTENDED sessions — a wrong autonomous change here is itself the data-loss risk)

| # | Item | State | Notes / acceptance |
|---|------|-------|--------------------|
| P0.1 | **Backup at 100 GB+** (Item 9, escalated by the 2026-07-09 crash) | OPEN — top priority | Root-cause the crash from the logs. Kill every whole-corpus materialization on the path (the disposable **plaintext corpus snapshot** = decrypt-the-world, dead at scale; the in-RAM zip paths died at 2 GiB already). Target: **server-side, streaming, bounded-RAM, RESUMABLE, VERIFIABLE, INCREMENTAL** — the volumes+parity engine already checksums per volume, so re-emit only changed volumes (natural incremental). No browser delivery of the artifact. Acceptance: a 100 GB backup completes with bounded RAM, survives interruption + resumes, `verify` passes, measured wall-time reported honestly. |
| P0.2 | **Restore/import at scale** | OPEN — untestable today | Once P0.1 produces a 100 GB artifact: staged, resumable, disk-preflighted restore; the additive-merge stays sacred. Acceptance: the maintainer's real 100 GB backup imports on a fresh install. |
| P0.3 | **Crash root-cause + crash-safety** (Item 11) | OPEN — logs pending | Why did the app stop after ~4 days? (Prime suspect: the request/memory death-spiral — ALPHA A1's concurrency cap + deadlines land the structural fix; the logs confirm or refute.) Add a memory guard; **WAL checkpoint hygiene** under multi-day continuous writes (a runaway WAL is a crash suspect AND the unlock suspect); prove crash-mid-backup can never corrupt the live DB. DispVM ruling stands: durability must work in deliberately-ephemeral VMs. |
| P0.4 | **Unlock at scale** (re-opened; first fixed in PR #550, re-measured 60 s @ 2.28 GB in the 07-08 ledger Item 8, now much worse at 130 GB) | OPEN | Suspects: (a) WAL replay inside the synchronous `init_db`; (b) `init_db` self-heals assuming "fast on an existing store" breaks at scale; (c) the "backgrounded" upkeep (ANALYZE/COUNT/warm) saturating the single worker so the app is unusable even after unlock returns. Acceptance: unlock returns < 2 s at 100 GB; the UI is responsive during upkeep; upkeep is deferrable/skippable and never blocks interaction. |
| P0.5 | **Scale test harness** | OPEN — the structural gap | Everything so far was verified at MB–GB scale; 100 GB behavior was discovered in the field. Build a synthetic large-corpus generator + a scheduled benchmark suite (unlock time, backup wall, hot-endpoint p95s, WAL size under write load) so the next scale cliff is found in dev. |

## P1 — SNAPPINESS AT SCALE (adoption-critical)

**The rule at 5 TB: NO full scan on any hot path — everything index-, counter-, rollup- or
cache-served; every heavy operation is a visible background job; the derived layer stops
being optional** (an in-memory rollup rebuilt per boot dies at this scale ⇒ the **D1
persisted encrypted columnar store is PROMOTED** — still gated on the per-OS httpfs
crypto-extension bundling decision, see Ruling-gated #2).

Done (evidence-verified): expression index on `coalesce(published_at,created_at)` (#588,
735 s of scans → index-only) · alert-strip memo cache, bind-aware (#589, 24 s → sub-ms) ·
2-hop graph bounded + deadline, never 503 (#591) · rollup serve auto-on for
trending/trending-windows · single-writer gate · covering mention indexes · FTS optimize ·
batched commits.

| # | Item | State |
|---|------|-------|
| P1.1 | ALPHA A1: **server deadlines + concurrency cap + single-flight** (the death-spiral structural fix) | IN FLIGHT |
| P1.2 | ALPHA A2: **job-ify heavy sync handlers** (enrich-source-types 8.5 min · governments 2.9 min · backfill · server-locations) | IN FLIGHT |
| P1.3 | ALPHA A3: **`count(*)` from maintained counters** (724 ms × 172) | IN FLIGHT |
| P1.4 | **`/api/insights/latest` 59 s** (near-dup content reads defeat the scan cap — SQLCipher decrypts) | OPEN |
| P1.5 | **Storage-composition diagnostic** — per-table bytes (dbstat) so we know what the 130 GB IS; informs P0.1/P1.6/P1.5-hygiene | OPEN, small, high-leverage |
| P1.6 | **Corpus-epoch mechanism** (`derived_meta` + `bump_corpus_epoch` wired into re-index/prune/restore) — prerequisite for persisted INCREMENTAL rollups (designed in 5A-bis D3, not built) | OPEN |
| P1.7 | **5 TB architecture verify-before-trust review** — single-file SQLCipher at 5 TB (page cache, VACUUM infeasibility, backup windows, single writer) validated against `docs/design/DATA_ARCHITECTURE_SKELETON.md` (it anticipated 1000×). Constraint carried: **cross-time recall is sacred** — no partitioning that makes old data second-class. Design session, then measured slices. | OPEN |
| P1.8 | Whatever the 2026-07-09 diagnostics zip surfaces (new measured hot spots) | PENDING LOGS |

**Definition of snappy (acceptance, measured via the latency reservoir + the P0.5 bench):**
every interactive endpoint p95 < ~500 ms at 100 GB; unlock < 2 s; no UI action blocks > 1 s
without becoming a visible job; background work never freezes the UI.

## P1.5 — STORAGE HYGIENE (growth control; 130 GB in days ⇒ growth itself is a scale bug)

- **Keyword junk is now a STORAGE item, not just quality:** Heaps β = 0.95 (zh 46 K + th
  21 K + ja 12 K junk keywords from missing segmentation; ko/vi/mr stoplist gaps). The
  zh/ja/th segmenter ruling (Ruling-gated #1) escalates. ALPHA A5 checks the vi wiring.
- **WAL/checkpoint policy** under continuous collection (see P0.3).
- **Near-dup content growth** (wire reprints stored whole) — quantify via P1.5 diagnostic,
  then decide: the tiered-retention/eviction design exists (designed-not-built, default-off,
  WARC-gated) — a ruling when the numbers are in.
- Incremental-vacuum posture at scale (full VACUUM is infeasible at 5 TB).

## P2 — QUALITY & FEATURES (the condensed backlog; autonomous-safe unless marked)

1. **Surfacing session** for ALPHA's new backend (job statuses, busy/429 handling, counter basis) once ALPHA merges.
2. **BETA shipped (#593, merged):** world-map subtabs + story lenses · map-staleness chip · poll-transparency form · i18n sweep — pending my combined health-check with ALPHA.
3. Item 5 Agenda: flood article-extracted dates into the agenda (backend exists); the global election/summit calendar needs SOURCED entries (semi-attended).
4. Item 3: Wikidata-discovery auto-pick countries + i18n.
5. Home "Latest" S3: per-content-type default thresholds (calibration data exists) — pairs with P1.4.
6. Translation coverage 15.2%: corpus-driven ring growth (`generate_wikidata_rings.py --from-log`, networked/operational) + evaluate the bundled common-vocabulary idea.
7. fa/hu date recall re-measure on the next export (post #590+#592).
8. `event_imports` native UNION-merge retiring the JSON side-file (the D1 follow-up Wave 5 deliberately deferred).
9. Dead-UI-code cleanup (needs a browser-verified pass; the interleaved-shared-helper hazard).
10. **3D keyword explorer** (maintainer flagship — large, own dedicated wave; needs backend spread-metrics).
11. Small riders: poll-cache `_decorate` deepcopy + #591 cosmetic nits (ALPHA A6, in flight).

## RULING-GATED (maintainer decisions — nothing moves until picked)

1. **zh/ja/th segmenter + ko/mr stoplist artifacts** — which library/wordlist to vendor + license. NOW SCALE-CRITICAL (storage), not just quality. Highest-value single ruling.
2. **httpfs crypto-extension bundling** (per-OS) — unblocks the D1 persisted encrypted columnar store, which the 5 TB target effectively requires. Second-highest.
3. Item 7 rare earths source (USGS supply data recommended / proxy / paid / defer).
4. Version bump 0.1.0 → 0.11.0 scope (version-only recommended vs full branch flip).
5. Keyword hover-stats Slice 2 (which stats).
6. Lemmatization default-on (needs the gold-set measure).
7. Retention/eviction posture (after the P1.5 storage numbers are in).

## OPERATIONAL (maintainer's machine)

- The **diagnostics zip** now exporting (root-causes P0.3/P0.4/P0.1). Plus: the `-wal` file
  size before the next unlock (one number tests the WAL hypothesis).
- Interim backup of the 130 GB corpus: app stopped → filesystem-copy the data folder
  (SQLCipher-encrypted at rest) — currently the ONLY safe copy path.
- "Clean up keywords" re-index on the live corpus — NOTE: at 130 GB this is a multi-hour+
  job; it is pausable/persisted (the reindex job), but schedule it deliberately.
- The graded IR gold set (unlocks BM25F default + lemmatization measures).
- Rollup benchmark + fresh diagnostics after ALPHA lands (measures waves 7–9 on real data).

## SEQUENCE (the short version)

1. **Now:** logs land → root-cause the crash/unlock/backup trio → P0.1–P0.4 as attended
   sessions (P0.1 backup first: until it ships, the corpus has no safe in-app copy path).
2. **Parallel (autonomous):** finish ALPHA → combined health-check → the surfacing session →
   P1.4/P1.5/P1.6 as the next wave.
3. **Maintainer:** the two scale-critical rulings (segmenter, httpfs) whenever ready — they
   unblock more value than any further autonomous wave.
4. **Then:** the P1.7 5 TB design review, informed by the storage-composition numbers, sets
   the architecture for everything after.
