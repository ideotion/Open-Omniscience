# Autonomous build session — work the Open Omniscience to-do list (2026-06-26)

> **This file is the verbatim build brief for the next autonomous session.** It is your
> reset-proof durable memory: after ANY context reset, re-read this file plus `CLAUDE.md` and
> `docs/FUTURE_DEVELOPMENTS.md` → the **"CONSOLIDATED TO-DO"** and the
> **"AUTONOMOUS BRIEF 2026-06-24 — UNRESOLVED & PARTIAL"** sections. If anything here ever
> conflicts with `CLAUDE.md`, **`CLAUDE.md` wins** (it is the single authoritative ledger).

You are running an **autonomous, multi-step build session** on the Open Omniscience repo
(default branch `0.09`; this session ships toward release **0.0.9 → V0.1**). Work through the
project to-do list, shipping each step as its own well-scoped change, and verify each is fully
integrated before the next. Work in **complete autonomy** — never stop to ask. At any genuine
fork pick the most honest, conservative option, **record it in the `CLAUDE.md` ledger the same
turn**, and keep going (the maintainer's standing "don't ask me anything / make every decision
yourself" ruling). Reserve a question ONLY for a genuinely new ethics/irreversible/outward-facing
surface not covered here or in `CLAUDE.md`.

**This brief is self-contained.** Everything else you need you reconstruct from the repo
(`CLAUDE.md` + the to-do + the design docs + the code itself).

---

## 0. First moves — every time your context resets

1. **Read `CLAUDE.md` IN FULL.** It is the single ledger of every maintainer ruling and your
   long-term memory. **THE PROTOCOL is mandatory:** record every new ruling and every shipped
   step IN `CLAUDE.md` the SAME turn it happens — that is how your work survives context
   summarization. If the maintainer ever repeats feedback, that is a ledger failure: fix the
   gap AND the ledger.
2. **Read `docs/FUTURE_DEVELOPMENTS.md`** → the **"CONSOLIDATED TO-DO"** checklist and the
   **"AUTONOMOUS BRIEF 2026-06-24 — UNRESOLVED & PARTIAL (audited 2026-06-25)"** section. That
   audited list IS the remaining work; the "FIELD-TEST REMARKS 2026-06-24" section above it
   carries each remark's full context.
3. **Read the active design docs you will build from** (don't reread end-to-end — have an
   Explore agent summarize them): `docs/design/SCALING_DERIVED_LAYER_1000X.md`,
   `docs/design/PERSISTED_DUCKDB_HTTPFS.md`, `docs/design/COLLECTOR_WRITER_BATCHING.md`,
   `docs/design/UNIFIED_IMPORT_EXPORT.md`, and the **statistical-data + ooViz** design in
   `docs/FUTURE_DEVELOPMENTS.md` → "Statistical-data ingestion + diversified honest
   visualization" (its verbatim research artifacts live under `docs/research/`).
4. **Re-derive where you are**: `git log --oneline -20`, `git branch -a`, list open PRs,
   re-read your latest ledger entries. **Never redo a merged/shipped step.**
5. **MOST OF THE 2026-06-24 BRIEF IS ALREADY SHIPPED — Explore the current code FIRST and build
   only the missing piece (the Desk lesson: never rebuild what exists).** Already done, do NOT
   redo (verified merged into `0.09` as of 2026-06-25):
   - Home "Loading the briefing…" hang + progress bar (#455); the per-corpus endpoint caching +
     the **statement-deadline guard** on associations/graph/framing (#458 + the 2026-06-24
     autonomous session).
   - Search **Enter → new analysis tab** (`openAnalysisInNewTab` + the `?analyze=` boot
     deep-link).
   - **Library world map** (per-country choropleth + `ooDonut` for the uncountried-by-language
     bucket) **and** the **Library central dashboard** (`GET /api/library/overview`).
   - Settings: intro-box removal · Appearance+GUIs fused into **"Graphics"** · sidebar
     click-empty-space toggle · opaque status bar (`.chrome` bg fix, 2026-06-25).
   - AI prompt UI re-translates on language switch + single-article summarize/translate emit in
     the UI language.
   - The **copypasta** manipulation card (#6 of 9) + the **gov-newsletter keyword filter**.
   - The data-architecture **seam already exists**: the honesty envelope (`src/analytics/envelope.py`),
     denormalised keyword counters, `src/analytics/readmodel.py` (ALL seven delegators —
     `top_terms`·`trending`·`trending_windows`·`associations`·`layered_graph`·`article_graph`·
     `source_country_counts` — already forward to v1), `src/analytics/columnar.py` (`connect` ·
     `secure_crypto_available` · `encryption_gate` · `store_format_marker`+`marker_compatible` ·
     `build_keyword_read_model`+`top_terms_raw` over the in-memory `keyword_agg` table + the
     `oo_meta` marker), and the `ix_mention_date_keyword` covering index. There is **NO
     `keyword_daily` / `source_coverage` table yet** (that IS the 5A-bis work). **5A-bis EXTENDS
     these — extend, never recreate;** the seam exposes `top_terms`/`trending`, NOT the design-doc
     names `most_mentioned`/`rising_terms` (map them).
   - The 5C **design docs already exist** (LLM-perception eval · Tor · voice · Open Commons
     Mirror) and the **5B httpfs build recipe** — extend/update them, don't re-author.
6. **Maintain a task list** (TaskCreate/TaskUpdate) of the step queue as a within-window
   progress aid — but the DURABLE memory is the `CLAUDE.md` ledger, so write there too.

## 1. Working mode

- One **step** = one self-contained, additive change = one **draft PR** (or one well-scoped
  commit if your harness locks you to a single branch — see §2). Keep steps small and
  single-purpose; prefer many small PRs over one big one.
- **Never fabricate** data, results, scores, checksums, endpoints, DOIs, or test outcomes — honesty
  by construction is the FIRST non-negotiable. If something needs data/binaries/a live corpus you
  don't have, build the honest part, ship a clearly-flagged **EMPTY SEAM** (a blank pin/checksum
  table, an inert disabled control, a stub returning "unavailable" with the reason), write a
  one-line ledger note, and move on.
- **Verify-before-trust the research files.** `docs/research/` rows (producer endpoints, source
  catalogues, dataset URLs) are LEADS, not facts — this project has been burned by fabricated
  endpoints before. Only live-fetch the explicitly verified subset; treat the rest as a metadata
  directory at scaffold confidence, clearly labelled.
- **Consolidation/removal steps must NEVER lose a capability** (the Desk lesson). When you fuse
  or move a surface (unified import/export, a Settings reorg), keep an absorption guard/test
  proving nothing is lost, and make removed things UNREACHABLE rather than deleted where the
  project pattern calls for it.
- Report faithfully: failing test → say so with output; partial step → say which half shipped,
  which is deferred, and why.

## 2. PR / branch model — stack and keep moving

The maintainer merges on their own schedule, so **do not wait for a merge to start the next
step**:

- **Step 1**: branch off a freshly-fetched `origin/0.09`; push; open a **draft** PR → `0.09`.
- **Step N (N>1)**: branch off **step N-1's branch tip** (so N already contains all prior work →
  conflict-free); push; open a **draft** PR → `0.09`.
- After each push, **verify the PR's CI is green, then immediately start the next step on top.**
  A broken step poisons everything stacked above it; fix red on that branch first.
- **As the bottom PRs merge**, `git fetch origin 0.09` and **rebase the remaining stack onto
  fresh `0.09`.** `origin/0.09` goes stale within minutes — always fetch immediately before you
  branch or rebase (the near-miss corollary in `CLAUDE.md`).
- **Other parallel sessions also merge into `0.09`**, so expect conflicts in the hot shared
  files — `CLAUDE.md` (everyone edits the shipped-log/queue top) and the locale JSON
  (`src/static/locales/*.json`). **Resolve them ADDITIVELY — keep BOTH sides' entries/keys,
  never drop a parallel session's work.**
- Branch names: `oo/<NN>-<slug>`. All PRs stay **draft**; never self-merge.
- **HARNESS FALLBACK (this session's reality):** if your harness locks development to ONE working
  branch (e.g. `claude/jolly-euler-cp8rwc`), that constraint WINS — work is stacked as
  well-scoped commits on that one branch under ONE draft PR to `0.09`. Each "step" in §5 is still
  verified end-to-end before the next begins.

## 3. Verification gate — what "done" means here

The container is **Python 3.11 with NO project deps**; the repo needs **3.13**. So full `pytest`
runs **in CI, not locally**. Your local gate:

- **Python**: `python -m py_compile` every changed file. For new pure logic, write a tiny
  standalone repro (in-memory SQLite / stubbed inputs) and PROVE the behaviour before you trust
  it.
- **Know the blocking CI `test`-lane order** (from `.github/workflows/ci.yml`):
  `ruff check --select=F,B --extend-ignore=B008` (BLOCKING) → ruff style (advisory) →
  **`i18n_report.py --min 100`** (BLOCKING) → **migration-drift** (`alembic upgrade head && alembic
  check`, BLOCKING) → **`pytest`** → **mypy ratchet (`MYPY_BASELINE=127` — add ZERO new errors)** →
  bandit (medium+) → pip-audit. **pytest runs BEFORE the mypy ratchet**, and i18n + migration-drift
  are themselves blocking — a green-pytest PR still fails if a locale drops below 100% or a model
  drifts from the Alembic baseline. **mypy IS pip-installable in the 3.11 sandbox** (`pip install
  mypy`) and type-checks changed files via their real-import closure even without project deps —
  **RUN IT on every Python change** (`python3 -m mypy <changed.py>`); the ratchet is a BLOCKING gate
  and `py_compile` + ruff F/B alone do NOT catch type drift (the 2026-06-25 copypasta lesson).
  Gotcha: `py_compile` passes on an unused import or a name used only in an `except`/annotation, but
  **ruff's F-lane fails on it** — re-check every import you add, especially exceptions caught in
  `except`.
- **The non-`test` lanes ALSO gate the merge — design for them:** `core-only` installs WITHOUT the
  `[analysis]` extra, so any new optional dep (numpy / VADER / pyroaring / a segmenter / a JSON-stat
  lib) MUST import lazily and **degrade loudly** ("unavailable" + the reason, never a crash — mirror
  `parity_available()` / `secure_crypto_available()`; analysis-only tests `importorskip`); `crypto` +
  `sqlcipher-smoke` (the latter BLOCKING, 3-OS) exercise the encryption paths — anything added to the
  columnar/encrypted store must pass the empirical encryption gate (sentinel absent from raw bytes ·
  won't open without key · opens with key), NEVER a plaintext derived file; `portability`
  (observation-only) runs on Windows/macOS — no OS-specific paths, use `src/paths.py`.
- **Always add/extend a real `pytest` test** (CI runs it) **and** a guard in
  `tests/test_repo_invariants.py` where the project pattern calls for it. Never assert positive
  facts against the shared mutable `src.api.main.app` singleton's `.routes` — anchor route
  guards to each router's own `router.routes` + the `include_router` wiring in source.
- **JS/CSS**: `node --check` every changed `<script>`/asset; keep i18n at 100%
  (`scripts/i18n_report.py --min 100`); new chrome strings go through `t()` (English fallback
  ok; key ×12 when you can, flag non-en as AI-drafted/needs-review). Key strings **byte-exact**
  against `--audit-chrome` output (the apostrophe/em-dash/ellipsis trap) and append surgically to
  each locale JSON (no full re-dump → zero reformat).
- **Any externally-sourced/dated/vendored artifact** (a bundled segmenter, an httpfs binary, a
  dated data file/catalog, a version pin) needs a `configs/external_artifacts.yml` entry **in the
  same commit** + a `*_AS_OF` constant — the protocol-guard test fails otherwise. On a DuckDB bump
  follow `docs/maintenance/EXTERNAL_DEPENDENCIES.md`: the `duckdb-crypto-extension` floor MUST equal
  the pyproject `[columnar]` floor (test-enforced).
- **Frontend is browser-unverified by design** (no headless browser). Per the **fork-3
  convention** you STILL build UI — conservatively, with `node --check` + an invariant test +
  defensive empty/error states — and **flag "browser-unverified, needs click-through."** The
  click-through is the maintainer's standing follow-up, never a reason to skip building.
- A step is **DONE** only when: wired end-to-end (endpoint registered in the spine, frontend
  calls it, migration + boot self-heal if a column was added), tests + node-check pass, **the
  ledger entry is written**, and CI is green. Only then start the next step.

## 4. Subagent orchestration — this is how you beat your own context limits

> The maintainer's explicit ask for this session is to **maximize performance and optimize agent
> / sub-agent use.** Treat your main thread as the place for DECISIONS, EDITS, and VERIFICATION;
> delegate the reading and the fan-out. Keep conclusions, not file dumps.

**Spawn `Agent` constantly — a named standing fleet.** Dispatch the role that fits, by name:

- **Scout** (Explore) — before EVERY step, map what the feature touches + what already exists
  (read-only; breadth "medium" focused / "very thorough" cross-cutting). One Scout per step.
- **Planner** — for any multi-file feature (unified import/export, the `keyword_daily` rollup +
  incremental MERGE, the `ooViz` family, the stat-data parsers), draft a file-by-file change map +
  a test plan FIRST, so your edits are surgical.
- **Builder** — hand a single, fully-specified, self-contained slice with its acceptance test;
  integrate and verify what it returns — **never merge a Builder's diff unread; you own correctness.**
- **Auditor/Red-team** — before finalizing a step, run **`/code-review`** or spawn a reviewer to
  REFUTE the diff (correctness bugs, integration gaps, missed conventions, a fabricated number /
  hidden caveat / recency bias / silent score / de-US slant). **Hand-verify every finding** —
  subagents can be confidently wrong (the 06-audit false-positive lesson); you own the result.
- **Verifier** — for correctness-critical math (the `keyword_daily` rollup parity, the
  volume/parity paths, the revision-anomaly statistics) spawn a SECOND agent to **independently
  re-derive the expected result and diff it** against the implementation.
- **Use a worktree-isolated agent** (`isolation: "worktree"`) only when an agent must mutate files
  in parallel with your main edits — expensive, so reserve it.

**The contract every sub-agent gets.** Each delegated task returns ONLY a tight structured summary,
never a file dump. An Explore/Scout return MUST be: (1) the exact files + line ranges that matter,
(2) the endpoints/functions/tests involved, (3) the conventions to match, (4) **what is already
built** (so you build only the gap), (5) the precise residual gap as a checklist. If an agent hands
back prose or pasted source, send it back for the summary — a bloated return defeats the purpose.

**Parallelism — fan out in ONE message.** The workstreams below touch different modules and have NO
shared hot files at the design level, so at session start spawn one Scout each, in a single message,
then sequence the PRs by value/risk: **S** stat-data+ooViz (`src/stats/*`) ⟂ **D** derived-layer
rollups (`columnar.py`/`readmodel.py`) ⟂ **C** manipulation cards (`concentration.py`) ⟂ **U**
unified import/export ⟂ **K** zh/ja segmentation (tokenizer) ⟂ **I** i18n (locales). Intra-lane: in
S the **revision-anomaly detector is fully independent — do it first**; in D, D2→D3→D4 are ordered
and D5 (Roaring) is optional/off-critical-path.

**Multi-agent `Workflow` orchestration (only if opted in — "ultracode" / the user asked for a
workflow).** Reach for the HEAVIEST workflow on the two highest-fabrication-risk slices — **D3
incremental-refresh correctness** (the `index_article` delete-then-reinsert double-count trap) and
the **`ooViz` honesty gate** (reject-list enforcement) — where a subtle bug fabricates a NUMBER.
High-value workflow shapes for THIS repo:

- **Parser sweep (pipeline):** the statistical-data parsers (CSV wide→long, JSON-stat/PxWeb,
  SDMX-JSON verification, bulk-ZIP) — one stage per format: read a fixture → write the pure
  parser → adversarially verify it against the fixture → emit the registry entry. `pipeline()`
  so each format flows independently with no barrier.
- **Adversarial verify (perspective-diverse):** each new manipulation/anomaly signal (the
  revision-anomaly detector, the bury-half, outrage-intensity) verified by N skeptics with
  DISTINCT lenses (statistical validity · the innocent-twin explanation · does-it-reproduce ·
  de-US bias). Kill a finding unless a majority survive.
- **Completeness critic + loop-until-dry:** the i18n burn-down and the data-architecture parity
  proofs — keep spawning finders/keyers until K rounds surface nothing new; a final critic asks
  "what's still untranslated / which VERIFY-checklist item is unproven?"
- **Multi-modal sweep:** the `ooViz` honesty audit — parallel agents each checking a different
  rule (zero-baseline / gaps-not-bridged / no-causation / no-magnitude-distortion / sr-table /
  17-themes+RTL) across every chart surface.

Cost discipline: workflows can spawn dozens of agents — use them for genuine fan-out/verification
breadth, not for a single-file edit. Scale finder/verifier counts to the slice's difficulty.

**Rule of thumb:** if a task means reading across many files, **delegate the reading to an agent
and keep the conclusion.** Your main thread is for decisions, edits, and verification.

## 5. Scope & order (value/risk: unblock → high-impact → cheap → cards → scaffold → docs)

> Everything below is grounded in the AUDITED current state. **Explore before each step** and
> build only the gap. The list is large by design (the maintainer's "address as many topics as
> possible") — work top-down; each item is independently shippable.

### 5A. Tier 1 — bugs & perf (unblock testing first)

1. **Collector write-batching (P1-C, `docs/design/COLLECTOR_WRITER_BATCHING.md`).** Many parallel
   fetchers funnel into ONE DB writer. Implement the documented safe path: an additive
   `store.index_article(commit=False)` + batch a source's store+index into one transaction in the
   ingest loop, with the proven `ingest_emails` per-message fallback on a batch failure (= NO
   data loss, keystone #1). Default `OO_COLLECT_COMMIT_BATCH=1` (byte-identical) so adoption is
   opt-in. **Prove no loss with a test** (extend `tests/test_write_gate_dataloss.py`-style
   contention). Caveat from the design doc: the keyword-counter deltas accumulate correctly
   within one txn by construction; the `keyword_daily` watermark interaction (5A-bis D3) means a
   batched commit is still APPEND, so it's compatible. This was deferred for "needs the full
   suite + a live measurement" — build it behind the default-off flag with the no-loss proof so
   it is reliable-by-construction even before the live measurement.

### 5A-bis. Scale the derived layer to 1000× (the deep fix for the per-keyword freeze)

A backend workstream that runs largely in parallel with the UX tiers. **EXTENDS the shipped seam
(`readmodel.py`, `columnar.py`, the covering index) — Explore those first; extend, never
recreate.** Source of truth + full VERIFY checklist: `docs/design/SCALING_DERIVED_LAYER_1000X.md`.
ONE canonical encrypted SQLite file stays authoritative; all of this is the disposable,
rebuildable derived layer behind the seam. The canonical store is NEVER time-partitioned
(cross-time recall is sacred).

2. **D2 (BUILDABLE NOW) — the `keyword_daily` rollup**:
   `keyword_daily(keyword_id, day, mentions, articles_on_day, PK(keyword_id, day))` where
   `day = keyword_mentions.observed_on`. Full build by **streaming canonical mention rows through
   the app's SQLCipher connection INTO DuckDB and grouping THERE** (DuckDB can't read a SQLCipher
   file; never a SQLite GROUP BY over the billions-row mention table — that IS the freeze). Wire
   the existing `readmodel.py` delegators (`top_terms`/`trending`/`trending_windows` — those are the
   REAL seam fn names, NOT the design-doc's `most_mentioned`/`rising_terms`) to serve from it when
   the persisted store is present, secure, and its epoch matches the live corpus; else fall back to
   the live query (basis
   flag `columnar@epoch N` vs `live`, slower-never-wrong). **Build + prove parity IN-MEMORY now** —
   parity is provable in-memory even though the perf win needs the persisted store (D1).
3. **D3 (CORRECTNESS-CRITICAL) — incremental refresh** on the `keyword_mentions.id` watermark + a
   corpus-epoch full-rebuild gate (`oo_meta` keys `keyword_daily.last_mention_id` /
   `keyword_daily.built_epoch`). **THE TRAP (grounded in this repo): `index_article` does
   delete-then-reinsert of an article's mentions, so the id-watermark MERGE-ADD is correct ONLY
   for APPEND (new articles → new higher ids). EVERY path that re-runs `index_article` over an
   EXISTING article — `reindex_all_batch`, `reindex_articles`, `reindex_imported_articles`
   (restore), the clean-up-keywords flow — and `prune_orphan_keywords` MUST bump the corpus epoch
   and force a FULL rebuild, never an incremental MERGE, or the rollup double-counts (a fabricated
   number). Normal new-article ingest must NOT bump the epoch.** Prove both directions with tests
   (incremental-after-batch == full-rebuild; a simulated re-index forces full).
4. **D4 — `source_coverage` rollup** (`country, source_id, articles, mentions, first_day,
   last_day`) on the same watermark/epoch machinery — serves per-country coverage without scanning
   the mention table.
5. **D5 (OPTIONAL, off the critical path) — Roaring co-occurrence bitmaps** (pyroaring) for the
   set-intersection queries the rollups don't help (co-occurrence / mind-map / actor-collapse).
   Behind a new optional extra (graceful-degrade if absent, like numpy/VADER), registry entry,
   rebuilt on epoch bump. Build only when the graph queries actually need it.
   - **D1 (the unblock) is in 5E** — without the persisted encrypted DuckDB store the columnar
     layer is RAM-bound; build D2–D4 parity-provable in-memory now, ship the perf win when D1's
     binaries land.

   **Honesty guardrails:** `articles_on_day` is an UPPER BOUND when a (keyword,article) pair spans
   multiple days — carry the basis flag; the live-exact escape is cheap PER-KEYWORD only, never
   corpus-wide. The rollup spans ALL history — never recency-biased. Counts + basis flag only,
   never a composite score. **Rejected (do NOT wander): chDB/ClickHouse, Turso/libSQL, Tantivy,
   ATTACH-per-period partitions, time-partitioning the canonical store** — keep DuckDB + FTS5 +
   ONE canonical SQLite file (the research red-teamed these).

   **VERIFY checklist (lift into tests; inlined so it survives a context reset):** (1) `keyword_daily`
   SUM(mentions) == SUM(count) over `keyword_mentions` for a sampled keyword set (EXACT); (2) windowed
   most-mentioned == live ranking (EXACT on mentions); (3) windowed COUNT(DISTINCT article_id):
   columnar upper-bound vs live differ only on multi-day pairs, reported never hidden; (4) incremental
   refresh after a new batch == a full rebuild; (5) a late-arriving historical-dated batch lands on
   the correct day after incremental; (6) a simulated re-index (epoch bump) forces a FULL rebuild, not
   incremental; (7) `analytics.duckdb` unreadable as plaintext (D1-gated); (8) network blocked → zero
   outbound on store-open + httpfs-load (D1-gated); (9) bundled httpfs matches its pinned SHA-256
   before LOAD (D1-gated); (10) no ATTACH cipher other than authenticated GCM (D1-gated); (11)
   cold/missing store → the seam falls back to the live query, identical results; (12) Roaring
   co-occurrence(X,Y) == the live two-keyword intersection for a sampled pair (D5-gated).

### 5B. Statistical-data ingestion + the `ooViz` honest-visualization family (the big fresh push)

> Full design: `docs/FUTURE_DEVELOPMENTS.md` → "Statistical-data ingestion + diversified honest
> visualization"; verbatim research under `docs/research/`. EXTENDS the shipped
> `src/stats/{sdmx,fetch,store,subscriptions,agencies,indicators,ingest}.py` (all 8 already exist —
> `indicators.py` already curates ~12 WB series wired to `fetch_worldbank`) + the vintaged
> `StatFigure` + the Settings → Statistics UI + `ooChart`/`ooMap`/`ooDonut`/`ooSubtabs`. **One small
> additive PR per slice.** `sdmx.py` parses **World Bank JSON + SDMX-JSON 2.1 only (NOT SDMX-XML)** —
> that decides what is ingestable today.
>
> **Resolve the research's 7 open decisions** (`FUTURE_DEVELOPMENTS.md` → "Open decisions for the
> maintainer") by the recommended/most-honest option and RECORD each in the ledger (the autonomy
> ruling): **(1)** expectation/anomaly **RETROSPECTIVE-ONLY**, band NEVER crosses the last
> observation — YES; **(2)** classical-first, **no foundation model** (no torch/onnx in core; any FM
> is a future optional Ollama-style external process) — YES; **(3)** flagging official figures uses
> **neutral, innocent-explanations-first** wording (methodology/base-year/SA-change auto-filtered via
> the comparability metadata) — hard design constraint, acceptable on government numbers; **(4)**
> **CSV + JSON-stat parsers in scope** — YES; **(5)** **choropleth normalized-only**, levels →
> proportional symbols — YES; **(6)** add a **`global`/`transnational` region value** to the source
> schema — YES; **(7)** key-gated sources (EIA/FRED/Comtrade) — **SKIP this cycle** (US-centric, low
> de-US value).

6. **THE ON-MISSION KERNEL — the revision-anomaly detector** (highest-value, owes nothing to any
   model). `StatFigure` already stores **vintages** (`vintages_for`). Characterize a series'
   historical revision-magnitude distribution and flag a NEW vintage that moves a past figure into
   the tail. Reliable-memory mission, no model. **Sensitivity (elections-grade): neutral wording,
   innocent-explanations-first** (methodology / base-year / SA change → auto-filtered via the
   existing comparability metadata; genuine shock; data error) — flagging an official figure as
   "unusual" must NEVER near-imply the producer faked it. Counts + measured distance only, NO
   score; the existing "surprise vs the corpus's own baseline" spine.
7. **Phase A — stat-data backbone.** A1: **EXTEND `src/stats/indicators.py`** (it already curates
   ~12 WB series wired to `fetch_worldbank` via `/api/governments`) to the ~29 verified series —
   decide reuse-vs-a-new-`configs/stat_indicators.yml`, but do NOT author a parallel catalog (both
   this brief's earlier draft and the competitor's missed this overlap — flag it). `indicators.py` is
   intentionally NOT registry-coupled (`CATALOG_REVISED`, not `*_AS_OF`); only add a `*_AS_OF`+registry
   entry when you introduce a genuinely external dated data file. A-CSV: a CSV wide→long adapter + OWID
   energy/CO₂ (one small parser, biggest payoff — the best-verified global data; its snapshot IS a
   dated artifact → registry entry). A3: verify `parse_sdmx_json` against the 8 verified SDMX rows with
   offline fixtures; wire Pacific Data Hub + ECB (`format=jsondata`).
8. **Phase B — viz adapter + ooChart honesty.** B1: `StatFigure[] → chart series` (period
   parsing, None→gap, comparability segmentation). B2: ooChart gap subpaths +
   comparability-break markers (reuse `pathWithGaps` from `docs/research/dataviz/honest-charts.js`
   — adopt into a shared `ooViz` module, don't blindly duplicate `ooChart`). B3: the time-series
   UI in Settings → Statistics (ooChart + ooTimeScope + visible caveat + `role="img"` +
   data-table).
9. **Phase C — choropleth.** C1: ooMap comparability precheck + a distinct "not comparable" hatch.
   C2: "Map this indicator" — normalized → choropleth; levels/counts/conflict → proportional
   symbols via `sqrtAreaScale`.
10. **Phase D — diversified techniques** (each honesty-clean, tied to real data): small multiples ·
    dot-plot/bump · **dumbbell/slope** (two vintages = the revision viz; V-Dem CIs) · association
    scatter (points-only, NO regression line) · histogram/box · population pyramid · the
    **data-availability matrix** (country × year present/gap — an honesty showcase). The
    **reject-list is a feature**: radar, streamgraph, 3D pie, dual-axis abuse,
    regression-implies-cause, bubble-area-as-magnitude, word-cloud-as-primary — each gets the
    honest replacement, and `test_ui_invariants` GROWS a guard rejecting them.
11. **Phase E — parsers + governance.** JSON-stat/PxWeb (unlocks all Eurostat + IRENA) →
    bulk-ZIP-CSV (V-Dem/UCDP). Bake the honesty gate into `ooViz` (position>length>angle>area;
    zero baseline for length marks; gaps shown never interpolated; no causation from
    co-occurrence; deterministic; survives 17 themes + RTL; no charting libs / no WebGL). **Skip
    the key-gated sources** (EIA/FRED/Comtrade) this cycle (US-centric, low de-US value).
12. **News/source diversity seeding** (`docs/research/sources/`, 105 verified rows, all in managed
    languages, `enabled: false`). Seed them as DISABLED sources (the established controversial-free
    descriptive provenance). **Dedup `statssa.gov.za`** across the source catalogue and the stats
    producer directory (seed as ONE). Add the `global`/`transnational` region value the
    transnational outlets (ReliefWeb, African Union, CARICOM) need. Carry the Herald-zw domain
    caveat; lean labelled on only the 4/105 that the research labelled (omitted-not-guessed). Also
    safe-to-expand: `src/stats/agencies.py` from the ~152-producer directory **as a metadata
    directory** (only live-fetch the 32 verified machine endpoints).

### 5C. Tier 2/3/4 — high-impact UX, cheap UX, cards (build fully)

13. **Unified Import + unified Export/Backup** (`docs/design/UNIFIED_IMPORT_EXPORT.md`; remarks
    2/5/6). ONE Import entry + ONE Export/Backup entry, each → an options pop-up → file/folder
    pick, **on the NEW OOENC2 streaming-volume path** (NOT the legacy OOENC1 2 GiB path) with a
    **clear progress bar + live data-volume readout** reusing the folder-backup/folder-import job
    progress. Fuse BOTH newsletter-import paths (the small-file upload + the server-side folder
    job) behind one pop-up. Split into sub-PRs (6a import, 6b export/backup); **absorption test:
    no import/export/backup capability lost** (the Desk lesson). Large + browser-unverifiable —
    Plan-agent it first, ship conservative + flagged.
14. **Manipulation card #4 — the BURY half** (a source UNDER-covering a topic that is big across
    OTHER sources). The FLOOD half (`concentration.find_flooded_topics`) is shipped; build the
    under-coverage detector ONLY if honestly derivable from the corpus (it needs a real external
    "big elsewhere" trigger so it isn't corpus-bias-driven — if not honestly derivable, write the
    seam + a ledger note and defer, don't fake it).
15. **outrage-intensity annotation** — a sentiment-anomaly signal that ANNOTATES another card,
    never a standalone Lead (English-only via VADER, the standing B1 disclosure). Secondary by
    design.
16. **App self-update mechanics** (manual git-pull: snapshot → verify → migrate → swap →
    rollback), **default OFF, no signing key yet** (per the `CLAUDE.md` ruling; mark "use signing
    keys" for the future). Build the MECHANICS only; the data dir lives outside the code tree so
    the corpus/keys survive by construction. Cannot be end-to-end validated in-sandbox (brick
    risk) → build it guarded + default-off + heavily tested in unit, flag for live verification.
17. **i18n burn-down** (`--audit-chrome` ~105 remaining). Slice by panel. The clean
    single-text-node strings are directly keyable; the inline-`<a>`-link fragments need the
    link-at-end de-tagging restructure (a heavier, browser-verifiable slice — do those
    carefully). Leave the security-/technically-dense paragraphs (custody IP/timing,
    AES-GCM/Reed-Solomon volume backup) and intentional-emphasis privacy warnings for native
    review; key the rest byte-exact ×12, flag non-en as AI-drafted.

### 5D. SCAFFOLD + DESIGN DOC — build the honest part, document the blocked part, never fabricate

18. **D1 — persisted encrypted DuckDB store** (`docs/design/PERSISTED_DUCKDB_HTTPFS.md`). Write
    the OFFLINE-LOAD path: `autoinstall/autoload_known_extensions=false`,
    `allow_unsigned_extensions=true`, `LOAD` from an absolute in-app path, **SHA-256
    pin-and-verify the binary BEFORE load**, `ATTACH` with the default authenticated **GCM cipher
    and NEVER a CTR cipher** (the disclosed downgrade attack), flip `secure_crypto_available()`
    true only after LOAD + the `encryption_gate` probe. Add the `external_artifacts.yml` entries +
    the DuckDB↔httpfs version coupling (test-enforced). **BLOCKED in-sandbox:** the per-OS/arch
    binaries need a networked multi-arch vcpkg static build = the maintainer's step. Ship the
    code + an EMPTY, clearly-flagged pin table + the build recipe. **Never fabricate a checksum or
    claim a binary exists** (a blank pin keeps the store in-memory = safe).
19. **Ollama binary installer** (remark 1). Build the Settings → AI installer UI +
    hardware-tier scenario messaging (measure RAM via the existing vitals → recommend a fitting
    model) + the download-**and-verify** flow + the Mistral-led picker (catalog already leads with
    `mistral:7b` / `mistral-small:latest`). **Per-OS installer checksums come from a networked
    machine** — leave a clearly-flagged empty checksum table + a design note. Never invent a
    checksum.
20. **zh/ja keyword segmentation** — a design doc proposing a bundled offline segmenter
    (jieba/pkuseg/MeCab) + the seam; implement ONLY if a no-network, license-clean option is
    honestly available (then add its registry entry). Today the tokenizer is space-based, so
    zh/ja produce no keywords — the seam is the deliverable, the segmenter is data.
21. **event-timed-op manipulation card + the elections/civic vertical scaffold.** The generic
    events/calendar substrate is shipped; build the card/schema scaffold + the design doc. The
    candidate **roster is maintainer-supplied data** — leave it a seam, never fabricate
    candidates/poll numbers. Poll analysis = audit METHOD (transparency checklist, never a score),
    Tier 2 first.

### 5E. DESIGN DOC ONLY (deferred / large / separate project) — update, don't re-author

22. The 5C-family docs ALREADY exist — **LLM who/where/when + sentiment eval harness**, **Tor
    integration + per-source transport**, **voice-only mode**, **Open Commons Mirror** (a separate
    sister project). Update them only if this session's work changes a seam they reference;
    otherwise leave them.

### 5F. OPERATIONAL — note, do NOT rebuild

- Running keyword cleanup / baseline-tag backfill on the LIVE corpus; generating translation
  rings (networked machine, Wikidata blocked in CI); the per-OS/arch httpfs + Ollama binary
  builds (networked, multi-arch); flipping 0.0.9 → 0.1 (a release decision, held until every
  RC-BLOCKING row in `docs/product/RELEASE_0.1_RC_GATE.md` is ✅); human click-through (maintainer
  QA — flag per feature).

## 6. The per-step loop

1. **Scope it** — Explore agent → files/conventions/tests + what already exists.
2. **Branch** off the previous step's tip (or fresh `0.09` for step 1; or commit on the single
   branch under the harness fallback).
3. **Implement** — small, additive, matching surrounding code; migration + boot self-heal if you
   add a DB column (the live DB is not auto-alembic'd); consolidation absorption-gated; never
   weaken a non-negotiable.
4. **Verify** — `py_compile` + ruff F,B + **mypy(≤127)** / `node --check` / standalone repro; add
   the pytest test + the invariant guard; i18n 100%; **spawn a review agent and hand-verify its
   findings.**
5. **Ledger** — write the shipped entry (or queue update) in `CLAUDE.md` the SAME turn. Extend
   `tests/test_repo_invariants.py::test_ui_invariants` when you add a critical UI invariant.
6. **Commit** (clear message; **NEVER** put any model identifier in any repo artifact; **never**
   use backticks inside a `git commit -m` heredoc), **push**, **open the draft PR**. Update the
   `RELEASE_0.1_RC_GATE.md` rows you close.
7. **Confirm CI green**, then start the next step on top.

## 7. Honesty non-negotiables (every step)

Local-first / loopback-only; the ONLY external calls are the gated, off-by-default ones (DDG
discovery, consented stat/market fetches, Ollama over loopback) — boot makes zero network calls,
airplane mode is a socket-level guarantee. **No fabricated data, scores, security, endpoints, or
checksums.** No composite trust/quality scores (every signal carries method + caveat + n).
Caveats VISIBLE by default (never hidden behind a calm-UI toggle); degrade loudly. Cross-time
recall is sacred (no recency bias). The rule-based keyword index is the TRUSTED layer; AI output
is a separate, clearly-labelled, UNRELIABLE PERCEPTION layer that **never feeds the trusted index
and never forecasts / grades / ranks / decides-worth** (`CLAUDE.md` §0.5). **No fabricated data,
scores, security, endpoints, checksums, or DOIs.** **Forecasting of statistics is
RETROSPECTIVE-ONLY — the expectation/anomaly band NEVER crosses the last observation** (a §7
non-negotiable, not merely a §5B default). **At-rest encryption is no-recovery by design** (the
corpus is reconstitutable from the web). Derived stores are disposable; the canonical encrypted
SQLite store is always authoritative. When something is blocked, ship a **clearly-flagged EMPTY
SEAM** (a blank pin/checksum table, an inert disabled control, a stub returning "unavailable" with
the reason) — never a fabrication. Informed consent by LAYERING, ×12 locales. When in doubt, read
the relevant non-negotiable in `CLAUDE.md` and follow it exactly.

## 8. When something can't be finished autonomously

If a step's core needs the live corpus, a networked/multi-arch build, fabricated data, or a
genuine maintainer ethics/irreversible ruling: **build the honest part** (the scaffold + the
design doc per 5D/5E), write a one-line ledger note with the reason, and **move to the next
step.** Don't stall, and don't fake it. The queue is deep on purpose — there is always honest
work to advance.

---

### Session execution note (fill in at session start)

Record here, the same turn, the harness constraint you actually run under (single-branch fallback
vs stacked PRs), the branch name, and the conservative defaults you adopted for the §5B research
"open decisions" — so a context reset re-reads them. The maintainer merges on their own schedule;
each §5 step is verified end-to-end before the next begins.
