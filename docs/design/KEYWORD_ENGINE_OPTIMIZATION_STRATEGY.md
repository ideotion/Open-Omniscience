> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — Phases 1 through 5.1, 4.2, and 4.3 (mechanism AND the 2026-07-18 default-on flip, `OO_FAMILY_LEMMA` now defaults to `"1"`) are all confirmed SHIPPED. P5.2 (static-embedding recall layer) and P6 (entity→QID via OpenTapioca) remain genuinely unbuilt — zero code for either. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Keyword-engine optimization — implementation strategy

> **What this is.** The build blueprint for the keyword search-and-analytics optimization, synthesizing
> three research artifacts under `docs/research/keywords/` (the FOSS conflation research, the
> complete-log evidence addendum, the performance-first IR/computational-journalism report) with a
> **code-grounded** audit of the live engine. It is sequenced by dependency and cost/yield so a build
> session can execute it top-down. Every code anchor below was verified against the tree
> (commit base: `0.09`). If anything here conflicts with `CLAUDE.md`, **`CLAUDE.md` wins.**
>
> **Reset-proof reading order:** this doc → `docs/research/keywords/*` → the existing scaling/rebuild
> design docs it EXTENDS (`docs/design/SCALING_DERIVED_LAYER_1000X.md`,
> `docs/design/COLLECTOR_WRITER_BATCHING.md`, `docs/design/PERSISTED_DUCKDB_HTTPFS.md`) → the code.
> **Extend those, never recreate them.**

---

## 0. North star + the one reframe

**Serve the investigative journalist: find, cross-reference, and verify across many sources and
languages WITHOUT being misled.** That last clause is the design constraint — a recall aid that can't
explain itself is worse than useless, because a false lead costs the user's scarcest resource (trust +
time). So there is a hard line between the **trusted layer** (exact, reversible, provenance-bearing —
the rule-based keyword/entity index + FTS5) and any **recall/perception layer** (approximate, labelled,
disposable — embeddings, near-dup, the LLM tier), which **never feeds the trusted index.**

**The reframe both research streams + the code converge on:** almost none of the current pain is a
*search-engine* problem; it is a **derived-state-rebuild problem.** FTS5 at 10^5 docs / 10^6 keywords is
inside its envelope. What hurts is (1) how the index/keywords are *rebuilt*, (2) running whole-corpus
aggregates *on demand* instead of maintaining them, and (3) carrying *junk* keywords that inflate every
pass. **Fix the rebuild, the rollups, and the junk — keep the rule-based primitive, augment it.** This
is the SAME skeleton the project already committed to (`DATA_ARCHITECTURE_SKELETON` +
`SCALING_DERIVED_LAYER_1000X`): one canonical encrypted store + disposable derived representations off a
single seam. An independent IR researcher arriving at the project's own architecture is corroboration,
not novelty — which lowers the risk of this whole plan.

---

## 1. Current state — code-grounded (so we extend, never rebuild)

| Fact | Anchor |
|---|---|
| Live index is built by the **BaselineExtractor** — `get_extractor("baseline")` is hardcoded at ingest, so **spaCy NER never runs** and entities are **acronym-only** | `src/ingest/pipeline.py:215`; `extract.py:813` even loads spaCy with `disable=["lemmatizer","tagger"]` |
| Conflation is **display-time + reversible**: possessive + plural via `canonical_key`/`build_families`, cross-language **rings**, **super-groups**; stored rows are never rewritten | `src/analytics/families.py:104` (`canonical_key`), `:202` (`build_families`); `src/analytics/queries.py:49` (`_ring_lang_of`) |
| **Re-index is the slow path**: `reindex_all_batch` FORCE-re-indexes EVERY article via `index_article` — full re-extraction (keywords + when/where/who + sentiment) + delete-then-reinsert + counter deltas + FTS, all serialized through the **single-writer gate**, SQLCipher-decrypting each page | `src/analytics/store.py:384` (`reindex_all_batch`), `:180` (`index_article`), `:357` (`reindex_articles`) |
| The re-index is a **client-driven loop with NO persisted cursor** (restart re-does from article 0; closing the tab stops it) | `src/static/app.js` `_reindexAllLoop` (~7370), `/api/insights/reindex-all` `src/api/insights.py:217` |
| `prune_orphan_keywords` is cheap, curation-safe orphan GC | `src/analytics/store.py:433` |
| **`Keyword.language` is first-write-wins and NEVER reconciled** (the 16% / 40%-of-head mismatch). The COUNTERS *are* reconciled — the exact pattern to mirror | set at `src/analytics/store.py:75`; `reconcile_keyword_counters` `:558`, `backfill_keyword_counters` `:506` |
| Analytics "freeze" = whole-corpus `GROUP BY` over `keyword_mentions` **on demand** | `queries.top_terms:255`, `trending:981`; the covering index `ix_mention_date_keyword` exists |
| The scaling **seam exists** (delegates to live queries today); **no `keyword_daily`/`source_coverage` rollup tables yet** | `src/analytics/readmodel.py`, `src/analytics/columnar.py` |
| `columnar.py` **already uses native DuckDB `ATTACH … (ENCRYPTION_KEY …)`** + an empirical `encryption_gate`, but gates "secure" on `LOAD httpfs` (OpenSSL) because "DuckDB's built-in mbedtls is NOT securely encrypted" — **this is the D1 blocker** | `columnar.py:90` (`secure_crypto_available`), `:111` (`encryption_gate`), `:131/259` (ATTACH); `pyproject` pins `duckdb>=1.4` |
| Near-dup / coordination (MinHash + LSH) + the echo_chamber / copypasta / source-laundering cards are **already shipped** | `src/signals/near_dup.py` + producers |
| `langdetect.detect_language` never-guesses (short strings → None) | `src/analytics/langdetect.py:67` |
| A keyword-**quality** harness exists (self-test, engine report, growth curve, diagnostics exports); an IR **retrieval** eval harness does NOT | `src/analytics/selftest.py`, `engine_report.py`, `keyword_growth.py` |

---

## 2. Non-negotiables carried into every item

Offline / loopback-only; **no torch/onnx/transformers in core** (heavy ML is an optional external
Ollama-style process only). Derived stores are **disposable + encrypted-at-rest OR in-memory — never a
plaintext side file**; the canonical SQLCipher store is always the source of truth. **Honesty by
construction:** every signal carries method + caveat + n; **no composite trust/quality score**; every
merge/conflation is **reversible + provenance-tracked** ("merged by X"). The rule-based index is the
**trusted** layer; any recall/embedding/LLM output is a **separate, clearly-labelled, unreliable**
layer that never feeds it and never forecasts/grades/ranks-worth. Cross-time recall is sacred (no
recency bias). **×12 languages incl. RTL + CJK** (evaluate per-language, never one pooled average).
De-US-centring. Verify-before-trust (no fabricated endpoints/DOIs/checksums). Any dated/vendored
artifact (a segmenter, an embedding model, a lexeme table) needs a `configs/external_artifacts.yml`
entry + a `*_AS_OF` constant in the same commit.

---

## 3. Already shipped — DO NOT rebuild

Near-dup/coordination (`src/signals/near_dup.py`); BM25 ranking (FTS5's default `rank` IS bm25, so
relevance ordering is already on — the increment is BM25F column weighting); the "mmap is
plaintext-only under SQLCipher" finding + pooled connections (perf batch T1); the rings / families /
super-groups display layer; the engine report + self-test + growth curve + diagnostics exports; the
`readmodel`/`columnar` seam + the `ix_mention_date_keyword` covering index; the "Prune unused
keywords" + "Clean up keywords (re-index, then prune)" buttons.

---

## 4. The sequenced plan

Each **phase** is independently shippable; each **item** lists What / Where / Cost / Yield / Fit /
Acceptance / Gating. Phases 1–2 are *mechanical perf* (validated by timing + no-data-loss tests, NOT
retrieval metrics, so they do not block on the eval harness). Phases 4–5 are *quality* and **gate on
Phase 3**.

### Phase 1 — UNBLOCK THE REBUILD (the live pain; "hours-to-days → bounded")

- **1.1 Backend re-index JOB with a persisted cursor + task-manager visibility.** Move the re-index off
  the browser loop into a pausable background job that survives a tab close and **resumes from a
  persisted cursor** (don't restart from 0). *Where:* mirror `src/ingest/import_job.py`
  (`NewsletterImportManager` — worker thread + stop-event + on-disk cursor + `/api/jobs` surfacing);
  drive `reindex_all_batch`. *Cost:* medium. *Yield:* high (removes the "keep the tab open / restart
  from scratch" trap the maintainer hit). *Fit:* DB-writer job kind, single-writer gate, zero network.
  *Acceptance:* a full re-index runs to completion unattended, survives a restart, and is pausable from
  the task manager. *Gating:* none.
- **1.2 Keyword-only re-index mode.** `index_article` re-does keywords + when/where/who + sentiment; a
  *keyword cleanup* needs only the keywords. Add `index_article(..., scope="keywords")` (or a
  `reindex_keywords_batch`) that skips the date/place/entity + sentiment passes. *Cost:* low-medium.
  *Yield:* high (≈⅔ less work per article for the common cleanup). *Fit:* additive; default scope
  unchanged. *Acceptance:* keyword-only re-index produces identical keyword rows to a full re-index but
  leaves dates/places/entities/sentiment untouched (test). *Gating:* none.
- **1.3 Batched commits in the re-index/ingest.** Implement the documented
  `COLLECTOR_WRITER_BATCHING.md` path: `index_article(commit=False)` + batch a group into one
  transaction, with the proven `ingest_emails` per-item fallback on a batch failure (= NO data loss,
  keystone #1). Default `OO_COLLECT_COMMIT_BATCH=1` (byte-identical) so adoption is opt-in. *Cost:*
  medium. *Yield:* medium-high (cuts per-article fsync through the encrypted writer). *Fit:* counter
  deltas accumulate correctly within one txn by construction; the rollup watermark (2.2) stays
  append-compatible. *Acceptance:* a contention no-loss test (extend `tests/test_write_gate_dataloss.py`).
  *Gating:* none.
- **1.4 SQLCipher + FTS5 tuning pass.** Run FTS5 **`'optimize'`** after bulk loads (the
  `INSERT INTO ft(ft) VALUES('optimize')` segment-merge — DISTINCT from `PRAGMA optimize`; **verify
  whether it runs today**), tune `cache_size` (the main in-memory lever, since mmap is unavailable
  under the codec), keep one pooled connection (already done — confirm no churn), WAL. *Cost:* low.
  *Yield:* compounding read/ingest gains. *Fit:* in-store, no dependency. *Acceptance:* a benchmark
  shows query/ingest latency improvement; FTS5 `'optimize'` wired into the bulk-load path.
  *Gating:* none (makes 1.1–1.3 measurements clean).

### Phase 2 — END THE ANALYTICS FREEZE (the maintained rollups = the project's **5A-bis**)

> EXTENDS `SCALING_DERIVED_LAYER_1000X.md` (the seam, the covering index, the epoch machinery). The seam
> fn names are `top_terms`/`trending`/`trending_windows` (NOT the design-doc's `most_mentioned`/
> `rising_terms` — map them).

- **2.1 `keyword_daily` rollup (D2).** `keyword_daily(keyword_id, day, mentions, articles_on_day,
  PK(keyword_id, day))` where `day = keyword_mentions.observed_on`. Build by **streaming canonical
  mention rows through the app's SQLCipher connection INTO DuckDB and grouping THERE** (never a SQLite
  GROUP BY over the billions-row mention table — that IS the freeze; DuckDB can't read a SQLCipher
  file). Wire the `readmodel` delegators to serve from it when the persisted store is present + secure +
  epoch-matches, else fall back to the live query (basis flag `columnar@epoch N` vs `live`,
  slower-never-wrong). *Cost:* medium. *Yield:* high (per-keyword analytics: freeze → instant).
  *Fit:* counts + basis flag, no score; spans ALL history (never recency-biased). *Acceptance:* **parity
  proof IN-MEMORY now** — `keyword_daily` SUM == live `SUM(count)` for a sampled keyword set; windowed
  ranking == live. *Gating:* the persisted *perf win* is D1-gated (2.4); parity is provable in-memory
  today.
- **2.2 Incremental refresh + epoch full-rebuild gate (D3) — CORRECTNESS-CRITICAL.** Watermark on
  `keyword_mentions.id` + `oo_meta` epoch keys. **THE TRAP (grounded in this repo):** `index_article`
  does **delete-then-reinsert**, so the id-watermark MERGE-ADD is correct ONLY for APPEND (new articles
  → new higher ids). EVERY path that re-runs `index_article` over an EXISTING article —
  `reindex_all_batch`, `reindex_articles`, `reindex_imported_articles` (restore), the cleanup flow — AND
  `prune_orphan_keywords` MUST **bump the corpus epoch and force a FULL rebuild**, never an incremental
  MERGE, or the rollup double-counts (a fabricated number). Normal new-article ingest must NOT bump the
  epoch. *Acceptance:* incremental-after-batch == full-rebuild; a simulated re-index forces full
  (tests). *Gating:* 2.1.
- **2.3 `source_coverage` rollup (D4).** `(country, source_id, articles, mentions, first_day, last_day)`
  on the same watermark/epoch machinery — serves per-country coverage without scanning mentions.
  *Acceptance:* parity vs live per-country counts. *Gating:* 2.1/2.2.
- **2.4 VERIFY-then-maybe-UNBLOCK the persisted store (D1) — highest-leverage thread.** The IR report
  finds DuckDB ≥1.4 LTS ships **default authenticated AES-256-GCM** via `ATTACH … (ENCRYPTION_KEY)`.
  The project already uses that API; the only blocker is `secure_crypto_available()` (`columnar.py:90`)
  requiring `LOAD httpfs` (OpenSSL) because the OLDER mbedtls (CBC/CTR, non-authenticated) was "NOT
  securely encrypted." **VERIFY** whether 1.4's default is GCM (authenticated) — if yes, **relax
  `secure_crypto_available` to accept the native GCM backend for the DISPOSABLE store** (keep
  `encryption_gate`'s empirical proof: sentinel absent / no-key open fails / with-key open works),
  which **removes the per-OS OpenSSL-httpfs-binary packaging blocker** and lets the rollups (2.1–2.3) be
  PERSISTED = the real perf win across restarts. *Honesty kept:* disposable cache, never the source of
  truth, "not NIST-validated / header-plaintext" caveats stated. *Cost:* low (after verify). *Yield:*
  high (unblocks a stalled workstream). *Fit:* the `encryption_gate` is backend-agnostic — it proves the
  file is genuinely encrypted regardless of backend. *Acceptance:* the gate passes on the native-GCM
  store on all 3 OSes (the existing sqlcipher-smoke-style lane). *Gating:* the verify must come first;
  **never fabricate the capability** — if 1.4's bundled default isn't authenticated GCM, keep the
  in-memory fallback and leave D1 blocked on the binaries (do not relax the gate).

### Phase 3 — THE EVALUATION HARNESS (build EARLY / in parallel; gates Phases 4–5)

- **3.1 A frozen multilingual gold query set.** Pool the top-k from several variants (BM25,
  BM25+facets, hybrid), judge only the pool, **graded relevance 0/1/2**, tens-to-low-hundreds of queries
  spread across the 12 languages and the real axes (known-item / topic / cross-lingual / near-dup).
  *Cost:* low-medium (mostly one-time human judging). *Fit:* local, no telemetry, no user pool.
- **3.2 Metrics + tooling.** nDCG@10 / MRR@10 / Recall@k / P@k via `pytrec_eval` or `ranx` (a NEW
  optional `[eval]` extra; graceful-degrade if absent, like numpy/VADER), **per-language, n stated**.
  Single-assessor is enough for *comparisons* (Voorhees: assessor disagreement doesn't move system
  *rankings*). *Acceptance:* the harness reproduces a known metric on a fixture.
- **3.3 The conflation trade-off measured SEPARATELY.** For each conflation/lemmatization rule, report
  **recall gained AND precision lost** with n examples of newly-merged-correct vs newly-merged-wrong —
  never one number (respects no-composite-score). *Acceptance:* the report renders both deltas + the
  example sets.
- **3.4 A regression gate.** Freeze the gold set; run the metrics on every index/conflation change;
  fail the build on a regression beyond a threshold; store the per-language breakdown. *Where:* extend
  the existing self-test harness with RETRIEVAL metrics. *Gating:* none (it gates the others).

### Phase 4 — KEYWORD QUALITY (the conflation roadmap; each item gates on Phase 3)

- **4.1 Run re-index + prune on the LIVE corpus — OPERATIONAL.** Now fast after Phase 1; flushes the
  stale digit/code backlog + zero-mention orphans the `§2.5/§2.6` filters already drop. Measure the drop
  via the engine report's `mention_distribution`. *(Maintainer step; not in-session code.)*
- **4.2 `reconcile_keyword_language`.** A background pass setting `Keyword.language` to the
  **signature-majority** (mirror `reconcile_keyword_counters` `store.py:558`), OR make grouping/
  lemmatization read the signature (`queries._ring_lang_of`). Route the "?" bucket through the English
  stoplist + a boilerplate filter (email/click/newsletter…). *Cost:* low-medium. *Yield:* high on the
  head (fixes the 16% / 40%-of-head mismatch). *Fit:* additive; the stored tag becomes truthful,
  reversible. *Acceptance:* a keyword first-written in a mis-detected language is re-languaged to its
  signature majority; "?" boilerplate is filtered. *Gating:* prereq for 4.3 (lemmatizing on a wrong
  language applies the wrong rules).
- **4.3 Lemmatization (simplemma) at the DISPLAY layer.** EXTEND `families.canonical_key`
  (`families.py:104`) with a lemma step — **NOT `_normalize()`** (the live BaselineExtractor keys on the
  de-elided lowercased token, and conflation already lives in `families`, reversible). Add a
  `conflated_by` provenance + a **visible "merged by lemma (simplemma, lang=…)" label** (a lemma merge
  is less transparent than a regex — provenance is mandatory). Ship the **mislemma denylist** (goods,
  media, wrong, downing, saw, … — evidence-grown like `_PLURAL_DENYLIST`/`_CODE_TOKEN_KEEP`),
  `degree_policy: keep_separate`, lemmatize per the (now-correct, 4.2) signature-majority language.
  simplemma is pure-Python; gate it like VADER (optional extra; absent → no-op). *Cost:* medium.
  *Yield:* medium head (≈20.7% of en single-token terms share a lemma), high tail (gated on 4.2). *Fit:*
  display-time + reversible + provenance + denylist = honesty-clean. *Acceptance:* the eval harness (3.3)
  shows recall-gain > precision-loss; the denylist cases stay split; verbs OFF for entity names.
  *Gating:* Phase 3 + 4.2.
- **4.4 Multilingual extraction.** **th is URGENT** (no inter-word spaces → mid-word fragments): add a
  Thai segmenter (pythainlp / ICU) or stop minting th keywords. **zh is degraded-not-garbage** (usable;
  compounds unsplit) → a jieba/ICU segmenter is lower priority. Add stoplists for the `no_stoplist`
  tail. Each bundled segmenter is a registry-tracked artifact + graceful-degrade. *(Overlaps the
  existing zh/ja-segmentation design-doc track — reconcile, don't duplicate.)* *Gating:* Phase 3 for the
  quality measurement.

### Phase 5 — SERVING QUALITY (mostly independent; the recall layer gates on Phase 3)

- **5.1 BM25F + facets.** Add per-column BM25F weights (title vs body) and entity / temporal /
  geographic facets co-equal with the text query in the main search (BM25 default is likely already on;
  this is the increment + the facet UI). *Cost:* low-medium. *Yield:* large, near-free, explainable.
  *Fit:* ranking points at real tokens; facets are exact. *Gating:* none (proven by 3.x optionally).
- **5.2 Static-embedding hybrid recall layer (the headline outside-the-box item).** model2vec/potion
  (numpy-only, **no torch**) → vectors as BLOBs in the encrypted file via **sqlite-vec** → fuse with
  BM25 via **RRF** (k≈60). It is a **labelled, disposable, in-core recall layer** with a provenance-first
  result card ("lexical match" vs "semantic neighbour (model X, cosine c)"); **never feeds the trusted
  index.** NEW optional extra + registry entry (the embedding model is a dated artifact). *Cost:* medium.
  *Yield:* meaningful recall for vocabulary-mismatch + cross-lingual leads. *Fit:* constraint-clean
  (static = no torch; in the encrypted store; reversible; labelled). *Acceptance:* **PILOT gated on
  Phase 3 — prove per-language recall-gain** (the 80–92% MTEB figure is English-leaning; multilingual
  payoff is uncertain). *Gating:* Phase 3. *Honesty:* static embeddings are context-free (conflate
  polysemy, miss negation) — label every dense hit approximate. Scale note: brute-force sqlite-vec is
  fine to a few hundred-k vectors; at 100× go passage-level + binary quantization or wait for ANN.
- **5.3 (optional, later) Ollama-tier BGE-M3 contextual / cross-lingual embeddings** — the perception
  tier; the model is a schema commitment (re-embed on change). Same sqlite-vec + RRF plumbing.
- **5.4 (optional, later) Corpus-driven query expansion / did-you-mean** — suggest family/ring/high-PMI
  members + static-NN neighbours as *optional* expansions (never silently applied); did-you-mean via a
  trigram-tokenizer FTS over the own vocabulary (no model). Reversible, labelled.

### Phase 6 — ENTITY LAYER (strategic, last)

- **6.1 OpenTapioca entity-linking → Wikidata QIDs.** Net-new (entities are acronym-only today); key
  entities on the QID so Trump / Donald Trump / President Donald Trump / the Cyrillic form collapse to
  one canonical entity; `families` containment becomes the fallback. After confirming the extractor + the
  eval harness; needs a Wikidata index (operational / networked). *Gating:* Phases 3–4.
- **6.2 Seed baseline tags from a dated Wikidata P31 (CC0) snapshot** (the conflation P6); route the
  lemma proposals (4.3) + the language-mismatch queue (4.2) into the existing human-review loop, not a
  parallel store. *(Networked-machine generation; registry-tracked.)*

---

## 5. Verify-before-build (do NOT wire blindly — this project has been burned by fabricated capabilities)

- **DuckDB ≥1.4 default = authenticated AES-256-GCM** (the 2.4 D1 unblock) — confirm before relaxing
  `secure_crypto_available`. If unconfirmed, keep in-memory + the httpfs-binary path.
- **Static-embedding multilingual quality PER-LANGUAGE** — the 80–92% MTEB is English-leaning; pilot +
  eval (Phase 3) before committing the subsystem.
- **Licenses (read each before bundling):** simplemma code MIT + per-language *data* licenses; model2vec/
  potion, sqlite-vec, datasketch, pytrec_eval/ranx, BGE-M3, OpenTapioca. **CC0-first** (Wikidata
  Lexemes); **Wiktextract is CC-BY-SA = a separate maintainer ruling**; **SPLADE official weights are
  CC-NonCommercial → never bundle** (also needs torch + has a multilingual gap → out).
- The research files' `[FLAG]` items (NEWS-COPY venue; the ranx ECIR-2022 citation) — verify if cited
  formally.

## 6. Blocked / operational (maintainer or networked machine — not in-session code)

Running cleanup (re-index + prune) + `reconcile_keyword_language` + baseline-tag backfill on the LIVE
corpus; Wikidata Lexeme form→lemma table + ring generation (Wikidata is blocked in CI); a bundled
segmenter / embedding model / OpenTapioca Wikidata index (networked, license-checked, registry-tracked);
the per-OS httpfs OpenSSL binaries — **only if** the DuckDB-1.4-GCM verify (2.4) fails.

## 7. One-line sequencing

Unblock the rebuild (P1) → maintain rollups + **verify-DuckDB-encryption to unblock the persisted
store** (P2) → stand up the eval harness in parallel (P3) → keyword quality gated on eval (P4) → serving
BM25F/facets + the labelled static-embedding recall layer gated on eval (P5) → entity QIDs (P6). Keep
the rule-based index **trusted**; everything new is a **labelled, reversible, disposable** augmentation.
