> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — S1 (wiring the real triage run) and S2 (the source-tag-assignment run on the same chassis) are confirmed SHIPPED — see `src/ai_layer/triage_job.py`, which now calls `run_triage_batch` for real production runs, not just the selftest. What remains is the actual operator run on the Ollama rig plus the Claude-side verification pass this brief's §4 specifies — that hasn't happened yet. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Autonomous session brief — wire the real LLM triage run + build the source-tag run (2026-07-20)

**Mission.** The maintainer ruled (2026-07-20): run the §8 LLM keyword-triage AND the LLM
source-tag assignment on the local Ollama rig, EXPORT-ONLY, producing JSONL logs that a
Claude session then VERIFIES before anything is applied ("I currently don't trust enough
small models. You should verify it."). This is the ruled provenance chain made operational:
**ai-proposed → claude-verified → maintainer-merged.** This session makes both runs
operator-runnable from Settings → Diagnostics. NOTHING in either run writes the trusted
index or `Source.tags` — logs only.

**Executor:** one Claude Code CLI session, LOCAL only. Branch `claude/llm-runs-*` off a
freshly-fetched `origin/main`, ONE draft PR, commit-per-slice. House gates: skeptics
complete before push on the prompt/parser surfaces (negative-space lens: inputs that must
yield NO verdict/tag must yield none); full local suite green; ruff + mypy on new files;
ledger + shipped.csv rows; the all-diagnostics bundle RATCHET (2026-07-17): every new GET
diagnostics route joins the bundle or the documented exemption list, or
`test_all_diagnostics_bundle_covers_every_get_diagnostic` reddens.

---

## §1 Ground truth (verified in-session 2026-07-20 — re-verify, staleness guard)

- `src/ai_layer/triage.py` HAS the core: head-scope selection (~:355, `Keyword.article_count`
  DESC, counter-only, `min_articles` floor), `run_triage_batch` (:391 — prompt build →
  `client.generate` → `parse_verdicts` echo-back → `check_canaries` → timing), and
  `export_triage_jsonl` (:427 — APPEND-only, refuses non-`.jsonl`/`.json` paths + DB
  sidecar names by contract).
- **The real-run WIRING does not exist.** `run_triage_batch`'s ONLY caller is
  `run_triage_selftest` (:704, stub client — no model, no network). The only endpoint is
  `GET /api/diagnostics/keyword-triage-selftest` (`src/api/diagnostics.py:1125`). There is
  no run endpoint, no job, no panel button.
- Source-tag assignment: DESIGN-ONLY — the CLAUDE.md Open-queue entry "LLM SOURCE-TAG
  ASSIGNMENT FROM TOP KEYWORDS (2026-07-20)" is the spec (closed tag vocabulary · two-class
  deduced channel · evidence floor · export-only first). No code exists.
- Ollama gate caveat: under the CURRENT blanket `_check_kill_switch`
  (`src/llm/ollama.py:183`) every LLM call requires airplane mode OFF. The gate-split fix
  (same-day ledger entry) is a SEPARATE pending build — do NOT block on it; the operator
  runs online for now. If you fix it first, generation becomes airplane-safe — a bonus,
  not a dependency.

## §2 Slice S1 — wire the real keyword-triage run

A visible, abortable background job (the `BackgroundJob` pattern) driving the EXISTING
core over the LIVE corpus:

1. `POST /api/diagnostics/keyword-triage/run` (params: `model` [validated via the
   `verify_roster` convention — an uninstalled tag is REFUSED, never substituted], `limit`,
   `min_articles`, optional per-language stratification) + `/status` + `/cancel` +
   `/download` (the dated JSONL). 409 while one runs; refuse under the kill switch with the
   honest message.
2. The job loop: head-scope selection → batches through `run_triage_batch` (canaries per
   batch, per the shipped prompt builder) → `export_triage_jsonl` to
   `data_dir()/triage/oo-keyword-triage-<date>.jsonl` — a RUN HEADER record first (model
   tag, ollama version if reachable, prompt version, selection params, corpus snapshot
   counts, started_at), then one record per batch. Abort leaves the partial log honest
   (header says cancelled).
3. Settings → Diagnostics panel button + live status line (un-keyed-diagnostics-strings
   convention, browser-unverified per fork-3/Q6a).
4. Tests: the job state machine with an injected fake client; an assertion that the run
   NEVER writes Keyword/KeywordMention rows (the export-only contract); the export-path
   guard; cancel mid-run leaves a valid parseable JSONL.

## §3 Slice S2 — the source-tag assignment run (same chassis)

Per the recorded design entry, as a sibling module (`src/ai_layer/source_tags.py` or
similar) reusing triage's conventions (echo-back, canaries, timing, JSONL, refusal of
uninstalled models):

1. Input: per-source top-N TERMS (default N=200 per the maintainer's ask), post-stoplist,
   via the denormalised `KeywordMention.source_id` covering scan — never a codec join.
   EVIDENCE FLOOR: a source below a minimum article/mention count is SKIPPED with a counted
   reason, never guessed at.
2. Prompt: the model picks ONLY from the existing closed tag vocabulary (the catalog
   taxonomy the wizard reads — resolve it from the live tag set, state it in the prompt,
   REJECT out-of-vocabulary answers in the parser). Canaries: hand-known obvious sources
   (a sports outlet, a stats agency) with expected tags — a failed canary marks the batch
   distrusted in the log.
3. Output: JSONL to `data_dir()/triage/oo-source-tags-<date>.jsonl` — run header + one
   record per source (domain, evidence sample [top terms], proposed tags, skip reasons).
   EXPORT-ONLY: `Source.tags` is NEVER touched by this run; the deduced-channel apply step
   is a LATER slice, gated on the maintainer having reviewed a Claude-verified batch.
4. Endpoint + status/cancel/download + panel button + a selftest (stub client) mirroring
   the triage selftest; bundle-ratchet membership.
5. Skeptic (mandatory, negative-space): a source whose top terms are nav-soup/junk must
   yield either a skip or tags the parser REJECTS — never a confident wrong tag stored as
   valid; an empty vocabulary, a model echoing the vocabulary verbatim, and a source with
   0 keywords must all produce honest empties.

## §4 The verification contract (what the logs must carry — Claude-side protocol)

The maintainer uploads the JSONL(s) to a Claude session, which verifies BEFORE anything is
applied. For that to be possible the log must carry (S1 largely already does via the
shipped schema — S2 must match): the run header (model + prompt version + params + corpus
counts), and per batch/source: the input items WITH language + counts, the post-echo-back
verdicts/tags, the rejected/mangled tally, canary outcomes, wall/eval timing.

The verifying session then: (1) checks CANARY integrity across the run (a failed-canary
batch is distrusted wholesale); (2) re-judges a STRATIFIED sample (~50–100 items across
languages × verdict/tag classes) and reports agreement, itemizing every disagreement —
especially per-language: small local models degrade off-English, so ar/zh/hi/bn/ru get
proportionally MORE re-checks, never fewer; (3) sanity-checks rejection rates + timing;
(4) builds the deterministic artifact (a stoplist batch / a reviewed tag batch) ONLY from
verdicts that survive, as a draft PR the maintainer merges. Provenance recorded on the
artifact: ai-proposed (model tag) · claude-verified (sample size + agreement) ·
maintainer-merged.

## §5 Operator prerequisites (before running)

- Ollama running locally with the chosen model pulled (`ollama list` — the run refuses an
  uninstalled tag rather than substituting; the 7-model bench roster is a separate,
  optional exercise).
- The app ONLINE (until the airplane/Ollama gate split lands — see §1).
- Time budget: the log's own timing telemetry computes verdicts/sec — start with a bounded
  `limit` (e.g. 500 keywords / 200 sources) to measure the rig before a full-head run.

## §6 Explicitly NOT this session

The deduced-tag APPLY step (waits for a verified batch + maintainer review) · the
airplane/Ollama gate split (own ledger entry) · the 7-model bench run (operator-only) ·
any write to the trusted index or `Source.tags` (forbidden by contract in BOTH slices).
