# AUTONOMOUS SESSION BRIEF — REMEDIATE PR #740 + PR #744 (2026-07-22)

**Status:** brief of record, execution PENDING.
**Scope:** execute the still-open, buildable-now work left by two merged PRs —
**#740** (`docs: design-folder audit + remediation plan`, delivering
`docs/design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`, an 11-phase
backend/docs remediation board) and **#744** (`test: systematic GUI test —
100-agent Chromium pass`, delivering `docs/audit/GUI_TEST_REPORT_2026-07-22.md`
+ `docs/audit/gui-test-2026-07-22/findings.csv`, 72 merged UI findings: 5 P0,
24 P1, 38 P2, 5 OPT).
**Merge order (verified, clean linear chain, nothing interleaved):** #740
(`1caa848`) → #742 (`8a21300`, unrelated bandit fix) → #744 (`3be0622`, current
`origin/main` tip as of this brief).
**Why these two together:** their scopes are **almost entirely file-disjoint**
(#740 = database/backend/docs; #744 = frontend HTML/CSS/JS) — the ideal shape
for a subagent-parallelized session, and stated explicitly in §5's orchestration
design.

---

## 0. Ground truth hierarchy (unchanged from both source PRs)

`CLAUDE.md` is still the single binding ledger. Neither source plan, nor this
brief, overrides it. **Re-verify staleness against a freshly-fetched
`origin/main` before starting** — this repo fast-merges (the two source PRs
merged hours apart on the same day) and every citation below was re-derived
from the live tree during this brief's authoring, not copied from either PR's
own text. Where this brief's re-verification found a PR's own claim imprecise
or incomplete, that correction is called out explicitly below — **trust this
brief's citations over the source PRs' prose** for exact line numbers and the
Phase-1 safety requirement in particular (§1.4).

---

## 1. Mission

One autonomous session, maximizing subagent parallelism, that:

1. **Builds the buildable-now items** from PR #740's remediation plan (Phases
   1–4, 6, 9 — backend, data, and documentation work), respecting every
   maintainer-ruling-gate, operator-gate, and browser-gate the plan itself
   marks (§2 below is the exhaustive do-NOT-touch list).
2. **Fixes the P0 and P1 findings** from PR #744's GUI test report (frontend
   HTML/CSS/JS + the two backend-adjacent P0s), each as an isolated,
   individually-verified change that closes the exact reported defect.
3. Ships each logically-independent piece of work as its **own small PR**
   (never one giant PR spanning both source reports), following the house
   "one PR per phase/finding, draft onto main" convention both source PRs
   already establish.

**Explicitly NOT in scope for this session** (see §2): anything tagged
maintainer-ruling-gated, operator-gated, or browser-gated in PR #740's plan;
PR #744's P2/OPT tier (left as a documented backlog, not silently dropped —
note their status in the closeout); anything requiring a real Ollama rig, a
networked machine, or a browser click-through beyond what this session's own
environment can provide (Chromium + a scratch server, exactly as PR #744's own
session used).

---

## 2. Binding scope fence — do NOT touch these

Copied and re-verified from PR #740's own tagging (its own text is accurate
here; no drift found):

- **Maintainer-ruling-gated (ask, don't build):** PR #740 §11.1 (V1-2 through
  V1-9 — API-key policy, license policy, PubMed strategy, win/mac-at-1.0, KPI
  bars, elections-required-for-1.0, edition-count bar). PR #740 §1.4's
  page_size ratification question (**this brief resolves it explicitly in
  §4.1.5 below — read that before touching Phase 1**).
- **Operator-gated (needs a human's machine/time, not this session's):** §5.1
  (LLM batch-enrichment, needs a local Ollama rig), §5.2 (source-diversification
  live-network pass, needs a networked CLI session), §8.1 (LLM triage/tag real
  runs, same Ollama rig), §11.3 (the `ui_walk` AppVM runner — needs the
  maintainer's actual AppVM), §11.4 (grading a real IR gold set — needs the
  maintainer's 15 minutes), §3.4 (broadening law adapters past the first proven
  one — sequenced after 3.2/3.3 prove the pattern, not concurrent with them).
- **Browser-gated by explicit design (not conservative-flaggable):** §10.1
  (the Observatory `ooSky` frontend) — do not build this "conservative and
  flagged" like ordinary frontend work; its own design doc says it needs a real
  click-through session, which this one is not (Chromium-in-sandbox, per PR
  #744's own honest stamp, is NOT the human UX pass).
- **Blocked on a prerequisite:** §4.3 (static-embedding recall layer — gated on
  §11.4's gold set existing), §4.4 (entity→QID linking — needs a license check
  + a networked machine), §7.1 (skeleton fingerprint persistence — the source
  doc explicitly sequences this AFTER Phase 4/8's keyword cleanup; build it
  last if time remains, or leave it — its own docstring calls it a legitimate
  "skip without guilt" stretch), §11.2 (the five new verticals — need an
  explicit maintainer go per V1-8, zero code exists, out of scope entirely).
- **From PR #744:** the P2/OPT tier (38 + 5 = 43 findings) — real, but lower
  priority; this session's fix budget goes to P0+P1 first (§4.2). If time
  remains after every P0/P1 fix + PR #740's buildable-now phases are done, pick
  UP TO 5 of the highest-value P2s (§4.2.4 has a recommended shortlist) —
  never silently claim the whole P2/OPT tier was addressed.

---

## 3. Verified current-state snapshot (re-derived this brief, not trusted from either PR)

Every citation below was read directly from `origin/main` at the time this
brief was authored (commit `3be0622` and its ancestors). Re-confirm at your
own session's start — a "still open" here could have shifted if more work
landed on `main` between now and then.

- `src/database/connect.py`: **confirmed** no `auto_vacuum` or `page_size`/
  `cipher_page_size` PRAGMA is set anywhere in the fresh-file creation path
  today. PR #740's own citation ("`connect.py`'s fresh-file branch ~line 86")
  is **imprecise** — line 86 is inside `is_encrypted_file()` (a helper that
  returns `None` for a missing/empty file), not the actual fresh-file
  PRAGMA-setting site. The real target is `connect()`'s **"Fresh file" section**
  (the comment at line 169, `# Fresh file. Decide its at-rest fate
  EXPLICITLY...`), which has **three** sub-branches that each open a brand-new
  connection and return it immediately: an explicit-key encrypted path (open at
  line 177), a plaintext path (open at line 181), and an ambient-passphrase
  encrypted path (open at line 187). **All three need the new PRAGMA(s)
  applied** — see §4.1 for the exact, path-aware fix.
- `src/database/session.py:63`: **confirmed** the normal app-boot reopen path
  calls `connect(db_path, check_same_thread=False, timeout=30)` with **no
  `cipher_page_size` argument at all**. This is the safety gap detailed in
  §4.1.2 — read it before touching Phase 1.
- `src/api/main.py` (the reader's "Related in your corpus" query) and
  `src/analytics/store.py` (`index_article`): **confirmed** `grep -rln
  "article_keyword_association" src/ --include="*.py"` returns exactly three
  files — `src/database/models.py` (the table's own definition + a `relationship`
  declaration), `src/api/main.py` (the reader's broken query), and
  `src/backup/merge.py` (carries legacy rows through a restore, never inserts
  new ones). **Zero writers in the live ingest path** — PR #744's P0 finding is
  accurate and unchanged.
- `src/static/unlock.html`: **confirmed** `function go(btn, fn)` is still at
  line 383, unchanged; the hide-before-request / never-unhide-on-error bug PR
  #744 found is still present exactly as described.
- `src/static/app.js`: **confirmed** `let _anTabs = []` (line 15293),
  `function _anRestoreTabs()` (line 15397), and the `_hydrateCardCorpus()` IIFE
  (line 17461) are all at the same line numbers PR #744 cited — nothing shifted.
- **DB-10 ruling status, quoted verbatim from `CLAUDE.md`** (grep `"DB-10 §1a
  RULED"` and `"§1b EVIDENCE PAIR"`):
  - **§1a (`auto_vacuum=INCREMENTAL`) is FORMALLY RULED YES** — the maintainer's
    verbatim words: *"I agree with your proposal to change the auto_vacuum to
    incremental."* No further permission is needed to build this.
  - **§1b (`page_size=16384`) is NOT yet formally ratified.** `CLAUDE.md`'s own
    words: *"recommendation FIRM, awaiting the maintainer's ratification."* The
    evidence is exceptionally strong (two real live-corpus A/B runs, 16384 won
    every measured dimension at both 3 GB and 22 GB scale) but this is
    explicitly a recommendation, not yet a ruling. **§4.1.5 resolves exactly
    how this session should handle that gap** — read it before starting Phase 1.

---

## 4. Workstream A — PR #740 backend/docs remediation

### 4.1 Phase 1 — DB-10 create-time seam (build this FIRST, sequentially, with extra care — it changes how every future corpus is created)

This is the single highest-value item either PR identifies, and the one this
brief's own re-verification found a real, previously-unstated safety gap in.
Do not rush it; do not parallelize it with anything else touching
`src/database/`.

**4.1.1 [BUILDABLE NOW, ruled] Wire `auto_vacuum=INCREMENTAL` on fresh-file
creation.** In `src/database/connect.py`'s `connect()` function, in **all
three** "Fresh file" sub-branches (the connections opened at lines ~177, ~181,
~187), issue `PRAGMA auto_vacuum = 2` (2 = `INCREMENTAL`) on the connection
**immediately after opening it, before any table is created** — SQLite
requires `auto_vacuum` to be set before the schema exists. Read
`src/monitoring/pagesize_bench.py`'s `rebuild_at_pragmas()` function
(lines 80–135) FIRST — it already proves the exact working ordering for both
the plaintext (`PRAGMA auto_vacuum = N` directly) and encrypted
(`PRAGMA <alias>.auto_vacuum = N` on an ATTACHed target) cases; don't
rediscover it. Auto_vacuum has **no reopen hazard** (unlike page_size below) —
SQLite records the mode in the file's own header and reads it back
transparently on every subsequent open, encrypted or not, with no extra
plumbing required. This half is safe to ship on its own even if §1b (below)
is deferred.

**4.1.2 [DECISION REQUIRED BEFORE BUILDING] `page_size=16384` carries a real
reopen-safety requirement PR #740's plan does not mention.** Read
`src/monitoring/pagesize_bench.py` lines 118–135 closely: for an **encrypted**
target it sets `PRAGMA <alias>.cipher_page_size = N` (the SQLCipher-specific
pragma), **not** the plain SQLite `page_size` pragma — and `connect()`'s own
docstring (around its `cipher_page_size` parameter) states the reason
explicitly: *"SQLCipher decodes a database ONLY at the page size it was
created with, and that size is NOT discoverable from the file."* This project
was already burned by exactly this failure mode once (see `CLAUDE.md`'s
Session-rituals Lessons entry titled "SQLCIPHER CANNOT DISCOVER
`cipher_page_size` FROM THE FILE" — a real field incident where a correct
passphrase read as wrong because the opener never declared the non-default
page size). **`src/database/session.py:63` — the app's NORMAL boot reopen
path — passes no `cipher_page_size` at all.** If Phase 1 creates new encrypted
stores at `cipher_page_size=16384` without ALSO teaching the normal reopen
path to redeclare that size on every subsequent boot, the very next restart
after a fresh install would misread the user's correct passphrase as wrong —
a severe, silently-introduced regression, and the exact bug class this
project has a named lesson about. **This must be designed and tested as part
of Phase 1, not treated as a follow-up.** Two candidate designs (pick one,
justify the choice in the PR description, and prove it with the acceptance
test in §4.1.6 — do not ship without that proof):
  - **(a) A persisted marker.** Record the page size a store was created at in
    a small sidecar (e.g. a field in `session_state.json`, or a dedicated
    `<data_dir>/db_pagesize.json`) at creation time; have the normal boot path
    (`session.py`'s engine setup, wherever it calls `connect()`) read that
    marker and pass `cipher_page_size=<recorded value>` on every open of an
    encrypted store. Legacy stores with no marker default to `None` (today's
    behavior — the SQLite/SQLCipher compiled-in default, effectively 4096),
    preserving byte-identical behavior for every existing corpus.
  - **(b) A verify-then-fallback probe.** On an encrypted open with no known
    size, try the new default (16384) first; if `_verify_readable()` raises,
    retry once at the legacy default before giving up. Simpler (no new
    on-disk state), but pays a wasted connect+HMAC-check on every legacy-store
    boot — measure whether that cost is acceptable before choosing this over
    (a).
  Either way: **the fix is incomplete without solving this**, regardless of
  whether §1b's specific *value* (16384) is ratified now or deferred (§4.1.5).

**4.1.3 [BUILDABLE NOW] Wire `incremental_vacuum(N)` into the idle-maintenance
pass.** `src/scheduler/maintenance.py`'s `run_idle_maintenance` — follow the
same idle-gated, bounded, throttled, `run_now`-honest pattern it already uses
for its other housekeeping steps. A documented no-op on a pre-seam corpus
(where `auto_vacuum` is still `FULL`/`NONE`) is correct and expected — assert
that explicitly in a test, don't just hope for it.

**4.1.4 [BUILDABLE NOW] Add a size gate to the Settings "Full VACUUM"
button.** `vacuumNow()` in `src/static/app.js` runs unconditionally today at
any corpus size — a full VACUUM on a multi-GB corpus is exactly the kind of
unbounded synchronous operation this project's own "`async def` freezes the
whole server" lesson warns against. Gate it with a size threshold + an honest
time estimate derived from `pagesize_bench`'s own measured
rebuild-seconds-per-GB (≈10–17 s/GB, cited in `CLAUDE.md`'s §1b evidence
entry), or a plain confirm-with-caveat if a cheap estimate isn't available.

**4.1.5 (resolving PR #740's own §1.4 ask) — how THIS session should handle
the not-yet-ratified page_size value:** PR #740's plan explicitly says *"get
an explicit 'yes, wire it' from the maintainer... or at minimum flag the PR
loudly and let the maintainer's merge stand as the ratification — but say so
explicitly in the PR description so it's an intentional reading, not an
assumption slipped past review."* Since this is meant to be an entirely
autonomous session (no mid-session human available to ask), take the
SECOND path, but make it maximally conservative and legible:
  - Ship **§1.1 (auto_vacuum) as its own PR**, titled and described as the
    ruled, uncontroversial half.
  - Ship **§1.2 (page_size=16384 + its mandatory reopen-safety mechanism from
    §4.1.2) as a SEPARATE PR**, with a title and an opening paragraph that
    states, verbatim and prominently: *"This wires the FIRM-recommended but
    not-yet-explicitly-ratified page_size=16384 default (CLAUDE.md §1b,
    evidence delivered 2026-07-19/20). Per that entry's own stated path,
    merging this PR is being treated as the ratification, exactly as
    precedent for §1a. If you want to hold or discuss this first, close this
    PR without merging — nothing else in this session depends on it."* This
    keeps the maintainer's actual decision-making power fully intact (a closed
    PR costs nothing) while not blocking indefinitely on a synchronous
    question this session cannot ask.

**4.1.6 [DoD — do not skip]** `tests/test_repo_invariants.py` gains an
assertion that a freshly created (non-fixture) DB reports `auto_vacuum=2` via
`PRAGMA` read-back (remember the `int()`-coercion lesson — some SQLCipher
builds return PRAGMA values as TEXT, e.g. `"4096"` not `4096`). If §1.2 ships,
add the **create → close connection → reopen via the NORMAL boot path (not a
special test-only helper) → confirm the passphrase still opens it AND
`page_size`/`cipher_page_size` reads back 16384** round-trip as its own
dedicated test — this is the proof that closes the safety gap in §4.1.2; a
green suite without this specific test does not mean the gap is closed. Full
suite green; run the exact CI commands from §6 before pushing, not just a
local ad hoc check.

### 4.2 Phase 2 — Documentation hygiene (cheap, overdue, zero code risk)

All items are `[BUILDABLE-NOW]`, verified still open (nothing in §0's
snapshot suggests any of these shipped since 2026-07-22):

- **2.1** `docs/README.md` index reconciliation — it's missing `docs/legal/`,
  `GOVERNANCE.md`, `CODE_OF_CONDUCT.md`, `QUARANTINE_ARCHIVE.md`,
  `docs/audit/` (note: as of this session there are now potentially THREE
  entries under `docs/audit/` — the two from PR #740's own audit era plus
  this brief's eventual `docs/audit/GUI_TEST_REPORT_2026-07-22.md` from #744 —
  make sure the reconciliation picks up all of them), `docs/process/`,
  `docs/maintenance/`, `docs/testing/`, `docs/research/`, `docs/i18n/`. Walk
  `find docs -maxdepth 2 -type f` fresh and reconcile against the live tree,
  not against the 2026-07-22 snapshot in the plan.
- **2.2** A repo-invariant test (`test_docs_index_covers_live_docs`) enumerating
  every top-level doc folder/first-launch-gated doc and asserting
  `docs/README.md` mentions it — this is what stops the index drifting stale
  again; build it in the SAME PR as 2.1, not a follow-up.
- **2.3** `AUDIT_TRAIL.md` backfill — append the missing 2026-07-13
  cumulative-integrity audit, the 2026-07-15 external audit, and (now) this
  session's own PR-740/744-remediation work once it lands, plus anything else
  since. Append-only per the file's own convention.
- **2.4** Banner the historical USER_MANUAL sections (`### Recent additions
  (0.0.8 live-test cycle...)` near line 164, and the embedded `# What shipped
  in 0.0.8` section near line 2280) with a short "this is a historical
  snapshot; see CLAUDE.md for the live ledger" note above each — don't rewrite
  the content, just label it.
- **2.5** Retire the QUICKSTART "## D. Analysis capabilities (Phases 2–5)"
  heading (`docs/QUICKSTART.md:187`) to just "## D. Analysis capabilities" —
  the content underneath was independently verified current by the 2026-07-17
  audit; only the stale "Phases" vocabulary needs to go. Mirror the exact same
  heading change to `docs/i18n/fr/QUICKSTART.md`.
- **2.6** Verify (don't blindly "fix") whether
  `ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`'s `SCALE_ROADMAP.md` link is
  actually still bare/unqualified before touching it.
- **DoD:** `python scripts/i18n_report.py --min 100` still green (docs-only
  changes shouldn't touch it, but run it to prove that); 2.2's new invariant
  test passes; a human-equivalent skim (`diff <(find docs -maxdepth 2 -type f
  | sort) <(grep -o 'docs/[A-Za-z0-9_/.-]*' docs/README.md | sort -u)` or
  similar) shows no orphaned top-level doc.

### 4.3 Phase 9 — Field-diagnostics fixes (#728), small and self-contained

- **9.1** `rising_now`'s `Card(...)` call in `src/briefing/producers.py`
  (around line 230 per the plan — **re-verify the exact current line yourself**,
  since this file may have shifted since 2026-07-22 unlike the ones this brief
  hand-checked) is still missing `article_ids=` — the exact-set-seeding
  convention every other Home Lead card producer already follows (the
  pattern this bug class was fixed on for other producers back on
  2026-06-16). Small, mechanical, matches an established precedent exactly.
- **9.2** Profile the slow `/api/insights/map-coverage` endpoint
  (`src/api/insights.py`, around line 1161 per the plan — **re-verify the
  current line**) for real (`EXPLAIN QUERY PLAN`, or the app's own slow-query
  diagnostic) before assuming a fix; per the project's own SQLite
  scan-classification lesson (a `SCAN <table> USING [COVERING] INDEX` is
  healthy, only a *bare* `SCAN <table>` is the real smell), it may be a missing
  index rather than a structural rewrite. Build whichever the profile actually
  shows is needed.
- **9.3** [SKIP — needs the raw diagnostics JSON already delivered in PR #728,
  no code prerequisite, low urgency]. Leave this one for a future session with
  that JSON in hand; don't guess at a fix without the data.

### 4.4 Phase 3 — Law vertical remainder (S3, S6-one-adapter, S7-one-feed)

- **3.1** Build `POST /api/law/documents` (or the equivalent the codebase's
  naming convention favors — check `src/api/` for the existing law router's
  style before naming it) accepting a URL + jurisdiction + title, running it
  through the SAME guarded-fetch → `LawDocument`/`LawRevision` → `index_article`
  pipeline `src/law/corpus.py` already wires for tracked documents. This closes
  the gap where the law catalog can only grow via the maintainer hand-editing
  YAML.
- **3.2** Build exactly ONE structured adapter — legislation.gov.uk (UK, clean
  XML), per the plan's own sequencing rationale (easiest real win). **A real
  fetch against the live endpoint is mandatory before this ships** — the
  project's standing rule is "never fabricate an endpoint" (a prior session's
  GDELT-endpoint mistake is the cited cautionary precedent); verify the XML
  shape empirically, don't assume it from documentation. Do NOT attempt
  gesetze-im-internet or EUR-Lex ELI in the same slice — each needs its own
  verify-the-real-endpoint pass.
- **3.3** Ingest ONE gazette as an RSS source — the plan names
  `legal.gov.vc` (St Vincent) as having a working Joomla RSS feed identified in
  the 2026-07-17 acquisition batch. **Verify it's still live before wiring
  it** (a feed can go dark between when it was found and when this session
  runs). Route it through the existing RSS pipeline with `source_type=legal`.
- **DoD:** each new adapter/feed carries its OWN negative-space-tested parser
  (per the project's S5.1/S5.2 lesson: test the SHOULD-BE-EMPTY / malformed
  cases, not just the happy path) and was fetched for real by this session,
  not assumed.

### 4.5 Phase 4.1/4.2 — Keyword-baseline remainder

- **4.1** Migrate `_EXTRA_STOPWORD_TEXT` (`src/analytics/extract.py:300` —
  **re-verify this line number fresh**, it's a large file that may have moved)
  from an in-Python string blob into `configs/keyword_baseline/<lang>.yml`-style
  data files, matching the pattern already established for the positive
  baseline tags. **Byte-identical behavior is the acceptance bar** — this is a
  representation change only, pin it with a test that the stopword SET before
  and after the migration is identical.
- **4.2** Build an in-app Settings panel (extend the existing `#set-keywords`
  Keywords-explorer subtab) that lists the offline `analyze_keyword_log.py`
  script's and the in-app `generic_terms` diagnostic's PROPOSED stopword/ring/
  mistag candidates and lets the maintainer accept/reject per item. **NEVER
  auto-apply** — this is the standing "propose, human judges" rule for this
  exact surface, load-bearing. Frontend-facing, so browser-verify-gated per
  the standing Q6a convention (conservative + flagged, `node --check`-clean,
  no click-through claimed — same posture PR #744's own report used for its
  frontend findings' fix specs).

### 4.6 Phase 6 — OSM boundary/gazetteer offline-preprocessing bridge

Build the pure preprocessing pipeline that turns a downloaded OSM extract
(only the download manager exists today — `src/geo/osm_downloads.py`/
`osm_regions.py`) into the choropleth-ready artifact the world map needs. This
is testable against a SMALL downloaded region — do not attempt to process the
full planet. Fixture-test the pure function; document the offline artifact
format. Wiring the artifact into the existing world-map choropleth is
explicitly a follow-up slice, not required for this phase's own DoD.

---

## 5. Workstream B — PR #744 GUI-fix remediation

**Full source of truth:** `docs/audit/gui-test-2026-07-22/findings.csv` (72
rows) and `docs/audit/GUI_TEST_REPORT_2026-07-22.md`. This brief gives fix
specs for the 5 P0s (mandatory) and groups the 24 P1s into buildable clusters;
consult the CSV directly for any finding's full repro/expected/actual text —
do not re-derive it from memory.

**Fix discipline for every item below:** (1) reproduce the ORIGINAL bug first,
exactly per the CSV's `repro` column, on a scratch server (same recipe PR #744
itself used — `python3.13 -m venv`, `pip install -e ".[analysis]"`, a scratch
`OO_DATA_DIR`, `OO_DB_PLAINTEXT=1`, then boot); (2) apply the isolated fix; (3)
re-run the EXACT SAME repro and confirm the reported `actual` behavior no
longer occurs; (4) add a regression test where the codebase's existing test
shape makes one straightforward (an invariant test, a Playwright-free DOM/unit
test, or a backend test as appropriate — do not force a browser test where a
cheaper one suffices, but do not skip testing entirely either); (5) ship as
its own PR, citing the finding id from `findings.csv` in the PR description.

### 5.1 P0s — all five, mandatory

1. **`reader-dead-legacy-table-related`** — In `src/api/main.py`, the
   `related_html` block (built from `article_keyword_association`, a table
   with zero writers) must instead query `KeywordMention` — the same table
   every other keyword-driven surface in the app already uses as its source of
   truth (see `src/analytics/store.py`'s `index_article` for the write side).
   Rewrite the query: for the current article, find its mentioned keyword ids
   via `KeywordMention`, then find OTHER articles sharing the most of those
   keyword ids, ranked by shared-keyword count — the same shape the current
   (broken) query already expresses, just pointed at the live table. **Watch
   the codec column-order perf trap** (a documented project lesson: a query
   joining `KeywordMention`→`Article` for one small column can drag whole
   article bodies through the SQLCipher codec) — this reader endpoint is
   per-article and low-volume, so a straightforward join is likely fine, but
   check `EXPLAIN QUERY PLAN` before shipping. Also address the linked OPT
   finding `reader-dupbadge-n-plus-1-decrypt-risk` in the SAME change: bound
   or cache the candidate query so fixing the honesty bug doesn't re-expose an
   N+1-style full-body decrypt (up to 40 articles per reader page view) —
   an id/count-only query suffices for both the badge AND the "Related"
   list's shared-keyword-count column; only fetch full titles for the
   (small, capped) result set actually displayed.
2. **`net-coach-blocks-topbar-buttons`** (merges the related P1
   `netcoach-blocks-lang-switch` — same root cause, one fix) — the
   `#net-coach` coachmark's CSS/positioning must never occupy screen space
   that overlaps a clickable neighbor. Two viable approaches, pick based on
   what's least disruptive to the coachmark's own visual design: (a) give the
   coachmark's own interactive elements (its buttons) a higher stacking
   context via `pointer-events` scoping so everything EXCEPT its own buttons
   passes clicks through to whatever is beneath — risky if the coachmark's
   body itself needs to be clickable for dismissal; more likely correct is (b)
   reposition/resize the coachmark so its bounding box genuinely does not
   overlap `#net-toggle`, `#lang-switch`, `#tm-open`, or `#app-shutdown` at any
   supported viewport width — recompute its anchor via `getBoundingClientRect`
   of the SET of buttons it must avoid, not just the one it points at.
   Acceptance: `document.elementFromPoint()` at the exact center of all four
   buttons must resolve to the button itself, not the coach, while the coach
   is visible; a real Playwright `.click()` on each must succeed without
   timing out.
3. **`LC-VIEW-HIDDEN-ON-ERROR`** — In `src/static/unlock.html`'s `go(btn, fn)`
   (line 383), the `catch` block must re-show whichever view was active before
   `_startPrep()` hid it. The cleanest fix: have `_startPrep()` remember which
   view was visible (it already knows — it's the caller's context, since `go`
   is invoked from a specific button's click handler) and have the `catch`
   block un-hide that SAME view (removing the `hidden` class it added) instead
   of just hiding `view-preparing`. Acceptance: submit a too-short passphrase
   → `#view-create` must remain visible with `#msg2`'s error text actually
   rendered (not just present in the DOM but hidden); `document.body.innerText`
   must be non-empty and must contain the error message.
4. **`topbar-overflow-mobile-375-net-toggle-unreachable`** (this is the acute
   end of the broader P1 `topbar-overflow-mainstream-widths`, which reproduces
   the SAME overflow at 1024/768/601px too — fix both findings with ONE
   responsive strategy change, don't patch 375px in isolation) — the top bar
   needs a real narrow-viewport strategy: either an overflow/kebab menu
   collapsing the airplane/language/task-manager/shutdown cluster below a
   breakpoint, or a wrapping flex layout that never lets `documentElement.
   scrollWidth` exceed `clientWidth`. Acceptance: at each of 1400/1024/768/
   601/375px, `document.documentElement.scrollWidth` must not exceed
   `clientWidth` (a few px of rounding tolerance is fine), and all four
   controls must be reachable (in the DOM, visible, and clickable) via
   on-screen interaction alone — no undiscoverable horizontal scroll.
5. **`font-size-slider-missing-label`** — In `src/static/index.html`, wrap
   `<input type="range" id="dr-font" ...>` in the semantic `<label>` its
   sibling "Text size · <span id=dr-font-val>" text already visually
   describes, OR add `aria-labelledby` pointing at that span's id (simpler:
   wraps the existing markup with minimal disruption — check which pattern
   the codebase's OTHER labelled inputs on the same panel already use and
   match it, for consistency). Acceptance: axe-core's `label` violation on
   `#dr-font` must no longer fire; a screen-reader-equivalent accessible-name
   computation must return something containing "text size".

### 5.2 P1s — buildable clusters (24 total; group and fix together where one root cause covers several)

- **State/architecture cluster** (fix together — all touch
  `src/static/app.js`'s analysis-tab machinery):
  - `analysis-boot-race-destroys-tab-workspace` — in the boot IIFE sequence
    (`app.js` lines 17455–17497), `_hydrateCardCorpus()`'s `?analyze=`/
    `?corpus=` deep-link spawn (which calls `_anSpawn`→`_anActivate`→
    `_anSaveTabs()`, overwriting `localStorage['oo.an.tabs.v1']`) must not run
    BEFORE `_anRestoreTabs()` has had a chance to load the EXISTING persisted
    tabs. Fix: call `_anRestoreTabs()` FIRST (restoring whatever was already
    open), THEN run `_hydrateCardCorpus()`'s spawn logic so the deep-linked
    seed gets ADDED to the restored set rather than replacing it (dedup by
    `_anSpawn`'s existing `key` logic already handles "reuse if identical" —
    just don't let the order clobber the array before restore runs).
    Acceptance: open the omnibar in 3 successive new browser tabs with 3
    different queries; the 3rd tab's tab-strip must show all 3 as coexisting,
    named tabs (up to the existing 10-tab soft cap).
  - `dblclick-opens-duplicate-analysis-tabs` — debounce `openCardCorpusQuery`/
    `openAnalysisInNewTab`'s `window.open` call (e.g. a simple in-flight guard
    keyed on the exact URL, cleared after a short timeout or on window focus
    return) so a fast double-click cannot fire two `window.open` calls for the
    identical URL. Acceptance: a scripted double-click (≤50ms apart) must
    produce exactly one new tab/window.
  - `ins-watches-doubleclick-duplicate` — same debounce pattern applied to the
    "Add watch" button's click handler.
- **Settings-integrity cluster:**
  - `theme-select-lossy-overwrite` — `syncThemeSelect()` (app.js ~1548) and
    `saveSettings()` (app.js ~4959) must stop lossily bucketing all 17 named
    themes into a 3-way light/dark/system choice. Either: (a) extend the
    General panel's theme `<select>` to carry the FULL 18-way choice (removing
    the lossy bucketing entirely — likely the more honest fix, since it
    removes the redundant/conflicting control rather than patching around it),
    or (b) if the bucketed control is intentionally kept as a coarse shortcut,
    make `saveSettings()` a no-op on theme when the select's value hasn't
    changed FROM its own last-synced state (i.e., only write a theme change
    when the user actually touched that specific control, never as a
    side-effect of saving unrelated preferences). Prefer (a) — it's simpler
    and removes the two-controls-for-one-setting inconsistency the finding's
    CONSISTENCY-lens framing already flags. Acceptance: pick "Midnight" in
    Graphics → save unrelated preferences in General → Midnight must still be
    the active theme afterward.
- **Layout/freeze cluster:**
  - `imp-ghost-modal-after-back` — add a `popstate` listener that closes any
    currently-open `<dialog>` (query `document.querySelectorAll('dialog[open]')`
    and call `.close()` on each) when the browser's Back/Forward navigation
    fires. This is a SHARED native-`<dialog>` mechanism per the finding's own
    note ("likely applicable to any `<dialog>` in the app"), so one listener
    at the app's top level should fix `#ux-export`/`#ux-import` and every
    other dialog at once — verify that breadth explicitly, don't assume it.
    Acceptance: open the Export dialog → browser Back → the dialog must be
    closed (not just visually hidden) and every other UI control must be
    immediately clickable with no Escape-key workaround needed.
- **Data-honesty cluster** (each is independent, but share the "surface a
  clear error" theme):
  - `ins-convergence-window-cap-mismatch` — lower the `#cv-window` input's
    `max="3650"` to `max="90"` (matching the backend's real `le=90` cap,
    `src/api/insights.py`'s convergence endpoint) so the input never invites a
    value the backend will reject. SEPARATELY (this is the more broadly
    valuable half — likely affects other endpoints too), fix the generic
    `api()` helper's error path (`app.js`, the `throw new Error((data &&
    data.detail) || ...)` line) to handle a FastAPI/Pydantic 422 validation
    error body correctly: `data.detail` can be an ARRAY of `{type, loc, msg}`
    objects, not a string — when it's an array, join the `.msg` fields into a
    readable message instead of letting `Error()`'s string coercion produce
    `[object Object]`. This second half is the higher-value fix since it
    prevents the SAME class of confusing error on every other endpoint with a
    similar validation constraint, not just this one field.
  - `governments-law-pointer-misleading-zero-tracked` (this finding was
    independently rediscovered by 4 separate test groups in PR #744 — strong
    signal) — the Governments→Countries pointer text ("⚖ Law: N tracked · M
    changes") must use the SAME "tracked" definition the Law subtab itself
    uses (total documents being watched, not only baselined ones) — find the
    backend field the pointer reads (likely in the same endpoint the Law
    subtab's own stat grid reads) and either point both at the same count, or
    give the pointer its own distinctly-worded field if the two numbers are
    legitimately different concepts (e.g. "23 tracked · 0 baselined" instead
    of a bare "0 tracked" that implies emptiness). Prefer showing BOTH numbers
    if the distinction is real — that's more honest than collapsing to one
    misleading word.
- **Accessibility/contrast cluster:**
  - `pillwarn-severe-contrast` (P1, the severe-theme half; the merged entry
    also covers the borderline-theme P2 half) — apply the SAME fix pattern
    the project already used for `var(--caveat)` (invariant #23's contrast
    fix) to the sibling `var(--warn)` variable used by `.pill.warn`: verify
    computed contrast ≥4.5:1 against `.pill.warn`'s background across ALL 18
    themes (not just the 7 that currently fail), the same way the caveat-color
    fix was verified. This single CSS-variable fix should resolve both the P1
    (Dawn/Paper/Solar, 1.87–2.42:1) and P2 (Light/System/Mist/Mint,
    3.3–3.5:1) tiers at once.
  - `evidence-links-contrast-and-no-underline` — add either an underline or a
    sufficiently distinct color to Home Lead-card evidence links and
    "Latest in your corpus" article links (axe: `link-in-text-block`, serious,
    24 nodes) so links are distinguishable from surrounding text by more than
    color alone.
  - `lead-card-nested-interactive` — the Lead card's outer flip-card container
    is `role="button" tabindex="0"` while ALSO containing further genuinely
    interactive controls inside it (axe: `nested-interactive`, serious, 23
    nodes). Restructure so the outer container is not itself a focusable
    interactive role if it must contain nested interactive children — e.g.
    make the flip-trigger a distinct, appropriately-scoped control rather than
    the whole card, or use `role="group"` on the outer container with the
    flip behavior triggered by an explicit inner button.
- **i18n reactivity cluster** (a systemic pattern across many surfaces —
  build ONE reusable mechanism if the codebase's i18n engine (`OOI18N`)
  supports re-render-on-language-change hooks; check `src/static/i18n.js` or
  wherever `OOI18N.setLang` lives for an existing subscription/callback
  mechanism before adding a new one):
  - `home-i18n-mixed-language-glance`, `home-lead-title-frozen-locale`,
    `hazard-caveat-untranslated`, `insights-landscape-headers-hardcoded`,
    `reader-i18n-dynamic-content-untranslated` — each needs the specific
    dynamically-rendered text (glance-strip labels, Lead-card titles built via
    `OOI18N.tf`, the hazard/consent disclosure paragraph, the corpus-landscape
    column headers, reader.js's tab labels/dynamic caveats) to actually call
    the live translation function at RENDER TIME rather than being computed
    once and cached, OR to re-render on a language-change event if one exists.
    Fix as a cluster: find the shared root cause first (likely: some of these
    render once at initial load using a captured/stale locale reference rather
    than reading `OOI18N.current()` fresh, or `reader.js` — per the finding —
    never imports/calls the translation function at all, a more fundamental
    gap than the others). Prioritize `reader-i18n-dynamic-content-untranslated`
    first (it's the most complete gap — the standalone reader's dynamic
    content is not localized AT ALL, not just stale-on-switch).

### 5.3 Recommended P2 shortlist (only if time remains after all P0/P1 + Workstream A)

Per `findings.csv`, in priority order if budget allows: `mkt-004-feed-verdicts-never-shown`
(dead code with no live UI path — either wire it or remove it, don't leave a
maintained-but-unreachable function), `diag-multi-download-buttons` (6 stray
buttons the one-button-bundle ruling should have removed), `sf-ollama-hidden`
(Storage footprint should show an honest "unavailable" row for the Ollama
store instead of omitting it silently), `mkt-003-compare-feature-unreachable`
(a built, unreachable feature — wire its entry point), `leads-carousel-ignores-reduced-motion`
(respect `prefers-reduced-motion` in the carousel's JS timer, not just via
static CSS).

---

## 6. House verification protocol (exact commands — copy these, don't approximate)

Every fix, in every PR this session opens, must pass:

```bash
# Blocking correctness lint (F = pyflakes, B = bugbear; B008 re-ignored since
# --select on the CLI drops pyproject's config-level ignore list)
ruff check --select=F,B --extend-ignore=B008 src/ tests/

# Full style lint (advisory in CI, but worth running clean anyway)
ruff check src/ tests/

# i18n completeness gate (only touch this if a fix adds/changes a user-facing
# chrome string — key it in all 12 locales, then:)
python scripts/i18n_report.py --min 100

# Migration drift check (only relevant if a fix touches src/database/models.py)
OO_DB_PLAINTEXT=1 alembic upgrade head
OO_DB_PLAINTEXT=1 alembic check

# Full test suite
python -m pytest -q

# Type-check ratchet — must NOT exceed the current baseline (127 as of this
# brief's authoring; re-check .github/workflows/ci.yml's MYPY_BASELINE env var
# for the current number, it may have moved)
python -m mypy src/ 2>/dev/null | grep -c " error: "   # compare against MYPY_BASELINE

# Security (blocking; pinned version matters — an unpinned bandit can redden
# a PR through no code change of your own)
python -m pip install bandit==1.9.4
bandit -r src/ -ll -q
```

`make check` (= `ruff check src/ tests/` + `python -m pytest -q`) is the quick
local convenience target but does NOT run the full CI gate set above — run
the explicit commands before pushing, not just `make check`.

**Data-safety / shared-connection skeptic gate:** per the standing house
convention, anything touching `src/database/connect.py`, `src/database/
session.py`, or any migration MUST get an adversarial skeptic pass (a fresh
agent trying to REFUTE the fix, with a negative-space lens — malformed input,
concurrent access, the reopen-after-restart case explicitly) before that PR
is pushed. This applies squarely to Phase 1 (§4.1) — do not skip it because
Phase 1 "looks small."

**PR discipline:** one PR per phase/finding-cluster (never one PR spanning
both PR #740's and PR #744's remediation), draft onto `main`, each PR's
description cites the exact finding id(s) or plan phase number(s) it
addresses. Record each shipped slice as a `docs/ledger/shipped.csv` row per
the house append-rule (date, area, item, status, refs, key_paths, summary);
add a `CLAUDE.md` Lessons bullet only if a slice surfaces a genuinely reusable
lesson (the §4.1.2 reopen-safety design, if built, likely qualifies — it's
exactly the kind of "would bite the next person building something similar"
fact the Lessons list exists to capture).

---

## 7. Orchestration — maximizing subagent parallelism

The two workstreams are **almost entirely file-disjoint**: Workstream A
touches `src/database/`, `src/scheduler/`, `src/law/`, `src/analytics/`,
`src/geo/`, `src/briefing/`, `src/api/insights.py`, and `docs/`; Workstream B
touches `src/static/app.js`, `src/static/index.html`, `src/static/unlock.html`,
and (for one P0 only) `src/api/main.py`. This is the ideal shape for real
parallel execution, with one important exception below.

**Recommended shape** (adapt to whatever orchestration tooling the executing
session has available — a `Workflow`-style script if available, or manual
`Agent` fan-out otherwise):

1. **Phase "DB-10" (sequential, solo or one dedicated agent):** build §4.1 in
   full (both PRAGMAs, the reopen-safety mechanism, the idle-vacuum wiring,
   the VACUUM-button gate, the acceptance test) before starting anything else
   that touches `src/database/`. This is the one workstream that should NOT
   be parallelized with other database work, given its safety stakes and the
   mandatory skeptic gate.
2. **Phase "Backend-parallel" (fan out, fully independent files):** once
   Phase 1 is merged (or at least stable on its own branch), run §4.2 (docs),
   §4.3 (field-diagnostics), §4.4 (law vertical), §4.5 (keyword-baseline), and
   §4.6 (OSM preprocessing) as GENUINELY PARALLEL agents — none of them share
   a file with each other or with Phase 1's changes. No worktree isolation
   needed; they simply don't collide.
3. **Phase "Frontend-P0s" (fan out with isolation):** the 5 P0 fixes from §5.1
   mostly touch DIFFERENT files (main.py, unlock.html, app.js×2 for
   net-coach+overflow, index.html for the label) — but two of them
   (net-coach and the responsive-overflow fix) both live in `app.js`/CSS
   territory and could plausibly touch overlapping regions. Use **worktree
   isolation** (`opts.isolation: 'worktree'` if using the Workflow tool, or an
   equivalent manual git-worktree-per-agent setup otherwise) for any pair that
   touches the same file, so concurrent edits never silently clobber each
   other; merge/rebase them back together as a final integration step before
   opening PRs.
4. **Phase "Frontend-P1s" (fan out with isolation, same caveat):** the P1
   clusters in §5.2 mostly touch `app.js` too (it's a single ~17,000-line
   file carrying nearly all frontend logic) — worktree-isolate these as well,
   or alternatively serialize them within ONE agent context if worktree
   isolation isn't available, since sequential edits to the same file by one
   agent are always safe.
5. **Phase "Verify" (fan out per fix):** for every fix from Workstreams A and
   B, spawn an independent re-verification agent that reproduces the ORIGINAL
   bug's repro steps (from the finding/phase description) against the FIXED
   code and confirms the defect is actually gone — this is the acceptance
   bar, not just "the new test I wrote passes" (a self-authored test can
   accidentally test the wrong thing; re-running the ORIGINAL external repro
   is the check that catches that).
6. **Phase "Skeptic" (mandatory for Phase 1 only, recommended for the rest):**
   an adversarial pass specifically on the DB-10 changes (negative-space lens:
   concurrent opens, a corrupted/missing marker file if using design (a),
   a legacy 4096-page-size store's reopen behavior must be BYTE-IDENTICAL to
   today — prove that explicitly, don't just assume the new code path is
   inert for old stores).
7. **Phase "Ship":** one PR per completed, verified slice, per §6's
   discipline; ledger rows for each.

---

## 8. Deliverables & definition of done

- Every §4.1 sub-item (Phase 1) built, tested per §4.1.6's exact acceptance
  criteria (including the mandatory create→restart→reopen round-trip if §1.2
  ships), skeptic-verified, and shipped as 1–2 PRs (auto_vacuum alone, and
  optionally page_size+reopen-safety as its own clearly-flagged PR per
  §4.1.5).
- Phases 2, 3 (3.1–3.3), 4.1–4.2, 6, and 9 (9.1–9.2) from Workstream A each
  built and shipped as their own PR(s), respecting every gate in §2.
- All 5 P0s from Workstream B fixed, each re-verified against its ORIGINAL
  repro, each shipped as its own PR (or one combined PR if the net-coach fix
  and the responsive-overflow fix turn out to share enough surface area that
  splitting them is artificial — use judgment, but default to separate).
- As many of the 24 P1 clusters from §5.2 as the session's time budget allows,
  prioritizing the state/architecture cluster (restores a flagship feature)
  and the settings-integrity cluster (silent data loss of a user's
  preference) first.
- A closeout note (in this brief's own status line, or a fresh `CLAUDE.md`
  Open-queue entry if substantial work remains) stating PLAINLY what was
  built vs what's left — including any P1s not reached and the full P2/OPT
  tier, which is expected to remain open after this session; never claim more
  than what's actually shipped and verified.
- Every shipped slice has its `docs/ledger/shipped.csv` row.
