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

**The 2026-07-09 field event — ROOT-CAUSED from the diagnostics zip (analyzed 2026-07-09;
zip: ooalldiagnostics202607091306):**
- **The crash = OOM during a 21.6-hour continuous crawl pass.** The app died SILENTLY at
  07-05 21:32 (no error/traceback = external-kill signature); the last collect_perf sample
  seconds earlier shows **process RSS 10,599 MB on a ~10,237 MB VM**, 77,885 s into ONE
  crawl pass at 50-worker parallelism — memory accumulates across a marathon pass until
  the kernel OOM-killer fires. (Confirm: `journalctl -k | grep -i oom` in the VM.)
- **Writer-gate saturation measured:** 847,351 s cumulative write-wait across the pass
  (≈22% of all worker-time), 234,551 contentions, max single wait 438 s — the deferred
  COLLECTOR-path write-batching (strategy P1.3) now has its live justification. PROMOTED.
- **The "130 GB" is NOT the database: db_bytes = 11.7 GB** (268,241 articles / 3.06 M
  keywords / 20.9 M mentions). The other ~120 GB in the data folder is unidentified —
  suspects in order: ORPHANED PLAINTEXT STAGING from the crashed backup attempts (would
  also be an at-rest-encryption violation — check first), wiki dumps / OSM regions, a
  runaway `-wal`. Maintainer command: `du -sh <data_dir>/* | sort -rh`.
- **The backup crash ≈ OOM too:** the crashing path materializes the corpus (plaintext
  snapshot + in-RAM packaging) — guaranteed death at 11.7 GB on a 10 GB VM. The
  volumes+parity streaming path should already handle 11.7 GB; P0.1 = make streaming the
  ONLY path + clean any orphaned plaintext staging.
- **Unlock = 981 s measured (ONE post).** Most likely the ONE-TIME reinstall cost: newer
  code vs the 4-day-old DB (schema stamp behind head) ⇒ synchronous init_db ran
  migrations/self-heals incl. building the new expression index over 268 K articles
  through the codec, with zero progress UI; possibly + WAL recovery from the OOM kill.
  DISCRIMINATOR: if the NEXT unlock is fast → one-time (fix = visible progress + move
  index builds to a background job); if still slow → WAL/deeper.
- **Post-unlock slowness measured:** trending-windows **467 s/call ×6** (the in-memory
  rollup was STILL BUILDING at export — the D1 persisted-columnar promotion made flesh);
  map-coverage 24 s; /latest 12.6 s; the diagnostics `/all` export itself ran **36+ min**
  and repeatedly blocked the event loop (Item 10 job-ify confirmed).
- **Healthy:** zero counter drift, zero dangling mentions, 0 locked errors this session;
  the wave-7 alert cache works (p50 25 ms, was 23.7 s). FLAGS: an FTS present/absent
  probe contradiction (verify search works; re-index heals), and 71% of 3.06 M keywords
  are single-article (the segmenter ruling keeps climbing).
- **12:14-boot follow-up logs (same day, analyzed 2026-07-09):** unlock **1,645 s** on the
  next boot ⇒ the one-time-migration hypothesis is REFUTED (P0.4 escalated, see the row);
  trending-windows 62 calls / 3,286 s (the TTL rollup rebuild churns); NEW #1 slow query =
  the map/ring country GROUP BY at ~150 s/call (⇒ P1.11 flip on the existing map serve);
  counter-reconcile 86–104 s/pass at 3.06 M keywords (⇒ P1.12); the integrity FTS-absent
  verdict co-occurred with its own deadline interrupt (supports the D4 probe-artifact fix,
  shipped #600). GOOD: full-curve Heaps **β = 0.8156** (r²=.998; the 0.95 was a subset
  artifact — the vocabulary IS saturating), entity precision 98.6%, selftest 43/43, FDR
  spine 10/10, dated coverage back to 1995 (cross-time recall real). The full per-language
  keyword export (61 files) is in hand for the segmenter/stoplist track when ruled.

---

## P0 — DATA SAFETY AT SCALE (blockers; ATTENDED sessions — a wrong autonomous change here is itself the data-loss risk)

| # | Item | State | Notes / acceptance |
|---|------|-------|--------------------|
| P0.1 | **Backup at 100 GB+** (Item 9, escalated by the 2026-07-09 crash) | **ENGINE SHIPPED (Round 2 ZETA, 2026-07-09, draft PR)** — awaiting the maintainer's ONE live validation (the v0.2.0 gate item) | The oo-volumes-2 streaming engine (`src/backup/stream_backup.py`) replaced the container: NO plaintext corpus snapshot (the corpus streams as its at-rest SQLCipher bytes inside one writer-gate window after a WAL checkpoint — decrypt-the-world is gone), NO zip, bounded RAM end to end **including parity** (the old Reed-Solomon loaded the WHOLE volume set into RAM — itself an OOM at 11.7 GB on the 10 GB VM; now banded, (M+1)×32 MiB). INCREMENTAL: per-volume plaintext checksums, only changed volumes re-emit (checksum, never size/mtime), passphrase-bound reuse. RESUMABLE: an interrupted run leaves NO final manifest (never mistakable for a good backup) and the next run completes it against the CURRENT state in one gate window; a refresh never overwrites the previous complete set (run-unique volume names, atomic manifest swap, post-finalize GC). VERIFY: signed manifest + every volume checksum without decrypting; with the passphrase a full hash-sink decrypt — as a job (`POST /api/backup/v2/volumes/verify`) + pause/resume endpoints. Acceptance measured in-dev via the GAMMA gate (`acceptance_gate`, asserts corpus **encrypted**) on an encrypted synthetic corpus at the sandbox's max tier (~6 GB; 30 GB disk cap — the 50–100 GB tier needs an operator machine); interruption+resume and verify proven there and unit-pinned. REMAINING: the maintainer's live-corpus validation run; UI wiring for verify/pause + the paused state label (jobs surface passes them through). |
| P0.2 | **Restore/import at scale** | ENGINE HALF SHIPPED (with P0.1) — full-scale proof still gated on an operator run | The volume restore now streams member-by-member (bounded RAM), disk-preflights staging (members + encrypted-corpus conversion + the merge's working copy), converts the SQLCipher corpus/custody members with the corpus's OWN passphrase (`corpus_passphrase` → live key → backup passphrase; wrong keys fail loudly), and hands the standard StagedArtifact to the UNCHANGED additive-only merge. Round-trip + parity-recovery + tamper/traversal refusals test-pinned; the restore phase of the GAMMA bench exercises it at the synthetic tier. Acceptance unchanged: the maintainer's real 100 GB backup imports on a fresh install. |
| P0.3 | **Crash root-cause + crash-safety** (Item 11) | ROOT-CAUSED 2026-07-09 (OOM in a 21.6-h continuous crawl pass; RSS 10.6 GB > VM RAM; silent external kill). **COLLECTOR FIX SHIPPED 2026-07-09 (ETA Round-2, draft PR)** | Shipped: (a) per-pass accumulation INSTRUMENTED (per-sample component gauges + the RSS curve on every pass summary in collect_perf) and BOUNDED (robots-cache cap; politeness-first last-request eviction; trafilatura reset_caches + gc + glibc malloc_trim between passes, measured before/after); (b) PASS RECYCLING — `OO_PASS_BUDGET_MINUTES` (default 60; 0=off) + optional `OO_PASS_MAX_SOURCES` bound one pass; the un-run remainder DEFERS and runs FIRST next pass (ordering, never exclusion; exactness pinned: processed + deferred == all); (c) RSS MEMORY GUARD (`src/scheduler/memguard.py`) — measured psutil trip/resume latch with hysteresis both ways (defaults: RSS ≥ 85% of RAM or avail ≤ 256 MB for 3 consecutive samples; missing readings never count), pauses collection LOUDLY (phase `paused-low-memory` + `status.memory_guard` + perf samples), resumes on measured recovery or user action (start / run-now / POST /api/scheduler/memory-guard/resume), never touches the writer gate; (d) WAL checkpoint(TRUNCATE) between passes via write_lock(), measured, honest busy=1 partial under an active reader. Soak-verified (src/testing/collect_soak.py, zero-network): flat RSS across recycled passes; guard proven pause-not-die on injected fake readings. REMAINING: the maintainer's live-run validation (a v0.2 gate item). DispVM ruling stands. |
| P0.4 | **Unlock at scale — ESCALATED** (60 s @ 2.28 GB in the 07-08 ledger; **981 s** then **1,645 s (27.4 min)** on consecutive 2026-07-09 boots) | The one-time-migration hypothesis is **REFUTED** (12:14-boot logs): the cost RECURS every boot and grew; the schema stamp did not advance between boots. Prime suspects now: (i) WAL recovery after unclean shutdowns (free test: stop via the in-app Shutdown button, then time the next unlock), (ii) corpus-scaled synchronous init_db work. | The instrumentation to name it is NOW MERGED (#596 per-phase timing + wal-bytes-before-open; #599 honest elapsed-clock UI): the maintainer UPDATES the install → the very next boot's export names the phase. GAMMA's G2 unlock-wall benchmark reproduces it in dev against a synthetic ~12 GB corpus. Acceptance unchanged: steady-state unlock < 2 s at 100 GB; any long phase visible and honest. |
| P0.5 | **Scale test harness** | **SHIPPED #601 (GAMMA G1/G2/G3)** — synthetic corpus generator (Base.metadata schema-parity, deterministic seed, synthetic marker) + benchmark runner (unlock wall · backup wall + peak RSS · restore round-trip · hot-endpoint p95s · WAL growth) + a CI smoke tier; the 50–100 GB tier is operator-run via scripts/ | The benchmark report format is the ACCEPTANCE CONTRACT for Round 2 (ZETA/ETA below). Post-merge audit pending. |

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
| P1.4 | `/api/insights/latest` (measured 40 s @ 268 K) | **SHIPPED #600 D1** (near-dup bounded via content-prefix fold) — re-measure on the next field export |
| P1.5 | **Storage-composition diagnostic** — per-table bytes (dbstat) so we know what the 130 GB IS; informs P0.1/P1.6/P1.5-hygiene | **SHIPPED (THETA R2)** — `src/monitoring/storage.py` + `GET /api/diagnostics/storage-composition` (+download) + debug-bundle member + the /all zip. HONEST LIMIT (probed 2026-07-09): the **sqlcipher3 build ships WITHOUT dbstat**, so on the encrypted live store the report degrades to `{available:false, reason}` with the PRAGMA-level totals (db_bytes/free_bytes) still reported; plaintext/stdlib stores get the full per-table/per-index split. A dbstat-enabled sqlcipher3 build is the follow-up if the split is wanted on encrypted stores. |
| P1.6 | **Corpus-epoch mechanism** (`derived_meta` + `bump_corpus_epoch`) — prerequisite for persisted INCREMENTAL rollups (designed in 5A-bis D3) | **SHIPPED (row was stale; corrected 2026-07-09 THETA R2)** — `src/analytics/corpus_epoch.py` + migration `e7f8a9b0c1d2` (derived_meta) + `bump_corpus_epoch` wired into `reindex_articles`/`reindex_all_batch`/`prune_orphan_keywords` (verified in-tree). NOT yet wired into the restore-merge (src/backup) — the one residual mutator; over-bumping is harmless, a missed bump is bounded by the serves' backstop TTL. The epoch now ALSO gates the in-memory serves' change-gated refresh (P1.10). |
| P1.7 | **5 TB architecture verify-before-trust review** — single-file SQLCipher at 5 TB (page cache, VACUUM infeasibility, backup windows, single writer) validated against `docs/design/DATA_ARCHITECTURE_SKELETON.md` (it anticipated 1000×). Constraint carried: **cross-time recall is sacred** — no partitioning that makes old data second-class. Design session, then measured slices. | OPEN |
| P1.11 | **FLIP ON the D4 map serve** (`map_serve.enabled: false` today): the 12:14 logs' #1 slow query is the map/ring country GROUP BY — **748 s total, ~150 s/call, max 211 s** — plus map_data at 146 s median; the opt-in serve already exists (Wave 4) with bind-aware fallback. Measured justification to default it on. | **SHIPPED (THETA R2)** — `map_serve.serve_enabled()` now mirrors rollup_serve's tri-state (unset = auto-on when duckdb is available; `OO_COLUMNAR_MAP_SERVE=0` forces off / `1` forces on); bind-aware fallback-to-live + `basis` disclosure unchanged, forced-off is the byte-identical live path (test-pinned). |
| P1.12 | **Background maintenance joins the job/deadline regime**: the counter-reconcile scans (86–104 s/pass) + the orphan-prune count (32 s) are heavy at 3.06 M keywords — keep freshness-gated, add deadlines + off-peak scheduling. | **DEADLINE HALF SHIPPED (THETA R2)** — `reconcile_keyword_counters` + `prune_orphan_keywords` now run in id-ordered slices under a soft budget (`OO_RECONCILE_BUDGET_S`/`OO_PRUNE_BUDGET_S`, default 30 s) with a RESUMABLE watermark persisted in `derived_meta`; partial passes are DISCLOSED (`complete:false` + the envelope stays `estimated` until a sweep completes — skeptic-pinned in tests/test_maintenance_deadline.py); the 32-s whole-table count is gone (per-slice covering-index scans). Freshness gates stay. REMAINING: off-peak scheduling (scheduler territory — ETA). |
| P1.8 | **Collector-path write batching** — the writer gate measured 847 K s cumulative wait / 22% of worker-time across the 21.6-h pass (the long-deferred strategy-P1.3 item now has its live justification; the `index_article(commit=False)` primitive already exists) | **SHIPPED 2026-07-09 (ETA Round-2, draft PR):** `src/ingest/batch.py` — fetch/extract/link-extraction OUTSIDE any gate (HTML dropped at stage time; buffer bounded by count AND bytes), then ONE write transaction per batch via `index_article(commit=False)` + the proven rollback-then-redo-per-article fallback (zero loss pinned: Nth-article collision, death-between-commits, live contention race with exact counters). Measured: 8-article feed ~16 gate windows → 1. `OO_COLLECT_COMMIT_BATCH` (default 8; 0 = the legacy path exactly). BONUS ROOT-CAUSE found while verifying: feed bookkeeping written BEFORE the article loop was AUTOFLUSHED by the loop's first dedup SELECT — acquiring the write gate and HOLDING IT ACROSS ARTICLE FETCHES (the 438 s max-single-wait signature); fixed (bookkeeping after the loop + committed; gate-probe tests pin both paths + the sequential shared-session case). |
| P1.9 | Job-ify the diagnostics `/all` export (Item 10; measured 36+ min blocking the loop) | **SHIPPED #600 D2** (+ stale-.part sweep hardening) — EPSILON's UI wiring for the job flow is the remaining half if not in #599 |
| P1.10 | trending-windows cold path (467 s/call; the 12:14 logs show 62 calls / 3,286 s total — the 15-min-TTL rebuild over 20.9 M mentions CHURNS) | **#600 D3 (stale-but-disclosed serve) + CHANGE-GATED REFRESH SHIPPED (THETA R2)** — rollup_serve + map_serve rebuild on CHANGE, not on a timer: corpus epoch (cross-connection re-index/prune) OR the append id tails (ingest appends without bumping the epoch — a pure epoch gate would freeze the rollup during collection, test-pinned in tests/test_serve_change_gate.py); old TTL env vars now bound the MIN rebuild interval; a LONG backstop TTL (`OO_COLUMNAR_SERVE_BACKSTOP_S`/`OO_COLUMNAR_MAP_SERVE_BACKSTOP_S`, 1 h) covers token-invisible change classes (cascade deletes, in-place backfills); staleness stays disclosed (basis.as_of/stale). REMAINING: the D1 persisted store (Ruling-gated #2) so the rollup survives restarts. |

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
4. ~~Version bump 0.1.0 → 0.11.0~~ **DECIDED 2026-07-09: the next cycle is 0.2 (supersedes
   the 0.11 idea), and v0.2.0 GATES ON THE P0 SCALE SET (option A)** — backup-at-scale
   verified on the live corpus + the collector OOM fix + unlock-at-scale. "0.2 = the
   version that survives a 100 GB field run." Mechanics mirror the 0.09→0.1 flip
   (#547 batch: pyproject 0.1.0→0.2.0 · tag v0.2.0 with a WATCHED-green CI run · the
   maintainer renames the default branch 0.1→0.2 · CLAUDE.md cycle refs rewritten in the
   SAME PR). HARD GUARD: never flip while parallel sessions are in flight on origin/0.1
   (the #548 stale-base revert precedent) — execute in a quiet window after the P0 gate
   passes. Tracked as task #10 in the session tracker.
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

## ROUND 2 — the next two autonomous sessions (spec, so any future session can emit the prompts)

Both follow the proven contract: read CLAUDE.md in full first · file-disjoint territories ·
commit-per-item + `git show HEAD --stat` all-files check · FULL suite per item (py3.13 .venv)
· mypy 127 / ruff F,B / bandit -ll / single alembic head · mid-run + pre-push rebase onto the
fresh tip · pre-push NEGATIVE-SPACE skeptics run to completion BEFORE push (two-connection
shape for any cache) · shipped.csv append-only · draft PR onto the current cycle branch.

- **ZETA (backend · P0.1/P0.2 backup rework):** territory src/backup/** + src/safety/crypto.py
  + new tests. Kill every whole-corpus materialization (the plaintext `snapshot_sqlite` staging
  + in-RAM zip paths); stream the SQLite backup API into the existing volumes+parity writer;
  INCREMENTAL = re-emit only changed volumes (per-volume checksums exist); a `verify` command;
  resumable; server-side only. ACCEPTANCE = GAMMA's benchmark report (#601 format, honesty
  fixes #604) at a synthetic 50–100 GB corpus, under the AUDIT CONDITIONS: (a) the corpus is
  ENCRYPTED and the gate ASSERTS `report.corpus.encrypted == true` (a plaintext run omits every
  SQLCipher codec cost — the report now carries a loud plaintext_caveat, but the gate must
  check); (b) the OFFICIAL backup number comes from a fresh-process `--phases backup` run (the
  full 5-phase run's earlier phases inflate process-lifetime ru_maxrss and can mask a brief
  backup RSS spike); (c) bounded peak RSS, interruption + resume, verify passes, honest
  wall-time; restore round-trip additive-merge-sacred. The maintainer runs ONE live validation
  at the end (the only attended step; it is the v0.2.0 gate item).
- **ETA (backend · P0.3 collector + P1.8):** territory src/scheduler/** + src/ingest/** +
  src/monitoring/collect_perf.py + new tests. (a) find + bound the per-pass memory
  accumulation (the 21.6-h pass reached RSS 10.6 GB); (b) PASS RECYCLING (bound pass
  duration/work); (c) an RSS MEMORY GUARD that pauses collection loudly before the OOM-killer;
  (d) WAL checkpoint hygiene under multi-day writes; (e) P1.8 collector write-batching (the
  `index_article(commit=False)` primitive exists; 22% of worker-time measured blocked).
  ACCEPTANCE: a long synthetic collect run (GAMMA harness) with flat RSS + the guard proven to
  pause-not-die; zero-loss batching (the proven `_redo_committed` fallback pattern).
- Small riders for whichever session fits: P1.11 flip on the D4 map serve (bind-aware fallback
  intact); the `noprobe` fallback cache key lacks a bind qualifier (probe-failure path only,
  insights.py); the 30-min `pollJobStatus` ceiling can toast a "0" tally for a still-running
  job (app.js); P1.12 reconcile deadlines.

## OPERATIONAL (maintainer's machine — refreshed 2026-07-09 after the 12:14 logs)

1. **UPDATE THE INSTALL** (pull the current cycle branch) — the single highest-value action:
   the next boot then self-reports the 27-min unlock's per-phase timing + WAL-size-before-open
   (#596) and the data-dir inventory that names the ~120 GB incl. any orphaned PLAINTEXT
   backup staging (#596 + the #599 Settings panel). Replaces every earlier terminal ask.
2. Free WAL discriminator: stop the app with the in-app SHUTDOWN button before a restart —
   next unlock fast ⇒ WAL recovery was the recurring cost; still ~20 min ⇒ corpus-scaled init.
3. Keep the exported per-language keyword log (the 61-file zip) — it is the input for the
   segmenter/stoplist session once the bundled-artifact ruling is made; re-exportable but slow.
4. Interim backup stays: app stopped → filesystem-copy the data folder (encrypted at rest).
5. The graded IR gold set + the two scale-critical rulings (segmenter artifact · httpfs
   bundling) whenever ready.

## SEQUENCE (the short version)

1. **Now:** logs land → root-cause the crash/unlock/backup trio → P0.1–P0.4 as attended
   sessions (P0.1 backup first: until it ships, the corpus has no safe in-app copy path).
2. **Parallel (autonomous):** finish ALPHA → combined health-check → the surfacing session →
   P1.4/P1.5/P1.6 as the next wave.
3. **Maintainer:** the two scale-critical rulings (segmenter, httpfs) whenever ready — they
   unblock more value than any further autonomous wave.
4. **Then:** the P1.7 5 TB design review, informed by the storage-composition numbers, sets
   the architecture for everything after.
