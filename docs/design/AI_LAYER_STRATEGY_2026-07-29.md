# AI layer: backend viability, model selection, and the honesty gap

**Status:** design of record. Nothing in this document is built.
**Date:** 2026-07-29 · **Base:** `main` @ 67d0a3f (v0.3.0)
**Evidence:** the operator's `oo-all-diagnostics` bundle of 2026-07-29T07:46, plus
hand-verification against the live tree. Every claim below carries its anchor.

This composes with — and does not restate — `V1_PATHWAY_2026-07-14.md` (the KPI
board), `AUTONOMOUS_SESSION_BRIEF_2026-07-24_B_AI_STACK.md` (what shipped), and
`SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md`.

---

## 0. Summary

Three findings, in descending order of how much they cost:

1. **The vLLM install cannot succeed on the operator's GPU machine**, for a
   reason this project already diagnosed and fixed once elsewhere. The machine
   also has no working Ollama, so it currently has *no* AI backend at all.
2. **The perception eval gate has a one-sided failure mode**: a model that
   extracts nothing is stamped as having passed, for every language.
3. **The shipped default model contradicts the maintainer's own ruling**, and
   neither candidate has ever been benchmarked on this app's tasks.

Two of these are small fixes. The third is a decision, not a build.

---

## 1. vLLM install — root cause

### 1.1 What the bundle shows

From `ai.json` and `manifest.json` of the 2026-07-29 bundle:

| Fact | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4070 Laptop, **8188 MB VRAM** |
| CPU | i7-13620H, **2 physical / 2 logical cores** |
| **System RAM** | **6,025,867,264 bytes ≈ 6.03 GB** |
| Swap | 1.07 GB |
| Disk free | 378 GB |
| OS | `Linux-6.18.31-1.qubes.fc41` — a **Qubes AppVM** |
| `vllm.installed` | `false` |
| `vllm.install_info` | `null` |
| `ollama_available` | **`false`** |
| `active_model` | `granite4:micro` |

The GPU is real and detected. The host, however, is a 2-core / 6 GB Qubes VM.

### 1.2 The mechanism

`run_install_job` (`src/llm/vllm_lifecycle.py:407`) runs
`pip install vllm==0.26.0` through `_default_runner`
(`src/llm/vllm_lifecycle.py:467`), which is a bare:

```python
proc = subprocess.Popen(argv, stdout=..., stderr=..., text=True, bufsize=1)
```

**There is no `env=` argument.** The subprocess therefore inherits the ambient
`TMPDIR`, which on Qubes is `/tmp` — **a tmpfs, backed by RAM**.

vLLM pulls torch and the CUDA runtime wheels. The module's own constant calls
this "typically 5-10 GB combined" (`ESTIMATED_INSTALL_SIZE_NOTE`,
`vllm_lifecycle.py:66`). pip unpacks wheels in `TMPDIR` before installing them.
Unpacking multi-GB wheels into a RAM-backed `/tmp` on a box with 6.03 GB of
total RAM fails with `ENOSPC` / `Errno 28` — **while `df` reports 378 GB free**,
which is exactly what makes the symptom confusing.

### 1.3 This is a recurrence, not a new bug

The project already hit this, diagnosed it, and recorded it:

- `CLAUDE.md:519-520` — *"pip unpacks big wheels in `TMPDIR` (=/tmp = tmpfs on
  Qubes) → `Errno 28` even with disk free; point `TMPDIR` at the install volume
  + classify disk-full vs network failures honestly."*
- `docs/ledger/SHIPPED_LOG.md:836-843` — the original fix, applied to
  `install.sh:pip_install`, for scipy/numpy/pandas wheels.

`vllm_lifecycle.py` is a newer module. It never inherited the fix, and vLLM's
wheels are an order of magnitude larger than the ones that caused the original
failure. Verified absent:

```
grep -n "TMPDIR|tmpdir|free_bytes|ram_total|disk_free|shutil.disk_usage|MemTotal" \
  src/llm/vllm_lifecycle.py   →  no matches
```

### 1.4 Three further gaps in the same path

**No resource preflight.** `run_install_job` refuses on non-Linux
(`platform_support()`), airplane mode (`_check_online()`), and no-GPU
(`detect_gpu()`). It checks **neither system RAM nor disk**. So a 6 GB / 2-core
box is invited to install a 5–10 GB GPU serving stack with no warning. The
module's own docstring says `platform_support()` exists precisely so a doomed
install becomes "an honest, actionable refusal instead of a confusing raw
pip/subprocess error" — the intent is right, the check set is incomplete.

**A failed install leaves no durable trace.** The marker is written only on
success (correct — `is_installed()` never claims a half-configured backend
works). But the *failure* is raised as a `VllmLifecycleError` into
`BackgroundJob` state, which is in-memory. After the app restarts,
`install_info` is `null` and nothing anywhere records that an install was
attempted or why it failed. The operator's only recourse is to reproduce it
live. A backend install is exactly the kind of long, fallible, once-in-a-while
operation that should leave a persisted record.

**`resolve_backend()` reports a fallback that isn't running.** The bundle shows
`reason: "GPU detected but vLLM is not installed -- using Ollama meanwhile"`
while `ollama_available: false`. The sentence is true about *selection* and
misleading about *capability*: there is no working backend on this machine. The
reason string should distinguish "fell back to Ollama, which is up" from "fell
back to Ollama, which is also unavailable — no backend".

### 1.5 The honest viability question

Fixing `TMPDIR` will very likely get the install to *complete*. Whether vLLM
will then *run usefully* on this host is a separate question, and it deserves a
straight answer rather than a smoother install button.

vLLM is designed for server GPUs with substantial host RAM. It needs host memory
for the Python process, the CUDA context, and the model-loading path, on top of
the 8 GB of VRAM. **6.03 GB of total system RAM with 1 GB of swap and 2 cores is
very marginal**, independent of the GPU. I have not measured this, and I am not
going to assert a threshold I cannot source — but the preflight should surface
the number and let the operator decide, rather than discovering it after a
multi-GB download.

The concurrency prize is real: vLLM's continuous batching is what would let the
throughput work land. That argues for making the install *diagnosable*, and for
measuring the outcome on this exact host — not for assuming it will work.

### 1.6 Remediation

Ordered, independently shippable. Slices V1–V3 are small.

**V1 — point `TMPDIR` at the install volume.** Give `_default_runner` an
optional `env` parameter; in `run_install_job`, pass an env whose `TMPDIR` is a
directory created under `venv_dir().parent` (the data dir, on real disk),
cleaned up afterwards. Mirror `install.sh:pip_install`'s already-proven shape.
Test: assert the runner receives an env whose `TMPDIR` is not `/tmp` and lies
under the data dir.

**V2 — a real resource preflight, before any download.** Extend the refusal set
with: free disk on the venv volume (need ≥ ~15 GB for a 5–10 GB install plus
unpack headroom) and total system RAM. Report RAM as an honest **warning with
the number**, not a hard refusal — the operator may know something the check
does not — but require explicit confirmation below a stated floor. Surface the
same numbers in the pre-install UI so the cost is visible before the click, per
the standing "state the cost before arming" convention.

**V3 — persist install attempts.** Write a `vllm_install_attempts.jsonl`
sidecar next to the marker: timestamp, version, phase reached, exit code, the
last N lines of pip output, and the preflight snapshot (RAM/disk/GPU). Ride it
into `ai.json` as `install_history`. Secret-safe — pip output carries no
credentials, but scrub anyway per the established `_scrub` convention. This is
what turns "vLLM install failed" into a diagnosable event.

**V4 — honest backend reason strings.** `resolve_backend()` must distinguish
*selected-and-available* from *selected-and-unavailable*. Add an explicit
`no_backend: true` state when neither is reachable, and surface it on the AI
pill (which is already green/red) with the actual reason.

**V5 — measure it on this host.** Once V1–V3 land and an install completes,
record the real numbers: peak host RSS during load, time to first token, and
whether concurrent requests actually improve aggregate throughput at this VRAM.
That measurement belongs in the model bench (§3), not in a claim here.

**Not in scope:** switching serving stacks, bundling weights, or relaxing the
torch-out-of-core dependency law. vLLM stays an external process in its own
venv.

---

## 2. The default model: Mistral vs Granite

### 2.1 I am not arguing for Granite

To be direct, since the question was put that way: **I did not recommend
Granite.** `granite4:micro` is simply what the code already ships:

```
src/llm/ollama.py:83   DEFAULT_MODEL = os.getenv("OO_LLM_MODEL", "granite4:micro")
```

What I flagged is a **drift**: the maintainer ruled Mistral-7B the default on
2026-07-24 (ledger ruling A13), and the code does not implement that ruling. The
operator's own bundle confirms the live value is `granite4:micro`. That drift is
the finding — not a preference for IBM.

It also means the one data point everyone has been reasoning from — the 94.7%
`who`-extraction hallucination rate — was measured on `mistral:7b`, **a model a
fresh install does not run**. Nobody has benchmarked the actual shipped default
on any of this app's tasks.

### 2.2 What can honestly be said about the two

From the catalog (`src/llm/ollama.py:55-64`, `CATALOG_AS_OF = "2026-06"`):

| Tag | Size | `min_ram_gb` | License | Catalog note |
| --- | --- | --- | --- | --- |
| `mistral:7b` | ~4.4 GB | 8 | Apache-2.0 | "prioritised" |
| `granite4:micro` | ~2.1 GB | 8 | Apache-2.0 | 3.4B hybrid, "the app's default" |
| `granite4.1:3b` | ~2 GB | 8 | Apache-2.0 | **multilingual** |
| `granite4.1:8b` | ~5 GB | 8 | Apache-2.0 | **multilingual** |

Two observations, and I want to be clear about how weak they are:

- The Granite entries are the only ones the catalog explicitly annotates as
  *multilingual*. Multilingual coverage is a hard requirement here — the corpus
  spans 20+ languages. But a catalog annotation is an **assertion, not a
  measurement**, and this catalog carries its own recorded caution that a
  previous version was hallucinated.
- `mistral:7b` at ~4.4 GB is roughly double `granite4:micro` at ~2.1 GB. On this
  fleet that matters: the weakest box is 3.46 GB, where **`mistral:7b` cannot
  load at all**, and the GPU box measured above has 6.03 GB of host RAM.

Neither observation is a quality argument. **There is no evidence that Granite
is better than Mistral at this app's tasks, because no such measurement exists.**

### 2.3 The real answer: one default cannot serve this fleet

The fleet spans 3.46 GB CPU-only boxes to an 8 GB-VRAM GPU VM. A single default
tag is wrong for one end or the other whatever it is set to:

- On the **GPU VM**, weights live in VRAM. `mistral:7b` fits 8 GB comfortably.
  The maintainer's preference is straightforwardly satisfiable here.
- On the **3.46 GB box**, `mistral:7b` is unloadable. `granite4:micro` (2.1 GB)
  is borderline; `granite4:350m` or `qwen3:1.7b` (~1.4 GB, Apache-2.0) are what
  actually run.

So the proposal is a **hardware-resolved default with a disclosed reason**, which
is the same shape as `resolve_backend()` already uses: prefer the operator's
chosen model; if it cannot fit the detected hardware, fall back down a stated
ladder and *say so in the UI*, never silently. That satisfies the Mistral
preference wherever Mistral fits, and stops the weak boxes from defaulting to a
model that cannot load.

**Recommendation:** set the preferred default to Mistral per the standing ruling
(closing the drift), add the hardware-resolved fallback ladder, and let the bench
(§3) decide whether the preference should change. If Mistral and Granite are
within noise on triage and tagging, the preference is the tiebreaker and Mistral
wins — that is the maintainer's call to make, and there is no evidence against it.

### 2.4 Ministral — a genuine gap, with one blocker to check

**Ministral is not in the catalog at all** (verified: no match for
`ministral` in `src/llm/ollama.py` or `configs/`). Only `mistral:7b` and
`mistral-small:latest` are present.

On the merits it is an attractive candidate: the 3B class is exactly the size
band this fleet needs, and it would satisfy the Mistral preference *and* the
memory constraint simultaneously — which `mistral:7b` cannot do.

**The blocker to verify before adding it is licensing.** Every non-restricted
model in this catalog is Apache-2.0 or MIT; the restricted ones (Gemma, Llama
Community, NVIDIA Open Model License) are explicitly labelled "use
restrictions". The recollection recorded here was that the Ministral family
shipped under a **Mistral Research License** (non-commercial research use)
rather than Apache-2.0 — which would be disqualifying for an application given
away free, and stronger than the "use restrictions" the catalog already
tolerates. That was flagged as explicitly unasserted, pending research.

#### RESEARCH RESULT (2026-07-29, same day) — the blocker is probably cleared

The web research came back **favourable, with one caveat that must not be
skipped**:

- **Ministral 3 (3B / 8B / 14B) is reported as Apache-2.0** — a licence change
  from the previous generation. The recollection above was correct about the
  *old* family (Ministral 8B-2410 did ship under the non-commercial Mistral
  Research License) and **wrong about the current one**.
- **The caveat: no licence was read from a model card.** The Apache-2.0 finding
  is search-convergence, **single-sourced**, against a family with a documented
  licence-flip history. The verifying agent's own words: *"This deserves one
  confirmation before it lands in a catalogue."* Given this repo's hallucinated-
  catalogue incident, **one page fetch of the model card settles it** and must
  happen before any catalog entry.
- **Tag:** `ministral-3:3b-instruct-2512-q4_K_M`, ~3.0 GB, `[search-verified]`.
  The short `ministral-3:3b` form **could not be verified**, and the researcher
  correctly refused to substitute it — do not invent the short tag.
- **Multilingual gap — the substantive concern.** The enumerated language list
  names only **ar, zh, ja, ko**. Absent: **ru, hi, bn, id, th, vi, el, sr, mr**.
  For a corpus spanning 20+ languages that is a real limitation, and it is
  precisely the axis where a 3B model is most likely to disappoint. It does not
  disqualify Ministral, but it means the bench (§3) must report **per-language**
  results before it is made a default anywhere.
- Unresolved: an Ollama ≥0.13.1 version gate and a possible multimodal/mmproj
  footprint (dead weight on a 3.46 GB box).

**Net:** at ~3.0 GB it fits the fleet where `mistral:7b` (~4.4 GB) cannot, and
it satisfies the Mistral preference. **Action: fetch the model card to confirm
Apache-2.0, then add it** — and measure it per-language rather than assuming
the multilingual tail.

**Wider warning from the same research.** Its own anti-fabrication critic caught
the draft roster presenting unsourced numbers as fact — a RAM-at-context figure
with no source ("the exact shape of the prior hallucinated catalogue"), a
throughput claim absent from the evidence, and a model recommended for "all
tiers" whose licence, quant size, per-language quality and JSON reliability were
*all* unverified. It also caught the draft asserting "Serbian has zero evidence
anywhere" while omitting that the one Serbian-capable candidate had been dropped
earlier on licence grounds. **Treat that roster as leads requiring fetches, not
as a catalog.**

---

## 3. The measurement that settles all of this

Everything in §2 is a preference argument in the absence of data. The
`pagesize_bench.py` precedent is the right shape and already exists in-repo:
rebuild per candidate, identical deterministic workload, runtime self-verify,
**side-by-side numbers and never a declared winner**.

The critical design point: **separate the quality signals that need no human
grading from those that do.** The ground-truth-free ones ship first, because
this project's gold sets have sat ungraded for months and a design that depends
on grading will not ship:

- format compliance / parse-rejection rate
- echo-back rejection rate (the shipped triage chassis already does this)
- canary accuracy on hand-known items
- cross-model agreement
- self-consistency across repeated cheap samples
- verbatim-span verification (does the emitted string occur in the source?)

Cost metrics ride alongside: load time, tokens/sec, wall-clock per item, peak
RSS/VRAM, timeout rate, abstention rate. Hallucination rate and parse-failure
rate are **reported separately and never merged**.

Hardware handling: the same batch on a 2-core box and the GPU VM produces
incomparable timings, so the hardware profile (already captured in the bundle
manifest) is recorded with every run. A model too large for the box reports
**`not-measurable-here`, never a fail**. Note the trap: on a 3.46 GB box
essentially nothing reports as comfortably fitting, so a naive
skip-unless-fits gate renders the bench empty on the machine it most exists to
serve — gate on `too_large`, not on `!= fits`.

The detailed bench design is the subject of the research now in flight and will
land as its own document.

---

## 4. Verified AI-layer findings

These four were hand-verified against the tree, not taken from an agent report.

### 4.1 A model that extracts nothing passes the gate

- `src/analytics/perception_eval.py:80` —
  `hallucination_rate = fp / (tp + fp) if (tp + fp) else None`
- `src/ai_layer/perception_extract.py:79-81` — fails only
  `if rate is not None and rate > MAX_HALLUCINATION_RATE`
- else branch → `{"active": True, "reason": "cleared the S6.5 harness"}`

An extractor returning empty for every article yields `tp+fp == 0` → `rate =
None` → never fails → **licensed for every language**. There is no recall check
in that loop. The gate catches a model that invents; it does not catch one that
says nothing.

Compounding it: the gold is 17 synthetic cases, n=1 for 11 of 12 languages, and
nine of those carry only `where` gold. For three-quarters of the UI locales the
gate reduces to "named one city, correctly stayed silent twice."

**Fix:** add a recall floor; make the gate **tri-state** (`true | false | null`)
where `null` = "no harness — running unmeasured" and is never describable as
cleared; carry `n_cases` into every entry so the visible reason can say "cleared
on 1 synthetic case — low power". Evaluate recall only on fields with non-empty
gold, or the nine `where`-only languages fail on a field they were never tested
on. This will correctly disable languages that currently read as active —
communicate it as the fix, not discover it as a regression.

### 4.2 Nothing the AI layer produces is inspectable

- `AiKeyword.evidence` exists (`src/database/models.py:1836`) and has **zero
  writers** (verified: no `evidence=` in `src/ai_layer/` or `src/api/ai.py`).
  A fabricated name and a real one are indistinguishable in the store.
- `POST /api/ai/keywords/confirm` has **no frontend consumer**.
- Indexes on `ai_keyword` are `(article_id, kind)` and `(term)` — nothing on
  `kind` or `created_at`, so a corpus-wide candidate browse has no supporting
  index and would repeat the `/api/database/countries` pathology.

**Fix:** require every stored AI candidate to occur **verbatim in the source
article**; drop what does not, count it, and write the verbatim sentence into
that dormant column. The verifier is a rule, not a model — the deterministic
half does the checking so the model only reads. Record three counters
(`returned` / `verified` / `dropped`), because zero-stored currently conflates
"produced nothing" with "produced ten fabrications" with "the article genuinely
has no who".

### 4.3 A live fabricated measurement, unrelated to LLMs

`src/awareness/framing.py:81`:

```python
avg = sum(tones) / len(tones) if tones else 0.0
```

An empty tone set publishes a **neutral tone of 0.0**. Its sibling
`src/analytics/sentiment.py:55` does the opposite and documents why: *"we NEVER
fabricate a 'neutral' for a language the lexicon cannot read."* One module
honours the rail; the other breaks it. XS fix, ships independently.

### 4.4 Throughput arithmetic bounds what is buildable

The only **measured** rate is ~2,100 keywords in ~7 h on a healthy 6-core box.
The often-quoted ~2.6-year figure for a full 6.9M-keyword sweep is **derived**
from that, assuming batch=25 and serial execution — not measured, and it should
never be quoted as though it were.

Either way the conclusion holds: **corpus-wide per-article LLM passes on CPU are
arithmetic-dead.** The sweep whose arithmetic actually closes is stoplist
worklist categorisation — ~500 terms/language, ~240 calls ≈ 20 h, one-off per
review cycle, with gold already in-repo (34 accepted-furniture files as
positives, the recorded dual-use tail as negatives). That is the shape to build:
**bound the LLM to a reviewable worklist, not the corpus.**

---

## 5. Why closed-set tasks are the right first target

The 94.7% figure was measured on open-ended entity generation — the hardest
possible shape, where the model emits an unbounded set of strings and nothing
mechanically checks them.

Keyword triage and article tagging are the opposite shape. The output space is
**finite and known**, so an invalid answer is mechanically rejectable and cannot
silently enter the data. The existing triage chassis already implements the
machinery this depends on — echo-back validation, canaries, closed vocabularies.

That distinction is why the honest reading of 94.7% is *"this model, on the
hardest task shape, unpinned"* — not *"local models do not work here"*. It also
means the app is currently under-using small models in the place they are
strongest, having measured them only in the place they are weakest.

---

## 6. Open maintainer rulings

1. **Default model.** Close the drift toward Mistral per the standing ruling,
   plus a hardware-resolved fallback ladder? (Recommended.)
2. **Ministral.** Research reports Ministral 3 as Apache-2.0 (§2.4), so the licence
   blocker is probably cleared — but it is search-verified only. Fetch the model
   card to confirm, then add `ministral-3:3b-instruct-2512-q4_K_M`? Note the
   unverified multilingual tail (ru/hi/bn/id/th/vi/el/sr/mr are not named).
3. **vLLM on the 6 GB host.** Fix the install and measure, accepting it may
   prove unviable on this host; or treat the GPU VM as needing more RAM first?
4. **RAM preflight posture.** Hard refusal below a floor, or a warning with the
   number and explicit confirmation? (Recommended: warn + confirm.)
5. **Evidence-column storage.** Always-on, or a setting a disk-constrained
   operator can disable while keeping drop-and-count?
6. **Gate tri-state rollout.** §4.1 will correctly disable languages that
   currently read as active. Land it as a visible fix, or behind a flag first?

---

## 7. Sequencing

```
V1 (TMPDIR) + §4.3 (framing) + §4.1 (gate)        — small, independent, ship first
V2/V3 (preflight + install history)                — unblocks diagnosis
§4.2 (span verification + evidence column)         — highest structural value
V4 (backend reason strings) + §2.3 (default ladder)
§3 (bench: ground-truth-free metrics first)
V5 (measure vLLM on the real host)
§4.4 (stoplist worklist sweep — the one that closes)
```

---

## Appendix — verification status

| Claim | Status |
| --- | --- |
| TMPDIR unset in the vLLM install path | **verified** — no match in `vllm_lifecycle.py` |
| Prior TMPDIR fix exists for `install.sh` | **verified** — `SHIPPED_LOG.md:836-843` |
| Hardware profile (2 cores / 6.03 GB / RTX 4070) | **verified** — operator bundle `manifest.json` |
| `vllm.installed: false`, `ollama_available: false` | **verified** — operator bundle `ai.json` |
| Shipped default is `granite4:micro` | **verified** — `ollama.py:83` |
| Null extractor clears the gate | **verified** — `perception_eval.py:80` + `perception_extract.py:79-81` |
| `AiKeyword.evidence` has zero writers | **verified** — grep across `src/ai_layer/`, `src/api/ai.py` |
| `framing.py` fabricates a 0.0 neutral | **verified** — `src/awareness/framing.py:81` |
| Ministral absent from the catalog | **verified** — no match in `src/llm/ollama.py`, `configs/` |
| ~~Ministral license is research-only~~ | **SUPERSEDED 2026-07-29** — true of the 8B-2410 generation; Ministral 3 is reported Apache-2.0 (§2.4) |
| Ministral 3 is Apache-2.0 | **search-verified only, single-sourced** — never read from the model card; one page fetch from confirmed |
| Ministral tag `ministral-3:3b-instruct-2512-q4_K_M` | **search-verified** — the short `ministral-3:3b` form could **not** be verified; do not substitute it |
| Ministral covers ru/hi/bn/id/th/vi/el/sr/mr | **NOT verified — absent from the enumerated language list**; only ar/zh/ja/ko are named |
| vLLM unusable at 6 GB host RAM | **UNVERIFIED — plausible, not measured; V5 settles it** |
| zh/ja/th FTS search failure | **reported by analysis, not re-verified here** |
| ~2.6-year sweep projection | **derived**, not measured |
