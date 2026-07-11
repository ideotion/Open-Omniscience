# Autonomous build session — implement the keyword-engine optimization IN FULL

> **This file is the verbatim build brief for an absolute, fully autonomous session.** It is your
> reset-proof durable memory: after ANY context reset, re-read **this file** + **`CLAUDE.md` (in
> full)** + **`docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md`** (THE blueprint) + the three
> reports under **`docs/research/keywords/`**. If anything here ever conflicts with `CLAUDE.md`,
> **`CLAUDE.md` wins** (the single authoritative ledger). This brief is the OPERATING MANUAL; the
> strategy doc is the per-item spec — execute the strategy, run it the way this brief says.

You are running an **absolute, fully autonomous, multi-step build session**. **Goal: implement the
keyword-engine optimization strategy END TO END.** Work in **complete autonomy — never stop to ask.**
At any genuine fork pick the most honest, conservative option, **record it in the `CLAUDE.md` ledger
the SAME turn**, and keep going (the maintainer's standing "don't ask me anything / make every
decision yourself" ruling). Reserve a question ONLY for a genuinely NEW ethics/irreversible/
outward-facing surface not covered here, in `CLAUDE.md`, or in the strategy doc.

---

## 0. First moves — every time your context resets

1. **Read `CLAUDE.md` IN FULL.** THE PROTOCOL is mandatory: record every new ruling and every shipped
   step IN `CLAUDE.md` the SAME turn it happens — that is how your work survives context
   summarization. If the maintainer ever repeats feedback, that is a ledger failure: fix the gap AND
   the ledger.
2. **Read `docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md`** — the blueprint. Its §4 has every
   item's What / Where (file:line) / Cost / Yield / Fit / Acceptance / Gating. §1 lists the
   code-grounded facts; §3 lists what is ALREADY SHIPPED (do not rebuild); §5/§6 the
   verify-before-build + operational items.
3. **Have an Explore agent summarize** (don't re-read end-to-end) the three reports under
   `docs/research/keywords/` and the design docs the strategy EXTENDS:
   `docs/design/SCALING_DERIVED_LAYER_1000X.md`, `docs/design/COLLECTOR_WRITER_BATCHING.md`,
   `docs/design/PERSISTED_DUCKDB_HTTPFS.md`. **Extend those, never recreate.**
4. **Re-derive where you are:** `git log --oneline -20`, `git branch -a`, list open PRs, re-read the
   latest ledger entries. **Never redo a merged/shipped step.**
5. **EXPLORE THE CODE FIRST for every step and build only the gap** (the Desk lesson). The seam
   already exists (`src/analytics/readmodel.py`, `src/analytics/columnar.py`, the
   `ix_mention_date_keyword` covering index); near-dup, BM25-default ranking, the engine report /
   self-test / growth diagnostics are shipped. Verify each anchor before you touch it.
6. **Maintain a task list** (TaskCreate/TaskUpdate) of the phase queue as a within-window aid — but the
   DURABLE memory is the `CLAUDE.md` ledger, so write there too.

## 1. Working mode

- One **step** = one self-contained, additive change = one **draft PR** (or one well-scoped commit on
  the single branch under the harness fallback, §2). Small + single-purpose; many small PRs over one
  big one.
- **NEVER fabricate** data, scores, checksums, endpoints, DOIs, benchmarks, library capabilities, or
  test outcomes — honesty by construction is the FIRST non-negotiable. When a step's core needs the
  live corpus / a networked or large artifact / a capability you can't confirm: build the honest part,
  ship a clearly-flagged **EMPTY SEAM** (an inert disabled control, a stub returning "unavailable" +
  the reason, a blank pin/model slot), write a one-line ledger note, and move on.
- **Verify-before-trust** the research: the `[FLAG]`/`(verify)` items, the **DuckDB-1.4 GCM claim**,
  and **per-language embedding quality** MUST be empirically proven before you wire or rely on them.
- **Consolidation/removal NEVER loses a capability** (the Desk lesson): keep an absorption guard/test;
  make removed things unreachable rather than deleted where the project pattern calls for it.
- **Report faithfully:** a failing test → say so with output; a partial step → which half shipped,
  which is deferred, and why.

## 2. PR / branch model — stack and keep moving

- **Step 1**: branch off a freshly-fetched `origin/0.09`; push; open a **draft** PR → `0.09`.
- **Step N (N>1)**: branch off step N-1's tip; push; open a **draft** PR → `0.09`.
- After each push, **verify CI is green, then start the next step on top.** A broken step poisons
  everything stacked above it — fix red on that branch first.
- As bottoms merge, `git fetch origin 0.09` and **rebase the remaining stack onto fresh `0.09`**
  (it goes stale within minutes — fetch immediately before you branch or rebase).
- Other parallel sessions also merge into `0.09`; resolve conflicts in the hot shared files
  (`CLAUDE.md` top, `src/static/locales/*.json`) **ADDITIVELY — keep BOTH sides' entries/keys.**
- Branch names `oo/kw-<NN>-<slug>`. All PRs **draft**; never self-merge; the maintainer merges.
- **HARNESS FALLBACK:** if your harness locks development to ONE working branch, that constraint WINS —
  stack well-scoped COMMITS on that branch under ONE draft PR to `0.09`; each §5 step is still verified
  end-to-end before the next begins.

## 3. Verification gate — what "done" means

The container is **Python 3.11 with NO project deps**; the repo needs **3.13**, so full `pytest` runs
in **CI, not locally**. Your local gate:

- **`python -m py_compile`** every changed file. For new pure logic write a tiny standalone repro
  (in-memory SQLite / stubbed inputs) and PROVE the behaviour before you trust it.
- **`python3 -m mypy <changed.py>`** on every Python change — mypy IS pip-installable in the sandbox and
  type-checks via the real-import closure even without project deps. The ratchet (`MYPY_BASELINE`; add
  **ZERO** new errors) is a **BLOCKING** gate; `py_compile` + ruff F/B alone do NOT catch type drift.
- **CI `test`-lane order, all BLOCKING unless noted:** `ruff check --select=F,B --extend-ignore=B008` →
  ruff style (advisory) → **`i18n_report.py --min 100`** → **migration-drift** (`alembic upgrade head &&
  alembic check`) → **`pytest`** → **mypy ratchet** → bandit (medium+) → pip-audit. A green pytest still
  fails if a locale drops below 100% or a model drifts from the Alembic baseline. Gotcha: `py_compile`
  passes on an unused import / a name used only in `except`, but **ruff's F-lane fails on it** —
  re-check every import you add.
- **Non-`test` lanes gate too:** `core-only` installs WITHOUT the `[analysis]` extra, so any NEW
  optional dep (**simplemma, model2vec, sqlite-vec, duckdb, py3langid, a segmenter, pytrec_eval/ranx**)
  MUST import lazily and **degrade loudly** ("unavailable" + the reason, never a crash — mirror
  `parity_available()` / `secure_crypto_available()`; analysis-only tests `importorskip`). `crypto` +
  `sqlcipher-smoke` (3-OS, **BLOCKING**) exercise encryption — anything added to the columnar/encrypted
  store must pass the empirical encryption gate, NEVER a plaintext derived file. `portability`
  (observation-only) runs on Windows/macOS — no OS-specific paths, use `src/paths.py`.
- **Always add/extend a real `pytest` test** (CI runs it) **and** a guard in
  `tests/test_repo_invariants.py` where the pattern calls for it. **Never assert positive facts against
  the shared `src.api.main.app` singleton's `.routes`** — anchor route guards to each router's own
  `router.routes` + the `include_router` wiring in `_wiring.py`.
- **Any new DB column → a migration + a boot self-heal** (`ensure_*_columns`; the live DB is not
  auto-alembic'd); keep a single Alembic head.
- **Any externally-sourced/dated/vendored artifact** (a segmenter, an embedding model, a lexeme table,
  an httpfs binary) → a `configs/external_artifacts.yml` entry + a `*_AS_OF` constant **in the same
  commit** (the protocol-guard test fails otherwise).
- **Frontend is browser-unverified by design (fork-3):** still build it — conservatively, with
  `node --check` + an invariant test + defensive empty/error states — and flag "browser-unverified,
  needs click-through." Key new chrome strings through `t()` (English fallback ok; key ×12 when you can,
  byte-exact against `--audit-chrome`; flag non-en AI-drafted).
- **DATA-LOSS DISCIPLINE (keystone #1):** Phase 1 touches the single-writer ingest/re-index hot path —
  every change there ships with a **no-loss test** (extend `tests/test_write_gate_dataloss.py`-style
  contention) BEFORE it is "done." A blind refactor of the writer is forbidden.
- A step is **DONE** only when: wired end-to-end, tests + node-check pass, **the ledger entry is
  written**, and CI is green. Only then start the next.

## 4. Subagent orchestration — beat your own context limits

Main thread = DECISIONS, EDITS, VERIFICATION; delegate the reading and the fan-out; keep conclusions,
not file dumps. Spawn a named fleet:

- **Scout** (Explore) before EVERY step — map what it touches + what already exists + the precise
  residual gap as a checklist (exact files + line ranges + endpoints/functions/tests + conventions).
  One per step.
- **Planner** for any multi-file item (the `keyword_daily` rollup + incremental MERGE, the eval
  harness, the static-embedding layer) — a file-by-file change map + a test plan FIRST.
- **Builder** for a single fully-specified self-contained slice + its acceptance test — integrate and
  verify what it returns; **never merge a Builder's diff unread; you own correctness.**
- **Verifier** (a SECOND agent) for the correctness-critical MATH — **independently re-derive the
  expected result and diff it**: the `keyword_daily` rollup parity + the double-count trap, the
  DuckDB-encryption gate, the conflation recall/precision deltas.
- **Auditor/Red-team** before finalizing each step — `/code-review` or a reviewer prompted to REFUTE
  the diff (correctness bugs, integration gaps, a fabricated number, a hidden caveat, a silent score,
  recency bias, a de-US slant). **Hand-verify every finding** (subagents can be confidently wrong —
  the 06-audit false-positive lesson).
- **Heaviest verification** (a `Workflow`, if opted in) on the two highest-fabrication-risk slices:
  **the `keyword_daily` incremental-refresh correctness** (the `index_article` delete-then-reinsert
  double-count trap) and **the DuckDB-1.4 GCM encryption claim** (must be EMPIRICALLY proven via the
  `encryption_gate`, never assumed). A subtle bug in either fabricates a NUMBER or a security claim.

## 5. Scope & order — execute the strategy's phases, with a build-class tag per item

> Read the per-item spec in `KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md §4`. Below is the **execution
> order + the build class**: **[BUILDABLE]** end-to-end in sandbox/CI · **[VERIFY-FIRST]** prove the
> capability before wiring · **[SEAM]** blocked on data/binaries/browser → ship the honest seam +
> flag · **[OPERATIONAL]** maintainer-only (the live corpus). Build top-down; each item is
> independently shippable.

### Phase 1 — Unblock the rebuild (the live pain) — all **[BUILDABLE]**
- **1.1 Backend re-index JOB** (persisted cursor, task-manager-visible, pausable) — mirror
  `src/ingest/import_job.py` (`NewsletterImportManager`); drive `reindex_all_batch`. *Acceptance:* runs
  unattended, survives a restart, pausable; **no-loss test**.
- **1.2 Keyword-only re-index mode** — `index_article(..., scope="keywords")` skipping when/where/who +
  sentiment. *Acceptance:* identical keyword rows to a full re-index; dates/places/entities/sentiment
  untouched (test).
- **1.3 Batched commits** — `index_article(commit=False)` + the proven `ingest_emails` per-item
  fallback; `OO_COLLECT_COMMIT_BATCH=1` default = byte-identical. *Acceptance:* contention no-loss test.
- **1.4 FTS5 `'optimize'` + cache_size tuning** — verify whether FTS5 `'optimize'` (distinct from
  `PRAGMA optimize`) runs today; wire it after bulk loads. *Acceptance:* a benchmark shows improvement.

### Phase 2 — Rollups + the DuckDB-encryption unblock
- **2.1 `keyword_daily` rollup (D2)** — **[BUILDABLE]** parity in-memory now. Build by streaming
  SQLCipher mentions → DuckDB → group THERE; serve `top_terms`/`trending` from it when
  present+secure+epoch-matches, else the live query (basis flag). *Acceptance:* **parity proven
  in-memory** (rollup SUM == live `SUM(count)` for a sampled set; windowed ranking == live).
- **2.2 incremental refresh + epoch full-rebuild gate (D3)** — **[BUILDABLE]**, CORRECTNESS-CRITICAL.
  **THE TRAP:** `index_article` does delete-then-reinsert, so the id-watermark MERGE-ADD is correct
  only for APPEND. EVERY re-index/prune/restore path MUST bump the epoch → FULL rebuild; normal ingest
  must NOT. *Acceptance:* incremental-after-batch == full-rebuild; a simulated re-index forces full →
  Verifier + heavy review.
- **2.3 `source_coverage` rollup (D4)** — **[BUILDABLE]**. *Acceptance:* per-country parity vs live.
- **2.4 DuckDB-1.4 GCM verify → maybe relax the gate (D1)** — **[VERIFY-FIRST]**, highest-leverage.
  `pip install duckdb`; PROVE whether ≥1.4's default `ATTACH … (ENCRYPTION_KEY)` is authenticated
  AES-256-GCM by running the existing `encryption_gate` (`columnar.py:111`) against a native-GCM store.
  **IF proven** → relax `secure_crypto_available` (`columnar.py:90`) to accept the native GCM backend
  for the DISPOSABLE store (keep `encryption_gate` as the empirical proof) → persisted rollups = the
  real perf win; honesty caveats kept (not-NIST-validated, disposable, never the source of truth).
  **IF NOT proven** → keep the in-memory fallback + leave D1 on the httpfs-binary path; **do NOT relax
  the gate, do NOT fabricate the capability.** *Acceptance:* the gate passes on the native-GCM store on
  all 3 OSes (the sqlcipher-smoke-style lane) OR a ledger note records that GCM was not confirmable.

### Phase 3 — IR eval harness — all **[BUILDABLE]** (build EARLY / in parallel; gates Phases 4–5)
- **3.1** a frozen multilingual gold query set (pooled, graded 0/1/2, per-language, across axes:
  known-item / topic / cross-lingual / near-dup). **3.2** `pytrec_eval` or `ranx` (NEW optional
  `[eval]` extra, graceful-degrade) → nDCG@10 / MRR@10 / Recall@k per-language, **n stated**.
  **3.3** conflation **recall-gain-vs-precision-loss reported SEPARATELY with n** (no composite score).
  **3.4** a regression gate extending the self-test harness with RETRIEVAL metrics. *Acceptance:*
  reproduces a known metric on a fixture; the gate reddens on a seeded regression.
- *Note:* Phases 1–2 are validated by **timing + correctness**, NOT retrieval metrics, so they do not
  block on this; Phases 4–5 DO.

### Phase 4 — Keyword quality (each quality item gates on Phase 3)
- **4.1 [OPERATIONAL — maintainer-only]** run re-index + prune on the LIVE corpus (the tools exist; the
  session can't run them on the maintainer's data) — note it in the ledger, do NOT fake a result.
- **4.2 `reconcile_keyword_language`** — **[BUILDABLE]**. A background pass setting `Keyword.language`
  to the signature-majority (mirror `reconcile_keyword_counters` `store.py:558`), + route the "?" bucket
  through the English stoplist + a boilerplate filter. *Acceptance:* a mis-detected keyword is
  re-languaged to its signature; "?" boilerplate filtered. **Prereq for 4.3.**
- **4.3 simplemma lemmatization** — **[BUILDABLE]** (lib is pure-Python; gate like VADER). At the
  DISPLAY layer — **EXTEND `families.canonical_key` (`:104`), NOT `_normalize`**; reversible;
  `conflated_by` provenance + a **visible "merged by lemma" label**; the evidence-grown **mislemma
  denylist** (goods/media/wrong/downing/saw…); `degree_policy: keep_separate`; per the (4.2) signature
  language; verbs OFF for entity names. *Acceptance:* the eval harness (3.3) shows recall-gain >
  precision-loss; denylist cases stay split. **Gated on Phase 3 + 4.2.**
- **4.4 multilingual extraction** — **th URGENT [SEAM if the segmenter DATA needs a networked fetch,
  else BUILDABLE]**: a Thai segmenter (pythainlp/ICU) or stop minting `th`; **zh** compound split is
  lower priority (usable today); add stoplists for the `no_stoplist` tail. Reconcile with the existing
  zh/ja-segmentation design-doc track (don't duplicate); a bundled segmenter = a registry artifact +
  graceful-degrade.

### Phase 5 — Serving quality (the recall layer gates on Phase 3)
- **5.1 BM25F + facets** — **[BUILDABLE]**. Per-column BM25F weights (title vs body) + entity /
  temporal / geographic facets co-equal with the text query (BM25 default is already on; this is the
  increment + the facet UI). *Acceptance:* ranking + facets work and stay explainable.
- **5.2 static-embedding hybrid recall layer** — **[BUILDABLE; SEAM for the model artifact]**.
  model2vec/potion (numpy-only, NO torch) → vectors as BLOBs in the encrypted file via **sqlite-vec** →
  fuse with BM25 via **RRF**. A labelled, disposable, in-core recall layer with a provenance-first
  result card; **never feeds the trusted index.** NEW optional extra + registry entry; if the embedding
  MODEL needs a networked fetch, ship the wiring + a flagged empty model slot. **PILOT gated on Phase 3
  — prove per-language recall-gain** (the 80–92% MTEB figure is English-leaning). Honesty: static =
  context-free, label every dense hit approximate; scale note (passage-level + binary quantization at
  100×).
- **5.3 [LATER/OPTIONAL]** Ollama-tier BGE-M3 contextual/cross-lingual embeddings (the perception tier;
  the model is a schema commitment — re-embed on change). **5.4 [LATER/OPTIONAL]** corpus-driven query
  expansion / did-you-mean (family/ring/PMI members + trigram FTS over the own vocabulary; opt-in,
  reversible).

### Phase 6 — Entity layer — **[SEAM/STRATEGIC, last]**
- **6.1 OpenTapioca entity → Wikidata QID** — net-new (entities are acronym-only today); needs a
  Wikidata index (networked, large) → build the seam + the design note, blocked on the data.
  **6.2** seed baseline tags from a dated Wikidata P31 (CC0) snapshot (networked generation;
  registry-tracked) → route lemma proposals (4.3) + the language-mismatch queue (4.2) into the existing
  human-review loop.

## 6. The per-step loop

1. **Scope** (Scout → files/conventions/tests + what already exists).
2. **Branch** off the previous step's tip (or fresh `0.09` for step 1; or commit on the single branch
   under the harness fallback).
3. **Implement** — small, additive, matching surrounding code; migration + boot self-heal for a new
   column; consolidation absorption-gated; never weaken a non-negotiable.
4. **Verify** — `py_compile` + ruff F,B + **mypy(≤ baseline)** / `node --check` / a standalone repro;
   add the pytest test + the invariant guard; i18n 100%; **spawn a review agent and hand-verify its
   findings.**
5. **Ledger** — write the shipped entry (or queue update) in `CLAUDE.md` the SAME turn. Extend
   `tests/test_repo_invariants.py::test_ui_invariants` when you add a critical UI invariant.
6. **Commit** (clear message; **NEVER** put any model identifier in any repo artifact; **never** use
   backticks inside a `git commit -m` heredoc), **push**, **open the draft PR**.
7. **Confirm CI green**, then start the next step on top.

## 7. Honesty non-negotiables (every step)

Offline / loopback-only. **No torch/onnx/transformers in core** (Ollama is the only heavy-ML tier).
Derived stores are **disposable + encrypted-at-rest OR in-memory — NEVER a plaintext side file**; the
canonical SQLCipher store is always the source of truth. **No fabricated data/scores/security/
endpoints/checksums/capabilities.** **No composite trust/quality score**; every signal carries method +
caveat + n. Every merge/conflation **reversible + provenance-tracked + a visible label**. The
rule-based index is the **TRUSTED** layer; embeddings / near-dup / the LLM are a **separate, clearly-
labelled, UNRELIABLE recall/perception layer that NEVER feeds the trusted index** and never
forecasts/grades/ranks-worth. **Cross-time recall is sacred** (no recency bias; the rollups span ALL
history). **×12 languages incl. RTL + CJK** (evaluate per-language, never one pooled average).
De-US-centring. **SPLADE is OUT** (CC-NonCommercial weights + torch + multilingual gap — do not add
it). When blocked → a clearly-flagged **EMPTY SEAM**, never a fabrication. Verify-before-build the
DuckDB-GCM claim, per-language embedding quality, and every bundled library's license (CC0-first;
Wiktextract CC-BY-SA is a separate maintainer ruling).

## 8. When a step can't be finished autonomously

If its core needs the **live corpus** (4.1), a **networked/large artifact** (a segmenter / embedding
model / OpenTapioca Wikidata index — 4.4 / 5.2 / 6.x), or a **capability you must VERIFY and cannot**
(2.4 if DuckDB-GCM isn't confirmable): build the honest part (the seam + the wiring + the design note),
write a one-line ledger note with the reason, and **move to the next step.** Don't stall; don't fake
it. The plan is deep on purpose — **P1, P2.1–2.3, P3, P4.2, P4.3, P5.1 are ALL fully buildable +
verifiable in sandbox/CI**, so there is always honest, shippable work.

## 9. Definition of "completely implemented"

The session is done when:
- every **[BUILDABLE]** item is shipped, CI-green, and ledgered;
- every **[VERIFY-FIRST]** item is either proven-and-wired or honestly-deferred with the reason in the
  ledger;
- every **[SEAM]** / **[OPERATIONAL]** item is shipped as a flagged seam + a ledger note naming exactly
  what the maintainer / networked step must do to finish it;
- each row of `KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md §4` is marked in the ledger as **shipped** /
  **verified-deferred** / **seam-only** / **operational**, so a context reset can tell at a glance what
  remains.

Keep the rule-based index **trusted**; everything new is a **labelled, reversible, disposable**
augmentation. Update `docs/archive/releases/RELEASE_0.1_RC_GATE.md` rows you close.

---

### Session execution note (fill in at session start)

Record here, the same turn: the harness constraint you actually run under (single-branch fallback vs
stacked PRs), the branch name, the DuckDB-1.4-GCM verify outcome (the D1 unblock hinges on it), and any
conservative default you adopt at a fork — so a context reset re-reads them. The maintainer merges on
their own schedule; each §5 step is verified end-to-end before the next begins.
