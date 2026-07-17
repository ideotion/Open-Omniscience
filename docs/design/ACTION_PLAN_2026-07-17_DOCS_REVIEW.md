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

## Sequencing, sizing, closeout

| Order | Task | Priority | Size | Commit |
|---|---|---|---|---|
| 1 | T1 index + T2 guard test | P1 | S+S | 1 |
| 2 | T3 audit-trail backfill | P1 | S | 2 |
| 3 | T4 testing-doc staleness | P2 | XS | 3 |
| 4 | T5 USER_MANUAL historical + nav verify | P2 | M | 4 |
| 5 | T6 QUICKSTART framing (+ fr) | P2 | S | 5 |
| 6 | T7 PARKED reconciliation | P3 | M | 6 |
| 7 | Ledger closeout (shipped.csv rows + Open-queue tick) | — | XS | 7 (or folded per-commit) |

Estimated one focused CLI session. Highest value first: T1–T3 fix *discoverability and
record integrity* (what a new reader or auditor hits); T4–T6 fix *stale claims in live
guides*; T7 is *record hygiene*.

**PR body must list:** per-task before/after, the T2 test red→green proof, any
found-already-fixed items (staleness-guard results), and anything deferred with reason
(e.g. the fr full-refresh, a T4 `CONSENT_DOC_VERSION` flag, T5 anchor-rename risks).
