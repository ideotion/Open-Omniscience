# Autonomous session brief — throughput scaling (2026-07-24, session C)

**You are the executing session.** This is the operating manual for building the scraping/download
throughput work toward ≥10×. The WHY + design of record is
[`docs/design/SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md`](SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md)
— read it first, then execute the slices below. This brief is the HOW: exact files, anchors,
setting names, test names, invariant guards, and gates. Written to be executed by a Sonnet-class
model without ambiguity.

Sibling briefs (do NOT touch their scope): `AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md`
(airplane-gate split, lang-detect, governments, law, imports, hazards) and `…_B_AI_STACK.md`
(vLLM/dual backend, triage/tag runs). Those run first per the A16 ruling. This brief composes with
the 2026-07-23 field-feedback workflow (S4 series) — S-B here is the natural continuation of S4.1.

---

## 0. Working mode (read every session, non-negotiable)

- **Draft-PR-only. Nothing auto-merges.** One draft PR per slice onto `main`, small and additive.
  Branch prefix `claude/oos-c-*`. The maintainer reviews and merges.
- **Staleness guard FIRST, every slice.** The engine moved four times in the week before this brief.
  Before editing, re-verify every anchor below against the live tree (`grep`/read). If an anchor
  moved or a slice is already shipped, VERIFY-AND-MARK, do not rebuild (the 06-audit lesson). Line
  numbers here are as of `main` @ `df8a9b0`; treat them as hints, re-derive before trusting.
- **Skeptics-before-push with the mandatory NEGATIVE-SPACE lens** on every honesty/data-safety/
  correctness-critical slice (marked ⚠ below): generate should-be-empty / should-never-happen inputs
  and assert them, not only the happy path. Reproduce a claimed defect live before trusting a fix.
- **House gates, every slice, all green before push** (these commands are verified-current):
  - `ruff check --select=F,B --extend-ignore=B008 src/ tests/`
  - `MYPY_BASELINE=127` ratchet — `python3 -m mypy <changed files>` must add **0 new** errors
    (a red count may be pre-existing baseline errors merely line-shifted; confirm with a git-stash
    before/after diff, per the errorlog.py lesson).
  - `bandit==1.9.4 -r src/ -ll -q` → exit 0 (add `# nosec Bxxx - <reason>` per the merge.py
    convention only when a constant-fragment SQL trips B608).
  - `python scripts/i18n_report.py --min 100` when any user-facing chrome string is added (a NEW
    `tf()` template key needs all 12 locale files or `--min 100` reddens; un-keyed English-fallback
    diagnostics/settings strings need no key — match the adjacent panel's convention).
  - `alembic check` + `alembic upgrade head` when a schema column is added (pick a RANDOM 12-hex
    revision id, `grep` the versions dir to confirm it is free, get the real head from
    `python3 -m alembic heads` — never a regex scan; the collision→"Cycle detected" lesson).
  - Full `pytest -q` after each push-ready slice (a full run catches cross-test pollution + the
    utf8-encoding guard that a single-file run misses).
- **Every projected multiplier is an estimate until measured.** Land each slice with its named
  collect_perf / Library-graph metric; never report a multiplier as achieved without the before/after
  bench (the maintainer's 8-core/20 GB machine). No fabricated pass — a "not-measurable-here" is
  honest, a claimed number without the measurement is not.
- **The ethics non-options (doc §5) outrank speed at every slice.** Per-host politeness (one
  in-flight + ≥1 s + Crawl-delay), robots fail-closed, honest UA, no evasion, no transport downgrade,
  no third-party proxy/scraping services, no headless fleet. If a slice would touch any of these,
  STOP and re-read — you have the wrong shape.
- Frontend is BROWSER-UNVERIFIED here (no headless harness): ship conservative + flagged
  ("browser-unverified, needs click-through"), node --check + an invariant guard, defensive empty
  states (fork-3 / Q6a). The maintainer's click-through is the ship gate for any UI.

---

## Phase 1 — duty cycle + crawl-by-default (hardware-independent, safe, high value)

### C1 — S-B: the housekeeping lane ⚠(concurrency)
**Goal:** move the serial post-pass network ride-alongs off the pass thread so pass N+1 can start
while they run. Duty cycle 48→90 %+ ≈ ×1.5–2 (measured basis, doc §2).

- **Anchor:** `src/scheduler/runner.py:1258-1454` — the serial post-pass tail. `_refresh_briefing_async`
  (`runner.py:1166-1211`) is the EXACT pattern to generalize (S4.1: own daemon thread, fresh
  `session_scope`, non-overlapping via a lane lock, task-manager-visible via `src.monitoring.tasks`).
- **Build:** one dedicated background lane thread with its own fetcher/session that runs the network
  ride-alongs (calendar auto-import, market CSVs, law auto-track, world-discovery advance,
  qualification advance, hazards). The pass tail becomes: register the lane task, kick it, return.
  Non-overlapping (a second kick while running is a no-op, never queued — the briefing pattern).
  Airplane-pausable; memguard pauses it first.
- **Preserve:** the qualification/world-discovery ride-alongs currently share the pass session +
  fetcher (`runner.py:1357-1388`) — give the lane its OWN session/fetcher so "never two writers on
  one cursor" still holds. DB-writer arbitration rules unchanged.
- **Tests:** `tests/test_scheduler_housekeeping_lane.py` — the lane runs off the pass thread (a blocked
  ride-along does not delay the next pass's fetch dispatch); non-overlapping (a second kick while
  running is skipped, allowed again once finished); a raising ride-along never crashes the thread AND
  releases the lock; the lane task is visible in `tasks.snapshot()` while running. Invariant guard in
  `test_repo_invariants.py`: the tail calls only the async kickoff, no direct serial ride-along call.
- **Metric:** collect_perf fetching-vs-gap share (already logged).

### C2 — S-B: wire KindLadder as the lane scheduler
**Goal:** implement the ruled 2026-06-13 bandwidth priority ladder with the shipped 2026-07-13 core.

- **Anchor:** `src/ingest/tor_throughput.py` — `KindLadder` (`:36-82`), currently unwired (only the
  selftest registry references it, `src/monitoring/recursive_loop.py:51`).
- **Build:** the lane (C1) draws its next ride-along kind from `KindLadder.next_kind(pending)` with
  per-kind weights (RSS collection keeps top priority and runs on the main pass; the lane's kinds —
  calendar/law/markets/discovery/qualification/hazards/**crawl-supplement (C3)**/**backfill (C-later)** —
  share the lane's headroom by the ladder's starvation-free stride schedule). Weights + floors are
  constants first (a settings knob later); the crawl/backfill rungs are the LOWEST.
- **Tests:** `tests/test_kind_ladder_wiring.py` — the lane serves kinds in ladder proportion; a
  zero-weight kind is a no-op; no kind starves (the ladder's own property, re-asserted at the wiring
  level).

### C3 — §8: crawl-by-default (the hybrid budgeted rung) ⚠(new fetch behaviour)
**Goal:** crawling ON by default as a bounded supplement, NOT a mode flip (doc §8).

- **Anchors:** `src/scheduler/settings.py:66` (`mode`), `:90-103` (the ride-along settings pattern to
  mirror), `:242-269` + `:294-345` (parse/coerce/update paths); `src/ingest/crawl.py`
  (`crawl_source`, `CrawlConfig.normalised`); `src/scheduler/runner.py:507-521` (`_process_source`
  mode branch).
- **Build:**
  1. Add `crawl_supplement: bool = True` and `crawl_per_pass: int = <default>` to `AppSettings`
     (mirror `world_discovery_per_pass` exactly: docstring stating the ruling, `_coerce_int` range,
     the parse + `_ranged` update wiring). `0` disables. Hardware-aware via the power-profile table
     (§6e — add a `crawl_per_pass` resolver to `src/config/power_profiles.py` following
     `dump_concurrency()`).
  2. Additive nullable `Source.last_crawled_at` column (migration + `ensure_*` boot self-heal — the
     established pattern, e.g. `ensure_article_ip_columns`; NULL sorts first for rotation).
  3. After the RSS fetch stage in the pass (or on the C1 lane's lowest rung), select `crawl_per_pass`
     qualified sources ordered least-recently-crawled + feedless-first, and run `crawl_source` on each
     with a tight `CrawlConfig` (small `max_pages`, existing depth/same-host bounds). Stamp
     `last_crawled_at`. The `mode="crawl"` full-crawl selector STAYS unchanged (orthogonal).
- **Safety (assert in tests):** the supplement adds NO new fetch path — it calls `crawl_source` which
  routes through the ONE `EthicalFetcher` (robots fail-closed, per-host one-in-flight + ≥1 s, honest
  UA, same_domain_only, dedup). Rotation covers every source (ordering ≠ exclusion).
- **Tests:** `tests/test_crawl_supplement.py` — default ON (`crawl_supplement` True by default);
  `crawl_per_pass=0` disables (no crawl call); rotation picks least-recently-crawled + feedless-first;
  `last_crawled_at` is stamped; NEGATIVE-SPACE: a feed-carrying already-recently-crawled source is NOT
  re-crawled this pass; the supplement never fetches outside `crawl_source`. Invariant guard: the two
  settings exist with the right defaults/ranges and the migration/self-heal are wired.
- **Metric:** new-article yield attributable to the crawl rung (per-pass tally split).

### C4 — A5: persist robots.txt + DNS caches across restarts
- **Anchor:** `src/ingest/__init__.py:110` (`_ROBOTS_TTL`=3600), `:778` (robots store), `:741`
  (TTL check), `_bound_host_caches` `:397`. Caches are in-memory today.
- **Build:** persist the robots verdict cache (host_key → verdict + fetched_at, TTL-respecting) and a
  short DNS cache to a small local store under `data_dir()` (a JSON sidecar or a tiny table — match
  the existing lightweight-state convention, e.g. `FeedFetchState`), loaded on init, so a cold start
  after restart skips re-fetching robots for hosts still within TTL.
- **Tests:** `tests/test_robots_cache_persistence.py` — a persisted in-TTL verdict is reused after a
  simulated restart (no re-fetch); an expired verdict IS re-fetched; fail-closed semantics unchanged
  (a persisted refusal stays a refusal until TTL). NEGATIVE-SPACE: a stale (past-TTL) persisted entry
  never allows a fetch that should re-check.

---

## Phase 2 — supply (the dominant term)

### C5 — S-A: hardware-aware qualification digestion budgets
- **Anchors:** `src/scheduler/settings.py:103` (`qualification_per_pass=5`); `src/catalog/qualify_job.py`
  (`run_bulk_qualification`, `batch_size=20`, `_MAX_CONSECUTIVE_NO_PROGRESS=10`);
  `src/catalog/qualification.py` (`TRIAL_MAX_ITEMS=5`, `run_qualification_pass`).
- **Build:** make `qualification_per_pass` and the bulk `batch_size` hardware-aware via the
  power-profile table (§6e) so capable boxes digest at 50–100/pass instead of 5. Do NOT change the
  admission logic (the S1 2026-07-23 zero-evidence + livelock fixes stand — re-verify they are present
  before touching this file).
- **Tests:** the resolver reads the profile; the admission logic is untouched (existing qualification
  tests stay green).
- **Blocked-on:** the feedless majority stays unqualifiable until C7 (sitemap trial channel) — note
  this honestly; digestion of feed-carrying candidates proceeds meanwhile.

### C6 — S-A: operator catalog runs (OPERATOR-GATED — spec only, do not run in-session)
- Document the networked steps (`scripts/build_world_news_catalog.py` → commit
  `world_news_sources.yml`; regional acquisition batches) in the PR body as the operator's to run on a
  networked machine — the sandbox has no Wikidata egress. No code.

### C7 — S-E slice 1: the sitemap core ⚠(new parser — negative-space mandatory)
**Goal:** the biggest single unlock — a URL-discovery channel that (a) catches what feeds miss, (b)
becomes the qualification trial channel for the feedless candidate majority (§6d), (c) feeds C8 backfill.

- **Anchors:** dormant `Source.sitemap_url` (`src/database/models.py:344`); `src/ingest/crawl.py:64`
  (crawler currently SKIPS `.xml`); `src/ingest/non_article.py:55` ("sitemap" is a skip slug — leave
  the article gate alone, this is a discovery channel not an article). `src/catalog/qualification.py`
  (`trial_fetch`, RSS-only — extend with a sitemap trial for feedless candidates).
- **Build:** a sitemap reader in the ONE fetch path — parse robots-declared `Sitemap:` lines +
  `sitemap.xml` / sitemap-index + Google News sitemaps (plain XML via **defusedxml**, size-bounded,
  through `EthicalFetcher` so robots/politeness apply). Three consumers, value order: (a) new-URL
  discovery for qualified sources; (b) the qualification trial channel for feedless candidates
  (unblocks C5); (c) populate/refresh `Source.sitemap_url`.
- **Tests:** `tests/test_sitemap.py` — parse a sitemap-index + urlset (offline fixtures); size bound
  honoured; robots-declared sitemaps discovered; NEGATIVE-SPACE: a malformed/huge/entity-expansion
  ("billion laughs") sitemap is refused safely (defusedxml), a non-XML body does not crash, a
  sitemap URL off the source's host is not followed blindly. The trial-channel test: a feedless
  candidate now produces evidence (extraction-validity) exactly like a feed candidate.
- **Gate:** `defusedxml` must be a declared dependency (pyproject) + a registry entry if it is a
  pinned artifact.

---

## Phase 3 — transport (raise ceilings where they bind)

### C8 — S-C slice 1: skip local DNS when proxied + A6 clearnet DNS cache ⚠(SSRF-guard change)
- **Anchor:** `src/ingest/__init__.py:558-585` (`_guard_target` — `socket.getaddrinfo` per fetch + per
  redirect hop `:662`, even when proxied).
- **Build:** when a SOCKS proxy is engaged, skip the local resolution (the SSRF concern is structurally
  absent — egress is via the proxy, the EXIT resolves; ensure the proxy URL is `socks5h` so resolution
  happens at the exit) — latency saved AND a DNS-metadata leak closed. Add a short-TTL DNS cache for
  the NON-proxied path (A6). **Verify-at-build:** what scheme `settings.http_proxy` actually carries.
- **Tests ⚠ NEGATIVE-SPACE:** the non-proxied path keeps the FULL SSRF guard byte-identical (a hostname
  resolving to a private/loopback address is STILL refused when not proxied); the proxied path skips
  the local resolve; a redirect hop obeys the same rule as the initial fetch.

### C9 — S-C: hardware-aware fetch ceilings + cache_size on profiles
- **Anchors:** `collect_parallelism`/`w_max` (`settings.py:65`, `runner.py:734`); `sqlite_cache_mb()`
  + `PUBLISHED_KNOBS` (`src/config/power_profiles.py`). Keep the mem-low floor EXACTLY as-is on small
  boxes (A4/S4.3 already tells the operator what RAM capped).
- **Build:** raise `w_max`/pool and `cache_size` on capable profiles only; suggest-never-silently-switch.

### C10 — S-C: operator-run SOCKS proxy pool (§6b) ⚠(transport honesty)
- **Build:** accept a *list* of SOCKS endpoints in settings; shard hosts across them by stable hash
  (a host maps to one endpoint + one circuit — per-host isolation preserved). **All-Tor or refused**
  (never a downgrade). The app NEVER spawns network daemons — the operator runs them.
- **Tests ⚠:** a non-Tor endpoint in the pool is refused (no silent downgrade); host→endpoint mapping
  is stable; per-host circuit isolation semantics unchanged.
- **Note:** raising w_max (C9) without this may hit the single-Tor-client ceiling first — state that in
  the PR; the pool is the lever that scales past it.

### C11 — S-C: wire the segmented-download + mirror-ranking cores (bulk artifacts only)
- **Anchor:** `src/ingest/tor_throughput.py` — `plan_segments`/`reassemble` (`:85-147`, integrity
  MANDATORY), `rank_mirrors` (`:158-199`); consumers `src/wiki/dumps.py`, `src/geo/osm_downloads.py`
  (both already Range/resume + per-URL isolation).
- **Build:** dump/OSM/large-legal-base downloads use `rank_mirrors` for mirror choice and
  `plan_segments`/`reassemble` for segmented multi-circuit HTTP-Range fetches (per-segment isolation
  tokens = parallel circuits; the core's checksum reassembly is mandatory). Applies ONLY to bulk
  artifacts explicitly published for mass download.
- **Tests:** segmented download of a fixture reassembles byte-identically; a corrupt/short segment is
  refused by `reassemble` (already the core's contract — assert it at the wiring level); mirror
  ranking picks the lowest measured-latency reachable mirror, unreachable mirrors listed never deleted.

---

## Phase 4 — processing ceilings (sequence last; A1/S-D are the biggest + riskiest)

### C12 — A2: in-memory dedup front ⚠(NEGATIVE-SPACE: never a false negative)
- **Anchor:** `src/ingest/pipeline.py:119-124` (canonical-URL `_exists`), `:179-190` (content-hash
  `_exists`).
- **Build:** a bounded in-memory seen-set / Bloom filter in front of the DB dedup read; a hit that says
  "seen" falls through to the real DB check (a Bloom can false-positive), a "not seen" is trusted only
  if the structure GUARANTEES no false negatives. Populate on store; bounded + LRU-evicted.
- **Tests ⚠:** the property test — the front NEVER reports "new" for something already stored (no false
  negative → no lost dedup → no duplicate article); a false positive merely triggers the real check
  (correctness preserved, just slower for that one); eviction never causes a false negative.

### C13 — A3: bulk mention insert ⚠(counter math must stay byte-identical)
- **Anchor:** `src/analytics/store.py:302` (idempotent delete), `:321-341` (per-term add),
  `:344` (`_apply_keyword_counter_deltas`).
- **Build:** two-phase — resolve keyword ids (get-or-create), then one Core `insert().values([...])`
  for the mention rows. The `new_contrib` map + `_apply_keyword_counter_deltas` output must be
  byte-identical.
- **Tests ⚠:** counters after a bulk-insert index == the live `GROUP BY` (zero drift); the
  delete-then-reinsert epoch is idempotent (re-index reproduces exact counts — the double-count
  lesson); a mid-batch failure loses nothing.

### C14 — A4: shrink per-worker memory footprint (small-box floor)
- **Anchor:** `src/ingest/batch.py` (4 MiB staged-text cap); collect_perf `mem_low_ticks`/
  `mem_low_min_permits` (the S4.3 measurement, already shipped) is the metric.
- **Build:** release article bodies sooner, shrink the staged-text cap under memory pressure, stream
  extraction — reduce peak RSS per worker so the governor's mem-low floor stops parking permits at ~2.
- **Tests:** peak staged bytes stay bounded under a synthetic large-batch; the collect_perf mem-low
  metric moves in the right direction on a memory-constrained fixture (mechanism only — the real
  before/after is the operator's small box).

### C15 — S-E slice 2: archive backfill job (§6a)
- **Build:** when a source qualifies, a bounded auto-backfill (~100–500 pages) of its sitemap-enumerated
  history + explicit per-source consent for full history; resumable, politeness-paced (per-host floor
  self-limits), task-manager-visible with a persisted cursor (the dump-manager pattern), scheduled on
  the ladder's LOWEST rung so live collection stays first. `created_at` vs `published_at` keeps
  backfilled history honestly distinct from live collection.
- **Tests ⚠:** the cursor survives a restart/resume (a paused backfill continues, never re-fetches);
  the per-source budget is honoured; live collection is never starved (ladder rung); a paywalled URL
  fails extraction honestly (no circumvention).

### C16 — S-D: extraction out of the writer gate (EVIDENCE-GATED — full skeptic matrix) ⚠⚠
- **Gate:** build ONLY when `writer-bound` collect_perf verdicts actually appear at the new offer
  (the fast box already throws them at permits ~27 — confirm at the current offer before building).
- **Anchor:** `src/ingest/batch.py:239-249` (`_flush_batched` holds the gate ACROSS per-article
  `index_article` CPU extraction); `src/analytics/reindex_parallel.py:167-211` (`precompute_batch`,
  the proven ProcessPoolExecutor cross-core precompute — re-index-only today).
- **Build:** stage-then-gate — run extraction per staged entry BEFORE `flush()` (single-threaded first
  = the correctness step), leaving inside the gate only INSERTs (+FTS trigger), mention DML, counter
  deltas, WWW DML, commit. Then feed the staged batch through the `precompute_batch` pattern for
  cross-core precompute. **Precompute must NEVER see a Session object** (serialization boundary = the
  safety boundary). Keep the SAVEPOINT-per-article isolation, the rollback-and-redo fallback, and the
  flush-time dedup re-check byte-identical.
- **Tests ⚠⚠:** the full skeptic matrix (correctness/data-loss/concurrency) — no lost article, counters
  exact, the autoflush-gate lesson (a read never acquires the gate across a fetch), the
  delete-then-reinsert epoch, the savepoint/commit-ownership lessons. Metric: collect_perf writer block
  (`wait_rate`, `max_wait_s`) drops.

### C17 — A1: decouple ingestion from enrichment (largest architecture change — sequence LAST) ⚠⚠
- **Build:** store fast (INSERT + FTS only) + a separate background enrichment lane with its own
  persisted cursor running the `index_article` passes. Reuse the re-index job machinery + the
  "N to index" backlog concept (`autoIndexInsights`). The UI already presents "indexed lag" honestly —
  keep that honesty (a just-stored article is searchable by FTS, its keyword/WWW analytics catch up).
- **Tests ⚠⚠:** no article is ever permanently unindexed (the cursor always catches up); a crash
  mid-enrichment resumes; search never returns a half-indexed article as if fully analyzed (the lag is
  disclosed, per the existing convention).

---

## Non-goals / scope fences (do NOT do these here)

- Do NOT touch per-host politeness, robots fail-closed, the honest UA, or add any evasion — the ethics
  non-options (doc §5) are hard lines.
- Do NOT flip the scheduler `mode` default to `"crawl"` — the ruling is the hybrid supplement (§8).
- Do NOT build A1/S-D before their gates (writer-bound verdicts for S-D; sequence A1 last).
- Do NOT run the operator networked steps (C6, catalog generation) — spec them, the maintainer runs them.
- Do NOT duplicate the DB-10 `page_size`/`auto_vacuum` wiring — it rides its own track.
- Do NOT spawn network daemons (the proxy pool is operator-run).
- Frontend stays conservative + flagged (no browser here).

## Definition of done (per slice)

A slice is done when: the change is minimal + additive; its named test file (with the negative-space
cases for ⚠ slices) is green; the invariant guard is added where behaviour/wiring must not regress;
all house gates pass; the draft PR body states what was built, the measurement metric, and any
honest remainder; the ledger gets a `shipped.csv` row and (if it carries a reusable lesson) a
Session-rituals Lessons entry. The maintainer merges.

---

*Prepared 2026-07-24 alongside the strategy doc. Composes with the 2026-07-24 A/B briefs and the
2026-07-23 S4 workflow. Nothing here auto-merges; the maintainer's review is the gate.*
