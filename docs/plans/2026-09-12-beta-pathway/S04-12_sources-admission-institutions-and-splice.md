# S04-12 — Sources: admission, identity, the institutions docket, the splice · 0.4, `RELEASE_0.4_GATE.md` row S

> **Scope:** `src/catalog/qualification.py` (`evaluate_and_stamp`, `select_unqualified`,
> `advance_qualification`, `trial_fetch`), the `scrape_unqualified` hatch (`src/scheduler/settings.py` /
> `runner.py`, `src/api/scheduler.py`, `src/api/source_management.py`), the headline counts
> (`src/api/database.py` and every surface showing one), a Settings overlay editor over
> `src/catalog/qualification_overlay.py`, `configs/official_sources.yml` /
> `academic_sources.yml`, `src/scheduler/runner.py::stratified_interleave`, the splice tooling under
> `docs/research/sources/discovered_candidates_2026-09-10/` + `scripts/analysis/scan_content_integrity.py`.
> NOT: feed-keyed sources (Q1102, 0.5), the stoplist (Q1103 / Q1104 CONFLICT, row M), the embassy platforms
> (Q1113 ⛔), publishing or contacting anyone about a compromised host, auto-applying any proposal.
> **Implements:** Q1101 ⛔ = a, Q1105, Q1106, Q1107, Q1108, Q1109 (b + note), Q1110, Q1111, Q1112, Q1113 ⛔
> (PENDING — stop at the seam), Q1114, Q1115, Q1116, Q1117, Q1118, Q1119, Q1156.
> **Gated on:** the flip (S1) needs the audit view + UNDO it relies on (absent today — built first); the
> shortlist run needs the maintainer's machine or row V's allowlist; the splice needs the report reviewed.
> **Sequencing:** S1 before S2's counts; the splice after S1 so admitted rows enter through the ruled gate;
> the shortlist run after the splice review (Q1118).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§12, with the `OPEN_QUEUE.md` entry "2026-09-11 — THE OPEN DOCKET after the
institutions pass" as its context). Grep the tree before building anything — the sheet's anchors were verified
at `main`@`bebcef4` on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1101** ⛔ — **(a)** «A `qualified` verdict flips `enabled=True`» (the sheet's full option: «(qualification
  IS the admission gate; the per-pass hardware budget bounds Tor use; the audit view's undo is the safety
  valve) and the hatch is retired.»)
- **Q1105** — **(a)** «A worklist for a review surface; never auto-applied.»
- **Q1106** — **(a)** «Ship the overlay editor (adopt / export / revert) in Settings.»
- **Q1107** — **(a)** «Keep 0.5, record it as unreachable, let the measured criteria decide.»
- **Q1108** — **(a)** «The 6-month re-verification reads the last 6 months, not the whole history.»
- **Q1109** — **(b)** «`academic_sources.yml`.» — NOTE (verbatim): «we should develop a strategy to
  comprehensively increase the list»
- **Q1110** — **(a)** «Defer-not-reject now; rewrite the axis as an observable ("publishes dated official
  instruments?") checkable against headlines.»
- **Q1111** — **(a)** «Move them to `academic_sources.yml`.»
- **Q1112** — **(b)** «Flag at admission: a candidate tripping `restricted_namespace` cannot be spliced without
  a written override; never a silent drop.»
- **Q1113** ⛔ — [PENDING — blank on a ⛔; STOP at the seam] «The compromised embassy platforms (institutions
  B5)»: no letter, no note. Nothing is defaulted.
- **Q1114** — **(a)** «`enabled AND qualified` everywhere a headline count is shown; the other predicates are
  labelled where they appear.»
- **Q1115** — **(a)** «A diagnostic proposes corrections for review; never an automatic ccTLD rule.»
- **Q1116** — **(a)** «Resolve the label at the polite rate or decline to admit the row.»
- **Q1117** — **(a)** «Admit them, tagged with the vendor path so a supplier outage is one visible cause; the
  balance shift disclosed in the splice report.»
- **Q1118** — **(a)** «Run the shortlist (3,031) next; the remainder and the religious lists after the splice
  is reviewed.» [operator/session run]
- **Q1119** — **(a)** «Admit the rows where both judges agree; defer the ~15% contested band.»
- **Q1156** — **(a)** «Keep the stratified round-robin (the ruled equilibrium lever) and randomise the order
  of the singleton strata across passes.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- The hatch: `scrape_unqualified` at `src/scheduler/settings.py:125–132` (its comment: it "RELAXES a maintainer
  ruling"), `:346`, `:390–392`; read at `src/scheduler/runner.py:421–441`; exposed at `src/api/scheduler.py:71`
  and `src/api/source_management.py:1688` — grep-verified. Sheet (VERIFIED): ~42 k disabled candidates are
  trial-fetched over Tor for a verdict with no collection effect.
- The functions: `trial_fetch` `src/catalog/qualification.py:230`, `select_unqualified` `:255` (the register
  said `:231` — moved), `evaluate_and_stamp` `:587` (writes only `status`), `advance_qualification` `:897`;
  `PATHOLOGY_ABS_FLOOR` `:42` / `:154`, surfaced at `source_management.py:1606,1632`; the ladder caps at 6
  months (`:28`, `:159–162`). **The audit view's UNDO is absent** — `grep -n -i "undo"
  src/api/source_management.py` returns nothing; the register (B1) expected PROMPT_04 to build it.
- The overlay: `src/catalog/qualification_overlay.py:65` sets `DEFAULT_OVERLAY_PATH` to
  `configs/source_qualification.yml`; the file is NOT in the tree (generated per instance; a session never
  writes verdicts — register B5); the export is `src/catalog/qualification_export.py`. The counts:
  `src/api/database.py:109–144` documents
  `sources_qualified` = enabled AND status=qualified, `sources_pending`, `sources_candidates`; docket C3 names
  the three OTHER predicates (`/api/scheduler/targets.total_enabled`, `/api/sources/qualification/config
  counts.qualified`, `/api/scheduler/coverage totals.total`) — grep-verified.
- `kind_overrides`: `propose_kind_overrides` in `src/ai_layer/triage.py` is a GENERATOR; no file holds the
  64,910 (register B4). `restricted_namespace`: `scripts/analysis/scan_content_integrity.py` +
  `tests/test_content_integrity_scan.py` (three legitimate outlets pinned as a negative control); the tier is
  10-for-10, eight hits are `embajada.gob.ve` subdomains, `lexicon` is ~0.6 precise. The moves:
  `configs/official_sources.yml` carries 16 `research-institute` / `academic-research` rows (16 / 16). The
  round-robin: `stratified_interleave` at `src/scheduler/runner.py:280`; the 2026-09-10 ruling SHIPPED a
  uniform draw among live languages at every step (`OPEN_QUEUE.md` ~13300–13365; sources leading every pass
  21 → 0, inter-instance head overlap 33 % → 39.5 %), pinned by `tests/test_stratified_interleave.py`.
- **The shortlist figure:** `shortlist.csv` has 3,588 rows; `stage_a/STAGE_A_RESULTS.md` records "shortlist …
  3588 of 3588 candidates judged, 643 feeds verified" with the 2026-09-10 kit; `OPEN_QUEUE.md` (~13489)
  derives "w1 3,588 -> 3,031" as the REBUILT kit's worklist after dedup against every shipped catalogue —
  "the shortlist (3,031)" names that deduped worklist, not an unjudged population. Stage B (docket A0): 1,200
  paired rows, kind agreement 97.2 %, `primary_source` 84.7 %, a 15.3 % contested band; C9: 116 of 267
  second-pass rows are Czech municipalities, 42 share `/uredni-deska?action=atom`; C8: 26 of 267 carry a bare
  Q-id as their name; C7: `cityofvancouver.us` with `country: ca`.

## 3. Slices — what to build, in order

### S1 — The flip and the hatch retirement (Q1101 ⛔ = a — data safety: full skeptic matrix)
- **What:** the audit view + UNDO first (a reversible record of every automatic `enabled` flip, ×12); then
  `evaluate_and_stamp` sets `enabled=True` on a `qualified` verdict and on nothing else; `scrape_unqualified`
  removed from settings, runner, API and UI with a migration that drops the persisted value and discloses it
  once; the per-pass hardware budget (`machine_floor`) stays the bound on Tor use. Negative space:
  `disqualified` never enables; a never-judged / `unqualified` stamp never enables (the 2026-07-24 inversion
  class PROMPT_07 §S5 records); an undo restores the prior `enabled` AND status. **Acceptance:** the
  data-safety review and tests (gate); mutation-checked.

### S2 — THE number, and the overlay editor (Q1114, Q1106)
- **What:** `enabled AND qualified` on every headline count; each other predicate labelled where it appears
  (the coverage panel's "sources collection will never touch" said as such); a test per surface reads the
  SHIPPED predicate. The overlay editor: adopt / export / revert over the per-instance overlay through the
  existing loader and export; the file stays operator-generated; ×12, caveats visible. **Acceptance:** one
  count per surface proven by test (gate); the editor Chromium-verified.

### S3 — The small rulings (Q1105, Q1107, Q1108, Q1110, Q1115, Q1116, Q1156)
- **What:** Q1105 — the generator's proposals rendered as a review worklist, never applied; Q1107 — 0.5 kept,
  the panel says "unreachable in the field"; Q1108 — the re-verification reads the last 6 months (touches
  `collect_article_stats`, shared with the audit report — published beside, never replacing, the whole-history
  verdict); Q1110 — `primary_source` deferred-not-rejected and rewritten as the observable "publishes dated
  official instruments?" checked against headlines; Q1115 — a diagnostic proposing corrections, no ccTLD
  rule; Q1116 — bare Q-id names resolved at the polite rate (R8: ≤ 1 request / 10 s, under the one consent,
  refused under the kill switch by name) or the row declined; Q1156 — measure the shipped draw against
  "singleton strata order randomised across passes"; if already true, record VERIFIED-PRESENT with the test;
  if not, add the per-pass offset and re-measure with the same thirty-pass method. **Acceptance:** a
  behavioural test each; every new string ×12.

### S4 — The moves, the growth strategy, the splice, the next runs (Q1109, Q1111, Q1119, Q1117, Q1112, Q1118)
- **What:** research institutes and the 16 mis-shelved journals moved to `academic_sources.yml` as catalogue
  diffs, plus a WRITTEN strategy for growing that list comprehensively (the note asks for it; it decides
  nothing). The splice: admit the rows where both judges agree; defer the ~15 % band (defer ≠ reject); Czech
  municipalities admitted, tagged with the vendor path; a `restricted_namespace` trip blocks the splice absent
  a written override, never a silent drop; bare Q-ids resolved or declined; the SPLICE REPORT with agree /
  defer counts and the balance shift; then the shortlist (3,031) run, the remainder and religious lists after
  the review. Q1113 ⛔: the flagged hosts stay excluded by the existing flag, nothing is published, nobody is
  contacted — today's state, not a decision. **Acceptance:** the diffs land; the report exists (gate).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (470 / 231 today); `node --check` on touched script blocks; the three i18n gates for every new
string; the whole-tree guard set; the full skeptic matrix on S1 and the catalogue moves; mutation-check every
guard by name; the consent fixture for Q1116 (engage airplane mode first, assert the NAMED refusal);
`tests/test_stratified_interleave.py` + the thirty-pass measurement for Q1156; the Chromium click-through
record (Q1128 = a) of the overlay editor, the audit view + undo, the worklist and every headline count in
en / fr / ar; the `shipped.csv` numstat + duplicate scan.

## 5. Operator steps

1. Review the splice report (agree / defer counts, the Czech balance shift, the `restricted_namespace` flags)
   and give any written overrides — the report is the artifact.
2. Run the shortlist (3,031) with the rebuilt kit on the maintainer's machine (or the sandbox once row V's
   allowlist lands); return the results; `not-measurable-here` until then. The remainder and religious lists
   follow the splice review.
3. The click-through of the four surfaces (Q1128 = a).
4. **Q1113 ⛔** — the ruling, recorded in `OPEN_QUEUE.md` and `RULINGS_INDEX.md` in the turn it is given.

## 6. What this slice may not decide

- **Q1113 ⛔** — exclusion / publication / disclosure; nothing changes and nothing is said.
- **Q1102** (feed-keyed identity, *proposed placement* 0.5) — the splice stays domain-keyed. **Q1103 / Q1104**
  (the stoplist CONFLICT) — row M's.
- **Which kit and population** "the shortlist (3,031)" names — the run's report states it; a 3,588-row judged
  list and a 3,031-row deduped worklist are different facts.
- **Whether the `primary_source` observable becomes a future splice gate** — built as a proposal surface;
  **the growth strategy** (Q1109 note) is a document, not a catalogue change.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
