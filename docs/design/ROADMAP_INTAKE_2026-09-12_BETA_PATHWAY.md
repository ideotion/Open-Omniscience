# Roadmap intake 2026-09-12 — eight field impressions, the verified state, and the alpha train to beta

**Status: INTAKE + PLAN ONLY.** Nothing here is built. The maintainer wrote (2026-09-12): *"We're only
making plans, I'd like a robust, detailed roadmap towards the beta release, with all detailed plans and
stages for all remaining alpha releases."* This document is that plan's first half: the verified current
state behind each of the eight impressions, the gaps, the proposals, and the **numbered questions**
(§6) whose answers turn the skeleton train in §5 into the release gates. The second half — per-release
gate files and per-slice session briefs — is written once the answers are in.

**Composes with, never restates:** the approved V1 train ([`V1_PATHWAY_2026-07-14.md`](V1_PATHWAY_2026-07-14.md)
§3, rulings of 2026-09-07), the two live gate boards ([`../product/RELEASE_0.3_GATE.md`](../product/RELEASE_0.3_GATE.md),
[`../product/RELEASE_0.4_GATE.md`](../product/RELEASE_0.4_GATE.md)), the 23-prompt action plan
([`../plans/2026-09-06-repo-analysis/`](../plans/2026-09-06-repo-analysis/)) and its 65-question register,
the storage plan ([`STORAGE_5TB_PLAN.md`](STORAGE_5TB_PLAN.md) + [`STORAGE_5TB_REFRESH_2026-09-07.md`](STORAGE_5TB_REFRESH_2026-09-07.md)
+ [`STORAGE_RULINGS_ROUND2_2026-09-07.md`](STORAGE_RULINGS_ROUND2_2026-09-07.md)), the map/sources action
plan ([`ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`](ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md)), and the
law brief ([`AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md)).
Where this document and one of those disagree, the disagreement is stated in place and put to the
maintainer as a question; nothing is silently superseded.

**Evidence tiers used below.** VERIFIED = read in the tree at `main`@`bebcef4` by the writing session,
with the anchor given. SEARCH-VERIFIED = consistent across several independent web search results
whose pages could not be fetched (this sandbox's egress proxy blocks npr.org, cnn.com, wikitech,
mediawiki.org and correctthemap.org). FROM MEMORY = a technical fact the writer is confident of but
could not check from here; every one is marked and must be confirmed by the session that builds on it.
Seven read-only recon agents produced the raw inventories; **every load-bearing anchor they returned was
re-verified by hand** before entering this document (the 06-audit false-positive lesson).

---

## 1. What changed since the last talk (2026-09-06 → 2026-09-12)

211 merges (#1011 → #1130). The ones that move this plan:

- The ledger was restructured (PR #1014): `CLAUDE.md` is the constitution, `docs/ledger/LESSONS.md` and
  `docs/ledger/OPEN_QUEUE.md` are mandatory reading and the docket. Rulings go to OPEN_QUEUE, shipped work
  to `shipped.csv`.
- The V1 train was **approved** with four amendments (2026-09-07): 0.4 living sources · 0.5 investigator's
  desk · 0.6 elections + climate (keyless) · 0.7 medical + patents · 0.8 conflict + 360° dossier + an OSM
  dated-boundary seed · 0.9 hardening RC · 1.0. V1-2 no key-gated sources; V1-3 NC / no-redistribution
  licences excluded; V1-9 ≥ 1 full Wikipedia edition + proven scaling machinery at 1.0.
- `RELEASE_0.3_GATE.md` has **one open row** (5: the Tier-A quarantine run, an operator step); the tag is
  cut from the maintainer's machine (the session git proxy refuses tag pushes). `RELEASE_0.4_GATE.md` exists
  with rows A–F. The version still reads `0.3.0`.
- Storage: `page_size=16384` + `auto_vacuum=INCREMENTAL` ship on create; Phase C (packed text store) became
  ruling-gated rather than mandatory (64 TiB single-file ceiling at 16K pages); four round-2 storage rulings
  are still pending (blob dedup, OOENC2 vs `age`, keyed addressing, sqlite3mc benchmark).
- Wikipedia: `Article.source_revision`, the tracked-changes modal, the offline dump FTS index and a bounded
  dump→corpus endpoint shipped; whole-edition ingest stopped at the seam (2026-09-07 pass).
- Law: CLML adapter wired (PR #1104), language columns and AI change summaries shipped, three gazette feeds
  on the ingest path; enumeration adapters still not live; egress to every priority portal still blocked.
- Cross-language search slice 1 shipped (PR #1010): ring expansion on `/api/articles` and the omnibar,
  disclosed, with a sense pick over the 91 measured collisions.
- Backups: wiki dumps / OSM regions / model blobs may ride inside the signed artifact (PR #1020, opt-in);
  import checkpoint interval K (PR #1034); the data-location chooser (PR #1020).
- The candidate-source pipeline (5,580 sources), audit 12 (collector CPU-bound at ~2.3 articles/s,
  `extract_dates` 53% of the cost), the crash brief's fourteen PRs, the Observatory.

## 2. Method and honest limits

- No browser was driven this session; every frontend statement is from source. No live corpus is
  reachable; every scale number is the ledger's recorded field figure with its date.
- Egress: search results are reachable; the source pages are not. Wikimedia, OSM and UN facts below carry
  the SEARCH-VERIFIED tier and one FROM MEMORY block each; none is presented as fetched.
- Two of the maintainer's premises were checked in both directions, and the result is symmetric: the
  claim about the **world** (a UN vote on the world map) was right and the writer's memory was stale;
  the claim about **the app** (that it defaults to Mercator) is wrong and the code says so. Both are
  recorded in §3.7 and in `docs/ledger/LESSONS.md`.

---

## 3. The eight impressions — verified state, gap, proposal

Each subsection ends with the questions it raises; the questions are numbered globally in §6.

### 3.1 Import / export UX

**The ask.** A fresh import page on reopen; no overlapping or blinking messages; drop "details"; put the
index merge inside the import experience (or take it out) so the user knows when the app can be closed,
updated, or the files removed; a clear export completion with contents and sizes; export into a dated
folder `YYYYMMDDHHMM_OOS_Backup` with an incremental suffix on collision.

**Verified state (all in `src/static/app-backup.js` unless noted).**
- `openUnifiedImport()` (:494–508) resets seven things — the checklist, status, progress, summary, bar,
  pass row, the Run button — and **deliberately** re-renders the previous run through
  `_uxShowLastCompletedSummary()` (:521–554). The comment beside it cites a **2026-07-16 field report**
  asking for exactly that ("after a successful import/merge, the interface doesn't…"). Today's ask
  reverses a previous ruling; both are legitimate and the resolution is a design choice (Q5).
- What is **never** reset on open: `#ux-imp-queue`, `#ux-imp-queue-note`, `#ux-imp-queue-rows`,
  `#ux-imp-details-body`, the poll timer `_uxImPollTimer` (:729), `#ux-imp-src`, `_uxPhase` (:313).
  `_uxImReattach()` (:946–952) repaints queue rows regardless of state. So the "previous import still
  there" is two mechanisms, one intended and one not.
- The blinking: `#ux-imp-bar` has **two owners at two cadences** — the verify poll `_uxPoll` at 1200 ms via
  `_uxPaintBar` (:243–248) and the queue renderer `_uxImRenderQueue` at 1000 ms (:845–854, a different
  `max`); the rows' `innerHTML` is rebuilt every tick (:860–874); and two `_uxImQueuePoll` chains can
  coexist (:736–742). That is the overlap.
- "Details" (`_uxImDetails`, :916–929) duplicates the queue rows except `it.path`. It adds nothing;
  the maintainer's read is correct.
- **The index merge is two different things, and only one is in the run.** The FTS5
  `optimize_after_bulk` runs inside `ImportQueueManager._tune_after_run` (`src/backup/import_queue.py:466–519`,
  phase `tuning` → "Merging the search index…", counted as `stages_total = len(items)+1`). The **article
  re-index** — the part that takes hours — is a *separate deferred job*: `defer_reindex()` defaults on
  (`src/backup/volume_job.py:73–74`, `OO_IMPORT_DEFER_REINDEX`), `hand_off_reindex` / `start_reindex_drain`
  hand it to `ReindexJobManager` (`src/analytics/reindex_job.py`, persisted cursor, job `reindex-resume`),
  exposed as `GET /api/backup/reindex-backlog`, `POST …/resume`, `GET …/resume/status`, `POST …/resume/cancel`
  (`src/api/backup_v2.py:770–905`) — **with zero frontend callers**. So the UI cannot say "safe to close":
  it does not know the re-index exists.
- No statement anywhere says "files can be removed" or "safe to update". The persisted import reports
  (`GET /api/backup/import-reports`) also have no frontend caller. `ImportQueueManager.clear()`
  (`import_queue.py:869–880`, refuses while running) is exposed as `POST /api/backup/import-queue/clear`
  with no caller.
- Export completion is one line (`_uxRun` :426–428, "Backup complete →" + dest + "Included:") that discards
  `s1.summary` — which carries volumes, `total_bytes` and per-table counts including articles
  (`src/backup/stream_backup.py:456–465`) — and the folder phase's `{files, copied, bytes_total, bytes_copied}`.
- Destination: volumes are written **directly into the chosen directory** (`volume_job.py:237–243`), no
  subfolder, **no timestamp naming anywhere**. A dated subfolder has one real cost: `_load_reuse_pool`
  (`stream_backup.py:766+`) finds reusable volumes in the *destination*, and the 2026-08-12 field run reused
  26 of 58 volumes (8.15 GB of writes saved). The import scan is recursive (`import_scan.py`), so dated
  subfolders cost the import side nothing.

**Proposal — the four-stage import lifecycle, stated on screen.**

| Stage | What runs | What the user may do afterwards |
|---|---|---|
| 1 Verify + stage | manifest signature, volume checksums, parity, staged restore | nothing yet; files are being read |
| 2 Merge + swap | the merge, the atomic swap, custody side files | **the import files may be removed**; **the app may be closed or updated** (a durable cursor resumes stage 4) |
| 3 Search-index merge | FTS5 `optimize_after_bulk` (minutes) | search is complete once it ends |
| 4 Re-index | the deferred article re-index (hours; resumable; runs in the task manager) | analytics (keywords, When×Where×Who, sentiment) are complete once it ends |

- One owner for the progress bar; one poll chain; rows patched, not rebuilt. Stage 4 appears in the
  import experience as a row with its own progress and a link to the task manager (Q6).
- Fresh page on open; the previous run collapses to one line — date, articles, an "open report" link
  onto the persisted import report (the endpoint exists) (Q5). "Details" goes (Q8).
- Export: a completion panel with volumes, bytes, per-table counts (articles first, the ruled headline
  unit), files copied per category, elapsed time, and the destination; plus a human-readable
  `BACKUP_SUMMARY.md` written **into the folder** beside `volumes.json`, so the folder explains itself
  on the removable drive (Q11).
- Export folder: `YYYYMMDDHHMM_OOS_Backup` created under the chosen path, local time, `_2`, `_3`… on
  collision (Q9). Volume reuse survives by widening `_load_reuse_pool` to sibling `*_OOS_Backup*` folders
  in the same parent, so an incremental refresh still finds the previous volumes (Q10).
- The two parallel backup-restore APIs the visual audit found (Q-VIS-5) are the reason this UI has two
  owners; the unification belongs in the same release (Q12).

Questions: Q5–Q12.

### 3.2 ISO 3166-1 alpha-3 everywhere

**The ask.** Replace the two-letter country codes with three-letter ones consistently — UI, bulletins,
diagnostics, inner workings, code and inner filenames.

**Verified state.**
- Storage is lowercase alpha-2 by a maintainer ruling at 0.09 (`src/catalog/countries.py:1–21`), with
  the migration `a3b4c5d6e7f8` that cleaned the fabricated-US default and a `[:2]` truncation corruption.
- **Six `String(2)` columns** (`src/database/models.py:335, 425, 667, 1246, 1835, 1947`): source metadata,
  `Source.country`, `Article.country` (the largest table), `ExternalSource.country`,
  `ArticleMentionedPlace.country`, `KeywordMention.country` (mention-sized). `LawDocument.jurisdiction`
  is `String(8)` and **not ISO** (`uk`, `eu`, `int`); `StatFigure.ref_area` is **already alpha-3**, uppercase,
  as published by the World Bank, bridged server-side through `to_iso2` (`stats/store.py:363`).
- An alpha-2 ⇄ alpha-3 table already exists and is fail-closed both ways: `ISO2_TO_ISO3` / `ISO3_TO_ISO2`
  (~190 pairs), `to_iso2` (:644), `to_iso3` (:672), `classify_ref_area` (:691). Its scope comment names the
  reason storage stayed alpha-2: *"the map (world_countries.json) and Intl.DisplayNames use alpha-2."*
- **Two frontend mechanisms break on alpha-3, silently.** `ooRegionName` (`app-map.js:91–99`) calls
  `Intl.DisplayNames([lang], {type:"region"}).of(code)`; the `region` type accepts alpha-2 and UN M49
  only, so `"FRA"` throws, is caught, and degrades to the bare code in all twelve locales. `agFlag`
  (`app-agenda.js:981–985`) derives the flag from two regional-indicator code points and is gated on
  `/^[A-Z]{2}$/`; an alpha-3 becomes 🌐. Both are pinned by tests.
- **Three external contracts are alpha-2 and cannot move:** the FRED/OECD symbol ids
  (`SPASTT01DEM661N`) — an alpha-3 attempt was already reverted once (`shipped.csv:239, :275`) and the
  two-letter form is regression-pinned; the OSM tag `ISO3166-1:alpha2` (`osmpbf.js:246`); DB-IP's country
  table (`ip_geo.py:13`, upstream data). Wikidata's `P297` is alpha-2 (`catalog_query.yml:5`); `P298` is
  alpha-3 and could be fetched.
- **The restore merge keys on the value.** `src/backup/merge.py:3280` matches `stat_subscriptions` on
  `COALESCE(t.country,'') = COALESCE(i.country,'')`, and `country` is an adoptable article column
  (`merge.py:2274`). A storage migration makes an old backup's `fr` and a migrated corpus's `FRA` unequal:
  the additive restore then **duplicates** instead of deduplicating, and can write alpha-2 into an alpha-3
  column with no conflict raised. Additive restore never deletes, so a half-migrated column is permanent.
- Config: 5,803 `country:`/`jurisdiction:` lines across 14 YAML files (`sources.yml` alone 3,981);
  `world_events.yml` is already UPPERCASE while everything else is lowercase; `world_countries.json` is
  keyed alpha-2 (175 countries). **Inner filenames: none carry a country code** (two independent greps;
  the OSM region codes are Geofabrik slugs). Language codes are ISO 639-1 (two letters) and share a
  normalisation branch with country at `csv_io.py:130` — the one place a change would leak.

**Proposal — a display-and-boundary migration, not a storage migration.** The user sees alpha-3
everywhere a code is shown; the store, the configs and the external contracts keep alpha-2 as the
internal identity.

- One formatter on each side: `country_display(code) -> "FRA"` in `countries.py` and `ooCountryCode()`
  in the shell, used by every surface that prints a code: the Sources table, Governments pickers and
  compare, Insights, the Corpus window, the bulletin (`render.py:307`, `:665` print raw codes today),
  diagnostics payloads (a `country_iso3` beside each `country`), CSV/JSON exports (an added column, never a
  redefinition), and the agenda (flag from alpha-2, label alpha-3).
- Every API parameter accepts both forms through `normalize_country` (today the diagnostics endpoints
  reject non-alpha-2 at `diagnostics.py:1163`).
- Non-ISO values need a declared mapping: `int`, `eu`, `xk`, `an`, and the law `uk`. Alpha-3 has no
  official code for the EU or "international"; the World Bank uses `EUU` for the EU aggregate and `XKX` for
  Kosovo (user-assigned); `ANT` is the withdrawn Netherlands Antilles code (Q15).
- Cost of the full storage migration, stated so the choice is informed: six column widenings, a
  backfill over the two largest tables, ~5,800 config lines, a re-keyed `world_countries.json`, the DB-IP
  table rebuilt, ~105 Python and 18 JS/HTML files, ~78 test files with two-letter literals — and the
  restore-merge hazard above, which is the one item that cannot be undone by another migration.

Questions: Q13–Q18 (Q13 is ⛔: the storage half is irreversible in the backup sense).

### 3.3 Keywords shown in the UI language, "translated from X"

**The ask.** Rising keywords, keywords everywhere, and cards should appear in the UI language and be
tagged "translated from X"; users must still be able to search and navigate the foreign keyword; use
Wikidata rings unless there is a better idea; automate; respect Wikidata's download limits (≤ 1 request
per 10 s); decide whether rings ride backups.

**Verified state.**
- Rings: `configs/keyword_equivalents.yml` (26 curated) + `configs/keyword_rings_generated.yml` (684) →
  **698 rings / 21,927 members** loaded, 12 languages (es 2,636 · en 2,519 · ar 2,384 · de 2,272 · zh 2,118 ·
  fr 1,989 · ja 1,868 · ru 1,807 · pt 1,599 · id 1,141 · hi 851 · bn 716). `equivalence.py` API: `ring_of`,
  `translate_term`, `ring_translation`, `expand_term`, `QueryExpander`. Three `lru_cache(maxsize=1)`
  loaders; **no runtime invalidation** — a changed ring file needs a restart. Rings live in `configs/`,
  are **not in any backup** (`src/backup/*` never references them) and are not user-editable at runtime.
- `_annotate_translations` (`queries.py:245–274`) emits `translation` + `translation_source="ring"` and
  **no source-language field**. The "translated from X" tag has nothing to read yet.
- Surfaces that render a translation today: Home rising strip, Insights Trends chips, Insights Top,
  Families, Supergroups, the analysis window's Keywords subtab. Surfaces that render the raw term with no
  translation: the Trends bar rows, keyword hover stats, associations / mind-map, context snippets, the
  graph, corpus-sources, the omnibar keyword group (siblings carry `via_ring` but no translation), the
  reader's keyword tab, the Observatory, `/where`, `/who`, `/ring-countries`. Seven endpoints accept no
  `target_lang` at all.
- **Card titles structurally never translate the term**: `Card.title_i18n` + `title_vars`
  (`src/briefing/card.py:190–191`), rendered by `OOI18N.tf`, and `i18n.js:162` states the design:
  *"card titles … whose data (the keyword term) must not translate."* Today's ask is an exception to that
  rule and needs to be ruled as one (Q24).
- The **91 collisions** (one `(language, term)` in several rings — `de wahl`, `de strom`) are handled
  honestly by `expand_term` (it refuses) but **`translate_term` has no refusal path**: a display label built
  on it shows the wrong concept's word for exactly those pairs (Q25).
- `Keyword.language` is first-write-wins (`store.py:112–121`) with a self-documented **16% / 40%-of-head
  mismatch** and a reconcile pass (`reconcile_keyword_language`, needs a strict majority over ≥ 2
  articles). The rings actually resolve on the *effective* language (`queries._ring_lang_of`), so the tag
  must be built from that, not from the stored column (Q26).
- LLM tentative fallback (`src/ai_layer/translate.py`): loopback only, skips ring-covered terms,
  labelled ≈, **process-global cache of 5,000 entries, lost on restart, never stored**; reached only by an
  explicit button in the Keywords subtab.
- The generator (`scripts/generate_wikidata_rings.py`) uses raw `urllib`, its own UA, `wbsearchentities`
  in the seed's language and batched `wbgetentities`, **`sleep=0.2` s between requests** — fifty times
  faster than the maintainer's 1-per-10-s rule. `--refresh` re-reads vetted QIDs and emits only additions
  for review. The app itself already contacts Wikidata at runtime through the **consented world-discovery
  ride-along** (`src/catalog/discover.py:36–41`, `query.wikidata.org`, kill-switch gated,
  `world_discovery_per_pass` default 2 per online pass), so Wikidata is not a new host — but see §4.3.
- Coverage: `translation_coverage` ≈ 5% of top keywords (the KPI K6 resolver reads it); the
  `ring_candidates` gap digest (`diagnostics.py:127–191`) already proposes the next rings per language.

**Proposal — a three-tier translation ladder, one label grammar, and an in-app ring loop.**

1. *Tier 1, verified:* the ring translation, tagged `translated from {lang}` where `{lang}` is the
   ring member's language (the effective language), never the stored column alone.
2. *Tier 2, tentative:* the LLM translation, persisted in a new `keyword_translations` table
   (term, source lang, target lang, text, model, prompt version, created) — never the trusted index,
   always ≈, filled by a background sweep under the AI coordinator when a backend is up (Q20, Q21).
3. *Tier 3, untranslated:* the original term with its language tag, and the search still works on it.
- One display helper renders all three; every list that shows a keyword calls it (the eleven silent
  surfaces above); the seven endpoints gain `target_lang`; `_annotate_translations` gains
  `translation_source_lang`, `translation_tier`, `senses` (for the 91).
- Cards: `title_vars` gains `term_translation` and `term_lang`; the template becomes
  `"{term_translation}" (translated from {term_lang}: {term})` where a translation exists (Q24).
- Ring growth: a consented, task-manager-visible **"Refresh translations"** job runs the gap digest →
  `wbgetentities` at the maintainer's cadence (≤ 1 request / 10 s, `maxlag=5`, the bot UA) → a proposal
  file → a review surface in Settings → accepted rings land in `data_dir()/keyword_rings_local.yml`, which
  the loader reads with curated-wins precedence and which **rides the corpus backup** (Q22, Q23). The
  shipped ring files stay in `configs/` and never enter a backup. `lru_cache` becomes an mtime cache.
- Honesty rails that survive: counts per language visible in the hover, "translated from" always
  present, ≈ never dropped, a collision shows "several senses" rather than one word.

Questions: Q19–Q26.

### 3.4 Cross-language search in every tab

**The ask.** A search for "climate" also searches "climat", "Klima", … and concatenates the results,
across every result tab (mind maps, trends, articles, sources, map); the user can restrict to the literal
keyword.

**Verified state.**
- The mechanism exists and is honest: `ExpandTerms` in `src/database/fts.py:170–194`, `QueryExpander`,
  Boolean composition threads expansion through AND/OR/NOT (excludes expand too), a disclosure payload
  (`{expanded, terms[], method, caveat}`), `expand=false` as the literal escape.
- It is wired on **two endpoints only**: `/api/articles` (`main.py:1452–1454`) and `/api/search/omni`.
  `_resolve_corpus` (`insights.py:381`) — the function behind every other analysis subtab — calls
  `_query_articles` with no `expand`, so **the analysis window is literal-only except its Articles list**.
  None of `/trend`, `/trend-articles`, `/associations`, `/context`, `/keyword-stats`, `/graph`, `/where`,
  `/who`, `/corpus-keywords`, `/corpus-sources`, `/map-coverage` accepts `expand`, `sense` or `ui_lang`. A
  Home card's corpus and its keyword trend therefore disagree by construction.
- `expand=false` and the sense pins live only in `_articleQuery` (`app-analysis.js:1107–1123`) and do
  not survive a reload or reach the tab seed / URL.
- A single term can OR in dozens of literals; `search_total` re-runs the same MATCH uncapped
  (`search_omni.py:110`) — untested at ring-size extremes on the SQLCipher store.

**Proposal — one concept resolution, two consumers.**
- `resolve_concept(term, ui_lang, sense) -> {ring_id, members_by_language, disclosure}` is computed once
  per analysis tab and passed to **both** consumers: the FTS path (as today) and the keyword-keyed
  aggregates, which sum over the member keyword ids (a covering-index sum on `keyword_mentions`, never a
  codec join). Trend, mind map, When×Where×Who, sources, map and the Observatory drill all read the same
  resolution, so every tab agrees.
- Series are **per language, stacked with a legend**, never a single merged line (Q28) — the honest
  form: the reader sees which languages carry the concept and by how much.
- The literal toggle ("only the words I typed") and the sense pick persist in the tab seed and the URL
  (`?expand=0`, `?sense=`) (Q27, Q30). A member cap with disclosure bounds the OR fan-out (Q29).
- Item 3's tier ladder feeds this: a Tier-2 (tentative) translation may **display** but never
  **expands** a search unless the user opts in per query — expansion stays ring-verified only.

Questions: Q27–Q30.

### 3.5 Advanced search

**The ask.** A unified advanced-search UI: language restriction, source-tag filtering, date selection,
article length and more; take existing search engines' advanced forms as the model; more Boolean
operators, each with a visual affordance.

**Verified state (`src/database/fts.py`, `src/api/main.py`, `src/static/app-analysis.js`).**
- Grammar: `AND`/`OR`/`NOT` (English, hard-coded, `fts.py:49`), quoted phrases, parentheses, implicit
  AND, precedence parens > NOT > AND > OR. `_quote` (`:160–167`) wraps **every** term as an FTS5 phrase, so
  prefix `climat*`, `NEAR(a b, N)` and `title:` column filters are **structurally impossible today** even
  though FTS5 supports all three natively. A purely negative query silently drops its exclusions.
- `/api/articles` filters: `source` (exact name, 404 on a typo), `start_date`/`end_date` on
  `published_at` only, `language` on the **asserted** column only (`detected_language` is returned but not
  filterable), `tags` (substring), `provenance`, `source_type`, `ids`, six `sort_by` fields. **Missing**:
  word count, sentiment, source country/region, author, `created_at` window, mentioned-date, multi-language,
  include-quarantined. All of those columns are indexed already.
- The Advanced subtab has **five controls** (`index.html:470–484`): query, free-text source, a language
  select, two bare `<input type=date>`. The ruled field list (OPEN_QUEUE "SEARCH = ONE CENTRAL ANALYTICAL
  TOOL") also names keywords, source tags and region — unbuilt. The ruling mandates reusing the
  begin/end/timescale component "built once": `ooTimeScope` (`app-markets.js:2351–2496`) exists with a range
  bar and presets but **no timescale selector**, and Advanced does not use it.
- Facet endpoints exist for source/language (`corpus-source-language-facets`) and drills
  (`corpus-facet-articles`: entity/place/when/source/language); none for word-count bands, sentiment,
  country, tags, provenance. Export (`/api/articles/export`) takes a strict subset (no sort, provenance,
  channel, expansion) — an export cannot reproduce a filtered view. Saved searches: only the Watch engine,
  which stores a query string plus threshold and window. Typo tolerance: **ruling pending**
  (OPEN_QUEUE:11361–11384; the 406,723-keyword scan cost is the blocker, SymSpell-shaped table is the
  buildable path).
- The i18n point the maintainer will hit: operator words are English only; a French user typing `OR`
  ("gold") gets an operator. Localised alias words would make it worse, not better (Q34).

**Proposal — a query builder that compiles to the existing grammar, plus the filter set the data can
already answer.**
- *Builder:* rows of `field · operator · value` (term, phrase, prefix, NEAR with distance, title-only,
  NOT, group) rendered as chips above the query box; the box stays editable and shows the compiled query.
  Operators have buttons and hover explanations ×12; typed tokens stay English (the builder is the
  localised layer) (Q32–Q34).
- *Grammar extension:* prefix `word*`, `NEAR(a b, N)`, `title:` — three FTS5-native additions gated by an
  explicit token class so `_quote`'s injection-safety stays (Q33).
- *Filters (v1 list, Q31):* language multi-select over asserted **and** detected (labelled), sources
  (facet picker with counts, no 404), source tags, provenance / channel, source country and region,
  published range via `ooTimeScope` with presets and a timescale selector, a **separate** "collected
  between" control (the ruled disclosure: never coalesced into "published"), word-count bands (script-aware:
  zh/ja/th excluded with a note), sentiment (English-only caveat visible), "mentions a date in range" over
  `article_mentioned_dates`, include-quarantined (advanced only, disclosed), sort.
- *Saved searches:* the Watch model gains the full filter set, so a saved search *is* a watch with a
  threshold of zero (Q36). *Export parity:* the export endpoint takes the same parameter set (Q37).
- *Enter:* the omnibar's Enter opens the analysis window; static commands need an explicit selection
  (the open product question at `app-shell.js:739–748`) (Q38).
- The DDG-discovered ingest ruled to hang off this tab keeps its slot.

Questions: Q31–Q38.

### 3.6 Wikipedia — the living encyclopaedia, without dumps

**The ask.** Wikipedia scraped, ingested, indexed and analysed like press articles, with as much metadata
as possible; every article tracked for changes, and the changes ingested, indexed and analysed; automatic;
defaulted to all twelve UI languages; the *entire* Wikipedia; **dumps are not the way**; a decisive plan.

**Verified state (`src/wiki/`, 13 files, 3,021 lines).**
- **Nothing is watched by default.** `WikiPage(...)` is constructed in exactly one place
  (`track.py:47`, `ensure_page`), reached only by `POST /api/wiki/pages` (a user adding one title). A fresh
  install has 0 pages, 0 revisions, 0 wiki Articles.
- Tracking is **per-page revision polling** (`update_page` → `fetch_revisions`). `list=recentchanges`
  has a builder, a parser and a client method and **no consumer**. No EventStreams / SSE anywhere.
- Wiki tracking is a scheduler **mode** (`settings.py:66` `mode="rss"`; `runner.py:744–761`), so on a
  default install the wiki pass **never runs**, and selecting it stops RSS collection.
- Per revision the store keeps `full_text` (compressed) plus a 2,000-char-per-side diff summary; per
  page it keeps `baseline_text` and `latest_text`. **No retention policy** for `wiki_revisions`.
- Corpus: only the **latest** text of a watched page becomes an Article (`corpus.py:324–334`;
  `source_revision` carried; no `pageid`, no QID, no `source_type`; `language` NULL outside 17 codes;
  `published_at` = last edit time). Revisions are stored but **never indexed or searchable**.
- Dumps: a full download manager, an offline reader, a disposable FTS side-file; dump→corpus exists
  only as `POST /api/wiki/dumps/corpus-ingest` with an explicit title list, limit 1,000, **no UI**.
- Fetch path: three Wikimedia hosts through `guarded_session` (kill switch honoured, Tor honoured, the
  descriptive bot UA kept on purpose), `maxlag=5`, 1.0 s per-process interval; **robots.txt is not
  consulted for these API/dump endpoints by design** (`fetcher.py:173–175`, the SDMX precedent) — the
  Wikipedia surface does not state that the way `stats/fetch.py:22–25` does.
- Rulings on record: 2026-06-12 "download a language dataset → the entire edition tracked
  automatically, per-article tracking retired" (record-only); 2026-06-13 "watched entirely and by default
  in all 12 UI editions" (not built; the Settings move and the download job **are** built); the mechanism
  named in both is **dump-as-baseline + `recentchanges`-delta**, P0-scale-gated on storage steps 3–5.
  Open: Q1 tiering, Q5 backups.
- Scale on record: enwiki ≈ 80–160k edits/day (~100k planning figure); ~6M+ articles for enwiki,
  tens of millions across editions; the 12 UI editions ≈ 65 GB of compressed dumps; the reference VM is
  2-core; the collector indexes ~2.3 articles/s CPU-bound (audit 12). Per-edition article and edit counts
  for the other eleven editions are **not recorded** in the repo.

**The consequence of "no dumps", stated before the plan.** A dump is the only way to obtain the pages
that nobody edits. Without it, a whole-edition baseline means fetching every page through the API —
~6M+ requests for enwiki alone, serialised at Wikimedia's etiquette, i.e. **months per edition** and a
load pattern the API policy discourages. So "the entire Wikipedia, no dumps" is reachable in exactly
one honest form: **stream-forward coverage** — every page that changes, from the day tracking starts,
enters the store on its first change; the never-edited tail is reached only slowly (a background
`allpages` walk at etiquette pace) or never. Coverage grows toward the whole edition and the report
says how far it has got (Q39 asks the maintainer to confirm this trade knowingly, and why dumps are out —
bandwidth over Tor, disk, or staleness — because a one-time dump baseline for the 12 editions remains the
cheapest route to the tail if the objection is only staleness).

**CORRECTED 2026-09-12 (the answer sheet, §8):** the "months per edition" above assumed one page per
request. The Action API returns the latest revision of up to **50 titles per request** (SEARCH-VERIFIED 2026-09-12),
so the ~24 M articles of the twelve editions are ~480,000 serial requests ≈ **5.6 days at one request per second**
on clearnet, moving 150–250 GB of wikitext (FROM MEMORY). The never-edited tail is reachable in about a week per
pass; the constraint is disk, not the API. Q39 is superseded by the sheet's Q701, which offers the background walk as
the recommended option.

**Proposal — the living-Wikipedia architecture (stream-forward, tiered, budgeted).**
1. *Identity.* `WikiPage` keyed `(wiki, pageid)` with `qid`; the Article carries `wiki_pageid`, `qid`,
   `source_revision` (exists), `source_type="wikipedia"`, categories, page length, revision count,
   last editor class (bot/anon/registered), and the edition as language (Q46).
2. *The change feed.* One SSE connection to Wikimedia EventStreams
   (`https://stream.wikimedia.org/v2/stream/recentchange`, SEARCH-VERIFIED), filtered client-side to the
   twelve editions and namespace 0, resumed with `Last-Event-ID` (SEARCH-VERIFIED; the replay window is
   bounded — days, FROM MEMORY, confirm at build). Event fields FROM MEMORY: `wiki`, `server_name`,
   `type`, `title`, `namespace`, `revision.old/new`, `timestamp`, `bot`, `minor`, `user`,
   `length.old/new`. A durable cursor per connection; a gap longer than the window falls back to
   `list=recentchanges` per edition (the client exists), never to a silent skip.
3. *Text fetch.* Changed pages are coalesced per page per interval, then fetched in batches of up to
   50 pages per `prop=revisions&rvprop=content` request (FROM MEMORY: the API caps multi-page content
   requests at 50; confirm), serialised at ≥ 1 s with `maxlag=5`. At ~3 edits/s across the twelve
   editions (FROM MEMORY, order of magnitude) this is well inside one request per second.
4. *Tiering (docket Q1).* **Metadata for every edit** in the twelve editions (a stream event is small;
   tens of MB/day compressed for enwiki, per the ledger). **Full text + `index_article`** for changed
   pages in priority order: HOT = pages the corpus already mentions or that are trending in the corpus,
   WARM = every other changed page, indexed lazily under a per-edition daily budget, COLD = never-changed
   pages, not fetched. The CPU arithmetic that forces this: at ~2.3 articles/s a full re-index of ~100k
   changed pages/day is ~12 h of one core — impossible on the 2-core VM beside collection (Q41).
5. *Revisions.* Metadata rows for every observed change; full text for the versions actually
   ingested; diff **against the previous ingested version**; a retention policy per tier (Q42).
   `index_article` runs on the latest text; per-mention revid anchoring per the standing ruling.
6. *Scheduler.* Wikipedia becomes a **lane** (a ride-along under the one online consent, like the
   hazard feeds), never a mode; the `mode="wiki"` path is retired (Q45).
7. *Ethics and disclosure.* EventStreams and the Action API are documented public services; the app
   follows their etiquette (UA, `maxlag`, serial requests); the robots exemption is stated on the
   Wikipedia surface like the SDMX precedent; the hosts are enumerated in `docs/SECURITY.md` (§4.3);
   ORES is either verified (Wikimedia has been migrating scoring to Lift Wing — FROM MEMORY, verify) or
   dropped (Q44). Wikimedia Enterprise is a keyed commercial service and stays excluded under V1-2 (Q48).
8. *Backups (docket Q5).* Wiki Articles ride the corpus backup as any Article; the revision store is an
   opt-in artifact member like the dumps (Q43).
9. *UI.* The tracked-changes modal (`#wiki-tc`) grows into the shared **Living sources** view of §4.1;
   the first-run wizard gains the edition choice ruled in 2026-06-13 (default: all twelve) (Q47).

Questions: Q39–Q48 (Q39, Q40 ⛔).

### 3.7 Maps and OpenStreetMap

**The ask.** Fix the map app-wide; adopt the Equal Earth projection the UN voted for instead of the
Mercator default; review how maps are handled; scrape, ingest, index and analyse OpenStreetMap, track its
changes, use it for analytics and spatial representation; maps treated as articles.

**Two premise corrections, one each way.**
- **The app does not use Mercator.** Its one projection is equirectangular (plate carrée):
  `lon2x = (lon+180)/360·720`, `lat2y = (90−lat)/180·360` (`app-map.js:21–24`, VERIFIED). There is no
  inverse anywhere, and no other projection is named in the tree. The 2026-06-18 map ruling kept it
  deliberately ("SALVAGE: the equirectangular projection"). Plate carrée distorts area too (it
  stretches high latitudes horizontally), so the maintainer's instinct is right even though the named
  culprit is wrong.
- **The UN vote is real and recent.** On 2026-09-04 the UN General Assembly adopted the
  "Correct the Map" resolution — 164 in favour, the United States against, 6 abstentions; put forward by
  African Union member states and the Bahamas; **non-binding**; it encourages equal-area projections such
  as Equal Earth (SEARCH-VERIFIED across CNN, NPR and Newsweek; the pages themselves are egress-blocked
  here). The African Union had endorsed the campaign in August 2025. The writer's memory had only the 2025
  endorsement; the maintainer's claim was newer than the writer's cutoff.

**Verified state.**
- Every map surface is the one `ooMap` component: World map (4 dimensions), Governments choropleth,
  Library "World coverage", Insights concept map, Statistics figure map, plus the legacy When×Where mini
  map. Nine `lon2x`/`lat2y` call sites (`app-map.js:44–49, 167–170, 211, 221, 332–333, 367, 380, 396, 427,
  439, 447`). Zoom rides the SVG `viewBox`, not the projection — a documented performance precondition
  that Equal Earth preserves (it is view-independent).
- Geometry: `world_countries.json` = Natural Earth 110m admin-0, 175 countries, 285 rings, 10,521
  vertices at 0.1° (~11 km), keyed alpha-2; ~75 microstates have no polygon and are drawn as a
  gazetteer-city point. **No admin-1 anywhere.** `world_outline.json` has no consumer.
- Gazetteer: **`configs/cities.yml` does not exist in the tree** — only a 2 KB `cities.sample.yml`; the
  Wikidata builder (`scripts/build_city_gazetteer.py`) needs a networked run.
- OSM: nine Geofabrik regions (dated sizes, planet ≈ 72 GB), a resumable segmented download manager
  through the guarded factory, and a **browser-side** PBF reader (`osmpbf.js`) that parses a ≤ 8 MB prefix
  of the first completed region for an ephemeral overlay. **No Python PBF reader, no preprocessing script,
  no admin-1 artifacts, no stored features, no `.osc` / replication handling** — `-latest.osm.pbf`
  overwrites vintage. `pyosmium`, `shapely`, `pyproj`, `geopandas` appear nowhere in `pyproject.toml`.
- **There is no Place entity.** `ArticleMentionedPlace` is a per-article, disposable, deduced row
  (name, country, kind, lat/lon copied from the gazetteer); identity is a string convention
  (`place_identity.py`). Nothing exists to attach a map feature, an id, metadata or a history to.
- Rulings on record: Q1a 2026-07-13 — OSM preprocessed **offline** into boundary/gazetteer artifacts
  feeding all thematic maps; **no-WebGL is firm**; live street-level detail out of scope; the build
  deferred to its own session. The 2026-07-13 action plan §Part 2 already names "a boundary is an Article;
  its OSM history is the linked audit layer" and border honesty ("OSM's convention as of `<date>`,
  contested borders as CONTESTED with both claims"). V1 0.8 carries "OSM dated-boundary change-tracking
  seed".

**Equal Earth, concretely.** A closed-form forward projection (Šavrič, Patterson & Jenny, 2018;
constants FROM MEMORY — confirm against the paper or d3-geo's reference before shipping):
`θ = asin((√3/2)·sin φ)`, `x = (2√3/3)·λ·cos θ / (9A₄θ⁸ + 7A₃θ⁶ + 3A₂θ² + A₁)`,
`y = A₁θ + A₂θ³ + A₃θ⁷ + A₄θ⁹`, with `A₁ = 1.340264, A₂ = −0.081106, A₃ = 0.000893, A₄ = 0.003796`.
Consequences for the code: `lon2x(lon)` and `lat2y(lat)` become one `project(lon, lat) → [x, y]` (x
depends on both); the nine call sites are rewritten; graticule lines become polylines (meridians curve);
the 720×360 box becomes ~2.05:1 and the viewBox/zoom/fullscreen/label maths follow; the a11y text summary
is unaffected; there is no inverse today, so nothing breaks, but a future click-to-coordinate needs
Newton iteration. The 0.1° polygons will look faceted under the polar shear — a 50m rebuild of
`world_countries.json` is the likely companion (Q50).

**Proposal — maps in three layers, OSM as a versioned source.**
1. *Projection (small, early).* Equal Earth on all five surfaces through the single seam, one
   projection, no toggle, named in the legend ("Equal Earth · equal-area") (Q49, Q50).
2. *Artifacts (build-time, maintainer machine).* The ruled preprocessing bridge: OSM → admin-0 at a
   finer tolerance + **admin-1** + a gazetteer with OSM ids, QIDs, population and names in the twelve
   languages → simplified shipped artifacts with registry entries and freshness tests, replacing Natural
   Earth; a pure-Python PBF reader for the bounded feature classes (a port of `osmpbf.js`, ~500 lines) so the
   core stays free of C extensions (Q53, Q56).
3. *Place entity (the entity spine).* `Place(id = OSM type+id, qid, kind, admin path, names ×12,
   geometry ref, as_of)` with `article_mentioned_places` resolving into it; a Place is the thing that can
   be an Article: its body is the Wikidata/Wikipedia description plus its OSM metadata rendered as
   metadata, its keywords come from that text, it is searchable and indexed (Q55, Q58).
4. *Change tracking.* Daily replication diffs (Geofabrik per-region `.osc.gz`, kept 100 days;
   planet minutely/hourly/daily at `planet.openstreetmap.org/replication` — SEARCH-VERIFIED) applied to the
   **tracked feature set only** (admin boundaries, populated places, and whatever Q52 adds); `.osc` is XML,
   so the reader is pure Python; each applied change is a `PlaceRevision` with a dated boundary snapshot,
   "OSM as of `<date>`" on every map, contested borders as CONTESTED with both claims (Q54, Q57).
5. *Analytics.* Place-keyed aggregates (articles → Place), admin-1 choropleths, point-in-polygon at build
   time into the artifacts, never at request time; LOD limits hold the no-WebGL line.
6. *Licence.* OSM data is ODbL: attribution plus share-alike on derived databases. OSM-derived rows inside
   the corpus make an exported corpus or a bulletin an ODbL-affected work — the same class as the CC BY-SA
   Wikipedia text the app already ingests, and inside the V1-3 line (redistributable), but it must be
   stated where the data leaves the machine (Q51 ⛔).

Questions: Q49–Q58 (Q51 ⛔).

### 3.8 Laws

**The ask.** Scrape, ingest, index and analyse all laws in the twelve UI languages from every country;
track their changes; analyse the tracked changes over time and geography; laws treated as articles with
metadata, keywords, search.

**Verified state (`src/law/`, 10 files).**
- Catalog: 275 sources (51 curated + 226 generated, 163 countries) and **24 documents → 23 registrable
  `LawDocument` rows on a fresh install** (uk 5, tl 6, eu 4, de 2, ca 2, int 2, us 1, fr 1). Only five of
  the twelve UI languages have any tracked document (en, pt, de, fr; tet is not a UI language);
  **es, ru, ar, zh, ja, hi, bn, id have zero**.
- **No enumeration anywhere**: no `list_documents()`, no crawl of any jurisdiction's index; 100 catalog
  rows carry an `enumeration_url` that nobody has fetched. 39 official counts on 32 countries, units not
  commensurable (acts, codes, gazette issues); the coverage diagnostic honestly refuses to divide.
- One adapter, CLML (legislation.gov.uk), fixture-tested, **never run on a fetched document**;
  `diff_provisions` exists and has no production caller. No EUR-Lex, gesetze-im-internet, Légifrance/LEGI,
  govinfo or BOE adapter.
- **No law-specific metadata model**: no ELI/CELEX/ECLI/act number, no enactment/commencement/in-force/
  repeal dates persisted (the adapter computes three dates and nothing stores them), no issuing body, no
  amends/amended-by relation. `jurisdiction` is a free `String(8)`.
- Only the **latest** text is an Article and searchable; `LawRevision.full_text` is written and never
  read. Diffs are **against the immutable baseline**, not the previous revision, so revision N's diff
  conflates every change since capture — the wrong primitive for evolution analysis.
- **Defect:** the reader (`GET /api/law/documents/{id}/view`, `src/api/law.py:417`) renders
  `doc.baseline_text` — the oldest text — although `latest_text` exists.
- Cadence: `auto_track_due` with a 24 h gate and `adaptive_track_budget` → 5 documents per pass at 23
  documents; no bulk/managed-dataset path. `[pdf]` is optional while 63 of 275 sources are PDF-only and 6 of
  the 23 tracked documents are PDFs. Three gazette feeds are on the ingest path but enter the
  qualification ladder rather than collection.
- Egress: `www.legislation.gov.uk`, `eur-lex.europa.eu`, `www.gesetze-im-internet.de`, `legal.gov.vc`
  all `000` from this sandbox (re-probed 2026-09-07); Légifrance's code list 403. The ruled adapter-first
  path (A4) cannot be live-verified from any session until the allowlist changes (F1 ⛔).
- Rulings: A3 act/code level by default, per-provision rows only for pre-split bulk sources; A4
  adapter-first; A5 AI summaries auto for UI-language jurisdictions (shipped). Open: Q-LAW-1..4.

**Proposal — the law vertical as a versioned source, with a change-analysis surface.**
- *L0 defects (small, now):* the reader shows `latest_text` with a version selector; diffs are computed
  against the previous revision (the baseline diff kept as a derived view); the adapter's three dates are
  persisted (Q59).
- *L1 metadata model:* `LawDocument` gains official identifiers (ELI / CELEX / ECLI / act number),
  issuing body, dates (enacted, commenced, in force, repealed), legal system, status; a `Provision` table
  with a stable address for pre-split sources (A3); `jurisdiction` normalised through the same country
  formatter as §3.2 (Q60).
- *L2 enumeration adapters (adapter-first, A4):* legislation.gov.uk → gesetze-im-internet → EUR-Lex, each
  a `list_documents()` + `parse()` pair with a per-document live-verification instrument
  (`structured.documents_captured` is the hook), fixture-exercised now, live-verified the day egress opens
  (Q65).
- *L3 managed datasets:* France through DILA's LEGI base + daily deltas — the wiki-dump precedent applied
  to law, and the only honest route to ~10⁵ articles in force (Q65).
- *L4 per-revision searchability:* FTS over revisions with `valid_on`, so a point-in-time search ("what
  did this say in 2019") is possible without one Article per revision (Q61).
- *L5 the evolution surface:* per-provision diff promoted to the stored primitive; amendment velocity per
  jurisdiction over time; cross-jurisdiction comparison by **concept** (the same ring translation as
  §3.3 — a search for "asylum" finds the provisions across languages); an Equal Earth map of amendment
  activity with the vintage stated (Q62).
- *L6 breadth:* gazette streams (S7) for countries with no structured source, the qualification ladder
  admitting them; the coverage floor = every country where a UI language is official, reusing the
  elections language→country mapping (V1 §4.5) (Q63).
- *L7 operability:* `[pdf]` in the default extras (Q-LAW-2); `counts_documents` declared per official
  count (Q-LAW-1); the 44-row vetting board and the verification tier for endpoints (Q-LAW-3/4) (Q64).
- *AI stays where it is:* summaries "AI-derived · unreliable"; dates and provisions come from rules,
  never from the model (Q66).

Questions: Q59–Q66 (Q65 ⛔ on egress).

---

## 4. Cross-cutting threads

### 4.1 One versioned-source substrate for Wikipedia, laws and OSM

Items 6, 7 and 8 ask for the same thing three times: an external, mutable, authoritative corpus, ingested
as Articles with rich metadata, tracked for changes, with the changes themselves ingested and analysable.
`FUTURE_DEVELOPMENTS.md` already names the pattern ("a versioned source is an Article + a linked
revision/audit trail"). Three parallel implementations would drift; one substrate would not. Proposed
shape (`src/versioned/`, Q68):

| Concern | Shared | Per kind |
|---|---|---|
| Identity | `(kind, external_id)` + optional QID | wiki `(wiki, pageid)` · law identifier · OSM `type+id` |
| Baseline | first-seen text/geometry, immutable | — |
| Change feed | cursor, gap detection, budget, politeness | EventStreams · adapter poll / bulk delta · replication diff |
| Revision store | metadata for every change; text/geometry for ingested versions; diff vs previous | retention policy per kind |
| Latest as Article | `source_revision`, `source_type`, provenance class | metadata fields |
| Point in time | reconstruct from stored versions; optional FTS over revisions | — |
| Disclosure | "as of revision / date", deduced-never-confirmed, no scores | licence line |
| UI | one **Living sources** view: timeline, diff, coverage, freshness | — |
| Diagnostics | one coverage/freshness member per kind in the all-diagnostics bundle | — |
| Backup | Articles ride the corpus; revision stores are opt-in members | — |

### 4.2 The identity rule that item 2 sets

Whatever §3.2 decides, one principle carries: **internal identity is a stable code; display is a
formatter**. The same rule serves Places (OSM id inside, name outside), laws (ELI inside, title outside)
and wiki pages (pageid inside, title outside). The country migration is the first application and its
shape sets the precedent.

### 4.3 Endpoint enumeration — a documentation defect found on the way

`docs/SECURITY.md` §"the full set of endpoints the app can reach … re-verified 2026-09-08" lists
DuckDuckGo, Open-Meteo, the statistics endpoints, the GitHub releases API, Ollama's pulls and the hazard
feeds. It **omits** (VERIFIED against the tree): the Wikidata Query Service reached by the world-discovery
ride-along on every online pass by default (`src/catalog/discover.py:36–41`, `world_discovery_per_pass=2`),
the Wikipedia Action API and ORES (`src/wiki/client.py`, `ores.py`), Wikimedia dumps, and the Geofabrik /
planet.osm mirrors. The sentence "every other outbound call is consented and off the default path" is
true; the list under it is not complete. This is a docs-only fix; it is recorded here and not made,
per "we're only making plans" (Q67). Every new host this roadmap introduces (EventStreams, replication
diffs, Wikidata for ring refresh) must land in that list in the same PR that adds the call.

### 4.4 The egress allowlist is the critical path

Five consecutive sessions have failed a reach-a-named-publisher task through five different tool
surfaces; the variable was never the prompt. One allowlist entry each for `www.legislation.gov.uk`,
`eur-lex.europa.eu`, `www.gesetze-im-internet.de`, `api.worldbank.org`, `www.wikidata.org` /
`query.wikidata.org` and `dumps.wikimedia.org` unblocks the law adapters, the World Bank code
verification, the month-occupancy diagnostic's ring refresh and the Wikipedia edition facts this plan
could not record. Without it every "live-verified" bar in §5 is an operator step on the maintainer's own
machine (Q4).

### 4.5 Licences

Wikipedia text is CC BY-SA 4.0 (already ingested); OSM is ODbL (share-alike on derived databases);
DB-IP is CC BY 4.0 (attribution kept by ruling); Wikidata is CC0. All are redistributable and inside
V1-3. What each requires is a **statement at the point the data leaves the machine** (exports,
bulletins, evidence ZIPs): attribution lines and, for OSM-derived rows, the share-alike note (Q51).

### 4.6 What the 2-core reference VM forbids

Every scale-bound design above (Wikipedia tiers, OSM preprocessing on the maintainer's machine, law
bulk datasets as managed jobs) follows from two recorded facts: the collector indexes ~2.3 articles/s
on one core, and the field fleet includes 2-core / 3.5 GB machines. A plan that ignores them ships
features that only the maintainer's GPU box can run. Every budget in §5 is therefore **hardware-aware and
published**, never silent.

---

## 5. The alpha train to beta (proposal)

**Where beta sits.** The approved train has 0.9 as the hardening RC. This plan proposes **beta = 0.9.0**:
feature-complete for the 1.0 scope, no new verticals after it, external testers invited, the 1.0 RC gate
(V1 §8) built and run. Every release before it is an alpha: 0.3 (closing), 0.4, 0.5, 0.6, 0.7, 0.8 (Q1).
The eight impressions load 0.4 and 0.5 heavily and pull one 0.8 item forward; the theme names of the
approved train are kept, their contents amended (Q2).

Each release below lists: theme · contents (S = slice) · entry gate · exit gate rows · rulings it needs
· operator steps. Gate files are written per release once the answers are in.

### 0.3 → close now
- Row 5 (the Tier-A quarantine run, 8 articles) + the `v0.3.0` tag from the maintainer's machine; then
  the version flips to `0.4.0` (Q3). Nothing in this plan should wait for it, but 0.4 work should land on
  a tagged base.

### 0.4 — Living sources (the substrate release)
- **S4.1** the versioned-source substrate (§4.1) with the wiki adapter first.
- **S4.2** Wikipedia stream-forward, twelve editions, metadata tier for every edit + HOT full-text tier,
  as a lane; the edition choice in the first-run wizard; the Living sources view replaces the modal.
- **S4.3** laws L0 (defects) + L1 (metadata model) + the enumeration seam fixture-exercised; L2 adapters
  live-verified the day egress opens (operator).
- **S4.4** import/export UX: the four-stage lifecycle, fresh page, one poll owner, export completion
  panel + `BACKUP_SUMMARY.md`, dated folders with reuse; the two backup APIs unified.
- **S4.5** keyword translation: `translation_source_lang`, the display helper on every keyword
  surface, the seven endpoints gain `target_lang`, cards translate with "(translated from X)".
- **S4.6** cross-language search everywhere: `resolve_concept` shared by FTS and the keyword-keyed
  aggregates; per-language stacked series; literal toggle and sense pins persisted.
- **S4.7** ISO-3 display boundary (§3.2) — the storage half only if Q13 rules it.
- **S4.8** Equal Earth on the single projection seam (small).
- **S4.9** `docs/SECURITY.md` enumeration completed; every new host added with its call.
- Entry gate: 0.3 tagged. Exit gate: the existing 0.4 rows A–F **plus** rows for: Wikipedia lane running
  ≥ 72 h on the reference VM inside budget; laws L0/L1 shipped and the reader shows the latest text; the
  import lifecycle states all three "you may now" facts and a killed-then-restarted import resumes stage 4;
  every keyword surface shows a tier tag; every analysis tab agrees with the Articles list on the same
  concept; SECURITY.md complete. Rulings: Q5–Q30, Q39–Q48, Q59–Q60, Q67–Q68. Operator: allowlist (Q4),
  the 0.4 rows A–C runs.

### 0.5 — The investigator's desk
- **S5.1** advanced search (§3.5): builder, grammar extension, the v1 filter set on `ooTimeScope`,
  saved searches on the Watch model, export parity, Enter → analysis.
- **S5.2** the Place entity + the OSM preprocessing bridge producing admin-1 + gazetteer artifacts
  (maintainer-machine build); `article_mentioned_places` resolves into Places; Places as Articles.
- **S5.3** the claim workspace A1 and the entity spine (approved 0.5 content), now with Places and
  keyword concepts as first-class entities.
- **S5.4** laws L4 (point-in-time search) + L5 (the evolution surface).
- **S5.5** Wikipedia WARM tier under a published per-edition budget; the in-app ring-refresh job and
  the tentative-translation store (Tier 2).
- **S5.6** typo tolerance per Q35.
- Exit rows: every ruled advanced-search field reachable and exported; a saved search re-runs
  identically; admin-1 renders on all five surfaces from shipped artifacts with their vintage; a law's
  2019 text is findable; the ring-refresh job runs at ≤ 1 request / 10 s and its proposals reach review.
  Rulings: Q31–Q38, Q49–Q58, Q61–Q62.

### 0.6 — Elections + climate (approved), plus breadth
- The approved keyless climate and elections verticals; laws L6 breadth via gazettes toward the
  language coverage floor; Wikipedia coverage report per edition (how much of the edition the stream has
  reached); OSM change tracking for the tracked feature set (daily diffs, dated boundary snapshots).
- Exit rows: the elections coverage floor; laws tracked in all twelve UI languages; OSM vintage stated on
  every map; a contested border renders as contested.

### 0.7 — Medical + patents (approved)
- As approved; patents remain at risk on the USPTO bulk precondition. Cross-vertical: the versioned-source
  substrate gains PubMed-style managed datasets if the 0.6 exit shows the machinery holds.

### 0.8 — Conflict + the 360° dossier (approved)
- The dossier composes press, Wikipedia, law, Places and statistics over one entity; the OSM
  dated-boundary seed (approved) is by then the tracked-feature history from 0.6.

### 0.9 — Beta (hardening RC)
- Feature freeze; the 1.0 RC gate from V1 §8; the Windows lane blocking; the Gecko/AppVM browser bar;
  the storage rulings executed; migrations frozen; docs↔app reciprocity swept; the no-telemetry re-check;
  external testers. Exit = the 1.0 gate green.

### 1.0

### What this train does *not* do
- It does not schedule a whole-edition dump baseline (the maintainer ruled dumps out; Q39 asks whether
  a one-time baseline is still acceptable for the never-edited tail).
- It does not put OSM street-level detail, WebGL, or an in-app planet preprocessing job anywhere.
- It does not move the four pending storage rulings; they gate Phase C, which the stream-forward
  Wikipedia design makes less urgent, not moot.
- It does not decide any ⛔ question.

---

## 6. Questions for the maintainer

> **SUPERSEDED 2026-09-12 by [`ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md).**
> Every question below is folded into the sheet under a new ID (cited there as "was Qn") with its options,
> impacts and a default; answer the sheet, not this list. Kept for the record.

Answer by number and letter ("Q13: a"). Each question carries the recommended default the executing
session would take under the 2026-06-15 autonomy ruling **unless marked ⛔** (irreversible, outward-facing
or data-safety): those stay gated until answered. 🔒 marks a ruling that is reversible but must still be
explicit because it changes what the app retains or contacts.

### The train
- **Q1.** Beta placement: (a) beta = 0.9.0, feature-complete + hardening, alphas 0.4–0.8 (recommended);
  (b) an earlier beta at 0.6 with verticals continuing in beta.
- **Q2.** Accept the amended contents of 0.4/0.5 in §5 (the eight items absorbed there, OSM artifacts
  pulled from 0.8 to 0.5)? (a) yes (recommended); (b) keep the approved contents and add a 0.4.5.
- **Q3.** Close 0.3 now (row 5 + tag) before 0.4 work lands? (a) yes (recommended); (b) fold row 5 into
  0.4.
- **Q4 ⛔.** The egress allowlist for the hosts in §4.4: (a) add them to the session environment;
  (b) the maintainer runs the live-verification steps on their own machine each time; (c) both.

### Import / export (§3.1)
- **Q5.** Reopening the import dialog: (a) fresh page + a one-line "last import" link onto the persisted
  report (recommended); (b) keep re-rendering the previous run (the 2026-07-16 ruling).
- **Q6.** The deferred re-index: (a) stage 4 inside the import experience with its own row and a
  task-manager link (recommended); (b) task manager only, the import ends at stage 3.
- **Q7.** The three statements — "files may be removed", "safe to close or update", "analytics
  complete" — at stages 2, 2 and 4 as in the table: confirm or amend.
- **Q8.** "Details": (a) remove (recommended); (b) collapse behind a toggle.
- **Q9.** Folder name `YYYYMMDDHHMM_OOS_Backup`: (a) local time (recommended); (b) UTC. Collision suffix
  `_2`, `_3`…: confirm.
- **Q10.** Dated folders vs incremental reuse: (a) always a new dated folder, reuse pool widened to
  sibling `*_OOS_Backup*` folders (recommended); (b) a per-export choice "refresh existing / new dated";
  (c) always a full new backup.
- **Q11.** Export completion panel + `BACKUP_SUMMARY.md` inside the folder: (a) yes (recommended); (b)
  panel only.
- **Q12.** Unify the two backup-restore APIs (Q-VIS-5) in 0.4: (a) yes (recommended); (b) later.

### ISO 3166-1 alpha-3 (§3.2)
- **Q13 ⛔.** (a) display-and-boundary migration, storage stays alpha-2 (recommended, for the restore-merge
  and external-contract reasons in §3.2); (b) full storage migration, accepting the six column rewrites,
  the config rewrite and the backup-identity break, with a one-way migration and a restore-side
  normaliser.
- **Q14.** Display form: (a) uppercase `FRA` beside the localised name everywhere a code shows
  (recommended); (b) code only; (c) name only, code in the hover.
- **Q15.** Non-ISO values: `int` → `INT` (app-defined, disclosed), `eu` → `EUU` (World Bank convention),
  `xk` → `XKX`, `an` → `ANT`, law `uk` → `GBR`: confirm or amend.
- **Q16.** API: (a) keep `country` alpha-2 and add `country_iso3` to every payload; every parameter
  accepts both (recommended); (b) redefine `country` (breaks exports, tests, old backups).
- **Q17.** Config files stay alpha-2 (recommended) or are rewritten (5,803 lines)?
- **Q18.** Language codes stay ISO 639-1 (two letters): confirm (recommended). ISO 639-3 would touch the
  twelve locale files, `Article.language`, and every language filter.

### Keyword translation (§3.3)
- **Q19.** Label grammar: (a) translated term first, "translated from French: climat" in the hover and
  as a small tag (recommended); (b) original first with an arrow, as today's `→`.
- **Q20.** Tentative (LLM) translations in lists: (a) shown by default once persisted, always ≈
  (recommended when the AI coordinator is on); (b) on demand only, as today.
- **Q21 🔒.** Persist tentative translations in a `keyword_translations` table (never the trusted index):
  (a) yes (recommended); (b) keep the process cache.
- **Q22 ⛔.** In-app ring refresh contacting Wikidata: (a) a consented job at ≤ 1 request / 10 s, proposals
  reviewed before they load (recommended); (b) operator script only. Note the generator's 0.2 s spacing
  must change either way.
- **Q23.** Rings in backups: (a) locally accepted rings live in `data_dir()` and ride the backup; shipped
  rings do not (recommended); (b) all rings; (c) none.
- **Q24.** Card titles translate the term with "(translated from X)": (a) yes, as a ruled exception to
  the "data never translates" design (recommended); (b) cards keep the original term.
- **Q25.** The 91 collision terms: (a) no single translation; show "several senses" and the picker
  (recommended); (b) show the most common sense's word with a marker.
- **Q26.** Source-language basis = the ring member's language (the effective language), with the
  reconcile pass run in the 0.4 gate: confirm.

### Cross-language search (§3.4)
- **Q27.** Expansion on by default in every analysis subtab, disclosed, one persisted literal toggle:
  (a) yes (recommended); (b) per-tab opt-in.
- **Q28.** Merged concept series: (a) stacked per language with a legend (recommended); (b) one merged
  line; (c) one series per language, unstacked.
- **Q29.** A member cap per expansion (e.g. 40 literals) with disclosure: (a) yes (recommended); (b)
  no cap.
- **Q30.** Sense pins and the literal toggle persist in the tab seed and URL: confirm (recommended).

### Advanced search (§3.5)
- **Q31.** The v1 filter list in §3.5: confirm or prune.
- **Q32.** Builder style: (a) rows `field · operator · value` compiling to the visible query
  (recommended); (b) chips only; (c) a plain form.
- **Q33.** Add FTS5-native prefix, NEAR and `title:`: (a) yes (recommended); (b) no.
- **Q34.** Operator words: (a) English tokens stay canonical; the builder is the localised layer
  (recommended); (b) accept localised aliases (risky: French `OR`).
- **Q35.** Typo tolerance: (a) unbuilt (ledger default); (b) a SymSpell-shaped precomputed table with a
  build job (recommended for 0.5); (c) `spellfix1` (rejected: vendors a compiled extension).
- **Q36.** Saved searches: (a) the Watch model gains the full filter set (recommended); (b) a new
  `SavedSearch` model.
- **Q37.** Export takes the full parameter set: confirm (recommended).
- **Q38.** Omnibar Enter always opens the analysis window: (a) yes (recommended); (b) keep the current
  precedence of static commands.

### Wikipedia (§3.6)
- **Q39 ⛔.** Coverage without dumps: (a) stream-forward only, coverage reported per edition
  (recommended given the ruling); (b) stream-forward plus a one-time dump baseline per edition for the
  never-edited tail; (c) stream-forward plus a slow `allpages` background walk. Please state the reason
  dumps are out (bandwidth over Tor, disk, staleness) so the trade is recorded.
- **Q40 ⛔.** EventStreams + the Action API + ORES as automatic egress under the one online consent,
  default on for the twelve editions, enumerated in SECURITY.md: (a) yes (recommended); (b) a dedicated
  Wikipedia toggle, default off.
- **Q41.** The three tiers (metadata for every edit; full text + index for HOT then WARM under a per-edition
  daily budget; COLD never fetched): confirm; and the default budget on the reference VM (proposed: what
  one core can index in 2 h/day, published).
- **Q42 🔒.** Retention: (a) every ingested version's text kept for HOT pages, latest + previous for WARM,
  metadata forever (recommended); (b) all versions for all tiers; (c) latest only.
- **Q43.** Backups: wiki Articles in the corpus backup; the revision store an opt-in member:
  confirm (recommended).
- **Q44.** ORES: (a) keep as opt-in, verified against Wikimedia's current scoring service first;
  (b) drop.
- **Q45.** Wikipedia as a lane, the `mode="wiki"` path retired: confirm (recommended).
- **Q46.** Identity: `pageid` + QID on `WikiPage` and the Article: confirm (recommended).
- **Q47.** The Living sources view (one shared view for wiki/law/OSM) replaces the tracked-changes modal:
  (a) yes (recommended); (b) keep per-kind surfaces.
- **Q48.** Wikimedia Enterprise and other keyed APIs stay excluded under V1-2: confirm.

### Maps and OSM (§3.7)
- **Q49.** Equal Earth on all five surfaces, one projection, no toggle, named in the legend:
  (a) yes (recommended); (b) keep a plate-carrée toggle.
- **Q50.** Rebuild `world_countries.json` from Natural Earth 50m for the new projection
  (a few hundred KB more): (a) yes (recommended); (b) keep 110m.
- **Q51 ⛔.** ODbL: OSM-derived rows inside the corpus make exports and bulletins share-alike works;
  accept, with the attribution + share-alike line at every export point: (a) yes (recommended);
  (b) keep OSM out of the corpus (artifacts and rendering only).
- **Q52.** Tracked feature classes that become Places/Articles: (a) admin boundaries (levels 2–6) +
  populated places (recommended); (b) plus named natural features and infrastructure classes; (c) more.
- **Q53.** PBF reading: (a) a pure-Python reader for the bounded classes, planet preprocessing on the
  maintainer's machine (recommended); (b) a `[geo]` extra with pyosmium/shapely.
- **Q54 🔒.** Change feed: (a) Geofabrik daily diffs per region, filtered to tracked features
  (recommended); (b) planet hourly; (c) planet minutely.
- **Q55.** The Place entity as in §3.7, `article_mentioned_places` resolving into it: confirm.
- **Q56.** Gazetteer rebuilt from an OSM + Wikidata join (needs a networked run): confirm.
- **Q57.** Contested borders rendered as CONTESTED with both claims, never a silent pick: confirm.
- **Q58.** A Place's article body = Wikidata/Wikipedia description + OSM metadata as metadata:
  (a) yes (recommended); (b) OSM tags only.

### Laws (§3.8)
- **Q59.** L0 defects first (reader shows latest text with a version selector; diff vs previous; dates
  persisted): confirm (recommended).
- **Q60.** The metadata model in §3.8 (identifiers, dates, issuing body, status, `Provision` table):
  confirm or amend.
- **Q61.** Per-revision search: (a) FTS over revisions with `valid_on` (recommended); (b) one Article per
  revision; (c) latest only.
- **Q62.** The evolution surface: per-provision diff, amendment velocity per jurisdiction, cross-
  jurisdiction comparison by concept, the map of amendment activity: confirm the four for 0.5.
- **Q63.** Coverage floor = every country where a UI language is official (reusing the elections
  mapping): confirm.
- **Q64.** Q-LAW-1 `counts_documents` (recommended a), Q-LAW-2 `[pdf]` default (recommended yes),
  Q-LAW-3 the 44-row vetting board, Q-LAW-4 the verification tier: answer each.
- **Q65 ⛔.** Adapter order and the bulk path: legislation.gov.uk → gesetze-im-internet → EUR-Lex, then
  DILA LEGI as the first managed dataset: confirm; and see Q4.
- **Q66.** AI stays summary-only and unreliable-labelled; dates and provisions from rules: confirm.

### Cross-cutting
- **Q67.** Complete the `docs/SECURITY.md` endpoint list now as a docs-only PR: (a) yes (recommended);
  (b) with 0.4.
- **Q68.** One versioned-source substrate (`src/versioned/`) for wiki/law/OSM: (a) yes (recommended);
  (b) three implementations.
- **Q69.** The rulings artifact ("Open Omniscience Rulings") recorded one answer, `A2: default`, at
  2026-09-12T07:37Z. Was that you? (a) yes, record A2 as its default; (b) no, ignore it.
- **Q70.** Where to collect the answers to this list: (a) inline by number (recommended); (b) add these
  questions to the rulings artifact.

---

## 7. Operator steps this plan depends on (none guessable from a session)
1. The egress allowlist entries in §4.4, or the equivalent runs on the maintainer's machine.
2. The 0.3 row-5 quarantine run and the `v0.3.0` tag.
3. The 0.4 rows A–C runs (committed full import at scale, the ≥ 72 h soak, the ~1M diagnostics).
4. A networked run of the gazetteer builder and, later, the OSM preprocessing bridge.
5. One fetched CLML document through `parse_clml`.
6. Per-edition Wikipedia facts (article and daily-edit counts for the eleven non-English editions) —
   not recorded in the repo; needed to set the per-edition budgets honestly.

## 8. Rulings received in the 2026-09-12 message (recorded in `docs/ledger/OPEN_QUEUE.md`)
The message itself decides several things regardless of the questions above: a fresh import page;
"details" adds no value; export completion must be clear and enumerated; the export folder naming
convention; alpha-3 is wanted (the *how* is Q13); keywords and cards in the UI language with a
"translated from X" tag; cross-language search across every tab with a literal restriction; an advanced
search with visual operators; Wikipedia in all twelve UI languages, whole and automatic, **without
dumps**; Equal Earth; OSM as a tracked, ingested source; laws for every country in the twelve languages
with change analysis over time and geography. Each is recorded as a ruling with its open questions.
