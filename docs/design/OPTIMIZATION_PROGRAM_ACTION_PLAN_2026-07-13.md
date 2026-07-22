> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — the §1–§8 buildable-now optimization cores plus R1/R2/R4 are all confirmed SHIPPED. R3 (the `ui_walk` AppVM runner — still scaffolding, no real browser) and R6 (a real graded IR gold set) remain exactly as operator/browser-gated as this doc anticipated. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Optimization-program action plan (2026-07-13)

**What this is.** A per-phase, build-class-tagged action plan for
[`PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md`](PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md)
(§1 Conjunction Lens · §2 Leads 2.0 · §3 keyword fingerprints · §4 search
instrumentation-first · §5 Tor throughput · §6 recursive improvement · §7 power
profiles · §8 LLM keyword triage · §9 sequencing). It is the durable bridge from
that design doc to session-sized, honest, draft-PR work.

**Binding context.**
- **Staleness-guarded against `origin/0.2` @ `13223498`** (S1–S6 + the 2026-07-13 audit→fix→build
  pipeline all merged). Every "already built / not built" claim below was verified by a
  read-only agent fan-out (per-section scouts + a cross-section critic) against the current
  tree, **not** the 2026-07-12 doc snapshot. The critic found **zero staleness errors**; the
  program's staleness guard (SESSIONS_2026-07-11_CONVENTIONS §1) still applies at build time.
- **Nothing auto-merges.** Every slice is a DRAFT PR the maintainer accepts or rejects — that
  review is the safety gate. Skeptics-before-push (negative-space lens mandatory for any
  parser/extractor, #590). Shared files (CLAUDE.md Open-queue, `shipped.csv`, ROADMAP) edited
  APPEND-ONLY.
- **Honesty non-negotiables inherit.** No composite scores (`assert_no_score_fields` is
  import-time-enforced; a field named `*score*`/`*ranking*` fails it), method+caveat+n on every
  signal, three provenance classes never blended, degrade loudly, never fabricate a number.

## Build-class legend

| Tag | Meaning |
|-----|---------|
| **BUILDABLE-NOW** | Measurement-first, non-networked, **unit-testable without a browser/Ollama/GPU/network/live-corpus**. The project pattern: prove the pure algorithm here with a standalone repro; leave the networked/hardware call as an injected seam. |
| **OPERATOR-GATED** | Needs the maintainer's rig: a live encrypted corpus, network egress, a running Tor SOCKS proxy, an Ollama box with the model(s), a GPU, or a hand-graded gold set. |
| **BROWSER-GATED** | Frontend that ships conservative + flagged (`node --check` + invariant guard), browser-unverified per fork-3 (no headless browser in-session). |
| **DESIGN-ONLY** | Ruling-heavy or VM-environment work — its own design/runbook, not code this cycle. |
| **VERIFIED-PRESENT** | Staleness guard paid off: already shipped; verify-and-mark, never rebuild. |

## Shared foundations (reuse map — so no phase rebuilds another's primitive)

The critic surfaced these as depended-on by ≥2 phases. **Reuse, never re-implement:**

| Foundation | Anchor | Reused by |
|-----------|--------|-----------|
| `near_duplicate_clusters` / `minhash_signature(set[int])` / `jaccard_estimate` / `_connected_components` | `src/signals/near_dup.py:308/164/186/250` — `minhash_signature` is already token-agnostic (keyword-ids drop in) | §2 story-clustering, §3 skeleton echo |
| Head-by-article-spread SELECT (`ORDER BY Keyword.article_count DESC`) | `src/analytics/queries.py:294`, `engine_report._generic_terms` | §6 generic-terms, §8 head-scope selection |
| Phase-timing + bounded-JSONL | `unlock._forensic_timer.phase/finish` (`src/api/unlock.py:263`); `collect_perf._append_jsonl/_trim_jsonl` (`src/monitoring/collect_perf.py:132/142`) | §4 search timer, §8 triage JSONL |
| Latency reservoir + percentile | `src/monitoring/latency.py:111/122` | §4 per-phase aggregate, §5 mirror ranker |
| `_all_diagnostics_members` (20-member aggregator, single source of truth) | `src/api/diagnostics.py:2143` | §6 recursive loop |
| `ooSubtabs` Settings/facet framework | `src/static/app.js:8325` | §2 Settings→Leads subtab, §7 profile chip |
| `assert_no_score_fields` (import-time no-composite guard) | `src/briefing/card.py:76` | every phase's honesty gate |
| `_resolve_corpus` / `openAnalysisForIds` (seed the analysis surface from an id set) | `src/api/insights.py:222`, `app.js` | §1 conjunction result → analysis window |
| `corpus_tier` (early/developing/established maturity) | `src/briefing/producers.py:107` | §2 ordering, §1/§8 early-corpus caveats |

---

## §1 — Conjunction Lens (deep keyword analytics over N keywords)

**State.** Single-SEED analytics are mature (`associations`/PMI, `trend`, `corpus_keywords`).
The set-algebra SUBSTRATE already exists but is private to `layered_graph`: `_article_set(session,
terms)` = the DISTINCT article-id UNION over N terms (`queries.py:2146`); `_overlap_edges` =
pairwise INTERSECTION cardinality (`:2161`). No public N-keyword surface; no endpoint takes a LIST
of terms; **FTS5 NEAR is entirely absent** (`build_match` emits only AND/OR/NOT).

- **BUILDABLE-NOW** — `corpus_algebra(session, terms, op∈{intersection,difference,union})` → the
  combined article-id set + per-term n + combined n, promoting the private `_article_set`
  intersection/difference to a public, tested function. The result is an id set that seeds the
  whole existing analysis surface via `_resolve_corpus`/`openAnalysisForIds` for free. Test: pure
  SQLAlchemy over an in-memory corpus.
- **BUILDABLE-NOW** — `conditional_trend` + `per_article_intensity` as thin wrappers feeding the
  intersection id set into the existing `trend` bucketer + a `GROUP BY (article_id, keyword_id)`.
- **BUILDABLE-NOW** — `vocabulary_contrast(setA, setB)` = difference of `corpus_keywords` per-term
  article-spread, **as a count delta with each side's n shown** (never a `*score*` field).
- **BUILDABLE-NOW (pure half)** — extend `build_match`/`_render` to emit `NEAR(...)`; the pure
  parse→MATCH-string emission is testable. Executing it against a real FTS index is OPERATOR-GATED.
- **BROWSER-GATED** — the N-keyword picker UI + wiring the result into the analysis-window tab.
- **OPERATOR-GATED** — perf validation of the `IN()` intersection at 974k-keyword / 5 TB scale.
- **Honesty:** the set expression is the transparent corpus label; contrast/silence are count
  differences with n, never verdicts; co-occurrence-never-causation on lead/lag; silence surfaced
  as a shape to investigate (the #620 same-language-cohort lesson).

## §2 — Leads 2.0 (card system elaboration)

**State.** The spine is mature + honesty-clean: `Card` already carries `_trigger` (evidence tier),
`article_ids`, `title_i18n`/`title_vars`, `n`, `key`, `signal`+`method`+`caveat`; `corpus_tier`
rides the briefing. The **specific elaborations are unbuilt**: no evidence-chip ROW, no
distinct-sources/effect/freshness quartet, ordering is a simple 2-key sort, no major-leads floor,
no Settings→Leads subtab, no story-cluster stacking, no user sort.

- **BUILDABLE-NOW** — `newest_evidence_age(card, now)` freshness primitive (degrade to None when no
  dated evidence).
- **BUILDABLE-NOW** — `order_key(card)` = the disclosed lexicographic tuple (evidence-tier rank →
  magnitude bucket → −recency) + `explain_order(card)` for the "why is this first?" string. Pure;
  replaces `service._sorted`.
- **BUILDABLE-NOW** — `is_major(card, floors={min_n:50,min_sources:5})` → a threshold FACT string
  ("n=120 ≥ 50 AND 6 sources ≥ 5"), never a judgment.
- **BUILDABLE-NOW** — `cluster_by_article_ids(cards, threshold=0.5)` = Jaccard over `article_ids`
  sets via the shared `_connected_components`/`jaccard_estimate` (reuse §-shared foundation).
- **BUILDABLE-NOW** — `card_deltas(prev, new)` lifecycle diff (new|strengthened|weakened|unchanged
  + the (n, sources) delta); the persistence of prev-state is a follow-up.
- **BROWSER-GATED** — the Settings→Leads subtab (plugs into `ooSubtabs`), evidence-chip ROW render,
  user sort control, "why first?" hover, per-producer enable/disable surfaced from `recipes.py`.
- **OPERATOR-GATED** — tuning the major-floor defaults on real field data.
- **Honesty:** every chip a real number with a method hover; importance = the user reading the
  chips aided by a disclosed ordering; NO composite score ever.

## §3 — Keyword fingerprints (same-skeleton echo tier)

**State.** The near-dup machinery is ideal to reuse: `minhash_signature(set[int])` is token-agnostic
(keyword-ids drop in without touching it); `first_offset` is stored per (article,keyword);
`actor_signature` is the exact sorted-set-hash template; the ≥3-distinct-sources gate exists in
`echo_chamber`. **Nothing skeleton-specific is built.**

- **BUILDABLE-NOW** — `skeleton_fingerprint(keyword_ids: set[int]) -> str` (blake2b over the sorted
  id set, mirroring `actor_signature`); `skeleton_clusters(docs: dict[str,set[int]], threshold)`
  feeding each set straight into `minhash_signature` (bypassing `shingles`); an ordered-skeleton
  comparator over `first_offset`-sorted sequences (LCS-ratio / ordered-shingle Jaccard). All pure.
- **BUILDABLE-NOW** — `skeleton_echo` producer assembly given precomputed clusters (≥3 distinct
  sources, cluster NOT a text near-dup): a Card with method+caveat+n, single-source flagged
  `single_source`, innocent explanation stated beside the pattern, exact `article_ids` carried.
- **OPERATOR-GATED** — persisting the fingerprint (schema change + migration + corpus-scale
  backfill through `index_article`) and wiring the producer into `refresh_briefing` on the live
  encrypted corpus.
- **Sequencing:** per §9, this lands AFTER the §8 triage batch cleans the worst junk (a cleaner
  keyword layer sharpens skeleton matching).

## §4 — Search instrumentation FIRST (per-search timing breakdown)

**State.** Both SUPPORTING instruments exist: the S2.7 snappy p95-vs-500ms latency reservoir
(`latency.py`, per-ROUTE) and the slowquery EXPLAIN no-bare-SCAN instrument (`slowquery.py`), both
in the debug bundle. **The parked slice itself is unbuilt**: no per-SEARCH intra-request breakdown
(FTS MATCH ms / content-fetch ms / serialization ms), no search-timing JSONL schema.

- **BUILDABLE-NOW** — `SearchPhaseTimer` mirroring `unlock._forensic_timer`: `phase(name)` →
  `{phase, ms}`; `finish()` → `{phases, total_ms, method, caveat}`. A bounded per-route aggregate
  reuses the `latency.py` reservoir + `_pct` percentile. The JSONL log reuses
  `collect_perf._append_jsonl`.
- **OPERATOR-GATED** — the actual per-phase ms on the live 100–130 GB encrypted corpus (which phase
  dominates decides the §4 lever); end-to-end TestClient wiring (needs the crypto extra) is CI.
- **Honesty:** measurements only; the next optimization is chosen by the measured dominant term,
  never by theory.

## §5 — Tor throughput (bandwidth ladder + segmented downloads)

**State.** The per-kind token-bucket ladder does NOT exist. What exists: an AIMD `BandwidthGovernor`
(varies WORKER COUNT to a KiB/s target, not a per-kind budget) and the `country_priority` stable
sort (ordering-not-exclusion, per-COUNTRY). Circuit isolation is genuinely built
(`_with_stream_isolation` injects per-token SOCKS auth, per-host/per-URL). **Segmented multi-circuit
Range download and measured mirror selection are absent** (`dump_url` hardcodes one host).

- **BUILDABLE-NOW** — `KindLadder(rates, floors, now=injectable)` pure token-bucket emitting an
  admission ORDER honoring per-kind floors (ordering ≠ exclusion, every kind keeps a floor).
- **BUILDABLE-NOW** — `plan_segments(total, n, min_seg)` + `reassemble(parts)` byte-range math with
  an integrity check; `rank_mirrors(samples)` pure ranker over injected {latency, ok, size} probes
  (method+caveat+n per candidate).
- **OPERATOR-GATED** — the real multi-circuit GET over live Tor, Accept-Ranges/206 negotiation,
  populating + probing the mirror list, wiring the ladder into `run_scrape_once`.
- **Honesty:** never silently downgrade transport (non-negotiable); ordering ≠ exclusion; per-host
  politeness never traded for speed.

## §6 — Recursive improvement (AppVM env + ui_walk + diagnostics self-observation) ★

**State.** The diagnostics self-observation loop is deep: a full `/api/diagnostics/all` (+ cancellable
`all-job`) aggregator whose membership is the single source of truth `_all_diagnostics_members`
(`diagnostics.py:2143`) — currently **20 members**. `ui_walk` is CONCLUSIVELY ABSENT (zero hits for
ui_walk/screenshot/playwright/selenium). The recursive-loop's own gates (`article-length`,
`keyword-growth`, `perception-eval-selftest`, `ir-eval-selftest`) exist as endpoints **but are NOT in
the aggregator**, and there is **no membership contract test** guarding it.

- **BUILDABLE-NOW (this cycle)** — a **recursive-loop diagnostics self-inventory** instrument: given
  the membership list, report per-instrument `{present, importable, last_error}` counts-only — the
  measurement-first proof that the loop's instruments are all wired (§6.2 "the instruments improve,
  which improves the loop"). Add the 4 missing cheap recursive-loop members to
  `_all_diagnostics_members`. Add the membership CONTRACT test (the guard that does not exist today,
  so no future edit silently drops a loop instrument). All pure/testable, decrypt-light, no browser.
- **DESIGN-ONLY (runbook)** — the §6.4 AppVM certification runbook + the §6.3 four binding safety
  lines (synthetic ENCRYPTED corpus only; the real corpus NEVER enters an agent session; app stopped
  across branch switches; airplane default) + the §6.1 convention amendment ("browser-unverified ·
  flagged" → "Gecko-verified (VM) · awaiting human UX pass").
- **BROWSER/OPERATOR-GATED** — the `ui_walk` instrument itself (boot→walk every tab/subtab→screenshot
  + console-error dump) needs a headless browser (playwright/selenium, ABSENT here); the AppVM
  recursive-improvement runner needs the maintainer's VM.
- **Honesty:** counts-only; the self-inventory reports `importable:false`/`last_error` loudly, never a
  fabricated green.

## §7 — Power profiles (Low/Optimized/Max preset over a published knob table)

**State.** The design is fully specified; ZERO profile code exists. But 6 of the 7 named knobs are
already live `OO_*` env vars / settings (`cache_size`, collect parallelism, pass budget/cadence,
rollup residency, FTS merge, LLM keep_alive); the gap is poll cadence (hardcoded) and the FTS
`analysis_limit` literal.

- **BUILDABLE-NOW** — `src/config/power_profiles.py`: a `PUBLISHED_KNOBS` registry (name, env_var,
  unit, kind, optimized_default) over the 6 env-backed knobs; `PROFILES = {low, optimized, max}`;
  `resolve_effective(profile, overrides)` → the effective values. Pure/testable. Wire
  `OO_FTS_ANALYSIS_LIMIT` (replacing the `1000` literal) + `OO_POLL_*` cadences into the table.
- **OPERATOR-GATED** — the exact Low/Max numeric values (§7 says MEASURED on the GAMMA synthetic
  harness before shipping); live re-application of a changed `cache_size` to a running engine.
- **BROWSER-GATED** — the active-profile chip in the task-manager System tab + the dismissible
  suggest-a-lower-level proposal.
- **Honesty:** a profile changes RESOURCE SPEND only — never data visibility or caveats; the app
  suggests, never silently switches; the active profile is always visible.

## §8 — LLM keyword triage (design + the pure testable core + the 7-model bench) ★

**State.** The triage pipeline is ABSENT (no batch→Ollama→{junk|content|unsure}+kind classifier, no
echo-back/canary validation, no EXPORT-ONLY JSONL, no head-scope selection, no timing schema/ETA, no
7-model bench). Directly mirror-able: the `OllamaClient` seam (`generate` already parses
`prompt_eval_count`/`eval_count`; `list_installed`/`is_available`; kill-switch + loopback guards),
the `ai_layer` pure-vs-networked split (`extract.parse_terms`/`extract_terms` + `jobs.extract_for_
articles`), and the `perception_eval` harness+stub-selftest+diagnostics-endpoint blueprint. This box
has Ollama installed but **server down, 0 models, no GPU** — so, exactly as §8.3 predicts, it is not
the bench venue; the core ships measure-first with the model run left to the operator.

- **BUILDABLE-NOW (this cycle)** — the pure/testable core, Ollama = injected seam:
  - `build_triage_prompt(items, canaries)` — batch (term·language·counts·1–2 snippets), constrained
    verdicts, echo-back requirement.
  - `parse_verdicts(raw, expected_terms)` — per-keyword `{term, verdict∈junk|content|unsure,
    kind∈person|org|place|other}`, **echo-back validation** (a mangled/absent term = invalid),
    malformed items COUNTED never guessed. Mirrors `parse_terms`.
  - `check_canaries(verdicts, canary_expected)` — flag the batch for re-run on any canary mismatch.
  - `batch_record(...)` — the JSONL timing schema (pass-through Ollama fields + model + `model_digest`
    + keywords_in/verdicts_out/parse_failures/unsure_count); `eta_line(remaining, valid, wall_s)`.
  - `select_triage_head(session, limit)` — head scope `ORDER BY Keyword.article_count DESC`
    (reuse the shared head-select foundation), returning term·language·counts + bounded snippets.
  - EXPORT-ONLY JSONL writer — the model **NEVER writes the trusted index** (honesty by construction;
    an invariant test asserts zero `KeywordMention`/`Keyword` writes on the triage path).
  - `verify_roster(requested, installed)` — the bench HARD RULE: REFUSE any tag not in `ollama list`,
    never substitute a "close" one (the hallucinated-catalog lesson).
  - The bench METRICS each reported ALONE (no composite): valid-verdicts/sec, format-validity rate,
    %unsure, anchor accuracy (junk P/R SEPARATE from kind accuracy), pairwise agreement.
  - Deterministic ARTIFACT proposals (scoped stoplist additions, kind-override file) carrying the
    provenance chain `ai-proposed` (claude-verified · maintainer-merged added downstream) — PROPOSE,
    never auto-apply (the `analyze_keyword_log.py` discipline).
  - `run_triage_selftest()` — prove the MECHANISM against a STUB client (known verdicts incl. a
    mangled echo + a failed canary + an unsure), asserting parse/validate/canary/metrics — mirrors
    `run_perception_eval_selftest`; exported as a diagnostics endpoint so a regression reddens both
    the in-app self-test and CI.
- **OPERATOR-GATED** — the actual batch run (keywords→local Ollama→verdicts) on the maintainer's rig;
  the 7-model bench (needs the roster installed, tags verified vs `ollama list`); the ~50-keyword
  ANCHOR SET hand-grading; the steady-state throughput/ETA numbers (the 1–2-days vs 2–4-weeks
  decision); emitting the artifacts as reviewed PRs.
- **Honesty:** EXPORT-ONLY (never the trusted index); constrained verdicts validated; malformed
  counted never guessed; canaries ride every batch; metrics each stand alone (no composite); the ETA
  is counted in VALID verdicts/sec; the sanity envelope is labelled to-be-REPLACED-by-measurement.

---

## §9 — Sequencing (revised for the current tree)

The doc's §9 order holds, re-grounded on what shipped:

1. **§6 recursive-loop diagnostics self-inventory** (this cycle) — cheap, non-networked, multiplies
   every later measurement. `ui_walk` + AppVM stay DESIGN-ONLY/runbook (browser+VM gated).
2. **§8 triage measure-first core** (this cycle) — the pure/testable pipeline + bench harness +
   self-test; the operator runs the real bench + head-scope production run on the rig.
3. **§4 search timing instrument** + **§7 power-profile knob table** — small, measurement-first,
   BUILDABLE-NOW; each unblocks a measured decision.
4. **§1 Conjunction Lens (set-algebra core)** and **§2 Leads 2.0 (ordering/floor/clustering cores)** —
   the pure halves BUILDABLE-NOW; the UIs are BROWSER-GATED slices.
5. **§3 keyword fingerprints** — AFTER §8's triage batch cleans the worst junk (sharper skeletons).
6. **§5 Tor ladder + segmented downloads** — pure cores BUILDABLE-NOW; the live multi-circuit run is
   OPERATOR-GATED, scheduled with a scraping session.

## This-run scope

Per the maintainer's two topics of attention, this cycle ships the **BUILDABLE-NOW cores** for the
two priority phases, each a stacked draft PR onto `0.2`, skeptics-before-push:

- **§8 triage measure-first core** — the pure pipeline (prompt/parse/echo-back/canaries/timing/ETA/
  head-select), the bench harness (roster verification + per-metric-alone scoring), the EXPORT-ONLY
  guarantee + its invariant, the self-test endpoint, and the deterministic artifact proposals. The
  real model run + bench + anchor grading stay OPERATOR-GATED (this box has no models/GPU).
- **§6 recursive-loop diagnostics self-inventory** — the self-inventory instrument, the 4 missing
  recursive-loop members added to the aggregator, the membership contract test, plus the AppVM
  runbook + convention amendment (DESIGN). `ui_walk` stays browser-gated.

Everything else above is queued as its own session-sized brief per §9.
