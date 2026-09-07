> **Archived 2026-09-07 from `docs/FUTURE_DEVELOPMENTS.md`, verbatim and unedited.** It is an embedded
> HISTORICAL LEDGER — the maintainer's own rechecked checklist, which the section itself records as overlapping the authoritative CLAUDE.md queue — and it was displacing the design-intent material that document exists
> for. Nothing was condensed or dropped in the move. Its still-open items live on the live boards
> (`CLAUDE.md`'s Open queue and `docs/ROADMAP.md`); read this file as a record of what was observed and
> when, not as a status.

## CONSOLIDATED TO-DO (rechecked & complete, captured 2026-06-24)

> The maintainer's own rechecked checklist (reconciled with the parallel testing session).
> Overlaps the detailed **CLAUDE.md Open queue** (the authoritative ledger) — kept here as a
> single glanceable list. Status: `[x]` done · `[~]` in progress · `[ ]` not started.
> **Verify against current `0.09` before starting** — the parallel BACKUP workstream (OOENC2
> streaming volumes + large-data folder backup, #450/#454/#456) and the 2026-06-24 diagnostics
> fixes have advanced the tree.

### Your field-test remarks, 24 Jun
- [~] 1. Ollama installer in Settings → AI: hardware-tiered scenarios + guided model-download; lead with Mistral (mistral-small, mistral:7b) — PARTIAL (2026-06-24): the model CATALOG now leads with Mistral (mistral:7b + mistral-small:latest). DEFERRED: the binary installer (blocked on per-OS checksums, networked machine) + the hardware-tier scenario messaging.
- [~] 2/5/6. ONE unified Import + ONE unified Export/Backup: pop-up options → file/folder pick, on the new streaming-volume path; clear progress bar + live data-volume readout; fuse both newsletter-import paths in — DESIGN DONE (`docs/design/UNIFIED_IMPORT_EXPORT.md`): one Import + one Export dialog reusing the shipped backends (OOENC2 volumes + folder backup + the two newsletter paths). Build deferred to a click-through session (large frontend, browser-unverifiable).
- [x] 7. Home "Loading the briefing…" hang + progress bar — DONE (#455: non-blocking background recompute + determinate progress bar)
- [~] 8. Insights / per-keyword analysis freeze ("Loading…" forever) — in progress (#458 cached the 5 per-corpus endpoints + an honest slow-load note; #455 warmed grouped top/trending off-thread; the 2026-06-24 autonomous session added a STATEMENT-DEADLINE guard on associations/graph/framing → typed 503 within 60s instead of an infinite hang, surfaced by the existing subtab error-notes. LEFT: the cold FIRST-open speed — the keyword_daily rollup [5A-bis D2], gated on the persisted encrypted DuckDB store [D1])
- [x] 9. Search: pressing Enter should open a new analysis window/tab — DONE (2026-06-24 autonomous session): the palette Enter now calls `openAnalysisInNewTab(raw)` → `window.open("/?analyze=…")`, hydrated by the existing `_hydrateCardCorpus` boot deep-link; in-SPA `openAnalysisFor` kept for results/cards. Browser-unverified (fork-3).
- [x] 10. Library tab world map: per-country article counts + a per-language donut for "no country" articles (full language names) — DONE (2026-06-24): the Library "World coverage" now leads with an ooMap choropleth of per-country article counts + a new `ooDonut` of the unlocated-by-language bucket (full names via ooLangName). Backend `source_country_counts` gained the column-projected `by_language` breakdown. Browser-unverified (fork-3).
- [x] 11. Settings: fuse Appearance + GUIs into one "Graphics" subtab — DONE (2026-06-24): one `data-tab="graphics"` subtab holds both the Appearance controls + the GUIs gallery (`#guis-gallery` kept). Browser-unverified (fork-3).
- [x] 12. Settings: remove the top intro box on every subtab (reclaim space) — DONE (2026-06-24): the h2+intro panel removed, the subtab nav un-wrapped. Browser-unverified (fork-3).
- [x] 13. AI prompts: translate the prompt textareas on language switch + verify output comes out in the UI language — DONE (2026-06-24): the labels auto-translate (static, keyed) + loadLlmPrompts re-renders on langchange; the prompt BODIES stay English by design; closed the 3 output-language gaps so single-article summarize (ui_lang) + translate (defaults to UI language) come out in the UI language like bulk/synthesis. Browser-unverified (fork-3).
- [~] 14. Status bar: opaque background matching the left sidebar (content shows through when scrolling) — first fix 2026-06-24 (`.topbar` + `.subtab-strip` → `var(--bg2)`, backdrop-blur dropped) **REOPENED 2026-06-25 (field report: STILL transparent).** Root cause: the bg was on the CHILDREN only; the sticky `.chrome` WRAPPER (`app.css:127`) had no background, so when the facet strip is hidden (most tabs) or a seam exists, scrolled content shows through. Candidate fix applied 2026-06-25 (`background:var(--bg2)` on `.chrome` itself + guard in `test_settings_chrome_cleanups`); **browser-unverified — confirm on click-through.** If still see-through after this build: the deployed app may predate the fix, a theme's `--bg2` may be translucent, or a GUI skin restyles the bar.
- [x] 15. Sidebar: click empty space to collapse/expand + a clear maximize button in the collapsed rail — DONE (2026-06-24): empty-space click → `toggleSidebar()` (ignoring nav items/controls); the #sb-collapse/#sb-expand affordances already existed. Browser-unverified (fork-3).
- [x] 16. Library tab = central dashboard of everything downloaded (maps, Wikipedia, indices, laws, stats) + extrapolated (summaries/translations/synthesis counts) — DONE (2026-06-24): new `GET /api/library/overview` rolls up the downloaded layer (wiki dumps/OSM/markets/laws/stats/models, counts + on-disk bytes) + the AI-derived layer (article_analyses by kind + ai_keyword + watches); a top "Library" dashboard panel renders both. Reuses cached database_stats + the download managers; honest counts/sizes, no score. Browser-unverified (fork-3).

### Bugs
- [x] Folder newsletter import: `UNIQUE constraint failed: articles.hash` on large multi-folder .eml imports — **fix-merged (#453)**: the hardened `ingest_emails` dedup keys on the real unique column + recovers per-message, fixing BOTH the upload endpoint AND the folder-import job (both call it). The 17:55 debug bundle confirms only HISTORICAL occurrences (locked/unique errors this session = 0) — **verify on a fresh live re-import of the 5 GB tree**.
- [~] Collector is writer-bound (many parallel fetchers → 1 DB writer): batch writes / cut gate contention *(ledger P1-C)* — DESIGN DONE (`docs/design/COLLECTOR_WRITER_BATCHING.md`: safe per-source batched store+index via `index_article(commit=False)` + the `ingest_emails` fallback; `synchronous=NORMAL` already in place). Implementation DEFERRED to a session that can run the full suite + measure on the live corpus (a blind refactor of the keystone-#1 writer hot path violates "entirely reliable or it should not exist").

### Keyword engine cleanup (on your live corpus)
- [ ] Run "Clean up keywords (re-index, then prune)" + measure the drop
- [ ] Run baseline-tag backfill (tag coverage is 0%)
- [ ] Generate translation rings from the exported keyword log (networked machine)
- [x] Filter English gov-newsletter boilerplate (govdelivery / gd_combo_table) from the "?" bucket — DONE (2026-06-24): `gd_combo_table` (underscore template id) already drops via the shipped §2.6 `_is_code_token` rule; `govdelivery` STAYS content per ruling #4. Added a self-test golden case pinning both. The bucket's undetected-English half is the shipped §2.6 langdetect.
- [ ] Decide zh/ja segmentation (currently no keywords for those)

### Manipulation-pattern cards (7 of 9 measures built; 6 standalone producers + outrage as secondary)
- [x] astroturf / copypasta — DONE (2026-06-25): a SPAN-level card distinct from echo_chamber (verbatim phrase across many distinct sources in NON-duplicate articles; wire republish excluded). `src/signals/near_dup.py:shared_word_ngrams` + `src/analytics/copypasta.py` + producer + `GET /api/insights/copypasta`.
- [x] outrage-intensity — DONE (2026-06-25): the 9th measure, built SECONDARY per the ruling (annotates another card, never a standalone Lead). `src/analytics/outrage.py:outrage_intensity` (loaded/intensifier density + `!` + ALL-CAPS runs; structure-not-intent; English-only with an honest gap, never a fabricated 0; no score) wired as an `outrage` component on the headline-body card. 6 sandbox tests.
- [ ] #4 "bury" half (needs an external trigger) · event-timed-op (needs elections roster)

### Release / housekeeping
- [ ] Human click-through of all browser-unverified UI
- [ ] Flip 0.0.9 → 0.1 when RC-blocking items are green
- [ ] App self-update (manual git-pull: snapshot → verify → migrate → swap → rollback)
- [~] i18n: key the remaining English-fallback panel strings ×12 — IN PROGRESS (2026-06-25): keyed 35 across three slices — the new Library/Governments/Graphics + backup labels, the 12 diagnostics download buttons + large-backup label + world-map drag hint, then 5 clean help paragraphs (volume-restore honesty line, diagnostics-archive + all-keywords + keyword-growth descriptions, technical tokens preserved). audit 140→105, gate 100%. Remaining ~105 are mostly data/examples/URLs that stay literal + the most security-/technically-dense paragraphs (custody IP/timing, AES-GCM/Reed-Solomon volume backup — left for native review) + the mid-`<a>`-link sentence fragments (de-tagging tail).

### Bigger / deferred (design-only)
- [ ] Elections & civic vertical (needs a sourced candidate roster)
- [ ] Persisted encrypted columnar store (per-OS httpfs crypto-extension packaging decision)
- [ ] LLM who/where/when + sentiment eval harness
- [ ] Tor integration + per-source transport
- [ ] Voice-only mode
- [ ] Open Commons Mirror (separate sister project, when mature)
- [ ] Content-provenance class — descriptive ingestion-channel/format metadata (newsletter · web-article · wiki · official-statistic · law · market · discovery), asserted-at-ingest, exposed as a facet + reading-diet-by-type (full design + backward-compat analysis in the section below)

### AUTONOMOUS BRIEF 2026-06-24 — UNRESOLVED & PARTIAL (audited against the code 2026-06-25)

> Authoritative status of the `docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-06-24.md` scope,
> verified item-by-item against the actual tree by a 6-agent parallel audit (not from memory).
> SHIPPED + merged into `0.09` this session: Tier 1.1 (statement-deadline guard), 2.3 (search
> Enter→new tab), 2.4 (Library world map + donut), 2.5 (Library dashboard), 3.7–3.11 (intro-box
> removal · Graphics fuse · opaque status bar · sidebar click-toggle · AI output-language),
> 4.13a (copypasta card), 4.15 (gov-newsletter keyword filter), 5A-bis.D0 (scaling design doc),
> 5B httpfs build recipe, and the 5C design docs (LLM-perception eval · Tor · voice · Mirror).
> **Also merged this session — the whole §5B statistical-data → honest-viz arc** (see the
> "Statistical-data ingestion + diversified honest visualization" section's BUILD STATUS block):
> CSV/JSON-stat/bulk parsers, the `to_chart_series` adapter + `ooViz` honest-chart primitives + the
> Settings → Statistics time-series chart, the `choroplethData` comparability gate + `symbolRadii` +
> the `/api/stats/map` feed + the ooMap stats choropleth, the OWID + JSON-stat live fetch clients,
> the **revision-anomaly detector** (+ store/endpoint/UI), and **4.13b outrage-intensity** (secondary).
> Everything below is what remains.

**NOT STARTED (design/spec exists, no code wired):**
- [ ] **Tier 1.2 — collector write-batching** (`docs/design/COLLECTOR_WRITER_BATCHING.md`; `Status: DESIGN, not built`). `ingest/pipeline.py` still commits per-article; `store.index_article()` has no `commit=` param. REMAINS: `index_article(commit=False)` + batch in the ingest loop + per-article fallback on batch failure + a no-loss test + `OO_COLLECT_COMMIT_BATCH`. (Deferred: needs the full suite + a live-corpus measurement — a blind refactor of keystone-#1 is too risky.)
- [ ] **Tier 2.6 — unified Import + unified Export/Backup** (`docs/design/UNIFIED_IMPORT_EXPORT.md`; design only). Import/export controls are still scattered (`importNewsletters`, `modelsBackupImport`, `v2Backup`, `v2Preview`…). REMAINS: one Import dialog (6a) + one Export/Backup dialog (6b) on the OOENC2 streaming path, an absorption test (no capability lost), retire the scattered controls. (Deferred: large browser-unverifiable frontend.)
- [x] **Tier 4.13b — outrage-intensity annotation** — DONE (2026-06-25). `src/analytics/outrage.py:outrage_intensity` (loaded/intensifier density + `!` + ALL-CAPS runs; structure-not-intent; English-only with an honest gap, never a fabricated 0; no score) wired as a SECONDARY `outrage` component on the headline-body card (never a standalone Lead). 6 sandbox tests + the headline-body test extended.
- [ ] **Tier 4.16 — app self-update mechanics** (snapshot→verify→migrate→swap→rollback, default OFF) — design-only; the maintainer's 5 open questions are unresolved. REMAINS: the whole mechanism. (Deferred: can't be end-to-end validated in-sandbox — brick risk.)
- [ ] **5A-bis.D2 — `keyword_daily` rollup** — no `keyword_daily` in code (only `keyword_agg` counters in `columnar.py`); `readmodel.py` still delegates to live queries. REMAINS: the table, the SQLCipher→DuckDB stream+group build, the incremental MERGE, and the readmodel wiring. (Gated on D1.)
- [ ] **5A-bis.D3 — incremental refresh + epoch full-rebuild gate** — no `last_mention_id`/`built_epoch`/`corpus_epoch`. REMAINS: the watermark + epoch tracking + the re-index/prune→force-full-rebuild gate (the double-count trap) + the append-only correctness proof. (Gated on D2.)
- [x] **5A-bis.D4 — `source_coverage` rollup** — DONE. The table + watermark/epoch build + parity shipped earlier (`columnar.py:build_source_coverage`/`refresh_source_coverage`/`source_coverage_rows`/`source_coverage_parity`, `tests/test_source_coverage_rollup.py`), and the SERVE-wiring shipped Wave 4 J: `src/analytics/map_serve.py` serves `/api/insights/map-coverage` from an OPT-IN (`OO_COLUMNAR_MAP_SERVE=1`, default off), bind-aware, in-memory rollup with a `basis` disclosure and fallback-to-live (numbers byte-identical; the unlocated per-language donut is computed live via the shared `queries.unlocated_language_breakdown`). `tests/test_map_serve.py`.
- [ ] **5A-bis.D5 — Roaring co-occurrence bitmaps** (pyroaring) — absent. REMAINS: the dependency (new optional extra), per-keyword bitmaps in DuckDB blobs, precomputed top-K neighbours, registry entry. (Optional, off the critical path.)
- [ ] **5B — zh/ja keyword segmentation** — no segmenter; tokenizer is space-based. REMAINS: a decision on a bundled offline segmenter (jieba/pkuseg/MeCab — license-clean, no-network) + the seam + registry entry.
- [ ] **event-timed-op manipulation card + elections & civic VERTICAL** — the generic events/calendar substrate (`src/events/`, `/api/events`, civic categories) IS shipped, but the *manipulation card* (#3+#6+agenda composition) and the civic vertical (candidate roster, poll-analysis tiers) are NOT built. REMAINS: the card/schema + the maintainer-supplied candidate roster (a data seam).

**PARTIAL (some shipped, a named piece missing):**
- [~] **Tier 4.14 — manipulation card #4 BURY half** — the FLOOD half (`concentration.find_flooded_topics`) is shipped; the BURY half (a source UNDER-covering a topic big elsewhere) is deferred in the module docstring. REMAINS: the under-coverage detector (needs a real external trigger so it isn't corpus-bias-driven).
- [~] **5A-bis.D1 — persisted encrypted DuckDB store** — the offline-load SCAFFOLD exists (`columnar.py` `encryption_gate`/`secure_crypto_available`/`_offline_config`, graceful in-memory fallback) + the design doc + the `external_artifacts.yml` coupling entry. REMAINS: the per-OS/arch httpfs binaries (`duckdb_ext/`, SHA-256 pins currently blank) + the pin-verify-before-LOAD code path. (Blocked: needs a networked multi-arch build — maintainer's step; never fabricate a checksum.)
- [~] **5B — Ollama binary installer** — the Mistral-led catalog + model-pull/queue UI are shipped; the binary download-verify-run installer is NOT. REMAINS: the Settings→AI installer UI + per-OS installer checksums. (Blocked: checksums need a networked machine.)
- [~] **Tier 3.12 — i18n keying** — 35 strings keyed this session (`--audit-chrome` 140→105, gate 100%). REMAINS: ~105 strings — mostly data/URLs/proper-nouns that correctly stay literal, the security-/technically-dense paragraphs (custody IP/timing, AES-GCM/Reed-Solomon volume backup — native review), and the mid-`<a>`-link fragments whose tags are deliberately kept (e.g. the discovery "Your query leaves this machine." privacy emphasis) — de-tagging would undo intentional emphasis, so it needs browser verification.

**Operational (not code — the maintainer runs these):** keyword cleanup / baseline-tag backfill on the live corpus · translation-ring generation (networked machine, Wikidata blocked in CI) · the per-OS httpfs + Ollama binary builds · the 0.0.9→0.1 flip · human click-through of every browser-unverified UI.

---
