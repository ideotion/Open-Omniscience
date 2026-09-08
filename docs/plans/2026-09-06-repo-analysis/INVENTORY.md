# Inventory — every open item found by the 2026-09-06 repo analysis

Anchored at `main` @ `1d421e9`. Produced by twelve read-only investigation agents (documentation,
design docs, roadmaps/gates, the whole PR history #1–#1010, code/test/CI markers, audit reports)
plus a verification pass by the orchestrating session. **Every verdict below was re-derived from the
tree or from a named artifact — a doc's own status text was treated as a claim, never as evidence.**

Verdict vocabulary: **BUILT** (found shipped — record, never rebuild) · **PARTIAL** (a named piece missing) ·
**UNBUILT** · **STALE-CLAIM** (a doc says one thing, the tree says another) · **OPERATOR-GATED** (needs a
networked machine, a real corpus, or the maintainer's hands) · **RULING-GATED** (needs a maintainer decision;
question ID in QUESTIONS_FOR_THE_MAINTAINER.md) · **BROWSER-GATED** (needs a real page driven — the sandbox
CAN do this in Chromium; the maintainer's UX pass is the remaining bar) · **UNCHECKED** (not verified this pass).

Columns: ID · item · verdict · evidence (anchor in the tree or the doc, as of `main` @ `1d421e9`) · where the
claim lives · owning prompt.

## REL — release and process
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| REL-01 | 0.3 gate row 5: Tier A quarantine pass (8 articles, `nav-soup-v2`) executed with `write=True` + re-index | OPERATOR-GATED (A1) | `docs/product/RELEASE_0.3_GATE.md` §1 row 5 OPEN, §7.1 | gate doc | P01 |
| REL-02 | `v0.3.0` tag cut from the maintainer's machine after CI green at the SHA | OPERATOR-GATED | gate §7.3; the session proxy refuses tag pushes | gate doc | P01 |
| REL-03 | `RELEASE_0.4_GATE.md` stood up from §5 (3-at-scale, row 4, row 7b) | UNBUILT (A2) | no `docs/product/RELEASE_0.4_GATE.md` | gate §5 | P01 |
| REL-04 | P0 validation bar strings still say "100 GB" while the ruled bar is ~1M / release-scale | STALE-CLAIM | `src/monitoring/p0_validation.py` acceptance strings (ledger 2026-08-03) | CLAUDE.md | P01 |
| REL-05 | Criteria-calibration prose arm pinned at `after_id=0, limit=500` — never advances in the bundle | UNBUILT (instrument defect) | CLAUDE.md 2026-08-23 "expensive calibration arm"; `src/api/diagnostics.py` member args | CLAUDE.md | P01 |
| REL-06 | 0.4 row 4 tooling: committed import demonstration + disqualified-source spot-check script | UNBUILT | gate §5 closing clause | gate doc | P07 |
| REL-07 | 0.4 row 7b ≥72 h soak — instrumentation exists (`collect_perf`, stall forensics), the run is the operator's | OPERATOR-GATED | gate §5; `UNATTENDED_RUN_RUNBOOK.md` | gate doc | P01 |
| REL-08 | `docs/CHANGES.md` 0.3.0 section is current up to 2026-09-05; the tag-day amendment of "Not yet tagged" | UNBUILT (at tag) | `docs/CHANGES.md` | — | P01 |
| REL-09 | Ledger restructure (Open queue → `docs/ledger/OPEN_QUEUE.md`, rule (1) amendment, retire shipped entries, size ratchet) | RULING-GATED (A3) | `docs/design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md` §7; CLAUDE.md 1,339,174 B / 161 bullets | proposal | P03 |
| REL-10 | Freshness issue #998: vendored Alpine upstream v3.17.0 vs `reviewed_through` v3.16.2 (on-security policy) | OPERATOR-GATED (review) | GitHub issue #998; `configs/external_artifacts.yml` `vendored-alpine` | issue | P14 |

## DOC — documentation hygiene
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| DOC-01 | 2026-07-17 docs-review T1 (docs/README index), T2 (`test_docs_index_covers_live_docs`), T3 (AUDIT_TRAIL backfill), T5 (USER_MANUAL banner), T6 (QUICKSTART "Phases" heading + fr mirror) | BUILT (STALE-CLAIM in `ACTION_PLAN_2026-07-22` Phase 2, which still lists them open) | `docs/README.md` mentions legal/audit/process/…; `tests/test_repo_invariants.py:7651`; `AUDIT_TRAIL.md` entries to 2026-07-22; `docs/USER_MANUAL.md:2780` banner; `docs/QUICKSTART.md:365` | ACTION_PLAN_2026-07-22 §Phase 2 | P02 |
| DOC-02 | T9 FUTURE_DEVELOPMENTS reality-check: 19/50 sections STALE-CLAIM, 4 embedded historical ledgers (§3 field-test 2026-06-24, §4 consolidated to-do, §5 0.0.9 sequencing, §47 field diagnostics 2026-06-27), 3 duplicate pairs (§1/§22, §35/§43, §2/§49) | UNBUILT (A4 decides depth) | agent A report; `docs/FUTURE_DEVELOPMENTS.md` 3,099 lines / 50 sections | ACTION_PLAN_2026-07-17 T9 | P02 |
| DOC-03 | Dead refs: `scripts/import_eml.py`, ROADMAP "Email & Newsletter Intelligence", `docs/design/COLLECTOR_WRITER_BATCHING.md` (→ archive), `configs/stat_indicators.yml` (never created), `app.js:6151` / `backup_v2.py:269` line refs, bare `SCALE_ROADMAP.md` link | STALE-CLAIM | agent A; `ls scripts/import_eml.py` absent | FUTURE_DEVELOPMENTS | P02 |
| DOC-04 | `docs/ROADMAP.md` last reconciled 2026-07-11 (+ a few 2026-08-20 touches); many rows stale vs the tree | STALE-CLAIM | `docs/ROADMAP.md:5,354` | ROADMAP | P02 |
| DOC-05 | `docs/process/NAV_SOUP_QUARANTINE_STRATEGY_DRAFT.md` — superseded by the shipped quarantine column/write step + gate row 5 | STALE-CLAIM (retire/banner) | shipped.csv 2026-07-23 rows | process/ | P02 |
| DOC-06 | Design-doc status banners: `ACTION_PLAN_2026-07-22` Phase 2 (done), Phase 8 (triage runs — done 2026-09-05), Phase 9 (closed); `AI_LAYER_STRATEGY_2026-07-29` "nothing built" (most built); `OBSERVATORY_DESIGN` "nothing built" (S0/S1 built); `SCRAPING_AUTOMATION_PLAN` / `UI_SHELL_REDESIGN_PLAN` "awaiting review" (largely built) | STALE-CLAIM | banners quoted in the analysis | design/product docs | P02 |
| DOC-07 | CLAUDE.md Open-queue entries that describe since-shipped work as open: card-audit `-inf` (fixed, `src/briefing/card_audit.py:1623`); qualification-assist UI trigger (`src/static/app-sources.js:396`); newsletter links → `ArticleLink` (`src/ingest/email.py:418,474`); server IP in the reader (`src/api/main.py:1842`); per-source observed IPs (`src/analytics/queries.py:1369`) | STALE-CLAIM | tree anchors | CLAUDE.md | P02 |
| DOC-08 | `docs/product/USE_CASES.md` predates the UI rework (banner present) | BUILT (banner) | file header | — | P02 |

## SRC — sources, qualification, discovery
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| SRC-01 | `enabled` vs `qualified` split: `select_unqualified` trial-fetches DISABLED candidates; a `qualified` verdict never flips `enabled`; collection requires both | RULING-GATED (B1) | `src/catalog/qualification.py:231`; `src/scheduler/runner.py:419-426` | CLAUDE.md 2026-07-26 item 9 | P04 |
| SRC-02 | Phase-2 promotion frontier (candidate → trial → graduated; additive `SourceCandidate` state columns; consent-gated trial-enable; audit view + undo) | UNBUILT | `ACTION_PLAN_2026-07-13` omnibus status "REMAINING (the dedicated Phase-2 slice)" | design doc | P04 |
| SRC-03 | Discovery-trail provenance panel (first citing article + citing source, click-through) | BUILT (STALE-CLAIM, verified 2026-09-07) | `src/discovery/source_trail.py:source_provenance`; `GET /api/sources/{id}/provenance` (`source_management.py:239`); `tests/test_source_trail.py` | CLAUDE.md 2026-07-20 SOURCE DISCOVERY TRAIL (1) | P04 |
| SRC-04 | Qualified-citations tally + reciprocal drills (per class → cited domains list → citing articles) | BUILT (STALE-CLAIM, verified 2026-09-07) | `source_trail.py:source_citation_tally` (+ `TALLY_CAVEAT`); `GET /api/sources/{id}/citation-tally`; rendered at `app-sources.js:437` | CLAUDE.md 2026-07-20 (2) | P04 |
| SRC-05 | Corpus facet filters (source/language present in the current corpus) in the Articles subtab; id-seeded corpus INTERSECT on refine | UNBUILT | CLAUDE.md 2026-07-20 (3) | CLAUDE.md | P15 |
| SRC-06 | Newsletter links → `ArticleLink` rows (feeds both funnels) | BUILT (STALE-CLAIM in CLAUDE.md "not the case today") | `src/ingest/email.py:418 _email_link_rows`, `:474` | CLAUDE.md 2026-07-20 (1) | P02 |
| SRC-07 | `configs/source_qualification.yml` generation from real instances (loader/export/merge script shipped 2026-09-04) | OPERATOR-GATED (B5) | file absent; `scripts/merge_source_qualification.py` present | CLAUDE.md 2026-09-04 | P04 |
| SRC-08 | Recency-windowed re-check (the 6-month re-verification reads whole history) | RULING-GATED (B7) — the DISCLOSURE half already ships (verified 2026-09-07): the panel's `recheck.scope_note` says the re-check sees a broadly-broken source and not a recently-degraded one (`source_management.py:1615`) | CLAUDE.md 2026-09-04 | CLAUDE.md | P04 |
| SRC-09 | `PATHOLOGY_ABS_FLOOR` 0.5 unreachable (max observed 0.211); options (a)/(b)/(c) | RULING-GATED (B6) — the DISCLOSURE half already ships (verified 2026-09-07): the tunable's `impact` states the floor was never reached and names 0.211 (`src/catalog/gates.py:124-134`), so only the constant itself is open | CLAUDE.md 2026-08-03 | CLAUDE.md | P04 |
| SRC-10 | Source-tag review remainder: 59 domains below the article floor; 47 whose batch failed the canary (re-run after the canary re-spec) | OPERATOR-GATED (a re-run) | CLAUDE.md 2026-09-05 source-tags entry | CLAUDE.md | P04 |
| SRC-11 | duplicate domains → **475 of the 3,870 entries a real boot seeds** unreachable by the create-only seeder (227 inside `configs/sources.yml` alone) | GUARD BUILT 2026-09-07; the RECOVERY is RULING-GATED (new: B11). The "data fix" direction was wrong — measured, 75 declare a DIFFERENT language than the surviving sibling (30 BBC language services, DW Arabic/Deutsch/Español/Brasil) and 192 carry a `lean-*` tag the survivor lacks, so deleting them deletes the multilingual breadth AND the political-lean catalogue; recovery needs a source-identity ruling (domain vs feed), and NOT the catalogue-data split first recommended — the language services share one RSS host | `catalog_domain_collisions`; `tests/test_catalog_domain_collisions.py` | CLAUDE.md 2026-09-05 lesson | P04 |
| SRC-12 | Retroactive apply of tag edits to an existing corpus (seeder is create-only) | UNBUILT | CLAUDE.md 2026-09-05 | CLAUDE.md | P04 |
| SRC-13 | Source-diversification brief's 14-cluster networked run (English share ~69%) | OPERATOR-GATED | `SOURCE_DIVERSIFICATION_BRIEF.md` banner | design doc | P04 |
| SRC-14 | De-US remainder: Wikidata generator run for the 73 named gaps; `catalog_targets.yml` ratification; alias table | OPERATOR-GATED / RULING-GATED | FUTURE_DEVELOPMENTS §"De-US-centring" | FD | P04 |
| SRC-15 | World-discovery ride-along RUN on a real instance + `build_world_news_catalog.py` committed for every install | OPERATOR-GATED | CLAUDE.md 2026-07-15 | CLAUDE.md | P04 |
| SRC-16 | S6.1b cited-provenance remainder: background citing-resolve job at scale, denormalised `citing_source_id`, the citing-trail surface | UNBUILT | CLAUDE.md S6 closeout (2) | CLAUDE.md | P04 |

## KW — keyword engine, translation, disambiguation
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| KW-01 | Slice 3: date-aware month block + re-index (gated on the occupancy number) | OPERATOR-GATED (E1) then buildable | design doc §8 row 3; `src/analytics/month_occupancy.py` shipped | KEYWORD_TRANSLATION design | P06 |
| KW-02 | Slice 4: ambiguity map from the Wikidata fetch + `held_back.ambiguous_language` | OPERATOR-GATED (E2 allowlist) | §8 row 4; §6c.5 the one open number | design doc | P06 |
| KW-03 | Slice 5: ring coverage expansion (168-seed batch prepared; generator OVERWRITES `-o`) | OPERATOR-GATED | CLAUDE.md RING LIFECYCLE | CLAUDE.md | P06 |
| KW-04 | Slice 6: sense INVENTORY coverage (the pick mechanism shipped over 91 collisions) | OPERATOR-GATED (dump) | §8 row 6, §8c | design doc | P06 |
| KW-05 | Slice 7: synonym tier via the SKOS family (OMW refuted) — licence check | RULING-GATED (E4) | §8 row 7 | design doc | P06 |
| KW-06 | Wiktextract share-alike ruling | RULING-GATED (E3) | §6b.4 | design doc | P06 |
| KW-07 | Stoplist (1)/(2) ruling; English 11,263 + French 881 global-channel batch; zh/ja/th 611 after `[segmentation]` re-index | RULING-GATED (B2/B3) + OPERATOR-GATED | CLAUDE.md 2026-09-05 | CLAUDE.md | P05 |
| KW-08 | 64,910 `kind_overrides` proposals | RULING-GATED (B4) | CLAUDE.md 2026-09-05 | CLAUDE.md | P05 |
| KW-09 | Ring lifecycle: institutionalised refresh cadence + `translation_coverage` on the KPI board + a `--refresh` QID-refresh mode for `generate_wikidata_rings.py` | BUILT 2026-09-07 (`IMPROVEMENT_CYCLE.md` §1b; `kpi.record_translation_coverage`/`_k6_coverage`; `generate_wikidata_rings.refresh_rings`). **The row was PARTLY stale when written: K6 was already listed on the board — with no resolver, so it could only ever answer `not-measurable-here`.** The operator run of either pass stays gated on E2. | CLAUDE.md RING LIFECYCLE (two agreed mechanisms) | CLAUDE.md | P06 |
| KW-10 | Keyword-skeleton fingerprint persistence + live `skeleton_echo` producer wiring | UNBUILT (dormant stretch) | `ACTION_PLAN_2026-07-22` Phase 7; `src/analytics/skeleton.py` pure core | design doc | P05 |
| KW-11 | In-app review-and-apply of analyzer proposals (`generic_terms`, ring candidates, mistags) — the S4 panel | UNBUILT | `ACTION_PLAN_2026-07-22` 4.2 | design doc | P05 |
| KW-12 | Stoplists → data files (4.1) | BUILT (2026-07-23 `configs/stopwords_extra/<lang>.yml`; STALE-CLAIM in the 2026-07-22 plan) | `ls configs/stopwords_extra` | design doc | P02 |
| KW-13 | P5.2 static-embedding recall layer (model2vec/sqlite-vec/RRF) | OPERATOR-GATED (graded gold set) | KEYWORD_ENGINE_OPTIMIZATION_STRATEGY | strategy doc | P05 |
| KW-14 | P6 entity→QID (OpenTapioca) | OPERATOR-GATED + licence check | same | strategy doc | P05 |
| KW-15 | BM25F default weights (A/B harness built, no chosen weights) — needs the graded gold set | OPERATOR-GATED | strategy doc; Settings → Diagnostics gold-set builder | strategy doc | P05 |
| KW-16 | Entity families: caps-furniture batch, Roman-numeral exclusion, cross-script alias rings, kind-dropdown honesty | BUILT (2026-07-19..21, per the 2026-07-22 audit) | `ACTION_PLAN_2026-07-22` §0 | — | — |
| KW-17 | Clickable-keyword stats hover (slice 2) — "which stats" undecided | **VERIFIED-PRESENT 2026-09-07** (`58a4d6d`) — shipped, not ruling-gated: `GET /api/insights/keyword-stats` (`src/api/insights.py:1240`) behind the reader's `kwStatLine` (`src/static/reader.js:130`) and the SPA `#oo-tip` hover (`src/static/app-boot.js:206`); mentions · spread · windowed trend rate · top co-occurrences, counts only. `docs/ROADMAP.md` already recorded it as shipped | FUTURE_DEVELOPMENTS §"Clickable in-article keywords" | FD | P17 |
| KW-18 | Per-language month scoping (a stopwords-ARCHITECTURE change; complement to slice 3) | UNBUILT — and RECORDED 2026-09-07 at the code that makes it impossible (`services/stopwords.get_stopwords`'s docstring + a behavioural branch-order guard), so the next reader meets the constraint where they would act on it rather than in a design doc | design doc §8 last row | design doc | P06 |

## LAW — the law vertical
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| LAW-01 | CLML adapter offline half | BUILT | `src/law/adapters/clml.py`, `diff.py` | law brief S6 | P13 |
| LAW-02 | Adapter LIVE half + enumeration (legislation.gov.uk, gesetze-im-internet, EUR-Lex) — egress 403 in the sandbox | OPERATOR-GATED (F1) | CLAUDE.md law rulings 34a status | CLAUDE.md | P13 |
| LAW-03 | Gazettes-as-streams (S7): verified RSS candidates → `rss_url` | **BUILT 2026-09-07 (PR #1023) — 3 of 4, and the count was wrong in both directions.** Georgia `matsne.gov.ge` also qualifies; Uruguay `impo.com.uy` does NOT — its feed was never fetched and its own notes call it the site's generic WordPress news feed, so it ships as a `lead`. A feed now carries its own validator-enforced `gazette_feed_verification` tier, because the row-level status is about the PORTAL. NOT yet collected: `select_sources` admits only QUALIFIED sources, so the three enter the qualification ladder first | `src/law/catalog.feed_rss_url`; `scripts/validate_legal_catalog._check_feed_verification` | — | P13 |
| LAW-04 | PDF handling: `[pdf]` extra + `src/ingest/pdf.py` degrade loudly | BUILT — and **the narrowing is now STATED (2026-09-07, L6's default applied not decided)**: the coverage report publishes `pdf_extractor_available` with the numbers, measured at 63 of 275 catalog sources PDF-only across 54 countries and 6 of 23 tracked documents PDF by URL, both as floors. Promoting `[pdf]` into the default extras is still an open call | `src/law/coverage._pdf_reach`; pyproject `[pdf]` | ROADMAP Q-LAW-2 | P13 |
| LAW-05 | Breadth-first track (per-country corpora beyond adapters) — ruled "marked for later" (A4) | UNBUILT (ROADMAP row) | CLAUDE.md 2026-07-24 A4 | CLAUDE.md | P13 |
| LAW-06 | AI change summaries auto at track time for UI-floor jurisdictions (A5) | **CHECKED 2026-09-07 — BUILT, ruling A5 met as written, nothing extended.** `advance_law_summaries` runs as a scheduler ride-along; `summarize_revision` is the on-demand path; the floor is `UI_LOCALE_CODES`; each summary stores model + prompt_version + the verbatim prompt | `src/scheduler/runner.py` ride-along; `src/api/law.py:378`; `pending_ai_summaries` | — | P13 |
| LAW-07 | Catalog language threading (Cambodia-in-French → `LawDocument`/`Article.language`) — S4b | **CHECKED 2026-09-07 — BUILT since 2026-07-17, not rebuilt.** The columns exist, `register_documents` populates AND heals them, and the Article gets `language=doc.language`. PROMPT_13 described this as missing; the prompt and the brief are corrected | `src/database/models.py:2187-2188`; `src/law/catalog.register_documents`; `src/law/corpus.py:119` | — | P13 |
| LAW-08 | Coverage diagnostic denominators from the official enumeration | **BUILT 2026-09-07 (PR #1023) — and the count is 39 across 32 countries, not 27.** Printed beside the tracked count with unit/as_of/source_url, plus the 31 of 32 countries enumerated-but-untracked. **NO fraction is computed**, and that is deliberate: the units run over codes, acts, volumes, gazette issues and treaties, and inferring commensurability from the unit string is what ruling 47's rail forbids | `src/law/coverage.official_enumerations` | RULING OWED → ROADMAP Q-LAW-1 | P13 |
| LAW-09 | Per-country aggregate figures/indices/law/revisions + the Gini/GDP-through-time map | PARTIAL (map exists; per-country law aggregate not) | CLAUDE.md 2026-07-24 (3) | CLAUDE.md | P13 |
| LAW-10 | Vetting board: the leads, the blocked domains, Grenada down, the NK gap | **BOARD BUILT 2026-09-07; the REVIEW is still operator-gated.** 44 rows, generated from the catalog so no cell can be back-filled: 2 confirmed gaps · 9 unverified leads with a real domain · 29 access-blocked or bot-walled · 4 recorded down. Sections 3–4 are a stated keyword triage, not a finding. NK's gap was a YAML comment no tool could read and is a domain-less `lead` row now | `docs/product/LAW_VETTING_BOARD.md`; `scripts/law_vetting_board.py` | ROADMAP Q-LAW-3 | P13 |
| LAW-12 | Should the per-endpoint verification tier generalise beyond `gazette_feed`? `enumeration_url` (107, none fetched by anyone) and `structured.api` / `structured.bulk` sit in the identical position — an endpoint field no test can tell apart from a URL somebody wrote down | RULING-GATED (raised 2026-09-07) | `scripts/validate_legal_catalog.FEED_VERIFICATION_STATUSES` | ROADMAP Q-LAW-4 | P13 |
| LAW-11 | Legal-review anonymity clause (disclose identity to GitHub) — maintainer action | OPERATOR-GATED | D3 notes #693 | PR history | P02 |

## GOV — governments and official statistics
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| GOV-01 | 36 WB indicator codes never fetched — `scripts/verify_worldbank_indicators.py` is ONE command on a networked machine | OPERATOR-GATED (F1) | script docstring | CLAUDE.md | P14 |
| GOV-02 | Bloc rosters (Task 4) — registry deliberately EMPTY; own networked session | OPERATOR-GATED (G3) | `src/catalog/blocs.py` docstring | CLAUDE.md | P14 |
| GOV-03 | OECD SDMX-JSON 1.0 / IMF message support | PART-BUILT 2026-09-07 @ `58a4d6df`: the 1.0 `AllDimensions` CONTAINER (`dataSets[].observations`, no `series` key) parsed to ZERO rows and logged nothing — fixed, with an unreadable dataSet now logged and a 2.0 message refused BY NAME. SDMX-JSON **2.0** remains unbuilt and still needs a real fetched body. | `src/stats/sdmx.py`; `tests/test_sdmx_parse.py` | CLAUDE.md 2026-08-13 lesson | P14 |
| GOV-04 | Agencies directory 29 → ~152 with `news_url` (networked research pass) | OPERATOR-GATED (G5) | `src/stats/agencies.py` 29 entries | CLAUDE.md | P14 |
| GOV-05 | CSV/OWID + JSON-stat/PxWeb + bulk-ZIP parsers (V-Dem/UCDP) | VERIFIED-PRESENT 2026-09-07 @ `58a4d6df` — all three families ship: `parse_csv`/`parse_jsonstat` (`sdmx.py`), `parse_csv_wide` + `zip_csv_members`/`read_zip_member` (`bulk.py`), tested in `test_stats_csv_jsonstat_parse.py` + `test_stats_bulk.py`. Do not rebuild. | `src/stats/sdmx.py`, `src/stats/bulk.py` | FD | P14 |
| GOV-06 | Revision-anomaly detector over `StatFigure` vintages | VERIFIED-PRESENT 2026-09-07 @ `58a4d6df` — shipped AND wired end to end: `find_revision_anomalies` → `store.py:267` → `/api/stats/revision-anomalies` → `app-map.js:2143`, with `test_stats_revision.py`, `test_stats_revision_store.py` and a `test_repo_invariants.py` guard. Do not rebuild. | `src/stats/revision.py` | FD | P14 |
| GOV-07 | IPCC as a source + forecast/prediction tracking | RULING-GATED (G4) | FD §"IPCC" | FD | P14 |
| GOV-08 | Key-gated sources (EIA API v2, FRED, Comtrade, FIRMS, OpenAQ) — V1-2 | RULING-GATED (G1) | V1_PATHWAY §7 | V1 | P14 |
| GOV-09 | BRICS Joint Statistical Publication; AfDB/UNECA continental endpoints | OPERATOR-GATED | CLAUDE.md 2026-08-07 rulings 2/46 | CLAUDE.md | P14 |
| GOV-10 | Governments UI: WB-lens "no continental Africa" disclosure, compare rows, aggregates — maintainer click-through | BROWSER-GATED (UX pass) | CLAUDE.md 2026-08-20 board | CLAUDE.md | P15 |
| GOV-11 | `page=2` cache-disabled confirmation + page-1 tail read (Task 2 loose ends) | OPERATOR-GATED | INTERNET_SESSION_PROMPT status | design doc | P14 |
| GOV-12 | Series-as-Articles: FTS no longer matches `World Bank` / the series code (stated loss); `?source=`/`?tags=statistics` cover it | BUILT (loss stated) | CLAUDE.md 2026-08-20 lesson | — | P14 |

## AI — the AI layer and the Bulletin
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| AI-01 | Bulletin S1: Layer-B narration as a `BackgroundJob` with a persisted cursor | SHIPPED 2026-09-07 | `src/bulletin/narration_job.py`; `POST /api/bulletin/editions/{f}/narrate` | FD | P12 |
| AI-02 | Bulletin S2: §18 export-privacy enumeration before a first evidence ZIP leaves a machine | SHIPPED 2026-09-07 | `src/bulletin/privacy.py`; rides the evidence plan, the review screen and both ZIPs | FD | P12 |
| AI-03 | Bulletin Q4: `LAYER_A_REQUIRES_CAPABLE_HARDWARE` | RULED False 2026-09-07 (D1) — the gate covers narration only; two verdicts | `src/bulletin/gate.py` | FD §20 | P12 |
| AI-04 | Bulletin Q1/Q2/Q3/Q5 | RULED 2026-09-07 (D2–D4) — sections + review screen ratified; introduction narrated; mail never | FD §20 | FD | P12 |
| AI-05 | Bulletin S4: `/llm-bench` on a GPU machine and a slow one (the §6.3 time budget) | OPERATOR-GATED | FD REMAINING (S4) | FD | P12 |
| AI-06 | Model-weights revision pin in the registry + refuse-on-mismatch | SHIPPED 2026-09-07 (D6 taken on its recommended default; pins ship BLANK — huggingface.co/ollama.com both 403 here) | `src/llm/weights_pin.py`; `model-weights-revision` in `configs/external_artifacts.yml`; `tests/test_model_weights_pin.py` | PROMPT_11 | P11 |
| AI-07 | `X_AVAILABLE` capability probes (PQC/OTS) probe a round trip, not an import; pqcrypto stays `<1.0` | SHIPPED 2026-09-07 (both flags are round trips; `[timestamping]` joined the crypto lane; a dependabot `ignore` for pqcrypto MAJORS is the missing half of the ceiling's defence) | `src/custody/signing.py:_probe_mldsa`, `timestamp.py:_probe_ots`; `tests/test_capability_probes.py` | PROMPT_11 | P11 |
| AI-08 | Q8 live ollama.com library browse | DROPPED 2026-09-07 (D9 recommended default, reason recorded) — the curated dated catalog + the free-text tag box cover the need; a live browse is a network surface with a maintenance tail against a ruling whose point is that the default is not a menu | no browse code (grep-verified: `ollama.com` is a static link only) | OPEN_QUEUE 2026-09-07 | P11 |
| AI-09 | Multi-model specialisation bench | STALE-CLAIM CORRECTED 2026-09-07: the HARNESS IS BUILT (476 lines + its own suite); what is missing is any way to START it — `run_shape` has no caller outside the test tree, so the operator step D8 defers to is not actually available on the rig. D8's "no build" honoured; recorded, not built | `src/ai_layer/specialisation.py`, `tests/test_specialisation.py` | OPEN_QUEUE 2026-09-07 | P11 |
| AI-10 | Perception extraction rollout: cleared fields only; graded gold set (R6) for numeric floors | VERIFIED-PRESENT 2026-09-07 @ `main` 690920e — the sweep defaults ON, `field_gate` stores only `active is True` and refuses the unmeasured, and both structural points are pinned (only `ai-who`/`ai-place`/`ai-date`, never the trusted tables; WHO stays ONE kind). Only the numeric floors remain = OPERATOR (R6) | `src/ai_layer/perception_extract.py`; `test_repo_invariants.py::test_perception_extraction_is_eval_gated_and_never_touches_the_trusted_tables` | OPEN_QUEUE 2026-09-07 | P11 |
| AI-11 | The refused-field list uncapped in the AI check | SHIPPED 2026-09-07 (D5 recommended default: collapsed behind a VISIBLE count naming how many and which fields; the summary IS the caveat, the list inside is complete) | `src/static/app-diagnostics.js`; `tests/gate_fields_node_test.js` | PROMPT_11 | P11 |
| AI-12 | Ollama `num_ctx` RAM auto-tune (B7 gap) | BUILT (STALE-CLAIM in the Session-B carry-over) | `src/ai_layer/context.py:169`, `MIN_NUM_CTX` | CLAUDE.md | P02 |
| AI-13 | Bench roster reduction after the one-model ruling (8 entries; six roster tests are ABOUT the dropped entries) | VERIFIED-PRESENT 2026-09-07 @ `main` 690920e — the roster went WITH the ruling: `DEFAULT_ROSTER` is `_incumbents()`, `BENCH_ROSTER_AS_OF` is gone, and `MINISTRAL_AS_OF` records that it inherited the dated-registry duty. The "six roster tests" CI risk is spent | `src/ai_layer/model_bench.py:123`, `src/llm/ollama.py:144` | OPEN_QUEUE 2026-09-07 | P11 |
| AI-14 | Custom-model field moved to a buried advanced position | VERIFIED-PRESENT 2026-09-07 — Settings → Advanced → AI → "Run your own model", inside `<details class="adv-sec" data-adv="ai">`, with the ruling quoted verbatim above it | `src/static/index.html` `#set-advanced` | OPEN_QUEUE 2026-09-07 | P11 |
| AI-15 | LFM2.5 Instruct first-party tag question (`LiquidAI` Ollama account) | OPERATOR-GATED — re-probed 2026-09-07 and STILL blocked: `ollama.com` answers `CONNECT … 403` (`pypi.org` 200 as the control), seventh consecutive session. Deliberately not guessed; joins F1 | CLAUDE.md BENCH-ROSTER entry | OPEN_QUEUE 2026-09-07 | P11 |
| AI-16 | Qualification-assist per-source button | BUILT (STALE-CLAIM in Session-B carry-over (c)) | `src/static/app-sources.js:396` | CLAUDE.md | P02 |
| AI-17 | The ~50-anchor triage grading sitting + the real roster bench run on the rig | OPERATOR-GATED | CLAUDE.md Session E remaining | CLAUDE.md | P11 |
| AI-18 | Deep-model tier / whole-corpus cited synthesis / corpus Q&A / per-surface LLM lenses (2026-06-17 expansion rulings) | UNBUILT (design-only) | CLAUDE.md IN-APP OLLAMA entry "REMAINING" | CLAUDE.md | P11 |
| AI-19 | Per-article Summarize/Translate on the analysis Articles list | **CLOSED BY RULING, checked 2026-09-07** (`58a4d6d`) — not a gap to build: maintainer ruling 22 (field feedback 2026-08-07, shipped 2026-08-20) REMOVED the per-row buttons as an absorption, because the reader runs both on the same endpoints and shows the original URL as its own visible text (invariant #6); the bulk Summarize-all / Translate-all actions are untouched. Recorded at the call site (`src/static/app-analysis.js:1243`) and in the `shipped.csv` row for rulings 20-22 | same | CLAUDE.md | P17 |

## UI — browser-verified backlog
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| UI-01 | 12-locale sweep (4 covered), rule 9 adversarial screenshot reading, the Gecko/AppVM bar | BROWSER-GATED (H2) | `docs/audit/UI_CLICKTHROUGH_2026-08-20.md` open items | audit | P15 |
| UI-02 | a11y P2s filed by the axe-core pass | UNCHECKED (agent F) | same | audit | P15 |
| UI-03 | Inline `on*=` handlers: 331 in `index.html` + 259 in `app-*.js` (= 590); CSP `'unsafe-inline'` | UNBUILT (H4) | `grep -o " on[a-z]*=\""` counts; `src/api/main.py:555` | ROADMAP/PARKED | P15 |
| UI-04 | Dead temporal-map cluster (`loadTimemap`/`renderTimemap`/`showTmapDetail` at `app-map.js:1633/1671/1689`) interleaved with live helpers — **SHIPPED 2026-09-08** (see `docs/ledger/shipped.csv`), verified by `node --check` + full grep-based code inspection (the deletion could not be clicked through in this environment, so it is NOT browser-verified); the shared helpers ooMap still calls (`kindColor`/`TMAP_KINDS`/`kindLabel`/`MON`/`fmtYear`/`fmtDate`/`TMAP_NEAR_DEG`/`tmapFindCoverage`) were kept, and `dateToT`/`TMAP_SPAN_OVERRIDE` — which the code's own retired comment also called shared — turned out to have zero live callers on a fresh grep and were deleted too. STILL OPEN, unverified-in-this-pass, tracked here only: `#corpus-win` modal (`index.html:2895`); orphan `loadIndicesData`/`loadMarketData`; orphan `#onboard` keys | PARTIALLY SHIPPED (temporal-map cluster only; the rest UNBUILT, browser-verified deletion) | tree greps | CLAUDE.md DEFERRED DEAD-UI-CODE | P15 |
| UI-05 | Insights search bar removal (`#ins-term` `index.html:1135`, `exploreTerm` `app-corpus.js:626`) — absorption-gated | RULING-GATED (H3) | tree | CLAUDE.md S4.4 | P15 |
| UI-06 | `ooViz` unwired primitives (11: `binCounts1D`, `bin2D`, `fiveNumberSummary`, `sqrtAreaScale`, `symbolRadii`, `pathWithGaps`…) | UNBUILT (activations need a surface) | `docs/plans/2026-08-04-gui-visualization-plan.md` status | plans | P16 |
| UI-07 | i18n ratchets 560 untranslatable / 297 unkeyed `t()` — a lowering program | UNBUILT | ci.yml | ci | P15 |
| UI-08 | Leads 2.0 grading onto Home (evidence chips, sort control, lifecycle deltas) | BROWSER-GATED | CLAUDE.md OPTIMIZATION-TAIL carry-over (a) | CLAUDE.md | P15 |
| UI-09 | Conjunction-lens deeper views (conditional trend · vocabulary contrast · intensity · lead/lag) — payload extension | UNBUILT | carry-over (b) | CLAUDE.md | P15 |
| UI-10 | Sparse-rule reach decision for `ringDumbbellSvg` / `commodityOverlaySvg` / `ooDonut` | RULING-GATED (soft) | Session D §1.9 | CLAUDE.md | P15 |
| UI-11 | El Niño agenda span banners (after ONI verification + span support) | OPERATOR-GATED (ONI) | omnibus 1(c) | design doc | P19 |
| UI-12 | Subjectivity reader HIGHLIGHT panel (spans emitted, no surface) | UNBUILT | S5 carry-over (e) | CLAUDE.md | P15 |
| UI-13 | Post-import results screen (Articles-first headline, corpus delta, work induced) | UNCHECKED (2026-07-22 audit said the headline shipped) | CLAUDE.md POST-IMPORT entry | CLAUDE.md | P15 |
| UI-14 | `prefers-contrast` unhandled; `.sr-only` absent from the static shell | UNCHECKED | GUI audit G-3 | audit | P15 |
| UI-15 | Observatory `ooSky` renderer + dedicated tab (backend S0/S1 shipped) | BROWSER-GATED (H1) | `src/analytics/observatory.py`, `/observatory` route; no frontend hits | OBSERVATORY_DESIGN | P16 |
| UI-16 | ooMap embed on When/Where + Insights; per-slide perf on huge corpora | UNBUILT | CLAUDE.md MAP REWORK remaining | CLAUDE.md | P19 |
| UI-17 | Task-manager History tab; per-job rate/ETA/bandwidth cap (owner-measured) | UNBUILT (deliberately, needs owner-measured rates) | CLAUDE.md #20 | CLAUDE.md | P10 |
| UI-18 | GUIs gallery: human click-through across themes; screenshot thumbnails; translate the per-UI essays | BROWSER-GATED | invariant #30 | CLAUDE.md | P15 |
| UI-19 | Every "browser-unverified per fork-3/Q6a" slice since 2026-06 not covered by the 08-13/08-20 walks | BROWSER-GATED | the walks' surface list | audits | P15 |

## DAT — data, backup, import, storage
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| DAT-01 | S6.2 file members (wiki/OSM/models) inside the SIGNED volume manifest (`file_members` block + traversal guards) | UNBUILT | no `file_members` in `src/backup/artifact.py`/`stream_backup.py` | CLAUDE.md S6 closeout (1) | P07 |
| DAT-02 | Legacy single-file restore removal | RULING-GATED (C1) | `src/api/backup_v2.py:49…374`, `app-backup.js:604,660` | FD §49 | P07 |
| DAT-03 | Import checkpoint interval K | **BUILT 2026-09-07** — the mechanism ships; K is `AppSettings.import_checkpoint_k`, range 1..24, **default 1 = today's behaviour**, so the RULING (C2: which K) is still the maintainer's and is all that is left | `src/backup/import_queue.py:import_checkpoint_k`; `src/backup/merge.py:run_restore(working_copy=, hold_after_merge=)`; `tests/test_import_checkpoint.py` | CLAUDE.md 2026-08-08 (b) | P08 |
| DAT-03b | Import prefetch (stage the next backup while the current one merges) | PARKED, blockers re-verified at `main`@690920e | singleton `volume_job.py:196` `_reap_or_reject`; `cleanup_staging` in a merge-thread `finally` at `volume_job.py:764`; the digest check at `volume_job.py:456` runs 94 lines before `read_volume_backup` at `:550`. C3's own gate (a field `verify_copy` number) is still unmet | CLAUDE.md 2026-08-08 (a) | P08 |
| DAT-04 | DB-10 migrate op (rebuild at the ruled pragmas) as a user-facing action | RULING-GATED (C5) | `src/database/connect.py:84` fresh-file pragmas; bench = mechanism proof | CLAUDE.md | P22 |
| DAT-05 | D1 httpfs binaries + pins (`configs/external_artifacts.yml:491-495` blank) | OPERATOR-GATED (C6) | registry | PERSISTED_DUCKDB_HTTPFS | P22 |
| DAT-06 | Data-location chooser at first launch (`OOS data` subfolder) | UNBUILT (C7) | no hits in unlock.html/unlock.py | FIX_SESSION_2026-07-14_STATE | P07 |
| DAT-07 | Storage plan Phase C (packed/keyed/OOENC2 store, contentless FTS, hash-sharding prototype) + §8 rulings 3–6 | RULING-GATED (C4) | STORAGE_5TB_PLAN §8 | design doc | P22 |
| DAT-08 | `_MERGE_NOT_CARRIED` five identity-less tables — handlers | BUILT (2026-08-03 rulings received + built) | CHANGES 0.3.0; `src/backup/merge.py:1696` list now only derived/per-machine tables | — | — |
| DAT-09 | Run-journal + `run_logs` in backups? (journal files are per-machine; not carried) | UNCHECKED | `docs/maintenance/RUN_JOURNAL.md` | — | P07 |
| DAT-10 | Postgres parity vs SQLite-only | **SHIPPED 2026-09-07** (J3 ruled SQLite-only; ARCHITECTURE.md's lower half rewritten, session.py degrades loudly, init-postgres.sql bannered) | `tests/test_sqlite_only_backend.py` | PARKED ARCH-06 | P20 |
| DAT-11 | `sqlite3mc` benchmark trial | RULING-GATED (C4 #6) | STORAGE_5TB_PLAN §6 | design doc | P22 |
| DAT-12 | Merge step 3 unexplained 15–65× gap (FTS relocated; residual candidates: codec over multi-GB FTS segments, virtual disk); `cost_probe` measures on the operator's machine | OPERATOR-GATED | CLAUDE.md MERGE STEP 3 entry | CLAUDE.md | P08 |

## PERF — throughput, scale, crash-brief remainder
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| PERF-01 | Crash brief S3.6: lock-state cache + 56 DB-touching `async def` handlers → `def` (source_management 50) | **BUILT 2026-09-07** (was HALF-SHIPPED: the lock-state cache landed with PR-10 `d447fe6d`; the 56 handlers did not) | cache: `src/database/connect.py:394-437` (`main_header_state` + `invalidate_header_cache`, TTL belt) via `src/api/unlock.py:53`. Handlers: 56 → 4 (`tests/test_handlers_off_the_event_loop.py` is the AST guard; the 4 that remain await the request stream) | crash brief §5 S3.6 | P09 |
| PERF-02 | Crash brief §8 field twins (B pass, C 72 h soak, A bundle, P0-style run) + host kernel-log checks | **OPERATOR-GATED — and now the ONLY thing left of the whole crash brief.** All 29 slices shipped as of 2026-09-07 (verified by matching every `#### S<n>.<m>` heading against `shipped.csv`), so this batch has MECHANISM evidence and no EFFECT evidence until these run. The `-b -1` host checks EXPIRE: a boot rotation destroys that journal | brief §8; the remainder is itemised in `docs/ledger/OPEN_QUEUE.md` under the SYSTEMATIC CRASHES entry | brief | P09 |
| PERF-03 | Throughput C16 (S-D extraction out of the write gate, evidence-gated on writer-bound verdicts) + C17 (A1 decouple ingestion from enrichment) | UNBUILT (deferred per the brief's own gates) | shipped.csv row 464 | C brief | P10 |
| PERF-04 | Indexing throughput board ①–⑨ (`INDEXING_THROUGHPUT_ANALYSIS_2026-08-03`) — per-item status | UNCHECKED (agent B) | design doc | design doc | P10 |
| PERF-05 | Before/after bench on the 8-core/20 GB machine for the duty-cycle fix; the 5M diagnostics bar returns when speed allows | OPERATOR-GATED | CLAUDE.md 2026-07-23; gate row 3 note | CLAUDE.md | P10 |
| PERF-06 | `collect_perf` rolling retention too short to see multi-hour stalls (Library graphs are the detector) | PARTIAL | CLAUDE.md 2026-07-23 | CLAUDE.md | P10 |
| PERF-07 | Overlap the network ride-alongs with the next pass's fetch phase (S4.1 cause ii) | UNBUILT | CLAUDE.md 2026-07-23 REMAINING | CLAUDE.md | P10 |
| PERF-08 | Collector write-batching remainder (extraction-in-gate) = C16 | see PERF-03 | — | — | P10 |
| PERF-09 | Per-job rate/ETA/bandwidth cap (owner-measured bytes-over-time; throttling backend) | UNBUILT | CLAUDE.md #20 | CLAUDE.md | P10 |
| PERF-10 | 0.4 row 7b soak support: engage cycles/day, `wal_history` max, busy share, `/api/database/stats` p95, `interrupted` count — a one-page soak REPORT member | UNBUILT (instrument) | brief §8 field twins | brief | P01 |

## NET — security and network
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| NET-01 | SSRF TOCTOU: the guard's `getaddrinfo` answer is not the one `requests` connects on | FIXED 2026-09-07 — by validating the address ACTUALLY reached, not by pinning (pinning needs urllib3's private connection construction plus a hand-carried hostname for SNI/cert matching, and fails OPEN when that moves) | `src/ingest/ssrf_guard.py`; scope entered in `src/ingest/__init__.py::_guarded_redirect_get`; `tests/test_ssrf_connect_guard.py` | PARKED | P21 |
| NET-02 | `safe_href` and `sanitize_url` held a broad `except Exception` around `urlparse` | FIXED 2026-09-07 (`ValueError` only; `urlparse` hoisted so the propagation half is testable) | `src/utils/security.py`; `tests/test_security_hardening.py` NET-02 block (+ `test_a_non_str_input_already_raised_BEFORE_the_narrowing`, PR #1035, which measures that PARKED's stated blocker — "changes behaviour for non-str inputs" — was false: both functions touch the input before the `try`, so a non-str always raised outside the block) | PARKED | P21 (PROMPT_20 S5 also claimed it; #1031 landed first and this row follows the code) |
| NET-03 | DDG redirect results dropped (`uddg` unwrap) | FIXED 2026-09-07 (same fix as PRH-03) | `src/services/duckduckgo.py::_unwrap_search_redirect`; `tests/test_duckduckgo_url_helpers.py` PRH-03 block | PARKED | P21 |
| NET-04 | Nonce-based CSP (blocked on inline-handler retirement — the blocker is ~590 handlers, ~331 in `index.html` + ~259 across the 17 `app-*.js` modules; landing the nonce first breaks the app) | UNBUILT (sequenced behind P15 S2) | `src/api/main.py::_CSP` `script-src 'self' 'unsafe-inline'` | audit S-006 residual | P21 |
| NET-05 | S-012 indirect prompt-injection posture for LLM inputs | UNCHECKED | D1 notes #34 | PR history | P21 |
| NET-06 | Tor-exit-resolve (SOCKS 0xF0) for source IP over Tor | RULING-GATED (I3); re-verified 2026-09-07: `0xF0`/`dns-via-tor-exit` appear nowhere under `src/` | CLAUDE.md SOURCE IPs amendment | CLAUDE.md | P21 |
| NET-07 | `oo-netcut` privileged airplane layer; Stem-controlled Tor + consented per-source clearnet | RULING-GATED (I4); re-verified 2026-09-07: nothing under `src/` imports `stem` or names `netcut` | FD §"Reliable Tor" / network switch | FD | P21 |
| NET-08 | App self-update mechanics (snapshot→verify→migrate→swap→rollback) + Q1–Q5 | RULING-GATED (G9); re-verified 2026-09-07: no `self_update` module (the two `src/static/` hits are unrelated comments) | FD §"In-app self-update"; no `self_update` code | FD | P21 |
| NET-09 | Release signing key (checksums only today) | RULING-GATED; re-verified 2026-09-07: `release.yml` publishes `SHA256SUMS` and its own header already says signing is a tracked future item, so the release path does not over-claim | gate §7.3 step 7 | gate | P21 |
| NET-10 | Airplane guard: SOCKS/Tor blind spot CLOSED 2026-07-25; `_tunnel` + `socksocket.connect` patched | BUILT | audit 09 fix-forward | — | P21 |

## STRUCT — structural debt and test hygiene
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| STR-01 | S-1 `src/api/diagnostics.py` **6,291 lines / 100 GET + 128 total routes** → package split | UNBUILT; J1 answered "yes" but NOT attempted 2026-09-07 — see the carry-over. The completeness ratchet the prompt says is needed ALREADY EXISTS (`test_all_diagnostics_bundle_covers_every_get_diagnostic`), and it plus **19 others — 20 sites across 4 test files in total** — read `diagnostics.py` AS A FILE, so the split must ship a concatenating reader first (the 2026-08-20 `app.js` lesson) | `wc -l`; `grep -c @router` | ROADMAP S-1 | P20 |
| STR-02 | S-2 import cycles: 6 modules import `src.api.main` (diagnostics, llm, ai, insights, unlock, scale_bench) | UNBUILT | grep | ROADMAP S-2 | P20 |
| STR-03 | S-4 ad-hoc slicer budget 232 → lower (route through `js_source_helper`) | UNBUILT (ratchet) | `tests/test_source_slicing_discipline.py:253` | ROADMAP S-4 | P20 |
| STR-04 | `structlog` orphaned core dependency (pyproject:79, 0 call sites) | **SHIPPED 2026-09-07** (J2 ruled drop; pyproject + lockfile + ETHICS table; both venv profiles re-verified) | `tests/test_dependency_hygiene.py` | PARKED MAINT-04 | P20 |
| STR-05 | `view_article` (`src/api/main.py`) / `build_families` refactors; cc≥C list | UNBUILT | PARKED | PARKED | P20 |
| STR-06 | MinHash vectorisation (PERF-01) | UNBUILT (low) | PARKED | PARKED | P20 |
| STR-07 | ruff advisory lane 344 → 0; mypy/ruff-style blocking flip | PARTIAL (mypy blocking; ruff style advisory) | PARKED; ci.yml | PARKED | P20 |
| STR-08 | Subset-order test pollution: `test_a2_job_endpoints` before `test_doctor_healthy_returns_zero` | UNBUILT (flagged 2026-07-12) | CLAUDE.md S1.1 finding | CLAUDE.md | P20 |
| STR-09 | 84 `print(` statements — all blessed by the AST guard; migration set EMPTY | BUILT (nothing to do) | PARKED MAINT-04 | — | P20 |
| STR-10 | `ConfidenceInterval.sample_size` fractional under Haldane–Anscombe — a statistics call | RULING-GATED (soft) | PARKED | PARKED | P20 |

## NEWS — newsletters
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| NEWS-01 | eTLD+1 PSL resolver + deterministic silent auto-attach + UNDO window + platform inversion (substack etc.) | UNBUILT | no `public_suffix`/`etld` in src; `src/privacy/` holds only `link_sanitizer.py` | EMAIL_NEWSLETTER_IMPORT_PLAN S2/S3 | P19 |
| NEWS-02 | Task-manager-visible job over a long live mailbox pull | UNBUILT | CLAUDE.md ruling 11 REMAINING | CLAUDE.md | P19 |
| NEWS-03 | Stored/encrypted credentials for repeat pulls | RULING-GATED (I1) | same | CLAUDE.md | P19 |
| NEWS-04 | Import-time no-recovery disclosure ×12 | UNCHECKED | Non-negotiables contingency | CLAUDE.md | P19 |
| NEWS-05 | Legacy `scripts/import_eml.py` retirement | BUILT (file absent) | ls | plan "To retire" | P19 |

## WIKI — Wikipedia as a living source
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| WIKI-01 | Whole-edition ingest: dump-as-baseline + `recentchanges` delta + auto-track after a dump download | UNBUILT (only title-list `ingest_dump_pages` + `fetch_recentchanges` client exist) | `src/wiki/corpus.py:237,275`; `client.py:81` | FD §1/§22; V1-9 | P18 |
| WIKI-02 | Dedicated tracked-changes TAB in the reader | **CORRECTED 2026-09-07 — the VIEW was already SHIPPED, the READER was not**; the "no hits" evidence was wrong. Now complete: the reader states the version and links the local history. | `src/static/app-map.js` `openWikiTC`/`_wikiRevRow`/`loadWikiTC`; `index.html` `#wiki-tc`; `GET /api/wiki/pages/{id}/revisions`; reader + `?wikitc=` deep link 2026-09-07 | CLAUDE.md WIKIPEDIA entry | P18 |
| WIKI-03 | Wikitext rendering | UNBUILT — design written 2026-09-07, deliberately not half-built (a new HTML-emitting surface over untrusted markup; its safety argument is the whole slice) | no renderer | CLAUDE.md | P18 |
| WIKI-04 | Per-mention revid anchoring | **SHIPPED 2026-09-07 as a per-ARTICLE anchor** (`Article.source_revision`) — per-mention would store a per-article constant once per mention; deviation recorded | `src/database/models.py`; `src/wiki/corpus.py`; migration `b5684999c1e1` | CLAUDE.md | P18 |
| WIKI-05 | One consented "refresh exact sizes" replacing the per-edition probe button | **SHIPPED 2026-09-07**; the single-request `dumpstatus.json` mechanism is PARKED — the premise was never verified and the host is egress-blocked here | `src/wiki/dumps.py` `probe_sizes`; `GET /api/wiki/dumps/sizes` | CLAUDE.md | P18 |
| WIKI-06 | Questions 1–5 | **CORRECTED 2026-09-07 — THREE OF THE FIVE ARE ALREADY RULED** (Q2 same pools · Q3 per-revision full text, shipped · Q4 the tracker is the feed), all by the maintainer's own 2026-06-12 ruling recorded in the section that filed them. Q1 (ingest scope) and Q5 (backups) remain RULING-GATED (G10). | FD §22's ruling block | FD | P18 |
| WIKI-07 | `plain_from_wikitext` carried the recorded K·N `OPEN.*?CLOSE` bomb in three patterns, on the wiki INGEST path | **FIXED 2026-09-07** — measured 13.4 s per 400 KB of unclosed-`<ref>` spam against 0.014 s well-formed; now 0.0030 s, byte-identical over 20,000 randomised documents | `src/utils/markup_blocks.py`; `src/wiki/corpus.py`; `src/analytics/extract.py` | found this session | P18 |

## MAP — maps and geo
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| MAP-01 | OSM offline preprocessing bridge (admin-1 boundaries + gazetteer + finer admin-0; border honesty) | UNBUILT | only `src/geo/osm_*` download manager + `src/static/osmpbf.js` bounded preview | ACTION_PLAN_2026-07-13 Part 2; 2026-07-22 Phase 6 | P19 |
| MAP-02 | Map change-tracking over dated OSM extracts | UNBUILT (later) | same | design doc | P19 |
| MAP-03 | Sources-by-observed-IP choropleth dimension (distinct from asserted country) | UNCHECKED (reader + per-source view built) | `queries.py:1369 source_observed_ips` | CLAUDE.md SOURCE IPs (3) | P19 |
| MAP-04 | Dead temporal-map deletion (see UI-04) | — | — | — | P15 |

## AGD — agenda, events, hazards, weather
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| AGD-01 | Religious calendars (Islamic tabular ±1 day; Hindu/Buddhist published tables) + eclipse canon — dates from the maintainer | OPERATOR-GATED (G8) | ruling 9 (2026-06-17) | CLAUDE.md | P19 |
| AGD-02 | RRULE recurrence expansion of imported VEVENTs; month-span banners; `since:` origin display; saved-filter smart calendars | UNBUILT | no `rrule` in `src/events`; `catalog.py:73` spans exist for curated | S6 closeout (3) | P19 |
| AGD-03 | Moon quarter phases (accepted loss when the feed was retired) | UNBUILT (optional) | CLAUDE.md 2026-07-17 (2) | CLAUDE.md | P19 |
| AGD-04 | Online-calendar catalog expansion (networked acquisition) | OPERATOR-GATED | CLAUDE.md 2026-07-17 (5) | CLAUDE.md | P19 |
| AGD-05 | Elections calendar acquisition session (coverage floor + three-tier confidence) | RULING/OPERATOR-GATED (G2) | V1 §4.5 | V1 | P23 |
| AGD-06 | Event significance tier / personal tag namespace / IPO-tech-launch-regulatory calendars | UNBUILT (ideas) | D1 notes #43/#50 | PR history | P19 |
| AGD-07 | Hazard channels beyond USGS/GDACS (NWS, ReliefWeb, FEWS NET, EONET, WHO); nuclear/radiological urgent rule; official forecast relay | UNBUILT | `src/hazards/parse.py` GDACS+USGS only | FD §"Hazard & news alerting"; D1 #51/#52 | P19 |
| AGD-08 | Open-Meteo anomaly baselines, signal-keywords, reader weather row, temporal-map overlay | UNBUILT (slice 1 shipped) | FD §"Open-Meteo" | FD | P19 |
| AGD-09 | El Niño ONI clearnet verification (`verification_status` flagged) | OPERATOR-GATED | `configs/climate_events.yml:11,20` | FD | P19 |
| AGD-10 | Agenda ↔ Wikipedia linking | UNBUILT | FD §"Agenda ↔ Wikipedia" | FD | P19 |
| AGD-11 | Lunar-effects testing framework (correlate daily series vs lunar, BH-FDR, pre-registration UI) | UNBUILT (series shipped) | FD §"Lunar-effects" | FD | P19 |

## V1 — verticals and user-centric features
| ID | Item | Verdict | Evidence | Claim lives in | Prompt |
|---|---|---|---|---|---|
| V1-A | V1-1..V1-9 rulings | RULING-GATED (G1) | V1_PATHWAY §7 | V1 | P23 |
| V1-B | Elections/civic: roster (two-class deduced/confirmed), coverage floor, poll Tier 2, event-timed-op card, flag-distribution self-audit | UNBUILT (design complete) | FD §"Elections"; `configs/world_events.yml` elections calendar only | FD | P23 |
| V1-C | Climate/environment: OWID CSVs, quakes/fires/air quality (key-gated), ONI | UNBUILT | V1 §4.3 | V1 | P23 |
| V1-D | Patents/IP, PubMed (V1-4), conflict/defense (V1-3) | UNBUILT (no code) | `grep pubmed/patent src` → producers only | V1 §4 | P23 |
| V1-E | Claim Workspace A1, entity spine, dossier (0.5); A2 corpus passport; A8 saved analyses; A9 since-last-visit | UNBUILT | FD §"User-centric reflections" A1–A9 | FD | P23 |
| V1-F | Scenario cards remaining: #1 warnings-existed, #5 news-desert atlas, #6 story-propagation (BUILT as `story_propagation`?), #4b BURY half, silent-disasters, law-takes-effect | PARTIAL (`disputed_chronology`, `story_propagation` exist at producers.py:2589/2654) | grep | FD §"Seven remaining scenario cards" | P23 |
| V1-G | Training & onboarding supervised track (curriculum, facilitator guide, synthetic exercise corpus) | UNBUILT (design) | FD §"Training & onboarding" | FD | P23 |
| V1-H | Voice-only mode; Open Commons Mirror sister project; offline LLM kit (RM-08) | UNBUILT (designed, not committed) | FD | FD | P23 |
| V1-I | Language-manipulation detector ideas from the never-merged PR #16 (fallacies, euphemism, doublespeak, weasel claims) — recorded in FD? | UNCHECKED (grep found FD mentions) | D1 notes | PR history | P23 |

## PRH — items found ONLY in the PR history (not in CLAUDE.md, ROADMAP, PARKED, FUTURE_DEVELOPMENTS or shipped.csv)

The four PR-history agents read every merged and closed pull request from #1 to #1010 and cross-checked each
forward-looking sentence against the five memory files. These are the ones that matched nothing. Each is small;
the value is that a deliberate decision or a known defect stopped being written down anywhere a future session
would look.

| ID | Item | Verdict | Evidence | First recorded in | Prompt |
|---|---|---|---|---|---|
| PRH-01 | `backfill_corpus` (the automatic Insights top-up) has **no cursor** — an article that legitimately yields zero terms is re-selected on every call, forever, and occupies the front of the queue | UNBUILT (live-reproduced) | `src/analytics/store.py:507` `_unindexed_query(...).order_by(Article.id).limit(...)`; reproducer `scripts/analysis/repro_backfill_wedge.py` | PR #851 | P05 |
| PRH-02 | `structlog` is an orphaned core dependency: declared in `pyproject.toml:79`, **zero** call sites in `src/` (stdlib logging ~612 sites) | RULING-GATED (J2) | `grep -c structlog src/**/*.py` → 0 | PR #967 (PARKED) | P20 |
| PRH-03 | `_clean_url` strips the query string **before** validation, so every real DuckDuckGo `/l/?uddg=<target>` redirect result loses its target and is discarded as scheme-less; the existing test asserts only `isinstance(results, list)` | FIXED 2026-09-07 — the redirect is resolved FIRST; a redirect with no usable target is discarded rather than falling back to the redirector (which on the absolute form is a valid https URL and would register duckduckgo.com as a discovered source). The query strip on the final url is deliberately UNCHANGED and now stated | `src/services/duckduckgo.py::_unwrap_search_redirect`; `tests/test_duckduckgo_url_helpers.py` (+ four negative-space cases added there by PR #1035: the `html.duckduckgo.com` subdomain hop that is the production host, a `duckduckgo.com.evil.example` lookalike, `uddg` after `rut`, and an empty `uddg`) | PR #967 | P21 (PROMPT_20 S5 also claimed it; #1031 landed first and this row follows the code) |
| PRH-04 | `scripts/setup_llm.py` — WORSE than recorded: BOTH its imports (`src.llm.config`, `src.llm.model_manager`) name modules that are gone, so it died at import with `ModuleNotFoundError` before parsing an argument; `start_ollama` was never reachable | **SHIPPED 2026-09-07** (deleted; the capability is in-app, and `scripts/README.md` records the removal) | reproduced, not read | PR #793 | P20 |
| PRH-05 | `extract_locations` compiles and scans the whole text once **per gazetteer entry** (~4,700 regexes; 2,558 ms/article at 4,500 cities) — only bites installs that ran `build_city_gazetteer.py` | UNBUILT (measured, not fixed) | `src/timemap/locextract.py:164` `for rx, name, kind in _patterns(): for m in rx.finditer(text)` | PR #799 | P05 |
| PRH-06 | Keyword aggregates in `store.py`, `rollup_serve.py` and `columnar.py` have **no quarantine filter** (`queries.py` has 9 references, the other three have 0) — the two must move together with `corpus_language_shares` | UNBUILT | grep counts above | PR #817 / #863 | P05 |
| PRH-07 | `AiKeyword.evidence` (`models.py:1944`) has zero writers, and `POST /api/ai/keywords/confirm` has no frontend consumer | SHIPPED 2026-09-07 — WIRED, not retired. `evidence` is a deterministic read of the article's own stored text (never a model claim) and is ABSENT when the term is not in it, which is the finding; the read-only lens + confirm control live beside the trusted keywords in the reader | `src/ai_layer/store.py:evidence_for`, `src/static/reader.js`; `tests/test_ai_keyword_evidence.py`, `tests/ai_lens_node_test.js` | PROMPT_11 | P11 |
| PRH-08 | `r.samples` is dead at THREE sites, not one — `sources`, `articles` and `wiki_pages`, all in `src/backup/merge.py` (not `source_management.py`): each sample query runs after its INSERT, so the `NOT EXISTS` is never true and every restore report omitted its examples | FIXED 2026-09-07 (read back from `merged_rows`) | `merge.py:_new_row_samples`; `tests/test_merge_report_samples.py` | PR #915 | P04 |
| PRH-09 | `#vllm-model-input` is never prefilled from the stored `llm_model_vllm` setting | RESOLVED 2026-09-07 as RETIRE, not prefill — the element exists NOWHERE in the tree and its only reader (`startVllm`) had ZERO callers, so its own guard toasted "Enter a model id first." on every possible click. The 2026-08-04 fusion made the Local AI card THE one control (`/api/llm/activation/start`); a second start button would re-create the routing-vs-provisioning confusion that fusion removed | `src/static/app-ai-tools.js` | OPEN_QUEUE 2026-09-07 | P11 |
| PRH-10 | Nine `shipped.csv` rows (2026-07-18 … 08-13) carry a bare `PR pending` in `refs` although all nine merged — either a sweep or a convention ruling ("record the PR number on merge" vs "`PR pending` is fine") | UNBUILT (flagged) | PR #993 body | PR #993 | P02 |
| PRH-11 | The four cross-language collision words deliberately omitted from the global stoplist (`sea`/`tom`/`fin`/`laut`) — the refusal is reasoned and recorded nowhere a future stoplist batch would read it | UNBUILT (record) | PR #514 body | PR #514 | P05 |
| PRH-12 | A NULL-only backfill migration for the `country_from_title` recoveries | NON-ITEM (measured 2026-09-07: `country_from_title` recovers **0** of the 1,599 catalogue entries that carry no explicit `country` — the 2026-06-16 batch promoted all 68 `(Country)`-suffix entries into explicit fields and a regression guard keeps it so, leaving the migration with no subject). The REAL gap it was standing in for is broader and unmeasured: the seeder is create-only, so no catalogue metadata improvement (country, language, tags) ever reaches an existing install — same root cause as SRC-12 | `catalog_domain_collisions` probe; `tests/test_seed_sources.py::test_catalog_honours_its_own_country_suffix_convention` | PR history | P04 |
| PRH-13 | Platform-name stoplist ruling (`facebook`/`twitter`, `comments`/`follow`) — dual-use, never ruled | RULING-GATED (soft, fold into B2) | PR range #423–#520 notes | PR history | P05 |
| PRH-14 | The unwired `#vitals-pop` popover is still in the tree (`index.html`, `app-boot.js`, `app-core.js`) and is **absent from** the recorded dead-UI worklist | UNBUILT | PR range #423–#520 notes; grep | PR history | P15 |
| PRH-15 | Per-source boilerplate flags (the Pluralistic `yrsago` / `permalink` / `ISSN` case) — a source-scoped furniture channel distinct from the language-scoped stoplist | UNBUILT | PR range #423–#520 notes | PR history | P05 |
| PRH-16 | `OO_REQUIRE_CONSENT`, `CONSENT_DOC_VERSION` and a web consent modal were designed during the legal-acceptance work and exist nowhere | STALE-CLAIM (corrected 2026-09-07): **two of the three exist.** `CONSENT_DOC_VERSION` is present with `is_accepted`/`needs_acceptance`/`record_consent` around it; the web consent surface is present too, as a dedicated PRE-APP PAGE rather than a modal — deliberately, because it blocks harder. Only `OO_REQUIRE_CONSENT` is absent, and that is a recorded decision (it would strand a launcher / `curl \| bash` user with no console), not an oversight. Open question: whether the opt-in hard block should ever ship | `src/legal/consent.py:43`; `src/api/legal.py` + `src/api/unlock.py` locked-state allowlist; `docs/legal/IMPLEMENTATION_NOTES.md`; `tests/test_legal_documents.py::test_unlock_first_launch_inserts_legal_step_before_passphrase` | PR history | P21 |
| PRH-17 | The legal `[À VÉRIFIER]` items and the per-release "confirm no telemetry" ritual are recorded in no memory file | UNBUILT (record) | PR range #423–#520 notes | PR history | P02 |
| PRH-18 | Install docs were never updated for the seamless (no-prompt, auto-launch) installer | STALE-CLAIM | PR range #423–#520 notes | PR history | P02 |
| PRH-19 | A future opt-in "leave no uninstall log"; the uninstall dynamic preview/confirm dialogs stay English | UNBUILT | PR range #423–#520 notes | PR history | P15 |
| PRH-20 | The passphrase no-recovery WARNING and the security-dense custody paragraphs were deferred for native review, never scheduled | OPERATOR-GATED (native review) | PR #462 / i18n slices | PR history | P15 |
| PRH-21 | `configure_ollama_store_access` is defined and test-pinned but never called from `src/llm/installer.py`; the `OLLAMA_MODELS` hint is never keyed | PREMISE REFUTED 2026-09-07 — it is a SHELL function in `install.sh:495`, not in `installer.py`, and its uninvoked state is a deliberate maintainer ruling (2026-06-20 field test: the installer "asks NOTHING and never provisions Ollama") recorded in the comment above it and pinned by `test_seamless_install_and_language_first_first_launch`. Wiring it would run `sudo chmod` during install. NOT DONE. (SECOND HALF ALSO REFUTED 2026-09-07: the `OLLAMA_MODELS` hint is `install.sh:526`, INSIDE the never-invoked function (495-528, zero call sites), so it never prints and cannot be unkeyed for a user; `install.sh` has no i18n machinery either. The live question is keep-or-delete the dead block - OPEN_QUEUE 2026-09-07 item (5)) | `install.sh:480-529`, `tests/test_repo_invariants.py:928` | OPEN_QUEUE 2026-09-07 | P11 |
| PRH-22 | Real floating events for `configs/world_events.yml` (only CHOGM is present) | UNBUILT (data) | PR range #423–#520 notes | PR history | P19 |
| PRH-23 | First-run preflight still runs inline in `src/scheduler/runner.py` rather than as a visible job | **BUILT 2026-09-07** | `src/monitoring/preflight_job.py` (registered `first-run-preflight`); `src/scheduler/runner.py` kicks it under the `first-run-preflight` tail phase | PR history | P09 |
| PRH-24 | A "Registered statistics sources" view was designed and never built | UNBUILT | PR range #261–#520 notes | PR history | P14 |
| PRH-25 | Bare-year date extraction; an acronym-aware mistagged-entity pass; the in-app Wikidata ring importer | UNBUILT (ideas) | PR range #261–#520 notes | PR history | P05 |
| PRH-26 | `src/api/main.py` still holds inline endpoints that belong in the `core` router, and `observability.py` (Prometheus globals + middleware order) was never extracted | UNBUILT (refactor debt) | PR #236 | PR history | P20 |
| PRH-27 | `tests/test_installer.py` leaves an `oo.env` behind in the checkout when it runs | UNBUILT (test hygiene) | PR #931 | PR history | P20 |
| PRH-28 | `natural-earth-geometry` carries a blank `sha256` in the external-artifact registry (existence-only check) — the same one-line fix Alpine's entry got | UNBUILT | PR #976; `configs/external_artifacts.yml` | PR history | P02 |
| PRH-29 | The Windows `pytest` lane HANGS (3 h 21 m → failure; ~6 h → cancelled) | **PARTIAL 2026-09-07**: `timeout-minutes: 45` caps the cost and makes the hang diagnosable (a log that stops at a known minute). The BISECT is still unbuilt and still deserves its own task — no Windows runner here | `.github/workflows/ci.yml` `portability` | PR #977 | P20 |
| PRH-30 | `RestoreAborted` labels the outcome `cancelled` and journals "stopped-by-operator" when the operator cancelled nothing (also the quiesce barrier) | UNBUILT (re-labelling slice) | PR #987, recorded in a source comment | PR history | P07 |
| PRH-31 | `_window_daily_series` omits zero-count days, so the index axis compresses (day 1 and day 5 render adjacent); repair is zero-FILLING and touches the trending sparklines | UNBUILT (re-confirmed live 2026-09-07: `src/analytics/queries.py:1714`, and `app-corpus.js:1293` carries a comment acknowledging the omission) | PR #850 / #863 | PR history | P15 |
| PRH-32 | The `h3`-over-`h2` type inversion fixed for `#tab-settings` still exists on Home, Insights, Markets panels and the two Export/Import dialogs | **SHIPPED 2026-09-07 (PR #1029)** — measured in Chromium on all 17 themes first (Home's section title 12.5px `--muted` at 4.56-12.71:1 under a 15px full-`--fg` card title at 6.07-18.10:1), then lifted app-wide through a zero-specificity `:where()` default so the deliberately-small labels still win. The two dialogs were a SEPARATE defect: they alone of eleven omitted `background`/`color`, so the theme never reached them — fixed by one `dialog{}` rule | PR #921; PR #1029 | PR history | P15 |
| PRH-33 | Three Library subtab labels (`Activity`, `Tracked`, `Database & storage`) are unkeyed | **SHIPPED 2026-09-07 (PR #1029)** — keyed x12 by textual insert (3 added / 0 deleted per file), verified rendering live in all twelve locales through `OOI18N.setLang()`; untranslatable ratchet 560 -> 557 in the same PR | PR #867; PR #1029 | PR history | P15 |
| PRH-34 | The 2026-06-17 supervised-training track (curriculum, facilitator guide, train-the-trainer, synthetic exercise corpus, safety self-check) is recorded only in PR #49 | UNBUILT (design) | PR #49 | PR history | P23 |
| PRH-35 | The never-merged PR #16 (the maintainer's own idea file) lists a language-manipulation detector — formal/informal fallacies, sophism, euphemism, dysphemism, doublespeak, gaslighting, weasel claims, framing effect, slippery slope, false analogy, circular reasoning, red herring — and an article↔source publication-date delta | UNBUILT (idea) | PR #16 diff | PR history | P23 |

### PR-history dispositions worth keeping (verified, nothing to do)
- `p0_validation.py`'s "100 GB" acceptance strings were **corrected on 2026-08-03** — the module now carries the
  real figures in a comment. REL-04 above is therefore closed; the ledger entry naming it is the stale half.
- The three closed-unmerged PRs whose content re-landed elsewhere (#7 install, #18 PQC/custody, #66 the 0.09
  branch) hold nothing that is not in the tree, **except** #18's key-rotation / Key-Revocation-List /
  hardware-backed-key (YubiKey, TPM) design notes, which exist in no memory file.
- PR #398 (blind-by-language keyword filter) and PR #496 (Home "Latest") were closed on purpose and both
  refusals are recorded in CLAUDE.md — do not rebuild either.

## Cross-cutting lists

### Operator-gated (needs a networked machine, a real corpus, or the maintainer's hands)
REL-01 (Tier A quarantine pass) · REL-02 (the tag) · REL-07 (≥72 h soak) · SRC-07 (`source_qualification.yml`) ·
SRC-10 (source-tag canary re-run) · SRC-13/14/15 (diversification + de-US + world-discovery runs) ·
KW-01 (month-occupancy number) · KW-02/04 (`dumps.wikimedia.org`) · KW-03 (168-seed ring batch) ·
KW-13/14/15 (the graded gold sets) · LAW-02 (live enumeration) · LAW-10 (vetting board) ·
GOV-01/04/09/11 (World Bank, agencies, BRICS/AfDB/UNECA, page-2 tail) · AI-05 (`/llm-bench` twice) ·
AI-15 (the LiquidAI lookup) · AI-17 (the ~50-anchor grading) · DAT-05 (httpfs binaries) ·
DAT-12 (`cost_probe` on the field machine) · PERF-02/05 (field twins, the 8-core bench) ·
AGD-01/04/09 (calendars, ONI) · PRH-20 (native review) · REL-10 (Alpine freshness review).

### Ruling-gated (a maintainer decision; question IDs in `QUESTIONS_FOR_THE_MAINTAINER.md`)
A2 A3 A4 · B1 B2 B4 B6 B7 · C1 C2 C4 C5 C6 C7 · D1 D2 D3 D4 D5 D6 D7 D8 D9 D10 · E3 E4 · F1 ·
G1 G2 G4 G8 G9 G10 · H1 H2 H3 H4 · I1 I3 I4 · J1 J2 J3.

### Browser-gated (the sandbox CAN drive Chromium; the maintainer's UX pass is the remaining bar)
UI-01 UI-08 UI-15 UI-18 UI-19 · GOV-10 · every slice stamped "browser-unverified per fork-3/Q6a" since
2026-06 that the 2026-08-13 and 2026-08-20 walks did not reach.

### Stale claims to correct (a doc says one thing, the tree says another)
DOC-01 (the 2026-07-22 plan's Phase 2 is done) · DOC-03 (dead refs) · DOC-04 (ROADMAP) · DOC-05 (nav-soup draft) ·
DOC-06 (six design-doc banners) · DOC-07 (five CLAUDE.md Open-queue entries describing shipped work) ·
KW-12 (stoplists → data files) · SRC-06 (newsletter links) · AI-12 (Ollama `num_ctx`) · AI-16 (qualification-assist
button) · UI-03 (the inline-handler count: ledger says 295, the tree says ~590) · REL-04 (the "100 GB" strings) ·
PRH-18 (install docs) · the four "PENDING execution" brief banners whose briefs were executed within 48 hours.
