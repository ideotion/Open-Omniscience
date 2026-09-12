# Roadmap answer sheet 2026-09-12 — every decision the beta pathway needs, in one file

**Status: ANSWER SHEET — UNANSWERED.** Written 2026-09-12 at the maintainer's request:
*"produce a longer list of questions, go into much more details, add a tiny impact analysis and
explanation for each choice, all in markdown format, so I may read everything autonomously and mark
answers inside the markdown file … a single, extensive markdown file that I'll send back to you in this
session … Make sure everything we decide now counts and is accounted for, so that we don't have to
restate anything in the future."*

This file **supersedes §6 of
[`ROADMAP_INTAKE_2026-09-12_BETA_PATHWAY.md`](ROADMAP_INTAKE_2026-09-12_BETA_PATHWAY.md)** (its Q1–Q70 are
folded in here under new IDs; the old numbers are cited as `(was Q13)` so nothing is lost) and it folds
in **every still-open ruling from the docket** — the 2026-09-06 question register, the 2026-09-08 visual
audit, the 2026-09-11 institutions docket, the storage round-2 rulings — so that one answered file
closes the whole open queue as far as rulings go. Where a question was already ruled by the maintainer's
messages of 2026-09-12, it is **pre-filled** in §1 and needs only a confirmation.

Nothing here is built. Nothing here decides anything: the maintainer decides; the file records.

---

## §0 How to use this file

### §0.1 For the maintainer — how to answer

Every question ends with a line that reads `ANSWER Qnnn:`. Type the letter of the option you choose after
the colon. Everything below is accepted:

| You write | It means |
|---|---|
| `ANSWER Q101: a` | option (a) |
| `ANSWER Q101: a, c` | several options (only where the question says *multi-select*) |
| `ANSWER Q101: a — but only after 0.5` | option (a) plus a note; anything after the dash is recorded verbatim beside the ruling |
| `ANSWER Q101: x — <your own answer>` | none of the options; your text is the ruling |
| `ANSWER Q101: later` | you decline to decide now; the question stays PENDING in the docket, nothing is assumed |
| `a #### Q101 · …` | the letter typed at the very start of the question's heading line — exactly as you proposed; read the same as the ANSWER line |
| left blank | the **default** stated under the question is taken and recorded as an **ASSUMPTION** (revisitable, never called a ruling) — **except** for questions marked ⛔, which stay PENDING when blank and are never defaulted |
| `NOTE: …` on its own line under a question | free text, recorded verbatim |

Markers: **⛔** = irreversible, outward-facing or data-safety; never taken autonomously. **🔒** =
reversible but changes what the app retains or contacts; must be explicit. **★ recommended** marks the
option the writer would take. *Effort* is S (one session), M (two to four), L (a release slice), XL
(spans releases). *Risk* is about data, ethics or reversibility, not about difficulty.

You do not have to answer everything. Answer what you care about; `later` the rest; leave blanks where
the default is fine. **§1 needs one answer** (Q001) unless you want to change a recorded ruling.

### §0.2 For the session that receives this file back — the processing protocol

The maintainer said the returning session's context *"will be significantly compressed and the session's
memory will become quite untrustworthy."* Therefore this file is written to be processed **without any
memory of this session**. Do exactly this, in order:

1. **Protocol first.** Read `CLAUDE.md` and `docs/ledger/LESSONS.md` in full; open `docs/ledger/OPEN_QUEUE.md`
   and read its top entry (`ROADMAP INTAKE 2026-09-12 …`) and the entry this file's ledger row points to.
   Read this file in full — §0.2, then §1, then every section — before writing anything.
2. **Extract the answers mechanically.** For every `#### Qnnn` heading: the answer is the text after
   `ANSWER Qnnn:`; if that is empty, a letter at the very start of the heading line counts; `NOTE:` lines
   under the question are notes. Build one table `id · answer · note · source (answered | default |
   pending)`. Blank + ⛔ → `pending`. Blank + not ⛔ → the stated default, `source=default`. `later` → `pending`.
3. **Check consistency before recording.** The `Depends on:` lines name the couplings. Where two answers
   contradict (for example Q301 = display-only but Q305 = rewrite the configs), do **not** pick a winner:
   list every contradiction in the reply and record both answers as given with a `CONFLICT` flag.
4. **Record, in the same turn, per THE PROTOCOL:** (a) commit the answered file itself, in place, as the
   primary record (its answers are the rulings); (b) prepend ONE entry to `docs/ledger/OPEN_QUEUE.md` that
   indexes every question ID with the chosen option's **label verbatim** and the note, marks the ⛔ ones,
   lists the defaults taken as ASSUMPTIONS and the `later`/pending ones; (c) where an answer amends a
   non-negotiable or a UI invariant (the sheet says `Amends:` where that is so), add the amendment under
   the right heading of `CLAUDE.md` and extend `tests/test_repo_invariants.py::test_ui_invariants` where
   the invariant is testable — raising the CLAUDE.md line ratchet is normal for exactly this; (d) a
   `docs/ledger/shipped.csv` row (binary append, LF, `docs/planning`, `docs-only`); (e) push to the same
   branch / PR unless it has merged, then a fresh branch from a freshly-fetched `origin/main`.
5. **Then write the second half of the plan** — the per-release gate files
   (`docs/product/RELEASE_0.4_GATE.md` amended, `RELEASE_0.5_GATE.md` … `RELEASE_0.9_GATE.md` new) and
   the per-slice session briefs — **from the answers, not from memory**. Every gate row cites the question
   ID it implements.
6. **Never** decide a ⛔ question, never build anything the maintainer's messages called "only plans",
   never treat a blank as a ruling.

### §0.3 Evidence tiers used in this file

VERIFIED = read in the tree at `main`@`bebcef4` (anchor given). SEARCH-VERIFIED = consistent across
several web search results this session; the source pages themselves were egress-blocked (proj.org,
download.geofabrik.de, wikitech, mediawiki.org, npr, cnn all refused). FROM MEMORY = a technical fact the
writer is confident of but could not check from here; **the session that builds on it must confirm it**.
Every scale figure carries its tier.

---

## §1 Rulings already received — pre-filled, confirm once

These were decided by the maintainer's two messages of 2026-09-12 and are recorded in
`docs/ledger/OPEN_QUEUE.md`. They are listed so that the answered sheet is complete on its own and so that
nothing has to be restated. Each `R` is a ruling; the *how* behind several of them is a question later.

| R | Ruling (verbatim intent) | Source | Where the *how* is asked |
|---|---|---|---|
| R1 | After an import, reopening the import UI shows a **fresh, clean page** — the previous run's message and analytics do not remain. *Reverses the 2026-07-16 field-report behaviour `_uxShowLastCompletedSummary` implements.* | msg 1, item 1 | Q201 |
| R2 | The import **"details" adds no value** and goes. Overlapping / blinking messages are a defect; the UI must be cleaner and simpler. | msg 1, item 1 | Q206, Q207 |
| R3 | The **index merging** (the part that takes the most time) is either **inside the import experience or explicitly outside it**, so the user knows whether the app can be **closed, reopened, updated**, and whether the **import files can be removed** (removable drive). | msg 1, item 1 | Q202–Q205 |
| R4 | **Export completion** is marked by a clear message, with the **list of what the export contains**: size, content statistics, files, number of articles, etc. | msg 1, item 1 | Q208, Q209 |
| R5 | The export **creates a folder named `YYYYMMDDHHMM_OOS_Backup`** in the target location; on collision an **incremental number is appended**. | msg 1, item 1 | Q210–Q212 |
| R6 | **ISO 3166-1 alpha-3 replaces alpha-2 consistently** — UI, bulletin, diagnostics, inner workings, code, and the app's inner filenames. "Clearer and easier to understand." | msg 1, item 2 | Q301–Q314 |
| R7 | **Keywords (rising and everywhere) and cards appear in the UI language, tagged "translated from X"**; users can still search and navigate foreign-language keywords, with the translation shown to help track them. | msg 1, item 3 | Q401–Q418 |
| R8 | **Wikidata / rings** are the translation mechanism unless a better idea exists; translation is **automated**; any automated Wikidata download respects their limits: **≤ 1 request per 10 seconds**. | msg 1, item 3 | Q406–Q408 |
| R9 | **Rings in backups** is decided after the other ring decisions. | msg 1, item 3 | Q409 |
| R10 | A search for a keyword **searches all languages through the rings by default** and **concatenates** the results, across **every** result tab (mind maps, trends, articles, sources, map…); the user can **restrict to the literal keyword**. *"To allow users to analyze worldwide content outside of their current capability, language being the major barrier."* | msg 1, item 4 | Q501–Q516 |
| R11 | An **advanced search** exists: language restriction, source-tag filtering, date selection, article length, and more; modelled on search engines' advanced forms; **more Boolean operators, each with a visual affordance**; one unified UI for every search need. | msg 1, item 5 | Q601–Q618 |
| R12 | **Wikipedia is handled like press**: scraped, ingested, indexed, analysed; **as much metadata as possible**; every article **tracked for changes and the changes ingested, indexed, analysed**; **automatic**; **defaulted to all 12 UI languages**; **the entire Wikipedia**; **dumps are not the way**. | msg 1, item 6 | Q701–Q728 |
| R13 | **Equal Earth** replaces the current projection (the UN vote); maps are **entirely reviewed**; **OpenStreetMap is scraped, ingested, indexed, analysed and tracked for changes**, used for analytics and spatial representation; **maps are treated as articles** (tracked, metadata, indexed, keywords, searchable). | msg 1, item 7 | Q801–Q828 |
| R14 | **Laws** from every country are scraped, ingested, indexed, analysed, **tracked for changes**, with **analysis of the changes over time and geography**; **laws are treated as articles**. | msg 1, item 8 | Q901–Q930 |
| R15 | **Law eligibility = written, or formally translated, into any of the app's 12 UI languages** (ar, bn, de, en, es, fr, hi, id, ja, pt, ru, zh); ingest from **as many countries as possible** under that rule. | msg 2 | Q901, Q911, Q912 |
| R16 | **The OSM content that matters is the metadata attached to places** — market-place name, opening hours, website, contact information, email, etc. **Global trends and changes in the types of metadata, and tracking their changes**, is the feature "never seen anywhere before". Street names and the like are secondary. | msg 2 | Q809–Q816 |
| R17 | **Link every address and GPS (or equivalent) datum found on Wikipedia — and in any other indexed and analysed content — onto the map.** | msg 2 | Q819, Q820 |
| R18 | **0.9 can be the beta.** The maintainer's original intent was **version 1 = Beta 1**; they can adapt. *The final form is Q101 ⛔.* | msg 2 | Q101 |
| R19 | **The answer-sheet process**: one extensive markdown file, answered in place, returned into a compressed session; everything decided now counts and is not restated later. | msg 2 | §0, Q1201–Q1208 |

#### Q001 · Confirm the recorded rulings R1–R19
- (a) **All nineteen are correctly recorded.** _Impact: none; they are already in the docket._
- (b) **All except the ones I correct below.** Write `NOTE: R7 — …` lines under this question with the
  correction; each correction is recorded as an amendment to the docket entry.

Default if blank: (a).

ANSWER Q001:

---

## §2 The train — releases, the beta, and how the plan is executed

**Context (VERIFIED).** The approved V1 train ([`V1_PATHWAY_2026-07-14.md`](V1_PATHWAY_2026-07-14.md) §3,
ruled 2026-09-07 with four amendments): 0.3 measured-and-verified (closing: one open row, the Tier-A
quarantine run + the `v0.3.0` tag from your machine) · 0.4 living sources · 0.5 the investigator's desk ·
0.6 elections + climate (keyless) · 0.7 medical + patents · 0.8 conflict + the 360° dossier + an OSM
dated-boundary seed · 0.9 hardening RC · 1.0 "the gift". V1-9 puts **≥ 1 full Wikipedia edition** at 1.0.
`pyproject.toml` still reads `0.3.0`. `RELEASE_0.4_GATE.md` exists with rows A–C (ruled) and D–F
(proposed). The intake document proposed **beta = 0.9.0** and re-loaded 0.4 and 0.5 with the eight items.

#### Q101 ⛔ · What "beta" and "1.0" mean (was Q1)
Your original intent was *v1 = Beta 1*. Three coherent shapes:
- (a) ★ **0.9.0 = Beta 1, 0.9.x = later betas, 1.0.0 = general availability ("the gift").** Alphas are
  0.4–0.8. Semantic versioning reads as outsiders expect (1.0 = stable). _Impact: effort none · risk low ·
  unlocks the V1 §8 checklist as the 1.0 bar unchanged · costs nothing you have written._
- (b) **1.0.0 = Beta 1 (your original intent); GA becomes 1.x or 2.0.** Alphas run 0.4–0.9. _Impact:
  effort S (rename the RC gate) · risk: a "1.0" that is a beta confuses testers and packagers, and the
  hosting stance's "public release" moment moves to an unnamed later version · unlocks nothing new._
- (c) **An earlier beta (0.7 or 0.8) with verticals continuing during beta.** _Impact: effort none ·
  risk: a beta that keeps adding verticals is an alpha with a different name; testers see data-format
  churn (wiki/OSM/law lanes still landing) — the thing a beta promises not to do._

Default if blank: none (⛔ — stays pending).

ANSWER Q101:

#### Q102 · What the beta freezes
- (a) ★ **Features + schema (only additive migrations after 0.9.0) + backup format (every backup made
  since 0.9.0 restores forever) + the consent model.** UI copy and translations may still move. _Impact:
  effort S (a written freeze list in the 0.9 gate) · risk low · unlocks honest tester guidance ("your data
  survives every beta")._
- (b) **Features only.** _Impact: cheaper · risk: a schema break during beta forces testers to re-import;
  the data-safety promise is the app's whole reputation._
- (c) **Everything, including strings.** _Impact: blocks the i18n remainder (Q1155) and typo fixes — too
  rigid for a 12-locale app._

Default if blank: (a). Depends on: Q101.

ANSWER Q102:

#### Q103 · Who tests the beta, and how they get it
- (a) ★ **GitHub pre-release tags (`v0.9.0-beta.1` …) + a `docs/BETA_TESTERS.md` with the freeze list, the
  data-safety promise and the report format; invite-only, no accounts, no telemetry** (the hosting stance).
  _Impact: effort S · risk low · unlocks structured field reports._
- (b) **Public pre-release** (anyone may download). _Impact: effort S · risk: support load before the
  hardening is done; the same zero-telemetry rule means you learn only what people write to you._
- (c) **Private circle only, files shared by hand.** _Impact: effort none · risk: few reports._

Default if blank: (a).

ANSWER Q103:

#### Q104 · The beta exit bar (what lets 1.0.0 ship)
- (a) ★ **The V1 §8 acceptance checklist (already ruled) + a field bar: at least N external testers ran
  ≥ 30 days each with zero data-loss reports and every P0 validation row green on their machines.**
  Propose N = 5. _Impact: effort none now; the 0.9 gate carries the rows · risk low._
- (b) **V1 §8 only.** _Impact: no field evidence beyond your own machine._
- (c) **Time-boxed: 1.0 ships on a date regardless.** _Impact: contradicts "gate-driven, not date-driven"._

Default if blank: (a). Write `NOTE: N = …` to change the tester count.

ANSWER Q104:

#### Q105 · Accept the amended contents of 0.4 and 0.5 (was Q2)
The intake §5 absorbs items 1, 3, 4, 6, 8 + the alpha-3 boundary + Equal Earth into **0.4** on one
versioned-source substrate, and the advanced search + the Place entity + the OSM artifacts (pulled from
0.8) into **0.5**. The approved themes and order are unchanged.
- (a) ★ **Yes — amend the contents, keep the themes.** _Impact: 0.4 becomes a large release (nine slices);
  the mitigation is the slice briefs (Q113) so that parallel sessions can take slices independently._
- (b) **Keep the approved contents and insert an extra release (0.4.5) for the eight items.** _Impact:
  a cleaner 0.4 · risk: the eight items are what you asked for first; delaying them behind the approved
  0.4 contents delays the mission-critical language work by a cycle._
- (c) **Re-slice per my note.** Write which items move where.

Default if blank: (a). Depends on: Q106–Q108.

ANSWER Q105:

#### Q106 · Where the OSM place-metadata tracking (R16) lands
- (a) ★ **0.5 seeds it (the Place entity + the first country's POIs + the tag-completeness view); 0.6
  adds daily change tracking and the trend surfaces; 0.7–0.8 widen to more countries.** _Impact: the
  substrate (0.4) exists before the heaviest lane uses it · risk low._
- (b) **0.4.** _Impact: no substrate yet; the wiki and OSM lanes would be built in parallel with the thing
  they share — the drift the substrate exists to prevent._
- (c) **0.6, all at once.** _Impact: nothing spatial improves before 0.6._

Default if blank: (a).

ANSWER Q106:

#### Q107 · The law breadth cadence
- (a) ★ **0.4: the metadata model + the L0 defects + the first bulk adapters; 0.5: the evolution surface;
  0.6: breadth to the language coverage floor (R15); 0.7–0.8: the rest of the world + subnational.**
  _Impact: analytics arrive on a small, correct corpus before breadth multiplies any modelling mistake._
- (b) **Breadth first (0.4), analytics later.** _Impact: thousands of documents ingested on today's
  baseline-diff primitive (the wrong one for evolution analysis) and re-processed later._

Default if blank: (a).

ANSWER Q107:

#### Q108 · The Wikipedia timing
- (a) ★ **0.4: the stream (metadata for every edit, all twelve editions) + HOT full text; 0.5: WARM +
  the tail walk under budget; 0.6: the coverage report per edition.** _Impact: the lane runs ≥ 72 h on
  the reference VM before it is allowed to grow._
- (b) **Everything in 0.4.** _Impact: the 2-core VM budget cannot be measured before it is exceeded._
- (c) **Start in 0.5.** _Impact: the language mission's largest corpus waits a cycle._

Default if blank: (a).

ANSWER Q108:

#### Q109 · Close 0.3 now (was Q3)
- (a) ★ **Yes: row 5 (the Tier-A quarantine run, 8 articles) + the `v0.3.0` tag from your machine; then the
  version flips to `0.4.0`.** _Impact: an operator step of minutes; 0.4 work lands on a tagged base._
- (b) **Fold row 5 into 0.4.** _Impact: 0.3 stays open indefinitely; nothing else changes._

Default if blank: (a).

ANSWER Q109:

#### Q110 · Dates
- (a) ★ **Gate-driven with target dates, as the V1 train already says** ("if it takes one more year, it's
  OK"). _Impact: none._
- (b) **A fixed cadence (e.g. every 6 weeks) shipping whatever is green.** _Impact: predictable tags ·
  risk: half-landed lanes get tagged._
- (c) **No dates at all.**

Default if blank: (a).

ANSWER Q110:

#### Q111 · What every alpha tag ships with
- (a) ★ **Tag + GitHub release notes generated from `shipped.csv` since the previous tag + the
  no-telemetry re-check stated in the notes (the per-release ritual already in `CLAUDE.md`).** _Impact:
  effort S per tag._
- (b) **Tag only.** _Impact: the no-telemetry ritual is skipped by omission — the failure the ritual exists for._

Default if blank: (a).

ANSWER Q111:

#### Q112 · The per-release gate files
- (a) ★ **Write `RELEASE_0.5_GATE.md` … `RELEASE_0.9_GATE.md` now, from this sheet's answers, and amend
  `RELEASE_0.4_GATE.md`; every row cites the question ID it implements.** _Impact: effort M (one docs PR) ·
  unlocks parallel sessions reading one board each._
- (b) **Only the next board at a time.** _Impact: less to maintain · risk: the train's later contents live
  only in the intake document._

Default if blank: (a).

ANSWER Q112:

#### Q113 · The per-slice session briefs
- (a) ★ **One prompt file per slice under `docs/plans/2026-09-12-beta-pathway/` — the shape of the 23-prompt
  action plan: scope fence, verbatim gate commands, the rulings it implements by ID, the operator steps,
  what it may not decide.** _Impact: effort L (one docs PR, ~40 files) · unlocks handing a slice to any
  session cold._
- (b) **One brief per release.** _Impact: cheaper · risk: a release brief is too big for one session to
  hold, which is how scope creeps._
- (c) **None — the gate files suffice.**

Default if blank: (a).

ANSWER Q113:

#### Q114 ⛔ · The egress allowlist (was Q4; register F1)
Seven sessions could not reach a named publisher through the sandbox proxy; the variable was never the
prompt. Hosts by the work they unblock: `www.legislation.gov.uk`, `eur-lex.europa.eu`,
`www.gesetze-im-internet.de`, `laws.e-gov.go.jp`, `echanges.dila.gouv.fr` (laws) · `dumps.wikimedia.org`,
`stream.wikimedia.org`, `*.wikipedia.org`, `www.wikidata.org`, `query.wikidata.org` (Wikipedia + rings) ·
`download.geofabrik.de`, `planet.openstreetmap.org` (OSM) · `api.worldbank.org`, `sdmx.oecd.org`,
`api.imf.org` (statistics verification) · `extensions.duckdb.org` (the httpfs binaries) · `proj.org`
(the Equal Earth constants).
- (a) **Add them to the session environment's allowlist.** _Impact: every "live-verified" bar in the
  gates becomes a session step · risk: none to users (the app's own egress is unchanged; this is the build
  sandbox)._
- (b) **Never; you run the live-verification steps on your machine each time.** _Impact: the operator
  lists grow by one item per adapter; each takes minutes of your time per release._
- (c) **Both** — (a) for the read-only hosts, (b) for anything that writes.

Default if blank: none (⛔).

ANSWER Q114:

#### Q115 · Your operator-time budget per release
- (a) ★ **≤ 4 hours** (the V1 train's own assumption: "a few hours of maintainer time"). _Impact: every
  gate's operator list is cut to fit; the rest becomes session steps or is dropped with a note._
- (b) **≤ 1 day.**
- (c) **Unbounded.**

Default if blank: (a).

ANSWER Q115:

#### Q116 · Parallel lanes
- (a) ★ **Planning (web) + build (CLI) + verification (AppVM/Chromium), as today.** _Impact: none._
- (b) **Add a second build lane** (two slices in flight). _Impact: faster · risk: the stale-base merge
  hazards the ledger records (2026-06-15, 2026-07-02, 2026-07-18) recur more often; the slice briefs must
  fence files._

Default if blank: (a).

ANSWER Q116:

#### Q117 · The 0.4 board's proposed rows D, E, F (register A2's remainder)
- (a) ★ **D and E become bars; F ("the browser bar reaches a human, a second engine, or is closed as-is")
  is closed as-is with Q1128's answer.** _Impact: none beyond the board._
- (b) **All three become bars.**
- (c) **None.**

Default if blank: (a). Depends on: Q1128.

ANSWER Q117:

#### Q118 · Post-1.0 ambitions — where they are written down
All-twelve-edition full text, rosters + poll tier-2, street-level maps, subnational laws, case law:
- (a) ★ **A `docs/product/POST_1.0_BACKLOG.md` created with the 0.9 gate, each item citing its ruling.**
  _Impact: effort S · stops them being re-proposed as 1.0 work._
- (b) **Leave them in the individual design documents.**

Default if blank: (a).

ANSWER Q118:

---

## §3 Import and export (R1–R5)

**Context (VERIFIED, `src/static/app-backup.js` unless noted).** `openUnifiedImport()` (:494–508) resets
seven things and then deliberately re-renders the previous run through `_uxShowLastCompletedSummary()`
(:521–554) — the 2026-07-16 field report asked for that. Never reset on open: the queue rows, the details
body, the poll timer, the phase. The bar has two owners at two cadences (1200 ms verify poll, 1000 ms
queue renderer) and rows are rebuilt by `innerHTML` every tick — that is the blinking. "Details"
duplicates the queue rows except the path. The **search-index merge** (FTS5 `optimize_after_bulk`,
minutes) runs inside the run; the **article re-index** (hours) is a separate deferred job
(`ReindexJobManager`, `src/analytics/reindex_job.py`; four endpoints in `src/api/backup_v2.py:770–905`)
with **zero frontend callers**, so the UI cannot know when analytics are complete. The import reassembles
the volumes into a **disposable local staging directory** (`read_volume_backup` → parity recovery →
reassembly → staging, `volume_job.py:437–448`) and merges into a **working copy** that is swapped onto the
live corpus (`import_queue.py:232–241`, "staged" ≠ "done"). Export writes volumes **directly into the
chosen directory** with no subfolder and no timestamp (`volume_job.py:237–243`); the completion line
discards the summary that already carries per-table counts and bytes (`stream_backup.py:456–465`); the
reuse pool that saved 8.15 GB on the 2026-08-12 run scans the **destination** for reusable volumes
(`stream_backup.py:766+`). No "OOS" string exists in the tree; the browser-tab suffix is "· FOOS".

#### Q201 · Where the previous run goes when the page is fresh (was Q5)
- (a) ★ **One quiet line: "Last import · 2026-09-12 10:45 · 12,340 articles · open report", linking the
  persisted import report (`GET /api/backup/import-reports`, unused today).** _Impact: effort S · keeps
  the 2026-07-16 need (find what just happened) without the clutter._
- (b) **Nothing — fully fresh.** _Impact: effort S · the report is reachable only from the task manager
  History (Q222)._
- (c) **A History subtab in the task manager only** (the invariant #20 "REMAINING: History" item), the
  import page fully fresh. _Impact: effort M · the cleanest page; two clicks to the last report._

Default if blank: (a). Amends: the 2026-07-16 behaviour (recorded as superseded either way).

ANSWER Q201:

#### Q202 · The visible import lifecycle
| Stage | What runs | Afterwards the user may… |
|---|---|---|
| 1 Verify + stage | signature, checksums, parity, reassembly into local staging | nothing yet |
| 2 Merge + swap | the merge into the working copy, the atomic swap, custody side files | remove the files; close or update the app |
| 3 Search-index merge | FTS5 `optimize_after_bulk` (minutes) | search is complete |
| 4 Re-index | the deferred article re-index (hours, resumable) | analytics are complete |
- (a) ★ **Four stages, shown as four rows with their own progress.** _Impact: effort M (one owner for the
  bar and the poll; rows patched, not rebuilt)._
- (b) **Three stages — fold 3 into 2** ("Merge", then "Analytics"). _Impact: simpler · the minutes-long
  FTS merge shows inside "Merge", which is where a user waits anyway._
- (c) **Two stages — "Import" (1–3) and "Afterwards" (4).** _Impact: simplest · the safety facts move
  onto one boundary._

Default if blank: (a).

ANSWER Q202:

#### Q203 · When each safety statement is shown
"Files may be removed" is honest **after the swap** in every case; it is honest **after staging** only
if no crash occurs before the swap (a resumed import would need the files again).
- (a) ★ **Files: after the swap. Close/update: after the swap (a durable cursor resumes stages 3–4 on the
  next boot). Analytics complete: after stage 4.** _Impact: no false promise; the three facts are three
  labelled ticks._
- (b) **Files: after staging, with the caveat "unless the import is interrupted before it completes".**
  _Impact: earlier freedom on a removable drive · a caveat the user must read._

Default if blank: (a).

ANSWER Q203:

#### Q204 · The deferred re-index (was Q6)
- (a) ★ **Stage 4 lives inside the import experience as its own row (progress from
  `GET …/reindex-backlog/resume/status`) with a link to the task manager.** _Impact: effort M · the UI
  finally knows the job exists._
- (b) **Task manager only; the import experience ends at stage 3 with a line "analytics will complete in
  the background — see Tasks".** _Impact: effort S._
- (c) **No deferral: re-index synchronously inside the import.** _Impact: hours inside a dialog; the
  2026-08 field runs are why deferral exists._

Default if blank: (a).

ANSWER Q204:

#### Q205 · Re-index resumability across restarts and updates
- (a) ★ **The existing durable cursor (`reindex-resume`) auto-resumes on boot; the UI shows "resuming
  re-index (N left)".** _Impact: effort S (wire the existing job)._
- (b) **A manual "resume" button only.** _Impact: a user who updates the app and forgets never gets the
  analytics._

Default if blank: (a).

ANSWER Q205:

#### Q206 · The blinking and overlap (R2)
- (a) ★ **One poll chain, one bar owner, rows patched in place (keyed by item id), the two `_uxImQueuePoll`
  chains reduced to one.** _Impact: effort S–M · a Chromium check pins it._

Default if blank: (a). (Confirm-only; write a NOTE if you saw other overlapping surfaces.)

ANSWER Q206:

#### Q207 · "Details" (was Q8)
- (a) ★ **Remove it.** _Impact: effort S._
- (b) **Collapse it behind a toggle.** _Impact: keeps the path column, which nothing else shows._

Default if blank: (a).

ANSWER Q207:

#### Q208 · The export completion panel (R4)
- (a) ★ **Volumes · total bytes · per-table counts with articles first (the ruled headline unit) · files
  copied per category (dumps, models, newsletters) · elapsed · destination path · encryption state ·
  schema version · app version · the licence lines that apply (Q1008).** _Impact: effort S — every field
  already exists in `s1.summary`._
- (b) **A minimal line: articles, bytes, destination.**

Default if blank: (a).

ANSWER Q208:

#### Q209 · A human-readable summary inside the folder (was Q11)
- (a) ★ **Write `BACKUP_SUMMARY.md` beside `volumes.json` with the same facts, so the folder explains
  itself on a removable drive years later.** _Impact: effort S._
- (b) **Panel only.**

Default if blank: (a).

ANSWER Q209:

#### Q210 · The timestamp in `YYYYMMDDHHMM_OOS_Backup` (was Q9)
- (a) ★ **Local time** (what the user sees on their clock when they look at the drive). _Impact: two
  exports across a DST change can sort out of order once a year._
- (b) **UTC** (monotonic, sortable everywhere). _Impact: a folder made at 10:45 Paris reads 08:45._

Default if blank: (a).

ANSWER Q210:

#### Q211 · The collision suffix
- (a) ★ **`_2`, `_3` … appended: `202609121045_OOS_Backup_2`.** _Impact: sorts beside its sibling._
- (b) **` (2)`** in the Windows/macOS Finder style. _Impact: a space in a folder name; scripts need quoting._
- (c) **Add seconds (`YYYYMMDDHHMMSS`) and never collide.** _Impact: departs from the ruled name._

Default if blank: (a).

ANSWER Q211:

#### Q212 · The "OOS" token
- (a) ★ **Keep `OOS` as ONE constant** (`BACKUP_FOLDER_TOKEN`), so the expected rename later is one edit.
  _Impact: none._
- (b) **`FOOS`**, matching the browser-tab suffix. _Impact: consistency with the tab suffix, which the
  ledger already calls a placeholder._
- (c) **Spell it out: `OpenOmniscience`.**

Default if blank: (a).

ANSWER Q212:

#### Q213 · Dated folders versus incremental reuse (was Q10)
- (a) ★ **Always a new dated folder; the reuse pool is widened to sibling `*_OOS_Backup*` folders in the
  same parent, so an incremental refresh still finds last time's volumes.** _Impact: effort S–M · keeps the
  8 GB-class savings._
- (b) **A per-export choice: "refresh the existing folder" or "new dated folder".** _Impact: one more
  control on a dialog you asked to simplify._
- (c) **Always a full new backup, no reuse.** _Impact: hours and gigabytes on every export._

Default if blank: (a).

ANSWER Q213:

#### Q214 · The two parallel backup-restore APIs (was Q12; Q-VIS-5)
`import-queue/*` is what the UI drives; `v2/restore/preview→commit→discard`, `legacy/restore` and
`reindex-*` sit beside it unreferenced, both sets claiming to back the unified dialog.
- (a) ★ **`import-queue/*` is the one path: delete `v2/restore/*` after moving anything only it does into
  the queue; wire `reindex-*` (Q204).** _Impact: effort M · one owner for the UI._
- (b) **Keep both.** _Impact: the two-owner bug class stays._
- (c) **`v2/restore/*` wins and the queue is rebuilt on it.** _Impact: effort L._

Default if blank: (a).

ANSWER Q214:

#### Q215 ⛔ · Legacy single-file restore (register C1)
`read_artifact`'s docstring says it accepts legacy bare SQLite backups and v1 `.ooenc` files **"forever
(D7)"**; the create path was retired 2026-06-25.
- (a) ★ **Keep the restore half forever, as the docstring commits; close C1.** _Impact: none · risk none._
- (b) **Remove it in 0.4, after you confirm every legacy backup you hold has been merged; amend the
  docstring.** _Impact: effort S · risk: a forgotten legacy file becomes unrestorable._

Default if blank: none (⛔).

ANSWER Q215:

#### Q216 ⛔ · The import checkpoint interval K (register C2)
Verify + swap once per K backups; nothing is durable until a swap. K = 1 is today's behaviour.
- (a) ★ **K = 3.** _Impact: ~2/3 of the verify+snapshot+swap cost saved on long queues · a kill loses at
  most two merges._
- (b) **K = 1 (today).**
- (c) **Another K** — write it.

Default if blank: none (⛔).

ANSWER Q216:

#### Q217 · Import prefetch (register C3)
- (a) ★ **Build only if the first real `verify_copy` timing shows "prepare" still dominating.** _Impact:
  a measurement gates a build._
- (b) **Build it.**
- (c) **Never.**

Default if blank: (a).

ANSWER Q217:

#### Q218 · Removable-drive exports — verify after write
- (a) ★ **Re-read every volume after writing and check its checksum; default ON; the panel says
  "verified".** _Impact: doubles the read time of an export · catches the silent USB corruption class._
- (b) **Optional, default OFF.**

Default if blank: (a).

ANSWER Q218:

#### Q219 · What an export contains when the new lanes exist
- (a) ★ **The corpus always; the Wikipedia, OSM and law lanes as opt-in members with their sizes shown
  before the export starts** (the artifact-member mechanism of PR #1020). _Impact: a 100 GB wiki lane
  never surprises a 32 GB stick._
- (b) **Everything, always.**

Default if blank: (a). Depends on: Q1004.

ANSWER Q219:

#### Q220 · Scheduled automatic exports
- (a) ★ **Record as a 0.6+ backlog item (a scheduled export to a chosen folder, dated folders, the reuse
  pool).** _Impact: none now._
- (b) **Build in 0.4.**
- (c) **Never** (exports stay a deliberate act).

Default if blank: (a).

ANSWER Q220:

#### Q221 · Importing the new lanes
- (a) ★ **The same import dialog and lifecycle; each lane is a row with the same four stages.** _Impact:
  one UI._
- (b) **Separate dialogs per lane.**

Default if blank: (a).

ANSWER Q221:

#### Q222 · Where import history lives
- (a) ★ **A History subtab in the task-manager window (invariant #20's recorded "REMAINING: History"),
  listing imports and exports with their persisted reports.** _Impact: effort M._
- (b) **Settings → Backup.**

Default if blank: (a).

ANSWER Q222:

---

## §4 ISO 3166-1 alpha-3 everywhere (R6)

**Context (VERIFIED).** Storage is lowercase alpha-2 by a 0.09 ruling (`src/catalog/countries.py:1–21`).
Six `String(2)` columns (`models.py:335, 425, 667, 1246, 1835, 1947`) — source metadata, `Source.country`,
`Article.country` (the largest table), `ExternalSource.country`, `ArticleMentionedPlace.country`,
`KeywordMention.country`; `LawDocument.jurisdiction` is a free `String(8)` (`uk`, `eu`, `int`);
`StatFigure.ref_area` is already alpha-3 uppercase (World Bank). `ISO2_TO_ISO3` / `to_iso2` (:644) /
`to_iso3` (:672) exist, fail-closed. Two frontend mechanisms break silently on alpha-3:
`Intl.DisplayNames(type:"region")` accepts alpha-2 and M49 only (`app-map.js:91–99` degrades to the bare
code) and the flag derivation is gated on `/^[A-Z]{2}$/` (`app-agenda.js:981–985`). Three external
contracts are alpha-2 and cannot move: FRED/OECD symbol ids (an alpha-3 attempt was reverted once,
`shipped.csv:239, :275`), the OSM tag `ISO3166-1:alpha2`, DB-IP's table. The restore merge keys on the
**value** (`merge.py:3280`; `country` adoptable at :2274): an old backup's `fr` and a migrated `FRA` are
unequal, so an unnormalised restore duplicates instead of deduplicating. 5,803 `country:` /
`jurisdiction:` lines across 14 YAML files. **No filename in the tree carries a country code.** Language
codes are ISO 639-1 and share a normalisation branch with country at `csv_io.py:130`.

#### Q301 ⛔ · Migration depth (was Q13)
Your ruling says "consistently throughout both the UI and the app … all inner workings and code as well
as the app's inner filenames." The honest cost of each reading:
- (a) **FULL: storage, configs, code, tests, payloads and a filename rule all move to alpha-3; alpha-2
  survives only at the three external contracts behind explicit converters; the backup format version
  bumps and the restore path normalises alpha-2 → alpha-3 on import so every older backup stays
  restorable.** _Impact: effort L (six column widenings + backfill over the two largest tables, ~5,800
  config lines by script, ~105 Python + 18 JS/HTML files, ~78 test files, `world_countries.json` re-keyed,
  DB-IP rebuilt) · risk: MEDIUM-HIGH and irreversible in the backup sense — one missed normaliser path
  duplicates rows forever (additive restore never deletes); mitigated by a restore-time normaliser +
  a duplicate-key scan in the 0.4 gate · unlocks exactly what you asked._
- (b) ★ **DISPLAY + BOUNDARY: the user sees alpha-3 everywhere a code is shown (UI, bulletin, diagnostics
  payloads, CSV/JSON exports gain `country_iso3`); the store, configs and contracts keep alpha-2 as the
  internal identity behind one formatter per side.** _Impact: effort M · risk low · does NOT satisfy
  "inner workings and code" — the ruling's letter — and a developer reading the DB still sees `fr`._
- (c) **FULL, staged: (b) in 0.4, the storage half in 0.5 once the backup-format bump and the normaliser
  have shipped and been exercised on a real restore.** _Impact: effort L spread over two releases · risk
  lowered by sequencing · the DB shows `fr` for one more cycle._

Default if blank: none (⛔). Depends on: Q304, Q305, Q310, Q312.

ANSWER Q301:

#### Q302 · How a country reads on screen (was Q14)
- (a) ★ **Uppercase code beside the localised name: "France · FRA".** _Impact: the code is learnable; the
  name is what people read._
- (b) **Code only ("FRA").** _Impact: densest · `BGD`, `MMR`, `KHM` are not obvious to most readers._
- (c) **Name only, the code in the hover bubble.** _Impact: the code you asked for is one hover away._

Default if blank: (a).

ANSWER Q302:

#### Q303 · Codes for non-countries and special cases (was Q15)
Alpha-3 has no official code for the EU or "international"; the ISO **user-assigned** range is
AAA–AAZ, QMA–QZZ, XAA–XZZ, ZZA–ZZZ (FROM MEMORY; confirm). The World Bank uses `EUU` (EU) and `XKX`
(Kosovo), and `StatFigure.ref_area` already stores those.
- (a) ★ **World-Bank-compatible: `EUU` (EU), `XKX` (Kosovo), `ANT` (the withdrawn Netherlands Antilles,
  legacy rows only), `GBR` for the law `uk`, and app-defined `INT` for "international", each disclosed in
  the hover as "not an ISO code".** _Impact: statistics rows and corpus rows agree without a bridge._
- (b) **Strictly user-assigned: `XEU`, `XKX`, `XIN`, `XAN`.** _Impact: formally correct · disagrees with
  the World Bank rows already stored._

Default if blank: (a).

ANSWER Q303:

#### Q304 · The API and payload shape (was Q16)
- (a) **If Q301 = FULL: `country` becomes alpha-3 everywhere; every parameter accepts both forms through
  `normalize_country`; external-contract endpoints emit `country_iso2` beside it.** _Impact: one breaking
  API change, versioned in the release notes._
- (b) **If Q301 = DISPLAY: `country` stays alpha-2; every payload gains `country_iso3`; parameters accept
  both.** _Impact: additive, nothing breaks._

Default if blank: follows Q301.

ANSWER Q304:

#### Q305 · The 5,803 config lines (was Q17)
- (a) **Rewrite them all in one scripted pass, with a test that no lowercase alpha-2 `country:` value
  remains** (FULL). _Impact: one large mechanical diff; the loader keeps accepting alpha-2 for third-party
  overlays._
- (b) ★ **Keep the files alpha-2; the loader normalises** (DISPLAY, or FULL-staged step 1). _Impact:
  smallest diff · the files a contributor edits still say `fr`._

Default if blank: follows Q301.

ANSWER Q305:

#### Q306 · Language codes (was Q18)
"Clearer and easier to understand" could be read as applying to languages too (`eng`, `fra`).
- (a) ★ **Stay ISO 639-1 (`fr`).** _Impact: none · BCP-47, `Intl`, the browser, `lang=` attributes and
  every locale file speak two-letter codes._
- (b) **Move to ISO 639-2/3 (`fra`).** _Impact: effort M–L (12 locale files, `Article.language`,
  `detected_language`, every filter, the FTS language configs, the i18n engine) · risk: the browser and
  `Intl` still need two-letter codes at the boundary — a second converter layer like the country one._

Default if blank: (a).

ANSWER Q306:

#### Q307 · Flags
- (a) ★ **Keep the flag emoji, derived internally from alpha-3 → alpha-2** (invariant #15's "flag is a
  visual convention only" stands). _Impact: none._
- (b) **Drop flags** (codes and names only). _Impact: a visual anchor lost on the agenda and sources._

Default if blank: (a).

ANSWER Q307:

#### Q308 · Ordering in pickers and lists
- (a) ★ **By localised name, the code as a secondary column.** _Impact: none._
- (b) **By code.**

Default if blank: (a).

ANSWER Q308:

#### Q309 · The filename rule (the ruling's "inner filenames")
No file today carries a country code, so this is a rule for future files (OSM extracts, law bundles,
per-country reports).
- (a) ★ **Rule: a filename carrying a country uses uppercase alpha-3 (`osm_FRA_2026-09.pbf`,
  `laws_DEU.jsonl`), enforced by a repo test over `data/` naming helpers.** _Impact: effort S._
- (b) **No rule.**

Default if blank: (a).

ANSWER Q309:

#### Q310 · Old backups after a storage migration
- (a) ★ **The restore path normalises alpha-2 → alpha-3 while importing (old backups restorable
  forever), and the 0.4 gate proves it with a duplicate-key scan after restoring a pre-migration backup.**
  _Impact: the one item that makes FULL safe._
- (b) **A one-way migration tool the user runs on old backups first.** _Impact: a step people skip._

Default if blank: (a). Applies if Q301 ∈ {a, c}.

ANSWER Q310:

#### Q311 · External contracts stay alpha-2 behind converters
FRED/OECD ids, the OSM `ISO3166-1:alpha2` tag, DB-IP, `Intl.DisplayNames`, Wikidata `P297` (alpha-2;
`P298` alpha-3 can be fetched too).
- (a) ★ **Confirm; fetch `P298` in the catalog query as a cross-check.** _Impact: none._
- (b) **Amend** — write which.

Default if blank: (a).

ANSWER Q311:

#### Q312 · Timing
- (a) ★ **0.4** (before more data accumulates; alongside the substrate, whose new tables are born alpha-3).
- (b) **0.5.**

Default if blank: (a).

ANSWER Q312:

#### Q313 · Exports and diagnostics during the transition
- (a) ★ **CSV/JSON exports carry both `country` (old form) and `country_iso3` for one release, then the
  old column is dropped; diagnostics payloads switch in the same release as storage.** _Impact: a stated
  deprecation instead of a silent break._
- (b) **Switch everything at once.**

Default if blank: (a).

ANSWER Q313:

#### Q314 · Subnational identity (for the admin-1 maps of §9)
- (a) ★ **ISO 3166-2 (`FR-75`, `US-CA`) where OSM carries the `ISO3166-2` tag; the OSM relation id as the
  fallback identity.** _Impact: the same "stable code inside, formatter outside" rule as countries._
- (b) **OSM relation ids only.**

Default if blank: (a).

ANSWER Q314:

---

## §5 Keywords in the UI language, "translated from X" (R7–R9)

**Context (VERIFIED).** Rings: 26 curated + 684 generated = **698 rings / 21,927 members** in 12 languages
(es 2,636 · en 2,519 · ar 2,384 · de 2,272 · zh 2,118 · fr 1,989 · ja 1,868 · ru 1,807 · pt 1,599 · id 1,141 ·
hi 851 · bn 716). `equivalence.py`: `ring_of`, `translate_term` (no refusal path), `expand_term` (refuses
the **91 collisions** such as `de wahl`, `de strom`), `QueryExpander`; three `lru_cache(maxsize=1)` loaders,
no runtime invalidation; rings live in `configs/` and ride no backup. `_annotate_translations`
(`queries.py:245–274`) emits `translation` + `translation_source="ring"` and **no source language**. Card
titles structurally never translate the term (`Card.title_i18n`/`title_vars`, `i18n.js:162`: "data (the
keyword term) must not translate"). `Keyword.language` is first-write-wins with a self-documented 16% /
40%-of-head mismatch; rings resolve on the *effective* language. The LLM tentative fallback
(`src/ai_layer/translate.py`) is loopback-only, ≈-marked, a 5,000-entry process cache lost on restart,
reached only by a button. The ring generator (`scripts/generate_wikidata_rings.py`) sleeps **0.2 s**
between Wikidata requests — fifty times faster than R8. The app already reaches Wikidata at runtime through
the consented world-discovery ride-along (`discover.py:36–41`). `translation_coverage` ≈ 5% of top keywords.
Coverage of surfaces: six render a translation today, eleven render the raw term, seven endpoints accept no
`target_lang`.

#### Q401 · The label grammar (was Q19)
- (a) ★ **The translation is the visible term; a small tag "translated from French" follows it; the hover
  bubble shows the original `climat`, the ring's other members with counts, and the source.** _Impact:
  effort S per surface (one shared display helper) · the list stays readable in the UI language._
- (b) **Original first with an arrow: "climat → climate".** _Impact: today's `→` form; the foreign word
  leads, which is what R7 objects to._
- (c) **Both inline: "climate (climat, fr)".** _Impact: honest and dense · long lists get wide._

Default if blank: (a).

ANSWER Q401:

#### Q402 · How the source language is named in the tag
- (a) ★ **The language's name in the UI language ("traduit de l'anglais", "translated from Arabic").**
  _Impact: 12 × 12 names, all already in the locale files._
- (b) **The autonym ("Deutsch", "العربية").** _Impact: recognisable to its speakers, opaque to others._
- (c) **The code ("from DE").**

Default if blank: (a).

ANSWER Q402:

#### Q403 · The three-tier ladder
Tier 1 verified = ring translation · Tier 2 tentative = LLM, always ≈ · Tier 3 = untranslated, tagged with
its language, still searchable. One display helper renders all three on every keyword surface (the eleven
silent surfaces gain it; the seven endpoints gain `target_lang`; `_annotate_translations` gains
`translation_source_lang`, `translation_tier`, `senses`).
- (a) ★ **Confirm.** _Impact: effort M across surfaces._
- (b) **Amend** — write which tier changes.

Default if blank: (a).

ANSWER Q403:

#### Q404 🔒 · Persist tentative (LLM) translations (was Q21)
- (a) ★ **A `keyword_translations` table (term, source lang, target lang, text, model, prompt version,
  created) — never the trusted index, always ≈, rides the backup.** _Impact: effort S · what the app
  retains grows by a small, labelled table._
- (b) **Keep the in-process cache** (lost on restart, recomputed at cost).

Default if blank: (a).

ANSWER Q404:

#### Q405 · Tentative translations in lists (was Q20)
- (a) ★ **Shown by default once persisted, ≈-marked, when the AI coordinator is on; filled by a
  background sweep over the untranslated head.** _Impact: the head of every list reads in the UI language
  within hours of a backend being up._
- (b) **On demand only, as today.**

Default if blank: (a). Depends on: Q404.

ANSWER Q405:

#### Q406 ⛔ · The in-app Wikidata ring refresh (was Q22)
- (a) ★ **A consented, task-manager-visible job: the gap digest → `wbgetentities` at ≤ 1 request / 10 s,
  `maxlag=5`, the bot UA → a proposal file → a review surface in Settings → accepted rings land in
  `data_dir()/keyword_rings_local.yml` (curated-wins precedence).** _Impact: effort M · ≤ 8,640 lookups a
  day at the ruled cadence · nothing loads without a human accepting it._
- (b) **Auto-load without review** (still ≤ 1 / 10 s). _Impact: faster coverage · a wrong sense enters the
  trusted index unreviewed — the thing `expand_term`'s refusal exists to prevent._
- (c) **Operator script only; the app ships rings and never fetches.** _Impact: coverage grows only with
  releases._

Default if blank: none (⛔). The generator's 0.2 s spacing changes to 10 s in every case.

ANSWER Q406:

#### Q407 · What triggers ring growth
- (a) ★ **The gap digest: the most frequent untranslated keywords per language first** (the
  `ring_candidates` diagnostic already computes it). _Impact: the head of every list gets covered first._
- (b) **Every new keyword as it appears.** _Impact: the 10 s budget is spent on the long tail._
- (c) **Only keywords the user asks about.**

Default if blank: (a).

ANSWER Q407:

#### Q408 · The Wikidata call pattern
- (a) ★ **`wbsearchentities` in the term's language, then `wbgetentities` for labels in all twelve
  languages, one item per request, 10 s apart.** _Impact: ~2 requests per keyword · simple, resumable._
- (b) **WDQS SPARQL batches** (many labels per query, still 10 s apart). _Impact: fewer requests · WDQS
  has its own limits (60 s query time per minute per IP, SEARCH-VERIFIED earlier) and returns less
  predictable payloads._

Default if blank: (a).

ANSWER Q408:

#### Q409 · Rings in backups (was Q23; R9)
- (a) ★ **Locally accepted rings and the tentative table ride the corpus backup; the shipped ring files
  never do.** _Impact: a restore on a new machine keeps what cost network time._
- (b) **All rings, including shipped.** _Impact: a few MB of duplication per backup._
- (c) **None.**

Default if blank: (a).

ANSWER Q409:

#### Q410 · Refreshing the shipped rings per release
- (a) ★ **Regenerate `keyword_rings_generated.yml` on your machine before each tag at the polite rate,
  targeting the top 2,000 keywords per language (≈ 24,000 lookups ≈ 3 days of a background script).**
  _Impact: coverage of the head climbs from ~5% toward the majority of what users see._
- (b) **Freeze the shipped set; rely on the in-app job.**

Default if blank: (a).

ANSWER Q410:

#### Q411 · Cards translate the term (was Q24)
- (a) ★ **Yes, as a ruled exception to the "data never translates" design: `title_vars` gains
  `term_translation` + `term_lang`; the template reads `"{term_translation}" (translated from {term_lang}:
  {term})`.** _Impact: effort S · the `i18n.js:162` comment is amended to cite this ruling._
- (b) **Cards keep the original term.**

Default if blank: (a). Amends: the i18n design note at `i18n.js:162`.

ANSWER Q411:

#### Q412 · The 91 collision terms (was Q25)
- (a) ★ **No single translation: "several senses" + a sense picker; `translate_term` gains the refusal
  path `expand_term` already has.** _Impact: effort S · never the wrong concept's word._
- (b) **Show the most common sense's word with a marker.**

Default if blank: (a).

ANSWER Q412:

#### Q413 · The source language is the ring member's effective language (was Q26)
- (a) ★ **Confirm; the `reconcile_keyword_language` pass runs in the 0.4 gate.**
- (b) **Amend.**

Default if blank: (a).

ANSWER Q413:

#### Q414 · Fixing `Keyword.language` for good
- (a) ★ **Store the language per mention (= the article's language) and derive the keyword's language as
  the majority; the first-write-wins column becomes a cache.** _Impact: effort M (a `KeywordMention`
  column + backfill) · the 16% / 40% mismatch disappears by construction._
- (b) **Leave it; rely on the reconcile pass.**

Default if blank: (a).

ANSWER Q414:

#### Q415 · Entities (people, organisations, places) by QID
- (a) ★ **The same ladder for entities, keyed by Wikidata QID — this is the 0.5 entity spine's first
  concrete use.** _Impact: effort M in 0.5._
- (b) **Keywords only.**

Default if blank: (a).

ANSWER Q415:

#### Q416 · Lemmatisation across the twelve languages
Keyword normalisation today is per-language ad hoc; `simplemma` (MIT, pure Python, 40+ languages) would
make "élections"/"élection" one keyword in every UI language.
- (a) ★ **Add `simplemma` to the core dependencies; lemmatise at extraction; a migration re-normalises
  existing keywords under a job.** _Impact: effort M · fewer, truer keywords · a one-time re-index cost._
- (b) **No new dependency.**

Default if blank: (a).

ANSWER Q416:

#### Q417 · Trends and rising keywords computed per concept
- (a) ★ **Aggregates (rising, trends, top) are computed per RING when the term is in one, with a
  per-language breakdown in the hover; the display shows the UI-language label.** _Impact: effort M ·
  "climate" rising in three languages reads as one concept rising, which is the mission._
- (b) **Per term, as today; translation is display-only.** _Impact: the same concept appears three times
  in three languages._

Default if blank: (a). Depends on: Q501.

ANSWER Q417:

#### Q418 · The hover bubble on a translated keyword
- (a) ★ **Original term · source language · ring members with per-language counts · the QID with a LOCAL
  preview first (invariant #6) · the tier (verified / ≈ tentative).** _Impact: effort S._
- (b) **Original term and source language only.**

Default if blank: (a).

ANSWER Q418:

---

## §6 Cross-language search in every tab (R10)

**Context (VERIFIED).** `ExpandTerms` (`fts.py:170–194`) + `QueryExpander` thread ring expansion through
AND/OR/NOT with a disclosure payload; `expand=false` is the literal escape. Wired on **two endpoints only**
(`/api/articles`, `main.py:1452–1454`; `/api/search/omni`). `_resolve_corpus` (`insights.py:381`) — behind
every analysis subtab — is literal-only, so eleven endpoints (`/trend`, `/trend-articles`,
`/associations`, `/context`, `/keyword-stats`, `/graph`, `/where`, `/who`, `/corpus-keywords`,
`/corpus-sources`, `/map-coverage`) know nothing of rings: a Home card's corpus and its keyword trend
disagree by construction. `expand=false` and sense pins live only in `_articleQuery`
(`app-analysis.js:1107–1123`) and do not survive a reload. `search_total` re-runs the MATCH uncapped
(`search_omni.py:110`). FTS5 tokeniser is `unicode61` (FROM MEMORY for the exact config; confirm), which
does not segment Chinese or Japanese.

#### Q501 · Expansion on by default everywhere, one persisted literal toggle (was Q27)
- (a) ★ **Yes: `resolve_concept(term, ui_lang, sense)` computed once per analysis tab and passed to both
  the FTS path and the keyword-keyed aggregates; "only the words I typed" is one toggle persisted in the
  tab seed and the URL.** _Impact: effort M–L (eleven endpoints gain `expand`/`sense`/`ui_lang`) · every
  tab agrees with the Articles list._
- (b) **Per-tab opt-in.** _Impact: the disagreement stays unless the user remembers to toggle each tab._

Default if blank: (a).

ANSWER Q501:

#### Q502 · Series for a concept with several languages (was Q28)
- (a) ★ **Stacked per language with a legend.** _Impact: the reader sees which languages carry the concept
  and how much._
- (b) **One merged line.** _Impact: loses the language signal that is the point._
- (c) **One series per language, unstacked.**

Default if blank: (a).

ANSWER Q502:

#### Q503 · A member cap per expansion (was Q29)
- (a) ★ **Cap at 40 literals, the most frequent first, disclosed as "expanded to 40 of 63 forms".**
  _Impact: bounds the OR fan-out on the SQLCipher store._
- (b) **No cap.**

Default if blank: (a).

ANSWER Q503:

#### Q504 · Sense pins and the literal toggle persist in the tab seed and URL (was Q30)
- (a) ★ **Confirm (`?expand=0`, `?sense=`).**

Default if blank: (a).

ANSWER Q504:

#### Q505 · Restricting to some languages
- (a) ★ **A multi-select on the expansion chip ("searching: en, fr, de — change") in the search bar and
  the analysis window.** _Impact: effort S._
- (b) **Advanced search only.**

Default if blank: (a).

ANSWER Q505:

#### Q506 🔒 · Chinese and Japanese tokenisation
`unicode61` treats a Chinese sentence as one token; today `zh`/`ja` articles are effectively not searchable
by word.
- (a) ★ **The FTS5 `trigram` tokeniser for a second FTS table over `zh`/`ja` (and any script without
  spaces), queried transparently.** _Impact: effort M · index size grows roughly 3× for those rows ·
  substring search becomes possible._
- (b) **A segmenter dependency (`jieba` for zh, `sudachipy` for ja).** _Impact: better precision · two
  large dependencies and dictionaries._
- (c) **Leave as is** (disclosed as a known gap).

Default if blank: (a).

ANSWER Q506:

#### Q507 · Arabic and diacritic normalisation
- (a) ★ **`remove_diacritics=2` + alef/teh-marbuta/yeh folding at index and query time.** _Impact:
  effort S · a re-index of Arabic rows._
- (b) **As is.**

Default if blank: (a).

ANSWER Q507:

#### Q508 · How concatenated results are ordered
- (a) ★ **Interleaved by date, a language chip on every row.** _Impact: none._
- (b) **Grouped by language.**

Default if blank: (a).

ANSWER Q508:

#### Q509 · Per-language counts on the expansion chip
- (a) ★ **"climate 120 · climat 45 · Klima 30 · …" — the honest picture of where the concept lives.**
- (b) **A single total.**

Default if blank: (a).

ANSWER Q509:

#### Q510 · Watches and alerts
- (a) ★ **A watch on "climate" watches the ring** (disclosed on the watch row). _Impact: effort S._
- (b) **Watches stay literal.**

Default if blank: (a).

ANSWER Q510:

#### Q511 · The bulletin
- (a) ★ **Bulletin sections built from keywords use the ring** (and label the concept in the edition's
  language). _Impact: effort S._
- (b) **Literal.**

Default if blank: (a).

ANSWER Q511:

#### Q512 · The mind map
- (a) ★ **The ring is the centre node; each language is an arm; associations hang off the arms.**
  _Impact: effort M · fits the ruled radial-tree grammar._
- (b) **Merged as one node.**

Default if blank: (a).

ANSWER Q512:

#### Q513 · Beyond keywords — the vision question
"To allow users to analyze worldwide content outside of their current capability." Keywords are ruled.
The next steps up the ladder:
- (a) **Keywords only** (R7 as ruled). _Impact: none._
- (b) ★ **Also article titles and summaries, translated by the local LLM, ≈-marked, shown on hover and in
  lists when the AI coordinator is on; never stored as the article; opt-in.** _Impact: effort M in 0.5 ·
  local compute only · a French reader can scan Arabic headlines._
- (c) **Also full-article translation in the reader, on demand, local LLM, ≈, never stored as the
  article.** _Impact: effort M in 0.7+ · minutes per article on the reference VM · the reader shows the
  original beside it._

Default if blank: (b) — multi-select allowed (b, c).

ANSWER Q513:

#### Q514 · Tentative translations never expand a search
- (a) ★ **Confirm: expansion is ring-verified only; a ≈ translation may display but expands a query only
  when the user opts in per query.**

Default if blank: (a).

ANSWER Q514:

#### Q515 · Totals on ring-size extremes
- (a) ★ **`search_total` is capped (e.g. 10,000) and shows "≥ 10,000".** _Impact: effort S._
- (b) **Exact, uncapped.**

Default if blank: (a).

ANSWER Q515:

#### Q516 · The Observatory, the map and the sources tab read the same resolution
- (a) ★ **Confirm.**

Default if blank: (a).

ANSWER Q516:

---

## §7 Advanced search (R11)

**Context (VERIFIED).** Grammar: `AND`/`OR`/`NOT` (English, hard-coded, `fts.py:49`), quoted phrases,
parentheses, implicit AND. `_quote` (`fts.py:160–167`) wraps every term as a phrase, so prefix `climat*`,
`NEAR(a b, N)` and `title:` are structurally impossible today although FTS5 supports all three. Filters on
`/api/articles`: `source` (exact, 404 on a typo), `start_date`/`end_date` on `published_at`, `language`
(asserted column only), `tags` (substring), `provenance`, `source_type`, `ids`, six sorts. Missing: word
count, sentiment, source country/region, author, `created_at` window, mentioned-date, multi-language,
include-quarantined — all indexed already. The Advanced subtab has five controls (`index.html:470–484`).
`ooTimeScope` (`app-markets.js:2351–2496`) exists with presets but no timescale selector; Advanced does not
use it. Export takes a strict subset of the filters. Saved searches exist only as Watches. Typo tolerance:
ruling pending (OPEN_QUEUE, the 406,723-keyword scan cost). Operator words are English only.

#### Q601 · The v1 filter list (was Q31)
Proposed: language multi-select over asserted **and** detected (labelled) · sources (facet picker with
counts) · source tags · provenance / channel · source country + region (alpha-3) · published range via
`ooTimeScope` with presets + a timescale selector · a separate "collected between" control (never
coalesced with "published") · word-count bands (script-aware; zh/ja/th excluded with a note) · sentiment
(English-only caveat visible) · "mentions a date in range" · include-quarantined (advanced only, disclosed)
· keyword / concept (ring or literal) · sort.
- (a) ★ **Confirm the list.** _Impact: effort L (0.5 S5.1)._
- (b) **Prune** — write which to drop in a NOTE.
- (c) **Add** — write which in a NOTE (each addition is checked against an existing indexed column first).

Default if blank: (a).

ANSWER Q601:

#### Q602 · The builder (was Q32)
- (a) ★ **Rows of `field · operator · value` rendered as chips above the query box; the box stays editable
  and shows the compiled query (two-way: typing updates the rows where parseable).** _Impact: effort M ·
  the model of every search engine's advanced page._
- (b) **Chips only** (no visible compiled query). _Impact: hides the grammar power users want._
- (c) **A plain form** (one field per filter). _Impact: cheapest · no operators._

Default if blank: (a).

ANSWER Q602:

#### Q603 · Grammar extension (was Q33)
- (a) ★ **Add prefix `word*`, `NEAR(a b, N)`, and column filters `title:`, `author:` — three FTS5-native
  additions behind an explicit token class so `_quote`'s injection safety stays.** _Impact: effort S._
- (b) **No.**

Default if blank: (a).

ANSWER Q603:

#### Q604 · Operator words (was Q34)
- (a) ★ **English tokens stay canonical; the builder is the localised layer (buttons say "ET/OU/SAUF" in
  French, compile to `AND/OR/NOT`); a hover explains each.** _Impact: a French user typing `OR` ("gold")
  still gets an operator — disclosed in the hover, and the phrase button avoids it._
- (b) **Accept localised aliases in the typed grammar.** _Impact: `or` in French, `y` in Spanish, `et`…
  become ambiguous words; worse, not better._

Default if blank: (a).

ANSWER Q604:

#### Q605 · Typo tolerance (was Q35)
- (a) **Unbuilt** (the ledger's current default).
- (b) ★ **A SymSpell-shaped precomputed table built by a background job (deletes-within-2 over the keyword
  vocabulary), offering "did you mean" — never silently rewriting the query.** _Impact: effort M in 0.5 ·
  a few hundred MB for a 400k-keyword vocabulary._
- (c) **`spellfix1`** (vendors a compiled SQLite extension). _Impact: rejected earlier for that reason._

Default if blank: (b).

ANSWER Q605:

#### Q606 · Saved searches (was Q36)
- (a) ★ **The Watch model gains the full filter set; a saved search is a watch with threshold zero.**
  _Impact: effort S–M · one model._
- (b) **A new `SavedSearch` model.**

Default if blank: (a).

ANSWER Q606:

#### Q607 · Export parity (was Q37)
- (a) ★ **`/api/articles/export` takes the full parameter set, so an export reproduces the filtered
  view.**

Default if blank: (a).

ANSWER Q607:

#### Q608 · The omnibar's Enter (was Q38)
- (a) ★ **Enter always opens the analysis window on the typed query; static commands need an explicit
  selection.** _Impact: the open product question at `app-shell.js:739–748` closes._
- (b) **Keep the current precedence of static commands.**

Default if blank: (a).

ANSWER Q608:

#### Q609 · The time component
- (a) ★ **`ooTimeScope` gains the timescale selector and becomes the one begin/end/scale component for
  Advanced, Markets and Insights** (the ruled "built once").
- (b) **A separate date control for Advanced.**

Default if blank: (a).

ANSWER Q609:

#### Q610 · Diacritics and case
- (a) ★ **Fold by default (`é` = `e`, case-insensitive) with an "exact" toggle per query.** _Impact: the
  FTS5 default behaviour; Arabic per Q507._
- (b) **Exact by default.**

Default if blank: (a).

ANSWER Q610:

#### Q611 · Field search
- (a) ★ **`title:`, `author:`, `source:` (name) — body is the default field.** _Impact: effort S._
- (b) **Also `url:` and `tag:`.**

Default if blank: (a).

ANSWER Q611:

#### Q612 · Proximity default
- (a) ★ **`NEAR` defaults to 10 tokens; the builder's row has a distance stepper.**
- (b) **Another default** — write it.

Default if blank: (a).

ANSWER Q612:

#### Q613 · Regular expressions
- (a) ★ **A deliberate omission** (FTS5 has no regex; a `LIKE` fallback scans every row). Recorded so
  nobody re-proposes it as an oversight.
- (b) **A `LIKE`/regex fallback on bounded result sets** (≤ 10,000 rows after the FTS filter).

Default if blank: (a).

ANSWER Q613:

#### Q614 · Search history
- (a) ★ **Local, private, opt-in (default off), clearable, never exported.** _Impact: effort S._
- (b) **None.**

Default if blank: (a).

ANSWER Q614:

#### Q615 · Result views
- (a) ★ **List (cards) + a table view toggle (sortable columns: date, source, language, words,
  sentiment).** _Impact: effort S._
- (b) **List only.**

Default if blank: (a).

ANSWER Q615:

#### Q616 · Permalinks
- (a) ★ **The full query + every filter is URL-addressable (`?q=…&lang=…&from=…`), so a search can be
  shared as a local link and re-opened after a restart.**
- (b) **No.**

Default if blank: (a).

ANSWER Q616:

#### Q617 · Quarantined articles
- (a) ★ **Excluded by default; "include quarantined" is an advanced-only control with the quarantine
  reason shown on each such row.**
- (b) **Never searchable.**

Default if blank: (a).

ANSWER Q617:

#### Q618 · Default sort
- (a) ★ **Date descending** (news). _Impact: none._
- (b) **Relevance** (FTS5 `bm25`). _Impact: better for research questions · surprising for a news app._

Default if blank: (a).

ANSWER Q618:

---

## §8 Wikipedia — the living encyclopaedia, without dumps (R12)

**Context (VERIFIED, `src/wiki/`, 13 files).** Nothing is watched by default (`WikiPage(` is constructed
only at `track.py:47`, reached by `POST /api/wiki/pages`). Tracking is per-page revision polling;
`list=recentchanges` has a client and no consumer; no EventStreams anywhere. Wiki tracking is a scheduler
**mode** (`settings.py:66` `mode="rss"`; `runner.py:744–761`) that never runs by default and stops RSS
when selected. Per revision: `full_text` compressed + a diff summary; per page: `baseline_text` +
`latest_text`; no retention policy. Only the latest text becomes an Article (`corpus.py:324–334`; no
`pageid`, no QID, no `source_type`). Dumps: a full download manager, an offline reader, a disposable FTS
side-file; dump→corpus only via `POST /api/wiki/dumps/corpus-ingest` (limit 1,000, no UI). Fetch path:
three Wikimedia hosts through `guarded_session`, the bot UA
`OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; …)` (`client.py:21`),
`maxlag=5`, 1.0 s per-process interval; robots.txt is not consulted for API/dump endpoints by design
(`fetcher.py:173–175`, the SDMX precedent). Rulings on record: 2026-06-12 (edition-level tracking replaces
per-article), 2026-06-13 (watched entirely and by default in all 12 UI editions — not built); both named
dump-as-baseline, which R12 now rules out. V1-9 (2026-09-07): ≥ 1 full edition + the scaling machinery at 1.0.

**Scale (SEARCH-VERIFIED, September 2026 unless noted): article counts** en 7.24 M · de 3.15 M (2024
figure) · fr 2.75 M · es 2.13 M · ru 2.11 M · zh 1.54 M · ja 1.51 M · ar 1.33 M · pt 1.18 M · id 0.79 M ·
bn 0.19 M · hi ≈ 0.17 M (older figure) — **≈ 24 M articles across the twelve editions**. **Edits:** enwiki
≈ 80–160 k/day (the ledger's planning figure); the other eleven together are of the same order (FROM
MEMORY); bots are a large share. **Etiquette (SEARCH-VERIFIED):** up to **50 titles per request**, and for
several pages only the **latest** revision's content may be fetched in one call (`rvlimit` is refused with
multiple titles; with content it is capped at 50); requests are to be made serially; EventStreams is
Kafka-backed, resumes with `Last-Event-ID`, and its retention is bounded (7 days by default FROM MEMORY;
the service can extend to 31).

**A correction to the intake document (§3.6 said "months per edition").** With 50-page batching the
arithmetic is: 24 M pages ÷ 50 = ~480,000 requests; serial at 1 request/s = **~5.6 days for one full pass
over all twelve editions**, on clearnet, moving on the order of 150–250 GB of wikitext (FROM MEMORY: ~10 KB
average for enwiki, less elsewhere). So the never-edited tail is **reachable in about a week per pass**,
not months — a background walk is a real option, and the constraint is disk, not the API.

#### Q701 ⛔ · Coverage without dumps — the trade, ruled knowingly (was Q39)
- (a) **Stream-forward only: every page that changes enters on its first change; the never-edited tail is
  never fetched; coverage is reported per edition.** _Impact: cheapest · a young install knows only what
  moved since it started (the 2026-09-07 pass found 52 of 77 galaxies "not observed yet" on a young corpus —
  the same shape)._
- (b) **Stream-forward plus a one-time dump baseline per edition for the tail** (contradicts R12; listed
  so the refusal is explicit). _Impact: ~65 GB compressed download once · complete from day one._
- (c) ★ **Stream-forward plus a slow `allpages` walk for the tail, batched 50 per request, serial, under
  the storage budget (Q707), coverage reported per edition.** _Impact: complete metadata for all ~24 M
  pages within a week or two of clearnet time; full text only as far as the budget allows · exactly what
  the API etiquette permits._

Please also write the reason dumps are out (`NOTE: bandwidth over Tor / disk / staleness / other`) so the
trade is recorded and never re-litigated.

Default if blank: none (⛔).

ANSWER Q701:

#### Q702 ⛔ · Automatic egress, default on, under the one online consent (was Q40)
EventStreams (a persistent SSE connection), the Action API, the pageviews API (Q706), ORES/Lift Wing
(Q717) — reached automatically whenever the app is online, for all twelve editions, enumerated in
`docs/SECURITY.md` and in the consent popup's hover.
- (a) ★ **Yes — a lane under the one online consent, like the hazard feeds; the consent popup names it.**
  _Impact: the R12 "automatic, defaulted" ruling as written · every user who goes online holds an open
  stream to Wikimedia._
- (b) **A dedicated Wikipedia toggle, default off.** _Impact: contradicts "automatic and defaulted"._
- (c) **The stream (metadata) is default-on; the full-text fetch waits for the storage budget the first-run
  wizard sets.** _Impact: default-on with a disk ceiling the user chose._

Default if blank: none (⛔).

ANSWER Q702:

#### Q703 · What "the entire Wikipedia" includes
- (a) ★ **Namespace 0 (articles), excluding redirects, including disambiguation and list pages.**
  _Impact: ~24 M pages._
- (b) **Also exclude disambiguation and list pages.** _Impact: fewer, denser pages · lists carry real data
  (elections, laws, places)._
- (c) **All namespaces** (talk, user, project…). _Impact: several times the volume; talk pages are
  arguments, not knowledge._

Default if blank: (a).

ANSWER Q703:

#### Q704 · The text form stored
- (a) ★ **Wikitext (the source of truth: infoboxes, `{{coord}}`, categories and templates are extractable
  from it) + a derived plain text for the FTS index.** _Impact: infobox fields and coordinates (R17) come
  for free._
- (b) **Plain text only** (`TextExtracts`). _Impact: smallest · loses every structured field._
- (c) **Parsed HTML.** _Impact: largest · easiest to render._

Default if blank: (a).

ANSWER Q704:

#### Q705 · Metadata captured per page ("as much metadata as possible")
Proposed: `pageid` · QID (`pageprops.wikibase_item`) · sitelink count · categories · length · revision
count · protection level · last editor class (bot / anonymous / registered) · infobox fields (key/value)
· coordinates (`prop=coordinates`, GeoData) · image count · external-link count · citation-needed count
· page assessment class where the edition has it (`prop=pageassessments`) · creation date · the edition.
- (a) ★ **Confirm the list.**
- (b) **Prune** — write which.
- (c) **Add** — write which.

Default if blank: (a).

ANSWER Q705:

#### Q706 · Pageviews (the Wikimedia Analytics API — attention as a signal)
- (a) ★ **The daily top-1,000 per edition (12 requests a day) + per-article daily views for HOT pages.**
  _Impact: a cheap "what the world is reading" signal per language · one more Wikimedia host._
- (b) **None.**
- (c) **Per-article views for every tracked page.** _Impact: millions of requests; not polite._

Default if blank: (a).

ANSWER Q706:

#### Q707 · Tiers and the storage budget (was Q41)
- (a) ★ **Three tiers under a per-edition daily budget the first-run wizard sets (default proposed: 20 GB
  total, published): HOT = pages the corpus already mentions, tracked pages, and the pageview top-1,000
  (full text + `index_article` on every change); WARM = every other changed page (full text, indexed
  lazily under the daily budget); COLD = the tail reached by the walk (metadata now; text as budget
  allows).** _Impact: the 2-core VM stays alive · the arithmetic that forces it: ~2.3 articles/s indexed
  on one core, so ~100 k changed pages/day is ~12 h of a core._
- (b) **Full text for everything, no budget.** _Impact: ~50–80 GB compressed, growing; the reference VM
  cannot index it._
- (c) **HOT only.**

Default if blank: (a). Write `NOTE: budget = … GB` to change the default.

ANSWER Q707:

#### Q708 · Per-edit rows versus per-page counters
Metadata for every edit in twelve editions is roughly 250–300 k rows/day (FROM MEMORY) — on the order of
15 GB/year uncompressed as rows.
- (a) ★ **Per-page daily counters for every page (edits, bytes delta, distinct editors, reverts) + full
  per-edit rows for HOT and WARM pages.** _Impact: the "changes analysed" promise at a fraction of the
  volume._
- (b) **Every edit as a row for every page.** _Impact: complete · ~15 GB/year, less in DuckDB._

Default if blank: (a).

ANSWER Q708:

#### Q709 · Noise
- (a) ★ **Reverted pairs collapse (the `mw-reverted` tag); bursts by one editor within 10 minutes
  coalesce; bot edits are counted and flagged, never dropped.** _Impact: trends measure human change._
- (b) **Keep everything raw.**
- (c) **Drop bot and minor edits.** _Impact: bots carry real maintenance signal (dead links, categories)._

Default if blank: (a).

ANSWER Q709:

#### Q710 🔒 · Retention (was Q42)
- (a) ★ **HOT: every ingested version's text; WARM: latest + previous; counters and metadata forever.**
- (b) **All versions for all tiers.**
- (c) **Latest only.**

Default if blank: (a).

ANSWER Q710:

#### Q711 · The diff primitive
- (a) ★ **Against the previous ingested version, section-aware (which section changed), per-mention
  revid anchoring per the standing ruling.**
- (b) **Against the first-seen baseline** (today's law-side primitive; wrong for evolution).

Default if blank: (a).

ANSWER Q711:

#### Q712 · The analytics that ship first, in order
1 edit velocity per topic / country / language · 2 contested pages (revert rate) · 3 newly created pages
as emerging topics · 4 cross-edition divergence for one QID (size, edit rate, existence across the twelve)
· 5 attention (pageviews) versus coverage in the press corpus.
- (a) ★ **Confirm the five and the order (1–3 in 0.4, 4–5 in 0.5).**
- (b) **Reorder / prune** — write it.

Default if blank: (a).

ANSWER Q712:

#### Q713 · Page creation, deletion and move events
- (a) ★ **Tracked from the stream's log events; a deleted page keeps its last text and is marked deleted.**
- (b) **Ignore.**

Default if blank: (a).

ANSWER Q713:

#### Q714 · Wikipedia rows next to press counts
~24 M wiki pages beside ~40 k press articles would swamp every count and KPI.
- (a) ★ **Separate lane counts everywhere; the "articles" headline stays press unless a lane filter is
  chosen; the Home strip shows "Wikipedia: N pages · M changes today" as its own figure.** _Impact:
  effort S in each surface · honest denominators._
- (b) **Merged counts.**

Default if blank: (a).

ANSWER Q714:

#### Q715 · Identity (was Q46)
- (a) ★ **`WikiPage` keyed `(wiki, pageid)` with `qid`; the Article carries `wiki_pageid`, `qid`,
  `source_revision` (exists), `source_type="wikipedia"`, the edition as language.**

Default if blank: (a).

ANSWER Q715:

#### Q716 · Lane, not mode (was Q45)
- (a) ★ **Wikipedia becomes a lane beside RSS collection; `mode="wiki"` is retired; `POST /api/wiki/pages`
  survives as "pin this page to HOT".**
- (b) **Keep the mode.**

Default if blank: (a).

ANSWER Q716:

#### Q717 · ORES / Lift Wing (was Q44)
- (a) ★ **Verify Wikimedia's current scoring endpoint (the ORES → Lift Wing migration, FROM MEMORY), keep
  it opt-in, ≈-labelled.**
- (b) **Drop it.**

Default if blank: (a).

ANSWER Q717:

#### Q718 · Wikimedia Enterprise and other keyed APIs (was Q48)
- (a) ★ **Excluded under V1-2 (no key-gated source), confirm.**

Default if blank: (a).

ANSWER Q718:

#### Q719 🔒 · A separate database file per lane
- (a) ★ **`wiki.db` (and `osm.db`, `law.db`) beside the corpus, linked by ids; backups per lane; a 100 GB
  lane never bloats the corpus file or its encryption rekey.** _Impact: effort M in the substrate · the
  single-file simplicity of today goes._
- (b) **One database file for everything.** _Impact: simplest · the 64 TiB ceiling is far, but a rekey or
  an integrity check of one 100 GB file is hours._

Default if blank: (a). Depends on: Q1004 (the general rule).

ANSWER Q719:

#### Q720 🔒 · Encryption at rest for the public-data lanes
The data is public; the **selection** (which pages, which countries) reveals the user's interests.
- (a) ★ **Encrypted with the same passphrase, same threat model, no exceptions.**
- (b) **A per-lane plaintext option for speed, disclosed as "this lane reveals what you track".**

Default if blank: (a).

ANSWER Q720:

#### Q721 · Backups (was Q43)
- (a) ★ **Lane backups are opt-in members with their size shown (Q219); HOT pages' Articles ride the corpus
  backup as any Article.**
- (b) **Always included.**

Default if blank: (a).

ANSWER Q721:

#### Q722 · Transport
Wikimedia serves reads over Tor; the tail walk moves hundreds of GB.
- (a) ★ **The stream and the change fetches follow the user's transport setting (Tor or clearnet), never
  downgraded; the tail walk runs only on clearnet and says so ("waiting for a clearnet session").**
- (b) **Everything follows the transport setting, including the walk over Tor.** _Impact: weeks instead
  of days, and a heavy Tor load._

Default if blank: (a).

ANSWER Q722:

#### Q723 · The coverage report
- (a) ★ **Per edition: pages seen / edition total (from `siteinfo` statistics), full-text share, last
  event time, gap history — in the Living sources view and the diagnostics bundle.**

Default if blank: (a).

ANSWER Q723:

#### Q724 · Wikidata items for entities
- (a) ★ **In 0.5 (the entity spine): labels, descriptions and a claims subset (P31, P17, P625, P571…) per
  QID the corpus mentions, fetched at etiquette pace, cached locally.**
- (b) **No.**

Default if blank: (a).

ANSWER Q724:

#### Q725 · The first-run wizard
- (a) ★ **Edition choice (default: all twelve) + the storage budget (Q707) + the plain statement of what
  the lane contacts.**

Default if blank: (a).

ANSWER Q725:

#### Q726 · Disclosure
- (a) ★ **`docs/SECURITY.md` lists every Wikimedia host; the Wikipedia surface states the robots exemption
  the way `stats/fetch.py:22–25` does; the reader shows the CC BY-SA 4.0 attribution with a link to the
  page history.**

Default if blank: (a).

ANSWER Q726:

#### Q727 · Long offline gaps
- (a) ★ **If the gap exceeds the stream's retention, fall back to `list=recentchanges` per edition (bounded
  at 30 days by MediaWiki), then record an honest gap ("no change data between … and …").**
- (b) **Resume only; ignore the gap.**

Default if blank: (a).

ANSWER Q727:

#### Q728 · Superseded surfaces
The tracked-changes modal (`#wiki-tc`), the dump download manager, the offline dump reader, the dump→corpus
endpoint.
- (a) ★ **The modal becomes the Living sources view; the dump machinery stays (it is built and tested) as
  an opt-in offline reader, never the tracking path; the dump→corpus endpoint is retired.**
- (b) **Remove the dump machinery entirely.** _Impact: deletes working code that the 2026-06 rulings paid for._

Default if blank: (a).

ANSWER Q728:

---

## §9 Maps and OpenStreetMap (R13, R16, R17)

**Context (VERIFIED).** The app's one projection is **equirectangular** (`app-map.js:21–24`; not Mercator;
the 2026-06-18 ruling kept it deliberately); nine `lon2x`/`lat2y` call sites; zoom rides the SVG `viewBox`.
Geometry: `world_countries.json` = Natural Earth 110m, 175 countries, keyed alpha-2; ~75 microstates drawn
as gazetteer points; **no admin-1**; `configs/cities.yml` is absent (only the 2 KB sample). OSM: nine
Geofabrik regions (`src/geo/osm_regions.py`: planet 72 GB · europe 28 · north-america 14 · asia 13 ·
africa 5 · south-america 3 · australia-oceania 1.3 · central-america 0.6 · antarctica 0.03, sizes as of
2026-06), a resumable segmented downloader through the guarded factory, and a **browser-side** PBF reader
(`osmpbf.js`, ≤ 8 MB prefix, ephemeral overlay). **No Python PBF reader, no stored features, no
`.osc`/replication handling, no Place entity** (`ArticleMentionedPlace` is a disposable per-article row).
Rulings: OSM preprocessed offline into artifacts (2026-07-13 Q1a); **no-WebGL is firm**; street-level
detail out of scope; "a boundary is an Article; its OSM history is the linked audit layer"; contested
borders shown as contested.

**The UN vote (SEARCH-VERIFIED).** On 2026-09-04 the General Assembly adopted "Correct the Map" (164 for,
the United States against, 6 abstentions; sponsored by African Union member states and the Bahamas;
non-binding; encourages equal-area projections such as Equal Earth). **Equal Earth (FROM MEMORY — proj.org
was egress-blocked; confirm before shipping):** θ = asin((√3/2)·sin φ); x = (2√3/3)·λ·cos θ / (9A₄θ⁸ +
7A₃θ⁶ + 3A₂θ² + A₁); y = A₁θ + A₂θ³ + A₃θ⁷ + A₄θ⁹; A₁ = 1.340264, A₂ = −0.081106, A₃ = 0.000893, A₄ =
0.003796; aspect ≈ 2.05:1; no closed-form inverse (Newton iteration).

**OSM facts (SEARCH-VERIFIED):** Geofabrik's public extracts have had **user, uid and changeset stripped
since 2018-05-03** (GDPR); full-metadata extracts need an OSM login on `osm-internal`. Replication:
planet minutely/hourly/daily at `planet.openstreetmap.org/replication/`; Geofabrik publishes **daily**
change files per extract; **change files are kept about three months**. The `opening_hours` key carries
~5.3 M objects (978,867 distinct values, December 2025). HeiGIT's **ohsome API** (`api.ohsome.org/v1`,
free, public) answers full-history tag statistics. FROM MEMORY: the public extracts keep `version` and
`timestamp`; the `wikidata` tag is on several million objects; `website`, `phone`, `contact:*`, `email`,
`addr:*` are each in the millions; Geofabrik offers **country** and, for large countries, **sub-country**
extracts.

#### Q801 · The projection (was Q49)
- (a) ★ **Equal Earth on all five map surfaces through the one `project(lon, lat)` seam, no toggle, named
  in the legend ("Equal Earth · equal-area").** _Impact: effort S–M (nine call sites, curved graticule,
  a ~2.05:1 box, the viewBox maths) · one truth._
- (b) **Equal Earth default with a plate-carrée toggle.** _Impact: two truths; every screenshot differs._

Default if blank: (a).

ANSWER Q801:

#### Q802 · The base boundaries (was Q50)
- (a) ★ **Natural Earth 50m now (a few hundred KB more; the 110m polygons facet under the polar shear),
  OSM-derived admin-0/admin-1 artifacts from 0.5 replacing it.** _Impact: effort S now, M later._
- (b) **OSM-derived from the start.** _Impact: the preprocessing bridge moves into 0.4._
- (c) **Keep 110m.**

Default if blank: (a).

ANSWER Q802:

#### Q803 · Whose borders
OSM draws boundaries by its "on the ground" rule and keeps disputed claims as separate relations; Natural
Earth follows a de-facto policy of its own.
- (a) ★ **OSM's convention as of `<date>`, with every disputed area rendered CONTESTED showing both claims
  (the 2026-07-13 ruling), the convention named in the legend.**
- (b) **Natural Earth's convention** (until the OSM artifacts exist), then (a).
- (c) **A user-selectable worldview.** _Impact: the app takes a side per user; the honest form is (a)._

Default if blank: (a) with (b) as the interim.

ANSWER Q803:

#### Q804 · Admin-1
- (a) ★ **OSM `admin_level=4` relations → shipped artifacts keyed ISO 3166-2 (Q314), rendered on all five
  surfaces from 0.5.** _Impact: effort M (the preprocessing bridge) · choropleths below the country._
- (b) **None before 1.0.**

Default if blank: (a).

ANSWER Q804:

#### Q805 · The gazetteer (was Q56)
- (a) ★ **Built from the ingested OSM `place=*` nodes joined to Wikidata (population, names ×12, QID) at
  artifact-build time on your machine; shipped with a registry entry and a freshness test.**
- (b) **Wikidata only** (the existing networked script).

Default if blank: (a).

ANSWER Q805:

#### Q806 · Extract granularity
- (a) ★ **Country-level Geofabrik extracts keyed by alpha-3 (sub-country for the large ones: US states,
  German Länder, French régions, Brazilian states…), catalogued in `configs/osm_extracts.yml` with dated
  sizes.** _Impact: France ≈ 4.5 GB, Germany ≈ 4 GB, Monaco ≈ 1 MB (FROM MEMORY) · a user picks countries._
- (b) **Continent-level as today.** _Impact: Europe is 28 GB before a single feature is read._

Default if blank: (a).

ANSWER Q806:

#### Q807 · The OSM lane's default state
- (a) ★ **Off until the user picks countries (sizes and the daily diff cost shown); the wizard suggests
  the countries of the UI language, never from the IP.** _Impact: no surprise download._
- (b) **On for the countries of the UI language.**
- (c) **On for everything.** _Impact: impossible on the reference VM._

Default if blank: (a).

ANSWER Q807:

#### Q808 · Reading PBF (was Q53)
Under R16 the lane reads every POI of a country and its daily diffs; a pure-Python PBF decoder manages on
the order of 10⁵ nodes/s (FROM MEMORY), so a 4 GB country is hours to a day; `pyosmium` (C++, wheels for
Linux/macOS/Windows) does it in tens of minutes.
- (a) ★ **A `[geo]` extra with `pyosmium` for the extract pass; `.osc` diffs are XML and stay pure Python;
  without the extra the lane says so and offers the small-country path.** _Impact: the first compiled
  dependency in an optional extra · the honest way to meet R16 at country scale._
- (b) **Pure Python only.** _Impact: no compiled code · big countries take a day per extract and the
  reference VM is busy for it._
- (c) **Both — pure Python fallback, `pyosmium` when present.** _Impact: two code paths to test._

Default if blank: (a).

ANSWER Q808:

#### Q809 · Feature classes ingested (was Q52; R16)
- (a) ★ **Places with metadata: `amenity`, `shop`, `office`, `tourism`, `craft`, `healthcare`, `leisure`,
  `public_transport` stations, plus addresses (`addr:*` on any object), admin boundaries and `place=*`
  nodes.** _Impact: on the order of millions of rows per large country (FROM MEMORY) · what R16 asks for._
- (b) **Also roads and buildings.** _Impact: 10–100× the volume for street names and footprints — R16 calls
  those secondary._
- (c) **Admin boundaries and `place=*` only.** _Impact: cheap · none of the R16 metadata._

Default if blank: (a).

ANSWER Q809:

#### Q810 · The tags kept per object
- (a) ★ **A curated column set (`name`, `name:*`, `brand`, `brand:wikidata`, `operator`, `opening_hours`,
  `website`, `contact:*`, `phone`, `email`, `addr:*`, `wikidata`, `wikipedia`, `cuisine`, `level`,
  `check_date`, `disused:*`, `wheelchair`, `payment:*`) + every other tag in one compact JSON blob, so
  nothing is lost and the columns stay queryable.** _Impact: trend queries are column scans._
- (b) **The curated set only.** _Impact: smaller · a tag nobody thought of is gone._
- (c) **Every tag as a column.** _Impact: thousands of columns._

Default if blank: (a).

ANSWER Q810:

#### Q811 · Storage engine for the OSM rows and their history
- (a) ★ **DuckDB (the columnar store the app already ships) for objects, tags and tag-change rows;
  SQLite keeps the Place entity and its links.** _Impact: compressed columns; fast aggregates by country
  and tag._
- (b) **SQLite for everything.**

Default if blank: (a).

ANSWER Q811:

#### Q812 🔒 · The change feed (was Q54)
- (a) ★ **Geofabrik daily diffs per selected extract, applied to the ingested classes; if a diff older
  than the three-month retention is needed, re-baseline from a fresh extract and say so.** _Impact: a few
  MB to ~100 MB a day per country (FROM MEMORY)._
- (b) **Planet hourly/minutely diffs filtered locally.** _Impact: global volume for a few countries._
- (c) **Periodic full re-download and local diff.** _Impact: simplest · gigabytes per refresh._

Default if blank: (a).

ANSWER Q812:

#### Q813 · What counts as a change
- (a) ★ **Tag-level: for each object, each key added / removed / modified, with the diff's timestamp
  (and the object's `version`).** _Impact: "opening hours changed at 2,140 shops in Lyon this month" is a
  query._
- (b) **Object-level (changed / not).**

Default if blank: (a).

ANSWER Q813:

#### Q814 · History depth
- (a) ★ **From the day tracking starts, plus each object's `version`/`timestamp` from the extract as a
  coarse prior ("last edited 2023-04-12, version 7"); stated on every trend as "observed since <date>".**
- (b) **The full-history planet.** _Impact: >100 GB and a different reader; out._
- (c) **Also the ohsome API for pre-tracking aggregate history** — an external, consented call per query,
  enumerated in SECURITY.md. _Impact: trends reach back a decade the day the lane starts · a third-party
  service answers analytical questions (disclosed as such)._

Default if blank: (a). Multi-select allowed (a, c).

ANSWER Q814:

#### Q815 · The analytics that ship first (R16)
1 tag completeness per country / admin-1 (share of places with `opening_hours`, `website`, `email`,
`phone`) · 2 adoption trends of each metadata type over time · 3 openings and closures (objects appearing
/ disappearing, `disused:*`, `shop=vacant`, `opening_hours` set to closed) · 4 brand and chain footprint
by country · 5 contact-channel mix (site / phone / email / social) · 6 data freshness (`check_date`,
last-edit age) by area.
- (a) ★ **Confirm the six and the order (1–3 first).**
- (b) **Reorder / prune / add** — write it.

Default if blank: (a).

ANSWER Q815:

#### Q816 · The geography axis
- (a) ★ **Choropleths by alpha-3 and admin-1 on Equal Earth + the ranked table in full (the Observatory
  rule: the table is canonical), the vintage stated.**
- (b) **Countries only.**

Default if blank: (a).

ANSWER Q816:

#### Q817 · Which OSM objects become Articles (R13 "maps as articles")
- (a) ★ **Notable Places only — admin areas, `place=*` (cities, towns, villages), and any object carrying
  `wikidata`/`wikipedia` — become Articles with a body (Q818); every other POI stays a structured row with
  its own search facet ("Places"), and the aggregates surface as cards.** _Impact: tens of thousands of
  Articles per country, not millions._
- (b) **Every object an Article.** _Impact: millions of Articles; the corpus stops meaning anything._
- (c) **None** (OSM stays a data layer, never an Article).

Default if blank: (a).

ANSWER Q817:

#### Q818 · The Place entity and its article body (was Q55, Q58)
- (a) ★ **`Place(id = OSM type+id, qid, kind, admin path, names ×12, geometry ref, as_of)` with
  `article_mentioned_places` resolving into it; its body = the Wikidata/Wikipedia description + its OSM
  metadata rendered as metadata; keywords come from that text; it is searchable and indexed.**
- (b) **OSM tags only as the body.**

Default if blank: (a).

ANSWER Q818:

#### Q819 · Linking everything with a location onto the map (R17) — the order
1 Wikipedia page coordinates (`prop=coordinates` / Wikidata P625) → a map layer of the wiki lane · 2 OSM
objects tagged `wikidata`/`wikipedia` → the same Place as the wiki page · 3 press articles' mentioned
places → the gazetteer (exists) → Places · 4 free-text addresses in articles and wiki infoboxes → the
local OSM address index (Q820).
- (a) ★ **Confirm the order (1–2 in 0.4/0.5 with the wiki lane, 3 in 0.5, 4 in 0.6).**
- (b) **Reorder** — write it.

Default if blank: (a).

ANSWER Q819:

#### Q820 · A local geocoder from the ingested addresses
- (a) ★ **Yes, for the countries the user ingested, disclosed ("addresses outside your OSM countries are
  not located"); never an external geocoding service.** _Impact: effort M in 0.6._
- (b) **No address geocoding.**

Default if blank: (a).

ANSWER Q820:

#### Q821 · A street-level base map
- (a) ★ **None at beta: data views on Equal Earth, zoomable admin polygons, clustered points and heat;
  a place opens as a card, not a street map.** _Impact: the no-WebGL line holds._
- (b) **Self-rendered vector streets at high zoom from the ingested roads.** _Impact: effort XL · roads
  are the class Q809 leaves out._
- (c) **External tile servers.** _Impact: rejected — egress on every pan, and against the OSM tile policy._

Default if blank: (a).

ANSWER Q821:

#### Q822 · Rendering budgets under no-WebGL
- (a) ★ **Canvas 2D with published level-of-detail caps (points per view, polygon vertices per zoom),
  degrading to clusters, never to a frozen tab.**

Default if blank: (a).

ANSWER Q822:

#### Q823 ⛔ · ODbL (was Q51)
OSM-derived rows inside the corpus make an exported corpus, an evidence ZIP or a bulletin an
ODbL-affected work (attribution + share-alike on a derived database) — the same class as the CC BY-SA
Wikipedia text already ingested, and inside the V1-3 line.
- (a) ★ **Accept: attribution + the share-alike line at every point data leaves the machine.**
- (b) **Keep OSM out of exports and bulletins** (artifacts and rendering only).

Default if blank: none (⛔).

ANSWER Q823:

#### Q824 · Cadence and budget
- (a) ★ **Daily diff apply per selected extract inside the online consent; re-baseline when a diff gap
  exceeds the retention; the per-country cost shown before selection.**

Default if blank: (a).

ANSWER Q824:

#### Q825 · The OSM lane's database file and encryption
- (a) ★ **Same answers as the Wikipedia lane (Q719, Q720).**
- (b) **Different** — write it.

Default if blank: (a).

ANSWER Q825:

#### Q826 · Contested borders (was Q57)
- (a) ★ **Rendered CONTESTED with both claims, never a silent pick; confirm.**

Default if blank: (a).

ANSWER Q826:

#### Q827 · Place names in the twelve languages
- (a) ★ **OSM `name:xx` first, Wikidata labels as the fallback, the source shown in the hover.**
- (b) **Wikidata only.**

Default if blank: (a).

ANSWER Q827:

#### Q828 · Where the country picker lives
- (a) ★ **Settings → Data sources → Maps (invariant #8: data tabs show data, acquisition lives in
  Settings); the World map tab shows the vintage and a link there.**
- (b) **Inside the map tab.**

Default if blank: (a).

ANSWER Q828:

---

## §10 Laws (R14, R15)

**Context (VERIFIED, `src/law/`, `configs/legal_sources*.yml`).** 51 curated + 226 generated sources;
**24 documents → 23 registrable `LawDocument` rows** on a fresh install (uk 5, tl 6, eu 4, de 2, ca 2,
int 2, us 1, fr 1); only en, pt, de, fr have any tracked document; **es, ru, ar, zh, ja, hi, bn, id have
zero**. No enumeration anywhere (100 rows carry an unfetched `enumeration_url`). One adapter (CLML,
legislation.gov.uk), fixture-tested, never run on a fetched document; `diff_provisions` has no caller.
**No law-specific metadata model** (no ELI/CELEX/ECLI, no enacted/in-force/repealed dates persisted, no
issuing body, no amends relation); `jurisdiction` is a free `String(8)`. Only the latest text is an
Article; `LawRevision.full_text` is written and never read; diffs are **against the immutable baseline**;
the reader renders `baseline_text` (`api/law.py:417`) — a defect. 5 documents per pass; `[pdf]` optional
while 63 of 275 sources are PDF-only. Every priority portal is egress-blocked from the sandbox (Q114).
Rulings: A3 act/code level, provisions only for pre-split bulk sources; A4 adapter-first; A5 AI summaries
auto for UI-language jurisdictions (shipped). `configs/language_countries.yml` already maps each UI
language to its countries with a `basis` (official / de-facto / regional) — the elections floor.

**Open-data facts (SEARCH-VERIFIED):** legislation.gov.uk — API since 2010, XML/RDF by appending
`/data.xml`, Open Government Licence, crawling and bulk use explicitly welcomed. France — LEGI (consolidated
codes, laws, regulations), KALI, JORF free under Licence Ouverte at `echanges.dila.gouv.fr` (HTTPS/FTPS;
the daily-delta structure FROM MEMORY). Japan — the e-Gov Law API: GET, no key, XML (`lawlists`,
`lawdata`), Government Standard Terms of Use v2.0 (attribution, commercial use allowed). EU — Cellar is
public with a SPARQL endpoint; weekly RDF bulk on the EU Open Data Portal; **the "all acts in force per
language" dump requires an EU Login account**. EuroVoc: 24 EU languages (of ours: en, fr, de, es, pt),
XML/SKOS, one result says CC0 (confirm).

#### Q901 · What "formally translated" admits (R15)
- (a) ★ **An official translation by the issuing state or its designated body** (Japan's Japanese Law
  Translation, Germany's English translations at gesetze-im-internet, Switzerland's Fedlex English,
  Korea's law.go.kr English, Hong Kong's bilingual e-Legislation, Bangladesh's bdlaws in Bengali and
  English). _Impact: strict; every text carries state authority._
- (b) **Also translations published by intergovernmental bodies** (WIPO Lex, ILO NATLEX, FAOLEX, the UN
  Treaty Collection in six languages — ar, en, es, fr, ru, zh are all UI languages). _Impact: dozens more
  countries reachable through IP, labour, food and treaty law; the translation's authority is the body's,
  disclosed._
- (c) **Also any government's translation of another state's law** (e.g. a national law library's).
  _Impact: broadest · provenance becomes a per-document field the reader must see._

Default if blank: (b). Multi-select allowed.

ANSWER Q901:

#### Q902 · Document types in scope — *multi-select*
- (a) ★ **Constitutions, statutes and codes (consolidated).**
- (b) ★ **Regulations, decrees, ordinances (executive instruments).**
- (c) **Bills and drafts** (tracked as a separate lifecycle: proposed → adopted → in force).
- (d) **Treaties and international instruments** (jurisdiction `INT`).
- (e) **Case law** (courts; ECLI identifiers). _Impact: a different corpus shape (decisions, not versions);
  post-beta unless chosen._

Default if blank: (a, b, d).

ANSWER Q902:

#### Q903 · Levels
- (a) ★ **National + supranational (EU, OHADA's uniform acts for its 17 member states) through beta;
  subnational recorded for post-beta.**
- (b) **Subnational from 0.7** (US states, German Länder, Canadian provinces, Swiss cantons, Indian
  states). _Impact: an order of magnitude more sources and formats._
- (c) **All levels now.**

Default if blank: (a).

ANSWER Q903:

#### Q904 · Granularity (A3 stands)
- (a) ★ **Act / code level by default; per-provision rows for sources that arrive pre-split (LEGI, CLML,
  USLM, e-Gov XML, EUR-Lex Formex).**
- (b) **Provisions for everything via a per-language heuristic splitter.** _Impact: wrong splits on
  unstructured PDFs become permanent addresses._

Default if blank: (a).

ANSWER Q904:

#### Q905 · The versioning primitive
- (a) ★ **Point-in-time consolidated versions with `valid_from` / `valid_to` (the legislation.gov.uk and
  Légifrance model); an observed snapshot without official dating becomes a version dated by observation
  and labelled so.**
- (b) **Observed snapshots only** (today).

Default if blank: (a).

ANSWER Q905:

#### Q906 · The internal model
- (a) ★ **Akoma-Ntoso-lite: document → versions → provisions with stable addresses, plus a metadata block
  (ELI / CELEX / ECLI / act number, issuing body, dates, status, language, translation provenance,
  licence); one adapter per source format (CLML, LEGI XML, USLM, e-Gov XML, Formex/HTML, gesetze-im-internet
  XML, Akoma Ntoso itself where a portal serves it); text-only sources fill the same model with one
  provision.** _Impact: effort L across 0.4–0.5 · the one shape the evolution analytics can be built on._
- (b) **Plain text + heuristic splitter.** _Impact: cheap · no cross-source comparability._
- (c) **Hybrid.**

Default if blank: (a).

ANSWER Q906:

#### Q907 · The metadata fields (was Q60)
Proposed: official identifiers (ELI, CELEX, ECLI, act number, gazette reference) · title ×languages ·
issuing body · dates (enacted, published, commenced, in force, amended, repealed) · status (in force /
amended / repealed / draft) · legal system · jurisdiction (alpha-3 + level) · language + translation
provenance (original / official translation by X) · licence · source authority + URL · amends / amended-by
· topics (Q913).
- (a) ★ **Confirm.**
- (b) **Amend** — write it.

Default if blank: (a).

ANSWER Q907:

#### Q908 · One law in several languages
EU acts exist in 24 languages; Swiss, Canadian, Belgian, Hong Kong and Finnish law in two or more.
- (a) ★ **One document identity (CELEX/ELI), N language versions aligned by identity — no ring needed;
  the reader offers the language switch; cross-language search finds it through any version.**
- (b) **Separate documents per language.**

Default if blank: (a).

ANSWER Q908:

#### Q909 · Source strategy
- (a) ★ **Bulk open data first wherever it exists (LEGI, legislation.gov.uk, gesetze-im-internet XML,
  e-Gov API, US Code XML + govinfo, Canada's XML, Austria's RIS, Portugal's DRE API, Spain's BOE open data,
  Brazil's LexML), then enumeration adapters (crawl an index politely), then gazette feeds for countries
  with neither.** _Impact: complete and polite for the big jurisdictions · three pipeline kinds to maintain._
- (b) **Crawl-only.** _Impact: uniform code · slow, impolite at scale, incomplete._
- (c) **Gazette feeds only.** _Impact: cheap · no consolidated texts, so no evolution analysis._

Default if blank: (a).

ANSWER Q909:

#### Q910 · Account-gated bulk data (the EUR-Lex "acts in force" dump behind EU Login)
- (a) ★ **Treated as key-gated → excluded under V1-2; EU law comes through the open per-document API,
  the Cellar SPARQL endpoint and the weekly public RDF bulk.** _Impact: slower first fill · consistent
  with the no-keys ruling._
- (b) **Allowed as an operator-side manual download, never from the app.**

Default if blank: (a).

ANSWER Q910:

#### Q911 · The per-language seed list (FROM MEMORY — every row to be verified live before it enters a catalogue)
| UI lang | Candidate authoritative sources (open data / bulk noted) |
|---|---|
| en | legislation.gov.uk (OGL, XML) · US Code XML + govinfo bulk (public domain) · Canada Justice Laws (XML, en/fr) · Ireland (irishstatutebook.ie) · New Zealand (legislation.govt.nz, CC BY) · Australia (legislation.gov.au) · India Code (indiacode.nic.in) · South Africa (gov.za) · Kenya Law (kenyalaw.org) · Nigeria · Singapore (sso.agc.gov.sg) · Hong Kong e-Legislation (zh/en) · EUR-Lex |
| fr | LEGI/JORF (Licence Ouverte, bulk) · Belgium (ejustice) · Switzerland Fedlex (API; de/fr/it) · Luxembourg (legilux) · Canada · Québec (LégisQuébec) · OHADA uniform acts (17 states) · Senegal, Côte d'Ivoire, Cameroon, Mali, Burkina Faso, Niger, Togo, Benin, Gabon, Congo, DR Congo, Madagascar (official journals; JuriBurkina/JuriNiger LIIs) · Morocco, Tunisia, Algeria (fr + ar bulletins) · Haiti |
| es | Spain BOE (open data) · Mexico (diputados.gob.mx federal laws) · Argentina (InfoLEG / SAIJ) · Chile (BCN Ley Chile, open) · Colombia (SUIN-Juriscol) · Peru (SPIJ) · Ecuador, Bolivia, Uruguay, Paraguay, Venezuela · Central America · Cuba · Dominican Republic |
| de | gesetze-im-internet (XML; official EN translations) · Austria RIS (open data, API) · Switzerland Fedlex · Liechtenstein (gesetze.li) · Luxembourg, Belgium (de) |
| pt | Portugal DRE (API, open) · Brazil Planalto + LexML + Senado normas · Angola, Mozambique, Cape Verde, Guinea-Bissau, São Tomé, Timor-Leste (already 6 docs), Macau (zh/pt) |
| ru | pravo.gov.ru (official publication) · Belarus pravo.by · Kazakhstan adilet.zan.kz (ru/kk) · Kyrgyzstan, Tajikistan (ru versions) |
| zh | flk.npc.gov.cn (the national law database) · Hong Kong e-Legislation · Taiwan law.moj.gov.tw (zh + official EN) · Macau · Singapore (zh versions) |
| ja | e-Gov 法令検索 API (XML, no key) · Japanese Law Translation (official EN) |
| ar | Saudi laws.boe.gov.sa (ar/en) · UAE uaelegislation.gov.ae (ar/en) · Qatar Almeezan (ar/en) · Jordan, Egypt, Lebanon, Iraq, Kuwait, Bahrain, Oman · Morocco / Tunisia / Algeria (ar) · the UN Treaty Collection (ar) |
| hi | India Code (Hindi versions of central acts) · legislative.gov.in · Indian states with Hindi as official |
| bn | Bangladesh bdlaws.minlaw.gov.bd (bn + en) · West Bengal (bn) |
| id | Indonesia JDIH network / peraturan.go.id · peraturan.bpk.go.id |
| INT | UN Treaty Collection (6 langs) · WIPO Lex · ILO NATLEX · FAOLEX · EUR-Lex · OHADA |
- (a) ★ **Take this as the 0.6 verification worklist** (each row verified live: reachability, robots,
  licence, format), nothing enters a catalogue unverified.
- (b) **Prune / add** — write it in a NOTE.

Default if blank: (a).

ANSWER Q911:

#### Q912 · The coverage floor and the order of work (was Q63)
- (a) ★ **Floor = every country in `language_countries.yml` (official / de-facto / regional bases all
  count, labelled); order = sources serving many countries first (EU, OHADA, UN/WIPO), then by population
  reached.** _Impact: the elections floor and the law floor are one file._
- (b) **Order by language: en → fr → es → de → pt → ru → zh → ja → ar → id → hi → bn.**
- (c) **Your own list** — write it.

Default if blank: (a).

ANSWER Q912:

#### Q913 · Topic classification for "evolution over geography"
Comparing "asylum law" across countries needs a topic that is not a word.
- (a) ★ **EuroVoc concepts (en/fr/de/es/pt), reached in the other seven languages through Wikidata's
  EuroVoc-ID property (P5437, FROM MEMORY) and the keyword rings; assigned by rules over titles and
  provisions, ≈ where the LLM proposes one.** _Impact: effort M · a multilingual legal taxonomy the EU
  maintains._
- (b) **Keyword rings only.**
- (c) **LLM topic tags only (≈).**

Default if blank: (a).

ANSWER Q913:

#### Q914 · The evolution analytics that ship first (was Q62)
1 per-provision diff timeline · 2 amendment velocity per jurisdiction over time · 3 cross-jurisdiction
comparison by topic ("who changed data-protection law in 2026") · 4 an Equal Earth map of amendment
activity with the vintage stated · 5 "what changed this week in the laws I follow".
- (a) ★ **Confirm the five (1–2 in 0.4 on the small corpus, 3–5 in 0.5).**
- (b) **Reorder / prune** — write it.

Default if blank: (a).

ANSWER Q914:

#### Q915 · Change cadence per source class
- (a) ★ **Daily for gazettes and bulk deltas; weekly for consolidated portals without deltas; on-demand
  for a document the user opens; every fetch within the adaptive per-pass budget and the host's politeness.**

Default if blank: (a).

ANSWER Q915:

#### Q916 · Point-in-time search (was Q61)
- (a) ★ **FTS over versions with `valid_on`, so "what did this say in 2019" works without an Article per
  version.**
- (b) **One Article per version.**
- (c) **Latest only.**

Default if blank: (a).

ANSWER Q916:

#### Q917 · The L0 defects first (was Q59)
The reader shows `latest_text` with a version selector; diffs run against the previous revision (the
baseline diff kept as a derived view); the adapter's three dates are persisted.
- (a) ★ **Confirm, in 0.4 before anything else in this section.**

Default if blank: (a).

ANSWER Q917:

#### Q918 · The reader
- (a) ★ **Version selector · side-by-side diff · provision navigation · an ELI/CELEX permalink · the
  licence line · "AI-derived · unreliable" on summaries · translation provenance where applicable.**
- (b) **Amend** — write it.

Default if blank: (a).

ANSWER Q918:

#### Q919 · Authorities as Source rows
- (a) ★ **Each law authority is a `Source` row with `source_type="law"`, so the Sources tab, coverage and
  qualification see it like any other source.**
- (b) **Kept apart from the sources catalogue.**

Default if blank: (a).

ANSWER Q919:

#### Q920 · AI (was Q66)
- (a) ★ **Summaries only, ≈, "AI-derived · unreliable"; dates, provisions and identifiers come from rules,
  never from the model.**

Default if blank: (a).

ANSWER Q920:

#### Q921 · Q-LAW-1 `counts_documents`
- (a) ★ **Declare `counts_documents` per official count so the coverage diagnostic can divide where units
  are commensurable and refuse where not.**
- (b) **Leave the diagnostic refusing everywhere.**

Default if blank: (a).

ANSWER Q921:

#### Q922 · Q-LAW-2 / L6 — `[pdf]` in the default install
- (a) ★ **Yes: 63 of 275 sources are PDF-only.**
- (b) **Keep optional.**

Default if blank: (a).

ANSWER Q922:

#### Q923 · Q-LAW-3 — the 44-row vetting board
- (a) ★ **Run it as the 0.4 law operator step.**
- (b) **Skip.**

Default if blank: (a).

ANSWER Q923:

#### Q924 · Q-LAW-4 — a verification tier for law endpoints
- (a) ★ **Yes: each source carries `verified: live | fixture | unverified` with a date; the UI shows it.**
- (b) **No.**

Default if blank: (a).

ANSWER Q924:

#### Q925 ⛔ · Adapter order and the first managed dataset (was Q65)
- (a) ★ **legislation.gov.uk (CLML, exists) → gesetze-im-internet (XML) → e-Gov (XML API) → EUR-Lex
  (per-document) → LEGI (the first bulk dataset with daily deltas — the wiki-dump precedent applied to
  law).** _Impact: each adapter live-verified the day Q114 opens the host, fixture-exercised before._
- (b) **LEGI first** (the largest corpus in force, ~10⁵ articles). _Impact: the bulk path before the
  adapter pattern is proven._
- (c) **Your order** — write it.

Default if blank: none (⛔).

ANSWER Q925:

#### Q926 · The law lane's database file and encryption
- (a) ★ **Same answers as the Wikipedia lane (Q719, Q720).**
- (b) **Different** — write it.

Default if blank: (a).

ANSWER Q926:

#### Q927 · Licence per document
- (a) ★ **Recorded per document (OGL, Licence Ouverte 2.0, Japan's Standard Terms, the EU reuse notice, US
  public domain, …), shown in the reader, and stated at every export point (Q1008); a source whose terms
  forbid redistribution is excluded under V1-3.**

Default if blank: (a).

ANSWER Q927:

#### Q928 · Subnational law
- (a) ★ **Post-beta backlog (Q118) unless Q903 = (b) or (c).**

Default if blank: (a).

ANSWER Q928:

#### Q929 · Case law
- (a) ★ **Post-beta backlog** (a different corpus shape).
- (b) **0.7** (with ECLI as the identity).

Default if blank: (a). Depends on: Q902 (e).

ANSWER Q929:

#### Q930 · Treaties and international instruments
- (a) ★ **0.6, as jurisdiction `INT` — the UN Treaty Collection (six UI languages at once) and WIPO Lex are
  the highest-yield multilingual sources on the list.**
- (b) **Later.**

Default if blank: (a). Depends on: Q902 (d).

ANSWER Q930:

---

## §11 Cross-cutting — architecture, storage, security, budgets

**Context (VERIFIED).** Items 6, 7 and 8 ask for the same thing three times: an external, mutable,
authoritative corpus ingested as Articles with metadata, tracked for changes, the changes analysable. The
intake §4.1 proposed one substrate (`src/versioned/`): identity `(kind, external_id)` + QID · immutable
baseline · a change feed with cursor, gap detection, budget and politeness · a revision store (metadata for
every change, text/geometry for ingested versions, diff vs previous) · the latest as an Article · point in
time · disclosure · one Living sources view · one diagnostics member per kind · backups as opt-in members.
`docs/SECURITY.md` §"the full set of endpoints the app can reach" (re-verified 2026-09-08) **omits** the
Wikidata Query Service the default-on discovery ride-along reaches (`discover.py:36–41`), the Wikipedia
Action API, ORES, the Wikimedia dumps host and the OSM mirrors. The columnar DuckDB store exists (CI lane
"Columnar store (DuckDB rollup + D1 persisted-httpfs)"). The reference VM is 2 cores / 3.5 GB; the
collector indexes ~2.3 articles/s on one core (audit 12). Four storage round-2 rulings are pending
([`STORAGE_RULINGS_ROUND2_2026-09-07.md`](STORAGE_RULINGS_ROUND2_2026-09-07.md) rows 3–6).

#### Q1001 · `docs/SECURITY.md` enumeration (was Q67)
- (a) ★ **Complete it now as a docs-only PR; from then on every PR adding a host adds it there and to the
  consent popup's hover in the same diff (a repo test greps the fetch sites against the list).**
- (b) **With 0.4.**

Default if blank: (a).

ANSWER Q1001:

#### Q1002 · The consent popup and the lanes
- (a) ★ **The one popup stays; its hover lists, per lane, the hosts it will contact (Wikimedia ×4, the OSM
  mirrors, the law authorities of the countries chosen); the popup's body names the lanes that are on.**
- (b) **One popup per lane.** _Impact: consent fatigue; the ruling is ONE popup._

Default if blank: (a).

ANSWER Q1002:

#### Q1003 · One versioned-source substrate (was Q68)
- (a) ★ **`src/versioned/` shared by the wiki, law and OSM lanes, the wiki adapter first.**
- (b) **Three implementations.**

Default if blank: (a).

ANSWER Q1003:

#### Q1004 🔒 · One database file per lane (the general rule)
- (a) ★ **Yes: `corpus.db` (press, as today) + `wiki.db` + `osm.db` + `law.db`, each encrypted alike,
  each an opt-in backup member, linked by ids.**
- (b) **One file.**

Default if blank: (a). (Q719/Q825/Q926 inherit this unless they say otherwise.)

ANSWER Q1004:

#### Q1005 🔒 · Encryption of the public-data lanes (the general rule)
- (a) ★ **Encrypted, same passphrase, same threat model, because the selection reveals interests.**
- (b) **A per-lane plaintext option, disclosed.**

Default if blank: (a).

ANSWER Q1005:

#### Q1006 · A data-budget surface
- (a) ★ **Settings → Storage shows each lane's size, its budget, the honest arithmetic ("at your current
  rate this lane grows ~2 GB/month"), and the disk left; budgets are published defaults sized for the
  reference VM.**
- (b) **No budgets; the user watches the disk.**

Default if blank: (a).

ANSWER Q1006:

#### Q1007 · DuckDB for the high-volume lane tables
- (a) ★ **Wiki per-edit rows, OSM objects/tags/changes, law provision versions in DuckDB; entities and
  links in SQLite.**
- (b) **SQLite for everything.**

Default if blank: (a).

ANSWER Q1007:

#### Q1008 · Licence statements where data leaves the machine
- (a) ★ **Every export, bulletin and evidence ZIP carries the attribution lines that apply (CC BY-SA 4.0
  Wikipedia, ODbL OSM, per-law licences, DB-IP CC BY) and, for OSM-derived rows, the share-alike note.**

Default if blank: (a).

ANSWER Q1008:

#### Q1009 ⛔ · The storage round-2 rulings (register C4; rows 3–6) — answer each as `a/b` in order, e.g. `y, OOENC2, y, y`
- **Row 3 — blob-store dedup ON?** (y ★ / n)
- **Row 4 — pack AEAD: OOENC2 ★ or `age`?**
- **Row 5 — keyed-HMAC blob addressing + opaque pack names?** (y ★ / n)
- **Row 6 — authorise the sqlite3mc benchmark trial (benchmark only, no migration)?** (y ★ / n)

Default if blank: none (⛔).

ANSWER Q1009:

#### Q1010 · The reference-VM policy
- (a) ★ **Every budget is published and sized for the 2-core / 3.5 GB VM by default; power users raise
  them; nothing silently assumes the maintainer's machine.**

Default if blank: (a).

ANSWER Q1010:

#### Q1011 · Hardware-profile detection
- (a) ★ **The app reads cores, RAM and free disk at boot (no network), proposes budgets from a published
  table, and shows the reading.**
- (b) **Fixed defaults only.**

Default if blank: (a).

ANSWER Q1011:

#### Q1012 · The per-job bandwidth cap (invariant #20's recorded omission)
- (a) ★ **A per-PROCESS budget composed with the collection-speed governor (`#rate-toggle`), never a second
  rate authority beside it; per-job caps stay omitted.**
- (b) **Per-job caps.**
- (c) **Keep omitting it.**

Default if blank: (a).

ANSWER Q1012:

#### Q1013 · The Crawl-delay cap (the 2026-09-10 pending ruling)
- (a) ★ **Persist a per-host next-allowed-at beside the robots cache; refuse an inline wait beyond a few
  minutes with a named deferral counted as its own bucket; the ride-along and trial fetch inherit both.**
- (b) **Leave the unbounded inline sleep.**

Default if blank: (a).

ANSWER Q1013:

#### Q1014 · Transport per lane
- (a) ★ **Each lane declares its transport in the consent hover; a lane never downgrades Tor → clearnet
  without the explicit consent the non-negotiable requires (Q722's walk waits instead).**

Default if blank: (a).

ANSWER Q1014:

#### Q1015 · New dependencies
- (a) ★ **Compiled code only in optional extras (`[geo]` = pyosmium); pure Python in core (`simplemma`);
  SSE hand-rolled over the guarded session (no new client library); every addition registered in
  `configs/external_artifacts.yml`.**
- (b) **Amend** — write it.

Default if blank: (a).

ANSWER Q1015:

#### Q1016 · The Living sources view (was Q47)
- (a) ★ **One view for wiki / law / OSM: timeline of changes, diff, coverage, freshness, budget; replaces
  the tracked-changes modal; a main tab or a Home family — your call in a NOTE.**
- (b) **Per-kind surfaces.**

Default if blank: (a).

ANSWER Q1016:

#### Q1017 · KPI bars for the lanes
- (a) ★ **Measured first (V1-6): each lane ships its coverage/freshness resolver; bars are set only after a
  release has recorded values.**

Default if blank: (a).

ANSWER Q1017:

#### Q1018 · CI fixtures for the lanes
- (a) ★ **A synthetic wiki edition, a synthetic OSM extract and a synthetic jurisdiction in `tests/fixtures/`,
  so every lane's pipeline runs end-to-end in CI without a socket.**

Default if blank: (a).

ANSWER Q1018:

#### Q1019 · The Windows lane and the new lanes
- (a) ★ **`pyosmium` wheels exist for Windows (FROM MEMORY); the lanes are in the Windows CI matrix from
  the release they land in, blocking at 0.9 per V1-5.**

Default if blank: (a).

ANSWER Q1019:

#### Q1020 · The `mode` retirement and the scheduler shape
- (a) ★ **The scheduler runs lanes (press, wiki, osm, law, hazards, discovery) under one online consent
  with one governor and per-lane budgets; the `mode` setting is retired with a migration.**
- (b) **Keep modes.**

Default if blank: (a).

ANSWER Q1020:

---

## §12 The standing docket — every other open ruling, in one place

These are the rulings still open in the 2026-09-06 register, the 2026-09-08 visual audit and the
2026-09-11 institutions docket, compressed to what a decision needs. The full argument for each is at the
place cited. Answer, `later`, or leave the default.

#### Q1101 ⛔ · `enabled` vs `qualified`, and the `scrape_unqualified` hatch (register B1)
~42 k disabled candidates are trial-fetched over Tor for a verdict with no collection effect; the runner
also carries a `scrape_unqualified` setting relaxing `status == qualified` to `status != disqualified`.
- (a) **A `qualified` verdict flips `enabled=True`** (qualification IS the admission gate; the per-pass
  hardware budget bounds Tor use; the audit view's undo is the safety valve) **and the hatch is retired.**
- (b) **Restrict trials to `enabled=True` sources; the hatch is retired.**
- (c) **(a) and keep the hatch as an operator-only, disclosed setting.**

Default if blank: none (⛔).

ANSWER Q1101:

#### Q1102 ⛔ · What identifies a source — a domain or a feed (register B11)
475 of 3,870 seeded entries are shadowed by a same-domain sibling; 75 are language services (BBC Arabic,
DW Español…) that differ only by feed path, and 192 carry `lean-*` tags the survivor lacks.
- (a) **Leave it, count visible, ratchet holds** (one feed per outlet).
- (b) **Key a source on its FEED** — a migration + data-safety review reaching the alias dedup, the
  restore-merge joins, the overlay, the citations tally. _Impact: effort L · recovers the language
  services, which is the mission case._
- (c) **Split the few genuinely distinct hosts only** (cannot recover the language services).

Default if blank: none (⛔).

ANSWER Q1102:

#### Q1103 · Triage-derived stoplist additions (register B2, narrowed 2026-09-11)
- (a) ★ **May merge into `configs/stopwords_extra` after a review, versioned and registry-tracked.**
- (b) **Never; the shipped stoplists are frozen.**

Default if blank: (a).

ANSWER Q1103:

#### Q1104 · The English (11,263) + French (881) triage proposals into the GLOBAL channel (B3)
- (a) ★ **Yes, through the review surface, batch by batch.**
- (b) **No.**

Default if blank: (a). Depends on: Q1103.

ANSWER Q1104:

#### Q1105 · The 64,910 `kind_overrides` proposals (~50% precision) (B4)
- (a) ★ **A worklist for a review surface; never auto-applied.**
- (b) **Discard.**

Default if blank: (a).

ANSWER Q1105:

#### Q1106 · `configs/source_qualification.yml` — the operator loop UI (B5)
- (a) ★ **Ship the overlay editor (adopt / export / revert) in Settings.**
- (b) **File-only.**

Default if blank: (a).

ANSWER Q1106:

#### Q1107 · `PATHOLOGY_ABS_FLOOR` (0.5) unreachable in the field (B6)
- (a) ★ **Keep 0.5, record it as unreachable, let the measured criteria decide.**
- (b) **Lower it** — write the value.

Default if blank: (a).

ANSWER Q1107:

#### Q1108 · A recency-windowed re-check (B7)
- (a) ★ **The 6-month re-verification reads the last 6 months, not the whole history.**
- (b) **Whole history.**

Default if blank: (a).

ANSWER Q1108:

#### Q1109 · Where a research institute belongs (institutions B1)
- (a) ★ **`official_sources.yml` with `source_type: academic-research`, tagged `research` /
  `research-institute`.**
- (b) **`academic_sources.yml`.**

Default if blank: (a).

ANSWER Q1109:

#### Q1110 · The `primary_source` axis (institutions B2)
- (a) ★ **Defer-not-reject now; rewrite the axis as an observable ("publishes dated official
  instruments?") checkable against headlines.**
- (b) **Keep the judgement axis with the 84.7% two-judge agreement as its calibration.**

Default if blank: (a).

ANSWER Q1110:

#### Q1111 · The 16 mis-shelved journals (institutions B3)
- (a) ★ **Move them to `academic_sources.yml`.**

Default if blank: (a).

ANSWER Q1111:

#### Q1112 · A content-integrity signal near the app (institutions B4)
- (a) **Stay in the analysis kit.**
- (b) ★ **Flag at admission: a candidate tripping `restricted_namespace` cannot be spliced without a
  written override; never a silent drop.**
- (c) **Also re-check admitted sources periodically** (a recurring fetch for a reason the user did not
  ask for — needs its own consent story; design before code).

Default if blank: (b).

ANSWER Q1112:

#### Q1113 ⛔ · The compromised embassy platforms (institutions B5)
Ten of thirteen `embajada.gob.ve` missions, two Indonesian district courts and `usf.gov.jm` serve gambling
copy on restricted government namespaces. We found it; we are not the affected party.
- (a) **Exclude them and say nothing.**
- (b) **Publish the list as research** (it is a fact about public web content; the CSV is committed).
- (c) **Attempt responsible disclosure to each body** (initiating contact with foreign government bodies —
  outside anything the ethics section contemplates).

Default if blank: none (⛔).

ANSWER Q1113:

#### Q1114 · Which "source count" is THE number (institutions C3)
- (a) ★ **`enabled AND qualified` everywhere a headline count is shown; the other predicates are labelled
  where they appear.**
- (b) **Another** — write it.

Default if blank: (a).

ANSWER Q1114:

#### Q1115 · Country-vs-domain audit (institutions C7)
- (a) ★ **A diagnostic proposes corrections for review; never an automatic ccTLD rule.**

Default if blank: (a).

ANSWER Q1115:

#### Q1116 · Bare QID names (institutions C8)
- (a) ★ **Resolve the label at the polite rate or decline to admit the row.**

Default if blank: (a).

ANSWER Q1116:

#### Q1117 · The 116 Czech municipalities on one CMS (institutions C9)
- (a) ★ **Admit them, tagged with the vendor path so a supplier outage is one visible cause; the balance
  shift disclosed in the splice report.**
- (b) **Cap per country per splice.**
- (c) **Exclude.**

Default if blank: (a).

ANSWER Q1117:

#### Q1118 · The three unrun worklists (institutions D2)
- (a) ★ **Run the shortlist (3,031) next; the remainder and the religious lists after the splice is
  reviewed.**
- (b) **Run all three.**
- (c) **Stop the pipeline here.**

Default if blank: (a).

ANSWER Q1118:

#### Q1119 · The Stage B splice (institutions D3)
- (a) ★ **Admit the rows where both judges agree; defer the ~15% contested band.**
- (b) **Hold everything until B2 (Q1110) is rebuilt as an observable.**

Default if blank: (a).

ANSWER Q1119:

#### Q1120 · The information architecture (Q-VIS-1)
- (a) ★ **"Rings, not gates" as the spine (a Ring controls what is pinned, never what is reachable) with
  the two grafts from "Works while you sleep".**
- (b) **"Works while you sleep".**
- (c) **The task-first / verb-first angle** (unjudged).
- (d) **Keep the current shell.**

Default if blank: (a).

ANSWER Q1120:

#### Q1121 · The skipped-first-run default (Q-VIS-2)
- (a) ★ **Standard (Ring 1) when the depth question is skipped; Essentials only by explicit choice.**
- (b) **Essentials.**

Default if blank: (a).

ANSWER Q1121:

#### Q1122 · Help's body (Q-VIS-3)
- (a) ★ **An explicit exception: the Help body is English-by-design with a translated banner saying so
  ×12; the chrome rule is unchanged.** _Amends: the "every user-facing string ×12" non-negotiable, by
  stated exception._
- (b) **Translate the 167,022-character body ×12** (~2 M characters).

Default if blank: (a).

ANSWER Q1122:

#### Q1123 · The theme catalogue (Q-VIS-4)
- (a) ★ **Keep 17; invariant #12 unchanged.**
- (b) **Cull the near-duplicates to ≥ 10 with an amendment to invariant #12.**

Default if blank: (a).

ANSWER Q1123:

#### Q1124 · The Patterns lens field-validation bar (Q-VIS-6)
- (a) ★ **Flip on only when the corpus is ≥ 100 k articles and a labelled sample shows a false-positive
  rate ≤ 5%; both numbers on the toggle.**
- (b) **Stay off until 1.0.**
- (c) **Other numbers** — write them.

Default if blank: (a).

ANSWER Q1124:

#### Q1125 · `#net-coach` emphasis (Q-VIS-7)
- (a) ★ **Both actions carry equal visual weight; "Not now" is not quieter than "Go online".**
- (b) **Keep.**

Default if blank: (a).

ANSWER Q1125:

#### Q1126 ⛔ · The airplane toggle's two titles (register M2)
- (a) ★ **Align the task-manager title to the stronger, true claim ("every new network request will be
  refused"), re-translated ×12.**
- (b) **Keep both.**

Default if blank: none (⛔ — consent copy).

ANSWER Q1126:

#### Q1127 · Inline handlers and the CSP (register H4: 613 handlers, growing ~4% in five days)
- (a) ★ **Fund a retirement slice in 0.5 with a ratchet that fails on any new inline handler; drop
  `'unsafe-inline'` when it reaches zero.**
- (b) **Later.**

Default if blank: (a).

ANSWER Q1127:

#### Q1128 · The verification bar (register H2 = L2)
- (a) ★ **Chromium in the sandbox + your click-through = verified; Gecko stays best-effort.**
- (b) **Gecko required for "verified".**

Default if blank: (a).

ANSWER Q1128:

#### Q1129 · The political-lean scale (register L9)
- (a) ★ **Keep the stance: reported, never filtered.**
- (b) **Remove the scale.**

Default if blank: (a).

ANSWER Q1129:

#### Q1130 · Non-topical vocabulary (register L10)
- (a) ★ **Filter only the `via:*` provenance prefixes from topical displays; keep the rest reported.**
- (b) **Keep all.**

Default if blank: (a).

ANSWER Q1130:

#### Q1131 · Bulletin mail sending (register D3)
- (a) ★ **Never.**
- (b) **Opt-in later, off Tor, credentials never stored** (see Q1138).

Default if blank: (a).

ANSWER Q1131:

#### Q1132 · Model-weights pin (register D6)
- (a) ★ **Pin digests in the external-artifact registry; the pull verifies them.**
- (b) **Unpinned.**

Default if blank: (a).

ANSWER Q1132:

#### Q1133 · IPCC as a source (register G4)
- (a) ★ **AR6 Summaries for Policymakers first; `pypdf` acceptable.**
- (b) **Other** — write it.

Default if blank: (a).

ANSWER Q1133:

#### Q1134 · Open-Meteo layer (register G7)
- (a) ★ **Temperature and precipitation first; 1991–2020 baseline; soil moisture later.**
- (b) **Other** — write it.

Default if blank: (a).

ANSWER Q1134:

#### Q1135 · Religious calendars and the eclipse canon (register G8)
- (a) **You will provide the dates** (as ruled 2026-06-17).
- (b) **Drop the feature.**
- (c) ★ **Derive from published astronomical/calendar algorithms with the method stated, no external call.**

Default if blank: (c).

ANSWER Q1135:

#### Q1136 · App self-update (register G9)
- (a) ★ **Tags only, signed releases, an opt-in check that is consented like any egress, never
  auto-install.**
- (b) **Other** — write it.

Default if blank: (a).

ANSWER Q1136:

#### Q1137 · Stored mailbox credentials (register I1)
- (a) ★ **Never stored; each pull asks.**
- (b) **OS keyring, opt-in, disclosed.**

Default if blank: (a).

ANSWER Q1137:

#### Q1138 · Tor-exit-resolve and `oo-netcut` / Stem (register I3, I4)
- (a) ★ **Parked until 0.9's security review.**
- (b) **Build in 0.6.**

Default if blank: (a).

ANSWER Q1138:

#### Q1139 · `src/api/diagnostics.py` (6,200 lines / 126 routes) (register J1)
- (a) ★ **Authorise the mechanical split into a package, routes unchanged.**
- (b) **Leave.**

Default if blank: (a).

ANSWER Q1139:

#### Q1140 · SQLite-only, documented (register J3)
- (a) ★ **Document SQLite-only and remove the Postgres parity stubs.**
- (b) **Keep parity as an aspiration.**

Default if blank: (a).

ANSWER Q1140:

#### Q1141 · `docs/FUTURE_DEVELOPMENTS.md` reality-check depth (register A4)
- (a) ★ **Full: every section re-checked against the tree, stale claims corrected.**
- (b) **Only the sections this roadmap touches.**

Default if blank: (a).

ANSWER Q1141:

#### Q1142 · The multi-model specialisation bench (register D8)
- (a) ★ **Run it when the AI-coordinator translation sweep (Q405) lands in 0.5.**
- (b) **Drop.**

Default if blank: (a).

ANSWER Q1142:

#### Q1143 · Live ollama.com library browse (register D9)
- (a) ★ **Consented, opt-in, egress named.**
- (b) **Never.**

Default if blank: (a).

ANSWER Q1143:

#### Q1144 · Perception extraction languages (register D10)
- (a) ★ **Enable per language only where the measured gate passes; `who` stays refused where it fails.**

Default if blank: (a).

ANSWER Q1144:

#### Q1145 · Wiktextract (register E3)
- (a) ★ **Exclude** (a CC BY-SA 3.0/4.0 revision mixture).
- (b) **Include a 4.0-only subset if one can be isolated.**

Default if blank: (a).

ANSWER Q1145:

#### Q1146 · The SKOS thesaurus family (register E4)
- (a) ★ **Adopt EuroVoc + the UNESCO Thesaurus (ar/en/fr/ru/es) + AGROVOC + IPTC Media Topics for topic
  tagging, tied to Q913.**
- (b) **No.**

Default if blank: (a).

ANSWER Q1146:

#### Q1147 · Official-statistics breadth, 29 of ~152 agencies (register G5)
- (a) ★ **A networked session builds the directory; `news_url` per agency verified live.**
- (b) **Later.**

Default if blank: (a).

ANSWER Q1147:

#### Q1148 · The guarded-route rate limit, 100/hour (register L4)
- (a) ★ **Raise it for loopback UI calls (1,000/hour), keep 100 for anything else.**
- (b) **Keep.**

Default if blank: (a).

ANSWER Q1148:

#### Q1149 · The synthetic click-through corpus runs plaintext (register L7)
- (a) ★ **Add an encrypted variant to the runner.**
- (b) **Keep plaintext.**

Default if blank: (a).

ANSWER Q1149:

#### Q1150 · The ooMap embed on When/Where (register M3)
- (a) ★ **Keep.**
- (b) **Remove.**

Default if blank: (a).

ANSWER Q1150:

#### Q1151 · The newsletter attach go-ahead (register M4)
- (a) ★ **Go** (ruled in principle; this is the go-ahead because it moves data).
- (b) **Hold.**

Default if blank: (a).

ANSWER Q1151:

#### Q1152 · The i18n remainder, 470 strings (register M5)
- (a) ★ **Fund it in 0.4.**
- (b) **0.9.**

Default if blank: (a).

ANSWER Q1152:

#### Q1153 · Intensive indicators with no exact weighting (register G11)
- (a) ★ **Population-weighted with the weighting disclosed on the figure.**
- (b) **Unweighted mean, disclosed.**

Default if blank: (a).

ANSWER Q1153:

#### Q1154 · The rulings artifact's lone answer (was Q69)
The "Open Omniscience Rulings" artifact recorded `A2: default` at 2026-09-12T07:37Z.
- (a) **That was me; record A2 at its default.**
- (b) ★ **Not me; ignore it.**

Default if blank: (b).

ANSWER Q1154:

#### Q1155 · Ratify the defaults taken autonomously since 2026-09-07
PROMPT_20's four questions answered on their recommended defaults; M1's two items closed on their own.
- (a) ★ **Ratify all.**
- (b) **Ratify all except** — write the exceptions.

Default if blank: (a).

ANSWER Q1155:

#### Q1156 · The airplane-mode field bar and the 2026-09-10 "shuffle" finding
Singleton language strata put the same twelve sources at the head of every pass on every instance.
- (a) ★ **Keep the stratified round-robin (the ruled equilibrium lever) and randomise the order of the
  singleton strata across passes.**
- (b) **Keep as is.**

Default if blank: (a).

ANSWER Q1156:

#### Q1157 · G10 — the earlier Wikipedia questions 1–5
- (a) ★ **Superseded by §8 of this sheet.**

Default if blank: (a).

ANSWER Q1157:

---

## §13 Process — how the answers become rulings, and how we keep from restating

#### Q1201 · Where the answered sheet lives
- (a) ★ **This file, overwritten in place with your answers, is the primary record; the OPEN_QUEUE entry
  is the index.**
- (b) **A separate `…_ANSWERED.md` beside the blank one.**

Default if blank: (a).

ANSWER Q1201:

#### Q1202 · How the rulings are recorded
- (a) ★ **One OPEN_QUEUE entry indexing every question ID with the chosen option's label verbatim and your
  note; `CLAUDE.md` amendments only for non-negotiables and UI invariants (each marked `Amends:` above);
  tests extended where an invariant is testable.**
- (b) **Per-theme entries.**

Default if blank: (a).

ANSWER Q1202:

#### Q1203 · Blanks
- (a) ★ **A blank non-⛔ question takes its default, recorded as an ASSUMPTION you may reverse at any time;
  a blank ⛔ stays pending.**
- (b) **A blank is a `later`.**

Default if blank: (a).

ANSWER Q1203:

#### Q1204 · The second half of the plan
- (a) ★ **Gate files for 0.4–0.9 (Q112) and the slice briefs (Q113) written in one session from the
  answered sheet, as one docs PR.**
- (b) **Per release, when each starts.**

Default if blank: (a).

ANSWER Q1204:

#### Q1205 · The rulings artifact
- (a) ★ **Retire it; the markdown sheet is the channel.**
- (b) **Keep both.**

Default if blank: (a).

ANSWER Q1205:

#### Q1206 · A rulings index
- (a) ★ **Create `docs/ledger/RULINGS_INDEX.md` — one line per ruling (id · date · ruling · source · where
  enforced) — maintained under THE PROTOCOL, so nothing is restated.**
- (b) **The OPEN_QUEUE entries suffice.**

Default if blank: (a).

ANSWER Q1206:

#### Q1207 · This format as the standard
- (a) ★ **Future question rounds use this sheet format (IDs, options with impact, defaults, ANSWER lines,
  a processing protocol).**
- (b) **No.**

Default if blank: (a).

ANSWER Q1207:

#### Q1208 · Anything else you decided while reading
Write it here as `NOTE:` lines. Each becomes a ruling recorded verbatim.

ANSWER Q1208:

---

## §14 Index

| Block | IDs | Count | ⛔ | 🔒 |
|---|---|---|---|---|
| §1 recorded rulings | Q001 | 1 | — | — |
| §2 the train | Q101–Q118 | 18 | Q101, Q114 | — |
| §3 import / export | Q201–Q222 | 22 | Q215, Q216 | — |
| §4 alpha-3 | Q301–Q314 | 14 | Q301 | — |
| §5 keyword translation | Q401–Q418 | 18 | Q406 | Q404 |
| §6 cross-language search | Q501–Q516 | 16 | — | Q506 |
| §7 advanced search | Q601–Q618 | 18 | — | — |
| §8 Wikipedia | Q701–Q728 | 28 | Q701, Q702 | Q710, Q719, Q720 |
| §9 maps / OSM | Q801–Q828 | 28 | Q823 | Q812 |
| §10 laws | Q901–Q930 | 30 | Q925 | — |
| §11 cross-cutting | Q1001–Q1020 | 20 | Q1009 | Q1004, Q1005 |
| §12 standing docket | Q1101–Q1157 | 57 | Q1101, Q1102, Q1113, Q1126 | — |
| §13 process | Q1201–Q1208 | 8 | — | — |
| **Total** | | **278** | **15** | **8** |

*Recorded per THE PROTOCOL: `docs/ledger/OPEN_QUEUE.md` (the 2026-09-12 entries) and a `shipped.csv` row
point here. This file supersedes §6 of the intake document; the intake's §1–§5 and §7 remain the design
of record for the verified state and the proposed train.*
