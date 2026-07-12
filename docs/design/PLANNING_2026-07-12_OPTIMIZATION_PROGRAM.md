# Planning session 2026-07-12 — the optimization program (designs of record)

**Status:** DESIGN-ONLY. Product of the maintainer↔Fable-5 planning dialogue held WHILE the
S1–S6 autonomous program ran (the maintainer's standing instruction for that dialogue was
"please don't code — we will do only planning"). This doc is the durable record so a later
instance can make safe, sound decisions for later autonomous sessions **without re-deriving or
losing any of it**. Storage got its own plan doc
([`STORAGE_5TB_PLAN.md`](STORAGE_5TB_PLAN.md)) — everything else lives here.

**Binding context for any session executing from this doc:**
- The STALENESS GUARD (SESSIONS_2026-07-11_CONVENTIONS.md §1) applies to every item: these
  designs were written against the tree of 2026-07-12 (S3 merged); verify before building.
- Every design inherits the honesty non-negotiables (no composite scores; method + caveat + n;
  caveats visible by default; three provenance classes never blended; degrade loudly).
- Maintainer WORKFLOW ruling (2026-07-12): all coding goes through Claude Code CLI sessions
  (Opus 4.8, maximum effort); the web Fable-5 instance does thinking/planning/design and
  produces the briefs/kickoff prompts. This doc is that interface.

---

## §1 Deep keyword analytics — the multi-keyword lens ("Conjunction Lens")

**Maintainer intent (verbatim spirit):** analyze keyword PROXIMITIES, ORDER of appearance, and
AVERAGE PER-ARTICLE COUNTS; the flagship example — how does coverage treat "Trump × Climate":
what happens around one keyword when another is present. Explicit rulings: **keep BOTH ideas**
(the corpus-algebra sets AND the analytical lens); support **SEVERAL keywords, not just two**;
"the UI will greatly determine usefulness" (invest in the lens UI). Framed "for the good
interest of journalism and the common good."

### 1.1 Corpus algebra (the set layer)
For keywords K1..Kn, compute article-id SETS via `keyword_mentions` (article-id-indexed reads —
NEVER the keyword→articles codec join, the column-order perf trap): intersections (K1∩…∩Kn),
differences (K1∖K2, K2∖K1), unions. Each resulting set feeds the EXISTING analysis window via
`openAnalysisForIds` (the exact-set precedent) — so every subtab (keywords/mindmap/sentiment/
sources/WWW/links/trend) works on "articles mentioning both Trump AND climate" for free, with
zero new analytics code. The set expression is displayed as the corpus label (transparency).

### 1.2 The Conjunction Lens (a new analysis surface over N keywords)
- **Conditional trend:** share of K1-articles that also mention K2 (…Kn) over time — a
  disclosed ratio with n per bucket, honest sparse rendering (bars under `_SPARSE_BAR_MAX`).
- **Vocabulary contrast:** top terms of K1∩K2 vs K1∖K2 (what changes in the language when
  both are present) — counts only, side by side.
- **Silence lens:** sources covering K1 that NEVER co-mention K2 — with SAME-LANGUAGE cohort
  denominators (the #620 BURY lesson: a source is measured against its language slice, rings
  bridging labelled) — surfaced as a shape to investigate, never a verdict.
- **Lead/lag chronology:** within co-mentioning articles, which keyword appears FIRST
  (`KeywordMention.first_offset` ordering) and the offset distance distribution —
  co-occurrence-never-causation caveat on every view.
- **Per-article intensity:** average mentions-per-article (`count` column) for each keyword
  inside vs outside the intersection.

### 1.3 Three computation tiers (cost honesty)
- **T1 — stored aggregates** (always cheap): counts, co-mention counts, per-article averages
  from `keyword_mentions(count, first_offset, observed_on)` set intersections.
- **T2 — FTS5 NEAR** (no new storage): proximity queries via the positional index
  (`detail=full` today) for "within N tokens" questions. CJK caveat: the FTS tokenizer is
  unicode61 (≠ the B1 extraction segmenter), so NEAR over zh/ja is unreliable until the FTS
  CJK tokenizer lands (storage-plan watch list).
- **T3 — bounded deep pass** (on demand, visible): exact distances/order stats via re-scan of
  a BOUNDED article set (cap stated; a task-manager job if heavy). Never a corpus-wide sweep.

Perf discipline: `EXPLAIN QUERY PLAN` no-bare-SCAN rule on every new query; big set ops in
Python over id arrays, not SQL joins that drag article rows through the codec.

---

## §2 The card system — "Leads 2.0"

**Maintainer rulings (2026-07-12):** the card idea "should be elaborated even further"; some
cards are MORE IMPORTANT than others and some findings MORE INTENSE ("a rare word depicted in
10,000 articles bears more importance than … 10 articles"); the system should be "better
organized and smarter"; it gets **its own place in the Settings tab**; **there should be a
default** (good defaults + user control).

### 2.1 Evidence chips (importance made visible, never scored)
Every Lead renders a chip row of REAL numbers: **n** (articles) · **independence** (distinct
sources, the r-not-n doctrine) · **effect** (the producer's own measured magnitude — rate
ratio, gap days, byte delta — whatever it already computes) · **freshness** (newest evidence
age). Each chip is a fact with a hover explaining its method. NO composite score ever
(`CardSchemaError` stands); "importance" is the user READING the chips, aided by ordering.

### 2.2 Transparent ordering + user sort
Ordering is LEXICOGRAPHIC over disclosed keys (evidence tier → magnitude bucket → recency),
with a "why is this first?" hover stating the comparison, and a user-facing SORT control
(by n / by sources / by recency / default). An ordering the user can inspect and override is
honest; a hidden blend is not.

### 2.3 Major-leads floor (user-owned thresholds)
A Lead is flagged **major** when it clears user-set floors — default **n ≥ 50 AND ≥ 5
independent sources** (the recorded default; tune on field data). Major leads get the visual
tier + optionally pin to the Home strip. Thresholds live in Settings → Leads; the flag is a
threshold FACT ("n=120 ≥ 50"), never a judgment.

### 2.4 Lifecycle + story clustering
- **Lifecycle:** cards carry identity (the existing `key`); re-emissions show deltas
  ("strengthened: n 120→180, +2 sources") instead of appearing as fresh cards; genuinely new
  = "new". Dismissed state persists (with the existing reversibility conventions).
- **Story clustering:** group Leads whose `article_ids` sets overlap (Jaccard over id sets —
  reuse the near-dup set math) into one "story" stack, so five producers firing on the same
  event read as one investigation with five lenses, not five cards.

### 2.5 Settings → Leads subtab (the ruled home)
ooSubtabs grammar (#18): per-producer enable/disable (the `recipes.py` toggles surfaced) ·
major-floor thresholds · default sort · story-clustering on/off · the existing bucket
descriptions. ×12 locales; every control titled (hover convention #17).

---

## §3 Keyword fingerprints — the same-skeleton echo tier

**Maintainer intent:** detect articles that are "not purely identical, but have the exact same
keywords" — coordinated/templated content that whole-text near-dup misses.

Three echo tiers, each already-or-now covered: (1) verbatim span → the copypasta card;
(2) near-identical TEXT → echo_chamber (MinHash over text); (3) **NEW: same keyword SKELETON**
— different words, same extracted-keyword structure.

- **Exact fingerprint:** a stored derived column = hash over the article's sorted keyword-id
  set (the derived-but-stored precedent, like sentiment columns); equal fingerprints across
  DISTINCT sources = the strongest form. Maintained through the ONE `index_article` hook so
  re-index keeps it honest.
- **Fuzzy skeleton:** MinHash-LSH REUSING `src/signals/near_dup.py` machinery with
  keyword-ids as the token stream (instead of text shingles) — high-Jaccard keyword-set
  overlap without text similarity.
- **Ordered skeleton (stretch):** compare keyword APPEARANCE SEQUENCES (`first_offset` order)
  — same keywords in the same order is stronger evidence of a shared template than the same
  set alone.
- **Card:** a `skeleton_echo` producer — fires on ≥3 DISTINCT sources sharing a skeleton
  while NOT being text near-dups (excludes what tier 2 already owns); single-source repeats
  flagged `single_source`, never called coordination; innocent explanation stated beside the
  pattern (same wire template / genuine topic convergence); counts only, exact `article_ids`
  carried (the F1 discipline).
- **Cross-language phase 2:** map keyword-ids → RING ids before fingerprinting, so the same
  story skeleton is detectable ACROSS languages (the rings make it possible; label the
  ring-bridge in the method).

---

## §4 Search at scale — instrumentation FIRST

**Maintainer ground truth (verbatim):** "The logs will tell you the honest truth after
searches. Currently it is still not snappy / never instant." So: no optimization before
measurement.

- **Phase 0 (build first): a per-search timing breakdown** — FTS MATCH ms · content/row fetch
  ms · serialization ms · (client) render ms — logged per query into the perf diagnostics
  (the `slowquery.py`/S2.7 snappy-bar precedent), exported with the routine diagnostics zip.
  The next optimization is chosen by the measured dominant term, not by theory.
- Ranked candidate levers (post-measurement): the fts.db split (storage plan §3-B — smaller
  hot file, no boot rebuild) · FTS merge budgets (automerge/crisismerge + quiet-window
  incremental `merge`, riding S2.2 idle maintenance) · commit batching (fewer level-0
  segments — P1.8 already helps) · result-row hydration cost (avoid dragging `content`
  through the codec for list views) · at the far end, sharding (storage plan §3-bis).
- The snappy bar stays the S2.7 instrument's p95-vs-500ms verdict.

---

## §5 Tor throughput

- **Bandwidth priority ladder as a TOKEN-BUCKET scheduler** across job kinds — the ruled
  ladder (1 markets/commodities/weather → 2 interactive DDG → 3 RSS → 4 recursive crawl),
  implemented as budget allocation, with the standing rule ORDERING ≠ EXCLUSION (every kind
  retains a floor; no source starved; the 6h-cap style guarantees stand).
- **Segmented HTTP-Range downloads** of big dumps over MULTIPLE isolated circuits
  (`IsolateSOCKSAuth` per segment — the SCRAPING_AUTOMATION_PLAN Step-3 item), aggregate
  N-circuit throughput without touching per-host politeness (segments hit the same host —
  respect a per-host cap; mirrors below help).
- **Measured mirror selection** (Step 4): pick dump mirrors by measured throughput over Tor,
  disclosed; never silently downgrade transport (non-negotiable).
- Task-manager surfaces the ladder's live allocation (the "which job gets bandwidth and why"
  transparency the ledger already promises).

---

## §6 Frontend verification — the three-tier model + the AppVM recursive environment

**Maintainer rulings (2026-07-12):** runs coding through Claude CLI in a persistent Qubes
AppVM (Firefox preinstalled); asked whether an OOS instance there creates a recursive
improvement environment — **"If this is possible, then we should go for it."** Screenshots
give the agent literal eyes (multimodal review).

### 6.1 The three tiers (replaces fork-3's "no browser" premise)
- **T1 — CI headless-Chromium smoke** (observation lane first; graduates when stable).
- **T2 — in-session self-verification:** cloud sessions use the preinstalled Chromium +
  screenshots to review their own UI work.
- **T3 — the AppVM station:** Claude CLI + **Firefox (Gecko)** + synthetic corpus = the
  cross-engine verification bench; the HUMAN keeps UX/taste judgment.
- **Convention amendment (to formalize with the first VM session):** frontend verified in the
  VM graduates from "browser-unverified · flagged" to **"Gecko-verified (VM) · awaiting human
  UX pass."** Cloud Chromium + VM Firefox = cross-engine coverage for free.

### 6.2 The recursive improvement loop
code → run the app → observe (screenshots + browser console + the app's OWN diagnostics
endpoints: keyword-selftest, engine report, rollup-benchmark, article-length, debug bundle) →
fix → re-run → PR. The app's diagnostics were designed as "export and send to Claude";
co-located, the agent curls them directly — the instruments improve, which improves the loop.

### 6.3 SAFETY LINES (binding rules for any agent session in the VM)
1. **Synthetic corpus ONLY** for agent-driven instances — generated by the GAMMA/scale
   harness into a dedicated `OO_DATA_DIR`, **ENCRYPTED under a known test passphrase**
   (plaintext test stores are blind to the SQLCipher codec-path perf traps).
2. **The REAL corpus never enters an agent session.** An agent reading it would ship corpus
   content to a third-party API — the exact thing the never-host-user-data ethos forbids.
   The safe channel for real-corpus insight stays the diagnostics EXPORTS (counts/structure,
   not content), maintainer-reviewed before sharing.
3. **App lifecycle discipline:** the session starts/stops the app per verification pass;
   never leave it running across a branch switch (the 2026-07-09 mutated-tree lesson,
   doubled for a live server importing from the tree).
4. **Airplane by default**; fetch-path testing via a loopback fixture server; going genuinely
   online from the VM is the maintainer's per-run choice, never the agent's default.

### 6.4 Setup runbook (operator, ~30 min) + first-session queue
(1) clone + `python3.13 -m venv .venv` + `pip install -e ".[analysis,dev]"` + full
`pytest -q` + mypy ratchet once — certifies the VM (py3.11-only ⇒ the ledger's CI-only
fallbacks, and know it now); (2) `ollama list` + GPU visibility check (Qubes AppVMs normally
lack GPU passthrough — run the §8 bench wherever Ollama runs in production); (3) generate the
synthetic corpus, note the test passphrase; (4) `firefox --headless --screenshot` smoke
against the booted app; (5) the FIRST VM session builds **`ui_walk`** (boot → walk every
tab/subtab → per-surface screenshot + console-error dump) — the reusable instrument — then
starts the "browser-unverified" click-through burn-down (each verified surface flips its flag
in a PR), then stands up the §8 triage-bench scaffold. Persistent VM assets: synthetic
corpora, **screenshot baselines (a growing visual-regression asset)**, the Ollama store,
long-running jobs.

---

## §7 Power profiles (the memory-budget answer)

**Maintainer ruling (2026-07-12, upgrading the "low-memory mode" draft):** power management
must be USER-ACTIVATABLE with three levels — **Low power / Optimized / Max power** — "each
should have an effect on memory management, scraping management, and so forth."

- **A profile is a TRANSPARENT PRESET over a PUBLISHED knob table** (every value visible in
  Settings, per-knob overrides allowed): SQLite `cache_size` · collect parallelism · pass
  budget/cadence · rollup residency (in-memory serve on/off) · poll cadences · FTS merge
  budget · LLM keep-alive. Indicative shape: Low ≈ 32 MiB cache / 1–2 workers / rollups
  cold / sparse polls / keep_alive 0; Optimized = today's defaults; Max ≈ big cache /
  high parallelism / rollups resident / keep_alive -1. Exact values are MEASURED on the
  GAMMA harness before shipping, not asserted.
- **Suggest, never silently switch:** the memory guard may PROPOSE dropping a level under
  pressure (a visible, dismissible suggestion naming the measured trigger); the app NEVER
  auto-switches. The active profile is always visible (task-manager System tab).
- Honest framing: profiles change RESOURCE SPEND, never data visibility or caveats — no
  profile may hide data, skip caveats, or degrade honesty surfaces.

---

## §8 LLM keyword triage — the design + the SEVEN-model bench

**Problem + maintainer rulings:** ~3.06 M keywords carry junk and mis-tagged kinds
("Organizations tagged as Persons"); hand curation "cannot be handled by hand" (ruled).
Maintainer's design (endorsed + refined): a TEMPORARY in-app button sends keywords to a local
Ollama model (small model, 8 GB VRAM class) which outputs FILES "digestible by Claude" for
verification/correction. Timestamps ruling: logs must carry timing so the strategy's cost is
COMPUTED ("if one week, do it; if 10 years, change strategy"). Bench ruling: a SEPARATED
testing phase first, "a batch of a few hundred keywords," comparing the candidate small
models.

### 8.1 The production pipeline (design)
- **Scope: head-first** — the top ~100–200 K keywords by ARTICLE SPREAD (not all 3 M); the
  long tail is mostly hapax noise the analytics barely surface. Batches of 50–100 keywords
  per prompt, each with: term · language · counts (mentions/articles) · 1–2 context snippets.
- **Constrained verdicts, validated:** `junk | content | unsure` + kind
  `person | org | place | other`; the response must ECHO each keyword exactly (echo-back
  validation — a mangled term = invalid); malformed items are counted, never guessed.
- **EXPORT-ONLY: JSONL files.** The model NEVER writes the trusted index. Claude (CLI)
  verifies stratified samples and emits the DETERMINISTIC artifacts as reviewed PRs:
  scoped stoplist additions (retroactive at query time — no migration), a kind-override
  file, denylist entries, extractor-rule improvements. Provenance chain on every artifact:
  **ai-proposed · claude-verified · maintainer-merged**.
- **Canaries:** 2–3 anchor keywords with known verdicts sprinkled into EVERY production
  batch; a batch whose canaries fail is flagged for re-run (continuous QA riding the log).
- The digest doubles as the first measured dataset for the S6.5 perception eval harness
  (per-stratum reporting with n, hallucination rate vs the rule-based baseline).

### 8.2 The JSONL timing schema (the timestamps ruling)
Per batch record: `started_at`/`finished_at` (ISO UTC) · **Ollama's own measured fields
passed through verbatim** (`total_duration`, `load_duration`, `prompt_eval_count`,
`prompt_eval_duration`, `eval_count`, `eval_duration`) · `model` + `model_digest` (from
`ollama list` — a silently-updated tag stays distinguishable) · `keywords_in` /
`verdicts_out` / `parse_failures` / `unsure_count` · run header: hardware fingerprint
(GPU/VRAM or CPU, RAM). First-batch `load_duration` reported separately (with `keep_alive`
holding the model resident, steady-state throughput is not polluted by load time).
**The ETA line the log prints:** `ETA = remaining_keywords ÷ (valid_verdicts ÷ Σ batch_wall_s)`
— throughput counted in VALID verdicts/sec. Sanity envelope (to be REPLACED by measurement):
a 4B-class Q4 model ≈ 1–3 valid verdicts/sec ⇒ head scope ≈ 1–2 days unattended; full 3 M ≈
2–4 weeks. The run is cursor-resumable (background work, not a blocked machine); it composes
with §7 as a Max-profile / idle-hours job.

### 8.3 The bench (separated test phase — run BEFORE production)
- **Roster (7, maintainer-named):** gemma4:e4b · mistral:7b · granite4.1 · qwen3.5:4b ·
  translategemma:4b · nemotron-3-nano:4b · ministral-3:3b. **HARD RULE: every tag is verified
  against the local `ollama list` before the run; the bench REFUSES an uninstalled tag and
  never substitutes a "close" one** (the hallucinated-catalog lesson; as of the Fable
  knowledge cutoff the closest known tags were gemma3n:e4b / granite4 / qwen3 — newer tags
  may be real on the maintainer's machine; tag + digest recorded per run either way). All
  3–7B Q4 candidates fit 8 GB VRAM; total store cost ~20–30 GB (prune losers after).
- **The frozen test batch (~400–500 keywords, built once):** stratified across languages
  (floor ~20 each) × article-spread deciles × current kind tags; deliberately seeded with
  adversarial cases (acronyms WHO/US, org-vs-person confusions, cross-language homographs
  en"content"/fr"content", platform boilerplate) + real content controls. Inside it, a
  **~50-keyword ANCHOR SET the maintainer hand-grades once** (the micro-gold-set — turns
  "models agree" into "models are right"). Keyword order randomized once then FROZEN —
  all models see byte-identical prompts; temperature 0; models run sequentially.
- **Metrics — each reported ALONE, never blended:** valid verdicts/sec · format-validity
  rate (parse failures, skipped items, echo-back mismatches) · %unsure · accuracy vs anchors
  (junk precision/recall SEPARATE from kind accuracy) · pairwise inter-model agreement
  (21 pairs) including whether a **consensus-of-two-cheap-models** beats the single best on
  junk (if yes: production runs two fast models with agreement-gating).
- **Batch-size sweep** on the leader (25/75/150 keywords/prompt) — small models degrade on
  long contexts; item-skipping appears first; pick the operating point on validity × speed.
- **translategemma side-bench:** a translation specialist likely lags on constrained
  classification (measure, don't assume) — but give it its OWN task: translate ~50 keywords
  that ARE in verified Wikidata rings, score against the ring members we already trust. If it
  wins there, it becomes the designated **ring-translation LLM fallback** model (the ruled
  tentative/flagged channel for un-ringed keywords) regardless of its triage rank.
- **Venue:** run the bench wherever Ollama runs in PRODUCTION (the 8 GB VRAM box) — a
  CPU-only AppVM bench answers the strategy question but understates the real rig (§6.4-2).
- Wall-clock: roughly an afternoon (7 × ~500 keywords at 1–3/sec + downloads + the sweep +
  the side-bench).

---

## §9 Sequencing (recommended adoption order, post-S1–S6)

1. **AppVM certification + `ui_walk`** (§6.4) — multiplies every later session.
2. **Search timing instrumentation** (§4 Phase 0) + the storage plan's Phase-A deltas —
   small, measurement-first.
3. **The triage BENCH** (§8.3; needs the maintainer's ten minutes of anchor grading), then
   the head-first production run + the first artifact PRs.
4. **Leads 2.0** (§2) and the **Conjunction Lens** (§1) — the two big product designs; each
   is its own session-sized brief when scheduled.
5. **Keyword fingerprints** (§3) — after the triage batch has cleaned the worst junk (a
   cleaner keyword layer makes skeleton matching sharper).
6. **FTS sharding prototype + Phase-C spike** per the storage plan (§3-bis/§9 there).
7. **Tor ladder + segmented downloads** (§5) when a scraping-focused session is scheduled.
8. **Power profiles** (§7) after GAMMA-measured knob values exist.

Every item: verify-against-tree first, skeptics-before-push, honest ledger rows — the
standing program discipline.
