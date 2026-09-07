# Prompt 11 — The AI layer: model supply, capability probes, and the honest gaps

> **Scope:** `src/llm/`, `src/ai_layer/`, the AI Settings surfaces, the external-artifact registry.
> **Gated on:** D5, D6, D7, D8, D9, D10, AI-15 (one lookup), L9.
> **Sequencing:** independent. Its S1 is a supply-chain gap; its S6 is a live CI risk.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md entries **"ONE MODEL, MINISTRAL 3B, THROUGHOUT THE ENTIRE APP"**,
**"LOCAL INFERENCE IS GATED ON HARDWARE SUITABILITY"** and **"PQC_AVAILABLE ANSWERS 'DOES IT IMPORT?'"**, then
`docs/design/AI_LAYER_STRATEGY_2026-07-29.md` (banner-stale: most of it is built).

There is no GPU in this sandbox. Every GPU-path claim in this prompt is fixture-testable and **not**
live-verifiable here; the maintainer's GPU machine is the gate, and saying so is part of the deliverable.

## 1. Slices

### S1 — D6: model weights are the one downloaded artifact with no integrity pin

House doctrine everywhere else: the DuckDB httpfs extension is SHA-pinned and verified before every `LOAD`;
the Ollama installer verifies against GitHub's attested `digest: sha256:…` and **refuses when no digest is
attested**; the external-artifact registry exists so that anything externally sourced gets an entry in the
same commit. Model weights escape all three — downloaded by repo id at whatever `main` points to, with no
check, so the bytes can change under an operator between two installs and nothing would say so.

The pin itself is cheap: HF revisions resolve to a commit SHA and `huggingface_hub` accepts `revision=`. The
work is deciding where the pin lives (a dated registry entry per roster model) and what a **mismatch** does —
refuse, per the no-fabricated-security rule, with the operator able to re-pin deliberately.

Recorded as considered and **not** adopted from the same source, with reasons, so nobody re-proposes them:
`--max-num-seqs` (the app already bounds concurrency client-side, and a server-side cap kept in sync with a
client-side one is two copies of one decision); a compute-capability ≥7.5 preflight (`detect_gpu()` already
gates on CUDA and the failure it prevents is loud); a per-launch `--api-key` on a loopback socket.

### S2 — D7: capability flags must probe the capability, not the import

`PQC_AVAILABLE` is set by a bare `import` succeeding, so when upstream `pqcrypto` 1.0.0 renamed
`generate_keypair` → `keygen` the module still imported, the flag stayed `True`,
`pqc_unavailable_but_requested` — a property that exists **specifically** to say "the operator wants PQC and
the library cannot provide it" — returned `False`, and the call raised. The whole honest-degrade machine
around it was walked straight past.

The fix probes a **round trip** (keygen → sign → verify-true → verify-false), not an attribute list: 1.0.0's
`verify` returns `None` for a valid signature and raises for an invalid one, so an attribute probe would pass
while `bool(verify(...))` reported every genuine signature as a failure — silently, in a tamper-evidence
path, on an install whose keys already exist. The negative-direction test is the load-bearing one: a module
that imports but lacks the capability must report unavailable, never raise.

Sweep for the class: any `X_AVAILABLE` set from a bare import inside a `try`. `OTS_AVAILABLE` sits in the
same payload.

### S3 — The `pqcrypto` bound and its migration

The ceiling is `<1.0` and it has been widened by a bot once already, because a comment addresses humans and
only a CI-visible mechanism addresses a bot. Either a dependabot `ignore` for majors or a guard pinning the
ceiling until migration — that choice is D7's second half. The migration itself follows
`docs/maintenance/EXTERNAL_DEPENDENCIES.md`: the rename **and** the changed verify contract, on a path that
persists keys.

Record what was measured rather than a changelog paraphrase: 1.0.0 gives 16 failed / 23 passed in this
repository's own suite against 0.4.0's 39 passed; `keygen()` returns plain `bytes` and `PUBLIC_KEY_SIZE` is
1952 in both versions — so the older comment claiming a `PublicKey`/`SecretKey` object change is wrong and
points a future migrator at a problem that does not exist.

### S4 — D10 / the perception rollout

The eval harness is shipped and gated per field, per language, tri-state, with `unmeasured` kept epistemic
rather than permissive. What rolls out is only what a language and field **cleared**; a field the model fails
stays disabled with the honest report. Numeric floors want the graded gold set (operator).

Two structural points to preserve while extending: the extraction writes only `ai_keyword` candidates under
`ai-who` / `ai-place` / `ai-date` and never the trusted index (a repo invariant plus dedicated negative-space
tests pin this); and WHO stays one combined persons-and-orgs kind, matching the harness's own shape and the
ruling's own framing — splitting it would fabricate a distinction the extraction never determined.

### S5 — PRH-07: the AI layer's two dead ends

`AiKeyword.evidence` (`src/database/models.py`) has **zero writers**, and `POST /api/ai/keywords/confirm` has
**no frontend consumer**. Both were built so a caller could use them. Wire them or retire them, and say
which; the read-only AI-keyword lens beside the trusted keywords is the natural consumer for both.

### S6 — The roster reduction after the one-model ruling

The bench roster still lists eight models. Six roster tests are **about** the dropped entries, so a blind
delete takes working guards with it. The drop must record why each went — especially the two that echo the
source verbatim (13% and 11% of items on a 298-translation field probe), which is the one translation failure
a reader cannot detect and therefore the one worth writing down.

Also here: move the custom-model field to the buried advanced position the ruling asks for; prefill
`#vllm-model-input` from the stored `llm_model_vllm` (PRH-09); and call
`configure_ollama_store_access` from `src/llm/installer.py`, where it is defined, test-pinned and never
invoked (PRH-21).

### S7 — D5, D8, D9, AI-15

- **D5:** the refused-field list in the AI check is uncapped (thirty caveat lines on one real report shape).
  Collapse behind a count, or keep, per the ruling.
- **D8:** multi-model specialisation — the harness is built, the measurement is an operator step on the rig,
  and the task-to-model map stays a parameter rather than a Settings knob until there is a figure.
- **D9:** the live ollama.com library browse. Recommended default is to drop it; the curated dated catalog
  plus the free-text tag box covers the need and a live browse is a network surface with a maintenance tail.
- **AI-15:** one lookup — is the Ollama account `LiquidAI` the publisher's own? It decides whether
  `LiquidAI/lfm2.5-1.2b-instruct` is a first-party tag.

## 2. Scope fence

Do not change the default model. Do not relax the hardware gate's two-predicate invariant — `detect_gpu()`
answers "can vLLM run here" and `inference_capability()` answers "is local inference practical", and
collapsing them routes every Mac to a vLLM that cannot serve it. Do not state a hardware-damage claim. Do not
promote an AI output into the trusted index.
