# Autonomous build session — work the Open Omniscience to-do list

> **This file is the verbatim build brief for the 2026-06-24 autonomous session.** It is the
> reset-proof durable memory: after ANY context reset, re-read this file plus `CLAUDE.md` and
> `docs/FUTURE_DEVELOPMENTS.md` → "CONSOLIDATED TO-DO (rechecked & complete, captured
> 2026-06-24)". If anything here ever conflicts with `CLAUDE.md`, `CLAUDE.md` wins.

You are running an **autonomous, multi-step build session** on the Open Omniscience repo
(default branch `0.09`). Work through the project to-do list, shipping each step as its own
stacked pull request, verifying each is fully integrated before the next. Work in **complete
autonomy** — never stop to ask. At any genuine fork, pick the most honest, conservative
option, record it in the `CLAUDE.md` ledger, and keep going (the maintainer's standing
"don't ask me anything" ruling).

**This brief is fully self-contained — it is the only artifact you need to start.** Nothing
external is required; you reconstruct all context from the repo (`CLAUDE.md` + the to-do)
and from this brief, which you commit to the repo as your first step.

## 0. First moves — every time your context resets

1. **Bootstrap your durable memory (do this ONCE, as PR #1):** write this entire brief
   verbatim to `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-24.md` and ship it as a
   doc-only PR. This is your reset-proof memory — after ANY context reset, re-read that
   committed brief. (Skip the write if the file already exists; just re-read it.)
2. **Read `CLAUDE.md` in full.** It is the single ledger of every maintainer ruling and your
   long-term memory. The PROTOCOL is mandatory: record every new ruling and every shipped
   step IN `CLAUDE.md` the same turn — that is how your work survives context summarization.
   If anything here ever conflicts with `CLAUDE.md`, `CLAUDE.md` wins.
3. **Read `docs/FUTURE_DEVELOPMENTS.md` → "CONSOLIDATED TO-DO (rechecked & complete, captured
   2026-06-24)"** — that checklist is the work; the verbatim "FIELD-TEST REMARKS 2026-06-24"
   section above it carries each remark's full context.
4. **Re-derive where you are**: `git log --oneline -15`, `git branch -a`, list open PRs,
   re-read your latest ledger entries + your committed brief. Never redo a merged/shipped step.
5. **Several remarks are already partly or fully shipped — Explore the current code FIRST and
   build only the missing piece (the Desk lesson: never rebuild what exists).** Already done,
   do NOT redo:
   - Remark 7 (Home "Loading the briefing…" hang + progress bar) — **#455**.
   - Folder-import `UNIQUE constraint failed: articles.hash` + the law-revision pass rollback
     — **#453**.
   - Insights background-warm + per-corpus endpoint caching — **#455 / #458** (your remaining
     work on remark 8 is the *statement-deadline* + the rollup, see Tier 1 + 5A-bis).
   - Sidebar expand/collapse buttons exist ("Item R") — remark 15's new part is only the
     *click-empty-space* toggle.
   - The data-architecture seam already exists: the honesty envelope, denormalised counters,
     `src/analytics/readmodel.py`, `src/analytics/columnar.py`
     (`connect()`/`keyword_agg`/`oo_meta`/`encryption_gate`/`secure_crypto_available()`), and
     the `ix_mention_date_keyword` covering index. **5A-bis extends these — never recreate.**
6. **Maintain a task list** (TaskCreate/TaskUpdate) of the step queue as a within-window
   progress aid — but the durable memory is the `CLAUDE.md` ledger + your committed brief, so
   write there too.

## 1. Working mode

- One **step** = one self-contained, additive change = one **draft PR**. Keep steps small and
  single-purpose; prefer many small PRs over one big one.
- **Never fabricate** data, results, scores, checksums, or test outcomes — honesty by
  construction is the first non-negotiable. If something needs data you don't have, build the
  honest part, flag the gap, move on.
- **Consolidation/removal steps must never lose a capability** (the Desk lesson): when you
  fuse or move a surface (Graphics, unified import/export, the Settings intro box), keep an
  absorption guard/test proving nothing is lost, and make removed things unreachable rather
  than deleted where the project pattern calls for it.
- Report faithfully: failing test → say so with output; partial step → say which half shipped
  and which is deferred and why.

## 2. PR / branch model — stack and keep moving

The maintainer merges on their own schedule, so **do not wait for a merge to start the next
step**:

- **Step 1**: branch off a freshly-fetched `origin/0.09`; push; open a **draft** PR → `0.09`.
- **Step N (N>1)**: branch off **step N-1's branch tip** (so N already contains all prior work
  → conflict-free); push; open a **draft** PR → `0.09`.
- After each push, **verify the PR's CI is green, then immediately start the next step on top
  — without waiting for the maintainer to merge.** A broken step poisons everything stacked
  above it; fix red on that branch first.
- **As the bottom PRs merge**, `git fetch origin 0.09` and **rebase the remaining stack onto
  fresh `0.09`**. `origin/0.09` goes stale within minutes — always fetch immediately before
  you branch or rebase.
- **Other parallel sessions also merge into `0.09`**, so expect conflicts in the hot shared
  files — `CLAUDE.md` (everyone edits the shipped-log/queue top) and the locale JSON
  (`src/static/locales/*.json`). **Resolve them ADDITIVELY — keep both sides' entries/keys,
  never drop a parallel session's work.**
- Branch names: `oo/todo-01-<slug>`, `oo/todo-02-<slug>`, … All PRs stay **draft**; never
  self-merge. If your environment can't open a PR, push the branch and note the PR is pending
  — don't stall.
- **Fallback** if your harness locks you to one working branch: that constraint wins — use
  sequential re-cut (one PR, wait for its merge, re-cut the next from fresh `0.09`).

## 3. Verification gate — what "done" means here

The container is Python 3.11 with **no project deps**; the repo needs 3.13. So full `pytest`
runs **in CI, not locally**. Your local gate:

- **Python**: `python -m py_compile` every changed file. For new pure logic, write a tiny
  standalone repro (in-memory SQLite / stubbed inputs) and prove the behaviour.
- **Know the blocking CI `test` lane order**: `ruff check --select=F,B --extend-ignore=B008` →
  **mypy (must stay ≤ the 127 baseline — add zero new errors)** → `pytest`. Gotcha that has
  bitten before: **`py_compile` passes on an unused import or a name used only in an
  `except`/annotation, but the ruff F-lane fails on it** — re-check every import you add,
  especially exceptions caught in `except` clauses.
- **Always add/extend a real `pytest` test** (CI runs it) **and** a guard in
  `tests/test_repo_invariants.py` where the project pattern calls for it.
- **JS/CSS**: `node --check` every changed script; keep i18n at 100% (`scripts/i18n_report.py
  --min 100`); new chrome strings go through `t()` (English fallback ok; key ×12 when you can,
  flag non-en as AI-drafted/needs-review).
- **Any externally-sourced/dated/vendored artifact** (a bundled segmenter, a httpfs binary, a
  dated data file, a version pin) needs a `configs/external_artifacts.yml` entry **in the same
  commit** — a protocol-guard test fails otherwise.
- **Frontend is browser-unverified by design** (no headless browser). Per the fork-3
  convention you **still build UI** — conservatively, with `node --check` + an invariant test
  + defensive empty/error states — and **flag "browser-unverified, needs click-through."** The
  click-through is the maintainer's standing follow-up, never a reason to skip building.
- A step is **DONE** only when: wired end-to-end (endpoint registered, frontend calls it,
  migration + boot self-heal if a column was added), tests + node-check pass, the ledger entry
  is written, and CI is green on its PR. Only then start the next step.

## 4. Leverage subagents aggressively — this is how you beat your memory limits

Spawn subagents with the **Agent** tool constantly, to keep your own context lean (delegate
the file-dumps, keep only the conclusions):

- **Before each step**, spawn an **Explore** agent to map exactly what the feature touches:
  files, endpoints, existing tests, conventions to match, and **what's already built** (so you
  build only the gap). Get a tight summary back — don't read ten files into your context.
- **Fan out in parallel**: for independent steps/questions, spawn multiple agents **in one
  message** so they run concurrently.
- **Plan big steps with an agent**: for multi-file features (unified import/export, Library
  dashboard, the 5A-bis rollup), have a **Plan** or general-purpose agent draft a file-by-file
  change map first.
- **Verify with an agent**: before finalizing a step, run **`/code-review`** or spawn a review
  agent to adversarially check the diff for correctness, integration gaps, and missed
  conventions. **Hand-verify its findings** — subagents can be wrong; you own the result.
- If multi-agent orchestration is opted in (the **Workflow** tool / "ultracode"), use a
  workflow for exhaustive fan-out + adversarial verification on the harder steps.

Rule of thumb: if a task means reading across many files, **delegate the reading to an agent
and keep the conclusion.** Your main thread is for decisions, edits, and verification.

## 5. Scope & order (value/risk: unblock → high-impact → cheap → cards → deferred docs)

### 5A. BUILD FULLY — in this order

**Tier 1 — bugs & perf (first, unblock testing):**
1. **Per-keyword Insights freeze (remark 8, finish it):** #455 made the briefing recompute
   non-blocking and #458 cached the 5 per-corpus endpoints + added an honest slow-load note —
   **build on those, don't redo them.** Add a **statement-deadline guard** (typed 503, never
   an infinite "Loading…") to the slow per-corpus/per-keyword endpoints (associations / graph
   / framing). The deeper cold-first-open fix is the `keyword_daily` rollup (workstream
   **5A-bis**), load-bearing once the persisted encrypted store (**5B**) is unblocked; the
   statement-deadline is the honest stopgap until then.
2. **Collector writer-bound (P1-C):** many parallel fetchers funnel into one DB writer —
   reduce gate contention (batch writes where safe) **without** weakening the single-writer
   no-data-loss guarantee (keystone #1). Prove no loss with a test.

**Tier 2 — high-impact UX:**
3. **Search: Enter opens a new analysis window/tab** (remark 9).
4. **Library world map** (remark 10): per-country article counts (reuse `ooMap` +
   `/api/insights/where`/source-country) + a per-language **donut** for "no country" articles,
   **full language names**.
5. **Library central dashboard** (remark 16): counts/sizes for everything downloaded (maps,
   Wikipedia dumps, indices, laws, official stats, events) **and** extrapolated (summaries /
   translations / synthesis counts) — aggregation over existing counters, honest counts, no
   score. (4 + 5 are the same tab → two PRs.)
6. **Unified Import + unified Export/Backup** (remarks 2/5/6): one Import entry + one
   Export/Backup entry, each → an **options pop-up → file/folder pick** on the new
   streaming-volume backup path; **clear progress bar + live data-volume readout**; fuse both
   newsletter-import paths in. **Read the backup PRs first** (the OOENC2 streaming volumes +
   large-data folder backup work, in `CLAUDE.md`'s shipped log) — build on that path, don't
   fork it; honor the Desk lesson (no import/export/backup capability lost). Split into sub-PRs
   (6a import, 6b export/backup).

**Tier 3 — cheap UX & i18n:**
7. **Remove the top intro box** on every Settings subtab (remark 12) — absorption-safe.
8. **Fuse Appearance + GUIs into one "Graphics" subtab** (remark 11) — Desk-lesson gated.
9. **Status bar opaque background** matching the left sidebar (remark 14; content currently
   shows through on scroll).
10. **Sidebar: click empty space to collapse/expand** (remark 15). The expand/maximize button
    already exists ("Item R") — verify it, build the click-empty-space toggle, ensure a clear
    maximize affordance in the collapsed rail.
11. **AI prompts (remark 13):** translate the prompt-editor **UI/labels** on language switch
    and **verify summary/translation/synthesis output comes out in the UI language** (confirm
    the `output_language` pin is wired end-to-end; add coverage). **Caveat (CLAUDE.md
    ruling):** the prompt *bodies* are deliberately English — translating multi-sentence system
    prompts degrades weak models; the reliable lever is output-language. Surface the body
    readably without blindly translating the text sent to the model; reconcile, don't regress
    model compliance.
12. **i18n**: key the remaining English-fallback panel strings ×12 (slice by panel).

**Tier 4 — manipulation cards & keyword-engine code:**
13. **Copypasta card** (near-dup primitive exists) + **outrage-intensity** as an annotation on
    another card (not a standalone Lead). Astroturf is **partly covered by `echo_chamber`** —
    check it before building a separate card.
14. **Card #4 "bury" half** — a source *under*-covering a topic big across other sources — only
    if honestly derivable from the corpus.
15. **Filter gov-newsletter boilerplate** (`govdelivery` / `gd_combo_table`) at the keyword
    extraction chokepoint (the "?" bucket); add a keyword self-test golden case.
16. **App self-update mechanics** (snapshot → verify → migrate → swap → rollback), **default
    OFF**, no signing key yet (per the CLAUDE.md ruling).

### 5A-bis. Scale the derived layer to 1000× (data-architecture — the deep fix for remark 8)

A backend workstream; sits with the perf work (right after Tier 1) and runs largely in
parallel with the UX tiers. **Its full payoff is gated on the maintainer's binary build (D1),
so build the engine + parity tests + seam wiring now and DON'T block the rest of the list on
it.** Extends the shipped seam (`readmodel.py`, `columnar.py`, the covering index) — **Explore
those first; extend, never recreate.** Keep ONE canonical encrypted SQLite file as the source
of truth; all of this is the disposable, rebuildable derived layer behind the seam. The
canonical store is NEVER time-partitioned (cross-time recall is sacred); partitioning, if any,
lives only inside the derived DuckDB file (year zonemaps), never as plaintext on disk.

- **D0 — author the design doc** `docs/design/SCALING_DERIVED_LAYER_1000X.md` from this spec
  (it becomes the workstream's source of truth + test plan; expand the schemas, the
  incremental-MERGE correctness argument, and the VERIFY checklist below).
- **D2 (BUILDABLE NOW) — the `keyword_daily` rollup**: table
  `keyword_daily(keyword_id, day, mentions, articles_on_day, PK(keyword_id, day))` where
  `day = keyword_mentions.observed_on`, `mentions = SUM(count)`,
  `articles_on_day = COUNT(DISTINCT article_id)`. Full build by **streaming canonical mention
  rows through the app's SQLCipher connection INTO DuckDB and grouping THERE** (DuckDB can't
  read a SQLCipher file; never a SQLite GROUP BY over the billions-row mention table — that is
  the freeze). Wire `readmodel.py` `most_mentioned`/`rising_terms` to serve from it when the
  persisted store is present, secure, and its epoch matches the live corpus; else fall back to
  the live query (basis flag `columnar@epoch N` vs `live`, slower never wrong). **Build + prove
  parity IN-MEMORY now** — parity is provable in-memory even though the perf win needs the
  persisted store; seam-guard on `secure_crypto_available()` + epoch.
- **D3 (CORRECTNESS-CRITICAL) — incremental refresh** on the `keyword_mentions.id` watermark
  (a confirmed monotonic autoincrement PK) + a corpus-epoch full-rebuild gate. Keep two
  `oo_meta` keys: `keyword_daily.last_mention_id` and `keyword_daily.built_epoch`. Refresh
  decision: if `corpus_epoch != built_epoch` → **full rebuild** (reset watermark + epoch);
  else **incremental** — `MERGE INTO keyword_daily` using the tail (`id > last_mention_id`)
  grouped by `(keyword_id, day)`: MATCHED → add the deltas, NOT MATCHED → insert; then advance
  the watermark to `MAX(id)` processed. **The trap (grounded in this repo): `index_article`
  does delete-then-reinsert of an article's mentions (`store.py:248`), so the id-watermark
  MERGE-ADD is correct ONLY for APPEND (new articles → new higher ids). EVERY path that re-runs
  `index_article` over an EXISTING article — `reindex_all_batch`, `reindex_articles`,
  `reindex_imported_articles` (restore), the clean-up-keywords flow — and
  `prune_orphan_keywords` (deletes rows) MUST bump the corpus epoch and force a FULL rebuild,
  never an incremental MERGE, or the rollup double-counts (a fabricated number). Normal
  new-article ingest must NOT bump the epoch (or you full-rebuild every pass).** The full
  rebuild streams ~10^10 rows through Python → a resumable BATCH job scheduled WITH the
  re-index, never on the query path.
- **D4 — `source_coverage` rollup**:
  `source_coverage(country, source_id, articles, mentions, first_day, last_day,
  PK(country, source_id))` — same watermark/epoch machinery; serves per-country coverage
  without scanning the mention table.
- **D5 (OPTIONAL, OFF the critical path) — Roaring co-occurrence bitmaps** (pyroaring) for the
  SET-INTERSECTION queries the rollups don't help (co-occurrence / mind-map / actor-collapse):
  per-keyword article-id bitmap as an encrypted-DuckDB blob;
  `co-occurrence(X,Y) = popcount(bmp[X] AND bmp[Y])` in Python; precompute top-K neighbours
  offline for all-pairs. Behind a new optional extra (graceful-degrade if absent, like
  VADER/numpy), registry entry, rebuilt on epoch bump. Build only when the graph queries
  actually need it.
- **D1 (the unblock — SCAFFOLD + DOC, see 5B): the persisted encrypted DuckDB store.** Without
  it the columnar layer is RAM-bound and gives no gain over the counters (CLAUDE.md already
  found this for `build_keyword_read_model`). You write the offline-LOAD code; the maintainer
  supplies the binaries — see 5B.

**VERIFY checklist (lift into tests):** (1) `keyword_daily` SUM(mentions) == `SUM(count)` over
`keyword_mentions` for a sampled keyword set (exact). (2) windowed most-mentioned == live
ranking for a sampled window (exact on mentions). (3) windowed `COUNT(DISTINCT article_id)`:
columnar upper-bound vs live exact differ only where re-observation creates multi-day pairs;
the gap is reported, never hidden. (4) incremental refresh after a new batch == a full rebuild
(MERGE-add correctness). (5) a late-arriving historical-dated batch lands on the correct day
after incremental (id-watermark). (6) a simulated re-index (epoch bump) forces a full rebuild,
not incremental. (7) `analytics.duckdb` is unreadable as plaintext (encryption_gate passes with
the OpenSSL backend). (8) network blocked → opening the store + loading bundled httpfs makes
ZERO outbound connections (autoload off). (9) the bundled httpfs binary matches its pinned
SHA-256 before LOAD. (10) no ATTACH cipher other than the default authenticated GCM is ever
requested. (11) cold/missing `analytics.duckdb` → the seam falls back to the live query with
the correct basis flag, identical results. (12) Roaring co-occurrence(X,Y) == the live
two-keyword article-intersection count for a sampled pair (exact).

**Honesty guardrails:** `articles_on_day` is an UPPER BOUND when a (keyword,article) pair spans
multiple days — carry the basis flag (`columnar (upper bound)` vs `live (exact)`); the
live-exact escape is cheap PER-KEYWORD only, never corpus-wide. The rollup spans ALL history —
never recency-biased. Counts + basis flag only, never a composite score.

**Explicitly rejected — do NOT wander to these (the research red-teamed them):** chDB /
ClickHouse (unauthenticated AES-CTR / LUKS-punt — loses the in-engine authenticated encryption
that is the whole point), Turso/libSQL (solves write-concurrency you don't have, costs
SQLCipher), Tantivy (FTS5 scales to tens of millions of docs — keep it), ATTACH per-period
partitions of the canonical store (WAL has no cross-attach atomicity), and time-partitioning
the canonical store (already abandoned). Keep **DuckDB + FTS5 + ONE canonical SQLite file**.
In-engine vectors (sqlite-vec / sqlite-vector) are orthogonal (semantic search, not a scaling
lever, not dedup) — defer. Single-node is by intent; data volume is not the ceiling,
multi-writer would be (that's the separate Open Commons Mirror project).

### 5B. SCAFFOLD + DESIGN DOC — build the honest part, document the blocked part, never fabricate
- **Persisted encrypted DuckDB — the static-OpenSSL httpfs build (workstream 5A-bis D1):**
  DuckDB 1.4.2 forces the OpenSSL/httpfs backend for any encrypted write and AUTOLOADS httpfs
  over the network (forbidden offline); the built-in mbedTLS RNG was found insecure (advisory
  GHSA-vmp8-hg63-v2hp). So you **write the offline path**: `autoinstall_known_extensions=false`
  + `autoload_known_extensions=false`, `allow_unsigned_extensions=true`, `LOAD` from an
  **absolute in-app path**, **SHA-256 pin-and-verify the binary BEFORE load**, `ATTACH` with the
  **default authenticated GCM cipher and NEVER a CTR cipher** (the disclosed GCM→CTR downgrade
  attack), and flip `secure_crypto_available()` true only after LOAD + the `encryption_gate`
  probe confirms a real OpenSSL-encrypted file. Add the `configs/external_artifacts.yml`
  entries and the **DuckDB ≥1.4.2 ↔ bundled-httpfs version coupling** (test-enforced, like the
  existing crypto-extension coupling). **BLOCKED in-sandbox:** the per-OS/arch binaries
  (linux-amd64/arm64, macOS, windows-amd64) need a networked, multi-arch vcpkg static build =
  the maintainer's step. **Never fabricate a checksum or claim a binary exists** — ship the
  code + an empty, clearly-flagged pin table + the build recipe in the design doc.
- **Ollama binary installer** (remark 1): build the Settings→AI installer UI, hardware-tier
  scenarios, and the download-**and-verify** flow + Mistral-led model picker — but the per-OS
  installer **checksums must come from a networked machine**; leave a clearly-flagged empty
  checksum table + a design note. Never invent a checksum.
- **zh/ja keyword segmentation**: a design doc proposing a bundled offline segmenter + the
  seam; implement only if a no-network, license-clean option is honestly available (and then
  add its external-artifact registry entry).
- **Event-timed-op card / elections & civic vertical**: build the card/schema scaffold +
  design doc; the candidate **roster is maintainer-supplied data** — leave it a seam.

### 5C. DESIGN DOC ONLY (deferred / large / separate project)
- **LLM who/where/when + sentiment eval harness**, **Tor integration + per-source transport**,
  **voice-only mode**, **Open Commons Mirror** (a separate sister project — a doc here, no app
  code beyond existing seams). One `docs/design/*.md` each, its own PR.

### 5D. OPERATIONAL — note, do NOT rebuild
- Running keyword cleanup / baseline-tag backfill (tools/endpoints already shipped — the
  maintainer runs them on the live corpus); generating translation rings (networked machine,
  Wikidata blocked in CI); the per-OS/arch httpfs + Ollama binary builds (networked,
  multi-arch — maintainer); flipping 0.0.9 → 0.1 (release decision); human click-through
  (maintainer QA — flag per feature).

## 6. The per-step loop

1. **Scope it** (Explore agent → files/conventions/tests + what already exists).
2. **Branch** off the previous step's tip (or fresh `0.09` for step 1).
3. **Implement** — small, additive, matching surrounding code; migration + boot self-heal if
   you add a DB column; consolidation absorption-gated; never weaken a non-negotiable.
4. **Verify** — py_compile + ruff F,B + mypy(≤127) discipline / node --check / standalone
   repro; add the pytest test + the invariant guard; i18n 100%; spawn a review agent and
   hand-verify.
5. **Ledger** — write the shipped entry (or queue update) in `CLAUDE.md` the same turn.
6. **Commit** (clear message; **never** put the model identifier in any repo artifact;
   **never** use backticks inside a `git commit -m` heredoc), **push**, **open the draft PR**.
7. **Confirm CI green**, then start the next step on top.

## 7. Honesty non-negotiables (every step)

Local-first / loopback-only; no fabricated data, scores, security, or checksums; caveats
visible by default (never hidden behind a toggle); degrade loudly; cross-time recall is sacred
(no recency bias); the rule-based keyword index is the trusted layer and AI output is a
separate, clearly-labelled, unreliable layer that never feeds it; derived stores are disposable
and the canonical encrypted SQLite store is always authoritative. When in doubt, read the
relevant non-negotiable in `CLAUDE.md` and follow it exactly.

## 8. When something can't be finished autonomously

If a step's core needs the live corpus, a networked/multi-arch build, fabricated data, or a
maintainer decision: build the honest part (per 5B/5C), write a one-line ledger note with the
reason, and move to the next step. Don't stall, and don't fake it.

---

## Session execution note (harness constraint)

This session's harness locks development to the single branch
`claude/vibrant-thompson-bez6dq` (the git requirement: develop only there, never push
elsewhere). Per §2's fallback, that constraint wins: work is stacked as well-scoped commits on
that one branch under ONE draft PR to `0.09`. The maintainer merges on their own schedule.
Each "step" in §5 is still verified end-to-end before the next begins.
