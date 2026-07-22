> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — **SUPERSEDED for its unexecuted items.** A 2026-07-22 audit found almost none of T1–T10 was ever executed: no docs/README.md index reconciliation (T1), no `test_docs_index_covers_live_docs` invariant (T2), AUDIT_TRAIL.md still stops around 2026-06-14 (T3), no USER_MANUAL staleness banner (T5), QUICKSTART still says "Phases 2–5" (T6), and the archival sweep (T8) had never run before this pass. The remaining items are now carried forward as Phase 1 of `ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md` — treat that plan as authoritative for what's left. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Action plan — documentation review & reconciliation (2026-07-17)

**Status:** plan of record, ready for execution. **Executor:** a Claude Code CLI session
(one session; docs-only + one small guard test — no product code changes).
**Written by:** the 2026-07-17 documentation-review session, after a full survey of the
documentation tree at `main` tip `786a5c1` (2026-07-16). **Every anchor below was
verified against that tree on 2026-07-17** — but the maintainer fast-merges, so run the
staleness guard (re-verify each task's "verified current state") before executing it.

**Mission in one line:** the *content* of the documentation is in unusually good shape
(everything touched within the last week; the 2026-07-15 external audit's doc findings
already remediated) — what drifted is the **meta layer**: the index, the audit trail,
and a handful of historical framings inside live guides. This plan closes those gaps
and adds one guard so the index can't silently drift again.

---

## 0. Working mode (binding conventions — the house rules)

- **Base:** `git fetch origin main` immediately before cutting/rebasing the work branch
  (`git checkout -B <branch> origin/main`) — the stale-base hazard is real here
  (#548 precedent; fast merges).
- **PR strategy:** ONE draft PR onto `main`, **one commit per task** (T1+T2 may share a
  commit — the test pins the index). Nothing self-merges; the maintainer review is the gate.
- **Gates per commit:** `python3 -m pytest tests/test_repo_invariants.py -q` (the py3.13
  `.venv` runs the full suite if present — prefer it); `scripts/i18n_report.py --min 100`
  ONLY if locale files are touched (not expected); no `node --check` needed (no JS/HTML
  edits expected). Run the T2 guard test locally before pushing.
- **Staleness guard:** before each task, re-verify its "verified current state" block.
  A finding that is already fixed is **verify-and-marked, never rebuilt**.
- **Honesty rules that bind these edits:** reconcile live guides to **code ground truth**
  (`src/static/index.html` for UI claims); historical/archived docs are RECORDS — never
  rewritten, at most banner-marked. Never delete content non-lossily reachable only here
  (`git mv`/pointer instead). The legal docs' remaining `[À COMPLÉTER : …]` markers are a
  **deliberate permanent choice** (see `docs/legal/README.md`) — do NOT "fix" them.
- **Ledger closeout (mandatory):** one `docs/ledger/shipped.csv` row per task (or one row
  for the batch with per-task detail in the summary), and tick off the corresponding
  bullet in the CLAUDE.md Open-queue entry for this plan. Additive merges only on the
  shared ledger files.

**Out of scope, explicitly:** any product-code change; the `[À COMPLÉTER]` legal markers
(deliberate); anything under `docs/archive/` (records); CLAUDE.md compression (protocol
rule 5 territory, maintainer-gated); executing PARKED.md's still-open engineering items
(T7 only *reconciles the record*, it does not build).

---

## T1 — Reconcile `docs/README.md` (the documentation index) — P1, size S

**Problem:** the index was last reconciled 2026-07-11 and no longer covers the live set.
A reader navigating from the index cannot discover several load-bearing documents —
most importantly the **legal tree that now gates first launch**.

**Verified current state (2026-07-17):** `docs/README.md` does NOT mention any of:

| Missing entry | What it is | Suggested index section |
|---|---|---|
| `docs/legal/` (via `legal/README.md`) | CGU · privacy (RGPD) · mentions légales · usage charter ×12 langs; wired into first-launch consent; finalized v1.0 on 2026-07-16 | **Trust it** |
| `GOVERNANCE.md` | dual-use red lines, acceptable use, misuse resistance (backed by `test_red_lines_not_crossed`) | **Trust it** |
| `CODE_OF_CONDUCT.md` | contributor conduct | **Contribute / history** |
| `QUARANTINE_ARCHIVE.md` | the permanent record of the removed ~79.5k-line quarantine tree | **Contribute / history** |
| `docs/audit/` | the 3 records of record + the 2026-07-13 cumulative integrity audit + the 2026-07-15 external audit | **Trust it** (or History) |
| `../AUDIT_TRAIL.md` (root) | append-only ledger of audit runs | **Trust it**, beside `docs/audit/` |
| `../PARKED.md` (root) | deferred v0.0.7-audit backlog (being reconciled by T7) | **Plan / track** |
| `process/IMPROVEMENT_CYCLE.md` | the standing R4 recursive-improvement protocol | **Plan / track** |
| `product/USE_CASES.md` | product use cases | **Understand it** |
| `maintenance/EXTERNAL_DEPENDENCIES.md` | the external-artifact registry + upgrade checklist | new **Operate / maintain** subsection (or Plan / track) |
| `testing/` (`LEGAL_DECLINE_UNINSTALL_TEST.md`) | destructive-path test procedure | Operate / maintain |
| `research/` (via `research/README.md`) | verbatim internet-research artifacts (leads, verify-before-trust) | **Understand it**, with the verify-before-trust caveat |
| `i18n/` (`fr/QUICKSTART.md`) | translated-docs infrastructure (fr seed) | **Use it**, one line |

(The root `README.md` needs **no** work here — it already links the legal tree at
lines ~331 and ~354–366 and states the no-lawyer-review posture.)

**Steps:**
1. Extend the existing sections (Use / Understand / Plan-track / Trust / Contribute-history)
   with the rows above; add a short **Operate / maintain** subsection for
   maintenance + testing. Keep the file's terse one-line-per-doc style and the
   planning-homes map paragraph intact.
2. For `docs/legal/`, carry the honesty framing in the one-liner: *French-authoritative
   working documents, permanently without professional legal review (a stated choice)* —
   mirroring root README line ~331.
3. Link-check the finished file (every `](...)` target exists on disk — a 5-line Python
   snippet or `grep -oP '\]\(\K[^)]+'` + existence loop is enough).

**Acceptance:** every live (non-archive) doc or doc-subtree is reachable within one hop
from `docs/README.md`; zero dead links; T2's guard test passes.

---

## T2 — Guard test: the index can't silently drift again — P1, size S

**Rationale:** the project's own convention — a reconciled invariant gets a test
(`tests/test_repo_invariants.py` already has the same shape at
`test_in_app_docs_exist_on_disk`, line ~1421).

**Spec — add `test_docs_index_covers_live_docs` to `tests/test_repo_invariants.py`:**
- Read `docs/README.md` once.
- **Dynamic sweep:** every top-level `docs/*.md` file (except `README.md` itself) must
  appear by filename in the index; every direct subdirectory of `docs/` **except
  `archive/`** must appear by name (directory-level mention suffices — do NOT require
  per-file listing inside `design/`/`product/`/etc.).
- **Explicit extras:** `AUDIT_TRAIL.md` and `PARKED.md` (root-level) must appear.
- Keep a small in-test exemption list (initially empty) for any future deliberate
  omission, each entry requiring a reason string — the pattern the repo's other
  ratchet tests use.
- Failure message lists the missing names (actionable, like the neighbors).

**Acceptance:** test red on the pre-T1 tree (proves it bites), green after T1; full
`test_repo_invariants.py` stays green.

---

## T3 — Backfill `AUDIT_TRAIL.md` (root) — P1, size S

**Problem:** the file declares itself an *append-only ledger of audit runs, newest
first*, but its newest entry is **2026-06-18**, while two audits have run since and
live only under `docs/audit/`:

**Verified current state:**
- `docs/audit/CUMULATIVE_INTEGRITY_AUDIT_2026-07-13.md` — 324 shipped-claims sweep +
  16-claim deep-verify fan-out; headline "HIGH cumulative integrity, no #548-style
  silent revert"; exactly one ACT finding (BUG-1, the columnar CI-red swallowed exception).
- `docs/audit/EXTERNAL_AUDIT_2026-07-15.md` — transversal/docs-vs-reality audit at
  `da393591`; 8 findings (OO-01 restore-path SQLi **High**, OO-02 panic-wipe 4 MiB cap
  **High**, OO-03 numpy pin, OO-04..08 informational); remediated the same/next day
  (commits `18262b9`, `5a024ac`, `2309785`, `0f38a34`, `da7bb11`, `fec85b7` per
  `git log`).

**Steps:** append two entries at the TOP (newest first), each in the file's established
shape: date · commit audited · scope · headline findings · remediation status with
resolving commits · pointer to the full log under `docs/audit/`. Write them **from the
existing audit documents + git history only** — record what happened, assert nothing new.

**Acceptance:** `AUDIT_TRAIL.md` covers all audits that have a log under `docs/audit/`;
existing entries byte-untouched (append-only discipline).

---

## T4 — Fix the stale "Outstanding" note in the legal-decline test doc — P2, size XS

**Problem:** `docs/testing/LEGAL_DECLINE_UNINSTALL_TEST.md` (§Outstanding) says the
legal docs *"still carry `Version:` / `Date: [À COMPLÉTER]`; finalize them and bump
`CONSENT_DOC_VERSION`"* — written before the same-day finalization landed.

**Verified current state (2026-07-17):**
- `docs/legal/CGU.md:13` reads `**Version :** 1.0` (commit `e48ec10` finalized
  version/date fields; `7ab0741` dropped the "pending lawyer review" framing repo-wide).
- 66 `[À COMPLÉTER]`/`[À VÉRIFIER]` markers remain across 50 legal files — but these are
  now a **stated permanent choice** (`docs/legal/README.md` header), not pending work.
- Bullet 2 (the 11 non-French translations are AI-drafted, flagged for native review)
  is **still true** — keep it.

**Steps:**
1. Rewrite Outstanding bullet 1: versions are finalized (v1.0, 2026-07-16); the
   remaining bracketed markers are deliberate per `docs/legal/README.md`; the only live
   follow-through is *bumping `CONSENT_DOC_VERSION` on any future substantive edit*.
2. While there: verify `CONSENT_DOC_VERSION` in `src/legal/consent.py` is coherent with
   the finalized v1.0 documents (the accept flow records it — `src/legal/documents.py:155`).
   If it still encodes a pre-finalization value, flag it in the PR body for the
   maintainer (that's a code constant → maintainer decision, not a silent doc fix).

**Acceptance:** the doc's Outstanding section states only things that are actually
outstanding; no claim contradicts `docs/legal/README.md`.

**EXECUTED 2026-07-17, overtaken by a live maintainer decision (record, don't re-plan):**
the "66 markers … a stated permanent choice" premise above was overruled the same day —
the maintainer, hitting the brackets live in the legal review/acceptance screen, asked
for them to be **removed outright** (PR #702: the meta-explanatory sentence about the
`[À COMPLÉTER]`/`[À VÉRIFIER]` convention, present in every document's intro across all
12 languages, and a genuinely dangling SIREN/SIRET/VAT placeholder in
`MENTIONS_LEGALES.md`, also all 12 languages). Zero bracket markers remain
(`tests/test_legal_documents.py::test_no_document_carries_an_unresolved_completer_verifier_bracket`).
`docs/testing/LEGAL_DECLINE_UNINSTALL_TEST.md`'s Outstanding section was rewritten to
match. A follow-up sweep the same day also fixed a real, unrelated bug the T4 audit
missed: every translated copy's relative links to `LICENSE`, `README.md`, and
`IMPLEMENTATION_NOTES.md` were broken by one directory level (the translations live one
level deeper than the French originals, at `docs/legal/<lang>/`, but kept the shallower
originals' relative paths verbatim) — fixed across all 11 languages, plus a stale claim
in `IMPLEMENTATION_NOTES.md` that the web-GUI consent gate was still unbuilt (it shipped
2026-06-21, commit `5aefbc01`, as `src/static/unlock.html`'s `view-legal` step).

---

## T5 — USER_MANUAL: mark the historical section + re-verify nav ground truth — P2, size M

**Problem A (verified):** `docs/USER_MANUAL.md:2269` opens a top-level section
`# What shipped in 0.0.8 — the roadmap cycle` inside the live manual — a historical
record embedded without saying so, five release cycles later.

**Decision guidance (recommended):** keep it in place but retitle/banner it explicitly —
e.g. `# Feature history — what shipped in the 0.0.8 cycle (historical record)` with a
one-line note that current behaviour is described in §1–§7 and the deep-dives.
*Rationale:* moving ~30% of the manual to HISTORY.md would break deep links and the
in-app docs reader registry (`test_in_app_docs_exist_on_disk` pins files, and the
reader serves whole files); a banner is honest and cheap. If the CLI session finds the
section's content actively CONTRADICTS current behaviour anywhere, fix those spots to
ground truth (live manual > record).

**Problem B (needs in-session verification — precedent, not yet confirmed):** the
manual's nav/shell descriptions have gone stale twice before (caught by the 2026-06-15
and 2026-06-18 audits: dissolved Source-integrity tab, retired Search tab, the
World-map rename). Re-verify the current claims against `src/static/index.html`:
- `USER_MANUAL.md:135` + `:264` — "left sidebar … flat list of the data tools": diff the
  listed tabs against the actual `data-tab` nav entries (Analysis tab was REMOVED
  2026-06-20; Source integrity dissolved to Settings → Safety; Collect/Sources/Wikipedia
  moved into Settings; "World map" naming).
- §2's top-bar description vs the shipped chrome (omnibar, airplane icon-only button
  #14d, task-manager access #4, language switcher #15, power button).
- Spot-check the deep-dive sections' entry-path claims ("open X from tab Y") the same way.

**Steps:** verify → fix only what code contradicts → leave everything else untouched.
**Acceptance:** every tab/control named in §2–§3 exists under that name in
`src/static/index.html`; the 0.0.8 section is explicitly marked historical; no deep-link
anchors broken (grep the repo + `src/` for links into USER_MANUAL before renaming any
heading — the in-app help may reference anchors).

---

## T6 — QUICKSTART: retire the "Phases 2–5" framing (+ mirror to fr) — P2, size S

**Verified current state:** the *content* of `docs/QUICKSTART.md` §D is CURRENT
(Settings → AI installer, model download queue, clearnet-egress disclosure, honest
503s, quarantine pointer — all match shipped behaviour). What's stale is the
**vocabulary**: the section heading `## D. Analysis capabilities (Phases 2–5)` and the
inline `— Phase 2.` / `— Phase 3.` / `— Phase 4.` / `— Phase 5.` labels are internal
build-phase numbering from the early project, meaningless to a new reader.

**Steps:**
1. Retitle §D to `## D. Analysis capabilities` and replace the per-block phase labels
   with plain capability names (**Local LLM (Ollama)** · **Commodity prices + honest
   correlation** · **Monitoring** · **Image metadata verification** · **Signed evidence
   bundles**). Content otherwise untouched.
2. Spot-check §C's end-to-end loop endpoints still exist (grep the routes in `src/api/`)
   — same verify-don't-assume rule as T5.
3. **fr mirror:** `docs/i18n/fr/QUICKSTART.md` was hand-seeded and will now lag. Apply
   the same reframe to the fr file (AI-drafted, flagged for native review — the
   established translated-docs convention with the honest machine-drafted banner). If
   the fr file has drifted further from the English original than this one edit,
   do NOT attempt a full re-translation in this session — note the lag in the PR body
   instead (a full refresh is `scripts/translate_docs.py` territory, operator-gated).

**Acceptance:** no "Phase N" vocabulary remains in QUICKSTART (en); fr carries the same
§D structure or a noted lag; all §C/§D curl examples name real routes.

---

## T7 — PARKED.md: reconcile the v0.0.7-era backlog to today's tree — P3, size M

**Problem:** the root `PARKED.md` still presents its items as open, but the tree has
moved. Partially verified already (2026-07-17):

| Item | Verified status | Evidence |
|---|---|---|
| MAINT-03 `Mapped[]` ORM migration | **DONE** | `src/database/models.py`: 448 `Mapped[` uses, 0 legacy `= Column(` assignments |
| Core-only CI job | **DONE** | `.github/workflows/ci.yml:164` (`core-only:` job) |
| mypy blocking | **PARTIAL** | ratchet gate at baseline ≤127 (`ci.yml:~130`), not the parked "flip to blocking-zero" |
| MAINT-04 `print()` → logger | **STILL OPEN** | 68 live `print(` calls across `src/` (diagnostics.py, source_manager.py, models.py, forensics.py, duckduckgo.py, api/main.py, crypto/*, events/*, signals/near_dup.py, utils/cache.py…) |
| PERF-02 FTS large-match materialization | **LIKELY DONE** — verify | the S2.5 FTS over-fetch bound (id-only resolve → load the page only, ledger 2026-07-12) is exactly this fix; confirm `fts.py:search_ids` + `main.py:_query_articles` |
| SSRF TOCTOU (TEST-03 residual) | **STILL OPEN, tracked** | re-confirmed by the 2026-06 audits + external audit; known/accepted |
| The rest (view_article refactor, build_families split, MinHash numpy, narrow excepts, Postgres parity, TEST-04/05) | **verify in-session** | grep anchors are in the file itself |

**Steps:**
1. Verify every row above plus the unverified tail (each item names its own anchor).
2. Annotate each item **in place** with a status line — `✅ done (evidence/pointer)` ·
   `🔶 partial (what remains)` · `⬜ open` — non-lossy, the record stays.
3. Add a header line: *"Reconciled 2026-07-17 against `<sha>`; the live forward board is
   [`docs/ROADMAP.md`](docs/ROADMAP.md) — still-open items below are candidates for its
   §4 backlog, not a second board."* Mirror any still-open item that is genuinely
   roadmap-worthy into ROADMAP §4 **only if it isn't already there** (check first —
   several likely are).
4. Do NOT archive the file this session (it's referenced from the index per T1, and the
   root location is part of its discoverability); if the maintainer prefers archiving,
   that's a one-line follow-up.

**Acceptance:** every PARKED item carries an evidence-backed status; no still-open item
exists ONLY in PARKED.md if it belongs on the roadmap; nothing deleted.

---

## T8 — `docs/design/` archival sweep (deep-dive follow-up, maintainer-approved 2026-07-17) — P2, size M

**Source:** the 2026-07-17 four-reader deep dive over all 23 design docs (verdicts anchored in
the tree). The folder is due its next archival pass (the 2026-07-13 cleanup precedent, 26→18).
**Binding rule:** the deep-dive verdicts were agent-produced — **hand-re-verify each doc's
"no unique pending items" claim against its named anchors before moving it** (the 06-audit
false-positive lesson). All moves are non-lossy `git mv` with inbound links retargeted and the
archive README maps updated. Coordinate with T1 (the index) — do T8 after T1 or update both.

**T8.0 — lift the unique carry-overs to a live board FIRST (blocking):**
1. **Fix-session Slice 2 — first-launch data-location chooser** (maintainer-asked 2026-07-14):
   add a `docs/ROADMAP.md` §4 row pointing at the spec in `FIX_SESSION_PROMPT_2026-07-14.md`.
2. **Fix-session Slice 4a — reversible non-article QUARANTINE action** (only the count-only
   scan shipped): same treatment, ROADMAP §4 row + spec pointer.
3. **UNIFIED_IMPORT_EXPORT's browser-gated cleanup line** (delete the orphaned volume/folder JS
   handlers + the capped single-file-create backend endpoint after a click-through): move onto
   the browser-verify/AppVM burn-down list (ROADMAP §4 or the runbook's first-VM-session queue).

**T8.1 — reconcile `FIX_SESSION_2026-07-14_STATE.md` drift (before any archival decision):**
mark Slice 3 (laws as first-class Articles) **DONE** with evidence — `src/law/corpus.py` exists,
`LawDocument.latest_text`/`LawRevision.full_text` are in `models.py` (independently corroborated:
the #691 field bug was a `law_revisions` UNIQUE collision *inside* `index_article`, only possible
with law ingestion live) — and fix its reference to the non-existent base doc
`FIX_SESSION_2026-07-14.md` (the PROMPT is the base).

**T8.2 — the moves (after T8.0 + T8.1 + per-doc re-verify):**
| Doc | Destination | Condition |
|---|---|---|
| `DB_RELIABILITY_01_GAP_ANALYSIS.md` | `docs/archive/design/` (new subfolder + README) | executed; the defective restore path it catalogs was removed outright |
| `DB_RELIABILITY_02_DESIGN.md` | `docs/archive/design/` | executed (merge engine, SQLCipher factory, torture suite all verified) |
| `COLLECTOR_WRITER_BATCHING.md` | `docs/archive/design/` | executed (`index_article(commit=)`, `OO_COLLECT_COMMIT_BATCH`, tests) |
| `KEYWORD_BASELINE_AND_MANAGEMENT.md` | `docs/archive/design/` | executed (all 4 slices in tree); its one residual overlaps keyword-engine P6.2 |
| `OPTIMIZATION_PROGRAM_ACTION_PLAN_2026-07-13.md` | `docs/archive/session-briefs/` | spent bridge; operator tails duplicated in the PLANNING doc |
| `AUTONOMOUS_SESSION_BRIEF_2026-07-14_OPTIMIZATION_TAIL.md` | `docs/archive/session-briefs/` | all 13 slices verified shipped |
| `UNIFIED_IMPORT_EXPORT.md` | `docs/archive/design/` | ONLY after T8.0 item 3 |
| `FIX_SESSION_PROMPT_2026-07-14.md` + `_STATE.md` | **stay in `docs/design/`** | PARTIALLY-SPENT — they hold the Slice-2/4a specs until those build (the "live briefs stay until their sessions complete" convention); T8.0 rows make the pending work board-visible |

**Explicitly NOT archived (live designs-of-record):** V1_PATHWAY · PLANNING_2026-07-12 ·
ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS · RECURSIVE_IMPROVEMENT_RUNBOOK · DATA_ARCHITECTURE_SKELETON ·
STORAGE_5TB_PLAN · DB10_RETENTION_VACUUM_MEMO · SOURCE_DIVERSIFICATION_BRIEF ·
SOURCE_METADATA_ENRICHMENT_STRATEGY · KEYWORD_ENGINE_OPTIMIZATION_STRATEGY (sole spec for
P5.2/P6 + the P2.4 guardrail) · PERSISTED_DUCKDB_HTTPFS + SCALING_DERIVED_LAYER_1000X (alive
until the httpfs binaries land) · this plan.

**Acceptance:** every moved doc re-verified spent; no unique pending item exists only in an
archived file; `docs/README.md` + archive READMEs consistent; all inbound links resolve.

---

## T9 — FUTURE_DEVELOPMENTS.md reality-check pass — P2, size M-L

**Problem (deep-dive verified):** the doc's own preamble discipline ("shipped material is
REMOVED, never carried as stale status notes") broke down for the ≥2026-06-15 cohort — of 19
sections spot-checked, 9 are STALE (marked designed-only while the code ships), 4 partially
stale. Worst offenders, each verified by file existence: clickable in-article keywords
(`reader.js` `?tab=keywords`), poll analysis (`poll_transparency.py`), manipulation/scenario
cards (~7 of 9 producers exist), Home "Latest" (`analytics/latest.py` + `/api/insights/latest`),
content-provenance (`catalog/provenance.py`), and the 2026-07-12 planning section
(`conjunction.py`/`skeleton.py`/`tor_throughput.py` all live despite its "gated" banner).

**Steps (re-verify each claim by grep before marking — never on the deep-dive's word alone):**
1. **Re-status the ≥2026-06-15 cohort:** per section, apply the doc's own rule — remove/condense
   shipped material to a one-line pointer (shipped.csv / the module path), keep the design
   rationale + open questions for the unbuilt remainder. Where a section mixes shipped and
   unbuilt, use the §43 "Statistical-data ingestion" inline **BUILD STATUS** block as the model.
2. **Split the four embedded historical ledgers to `docs/archive/`** (non-lossy): §3 FIELD-TEST
   REMARKS 2026-06-24 · §4 CONSOLIDATED TO-DO 2026-06-24 · §5 the 0.0.9 sequencing · §47 field
   diagnostics 2026-06-27. Before moving, verify their unresolved items are tracked in the
   CLAUDE.md queue or ROADMAP (the doc itself admits §4 duplicates the authoritative ledger).
3. **De-duplicate conservatively:** the two Wikipedia sections (§1 2026-07-10 vs §22 2026-06-12)
   and the two statistics sections (§35 vs §43). Default = banner + cross-reference (mark the
   older as the historical precursor of the newer); a true merge only where content is verbatim
   duplicative — **never drop a recorded ruling** (§22 carries the load-bearing superseding
   auto-track ruling; it must survive verbatim wherever it lands).
4. **Fix the internal contradiction:** §41's "designed-only" header vs its own TO-DO marking
   copypasta + outrage DONE.
5. **Fix the broken relative link:** bare `SCALE_ROADMAP.md` → `product/SCALE_ROADMAP.md`.

**Acceptance:** no section dated ≥2026-06-15 claims design-only for a thing that exists in
`src/` (spot-check re-run comes back 0 STALE); every ruling recorded in a moved/merged section
survives verbatim; links resolve; the preamble's discipline statement is true again.

---

## T10 — two one-line drift fixes in the storage docs — P3, size XS

1. **`STORAGE_5TB_PLAN.md` §3 (Phase A):** the claim "`journal_size_limit` is set NOWHERE
   (grep-verified 2026-07-12)" is stale — it is now set at `src/database/session.py:137`, whose
   comment cites this very plan. Tick that Phase-A delta as shipped (the plan's own staleness
   guard anticipates exactly this update).
2. **`5TB_ARCHITECTURE_REVIEW.md`:** add a short header status note — Recs 1/4/8 shipped
   (adaptive volume sizing in `stream_backup.py`, D2/D3 columnar, the cross-time-recall
   invariant test), Rec 3 (`auto_vacuum`) still pending the DB-10 ruling — rather than rewriting
   the body (it is a dated review; the note keeps it honest without editing history).

---

## Sequencing, sizing, closeout

| Order | Task | Priority | Size | Commit |
|---|---|---|---|---|
| 1 | T1 index + T2 guard test | P1 | S+S | 1 |
| 2 | T3 audit-trail backfill | P1 | S | 2 |
| 3 | T4 testing-doc staleness | P2 | XS | 3 |
| 4 | T5 USER_MANUAL historical + nav verify | P2 | M | 4 |
| 5 | T6 QUICKSTART framing (+ fr) | P2 | S | 5 |
| 6 | T7 PARKED reconciliation | P3 | M | 6 |
| 7 | T10 storage-doc one-liners | P3 | XS | 7 |
| 8 | T8 design-folder archival sweep (T8.0 lift → T8.1 reconcile → T8.2 moves) | P2 | M | 8 |
| 9 | T9 FUTURE_DEVELOPMENTS reality-check | P2 | M-L | 9 |
| 10 | Ledger closeout (shipped.csv rows + Open-queue tick) | — | XS | folded per-commit |

Estimated one to two focused CLI sessions (T1–T7 + T10 fit one; T8–T9 may be a second).
Highest value first: T1–T3 fix *discoverability and record integrity* (what a new reader or
auditor hits); T4–T6 fix *stale claims in live guides*; T7/T10 are *record hygiene*; T8–T9
(added 2026-07-17 after the design-folder + FUTURE_DEVELOPMENTS deep dive, maintainer-approved)
restore the *forward-planning layer's* accuracy. T8/T9 touch shared ledger surfaces
(ROADMAP, archive READMEs) — additive merges only, never revert a sibling session's lines.

**PR body must list:** per-task before/after, the T2 test red→green proof, any
found-already-fixed items (staleness-guard results), and anything deferred with reason
(e.g. the fr full-refresh, a T4 `CONSENT_DOC_VERSION` flag, T5 anchor-rename risks).
