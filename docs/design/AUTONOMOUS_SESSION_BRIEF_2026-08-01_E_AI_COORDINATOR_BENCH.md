# Autonomous session brief — 2026-08-01 Session E: the Background-AI coordinator · the comparative model bench · context management

**Status:** EXECUTED 2026-08-02 (branch `claude/oos-optimization-planning-iawlbj`, rebased onto
the merged vLLM download fix). S1–S5 all shipped; see the five 2026-08-02 `docs/ledger/shipped.csv`
rows and the "SESSION E EXECUTED" block in CLAUDE.md for what remains — chiefly the bench's actual
roster run and the ~50-anchor grading sitting, both OPERATOR steps on the model rig, and §3's
per-task model selection with the VRAM co-fit check, which is not built.
**Answers of record:** the "FIELD IMPRESSIONS 2026-08-01" entry in CLAUDE.md (rulings 12–16
govern this session).
**Base:** freshly-fetched `origin/main`; draft PR(s); nothing auto-merges.
**Operator split:** this session builds the machinery; the actual roster RUN happens on the
maintainer's GPU rig, logs come back for the ai-proposed → claude-verified → maintainer-merged
chain.

## §0 Working mode

Same gates as Session D (§0 there — staleness guard, skeptics + negative-space on
honesty-critical slices, the verbatim CI commands, i18n ×12, stale-anchor greps). Additional
standing invariants that bind THIS session specifically:

- The **eval-first ruling**: no extraction capability activates on a language/stratum that
  failed or was never measured — "never evaluated" is epistemic and still refuses.
- The **hardware-gate two-predicate invariant**: CPU/RAM/practicality policy lives in
  `inference_capability()` ONLY; `detect_gpu()` answers "can vLLM run here?" and carries no
  policy (ast-guard test enforces).
- The **roster rule**: a model tag is verified LIVE against the resolved backend's installed
  list and REFUSED if absent — never substituted with a close tag.
- No composite score anywhere; walk new payload KEYS for the banned substrings
  (score/ranking/rating/grade — remember "degraded" contains "grade").

## §1 (S1) The Background-AI coordinator (rulings 12–13)

**Anchors (verified):** per-sweep toggles `_toggleAiSweep` chassis app.js:12436–12438 with
`toggleKeywordTriage` :12530 / `toggleSourceTags` :12552 / `togglePerceptionExtract` :12650
(buttons index.html:1714/1733/1763); langdetect auto-start ride-along
`advance_langdetect_auto_start` src/api/ai.py:659–690 (wired runner.py:1882–1884;
`ai_langdetect_auto` default True — today the ONLY auto-start AND the only
hardware-gated sweep); persisted cursors: `triage_progress_state.json` (triage_job.py:65),
`source_tags_progress_state.json` (source_tags_job.py:49),
`perception_extract_progress_state.json` (perception_extract_job.py:59); `concurrency_for` +
`run_concurrent` src/llm/concurrency.py:67–114; `inference_capability()` call sites =
llm.py:321/:367, ai.py:688, ai_diagnostics.py:63, bulletin/gate.py:62 — the three sweeps and
manual runs never consult it today. qualification-assist has NO UI trigger
(diagnostics.py:4664, zero src/static hits); `/api/ai/keywords/extract` has zero frontend
callers.

1. **ONE master "Background AI" toggle** (Settings → AI; consider mirroring on the AI-pill
   menu) starting a COORDINATOR: a single background lane that runs the ENABLED sweeps
   ROUND-ROBIN — one bounded batch per sweep per turn (each sweep's persisted cursor makes
   interleaving free) — over keyword-triage · source-tags · perception-extract · langdetect
   (folds in, `ai_langdetect_auto` honored) · a NEW qualification-assist batch member.
   Per-feature enable checkboxes stay beneath the master switch (informed-consent layering —
   the master is a convenience, never a hider). Custom-prompt auto-on-ingest stays
   scheduler-side (already bounded per-pass) — document the boundary, don't move it.
2. **vLLM handled optimally (ruled 12):** backend-aware dispatch — when the resolved backend
   is vLLM, member batches may run CONCURRENTLY up to `concurrency_for("vllm")` (continuous
   batching makes this efficient); on Ollama strictly SERIAL. Reuse `run_concurrent`; never
   hardcode a backend name — go through `resolve_backend()`.
3. **Preemption (ruled 13):** interactive single calls (reader summarize/translate, one-off
   asks) are NEVER governed by the toggle and never queue behind sweeps. A USER-INITIATED
   BATCH (bulk translate/summarize, a manual sweep run, a synthesis over many articles)
   PAUSES the coordinator — cursors persist by construction — with a VISIBLE notice
   ("Background AI paused while your batch runs", ×12), AUTO-RESUME when the batch ends + a
   resume notice. Implement as a dedicated hold flag; **heed the 2026-07-24 exclusive-hold
   lesson**: EVERY entry point that can start background AI work (the coordinator loop, the
   langdetect ride-along, any manual sweep endpoint) checks the SAME hold, released in a
   `finally`.
4. **Hardware-aware default:** the master toggle's DEFAULT state consults
   `inference_capability()` (practical → default on; impractical → default off + the standing
   disclosure); `llm_allow_impractical_hw` honored. This closes the gap where only
   langdetect-auto was hardware-gated.
5. **Honest status:** the coordinator is a task-manager-visible `BackgroundJob` with
   per-member progress + which member is active; its state survives restart (the sweeps' own
   cursors are the durable state — the coordinator itself stays thin).

**Tests:** pause/resume never loses cursor progress (and re-supplies each sweep's MODE
explicitly on resume — the resumable-job mode-preservation lesson); the hold covers every
entry point (a manual sweep run during a user batch is refused/queued, not run); Ollama-serial
vs vLLM-concurrent dispatch; the hardware default both directions; the master toggle never
hides the per-feature state.

## §2 (S2) The comparative model bench runner (rulings 14–15)

**Anchors (verified):** triage.py:600–709 — `verify_roster` (exact-tag match, REFUSES missing,
never substitutes) + per-metric helpers `anchor_accuracy` (junk precision/recall SEPARATE from
kind accuracy) · `pairwise_agreement` (per model pair over shared terms; no-shared → None) ·
`format_validity_rate` · `pct_unsure` · canaries mixed into every batch; batch selection today
is head-scope + keyset (:359/:393) — **NO frozen-batch builder, NO multi-model runner, NO
bench endpoint exists**; `run_llm_bench` llm_bench.py:180 (per-prompt-shape latency,
backend-aware timing, warmup excluded); `run_perception_eval_against_model` perception.py:114
+ the persisted dated report (perception_job.py) with per-language/per-field
precision/recall/hallucination; the vLLM lifecycle module (managed venv, start/stop);
`llm_keep_alive` setting. Defaults today: Ollama `ministral-3:8b-instruct-2512-q4_K_M`
(ollama.py:186, since 2026-07-30); vLLM `mistralai/Ministral-3-3B-Instruct-2512`
(ollama.py:137).

1. **Frozen-batch builder:** a stratified ~400–500-keyword batch (strata per the ruled
   2026-07-12 protocol: language × head/tail article-spread), PERSISTED as a dated artifact —
   the constant every model sees. An ANCHORS file (~50 maintainer-graded keywords) with a
   small grading flow reusing the IR gold-set builder's keyboard-fast pattern — graded ONCE,
   reused across every model and every future bench run.
2. **The runner:** for each roster model × each backend where that model is available
   (**ruled 15: BOTH Ollama and vLLM — the backend comparison is itself a goal**; the same
   weights differ by quantization across backends, so every artifact is labelled
   model + backend + quantization and the two are never conflated as "the same model"):
   run (i) the perception who/where/when harness, (ii) the frozen triage batch → all triage
   metrics, (iii) source-tag closed-vocabulary validity + canaries, (iv) a known-language
   langdetect sample, (v) `run_llm_bench` latency/tokens-per-sec. **Sequential model loading —
   minimize load/unload (ruled 16):** complete ALL tasks for one (model, backend) before
   switching; Ollama unload via keep-alive 0 between models; vLLM = a lifecycle restart per
   model. `verify_roster` semantics per backend; an absent model is REPORTED and skipped,
   never substituted.
3. **Roster (ruled 15):** `ministral-3:8b-instruct-2512-q4_K_M` (current default) ·
   `ministral-3:3b-instruct-2512-q4_K_M` · `mistral:7b` · the latest gemma4 (start from the
   ruled 7-model roster's `gemma4:e4b`; re-verify the current best tag at execution) ·
   `qwen3.5:4b` (a ruled-roster member — the maintainer doubts it; the bench IS the
   instrument that answers that doubt, at the cost of one roster slot) · the LiquidAI LFM
   candidate (the maintainer named "LFM2.5-8B-A1B" — verify the EXACT Ollama tag / HF repo
   LIVE; if Ollama lacks it, the vLLM/HF path on the GPU box; REFUSED if unverifiable) ·
   optionally `granite4.1`. Every tag verified at run time.
4. **Output:** every metric reported ALONE per (model, backend, task, language) — no
   composite, no winner column; persisted dated side-by-side artifacts + ONE downloadable
   log for the verification chain (the maintainer runs the bench on the rig → uploads the
   log → a Claude session verifies canary integrity, re-judges a stratified sample weighted
   toward non-English, checks rejection/timing sanity → the default-model decision is the
   maintainer's). Per-language results feed §3's gates directly.
5. **Surface:** endpoint + a Diagnostics-panel button + a cancellable, per-model-resumable
   task-manager job; bundle-EXCLUDED as a heavy operator bench (the llm-bench precedent,
   documented in the manifest's `excluded` block).

## §3 (S3) Per-language / per-task activation (ruling 16 constraints)

1. **Per-language tri-state gates extend to triage / source-tags / langdetect** (the
   `gate_languages_from_report` pattern; evidence = the §2 bench artifacts). A language never
   measured for a task = unmeasured → refuses — epistemic, not permissive. This is what makes
   a ~8-language LFM-class model honestly usable: ACTIVE where it measured well, gated
   elsewhere — a capability matrix, not an over-claim.
2. **Perception gate granularity:** move from whole-language to per-FIELD within a language
   (today one failing field deactivates the language for all fields —
   perception_extract.py:89–160). Recommended in the planning conversation and not objected
   to; ship WITH both-direction tests (a failing field stays gated; a passing sibling field
   activates).
3. **Per-task model selection — CONSTRAINED (ruled 16):** the setting ships but DEFAULTS to
   the ONE active model for everything. A several-models configuration is admissible ONLY
   when a VRAM co-fit check verifies both fit together in 7–8 GB (the check gates SAVING such
   a config, with the numbers shown); the coordinator groups work BY MODEL to minimize
   load/unload churn (process every task of model A, then switch). Never a silent swap
   mid-sweep.

## §4 (S4) Context management (ruling 16 — the adopted revertible defaults)

**Anchors (verified):** `llm_max_context_length` settings.py:107 (static); vLLM
`compute_server_args` auto-tunes from detected VRAM; **the Ollama `num_ctx` auto-tune was
NEVER built** (the documented B7 carry-over gap); the `article_length` diagnostic
(`article_length_report`) already measures the corpus's word-count distribution per
type/language.

1. **Measure first:** read the real article-length distribution off the live corpus via the
   article_length diagnostic + a STATED chars→tokens estimate per script (state the method +
   its uncertainty; never present the estimate as a token count). Choose `num_ctx` to cover
   ~p95 of articles + prompt overhead. Explicitly NOT max-context-for-all: KV-cache scales
   with context and taxes EVERY call's memory/latency + vLLM concurrency — the 1 % tail must
   not tax the 99 %.
2. **Build the Ollama `num_ctx` auto-tune** (RAM/VRAM-derived ceiling mirroring
   `compute_server_args`), closing the B7 gap; the resolved value is disclosed in the `ai`
   diagnostics member.
3. **Background sweeps:** an over-budget article is HEAD-TRUNCATED with DISCLOSURE — the
   provenance/log records "analyzed the first N of M chars" (never silent, never dropped).
4. **User-driven summarize/translate: NEVER silently truncate.** Fits → single call (today's
   path, unchanged). Too long → CHUNKED map-reduce: translation = paragraph-boundary chunks
   translated sequentially and concatenated, the result visibly labelled "translated in N
   parts" ×12; summary = hierarchical (chunk summaries → combined summary), visibly labelled
   "hierarchical summary over N parts" ×12 — a method change is disclosed, not hidden.
5. **Tests:** the chunker never splits mid-sentence where avoidable and covers 100 % of the
   text (concatenation reconstructs coverage); the disclosure renders; head-truncation never
   fires on the user-driven path; the auto-tune degrades honestly when RAM/VRAM is
   unreadable (unmeasured ≠ a guessed value — the epistemic-third-state rule).

## §5 (S5) Orphan homes

- **qualification-assist:** a per-source button in the source-management UI (its natural
  home, noted as a carry-over when B7 shipped) + the §1 coordinator batch member. Still
  propose-only — never touches `Source.status`/`Source.tags`.
- **`/api/ai/keywords/extract`:** zero frontend callers. Decide wire-vs-retire
  (absorption-gated per the Desk lesson — the custom-prompt run path covers the capability;
  if retiring, prove absorption first and keep the endpoint until then).

## §6 (S6) Docs + ledger

shipped.csv rows per slice; ledger append; USER_MANUAL touches for the master toggle + the
chunked summarize/translate disclosure (docs↔app reciprocity); conflict-marker grep after any
merge.

## §7 Scope fence

- Model pulls/downloads stay CONSENTED task-manager jobs — the coordinator never triggers a
  download.
- The eval-first ruling stands everywhere: nothing activates on an unmeasured stratum.
- `detect_gpu()` stays policy-free (the two-predicate ast guard).
- No change to the airplane/loopback posture: loopback generation works under airplane;
  pulls stay kill-switch-gated.
- The bench MEASURES; it never auto-changes the default model — that decision is the
  maintainer's, made on the verified logs.
- Frontend conservative + flagged per fork-3/Q6a; the maintainer's HTML exports are the
  browser check.
