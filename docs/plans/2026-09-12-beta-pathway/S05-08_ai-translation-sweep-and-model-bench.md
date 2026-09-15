# S05-08 — The AI-coordinator translation sweep and the model bench · 0.5, `RELEASE_0.5_GATE.md` row H

> **Scope:** `src/ai_layer/translate.py` (loopback-only, ≈, the process cache), `coordinator.py` (the
> background-AI coordinator), the `keyword_translations` table of 0.4 row K (Q404 🔒), a coordinator-managed
> translation sweep, the list/hover surfaces of 0.4 row M, the reader's on-demand full-article translation,
> the multi-model bench (`model_bench.py`, `specialisation.py`, `bench_batch.py`), a consented ollama.com
> library browse, `perception_extract.py`'s `language_gate`, the KPI board's K6. Must NOT: store a
> translation as the article, pull a model on its own, reach ollama.com without consent, enable a perception
> language whose measured gate fails, reach any non-loopback LLM, touch the ladder's trusted index.
> **Implements:** Q405, Q513 = b + c, Q1142, Q1143, Q1144 (none ⛔, none 🔒).
> **Gated on:** 0.4 row K (the `keyword_translations` table); 0.4 row M (the "translated from X" grammar,
> the ladder); 0.4 row H (`docs/SECURITY.md` enumerated). Nothing PENDING.
> **Sequencing:** S1 first — Q1142 runs the bench WHEN the sweep lands; the browse (S5) is independent; the
> perception languages (S6) last, on the measured gate.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q405** — **(a)** «(a) Shown by default once persisted, ≈-marked, when the AI coordinator is on; filled
  by a background sweep over the untranslated head.» [placement: the sheet's Q1142 places the sweep in 0.5]
- **Q513** — **(b)** «(b) Also article titles and summaries, translated by the local LLM, ≈-marked, shown
  on hover and in lists when the AI coordinator is on; never stored as the article; opt-in.» **and (c)**
  «(c) Also full-article translation in the reader, on demand, local LLM, ≈, never stored as the article.»
- **Q1142** — **(a)** «(a) Run it when the AI-coordinator translation sweep (Q405) lands in 0.5.»
- **Q1143** — **(a)** «(a) Consented, opt-in, egress named.»
- **Q1144** — **(a)** «(a) Enable per language only where the measured gate passes; `who` stays refused
  where it fails.»
- The table this slice rides, ruled in 0.4: **Q404 🔒 = (a)** «A `keyword_translations` table (term, source
  lang, target lang, text, model, prompt version, created) — never the trusted index, always ≈, rides the
  backup.»

**Register round 2026-09-15 (D8, D9, D10):** D8: «wait for the app wide one model ruling, new models might come
up and change what's best for the user. Wait. Mark that we need the decision to be made before version 0.8 r»
CONFLICTS with Q1142 = a (`RC04`) — the bench part of this brief is contested; the decision itself is 0.8 row C.
D9 = `default` (drop the live browse) CONFLICTS with Q1143 = a (`RC09`). D10 consistent.

**RC round 2026-09-15 — BLANK (0 of 22 `ANSWER` lines carry a letter); §0's blank rules applied, nothing resolved.** Two assumptions reach this slice, and both make it smaller.
**`RC04` → (a): the multi-model specialisation bench is NOT run here.** The app-wide one-model decision is
taken before 0.8 opens (0.8 row C; the 0.7 exit clause), so this slice drops its bench part rather than
producing numbers for a decision that will be taken on other grounds. **`RC09` → (a): the live ollama.com
library browse is DROPPED** — no new consented host, no search-and-filter UI, no ×12 strings for it; the
custom-model field stays the only path, and the reason is recorded rather than the surface built. D10 /
Q1144 (cleared fields only, the production sweep on, the per-field refusals rendered) is unchanged, and so
are Q405 and Q513. Both CONFLICTS stay recorded on their index rows.

## 2. Where this stands in the tree — the staleness guard, with anchors

- `src/ai_layer/translate.py` is "Local loopback only (Ollama); airplane mode (the kill switch) …
  A small process-global cache avoids re-translating the same term" (grep-verified head); the sheet §5
  (VERIFIED): a 5,000-entry process cache lost on restart, reached only by a button;
  `translation_coverage` ≈ 5% of top keywords. `keyword_translations` does not exist (grep-verified in this
  brief: `grep -rn keyword_translations src/` → nothing — 0.4 row K builds it).
- `src/ai_layer/coordinator.py`: "Ollama serves ONE generation at a time … independent sweeps simply queue"
  (grep-verified head) — the sweep is a coordinator-managed progressive sweep, never a new toggle.
- The bench exists as instruments: `src/ai_layer/model_bench.py` ("every roster model … over the SAME
  frozen inputs … every metric ALONE"), `bench_batch.py` ("the FROZEN bench inputs … persisted as a dated
  artifact … each report carries the batch's DIGEST"), `specialisation.py` ("Several models, each with a
  speciality — is the one cell that justifies it real?"; design of record
  `docs/design/MULTI_MODEL_SPECIALISATION_2026-08-10.md`, present) (grep-verified heads); tests
  `tests/test_model_bench.py`, `tests/test_specialisation.py`.
- ollama.com is reached only as click-target links: `src/static/app-settings.js:571–572` (`linkText:
  "ollama.com/library"`, `href: "https://ollama.com/library"`), `app-ai-tools.js:690` (grep-verified) —
  every external link passes invariant #7's confirm; no live browse exists. `src/ingest/egress_window.py`
  is "a purpose-scoped, temporary exemption from the airplane-mode refusal" built for installer downloads
  (grep-verified head) — the precedent for a named, consented egress outside the collector.
- `src/ai_layer/perception_extract.py`: `language_gate` — "`None` is EPISTEMIC, not permissive"; a language
  never evaluated is gated "never evaluated", never assumed safe (grep-verified lines 26–41, 92–99); tests
  `tests/test_perception_extract.py`, `tests/test_perception_eval.py`.
- K6 (`LESSONS.md`, 2026-09-07, "A MODULE DOCSTRING CAN DESCRIBE A MECHANISM THAT DOES NOT EXIST"):
  translation coverage sat on the KPI board "structurally unreadable" because `engine_report` is computed
  on demand and never written — the gate's "persisted measurement" clause exists for this.
- 0.4 rows K, M and H are not in the tree at this brief's writing — verify each landed before building.

## 3. Slices — what to build, in order

### S1 — The sweep and its persisted coverage (Q405, Q404, K6)
- **What:** a coordinator-managed progressive sweep over the untranslated head filling
  `keyword_translations` (never the trusted index, always ≈); shown by default once persisted when the
  coordinator is on; its coverage written to a persisted file with an `as_of` that the KPI board reads
  (`not-measurable-here` when absent — never a recomputed on-demand number).
- **Acceptance:** the sweep's coverage appears on the KPI board as a persisted measurement (the gate's
  clause); the persisted-file guard mutation-checked (delete the file → the board says not measurable).

### S2 — Titles and summaries ≈, in lists and on hover (Q513 = b)
- **What:** article titles and summaries translated by the local LLM, ≈-marked, on hover and in lists when
  the coordinator is on; opt-in; kept in their own table keyed by article id + target language + model +
  prompt version — NEVER the article row; the label grammar of 0.4 row M ("translated from X") reused.
- **Acceptance:** a fixture proving the article row is byte-identical after translation; opt-in default
  off; the ≈ label ×12 with the caveat visible on hover.

### S3 — On-demand full-article translation in the reader (Q513 = c)
- **What:** on demand, local LLM, ≈, never stored as the article; the original stays visible; provenance
  (model, prompt version) in the hover; a visible job while it runs, never a frozen tab.
- **Acceptance:** Chromium-verified with its ≈ label in two locales (the gate's clause); the article row
  unchanged after the translation.

### S4 — The multi-model specialisation bench run (Q1142)
- **What:** when S1 lands, run the bench on the FROZEN batch (its digest stated) per the design of record,
  every metric reported alone, the fixture stated; no default model changes from a bench result.
- **Acceptance:** the bench report exists with its fixture stated (the gate's clause).

### S5 — The consented ollama.com library browse (Q1143, Q1001, Q1014)
- **What:** opt-in; the egress NAMED to the user ("this contacts ollama.com and reveals your IP to it")
  under the ONE online consent; refused under the kill switch by name; `docs/SECURITY.md` and the consent
  hover in the same diff; transport per the setting, never downgraded; model pulls stay Ollama's own.
- **Acceptance:** the consent + kill-switch fixture (socket guard armed: zero resolutions); the hover ×12.

### S6 — Perception extraction languages (Q1144)
- **What:** enable per language only where the measured gate passes; `who` stays refused where it fails;
  the gate's numbers (the eval's n and rate) on the toggle.
- **Acceptance:** a negation fixture — a failing language stays refused after the toggle is turned on.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the S5
consent and named-refusal fixture; the negative-space lens — no coordinator → nothing ≈ shown; a language
the model failed → absent, never blank; the article row byte-identical after S2 and S3; the K6 persisted
file absent → "not measurable"; the whole-tree guard set; `node --check`; the three i18n gates; the Chromium
click-through of a list with ≈ hovers and the reader's on-demand translation in `en` and `ar`, stamped
"Chromium-verified (remote sandbox) · awaiting human UX pass". No GPU here (the base working mode §6): the
bench beyond the fixture scale is `not-measurable-here`.

## 5. Operator steps

1. The bench run on the maintainer's Ollama rig over the frozen batch → the bench report with its fixture
   digest (`not-measurable-here` beyond the fixture scale).
2. The click-through of the §4 surfaces (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- Which models the bench rosters (the maintainer's rig) and any default-model change (a ruling, never a
  bench result acting on its own).
- The sweep's head size and cadence — the coordinator's budget, measured on the reference VM, then stated.
- Whether the article-level ≈ titles/summaries ride the backup (Q404's table does; Q513 is silent — asked).
- The per-language perception thresholds — measured by the eval harness, never set here.
- Where the browse lives (beside the existing library link in Settings is the obvious place — a design note).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
