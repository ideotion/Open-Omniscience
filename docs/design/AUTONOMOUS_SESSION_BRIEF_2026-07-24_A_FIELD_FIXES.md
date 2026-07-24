# Autonomous session brief — 2026-07-24 Session A: field-feedback fixes (items 1–7 + the airplane-gate split)

**Status:** PENDING execution (an autonomous Sonnet-5 CLI session).
**Rulings of record:** the CLAUDE.md Open-queue entry "FIELD FEEDBACK 2026-07-24" (intake +
investigation + the ANSWERS RECEIVED block). This brief is the operating manual; the ledger is
binding where they differ.
**Investigation baseline:** every anchor below was code-verified against `main@25dcb19`
(2026-07-24) by a six-agent read-only fan-out. **STALENESS GUARD IS MANDATORY:** re-verify each
anchor against the fresh tip before building — this repo ships fast, and prior briefs repeatedly
found "open" items already shipped (verify-and-mark, never rebuild).

---

## §0 Working mode (house standard — do not improvise)

- Read `CLAUDE.md` IN FULL first, every session. Record rulings/lessons per the protocol.
- One **draft PR per slice** onto `main`; ALWAYS `git fetch origin main` immediately before
  `git checkout -B <branch> origin/main` (the stale-base revert precedent). Nothing self-merges.
- **Gates per slice:** full pytest suite green in a py3.13 venv (`pip install -e ".[analysis,dev]"`
  works in-sandbox); `ruff check --select=F,B --extend-ignore=B008` clean;
  mypy ratchet ≤ 127 (run `python3 -m mypy <changed.py>` per file — 0 new errors);
  `bandit==1.9.4 -r src -ll -q` exit 0; `scripts/i18n_report.py --min 100` (new chrome keys ×12
  locales, or the established un-keyed-diagnostics-strings convention for Settings/Diagnostics
  panels); `node --check` every touched `<script>`; migrations: random 12-hex revision id,
  grep the versions dir for collisions, head via `python3 -m alembic heads` (the CLI), then
  `alembic upgrade head` + `alembic check` locally.
- **Skeptics-before-push** (parallel adversarial agents, distinct lenses, COMPLETE before
  `git push`) for the data-safety/parser slices: A4 (import pipeline changes) and A6 (hazard
  ingest). The **negative-space lens is mandatory** (should-be-empty inputs must yield empty).
- **Frontend** ships conservative + flagged: "browser-unverified, needs click-through" (fork-3/Q6a)
  — node --check + extended `test_repo_invariants` guards + defensive empty states.
- **Egress:** A2's indicator verification and A3's adapters need live network. If a host is
  egress-blocked: A2 ships ids flagged believed-correct + fail-loudly (the FRED-id precedent);
  A3 must NOT ship an unverified adapter endpoint at all (the fabricated-endpoint burn — an
  adapter's endpoints must be fetched live by the executing session, or the adapter is not built).
- **Closeout:** one `docs/ledger/shipped.csv` row per slice; reusable lessons → `SHIPPED_LOG.md`
  + the Session-rituals Lessons list; a carry-over section in the final PR body. Ledger merges
  are ADDITIVE — never revert sibling lines; grep for conflict markers after merging.

---

## §1 Slice A1 — language detection: resilient + auto-start + toggle UI

**Root cause (verified):** the continuous run is a non-persisted `BackgroundJob` whose worker
loop breaks on the first `LLMUnavailable` (`src/api/ai.py:449-516`, break at `:511-514`);
`OllamaClient.generate` maps ANY `httpx.HTTPError` — including its own 120 s per-call timeout —
to `LLMUnavailable` (`src/llm/ollama.py:307-308`); `detect_for_articles` treats that as a hard
abort ending the generator (`src/ai_layer/langdetect_llm.py:184-191`). The run then ends in
state `done` (benign-looking), forcing manual re-launch.

Build:
1. **Never abort-to-done.** Treat `LLMUnavailable` mid-run as TRANSIENT: retry the current
   article with exponential backoff (e.g. 5 s → 60 s cap), keep the run alive; surface an honest
   `error` state only after N consecutive failures (suggest N=10, env-tunable) — the status must
   then SAY the backend is down, never read as a completed run. Per-article `LLMError`
   (garbage output) stays a skip-and-tally, as today.
2. **Auto-start, DEFAULT-ON (ruled):** a lightweight monitor (scheduler ride-along or the
   existing job registry) that (re)starts the detection job whenever: the AI backend is
   available AND unknown-language candidates exist AND setting `ai_langdetect_auto` (new,
   default true) is on. Loopback inference is airplane-safe by the client's own gate
   (`ollama.py:202-224`) — no consent popup involved. Opt-out exposed in Settings → AI.
3. **Resume is inherent** (stored labels slide the SQL window — `langdetect_llm.py:116-122`),
   but persist a small state file (last-run tally, consecutive-failure count) so the status
   line after a restart is honest about what happened.
4. **UI (ruled):** DELETE the `#langdetect-continuous` checkbox (`src/static/index.html:1345`);
   ONE button toggling "Detect languages" ↔ "Language detection ongoing — click to stop"
   (`runLangDetect`, `app.js:4848-4882`); status line kept; task-manager visibility kept
   (kind `ai-langdetect`).
5. **Tests:** pin BOTH directions — an injected transient `LLMUnavailable` does NOT end the run
   (it retries and continues); N consecutive failures yields state `error` (never `done`);
   the auto-start monitor respects the setting + backend availability; a UI invariant pins the
   single-toggle-button shape (no checkbox).

## §2 Slice A2 — Governments: automatic country data + extended indicator catalog

**Verified state:** ALL country data hangs on the user clicking `POST /api/governments/load-standard`
(`src/api/governments.py:202`); the scheduler never calls it; `stats/subscriptions.refresh_due`
only replays PREVIOUSLY-fetched series. The map-over-time substrate already exists
(`/api/governments/map` carries a `years` list; `loadGovMap` at `app.js:4083`).

Build:
1. **Extend `INDICATOR_CATALOG`** (`src/stats/indicators.py`, currently 12 entries) with "as
   many items as possible" (ruled): target several dozen well-known World-Bank series across
   economy (GDP variants, trade, FDI), prices, labour, demographics, health (mortality,
   physicians, health expenditure), education, energy & CO₂/environment, connectivity,
   military expenditure, tax/revenue. EVERY id must be a REAL WB series id — verify live
   against `api.worldbank.org` during the session where egress allows; anything unverifiable
   ships flagged believed-correct in-file and MUST fail loudly (dead-series verdict), never
   fabricate. Bump the catalog's revised date; external-artifact registry entry in the SAME
   commit if a dated `*_AS_OF` constant is introduced (the registry protocol test enforces).
2. **Scheduler ride-along** (the stats-vintage/world-discovery pattern): a bounded
   `advance_country_data(per_pass)` (suggest 2 indicators/pass, setting-tunable, 0=off) run in
   the post-pass housekeeping on ONLINE passes only, freshness-gated per indicator (annual
   series → ~30-day recheck vs the latest stored vintage), reusing `_load_standard_worker`'s
   fetch + subscription recording (`governments.py:137-176`). Honest named skips under
   airplane / while a manual load runs. Rides the standing online-consent envelope (the
   ruled stats-vintage precedent) — no new consent surface.
3. **UI:** the empty states (`app.js:4048-4049`, `:4118`) change from "use Load standard" to
   "country data loads automatically in the background when online"; the manual button STAYS as
   an override (Desk lesson). Confirm the map's year slider renders once data flows
   (browser-unverified flag).
4. **Tests:** freshness gate (only stale/never-seen indicators fetched), bounded per pass,
   airplane skip, no fetch for a fresh vintage; catalog entries schema-validated.

## §3 Slice A3 — law vertical: adapter-first enumeration + AI change summaries

**Rulings:** granularity = ACT/CODE-level LawDocuments by default; per-legal-article rows ONLY
for structured bulk sources that pre-split (the LEGI class — a later path). Adapter-first (a);
breadth-first (b) gets a ROADMAP row for later. AI change summaries AUTO for UI-language-floor
jurisdictions, on-demand elsewhere.

**Verified state:** ~23 trackable docs across ~8 jurisdictions (17 curated + 6 verified
generated); the 225 generated legal sources register Source rows only (no LawDocument);
enumeration adapters (2026-07-17 law brief S6) NOT built; add-by-URL (`src/api/law.py:224`) and
the coverage diagnostic (`src/law/coverage.py`) DID ship; `auto_track_due` runs 5 docs/pass with
a 24 h gate (`src/law/track.py:329-330`).

Build:
1. **The adapter seam + 2–3 live-verified adapters:** an `enumerate(jurisdiction) -> [DocRef]`
   contract (id, title, act-level URL, language, kind), implementations for
   **legislation.gov.uk** (XML/Atom enumeration of ukpga/uksi), **gesetze-im-internet.de**
   (the Teilliste XML index), **EUR-Lex** (ELI register) — each endpoint FETCHED LIVE by the
   executing session before commit (bulk/API-before-scraping, the SDMX precedent; robots
   fail-closed; guarded fetcher only). Enumerated docs register as act-level `LawDocument`s
   with jurisdiction + language metadata (close the S4b language-threading gap noted 2026-07-17:
   catalog language → LawDocument → the corpus Article's `language`).
2. **The completeness principle:** the coverage diagnostic reports tracked-vs-enumerated with
   the source's OWN denominator per adapter jurisdiction ("UK: N/M public general acts") —
   never a sample presented as coverage.
3. **Tracking budget scales:** `auto_track_due`'s batch=5/24 h cannot baseline hundreds of docs
   — make the per-pass budget adaptive (bounded, e.g. scale with watched-doc count up to a cap)
   AND/OR add a one-time task-manager-visible baseline job for a freshly-enumerated
   jurisdiction (network job, cancellable, persisted cursor).
4. **AI change summaries (ruled):** when a new `LawRevision` lands, auto-generate a summary via
   the active AI backend for jurisdictions whose official language is a UI language
   (background, best-effort, skipped honestly when the backend is down); an on-demand button
   for the rest. Stored as a linked layer (the `ArticleAnalysis` pattern: model + prompt_text +
   version recorded), rendered "AI-derived · unreliable" (the established third class). Never
   blocks tracking.
5. **Mark breadth-first (b)** as a ROADMAP backlog row (shallow-track one portal/gazette per
   country from the generated catalog — later).
6. **Tests:** adapter parse from committed fixtures (pure parsers, network-free tests — the
   SDMX pattern); act-level registration idempotent; coverage denominators; summary provenance
   + skip-when-down; negative-space on the parsers (a malformed index yields no fabricated doc).

## §4 Slice A4 — imports: instrument first, own the machine, then optimize

**Verified state:** 7 stages (A decrypt/reassemble → B snapshot → C 14-step merge → D verify →
E swap → F re-index → G post-steps); progress wired for ONLY C and F, and only on the volume-job
path — the sync REST restore (`src/api/backup_v2.py:164,215,290`) wires NO callbacks; ZERO
per-stage timing exists on the import side (export already records `wall_s`/`gate_held_s`,
`stream_backup.py:1025-1026`); only F's CPU half is parallel (`reindex_parallel.py`); C runs on
ONE SQLCipher connection single-threaded.

Build (in this order — measure before optimizing, the house doctrine):
1. **Per-stage timing instrumentation:** wall seconds (+ bytes where natural, + gate-held where
   relevant) for ALL stages of `run_restore`/`read_volume_backup`, folded into the persisted
   S3.3 import report (`src/backup/import_reports.py` — JSON + the Markdown rendering) and
   `merge_batches.report_json`, and rendered on the post-import screen. The report is the
   evidence base for step 3.
2. **Progress everywhere:** per-volume progress in stage A (`volumes.py:218-240` loop), phase
   pings for B/D/E/G; route the sync REST path through the same job/progress plumbing so every
   import reports; the frontend renders each phase (extend `_uxProgressView`, `app.js:5562-5577`).
3. **"Import owns the machine" (RULED):** while an import runs — pause scheduler collection
   (resume after, stated in the UI), enlarge the working-copy connection cache
   (`OO_SQLITE_CACHE_MB`-class knob for the import connection), re-index workers = all cores
   (revisit the cap of 8 in `reindex_parallel.py:69` — measure), all disclosed in the progress
   view.
4. **Optimize the MEASURED biggest stage** (candidates, evidence-ordered once step 1 lands):
   parallel per-volume decrypt+verify in stage A (volumes are independent; verify empirically
   that the crypto releases the GIL before claiming a speedup); write-batched re-index apply
   (commit_batch>1 with the PROVEN redo-per-article fallback — the P1.3 pattern; the savepoint
   lessons apply). NEVER weaken verification or the atomic-swap/crash-safety properties — this
   is the data-safety slice: **full skeptic matrix mandatory** (data-loss · traversal ·
   crash-mid-stage · concurrency lenses) before push.
5. **Export:** render its existing timings in the completion UI (no engine change needed).
6. **Honesty:** report only measured numbers; no projected speedups anywhere in UI or ledger.

## §5 Slice A5 — Library graphs: 4-line qualification tile, auto-log, hide-flat, window switcher

**Verified state:** no hide-when-flat logic (`dashChartSvg` renders all-zero series,
`app.js:8609-8693`); qualification counts are NOT snapshot metrics (`snapshots.py:45-53` is
plain COUNT(*) tables); the tile renderer is SINGLE-series; multi-series exists via
`chartEnlarge`→ooChart (`app.js:12973`) and `renderFamilyGraphs` (`app.js:8705`);
`/api/library/history` is single-metric, days default 30 (`src/api/library.py:45-46,195-203`).

Build:
1. **Filtered snapshot metrics:** a metric→callable code path in `snapshots.py` (beside the
   table-COUNT map) recording hourly: `sources_qualified` (enabled ∧ status=qualified),
   `sources_disqualified` (enabled ∧ status=disqualified), `sources_never_judged` (enabled ∧
   never judged), `sources_candidates` (enabled=False) — registered in `ALL_METRICS`, the
   `metric_history` gate, and `library.py` validation. Use the same savepoint-per-insert +
   hour-bucket-gate discipline. These four PARTITION cleanly against the S1.3 display counts —
   keep the definitions aligned with `src/api/database.py:155-173` (one source of truth for the
   predicates; never two divergent definitions).
2. **The 4-line tile:** an ooChart-based multi-series tile (the `renderFamilyGraphs` shape) in
   the Activity section; the enlarge modal already takes a `seriesList`.
3. **Scale disparity (ruled → auto-log):** ONE shared y-axis; when the cross-series spread
   exceeds a threshold (e.g. max/min > 50 with all values > 0), switch to log10 via the existing
   `opts.logY`, ALWAYS labeled "log scale" on the tile — NOT multi-axis (the honest-viz
   dual-axis rejection stands for same-unit series; all four lines are source counts).
4. **Hide-flat (ruled):** a tile whose whole fetched series is zero/no-data collapses to a
   one-line "no data yet" note (never a silently blank section — the never-blank-and-silent
   rule); it reappears when data exists.
5. **Window switcher (ruled):** per-tile 7d / 30d / 90d / all, ALL tiles starting on the
   identical default window (suggest 30d); full hourly resolution kept — no downsampling
   (invariant #16).
6. **Tests:** the four filtered metrics record + partition-sum against the display counts;
   invariant pins for the switcher, hide-flat note, log label; frontend flagged
   browser-unverified.

## §6 Slice A6 — hazards as Articles + the beautiful Alerts strip + map rings

**Rulings:** hazards are INGESTED AS ARTICLES (option b) with rich metadata + keyword
processing; the Home Alerts section becomes a COMPACT STRIP deep-linking to the World map —
"think of the UI, make it beautiful" (a maintainer click-through is owed regardless, fork-3).

**Verified state:** hazard records (USGS quakes + GDACS) carry `source, id, type, title,
severity, magnitude, lat, lon, place, time, url` (`src/hazards/parse.py:85-139`) into a local
JSON snapshot (`src/hazards/store.py:50-86`); `compute_alerts` DROPS magnitude/lat/lon and the
frontend never renders `time` (`src/analytics/alerts.py:110-119`, `app.js:2275-2280`); hazards
are NOT Articles; the ooMap signals layer already age-fades + click-details + "find coverage"
(`app.js:13348-13369, 13969-14007`), and `timemap.py`'s hazard signals already carry magnitude
(`src/api/timemap.py:84-85`) — but the stories lens doesn't request `hazards=true`
(`app.js:13671,13879`) and that path live-fetches (`timemap.py:56`).

Build:
1. **Ingest hazards as Articles** from the LOCAL snapshot (and on each consented hazard
   refresh): one Article per provider event id (hash/id dedup — an updated alert for the same
   event updates/dedups, never duplicates), body = the provider's title + description VERBATIM
   (never synthesized prose), `published_at` = event time, per-provider synthetic sources
   (e.g. `hazard.usgs.local`, `hazard.gdacs.local`, `source_type="hazard"`), a NEW `HAZARD`
   provenance class (`PROVENANCE_CLASSES` + `provenance_of` + implied tags + extend the
   closed-set test), indexed through the ONE `index_article` hook (keywords/when-where-who
   follow). Provider-asserted magnitude/coords/severity persist in a small linked record keyed
   by article_id (the linked-layer pattern) and render in the reader as SOURCE-ASSERTED class
   metadata (two-class discipline: asserted, not deduced). Zero network at ingest — the
   snapshot is already local.
2. **Map rings:** feed the signals layer's hazards from the LOCAL store (never a live fetch on
   render — replace the `fetch_hazards` path for map use); magnitude-scaled radius (sqrt scale,
   honest default radius when magnitude is null — GDACS non-quakes), the existing age-fade;
   click-detail gains the INTERNAL article/reader link + a composed corpus search
   (`type + place + after:<event-date>` through `tmapFindCoverage`, `app.js:14513`).
3. **The Home strip (ruled):** a compact, well-designed recent-alerts strip — per alert: tier
   dot, type glyph, magnitude (when real), place, RELATIVE date (stored `time` finally
   rendered), deep-links to the World map (centered on the event) and to the internal article.
   Replaces the current tiered list. Watches/convergences keep their existing internal links.
   Conservative + flagged (browser-unverified); +strings ×12 or the established fallback.
4. **Fix `compute_alerts`** to carry `time`/`magnitude`/`lat`/`lon` through (`alerts.py:110-119`).
5. **Skeptic (mandatory, negative-space):** a malformed/fields-missing feed entry must never
   fabricate an Article or a magnitude (missing magnitude = absent, never 0); dedup proven
   across snapshot refreshes; the ingest must not disturb non-hazard sources.

## §7 Slice A7 — the airplane/Ollama gate split (unblocks the triage/tag runs NOW)

**Verified:** loopback generation is ALREADY allowed under airplane everywhere except the two
run-endpoints' own blanket refusals: `src/api/diagnostics.py:3893-3898` (keyword-triage) and
`:4028-4033` (source-tags) — `if kill_switch_active(): raise 409`. The client's
`_check_kill_switch` (`ollama.py:202-224`) already models the correct loopback-vs-clearnet
distinction.

Build: remove the two blanket gates; rely on the client's per-call gate (a non-loopback backend
URL still refuses; pull/remove stay clearnet-refused). Tests pin BOTH directions: the runs start
and generate with the kill switch engaged against a loopback backend (no socket beyond
loopback — the socket-guard test pattern), and a model pull under airplane still refuses.
Update the two endpoints' error copy + the `triage_job.py:35-38` docstring note.

## §8 Item 7 (DB-IP) — RESOLVED, no build

Keep the bundled DB-IP Lite dataset + its CC BY 4.0 attribution line (ruled). No code change.

---

## §9 Explicitly OUT of scope for Session A

Everything in item 8 / Session B (the vLLM dual backend, pill rename, toggle-run rework, AI
metadata extraction, AI diagnostics) — EXCEPT the §7 gate split, which is ruled into A. Also out:
the Observatory, the 0.3 close-gate rows not named here, S4.2 collector write-batching (its own
skeptic-matrix slice), and any browser click-through claims (flag, never claim).

## §10 Closeout

Per slice: shipped.csv row + tests named + gates run. Final PR body: the carry-over list
(browser-unverified surfaces owed a click-through; anything egress-blocked that shipped flagged;
the A3 breadth-first ROADMAP row). Ledger updates additive; lessons harvested per the protocol.
