# AUTONOMOUS SESSION BRIEF — PR #744 GUI-FIX REMEDIATION, INCREMENTAL-WORKFLOW EDITION (2026-07-22)

**Status:** brief of record, execution PENDING.
**Scope:** PR #744 ONLY (`test: systematic GUI test — 100-agent Chromium pass finds 5
P0s, 24 P1s`, merged `3be0622`, delivering `docs/audit/GUI_TEST_REPORT_2026-07-22.md`
+ `docs/audit/gui-test-2026-07-22/findings.csv`, 72 merged findings: 5 P0, 24 P1, 38
P2, 5 OPT). **PR #740's workstream (DB-10, docs hygiene, law vertical,
keyword-baseline, OSM preprocessing) is explicitly OUT OF SCOPE for this document —
see §1.2.**

**How this differs from the existing combined brief
(`AUTONOMOUS_SESSION_BRIEF_2026-07-22_PR740_PR744_REMEDIATION.md`, delivered by
PR #745):** that brief already gives fix specs for PR #744's 5 P0s and clusters its
24 P1s — read alongside PR #740's disjoint backend/docs workstream, on the reasoning
that the two PRs' file scopes barely overlap. **This brief is a different, narrower
instrument, purpose-built to a different ask: PR #744 alone, at higher fix-spec
resolution (every P0 and P1 independently re-verified against the live tree with
exact current line numbers, several with corrections/refinements the combined brief
did not have — see §3.1 for what's new), and with an explicit, load-bearing
ORCHESTRATION DISCIPLINE the combined brief only sketched: this session must run as
**several separate, small `Workflow` tool invocations, issued one after another
across the session — never one large script, and never two invocations whose file
scope overlaps running at the same time.** §2 is the binding rule set for that
discipline; §5 is the ordered phase plan built around it. If a future session runs
BOTH this brief and PR #740's workstream, run them as fully separate sessions or
fully separate sequential passes — do not interleave their `Workflow` calls, since
this brief's own non-overlap guarantee only holds within its own phase sequence.

---

## 0. Ground truth hierarchy

`CLAUDE.md` is the single binding ledger; this brief does not override it. Every
citation below was **read directly from the live tree by the session authoring this
brief** (verified at `main` commit `7405968`, two commits after PR #744's own merge
`3be0622` — the two intervening commits are `885f809` (PR #745, docs-only: the
combined-brief) and the merge commit itself; neither touched any file this brief
cites). `git log 3be0622..HEAD -- src/static/app.js src/static/index.html
src/static/unlock.html src/static/app.css src/database/models.py src/api/main.py
src/analytics/store.py src/backup/merge.py src/api/law.py src/law/coverage.py
src/briefing/producers.py src/static/i18n.js` returns **empty** — confirmed zero
drift on every file this brief touches. **Re-run that same command yourself before
starting** — if it returns anything, re-verify the specific citations below before
trusting them; this repo fast-merges.

---

## 1. Mission and scope

### 1.1 In scope (mandatory)

1. Fix all **5 P0s** from `docs/audit/gui-test-2026-07-22/findings.csv`.
2. Fix **28 of the 24 P1s** — every P1 except `ins-map-cjk-sentence-keywords`, which
   is explicitly deferred (§1.4). (24 P1 rows total; 23 are in scope, 1 deferred —
   the arithmetic in this sentence intentionally spells out both counts so a partial
   run is never silently reported as complete.)
3. Two small bonus items that ride along at zero extra cost because they share a
   code block with a mandatory fix: the OPT-tier `reader-dupbadge-n-plus-1-decrypt-risk`
   (rides with the P0 dead-table fix) and the P2-tier `LC-ERROR-TEXT-UNTRANSLATED`
   (rides with the P0 unlock.html fix — it is currently invisible, masked by the P0
   bug itself, and becomes a visible defect the instant the P0 ships, so fixing it in
   the same phase is the honest choice, not scope creep).
4. Every fix: reproduce the ORIGINAL defect first, apply the fix, re-run the exact
   original repro and confirm the reported `actual` no longer occurs, add a durable
   regression test (§4.4), ship as its own small PR citing the finding id(s), record
   a `docs/ledger/shipped.csv` row.

### 1.2 Explicitly out of scope

- **All of PR #740's workstream.** Different session, different problem domain
  (DB-10 create-time PRAGMAs, docs hygiene, the law vertical, keyword-baseline
  migration, OSM preprocessing). Do not import any of it here, and do not let this
  session's `Workflow` calls interleave with a concurrently-running PR #740 session
  if one happens to be active — this brief's non-overlap guarantee is scoped to its
  own phase sequence only.
- **The P2 (38) and OPT (5) tiers**, beyond the two bonus items in §1.1.3. §9 gives
  an optional shortlist if time remains after every mandatory item ships — never
  claim the whole P2/OPT tier was addressed.
- **Anything needing a real Ollama rig, a networked machine, or the maintainer's
  actual click-through** — none of the in-scope findings need any of these (they are
  all fixable and testable in a Chromium-in-sandbox + scratch-server environment,
  the exact one PR #744's own session used).

### 1.3 Do NOT "fix" these three — they are deliberate, documented decisions, not defects

A pattern-match on their surface description could make an executing agent think
these are actionable bugs. They are not; re-read their `findings.csv` `expected`
column before touching anything nearby, and leave the underlying decision alone:

- **`LC-WIZARD-ONLINE-NO-SEPARATE-CONFIRM`** (P2) — the finding's own text confirms
  this is a **deliberate, dated (2026-07-17) design change**, in-source: the wizard's
  finish step carries its own equivalent consent disclosure and intentionally skips
  re-opening the separate `#net-consent` dialog via `ensureOnline(reason,
  {skipDialog:true})`. This is not a scope-fence item this brief is fixing — do not
  add a second confirmation back.
- **`governments-tab-defaults-to-countries-not-law`** (P2) — also a **documented,
  dated (2026-07-17) decision**: an in-source code comment explicitly states the
  Governments tab keeps Countries as its default subtab, with a small always-visible
  pointer chip (`#gov-law-pointer`) as the chosen discoverability mitigation instead
  of changing the default. **The only actionable item near this surface is
  `governments-law-pointer-misleading-zero-tracked` (P1, §5.8) — fixing the
  pointer's own honesty, never the default-tab choice.**
- **`llm-triage-airplane-mode-off-required-for-local-inference`** (P2) — this is
  PR #744 merely **reconfirming** an item already tracked in `CLAUDE.md`'s Open
  queue under "AIRPLANE MODE MUST NOT BLOCK LOOPBACK OLLAMA INFERENCE" (2026-07-20),
  which already carries its own detailed, correct design (split the kill-switch gate
  by egress class: loopback generation/list/health should work offline, only
  pull/remove — which egresses via the separate Ollama process — should stay
  gated). That ledger entry is the fix spec, not this brief; if picked up as a
  bonus item, use ITS design, not a new one invented here.

### 1.4 Deferred (needs a deeper fix than this session should attempt)

- **`ins-map-cjk-sentence-keywords`** (P1) — a real, user-visible manifestation of
  this project's own standing, tracked CJK/Thai segmentation gap (the `[segmentation]`
  extra / a proper NER pass, per the keyword-engine program already recorded in
  `CLAUDE.md`). A shallow UI patch here (e.g. truncating the pill text) would hide
  the symptom while misrepresenting it as fixed. Leave it; note it in the closeout
  as deferred, not silently dropped.

---

## 2. Orchestration discipline — read this before writing a single line of code

This is the part of the brief the user explicitly asked to get right. Three rules,
binding for the whole session:

**Rule A — many small `Workflow` invocations, not one big one.** Do not write a
single `Workflow` script that attempts §5's Phases 1 through 8 in one call. Issue
the `Workflow` tool **once per phase**, in the order given in §5, reading each
phase's result, confirming its PR is drafted and the working tree is clean, before
issuing the next phase's call. This is the tool's own documented guidance for large
work ("run several in sequence... you stay in the loop; each workflow is one
well-scoped fan-out") — follow it literally here, not just in spirit.

**Rule B — parallelize only across genuinely disjoint files; sequence everything
that shares a file.** `src/static/app.js` is 17,508 lines and is the single most
contended surface in this remediation (it carries the majority of both P0s and
P1s). Two agents editing the same file concurrently — even at "different, far-apart
line ranges" — is exactly the collision class this project's own ledger has been
burned by more than once (duplicate top-level function names silently overriding
each other; the interleaved-shared-helper hazard; parallel-session file races). So:

- **Across phases:** at most ONE phase in this brief's sequence may have an agent
  actively editing `src/static/app.js` (or `app.css`, or `index.html`) at any given
  wall-clock moment. §5's phase list is ordered precisely so this holds — never
  reorder two phases that both touch the same file to run concurrently.
- **Within a phase:** when a phase's own findings share a file, use ONE agent to
  handle all of them, sequentially, within its own single turn (safe — one agent
  editing one file serially never races itself) — or, if using `pipeline()`/
  `parallel()` inside a `Workflow` script, only ever place items with **disjoint**
  file scope into the same `parallel()`/pipeline-stage group. §5 states the exact
  grouping per phase; do not improvise a different grouping for convenience.
- This does NOT mean "less parallelism." It means parallelism is spent on the axis
  that is actually safe (across phases separated in time; across genuinely
  independent files within a phase) rather than the axis that would silently
  corrupt work (concurrent writers to one file). Phases 1, 6, 7, and 8 each fan out
  2–3 real parallel agents; Phases 2–5 use sequential-within-one-agent chains
  specifically because their scope is one contended file.

**Rule C — maximize subagents on the axes that ARE safe: fixer → verifier → skeptic,
per finding, in every phase.** Every fix in this brief goes through at minimum two
distinct agent roles, and the higher-risk phases (3 and 5, marked below) go through
three:
1. **Fixer** — reproduces the original defect (from `findings.csv`'s `repro`
   column), applies the fix, writes the regression test (§4.4).
2. **Verifier** — a FRESH agent (not the fixer) that re-runs the exact ORIGINAL
   repro steps against the fixed code and independently confirms the reported
   `actual` behavior is gone. This is the acceptance bar, not "the fixer's own new
   test passes" — a self-authored test can accidentally test the wrong thing;
   re-running the external repro is what catches that. This mirrors PR #744's own
   methodology exactly (a fresh skeptic agent re-reproduced every candidate finding
   before it was allowed to survive).
3. **Skeptic** (Phases 3 and 5 only, mandatory; recommended everywhere else if
   budget allows) — an adversarial agent explicitly hunting for a regression the fix
   might have introduced, with a negative-space lens (concurrent state, a second
   browser tab, a page reload mid-flow, an already-in-flight request) — never just
   re-confirming the happy path the fixer already tested.

So: dozens of `agent()` calls happen across this session's ~8 `Workflow`
invocations (never zero, never one monolithic pass) — Rule C is where the
subagent-maximization the user asked for actually lives; Rules A/B are what keep
that maximization from becoming a collision risk.

---

## 3. What's verified, and what's new versus the existing combined brief

### 3.1 Corrections/refinements this brief adds beyond both PR #744's own report and
the existing `PR740_PR744_REMEDIATION` brief (re-derived directly from source, not
copied):

- **The `#net-coach` positioning bug has a precise mathematical root cause neither
  prior document states.** `_placeCoach()` (`src/static/app.js:541-565`) has exactly
  two branches: place to the right of `#net-toggle`, or — if there is no room —
  place ABOVE it (`top = b.top - gap - h`). Because the topbar sits at the very top
  of the viewport (`b.top` is only ~14px), that "above" branch's computed `top` is
  always deeply negative, and the subsequent clamp
  (`top = Math.max(pad, Math.min(top, ...))`) always collapses it back down to
  `pad` (8px) — i.e. the "above" fallback can **never actually place the coach above
  the topbar**; it always lands back inside the topbar's own row, which is exactly
  why it ends up overlapping `#lang-switch`/`#tm-open`/`#app-shutdown`. This is not
  a "sometimes wrong" heuristic — it is guaranteed wrong every time the right-side
  branch doesn't fit, which is precisely the crowded-topbar case the finding
  reproduces. **The correct fix is a third, ALWAYS-SAFE fallback direction: below the
  entire topbar row**, not above it (see §5.2 for the exact change).
- **`saveSettings()`'s lossy theme-bucket call (line 4969) and `loadSettings()`'s
  structurally-IDENTICAL-looking call (line 4840) are NOT both bugs — only the
  first one is.** `loadSettings()`'s call is correctly guarded:
  `if (!localStorage.getItem(UI_KEY)) { setTheme({dark:"ink",...}[s.theme] || "ink"); }`
  — it only ever fires on a brand-new local install with no theme choice yet (a
  first-run seed from the server default), which is intentional and correct.
  `saveSettings()`'s call at line 4969 has **no such guard** and fires
  unconditionally on every Save click. **Do not "fix" line 4840 — only line 4969 is
  the defect.** (Neither prior document draws this distinction; a naive fix could
  otherwise break the legitimate first-run seeding behavior.)
- **The generic `api()` error handler (`src/static/app.js:1294-1312`) is the
  literal, single shared entry point for essentially every network call in the
  SPA.** Line 1312's `throw new Error((data && data.detail) || ...)` is why a
  FastAPI/Pydantic 422 validation error (whose `detail` is an array of `{type, loc,
  msg}` objects) renders as `[object Object]` — not just on the Convergence window,
  but potentially on any endpoint with a similar validation constraint. Given this
  blast radius, this brief promotes it out of the P1 cluster it originally
  co-occurred in and gives it its OWN phase (§5.5) with a mandatory skeptic pass —
  it is small, but it is shared infrastructure.
- **Two findings need a short investigation step before their exact fix location is
  certain** — flagged honestly rather than given a falsely-precise instruction:
  - `governments-law-pointer-misleading-zero-tracked`: `src/law/coverage.py`'s own
    `tracked = len(rows)` (line 53) already computes the CORRECT, non-baseline-
    filtered count the Law subtab uses — but the pointer at
    `src/static/app.js:4086-4091` reads a DIFFERENT `s.tracked` field from whatever
    endpoint populates the function surrounding that line (not yet traced to its
    exact source in this brief's own verification pass). §5.8 instructs: read
    `src/static/app.js` lines ~4060–4092 in full first, trace which `api()` call
    populates `s`, THEN decide between pointing the pointer at the
    `coverage.py`-backed count vs. showing both numbers explicitly.
  - `worldmap-fullscreen-hides-legend-caveat`: the fullscreen target is
    `host.querySelector(".oomap-wrap")` (`src/static/app.js:13242-13246`), and
    `.oomap-legend` (line 13159) is built in the same `host.innerHTML` template
    literal starting at line 13142 — but whether it is a DOM child or sibling of
    `.oomap-wrap` needs a direct read of that template literal before choosing
    between "fullscreen the wider container instead" and "move the legend inside
    `.oomap-wrap`." §5.8 gives both options with a stated preference.

### 3.2 Everything else in §5 below was independently confirmed by this brief's own
grep/read pass against the live tree (not merely trusted from either PR's prose):
exact function names, exact line numbers, and the exact current code shape are all
quoted or paraphrased from a direct read taken while authoring this brief.

---

## 4. Environment, reproduction, and fix discipline

### 4.1 Scratch environment (same recipe PR #744's own session proved works)

```bash
python3.13 -m venv /tmp/oo_venv
/tmp/oo_venv/bin/pip install -q --upgrade pip
/tmp/oo_venv/bin/pip install -q -e ".[analysis]"

export OO_DATA_DIR=/tmp/oo_data_744fix
mkdir -p "$OO_DATA_DIR"
nohup env OO_DATA_DIR=$OO_DATA_DIR OO_DB_PLAINTEXT=1 \
  /tmp/oo_venv/bin/open-omniscience > /tmp/oo_server.log 2>&1 &
# wait for "Uvicorn running on http://127.0.0.1:8000" (~15s)
```

Chromium is pre-installed at `/opt/pw-browsers`; drive it via `playwright-core`
(Node) exactly as PR #744's own session did, or via the Python `playwright` package
if a given fix's verification is cleaner as a backend-only test.

### 4.2 No committed synthetic-corpus seed script exists

PR #744's own 490-article, 8-language synthetic corpus was seeded by a **scratch
script that was never committed** (per its own brief, `docs/design/
AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md`: "session scratchpad,
NOT committed"). Do not assume a reusable seed script exists in the repo. Instead:
**seed the MINIMUM fixture each specific finding needs**, always through the real
`index_article` ingestion chokepoint (never raw SQL inserts) — e.g. the reader
dead-table fix needs only 2–3 near-duplicate articles sharing keywords; the boot-
race fix needs no article content at all, only the boot sequence and
`localStorage` state; the i18n findings need at least one non-English article to
exercise the Home glance strip meaningfully. Building a full 490-article corpus for
every single finding wastes effort where a 3-article fixture proves the same fix.

### 4.3 Per-fix discipline (every phase, every finding)

1. Reproduce the ORIGINAL bug exactly per `findings.csv`'s `repro` column, on the
   scratch server, BEFORE touching any code. Confirm the `actual` column's
   described behavior actually occurs in this environment.
2. Apply the isolated fix.
3. Re-run the identical repro steps; confirm the `actual` behavior is gone and the
   `expected` column's behavior now holds.
4. Add a regression test (§4.4).
5. Ship as its own PR (or the smallest sane bundle per §5's phase groupings),
   citing the finding id(s) from `findings.csv` in the PR description.

### 4.4 Regression-test convention — use the one this codebase already has

This project pins frontend behavior with **source-level string/regex assertions**
against the concatenated JS+HTML text, not live-browser tests, in
`tests/test_repo_invariants.py` (the `test_ui_invariants` function and its many
neighboring `test_*` functions are the existing pattern — e.g.
`test_net_coach_suppressed_while_the_wizard_is_open` at line 2606 slices out a
function body via `html.split("function maybeShowNetCoach() {", 1)[1].split
("\n    }\n", 1)[0]` and asserts specific substrings inside it). **Follow this exact
idiom for every frontend fix in this brief** — a new `test_repo_invariants.py::
test_<description>` function per fix (or per closely-related cluster), slicing the
relevant function body and asserting the fix's specific code characteristic is
present (and, where relevant, that the old broken characteristic is gone). This
gives durable CI coverage without needing a browser on every future run; the
live-Chromium repro in §4.3 is the one-time acceptance proof, this test is what
keeps the fix from regressing silently later. Backend fixes (Phase 1a, Phase 8a)
get an ordinary pytest test in the appropriate `tests/test_*.py` file instead.

---

## 5. The phase plan — one `Workflow` invocation per phase, in this order

### File-ownership map (the master reference — do not deviate from this grouping)

| File | Touched by (finding ids) | Phase(s) |
|---|---|---|
| `src/api/main.py` | `reader-dead-legacy-table-related`, `reader-dupbadge-n-plus-1-decrypt-risk` | 1a |
| `src/static/unlock.html` | `LC-VIEW-HIDDEN-ON-ERROR`, `LC-ERROR-TEXT-UNTRANSLATED` | 1b |
| `src/static/index.html` | `font-size-slider-missing-label`; `ins-convergence-window-cap-mismatch` (select `max` attribute only); `ins-kind-filter-nonfunctional-options` | 1c, 8b |
| `src/static/app.js` | `net-coach-blocks-topbar-buttons`+`netcoach-blocks-lang-switch`; `topbar-overflow-mobile-375`+`topbar-overflow-mainstream-widths`; `analysis-boot-race-destroys-tab-workspace`; `dblclick-opens-duplicate-analysis-tabs`; `an-mindmap-wrong-corpus-scope`; `theme-select-lossy-overwrite`; `imp-ghost-modal-after-back`; `ins-convergence-window-cap-mismatch` (the `api()`-error half only); `home-lead-title-frozen-locale`; `insights-landscape-headers-hardcoded`; `lead-card-nested-interactive`; `governments-law-pointer-misleading-zero-tracked` (frontend half); `ins-kind-filter-nonfunctional-options`; `home-recent-panel-hidden-on-error`; `mkt-002-stale-caveat-scale-toggle`; `worldmap-fullscreen-hides-legend-caveat`; `help-md-linebreak-bug` | 2, 2, 3, 3, 3, 4, 5, 5, 6a, 6a, 7, 8b, 8b, 8b, 8b, 8b, 8b (17 items, in the same order as the middle column) |
| `src/static/app.css` | `chip-button-color-contrast`; `evidence-links-contrast-and-no-underline`; `pillwarn-severe-contrast`; the `.topbar` responsive rules (shared with the `app.js` overflow fix above) | 7, 7, 7, 2 |
| `src/static/i18n.js` | `home-i18n-mixed-language-glance` | 6b |
| `src/static/locales/*.json` (12 files) | `hazard-caveat-untranslated` | 6c |
| `src/briefing/producers.py` | `home-opencorpus-recipe-promise-seed` | 8a |
| `src/api/law.py` / `src/law/coverage.py` (investigate first) | `governments-law-pointer-misleading-zero-tracked` (backend half) | 8a |

**Invariant this table encodes: `app.js` and `app.css` are each touched by more than
one phase, but never by two phases running at the same time (Rule A/B, §2). Within
Phase 8, the backend track (8a) and frontend track (8b) genuinely never touch the
same file, so — and only so — they run as true parallel agents inside that one
`Workflow` call.**

---

### Phase 1 — Isolated files, fully parallel (`Workflow` call #1)

Three findings, three completely disjoint files, zero shared territory — the one
phase in this brief where true `parallel()`/`pipeline()` fan-out across the fix
itself (not just fixer/verifier roles) is unambiguously safe.

**1a — `src/api/main.py`: `reader-dead-legacy-table-related` (P0) + `reader-dupbadge-n-plus-1-decrypt-risk` (OPT).**
Verified root cause: `src/api/main.py:1761` and `:1807` build the reader's "Related"
candidates via `article_keyword_association` (`src/database/models.py:748-749`), a
legacy `Table` with **zero writers** anywhere in the live ingest path — confirmed:
`grep -rln "article_keyword_association" src/` returns only `models.py` (definition),
`main.py` (this broken query), and `src/backup/merge.py` (carries legacy rows
through a restore, never inserts new ones). `src/analytics/store.py`'s
`index_article` (the real per-article extraction chokepoint) writes only
`KeywordMention` rows. **Fix:** rewrite both blocks (`~1761`, `~1807`) to find the
current article's `KeywordMention` keyword ids, then find OTHER articles sharing
the most of those ids, ranked by shared-keyword count — same shape, pointed at the
live table. **In the same change**, bound the query to an id/count-only projection
for the candidate step (do not `.get_content()` on every candidate row) so fixing
the honesty bug does not re-expose an N+1 full-body-decrypt cost (the OPT finding);
only fetch full titles for the small, capped result set actually rendered. Check
`EXPLAIN QUERY PLAN` before shipping (the project's own documented SQLCipher
codec-column-order perf trap).

**1b — `src/static/unlock.html`: `LC-VIEW-HIDDEN-ON-ERROR` (P0) + `LC-ERROR-TEXT-UNTRANSLATED` (P2 bonus).**
Verified root cause (confirmed live): `go(btn, fn)` (the click handler shared by
`#btn-unlock` and `#btn-create`) calls `_startPrep()`, which unconditionally hides
`view-unlock`/`view-create`/`view-open` and shows `view-preparing` BEFORE `fn()`
resolves. On a thrown error, the `catch` block sets `box.textContent = e.message`
and re-enables the button, but the ONLY hide/show call it makes is
`$("view-preparing").classList.add("hidden")` — it never removes `hidden` from
whichever view `_startPrep()` hid, so the whole form stays invisible with the error
text trapped inside it. **Fix:** have `_startPrep()` record which view was visible
before hiding it (the caller already knows — `go()` is invoked per-button), and have
the `catch` block re-show that exact view. Bonus, same file, now-unmasked: the error
strings ("use at least 8 characters", "passphrases do not match") are hardcoded
English regardless of locale — key them through the same `t()` mechanism the rest
of the page already uses, in all 12 locales. **Acceptance:** submit a too-short
passphrase → `#view-create` stays visible, `#msg2` shows the (correctly-localized)
error, `document.body.innerText` is non-empty.

**1c — `src/static/index.html`: `font-size-slider-missing-label` (P0).**
Verified: line 1136–1137, `<div class="seg"><div class="sl">Text size · <span
id="dr-font-val">100%</span></div><input type="range" id="dr-font" min="88"
max="124" step="2" oninput="setFont(this.value)"></div>` — the `.sl` div carries the
visible label text but has zero programmatic association with the input. **Fix:**
change the wrapping `<div class="sl">` to a `<label class="sl" for="dr-font">`
(same visual result, now a real `<label for>`). One-line change, zero blast radius.
**Acceptance:** axe-core's `label` violation on `#dr-font` no longer fires.

Orchestration shape: `parallel([fix1a, fix1b, fix1c])`, each thunk itself a
fixer→verifier pipeline (`pipeline([the one item], fixStage, verifyStage)` or a
plain sequential pair of `agent()` calls). Three separate small PRs.

---

### Phase 2 — Topbar chrome (`app.js` + `app.css`, sequential, `Workflow` call #2)

One agent handles both items sequentially (same-file discipline; both are "topbar
chrome," reasonable to bundle as one small PR if the executing session judges the
diffs cohesive, or two PRs if cleaner — use judgment, default to keeping them
together since they're genuinely the same subsystem).

**Net-coach overlap (`net-coach-blocks-topbar-buttons`, P0 + `netcoach-blocks-lang-switch`, P1).**
Root cause, precisely (see §3.1 — this is the refinement beyond both prior
documents): `_placeCoach()` (`src/static/app.js:541-565`)'s "float above" fallback
branch is mathematically incapable of placing the coach above the topbar (the
clamp always collapses `top` back to `pad`), so it always lands back inside the
topbar's own row, overlapping `#net-toggle`, `#lang-switch`, `#tm-open`, and
`#app-shutdown`. **Fix:** add a third fallback — when there is no room to the right,
compute the union bounding rect of ALL FOUR protected buttons
(`document.querySelectorAll` or four individual `getBoundingClientRect()` calls
unioned), and place the coach BELOW that entire union rect (`top = unionRect.bottom
+ gap`), never above it. Since the topbar sits at the top of the viewport, "below
the whole row" is the one direction guaranteed to have room, and it structurally
cannot overlap any of the four buttons since its vertical range starts strictly
after theirs ends. Keep horizontal placement centered under `#net-toggle`, clamped
to viewport, as today. **Acceptance:** while the coach is showing,
`document.elementFromPoint()` at the center of all four buttons resolves to the
button itself; a real `.click()` on each succeeds without timing out.

**Topbar overflow (`topbar-overflow-mobile-375-net-toggle-unreachable`, P0 +
`topbar-overflow-mainstream-widths`, P1).**
Verified: `.topbar` (`src/static/app.css:149-151`) is `display:flex` with no
`flex-wrap` (default `nowrap`) and no bounding media query anywhere in the file (the
only nearby breakpoints — `860px`/`601px`/`600px`, lines 870/875 — govern unrelated
elements). Confirmed via `documentElement.scrollWidth` exceeding `clientWidth` at
1024/768/601/375px, with zero responsive handling. **Fix:** add a real narrow-
viewport strategy — either (a) an overflow/kebab menu collapsing the airplane/
language/task-manager/shutdown cluster below a chosen breakpoint (needs a small
JS toggle handler in addition to CSS — this is the part of this item that touches
`app.js`, not just `app.css`), or (b) a `flex-wrap: wrap` layout with the row
allowed to become two rows below the breakpoint. Prefer whichever the executing
agent judges least disruptive to the existing visual design; either fully resolves
both the P0 (375px) and P1 (1024/768/601px) with one change. **Acceptance:** at each
of 1400/1024/768/601/375px, `document.documentElement.scrollWidth` does not exceed
`clientWidth` (small rounding tolerance fine), and all four controls are reachable
by on-screen interaction alone.

---

### Phase 3 — Analysis-tab subsystem (`app.js`, sequential + mandatory skeptic, `Workflow` call #3)

The single most architecturally delicate change in this brief — it reorders part of
the app's own boot sequence, which runs on every single page load for every user.
One agent, strictly sequential (boot-race fix first, fully verified, before the two
smaller companion fixes), followed by a mandatory adversarial skeptic pass before
this phase's PR ships.

**Boot-race (`analysis-boot-race-destroys-tab-workspace`, P1) — do this one first, alone, and verify it fully before touching the other two.**
Verified root cause: `let _anTabs = []` at `src/static/app.js:15293`; the
`_hydrateCardCorpus()` IIFE (starting right after `showTab(...)` near line 17461)
runs FIRST at boot and, for a `?analyze=`/`?corpus=` deep link, calls
`openAnalysisForIds`/`openAnalysisFor` → `_anSpawn` → `_anActivate` →
`_anSaveTabs()`, which **overwrites** `localStorage['oo.an.tabs.v1']` with only the
just-spawned tab; `_anRestoreTabs()` (the function that would load the PREVIOUSLY
persisted tabs) is called only afterward, at the very end of the same boot block —
by which point localStorage has already been clobbered. **Fix:** call
`_anRestoreTabs()` FIRST (restore whatever tabs were already persisted), THEN run
`_hydrateCardCorpus()`'s spawn logic, so the deep-linked seed is ADDED to the
restored set (via `_anSpawn`'s existing dedup-by-`key` logic, confirmed present at
`src/static/app.js:15368`) instead of clobbering it. **Acceptance:** open the
omnibar in 3 successive new browser tabs with 3 different queries; the 3rd tab's
tab-strip shows all 3 as coexisting named tabs (soft cap 10). **After this specific
fix, before touching anything else in this phase: re-verify with the exact repro
above, then run the mandatory skeptic pass** (negative-space: does closing the
middle tab still work; does a normal single-query open still land on exactly one
tab; does a corrupted/malformed `localStorage['oo.an.tabs.v1']` degrade gracefully
rather than throwing during boot).

**Then, same agent, same file:**
- `dblclick-opens-duplicate-analysis-tabs` (P1) — debounce `openCardCorpusQuery`/
  `openAnalysisInNewTab`'s `window.open` call (an in-flight guard keyed on the exact
  URL, cleared after a short timeout). Acceptance: a scripted double-click
  (≤50ms apart) produces exactly one new tab.
- `an-mindmap-wrong-corpus-scope` (P1) — verified: `loadAnalysis()`'s Mindmap
  handling (~`src/static/app.js:16213-16230`) picks `top = dk.terms[0].term` (the
  top keyword of the already-correctly-scoped corpus-keywords call) then builds a
  SEPARATE `gp` params object carrying only `level/term/hops/(days,start,end)` —
  dropping the query/source/language/article-id scope entirely — before calling
  `/api/insights/graph`, the CORPUS-WIDE keyword-graph endpoint, instead of the
  `article_ids=`-scoped variant the standalone reader's own Mindmap tab already
  uses correctly. **Fix:** thread the SAME scope params (`article_ids` when the
  corpus is id-seeded, else `q`/`src`/`lang`) that every sibling subtab already
  passes, into the `/api/insights/graph` call. Acceptance: `?analyze=election` on an
  all-English 26-article corpus renders a Mindmap whose terms are actually drawn
  from that corpus (no cross-language terms that cannot exist in it).

---

### Phase 4 — Settings/theme integrity (`app.js`, sequential, `Workflow` call #4)

**`theme-select-lossy-overwrite` (P1).** Verified precisely (see §3.1's correction):
`saveSettings()` (`src/static/app.js:4959`, the unconditional call at line 4969)
runs `setTheme({dark:"ink", light:"light", system:"system"}[$("set-theme").value]
|| "ink")` on EVERY Save click, collapsing any of the 17 named themes down to one
of exactly 3 buckets. **`loadSettings()`'s structurally similar call at line 4840
is CORRECTLY guarded (`if (!localStorage.getItem(UI_KEY))`) and must NOT be
touched** — it is intentional first-run seeding, not the bug. **Fix (pick one,
justify the choice in the PR description):** (a) — preferred, simpler, removes the
two-controls-for-one-setting inconsistency the finding's own CONSISTENCY framing
flags — make `saveSettings()` skip the `setTheme(...)` call entirely unless the
General panel's `#set-theme` select value has actually changed since it was last
synced (compare against what `syncThemeSelect()` would currently compute, storing
that as a baseline before Save runs); or (b) extend the General panel's select to a
full 17/18-way choice, removing the lossy bucketing outright. **Acceptance:** pick
"Midnight" in Graphics → save unrelated preferences in General → Midnight is still
active afterward.

---

### Phase 5 — Global shared infrastructure (`app.js`, sequential + mandatory skeptic, `Workflow` call #5)

Two small, high-leverage fixes to code paths used by nearly every surface in the
app. Small diffs, outsized blast radius — treat with the same care as Phase 3.

**`imp-ghost-modal-after-back` (P1).** Verified: no `popstate` listener anywhere
closes an open `<dialog>`. Browser Back while `#ux-export` (or any other
`<dialog>`) is open leaves the tab underneath repainted (Home, say) while the
dialog's native modal top-layer backdrop stays active, blocking every click with no
visual cue; only Escape recovers. **Fix:** one global `popstate` listener,
`document.querySelectorAll('dialog[open]').forEach(d => d.close())`, added once at
the app's top level. **Verify the breadth explicitly** — this should fix EVERY
`<dialog>` in the app via the shared native mechanism, not just `#ux-export`; test
at least `#ux-export` and one other dialog (e.g. `#chart-enlarge`) to confirm.
**Acceptance:** open the Export dialog → browser Back → the dialog is closed (not
just hidden) and every other UI control is immediately clickable, no Escape needed.

**`ins-convergence-window-cap-mismatch` — the `api()` half only (P1; the `<select>`
max-attribute half is in Phase 8b).** Verified: `src/static/app.js:1312`,
`if (!res.ok) throw new Error((data && data.detail) || res.status + " " +
res.statusText);` — this is the SHARED error path for essentially every call made
through the `api()` wrapper. A FastAPI/Pydantic 422 body's `detail` is an ARRAY of
`{type, loc, msg}` objects, which `Error()` string-coerces into `[object Object]`.
**Fix:** when `data.detail` is an Array, join its `.msg` fields (falling back to
`JSON.stringify` per item if `.msg` is missing) into one readable string before
passing it to `Error(...)`; otherwise keep today's behavior byte-identical (a
string `detail`, or no `detail`, must render exactly as before). **This fixes the
error-message half of the Convergence finding AND every other endpoint with a
similar validation constraint — do not scope the fix narrowly to Convergence.**
**Mandatory skeptic pass:** confirm the existing non-array `data.detail` string
path (used everywhere else in the app) is completely unaffected — a regression here
would silently corrupt error messages app-wide.

---

### Phase 6 — i18n reactivity cluster (parallel across 3 disjoint files, `Workflow` call #6)

**6a — `src/static/app.js` (sequential within this one agent, two findings):**
- `home-lead-title-frozen-locale` (P1) — verified: `app.js:17259`'s `'oo:langchange'`
  listener re-renders the world map/sources table/airplane-button title/AI-prompt
  editor on a language switch, but never calls `renderBriefing()`/
  `renderCorpusTier()` — so any `OOI18N.tf()`-built Home Lead-card title stays frozen
  in whatever locale was active when it last rendered. **Fix:** add the missing
  `renderBriefing()` (and `renderCorpusTier()` if it independently builds
  locale-dependent text) call to that listener.
- `insights-landscape-headers-hardcoded` (P1) — verified: `_KIND_GROUPS` in
  `app.js:9454-9460` builds `label:"Themes"`/`"Other entities"`/`"People"`/
  `"Orgs"`/`"Places"` and injects `${g.label}` with no `t()` wrapper anywhere in
  `loadLandscape()`. **Fix:** wrap each label in `t()` (or `esc(t(...))` matching
  the surrounding code's escaping convention).

**6b — `src/static/i18n.js` (independent agent, disjoint file):**
`home-i18n-mixed-language-glance` (P1) — verified root cause: the DOM-walker caches
each text node's first-seen value in a `WeakMap` as "the original English" via
`doText()`/`apply()`; `renderHomeStats()` rebuilds `#home-stats` directly via `t()`
calls (correctly, for whatever language is active at that instant), but if the
debounced `MutationObserver`'s own `apply()` pass fires AFTER a non-English render,
it caches THAT non-English string as the node's "original" — permanently poisoning
future lookups for that node (an Arabic map keyed by English source strings never
matches a French one). **Fix:** the cache must only ever store the TRUE original
English source string — either seed it eagerly at a point guaranteed to be
pre-translation, or exclude/re-derive nodes that `renderHomeStats()` (and similarly
data-driven renderers) directly control, rather than relying on "first `apply()`
pass wins."

**6c — `src/static/locales/*.json` (independent agent, disjoint files, all 12):**
`hazard-caveat-untranslated` (P1) — verified: the Home hazard-lens disclosure box's
long explanatory paragraph ("This layer never invents urgency. 'Urgent' appears
ONLY when...") has **zero matching key** in `ar.json`/`fr.json`/`de.json`/
`es.json`/`zh.json`/`ja.json` (confirmed 0/6 hit on the exact English source
string) — only the short headline is translated. **Fix:** add the missing key +
value across all 12 locale files (AI-drafted non-English translations, flagged for
native review per the project's own standing convention).

`parallel([fix6a, fix6b, fix6c])` — three genuinely disjoint file sets.

---

### Phase 7 — Accessibility/contrast cluster (`app.css` sequential + `app.js` parallel, `Workflow` call #7)

**7a — `src/static/app.css` (one agent, sequential, three findings — pure CSS, low
collision risk, do as one cohesive contrast pass so cross-effects across the three
are caught together rather than three separate uncoordinated edits):**
- `pillwarn-severe-contrast` (P1 half; the merged finding's P2 half — borderline
  themes — rides along since it's the same variable) — verified: `--warn` is
  defined per-theme (e.g. `:root`'s base `--warn:#d9a441`; `dawn`'s
  `--warn:#ea9d34`, line 69; similarly for `mint`/`solar`/etc.) and used directly as
  BOTH an accent color and `.pill.warn`'s text color; measured 1.87–2.42:1 contrast
  in Dawn/Paper/Solar (all badly below WCAG AA 4.5:1), 3.3–3.5:1 in
  Light/System/Mist/Mint (still below 4.5:1). **Fix:** apply the exact SAME pattern
  already proven for `var(--caveat)` (invariant #23's fix, which verified 6.29–
  10.5:1 across all 18 themes) to `--warn` — either recompute each theme's `--warn`
  value to clear 4.5:1 against `.pill.warn`'s actual background, or introduce a
  distinct `--warn-fg` used specifically for pill TEXT (keeping `--warn` itself for
  non-text uses like borders/accents where the contrast bar doesn't apply). Verify
  across all 18 themes, not just the 7 currently known to fail.
- `chip-button-color-contrast` (P1) — white text (`#ffffff`) on the accent-blue
  chip/button background measures 2.88:1 (Home channel chips, card "Open corpus ↗"
  buttons, Settings Graphics density buttons); nested count numbers hit 1.04:1.
  **Fix:** raise foreground/background contrast on this shared color pair to
  ≥4.5:1, verified across all 18 themes.
- `evidence-links-contrast-and-no-underline` (P1) — sourced-article links render at
  2.41:1 with no underline (axe: `link-in-text-block`, 24 nodes). **Fix:** add an
  underline (or a sufficiently distinct, ≥3:1-contrast color) to these links, since
  color alone is insufficient per WCAG 1.4.1.

**7b — `src/static/app.js` (independent agent, disjoint work — card MARKUP, not
CSS):**
`lead-card-nested-interactive` (P1) — verified: the Home Lead-card flip container is
`role="button" tabindex="0"` (e.g. `onclick="leadFlip(this,event)"
onkeydown="leadFlipKey(this,event)"`) while ALSO containing genuinely interactive
descendants (links/buttons) once flipped — axe flags `nested-interactive` on 23
nodes. **Fix:** restructure so the outer container is not itself a focusable
interactive role while also hosting nested interactive children — e.g. change the
outer container to `role="group"` and make the flip-trigger a distinct, explicitly-
scoped inner control, or otherwise ensure the flip affordance and the nested
links/buttons are not both independently-focusable within one ARIA interactive
role.

`parallel([fix7a, fix7b])` — CSS-only file vs. markup/behavior in a different file.

---

### Phase 8 — Backend + remaining frontend tail (parallel across Python vs. static/, `Workflow` call #8)

**8a — Backend (Python), independent agent:**
- `home-opencorpus-recipe-promise-seed` (P1) — verified: the `recipe_promise`
  producer (find it in `src/briefing/producers.py`; `rising_now` is confirmed at
  line 193 as the established precedent to match, not the producer itself — locate
  `recipe_promise`'s own `Card(...)` construction) seeds `openCardCorpusQuery` with
  a literal colon-joined internal string (`"429:2026-07-20"`), which re-runs a
  full-text search for text no article contains, instead of carrying an explicit
  `article_ids=[...]` — exactly the bug class already fixed for
  `lonely_signal`/`story_lineage`/`ownership_change` per this project's own
  2026-06-16 precedent. **Fix:** add `article_ids=` to `recipe_promise`'s `Card(...)`
  call, matching that established pattern exactly (read one of the already-fixed
  producers first, don't reinvent the convention).
- `governments-law-pointer-misleading-zero-tracked` (P1, backend half) —
  **investigate first, per §3.1**: `src/law/coverage.py:53`'s `tracked = len(rows)`
  is the non-baseline-filtered count the Law subtab correctly uses (its own
  in-source "completeness principle" comment is worth reading in full, `coverage.py`
  lines 8–19). Confirm whether the pointer's data source (traced from
  `src/static/app.js:4086-4091`, its OWN separate `s.tracked` field) can be pointed
  at this same `coverage.py`-backed value, or whether a genuinely different backend
  field needs adding. **Prefer showing BOTH numbers** ("23 tracked · 0 baselined")
  over collapsing to one word if the two concepts are legitimately distinct —
  that's the more honest fix per the finding's own framing.

**8b — Frontend (`src/static/app.js` + `src/static/index.html`), one agent,
sequential within itself (same-file discipline), five findings + the frontend half
of the law pointer:**
- `governments-law-pointer-misleading-zero-tracked` — the small `app.js:4086-4091`
  text/data-binding change, once 8a's investigation resolves what to bind it to.
- `ins-convergence-window-cap-mismatch` — the `<select>` `max` attribute half
  (`#cv-window` in `index.html`): lower `max="3650"` to `max="90"` to match the
  backend's real `le=90` cap (`src/api/insights.py`'s convergence endpoint), so the
  input never invites a value the backend will reject. (The `api()` error-message
  half already shipped in Phase 5.)
- `ins-kind-filter-nonfunctional-options` (P1) — verified: the Trends/Map `#trd-kind`
  select still lists `people`/`orgs`/`places`, which the extractor never assigns
  (confirmed: `GET /api/insights/map?kind=person` returns honestly-empty
  `{countries:[], cities:[]}` while `kind=""` on the identical corpus/window returns
  9 populated rows), while the sibling Families subtab's own `#fam-kind` select
  correctly restricts itself and shows an explicit honesty hint explaining why.
  **Fix:** either remove the non-functional options from Trends'/Map's kind
  selects, or add the same kind of honest "not yet populated by the extractor" hint
  Families already shows, matching that established pattern.
- `home-recent-panel-hidden-on-error` (P1) — verified: `loadHomeRecentList()`'s
  `catch(e)` branch sets an honest error message into the panel's inner box but
  never clears the panel's own `hidden` attribute (the static markup starts
  `<section ... id="home-recent-panel" hidden>`, and only the two SUCCESS paths
  toggle it visible). **Fix:** set `panel.hidden = false` in the catch branch too.
- `mkt-002-stale-caveat-scale-toggle` (P1) — verified: the Commodities enlarge
  dialog's dynamic scale hint updates correctly on the Absolute/Log toggle, but a
  SEPARATE static caption (`#chart-enlarge-note`, set once at dialog-open time from
  the family's own `cavText` and never refreshed by the toggle's click handler)
  permanently states "Indexed to 100 at the window start," directly contradicting
  the dynamic hint a few lines above it. **Fix:** refresh `#chart-enlarge-note`'s
  text in the same click handler that updates the dynamic hint.
- `worldmap-fullscreen-hides-legend-caveat` (P1) — per §3.1's flagged investigation:
  read `host.innerHTML`'s full template literal (`src/static/app.js:13142` onward)
  to confirm whether `.oomap-legend` (line 13159) is a DOM child or sibling of
  `.oomap-wrap` (the current `requestFullscreen()` target, lines 13242-13246).
  **Preferred fix, per the evidence:** change the fullscreen target to the wider
  container (`host`, or whatever element already wraps both `.oomap-wrap` and
  `.oomap-legend`) rather than the narrower `.oomap-wrap` div — verify this does not
  break the map's own internal sizing logic (which may assume `.oomap-wrap` is the
  fullscreen root) before committing to it; if it does, move the legend/caveat/
  dimension-controls markup to be true children of `.oomap-wrap` instead.
- `help-md-linebreak-bug` (P1) — verified conceptually from the report (locate the
  exact `mdToHtml()` function in `src/static/app.js` before fixing — not yet
  grep-confirmed by this brief's own pass, flagged honestly): the markdown
  renderer's paragraph/blockquote handling calls its inline-emphasis formatter
  PER RAW SOURCE LINE (`buf.map(inline).join(' ')`) before joining lines together,
  so a `**bold**` span whose opening `**` and closing `**` land on different
  wrapped source lines is invisible to the per-line regex on both lines, and can
  cause a LATER, unrelated `**` pair on the second line to mis-pair with the
  dangling first `**` — producing garbled, wrongly-placed `<strong>` tags (reported
  in both `docs/USER_MANUAL.md` and the Ethics doc, ~64 unrendered spans). **Fix:**
  join the raw source lines into one string PER PARAGRAPH/BLOCKQUOTE BEFORE running
  the inline-emphasis formatter, not after — so a span crossing a source line break
  is seen as one contiguous string by the regex.

`parallel([fix8a, fix8b])` inside this one `Workflow` call.

---

## 6. Note on the phases above vs. earlier §1 counts

Phases 1–8 cover: 5/5 P0s, 22 of 24 P1s directly, plus `ins-map-cjk-sentence-
keywords` explicitly deferred (§1.4) and `netcoach-blocks-lang-switch` +
`topbar-overflow-mainstream-widths` merged one-for-one with their P0 siblings in
Phase 2 (still counted as distinct rows in the closeout, per §1.1's own counting
discipline) — 23 of 24 P1s addressed, 1 deferred. The two bonus items (§1.1.3) ride
in Phases 1a/1b.

---

## 7. Optional stretch — only after every mandatory item above is shipped and verified

If time/budget remains, the existing combined brief's own P2 shortlist is still the
recommended order (unchanged, not re-verified in depth by this brief — spot-check
before starting any of these): `mkt-004-feed-verdicts-never-shown` (dead code, wire
or remove), `diag-multi-download-buttons` (6 stray buttons the one-button-bundle
ruling should have removed), `sf-ollama-hidden` (Storage footprint should show an
honest "unavailable" row instead of silently omitting the Ollama store),
`mkt-003-compare-feature-unreachable` (a built, unreachable feature), `leads-
carousel-ignores-reduced-motion` (respect `prefers-reduced-motion` in the
carousel's JS timer). **Never claim the whole P2/OPT tier was addressed — this is a
5-item optional shortlist out of 43 remaining rows.**

---

## 8. House verification protocol (exact commands — freshly re-confirmed against `.github/workflows/ci.yml` at this brief's authoring; re-check if it drifted)

```bash
# Blocking correctness lint (F = pyflakes, B = bugbear)
ruff check --select=F,B --extend-ignore=B008 src/ tests/

# Full style lint (advisory in CI, worth running clean anyway)
ruff check src/ tests/

# i18n completeness gate (only relevant if a fix adds/changes a locale key)
python scripts/i18n_report.py --min 100

# Full test suite
python -m pytest -q

# Type-check ratchet — MYPY_BASELINE is "127" as of this brief (ci.yml line 139);
# re-check that env var yourself before trusting this number
count=$(python -m mypy src/ 2>/dev/null | grep -c " error: "); echo "$count vs 127"

# Security (blocking in the weekly-audit lane; pinned version matters)
python -m pip install bandit==1.9.4
bandit -r src/ -ll -q
```

`make check` (= `ruff check src/ tests/` + `python -m pytest -q`) is a quick local
convenience target but does NOT run the full gate set above — run the explicit
commands before pushing.

**Any fix touching `src/static/app.js`'s boot sequence (Phase 3) or its shared
`api()`/global-listener infrastructure (Phase 5) gets the mandatory skeptic pass
per §2 Rule C — this is not optional for those two phases.**

---

## 9. PR and ledger discipline

One PR per phase (or per clearly-separable finding within a phase where the diffs
are unrelated enough that splitting is cleaner — use judgment, default to the
phase-level grouping given above), draft onto `main`, each PR description citing
the exact finding id(s) from `findings.csv` it addresses. A `docs/ledger/
shipped.csv` row per shipped slice, per the house append-rule. A `CLAUDE.md`
Lessons bullet only if a fix surfaces a genuinely reusable lesson (the `_placeCoach()`
vertical-clamp root cause in §3.1, and the shared `api()` error-array fix in Phase
5, both look like strong candidates if built).

## 10. Definition of done

- All 5 P0s fixed, each re-verified against its ORIGINAL repro, each its own PR.
- 22–23 of the 24 P1s fixed per the phase plan above (`ins-map-cjk-sentence-
  keywords` deferred by design, §1.4) — or, if the session's time budget runs out
  before every phase completes, an honest closeout stating EXACTLY which phases
  shipped and which did not, never a blanket "done."
- Every shipped fix carries a durable regression test (§4.4) and passed the house
  verification protocol (§8).
- Phases 3 and 5 specifically carry documented skeptic-pass results in their PR
  descriptions (not just "tests pass").
- A closeout note (fresh `CLAUDE.md` Open-queue entry, or this brief's own status
  line) stating plainly what was built vs. what's left, including the full P2/OPT
  tier remaining open (expected) and `ins-map-cjk-sentence-keywords` remaining
  deferred (expected, by design) — never claim more than what's actually shipped
  and independently re-verified.
