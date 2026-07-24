# Autonomous session brief — 2026-07-24 Session B: the AI-stack rework (dual backend · vLLM · AI pill · toggle runs · AI metadata extraction)

**Status:** PENDING execution (an autonomous Sonnet-5 CLI session), SEQUENCED AFTER Session A
(`AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md`) per the maintainer's A16 ruling.
**Rulings of record:** the CLAUDE.md "FIELD FEEDBACK 2026-07-24" entry (item 8 + answers
A12–A15). This brief is the operating manual; the ledger is binding where they differ.
**Hardware ground truth (maintainer, A12):** the app already runs on a GPU-enabled VM — 8 GB
VRAM + up to 40 GB RAM; `mistral:7b` measured 5.1 GB VRAM under Ollama with ~2 GB spare. The
rest of the fleet is CPU-only (2-core/3.2 GB and 4-core Qubes VMs).
**Investigation baseline:** the Ollama coupling inventory was verified at `main@25dcb19`
(2026-07-24). STALENESS GUARD MANDATORY — re-verify every anchor; Session A will have landed
changes (notably the §7 gate split and the langdetect rework) before this session runs.

---

## §0 Binding rulings (do not re-litigate)

1. **DUAL BACKEND, selected by HARDWARE DETECTION (A12):** vLLM on GPU machines; **Ollama is
   KEPT for CPU-only** — never a silent replacement, never dropping the CPU fleet.
2. **Default model = Mistral-7B where it fits (A13)**, with a DISCLOSED hardware-aware fallback
   (e.g. `granite4:micro`) below the RAM/VRAM floor.
3. **vLLM lives in its OWN venv/external process (A14)** — torch stays BANNED from core
   (pyproject); install + HF-weights download are consented, task-manager-visible jobs.
4. **The top-bar pill becomes "AI"** — green (on) / red (off), NO model count (A15). Click when
   red → start the preferred installed backend (vLLM first) or offer install; the default-model
   download rides the task manager.
5. **Triage + source-tag runs become ON/OFF TOGGLES** (numeric inputs removed) running
   progressively across ALL head-scope keywords / ALL sources in the background, persisted
   cursors, task-manager visible, logs downloadable for the Claude-verification chain (A15).
6. **AI-augmented article METADATA extraction (dates/events/locations/when-where-who) is now
   asked for (A15)** — and the standing LLM-PERCEPTION eval-first ruling APPLIES UNCHANGED:
   harness first, extraction as AI-layer candidates only, never the trusted index.
7. All standing honesty non-negotiables: no composite scores; model output is
   propose/candidate-class only ("AI-derived · unreliable"); download sizes and hardware
   decisions disclosed; loopback-only inference; never silently downgrade any gate.

## §0.5 Working mode

Identical to Session A's §0 (read CLAUDE.md in full; draft-PR-per-slice onto a
freshly-fetched `main`; the full gate set: pytest py3.13 / ruff F,B / mypy ≤127 / bandit /
i18n --min 100 / node --check; skeptics-before-push with the negative-space lens on
honesty-critical slices — here B6 extraction and B2 install; frontend conservative + flagged
per fork-3/Q6a; shipped.csv closeout rows). **Egress note:** verifying the exact vLLM package
name/version, the Mistral-7B quantized HF repo id, and any download URL requires live network —
NEVER commit an unverified repo id or URL (the fabricated-endpoint burn); if egress blocks
verification, the slice ships the seam with the id left as an operator-filled setting plus an
honest TODO, never a guessed string.

---

## §1 Slice B1 — the backend abstraction (the seam)

**Verified:** the entire inference surface sits behind ONE class — `OllamaClient`
(`src/llm/ollama.py`): `generate` (`:276`, POST `/api/generate`), `list_installed` (`:235`),
`is_available` (`:228`), plus `LLMError`/`LLMUnavailable` (`:120-125`) and `GenerationResult`
with Ollama's ns-timing fields (`:164-177`). Consumers (`src/api/llm.py`, all `src/ai_layer/*`,
`triage_job.py`/`source_tags_job.py`, `pull_queue.py`) never build HTTP themselves. There is no
OpenAI-compatible client anywhere. Ollama-only features: pull/remove (`:321,:350`), the binary
installer (`src/llm/installer.py`), the model-store backup (`src/backup/ollama_models.py` —
filesystem, no vLLM analog).

Build:
1. A backend protocol (e.g. `LlmBackend`: `generate / list_installed / is_available / close` +
   the shared `LLMError/LLMUnavailable/GenerationResult`). Keep `OllamaClient` as one
   implementation; add **`VllmClient`** speaking the OpenAI-compatible API
   (`POST /v1/chat/completions` — map system+prompt to messages; `GET /v1/models`), default
   `OO_VLLM_URL=http://127.0.0.1:8000`, loopback-enforced exactly like Ollama
   (`_require_loopback`), kill-switch semantics identical (loopback generate allowed under
   airplane; anything clearnet refused).
2. **Timing remap:** OpenAI-style `usage` (prompt/completion tokens) fills `GenerationResult`;
   Ollama's ns-timings become optional/None on vLLM — sweep the consumers that read them (the
   triage cost/ETA math) to degrade gracefully (an honest "timing unavailable on this backend",
   never a fabricated rate).
3. **Backend resolution** in one place (extend `get_llm_client()` / a `resolve_backend()`):
   hardware detection (nvidia-smi presence + VRAM read; honest `unavailable` when the probe
   fails) + installed-backend detection → **prefer vLLM when installed AND a GPU is present;
   Ollama otherwise**; env/setting override (`OO_LLM_BACKEND=auto|ollama|vllm`). The Settings →
   AI tab STATES the active backend and WHY (detection facts shown — disclosed, never silent).
4. **Per-backend model naming:** `llm_model` currently validates as an Ollama tag
   (`app_settings.py:169-173,221-229`) — split into per-backend settings (Ollama tag vs HF repo
   id), with the resolution layer picking the active one. Reconcile the near-duplicate
   informational `ollama_host/origins/base_url` config surface (`config/settings.py:96-99`)
   while there.
5. Update the repo invariants that assert Ollama specifics (`tests/test_repo_invariants.py:1586-1599,
   :851, :2311-2324`) to the dual-backend shape — intent preserved, never deleted.
6. **Tests:** a stub OpenAI-compatible server exercises `VllmClient` (chat mapping, usage
   remap, 404-model, unavailability); backend resolution matrix (GPU+both / GPU+ollama-only /
   CPU+both → ollama / overrides); kill-switch both directions on the new client.

## §2 Slice B2 — vLLM lifecycle: detect · start/stop · install · model download · context auto-tune

Build:
1. **Detection:** a managed external venv (configurable path, default under the data dir) +
   server-binary/import probe; health via `GET /v1/models`. vLLM is an EXTERNAL process like
   Ollama — never a core dependency.
2. **Managed start/stop:** launch the server as a subprocess bound to loopback
   (`--host 127.0.0.1`), with `--model`, `--max-model-len`, `--gpu-memory-utilization` computed
   (see 4); stop on app shutdown; status surfaced. Startup takes tens of seconds (model load) —
   honest "starting…" state, never a fake instant green.
3. **Install flow (consented, task-managed):** create the venv + `pip install vllm` — this
   drags torch/CUDA (multi-GB); disclose the size class BEFORE consent; run as a cancellable
   task-manager job with honest phase text (pip gives no reliable %, so phases not fake
   percentages). CPU-only machine + install attempt → an honest refusal/warning (vLLM is
   GPU-first; Ollama is the CPU path) rather than a doomed install.
4. **Default model + download:** Mistral-7B-Instruct in a 4-bit quantization (AWQ/GPTQ-class)
   that fits 8 GB VRAM with KV-cache headroom — the EXACT HF repo id must be live-verified by
   the executing session (never guessed); download = a consented task-manager job with real
   byte progress; hardware-aware fallback below the floor (RULED A13), disclosed.
5. **Context-size auto-tune (ruled):** compute `max_model_len` + `--gpu-memory-utilization`
   from detected VRAM minus weight footprint (KV-cache budget math), shown in the AI tab with
   the method; user override setting. On Ollama, the analog is `num_ctx` derived from RAM —
   same disclosed-auto-with-override shape.
6. **Skeptic (install/download slice):** no download without consent; checksums/integrity where
   the source attests them (the GitHub-digest lesson — never fabricate a checksum); a failed
   install leaves no half-configured backend claiming to work.

## §3 Slice B3 — concurrency (the point of vLLM)

Build: a bounded concurrent-generation helper ON the backend seam (per-backend parallelism:
vLLM → N concurrent requests, setting with a hardware-derived default; Ollama → 1 unless the
operator raises it), adopted by the batch consumers: bulk summarize/translate, the continuous
langdetect (Session A's rework), the triage/tag runs (B5), the law-change summaries (Session A
§3). Order-preserving where results are stored per article; per-request error isolation (one
failed generation never kills the batch — the A1 resilience discipline). Tests: N-way
concurrency against the stub server; serial-on-Ollama default pinned.

## §4 Slice B4 — the "AI" pill + install/start UX

**Verified:** `#llm` pill (`index.html:107`), `loadLlmHealth` renders "N LLM"/"LLM offline"
(`app.js:17459-17477`), click → `openAiSettings`.

Build (ruled): text becomes **"AI"**, green when the active backend is up, red when down — NO
model count. Click green → Settings → AI (unchanged). Click red → if a backend is installed:
start the preferred one (vLLM first) with a "starting…" state; if none: offer the install flow
(vLLM on GPU machines, Ollama otherwise), with the default-model download queued as a
task-manager job. Update every UI string/invariant that asserts the old pill text; keys ×12 for
new chrome. Browser-unverified flagged; the pill is top-bar chrome (invariant-#3 constant
footprint — keep the fixed min-width).

## §5 Slice B5 — triage + source-tag runs become progressive toggles

**Verified:** panels expose `#kt-limit` (500) and `#st-topn` (200) numeric inputs
(`index.html:1770-1797`); the runs are bounded one-shots (`diagnostics.py:3878-3968,
:4013-4055`; workers in `triage_job.py`/`source_tags_job.py`). Session A's §7 removes their
blanket airplane gates.

Build (ruled): remove the numeric inputs; each run becomes an ON/OFF toggle driving a
progressive background job across ALL head-scope keywords (triage) / ALL sources with
sufficient evidence (tags): bounded batches, a persisted cursor (the qualification-job pattern —
`Source`-status-like durable progress or a state file), resumable across restarts, honest
evidence-floor skips, task-manager visible, JSONL logs (verdicts + timing) APPENDED per batch
and downloadable — the 2026-07-20 §4 Claude-verification contract (canaries, echo-back,
stratified re-judgement sample) unchanged. Sensible internal defaults replace the removed knobs
(env-tunable, not UI). Tests: cursor resume, toggle stop/start, log append integrity,
no-trusted-index writes (re-pin).

## §6 Slice B6 — AI-augmented metadata extraction (eval-gated; the NEW ask)

**The standing ruling applies unchanged:** LLM = PERCEPTION never judgment; who/where/when
scope = dates + places + persons AND orgs (no "what"); **eval-first** — and the S6.5 perception
eval harness is ALREADY SHIPPED (`run_perception_eval_selftest`,
`/api/diagnostics/perception-eval-selftest`).

Build:
1. **Harness first:** run the perception eval against the ACTIVE default model (per backend
   actually present); produce the per-language/per-stratum precision/recall/HALLUCINATION
   report (no composite; place-string vs coordinate scored apart; de-US-centring split) and
   persist it as the gate evidence (a diagnostics artifact the maintainer can download).
2. **Extraction as AI-layer candidates:** a background toggle job (the B5 chassis) extracting
   dates/events/locations/persons/orgs per article via the backend seam, written as typed
   `ai_keyword` rows (kinds e.g. `ai-date`, `ai-place`, `ai-person`, `ai-org`, `ai-event`) with
   model + prompt-version provenance, `skip_existing`, persisted cursor. NEVER the trusted
   index; NEVER overwrites the rule-based extractors' tables (`article_mentioned_*`,
   `article_entities`); rendered inline in the article view under the established
   "AI-derived · unreliable" third class with confirm-within-the-lens.
3. **The gate bites:** a language/stratum where the model fails the harness bars (define
   honest per-stratum floors, e.g. hallucination above a stated threshold → that stratum
   disabled) ships DISABLED with the report stating why — never a fabricated capability. The
   toggle UI shows which strata are active and why.
4. **Skeptic (mandatory, negative-space):** should-be-empty inputs (no dates/places present)
   must yield zero candidates; a hallucinated/unparseable answer stores NOTHING (the B15/echo-
   back precedent); date candidates must never enter the agenda/trusted date store.

## §7 Slice B7 — AI diagnostics + qualification assist

Build:
1. An **`ai` diagnostics member** riding the all-diagnostics bundle (the 2026-07-17 coverage
   ratchet applies): backend/hardware detection facts, active model, context settings, timing
   stats, last run summaries per AI job — secret-safe (real scrub, the S1 lesson), read-only.
2. **Qualification assist (ruled, propose-only):** an LLM pass over a source's trial-fetch
   articles flagging nav-soup/extraction-junk signatures → a proposals log beside the
   auditor's evidence (never auto-decides, never touches `Source.status`); composes with the
   prose gate + the qualification lifecycle.
3. **Stoplist candidates:** the triage run already proposes deletions — ensure the loop is
   stated end-to-end in docs (run → download log → Claude verification → reviewed PR) and the
   log rides the download surface.

---

## §8 Explicitly OUT of scope

Dropping Ollama (forbidden — A12 keeps it for CPU); any cloud/remote inference (local-first is
constitutional); torch in core (banned); auto-applying ANY model output to trusted data;
the Observatory; Session A's slices (assumed landed — verify, don't rebuild). If vLLM's CPU
mode tempts as a shortcut: it is not viable on the fleet and must not be presented as such.

## §9 Closeout

Per slice: shipped.csv row, tests named, gates run; harvest lessons (the backend-seam and
eval-gate patterns are reusable). Final PR body: carry-overs (browser click-throughs owed —
the pill, the toggles, the extraction lens; the operator's GPU-box live validation of B2/B3 —
in-sandbox there is no GPU, so vLLM start/generate is fixture/stub-tested here and
live-verified by the maintainer, stated honestly, never claimed).
